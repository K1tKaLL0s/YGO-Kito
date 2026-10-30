"""Self-contained four-role course models and checkpoints, separate from GroupState.

Existing trainers, explicit inherited weights, course vocabulary and actual
LoRA sessions are reused. Restoring a course never rereads the initialization
artifact or relaxes the old group workflow/cursor gates.
"""
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict
import math
import random

import torch

from .autonomous_construction import AutonomousConstructionKernel, initialize_course_vocabulary
from .build_contracts import BuildTask, digest
from .build_model import FEATURE_VERSION as BUILD_FEATURES
from .build_training import BuildTrainer, BuildTrainingConfig, config_from_dict as build_config_from_dict
from .coordinator_model import (CoordinatorTrainer, CoordinatorModelConfig, FEATURE_VERSION as COORD_FEATURES,
                                MECHANISM_FEATURE_VERSION as COORD_MECHANISM_FEATURES)
from .course_game_adapter import course_config_from_dict
from .cpu_training import CpuTrainer, CpuTrainingConfig
from .device import (resolve_device, execution_metadata, checkpoint_execution, capture_device_rng,
                     restore_device_rng, optimizer_to)
from .duel_model import FEATURE_VERSION as DUEL_FEATURES, parameter_digest
from .group_initialization import initialize_group_weights
from .group_runner import tree_digest
from .lora import AdapterConfig, AdapterSession, tensor_digest
from .validation import ContractError, fields, integer

ROLES = ("build_goal", "build_optimizer", "duel", "coordinator")
FEATURES = {"build_goal": BUILD_FEATURES, "build_optimizer": BUILD_FEATURES, "duel": DUEL_FEATURES, "coordinator": COORD_FEATURES}


def _configs(value):
    rows = list(value.values()) if isinstance(value, dict) else value
    if not isinstance(rows, (list, tuple)):
        raise ContractError("four explicit role adapter configurations required")
    result = {}
    for row in rows:
        cfg = row if isinstance(row, AdapterConfig) else AdapterConfig.from_dict(row)
        if cfg.role in result: raise ContractError("duplicate course adapter role")
        result[cfg.role] = cfg
    if set(result) != set(ROLES) or (isinstance(value, dict) and (set(value) != set(ROLES) or any(
            (v.role if isinstance(v, AdapterConfig) else v.get("role")) != k for k, v in value.items()))):
        raise ContractError("all four exact course role adapters required")
    return result


def _finite(value):
    if isinstance(value, torch.Tensor):
        if value.layout != torch.strided or not torch.isfinite(value).all(): raise ContractError("nonfinite course tensor")
    elif isinstance(value, dict):
        for item in value.values(): _finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value: _finite(item)
    elif type(value) is float and not math.isfinite(value): raise ContractError("nonfinite course scalar")


def _asset_identity(task, assets, cards):
    assets.check_task(task)
    return {"resources": deepcopy(assets.receipt), "environment": deepcopy(task.environment),
        "period_context": deepcopy(getattr(assets, "period_context", None)), "limits": dict(assets.limits),
        "catalog_sha256": digest({c: assets.rows[c] for c in cards})}


def _check_optimizer(optimizer):
    for parameter, state in optimizer.state.items():
        for key, value in state.items():
            if isinstance(value, torch.Tensor) and key != "step" and (value.shape != parameter.shape or value.dtype != parameter.dtype):
                raise ContractError("course optimizer moments differ from actual parameters")
            if key == "step" and (not isinstance(value, torch.Tensor) or value.ndim != 0 or float(value) < 0):
                raise ContractError("course optimizer step differs")


class CourseModels:
    @classmethod
    def initialize(cls, task, assets, duel_config, adapter_configs, workspace, initialization,
                   available_ids, source_binding, device="cpu"):
        if not isinstance(task, BuildTask) or not isinstance(duel_config, CpuTrainingConfig):
            raise ContractError("typed task and actual duel configuration required")
        if not isinstance(source_binding, dict) or not source_binding: raise ContractError("explicit course source binding required")
        obj = cls()
        obj.binding = deepcopy(source_binding); obj._binding_sha256 = digest(obj.binding)
        obj.learning_stage = obj.binding.get("learning_stage", "lora_adaptation")
        if obj.learning_stage not in ("base", "lora_adaptation"): raise ContractError("explicit supported learning stage required")
        mechanisms = obj.binding.get("coordinator_mechanism_inputs", False)
        if type(mechanisms) is not bool:
            raise ContractError("explicit boolean coordinator mechanism input policy required")
        if mechanisms and (obj.learning_stage != "base" or initialization is not None):
            raise ContractError("new mechanism coordinator requires fresh base initialization; existing weights need explicit migration")
        obj.device = resolve_device(device); obj.adapter_configs = _configs(adapter_configs)
        obj.available_ids = tuple(sorted(set(available_ids)))
        obj.builder = BuildTrainer(task, assets, BuildTrainingConfig(batches=100000) if obj.learning_stage == "base" else BuildTrainingConfig(), device=obj.device)
        obj.duel = CpuTrainer(duel_config, sorted(c for c in assets.rows if 0 < c < 2**32), device=obj.device)
        obj.coordinator = CoordinatorTrainer(CoordinatorModelConfig(
            steps=100000 if obj.learning_stage == "base" else 2, mechanism_inputs=mechanisms), device=obj.device)
        target = {"task_sha256": task.sha256, **deepcopy(assets.receipt),
                  "period_context": deepcopy(getattr(assets, "period_context", None))}
        obj.initialization_provenance = (initialize_group_weights(obj.builder, obj.duel, obj.coordinator,
            workspace=workspace, spec=initialization, target_binding=target) if initialization is not None else
            {"kind": "explicit-fresh-untrained-course-models", "ability_verified": False,
             "source_checkpoint": None, "optimizer_state_inherited": False})
        if mechanisms:
            obj.initialization_provenance["coordinator_mechanisms"] = {
                "feature_version": COORD_MECHANISM_FEATURES, "new_untrained_parameters": ["mechanism_projection.weight"],
                "initialization": "zero", "ability_verified": False}
        obj.vocabulary_migration = initialize_course_vocabulary(obj.builder, obj.available_ids)
        obj._assets_identity = _asset_identity(task, assets, obj.duel.encoder.card_ids)
        obj.policy_rng = torch.Generator(device="cpu").manual_seed(duel_config.policy_seed)
        obj.sessions = ({role: AdapterSession(model, obj.adapter_configs[role], obj._adapter_binding(role))
                        for role, model in obj.models().items()} if obj.learning_stage == "lora_adaptation" else {})
        if obj.learning_stage == "base":
            for model in obj.models().values(): model.requires_grad_(True)
        obj.kernel = AutonomousConstructionKernel(obj.builder, obj.coordinator, assets=assets,
            host_available_ids=obj.available_ids, source_binding=obj.binding,
            allowed_theme_ids=obj.binding.get("construction_theme_ids"))
        return obj

    def models(self): return dict(self.builder.models, duel=self.duel.model, coordinator=self.coordinator.model)

    def versions(self): return {r: parameter_digest(m) for r, m in self.models().items()}

    def _adapter_binding(self, role):
        feature = (COORD_MECHANISM_FEATURES if role == "coordinator" and self.coordinator.config.mechanism_inputs
                   else FEATURES[role])
        return {"base_version": "course-base", "feature_version": feature,
                "context_sha256": digest({"source_binding": self.binding, "task": self.builder.task.sha256,
                    "encoder": self.builder.encoder.binding(), "initialization": self.initialization_provenance})}

    def _check(self):
        if digest(self.binding) != self._binding_sha256: raise ContractError("course model host binding changed")
        mechanisms = self.binding.get("coordinator_mechanism_inputs", False)
        if type(mechanisms) is not bool or mechanisms != self.coordinator.config.mechanism_inputs:
            raise ContractError("course coordinator architecture/input binding differs")
        if mechanisms and self.learning_stage != "base":
            raise ContractError("v3 course LoRA needs an explicit adapter/loss migration; legacy adapters are not rebound")
        if _asset_identity(self.builder.task, self.builder.encoder.assets, self.duel.encoder.card_ids) != self._assets_identity:
            raise ContractError("course model assets/task changed")
        self.builder.encoder.assert_binding(); self.kernel._check()
        expected = set(ROLES) if self.learning_stage == "lora_adaptation" else set()
        if self.learning_stage != self.binding.get("learning_stage", "lora_adaptation") or set(self.sessions) != expected:
            raise ContractError("course learning stage/adapter identities differ")
        if self.learning_stage == "base" and any(not p.requires_grad for m in self.models().values() for p in m.parameters()):
            raise ContractError("base learning parameters must remain trainable")
        for role, session in self.sessions.items():
            model = self.models()[role]
            if session.model is not model or session.detached or not session.enabled or session.config != self.adapter_configs[role]:
                raise ContractError("course role/adapter identity changed")
            session.verify_base()

    def rng_state(self):
        return deepcopy({"device_rng": capture_device_rng(self.device), "python": random.getstate(),
            "policy": self.policy_rng.get_state(), "build_batch": self.builder.batch_rng.get_state(),
            "duel_policy": self.duel.policy_rng.get_state(), "duel_batch": self.duel.batch_rng.get_state(),
            "coordinator_batch": self.coordinator.batch_rng.get_state(),
            "adapter": {r: s.rng.get_state() for r, s in self.sessions.items()},
            "modes": {r: {n: m.training for n, m in model.named_modules()} for r, model in self.models().items()}})

    def restore_rng(self, state):
        fields(state, {"device_rng", "python", "policy", "build_batch", "duel_policy", "duel_batch", "coordinator_batch", "adapter", "modes"})
        fields(state["adapter"], set(self.sessions)); fields(state["modes"], set(ROLES))
        generators = {"policy": self.policy_rng, "build_batch": self.builder.batch_rng,
            "duel_policy": self.duel.policy_rng, "duel_batch": self.duel.batch_rng, "coordinator_batch": self.coordinator.batch_rng}
        for key in generators:
            try: torch.Generator(device="cpu").set_state(state[key])
            except (RuntimeError, TypeError) as error: raise ContractError("course owned RNG differs") from error
        for role in self.sessions:
            try: torch.Generator(device="cpu").set_state(state["adapter"][role])
            except (RuntimeError, TypeError) as error: raise ContractError("course adapter RNG differs") from error
        for role in ROLES:
            expected = dict(self.models()[role].named_modules())
            if set(state["modes"][role]) != set(expected) or any(type(v) is not bool for v in state["modes"][role].values()):
                raise ContractError("course model mode schema differs")
        try: random.Random().setstate(state["python"])
        except (TypeError, ValueError) as error: raise ContractError("course Python RNG differs") from error
        previous = self.rng_state()
        def apply(value):
            for key, generator in generators.items(): generator.set_state(value[key])
            for role, session in self.sessions.items(): session.rng.set_state(value["adapter"][role])
            for role, model in self.models().items():
                for name, module in model.named_modules(): module.training = value["modes"][role][name]
            restore_device_rng(value["device_rng"], self.device); random.setstate(value["python"])
        try: apply(state)
        except Exception:
            apply(previous)
            raise

    def save_state(self):
        self._check(); rng = self.rng_state()
        try:
            with ExitStack() as stack:
                for session in self.sessions.values(): stack.enter_context(session.suspended())
                components = {"models": {r: deepcopy(m.state_dict()) for r, m in self.models().items()},
                    "model_hashes": self.versions(),
                    "build_optimizers": {r: deepcopy(o.state_dict()) for r, o in self.builder.optimizers.items()},
                    "build_schedulers": {r: deepcopy(s.state_dict()) for r, s in self.builder.schedulers.items()},
                    "duel_optimizer": deepcopy(self.duel.optimizer.state_dict()), "duel_scheduler": deepcopy(self.duel.scheduler.state_dict()),
                    "coordinator_optimizer": deepcopy(self.coordinator.optimizer.state_dict()),
                    "coordinator_scheduler": deepcopy(self.coordinator.scheduler.state_dict())}
        finally: self.restore_rng(rng)
        body = {"schema_version": 1, "kind": "course-four-role-full-state-v1", "binding": deepcopy(self.binding),
            "binding_sha256": self._binding_sha256, "execution": execution_metadata(self.device),
            "device_rng": capture_device_rng(self.device), "task": self.builder.task.to_dict(),
            "configs": {"build": asdict(self.builder.config), "duel": asdict(self.duel.config), "coordinator": asdict(self.coordinator.config),
                        "adapters": {r: c.to_dict() for r, c in self.adapter_configs.items()}},
            "vocabulary": {"build": self.builder.encoder.binding(), "duel": list(self.duel.encoder.card_ids),
                           "duel_sha256": self.duel.encoder.vocab_sha256, "migration": deepcopy(self.vocabulary_migration)},
            "available_ids": list(self.available_ids), "assets_identity": deepcopy(self._assets_identity),
            "initialization_provenance": deepcopy(self.initialization_provenance), "components": components,
            "adapters": {r: s.state() for r, s in self.sessions.items()}, "effective_hashes": self.versions(),
            "cursors": {"build_updates": dict(self.builder.updates), "build_batch": self.builder.batch_cursor,
                        "duel_updates": self.duel.updates, "duel_episodes": self.duel.episode_cursor,
                        "coordinator_updates": self.coordinator.updates},
            "duel_pending_episode_digest": getattr(self.duel, "_pending_episode_digest", None),
            "rng": rng, "kernel": self.kernel.state_dict()}
        _finite(body)
        return deepcopy(dict(body, state_sha256=tree_digest(body)))

    def fingerprint(self): return self.save_state()["state_sha256"]

    @classmethod
    def _candidate(cls, state, assets, expected_binding):
        required = {"schema_version", "kind", "binding", "binding_sha256", "execution", "device_rng", "task", "configs",
            "vocabulary", "available_ids", "assets_identity", "initialization_provenance", "components", "adapters",
            "effective_hashes", "cursors", "duel_pending_episode_digest", "rng", "kernel", "state_sha256"}
        fields(state, required); _finite(state)
        body = {k: v for k, v in state.items() if k != "state_sha256"}
        if (type(state["schema_version"]) is not int or state["schema_version"] != 1 or state["kind"] != "course-four-role-full-state-v1"
                or state["binding"] != expected_binding or state["binding_sha256"] != digest(expected_binding)
                or state["state_sha256"] != tree_digest(body)):
            raise ContractError("course model checkpoint hash/binding/kind differs")
        device = checkpoint_execution(state)
        if tree_digest(state["device_rng"]) != tree_digest(state["rng"]["device_rng"]):
            raise ContractError("course duplicate device RNG envelopes differ")
        task = BuildTask.from_dict(state["task"])
        fields(state["configs"], {"build", "duel", "coordinator", "adapters"})
        fields(state["vocabulary"], {"build", "duel", "duel_sha256", "migration"})
        obj = cls(); obj.device = device
        obj.binding = deepcopy(expected_binding); obj._binding_sha256 = digest(obj.binding)
        obj.learning_stage = obj.binding.get("learning_stage", "lora_adaptation")
        if obj.learning_stage not in ("base", "lora_adaptation"): raise ContractError("unsupported checkpoint learning stage")
        obj.available_ids = tuple(state["available_ids"]); obj.adapter_configs = _configs(state["configs"]["adapters"])
        obj.initialization_provenance = deepcopy(state["initialization_provenance"])
        obj.builder = BuildTrainer(task, assets, build_config_from_dict(state["configs"]["build"]), device=device)
        obj.duel = CpuTrainer(course_config_from_dict(state["configs"]["duel"]), state["vocabulary"]["duel"], device=device)
        obj.coordinator = CoordinatorTrainer(CoordinatorModelConfig(**state["configs"]["coordinator"]), device=device)
        seed = state["vocabulary"]["migration"]["initialization_seed"]
        obj.vocabulary_migration = initialize_course_vocabulary(obj.builder, obj.available_ids, seed=seed)
        if (obj.vocabulary_migration != state["vocabulary"]["migration"] or obj.builder.encoder.binding() != state["vocabulary"]["build"]
                or obj.duel.encoder.vocab_sha256 != state["vocabulary"]["duel_sha256"]):
            raise ContractError("course exact vocabulary/migration differs")
        obj._assets_identity = _asset_identity(task, assets, obj.duel.encoder.card_ids)
        if obj._assets_identity != state["assets_identity"]: raise ContractError("course physical/catalog/task binding differs")
        components = fields(state["components"], {"models", "model_hashes", "build_optimizers", "build_schedulers", "duel_optimizer",
            "duel_scheduler", "coordinator_optimizer", "coordinator_scheduler"})
        fields(components["models"], set(ROLES)); fields(components["model_hashes"], set(ROLES))
        for role, model in obj.models().items():
            saved = components["models"][role]; template = model.state_dict()
            if set(saved) != set(template) or any(not isinstance(t, torch.Tensor) or t.dtype != template[k].dtype or
                    t.shape != template[k].shape for k, t in saved.items()) or tensor_digest(saved) != components["model_hashes"][role]:
                raise ContractError("course base tensor shape/dtype/checksum differs")
            model.load_state_dict(saved, strict=True)
        fields(components["build_optimizers"], {"build_goal", "build_optimizer"})
        fields(components["build_schedulers"], {"build_goal", "build_optimizer"})
        optimizers = dict(obj.builder.optimizers, duel=obj.duel.optimizer, coordinator=obj.coordinator.optimizer)
        schedulers = dict(obj.builder.schedulers, duel=obj.duel.scheduler, coordinator=obj.coordinator.scheduler)
        for role in ROLES:
            opt = components["build_optimizers"][role] if role.startswith("build_") else components[role+"_optimizer"]
            scheduler = components["build_schedulers"][role] if role.startswith("build_") else components[role+"_scheduler"]
            optimizers[role].load_state_dict(opt); optimizer_to(optimizers[role], device); _check_optimizer(optimizers[role])
            schedulers[role].load_state_dict(scheduler)
        cursors = fields(state["cursors"], {"build_updates", "build_batch", "duel_updates", "duel_episodes", "coordinator_updates"})
        fields(cursors["build_updates"], {"build_goal", "build_optimizer"})
        for r in obj.builder.models: integer(cursors["build_updates"][r], "base building updates", 0, obj.builder.config.batches)
        integer(cursors["build_batch"], "base build cursor", 0, obj.builder.config.batches)
        integer(cursors["duel_updates"], "base duel updates", 0, len(obj.duel.config.game_seeds))
        integer(cursors["duel_episodes"], "base duel cursor", cursors["duel_updates"], cursors["duel_updates"])
        integer(cursors["coordinator_updates"], "base coordinator updates", 0, obj.coordinator.config.steps)
        obj.builder.updates = dict(cursors["build_updates"]); obj.builder.batch_cursor = cursors["build_batch"]
        obj.duel.updates, obj.duel.episode_cursor = cursors["duel_updates"], cursors["duel_episodes"]
        obj.duel._pending_episode_digest = state["duel_pending_episode_digest"]
        if obj.duel._pending_episode_digest is not None: raise ContractError("course checkpoint cannot contain an unconsumed base PPO episode")
        obj.coordinator.updates = cursors["coordinator_updates"]
        adapter_roles = set(ROLES) if obj.learning_stage == "lora_adaptation" else set()
        fields(state["adapters"], adapter_roles); obj.sessions = {}
        if obj.learning_stage == "base":
            for model in obj.models().values(): model.requires_grad_(True)
        for role in sorted(adapter_roles):
            model = obj.models()[role]
            meta = state["adapters"][role]["compatibility"]
            if (tree_digest(state["adapters"][role]["rng"]) != tree_digest(state["rng"]["adapter"][role]) or
                    tree_digest(state["adapters"][role]["device_rng"]) != tree_digest(state["device_rng"])):
                raise ContractError("course duplicate adapter RNG envelopes differ")
            if meta["config"] != obj.adapter_configs[role].to_dict() or meta["binding"] != obj._adapter_binding(role):
                raise ContractError("course adapter host/config binding differs")
            obj.sessions[role] = AdapterSession.restore(model, state["adapters"][role], meta)
            _check_optimizer(obj.sessions[role].optimizer)
        if obj.versions() != state["effective_hashes"]: raise ContractError("course effective LoRA weights differ")
        obj.policy_rng = torch.Generator(device="cpu")
        obj.kernel = AutonomousConstructionKernel(obj.builder, obj.coordinator, assets=assets,
            host_available_ids=obj.available_ids, source_binding=obj.binding,
            allowed_theme_ids=obj.binding.get("construction_theme_ids"))
        obj.kernel.load_state_dict(state["kernel"])
        obj.restore_rng(state["rng"]); obj._check()
        return obj

    def restore_state(self, state, *, assets, expected_binding):
        """Prevalidate into new objects, then atomically replace this bundle."""
        previous_rng = self.rng_state()
        try:
            if (state.get("execution") != execution_metadata(self.device) or
                    BuildTask.from_dict(state["task"]).sha256 != self.builder.task.sha256):
                raise ContractError("course restore device/base task differs")
            candidate = self._candidate(state, assets, expected_binding)
        except Exception:
            self.restore_rng(previous_rng)
            raise
        self.__dict__.clear(); self.__dict__.update(candidate.__dict__)
        return self

    @classmethod
    def from_state(cls, state, *, assets, expected_binding):
        """Fresh-process recovery with no dependency on the old source artifact."""
        device = checkpoint_execution(state)
        previous = capture_device_rng(device); python = random.getstate()
        try: return cls._candidate(state, assets, expected_binding)
        except Exception:
            restore_device_rng(previous, device); random.setstate(python)
            raise
