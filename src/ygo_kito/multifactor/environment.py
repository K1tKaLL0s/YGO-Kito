"""Independent environment value branches; never attach hooks to the base."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass
import math
import os
from pathlib import Path
import tempfile

import torch
from torch import nn

from .adapters import AdapterConfig, LowRankDelta
from .calibration import model_identity
from .contracts import CapabilityStatus, FactorContractError, digest, unit
from .network import encode_batch
from .task_queries import LEARNED_TASKS, observation_view

FEATURES=("interaction_demand","resource_horizon","tempo_pressure","opponent_diversity")
VERSION="axis-environment-adapter-v3-1"


@dataclass(frozen=True)
class EnvironmentConfig:
    mode: str = "lora_head"
    rank: int = 4
    alpha: float = 4.
    seed: int = 211
    learning_rate: float = .001
    weight_decay: float = .0001

    def __post_init__(self):
        AdapterConfig(self.rank,self.alpha,self.seed)
        if self.mode not in ("head_only","lora_head","full_copy"):
            raise FactorContractError("explicit environment comparison mode required")
        if (type(self.learning_rate) not in (int,float) or not 0<self.learning_rate<=.01 or
                type(self.weight_decay) not in (int,float) or not 0<=self.weight_decay<=1):
            raise FactorContractError("invalid environment optimizer configuration")


class _AdaptedLinear(nn.Module):
    def __init__(self,base,config):
        super().__init__()
        self.base=base
        self.delta=LowRankDelta(base.in_features,base.out_features,AdapterConfig(config.rank,config.alpha,config.seed))

    def forward(self,x):
        return self.base(x)+self.delta(x)


class EnvironmentAdapter:
    def __init__(self,trainer,config=EnvironmentConfig(),*,engineering_mode=False,base_capabilities=None):
        if trainer.model.config.feature_schema!="axis-graph-v3" or type(engineering_mode) is not bool:
            raise FactorContractError("explicit v3 base and engineering flag required")
        self.base,self.base_id,self.config=trainer,model_identity(trainer),config
        self.engineering_mode=engineering_mode
        capabilities={} if base_capabilities is None else dict(base_capabilities)
        if not engineering_mode and (not capabilities or any(task not in LEARNED_TASKS or
                not isinstance(cap,CapabilityStatus) or cap.status!="available" or trainer.head_status(task)!="trained_uncalibrated"
                for task,cap in capabilities.items())):
            raise FactorContractError("real environment adaptation needs explicitly validated calibrated base capabilities")
        self.base_capabilities={k:asdict(v) for k,v in capabilities.items()}
        self.encoder=deepcopy(trainer.model)
        for parameter in self.encoder.parameters():
            parameter.requires_grad_(config.mode=="full_copy")
        devices=list(range(torch.cuda.device_count())) if torch.cuda.is_initialized() else []
        with torch.random.fork_rng(devices=devices):
            torch.manual_seed(config.seed)
            if config.mode=="lora_head":
                graph=self.encoder.graph_network
                # Only the independent environment encoder receives low-rank deltas.
                for name,module in list(graph.named_modules()):
                    if isinstance(module,nn.Linear) and name.startswith(("node_encoder.","context_encoder.","intent_encoder.","relation_encoder.","messages.","updates.","route_projection")):
                        parent=graph
                        parts=name.split(".")
                        for part in parts[:-1]:
                            parent=getattr(parent,part)
                        setattr(parent,parts[-1],_AdaptedLinear(module,config))
            width=trainer.model.config.hidden_dim
            self.head=nn.Sequential(nn.Linear(width+len(FEATURES),width),nn.SiLU(),nn.Linear(width,1))
        self.encoder.to(trainer.device)
        self.head.to(trainer.device)
        self.parameters=[p for module in (self.encoder,self.head) for p in module.parameters() if p.requires_grad]
        self.optimizer=torch.optim.AdamW(self.parameters,lr=config.learning_rate,weight_decay=config.weight_decay)
        self.steps=0
        self.source_counts=Counter()
        self.training_groups=set()
        self.data_cursor=""
        self.experiment_binding=None

    def check_base(self):
        if model_identity(self.base)!=self.base_id:
            raise FactorContractError("environment adapter belongs to a different frozen base")

    @staticmethod
    def features(context):
        if not isinstance(context,dict) or set(context)!={"environment_id","period","driver_version","features"}:
            raise FactorContractError("explicit public environment context required")
        if any(not isinstance(context[k],str) or not context[k] for k in ("environment_id","period","driver_version")):
            raise FactorContractError("environment/period/driver identity missing")
        if set(context["features"])!=set(FEATURES):
            raise FactorContractError("fixed public environment features required; opaque IDs are not features")
        for value in context["features"].values():
            unit(value,"environment feature")
        return [context["features"][k] for k in FEATURES]

    def _forward(self,builds,contexts):
        self.check_base()
        vectors=[self.features(c) for c in contexts]
        if len(builds)!=len(vectors) or not 1<=len(builds)<=64:
            raise FactorContractError("one environment per bounded graph batch required")
        batch=encode_batch(builds,device=self.base.device,config=self.base.model.config)
        self.encoder.eval()  # Base dropout is irrelevant to environment comparisons.
        output=self.encoder(batch)
        pooled=output["global_node"]+output["intent"]
        return self.head(torch.cat((pooled,pooled.new_tensor(vectors)),-1)).squeeze(-1).sigmoid()

    def predict(self,builds,contexts):
        with torch.inference_mode():
            return self._forward(builds,contexts).cpu().tolist()

    def train(self,builds,contexts,values,sources,*,data_cursor=""):
        self.validate_feedback(builds,contexts,values,sources,engineering_mode=self.engineering_mode)
        self.check_base()
        groups=Counter(s["group"] for s in sources)
        kinds={s["kind"] for s in sources}
        if not any(s["confidence"] for s in sources):
            self.data_cursor=data_cursor
            self.training_groups.update(groups)
            return dict(skipped=True,steps=self.steps)
        output=self._forward(builds,contexts)
        weights=output.new_tensor([s["confidence"]/groups[s["group"]]/len(groups) for s in sources])
        loss=((output-output.new_tensor(values)).square()*weights).sum()
        if not torch.isfinite(loss):
            raise FactorContractError("nonfinite environment loss")
        self.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        norm=nn.utils.clip_grad_norm_(self.parameters,1.,error_if_nonfinite=True)
        self.optimizer.step()
        self.steps+=1
        self.source_counts.update(kinds)
        self.training_groups.update(groups)
        self.data_cursor=data_cursor
        self.check_base()
        return dict(skipped=False,steps=self.steps,loss=float(loss.detach()),gradient_norm=float(norm),
                    base_changed=False,capability_accepted=False)

    @staticmethod
    def validate_feedback(builds,contexts,values,sources,*,engineering_mode):
        if not (1<=len(builds)<=64 and len(builds)==len(contexts)==len(values)==len(sources)):
            raise FactorContractError("environment supervision lengths differ")
        for observed,context,value,source in zip(builds,contexts,values,sources):
            observation_view(observed)
            EnvironmentAdapter.features(context)
            if isinstance(observed,dict) and observed.get("comparison") is not None:
                raise FactorContractError("environment values refer to one actual configuration")
            if isinstance(observed,dict) and "supervision" in observed and (
                    observed["supervision"].get("partition")!="train" or
                    observed.get("provenance",{}).get("leakage_group")!=source.get("group")):
                raise FactorContractError("environment graph record belongs to a held-out/different source")
            unit(value,"environment value target")
            if (source.get("partition")!="train" or source.get("kind") not in ("engineering_fixture","environment_feedback") or
                    not isinstance(source.get("group"),str) or not source["group"] or
                    not isinstance(source.get("evidence_ref"),str) or not source["evidence_ref"]):
                raise FactorContractError("environment requires independent train feedback with provenance")
            if (source["kind"]=="engineering_fixture")!=engineering_mode:
                raise FactorContractError("engineering and real environment feedback cannot mix")
            unit(source.get("confidence"),"feedback confidence")

    def identity(self):
        import hashlib
        h=hashlib.sha256()
        for module in (self.encoder,self.head):
            for name,value in sorted(module.state_dict().items()):
                h.update(name.encode()); h.update(value.detach().cpu().contiguous().numpy().tobytes())
        return digest((self.base_id,asdict(self.config),h.hexdigest()))

    def status(self):
        return dict(enabled=False,stage="environment",mode=self.config.mode,steps=self.steps,
                    status="engineering_only" if self.engineering_mode else "trained_uncalibrated" if self.steps else "untrained",
                    base_id=self.base_id,capability_accepted=False)

    def save(self,path):
        self.check_base()
        from .graph_training import execution_environment
        path=Path(path)
        if path.exists():
            raise FactorContractError("environment adapter file already exists")
        value=dict(version=VERSION,base_id=self.base_id,config=asdict(self.config),engineering_mode=self.engineering_mode,
            encoder=self.encoder.state_dict(),head=self.head.state_dict(),optimizer=self.optimizer.state_dict(),steps=self.steps,
            source_counts=dict(self.source_counts),training_groups=sorted(self.training_groups),data_cursor=self.data_cursor,
            experiment_binding=self.experiment_binding,
            base_capabilities=self.base_capabilities,
            implementation=digest(Path(__file__).read_text("utf-8")),device=str(self.base.device),runtime=execution_environment())
        with tempfile.NamedTemporaryFile(dir=path.parent,suffix=".tmp",delete=False) as stream:
            temporary=Path(stream.name)
        try:
            torch.save(value,temporary)
            if os.name=="nt": os.rename(temporary,path)
            else: os.link(temporary,path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls,trainer,path):
        from .graph_training import execution_environment
        value=torch.load(Path(path),map_location="cpu",weights_only=True)
        if (value.get("version")!=VERSION or value.get("base_id")!=model_identity(trainer) or
                value.get("implementation")!=digest(Path(__file__).read_text("utf-8")) or value.get("device")!=str(trainer.device) or value.get("runtime")!=execution_environment()):
            raise FactorContractError("environment checkpoint base/source/device mismatch")
        capabilities={k:CapabilityStatus(**dict(v,evidence_refs=tuple(v["evidence_refs"]))) for k,v in value["base_capabilities"].items()}
        obj=cls(trainer,EnvironmentConfig(**value["config"]),engineering_mode=value["engineering_mode"],base_capabilities=capabilities)
        if type(value["steps"]) is not int or value["steps"]<0:
            raise FactorContractError("invalid environment update count")
        for module,key in ((obj.encoder,"encoder"),(obj.head,"head")):
            wanted=module.state_dict(); supplied=value[key]
            if set(wanted)!=set(supplied) or any(wanted[k].shape!=v.shape or wanted[k].dtype!=v.dtype or not torch.isfinite(v).all() for k,v in supplied.items()):
                raise FactorContractError("invalid environment tensors")
            if key=="encoder" and any(not p.requires_grad and not torch.equal(p.detach().cpu(),supplied[n]) for n,p in module.named_parameters()):
                raise FactorContractError("frozen environment encoder differs from its bound base")
            module.load_state_dict(supplied,strict=True)
        expected=obj.optimizer.state_dict()
        optimizer=value["optimizer"]
        if optimizer["param_groups"]!=expected["param_groups"]:
            raise FactorContractError("environment optimizer settings differ")
        ids=expected["param_groups"][0]["params"]; params=dict(zip(ids,obj.parameters))
        if set(optimizer["state"])-set(params) or bool(optimizer["state"])!=bool(value["steps"]):
            raise FactorContractError("invalid environment optimizer state")
        for key,state in optimizer["state"].items():
            step=state.get("step")
            if set(state)!={"step","exp_avg","exp_avg_sq"} or not isinstance(step,torch.Tensor) or step.ndim!=0 or not torch.isfinite(step) or not 0<float(step)<=value["steps"] or float(step)!=int(float(step)):
                raise FactorContractError("invalid environment Adam step")
            for name in ("exp_avg","exp_avg_sq"):
                moment=state[name]
                if moment.shape!=params[key].shape or moment.dtype!=params[key].dtype or not torch.isfinite(moment).all() or name=="exp_avg_sq" and (moment<0).any():
                    raise FactorContractError("invalid environment optimizer moments")
        obj.optimizer.load_state_dict(optimizer)
        expected_kind="engineering_fixture" if obj.engineering_mode else "environment_feedback"
        if set(value["source_counts"])-{expected_kind} or any(type(n) is not int or n!=value["steps"] for n in value["source_counts"].values()) or bool(value["source_counts"])!=bool(value["steps"]):
            raise FactorContractError("invalid environment supervision counters")
        obj.steps=value["steps"]; obj.source_counts=Counter(value["source_counts"])
        obj.training_groups=set(value["training_groups"]); obj.data_cursor=value["data_cursor"]
        obj.experiment_binding=value["experiment_binding"]
        return obj


class EnvironmentProvider:
    """Explicit calibrated environment estimator injected by the host."""
    def __init__(self,adapter,context_provider,artifact):
        self.adapter,self.context_provider,self.artifact=adapter,context_provider,deepcopy(artifact)
        if (not callable(context_provider) or artifact.get("version")!="axis-environment-calibration-v3" or
                artifact.get("engineering_only") is not False or artifact.get("adapter_id")!=adapter.identity() or
                artifact.get("base_id")!=adapter.base_id or artifact.get("validated") is not True or
                artifact.get("calibrated") is not True or not artifact.get("evidence_ref") or
                adapter.engineering_mode or not adapter.steps or
                not artifact.get("evaluation_groups") or not artifact.get("calibration_groups") or
                set(artifact["evaluation_groups"])&set(artifact["calibration_groups"]) or
                (set(artifact["evaluation_groups"])|set(artifact["calibration_groups"]))&adapter.training_groups):
            raise FactorContractError("environment capability needs matching independent real validation/calibration")
        for name in ("slope","intercept"):
            if type(artifact.get(name)) not in (int,float) or not math.isfinite(artifact[name]):
                raise FactorContractError("finite environment calibration coefficients required")
        if set(artifact.get("training_groups",()))!=adapter.training_groups:
            raise FactorContractError("environment calibration training sources differ from the actual adapter")
        for name in ("raw_mse","calibrated_mse","baseline_mse","max_mse","maximum_regression"):
            unit(artifact.get(name),"environment validation "+name)
        if (max(artifact["raw_mse"],artifact["calibrated_mse"])>artifact["max_mse"] or
                artifact["calibrated_mse"]>artifact["baseline_mse"]+artifact["maximum_regression"]):
            raise FactorContractError("environment validation metrics did not pass their declared gates")
        self.capability=CapabilityStatus("available","axis-environment-v3",adapter.identity(),
            (artifact["evidence_ref"],),True,True)

    def evaluate(self,build,context):
        if self.adapter.identity()!=self.artifact["adapter_id"]:
            raise FactorContractError("environment adapter changed after calibration")
        environment=self.context_provider(context)
        raw=self.adapter.predict([build],[environment])[0]
        calibrated=max(0.,min(1.,raw*self.artifact["slope"]+self.artifact["intercept"]))
        return dict(raw=raw,calibrated=calibrated,value=calibrated,environment_id=environment["environment_id"],
                    producer=self.capability.producer,version=self.capability.version)


def _feedback_rows(rows,partition,excluded):
    if not rows:
        raise FactorContractError("nonempty environment feedback required")
    groups=Counter(); kinds=set(); ids=set()
    for row in rows:
        if (row.get("partition")!=partition or not row.get("group") or row["group"] in excluded or
                not row.get("record_id") or row["record_id"] in ids or not row.get("evidence_ref") or
                row.get("kind") not in ("environment_feedback","engineering_fixture")):
            raise FactorContractError("environment feedback provenance/partition overlap")
        for key in ("prediction","value"):
            unit(row[key],"environment "+key)
        if partition=="test" and (row.get("final_eval_eligible") is not True or row.get("previously_consumed") is not False):
            raise FactorContractError("environment final evidence was previously consumed or is ineligible")
        ids.add(row["record_id"]); groups[row["group"]]+=1; kinds.add(row["kind"])
    return groups,kinds


def fit_environment_calibration(rows,*,adapter_id,base_id,training_groups):
    if not isinstance(adapter_id,str) or not adapter_id or not isinstance(base_id,str) or not base_id:
        raise FactorContractError("environment calibration needs actual adapter/base identities")
    groups,kinds=_feedback_rows(rows,"validation",set(training_groups))
    for row in rows:
        if row["kind"]=="environment_feedback":
            if row.get("adapter_id")!=adapter_id or row.get("base_id")!=base_id:
                raise FactorContractError("environment calibration predictions belong to a different adapter/base")
            EnvironmentAdapter.features(row["environment"])
    weights=[1/groups[r["group"]]/len(groups) for r in rows]
    x=sum(w*r["prediction"] for w,r in zip(weights,rows))
    y=sum(w*r["value"] for w,r in zip(weights,rows))
    variance=sum(w*(r["prediction"]-x)**2 for w,r in zip(weights,rows))
    slope=(sum(w*(r["prediction"]-x)*(r["value"]-y) for w,r in zip(weights,rows))/variance if variance>1e-12 else 0.)
    return dict(version="axis-environment-calibration-v3",adapter_id=adapter_id,base_id=base_id,
                training_groups=sorted(set(training_groups)),calibration_groups=sorted(groups),slope=slope,intercept=y-slope*x,
                engineering_only="engineering_fixture" in kinds,calibrated=True,validated=False)


def assess_environment(rows,calibration,*,baseline_predictions,max_mse=.10,maximum_regression=.03,evidence_ref):
    if (type(max_mse) not in (int,float) or type(maximum_regression) not in (int,float) or
            not 0<=max_mse<=1 or not 0<=maximum_regression<=1 or not evidence_ref):
        raise FactorContractError("explicit environment assessment gates/evidence required")
    if (calibration.get("version")!="axis-environment-calibration-v3" or calibration.get("calibrated") is not True or
            type(calibration.get("engineering_only")) is not bool or not calibration.get("adapter_id") or not calibration.get("base_id") or
            not calibration.get("calibration_groups") or
            set(calibration["calibration_groups"])&set(calibration["training_groups"])):
        raise FactorContractError("invalid environment calibration binding")
    for name in ("slope","intercept"):
        if type(calibration.get(name)) not in (int,float) or not math.isfinite(calibration[name]):
            raise FactorContractError("nonfinite environment calibration")
    excluded=set(calibration["training_groups"])|set(calibration["calibration_groups"])
    groups,kinds=_feedback_rows(rows,"test",excluded)
    if set(baseline_predictions)!={r["record_id"] for r in rows}:
        raise FactorContractError("environment comparison must use exactly the same held-out records")
    raw=calibrated=baseline=0.
    for row in rows:
        if row["kind"]=="environment_feedback":
            if row.get("adapter_id")!=calibration["adapter_id"] or row.get("base_id")!=calibration["base_id"]:
                raise FactorContractError("environment evaluation predictions belong to a different adapter/base")
            EnvironmentAdapter.features(row["environment"])
        old=baseline_predictions[row["record_id"]]; unit(old,"environment baseline")
        weight=1/groups[row["group"]]/len(groups)
        value=max(0.,min(1.,row["prediction"]*calibration["slope"]+calibration["intercept"]))
        raw+=weight*(row["prediction"]-row["value"])**2
        calibrated+=weight*(value-row["value"])**2
        baseline+=weight*(old-row["value"])**2
    engineering=calibration["engineering_only"] or "engineering_fixture" in kinds
    eligible=not engineering and max(raw,calibrated)<=max_mse and calibrated<=baseline+maximum_regression
    return dict(calibration,evaluation_groups=sorted(groups),raw_mse=raw,calibrated_mse=calibrated,
                baseline_mse=baseline,max_mse=max_mse,maximum_regression=maximum_regression,
                engineering_only=engineering,validated=eligible,evidence_ref=evidence_ref,active_pointer_changed=False)
