"""Versioned, effect-scoped observations for public planning and model input.

These records retain uncertainty and source text. They are neither legal-action
certificates nor a replacement interpretation of the legacy 18 feature slots.
Only explicitly bounded payment syntax is enriched; other clauses stay unknown.
"""
from copy import deepcopy
import re

from .rule_references import effect_reference_requests

EFFECT_RECORD_VERSION = "public-effect-records-v1"
SUMMARY_VERSION = "public-mechanism-summary-v1"
SUMMARY_FIELDS = (
    "fusion_target", "synchro_target", "xyz_target", "tuner",
    "effects", "costs", "known_cost_quantity", "unknown_cost_quantity",
    "targets", "restrictions", "unknown_effects", "grave_triggers",
    "summon_triggers", "fusion_operations", "special_summon_operations",
    "grave_operations", "recover_operations", "draw_operations", "interaction_operations",
    "from_hand", "from_grave", "to_field", "to_grave", "to_deck",
    "known_limit_maximum", "shared_or_player_limits", "unknown_limits",
    "known_activation_conditions", "self_costs", "opponent_costs",
    "unknown_cost_owner", "unknown_resource_quantity",
)
SUMMARY_WIDTH = len(SUMMARY_FIELDS)

_ZONE = {"手卡": "hand", "场上": "field", "墓地": "grave", "卡组": "deck"}
_PAYMENTS = (
    ("send_grave", re.compile(r"(?:丢弃|舍弃)(?P<quantity>\d+)张手卡"), "hand", "grave", "self"),
    ("send_grave", re.compile(r"从(?P<owner>自己|对方)(?:的)?(?P<zone>手卡|场上|墓地|卡组)"
                              r"(?:把|将|选)?(?P<quantity>\d+)[只张][^，,。；;]{0,60}?送去墓地"), None, "grave", None),
    ("send_grave", re.compile(r"(?:把|将)(?P<owner>自己|对方)(?:的)?(?P<zone>手卡|场上|墓地|卡组)"
                              r"(?:的)?(?P<quantity>\d+)[只张][^，,。；;]{0,60}?送去墓地"), None, "grave", None),
    ("pay_lp", re.compile(r"支付(?P<quantity>\d+)(?:基本分|LP)"), None, None, "self"),
)


def _cost_records(effect):
    """Keep individual explicit payments, without merging different effects."""
    head = effect.trigger.get("source", "")
    found = []
    for kind, pattern, zone, destination, owner in _PAYMENTS:
        for match in pattern.finditer(head):
            # A trigger describing a discard is not a payment instruction.
            if "场合" in head[match.end():] or "成功" in head[match.end():]:
                continue
            if any(match.start() < end and start < match.end() for start, end, _ in found):
                continue
            groups = match.groupdict()
            controller = {"自己": "self", "对方": "opponent"}.get(groups.get("owner"), owner or "unknown")
            origin = _ZONE.get(groups.get("zone"), zone)
            found.append((match.start(), match.end(), {
                "kind": kind, "reason": "cost", "quantity": int(groups["quantity"]),
                "quantity_status": "explicit", "owner": controller,
                "owner_status": "recognized" if controller != "unknown" else "unknown",
                "from_zones": [origin] if origin else [], "to_zone": destination,
                "resource": "lp" if kind == "pay_lp" else "cards", "source": match[0],
            }))
    result = [item for _, _, item in sorted(found)]
    for cost in effect.costs:
        if any(item["source"] in cost.get("source", "") for item in result):
            continue
        item = deepcopy(cost)
        source = item.get("source", "")
        owner = "opponent" if "对方" in source else "self" if "自己" in source else "unknown"
        item.update(owner=owner, owner_status="recognized" if owner != "unknown" else "unknown",
                    quantity_status="explicit" if item.get("quantity") is not None else "unknown",
                    resource="cards", to_zone="grave" if item["kind"] == "send_grave" else None)
        result.append(item)
    for index, item in enumerate(result):
        item.update(cost_index=index, effect_index=effect.index)
    return result


def effect_records(profile, *, semantic_version):
    """Return detached records; source/card identity is provenance, not a feature."""
    result = []
    for effect in profile.effects:
        costs = _cost_records(effect)
        operations = deepcopy(list(effect.operations))
        changes = [dict(item, phase="activation_payment") for item in costs]
        changes += [dict(item, phase="resolution") for item in operations
                    if item.get("from_zones") or item.get("to_zone")]
        record = {
            "record_version": EFFECT_RECORD_VERSION, "semantic_version": semantic_version, "card_id": profile.card_id,
            "cards_sha256": profile.cards_sha256, "text_sha256": profile.text_sha256,
            "effect_index": effect.index, "source_text": effect.text,
            "trigger": deepcopy(effect.trigger),
            "conditions": {"source": effect.trigger.get("source", ""),
                           "status": "recognized" if effect.conditions_known else "unknown",
                           "additional_conditions": effect.trigger.get("additional_conditions", "unknown")},
            "costs": costs, "targets": deepcopy(list(effect.targets)), "operations": operations,
            "resource_changes": changes, "count_limits": deepcopy(list(effect.count_limits)),
            "restrictions": deepcopy(list(effect.restrictions)),
            "card_restrictions": deepcopy(list(profile.restrictions)),
            "knowledge": deepcopy(effect.knowledge),
            "unknown": list(dict.fromkeys((*profile.unknown, *effect.unknown))),
            "legality_verified": False,
        }
        record["rule_references"] = effect_reference_requests(record)
        result.append(record)
    return tuple(result)


def mechanism_summary(catalog, codes):
    """ID-independent bounded means, supplementary to legacy card features.

    Exact payment quantities and associations remain in effect_records; this
    fixed-width model summary deliberately does not claim to be lossless.
    Repeated IDs count as actual deck copies. Empty decks have zero observations.
    """
    codes = tuple(codes)
    total = [0.] * SUMMARY_WIDTH
    for code in codes:
        row = catalog.assets.rows[code]
        records = catalog.effect_records(code)
        costs = [item for record in records for item in record["costs"]]
        operations = [item for record in records for item in record["operations"] if item.get("reason") == "effect"]
        changes = [item for record in records for item in record["resource_changes"]]
        limits = [item for record in records for item in record["count_limits"]]
        kinds = [item["kind"] for item in operations]
        values = [float(bool(row.get("type", 0) & flag)) for flag in (0x40, 0x2000, 0x800000, 0x1000)]
        values += [len(records)/8, len(costs)/8,
                   sum(item["quantity"] for item in costs if item.get("quantity") is not None and item.get("resource") == "cards")/16,
                   sum(item.get("quantity") is None for item in costs)/8,
                   sum(len(r["targets"]) for r in records)/8,
                   (len(catalog.card(code).restrictions)+sum(len(r["restrictions"]) for r in records))/8,
                   sum(bool(r["unknown"]) for r in records)/8,
                   sum(r["trigger"].get("event") == "sent_to_grave" for r in records)/8,
                   sum(r["trigger"].get("event") in ("normal_or_special_summon", "special_summon") for r in records)/8,
                   kinds.count("fusion_summon")/8, kinds.count("special_summon")/8,
                   sum(k in ("mill", "send_grave") for k in kinds)/8,
                   kinds.count("search_or_recover")/8, kinds.count("draw")/8,
                   sum(k in ("negate", "destroy") for k in kinds)/8]
        values += [sum(zone in item.get("from_zones", ()) for item in changes)/8 for zone in ("hand", "grave")]
        values += [sum(item.get("to_zone") == zone for item in changes)/8 for zone in ("field", "grave")]
        values += [sum(item.get("to_zone") in ("deck", "deck_bottom") for item in changes)/8,
                   sum(item["maximum"] for item in limits if item.get("maximum") is not None)/16,
                   sum(item.get("scope", "").startswith("player_") or item.get("subject", {}).get("kind") == "same_name_shared_effects" for item in limits)/8,
                   sum(item.get("status") == "unknown" for item in limits)/8,
                   sum(r["conditions"]["status"] == "recognized" for r in records)/8]
        values += [sum(item.get("owner") == owner for item in costs)/8 for owner in ("self", "opponent", "unknown")]
        values += [sum(item.get("quantity") is None for item in changes)/8]
        for index, value in enumerate(values):
            total[index] += min(value, 1.) / len(codes)
    return total
