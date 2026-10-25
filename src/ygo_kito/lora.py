"""CPU low-rank adapters with frozen, fingerprinted bases and explicit rollback.

Adapters use PyTorch parametrizations, including Linear weights accessed by a
Transformer fast path. No downloaded model, implicit merging or stacking.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path

import torch
from torch import nn
from torch.nn.utils import parametrize

from .agent_registry import identifier
from .build_contracts import digest
from .duel_model import parameter_digest
from .device import (model_device, execution_metadata, checkpoint_execution, optimizer_to,
                     capture_device_rng, restore_device_rng)
from .validation import ContractError, fields, integer

ROLES = ("duel", "build_goal", "build_optimizer", "coordinator")


def tensor_digest(values):
    if not isinstance(values, dict) or any(not isinstance(n, str) or not isinstance(v, torch.Tensor) for n, v in values.items()):
        raise ContractError("named tensors required for adapter checksum")
    h = hashlib.sha256()
    for name, value in sorted(values.items()):
        h.update(name.encode())
        h.update(value.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


@dataclass(frozen=True)
class AdapterConfig:
    adapter_id: str
    role: str
    targets: tuple
    rank: int = 4
    alpha: float = 8.
    seed: int = 881
    learning_rate: float = .003
    max_updates: int = 2

    def __post_init__(self):
        identifier(self.adapter_id)
        if self.role not in ROLES or not isinstance(self.targets, tuple) or not self.targets or len(self.targets) > 16:
            raise ContractError("explicit role and bounded LoRA targets required")
        if any(not isinstance(t, str) or not t or len(t) > 128 for t in self.targets) or len(set(self.targets)) != len(self.targets):
            raise ContractError("LoRA targets must be unique module names")
        integer(self.rank, "LoRA rank", 1, 16)
        integer(self.seed, "LoRA seed", 0, 2**32 - 8)
        integer(self.max_updates, "LoRA update budget", 1, 10000)
        for name, value, limit in (("alpha", self.alpha, 128), ("learning_rate", self.learning_rate, .01)):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= limit:
                raise ContractError("invalid LoRA " + name)

    @classmethod
    def from_dict(cls, value):
        d = fields(value, set(cls.__dataclass_fields__))
        if not isinstance(d["targets"], list):
            raise ContractError("LoRA targets must be an array")
        return cls(**dict(d, targets=tuple(d["targets"])))

    def to_dict(self):
        return dict(asdict(self), targets=list(self.targets))


class LowRankWeight(nn.Module):
    def __init__(self, weight, config):
        super().__init__()
        self.a = nn.Parameter(torch.empty(config.rank, weight.shape[1], dtype=weight.dtype, device=weight.device))
        self.b = nn.Parameter(torch.zeros(weight.shape[0], config.rank, dtype=weight.dtype, device=weight.device))
        nn.init.kaiming_uniform_(self.a, a=math.sqrt(5))
        self.scale, self.enabled = config.alpha / config.rank, True

    def forward(self, original):
        return original + (self.b @ self.a) * self.scale if self.enabled else original


class AdapterSession:
    def __init__(self, model, config, binding):
        if not isinstance(config, AdapterConfig) or not isinstance(model, nn.Module):
            raise ContractError("typed model and adapter configuration required")
        fields(binding, {"base_version", "feature_version", "context_sha256"})
        identifier(binding["base_version"])
        if not isinstance(binding["feature_version"], str) or not binding["feature_version"]:
            raise ContractError("adapter feature version required")
        from .coord_contracts import sha256
        sha256(binding["context_sha256"])
        if any(parametrize.is_parametrized(m) for m in model.modules()):
            raise ContractError("adapter stacking/replacement unsupported; unload explicitly")
        self.device = model_device(model)
        if any(p.dtype != torch.float32 for p in model.parameters()):
            raise ContractError("this adapter implementation requires float32 bases")
        targets = {}
        for name in config.targets:
            try:
                layer = model.get_submodule(name)
            except AttributeError:
                raise ContractError("unknown adapter target") from None
            if not isinstance(layer, nn.Linear) or config.rank > min(layer.weight.shape):
                raise ContractError("adapter target must be a compatible Linear weight")
            targets[name] = layer
        if len({id(m) for m in targets.values()}) != len(targets):
            raise ContractError("adapter targets cannot alias the same module")
        self.model, self.config, self.binding = model, config, dict(binding)
        self.base_parameters = dict(model.named_parameters())
        self.base_buffers = dict(model.named_buffers())
        self.base_sha256 = parameter_digest(model)
        self.base_flags = {n: p.requires_grad for n, p in self.base_parameters.items()}
        self.layers, self.deltas = targets, {}
        self.detached, self.enabled = False, True
        for p in self.base_parameters.values():
            p.requires_grad_(False)
            p.grad = None
        with torch.random.fork_rng(devices=[self.device.index] if self.device.type == "cuda" else []):
            torch.random.default_generator.manual_seed(config.seed)
            if self.device.type == "cuda":
                with torch.cuda.device(self.device):
                    torch.cuda.manual_seed(config.seed)
            for name, layer in targets.items():
                delta = LowRankWeight(layer.weight, config)
                parametrize.register_parametrization(layer, "weight", delta)
                self.deltas[name] = delta
        self.optimizer = torch.optim.AdamW(self.parameters(), lr=config.learning_rate, weight_decay=0., foreach=False, fused=False)
        self.scheduler = torch.optim.lr_scheduler.StepLR(self.optimizer, 1, .99)
        self.rng = torch.Generator(device="cpu").manual_seed(config.seed + 1)
        self.updates = 0
        self.verify_base()

    def parameters(self):
        return [p for d in self.deltas.values() for p in d.parameters()]

    def weights(self):
        return {name + "." + k: p for name, d in self.deltas.items() for k, p in d.named_parameters()}

    def compatibility(self):
        return {"schema_version": 1, "kind": "lora-linear-cpu-v1" if self.device.type == "cpu" else "lora-linear-device-v2", "config": self.config.to_dict(),
                **({"execution": execution_metadata(self.device)} if self.device.type == "cuda" else {}),
                "binding": self.binding, "base_sha256": self.base_sha256,
                "target_shapes": {n: list(self.layers[n].parametrizations.weight.original.shape) for n in self.layers}}

    def version_id(self):
        return digest({"compatibility": self.compatibility(), "weights": tensor_digest(self.weights())})

    def verify_base(self):
        actual = tensor_digest(dict(self.base_parameters, **self.base_buffers))
        if actual != self.base_sha256 or any(p.requires_grad or p.grad is not None for p in self.base_parameters.values()):
            raise ContractError("LoRA base changed, received gradients or became trainable")
        return actual

    def set_enabled(self, value):
        if type(value) is not bool or self.detached:
            raise ContractError("explicit active adapter selection required")
        for d in self.deltas.values():
            d.enabled = value
        self.enabled = value
        self.verify_base()

    @contextmanager
    def suspended(self):
        """Expose the exact base for existing checkpoint writers; restore on exit."""
        if self.detached:
            raise ContractError("adapter already unloaded")
        self.verify_base()
        for layer in self.layers.values():
            parametrize.remove_parametrizations(layer, "weight", leave_parametrized=False)
        try:
            yield
        finally:
            for name, layer in self.layers.items():
                parametrize.register_parametrization(layer, "weight", self.deltas[name])
            self.verify_base()

    def unload(self):
        if self.detached:
            raise ContractError("adapter already unloaded")
        self.verify_base()
        for layer in self.layers.values():
            parametrize.remove_parametrizations(layer, "weight", leave_parametrized=False)
        if parameter_digest(self.model) != self.base_sha256:
            raise ContractError("rollback did not restore original base")
        for name, p in self.base_parameters.items():
            p.requires_grad_(self.base_flags[name])
        self.detached = True
        return self.base_sha256

    def step(self, loss):
        if self.detached or not self.enabled or self.updates >= self.config.max_updates:
            raise ContractError("adapter inactive or update budget exhausted")
        if not isinstance(loss, torch.Tensor) or loss.device != self.device or loss.ndim != 0 or not loss.requires_grad or not torch.isfinite(loss):
            raise ContractError("adapter requires a finite scalar loss")
        self.verify_base()
        before = {n: p.detach().clone() for n, p in self.weights().items()}
        self.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        norm = float(torch.nn.utils.clip_grad_norm_(self.parameters(), .5, error_if_nonfinite=True))
        if not norm:
            raise ContractError("adapter gradient is zero")
        self.optimizer.step()
        self.scheduler.step()
        self.updates += 1
        self.verify_base()
        changed = sum(int(torch.count_nonzero(p.detach() != before[n])) for n, p in self.weights().items())
        delta = math.sqrt(sum(float(((p.detach() - before[n]) ** 2).sum()) for n, p in self.weights().items()))
        if not changed or not delta:
            raise ContractError("adapter parameters did not actually update")
        return {"role": self.config.role, "optimizer_step": self.updates, "loss": float(loss.detach()),
                "gradient_norm_before_clip": norm, "changed_adapter_elements": changed, "adapter_delta_l2": delta,
                "base_sha256_before": self.base_sha256, "base_sha256_after": self.verify_base(),
                "base_parameter_elements_changed": 0, "base_gradients_present": False,
                "trainable_adapter_parameters": sum(p.numel() for p in self.parameters()), "adapter_version": self.version_id()}

    def state(self):
        self.verify_base()
        return {"compatibility": self.compatibility(), "enabled": self.enabled,
                "execution": execution_metadata(self.device), "device_rng": capture_device_rng(self.device),
                "weights": {n: p.detach().clone() for n, p in self.weights().items()},
                "weights_sha256": tensor_digest(self.weights()), "optimizer": self.optimizer.state_dict(),
                "scheduler": self.scheduler.state_dict(), "rng": self.rng.get_state(), "updates": self.updates}

    def save(self, path):
        path = Path(path)
        if path.exists() or path.is_symlink():
            raise ContractError("adapter artifact exists; no overwrite")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            torch.save(self.state(), output)
        return {"artifact_bytes": path.stat().st_size, "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "base_sha256": self.base_sha256, "adapter_version": self.version_id(), "updates": self.updates,
                "contains_base_weights": False}

    @classmethod
    def restore(cls, model, state, expected_compatibility):
        fields(state, {"compatibility", "enabled", "weights", "weights_sha256", "optimizer", "scheduler", "rng", "updates"}, {"execution", "device_rng"})
        if state["compatibility"] != expected_compatibility or type(state["enabled"]) is not bool:
            raise ContractError("adapter role/base/version/context/targets differ")
        meta = fields(state["compatibility"], {"schema_version", "kind", "config", "binding", "base_sha256", "target_shapes"}, {"execution"})
        integer(meta["schema_version"], "adapter schema", 1, 1)
        device = checkpoint_execution(state, model_device(model))
        expected_kind = "lora-linear-cpu-v1" if device.type == "cpu" else "lora-linear-device-v2"
        if (meta["kind"] != expected_kind or (device.type == "cuda" and meta.get("execution") != execution_metadata(device))
                or parameter_digest(model) != meta["base_sha256"]):
            raise ContractError("adapter requires its exact unmodified base")
        cfg = AdapterConfig.from_dict(meta["config"])
        integer(state["updates"], "adapter restored updates", 0, cfg.max_updates)
        if not isinstance(state["weights"], dict) or tensor_digest(state["weights"]) != state["weights_sha256"]:
            raise ContractError("adapter weights checksum differs")
        session = cls(model, cfg, meta["binding"])
        try:
            if session.compatibility() != expected_compatibility or set(session.weights()) != set(state["weights"]):
                raise ContractError("adapter target schema differs")
            for name, p in session.weights().items():
                saved = state["weights"][name]
                if not isinstance(saved, torch.Tensor) or saved.dtype != p.dtype or saved.shape != p.shape or not torch.isfinite(saved).all():
                    raise ContractError("adapter tensor shape/type/finite check failed")
            for name, p in session.weights().items():
                p.data.copy_(state["weights"][name])
            session.optimizer.load_state_dict(state["optimizer"])
            optimizer_to(session.optimizer, session.device)
            session.scheduler.load_state_dict(state["scheduler"])
            session.rng.set_state(state["rng"])
            session.updates = state["updates"]
            session.set_enabled(state["enabled"])
            if "device_rng" in state: restore_device_rng(state["device_rng"], session.device)
        except Exception:
            session.unload()
            raise
        return session

    @classmethod
    def load(cls, model, path, expected_compatibility, receipt):
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise ContractError("adapter artifact unavailable")
        data = path.read_bytes()
        if len(data) != receipt["artifact_bytes"] or hashlib.sha256(data).hexdigest() != receipt["artifact_sha256"]:
            raise ContractError("adapter artifact length/checksum differs")
        return cls.restore(model, torch.load(path, map_location="cpu", weights_only=True), expected_compatibility)
