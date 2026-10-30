"""Evaluator-side, source-bound construction rubric; no reference card lookup.

The learner receives public_result(), not this module's audit inputs.  Scores
are expert priors, not win probabilities or proof that a basic CB was found.
New cards earn the same points for the same reviewed semantics.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
import math
from typing import Mapping, Sequence

VERSION = "theme-effect-block-rubric-v2-explicit-reference-scope"

# A prior is for one semantic fact, before feasibility/cost/resource discounts.
# Broad/narrow descriptions in one family and fact_id compete by max, not sum.
# Different operations on one card retain separate fact_ids and both earn value.
PEARL_PRIORS = {
    "grave_related": (1.0, "grave_function", 4.0),
    "grave_fusion": (1.5, "grave_function", 6.0),
    "grave_revival": (1.0, "grave_function", 4.0),
    "grave_draw": (1.0, "grave_function", 3.0),
    "grave_search": (1.0, "grave_function", 4.0),
    "mill": (1.0, "deck_to_grave", 6.0),
    "targeted_send": (1.25, "deck_to_grave", 5.0),
    "hand_effect_send": (0.75, "hand_to_grave", 3.0),
    "recycle": (1.0, "resource_return", 4.0),
    "grave_shuffle_interaction": (1.25, "grave_interaction", 4.0),
    "search": (1.0, "search", 4.0),
    "draw": (0.75, "draw", 3.0),
    "body": (0.75, "body", 4.0),
    "extra_fusion": (0.75, "extra_access", 3.0),
    "extra_synchro": (0.5, "extra_access", 1.5),
    "extra_xyz": (0.5, "extra_access", 2.0),
    "extra_link": (0.5, "extra_access", 2.0),
    "material_substitute": (0.75, "material", 1.5),
    "fusion_access": (1.0, "summon_access", 2.0),
    "ritual_access": (1.0, "summon_access", 2.0),
    "negate": (1.25, "interaction", 5.0),
    "removal": (1.0, "removal", 4.0),
    "protection": (0.5, "protection", 2.0),
    "lock": (1.0, "lock", 3.0),
    "hand_exchange": (0.75, "hand_refresh", 1.5),
    "extra_normal": (0.5, "normal_access", 1.0),
}


def _number(value, name, lo=0.0, hi=1.0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{name} outside [{lo}, {hi}]")
    return float(value)


def content_digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Block:
    kind: str
    fact_id: str
    quote: str
    # These are evaluator reviews of the particular function, not an assertion
    # that the entire card text has been interpreted or executed by the core.
    status: str = "reviewed"
    feasibility: float = 1.0
    cost_factor: float = 1.0
    count_factor: float = 1.0
    resource_factor: float = 1.0
    conflict_factor: float = 1.0
    conditions: tuple[str, ...] = ()
    costs: tuple[str, ...] = ()
    limits: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    knowledge: Mapping = field(default_factory=lambda: {k: "known" for k in
        ("conditions", "costs", "limits", "resources", "conflicts")})
    # A shared once-per-turn choice is a max across modes, not several uses.
    choice_group: str = ""
    choice_mode: str = ""

    def factor(self):
        if self.status not in ("reviewed", "unknown", "unavailable"):
            raise ValueError("unrecognized block review status")
        domains = {"conditions", "costs", "limits", "resources", "conflicts"}
        if set(self.knowledge) != domains or any(v not in ("known", "not_applicable", "unknown")
                                               for v in self.knowledge.values()):
            raise ValueError("every function requires scoped knowledge statuses")
        factors = [_number(getattr(self, k), k) for k in
                   ("feasibility", "cost_factor", "count_factor", "resource_factor", "conflict_factor")]
        return math.prod(factors) if self.status == "reviewed" and "unknown" not in self.knowledge.values() else 0.0


@dataclass(frozen=True)
class CardReview:
    # key/alias are opaque evaluator identities, never used as learned features.
    key: str
    alias: str
    zone: str
    copies: int
    text: str
    text_sha256: str
    blocks: tuple[Block, ...] = ()
    unknowns: tuple[str, ...] = ()


@dataclass(frozen=True)
class Requirement:
    kinds: tuple[str, ...]
    zones: tuple[str, ...] = ("main", "extra")
    # Optional source entities constrain an evaluator's particular unit. They
    # are not a reference similarity score. New cards may have different keys.
    entities: tuple[str, ...] = ()
    minimum_entities: int = 1


@dataclass(frozen=True)
class FunctionalUnit:
    key: str
    category: str  # main_axis / sub_axis / synergy / generic / conditional_generic
    description: str
    points: float
    requirements: tuple[Requirement, ...]
    relation: str
    relation_status: str = "unknown"  # reviewed_feasible / proposed / unknown
    factor: float = 1.0
    conditions: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    # Same semantic relation/family cannot be resubmitted under a different ID.
    family: str = ""


@dataclass(frozen=True)
class Policy:
    theme: str = ""
    priors: Mapping = field(default_factory=dict)
    reference_score: float | None = None
    reference_period_id: str | None = None
    minimum_ratio: float = 0.8
    max_score: float = 100.0
    block_cap: float = 40.0
    category_caps: Mapping = field(default_factory=lambda: {
        "main_axis": 15.0, "sub_axis": 10.0, "synergy": 15.0,
        "generic": 10.0, "conditional_generic": 10.0,
    })
    # Supply a sealed evaluator calibration for THIS period/goal/rubric only.
    reference_raw: float | None = None
    calibration_scope: str = ""

    def validate(self):
        if not self.theme or not self.calibration_scope:
            raise ValueError("theme and calibration_scope are required")
        if not self.priors:
            raise ValueError("theme/goal-conditioned priors must be explicitly supplied")
        if self.theme != "pearl_grave_fusion" and self.priors == PEARL_PRIORS:
            raise ValueError("a different theme requires explicit theme-conditioned priors")
        if self.reference_period_id is not None and self.reference_period_id not in ("2022-07", "2022-10"):
            raise ValueError("no reference anchor is authorized for this period; 2610 is autonomous")
        if self.reference_score is not None:
            _number(self.reference_score, "reference_score", 1, 100)
            if self.reference_period_id is None:
                raise ValueError("a reference score requires an explicit authorized reference period")
        elif self.reference_period_id is not None or self.reference_raw is not None:
            raise ValueError("reference calibration requires an explicit reference score")
        _number(self.minimum_ratio, "minimum_ratio")
        _number(self.max_score, "max_score", self.reference_score or 0, 100)
        _number(self.block_cap, "block_cap", 0, 100)
        for key, (base, family, cap) in self.priors.items():
            _number(base, key + ".base", 0, 100)
            _number(cap, key + ".cap", 0, 100)
            if not family: raise ValueError("a prior needs an overlap family")
        for cap in self.category_caps.values(): _number(cap, "category cap", 0, 100)
        if self.reference_raw is not None:
            _number(self.reference_raw, "reference_raw", 0.000001, 10000)


def score_construction(cards: Sequence[CardReview], units: Sequence[FunctionalUnit] = (), *,
                       policy: Policy, legality: str = "unknown", scope: str,
                       side_plan_verified: bool = False, evaluation_context: Mapping | None = None):
    """Return a private audit. Input must be built by the trusted evaluator.

    legality is the existing host validator's result. This routine never opens
    engines, trains, changes card pools, or certifies CBs. A blueprint is scored
    with this same algebra by projecting identities away after the audit.
    """
    policy.validate()
    if scope != policy.calibration_scope:
        raise ValueError("calibration scope mismatch")
    if evaluation_context is not None and (set(evaluation_context) != {"goal_id", "period_id"} or
            any(not isinstance(v, str) or not v.strip() for v in evaluation_context.values())):
        raise ValueError("evaluation_context must bind nonempty goal_id and period_id")
    if evaluation_context is not None and policy.reference_period_id is not None and (
            evaluation_context["period_id"] != policy.reference_period_id):
        raise ValueError("reference anchor cannot be applied to a different or autonomous period")
    if legality not in ("legal", "illegal", "unknown"):
        raise ValueError("invalid legality status")
    if len({c.key for c in cards}) != len(cards):
        raise ValueError("duplicate card review key")
    original_order = {c.key: i for i, c in enumerate(cards)}
    cards = sorted(cards, key=lambda c: ({"main": 0, "extra": 1, "side": 2}.get(c.zone, 3), c.alias, c.key))
    aliases = Counter()
    counts = Counter()
    for card in cards: counts[card.zone] += card.copies
    if not 40 <= counts["main"] <= 60 or counts["extra"] > 15 or counts["side"] > 15:
        legality = "illegal"
    actual = {}; rows = []; offers = []; unknowns = []
    for card in cards:
        if card.zone not in ("main", "extra", "side"):
            raise ValueError("invalid zone")
        if isinstance(card.copies, bool) or not isinstance(card.copies, int) or card.copies < 1:
            raise ValueError("copies must be a positive integer")
        if sha256(card.text.encode()).hexdigest() != card.text_sha256:
            raise ValueError("review text digest mismatch: " + card.key)
        alias = card.alias or card.key
        # Aliases across main/side share a listing limit. Illegal listings do
        # not acquire additional raw points; host legality is reported below.
        aliases[alias] += card.copies
        if aliases[alias] > 3:
            legality = "illegal"
        unique = {}
        for block in card.blocks:
            if block.kind not in policy.priors:
                unknowns.append(card.key + ":unpriced:" + block.kind); continue
            if not block.fact_id or not block.quote or block.quote not in card.text:
                raise ValueError("block must quote its exact source fact: " + card.key)
            base, family, cap = policy.priors[block.kind]
            value = base * block.factor()
            identity = (block.fact_id, family)
            if identity not in unique or value > unique[identity][0]:
                unique[identity] = (value, base, block, cap)
        choice_groups = defaultdict(lambda: defaultdict(list))
        for identity, entry in unique.items():
            block = entry[2]
            # Sum the independent operations INSIDE one mode, then choose the
            # best mode of a shared once-only use. Do not throw away the other
            # operations of the selected effect (e.g. removal + effect discard).
            group = block.choice_group or "fact:" + repr(identity)
            mode = block.choice_mode or "fact:" + repr(identity)
            choice_groups[group][mode].append(entry)
        modes = []
        for choices in choice_groups.values():
            modes.extend(max(choices.values(), key=lambda entries: sum(e[0] for e in entries)))
        cardrow = {"key": card.key, "alias": alias, "zone": card.zone, "copies": card.copies,
                   "base_points": round(sum(e[1] for e in modes), 6),
                   "context_points_one_copy": round(sum(e[0] for e in modes), 6),
                   "block_contribution": 0.0, "unit_attribution": 0.0,
                   "unknowns": list(card.unknowns), "blocks": []}
        # Side cards earn no simultaneous main-deck capacity. A verified
        # swap plan may grant a discounted preparation value in a BO3 rubric.
        zone_factor = 0.35 if card.zone == "side" and side_plan_verified else 0.0 if card.zone == "side" else 1.0
        before = aliases[alias] - card.copies
        multiplicity = sum((1.0, 0.35, 0.10)[i] for i in range(before, min(3, before + card.copies)))
        main_size = sum(c.copies for c in cards if c.zone == "main")
        density = min(1.0, 40 / main_size) if card.zone == "main" and main_size else 1.0
        if zone_factor and card.text:
            actual.setdefault(card.key, []).append(("@present", 1.0, card.zone))
        for value, base, block, cap in modes:
            offer = value * multiplicity * zone_factor * density
            record = {"kind": block.kind, "fact_id": block.fact_id, "base": base,
                      "context_factor": block.factor(), "context_one_copy": value,
                      "offered": offer, "awarded": 0.0, "conditions": list(block.conditions),
                      "costs": list(block.costs), "limits": list(block.limits),
                      "resources": list(block.resources), "conflicts": list(block.conflicts),
                      "knowledge": dict(block.knowledge)}
            cardrow["blocks"].append(record)
            offers.append((block.kind, offer, cap, cardrow, record))
            if zone_factor and block.factor():
                actual.setdefault(card.key, []).append((block.kind, block.factor(), card.zone))
        rows.append(cardrow)
        unknowns.extend(card.key + ":" + item for item in card.unknowns)
    # Saturate a repeated semantic channel across different card names too.
    totals = defaultdict(float)
    for kind, value, _, _, _ in offers: totals[kind] += value
    for kind, value, cap, row, record in offers:
        awarded = value * min(1.0, cap / totals[kind]) if totals[kind] else 0.0
        record["awarded"] = awarded; row["block_contribution"] += awarded
    block_total = sum(r["block_contribution"] for r in rows)
    if block_total > policy.block_cap:
        ratio = policy.block_cap / block_total
        for row in rows:
            row["block_contribution"] *= ratio
            for record in row["blocks"]: record["awarded"] *= ratio
        block_total = policy.block_cap
    unit_rows = []; semantic_units = {}; by_key = {r["key"]: r for r in rows}
    for unit in units:
        if unit.category not in policy.category_caps:
            raise ValueError("unknown unit category")
        _number(unit.points, "unit points", 0, 100)
        quality = _number(unit.factor, "unit factor")
        if unit.relation_status not in ("reviewed_feasible", "proposed", "unknown"):
            raise ValueError("invalid unit relation status")
        quality *= {"reviewed_feasible": 1.0, "proposed": 0.5, "unknown": 0.0}[unit.relation_status]
        witnesses = set(); matched = []; unmet = []
        if not unit.requirements or not unit.relation:
            raise ValueError("functional units require a relation and requirements")
        for requirement in unit.requirements:
            if requirement.minimum_entities < 1: raise ValueError("minimum_entities must be positive")
            candidates = {}
            for key, blocks in actual.items():
                if requirement.entities and key not in requirement.entities: continue
                factor = max((factor for kind, factor, zone in blocks if kind in requirement.kinds
                              and zone in requirement.zones), default=0.0)
                if factor: candidates[key] = factor
            if len(candidates) < requirement.minimum_entities:
                unmet.append(asdict(requirement)); quality = 0.0
            else:
                selected = sorted(candidates, key=lambda k: (-candidates[k], k))[:requirement.minimum_entities]
                quality = min(quality, *(candidates[k] for k in selected))
                witnesses.update(selected); matched.append(selected)
        signature = (unit.category, unit.family or unit.relation)
        raw = unit.points * quality
        row = {"key": unit.key, "category": unit.category, "description": unit.description,
               "points": unit.points, "factor": quality, "raw": raw, "awarded": 0.0,
               "relation": unit.relation, "relation_status": unit.relation_status,
               "conditions": list(unit.conditions), "risks": list(unit.risks),
               "witnesses": sorted(witnesses), "unmet": unmet, "deduplicated": False}
        unit_rows.append(row)
        old = semantic_units.get(signature)
        if old is None or raw > old["raw"]:
            if old: old["deduplicated"] = True
            semantic_units[signature] = row
        else: row["deduplicated"] = True
    category_totals = defaultdict(float)
    for row in semantic_units.values(): category_totals[row["category"]] += row["raw"]
    for row in semantic_units.values():
        cap = policy.category_caps[row["category"]]; total = category_totals[row["category"]]
        row["awarded"] = row["raw"] * min(1, cap / total) if total else 0.0
        for key in row["witnesses"]:
            by_key[key]["unit_attribution"] += row["awarded"] / len(row["witnesses"])
    raw_score = block_total + sum(r["awarded"] for r in unit_rows)
    if legality == "illegal": raw_score = 0.0
    reference_applicable = policy.reference_period_id is not None and policy.reference_score is not None
    calibrated = reference_applicable and policy.reference_raw is not None
    score = min(policy.max_score, policy.reference_score * raw_score / policy.reference_raw) if calibrated else None
    score = round(score, 6) if score is not None else None
    threshold = policy.reference_score * policy.minimum_ratio if reference_applicable else None
    multiplier = policy.reference_score / policy.reference_raw if calibrated else None
    attribution_scale = (score / (raw_score * multiplier)) if calibrated and raw_score else 0.0
    for row in rows:
        row["raw_contribution"] = row["block_contribution"] + row["unit_attribution"]
        row["score_contribution"] = row["raw_contribution"] * multiplier * attribution_scale if calibrated else None
    return {"version": VERSION, "theme": policy.theme, "scope": scope,
            "evaluation_context": dict(evaluation_context) if evaluation_context is not None else None,
            "score": score,
            "reference_score": policy.reference_score, "threshold": threshold,
            "reference_period_id": policy.reference_period_id,
            "reference_comparison_applicable": reference_applicable,
            "reference_raw": policy.reference_raw, "raw_score": round(raw_score, 6),
            "calibrated": calibrated, "legality": legality,
            "force_optimization": legality == "illegal" or bool(reference_applicable and (score is None or score < threshold)),
            "score_threshold_met": bool(score is not None and score >= threshold and legality != "illegal") if reference_applicable else None,
            "raw_block_points": block_total,
            "categories": {k: sum(r["awarded"] for r in unit_rows if r["category"] == k) for k in policy.category_caps},
            "cards": sorted(rows, key=lambda r: original_order[r["key"]]), "units": unit_rows, "unknowns": unknowns,
            "basic_cb_verified": None,
            "interpretation": "expert-prior construction quality; not a win probability or CB proof"}


def public_result(audit):
    """Minimal feedback before authorized hint escalation; no reference list."""
    return {k: audit[k] for k in ("version", "theme", "scope", "score", "reference_score", "threshold",
                                  "calibrated", "legality", "force_optimization", "score_threshold_met",
                                  "basic_cb_verified", "interpretation")}


def inventory_digest(cards):
    return content_digest(sorted((c.key, c.alias, c.zone, c.copies, c.text_sha256) for c in cards))


def calibrate_reference(cards, units=(), *, policy, expected_inventory_digest,
                        legality="unknown", scope):
    """The reference is assigned 70 by policy, not empirically measured at 70.

    Call only on evaluator-audited source-complete reference. Unknown functions
    on known cards may stay uncredited. Missing card text forbids anchoring.
    """
    from dataclasses import replace
    if policy.reference_period_id not in ("2022-07", "2022-10") or policy.reference_score is None:
        raise ValueError("reference calibration is only authorized for explicitly scoped 2207/2210 references")
    if inventory_digest(cards) != expected_inventory_digest:
        raise ValueError("reference inventory does not match the sealed source manifest")
    if any(not c.text or "missing_card_text" in c.unknowns for c in cards):
        raise ValueError("cannot calibrate an incomplete reference inventory")
    if legality == "illegal": raise ValueError("cannot calibrate an illegal reference")
    raw_policy = replace(policy, reference_raw=None)
    raw = score_construction(cards, units, policy=raw_policy, legality=legality, scope=scope)["raw_score"]
    if raw <= 0: raise ValueError("reference has no reviewed functional value")
    return replace(policy, reference_raw=raw)
