"""Paired real-core BO1 comparisons for bounded construction supervision.

The frozen driver is an explicit visible-rule engineering baseline, NOT a
qualified opponent or a trained duel policy. Tiny descriptive results are not
competitive/causal ability acceptance and never label a lone loss as a defect.
Audit seeds, full opponent lists and replays never enter BuildEncoder features.
"""
import inspect
import math
import time

from .build_contracts import DeckParts, digest
from .deck_profile import validate_deck_parts
from .effect_duel import choose_effect_duel_action, run_effect_duel
from .extra_routes import profile_for
from .validation import ContractError, array, fields, integer, member

SOURCE = "real_core_paired_frozen_rule_driver_bo1_v1"
DRIVER = "visible-dto-effect-protocol-baseline-v1"


def driver_binding():
    return {"version": DRIVER, "implementation_sha256": digest(inspect.getsource(choose_effect_duel_action)),
            "type": "visible_rule_engineering_baseline", "trained_policy": False}


def plan_for(task, candidates, opponent, seeds, purpose):
    member(purpose, "comparison purpose", ("construction_train", "construction_validation"))
    if not isinstance(seeds, tuple) or not 2 <= len(seeds) <= 8 or len(set(seeds)) != len(seeds):
        raise ContractError("paired comparisons require two to eight distinct audit seeds")
    for seed in seeds:
        integer(seed, "comparison seed", 0, 2**32 - 8)
    if len(candidates) != 2 or not all(isinstance(d, DeckParts) for d in candidates) or candidates[0] == candidates[1]:
        raise ContractError("comparison requires two distinct typed candidates")
    return {"task_sha256": task.sha256, "candidates": [d.to_dict() for d in candidates],
            "opponent": opponent.to_dict(), "paired_seeds_audit_only": list(seeds), "actor_seats": [0, 1],
            "purpose": purpose, "format": "BO1_engineering_only", "driver": driver_binding(),
            "versions": task.environment["versions"]}


def outcome_score(outcome, actor_seat):
    if outcome["winner"] not in (0, 1, 2):
        raise ContractError("unknown real core outcome")
    return .5 if outcome["winner"] == 2 else float(outcome["winner"] == actor_seat)


def comparison_projection(comparison):
    return {k: v for k, v in comparison.items() if k != "comparison_sha256"}


def validate_comparison(task, assets, comparison):
    fields(comparison, {"source", "plan", "plan_sha256", "games", "mean_scores", "paired_differences",
                        "preferred_index", "status", "uncertainty", "opponent_qualification",
                        "competitive_ability_validated", "comparison_sha256"})
    plan = fields(comparison["plan"], {"task_sha256", "candidates", "opponent", "paired_seeds_audit_only", "actor_seats",
                                      "purpose", "format", "driver", "versions"})
    raw_candidates = array(plan["candidates"], "compared candidates")
    integer(len(raw_candidates), "compared candidate count", 2, 2)
    candidates = [DeckParts.from_dict(d) for d in raw_candidates]
    opponent = DeckParts.from_dict(plan["opponent"])
    expected = plan_for(task, candidates, opponent, tuple(array(plan["paired_seeds_audit_only"], "audit seeds")), plan["purpose"])
    if (comparison["source"] != SOURCE or plan != expected or digest(plan) != comparison["plan_sha256"]
            or comparison["competitive_ability_validated"] is not False):
        raise ContractError("comparison versions, driver or evidence boundary differs")
    for deck in candidates:
        assets.validate(task, deck)
    validate_deck_parts(opponent.to_dict(), assets.rows, assets.limits)
    expected_keys = {(candidate, seed, seat) for candidate in (0, 1) for seed in plan["paired_seeds_audit_only"] for seat in (0, 1)}
    found, scores = {}, [[], []]
    raw_games = array(comparison["games"], "paired games")
    integer(len(raw_games), "paired game count", len(expected_keys), len(expected_keys))
    for game in raw_games:
        fields(game, {"candidate_index", "seed_audit_only", "actor_seat", "outcome", "score", "turns", "decisions",
                      "trace_sha256", "profile_sha256", "core_terminal_received", "replay_verified"})
        key = (game["candidate_index"], game["seed_audit_only"], game["actor_seat"])
        if key not in expected_keys or key in found or any(type(x) is not int for x in key):
            raise ContractError("duplicate/missing/out-of-plan comparison game")
        index, seed, seat = key
        fields(game["outcome"], {"winner", "reason_code"})
        integer(game["outcome"]["winner"], "core winner", 0, 2)
        integer(game["outcome"]["reason_code"], "core win reason", 0, 255)
        integer(game["turns"], "complete turns", 1, 10000)
        integer(game["decisions"], "complete decisions", 1, 3000)
        profile = profile_for(candidates[index], opponent=opponent) if seat == 0 else profile_for(opponent, opponent=candidates[index])
        if task.goal['kind']=='deck_constraints':profile['adapter_revision']=5
        if (game["profile_sha256"] != digest(profile) or game["core_terminal_received"] is not True or game["replay_verified"] is not True
                or type(game["score"]) not in (int, float) or game["score"] != outcome_score(game["outcome"], seat)):
            raise ContractError("comparison game does not match the frozen pairing or natural outcome")
        if not isinstance(game["trace_sha256"], str) or len(game["trace_sha256"]) != 64:
            raise ContractError("comparison trace fingerprint missing")
        found[key] = game["score"]
        scores[index].append(game["score"])
    if set(found) != expected_keys:
        raise ContractError("incomplete paired comparison cannot produce an optimization label")
    means = [sum(s) / len(s) for s in scores]
    differences = [found[(1, seed, seat)] - found[(0, seed, seat)] for seed in plan["paired_seeds_audit_only"] for seat in (0, 1)]
    preferred = None if means[0] == means[1] else int(means[1] > means[0])
    if comparison["preferred_index"] is not None:
        integer(comparison["preferred_index"], "preferred candidate", 0, 1)
    qualification = {"card_list_legal": True, "historical_environment_verified": False, "competitive_strength_verified": False}
    uncertainty = descriptive_uncertainty(differences)
    if (comparison["mean_scores"] != means or comparison["paired_differences"] != differences or comparison["preferred_index"] != preferred
            or comparison["status"] != ("no_strict_label" if preferred is None else "engineering_preference_observed")
            or comparison["uncertainty"] != uncertainty or comparison["opponent_qualification"] != qualification
            or digest(comparison_projection(comparison)) != comparison["comparison_sha256"]):
        raise ContractError("comparison summary/uncertainty/fingerprint differs")
    return candidates


def descriptive_uncertainty(differences):
    mean = sum(differences) / len(differences)
    se = math.sqrt(sum((x - mean) ** 2 for x in differences) / (len(differences) - 1) / len(differences))
    return {"paired_case_count": len(differences), "mean_candidate_1_minus_0": mean, "descriptive_standard_error": se,
            "confidence_gate_passed": False, "independent_test": False,
            "failure_attribution": "unresolved_driver_deck_interaction; no_single_loss_defect_label"}


def compare_candidates(task, assets, candidates, opponent, *, seeds=(7, 24), purpose="construction_train", seconds=120.):
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 300:
        raise ContractError("comparison exceeds bounded CPU budget")
    plan = plan_for(task, candidates, opponent, seeds, purpose)  # Frozen before any games.
    for deck in candidates:
        assets.validate(task, deck)
    validate_deck_parts(opponent.to_dict(), assets.rows, assets.limits)
    started, games, traces = time.monotonic(), [], []
    for index, candidate in enumerate(candidates):
        for seed in seeds:
            for seat in (0, 1):
                profile = profile_for(candidate, opponent=opponent) if seat == 0 else profile_for(opponent, opponent=candidate)
                if task.goal['kind']=='deck_constraints':profile['adapter_revision']=5
                remaining = seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise ContractError("paired comparison budget exhausted; incomplete cases cannot become labels")
                summary, trace = run_effect_duel(assets.root, profile, seed=seed, budget_seconds=min(30., remaining))
                remaining = seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise ContractError("paired replay budget exhausted; no completed comparison claimed")
                verified, replayed = run_effect_duel(assets.root, {}, replay=trace, budget_seconds=min(30., remaining))
                if replayed != trace or not verified["replay_verified"]:
                    raise ContractError("real comparison replay diverged")
                traces.append(trace)
                games.append({"candidate_index": index, "seed_audit_only": seed, "actor_seat": seat,
                              "outcome": trace["outcome"], "score": outcome_score(trace["outcome"], seat),
                              "turns": trace["turns"], "decisions": summary["decisions"],
                              "trace_sha256": digest(trace), "profile_sha256": digest(profile),
                              "core_terminal_received": trace["events"][-1]["kind"] == 5, "replay_verified": True})
    if driver_binding() != plan["driver"]:
        raise ContractError("driver changed during paired evaluation")
    scores = [sum(g["score"] for g in games if g["candidate_index"] == i) / (len(seeds) * 2) for i in (0, 1)]
    lookup = {(g["candidate_index"], g["seed_audit_only"], g["actor_seat"]): g["score"] for g in games}
    differences = [lookup[(1, seed, seat)] - lookup[(0, seed, seat)] for seed in seeds for seat in (0, 1)]
    preferred = None if scores[0] == scores[1] else int(scores[1] > scores[0])
    comparison = {"source": SOURCE, "plan": plan, "plan_sha256": digest(plan), "games": games, "mean_scores": scores,
                  "paired_differences": differences, "preferred_index": preferred,
                  "status": "no_strict_label" if preferred is None else "engineering_preference_observed",
                  "uncertainty": descriptive_uncertainty(differences),
                  "opponent_qualification": {"card_list_legal": True, "historical_environment_verified": False, "competitive_strength_verified": False},
                  "competitive_ability_validated": False}
    comparison["comparison_sha256"] = digest(comparison_projection(comparison))
    validate_comparison(task, assets, comparison)
    return comparison, traces


def real_game_dataset(task, assets, comparison):
    from .build_pipeline import verify_goal
    from .build_training import supervision_projection, validate_supervision
    candidates = validate_comparison(task, assets, comparison)
    if comparison["plan"]["purpose"] != "construction_train":
        raise ContractError("validation comparisons cannot be construction training labels")
    preferred = comparison["preferred_index"]
    if preferred is None:
        raise ContractError("tied comparison has no strict preference; no invented negative label")
    if task.source != "engineering_fixture":
        raise ContractError("engineering comparisons cannot silently relabel user-provided tasks")
    goals = []
    for deck in candidates:
        evidence = verify_goal(task, deck, assets, attempts=64 if task.goal["kind"] != "normal_summon" else 16, seconds=30.)
        if evidence["status"] != "verified_success":
            raise ContractError("conditional route is unknown/unsupported; no goal negative label")
        goals.append({"deck": deck.to_dict(), "label": 1., "source": "real_core_conditional_goal", "evidence": evidence})
        bad = DeckParts(deck.main[:-1], deck.extra, deck.side)
        goals.append({"deck": bad.to_dict(), "label": 0., "source": "explicit_hard_constraint_failure",
                      "evidence": {"status": "hard_constraint_failure", "reason": "main size differs from task"}})
    worse = 1 - preferred
    pair = {"better": candidates[preferred].to_dict(), "worse": candidates[worse].to_dict(),
            "better_value": comparison["mean_scores"][preferred], "worse_value": comparison["mean_scores"][worse],
            "source": SOURCE, "hard_constraints_checked": True, "evidence": comparison}
    data = {"source": "engineering_real_game_pair_v1", "task_sha256": task.sha256, "goals": goals, "pairs": [pair],
            "unknown_routes_used_as_negative": False, "competitive_quality_labels": False,
            "public_effect_receipts": assets.effect_receipts(task)}
    data["supervision_sha256"] = digest(supervision_projection(data))
    validate_supervision(task, assets, data)
    return data
