"""Repeatable, non-paid CPU acceptance for extra protocol and real feedback data.

This is a bounded engineering command, not the long training runner, a cloud
lifecycle controller, a user-deck benchmark, or permission to launch paid work.
"""
import hashlib
import json
from pathlib import Path
import platform
import resource
import time

import torch

from .agent_registry import identifier
from .build_contracts import BuildTask, DeckParts, digest
from .build_feedback import compare_candidates, real_game_dataset
from .build_pipeline import BuildAssets, apply_changes, deck_changes, verify_goal
from .build_training import BuildTrainer, BuildTrainingConfig, binding_for, load_checkpoint, save_checkpoint
from .contracts import ActionSelection
from .cpu_training import cpu_name
from .effect_duel import run_effect_duel
from .extra_routes import profile_for, verify_extra_goal
from .native import NativeNormalEngine
from .normal_duel import request_digest
from .validation import ContractError, canonical_json, fields, integer


def equal_state(first, second):
    if isinstance(first, torch.Tensor):
        return isinstance(second, torch.Tensor) and torch.equal(first, second)
    if isinstance(first, dict):
        return isinstance(second, dict) and first.keys() == second.keys() and all(equal_state(v, second[k]) for k, v in first.items())
    if isinstance(first, (list, tuple)):
        return type(first) is type(second) and len(first) == len(second) and all(equal_state(a, b) for a, b in zip(first, second))
    return first == second


def audit_player_views(root, trace):
    """Internal audit. Never return the engine handle or seed to a policy."""
    counts, material_counts, windows = set(), set(), 0
    with NativeNormalEngine(root, scenario="effect-duel", deck_profile=trace["profile"], seed=trace["seed"]) as engine:
        request = engine.next_decision()
        for row in trace["responses"]:
            if request is None or request_digest(request) != row["request_sha256"]:
                raise ContractError("view audit replay request differs")
            for observer in (0, 1):
                view = engine._observation(observer)
                for card in view.cards:
                    if card.visibility == "hidden" and any(v is not None for v in (card.card_id, card.owner, card.attack, card.defense)):
                        raise ContractError("view audit found hidden identity/owner/stat leakage")
                    if card.visibility == "observer" and card.controller != observer:
                        raise ContractError("view audit found another player's private card")
                    if card.zone == "extra" and card.controller != observer and card.visibility != "public" and card.card_id is not None:
                        raise ContractError("view audit found hidden extra identity")
                    if card.zone == "overlay":
                        host = next((c for c in view.cards if c.ref == card.attached_to), None)
                        if host is None or host.visibility == "hidden" or host.controller != card.controller:
                            raise ContractError("view audit material host differs")
                        counts.add((card.card_id, card.owner))
                    if card.material_count is not None and card.card_id == 78156759:
                        material_counts.add(card.material_count)
                windows += 1
            engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, row["action_id"]))
            request = engine.next_decision()
        if request is not None or engine.events != trace["events"] or engine.outcome != trace["outcome"]:
            raise ContractError("view audit replay events/outcome differ")
    return {"both_player_windows": windows, "no_hidden_identity_owner_stats": True,
            "visible_material_identity_owner_pairs": sorted(counts, key=lambda pair: (pair[0], -1 if pair[1] is None else pair[1])),
            "xyz_material_counts_observed": sorted(material_counts)}


def run_extra_feedback_acceptance(root, state_root, run_id):
    identifier(run_id)
    started, cpu_started = time.monotonic(), time.process_time()
    project = Path(__file__).resolve().parents[2]
    root = Path(root).resolve()
    assets = BuildAssets(root)  # Fails before creating a run directory if resources are absent.
    directory = Path(state_root).resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    artifacts = []

    def write(name, value):
        path = directory / name
        with path.open("x", encoding="utf-8") as handle:
            handle.write(canonical_json(value) + "\n")
        return register(path)

    def register(path):
        artifacts.append({"path": str(path.relative_to(directory)), "bytes": path.stat().st_size,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        return artifacts[-1]

    profile = json.loads((project / "configs/extra-material-engineering-v2.json").read_text())
    routes, full_games = [], []
    for kind, preference in (("extra", "first"), ("extra", "last"), ("xyz", "first")):
        task = BuildTask.from_dict(json.loads((project / f"configs/build-{kind}-engineering-v2.json").read_text()))
        deck = DeckParts(tuple(profile["decks"][0]), (task.goal["card_id"],))
        proof = verify_extra_goal(task, deck, assets, material_preference=preference)
        if proof["status"] != "verified_success":
            raise ContractError("extra route remained unknown/unsupported; acceptance cannot pass")
        write(f"route-{kind}-{preference}.json", proof)
        routes.append({"goal": task.goal["kind"], "status": proof["status"], "trajectory_sha256": proof["trajectory_sha256"],
                       "sum_selected_card_ids": [s["chosen_card_ids"] for s in proof["route_evidence"]["sum_choices"]]})
        summary, trace = run_effect_duel(root, profile_for(deck), seed=proof["core_attempts"][-1]["seed_audit_only"],
                                         route_task=task, option_preference=preference, budget_seconds=30.)
        replay, replayed = run_effect_duel(root, {}, replay=trace, budget_seconds=30.)
        if replayed != trace or not replay["replay_verified"] or not summary["conditional_route_verified"]:
            raise ContractError("full routed extra game replay failed")
        views = audit_player_views(root, trace)
        write(f"game-{kind}-{preference}.json", trace)
        full_games.append({"goal": task.goal["kind"], "preference": preference, "turns": summary["turns"],
                           "outcome": summary["outcome"], "decisions": summary["decisions"],
                           "prompt_counts": summary["prompt_counts"], "trace_sha256": digest(trace),
                           "exact_replay": True, "player_view_audit": views, "metrics": summary["metrics"]})
    if routes[0]["sum_selected_card_ids"] == routes[1]["sum_selected_card_ids"]:
        raise ContractError("sum preference did not exercise two distinct material choices")
    if not {0, 1, 2} <= set(full_games[-1]["player_view_audit"]["xyz_material_counts_observed"]):
        raise ContractError("real Xyz attach/detach observation transitions were not exercised")

    config = fields(json.loads((project / "configs/build-real-feedback-v1.json").read_text()),
                    {"schema_version", "source", "task_file", "candidates", "opponent", "paired_seeds", "actor_seats",
                     "driver", "purpose", "independent_ability_evaluation"})
    integer(config["schema_version"], "real feedback config", 1, 1)
    if (config["source"] != "engineering_fixture_not_user_decks" or config["actor_seats"] != [0, 1]
            or config["independent_ability_evaluation"] is not False or config["purpose"] != "construction_train"
            or config["task_file"] != "configs/build-real-feedback-task-v2.json"
            or config["driver"] != "visible-dto-effect-protocol-baseline-v1"):
        raise ContractError("engineering feedback configuration boundary differs")
    task = BuildTask.from_dict(json.loads((project / config["task_file"]).read_text()))
    candidates = [DeckParts.from_dict(d) for d in config["candidates"]]
    opponent = DeckParts.from_dict(config["opponent"])
    comparison, traces = compare_candidates(task, assets, candidates, opponent, seeds=tuple(config["paired_seeds"]))
    write("comparison.json", comparison)
    for i, trace in enumerate(traces):
        write(f"comparison-game-{i}.json", trace)
    data = real_game_dataset(task, assets, comparison)
    write("construction-train-data.json", data)
    trainer = BuildTrainer(task, assets, BuildTrainingConfig())
    config_hash = task.sha256
    def rank_scores(instance):
        model = instance.models["build_optimizer"].eval()
        with torch.no_grad():
            return model(instance.encoder.batch(task, candidates)).tolist()

    before_scores = rank_scores(trainer)
    updates = [trainer.step(data)]
    binding = binding_for(task, assets, data)
    first = save_checkpoint(trainer, directory, "paired-feedback-step-1", binding)
    register(first)
    updates.append(trainer.step(data))
    after_scores = rank_scores(trainer)
    continuous = save_checkpoint(trainer, directory, "paired-feedback-step-2", binding)
    register(continuous)
    restored = load_checkpoint(first, assets, binding)
    recovered_update = restored.step(data)
    recovered = save_checkpoint(restored, directory, "paired-feedback-resumed-step-2", binding)
    register(recovered)
    left, right = [torch.load(path, map_location="cpu", weights_only=True) for path in (continuous, recovered)]
    if not equal_state(left, right):
        raise ContractError("paired goal/optimizer recovery differs in parameters, optimizer, scheduler, RNG or cursor")
    preferred = comparison["preferred_index"]
    worse = 1 - preferred
    if after_scores[preferred] - after_scores[worse] <= before_scores[preferred] - before_scores[worse]:
        raise ContractError("observed training-pair margin did not improve; no corrective update acceptance")
    selected = max(range(2), key=lambda index: after_scores[index])
    chosen = candidates[selected]
    retained = verify_goal(task, chosen, assets, attempts=64, seconds=30.)
    changes = deck_changes(candidates[0], chosen)
    if retained["status"] != "verified_success" or apply_changes(candidates[0], changes) != chosen or task.sha256 != config_hash:
        raise ContractError("ranked candidate lost the goal, legal constraints or replayable edits")
    write("selected-goal-revalidation.json", retained)
    model_parameters = {role: sum(p.numel() for p in model.parameters()) for role, model in trainer.models.items()}
    result = {"ok": True, "scope": "extra-material-and-real-paired-construction-cpu-engineering",
              "run_id": run_id, "engine": "real-pinned-core-and-upstream-scripts", "versions": assets.receipt,
              "routes": routes, "full_extra_games": full_games, "comparison": comparison,
              "training": {"data_source": data["source"], "supervision_sha256": data["supervision_sha256"],
                           "canonical_batches": trainer.batch_cursor, "canonical_optimizer_calls": sum(trainer.updates.values()),
                           "recovery_verification_optimizer_calls": len(recovered_update),
                           "total_executed_optimizer_calls": sum(len(batch) for batch in updates) + len(recovered_update),
                           "updates": updates, "recovery_updates": recovered_update, "checkpoint_state_exact_match": True,
                           "independent_parameters": model_parameters, "binding": binding,
                           "before_optimizer_scores": before_scores, "after_optimizer_scores": after_scores,
                           "training_pair_margin_improved": True, "model_selected_index": selected,
                           "agrees_with_observed_training_preference": selected == preferred,
                           "goal_sha256_unchanged": True, "selected_deck": chosen.to_dict(), "changes_from_candidate_0": changes,
                           "selected_goal_status": retained["status"], "on_policy_ppo_data_used": False,
                           "opponent_driver_trained_policy": False, "general_quality_learned": False},
              "artifacts": list(artifacts), "metrics": {"elapsed_seconds": time.monotonic() - started,
                    "cpu_seconds": time.process_time() - cpu_started, "process_peak_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    "cpu_name": cpu_name(), "torch_threads": torch.get_num_threads(), "python": platform.python_version(), "torch": str(torch.__version__)},
              "gates": {"full_phase_1_delivered": False, "formal_training_ready": False, "competitive_ability_validated": False,
                        "qualified_opponents": False, "pc_compatibility_validated": False, "external_provider_e2e_verified": False},
              "cloud_resource_billing_stop_confirmed": False, "quota_remaining": None, "stop_threshold_percent": 20}
    write("acceptance.json", result)
    return result
