"""Mechanism-only, period-specific disclosures of the audited references.

No card names, IDs, exact listing quantities or verbatim effect text are carried
here. Only the explicitly retained 2207/2210 references authorize these hints.
"""
from copy import deepcopy
from .reference_hints import DEFAULT_HINT_TEMPLATES, validate_hint_template


def templates_for_period(period_id):
    if period_id not in ("2022-07", "2022-10"):
        raise ValueError("no reviewed reference hint template for period")
    templates = deepcopy(DEFAULT_HINT_TEMPLATES)
    generic = templates["generic_tools"]
    generic["blocks"].append(dict(
        role="recovery", functions=["draw"], conditions=["timing_window", "opponent_controls_relevant_card"],
        requirements=["supported_effect_evidence"], limits=["shared_name_limit"], risks=["opponent_benefits"]))
    if period_id == "2022-07":
        generic["blocks"][0]["conditions"] += ["another_fairy_in_hand"]
    else:
        # 2210 has no Fairy-pair counter package.
        generic["blocks"][0]["requirements"] = ["supported_effect_evidence"]
        generic["blocks"][0]["conditions"] = ["timing_window", "can_pay_cost"]
        generic["blocks"][0]["risks"] = ["self_conflict"]
    if period_id == "2022-10":
        templates["secondary_axes"]["blocks"].append(dict(
            role="material", functions=["special_summon", "flip_face_down"],
            conditions=["grave_resources_available", "can_pay_cost"],
            requirements=["available_cost_resource"], limits=["resource_competition"],
            risks=["shared_grave_resource"]))
    return {key: validate_hint_template(value) for key, value in templates.items()}
