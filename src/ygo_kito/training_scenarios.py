"""Executable preparation checks; not an enabled training recipe or ability claim."""
import math

from .validation import ContractError, fields, integer


def _count(value, name):
    return integer(value, name, 0, 2**53 - 1)


def volume_requirements(mean_seconds):
    if type(mean_seconds) not in (int, float) or not math.isfinite(mean_seconds) or mean_seconds <= 0:
        raise ContractError("mean actual game duration must be finite and positive")
    if mean_seconds <= 60:
        return {"count_unit": "completed_matches", "bo1_min": 1000, "bo3_min": 100}
    return {"count_unit": "completed_matches", "total_min": 1000,
            "ratio_bo1": 6, "ratio_bo3": 4, "minimum_bo1": 600, "minimum_bo3": 400}


def volume_met(mean_seconds, bo1_matches, bo3_matches):
    """Input counts must exclude pilot, held-out eval and incomplete matches."""
    _count(bo1_matches, "completed BO1 matches"); _count(bo3_matches, "completed BO3 matches")
    rule = volume_requirements(mean_seconds)
    if "bo1_min" in rule:
        return bo1_matches >= rule["bo1_min"] and bo3_matches >= rule["bo3_min"]
    return bo1_matches + bo3_matches >= rule["total_min"] and bo1_matches * 2 == bo3_matches * 3


def check_2610_rates(period, first_wins, first_completed, second_wins, second_completed,
                     *, stage="common-decks-bo3", partition="final_eval", anomalies=0):
    """Check arithmetic only; callers must supply actual, frozen small-game evidence.

    Completed denominators include draws. Unresolved anomalies remain visible
    and cannot create a pass by deleting failed attempts. No formal success is
    emitted by this preparation helper.
    """
    if period != "2026-10":
        raise ContractError("49/39 thresholds apply only to autonomous 2026-10")
    if stage != "common-decks-bo3" or partition not in ("validation", "final_eval"):
        raise ContractError("stage1/training/pilot results cannot satisfy stage2 frozen acceptance")
    for value, name in ((first_wins, "first wins"), (first_completed, "first completed"),
                        (second_wins, "second wins"), (second_completed, "second completed"), (anomalies, "anomalies")):
        _count(value, name)
    if first_wins > first_completed or second_wins > second_completed:
        raise ContractError("wins exceed actual completed small-game denominator")
    known = first_completed > 0 and second_completed > 0 and anomalies == 0
    return {"arithmetic_thresholds_met": (first_wins * 100 > first_completed * 49 and
            second_wins * 100 > second_completed * 39) if known else None,
            "first_rate": first_wins / first_completed if first_completed else None,
            "second_rate": second_wins / second_completed if second_completed else None,
            "unresolved_anomalies": anomalies, "formal_training_success_verified": False,
            "scope": "arithmetic_only_not_a_frozen_evidence_verifier"}


def eligible_card_ids(period_legal_ids, catalogue_ids, script_usable_ids):
    """Intersect host-checked evidence, excluding missing cards individually.

    script_usable_ids must include an explicit host decision for scripts not
    required by a card; this helper does not infer that from absent Lua files.
    Membership does not prove a complete deck, arbitrary CB or effect execution.
    """
    groups = []
    for values in (period_legal_ids, catalogue_ids, script_usable_ids):
        group = set(values)
        for code in group:
            integer(code, "host checked card ID", 1, 2**32 - 1)
        groups.append(group)
    return sorted(groups[0] & groups[1] & groups[2])


def validate_scenarios(config):
    """Freeze the confirmed scope; preserve unresolved historical statistics."""
    fields(config, {"schema_version", "kind", "execution_enabled", "budget_plan", "model_roles", "common", "periods", "isolation", "runtime_gaps"})
    if type(config.get("schema_version")) is not int or config.get("schema_version") != 1 or config.get("kind") != "training_scenario_preparation_not_runner_recipe":
        raise ContractError("unknown scenario preparation schema")
    if config.get("execution_enabled") is not False:
        raise ContractError("scenario preparation cannot enable a training worker")
    if config.get("model_roles") != ["duel", "build_goal", "build_optimizer", "coordinator"]:
        raise ContractError("retain the existing four model roles")
    if config["budget_plan"] != "configs/training-plan-v1.json":
        raise ContractError("retain the original budget plan; no silent extra allocation")
    common = fields(config["common"], {"count_unit", "timing_unit", "timing_pilot_counts_toward_training", "fast", "slow",
                                       "frozen_evaluation_counts_toward_training", "pilot_sample_recommendation"})
    if (common.get("count_unit") != "completed_matches" or
        common.get("timing_unit") != "actual_small_games_model_and_engine" or
        common.get("timing_pilot_counts_toward_training") is not False or
        common.get("frozen_evaluation_counts_toward_training") is not False or
        common.get("fast") != {"mean_seconds_at_most": 60, "bo1_min": 1000, "bo3_min": 100} or
        common.get("slow") != {"mean_seconds_above": 60, "total_min": 1000, "bo1_ratio": 6, "bo3_ratio": 4}):
        raise ContractError("common timing/quantity scope differs from confirmed complete-match rules")
    # Win thresholds never belong in the all-environments section.
    if set(common) != {"count_unit", "timing_unit", "timing_pilot_counts_toward_training", "fast", "slow",
                        "frozen_evaluation_counts_toward_training", "pilot_sample_recommendation"}:
        raise ContractError("unknown common rule; environment acceptance must stay scoped")
    periods = config.get("periods", {})
    if set(periods) != {"2022-07", "2022-10", "2026-10"}:
        raise ContractError("all three periods must retain separate scenarios")
    for period, slot, cutoff in (("2022-07", "main-01", "2022-09-30"), ("2022-10", "main-02", "2022-12-31")):
        row = fields(periods[period], {"construction_mode", "main_slot", "release_cutoff", "acceptance"})
        a = fields(row["acceptance"], {"kind", "source", "metric_unit", "external_at_least", "mirror_target", "mirror_tolerance",
             "frozen_external_bo3_min", "frozen_mirror_bo3_min", "confidence_level", "confidence_decision_rule", "draw_and_repeated_observation_rule"})
        if (row.get("construction_mode") != "existing_tearlaments_reference" or row.get("main_slot") != slot or
            row.get("release_cutoff") != cutoff or a.get("kind") != "legacy_reference_bo3" or
            a.get("metric_unit") != "bo3_match_with_siding" or a.get("external_at_least") != .6 or
            a.get("mirror_target") != .5 or a.get("frozen_external_bo3_min") != 200 or
            a.get("frozen_mirror_bo3_min") != 200 or a.get("confidence_level") != .95 or
            a.get("mirror_tolerance") is not None or a.get("confidence_decision_rule") is not None or
            a.get("draw_and_repeated_observation_rule") is not None or
            any(key.startswith(("first_", "second_")) for key in a)):
            raise ContractError("historical reference theme/BO3 acceptance cannot be overwritten by 2610 thresholds")
    row = fields(periods["2026-10"], {"construction_mode", "main_slot", "fixed_theme", "user_deck_role", "release_cutoff",
                 "eligible_pool", "missing_card_policy", "stages", "acceptance"})
    a = fields(row["acceptance"], {"kind", "source", "scope", "metric_unit", "first_strictly_greater_than",
               "second_strictly_greater_than", "both_required", "draws_are_wins", "draws_in_completed_denominator", "legacy_evaluation_sampling", "anomalies"})
    if (row.get("construction_mode") != "model_selected_theme_build_and_cb" or row.get("main_slot") is not None or
        row.get("fixed_theme") is not None or row.get("user_deck_role") != "preserved_optional_reference_not_required_entry" or
        row.get("release_cutoff") != "2026-11-01" or
        row.get("eligible_pool") != "confirmed_released_period_legal_catalogue_and_script_usable_subset" or
        row.get("missing_card_policy") != "exclude_missing_card_not_other_themes" or
        a.get("kind") != "actual_small_game_start_order_rates" or a.get("scope") != "common-decks-bo3_frozen_evaluation_only" or
        a.get("metric_unit") != "actual_completed_small_games_by_actual_start_order" or
        a.get("first_strictly_greater_than") != .49 or a.get("second_strictly_greater_than") != .39 or
        a.get("both_required") is not True or a.get("draws_are_wins") is not False or
        a.get("draws_in_completed_denominator") is not True):
        raise ContractError("autonomous 2610 scope, available pool or strict dual threshold differs")
    if a["legacy_evaluation_sampling"] != {
        "source": "unified spec section 12.1 originally applies 200 external plus 200 mirror BO3 per period",
        "external_bo3_min": 200, "mirror_bo3_min": 200,
        "mapping_to_autonomous_themes": "pending; not silently cancelled or satisfied by training matches"}:
        raise ContractError("legacy frozen evaluation sampling cannot silently disappear")
    if row.get("stages") != [
        {"stage_id": "available-bot-bo1", "format": "BO1", "opponents": "actually_runtime_qualified_available_bots", "requires": []},
        {"stage_id": "common-decks-bo3", "format": "BO3", "opponents": "explicit_2026_10_common_deck_pool", "requires": ["available-bot-bo1_completed"]}]:
        raise ContractError("stage2 requires stage1 completion and actual qualified opponent pools")
    isolation = fields(config["isolation"], {"partitions", "training_never_consumes_pilot_or_frozen_evaluation",
                     "freeze_model_deck_opponents_and_seeds_for_evaluation", "stage1_results_are_stage2_acceptance"})
    if (isolation.get("partitions") != ["timing_pilot", "train", "validation", "final_eval"] or
        isolation.get("training_never_consumes_pilot_or_frozen_evaluation") is not True or
        isolation.get("freeze_model_deck_opponents_and_seeds_for_evaluation") is not True or
        isolation.get("stage1_results_are_stage2_acceptance") is not False):
        raise ContractError("pilot/train/frozen evaluation must remain separate")
    return config
