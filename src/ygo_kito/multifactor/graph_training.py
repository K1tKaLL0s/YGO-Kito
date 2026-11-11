"""v3 masked learning and strict experiment recovery; never runs on import."""
from collections import defaultdict
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import random
import sys
import tempfile

import torch
from torch.nn import functional as F

from .contracts import (ROLES, TASK_DOMAINS, FactorContractError, digest, fields, sha256_text, unit)
from .task_queries import (CATEGORY_COORDINATES, CONTEXTUAL_TASKS, LEARNED_TASKS, ROLE_SOURCES, SOURCE_KINDS,
    encoder_fingerprint, feature_fingerprint, missing_axis_query, observation_view, query_domain, query_key, training_domain, validate_query,
    comparison_for_record, record_graph_size, validate_comparison, record_sources)

CHECKPOINT_VERSION = "axis-checkpoint-v3-m5"
SAMPLER_VERSION = "axis-source-shards-v3-m5"
GROUPS = {
    "membership":(1.0,("axis_membership",)),
    "function":(1.0,("axis_function","function_role","contribution")),
    "transferability":(1.0,("transferability",)),
    "compatibility":(.75,("receiver_compatibility","legacy:compatibility")),
    "relation":(.5,("pair_relation","legacy:pairs")),
    "axis_description":(.4,("axis_position","axis_origin")),
    "mechanism":(.2,("mechanism",)), "preference":(.2,("copy_preference",)),
    "legacy_summary":(1.0,tuple("legacy:"+r for r in ROLES)), "consistency":(.1,("consistency",)),
}


def implementation_fingerprint():
    root = Path(__file__).parent
    return digest({name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
        ("network.py","training.py","graph_network.py","graph_training.py","task_queries.py","contracts.py",
         "semantics.py","axis_candidates.py","conditions.py","functional_units.py")})


def initialize(trainer,binding,task_weights):
    trainer.bound_experiment = binding is not None
    if binding is None:
        binding = {k:digest("unbound engineering experiment") for k in ("dataset","split","calibration","recipe")}
    fields(binding,("dataset","split","calibration","recipe"))
    for name,value in binding.items():
        sha256_text(value,name+" binding")
    trainer.binding = dict(binding,architecture=digest(trainer.model.config_dict()),features=feature_fingerprint(),
                           label_protocol=trainer.label_protocol_sha256)
    trainer.task_weights = {name:value[0] for name,value in GROUPS.items()}
    if task_weights is not None:
        if not isinstance(task_weights,dict) or set(task_weights)-set(GROUPS):
            raise FactorContractError("unknown task loss group")
        for name,value in task_weights.items():
            if type(value) not in (int,float) or not 0<=value<=10:
                raise FactorContractError("finite task-group weight 0..10 required")
            trainer.task_weights[name] = float(value)
    trainer.updates = {task:{kind:0 for kind in SOURCE_KINDS} for task in LEARNED_TASKS}
    trainer.sampler_state = dict(version=SAMPLER_VERSION,epoch=0,next_batch=0,finished=False)
    trainer.run_state = dict(best_score=None,best_file=None)
    trainer.warm_start_report = None


def capability(trainer,head):
    if head=="state_readiness":
        return "deterministic_only"
    if head=="environment_value":
        return "disabled"
    if head not in trainer.updates:
        raise FactorContractError("unknown v3 task")
    counts = trainer.updates[head]
    if any(counts[k] for k in ("human_feedback","engine_probe","self_generated_candidate")):
        return "trained_uncalibrated"
    if counts["weak_context_annotation"]:
        return "weakly_supervised_uncalibrated"
    if counts["engineering_fixture"] or counts["definition_development"]:
        return "engineering_only"
    return "untrained"


def cells(targets):
    from .training import Targets
    yield from Targets.from_dict(targets).graph_cells()


def compile_records(trainer,records):
    if not isinstance(records,(tuple,list)) or not 1<=len(records)<=64:
        raise FactorContractError("1..64 prepared v3 records required")
    compiled,known_count,diagnostics = [],defaultdict(int),dict(deterministic_cells=0,unrepresented_candidate_cells=0)
    for b,row in enumerate(records):
        record_sources(row,label_protocol_sha256=trainer.label_protocol_sha256)
        if row.get("schema_version")!="axis-training-record-v3":
            raise FactorContractError("v3 record schema required")
        supervision,provenance = row["supervision"],row["provenance"]
        if supervision.get("partition")!="train" or supervision.get("trainable") is not True:
            raise FactorContractError("only explicitly trainable train records may update")
        if supervision.get("label_protocol_sha256")!=trainer.label_protocol_sha256:
            raise FactorContractError("record/trainer label protocol differs")
        group = provenance.get("leakage_group")
        if not isinstance(group,str) or not group:
            raise FactorContractError("source component required")
        example,graph,candidates = observation_view(row)
        domain = training_domain(query_domain(example,graph,candidates),candidates,supervision.get('training_queries',()))
        for task,subject,coordinate,cell in cells(row["targets"]):
            if not cell.known:
                continue
            if task=="state_readiness":
                diagnostics['deterministic_cells'] += 1
                continue
            if missing_axis_query(domain,task,subject,coordinate):
                diagnostics['unrepresented_candidate_cells'] += 1
                continue
            if task=="copy_preference":
                comparison=comparison_for_record(row)
                if tuple(subject)!=(comparison["left_key"],comparison["right_key"]) or coordinate!="preference":
                    raise FactorContractError("preference supervision endpoints differ from the paired observations")
            else:
                validate_query(domain,task,subject,coordinate)
            sources = supervision.get("cell_sources",{}).get(query_key(task,subject,coordinate))
            if not isinstance(sources,list) or not sources:
                raise FactorContractError("each known cell needs its original supervision sources")
            kinds = set()
            confidence = []
            for source in sources:
                kind = source.get("kind")
                if kind not in SOURCE_KINDS or task in CONTEXTUAL_TASKS and kind not in ROLE_SOURCES:
                    raise FactorContractError("source cannot supply this task's truth")
                if not trainer.bound_experiment and kind not in ("engineering_fixture","definition_development"):
                    raise FactorContractError("real supervision needs explicit data/split/recipe binding")
                unit(source.get("confidence"),"cell source confidence")
                if not source.get("source_record_id"):
                    raise FactorContractError("cell source identity missing")
                kinds.add(kind)
                confidence.append(source["confidence"])
            source_confidence = supervision.get("confidence",1.0)
            unit(source_confidence,"supervision confidence")
            evidence = min(cell.confidence,max(confidence))*source_confidence
            base = supervision.get("source_group_weights",{}).get(task)
            if base is not None and (type(base) not in (int,float) or not 0<base<=1):
                raise FactorContractError("positive source-group cell weight required")
            known_count[group,task] += 1
            compiled.append(dict(batch=b,task=task,subject=subject,coordinate=coordinate,cell=cell,
                                 group=group,evidence=evidence,kinds=kinds,base=base))
    for value in compiled:
        if value["base"] is None:
            value["base"] = 1/known_count[value["group"],value["task"]]
    return compiled,diagnostics





def _intrinsic(example):
    value = example.to_dict()["observations"]
    for name in ("context_ref","context","deck","visible_state","insertion"):
        value.pop(name,None)
    if value.get("analysis_context"):
        value["analysis_context"].pop("public_resources",None)
    if value.get("unit"):
        value["unit"].pop("unit_id",None)
    return value


def train_supervised(trainer,records,*,consistency=(),micro_batch_size=None):
    """One source-balanced effective-batch update for every v3 caller."""
    return train_accumulated(trainer,records,micro_batch_size=len(records) if micro_batch_size is None else micro_batch_size,consistency=consistency)


def train_accumulated(trainer,records,*,micro_batch_size,consistency=()):
    if getattr(trainer,"inference_only",False):
        raise FactorContractError("inference-only model cannot update")
    if type(micro_batch_size) is not int or not 1<=micro_batch_size<=64:
        raise FactorContractError("micro batch size must be 1..64")
    from .network import encode_batch
    compiled,diagnostics=compile_records(trainer,records)
    active=[v for v in compiled if v["evidence"]>0 and any(v["task"] in names and trainer.task_weights[g]>0 for g,(_,names) in GROUPS.items())]
    if not active:
        return dict(skipped=True,reason="no_effective_supervision",steps=trainer.steps,optimizer_updates=0,**diagnostics)
    pairs=[]
    for pair in consistency:
        fields(pair,("left","right","task","subject","coordinate","scope","evidence_ref","confidence"))
        a,b=pair["left"],pair["right"]
        if type(a) is not int or type(b) is not int or not 0<=a<len(records) or not 0<=b<len(records) or a==b:
            raise FactorContractError("distinct consistency record indices required")
        if pair["task"]!="transferability" or pair["scope"]!="unit_definition" or not pair["evidence_ref"]:
            raise FactorContractError("only explicitly evidenced intrinsic portability invariance is implemented")
        views=[observation_view(records[i]) for i in (a,b)]
        if records[a]["provenance"]["leakage_group"]!=records[b]["provenance"]["leakage_group"] or _intrinsic(views[0][0])!=_intrinsic(views[1][0]):
            raise FactorContractError("invariance crosses source or intrinsic definition")
        unit(pair["confidence"],"invariance confidence")
        for example,graph,candidates in views:
            validate_query(query_domain(example,graph,candidates),pair["task"],pair["subject"],pair["coordinate"])
        pairs.append(pair)
    tasks={v["task"] for v in compiled}
    if pairs:tasks.add("consistency")
    groups={g:[t for t in names if t in tasks] for g,(_,names) in GROUPS.items() if trainer.task_weights[g]>0 and any(t in tasks for t in names)}
    denominators={t:sum(v["base"] for v in compiled if v["task"]==t) for t in tasks if t!="consistency"}
    if pairs:denominators["consistency"]=len(pairs)
    group_weight=sum(trainer.task_weights[g] for g in groups)
    scales={t:trainer.task_weights[g]/group_weight/len(names)/denominators[t] for g,names in groups.items() for t in names}
    chunks=[];part=[];nodes=edges=graphs=0
    for i,row in enumerate(records):
        n,e,count=record_graph_size(row)
        if n>trainer.model.config.graph_node_budget or e>trainer.model.config.graph_edge_budget or count>64:
            raise FactorContractError("single configuration pair exceeds tensor budget")
        if part and (len(part)==micro_batch_size or nodes+n>trainer.model.config.graph_node_budget or edges+e>trainer.model.config.graph_edge_budget or graphs+count>64):
            chunks.append(part);part=[];nodes=edges=graphs=0
        part.append(i);nodes+=n;edges+=e;graphs+=count
    if part:chunks.append(part)
    if pairs and len(chunks)!=1:
        raise FactorContractError("consistency pairs require a single effective microbatch")
    trainer.model.train();trainer.optimizer.zero_grad(set_to_none=True)
    totals,kinds=defaultdict(float),defaultdict(set)
    try:
        for indices in chunks:
            selected=[v for v in compiled if v["batch"] in indices and v["task"] in scales and v["evidence"]>0]
            if not selected:continue
            batch=encode_batch([records[i] for i in indices],device=trainer.device,config=trainer.model.config,training=True)
            output=trainer.model(batch)
            queries=[(indices.index(v["batch"]),v["task"],v["subject"],v["coordinate"]) for v in selected]
            total=None
            for start in range(0,len(queries),32):
                scores=trainer.model.score_queries(output,batch,queries[start:start+32])
                for v,score in zip(selected[start:start+32],scores):
                    task,cell=v["task"],v["cell"]
                    loss=(F.cross_entropy(score[None],torch.tensor([TASK_DOMAINS[task].index(cell.value)],device=trainer.device)) if task in CATEGORY_COORDINATES else F.binary_cross_entropy_with_logits(score,score.new_tensor(float(cell.value))))
                    weighted=loss*v["base"]*v["evidence"]
                    term=weighted*scales[task]
                    total=term if total is None else total+term
                    totals[task]+=float(weighted.detach())/denominators[task]
                    kinds[task].update(v["kinds"])
            if pairs and "consistency" in scales:
                for pair in pairs:
                    if not pair["confidence"]:continue
                    queries=[(i,pair["task"],tuple(pair["subject"]),pair["coordinate"]) for i in (pair["left"],pair["right"])]
                    a,b=trainer.model.score_queries(output,batch,queries)
                    weighted=(a.softmax(-1)-b.softmax(-1)).square().mean()*pair["confidence"]
                    total=total+weighted*scales["consistency"]
                    totals["consistency"]+=float(weighted.detach())/len(pairs)
            if total is None or not torch.isfinite(total):raise FactorContractError("non-finite accumulated loss")
            total.backward()
        norm=torch.nn.utils.clip_grad_norm_(trainer.model.parameters(),trainer.gradient_clip,error_if_nonfinite=True)
        trainer.optimizer.step()
    except Exception:
        trainer.optimizer.zero_grad(set_to_none=True)
        raise
    trainer.steps+=1
    for task,sources in kinds.items():
        for kind in sources:trainer.updates[task][kind]+=1
    trainer.data_digest=digest((trainer.data_digest,[dict(record_id=r["record_id"],input_key=r["input_key"],targets=r["targets"],supervision=r["supervision"]) for r in records],consistency))
    loss=sum(sum(totals[t] for t in names)/len(names)*trainer.task_weights[g] for g,names in groups.items())/group_weight
    return dict(skipped=False,loss=loss,component_losses=dict(totals),gradient_norm=float(norm),steps=trainer.steps,optimizer_updates=1,micro_batches=len(chunks),**diagnostics,head_status={t:capability(trainer,t) for t in LEARNED_TASKS})






def capture_rng(trainer):
    state = dict(python=random.getstate(),torch=torch.get_rng_state(),cuda=None,numpy=None,
                 deterministic=torch.are_deterministic_algorithms_enabled())
    if trainer.device.type=="cuda":
        state["cuda"] = torch.cuda.get_rng_state_all()
    if "numpy" in sys.modules:
        value = sys.modules["numpy"].random.get_state()
        state["numpy"] = (value[0],value[1].tolist(),value[2],value[3],value[4])
    return state


def execution_environment():
    return dict(torch=str(torch.__version__),cuda=torch.version.cuda,threads=torch.get_num_threads(),
        interop_threads=torch.get_num_interop_threads(),float32_precision=torch.get_float32_matmul_precision(),
        matmul_tf32=torch.backends.cuda.matmul.allow_tf32,cudnn_tf32=torch.backends.cudnn.allow_tf32,
        cudnn_deterministic=torch.backends.cudnn.deterministic,cudnn_benchmark=torch.backends.cudnn.benchmark)


def train_preference(trainer,left,right,*,left_key,right_key,preferred_left,source,comparison_operation):
    if getattr(trainer,"inference_only",False):
        raise FactorContractError("inference-only model cannot update")
    from .training import Supervision
    from .network import encode_batch
    if not isinstance(source,Supervision):
        raise FactorContractError("typed candidate supervision required")
    source.admit("candidate")
    unit(preferred_left,"preference probability")
    if source.label_protocol_sha256!=trainer.label_protocol_sha256:
        raise FactorContractError("preference requires matching label protocol and explicit same comparison operation")
    if not trainer.bound_experiment and source.kind not in ("engineering_fixture","definition_development"):
        raise FactorContractError("real preference needs an experiment binding")
    for value in (left,right):
        if isinstance(value,dict) and "supervision" in value and (value["supervision"].get("partition")!="train" or value["supervision"].get("trainable") is not True):
            raise FactorContractError("held-out records cannot be preference updates")
    a,b=validate_comparison(left,right,left_key=left_key,right_key=right_key,operation=comparison_operation)
    if source.confidence==0 or trainer.task_weights["preference"]==0:
        return dict(skipped=True,reason="no_effective_supervision",steps=trainer.steps,optimizer_updates=0)
    batch = encode_batch((left,right),device=trainer.device,config=trainer.model.config)
    trainer.model.train()
    output = trainer.model(batch)
    logits = trainer.model.graph_network.score_preference(output,batch,left_key,right_key)
    target = logits.new_tensor([0.,1.,0.] if preferred_left==.5 else [preferred_left,0.,1-preferred_left])
    loss = -(target*logits.log_softmax(-1)).sum()*source.confidence
    if not torch.isfinite(loss):
        raise FactorContractError("nonfinite preference loss")
    trainer.optimizer.zero_grad(set_to_none=True)
    loss.backward()
    norm = torch.nn.utils.clip_grad_norm_(trainer.model.parameters(),trainer.gradient_clip,error_if_nonfinite=True)
    trainer.optimizer.step()
    trainer.steps += 1
    trainer.updates["copy_preference"][source.kind] += 1
    trainer.data_digest = digest((trainer.data_digest,a.to_dict(),b.to_dict(),left_key,right_key,
                                  preferred_left,asdict(source),comparison_operation))
    return dict(skipped=False,loss=float(loss.detach()),gradient_norm=float(norm),steps=trainer.steps,optimizer_updates=1)


def restore_rng(state,device):
    fields(state,("python","torch","cuda","numpy","deterministic"))
    random.Random().setstate(state["python"])
    torch.Generator().set_state(state["torch"])
    if device.type=="cuda" and (state["cuda"] is None or len(state["cuda"])!=torch.cuda.device_count()):
        raise FactorContractError("CUDA RNG topology differs on resume")
    numpy_state = None
    if state["numpy"] is not None:
        import numpy as np
        value = state["numpy"]
        numpy_state = (value[0],np.array(value[1],dtype='uint32'),value[2],value[3],value[4])
        np.random.RandomState().set_state(numpy_state)
    if type(state["deterministic"]) is not bool:
        raise FactorContractError("invalid RNG determinism metadata")
    random.setstate(state["python"])
    torch.set_rng_state(state["torch"])
    if device.type=="cuda":
        torch.cuda.set_rng_state_all(state["cuda"])
    if numpy_state is not None:
        np.random.set_state(numpy_state)
    torch.use_deterministic_algorithms(state["deterministic"])


def save(trainer,path,*,data_cursor=None):
    path = Path(path)
    if trainer.lora is not None or path.exists() or getattr(trainer,"inference_only",False):
        raise FactorContractError("v3 base requires a new independent checkpoint file")
    payload = dict(version=CHECKPOINT_VERSION,config=trainer.model.config_dict(),binding=trainer.binding,
        bound_experiment=trainer.bound_experiment,features=feature_fingerprint(),encoder=encoder_fingerprint(),
        implementation=implementation_fingerprint(),learning_rate=trainer.learning_rate,task_weights=trainer.task_weights,
        optimizer_config=trainer.optimizer_config,gradient_clip=trainer.gradient_clip,
        model=trainer.model.state_dict(),optimizer=trainer.optimizer.state_dict(),updates=trainer.updates,steps=trainer.steps,
        data_digest=trainer.data_digest,data_cursor=trainer.data_cursor if data_cursor is None else data_cursor,
        sampler=trainer.sampler_state,rng=capture_rng(trainer),device_type=trainer.device.type,
        runtime=execution_environment(),
        run_state=trainer.run_state,scheduler=None,
        calibrated=False,capability_accepted=False,warm_start=trainer.warm_start_report)
    with tempfile.NamedTemporaryFile(prefix=path.name+'.',suffix='.tmp',dir=path.parent,delete=False) as stream:
        temporary = Path(stream.name)
    try:
        torch.save(payload,temporary)
        if os.name=='nt':
            os.rename(temporary,path)  # Windows rename refuses an existing destination.
        else:
            os.link(temporary,path)  # Atomic, no-replace; no historical weight overwrite.
        trainer.data_cursor = payload["data_cursor"]
    finally:
        temporary.unlink(missing_ok=True)


def _validate_adam(trainer,value,steps):
    fields(value,("state","param_groups"))
    expected = trainer.optimizer.state_dict()["param_groups"]
    if len(value["param_groups"])!=len(expected):
        raise FactorContractError("Adam parameter group count differs")
    ids = []
    for actual,wanted in zip(value["param_groups"],expected):
        if actual!=wanted:
            raise FactorContractError("Adam parameter groups/settings differ")
        ids.extend(actual["params"])
    params = dict(zip(ids,trainer.model.parameters()))
    if any(k not in params for k in value["state"]) or bool(value["state"])!=bool(steps):
        raise FactorContractError("Adam state missing or contains foreign parameters")
    for key,state in value["state"].items():
        fields(state,("step","exp_avg","exp_avg_sq"))
        step = state["step"]
        if not isinstance(step,torch.Tensor) or step.ndim!=0 or not torch.isfinite(step) or not 0<float(step)<=steps or float(step)!=int(float(step)):
            raise FactorContractError("invalid Adam step")
        for name in ("exp_avg","exp_avg_sq"):
            tensor = state[name]
            if not isinstance(tensor,torch.Tensor) or tensor.shape!=params[key].shape or tensor.dtype!=params[key].dtype or not torch.isfinite(tensor).all() or name=="exp_avg_sq" and bool((tensor<0).any()):
                raise FactorContractError("invalid Adam moments")


def load(trainer_type,payload,*,config,binding,label_protocol_sha256,device,mode,learning_rate=None,task_weights=None,optimizer_config=None,gradient_clip=None):
    from .network import NetworkConfig
    if payload.get("version")!=CHECKPOINT_VERSION or config is None or binding is None:
        raise FactorContractError("v3 load needs explicit config, binding and v3 checkpoint")
    fields(payload,("version","config","binding","bound_experiment","features","encoder","implementation","learning_rate",
        "task_weights","model","optimizer","updates","steps","data_digest","data_cursor","sampler","rng","device_type",
        "run_state","scheduler","runtime","calibrated","capability_accepted","warm_start","optimizer_config","gradient_clip"))
    if not isinstance(config,NetworkConfig) or config.feature_schema!="axis-graph-v3":
        raise FactorContractError("explicit v3 architecture required")
    trainer = trainer_type(config,learning_rate=payload["learning_rate"] if learning_rate is None else learning_rate,label_protocol_sha256=label_protocol_sha256,
                           device=device,binding=binding,task_weights=(payload["task_weights"] if mode in ("resume","inference") else None) if task_weights is None else task_weights,
                           optimizer_config=payload['optimizer_config'] if optimizer_config is None else optimizer_config,
                           gradient_clip=payload['gradient_clip'] if gradient_clip is None else gradient_clip)
    if mode=="warm_start":
        keys = ("hidden_dim","message_rounds","feature_schema","stream_mode","use_route_features")
        if payload.get("encoder")!=encoder_fingerprint() or any(payload["config"][k]!=asdict(config)[k] for k in keys):
            raise FactorContractError("no semantically compatible shared graph encoder")
        prefixes = tuple("graph_network."+n for n in ("node_encoder.","context_encoder.","intent_encoder.","relation_encoder.","messages.","updates.","route_projection."))
        state = trainer.model.state_dict()
        copied = [name for name in state if name.startswith(prefixes)]
        if not copied or any(name not in payload["model"] or state[name].shape!=payload["model"][name].shape or state[name].dtype!=payload["model"][name].dtype or not torch.isfinite(payload["model"][name]).all() for name in copied):
            raise FactorContractError("shared encoder tensor contract differs")
        for name in copied:
            state[name] = payload["model"][name]
        trainer.model.load_state_dict(state,strict=True)
        trainer.warm_start_report = dict(source_binding=payload["binding"],copied=copied,optimizer_reset=True,
                                        new_heads_reset=True,capability_accepted=False)
        return trainer
    if mode not in ("resume","inference") or payload["binding"]!=trainer.binding or payload["config"]!=trainer.model.config_dict() or payload["features"]!=feature_fingerprint() or payload["implementation"]!=implementation_fingerprint() or payload["learning_rate"]!=trainer.learning_rate or payload["task_weights"]!=trainer.task_weights:
        raise FactorContractError("resume architecture/features/protocol/data/split/recipe differs")
    if payload['optimizer_config']!=trainer.optimizer_config or payload['gradient_clip']!=trainer.gradient_clip:
        raise FactorContractError('resume optimizer/gradient configuration differs')
    if payload.get("calibrated") is not False or payload.get("capability_accepted") is not False or mode=="resume" and payload.get("device_type")!=trainer.device.type:
        raise FactorContractError("resume capability or device metadata differs")
    if mode=="resume" and payload['runtime']!=execution_environment():
        raise FactorContractError('resume Torch/backend/thread environment differs; use an explicit new warm start')
    if payload["scheduler"] is not None or type(payload["bound_experiment"]) is not bool:
        raise FactorContractError("resume requires the declared constant-learning-rate protocol")
    if not {'best_score','best_file'}<=set(payload['run_state']) or set(payload['run_state'])-{'best_score','best_file','bad_epochs','stop_reason'}:
        raise FactorContractError('invalid run state fields')
    if type(payload['run_state'].get('bad_epochs',0)) is not int or payload['run_state'].get('bad_epochs',0)<0 or payload['run_state'].get('stop_reason') not in (None,'early_stopping','epochs_complete'):
        raise FactorContractError('invalid early stopping state')
    if payload["run_state"]["best_score"] is not None:
        unit(payload["run_state"]["best_score"],"development selection score")
    if payload["run_state"]["best_file"] is not None and not isinstance(payload["run_state"]["best_file"],str):
        raise FactorContractError("invalid selected checkpoint reference")
    steps = payload["steps"]
    if type(steps) is not int or steps<0:
        raise FactorContractError("invalid update count")
    fields(payload["updates"],LEARNED_TASKS)
    for counts in payload["updates"].values():
        fields(counts,SOURCE_KINDS)
        if any(type(v) is not int or not 0<=v<=steps for v in counts.values()):
            raise FactorContractError("invalid per-head update count")
    sha256_text(payload["data_digest"],"data digest")
    sampler = payload["sampler"]
    fields(sampler,("version","epoch","next_batch","finished"))
    if sampler["version"]!=SAMPLER_VERSION or any(type(sampler[k]) is not int or sampler[k]<0 for k in ("epoch","next_batch")) or type(sampler["finished"]) is not bool:
        raise FactorContractError("invalid sampler cursor")
    state = trainer.model.state_dict()
    if set(state)!=set(payload["model"]) or any(state[k].shape!=v.shape or state[k].dtype!=v.dtype or not torch.isfinite(v).all() for k,v in payload["model"].items()):
        raise FactorContractError("checkpoint model tensor contract differs")
    if mode=="resume":
        _validate_adam(trainer,payload["optimizer"],steps)
    trainer.model.load_state_dict(payload["model"],strict=True)
    if mode=="resume":
        trainer.optimizer.load_state_dict(payload["optimizer"])
    trainer.updates,trainer.steps = payload["updates"],steps
    trainer.data_digest,trainer.data_cursor,trainer.sampler_state = payload["data_digest"],payload["data_cursor"],sampler
    trainer.warm_start_report = payload["warm_start"]
    trainer.run_state = payload["run_state"]
    trainer.bound_experiment = payload["bound_experiment"]
    if mode=="resume":
        restore_rng(payload["rng"],trainer.device)
    else:
        trainer.inference_only=True
        trainer.model.eval()
        trainer.model.requires_grad_(False)
    return trainer
