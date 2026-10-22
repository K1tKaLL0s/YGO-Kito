"""Two-cycle real CPU proof: pause, evaluation crash and stage-budget recovery."""

from contextlib import closing
import copy
from pathlib import Path
import signal
import time

from .agent_bridge import AgentBridge
from .agent_registry import identifier
from .build_contracts import digest
from .engineering_acceptance import wait_for
from .group_runner import snapshot, tree_digest, validate_recipe
from .local_training import LocalCpuBackend, alive, verified_trainer, _connect, get_row, put_row
from .training_plan import BudgetBook
from .training_runner import atomic_json, sync_usage
from .validation import ContractError

ROOT = Path(__file__).resolve().parents[2]


def run_group_acceptance(root, state_root, run_id, recipe):
    import torch
    from .cpu_training import cpu_name
    identifier(run_id)
    recipe = validate_recipe(recipe)
    if recipe["max_updates"] != 2 or recipe["wall_seconds"] > 180 or recipe["stages_per_worker"] < 13:
        raise ContractError("group acceptance only runs two short CPU cycles within 180 active seconds per run")
    from .native_assets import verify_resources
    verify_resources(Path(root).resolve())  # Preserve the real missing-resource error before tool wrapping.
    directory = Path(state_root).resolve() / "experiments" / run_id
    if directory.exists():
        raise ContractError("group acceptance identity exists; preserve previous artifacts")
    directory.mkdir(parents=True)
    host = directory / "host"
    backend = LocalCpuBackend(host, root, recipe=recipe)
    backends = [backend]
    bridge = AgentBridge(ROOT, host, root, role="trainer", training_backend=backend)
    transcript = []
    started, cpu = time.monotonic(), time.process_time()
    name = "group-interrupted"

    def tool(method, params, *, expected=True, ident=None):
        request = {"schema_version": 1, "id": ident or f"group-proof-{len(transcript)}", "method": method, "params": params}
        response = bridge.dispatch(request)
        transcript.append({"request": request, "response": response})
        if response["ok"] != expected:
            raise ContractError("group acceptance " + method + ": " + response.get("error", {}).get("code", "unexpected_result") +
                                ": " + response.get("error", {}).get("message", "outcome differs"))
        return response

    def action(target, operation):
        current = backend.status(target)
        response = tool("training.control", {"run_id": target, "operation": operation, "expected_revision": current["revision"]})
        if response["result"]["execution"] != "applied":
            raise ContractError("group control outcome was not confirmed applied")
        return response["result"]["backend_result"]

    def finished(target, manager=backend):
        return wait_for(lambda: (r if (r := manager.refresh(target))["state"] != "running" and not alive(r) else None), seconds=90)

    try:
        initial = tool("training.prepare", {"run_id": name})["result"]
        if initial["metrics"]["optimizer_updates"] != 0 or len(initial["model_versions"]) != 4:
            raise ContractError("initial four models must not count as training")
        action(name, "start")
        wait_for(lambda: backend.details(name).get("active_stage") == "duel_train", seconds=45)
        paused = action(name, "pause")
        paused_row = backend.details(name)
        paused_state = verified_trainer(host, paused_row)
        if paused_state.phase != "coordinator_train" or paused_state.updates != 4 or not paused["local_process_exited"]:
            raise ContractError("pause must preserve the actual mixed-role stage boundary")
        paused_snapshot = snapshot(paused_state)
        manual = action(name, "save_checkpoint")
        action(name, "resume")
        wait_for(lambda: backend.details(name).get("active_stage") == "evaluate" and backend.details(name)["phase"] == "validating", seconds=30)
        lost = backend.details(name)
        updates_before_fault = copy.deepcopy(lost["updates"])
        backend._signal_owned(lost, signal.SIGKILL)
        failed = finished(name)
        tool("training.control", {"run_id": name, "operation": "resume", "expected_revision": failed["revision"]}, expected=False)
        recovered = tool("training.recover", {"run_id": name, "expected_revision": failed["revision"]})
        if recovered["result"]["execution"] != "applied":
            raise ContractError("group recovery did not apply")
        restored = verified_trainer(host, backend.details(name))
        if restored.phase != "evaluate" or restored.updates != 5 or backend.details(name)["updates"] != updates_before_fault:
            raise ContractError("group fault recovery repeated/lost committed model updates")
        action(name, "resume")
        final_row = finished(name)
        if final_row["state"] != "completed":
            raise ContractError("group recovered run failed: " + str(final_row.get("failure_detail", final_row["reason"])))
        final = verified_trainer(host, final_row)
        final_fingerprint = final.training_fingerprint()
        final_versions = final.versions()
        final_ledger = final.host.state_digest()

        baseline_name = "group-continuous"
        tool("training.prepare", {"run_id": baseline_name})
        action(baseline_name, "start")
        baseline_row = finished(baseline_name)
        if baseline_row["state"] != "completed":
            raise ContractError("group continuous run failed: " + str(baseline_row.get("failure_detail", baseline_row["reason"])))
        baseline = verified_trainer(host, baseline_row)
        equal = (final_fingerprint == baseline.training_fingerprint() and final.events == baseline.events
                 and final_versions == baseline.versions() and final_ledger == baseline.host.state_digest())
        if not equal:
            raise ContractError("four-model stage recovery differs from continuous models/optimizers/RNG/evaluation/ledger")

        # A host-selected stage slice stops after the second frozen evaluation,
        # keeping the same total active budget. Explicit resume only does feedback.
        sliced_recipe = dict(recipe, stages_per_worker=12)
        sliced = LocalCpuBackend(host, root, recipe=sliced_recipe)
        backends.append(sliced)
        sliced.prepare("group-stage-budget")
        sliced.control(run_id="group-stage-budget", operation="start", expected_revision=0, request_id="slice-start")
        slice_row = finished("group-stage-budget", sliced)
        if slice_row["state"] != "paused" or slice_row["reason"] != "worker_stage_budget_reached" or slice_row["metrics"]["steps"] != 12:
            raise ContractError("group stage budget did not stop at its durable boundary")
        slice_versions = dict(slice_row["model_versions"])
        slice_updates = copy.deepcopy(slice_row["updates"])
        active_before = slice_row["active_seconds"]
        sliced.control(run_id="group-stage-budget", operation="resume", expected_revision=slice_row["revision"], request_id="slice-resume")
        slice_final_row = finished("group-stage-budget", sliced)
        slice_final = verified_trainer(host, slice_final_row)
        slice_equal = (slice_final_row["state"] == "completed" and slice_versions == slice_final.versions() == final_versions
                       and slice_updates == slice_final_row["updates"] and slice_final_row["active_seconds"] >= active_before
                       and slice_final_row["wall_limit_seconds"] == recipe["wall_seconds"])
        if not slice_equal:
            raise ContractError("budget resume changed trained weights, repeated updates or reset the active budget")

        book = BudgetBook(host / "cpu-usage.sqlite3", final_row["budget_plan"])
        before = book.history()
        with closing(_connect(host)) as db, db:
            row = get_row(db, name)
            for event in row["usage_outbox"]:
                event["exported"] = False
            put_row(db, row)
        for _ in range(3):
            sync_usage(host, name)
            backend.status(name)
        if book.history() != before:
            raise ContractError("group usage outbox retry duplicated a worker segment")

        states = (final_row, baseline_row, slice_final_row)
        physical_updates = sum(len(r["updates"]) for r in states)
        training_games = sum(r["metrics"]["episodes"] for r in states)
        eval_games = sum(r["metrics"]["validation_episodes"] for r in states)
        result = {"schema_version": 1, "ok": True, "source": "real-core-four-model-alternating-cpu",
            "recipe": recipe, "binding": final_row["binding"], "transcript": transcript, "initial_status": initial,
            "pause_ack": paused, "paused_stage_snapshot": paused_snapshot, "manual_checkpoint_ack": manual,
            "fault_phase": lost["active_stage"], "fault_committed_stages": lost["metrics"]["steps"],
            "updates_before_fault": updates_before_fault, "updates_after_final": final_row["updates"],
            "final_snapshot": snapshot(final), "continuous_snapshot": snapshot(baseline),
            "continuous_recovery_equal": equal, "final_training_fingerprint": final_fingerprint,
            "final_ledger_state_sha256": final_ledger, "events": final.events, "consumed_stage_markers": final.consumed,
            "data_marks": final.data_marks, "evaluations": final.evaluations,
            "role_base_sha256": {r: s.verify_base() for r, s in final.sessions.items()},
            "role_adapters": {r: {"updates": s.updates, "version_id": s.version_id(), "compatibility": s.compatibility()} for r, s in final.sessions.items()},
            "stage_budget_status": snapshot(slice_final), "stage_budget_pause": {"state": slice_row["state"], "reason": slice_row["reason"],
                "cursor_step": slice_row["metrics"]["steps"], "active_seconds": active_before},
            "stage_budget_resume_equal": slice_equal, "total_budget_unchanged": True,
            "usage_reconciliation_idempotent": True, "usage_ledger": book.status(), "usage_history": book.history(),
            "final_status": backend.status(name), "continuous_status": backend.status(baseline_name),
            "stage_budget_final_status": sliced.status("group-stage-budget"),
            "confirmed_physical_optimizer_calls": physical_updates, "committed_training_games": training_games,
            "committed_frozen_evaluation_games": eval_games,
            "uncommitted_evaluation_completion": "unknown_after_worker_loss_not_counted", "discarded_optimizer_calls": 0,
            "resources": {"cpu": cpu_name(), "torch": str(torch.__version__), "torch_threads": torch.get_num_threads(),
                "parent_wall_seconds": time.monotonic() - started, "parent_process_cpu_seconds": time.process_time() - cpu,
                "interrupted_worker_cpu_seconds": None, "formal_gpu_throughput": None, "process_tree_peak_rss_bytes": None},
            "external_provider_calls": 0, "gpu_hours_used": 0, "cloud_billing_stopped": False,
            "formal_training_ready": False, "full_phase_1_delivered": False, "competitive_ability_validated": False}
        atomic_json(directory / "proof.json", result)
        return result
    finally:
        for manager in backends:
            for target, child in manager.children.items():
                row = manager.details(target)
                if alive(row):
                    manager._signal_owned(row, signal.SIGKILL)
                child.wait(timeout=5)
                manager.refresh(target)
        bridge.close()
