"""Short real-engine CPU runner acceptance, including an owned-worker crash.

Deliberately not a 100h run, an ability benchmark or a paid-training readiness gate.
"""

from contextlib import closing
import hashlib
from pathlib import Path
import signal
import time

from .agent_bridge import AgentBridge
from .agent_registry import identifier
from .build_contracts import digest
from .engineering_acceptance import wait_for
from .local_training import LocalCpuBackend, alive, verified_trainer, _connect, get_row, put_row
from .training_plan import BudgetBook
from .training_runner import sync_usage, opponent_binding, atomic_json, validate_recipe
from .validation import ContractError, read_json

ROOT = Path(__file__).resolve().parents[2]


def run_runner_acceptance(root, state_root, run_id, recipe):
    import torch
    from .cpu_training import cpu_name
    from .duel_model import parameter_digest
    identifier(run_id)
    recipe = validate_recipe(recipe)
    if not 3 <= recipe["max_updates"] <= 8 or recipe["wall_seconds"] > 180:
        raise ContractError("acceptance only runs short 3..8 update CPU recipes within 180 seconds")
    directory = Path(state_root).resolve() / "experiments" / run_id
    if directory.exists():
        raise ContractError("runner acceptance identity already used; preserve its evidence")
    directory.mkdir(parents=True)
    host_root = directory / "host"
    backend = LocalCpuBackend(host_root, root, recipe=recipe)
    backends = [backend]
    trainer = AgentBridge(ROOT, host_root, root, role="trainer", training_backend=backend)
    transcript = []
    started, cpu_started = time.monotonic(), time.process_time()
    name = "multiround-duel"
    continuous_name = "continuous-duel"

    def tool(method, params, *, ident=None, expected=True):
        request = {"schema_version": 1, "id": ident or f"runner-{len(transcript)}", "method": method, "params": params}
        response = trainer.dispatch(request)
        transcript.append({"request": request, "response": response})
        if response["ok"] != expected:
            raise ContractError("runner acceptance JSON result differs: " + method)
        return response

    def control(target, operation):
        status = backend.status(target)
        result = tool("training.control", {"run_id": target, "operation": operation, "expected_revision": status["revision"]})
        if result["result"]["execution"] != "applied":
            raise ContractError("runner control did not apply")
        return result["result"]["backend_result"]

    def finished(target):
        def read():
            row = backend.refresh(target)
            return row if row["state"] != "running" and not alive(row) else None
        return wait_for(read, seconds=60)

    try:
        tool("training.prepare", {"run_id": name})
        start_request = {"run_id": name, "operation": "start", "expected_revision": 0}
        first = tool("training.control", start_request, ident="start-exactly-once")
        duplicate = tool("training.control", start_request, ident="start-exactly-once")
        if first != duplicate:
            raise ContractError("duplicate runner start was not idempotent")
        wait_for(lambda: backend.details(name)["phase"] == "sampling", seconds=30)
        paused = control(name, "pause")
        paused_row = backend.details(name)
        if paused_row["metrics"]["steps"] != 1 or not paused["local_process_exited"] or paused["cloud_billing_stopped"]:
            raise ContractError("runner pause did not preserve exactly the first real boundary")
        control(name, "resume")
        wait_for(lambda: backend.details(name)["phase"] == "sampling", seconds=30)
        interrupted = backend.details(name)
        backend._signal_owned(interrupted, signal.SIGKILL)
        failed = wait_for(lambda: (r if (r := backend.refresh(name))["state"] == "failed" and not alive(r) else None), seconds=30)
        tool("training.control", {"run_id": name, "operation": "resume", "expected_revision": failed["revision"]}, expected=False)
        recovery = tool("training.recover", {"run_id": name, "expected_revision": failed["revision"]})
        if recovery["result"]["execution"] != "applied":
            raise ContractError("runner explicit recovery did not apply")
        control(name, "resume")
        final_row = finished(name)
        if final_row["state"] != "completed" or final_row["metrics"]["steps"] != recipe["max_updates"]:
            raise ContractError("recovered multiround runner failed: " + final_row["reason"])
        final = verified_trainer(host_root, final_row)
        tool("training.prepare", {"run_id": continuous_name})
        control(continuous_name, "start")
        baseline_row = finished(continuous_name)
        if baseline_row["state"] != "completed":
            raise ContractError("continuous runner failed: " + baseline_row["reason"])
        baseline = verified_trainer(host_root, baseline_row)
        equal = (parameter_digest(final.model) == parameter_digest(baseline.model)
                 and [v["update"] for v in final_row["updates"]] == [v["update"] for v in baseline_row["updates"]]
                 and torch.equal(final.policy_rng.get_state(), baseline.policy_rng.get_state())
                 and torch.equal(final.batch_rng.get_state(), baseline.batch_rng.get_state())
                 and final.scheduler.state_dict() == baseline.scheduler.state_dict())
        val_equal = ([v["trajectory_sha256"] for v in final_row["validations"]]
                     == [v["trajectory_sha256"] for v in baseline_row["validations"]])
        if not equal or not val_equal:
            raise ContractError("multiround interruption/recovery or validation diverged")
        book = BudgetBook(host_root / "cpu-usage.sqlite3", final_row["budget_plan"])
        before = book.history()
        # Simulates loss of the outbox acknowledgement after the ledger committed.
        # The measured events themselves remain the actual worker measurements.
        with closing(_connect(host_root)) as db, db:
            row = get_row(db, name)
            for event in row["usage_outbox"]:
                event["exported"] = False
            put_row(db, row)
        for _ in range(3):
            sync_usage(host_root, name)
            backend.status(name)
        ledger_equal = before == book.history()
        if not ledger_equal:
            raise ContractError("usage reconciliation duplicated or changed actual usage")
        # A budget smaller than one complete round stops at its actual initial
        # boundary instead of starting an episode it cannot safely finish.
        budget_recipe = dict(recipe, wall_seconds=10.)
        budget_backend = LocalCpuBackend(host_root, root, recipe=budget_recipe)
        backends.append(budget_backend)
        budget_backend.prepare("budget-boundary")
        budget_backend.control(run_id="budget-boundary", operation="start", expected_revision=0, request_id="budget-start")
        budget_row = wait_for(lambda: (r if (r := budget_backend.refresh("budget-boundary"))["state"] != "running" and not alive(r) else None), seconds=20)
        if budget_row["state"] != "stopped" or budget_row["reason"] != "wall_budget_reserve_reached" or budget_row["metrics"]["steps"]:
            raise ContractError("runner failed its finite-budget safe boundary check")
        result = {"schema_version": 1, "ok": True, "source": "real-native-multiround-cpu-runner",
                  "recipe": recipe, "recipe_sha256": digest(recipe), "binding": final_row["binding"],
                  "run_id": run_id, "transcript": transcript, "pause_ack": paused,
                  "canonical_updates_per_run": final.updates, "independent_runs": 2,
                  "physical_committed_optimizer_calls": final.updates + baseline.updates,
                  "completed_training_games": len(final_row["updates"]) + len(baseline_row["updates"]),
                  "completed_validation_games": len(final_row["validations"]) + len(baseline_row["validations"]),
                  "discarded_episode_attempts": final_row["discarded_episodes"],
                  "final_model_sha256": parameter_digest(final.model), "continuous_model_sha256": parameter_digest(baseline.model),
                  "continuous_recovery_equal": equal, "validation_trajectory_recovery_equal": val_equal,
                  "train_opponent_binding_sha256": opponent_binding(final_row, "train"),
                  "validation_opponent_binding_sha256": opponent_binding(final_row, "validation"),
                  "actual_updates": final_row["updates"], "validations": final_row["validations"],
                  "round_journal": final_row["rounds"], "scheduled_checkpoint_ids": final_row["scheduled_checkpoint_ids"],
                  "usage_outbox": final_row["usage_outbox"], "usage_reconciliation_idempotent": ledger_equal,
                  "usage_ledger": book.status(), "usage_ledger_history": book.history(),
                  "budget_boundary_status": budget_backend.status("budget-boundary"),
                  "final_status": backend.status(name), "continuous_status": backend.status(continuous_name),
                  "resources": {"cpu": cpu_name(), "torch": str(torch.__version__), "torch_threads": torch.get_num_threads(),
                                "parent_wall_seconds": time.monotonic() - started, "parent_process_cpu_seconds": time.process_time() - cpu_started,
                                "peak_rss_scope": "individual_worker_peaks_in_status_not_process_tree_sum",
                                "interrupted_worker_cpu_seconds": None, "formal_gpu_throughput": None},
                  "external_provider_calls": 0, "gpu_hours_used": 0, "cloud_billing_stopped": False,
                  "formal_training_ready": False, "full_phase_1_delivered": False, "competitive_ability_validated": False}
        atomic_json(directory / "proof.json", result)
        return result
    finally:
        for host in backends:
            for target, child in host.children.items():
                row = host.details(target)
                if alive(row):
                    host._signal_owned(row, signal.SIGKILL)
                child.wait(timeout=5)
                host.refresh(target)
        trainer.close()
