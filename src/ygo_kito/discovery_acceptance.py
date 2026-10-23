"""Non-paid cloud CPU acceptance: MSG26, discovery, and real-source cycles."""
from contextlib import closing
import copy
from pathlib import Path
import resource
import signal
import time

from .agent_registry import identifier
from .build_contracts import BuildTask, DeckParts, digest
from .build_pipeline import BuildAssets
from .catalog_search import CatalogQuery, expand_pool, recall, recalled_edits
from .engineering_acceptance import wait_for
from .group_runner import snapshot
from .local_training import LocalCpuBackend, alive, verified_trainer, _connect, get_row, put_row
from .route_search import discover_goal, replay_discovered_goal
from .training_plan import BudgetBook
from .training_runner import atomic_json, file_receipt, read_artifact, sync_usage
from .unselect_case import run_unselect_case
from .validation import ContractError, read_json

ROOT = Path(__file__).resolve().parents[2]


def run_gap_case(assets, task, deck):
    raw = task.to_dict()
    raw["pool"] = sorted((set(raw["pool"]) - {11066358}) | {549481})
    raw["requirements"] = [r for r in raw["requirements"] if r["card_id"] != 11066358]
    initial_task = BuildTask.from_dict(raw)
    initial = DeckParts(tuple(sorted([c for c in deck.main if c != 11066358] + [549481] * 3)), deck.extra)
    before = discover_goal(initial_task, initial, assets, seconds=4., attempts=3, branch_budget=6)
    if before["status"] != "not_found_within_budget":
        raise ContractError("gap engineering case did not retain its unverified outcome")
    query = CatalogQuery(effect_terms=("特殊召唤",), theme_terms=("银河",), context_terms=("调整", "通常怪兽"),
                         preferred_level=2, preferred_type=0x1011, limit=8)
    hits = recall(initial_task, assets, query)
    # This engineering query illustrates a supplied public theme; it is not a
    # learned semantic gap parser. Proposal/ranking and core evidence stay apart.
    added = next((h for h in hits if h["card_id"] == 11066358), None)
    if added is None:
        raise ContractError("catalog query did not recall this engineering gap candidate")
    revised, revision = expand_pool(initial_task, assets, [added], gap="bounded route unverified; recall normal tuner for level-5 goal")
    proposals = recalled_edits(revised, initial, assets, [added], limit=1)
    if not proposals:
        raise ContractError("gap recall produced no legal hard-constraint-preserving edit")
    proof = discover_goal(revised, proposals[0], assets, seconds=20.)
    replay = replay_discovered_goal(revised, proposals[0], assets, proof)
    return {"initial_task": initial_task.to_dict(), "initial_deck": initial.to_dict(), "initial_probe": before,
            "cross_recall": hits, "revision": revision, "revised_task": revised.to_dict(),
            "revised_deck": proposals[0].to_dict(), "proof": proof, "replay": replay}


def run_curriculum_cycles(root, directory):
    import torch
    recipe = read_json(ROOT / "configs/group-real-curriculum-v1.json")
    backend = LocalCpuBackend(directory / "host", root, recipe=recipe)
    name, baseline_name = "curriculum-recovered", "curriculum-continuous"
    controls = []
    def control(target, operation):
        row = backend.refresh(target)
        response = backend.control(run_id=target, operation=operation, expected_revision=row["revision"],
                                   request_id=f"curriculum-control-{len(controls)}")
        controls.append({"run_id": target, "operation": operation, "response": response})
        return response
    def finished(target):
        return wait_for(lambda: (r if (r := backend.refresh(target))["state"] != "running" and not alive(r) else None), seconds=295)
    try:
        backend.prepare(name)
        control(name, "start")
        # A real owned worker is killed during uncommitted PPO sampling, after
        # the real source, base warmup and construction updates are durable.
        wait_for(lambda: backend.details(name).get("active_stage") == "duel_train", seconds=110)
        lost = backend.details(name)
        committed = copy.deepcopy(lost["updates"])
        if lost["metrics"]["steps"] != 3:
            raise ContractError("fault did not target the intended committed construction boundary")
        backend._signal_owned(lost, signal.SIGKILL)
        failed = finished(name)
        if failed["state"] != "failed":
            raise ContractError("real worker loss was not recorded as failed")
        recovery_state = verified_trainer(backend.state_root, failed)
        if recovery_state.phase != "duel_train" or len(recovery_state.construction_state["consumed"]) != 4:
            raise ContractError("committed real-source consumption did not survive worker loss")
        backend.recover(name, failed["revision"])
        control(name, "resume")
        final_row = finished(name)
        if final_row["state"] != "completed" or final_row["updates"][:len(committed)] != committed:
            raise ContractError("resumed curriculum failed or repeated committed construction updates: " + str(final_row.get("failure_detail", final_row["reason"])))
        final = verified_trainer(backend.state_root, final_row)
        final_fingerprint, final_snapshot = final.training_fingerprint(), snapshot(final)
        backend.prepare(baseline_name)
        control(baseline_name, "start")
        baseline_row = finished(baseline_name)
        if baseline_row["state"] != "completed":
            raise ContractError("continuous real curriculum failed: " + str(baseline_row.get("failure_detail", baseline_row["reason"])))
        baseline = verified_trainer(backend.state_root, baseline_row)
        equal = (final_fingerprint == baseline.training_fingerprint() and final.events == baseline.events
                 and final.versions() == baseline.versions() and final.host.state_digest() == baseline.host.state_digest())
        if not equal:
            raise ContractError("real-curriculum recovery differs from continuous weights/optimizers/RNG/events/ledger")
        book = BudgetBook(backend.state_root / "cpu-usage.sqlite3", final_row["budget_plan"])
        history = book.history()
        with closing(_connect(backend.state_root)) as db, db:
            row = get_row(db, name)
            for entry in row["usage_outbox"]:
                entry["exported"] = False
            put_row(db, row)
        sync_usage(backend.state_root, name); sync_usage(backend.state_root, name)
        if book.history() != history:
            raise ContractError("curriculum recovery/retry duplicated the usage ledger")
        construction = final.construction_state
        run = backend.state_root / "runs" / name
        comparison_cases = sum(len(read_artifact(run, receipt)["comparison"]["games"]) for receipt in
            [construction["train_artifact"], *(m["artifact"] for m in construction["validation"])])
        result = {"source": final.data["source"], "supervision_sha256": final.data["supervision_sha256"],
                  "final_snapshot": final_snapshot, "events": final.events, "construction_state": construction,
                  "duel_data_marks": final.data_marks, "frozen_evaluations": final.evaluations,
                  "actual_updates": final_row["updates"], "recovered_equals_continuous": equal,
                  "failure_phase": "duel_train", "pre_fault_committed_updates": len(committed),
                  "committed_source_not_regenerated": len(list((backend.state_root / "runs" / name / "data/construction_train").glob("*.json"))) == 1,
                  "validation_never_training_labels": all(m["partition"] == "construction_train" for m in construction["consumed"]),
                  "usage_reconciliation_idempotent": True, "usage_ledger": book.status(), "usage_history": book.history(),
                  "canonical_optimizer_calls": len(final_row["updates"]),
                  "confirmed_physical_optimizer_calls": sum(len(r["updates"]) for r in (final_row, baseline_row)),
                  "physical_training_episodes_committed": sum(r["metrics"]["episodes"] for r in (final_row, baseline_row)),
                  "physical_frozen_neural_evaluation_episodes": sum(r["metrics"]["validation_episodes"] for r in (final_row, baseline_row)),
                  "uncommitted_sampling_after_loss": "discarded; partial rollout not reused; completion unknown",
                  "final_status": backend.status(name), "continuous_status": backend.status(baseline_name), "controls": controls,
                  "worker_resource_metrics": [{k: r.get(k) for k in ("active_seconds", "completed_worker_cpu_seconds", "metrics")} for r in (final_row, baseline_row)],
                  "construction_comparison_cases_per_run": comparison_cases, "comparison_replays_count_as_new_samples": False,
                  "on_policy_data_source": "only fresh real actor DTO rollouts; construction labels never PPO",
                  "formal_training_ready": False, "competitive_ability_validated": False, "cloud_billing_stopped": False}
        if not result["committed_source_not_regenerated"]:
            raise ContractError("committed comparison source was regenerated during recovery")
        atomic_json(directory / "curriculum-proof.json", result)
        return result
    finally:
        for target, child in backend.children.items():
            row = backend.details(target)
            if alive(row):
                backend._signal_owned(row, signal.SIGKILL)
            child.wait(timeout=5)
            backend.refresh(target)


def run_discovery_acceptance(root, state_root, run_id):
    import torch
    from .cpu_training import cpu_name
    identifier(run_id)
    root = Path(root).resolve()
    assets = BuildAssets(root)
    torch.set_num_threads(1)
    directory = Path(state_root).resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    started, cpu = time.monotonic(), time.process_time()
    artifacts = []
    def write(name, value):
        path = directory / name
        atomic_json(path, value)
        artifacts.append(file_receipt(path, directory))
    summary, trace = run_unselect_case(root)
    verified, _ = run_unselect_case(root, replay=trace)
    write("unselect-private-audit.json", trace)
    profile = read_json(ROOT / "configs/extra-material-engineering-v2.json")
    discoveries = []
    for kind in ("extra", "xyz"):
        task = BuildTask.from_dict(read_json(ROOT / f"configs/build-{kind}-discovery-v3.json"))
        deck = DeckParts(tuple(profile["decks"][0]), (task.goal["card_id"],))
        proof = discover_goal(task, deck, assets, seconds=20.)
        replay = replay_discovered_goal(task, deck, assets, proof)
        write(f"discovered-{kind}.json", proof)
        discoveries.append({"goal": task.goal, "proof": proof, "replay": replay})
        if kind == "extra":
            gap = run_gap_case(assets, task, deck)
            write("gap-recall.json", gap)
    curriculum = run_curriculum_cycles(root, directory)
    artifacts.append(file_receipt(directory / "curriculum-proof.json", directory))
    result = {"schema_version": 1, "ok": True, "source": "real-core-msg26-public-search-real-curriculum-cpu",
              "unselect": summary, "unselect_replay": verified, "discoveries": discoveries,
              "gap_recall": {"initial_status": gap["initial_probe"]["status"], "revised_status": gap["proof"]["status"],
                             "task_revision": gap["revision"], "replay": gap["replay"]},
              "curriculum": curriculum, "artifacts": artifacts,
              "resources": {"cpu": cpu_name(), "torch": str(torch.__version__), "torch_threads": torch.get_num_threads(),
                  "parent_wall_seconds": time.monotonic() - started, "parent_cpu_seconds": time.process_time() - cpu,
                  "parent_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  "workers_peak_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
                  "formal_gpu_throughput": None, "live_quota_reader_available": False},
              "gates": {"full_phase_1_delivered": False, "phase_1A_passed": False, "phase_1B_passed": False,
                        "formal_training_ready": False, "competitive_ability_validated": False, "pc_validated": False},
              "external_provider_calls": 0, "paid_training_started": False, "cloud_billing_stopped": False}
    atomic_json(directory / "proof.json", result)
    return result
