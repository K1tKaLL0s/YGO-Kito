"""One bounded CPU acceptance command with real training and owned-worker faults.

This validates the supported engineering chain. It does not certify full phase
1, competitive strength, external providers, user decks or PC compatibility.
"""

import copy
import hashlib
from pathlib import Path
import signal
import time

from .agent_bridge import AgentBridge
from .agent_monitor import RunMonitor, RunReporter
from .build_contracts import BuildTask, digest
from .coord_contracts import FeedbackPolicy
from .local_training import LocalCpuBackend, alive, verified_trainer
from .training_plan import BudgetBook
from .training_preflight import cpu_preflight
from .validation import ContractError, canonical_json, read_json

ROOT = Path(__file__).resolve().parents[2]


def wait_for(predicate, *, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise ContractError("bounded acceptance wait timed out; inspect managed worker state")


def control_acceptance(root, state_root):
    """Actual JSON actions, full-episode restart, SIGKILL recovery and time cap."""
    import torch
    from .duel_model import parameter_digest
    backend = LocalCpuBackend(state_root, root)
    trainer = AgentBridge(ROOT, state_root, root, role="trainer", training_backend=backend)
    monitor = AgentBridge(ROOT, state_root, root, role="monitor")
    opponent = AgentBridge(ROOT, state_root, root, role="opponent")
    transcript = []
    serial = 0

    def tool(bridge, method, params, *, expected=True, ident=None):
        nonlocal serial
        serial += 1
        request = {"schema_version": 1, "id": ident or f"acceptance-{serial}", "method": method, "params": params}
        response = bridge.dispatch(request)
        transcript.append({"role": bridge.role, "request": request, "response": response})
        if response["ok"] != expected:
            raise ContractError("acceptance tool result differs: " + method)
        return response

    def status(name):
        return tool(monitor, "runs.read", {"run_id": name})["result"]

    def action(name, operation, ident=None):
        current = status(name)
        response = tool(trainer, "training.control", {"run_id": name, "operation": operation,
                         "expected_revision": current["revision"]}, ident=ident)
        if response["result"]["execution"] != "applied":
            raise ContractError("real local CPU operation did not apply")
        return response["result"]["backend_result"]

    def done(name):
        def inspect():
            row = backend.refresh(name)
            return row if row["state"] != "running" and not alive(row) else None
        return wait_for(inspect)

    try:
        name = "controlled-duel"
        prepared = tool(trainer, "training.prepare", {"run_id": name})["result"]
        initial = tool(monitor, "checkpoints.read", {"run_id": name, "checkpoint_id": "local-step-0"})["result"]
        if initial["step"] != 0 or prepared["metrics"]["steps"] != 0:
            raise ContractError("initial checkpoint must not count as a training update")
        denied = tool(opponent, "training.control", {"run_id": name, "operation": "start", "expected_revision": 0}, expected=False)
        if denied["error"]["code"] != "PERMISSION_DENIED":
            raise ContractError("opponent training permission boundary failed")
        tool(opponent, "runs.read", {"run_id": name}, expected=False)
        tool(monitor, "training.prepare", {"run_id": "forbidden"}, expected=False)
        started = tool(trainer, "training.control", {"run_id": name, "operation": "start", "expected_revision": 0}, ident="start-once")
        replay = tool(trainer, "training.control", {"run_id": name, "operation": "start", "expected_revision": 0}, ident="start-once")
        if replay != started:
            raise ContractError("idempotent start changed response or launched twice")
        wait_for(lambda: backend.details(name)["phase"] == "sampling")
        paused = action(name, "pause")
        paused_status = status(name)
        if paused["state"] != "paused" or not paused["local_process_exited"] or paused_status["metrics"]["steps"] != 1:
            raise ContractError("pause must finish one actual update, checkpoint and exit")
        checkpoint = action(name, "save_checkpoint")
        checked = tool(monitor, "checkpoints.read", {"run_id": name, "checkpoint_id": checkpoint["checkpoint_id"]})["result"]
        before_restart = verified_trainer(state_root, backend.details(name))
        restart_from_hash = parameter_digest(before_restart.model)
        resumed = action(name, "resume")
        if resumed["state"] != "running":
            raise ContractError("resume did not start a fresh worker")
        wait_for(lambda: backend.details(name)["phase"] == "sampling")
        interrupted = backend.details(name)
        if interrupted["metrics"]["steps"] != 1:
            raise ContractError("fault must target the second, uncommitted episode")
        # Test-owned process only; the same identity guard as a controlled stop.
        backend._signal_owned(interrupted, signal.SIGKILL)
        failed = wait_for(lambda: (r if (r := backend.refresh(name))["state"] == "failed" and not alive(r) else None))
        failed_status = status(name)
        bad_resume = tool(trainer, "training.control", {"run_id": name, "operation": "resume",
                           "expected_revision": failed_status["revision"]}, expected=False)
        recovered = tool(trainer, "training.recover", {"run_id": name, "expected_revision": failed_status["revision"]})
        if recovered["result"]["execution"] != "applied":
            raise ContractError("explicit recovery did not validate the real checkpoint")
        action(name, "resume")
        finished = done(name)
        if finished["state"] != "completed" or finished["metrics"]["steps"] != 2:
            raise ContractError("recovered worker did not complete real update two")
        final = verified_trainer(state_root, finished)

        baseline_name = "continuous-duel"
        tool(trainer, "training.prepare", {"run_id": baseline_name})
        action(baseline_name, "start")
        baseline_row = done(baseline_name)
        baseline = verified_trainer(state_root, baseline_row)
        equivalent = (parameter_digest(final.model) == parameter_digest(baseline.model) and
                      [x["update"] for x in finished["updates"]] == [x["update"] for x in baseline_row["updates"]] and
                      torch.equal(final.policy_rng.get_state(), baseline.policy_rng.get_state()) and
                      torch.equal(final.batch_rng.get_state(), baseline.batch_rng.get_state()))
        if not equivalent:
            raise ContractError("paused/crashed/resumed run diverged from actual continuous training")

        stopped_name = "stopped-duel"
        tool(trainer, "training.prepare", {"run_id": stopped_name})
        action(stopped_name, "start")
        stopped = action(stopped_name, "stop")
        if not stopped["local_process_exited"] or stopped["cloud_billing_stopped"]:
            raise ContractError("local stop must exit its process and cannot claim cloud billing stopped")

        budget_name = "wall-budget-duel"
        backend.prepare(budget_name, wall_limit_seconds=2.)
        action(budget_name, "start")
        capped = done(budget_name)
        if capped["state"] != "stopped" or capped["reason"] != "kernel_wall_budget_exhausted" or capped["metrics"]["steps"] >= 2:
            raise ContractError("kernel wall budget did not stop unfinished real CPU work")

        # A valid-length/valid-hash file with a wrong version must fail before
        # launch, rather than falling back to an unverified model.
        wrong_name = "wrong-version-duel"
        tool(trainer, "training.prepare", {"run_id": wrong_name})
        wrong = backend.details(wrong_name)
        path = Path(state_root) / "runs" / wrong_name / "checkpoints/local-step-0.weights"
        state = torch.load(path, weights_only=True)
        state["binding"] = dict(state["binding"], python_implementation_sha256="0" * 64)
        with path.open("wb") as output:
            torch.save(state, output)
        from .local_training import checkpoint_receipt
        path.with_suffix(".json").write_text(canonical_json(checkpoint_receipt(wrong_name, path, 0)) + "\n")
        wrong_response = tool(trainer, "training.control", {"run_id": wrong_name, "operation": "start", "expected_revision": wrong["revision"]}, expected=False)
        if backend.details(wrong_name)["pid"] is not None:
            raise ContractError("incompatible version unexpectedly launched a worker")

        return {"source": "real-native-cpu-training-and-owned-process-fault-injection", "ok": True,
                "initial_checkpoint": initial, "paused_checkpoint": checked, "pause_ack": paused, "stop_ack": stopped,
                "restart_from_model_sha256": restart_from_hash, "final_model_sha256": parameter_digest(final.model),
                "continuous_final_model_sha256": parameter_digest(baseline.model), "continuous_recovery_equal": equivalent,
                "interrupted_worker_fault": "SIGKILL test-owned sampling process; no incomplete episode counted",
                "failed_checkpoint_preserved": failed["checkpoint_ids"][-1], "resume_without_recovery_rejected": not bad_resume["ok"],
                "final_status": status(name), "final_history": finished["history"], "actual_updates": finished["updates"],
                "continuous_updates": baseline_row["updates"], "kernel_budget_status": status(budget_name),
                "kernel_budget_reason": capped["reason"], "wrong_version_rejected_before_launch": not wrong_response["ok"],
                "version_fault_source": "explicit checkpoint-binding mutation with recomputed artifact receipt; negative fixture",
                "opponent_control_denied": True, "transcript": transcript,
                "cloud_resource_control_implemented": False, "cloud_billing_stop_verified": False}
    finally:
        # Only these prepared test jobs can be touched, and all have kernel
        # timers even if this host exits unexpectedly.
        for name in ("controlled-duel", "continuous-duel", "stopped-duel", "wall-budget-duel"):
            try:
                row = backend.refresh(name)
                if alive(row):
                    backend.control(run_id=name, operation="stop", expected_revision=row["revision"], request_id="acceptance-cleanup")
            except (ContractError, OSError):
                pass


def paired_hidden_information_check(root, trainer):
    """Two actual native hidden worlds, identical player features/predictions."""
    import torch
    from .native import NativeNormalEngine
    profile = read_json(ROOT / "configs/effect-duel-v1.json")
    variant = copy.deepcopy(profile)
    opponent = variant["decks"][1]
    variant["decks"][1] = opponent[17:] + opponent[:17]
    batches, outputs, private_hands = [], [], []
    trainer.model.eval()
    for candidate in (profile, variant):
        with NativeNormalEngine(root, scenario="effect-duel", deck_profile=candidate, seed=1724) as engine:
            request = engine.next_decision()
            if request.observation.observer != 0 or request.context.seed is not None:
                raise ContractError("privacy pair must start from the same legal player seat")
            for card in request.observation.cards:
                if card.visibility == "hidden" and any(x is not None for x in (card.card_id, card.attack, card.defense)):
                    raise ContractError("hidden identity/stats reached the player DTO")
                if card.zone == "deck":
                    raise ContractError("deck order reached the player DTO")
            # Controller-only assertion. Neither identities nor this audit are
            # returned to the policy/opponent tools.
            private_hands.append([engine._query(1, 2, i, 1)[0] for i in range(engine._count(1, 2))])
            batch = trainer.encoder.batch([request])
            batches.append(batch)
            with torch.no_grad():
                outputs.append(trainer.model(batch))
    worlds_differ = private_hands[0] != private_hands[1]
    equal = all(torch.equal(batches[0][k], batches[1][k]) for k in batches[0])
    predictions_equal = all(torch.equal(a, b) for a, b in zip(outputs[0], outputs[1]))
    if not worlds_differ or not equal or not predictions_equal:
        raise ContractError("actual hidden-world privacy comparison failed")
    return {"source": "two-real-core-initial-worlds", "hidden_hands_actually_differ": True,
            "legal_player_encodings_equal": True, "policy_and_value_equal": True,
            "private_identities_returned_to_policy": False, "games_completed": 0}


def run_engineering_acceptance(root, state_root, run_id):
    from .local_training import verified_trainer
    from .model_group import group_binding
    from .build_pipeline import BuildAssets
    from .agent_registry import identifier
    identifier(run_id)
    if len(run_id) > 24:
        raise ContractError("acceptance run ID exceeds bounded suffix budget")
    state_root = Path(state_root).resolve()
    run = state_root / "runs" / run_id
    if run.exists():
        raise ContractError("acceptance run exists; choose a new ID")
    plan = read_json(ROOT / "configs/training-plan-v1.json")
    preflight = cpu_preflight(root, plan)
    if not preflight["ok"]:
        raise ContractError("CPU acceptance preflight failed; no success or worker invented")
    from .lora_group import run_lora_group_smoke
    reporter = RunReporter(state_root)
    snapshot = {"schema_version": 1, "run_id": run_id, "state": "running", "revision": 0,
                "model_versions": {r: "supported-engineering-prototype-v1" for r in ("duel", "build_goal", "build_optimizer", "coordinator")},
                "metrics": reporter.resources(), "checkpoint_ids": [], "source": "trainer"}
    reporter.publish(snapshot)
    try:
        task = BuildTask.from_dict(read_json(ROOT / "configs/build-engineering-v1.json"))
        policy = FeedbackPolicy.from_dict(read_json(ROOT / "configs/coordinator-feedback-engineering.json"))
        lora = run_lora_group_smoke(root, state_root, run_id + "-lora", task,
                                    read_json(ROOT / "configs/lora-engineering-v1.json"), policy)
        controls = control_acceptance(root, run / "local-control")
        local = LocalCpuBackend(run / "local-control", root)
        trainer = verified_trainer(run / "local-control", local.details("controlled-duel"))
        privacy = paired_hidden_information_check(root, trainer)
        if lora["binding"] != group_binding(task, BuildAssets(root), policy):
            raise ContractError("whole-flow implementation/resources changed during acceptance")
        budget = BudgetBook(run / "cpu-usage.sqlite3", plan, role="trainer", source="host_reported_unverified", create=True)
        measured = reporter.resources()
        budget.record({"event_id": "bounded-cpu-acceptance", "stage_id": "throughput-small-train", "gpu_count": 0,
                       "wall_seconds": measured["elapsed_seconds"], "activity": "train", "outcome": "completed",
                       "amount": None, "currency": None, "expected_revision": 0})
        verdicts = {"real_rule_engine_to_four_trainable_prototypes": lora["ok"],
                    "actual_lora_freeze_update_rollback_restore": lora["restore_verified"],
                    "json_local_start_pause_save_resume": controls["pause_ack"]["local_process_exited"],
                    "real_worker_crash_and_exact_recovery": controls["continuous_recovery_equal"],
                    "kernel_wall_budget_and_local_stop": controls["kernel_budget_reason"] == "kernel_wall_budget_exhausted",
                    "hidden_world_isolation": privacy["legal_player_encodings_equal"],
                    "version_mismatch_fails_before_launch": controls["wrong_version_rejected_before_launch"],
                    "credential_free_preflight_and_handoff_inputs": preflight["ok"]}
        if not all(verdicts.values()):
            raise ContractError("mandatory bounded engineering-chain acceptance did not pass")
        result = {"schema_version": 1, "ok": True, "scope": "bounded-supported-engineering-chain-with-explicit-fault-tests",
                  "full_phase_1_delivered": False, "formal_training_ready": False, "competitive_ability_validated": False,
                  "required_engineering_verdicts": verdicts, "preflight": preflight, "lora": lora,
                  "local_training_control": controls, "hidden_information_check": privacy, "cpu_budget": budget.status(),
                  "metrics": reporter.resources(), "paid_instances_started": 0, "external_provider_calls": 0,
                  "external_validation_pending": ["CodeBuddy/DeepSeek actual model and constrained host", "PC compatibility and hardware",
                                                   "user 3+8 decks and historical environment freezes", "formal statistical and capability evaluation"],
                  "remaining_phase_1_engineering": ["general protocol/regions and standard replay", "three-era facts/tags and dataset isolation",
                                                    "general goals/cross-retrieval and qualified bots/DSH", "general multi-model training controller and quality promotion"]}
        (run / "proof.json").write_text(canonical_json(result) + "\n")
        reporter.publish(dict(snapshot, state="completed", revision=1, metrics=reporter.resources()))
        return result
    except Exception:
        reporter.publish(dict(snapshot, state="failed", revision=1, metrics=reporter.resources()))
        raise
