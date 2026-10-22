"""Four-role CPU alternation with complete stage transactions and frozen eval.

Base warmup precedes LoRA; construction uses the existing conditional-route /
weak-proxy supervision, and the learned coordinator remains synthetic/advisory.
"""

from contextlib import ExitStack, closing
from dataclasses import asdict, replace
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import tempfile
from uuid import uuid4

from .build_contracts import BuildTask, DeckParts, digest
from .validation import ContractError, canonical_json, fields, integer, read_json

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = "four-model-alternating-v1"
PHASES = ("build_goal", "build_optimizer", "duel_train", "coordinator_train", "evaluate", "feedback")
ROLE_PHASE = {"build_goal": 0, "build_optimizer": 1, "duel": 2, "coordinator": 3}
EXTRA_FIELDS = {"workflow", "task", "adapters", "bootstrap_seed", "stages_per_worker"}


def config_path(value):
    if not isinstance(value, str) or not value.startswith("configs/") or not value.endswith(".json"):
        raise ContractError("group inputs must be repository configs JSON paths")
    path = ROOT / value
    if path.is_symlink() or not path.resolve().is_relative_to(ROOT / "configs"):
        raise ContractError("group input outside repository configs")
    return path


def validate_recipe(value):
    from .training_runner import validate_recipe as validate_duel
    fields(value, {"schema_version", "max_updates", "validate_every", "checkpoint_every", "wall_seconds", "cpu_config",
                   "train", "validation"} | EXTRA_FIELDS)
    if value["workflow"] != WORKFLOW:
        raise ContractError("unsupported group workflow")
    validate_duel({k: v for k, v in value.items() if k not in EXTRA_FIELDS})
    integer(value["max_updates"], "group cycles", 1, 10000)
    integer(value["stages_per_worker"], "worker stage budget", 1, 60001)
    integer(value["validate_every"], "group validation interval", 1, 1)
    integer(value["bootstrap_seed"], "base warmup seed", 0, 2**32 - 8)
    train = value["train"]
    seeds = {train["seed_start"] + i * train["seed_stride"] for i in range(value["max_updates"])}
    if value["bootstrap_seed"] in seeds or value["bootstrap_seed"] in value["validation"]["seeds"]:
        raise ContractError("base warmup, adaptation and validation seeds must be disjoint")
    for key in ("task", "adapters"):
        config_path(value[key])
    if value["cpu_config"].get("actor_seat", 0) != 0:
        raise ContractError("conditional group curriculum currently binds actor seat zero")
    return json.loads(canonical_json(value))


def inputs(recipe):
    from .training_runner import recipe_inputs
    from .lora import AdapterConfig, ROLES
    profiles, config = recipe_inputs({k: v for k, v in recipe.items() if k not in EXTRA_FIELDS})
    task = BuildTask.from_dict(read_json(config_path(recipe["task"])))
    lora = read_json(config_path(recipe["adapters"]))
    fields(lora, {"schema_version", "base_version", "calibration", "scope", "adapters"})
    if lora["schema_version"] != 1 or lora["calibration"] != "pending" or lora["scope"] != "structural-engineering-not-transfer-ability":
        raise ContractError("group adapters must remain explicit engineering/pending")
    configs = [replace(AdapterConfig.from_dict(c), max_updates=recipe["max_updates"]) for c in lora["adapters"]]
    if len(configs) != 4 or {c.role for c in configs} != set(ROLES) or len({c.adapter_id for c in configs}) != 4:
        raise ContractError("four independent role adapters required")
    return profiles, config, task, lora, {c.role: c for c in configs}


def binding_for(root, row):
    from .cpu_training import resource_binding
    recipe = validate_recipe(row["recipe"])
    profiles, cfg, task, lora, _ = inputs(recipe)
    if (profiles["train"] != row["profile"] or profiles["validation"] != row["validation_profile"]
            or digest(asdict(cfg)) != digest(row["config"]) or task.to_dict() != row["task"]):
        raise ContractError("group recipe/task/profile changed")
    return dict(resource_binding(Path(root), profiles["train"]), workflow=WORKFLOW, runner_recipe_sha256=digest(recipe),
                validation_profile_sha256=digest(profiles["validation"]), task_sha256=task.sha256,
                adapters_config_sha256=digest(lora), feedback_policy_sha256=digest(row["feedback_policy"]))


def tree_digest(value):
    """Stable nested tensor/optimizer/RNG digest; excludes object identities."""
    import torch
    h = hashlib.sha256()
    def visit(v):
        if isinstance(v, torch.Tensor):
            t = v.detach().cpu().contiguous()
            h.update(b"tensor" + str(t.dtype).encode() + str(tuple(t.shape)).encode() + t.numpy().tobytes())
        elif isinstance(v, bytes):
            h.update(b"bytes" + hashlib.sha256(v).digest())
        elif isinstance(v, dict):
            h.update(b"dict")
            for key in sorted(v, key=lambda k: (type(k).__name__, str(k))):
                visit((type(key).__name__, key)); visit(v[key])
        elif isinstance(v, (list, tuple)):
            h.update(type(v).__name__.encode())
            for item in v:
                visit(item)
        else:
            h.update(canonical_json(v).encode() + b"\0")
    visit(value)
    return h.hexdigest()


def without_timing(value):
    if isinstance(value, dict):
        return {k: without_timing(v) for k, v in value.items() if k not in ("elapsed_seconds", "actor_inference_ms")}
    if isinstance(value, (tuple, list)):
        return [without_timing(v) for v in value]
    return value


class GroupState:
    def __init__(self, state_root, row, assets):
        import torch
        from .build_training import BuildTrainer, BuildTrainingConfig
        from .cpu_training import CpuTrainer, config_from_dict
        from .coordinator_model import CoordinatorTrainer
        from .coordinator import Coordinator
        from .coord_contracts import FeedbackPolicy
        from .local_training import run_path
        self.assets, self.row, self.state_root = assets, row, Path(state_root)
        self.task = BuildTask.from_dict(row["task"])
        self.builder = BuildTrainer(self.task, assets, BuildTrainingConfig())
        self.duel = CpuTrainer(config_from_dict(dict(row["recipe"]["cpu_config"], game_seeds=[row["recipe"]["bootstrap_seed"]])),
                               sorted(c for c in assets.rows if 0 < c < 2**32))
        self.coordinator = CoordinatorTrainer()
        self.sessions, self.data = None, None
        self.policy_rng = torch.Generator(device="cpu").manual_seed(self.duel.config.policy_seed + 10)
        self.cycle, self.phase, self.updates = 0, "bootstrap", 0
        self.consumed, self.events, self.data_marks, self.evaluations = [], [], [], []
        self.deck, self.candidate_id, self.forecast_id, self.last_feedback = None, None, None, None
        run = run_path(state_root, row["run_id"])
        run.mkdir(parents=True, exist_ok=True)
        self.host = Coordinator(run / ("working-" + uuid4().hex + ".sqlite3"), FeedbackPolicy.from_dict(row["feedback_policy"]),
                                role="coordinator", source="real_engine", assets=assets, create=True)

    def models(self):
        return dict(self.builder.models, duel=self.duel.model, coordinator=self.coordinator.model)

    def versions(self):
        from .duel_model import parameter_digest
        return {r: parameter_digest(m) for r, m in self.models().items()}

    def expected_adapter(self, role):
        from .build_model import FEATURE_VERSION as build_features
        from .coordinator_model import FEATURE_VERSION as coordinator_features
        from .duel_model import FEATURE_VERSION as duel_features
        from .duel_model import parameter_digest
        _, _, _, lora, configs = inputs(self.row["recipe"])
        features = duel_features if role == "duel" else coordinator_features if role == "coordinator" else build_features
        cfg = configs[role]
        model = self.models()[role]
        return {"schema_version": 1, "kind": "lora-linear-cpu-v1", "config": cfg.to_dict(),
                "binding": {"base_version": lora["base_version"], "feature_version": features,
                            "context_sha256": digest({"runner": self.row["binding"], "supervision": self.data["supervision_sha256"]})},
                "base_sha256": parameter_digest(model),
                "target_shapes": {name: list(model.get_submodule(name).weight.shape) for name in cfg.targets}}

    def attach(self):
        from .lora import AdapterConfig, AdapterSession
        expected = {r: self.expected_adapter(r) for r in self.models()}
        self.sessions = {r: AdapterSession(self.models()[r], AdapterConfig.from_dict(m["config"]), m["binding"]) for r, m in expected.items()}
        if any(self.sessions[r].compatibility() != expected[r] for r in expected):
            raise ContractError("group base/adapter binding differs")

    def cursor(self):
        return {"cycle": self.cycle, "phase": self.phase, "committed_stages": self.updates}

    def event_id(self):
        return "bootstrap" if self.phase == "bootstrap" else f"cycle-{self.cycle + 1}-{self.phase}"

    def advance(self, payload):
        event = self.event_id()
        if event in self.consumed:
            raise ContractError("group stage already consumed")
        self.events.append({"event_id": event, "payload": without_timing(payload)})
        self.consumed.append(event)
        self.updates += 1
        if self.phase == "bootstrap":
            self.phase = PHASES[0]
        elif self.phase == PHASES[-1]:
            self.cycle += 1
            self.phase = "done" if self.cycle == self.row["recipe"]["max_updates"] else PHASES[0]
        else:
            self.phase = PHASES[PHASES.index(self.phase) + 1]

    def validate_cursor(self):
        limit = self.row["recipe"]["max_updates"]
        integer(self.cycle, "group cycle cursor", 0, limit)
        integer(self.updates, "group committed stage cursor", 0, 1 + limit * len(PHASES))
        if self.phase not in (*PHASES, "bootstrap", "done"):
            raise ContractError("group phase unsupported")
        all_ids = ["bootstrap"] + [f"cycle-{c + 1}-{phase}" for c in range(limit) for phase in PHASES]
        position = 0 if self.phase == "bootstrap" else 1 + self.cycle * len(PHASES) + (0 if self.phase == "done" else PHASES.index(self.phase))
        if (self.updates != position or self.consumed != all_ids[:position] or len(self.events) != position
                or [e["event_id"] for e in self.events] != self.consumed or (self.phase == "done") != (self.cycle == limit)):
            raise ContractError("group committed data/stage cursor differs")
        warm = int(position > 0)
        if (self.builder.batch_cursor != warm or any(n != warm for n in self.builder.updates.values())
                or self.duel.updates != warm or self.duel.episode_cursor != warm or self.coordinator.updates != warm):
            raise ContractError("group base warmup cursor differs")
        if not warm:
            if (self.sessions is not None or self.data is not None or self.data_marks or self.evaluations
                    or any(v is not None for v in (self.deck, self.candidate_id, self.forecast_id, self.last_feedback))):
                raise ContractError("initial group cannot claim trained data/adapters")
            return
        if self.sessions is None or self.data is None:
            raise ContractError("warmed group lacks actual supervision/adapters")
        index = len(PHASES) if self.phase == "done" else PHASES.index(self.phase)
        for role, session in self.sessions.items():
            expected = self.cycle if self.phase == "done" else self.cycle + int(ROLE_PHASE[role] < index)
            if session.updates != expected or not session.enabled:
                raise ContractError("group role update/data cursor differs")
            session.verify_base()
        expected_marks = [("bootstrap", "train")]
        for cycle in range(limit):
            event = f"cycle-{cycle + 1}-duel_train"
            if event in self.consumed:
                expected_marks.append((event, "train"))
            event = f"cycle-{cycle + 1}-evaluate"
            if event in self.consumed:
                expected_marks.extend([(event, "validation")] * len(self.row["recipe"]["validation"]["seeds"]))
        if [(m["event_id"], m["partition"]) for m in self.data_marks] != expected_marks or len(self.evaluations) != sum(p == "validation" for _, p in expected_marks):
            raise ContractError("group committed train/eval markers differ from the phase cursor")

    def training_fingerprint(self):
        import torch
        return tree_digest({"models": {r: m.state_dict() for r, m in self.models().items()},
                            "base_optimizers": {r: o.state_dict() for r, o in self.builder.optimizers.items()},
                            "duel_optimizer": self.duel.optimizer.state_dict(), "coordinator_optimizer": self.coordinator.optimizer.state_dict(),
                            "base_schedulers": {r: s.state_dict() for r, s in self.builder.schedulers.items()},
                            "duel_scheduler": self.duel.scheduler.state_dict(), "coordinator_scheduler": self.coordinator.scheduler.state_dict(),
                            "adapters": {r: s.state() for r, s in self.sessions.items()},
                            "policy_rng": self.policy_rng.get_state(), "torch_rng": torch.get_rng_state(),
                            "python_rng": random.getstate(), "build_batch_rng": self.builder.batch_rng.get_state(),
                            "base_duel_policy_rng": self.duel.policy_rng.get_state(), "base_duel_batch_rng": self.duel.batch_rng.get_state(),
                            "coord_batch_rng": self.coordinator.batch_rng.get_state(), "cursor": self.cursor()})

    def save_to(self, path):
        import torch
        from .build_training import save_checkpoint as save_build, binding_for as build_binding
        from .cpu_training import save_checkpoint as save_duel, resource_binding
        self.validate_cursor()
        with self.host._db() as db:
            if db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('pending','leased')").fetchone()[0]:
                raise ContractError("cannot save a group with an in-flight evaluation")
        with tempfile.TemporaryDirectory(dir=path.parent) as temp:
            directory = Path(temp)
            supervision = self.data or {"supervision_sha256": digest({"phase": "before-bootstrap", "task": self.task.sha256})}
            with ExitStack() as stack:
                for session in (self.sessions or {}).values():
                    stack.enter_context(session.suspended())
                b = save_build(self.builder, directory, "build", build_binding(self.task, self.assets, supervision), allow_initial=True)
                d = save_duel(self.duel, directory, "duel", resource_binding(self.assets.root, self.row["profile"]), allow_initial=True)
                coordinator = self.coordinator.state()
                components = {"build": torch.load(b, weights_only=True), "duel": torch.load(d, weights_only=True), "coordinator": coordinator}
            backup = directory / "ledger.sqlite3"
            with self.host._db() as source, sqlite3.connect(backup) as destination:
                source.backup(destination)
            ledger_bytes = backup.read_bytes()
            state = {"schema_version": 1, "boundary": "complete-workflow-stage", "binding": self.row["binding"],
                     "components": components, "adapters": None if self.sessions is None else {r: s.state() for r, s in self.sessions.items()},
                     "cursor": self.cursor(), "consumed": self.consumed, "events": self.events, "data": self.data,
                     "data_marks": self.data_marks, "evaluations": self.evaluations, "deck": self.deck,
                     "candidate_id": self.candidate_id, "forecast_id": self.forecast_id, "last_feedback": self.last_feedback,
                     "ledger_bytes": ledger_bytes, "ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest(),
                     "ledger_state_sha256": self.host.state_digest(), "policy_rng": self.policy_rng.get_state(),
                     "global_rng": {"torch": torch.get_rng_state(), "python": random.getstate()}}
            with path.open("xb") as output:
                torch.save(state, output)
                output.flush(); os.fsync(output.fileno())

    @classmethod
    def restore(cls, path, state_root, row, assets):
        import torch
        from .build_training import load_checkpoint as load_build, binding_for as build_binding, validate_supervision
        from .cpu_training import load_checkpoint as load_duel, resource_binding, config_from_dict
        from .coordinator_model import CoordinatorTrainer
        from .coordinator import Coordinator
        from .coord_contracts import FeedbackPolicy
        from .lora import AdapterSession
        from .local_training import run_path
        from .training_runner import read_artifact, validate_shard, opponent_binding
        state = torch.load(path, weights_only=True, map_location="cpu")
        fields(state, {"schema_version", "boundary", "binding", "components", "adapters", "cursor", "consumed", "events", "data", "data_marks", "evaluations",
                       "deck", "candidate_id", "forecast_id", "last_feedback", "ledger_bytes", "ledger_sha256", "ledger_state_sha256", "policy_rng", "global_rng"})
        if (state["schema_version"] != 1 or state["boundary"] != "complete-workflow-stage" or state["binding"] != row["binding"]
                or binding_for(assets.root, row) != row["binding"] or hashlib.sha256(state["ledger_bytes"]).hexdigest() != state["ledger_sha256"]):
            raise ContractError("group checkpoint boundary/version/ledger differs")
        obj = cls.__new__(cls)
        obj.assets, obj.row, obj.state_root = assets, row, Path(state_root)
        obj.task, obj.data = BuildTask.from_dict(row["task"]), state["data"]
        if obj.data is not None:
            validate_supervision(obj.task, assets, obj.data)
        expected_data = obj.data or {"supervision_sha256": digest({"phase": "before-bootstrap", "task": obj.task.sha256})}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for role in ("build", "duel"):
                with (directory / (role + ".weights")).open("xb") as output:
                    torch.save(state["components"][role], output)
            obj.builder = load_build(directory / "build.weights", assets, build_binding(obj.task, assets, expected_data), allow_initial=True)
            obj.duel = load_duel(directory / "duel.weights", resource_binding(assets.root, row["profile"]), allow_initial=True)
        expected_cpu = config_from_dict(dict(row["recipe"]["cpu_config"], game_seeds=[row["recipe"]["bootstrap_seed"]]))
        if asdict(obj.duel.config) != asdict(expected_cpu):
            raise ContractError("group base duel configuration differs")
        obj.coordinator = CoordinatorTrainer.restore(state["components"]["coordinator"])
        expected = {r: obj.expected_adapter(r) for r in obj.models()} if state["adapters"] is not None else None
        if expected is not None and set(state["adapters"]) != set(expected):
            raise ContractError("group checkpoint must include all four adapters")
        obj.sessions = None if expected is None else {r: AdapterSession.restore(obj.models()[r], state["adapters"][r], expected[r]) for r in expected}
        obj.cycle, obj.phase, obj.updates = (state["cursor"][k] for k in ("cycle", "phase", "committed_stages"))
        for key in ("consumed", "events", "data_marks", "evaluations", "deck", "candidate_id", "forecast_id", "last_feedback"):
            setattr(obj, key, state[key])
        obj.policy_rng = torch.Generator(device="cpu")
        obj.policy_rng.set_state(state["policy_rng"])
        run = run_path(state_root, row["run_id"])
        ledger = run / ("working-" + uuid4().hex + ".sqlite3")
        with ledger.open("xb") as output:
            output.write(state["ledger_bytes"])
        obj.host = Coordinator(ledger, FeedbackPolicy.from_dict(row["feedback_policy"]), role="coordinator", source="real_engine", assets=assets)
        if obj.host.state_digest() != state["ledger_state_sha256"]:
            raise ContractError("restored workflow ledger differs")
        with obj.host._db() as db:
            if db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('pending','leased')").fetchone()[0]:
                raise ContractError("restored group contains an uncommitted evaluation")
        obj.validate_cursor()
        for mark in obj.data_marks:
            if mark["event_id"] not in obj.consumed or mark["partition"] not in ("train", "validation"):
                raise ContractError("group data marker was not committed in its stage")
            validate_shard(read_artifact(run, mark["artifact"]), obj.duel, purpose=mark["partition"], version=mark["policy_version"],
                           policy_sha256=mark["policy_sha256"], opponent_sha256=opponent_binding(row, "train" if mark["partition"] == "train" else "validation"))
        torch.set_rng_state(state["global_rng"]["torch"])
        random.setstate(state["global_rng"]["python"])
        return obj


def snapshot(state):
    warm = int(state.sessions is not None)
    role_updates = {r: s.updates for r, s in (state.sessions or {}).items()}
    return {"model_versions": state.versions(), "role_adapter_updates": role_updates, "cursor": state.cursor(),
            "metrics": {"steps": state.updates, "optimizer_updates": 4 * warm + sum(role_updates.values()),
                        "episodes": warm + role_updates.get("duel", 0), "validation_episodes": len(state.evaluations),
                        "cycles_completed": state.cycle, "committed_stages": state.updates}}


def prepare(backend, run_id, wall_limit_seconds):
    import time
    from .agent_registry import identifier
    from .agent_monitor import RunReporter
    from .build_pipeline import BuildAssets
    from .coord_contracts import FeedbackPolicy
    from .local_training import _connect, run_path, write_checkpoint, snapshot_for
    from .training_plan import validate_plan
    from .training_runner import sync_usage
    identifier(run_id)
    started, cpu = time.monotonic(), time.process_time()
    recipe = validate_recipe(backend.recipe)
    profiles, cfg, task, _, _ = inputs(recipe)
    assets = BuildAssets(backend.native_root)
    assets.check_task(task)
    directory = run_path(backend.state_root, run_id)
    if directory.exists():
        raise ContractError("group run directory exists; no overwrite")
    with closing(_connect(backend.state_root, create=True)) as db:
        if db.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone():
            raise ContractError("group run identity already prepared")
    row = {"schema_version": 1, "run_id": run_id, "native_root": str(backend.native_root),
           "recipe": recipe, "profile": profiles["train"], "validation_profile": profiles["validation"],
           "task": task.to_dict(), "feedback_policy": FeedbackPolicy().to_dict(),
           "config": json.loads(canonical_json(asdict(cfg))), "wall_limit_seconds": float(wall_limit_seconds),
           "active_seconds": 0., "segment_started": None, "state": "created", "desired": "created", "phase": "prepared",
           "active_stage": "bootstrap", "revision": 0, "pid": None, "pid_stamp": None, "generation": None,
           "checkpoint_ids": [], "rounds": [], "group_events": [], "updates": [], "validations": [], "history": [],
           "scheduled_checkpoint_ids": [], "usage_outbox": [], "discarded_episodes": 0, "recovery_count": 0,
           "completed_worker_cpu_seconds": 0., "reason": "prepared_initial_four_models_no_update_or_adapter_yet",
           "budget_plan": validate_plan(read_json(ROOT / "configs/training-plan-v1.json"))}
    row["binding"] = binding_for(backend.native_root, row)
    state = GroupState(backend.state_root, row, assets)
    initial = snapshot(state)
    row.update(model_versions=initial["model_versions"], metrics=dict(initial["metrics"], unmeasured_worker_segments=0))
    receipt = write_checkpoint(state, backend.state_root, row)
    row["checkpoint_ids"] = [receipt["checkpoint_id"]]
    row["active_seconds"] = time.monotonic() - started
    row["metrics"]["setup_process_cpu_seconds"] = time.process_time() - cpu
    row["usage_outbox"].append({"payload": {"event_id": "setup-" + digest(run_id)[:40], "stage_id": "throughput-small-train", "gpu_count": 0,
        "wall_seconds": max(.001, row["active_seconds"]), "activity": "setup", "outcome": "completed", "amount": None, "currency": None},
        "measurement": "measured_host_setup", "exported": False})
    row["history"].append({"event": "prepared_four_initial_models", "optimizer_updates": 0, "checkpoint_id": receipt["checkpoint_id"]})
    RunReporter(backend.state_root).publish(snapshot_for(row))
    with closing(_connect(backend.state_root)) as db, db:
        db.execute("INSERT INTO runs VALUES(?,?)", (run_id, canonical_json(row)))
    sync_usage(backend.state_root, run_id)
    return backend.status(run_id)


def verified(state_root, row):
    from .agent_monitor import RunMonitor
    from .build_pipeline import BuildAssets
    from .local_training import run_path
    if binding_for(Path(row["native_root"]), row) != row["binding"]:
        raise ContractError("group implementation/resources changed")
    latest = row["checkpoint_ids"][-1]
    receipt = RunMonitor(state_root).checkpoint(row["run_id"], latest)
    state = GroupState.restore(run_path(state_root, row["run_id"]) / "checkpoints" / (latest + ".weights"),
                               state_root, row, BuildAssets(Path(row["native_root"])))
    if state.updates != receipt["step"] or state.updates != row["metrics"]["steps"] or len(row["rounds"]) != state.updates:
        raise ContractError("group checkpoint differs from committed stage journal")
    if state.updates:
        manifest = read_json(run_path(state_root, row["run_id"]) / "stages" / f"step-{state.updates}.json")
        if digest(manifest) != row["rounds"][-1]["manifest_sha256"] or manifest["event"] != state.events[-1] or manifest["snapshot"] != snapshot(state):
            raise ContractError("group committed manifest/state differs")
    return state


def sampler(state):
    _, cfg, _, _, _ = inputs(state.row["recipe"])
    result = copy.copy(state.duel)
    result.config = cfg
    result.policy_rng = state.policy_rng
    result.updates = result.episode_cursor = state.sessions["duel"].updates
    return result


def record_episode(state, episode, generation):
    from .local_training import run_path
    from .training_runner import atomic_json, file_receipt, shard_for, opponent_binding
    event_id, purpose = state.event_id(), episode["purpose"]
    run = run_path(state.state_root, state.row["run_id"])
    index = sum(m["event_id"] == event_id for m in state.data_marks)
    path = run / "data" / purpose / f"{event_id}-{index}-{generation}.json"
    binding = opponent_binding(state.row, "train" if purpose == "train" else "validation")
    atomic_json(path, shard_for(episode, binding))
    state.data_marks.append({"event_id": event_id, "partition": purpose, "artifact": file_receipt(path, run),
                             "policy_version": episode["policy_version"], "policy_sha256": episode["policy_sha256"]})


def select_goal(state):
    import torch
    from .build_pipeline import goal_candidates, verify_goal
    base = None if state.deck is None else DeckParts.from_dict(state.deck)
    candidates = goal_candidates(state.task, state.assets, base)
    if not candidates:
        raise ContractError("group goal stage found no legal candidate")
    model = state.builder.models["build_goal"]
    model.eval()
    with torch.no_grad():
        scores = model(state.builder.encoder.batch(state.task, candidates))
    for index in scores.argsort(descending=True).tolist():
        proof = verify_goal(state.task, candidates[index], state.assets)
        if proof["status"] == "verified_success":
            state.deck = candidates[index].to_dict()
            return {"deck": state.deck, "validation": without_timing(proof), "model_score_uncalibrated": float(scores[index])}
    raise ContractError("group goal route remains unverified")


def evaluate(state, generation):
    from .model_group import call, route_with_model
    from .coordinator import Coordinator
    from .training_runner import opponent_binding
    frozen = state.training_fingerprint()
    deck = DeckParts.from_dict(state.deck)
    state.assets.validate(state.task, deck)
    with state.host._db() as db:
        existing = [json.loads(p) for p, in db.execute("SELECT payload FROM candidates")]
    same = next((c for c in existing if c["deck_sha256"] == digest(state.deck)), None)
    if same is None:
        candidate = call(state.host, "handoff.submit", {"candidate_id": f"cycle-{state.cycle + 1}-deck", "parent_candidate_id": state.candidate_id,
            "task": state.task.to_dict(), "deck": state.deck, "build_models": {r: state.versions()[r] for r in state.builder.models}})
        state.candidate_id = candidate["candidate_id"]
    else:
        state.candidate_id = same["candidate_id"]
    route, advice = route_with_model(state.host, state.coordinator, state.candidate_id, None, 1)
    if route["action"] not in ("register_forecast", "build_goal"):
        raise ContractError("rule coordinator did not grant versioned forecast stage")
    # Mandatory rebuild is enforced again by job.schedule; a same-deck rename
    # cannot clear its root lineage, warning or required reconstruction.
    state.forecast_id = f"cycle-{state.cycle + 1}-forecast"
    profile = state.row["validation_profile"]
    actor_hash = state.versions()["duel"]
    scope = {"actor_policy_sha256": actor_hash, "duel_lora": state.sessions["duel"].version_id(),
             "opponents": [{"opponent_id": "held-out-visible-engineering", "deck_sha256": digest({"main": profile["decks"][1], "extra": [], "side": []}),
                            "driver_sha256": opponent_binding(state.row, "validation"), "weight": 1.}],
             "initiative_weights": [1., 0.], "unit": "BO1", "prediction_target": "win_rate", "versions": state.task.environment["versions"]}
    forecast = call(state.host, "forecast.register", {"forecast_id": state.forecast_id, "candidate_id": state.candidate_id,
        "probability": advice["probability"], "origin_role": "coordinator", "model_sha256": state.versions()["coordinator"], "calibration": "pending", "scope": scope})
    worker = Coordinator(state.host.path, state.host.policy, role="duel_worker", source="real_engine", assets=state.assets)
    results = []
    for index, seed in enumerate(state.row["recipe"]["validation"]["seeds"]):
        job_id = f"cycle-{state.cycle + 1}-evaluation-{index}"
        call(state.host, "job.schedule", {"job_id": job_id, "forecast_id": state.forecast_id, "seed": seed, "purpose": "engineering_validation"})
        job = call(worker, "job.claim", {"job_id": job_id, "worker_id": "cpu-group-evaluator"})
        if job["scope"] != scope or job["actor_seat"] != 0 or job["deck"] != state.deck or job["seed"] != seed:
            raise ContractError("group frozen job/version/deck/seed differs")
        actual_profile = dict(profile, decks=[list(deck.main), profile["decks"][1]])
        episode = sampler(state).sample_episode(state.assets.root, actual_profile, purpose="validation", seed=seed,
            policy_seed=state.row["recipe"]["validation"]["policy_seed"], opponent=state.row["recipe"]["validation"]["opponent"])
        record_episode(state, episode, generation)
        winner = episode["summary"]["outcome"]["winner"]
        result = {"result_id": job_id + "-result", "job_id": job_id, "worker_id": "cpu-group-evaluator", "forecast_id": state.forecast_id,
            "candidate_id": state.candidate_id, "scope_sha256": job["scope_sha256"], "source": "real_engine", "unit": "BO1",
            "outcome": "win" if winner == 0 else "loss" if winner == 1 else "draw", "audit_sha256": episode["summary"]["trajectory_sha256"],
            "diagnosis": "unknown" if winner == 1 else "none"}
        status = call(worker, "results.append", {"results": [result]})
        entry = {"cycle": state.cycle + 1, "result": result, "duel": without_timing(episode["summary"]),
                 "actor_deck_sha256": digest(state.deck), "opponent_binding_sha256": opponent_binding(state.row, "validation")}
        state.evaluations.append(entry)
        results.append(entry)
    if state.training_fingerprint() != frozen:
        raise ContractError("frozen group evaluation changed training weights/optimizers/RNG/cursor")
    return {"forecast": forecast, "evaluations": results, "frozen_training_state_sha256": frozen,
            "training_state_unchanged": True, "ledger_state_sha256": state.host.state_digest()}


def execute_stage(state, generation):
    from .build_training import engineering_dataset
    from .lora_group import construction_loss, coordinator_loss, ppo_inputs, ppo_loss
    from .coordinator_model import engineering_examples
    from .build_pipeline import alternate_build
    from .model_group import route_with_model
    if state.event_id() in state.consumed:
        raise ContractError("cannot execute an already committed group stage")
    if state.phase == "bootstrap":
        state.data = engineering_dataset(state.task, state.assets)
        updates = state.builder.step(state.data)
        episode = state.duel.sample_episode(state.assets.root, state.row["profile"], opponent=state.row["recipe"]["train"]["opponent"])
        record_episode(state, episode, generation)
        updates.append(dict(state.duel.update(episode), role="duel"))
        updates.append(dict(state.coordinator.step(engineering_examples()), role="coordinator"))
        state.attach()
        return {"kind": "real-four-base-warmup", "updates": updates, "duel": without_timing(episode["summary"]),
                "supervision_source": {"building": state.data["source"], "optimization": "printed-attack-weak-proxy", "coordinator": "synthetic-rule-and-probability-anchors"}}
    if state.phase in ("build_goal", "build_optimizer"):
        role = state.phase
        update = state.sessions[role].step(construction_loss(role, state.sessions[role], state.builder, state.task, state.data))
        if role == "build_goal":
            construction = select_goal(state)
        else:
            construction = alternate_build(state.task, state.assets, state.builder.models, state.builder.encoder,
                base=DeckParts.from_dict(state.deck), lora_versions={r: state.sessions[r].version_id() for r in state.builder.models})
            if len(construction["stages"]) != 4 or construction["best_deck"] is None:
                raise ContractError("group goal/optimizer inner alternation remains unverified")
            state.deck = construction["best_deck"]
        return {"kind": "conditional-construction-adapter-update", "update": update, "construction": without_timing(construction),
                "hard_constraints": state.assets.validate(state.task, DeckParts.from_dict(state.deck)),
                "previous_feedback": state.last_feedback}
    if state.phase == "duel_train":
        current = sampler(state)
        profile = dict(state.row["profile"], decks=[list(DeckParts.from_dict(state.deck).main), state.row["profile"]["decks"][1]])
        episode = current.sample_episode(state.assets.root, profile, opponent=state.row["recipe"]["train"]["opponent"])
        if episode["purpose"] != "train" or episode["policy_version"] != state.sessions["duel"].updates:
            raise ContractError("group PPO requires this phase's fresh on-policy episode")
        values = ppo_inputs(episode, current, state.sessions["duel"])
        update = state.sessions["duel"].step(ppo_loss(state.sessions["duel"], values, current.config))
        record_episode(state, episode, generation)
        return {"kind": "live-core-single-epoch-ppo-adapter", "update": update, "duel": without_timing(episode["summary"]),
                "actor_deck_sha256": digest(state.deck), "batch_samples": values["samples"]}
    if state.phase == "coordinator_train":
        update = state.sessions["coordinator"].step(coordinator_loss(state.sessions["coordinator"]))
        return {"kind": "synthetic-advisory-coordinator-update", "update": update,
                "supervision_source": "synthetic-rule-and-probability-anchors", "rule_authority": True}
    if state.phase == "evaluate":
        return evaluate(state, generation)
    if state.phase == "feedback":
        # This cycle's fixed evaluation budget is exhausted. Global curriculum
        # cycles are a separate explicit program budget, not an LLM decision.
        route, advice = route_with_model(state.host, state.coordinator, state.candidate_id, state.forecast_id, 0)
        if route["action"] != "stop" or route["context"]["system_error"] or route["context"]["operation_error"]:
            raise ContractError("group feedback requires inspection/diagnosis before another cycle")
        state.last_feedback = {"cycle": state.cycle + 1, "evaluation_budget_route": route, "advice": advice,
            "next_cycle_remaining": state.row["recipe"]["max_updates"] - state.cycle - 1,
            "next_phase": "build_goal" if state.cycle + 1 < state.row["recipe"]["max_updates"] else "done",
            "incumbent_deck_sha256": digest(state.deck), "rebuild_required_stays_queued": route["context"]["rebuild_required"]}
        return state.last_feedback
    raise ContractError("group stage cannot execute")


def commit(row, manifest):
    step = manifest["snapshot"]["cursor"]["committed_stages"]
    if step != row["metrics"]["steps"] + 1 or manifest["checkpoint_id"] in row["checkpoint_ids"]:
        raise ContractError("group stage commit duplicates/skips the cursor")
    row["checkpoint_ids"].append(manifest["checkpoint_id"])
    row["rounds"].append({"step": step, "manifest_sha256": digest(manifest)})
    row["group_events"].append(manifest["event"])
    payload = manifest["event"]["payload"]
    updates = payload.get("updates", [payload["update"]] if "update" in payload else [])
    row["updates"].extend(updates)
    row["validations"].extend(payload.get("evaluations", []))
    row["model_versions"] = manifest["snapshot"]["model_versions"]
    row["metrics"].update(manifest["snapshot"]["metrics"])
    if updates:
        row["metrics"]["loss"] = updates[-1]["loss"]
    row["active_stage"] = manifest["snapshot"]["cursor"]["phase"]
    if manifest["scheduled_checkpoint"]:
        row["scheduled_checkpoint_ids"].append(manifest["checkpoint_id"])
    row["history"].append({"event": "group_stage_committed", "step": step, "event_id": manifest["event"]["event_id"],
                           "checkpoint_id": manifest["checkpoint_id"]})


def reconcile(state_root, row, previous):
    from .local_training import checkpoint_receipt, run_path
    run = run_path(state_root, row["run_id"])
    step = previous.updates + 1
    checkpoint = run / "checkpoints" / f"local-step-{step}.weights"
    manifest_path = run / "stages" / f"step-{step}.json"
    if not checkpoint.exists() and not manifest_path.exists():
        return None
    if not checkpoint.exists() or not checkpoint.with_suffix(".json").exists() or not manifest_path.exists():
        quarantine = run / "quarantine" / uuid4().hex
        quarantine.mkdir(parents=True)
        for path in (checkpoint, checkpoint.with_suffix(".json"), manifest_path):
            if path.exists():
                path.replace(quarantine / path.name)
        return {"event": "partial_group_stage_quarantined", "step": step}
    if read_json(checkpoint.with_suffix(".json")) != checkpoint_receipt(row["run_id"], checkpoint, step):
        raise ContractError("unregistered group checkpoint integrity differs")
    restored = GroupState.restore(checkpoint, state_root, row, previous.assets)
    manifest = read_json(manifest_path)
    fields(manifest, {"schema_version", "binding_sha256", "checkpoint_id", "previous_cursor", "event", "snapshot", "scheduled_checkpoint"})
    if (manifest["schema_version"] != 1 or manifest["binding_sha256"] != digest(row["binding"])
            or manifest["checkpoint_id"] != checkpoint.stem or restored.updates != step or manifest["previous_cursor"] != previous.cursor()
            or manifest["snapshot"] != snapshot(restored) or manifest["event"] != restored.events[-1]
            or restored.consumed[:-1] != previous.consumed or restored.events[:-1] != previous.events):
        raise ContractError("unregistered group stage lineage/versions differ")
    return {"event": "adopted_verified_group_stage", "manifest": manifest}


def worker(state_root, run_id, generation, reporter):
    from .local_training import _connect, get_row, put_row, elapsed, write_checkpoint, run_path
    from .training_runner import atomic_json
    with closing(_connect(state_root)) as db:
        row = get_row(db, run_id)
    state = verified(state_root, row)
    segment_stages = 0
    while state.phase != "done":
        with closing(_connect(state_root)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = get_row(db, run_id)
            if row["generation"] != generation:
                raise ContractError("group worker lease superseded")
            if row["desired"] != "running":
                break
            if segment_stages >= row["recipe"]["stages_per_worker"]:
                row.update(desired="paused", reason="worker_stage_budget_reached")
                put_row(db, row)
                break
            reserve = (state.duel.config.episode_seconds + 15 if state.phase == "bootstrap" else
                       state.duel.config.episode_seconds * len(row["recipe"]["validation"]["seeds"]) + 10 if state.phase == "evaluate" else
                       state.duel.config.episode_seconds + 3 if state.phase == "duel_train" else 33 if state.phase in ("build_goal", "build_optimizer") else 3)
            if row["wall_limit_seconds"] - elapsed(row) <= reserve:
                row.update(desired="stopped", reason="wall_budget_reserve_reached")
                put_row(db, row)
                break
            row.update(phase="validating" if state.phase == "evaluate" else "sampling" if state.phase == "duel_train" else "group-" + state.phase,
                       active_stage=state.phase, revision=row["revision"] + 1)
            row["history"].append({"event": "group_stage_attempt", "event_id": state.event_id(), "generation": generation,
                                   "committed_stages_before": state.updates, "model_versions": state.versions()})
            put_row(db, row)
        before_cursor = state.cursor()
        payload = execute_stage(state, generation)
        state.advance(payload)
        receipt = write_checkpoint(state, state_root, row)
        manifest = {"schema_version": 1, "binding_sha256": digest(row["binding"]), "checkpoint_id": receipt["checkpoint_id"],
                    "previous_cursor": before_cursor, "event": state.events[-1], "snapshot": snapshot(state),
                    "scheduled_checkpoint": before_cursor["phase"] == "feedback" and
                        (state.cycle % row["recipe"]["checkpoint_every"] == 0 or state.phase == "done")}
        atomic_json(run_path(state_root, run_id) / "stages" / f"step-{state.updates}.json", manifest)
        with closing(_connect(state_root)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = get_row(db, run_id)
            commit(row, manifest)
            resources = reporter.resources()
            row["metrics"].update(process_cpu_seconds=row["completed_worker_cpu_seconds"] + resources["process_cpu_seconds"],
                process_peak_rss_bytes=max(row["metrics"].get("process_peak_rss_bytes", 0), resources.get("process_peak_rss_bytes", 0)))
            row.update(phase="checkpoint_boundary", revision=row["revision"] + 1)
            put_row(db, row)
        segment_stages += 1
    return state.phase == "done"
