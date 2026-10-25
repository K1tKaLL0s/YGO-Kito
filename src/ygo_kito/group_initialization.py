"""Explicit group weight initialization across tasks/periods, never resume.

Only the four model parameter sets are transferred. Optimizers, RNG, episodes,
data/index/ledger state and run cursors belong to the fresh target. Source files
are pinned, read with weights_only, and never rewritten or executed.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import date
import hashlib
import io
import pickle
from pathlib import Path
import re

import torch
from torch.nn.utils import parametrize

from .build_contracts import BuildTask, digest
from .build_model import FEATURE_VERSION as BUILD_FEATURES
from .coordinator_model import FEATURE_VERSION as COORD_FEATURES, CoordinatorModelConfig, CoordinatorTrainer
from .duel_model import FEATURE_VERSION as DUEL_FEATURES, parameter_digest
from .lora import AdapterConfig, tensor_digest
from .validation import ContractError, canonical_json, fields, integer, member, text

ROLES = ("build_goal", "build_optimizer", "duel", "coordinator")
PHASES = ("build_goal", "build_optimizer", "duel_train", "coordinator_train", "evaluate", "feedback")
FEATURES = {"build_goal": BUILD_FEATURES, "build_optimizer": BUILD_FEATURES,
            "duel": DUEL_FEATURES, "coordinator": COORD_FEATURES}


def _sha(value, label):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ContractError(label + " requires a lowercase SHA256")


def validate_initialization_spec(value):
    d = fields(value, {"path", "sha256", "weights", "source_binding_sha256"})
    text(d["path"], "source group checkpoint path")
    _sha(d["sha256"], "source group checkpoint")
    _sha(d["source_binding_sha256"], "source group binding")
    member(d["weights"], "explicit inherited weight selection", ("effective", "base"))
    return deepcopy(d)


def _execution(state):
    if ("execution" in state) != ("device_rng" in state):
        raise ContractError("source execution metadata/RNG envelope differs")
    value = state.get("execution", {"schema_version": 1, "device": "cpu", "dtype": "float32"})
    fields(value, {"schema_version", "device", "dtype"})
    if (type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["dtype"] != "float32"
            or not isinstance(value["device"], str) or re.fullmatch(r"cpu|cuda:[0-9]+", value["device"]) is None):
        raise ContractError("source execution schema/dtype differs")
    return value


def _context(value, environment):
    if value is None:
        return None
    fields(value, {"period_id", "release_cutoff", "catalog_sha256", "release_manifest_sha256", "banlist_sha256", "banlist_section"})
    text(value["period_id"], "source/target period ID"); text(value["banlist_section"], "period banlist section")
    try:
        if date.fromisoformat(value["release_cutoff"]).isoformat() != value["release_cutoff"]:
            raise ValueError("noncanonical date")
    except (TypeError, ValueError) as error:
        raise ContractError("period initialization context requires an explicit ISO cutoff") from error
    for key in ("catalog_sha256", "release_manifest_sha256", "banlist_sha256"):
        _sha(value[key], "period " + key)
    versions = environment["versions"]
    if (environment.get("release_cutoff") != value["release_cutoff"]
            or versions["cards"] != value["catalog_sha256"]
            or versions["banlist"] != value["banlist_section"] + ":" + value["banlist_sha256"]):
        raise ContractError("period initialization context differs from its actual task environment")
    return deepcopy(value)


def _fresh_targets(builder, duel, coordinator):
    from .build_training import BuildTrainer
    from .cpu_training import CpuTrainer
    if not isinstance(builder, BuildTrainer) or not isinstance(duel, CpuTrainer) or not isinstance(coordinator, CoordinatorTrainer):
        raise ContractError("existing typed group trainers required")
    builder.encoder.assets.check_task(builder.task)
    expected_tags = tuple(sorted({canonical_json(a) for a in builder.task.annotations}))
    if (builder.encoder.card_ids != builder.task.pool or builder.encoder.tags != expected_tags
            or builder.encoder.card_index != {code: i + 1 for i, code in enumerate(builder.task.pool)}
            or builder.encoder.tag_index != {tag: i + 1 for i, tag in enumerate(expected_tags)}
            or builder.encoder.vocabulary_sha256 != digest({"cards": builder.encoder.card_ids, "annotations": expected_tags})
            or duel.encoder.index != {code: i + 1 for i, code in enumerate(duel.encoder.card_ids)}
            or duel.encoder.vocab_sha256 != digest(list(duel.encoder.card_ids))):
        raise ContractError("fresh target encoder identity mapping differs from its task/vocabulary")
    if (builder.batch_cursor or any(builder.updates.values()) or duel.updates or duel.episode_cursor
            or coordinator.updates or getattr(duel, "_pending_episode_digest", None) is not None):
        raise ContractError("group initialization requires fresh target trainer cursors")
    models = dict(builder.models, duel=duel.model, coordinator=coordinator.model)
    optimizers = dict(builder.optimizers, duel=duel.optimizer, coordinator=coordinator.optimizer)
    schedulers = dict(builder.schedulers, duel=duel.scheduler, coordinator=coordinator.scheduler)
    if set(models) != set(ROLES) or set(optimizers) != set(ROLES):
        raise ContractError("all four independent target roles required")
    if len({next(model.parameters()).device for model in models.values()}) != 1:
        raise ContractError("fresh target group roles require one execution device")
    occupied = set()
    for role in ROLES:
        parameters = list(models[role].parameters())
        pointers = {p.data_ptr() for p in parameters}
        assigned = [p for group in optimizers[role].param_groups for p in group["params"]]
        if (occupied & pointers or len(assigned) != len(parameters) or {id(p) for p in assigned} != {id(p) for p in parameters}
                or optimizers[role].state or schedulers[role].last_epoch != 0
                or any(p.grad is not None or not p.requires_grad for p in parameters)
                or any(parametrize.is_parametrized(m) for m in models[role].modules())):
            raise ContractError("fresh independent target models/optimizers without adapters required")
        occupied.update(pointers)
    return models


def _tensors(saved, template, *, remappable):
    if not isinstance(saved, dict) or set(saved) != set(template):
        raise ContractError("source role parameter names differ")
    for name, tensor in saved.items():
        if (not isinstance(tensor, torch.Tensor) or tensor.dtype != template[name].dtype
                or tensor.dtype != torch.float32 or tensor.layout != torch.strided or not torch.isfinite(tensor).all()
                or (name not in remappable and tensor.shape != template[name].shape)):
            raise ContractError("source role parameter shape/dtype/finite check failed")


def _materialize(role, model, base, adapter, source, *, selection):
    fields(adapter, {"compatibility", "enabled", "weights", "weights_sha256", "optimizer", "scheduler", "rng", "updates"},
           {"execution", "device_rng"})
    meta = fields(adapter["compatibility"], {"schema_version", "kind", "config", "binding", "base_sha256", "target_shapes"}, {"execution"})
    cfg = AdapterConfig.from_dict(meta["config"])
    execution = _execution(adapter)
    expected_kind = "lora-linear-cpu-v1" if execution["device"] == "cpu" else "lora-linear-device-v2"
    binding = fields(meta["binding"], {"base_version", "feature_version", "context_sha256"})
    from .agent_registry import identifier
    identifier(binding["base_version"])
    if (type(meta["schema_version"]) is not int or meta["schema_version"] != 1 or meta["kind"] != expected_kind
            or (execution["device"] != "cpu" and meta.get("execution") != execution)
            or execution != _execution(source) or cfg.role != role or adapter["enabled"] is not True
            or binding["feature_version"] != FEATURES[role] or meta["base_sha256"] != tensor_digest(base)
            or binding["context_sha256"] != digest({"runner": source["binding"], "supervision": source["data"]["supervision_sha256"]})):
        raise ContractError("source adapter role/base/features/context/execution differs")
    integer(adapter["updates"], "completed source adapter updates", source["cursor"]["cycle"], source["cursor"]["cycle"])
    if adapter["updates"] > cfg.max_updates:
        raise ContractError("source adapter cursor exceeds its declared budget")
    weights = adapter["weights"]
    names = {name + suffix for name in cfg.targets for suffix in (".a", ".b")}
    if not isinstance(weights, dict) or set(weights) != names or tensor_digest(weights) != adapter["weights_sha256"]:
        raise ContractError("source adapter weight names/checksum differ")
    fields(meta["target_shapes"], set(cfg.targets))
    result = {name: tensor.clone() for name, tensor in base.items()}
    for name in cfg.targets:
        key = name + ".weight"
        try:
            layer = model.get_submodule(name)
        except AttributeError as error:
            raise ContractError("source adapter target module differs") from error
        if (not isinstance(layer, torch.nn.Linear) or key not in base or base[key].ndim != 2
                or meta["target_shapes"][name] != list(base[key].shape)):
            raise ContractError("source adapter target layout differs")
        a, b = weights[name + ".a"], weights[name + ".b"]
        if (cfg.rank > min(base[key].shape) or not isinstance(a, torch.Tensor) or not isinstance(b, torch.Tensor)
                or a.dtype != base[key].dtype or b.dtype != base[key].dtype
                or a.shape != (cfg.rank, base[key].shape[1]) or b.shape != (base[key].shape[0], cfg.rank)
                or not torch.isfinite(a).all() or not torch.isfinite(b).all()):
            raise ContractError("source adapter matrix shape/dtype/finite check failed")
        if selection == "effective":
            result[key] = base[key] + (b @ a) * (cfg.alpha / cfg.rank)
            if not torch.isfinite(result[key]).all():
                raise ContractError("materialized source adapter is nonfinite")
    return result


def _remap(matrix, target, source_ids, target_ids, label):
    if matrix.ndim != 2 or matrix.shape != (len(source_ids) + 1, target.shape[1]):
        raise ContractError("source " + label + " vocabulary shape differs")
    index = {value: i + 1 for i, value in enumerate(source_ids)}
    result = target.detach().cpu().clone()  # Padding and new identities stay fresh.
    copied = 0
    for i, value in enumerate(target_ids, 1):
        if value in index:
            result[i].copy_(matrix[index[value]])
            copied += 1
    return result, {"source_count": len(source_ids), "target_count": len(target_ids), "copied": copied,
                    "new_kept_initialized": len(target_ids) - copied, "source_only_dropped": len(set(source_ids) - set(target_ids)),
                    "padding_kept_initialized": True}


def _initialize_group_weights(builder, duel, coordinator, *, workspace, spec, target_binding=None):
    """Atomically seed fresh existing models; return explicit source→target evidence."""
    spec = validate_initialization_spec(spec)
    models = _fresh_targets(builder, duel, coordinator)
    workspace = Path(workspace).resolve()
    original = workspace / spec["path"]
    path = original.resolve()
    if not path.is_relative_to(workspace) or original.is_symlink() or not path.is_file():
        raise ContractError("source group checkpoint must be a regular file inside workspace")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != spec["sha256"]:
        raise ContractError("source group checkpoint checksum differs")
    try:
        source = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
    except (OSError, EOFError, ValueError, RuntimeError) as error:
        raise ContractError("source group checkpoint cannot be read as weights-only") from error
    fields(source, {"schema_version", "boundary", "binding", "components", "adapters", "cursor", "consumed", "events", "data",
                    "ledger_bytes", "ledger_sha256"},
           {"execution", "device_rng", "data_marks", "evaluations", "deck", "candidate_id", "forecast_id", "last_feedback",
            "ledger_state_sha256", "policy_rng", "budget_snapshot", "global_rng", "construction_state", "data_index_snapshot",
            "initialization", "initialization_provenance"})
    if (type(source["schema_version"]) is not int or source["schema_version"] != 1
            or source["boundary"] != "complete-workflow-stage" or not isinstance(source["binding"], dict)
            or source["binding"].get("workflow") != "four-model-alternating-v1"
            or digest(source["binding"]) != spec["source_binding_sha256"]):
        raise ContractError("source group schema/workflow/provenance binding differs")
    provenance = source["binding"]
    if (provenance.get("feature_version") != DUEL_FEATURES or not isinstance(provenance.get("resources"), dict)
            or not {"cards", "banlist", "scripts", "client_protocol"} <= provenance["resources"].keys()
            or not isinstance(provenance.get("source_commits"), dict) or "core" not in provenance["source_commits"]):
        raise ContractError("source group physical/feature provenance is incomplete")
    for value in provenance["resources"].values(): _sha(value, "source physical resource")
    for value in provenance["source_commits"].values():
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise ContractError("source physical commit requires a full Git identity")
    fields(source["cursor"], {"cycle", "phase", "committed_stages"})
    cycles = integer(source["cursor"]["cycle"], "completed source cycles", 1, 10000)
    markers = ["bootstrap"] + [f"cycle-{i + 1}-{phase}" for i in range(cycles) for phase in PHASES]
    if (source["cursor"]["phase"] != "done" or source["cursor"]["committed_stages"] != len(markers)
            or source["consumed"] != markers or not isinstance(source["events"], list)
            or len(source["events"]) != len(markers)
            or [event.get("event_id") for event in source["events"] if isinstance(event, dict)] != markers):
        raise ContractError("source group must be a completed, consistently committed workflow")
    if (not isinstance(source["ledger_bytes"], bytes)
            or hashlib.sha256(source["ledger_bytes"]).hexdigest() != source["ledger_sha256"]):
        raise ContractError("source group ledger provenance checksum differs")
    if not isinstance(source["data"], dict):
        raise ContractError("completed source group lacks supervision provenance")
    _sha(source["data"].get("supervision_sha256"), "source supervision")
    fields(source["components"], {"build", "duel", "coordinator"}); fields(source["adapters"], set(ROLES))
    build, actor, coord = (source["components"][key] for key in ("build", "duel", "coordinator"))
    fields(build, {"schema_version", "kind", "boundary", "config", "task", "binding", "vocabulary_sha256", "updates", "batch_cursor",
                   "models", "model_hashes", "optimizers", "schedulers", "rng"}, {"execution", "device_rng"})
    fields(actor, {"schema_version", "role", "boundary", "config", "binding", "card_ids", "vocab_sha256", "model", "optimizer",
                   "scheduler", "updates", "episode_cursor", "model_sha256", "rng"}, {"execution", "device_rng"})
    fields(coord, {"config", "feature_version", "model", "optimizer", "scheduler", "batch_rng", "updates", "model_sha256"},
           {"execution", "device_rng"})
    integer(build["schema_version"], "source build schema", 1, 1); integer(actor["schema_version"], "source duel schema", 1, 1)
    integer(build["batch_cursor"], "source build cursor", 1, 1)
    for role, count in fields(build["updates"], {"build_goal", "build_optimizer"}).items():
        integer(count, "source " + role + " base update cursor", 1, 1)
    for count in (actor["updates"], actor["episode_cursor"], coord["updates"]):
        integer(count, "source base warmup cursor", 1, 1)
    task = BuildTask.from_dict(build["task"])
    source_cards, source_tags = tuple(task.pool), tuple(sorted({canonical_json(a) for a in task.annotations}))
    actor_cards = actor["card_ids"]
    if (not isinstance(actor_cards, list) or not 1 <= len(actor_cards) <= 50000 or actor_cards != sorted(set(actor_cards))
            or any(type(code) is not int or not 1 <= code < 2**32 for code in actor_cards)):
        raise ContractError("source duel card identities differ")
    if (build.get("schema_version") != 1 or build.get("kind") != "paired-building-cpu"
            or build.get("boundary") != "complete-role-update-batch" or build.get("batch_cursor") != 1
            or build.get("updates") != {"build_goal": 1, "build_optimizer": 1}
            or actor.get("schema_version") != 1 or actor.get("role") != "duel" or actor.get("boundary") != "complete-episode"
            or actor.get("updates") != 1 or actor.get("episode_cursor") != 1 or coord.get("updates") != 1):
        raise ContractError("source role checkpoint boundaries/cursors differ")
    fields(build["models"], {"build_goal", "build_optimizer"}); fields(build["model_hashes"], {"build_goal", "build_optimizer"})
    if (build["binding"].get("feature_version") != BUILD_FEATURES or actor["binding"].get("feature_version") != DUEL_FEATURES
            or coord.get("feature_version") != COORD_FEATURES or source["binding"].get("task_sha256") != task.sha256
            or build["binding"].get("task_sha256") != task.sha256
            or build["binding"].get("supervision_sha256") != source["data"]["supervision_sha256"]
            or build["vocabulary_sha256"] != digest({"cards": source_cards, "annotations": source_tags})
            or actor["vocab_sha256"] != digest(actor_cards)):
        raise ContractError("source role feature/task/vocabulary binding differs")
    for component in (build, actor):
        if any(component["binding"].get(key) != source["binding"].get(key) for key in ("resources", "source_commits")):
            raise ContractError("source role physical provenance differs from group binding")
    versions = task.environment["versions"]
    if (versions["core"] != provenance["source_commits"]["core"]
            or any(versions[key] != provenance["resources"][resource] for key, resource in
                   (("cards", "cards"), ("scripts", "scripts"), ("protocol", "client_protocol")))):
        raise ContractError("source task physical versions differ from group provenance")
    if (build["config"]["model"] != asdict(builder.config.model) or actor["config"]["model"] != asdict(duel.config.model)
            or CoordinatorModelConfig(**coord["config"]).hidden != coordinator.config.hidden):
        raise ContractError("source model architecture/configuration differs")
    source_context = _context(source["binding"].get("period_context"), task.environment)
    target_context = _context(getattr(builder.encoder.assets, "period_context", None), builder.task.environment)
    if target_binding is not None:
        if (not isinstance(target_binding, dict) or target_binding.get("task_sha256") != builder.task.sha256
                or target_binding.get("period_context") != target_context
                or any(target_binding.get(key) != builder.encoder.assets.receipt.get(key) for key in ("resources", "source_commits"))):
            raise ContractError("target group initialization binding differs from the fresh task/assets")
    target_binding_sha256 = digest(target_binding) if target_binding is not None else None
    if _execution(source) != _execution(build) or _execution(source) != _execution(actor) or _execution(source) != _execution(coord):
        raise ContractError("source group/component execution metadata differs")
    bases = dict(build["models"], duel=actor["model"], coordinator=coord["model"])
    hashes = dict(build["model_hashes"], duel=actor["model_sha256"], coordinator=coord["model_sha256"])
    planned, evidence = {}, {}
    for role in ROLES:
        template = models[role].state_dict()
        remappable = {"card.weight", "annotation.weight"} if role.startswith("build_") else {"card.weight"} if role == "duel" else set()
        _tensors(bases[role], template, remappable=remappable)
        if tensor_digest(bases[role]) != hashes[role]:
            raise ContractError("source role model checksum differs")
        effective = _materialize(role, models[role], bases[role], source["adapters"][role], source, selection=spec["weights"])
        mapping = {}
        if role != "coordinator":
            old_ids, new_ids = (source_cards, builder.encoder.card_ids) if role.startswith("build_") else (actor_cards, duel.encoder.card_ids)
            effective["card.weight"], mapping["cards"] = _remap(effective["card.weight"], template["card.weight"], old_ids, new_ids, "card")
        if role.startswith("build_"):
            effective["annotation.weight"], mapping["annotations"] = _remap(effective["annotation.weight"], template["annotation.weight"], source_tags, builder.encoder.tags, "annotation")
        planned[role] = effective
        evidence[role] = {"feature_version": FEATURES[role], "source_base_sha256": hashes[role],
                          "source_adapter_sha256": source["adapters"][role]["weights_sha256"],
                          "target_before_sha256": parameter_digest(models[role]), "target_after_sha256": tensor_digest(effective),
                          "vocabulary_mapping": mapping}
    backups = {role: deepcopy(model.state_dict()) for role, model in models.items()}
    try:
        for role in ROLES:
            models[role].load_state_dict(planned[role], strict=True)
    except (RuntimeError, ValueError, TypeError) as error:
        for role in ROLES: models[role].load_state_dict(backups[role], strict=True)
        raise ContractError("group weight initialization failed; all target parameters restored") from error
    return {"schema_version": 1, "kind": "explicit-group-weight-initialization-not-resume", "weights": spec["weights"],
            "source_checkpoint": str(path.relative_to(workspace)), "source_artifact_sha256": spec["sha256"],
            "source_binding_sha256": spec["source_binding_sha256"], "source_binding": deepcopy(source["binding"]),
            "source_period_context": source_context, "source_cursor": deepcopy(source["cursor"]),
            "source_task_sha256": task.sha256, "target_task_sha256": builder.task.sha256,
            "target_binding_sha256": target_binding_sha256,
            "target_period_context": target_context, "roles": evidence,
            "source_execution": deepcopy(_execution(source)),
            "target_execution": {"schema_version": 1, "device": str(next(duel.model.parameters()).device), "dtype": "float32"},
            "materialization": "cpu-fp32-base-plus-saved-lora" if spec["weights"] == "effective" else "explicit-base-only",
            "optimizer_state_inherited": False, "rng_state_inherited": False, "data_or_ledger_inherited": False,
            "historical_training_verified": False, "ability_verified": False}


def initialize_group_weights(builder, duel, coordinator, *, workspace, spec, target_binding=None):
    """Validate a pinned completed group, then atomically initialize four models."""
    try:
        return _initialize_group_weights(builder, duel, coordinator, workspace=workspace, spec=spec, target_binding=target_binding)
    except ContractError:
        raise
    except (OSError, KeyError, TypeError, IndexError, ValueError, OverflowError, pickle.UnpicklingError) as error:
        raise ContractError("source group initialization artifact/schema is invalid") from error
