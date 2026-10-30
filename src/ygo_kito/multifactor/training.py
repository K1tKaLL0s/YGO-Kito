"""Masked supervision, candidate preference updates and independent checkpoints."""

from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import tempfile

import torch
from torch.nn import functional as F

from .contracts import (DEFAULT_LABEL_PROTOCOL_SHA256, ROLES, FactorContractError, RoleInput,
                        digest, fields, schema_fingerprint, sha256_text, text, unit)
from .network import NetworkConfig, RoleNetwork, encode_batch

SOURCE_KINDS = ("engineering_fixture", "definition_development", "engine_probe", "self_generated_candidate", "human_feedback")
ENGINEERING_SOURCES = ("engineering_fixture", "definition_development")
HEADS = ("role", "compatibility", "pair", "utility")
OUTPUT_TASKS = HEADS + tuple("role:" + role for role in ROLES)
CHECKPOINT_VERSION = "multifactor-checkpoint-v2"


@dataclass(frozen=True)
class Supervision:
    kind: str
    evidence_ref: str
    partition: str = "train"
    scope: str = "group"
    label_protocol_sha256: str = DEFAULT_LABEL_PROTOCOL_SHA256

    def __post_init__(self):
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
    roles: tuple[tuple[str, tuple[float | None, ...]], ...] = ()
    compatibility: tuple[tuple[str, float | None], ...] = ()
    pairs: tuple[tuple[str, str, float | None], ...] = ()

    def validate(self, example, source):
        source.admit("group")
        keys = {group.key for group in example.groups}
        if any(not isinstance(value, tuple) for value in (self.roles, self.compatibility, self.pairs)):
            raise FactorContractError("immutable target tuples required")
        if self.roles and source.kind not in (*ENGINEERING_SOURCES, "human_feedback"):
            raise FactorContractError("engine/candidate outcomes do not supply contextual role labels")
        seen = set()
        for key, labels in self.roles:
            if key not in keys or key in seen or not isinstance(labels, tuple) or len(labels) != len(ROLES):
                raise FactorContractError("distinct known groups and one independent label per role required")
            seen.add(key)
            for value in labels:
                if value is not None:
                    unit(value, "role target")
            generic = labels[ROLES.index("generic_utility")]
            if generic is not None:
                from .functional_units import assess_unit
                group = next(group for group in example.groups if group.key == key)
                if group.unit is None:
                    raise FactorContractError("genericity labels require explicit function/context/dependencies")
                if generic > 0 and (not group.unit.function_tags or not assess_unit(group.unit, group.member_refs)["exact_minimum"]):
                    raise FactorContractError("positive genericity belongs to the exact usable joint unit; never broadcast to members")
        seen = set()
        for key, value in self.compatibility:
            if key not in keys or key in seen:
                raise FactorContractError("distinct compatibility target groups required")
            seen.add(key)
            if value is not None:
                unit(value, "compatibility target")
        seen = set()
        for left, right, value in self.pairs:
            identity = frozenset((left, right))
            if left not in keys or right not in keys or left == right or identity in seen:
                raise FactorContractError("distinct known unordered compatibility target pairs required")
            seen.add(identity)
            if value is not None:
                unit(value, "pair target")


def source_fingerprint():
    """Bind this optional package, not the mutable sibling construction windows."""
    return digest({path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in sorted(Path(__file__).parent.glob("*.py"))})


class RoleTrainer:
    def __init__(self, config=NetworkConfig(), *, learning_rate=0.001, label_protocol_sha256=DEFAULT_LABEL_PROTOCOL_SHA256):
        if type(learning_rate) not in (float, int) or not 0 < learning_rate <= 0.1:
            raise FactorContractError("bounded positive learning rate required")
        self.model = RoleNetwork(config)
        sha256_text(label_protocol_sha256, "label protocol")
        self.label_protocol_sha256 = label_protocol_sha256
        self.learning_rate = float(learning_rate)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=self.learning_rate)
        self.updates = {head: {kind: 0 for kind in SOURCE_KINDS} for head in OUTPUT_TASKS}
        self.steps = 0
        self.data_digest = digest([])
        self.data_cursor = ""
        self.lora = None

    def head_status(self, head):
        if head not in OUTPUT_TASKS:
            raise FactorContractError("unknown output head")
        if self.lora is not None and self.lora.active is not None:
            entry = self.lora.entries[self.lora.active]
            if self.lora.engineering_mode or any(counts[kind] for counts in entry.updates.values() for kind in ENGINEERING_SOURCES):
                return "engineering_only"
            counts = entry.updates[head]
            if any(counts[kind] for kind in SOURCE_KINDS if kind not in ENGINEERING_SOURCES):
                return "trained_uncalibrated"
            return "untrained"
        return self._base_head_status(head)

    def _base_head_status(self, head):
        if head not in OUTPUT_TASKS:
            raise FactorContractError("unknown output head")
        counts = self.updates[head]
        if any(counts[kind] for kind in SOURCE_KINDS if kind not in ENGINEERING_SOURCES):
            return "trained_uncalibrated"
        return "engineering_only" if any(counts[kind] for kind in ENGINEERING_SOURCES) else "untrained"

    def adaptation_status(self):
        return dict(enabled=False, stage="base_supervision") if self.lora is None else self.lora.status()

    def enable_lora(self, *, engineering_mode=False):
        from .adapters import AdapterBank
        if self.lora is not None:
            raise FactorContractError("adapter bank already enabled")
        self.lora = AdapterBank(self, engineering_mode=engineering_mode)

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

    def train_supervised(self, examples, targets, sources):
        if len(examples) != len(targets) or len(examples) != len(sources):
            raise FactorContractError("one target and supervision source per example required")
        # Validate every source/target before any mutation or optimizer work.
        for example, target, source in zip(examples, targets, sources):
            if not isinstance(example, RoleInput) or not isinstance(target, Targets) or not isinstance(source, Supervision):
                raise FactorContractError("typed supervised examples required")
            target.validate(example, source)
            if target.roles and source.label_protocol_sha256 != self.label_protocol_sha256:
                raise FactorContractError("role label protocol differs from trainer")
        destination = self._training_entry(sources)
        self.model.train()
        output = self.model(encode_batch(examples))
        losses, kinds = {}, {}

        def append(head, prediction, target, kind, *, dimension=None):
            if target is not None:
                loss = F.binary_cross_entropy_with_logits(prediction, prediction.new_tensor(float(target)))
                losses.setdefault(head, []).append(loss)
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
        return self._update(losses, kinds, identity, destination)

    def train_preference(self, left, right, *, left_key, right_key, preferred_left, source):
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
        output = self.model(encode_batch((left, right)))
        delta = output["utility"][0, indices[0][left_key]] - output["utility"][1, indices[1][right_key]]
        loss = F.binary_cross_entropy_with_logits(delta, delta.new_tensor(float(preferred_left)))
        return self._update({"utility": [loss]}, {"utility": {source.kind}},
                            dict(left=left.to_dict(), right=right.to_dict(), left_key=left_key, right_key=right_key,
                                 preferred_left=preferred_left, source=asdict(source)), destination)

    def save(self, path, *, data_cursor=None):
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
    def load(cls, path, *, expected_label_protocol_sha256=DEFAULT_LABEL_PROTOCOL_SHA256):
        payload = torch.load(Path(path), map_location="cpu", weights_only=True)
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
                      label_protocol_sha256=expected_label_protocol_sha256)
        trainer.model.load_state_dict(payload["model"], strict=True)
        trainer.optimizer.load_state_dict(payload["optimizer"])
        trainer.updates, trainer.steps = payload["updates"], payload["steps"]
        trainer.data_digest, trainer.data_cursor = payload["data_digest"], payload["data_cursor"]
        return trainer
