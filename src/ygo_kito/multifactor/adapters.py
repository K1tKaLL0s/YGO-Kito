"""Optional low-rank deltas, separately bound to an immutable supervised base.

No base is downloaded or inferred from an active construction model. Engineering
mode supports code checks on random bases and can never release trained scores.
"""

from dataclasses import asdict, dataclass
import hashlib
import math
import os
from pathlib import Path
import re
import tempfile

import torch
from torch import nn
from torch.nn import functional as F

from .contracts import ROLES, FactorContractError, digest, fields, schema_fingerprint
from .training import ENGINEERING_SOURCES, OUTPUT_TASKS, SOURCE_KINDS, source_fingerprint

ADAPTER_VERSION = "multifactor-lora-v1"
TARGETS = ("readout.0", "role_head", "compatibility_head", "utility_head", "pair_head.0")


def base_binding(trainer):
    weights = {key: dict(shape=list(value.shape), dtype=str(value.dtype),
                         sha256=hashlib.sha256(value.detach().cpu().contiguous().numpy().tobytes()).hexdigest())
               for key, value in trainer.model.state_dict().items()}
    return digest(dict(weights=weights, updates=trainer.updates, data_digest=trainer.data_digest,
                       config=trainer.model.config_dict(), label_protocol=trainer.label_protocol_sha256))


@dataclass(frozen=True)
class AdapterConfig:
    rank: int = 4
    alpha: float = 4.0
    seed: int = 140

    def __post_init__(self):
        if type(self.rank) is not int or not 1 <= self.rank <= 16:
            raise FactorContractError("adapter rank must be 1..16")
        if type(self.alpha) not in (float, int) or not math.isfinite(self.alpha) or not 0 < self.alpha <= 64:
            raise FactorContractError("adapter alpha must be finite and positive")
        if type(self.seed) is not int or not 0 <= self.seed < 2**31:
            raise FactorContractError("adapter seed must be bounded")


class LowRankDelta(nn.Module):
    def __init__(self, incoming, outgoing, config):
        super().__init__()
        self.a = nn.Parameter(torch.empty(config.rank, incoming))
        self.b = nn.Parameter(torch.zeros(outgoing, config.rank))
        nn.init.kaiming_uniform_(self.a, a=math.sqrt(5))
        self.scale = config.alpha / config.rank

    def forward(self, value):
        return F.linear(F.linear(value, self.a), self.b) * self.scale


class AdapterEntry:
    def __init__(self, model, config, learning_rate):
        self.config = config
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(config.seed)
            self.deltas = nn.ModuleDict({str(i): LowRankDelta(model.get_submodule(name).in_features,
                                                            model.get_submodule(name).out_features, config)
                                         for i, name in enumerate(TARGETS)})
        self.optimizer = torch.optim.Adam(self.deltas.parameters(), lr=learning_rate)
        self.updates = {head: {kind: 0 for kind in SOURCE_KINDS} for head in OUTPUT_TASKS}
        self.steps, self.data_digest, self.data_cursor = 0, digest([]), ""


class AdapterBank:
    @staticmethod
    def validate_mode(trainer, engineering_mode):
        if type(engineering_mode) is not bool:
            raise FactorContractError("explicit adapter engineering mode required")
        if not engineering_mode and any(trainer._base_head_status("role:" + role) != "trained_uncalibrated" for role in ROLES):
            raise FactorContractError("LoRA adaptation requires supervised base role records; random/engineering base is not learned concepts")

    def __init__(self, trainer, *, engineering_mode=False):
        self.validate_mode(trainer, engineering_mode)
        self.trainer, self.engineering_mode = trainer, engineering_mode
        self.binding = base_binding(trainer)
        self.entries, self.active = {}, None
        self.hooks = []
        self.original_grad_flags = tuple((parameter, parameter.requires_grad) for parameter in trainer.model.parameters())
        modules = tuple(trainer.model.get_submodule(name) for name in TARGETS)
        try:
            for parameter, _ in self.original_grad_flags:
                parameter.requires_grad_(False)
            for i, module in enumerate(modules):
                def hook(module, inputs, output, index=str(i)):
                    return output if self.active is None else output + self.entries[self.active].deltas[index](inputs[0])
                self.hooks.append(module.register_forward_hook(hook))
        except BaseException:
            self._rollback_install()
            raise

    def _rollback_install(self):
        for handle in self.hooks:
            handle.remove()
        self.hooks.clear()
        for parameter, original in self.original_grad_flags:
            parameter.requires_grad_(original)

    @staticmethod
    def validate_id(adapter_id):
        if not isinstance(adapter_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", adapter_id):
            raise FactorContractError("bounded adapter identifier required")

    def check_base(self):
        if base_binding(self.trainer) != self.binding:
            raise FactorContractError("base changed; adapter requires its exact independent base version")

    def create(self, adapter_id, config=AdapterConfig()):
        self.validate_id(adapter_id)
        self.check_base()
        if adapter_id in self.entries:
            raise FactorContractError("adapter already exists")
        self.entries[adapter_id] = AdapterEntry(self.trainer.model, config, self.trainer.learning_rate)
        self.active = adapter_id

    def activate(self, adapter_id):
        self.check_base()
        if adapter_id is not None and adapter_id not in self.entries:
            raise FactorContractError("unknown adapter")
        self.active = adapter_id

    def training_entry(self, sources):
        self.check_base()
        if self.active is None:
            raise FactorContractError("base is frozen for adapter versions; activate an adapter or train a separate base")
        if self.engineering_mode and any(source.kind not in ENGINEERING_SOURCES for source in sources):
            raise FactorContractError("engineering adapter cannot admit real-training provenance")
        if not self.engineering_mode and any(source.kind in ENGINEERING_SOURCES for source in sources):
            raise FactorContractError("normal adapter cannot admit engineering/development provenance")
        return self.entries[self.active]

    def status(self):
        return dict(enabled=True, active=self.active, engineering_mode=self.engineering_mode, base_binding=self.binding,
                    inference_source="base" if self.active is None else "adapter",
                    base_head_status={head: self.trainer._base_head_status(head) for head in OUTPUT_TASKS},
                    active_head_status=None if self.active is None else {head: self.trainer.head_status(head) for head in OUTPUT_TASKS},
                    adapters={key: dict(config=asdict(entry.config), steps=entry.steps, data_digest=entry.data_digest)
                              for key, entry in self.entries.items()}, base_concept_quality="not_certified_by_update_counts")

    def save(self, path, adapter_id, *, data_cursor=None):
        self.check_base()
        if adapter_id not in self.entries:
            raise FactorContractError("unknown adapter")
        entry = self.entries[adapter_id]
        cursor = entry.data_cursor if data_cursor is None else data_cursor
        from .contracts import text
        text(cursor, "adapter data cursor", optional=True)
        payload = dict(version=ADAPTER_VERSION, adapter_id=adapter_id, config=asdict(entry.config), targets=list(TARGETS),
                       base_binding=self.binding, label_protocol_sha256=self.trainer.label_protocol_sha256,
                       schema_sha256=schema_fingerprint(), source_sha256=source_fingerprint(),
                       engineering_mode=self.engineering_mode, learning_rate=self.trainer.learning_rate,
                       weights=entry.deltas.state_dict(), optimizer=entry.optimizer.state_dict(), updates=entry.updates,
                       steps=entry.steps, data_digest=entry.data_digest, data_cursor=cursor, calibrated=False)
        path = Path(path)
        with tempfile.NamedTemporaryFile(prefix=path.name + ".", suffix=".tmp", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
        try:
            torch.save(payload, temporary)
            os.replace(temporary, path)
            entry.data_cursor = cursor
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def load_into(cls, trainer, path):
        payload = torch.load(Path(path), map_location="cpu", weights_only=True)
        fields(payload, ("version", "adapter_id", "config", "targets", "base_binding", "label_protocol_sha256", "schema_sha256",
                         "source_sha256", "engineering_mode", "learning_rate", "weights", "optimizer", "updates", "steps", "data_digest", "data_cursor", "calibrated"))
        if (payload["version"] != ADAPTER_VERSION or payload["targets"] != list(TARGETS) or
                payload["schema_sha256"] != schema_fingerprint() or payload["source_sha256"] != source_fingerprint() or
                payload["label_protocol_sha256"] != trainer.label_protocol_sha256 or
                payload["base_binding"] != base_binding(trainer) or payload["learning_rate"] != trainer.learning_rate):
            raise FactorContractError("adapter base/schema/source/protocol binding differs; no implicit migration")
        if type(payload["steps"]) is not int or payload["steps"] < 0 or payload["calibrated"] is not False:
            raise FactorContractError("invalid adapter update metadata")
        fields(payload["updates"], OUTPUT_TASKS)
        for counts in payload["updates"].values():
            fields(counts, SOURCE_KINDS)
            if any(type(value) is not int or not 0 <= value <= payload["steps"] for value in counts.values()):
                raise FactorContractError("invalid adapter per-head counts")
        from .contracts import sha256_text, text
        sha256_text(payload["data_digest"], "adapter data digest")
        text(payload["data_cursor"], "adapter data cursor", optional=True)
        cls.validate_mode(trainer, payload["engineering_mode"])
        cls.validate_id(payload["adapter_id"])
        if not payload["engineering_mode"] and any(counts[kind] for counts in payload["updates"].values() for kind in ENGINEERING_SOURCES):
            raise FactorContractError("normal adapter checkpoint contains engineering/development provenance")
        if trainer.lora is not None and trainer.lora.engineering_mode != payload["engineering_mode"]:
            raise FactorContractError("adapter engineering mode differs")
        if trainer.lora is not None:
            trainer.lora.check_base()
            if payload["adapter_id"] in trainer.lora.entries:
                raise FactorContractError("adapter already exists")
        # Recover into a detached object. No base flags, hooks, registry or active
        # version may change while validating weights or restoring Adam.
        entry = AdapterEntry(trainer.model, AdapterConfig(**payload["config"]), trainer.learning_rate)
        expected = entry.deltas.state_dict()
        fields(payload["weights"], expected)
        for key, value in payload["weights"].items():
            if (not isinstance(value, torch.Tensor) or value.shape != expected[key].shape or
                    value.dtype != expected[key].dtype or not torch.isfinite(value).all()):
                raise FactorContractError("invalid adapter weight tensor")
        entry.deltas.load_state_dict(payload["weights"], strict=True)
        cls.validate_adam(entry, payload["optimizer"], payload["steps"])
        entry.optimizer.load_state_dict(payload["optimizer"])
        entry.updates, entry.steps = payload["updates"], payload["steps"]
        entry.data_digest, entry.data_cursor = payload["data_digest"], payload["data_cursor"]
        previous_bank = trainer.lora
        bank = previous_bank if previous_bank is not None else cls(trainer, engineering_mode=payload["engineering_mode"])
        previous_active = bank.active
        try:
            bank.entries[payload["adapter_id"]] = entry
            bank.active = payload["adapter_id"]
            trainer.lora = bank
        except BaseException:
            bank.entries.pop(payload["adapter_id"], None)
            bank.active = previous_active
            trainer.lora = previous_bank
            if previous_bank is None:
                bank._rollback_install()
            raise
        return payload["adapter_id"]

    @staticmethod
    def validate_adam(entry, value, steps):
        """Adam.load_state_dict alone does not reject wrong moment shapes."""
        fields(value, ("state", "param_groups"))
        expected_groups = entry.optimizer.state_dict()["param_groups"]
        if not isinstance(value["param_groups"], list) or len(value["param_groups"]) != len(expected_groups):
            raise FactorContractError("invalid adapter Adam parameter groups")
        ids = []
        for actual, expected in zip(value["param_groups"], expected_groups):
            fields(actual, expected)
            if any(type(actual[key]) is not type(expected[key]) or actual[key] != expected[key] for key in expected):
                raise FactorContractError("adapter Adam groups/settings differ")
            ids.extend(actual["params"])
        if not isinstance(value["state"], dict) or any(type(key) is not int or key not in ids for key in value["state"]):
            raise FactorContractError("invalid adapter Adam parameter state")
        if bool(value["state"]) != bool(steps):
            raise FactorContractError("adapter Adam state missing or inconsistent with updates")
        parameters = dict(zip(ids, entry.deltas.parameters()))
        for key, state in value["state"].items():
            fields(state, ("step", "exp_avg", "exp_avg_sq"))
            step = state["step"]
            if (not isinstance(step, torch.Tensor) or step.ndim != 0 or not step.is_floating_point() or
                    not torch.isfinite(step) or not 0 < float(step) <= steps or float(step) != int(float(step))):
                raise FactorContractError("invalid adapter Adam step")
            for name in ("exp_avg", "exp_avg_sq"):
                tensor = state[name]
                parameter = parameters[key]
                if (not isinstance(tensor, torch.Tensor) or tensor.shape != parameter.shape or tensor.dtype != parameter.dtype or
                        not torch.isfinite(tensor).all() or name == "exp_avg_sq" and torch.any(tensor < 0)):
                    raise FactorContractError("invalid adapter Adam moment tensor")
