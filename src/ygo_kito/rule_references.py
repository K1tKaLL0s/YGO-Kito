"""Local OCG research references, never a legal-action or counter authority.

A reference remains conditional even when its source is a direct ruling.
Card/effect identity, scope and a real event must be reviewed separately.
"""
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
import json


REFERENCE_VERSION = "ocg-negation-reference-v1"
RESOURCE = "resources/rules/ocg-negation-rules.json"
LOOKUP = "ygo_kito.rule_references.lookup_rule"

# Explicit cross references for the already reviewed, exact FAQ bindings.
# This map does not classify a new card, wording or event.
BOUND_RULE_IDS = {
    "qa17200": "USE_TURN_NEGATED",
    "qa17377": "USE_TURN_NEGATED",
    "qa17376": "USE_TURN_NEGATED",
    "qa22010": "CARD_ACTIVATION_COUNT",
    "qa7813-caligula": "EFFECT_ACTIVATION_COUNTEREXAMPLE",
    "qa23158-soul-crossing": "EFFECT_ACTIVATION_COUNTEREXAMPLE",
    "qa23158-unmei-no-draw": "EFFECT_ACTIVATION_COUNTEREXAMPLE",
}


@lru_cache(maxsize=1)
def _book():
    book = json.loads(files("ygo_kito").joinpath(RESOURCE).read_text(encoding="utf-8"))
    if book.get("schema_version") != "1.0":
        raise ValueError("unsupported OCG reference schema")
    return book


def library_reference():
    """Detached discovery metadata for model hosts and reviewing agents."""
    book = _book()
    return {
        "version": REFERENCE_VERSION, "resource": RESOURCE, "lookup": LOOKUP,
        "schema_version": book["schema_version"], "verified_on": book["verified_on"],
        "jurisdiction": book["jurisdiction"],
        "rule_ids": [rule["rule_id"] for rule in book["rules"]],
        "unresolved": deepcopy(book["unresolved"]),
        "status": "reference_only", "legality_authority": "engine",
        "applied_to_decision": False,
    }


def lookup_rule(rule_id):
    """Read one exact ID with its evidence and unresolved caveats intact."""
    book = _book()
    rule = next((rule for rule in book["rules"] if rule["rule_id"] == rule_id), None)
    result = {"version": REFERENCE_VERSION, "resource": RESOURCE,
              "status": "reference_only" if rule is not None else "unknown",
              "rule_id": rule_id, "applied_to_decision": False,
              "applicability": "unknown_requires_effect_scope_event_review",
              "legality_authority": "engine", "unresolved": deepcopy(book["unresolved"])}
    if rule is not None:
        result["rule"] = deepcopy(rule)
        result["source_records"] = {key: deepcopy(book["sources"][key]) for key in rule["sources"]}
    return result


def effect_reference_requests(record):
    """Attach lookup requests to parsed effects; never infer a negation policy.

    Only structured parser categories are referenced. No card-name or generic
    word search is performed, and unknown parser policies remain unknown.
    """
    requests = []
    for limit in record.get("count_limits", ()):
        rule_id = None
        event, scope = limit.get("count_event"), limit.get("scope")
        if limit.get("status") == "known":
            if event == "use" and scope in (
                    "same_name_shared_effects", "same_name_this_effect",
                    "same_name_all_effects", "this_card_effect"):
                rule_id = "USE_TURN_NEGATED"
            elif event == "card_activation" and scope == "player_trap_card_activations":
                rule_id = "CARD_ACTIVATION_COUNT"
            elif event == "effect_activation" and scope == "each_player_monster_effects":
                rule_id = "EFFECT_ACTIVATION_COUNTEREXAMPLE"
            elif event == "card_activation" and scope == "same_name_card":
                rule_id = "NAMED_CARD_ACTIVATION_ONCE"
        if rule_id is None:
            continue
        evidence = lookup_rule(rule_id)
        requests.append({
            "rule_id": rule_id, "lookup": LOOKUP, "status": "reference_only",
            "evidence_status": evidence["rule"]["evidence_status"],
            "binding": {"card_id": record.get("card_id"),
                        "effect_index": record.get("effect_index"),
                        "text_sha256": record.get("text_sha256"),
                        "scope": scope, "subject": deepcopy(limit.get("subject")),
                        "count_event": event, "outcome": "unknown_requires_engine_event",
                        "period": limit.get("period"), "condition": limit.get("condition")},
            "parsed_negation_policy": deepcopy(limit.get("negation_policy", {})),
            "applicability": "unknown_requires_effect_scope_event_review",
            "applied_to_decision": False,
        })
    if record.get("costs"):
        requests.append({"rule_id": "COST_NOT_REFUNDED", "lookup": LOOKUP,
                         "status": "reference_only", "applied_to_decision": False,
                         "binding": {"card_id": record.get("card_id"),
                                     "effect_index": record.get("effect_index"),
                                     "text_sha256": record.get("text_sha256"),
                                     "scope": "this_effect_activation_payment",
                                     "count_event": "payment",
                                     "outcome": "unknown_requires_engine_event"},
                         "applicability": "unknown_requires_confirmed_legal_payment"})
    return requests


def bound_counter_reference(binding, events):
    """Reference an existing exact counter binding and its observed events."""
    rule_id = BOUND_RULE_IDS.get(binding.rule_id)
    result = lookup_rule(rule_id)
    result["binding"] = {
        "binding_id": binding.binding_id, "counter_rule_id": binding.rule_id,
        "subject_key": binding.subject_key, "effects": [list(pair) for pair in binding.effects],
        "card_text_digests": [list(pair) for pair in binding.card_text_digests],
        "scope_complete": binding.scope_complete, "first_turn": binding.first_turn,
        "last_turn": binding.last_turn, "application_event_id": binding.application_event_id,
        "events": deepcopy(events),
    }
    return result
