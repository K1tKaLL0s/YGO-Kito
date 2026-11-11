"""Masked supervision, candidate preference updates and independent checkpoints."""

from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import tempfile

import torch
from torch.nn import functional as F

from .contracts import (DEFAULT_LABEL_PROTOCOL_SHA256, ROLES, FactorContractError, LabelCell, LabelSet, RoleInput,
                        digest, fields, schema_fingerprint, sha256_text, text, unit)
from .network import NetworkConfig, RoleNetwork, encode_batch

SOURCE_KINDS = ("engineering_fixture", "definition_development", "engine_probe", "self_generated_candidate", "human_feedback", "weak_context_annotation")
ENGINEERING_SOURCES = ("engineering_fixture", "definition_development")
HEADS = ("role", "compatibility", "pair", "utility")
OUTPUT_TASKS = HEADS + tuple("role:" + role for role in ROLES)
CHECKPOINT_VERSION = "multifactor-checkpoint-v7"


@dataclass(frozen=True)
class Supervision:
    kind: str
    evidence_ref: str
    partition: str = "train"
    scope: str = "group"
    label_protocol_sha256: str = DEFAULT_LABEL_PROTOCOL_SHA256
    confidence: float = 1.0
    role_confidence: tuple[float, ...] = (1.0,) * 5
    role_balance: tuple[float, ...] = (1.0,) * 5

    def __post_init__(self):
        unit(self.confidence, "supervision confidence")
        for name in ("role_confidence", "role_balance"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or len(values) != len(ROLES):
                raise FactorContractError("immutable per-role confidence and loss-balance vectors required")
            for value in values:
                unit(value, name)
        if self.kind not in SOURCE_KINDS:
            raise FactorContractError("external/reference/opponent deck sources are not learner supervision")
        if self.partition not in ("train", "validation", "final_eval") or self.scope not in ("group", "candidate"):
            raise FactorContractError("explicit supervision partition and scope required")
        text(self.evidence_ref, "supervision evidence")
        sha256_text(self.label_protocol_sha256, "label protocol")

    def admit(self, scope):
        if self.partition != "train" or self.scope != scope:
            raise FactorContractError("only train evidence with matching attribution scope may update weights")


@dataclass(frozen=True)
class Targets:
    roles: tuple = ()
    compatibility: tuple = ()
    pairs: tuple = ()
    task_labels: tuple[LabelSet, ...] = ()

    def __post_init__(self):
        for name in ("roles", "compatibility", "pairs", "task_labels"):
            if not isinstance(getattr(self, name), tuple):
                raise FactorContractError("immutable target tuples required")
        if any(not isinstance(v, tuple) or len(v) != 2 or not isinstance(v[1], tuple) for v in self.roles):
            raise FactorContractError("role targets require group/vector tuples")
        if any(not isinstance(v, tuple) or len(v) != 2 for v in self.compatibility) or any(
                not isinstance(v, tuple) or len(v) != 3 for v in self.pairs):
            raise FactorContractError("compatibility/pair target tuples required")
        object.__setattr__(self, "roles", tuple((k, tuple(LabelCell.from_legacy(c).validate_domain() for c in cs)) for k, cs in self.roles))
        object.__setattr__(self, "compatibility", tuple((k, LabelCell.from_legacy(c).validate_domain()) for k, c in self.compatibility))
        object.__setattr__(self, "pairs", tuple((a, b, LabelCell.from_legacy(c).validate_domain()) for a, b, c in self.pairs))
        if any(not isinstance(v, LabelSet) for v in self.task_labels):
            raise FactorContractError("typed task label sets required")
        scopes = [(v.task, v.subject) for v in self.task_labels]
        if len(set(scopes)) != len(scopes):
            raise FactorContractError("duplicate task supervision scope")

    def to_dict(self):
        return dict(roles=[[k, [c.to_dict() for c in cs]] for k, cs in self.roles],
                    compatibility=[[k, c.to_dict()] for k, c in self.compatibility],
                    pairs=[[a, b, c.to_dict()] for a, b, c in self.pairs],
                    task_labels=[v.to_dict() for v in self.task_labels])

    def graph_cells(self):
        """Typed v3 loss cells; omitted coordinates stay absent, never negative."""
        for key,values in self.roles:
            for role,cell in zip(ROLES,values):
                yield "legacy:"+role,(key,),"value",cell
        for key,cell in self.compatibility:
            yield "legacy:compatibility",(key,),"value",cell
        for a,b,cell in self.pairs:
            yield "legacy:pairs",(a,b),"value",cell
        for labels in self.task_labels:
            for coordinate,cell in labels.cells:
                yield labels.task,labels.subject,coordinate,cell

    @classmethod
    def from_dict(cls, value):
        fields(value, ("roles", "compatibility", "pairs", "task_labels"))
        if any(not isinstance(v, list) for v in value.values()):
            raise FactorContractError("target arrays required")
        for name, length in (("roles", 2), ("compatibility", 2), ("pairs", 3)):
            if any(not isinstance(v, list) or len(v) != length for v in value[name]):
                raise FactorContractError(f"targets.{name}: malformed row")
        if any(not isinstance(cs, list) for _, cs in value["roles"]):
            raise FactorContractError("targets.roles: cell arrays required")
        return cls(tuple((k, tuple(LabelCell.from_dict(c) for c in cs)) for k, cs in value["roles"]),
                   tuple((k, LabelCell.from_dict(c)) for k, c in value["compatibility"]),
                   tuple((a, b, LabelCell.from_dict(c)) for a, b, c in value["pairs"]),
                   tuple(LabelSet.from_dict(v) for v in value["task_labels"]))

    def validate(self, example, source):
        source.admit("group")
        keys = {group.key for group in example.groups}
        if any(not isinstance(value, tuple) for value in (self.roles, self.compatibility, self.pairs)):
            raise FactorContractError("immutable target tuples required")
        if self.roles and source.kind not in (*ENGINEERING_SOURCES, "human_feedback", "weak_context_annotation"):
            raise FactorContractError("engine/candidate outcomes do not supply contextual role labels")
        seen = set()
        for key, labels in self.roles:
            if key not in keys or key in seen or not isinstance(labels, tuple) or len(labels) != len(ROLES):
                raise FactorContractError("distinct known groups and one independent label per role required")
            seen.add(key)
            for value in labels:
                value.validate_domain()
            generic = labels[ROLES.index("generic_utility")]
            if generic.known:
                from .functional_units import assess_unit
                group = next(group for group in example.groups if group.key == key)
                if group.unit is None and generic.value > 0:
                    raise FactorContractError("positive conditional genericity needs an explicit minimum function scope")
                if generic.value > 0 and (not group.unit.function_tags or not assess_unit(group.unit, group.member_refs)["minimal_membership_complete"]):
                    raise FactorContractError("positive conditional genericity belongs to exact minimum membership; current readiness is separate and package roles never broadcast to members")
        seen = set()
        for key, value in self.compatibility:
            if key not in keys or key in seen:
                raise FactorContractError("distinct compatibility target groups required")
            seen.add(key)
            value.validate_domain()
        seen = set()
        for left, right, value in self.pairs:
            identity = frozenset((left, right))
            if left not in keys or right not in keys or left == right or identity in seen:
                raise FactorContractError("distinct known unordered compatibility target pairs required")
            seen.add(identity)
            value.validate_domain()


def source_fingerprint():
    """Bind this optional package, not the mutable sibling construction windows."""
    return digest({path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in sorted(Path(__file__).parent.glob("*.py"))})


class RoleTrainer:
    def __init__(self, config=NetworkConfig(), *, learning_rate=0.001, label_protocol_sha256=DEFAULT_LABEL_PROTOCOL_SHA256, device="cpu", binding=None, task_weights=None, optimizer_config=None, gradient_clip=1.0):
        if type(learning_rate) not in (float, int) or not 0 < learning_rate <= 0.1:
            raise FactorContractError("bounded positive learning rate required")
        self.device = torch.device(device)
        if self.device.type == "cuda" and not torch.cuda.is_available():
            raise FactorContractError("CUDA explicitly requested but unavailable; no CPU fallback")
        self.model = RoleNetwork(config).to(self.device)
        sha256_text(label_protocol_sha256, "label protocol")
        self.label_protocol_sha256 = label_protocol_sha256
        self.learning_rate = float(learning_rate)
        self.optimizer_config = dict(name="adam",weight_decay=0.0) if optimizer_config is None else dict(optimizer_config)
        fields(self.optimizer_config,("name","weight_decay"))
        if (self.optimizer_config['name'] not in ('adam','adamw') or
                type(self.optimizer_config['weight_decay']) not in (int,float) or not 0<=self.optimizer_config['weight_decay']<=1 or
                type(gradient_clip) not in (int,float) or not 0<gradient_clip<=100):
            raise FactorContractError('invalid optimizer/gradient configuration')
        if config.feature_schema!='axis-graph-v3' and (optimizer_config is not None or gradient_clip!=1.0):
            raise FactorContractError('training controls require v3')
        self.gradient_clip = float(gradient_clip)
        optimizer = torch.optim.AdamW if self.optimizer_config['name']=='adamw' else torch.optim.Adam
        self.optimizer = optimizer(self.model.parameters(),lr=self.learning_rate,weight_decay=self.optimizer_config['weight_decay'])
        self.updates = {head: {kind: 0 for kind in SOURCE_KINDS} for head in OUTPUT_TASKS}
        self.steps = 0
        self.data_digest = digest([])
        self.data_cursor = ""
        self.lora = None
        self.inference_only = False
        if config.feature_schema=="axis-graph-v3":
            from .graph_training import initialize
            initialize(self,binding,task_weights)
        elif binding is not None or task_weights is not None:
            raise FactorContractError("v3 experiment bindings cannot be attached to a legacy network")

    def head_status(self, head):
        if self.model.config.feature_schema=="axis-graph-v3":
            from .graph_training import capability
            return capability(self,head)
        if head not in OUTPUT_TASKS:
            raise FactorContractError("unknown output head")
        if self.lora is not None and self.lora.active is not None:
            entry = self.lora.entries[self.lora.active]
            if self.lora.engineering_mode or any(counts[kind] for counts in entry.updates.values() for kind in ENGINEERING_SOURCES):
                return "engineering_only"
            counts = entry.updates[head]
            if any(counts[kind] for kind in SOURCE_KINDS if kind not in (*ENGINEERING_SOURCES, "weak_context_annotation")):
                return "trained_uncalibrated"
            if counts["weak_context_annotation"]:
                return "weakly_supervised_uncalibrated"
            return "untrained"
        return self._base_head_status(head)

    def _base_head_status(self, head):
        if self.model.config.feature_schema=="axis-graph-v3":
            return self.head_status(head)
        if head not in OUTPUT_TASKS:
            raise FactorContractError("unknown output head")
        counts = self.updates[head]
        if any(counts[kind] for kind in SOURCE_KINDS if kind not in (*ENGINEERING_SOURCES, "weak_context_annotation")):
            return "trained_uncalibrated"
        if counts["weak_context_annotation"]:
            return "weakly_supervised_uncalibrated"
        return "engineering_only" if any(counts[kind] for kind in ENGINEERING_SOURCES) else "untrained"

    def adaptation_status(self):
        return dict(enabled=False, stage="base_supervision") if self.lora is None else self.lora.status()

    def enable_lora(self, *, engineering_mode=False):
        if self.model.config.feature_schema=="axis-graph-v3":
            raise FactorContractError("v3 base stage has no environment adapter activation")
        from .adapters import AdapterBank
        if self.lora is not None:
            raise FactorContractError("adapter bank already enabled")
        self.lora = AdapterBank(self, engineering_mode=engineering_mode)

    def create_environment_adapter(self, config=None, *, engineering_mode=False,base_capabilities=None):
        from .environment import EnvironmentAdapter, EnvironmentConfig
        return EnvironmentAdapter(self, EnvironmentConfig() if config is None else config, engineering_mode=engineering_mode,base_capabilities=base_capabilities)

    def create_adapter(self, adapter_id, config=None):
        from .adapters import AdapterConfig
        if self.lora is None:
            raise FactorContractError("explicitly enable the optional adapter bank first")
        self.lora.create(adapter_id, AdapterConfig() if config is None else config)

    def activate_adapter(self, adapter_id):
        if self.lora is None:
            raise FactorContractError("adapter bank is not enabled")
        self.lora.activate(adapter_id)

    def save_adapter(self, path, adapter_id, *, data_cursor=None):
        if self.lora is None:
            raise FactorContractError("adapter bank is not enabled")
        self.lora.save(path, adapter_id, data_cursor=data_cursor)

    def load_adapter(self, path):
        from .adapters import AdapterBank
        return AdapterBank.load_into(self, path)

    def _training_entry(self, sources):
        return self if self.lora is None else self.lora.training_entry(sources)

    def _update(self, losses, head_sources, identity, destination):
        if not losses:
            raise FactorContractError("no observed training labels; unknown is not a negative")
        total = torch.stack([torch.stack(values).mean() for values in losses.values()]).mean()
        if not torch.isfinite(total):
            raise FactorContractError("non-finite training loss")
        destination.optimizer.zero_grad(set_to_none=True)
        total.backward()
        parameters = self.model.parameters() if destination is self else destination.deltas.parameters()
        norm = torch.nn.utils.clip_grad_norm_(parameters, 1.0, error_if_nonfinite=True)
        destination.optimizer.step()
        for head, kinds in head_sources.items():
            for kind in kinds:
                destination.updates[head][kind] += 1
        destination.steps += 1
        destination.data_digest = digest((destination.data_digest, identity))
        return dict(loss=float(total.detach()), component_losses={head: float(torch.stack(values).mean().detach())
                                                                 for head, values in losses.items()},
                    gradient_norm=float(norm), steps=destination.steps,
                    head_status={head: self.head_status(head) for head in HEADS})

    def train_supervised(self, examples, targets=None, sources=None, *, consistency=(), micro_batch_size=None):
        if self.inference_only:
            raise FactorContractError("inference-only model cannot update")
        if self.model.config.feature_schema=="axis-graph-v3":
            if targets is not None or sources is not None:
                raise FactorContractError("v3 takes complete four-block records, not parallel legacy labels")
            from .graph_training import train_supervised
            return train_supervised(self,examples,consistency=consistency,micro_batch_size=micro_batch_size)
        if consistency or targets is None or sources is None:
            raise FactorContractError("legacy training requires explicit target/source arrays")
        if len(examples) != len(targets) or len(examples) != len(sources):
            raise FactorContractError("one target and supervision source per example required")
        # Validate every source/target before any mutation or optimizer work.
        for example, target, source in zip(examples, targets, sources):
            if not isinstance(example, RoleInput) or not isinstance(target, Targets) or not isinstance(source, Supervision):
                raise FactorContractError("typed supervised examples required")
            target.validate(example, source)
            if target.task_labels:
                raise FactorContractError("new task heads are not connected yet; preserve task labels for M5")
            if target.roles and source.label_protocol_sha256 != self.label_protocol_sha256:
                raise FactorContractError("role label protocol differs from trainer")
        destination = self._training_entry(sources)
        self.model.train()
        output = self.model(encode_batch(examples, device=self.device))
        losses, kinds, role_weights = {}, {}, []

        def append(head, prediction, target, kind, *, dimension=None):
            if target.known:
                weight = source.confidence * target.confidence
                if dimension is not None:
                    index = ROLES.index(dimension)
                    weight *= source.role_confidence[index] * source.role_balance[index]
                    if weight == 0:
                        return
                    # Confidence scales evidence strength; it must not cancel
                    # itself from the denominator of an all-weak batch.
                    role_weights.append(source.role_balance[index])
                if weight == 0:
                    return
                loss = F.binary_cross_entropy_with_logits(prediction, prediction.new_tensor(float(target.value)))
                losses.setdefault(head, []).append(loss * weight)
                kinds.setdefault(head, set()).add(kind)
                if dimension is not None:
                    kinds.setdefault("role:" + dimension, set()).add(kind)

        for batch, (example, target, source) in enumerate(zip(examples, targets, sources)):
            indices = {group.key: i for i, group in enumerate(example.groups)}
            for key, labels in target.roles:
                for role, value in enumerate(labels):
                    append("role", output["role_logits"][batch, indices[key], role], value, source.kind, dimension=ROLES[role])
            for key, value in target.compatibility:
                append("compatibility", output["compatibility_logits"][batch, indices[key]], value, source.kind)
            for left, right, value in target.pairs:
                append("pair", output["pair_logits"][batch, indices[left], indices[right]], value, source.kind)
        identity = dict(examples=[example.to_dict() for example in examples], targets=[asdict(t) for t in targets],
                        sources=[asdict(s) for s in sources])
        if "role" in losses:
            # Sampling frequency changes optimization weight, never the target or
            # its source confidence. Normalize to avoid scaling down all gradients
            # when a common class receives a small inverse-frequency weight.
            losses["role"] = [torch.stack(losses["role"]).sum() / sum(role_weights)]
        return self._update(losses, kinds, identity, destination)

    def train_preference(self, left, right, *, left_key, right_key, preferred_left, source, comparison_operation=None):
        if self.inference_only:
            raise FactorContractError("inference-only model cannot update")
        if self.model.config.feature_schema=="axis-graph-v3":
            from .graph_training import train_preference
            return train_preference(self,left,right,left_key=left_key,right_key=right_key,preferred_left=preferred_left,
                                    source=source,comparison_operation=comparison_operation)
        if not isinstance(source, Supervision) or not isinstance(left, RoleInput) or not isinstance(right, RoleInput):
            raise FactorContractError("typed candidate preference required")
        source.admit("candidate")
        unit(preferred_left, "candidate preference")
        if left.context_ref != right.context_ref or left.context != right.context:
            raise FactorContractError("paired candidates must share the exact frozen goal/context")
        indices = [{g.key: i for i, g in enumerate(e.groups)} for e in (left, right)]
        if left_key not in indices[0] or right_key not in indices[1]:
            raise FactorContractError("candidate target group missing")
        destination = self._training_entry((source,))
        self.model.train()
        output = self.model(encode_batch((left, right), device=self.device))
        delta = output["utility"][0, indices[0][left_key]] - output["utility"][1, indices[1][right_key]]
        loss = F.binary_cross_entropy_with_logits(delta, delta.new_tensor(float(preferred_left))) * source.confidence
        return self._update({"utility": [loss]}, {"utility": {source.kind}},
                            dict(left=left.to_dict(), right=right.to_dict(), left_key=left_key, right_key=right_key,
                                 preferred_left=preferred_left, source=asdict(source)), destination)

    def save(self, path, *, data_cursor=None):
        if self.model.config.feature_schema=="axis-graph-v3":
            from .graph_training import save
            return save(self,path,data_cursor=data_cursor)
        if self.lora is not None and self.lora.active is not None:
            raise FactorContractError("save active adapter independently; disable it before saving the unchanged base")
        data_cursor = self.data_cursor if data_cursor is None else data_cursor
        text(data_cursor, "data cursor", optional=True)
        path = Path(path)
        payload = dict(version=CHECKPOINT_VERSION, schema_sha256=schema_fingerprint(), source_sha256=source_fingerprint(),
                       label_protocol_sha256=self.label_protocol_sha256,
                       config=self.model.config_dict(), learning_rate=self.learning_rate,
                       model=self.model.state_dict(), optimizer=self.optimizer.state_dict(),
                       updates=self.updates, steps=self.steps, data_digest=self.data_digest, data_cursor=data_cursor,
                       rng_policy="deterministic operations; initialization preserves host RNG", calibrated=False)
        # Same-directory replacement leaves the previous checkpoint intact if serialization fails.
        with tempfile.NamedTemporaryFile(prefix=path.name + ".", suffix=".tmp", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
        try:
            torch.save(payload, temporary)
            os.replace(temporary, path)
            self.data_cursor = data_cursor
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls, path, *, expected_label_protocol_sha256=DEFAULT_LABEL_PROTOCOL_SHA256, device="cpu",
             mode="resume", expected_config=None, expected_binding=None, expected_learning_rate=None, expected_task_weights=None,
             expected_optimizer_config=None, expected_gradient_clip=None):
        payload = torch.load(Path(path), map_location="cpu", weights_only=True)
        if payload.get("version")=="axis-checkpoint-v3-m5":
            from .graph_training import load
            return load(cls,payload,config=expected_config,binding=expected_binding,label_protocol_sha256=expected_label_protocol_sha256,
                        device=device,mode=mode,learning_rate=expected_learning_rate,task_weights=expected_task_weights,
                        optimizer_config=expected_optimizer_config,gradient_clip=expected_gradient_clip)
        if mode!="resume" or expected_config is not None or expected_binding is not None:
            raise FactorContractError("legacy checkpoint has no compatible v3 encoder; no implicit warm start")
        fields(payload, ("version", "schema_sha256", "source_sha256", "label_protocol_sha256", "config", "learning_rate", "model", "optimizer",
                         "updates", "steps", "data_digest", "data_cursor", "rng_policy", "calibrated"))
        if (payload["version"] != CHECKPOINT_VERSION or payload["schema_sha256"] != schema_fingerprint()
                or payload["source_sha256"] != source_fingerprint()):
            raise FactorContractError("checkpoint schema or module source differs; preserve old version or migrate explicitly")
        sha256_text(expected_label_protocol_sha256, "expected label protocol")
        if payload["label_protocol_sha256"] != expected_label_protocol_sha256:
            raise FactorContractError("checkpoint label protocol differs; do not reuse weights under changed definitions")
        if type(payload["steps"]) is not int or payload["steps"] < 0 or payload["calibrated"] is not False:
            raise FactorContractError("invalid checkpoint training/calibration metadata")
        fields(payload["updates"], OUTPUT_TASKS)
        for counts in payload["updates"].values():
            fields(counts, SOURCE_KINDS)
            if any(type(n) is not int or not 0 <= n <= payload["steps"] for n in counts.values()):
                raise FactorContractError("invalid checkpoint update counts")
        text(payload["data_cursor"], "data cursor", optional=True)
        if (not isinstance(payload["data_digest"], str) or len(payload["data_digest"]) != 64
                or any(c not in "0123456789abcdef" for c in payload["data_digest"])):
            raise FactorContractError("invalid checkpoint data digest")
        trainer = cls(NetworkConfig(**payload["config"]), learning_rate=payload["learning_rate"],
                      label_protocol_sha256=expected_label_protocol_sha256, device=device)
        trainer.model.load_state_dict(payload["model"], strict=True)
        trainer.optimizer.load_state_dict(payload["optimizer"])
        trainer.updates, trainer.steps = payload["updates"], payload["steps"]
        trainer.data_digest, trainer.data_cursor = payload["data_digest"], payload["data_cursor"]
        return trainer

    @classmethod
    def warm_start(cls,path,*,config,binding,label_protocol_sha256,device="cpu",learning_rate=.001,task_weights=None):
        return cls.load(path,mode="warm_start",expected_config=config,expected_binding=binding,
            expected_label_protocol_sha256=label_protocol_sha256,device=device,
            expected_learning_rate=learning_rate,expected_task_weights=task_weights)
