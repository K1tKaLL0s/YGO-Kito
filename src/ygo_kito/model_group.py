"""One bounded real model-group workflow and recovery at a pending-job boundary.

Legacy callers retain advisory routing. Callers supplying public scope features
execute learned cycle decisions within host limits. Native evaluation is not
by itself a calibrated win-rate/strength experiment.
"""

from dataclasses import asdict
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import platform
import random
import sqlite3

import torch

from .agent_monitor import RunMonitor, RunReporter
from .agent_registry import identifier
from .build_contracts import BuildTask, DeckParts, digest
from .build_pipeline import BuildAssets, alternate_build
from .build_training import (BuildTrainer, BuildTrainingConfig, binding_for, engineering_dataset,
                             load_checkpoint as load_build, save_checkpoint as save_build)
from .coord_contracts import FeedbackPolicy
from .coordinator import Coordinator
from .coordinator_model import CoordinatorTrainer, engineering_examples
from .cpu_training import (CpuTrainer, CpuTrainingConfig, cpu_name, load_checkpoint as load_duel,
                           resource_binding, save_checkpoint as save_duel)
from .duel_model import parameter_digest
from .validation import ContractError, canonical_json, fields, integer, read_json

ROOT = Path(__file__).resolve().parents[2]


def group_binding(task, assets, policy):
    implementation = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        implementation.update(path.name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return {"task_sha256": task.sha256, "source_commits": assets.receipt["source_commits"], "resources": assets.receipt["resources"],
            "implementation_sha256": implementation.hexdigest(), "python": platform.python_version(), "torch": str(torch.__version__),
            "feedback_policy": policy.to_dict(), "schema_version": 1}


def call(host, method, params=None, ident="pipeline-request"):
    result = host.dispatch({"schema_version": 1, "id": ident, "method": method, "params": params or {}})
    if not result["ok"]:
        raise ContractError("coordinator operation failed: " + result["error"]["code"] + ": " + result["error"]["message"])
    return result["result"]


def route_with_model(host, model, candidate_id, forecast_id, remaining, *, features=None, allowed_routes=None, max_units=None):
    # Get the authoritative context, then log the actual model's advisory output.
    rule = call(host, "route", {"candidate_id": candidate_id, "forecast_id": forecast_id,
                              "remaining_tasks": remaining, "advisory": None})
    if features is None:
        advice = model.advice(rule["context"])
        extra = {}
        keys = ("route", "model_sha256", "calibration")
    else:
        allowed_routes = list(allowed_routes or ("build_goal", "build_optimizer", "evaluate_duel", "train_duel", "stop"))
        cap = remaining if max_units is None else min(remaining, max_units)
        advice = model.control(rule["context"], features, allowed_routes=allowed_routes, max_units=cap)
        extra = {"allowed_routes": allowed_routes, "max_units": cap}
        keys = ("route", "model_sha256", "calibration", "mode", "budget_units", "features_sha256")
    result = call(host, "route", {"candidate_id": candidate_id, "forecast_id": forecast_id, "remaining_tasks": remaining,
                                "advisory": {k: advice[k] for k in keys}, **extra})
    return result, advice


def save_group(path, builder, duel, coordinator, data, host, task, assets, policy, training_profile, cursor, *, adapters=None):
    from torch.nn.utils.parametrize import is_parametrized
    if adapters is None and any(is_parametrized(m) for model in (*builder.models.values(), duel.model, coordinator.model) for m in model.modules()):
        raise ContractError("parametrized model group requires explicit adapter states")
    path = Path(path)
    if path.exists():
        raise ContractError("group checkpoint exists; no overwrite")
    with host._db() as db:
        if db.execute("SELECT COUNT(*) FROM jobs WHERE state='leased'").fetchone()[0]:
            raise ContractError("cannot checkpoint an in-flight native duel as recoverable")
        job = host._row(db, "jobs", cursor["job_id"])
        if job["state"] != "pending":
            raise ContractError("group checkpoint requires a pending unclaimed job")
    path.parent.mkdir(parents=True, exist_ok=True)
    components = path.parent / "components"
    components.mkdir(exist_ok=True)
    adapter_states = None
    if adapters is not None:
        models = dict(builder.models, duel=duel.model, coordinator=coordinator.model)
        if set(adapters) != set(models) or any(adapters[r].model is not models[r] for r in models):
            raise ContractError("group adapters must bind all four actual role models")
        adapter_states = {r: a.state() for r, a in adapters.items()}
    with ExitStack() as stack:
        for adapter in (adapters or {}).values():
            stack.enter_context(adapter.suspended())
        build_file = save_build(builder, components, "build", binding_for(task, assets, data))
        duel_file = save_duel(duel, components, "duel", resource_binding(assets.root, training_profile))
        coordinator_state = coordinator.state()
    backup_path = components / "ledger.sqlite3"
    if backup_path.exists():
        raise ContractError("ledger backup exists; inspect before retry")
    with host._db() as source:
        with sqlite3.connect(backup_path) as destination:
            source.backup(destination)
    ledger_bytes = backup_path.read_bytes()
    state = {"schema_version": 1, "boundary": "pending-unclaimed-duel-job", "binding": group_binding(task, assets, policy),
             "task": task.to_dict(), "cursor": cursor, "training_profile": training_profile,
             "build": torch.load(build_file, map_location="cpu", weights_only=True),
             "duel": torch.load(duel_file, map_location="cpu", weights_only=True), "coordinator": coordinator_state,
             "ledger_bytes": ledger_bytes, "ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest(),
             "ledger_state_sha256": host.state_digest(), "global_rng": {"torch": torch.get_rng_state(), "python": random.getstate()}}
    if adapter_states is not None:
        state.update(schema_version=2, adapters=adapter_states)
    with path.open("xb") as handle:
        torch.save(state, handle)
    return {"path": path.name, "artifact_bytes": path.stat().st_size, "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "ledger_sha256": state["ledger_sha256"], "ledger_state_sha256": state["ledger_state_sha256"], "boundary": state["boundary"]}


def restore_group(path, destination, assets, expected_binding, *, expected_adapters=None):
    state = torch.load(path, map_location="cpu", weights_only=True)
    fields(state, {"schema_version", "boundary", "binding", "task", "cursor", "training_profile", "build", "duel", "coordinator",
                   "ledger_bytes", "ledger_sha256", "ledger_state_sha256", "global_rng"}, {"adapters"})
    integer(state["schema_version"], "group checkpoint schema", 1, 2)
    if ((state["schema_version"] == 2) != ("adapters" in state) or
            ("adapters" in state) != (expected_adapters is not None)):
        raise ContractError("adapter group requires explicit expected adapter bindings")
    if expected_adapters is not None:
        from .lora import ROLES
        if set(state["adapters"]) != set(ROLES) or set(expected_adapters) != set(ROLES):
            raise ContractError("all role adapter bindings required")
        if any(state["adapters"][r]["compatibility"] != expected_adapters[r] for r in ROLES):
            raise ContractError("adapter group base/version/context differs")
    task = BuildTask.from_dict(state["task"])
    policy = FeedbackPolicy.from_dict(state["binding"]["feedback_policy"])
    if (state["boundary"] != "pending-unclaimed-duel-job" or state["binding"] != expected_binding
            or group_binding(task, assets, policy) != expected_binding):
        raise ContractError("group checkpoint boundary/task/resources/implementation differs")
    if hashlib.sha256(state["ledger_bytes"]).hexdigest() != state["ledger_sha256"]:
        raise ContractError("embedded coordinator ledger checksum differs")
    destination = Path(destination)
    if destination.exists():
        raise ContractError("recovery destination exists; inspect before retry")
    destination.mkdir(parents=True)
    for role in ("build", "duel"):
        with (destination / f"{role}.weights").open("xb") as handle:
            torch.save(state[role], handle)
    builder = load_build(destination / "build.weights", assets, state["build"]["binding"])
    actual_duel_binding = resource_binding(assets.root, state["training_profile"])
    if actual_duel_binding != state["duel"]["binding"]:
        raise ContractError("restored duel training resource binding differs")
    duel = load_duel(destination / "duel.weights", actual_duel_binding)
    coordinator = CoordinatorTrainer.restore(state["coordinator"])
    adapters = None
    if expected_adapters is not None:
        from .lora import AdapterSession
        models = dict(builder.models, duel=duel.model, coordinator=coordinator.model)
        adapters = {r: AdapterSession.restore(models[r], state["adapters"][r], expected_adapters[r]) for r in models}
    ledger = destination / "coordinator.sqlite3"
    with ledger.open("xb") as handle:
        handle.write(state["ledger_bytes"])
    host = Coordinator(ledger, policy, role="coordinator", source="real_engine", assets=assets)
    if host.state_digest() != state["ledger_state_sha256"]:
        raise ContractError("restored coordinator state differs")
    torch.set_rng_state(state["global_rng"]["torch"])
    random.setstate(state["global_rng"]["python"])
    return {"builder": builder, "duel": duel, "coordinator": coordinator, "host": host, "cursor": state["cursor"], "task": task,
            "adapters": adapters}


def execute_duel_job(host, duel, coordinator, assets, opponent_profile, cursor, *, adapter=None):
    from torch.nn.utils.parametrize import is_parametrized
    if adapter is None and any(is_parametrized(m) for m in duel.model.modules()):
        raise ContractError("parametrized actor requires an explicit adapter session")
    worker = Coordinator(host.path, host.policy, role="duel_worker", source="real_engine", assets=assets)
    job = call(worker, "job.claim", {"job_id": cursor["job_id"], "worker_id": "native-neural-evaluator"})
    actor_hash = parameter_digest(duel.model)
    lora_version = None
    if adapter is not None:
        from .lora import AdapterSession
        if not isinstance(adapter, AdapterSession) or adapter.model is not duel.model or not adapter.enabled:
            raise ContractError("duel adapter must be explicitly active on the actual actor")
        adapter.verify_base()
        lora_version = adapter.version_id()
    if (actor_hash != job["scope"]["actor_policy_sha256"] or job["scope"]["unit"] != "BO1" or job["scope"]["duel_lora"] != lora_version or
            job["deck"]["extra"] or
            job["actor_seat"] != duel.config.actor_seat or job["source"] != "real_engine" or
            job["opponent"]["deck_sha256"] != digest({"main": opponent_profile["decks"][1], "extra": [], "side": []}) or
            job["opponent"]["driver_sha256"] != group_binding(cursor["task"], assets, host.policy)["implementation_sha256"] or
            duel.config.game_seeds[duel.episode_cursor] != job["seed"]):
        raise ContractError("evaluation executor model/deck/driver/seat/unit/seed binding differs")
    profile = dict(opponent_profile, decks=[job["deck"]["main"], opponent_profile["decks"][1]])
    episode = duel.sample_episode(assets.root, profile)
    summary = episode["summary"]
    winner = summary["outcome"]["winner"]
    outcome = "win" if winner == duel.config.actor_seat else "loss" if winner in (0, 1) else "draw"
    if parameter_digest(duel.model) != actor_hash:
        raise ContractError("evaluation changed frozen driving weights")
    result = {"result_id": job["job_id"] + "-result", "job_id": job["job_id"], "worker_id": "native-neural-evaluator",
              "forecast_id": job["forecast_id"], "candidate_id": job["candidate_id"], "scope_sha256": job["scope_sha256"],
              "source": "real_engine", "unit": "BO1", "outcome": outcome, "audit_sha256": summary["trajectory_sha256"],
              "diagnosis": "unknown" if outcome == "loss" else "none"}
    recorded = call(worker, "results.append", {"results": [result]})
    after, advice = route_with_model(host, coordinator, job["candidate_id"], job["forecast_id"], 0)
    return {"result": result, "status": recorded[job["forecast_id"]], "stop_route": after, "stop_advice": advice,
            "duel": {k: v for k, v in summary.items() if k not in ("actor_inference_ms", "elapsed_seconds")},
            "actor_inference_ms": summary["actor_inference_ms"], "ledger_state_sha256": host.state_digest()}


def run_model_group_smoke(root, state_root, run_id, task, policy=None):
    identifier(run_id)
    state_root = Path(state_root).resolve()
    run = state_root / "runs" / run_id
    if run.exists():
        raise ContractError("model-group run exists; choose a new ID")
    policy = policy or FeedbackPolicy()
    assets = BuildAssets(root)
    builder = BuildTrainer(task, assets, BuildTrainingConfig())
    reporter = RunReporter(state_root)
    snapshot = {"schema_version": 1, "run_id": run_id, "state": "running", "revision": 0,
                "model_versions": {r: "engineering-prototype-v1" for r in ("duel", "build_goal", "build_optimizer", "coordinator")},
                "metrics": reporter.resources(), "checkpoint_ids": [], "source": "trainer"}
    reporter.publish(snapshot)
    updates = []
    try:
        data = engineering_dataset(task, assets)
        for _ in range(2):
            updates.extend(builder.step(data))
        construction = alternate_build(task, assets, builder.models, builder.encoder)
        if len(construction["stages"]) != 4:
            raise ContractError("model-group construction did not verify four stages")
        profile = read_json(ROOT / "configs/effect-duel-v1.json")
        card_ids = sorted(c for c in assets.rows if 0 < c < 2**32)
        duel = CpuTrainer(CpuTrainingConfig(), card_ids)
        training_episode = duel.sample_episode(assets.root, profile)
        updates.append(dict(duel.update(training_episode), role="duel"))
        coordinator = CoordinatorTrainer()
        examples = engineering_examples()
        for _ in range(2):
            updates.append(dict(coordinator.step(examples), role="coordinator"))
        models = dict(builder.models, duel=duel.model, coordinator=coordinator.model)
        storage = [{p.data_ptr() for p in m.parameters()} for m in models.values()]
        if any(a & b for i, a in enumerate(storage) for b in storage[i + 1:]):
            raise ContractError("model group unexpectedly shares trainable storage")
        hashes = {r: parameter_digest(m) for r, m in models.items()}
        ledger = run / "coordinator.sqlite3"
        host = Coordinator(ledger, policy, role="coordinator", source="real_engine", assets=assets, create=True)
        candidate = call(host, "handoff.submit", {"candidate_id": "group-candidate", "parent_candidate_id": None,
                         "task": task.to_dict(), "deck": construction["best_deck"], "build_models": {r: hashes[r] for r in builder.models}})
        first_route, advice = route_with_model(host, coordinator, candidate["candidate_id"], None, 1)
        if first_route["action"] != "register_forecast":
            raise ContractError("prediction registration must precede evaluation")
        binding = group_binding(task, assets, policy)
        scope = {"actor_policy_sha256": hashes["duel"], "duel_lora": None,
                 "opponents": [{"opponent_id": "fixed-rule-engineering", "deck_sha256": digest({"main": profile["decks"][1], "extra": [], "side": []}),
                                "driver_sha256": binding["implementation_sha256"], "weight": 1.}],
                 "initiative_weights": [1., 0.], "unit": "BO1", "prediction_target": "win_rate", "versions": task.environment["versions"]}
        forecast = call(host, "forecast.register", {"forecast_id": "group-forecast", "candidate_id": candidate["candidate_id"],
                        "probability": advice["probability"], "origin_role": "coordinator", "model_sha256": hashes["coordinator"], "calibration": "pending", "scope": scope})
        before, _ = route_with_model(host, coordinator, candidate["candidate_id"], forecast["forecast_id"], 1)
        if before["action"] != "evaluate_duel":
            raise ContractError("scoped evaluation route not granted")
        job = call(host, "job.schedule", {"job_id": "group-evaluation", "forecast_id": forecast["forecast_id"], "seed": 24, "purpose": "engineering_validation"})
        cursor = {"job_id": job["job_id"], "forecast_id": forecast["forecast_id"], "run_id": run_id, "task": task}
        # Cursor is serialized as plain task data, never a pickle of a user class.
        persisted_cursor = dict(cursor, task=task.to_dict())
        checkpoint = run / "checkpoints/group-before-duel.weights"
        saved = save_group(checkpoint, builder, duel, coordinator, data, host, task, assets, policy, profile, persisted_cursor)
        meta = {"schema_version": 1, "run_id": run_id, "checkpoint_id": "group-before-duel", "artifact_bytes": saved["artifact_bytes"],
                "artifact_sha256": saved["artifact_sha256"], "step": len(updates)}
        checkpoint.with_suffix(".json").write_text(canonical_json(meta) + "\n")
        snapshot = dict(snapshot, revision=1, checkpoint_ids=["group-before-duel"], metrics=dict(reporter.resources(), steps=len(updates)))
        reporter.publish(snapshot)
        RunMonitor(state_root).checkpoint(run_id, "group-before-duel")
        canonical = execute_duel_job(host, duel, coordinator, assets, profile, cursor)
        recovered = restore_group(checkpoint, run / "recovery", assets, binding)
        restored_cursor = dict(recovered["cursor"], task=recovered["task"])
        repeated = execute_duel_job(recovered["host"], recovered["duel"], recovered["coordinator"], assets, profile, restored_cursor)
        verified = (canonical["result"] == repeated["result"] and canonical["duel"] == repeated["duel"] and
                    canonical["ledger_state_sha256"] == repeated["ledger_state_sha256"] and
                    all(parameter_digest(recovered["builder"].models[r]) == hashes[r] for r in builder.models) and
                    parameter_digest(recovered["coordinator"].model) == hashes["coordinator"] and
                    parameter_digest(recovered["duel"].model) == hashes["duel"])
        if not verified:
            raise ContractError("actual restored model-group evaluation/ledger diverged")
        metrics = dict(reporter.resources(), steps=len(updates), episodes=2, loss=updates[-1]["loss"])
        result = {"schema_version": 1, "ok": True, "scope": "bounded-model-group-and-rule-feedback-engineering", "binding": binding,
                  "task": task.to_dict(), "construction": construction, "updates": updates, "model_hashes": hashes,
                  "parameter_counts": {r: sum(p.numel() for p in m.parameters()) for r, m in models.items()},
                  "coordinator_supervision": examples, "coordinator_mode": "rule_authoritative_with_learned_advice",
                  "forecast": forecast, "job": job, "evaluation": canonical, "restore_verified": verified, "checkpoint": saved,
                  "training_duel": {k: v for k, v in training_episode["summary"].items() if k != "actor_inference_ms"},
                  "canonical_evaluation_matches": 1, "physical_evaluation_matches_including_recovery": 2,
                  "real_training_duels": 1, "canonical_optimizer_calls": len(updates), "metrics": metrics,
                  "history": host.history(), "statistical_calibration": "pending", "competitive_ability_validated": False,
                  "hardware": {"device": "cpu", "torch_threads": 1, "processor": cpu_name(), "cuda_build": torch.version.cuda},
                  "cost": {"new_paid_instances_started": 0, "external_api_calls": 0, "cloud_development_cpu_cost": "not-exposed"}}
        (run / "proof.json").write_text(canonical_json(result) + "\n")
        reporter.publish(dict(snapshot, state="completed", revision=2, metrics=metrics))
        return result
    except Exception:
        old = reporter.snapshot(run_id)
        reporter.publish(dict(old, state="failed", revision=old["revision"] + 1, metrics=reporter.resources()))
        raise
