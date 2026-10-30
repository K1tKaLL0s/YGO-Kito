"""Host adapter for the rubric; reference tables never enter learner inputs.

Audited profiles are keyed by exact public text digest, not card ID. They are
trusted evaluator data and are kept outside model features/checkpoints. Unknown
new text falls back to the existing bounded mechanism recognizer, preserving
its scoped uncertainties rather than manufacturing an equivalent card score.
"""
from dataclasses import fields
from hashlib import sha256
import re

from .reference_scoring import Block, CardReview, FunctionalUnit, Requirement


def _fallback_blocks(row, catalog, code):
    if catalog is None:
        return (), ("unreviewed_effect_text",)
    profile = catalog.card(code)
    blocks = []; unknowns = []
    for effect in profile.effects:
        limitations = tuple(c.get("source", "") for c in effect.count_limits)
        costs = tuple(c.get("source", "") for c in effect.costs)
        knowledge = {
            "conditions": "known" if effect.conditions_known else "unknown",
            "costs": "unknown" if effect.knowledge.get("costs") == "unknown" else "known",
            "limits": "known" if effect.count_limits and all(c.get("status") == "known" for c in effect.count_limits) else "unknown",
            "resources": "known", "conflicts": "unknown" if effect.knowledge.get("restrictions") == "unknown" else "known",
        }
        for index, op in enumerate(effect.observed_operations):
            kind = op["kind"]; target = None
            if kind in ("mill", "send_grave") and op.get("owner") == "self":
                if op.get("from_zones") == ("deck",): target = "mill" if kind == "mill" else "targeted_send"
                if op.get("from_zones") == ("hand",): target = "hand_effect_send"
            elif kind == "fusion_summon":
                target = "grave_fusion" if effect in profile.grave_fusion else "fusion_access"
            elif kind == "return_fusion_materials":
                # The grave_fusion prior already prices material return as its
                # mechanism. Do not count that same fact as generic recovery.
                target = None if effect in profile.grave_fusion else "recycle"
            elif kind == "search_or_recover": target = "grave_search" if "grave" in op.get("from_zones", ()) else "search"
            elif kind == "draw": target = "grave_draw" if effect.trigger.get("event") == "sent_to_grave" else "draw"
            elif kind == "special_summon": target = "grave_revival" if "grave" in op.get("from_zones", ()) else "body"
            elif kind == "negate": target = "negate"
            elif kind == "destroy": target = "removal"
            if not target: continue
            status = "reviewed" if op.get("reason") == "effect" else "unknown"
            blocks.append(Block(target, f"e{effect.index}:op{index}", effect.text,
                                status=status, knowledge=knowledge,
                                conditions=(str(effect.trigger.get("source", "")),),
                                costs=costs, limits=limitations,
                                count_factor=0.9 if effect.count_limits else 1.0,
                                cost_factor=0.8 if costs else 1.0))
        unknowns.extend(f"effect_{effect.index}:{item}" for item in effect.unknown)
    return tuple(blocks), tuple(unknowns)


def review_deck(deck, rows, *, semantic_registry=None, catalog=None, contextualize=None,
                reference_example=False):
    """Review the actual candidate. `rows` is its authorized environment catalog.

    semantic_registry is {text_sha256: {blocks: [...], unknowns: [...]}}. It is
    evaluator-only. The reference card listing is not an argument to this API.
    Full card, quote, and effect hash checks remain in score_construction.
    contextualize(row, block, deck, rows) is an optional TRUSTED host review
    callback to reassess a known function against changed targets/resources.
    The example registry contains reference-context feasibility assessments;
    these are not universal, permanent card ratings.
    """
    from collections import Counter
    if semantic_registry and contextualize is None and not reference_example:
        raise ValueError("candidate scoring requires a host context reviewer; reference feasibility cannot be inherited")
    profiles = semantic_registry or {}
    reviews = []
    for zone in ("main", "extra", "side"):
        for code, copies in sorted(Counter(deck.get(zone, ())).items()):
            row = rows.get(code) or rows.get(str(code))
            key = f"{zone}:{code}"
            if row is None:
                reviews.append(CardReview(key, str(code), zone, copies, "", sha256(b"").hexdigest(),
                                          unknowns=("missing_card_text",)))
                continue
            text = row.get("desc", ""); digest = sha256(text.encode()).hexdigest()
            source = profiles.get(digest)
            if source:
                allowed = {f.name for f in fields(Block)}
                blocks = []
                for data in source["blocks"]:
                    if set(data) - allowed: raise ValueError("unexpected review fields")
                    blocks.append(Block(**data))
                unknowns = tuple(source.get("unknowns", ()))
            else:
                blocks, unknowns = _fallback_blocks(row, catalog, code)
            # A partner-dependent hand negate cannot obtain the complete
            # function from its own text alone. Evaluate the actual inventory.
            revised = []
            for block in blocks:
                if block.kind == "negate" and "这张卡和1只天使族怪兽送去墓地" in block.quote:
                    from dataclasses import replace
                    fairy_count = sum(n for other, n in Counter(deck.get("main", ())).items()
                                      if (rows.get(other) or rows.get(str(other)) or {}).get("race", 0) & 0x4)
                    partners = max(0, fairy_count - 1)
                    # Chance of at least one partner among the other four
                    # opening cards; this models access, not a free trigger.
                    from math import comb
                    size = len(deck.get("main", ()))
                    probability = 1 - comb(size - 1 - partners, 4) / comb(size - 1, 4) if size - 1 >= 4 and size - 1 - partners >= 4 else float(partners > 0)
                    block = replace(block, feasibility=min(block.feasibility, probability),
                                    conditions=tuple(block.conditions) + ("requires another Fairy in the same hand",))
                if contextualize is not None:
                    block = contextualize(row, block, deck, rows)
                    if not isinstance(block, Block): raise ValueError("context review must return a Block")
                revised.append(block)
            reviews.append(CardReview(key, str(row.get("alias") or code), zone, copies, text, digest,
                                      tuple(revised), unknowns))
    return tuple(reviews)


def propose_functional_units(cards, *, theme):
    """Generic semantic hypotheses for a host without richer graph reviews.

    These are *proposed* and earn half relation value. A separate engine CB
    gate remains mandatory in the host. Host-reviewed functional graph edges
    can replace these with more specific units; card names never add points.
    """
    if not theme:
        raise ValueError("an explicit theme/goal is required for functional unit proposals")
    if theme != "pearl_grave_fusion":
        return ()  # Other goals use their own graph, not a Pearl main-axis test.
    def req(*kinds, zone=("main", "extra")):
        return Requirement(tuple(kinds), tuple(zone))
    return (
        FunctionalUnit("grave-fusion-engine", "main_axis", "effect send to grave, grave fusion, usable extra target",
                       15, (req("mill", "targeted_send", zone=("main",)), req("grave_fusion", zone=("main",)),
                            req("extra_fusion", zone=("extra",))),
                       "effect_grave_to_fusion_material_return", "proposed",
                       conditions=("matching materials and target access require graph/engine evidence",),
                       family="grave_fusion_engine"),
        FunctionalUnit("grave-control-support", "sub_axis", "grave loading with grave shuffling interaction",
                       7, (req("mill", zone=("main",)), req("grave_shuffle_interaction", zone=("main",))),
                       "load_grave_then_control_and_recycle", "proposed",
                       risks=("opponent also receives grave resources; timing can consume own fusion materials",),
                       family="grave_control"),
        FunctionalUnit("ritual-support", "sub_axis", "ritual access, searchable resources and grave recovery",
                       5, (req("ritual_access", zone=("main",)), req("search", "grave_search", zone=("main",)),
                           req("grave_revival", "recycle", zone=("main",))),
                       "ritual_resources_and_recovery", "proposed", family="ritual"),
    )


def read_semantic_registry(data):
    """Keep only digest-indexed host evidence, never names or card lists."""
    return data.get("profiles", data)
