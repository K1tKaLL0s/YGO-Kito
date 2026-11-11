"""Versioned, bounded observations. IDs, names and sources never become features."""

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math

INPUT_VERSION = "multifactor-input-v7"
ANALYSIS_INPUT_VERSION = "axis-input-v3"
ANALYSIS_MODES = ("unit_analysis", "deck_analysis", "candidate_insert", "state_evaluation")
DECK_SECTIONS = ("main", "extra", "side")
FEATURE_VERSION = "multifactor-plan-grounded-v7"
ROLES = ("large_axis", "small_axis", "strategic_core", "support_role", "generic_utility")
DEFAULT_LABEL_RUBRIC = {
    "version": "construction-role-and-readiness-separated-v7",
    "large_axis": "relatively substantial investment or relatively complete linked mechanism package; need not be the main core",
    "small_axis": "compact functional chain or mechanism package; need not be strategically secondary",
    "strategic_core": "organizes or substantially advances the declared primary plan, including starters and resources; current activation readiness is separate",
    "support_role": "contributes complementary capability to the declared plan; can coexist with strategic core and be large; current readiness is separate",
    "generic_utility": "conditional cross-construction utility of the minimum membership for an explicit function and construction plan, including costs and restrictions; instantaneous readiness is a separate output",
    "joint_dependency": "all necessary companions belong to the unit; package labels never propagate to members or imply singleton utility",
    "scale_reference": "explicit deck/extra/normal-summon budgets and a frozen annotation comparison set; no universal count cutoff",
    "annotation": "independent contextual soft labels; retain unknown/disagreement; record rubric, annotator and intervention scope",
}

# Every value is in [0, 1]. Fractions/rates require their actual upstream
# denominator; ordinal human assessments require an explicit source rubric.
GROUP_FACTORS = (
    "recognized_effect_coverage", "activation_access", "one_card_independence",
    "internal_dependency", "external_dependency", "required_brick_fraction",
    "search_reach", "recycle_closure", "resource_cost", "resource_return",
    "normal_summon_load", "summon_lock_risk", "goal_contribution",
    "main_space", "extra_space", "interaction_utility", "board_break_utility",
    "recovery_utility", "starter_utility", "followup_utility", "engine_goal_share",
    "cross_context_utility", "effect_send_grave", "effect_mill", "effect_search",
    "effect_special_summon", "effect_negate", "effect_destroy", "effect_draw",
    "effect_recover", "effect_fusion", "effect_once_per_turn", "effect_player_lock",
    "unit_minimum_size", "unit_joint_dependency", "unit_available_fraction",
    "unit_dependencies_reviewed", "unit_conditions_satisfied",
    "requested_function_negate_activation", "requested_function_destroy", "requested_function_draw",
    "requested_function_search", "requested_function_recover", "requested_function_send_grave",
    "requested_function_mill", "requested_function_special_summon", "requested_function_starter", "requested_function_follow_up",
    "text_reference_density", "text_cycle_fraction", "text_operation_variety",
    "text_grave_fraction", "text_banish_fraction", "text_counter_fraction",
    "text_pendulum_fraction", "text_transform_fraction", "text_normal_trigger_fraction",
    "type_fusion_fraction", "type_synchro_fraction", "type_xyz_fraction",
    "type_link_fraction", "type_ritual_fraction", "text_ritual_summon_fraction",
    "text_special_summon_fraction", "text_search_fraction", "text_negate_fraction",
    "text_destroy_fraction", "text_draw_fraction", "text_recover_fraction",
    "text_normal_summon_fraction", "text_additional_normal_fraction", "text_tribute_fraction",
    "node_primary_plan", "node_plan_clause", "node_goal_only_card", "construction_present", "plan_known", "plan_reference_coverage", "plan_clause_position", "plan_intent_marker", "plan_purpose_marker", "plan_before_marker", "plan_after_marker", "type_monster_fraction", "type_spell_fraction", "type_trap_fraction", "type_quickplay_fraction", "plan_operation_fusion", "plan_operation_link", "plan_operation_synchro", "plan_operation_xyz", "plan_operation_ritual", "plan_operation_search", "plan_operation_recover", "plan_operation_special_summon", "plan_operation_negate", "plan_operation_destroy", "plan_operation_draw", "plan_operation_grave", "plan_operation_banish", "plan_operation_attack", "plan_operation_pendulum", "plan_operation_spell_counter", "plan_operation_tribute",
    "condition_construct_compatibility",
    "semantic_resource_return_fraction", "semantic_variable_draw_fraction", "semantic_grave_to_deck_fraction", "semantic_deck_to_hand_fraction", "semantic_effect_opponent_fraction", "semantic_effect_self_fraction",
    "unit_excess_member_fraction", "requested_function_tribute",
    "node_aggregate", "node_member", "node_route", "node_condition", "node_option", "member_available", "member_required_quantity", "semantic_effect_count", "semantic_activation_known", "semantic_cost_observed", "semantic_target_observed", "semantic_unparsed_fraction", "semantic_restriction_observed", "condition_satisfied", "condition_unsatisfied", "condition_unknown", "condition_mentions_hand", "condition_mentions_deck", "condition_mentions_grave", "condition_mentions_field", "condition_mentions_extra", "condition_mentions_normal", "condition_mentions_opponent", "condition_mentions_special",
)
CONTEXT_FACTORS = (
    "plan_known", "plan_reference_coverage",
    "goal_engine_weight", "goal_interaction_weight", "goal_board_break_weight",
    "goal_recovery_weight", "goal_consistency_weight", "remaining_main_space",
    "remaining_extra_space", "normal_summon_headroom", "starter_gap",
    "interaction_gap", "board_break_gap", "recovery_gap", "going_first_weight",
    "objective_fusion", "objective_link", "objective_synchro", "objective_ritual",
    "objective_search", "objective_special_summon", "objective_negate", "objective_destroy",
    "objective_draw", "objective_recover", "objective_grave", "objective_banish",
    "objective_spell_counter", "objective_pendulum", "objective_transformation", "objective_attack",
    "objective_xyz", "objective_normal_summon", "objective_additional_normal_summon", "objective_tribute",
)
RELATION_FACTORS = (
    "plan_contains_clause", "plan_actor_reference", "plan_terminal_reference", "plan_resource_reference", "plan_text_precedes",
    "enables", "requires", "searches", "recovers", "competes_normal_summon",
    "summon_lock_conflict", "resource_competition", "goal_complementarity", "loop_closure",
    "contains", "co_constructed", "literal_reference", "candidate_search", "candidate_recover", "candidate_special_summon", "candidate_send_grave", "candidate_resource_return", "candidate_material", "dependency_and", "requires_condition", "has_option", "alternative_to",
)
FAMILIES = {"group": GROUP_FACTORS, "context": CONTEXT_FACTORS, "relation": RELATION_FACTORS}

# v7 legacy route-level features ("primary plan" entities/clauses/operations).
# They are not the mechanism tuple: mechanism metadata lives on
# RoleInput.mechanism and is never encoded into these factor families.
ROUTE_FACTOR_PREFIXES = ("plan_", "objective_")


class FactorContractError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


DEFAULT_LABEL_PROTOCOL_SHA256 = digest(DEFAULT_LABEL_RUBRIC)


def sha256_text(value, label):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise FactorContractError(f"{label} must be a SHA256 digest")


def text(value, label, *, optional=False):
    if not isinstance(value, str) or len(value) > 2048 or (not optional and not value.strip()):
        raise FactorContractError(f"bounded {label} text required")


def unit(value, label):
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
        raise FactorContractError(f"{label} must be finite in [0, 1]")


def fields(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise FactorContractError(f"expected exactly these fields: {sorted(keys)}")
    return value


@dataclass(frozen=True)
class Observation:
    value: float | None = None
    confidence: float = 0.0
    uncertainty: float = 1.0
    source: str = ""

    def __post_init__(self):
        unit(self.confidence, "confidence")
        unit(self.uncertainty, "uncertainty")
        text(self.source, "observation source", optional=self.value is None)
        if self.value is None:
            if self.confidence != 0 or self.uncertainty != 1:
                raise FactorContractError("unknown value requires confidence 0 and uncertainty 1")
        else:
            unit(self.value, "observation")

    def channels(self):
        # A measured zero has known=1. An absent observation has known=0.
        return (0.0 if self.value is None else self.value * self.confidence,
                float(self.value is not None), float(self.confidence), float(self.uncertainty))

    def to_dict(self):
        return dict(value=self.value, confidence=self.confidence,
                    uncertainty=self.uncertainty, source=self.source)

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, ("value", "confidence", "uncertainty", "source")))


@dataclass(frozen=True)
class Factors:
    family: str
    items: tuple[tuple[str, Observation], ...] = ()

    def __post_init__(self):
        if self.family not in FAMILIES or not isinstance(self.items, tuple):
            raise FactorContractError("known factor family and immutable items required")
        names = []
        for item in self.items:
            if (not isinstance(item, tuple) or len(item) != 2 or item[0] not in FAMILIES[self.family]
                    or not isinstance(item[1], Observation)):
                raise FactorContractError("unknown factor or untyped observation")
            names.append(item[0])
        if len(set(names)) != len(names):
            raise FactorContractError("duplicate factor")
        order = {name: i for i, name in enumerate(FAMILIES[self.family])}
        object.__setattr__(self, "items", tuple(sorted(self.items, key=lambda item: order[item[0]])))

    @classmethod
    def from_mapping(cls, family, mapping):
        if not isinstance(mapping, dict):
            raise FactorContractError("factor mapping required")
        return cls(family, tuple((name, value if isinstance(value, Observation)
                                  else Observation.from_dict(value)) for name, value in mapping.items()))

    @classmethod
    def observed(cls, family, values, *, source, confidence=1.0, uncertainty=0.0):
        """Convenience for explicitly sourced values, never a label generator."""
        return cls.from_mapping(family, {key: Observation(value, confidence, uncertainty, source)
                                         for key, value in values.items()})

    def get(self, name):
        if name not in FAMILIES[self.family]:
            raise FactorContractError("unknown factor")
        return dict(self.items).get(name, Observation())

    def without(self, name):
        self.get(name)
        return Factors(self.family, tuple((key, value) for key, value in self.items if key != name))

    def channels(self):
        return [channel for name in FAMILIES[self.family] for channel in self.get(name).channels()]

    def to_dict(self):
        return {"family": self.family, "observations": {name: item.to_dict() for name, item in self.items}}

    @classmethod
    def from_dict(cls, value):
        fields(value, ("family", "observations"))
        return cls.from_mapping(value["family"], value["observations"])


def _factor_family(value, expected):
    if not isinstance(value, Factors) or value.family != expected:
        raise FactorContractError(f"{expected} factors required")


@dataclass(frozen=True)
class Group:
    key: str
    factors: Factors
    member_refs: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    unit: object | None = None

    def __post_init__(self):
        text(self.key, "group key")
        _factor_family(self.factors, "group")
        from .functional_units import FunctionalContract, UNIT_FACTORS
        if self.unit is not None and not isinstance(self.unit, FunctionalContract):
            raise FactorContractError("typed functional unit contract required")
        if any(name in UNIT_FACTORS for name, _ in self.factors.items):
            raise FactorContractError("unit factors are derived from dependencies, not supplied as free scores")
        for name, limit in (("member_refs", 128), ("notes", 256)):
            values = getattr(self, name)
            if not isinstance(values, tuple) or len(values) > limit:
                raise FactorContractError(f"bounded immutable {name} required")
            for value in values:
                text(value, name)

    def to_dict(self):
        return dict(key=self.key, factors=self.factors.to_dict(), member_refs=list(self.member_refs), notes=list(self.notes),
                    unit=None if self.unit is None else self.unit.to_dict())

    def encoded_factors(self):
        from .functional_units import derived_unit_factors
        derived = derived_unit_factors(self.unit, self.member_refs)
        return Factors("group", self.factors.items + derived.items)

    @classmethod
    def from_dict(cls, value):
        fields(value, ("key", "factors", "member_refs", "notes", "unit"))
        if not isinstance(value["member_refs"], list) or not isinstance(value["notes"], list):
            raise FactorContractError("member references and notes must be JSON arrays")
        from .functional_units import FunctionalContract
        return cls(value["key"], Factors.from_dict(value["factors"]), tuple(value["member_refs"]), tuple(value["notes"]),
                   None if value["unit"] is None else FunctionalContract.from_dict(value["unit"]))


@dataclass(frozen=True)
class Relation:
    source: str
    target: str
    factors: Factors

    def __post_init__(self):
        text(self.source, "relation source")
        text(self.target, "relation target")
        if self.source == self.target:
            raise FactorContractError("internal loops belong to the group's recycle factor")
        _factor_family(self.factors, "relation")

    def to_dict(self):
        return dict(source=self.source, target=self.target, factors=self.factors.to_dict())

    @classmethod
    def from_dict(cls, value):
        fields(value, ("source", "target", "factors"))
        return cls(value["source"], value["target"], Factors.from_dict(value["factors"]))


CORE_ACTION_CLASSES = ("resource_acquisition", "resource_conversion", "interaction", "victory")
CORE_ACTIONS = {
    "resource_acquisition": ("mill", "draw_filter", "search", "recover", "revive"),
    "resource_conversion": ("fusion", "synchro", "xyz", "link", "ritual", "special_summon", "tribute", "place"),
    "interaction": ("destroy", "banish", "negate", "control", "lock", "hand_rip", "field_wipe"),
    "victory": ("battle", "burn", "deck_out", "alternate_win"),
}
ZONES = ("deck", "grave", "hand", "field", "banish", "extra", "unknown")
PAYOFFS = ("grave_effect", "banish_effect", "hand_effect", "destroy_trigger", "summon_trigger",
           "activation_trigger", "search_recover", "resource_loop", "board_terminal", "disruption",
           "lock", "battle_damage", "burn", "deck_out", "alternate_win", "unknown")
CONSTRAINTS = ("fiend", "dragon", "aqua", "spellcaster", "warrior", "light", "dark", "water",
               "fire", "earth", "wind", "level_2", "rank_2", "spell", "trap", "once_per_turn",
               "hard_once", "self_lock", "zone", "named_partner", "field_spell", "counter",
               "extra_deck", "unknown")
WIN_PATHS = ("battle", "resource", "lock", "burn", "deck_out", "alternate_win", "unknown")
MECHANISM_ROLES = ("primary", "secondary", "mixed")


def is_route_factor(name):
    """True for v7 route-level factors; mechanism metadata is not a factor."""
    return isinstance(name, str) and name.startswith(ROUTE_FACTOR_PREFIXES)


@dataclass(frozen=True)
class Mechanism:
    """Deck-level mechanism tuple, independent of a specific route or CB.

    It answers what the deck repeatedly does (core action), on which zones,
    with what payoff and constraints, and how it wins. It is metadata: the
    role network never encodes it as an input feature.
    """

    core_action: str
    core_action_class: str
    source_zone: str
    destination_zone: str
    payoff: tuple[str, ...]
    constraints: tuple[str, ...]
    win_path: str
    confidence: float = 1.0
    source: str = ""
    period_ref: str | None = None
    condition_zones: tuple[str, ...] = ()
    role: str = "primary"

    def __post_init__(self):
        text(self.source, "mechanism source")
        if self.period_ref is not None:
            text(self.period_ref, "mechanism period reference")
        unit(self.confidence, "mechanism confidence")
        if self.core_action_class not in CORE_ACTION_CLASSES:
            raise FactorContractError("unknown mechanism core-action class")
        if self.core_action not in CORE_ACTIONS[self.core_action_class]:
            raise FactorContractError("core action does not belong to its class")
        if self.source_zone not in ZONES or self.destination_zone not in ZONES:
            raise FactorContractError("unknown mechanism resource zone")
        if (not isinstance(self.payoff, tuple) or not 1 <= len(self.payoff) <= 8 or
                any(value not in PAYOFFS for value in self.payoff) or len(set(self.payoff)) != len(self.payoff)):
            raise FactorContractError("bounded distinct mechanism payoffs required")
        if (not isinstance(self.constraints, tuple) or len(self.constraints) > 8 or
                any(value not in CONSTRAINTS for value in self.constraints) or
                len(set(self.constraints)) != len(self.constraints)):
            raise FactorContractError("bounded distinct mechanism constraints required")
        if (not isinstance(self.condition_zones, tuple) or len(self.condition_zones) > 4 or
                any(value not in ZONES for value in self.condition_zones) or
                len(set(self.condition_zones)) != len(self.condition_zones)):
            raise FactorContractError("bounded distinct mechanism condition zones required")
        if self.win_path not in WIN_PATHS:
            raise FactorContractError("unknown mechanism win path")
        if self.role not in MECHANISM_ROLES:
            raise FactorContractError("mechanism must be primary, secondary or mixed")

    def to_dict(self):
        return dict(core_action=self.core_action, core_action_class=self.core_action_class,
                    source_zone=self.source_zone, destination_zone=self.destination_zone,
                    payoff=list(self.payoff), constraints=list(self.constraints),
                    win_path=self.win_path, confidence=self.confidence, source=self.source,
                    period_ref=self.period_ref, condition_zones=list(self.condition_zones), role=self.role)

    @classmethod
    def from_dict(cls, value):
        fields(value, ("core_action", "core_action_class", "source_zone", "destination_zone",
                       "payoff", "constraints", "win_path", "confidence", "source",
                       "period_ref", "condition_zones", "role"))
        for key in ("payoff", "constraints", "condition_zones"):
            if not isinstance(value[key], list):
                raise FactorContractError("mechanism collections must be JSON arrays")
        return cls(value["core_action"], value["core_action_class"], value["source_zone"],
                   value["destination_zone"], tuple(value["payoff"]), tuple(value["constraints"]),
                   value["win_path"], value["confidence"], value["source"], value["period_ref"],
                   tuple(value["condition_zones"]), value["role"])


LABEL_STATUSES = ("known", "unknown", "conflict", "not_applicable")
REVIEW_STATUSES = ("unreviewed", "reviewed", "resolved", "disputed")


@dataclass(frozen=True)
class LabelCell:
    """One per-cell label with evidence state, never a bare zero for missing."""

    value: bool | float | str | None = None
    status: str = "unknown"
    confidence: float = 1.0
    evidence_kind: str = "unknown"
    evidence_refs: tuple[str, ...] = ()
    review_status: str = "unreviewed"

    def __post_init__(self):
        if self.status not in LABEL_STATUSES:
            raise FactorContractError("label status must be known/unknown/conflict/not_applicable")
        if self.status == "known":
            if self.value is None:
                raise FactorContractError("known label requires a value")
            if isinstance(self.value, str):
                text(self.value, "label value")
            elif type(self.value) is not bool:
                unit(self.value, "label value")
        elif self.value is not None:
            raise FactorContractError("unknown/conflict/not_applicable label must not carry a value")
        unit(self.confidence, "label confidence")
        text(self.evidence_kind, "label evidence kind")
        if (not isinstance(self.evidence_refs, tuple) or len(self.evidence_refs) > 32 or
                any(not isinstance(v, str) for v in self.evidence_refs)):
            raise FactorContractError("bounded distinct evidence references required")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise FactorContractError("duplicate evidence reference")
        for ref in self.evidence_refs:
            text(ref, "evidence reference")
        if self.review_status not in REVIEW_STATUSES:
            raise FactorContractError("unknown review status")

    @property
    def known(self):
        return self.status == "known"

    def to_dict(self):
        return dict(value=self.value, status=self.status, confidence=self.confidence,
                    evidence_kind=self.evidence_kind, evidence_refs=list(self.evidence_refs),
                    review_status=self.review_status)

    @classmethod
    def from_dict(cls, value):
        fields(value, ("value", "status", "confidence", "evidence_kind", "evidence_refs", "review_status"))
        if not isinstance(value["evidence_refs"], list):
            raise FactorContractError("label evidence refs must be a JSON array")
        return cls(value["value"], value["status"], value["confidence"], value["evidence_kind"],
                   tuple(value["evidence_refs"]), value["review_status"])


    @classmethod
    def from_legacy(cls, value):
        if isinstance(value, cls):
            return value
        return cls() if value is None else cls(value=value, status="known", evidence_kind="legacy")

    def validate_domain(self, choices=None):
        if self.known:
            if choices is None:
                if type(self.value) is not bool:
                    unit(self.value, "binary label value")
            elif self.value not in choices:
                raise FactorContractError("label value outside task vocabulary")
        return self


TASK_DOMAINS = {
    "mechanism": None, "axis_membership": None, "axis_function": None,
    "function_role": None, "contribution": None, "pair_relation": None,
    "axis_position": ("main", "secondary", "support"),
    "axis_origin": ("intrinsic", "external", "mixed"),
    "transferability": ("open", "conditional", "closed"),
    "receiver_compatibility": ("compatible", "conflict"),
    "state_readiness": ("executable", "blocked"),
    "copy_preference": ("left", "equal", "right"),
}


@dataclass(frozen=True)
class LabelSet:
    """One supervised scope; omitted cells remain unknown even if complete."""
    task: str
    subject: tuple[str, ...]
    cells: tuple[tuple[str, LabelCell], ...]
    annotation_complete: bool = False

    def __post_init__(self):
        if not isinstance(self.task, str) or self.task not in TASK_DOMAINS:
            raise FactorContractError("unknown label task")
        if not isinstance(self.subject, tuple) or not 1 <= len(self.subject) <= 4:
            raise FactorContractError("label subject requires 1..4 references")
        for ref in self.subject:
            text(ref, "label subject")
        if not isinstance(self.cells, tuple) or len(self.cells) > 4096:
            raise FactorContractError("bounded immutable label cells required")
        seen = set()
        for item in self.cells:
            if not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[1], LabelCell):
                raise FactorContractError("typed named label cells required")
            key, cell = item
            text(key, "label coordinate")
            if key in seen:
                raise FactorContractError("duplicate label coordinate")
            seen.add(key)
            cell.validate_domain(TASK_DOMAINS[self.task])
        if type(self.annotation_complete) is not bool:
            raise FactorContractError("annotation_complete must be boolean")

    def get(self, coordinate):
        return dict(self.cells).get(coordinate, LabelCell())

    def to_dict(self):
        return dict(task=self.task, subject=list(self.subject), cells={k: c.to_dict() for k, c in self.cells},
                    annotation_complete=self.annotation_complete)

    @classmethod
    def from_dict(cls, value):
        fields(value, ("task", "subject", "cells", "annotation_complete"))
        if not isinstance(value["subject"], list) or not isinstance(value["cells"], dict):
            raise FactorContractError("label subject array and cell mapping required")
        return cls(value["task"], tuple(value["subject"]), tuple((k, LabelCell.from_dict(v)) for k, v in value["cells"].items()), value["annotation_complete"])


def _amounts(value, label):
    if not isinstance(value, tuple) or len(value) > 128:
        raise FactorContractError(f"{label}: bounded immutable card/count pairs required")
    seen = set()
    for item in value:
        if not isinstance(item, tuple) or len(item) != 2:
            raise FactorContractError(f"{label}: card/count pair required")
        code, count = item
        if type(code) is not int or code <= 0 or type(count) is not int or not 1 <= count <= 99:
            raise FactorContractError(f"{label}: positive card id and count 1..99 required")
        if code in seen:
            raise FactorContractError(f"{label}: duplicate card id")
        seen.add(code)


@dataclass(frozen=True)
class DeckSpec:
    main: tuple[tuple[int, int], ...] | None = None
    extra: tuple[tuple[int, int], ...] | None = None
    side: tuple[tuple[int, int], ...] | None = None

    def __post_init__(self):
        for section in DECK_SECTIONS:
            value = getattr(self, section)
            if value is not None:
                _amounts(value, "deck." + section)
                object.__setattr__(self, section, tuple(sorted(value)))

    def section_counts(self):
        return {s: None if getattr(self, s) is None else sum(n for _, n in getattr(self, s)) for s in DECK_SECTIONS}

    def to_dict(self):
        return {s: None if getattr(self, s) is None else [list(v) for v in getattr(self, s)] for s in DECK_SECTIONS}

    @classmethod
    def from_dict(cls, value):
        fields(value, DECK_SECTIONS)
        result = []
        for s in DECK_SECTIONS:
            pairs = value[s]
            if pairs is not None and (not isinstance(pairs, list) or any(not isinstance(p, list) or len(p) != 2 for p in pairs)):
                raise FactorContractError(f"deck.{s}: null or card/count arrays required")
            result.append(None if pairs is None else tuple(tuple(p) for p in pairs))
        return cls(*result)


@dataclass(frozen=True)
class UnitSpec:
    unit_id: str
    members: tuple[tuple[int, int], ...]
    function_id: str
    variant: str = "complete"

    def __post_init__(self):
        for name in ("unit_id", "function_id", "variant"):
            text(getattr(self, name), "unit." + name)
        _amounts(self.members, "unit.members")
        if not self.members:
            raise FactorContractError("unit.members must not be empty")
        object.__setattr__(self, "members", tuple(sorted(self.members)))

    def to_dict(self):
        return dict(unit_id=self.unit_id, members=[list(v) for v in self.members], function_id=self.function_id, variant=self.variant)

    @classmethod
    def from_dict(cls, value):
        fields(value, ("unit_id", "members", "function_id", "variant"))
        if not isinstance(value["members"], list) or any(not isinstance(p, list) or len(p) != 2 for p in value["members"]):
            raise FactorContractError("unit.members: card/count arrays required")
        return cls(value["unit_id"], tuple(tuple(p) for p in value["members"]), value["function_id"], value["variant"])


@dataclass(frozen=True)
class AnalysisContext:
    format: str = "unknown"
    period: str = "unknown"
    rule_version: str = "unknown"
    public_resources: tuple | None = None

    def __post_init__(self):
        for name in ("format", "period", "rule_version"):
            text(getattr(self, name), "analysis_context." + name)
        if self.public_resources is not None:
            from .conditions import Resource
            if not isinstance(self.public_resources, tuple) or len(self.public_resources) > 512 or any(not isinstance(r, Resource) for r in self.public_resources):
                raise FactorContractError("analysis_context.public_resources: resource tuple or null required")

    def to_dict(self):
        return dict(format=self.format, period=self.period, rule_version=self.rule_version,
                    public_resources=None if self.public_resources is None else [r.to_dict() for r in self.public_resources])

    @classmethod
    def from_dict(cls, value):
        fields(value, ("format", "period", "rule_version", "public_resources"))
        from .conditions import Resource
        stock = value["public_resources"]
        if stock is not None and not isinstance(stock, list):
            raise FactorContractError("analysis_context.public_resources: array or null required")
        return cls(value["format"], value["period"], value["rule_version"], None if stock is None else tuple(Resource.from_dict(r) for r in stock))


@dataclass(frozen=True)
class CandidateInsert:
    add: DeckSpec
    remove: DeckSpec
    section_limits: tuple[tuple[str, int], ...]

    def __post_init__(self):
        if not isinstance(self.add, DeckSpec) or not isinstance(self.remove, DeckSpec):
            raise FactorContractError("insertion: typed add/remove decks required")
        if any(getattr(d, s) is None for d in (self.add, self.remove) for s in DECK_SECTIONS):
            raise FactorContractError("insertion: changes must declare all sections")
        if not isinstance(self.section_limits, tuple) or len(self.section_limits) != 3 or any(not isinstance(p, tuple) or len(p) != 2 for p in self.section_limits):
            raise FactorContractError("insertion: three section/limit pairs required")
        if {s for s, _ in self.section_limits} != set(DECK_SECTIONS) or any(type(n) is not int or n < 0 for _, n in self.section_limits):
            raise FactorContractError("insertion: nonnegative limits required")

    def apply(self, deck):
        from collections import Counter
        result = []
        for section in DECK_SECTIONS:
            original = getattr(deck, section)
            if original is None:
                raise FactorContractError(f"insertion: deck.{section} must be known")
            counts = Counter(dict(original))
            for code, count in getattr(self.remove, section):
                if counts[code] < count:
                    raise FactorContractError(f"insertion.remove.{section}: unavailable copies")
                counts[code] -= count
            counts.update(dict(getattr(self.add, section)))
            if sum(counts.values()) > dict(self.section_limits)[section]:
                raise FactorContractError(f"insertion.{section}: slot limit exceeded")
            result.append(tuple(sorted((c, n) for c, n in counts.items() if n)))
        return DeckSpec(*result)

    def to_dict(self):
        return dict(add=self.add.to_dict(), remove=self.remove.to_dict(), section_limits=dict(self.section_limits))

    @classmethod
    def from_dict(cls, value):
        fields(value, ("add", "remove", "section_limits"))
        if not isinstance(value["section_limits"], dict):
            raise FactorContractError("insertion.section_limits: mapping required")
        return cls(DeckSpec.from_dict(value["add"]), DeckSpec.from_dict(value["remove"]), tuple(sorted(value["section_limits"].items())))


def visible_state(value):
    if value is None:
        return
    if not isinstance(value, tuple) or len(value) > 128:
        raise FactorContractError("visible_state: bounded observations required")
    seen = set()
    for item in value:
        if not isinstance(item, tuple) or len(item) != 2:
            raise FactorContractError("visible_state: key/value pair required")
        key, observation = item
        text(key, "visible_state.key")
        if key in seen:
            raise FactorContractError("visible_state: duplicate key")
        seen.add(key)
        if observation is not None:
            text(observation, "visible_state.value", optional=True)


@dataclass(frozen=True)
class RoleInput:
    context_ref: str
    context: Factors
    groups: tuple[Group, ...]
    relations: tuple[Relation, ...] = ()
    mechanism: Mechanism | None = None
    analysis_mode: str | None = None
    analysis_context: AnalysisContext | None = None
    deck: DeckSpec | None = None
    unit_definition: UnitSpec | None = None
    visible_state: tuple | None = None
    insertion: CandidateInsert | None = None

    def __post_init__(self):
        text(self.context_ref, "context reference")
        _factor_family(self.context, "context")
        if self.analysis_mode is None:
            if any(v is not None for v in (self.analysis_context, self.deck, self.unit_definition, self.visible_state, self.insertion)):
                raise FactorContractError("analysis_mode required for v3 fields")
        else:
            if self.analysis_mode not in ANALYSIS_MODES or not isinstance(self.analysis_context, AnalysisContext):
                raise FactorContractError("analysis_mode and typed analysis_context required")
            if self.mechanism is not None:
                raise FactorContractError("v3 mechanism supervision belongs outside observations")
            for v, kind, name in ((self.deck, DeckSpec, "deck"), (self.unit_definition, UnitSpec, "unit"), (self.insertion, CandidateInsert, "insertion")):
                if v is not None and not isinstance(v, kind):
                    raise FactorContractError(f"typed {name} required")
            if self.analysis_mode in ("unit_analysis", "candidate_insert", "state_evaluation") and self.unit_definition is None:
                raise FactorContractError("analysis_mode requires unit and requested function")
            if self.analysis_mode in ("deck_analysis", "candidate_insert") and self.deck is None:
                raise FactorContractError("analysis_mode requires deck")
            visible_state(self.visible_state)
            if self.visible_state is not None:
                object.__setattr__(self, "visible_state", tuple(sorted(self.visible_state)))
            if self.analysis_mode == "state_evaluation" and not self.visible_state:
                raise FactorContractError("state_evaluation requires visible_state")
            if self.analysis_mode == "candidate_insert":
                if self.insertion is None:
                    raise FactorContractError("candidate_insert requires explicit changes and slot limits")
                after = self.insertion.apply(self.deck)
                from collections import Counter
                installed = Counter()
                for section in DECK_SECTIONS:
                    installed.update(dict(getattr(after, section)))
                if any(installed[code] < count for code, count in self.unit_definition.members):
                    raise FactorContractError("insertion: resulting deck does not contain declared unit")
            elif self.insertion is not None:
                raise FactorContractError("insertion only applies to candidate_insert")
        if self.mechanism is not None and not isinstance(self.mechanism, Mechanism):
            raise FactorContractError("typed mechanism metadata or None required")
        low, high = (1, 64) if self.analysis_mode is None else (0, 512)
        if (not isinstance(self.groups, tuple) or not low <= len(self.groups) <= high
                or any(not isinstance(group, Group) for group in self.groups)):
            raise FactorContractError(f"{low}..{high} typed groups required")
        keys = {group.key for group in self.groups}
        if len(keys) != len(self.groups):
            raise FactorContractError("duplicate group key")
        if any(group.unit is not None and group.unit.context_ref != self.context_ref for group in self.groups):
            raise FactorContractError("functional unit context differs from role input")
        if not isinstance(self.relations, tuple) or len(self.relations) > len(keys) * (len(keys) - 1):
            raise FactorContractError("bounded immutable relations required")
        pairs = set()
        for relation in self.relations:
            if (not isinstance(relation, Relation) or relation.source not in keys or relation.target not in keys
                    or (relation.source, relation.target) in pairs):
                raise FactorContractError("unknown/duplicate relation endpoint")
            pairs.add((relation.source, relation.target))

    def to_dict(self):
        value = dict(schema_version=INPUT_VERSION, context_ref=self.context_ref, context=self.context.to_dict(),
                     groups=[group.to_dict() for group in self.groups], relations=[edge.to_dict() for edge in self.relations])
        if self.mechanism is not None:
            value["mechanism"] = self.mechanism.to_dict()
        if self.analysis_mode is not None:
            value.pop("schema_version")
            value.update(analysis_mode=self.analysis_mode, analysis_context=self.analysis_context.to_dict(),
                         deck=None if self.deck is None else self.deck.to_dict(),
                         unit=None if self.unit_definition is None else self.unit_definition.to_dict(),
                         visible_state=None if self.visible_state is None else [list(p) for p in self.visible_state],
                         insertion=None if self.insertion is None else self.insertion.to_dict())
            return dict(schema_version=ANALYSIS_INPUT_VERSION, observations=value)
        return value

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise FactorContractError("role input object required")
        if value.get("schema_version") == ANALYSIS_INPUT_VERSION:
            if set(value) not in ({"schema_version", "observations"}, {"schema_version", "observations", "provenance"}):
                raise FactorContractError("v3 requires observations, optional provenance; no targets")
            v = fields(value["observations"], ("context_ref", "context", "groups", "relations", "analysis_mode", "analysis_context", "deck", "unit", "visible_state", "insertion"))
            if not isinstance(v["groups"], list) or not isinstance(v["relations"], list):
                raise FactorContractError("observations.groups/relations: arrays required")
            state = v["visible_state"]
            if state is not None and (not isinstance(state, list) or any(not isinstance(p, list) or len(p) != 2 for p in state)):
                raise FactorContractError("visible_state: array of key/value arrays required")
            return cls(v["context_ref"], Factors.from_dict(v["context"]), tuple(Group.from_dict(g) for g in v["groups"]),
                       tuple(Relation.from_dict(r) for r in v["relations"]),
                       analysis_mode=v["analysis_mode"], analysis_context=AnalysisContext.from_dict(v["analysis_context"]),
                       deck=None if v["deck"] is None else DeckSpec.from_dict(v["deck"]),
                       unit_definition=None if v["unit"] is None else UnitSpec.from_dict(v["unit"]),
                       visible_state=None if state is None else tuple(tuple(p) for p in state),
                       insertion=None if v["insertion"] is None else CandidateInsert.from_dict(v["insertion"]))
        if set(value) not in (set(("schema_version", "context_ref", "context", "groups", "relations")),
                              set(("schema_version", "context_ref", "context", "groups", "relations", "mechanism"))):
            raise FactorContractError("expected role input fields with optional mechanism")
        if value["schema_version"] not in (INPUT_VERSION, "multifactor-input-v2"):
            raise FactorContractError("unsupported role input version")
        if not isinstance(value["groups"], list) or not isinstance(value["relations"], list):
            raise FactorContractError("groups and relations must be JSON arrays")
        mechanism = None if value.get("mechanism") is None else Mechanism.from_dict(value["mechanism"])
        return cls(value["context_ref"], Factors.from_dict(value["context"]),
                   tuple(Group.from_dict(group) for group in value["groups"]),
                   tuple(Relation.from_dict(edge) for edge in value["relations"]), mechanism)


def schema_fingerprint():
    return digest(dict(input_version=INPUT_VERSION, feature_version=FEATURE_VERSION,
                       families=FAMILIES, roles=ROLES, channels=("value*confidence", "known", "confidence", "uncertainty")))


# Separate graph schema: adding M3 observations must not change legacy tensors.
GRAPH_VERSION = "axis-graph-v3"
GRAPH_KINDS = ("card", "effect", "mode", "function", "axis", "dependency", "condition", "section", "resource")
GRAPH_RELATIONS = ("contains", "realizes", "calls", "provides", "consumes", "material",
                   "requires", "alternative", "conflicts", "recycles", "has_condition", "parent_axis")
GRAPH_FUNCTIONS = ("negate_activation", "destroy", "draw", "search", "recover", "send_grave",
    "mill", "special_summon", "starter", "follow_up", "tribute", "fusion_summon",
    "return_cards_to_deck", "banish", "ritual", "synchro", "xyz", "link", "protect",
    "interfere", "resource_supply", "resource_conversion")
GRAPH_ATTRIBUTES = ("scope_structure", "scope_state", "quantity", "capacity", "observation_known", "level", "attack", "defense", "unseen_function", "unparsed",
    "condition_all", "condition_any", "condition_at_least_k", "condition_not", "min_count",
    "consume", "occupy", "retain", "reusable", "stage_deck", "stage_activation", "stage_resolution",
    "stage_post_resolution", "reason_effect", "reason_cost", "reason_procedure", "owner_self", "owner_opponent",
    "from_deck", "from_hand", "from_grave", "from_field", "from_extra", "from_banish",
    "to_deck", "to_hand", "to_grave", "to_field", "to_extra", "to_banish",
    "limit_by_name", "limit_by_instance", "limit_use", "limit_activation", "count_maximum",
    "limit_card_activation", "limit_effect_activation",
    "resource_card", "resource_member", "resource_normal_summon", "resource_lp", "resource_counter", "resource_material", "resource_other",
    "zone_deck", "zone_hand", "zone_grave", "zone_field", "zone_extra", "zone_banish",
    "until_deck", "until_activation", "until_resolution", "until_post_resolution") + tuple(
    "race_bit_" + str(i) for i in range(26)) + tuple("attribute_bit_" + str(i) for i in range(7))


def _ref_amounts(value, label):
    if not isinstance(value, tuple) or not 1 <= len(value) <= 512:
        raise FactorContractError(label + ": 1..512 immutable reference/count pairs required")
    seen = set()
    for item in value:
        if not isinstance(item, tuple) or len(item) != 2:
            raise FactorContractError(label + ": reference/count pair required")
        ref, amount = item
        text(ref, label + ".ref")
        if ref in seen or type(amount) is not int or not 1 <= amount <= 4096:
            raise FactorContractError(label + ": distinct references and positive integer quantities required")
        seen.add(ref)


def _functions(value):
    if not isinstance(value, tuple) or any(not isinstance(v, str) for v in value) or len(set(value)) != len(value) or any(v not in GRAPH_FUNCTIONS for v in value):
        raise FactorContractError("controlled immutable graph functions required")


def _modes(value):
    if not isinstance(value, tuple):
        raise FactorContractError("immutable mode choices required")
    seen = set()
    for pair in value:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise FactorContractError("mode scope/choice pair required")
        for v in pair:
            text(v, "mode reference")
        if pair[0] in seen:
            raise FactorContractError("duplicate/conflicting mode scope")
        seen.add(pair[0])


@dataclass(frozen=True)
class StructureLink:
    source: str
    target: str
    kind: str
    functions: tuple[str, ...] = ()
    function_ref: str | None = None
    required: bool = False
    quantity: int = 1
    confidence: float = 1.0
    condition: object | None = None
    mode_choices: tuple[tuple[str, str], ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self):
        text(self.source, "structure source")
        text(self.target, "structure target")
        if self.source == self.target or self.kind not in GRAPH_RELATIONS:
            raise FactorContractError("typed directed non-self structure link required")
        _functions(self.functions)
        if self.function_ref is not None:
            text(self.function_ref, "structure function reference")
        if type(self.required) is not bool or type(self.quantity) is not int or not 1 <= self.quantity <= 4096:
            raise FactorContractError("structure required flag/quantity invalid")
        if self.required and self.kind != "requires":
            raise FactorContractError("only explicit requires links can be mandatory")
        unit(self.confidence, "structure confidence")
        if self.condition is not None:
            from .functional_units import BranchConditions
            if not isinstance(self.condition, BranchConditions):
                raise FactorContractError("typed branch conditions required")
        _modes(self.mode_choices)
        if not isinstance(self.evidence_refs, tuple):
            raise FactorContractError("immutable evidence references required")
        for ref in self.evidence_refs:
            text(ref, "structure evidence")

    def to_dict(self):
        return dict(source=self.source, target=self.target, kind=self.kind, functions=list(self.functions),
            function_ref=self.function_ref, required=self.required, quantity=self.quantity, confidence=self.confidence,
            condition=None if self.condition is None else self.condition.to_dict(),
            mode_choices=[list(v) for v in self.mode_choices], evidence_refs=list(self.evidence_refs))

    def structural_key(self):
        value = self.to_dict()
        value.pop("evidence_refs")
        value.pop("confidence")
        return digest(value)

    @classmethod
    def from_dict(cls, value):
        from .functional_units import BranchConditions
        fields(value, ("source", "target", "kind", "functions", "function_ref", "required", "quantity",
                       "confidence", "condition", "mode_choices", "evidence_refs"))
        if any(not isinstance(value[k], list) for k in ("functions", "mode_choices", "evidence_refs")):
            raise FactorContractError("structure collections must be JSON arrays")
        if any(not isinstance(p, list) or len(p) != 2 for p in value["mode_choices"]):
            raise FactorContractError("mode pairs required")
        return cls(value["source"], value["target"], value["kind"], tuple(value["functions"]), value["function_ref"],
            value["required"], value["quantity"], value["confidence"],
            None if value["condition"] is None else BranchConditions.from_dict(value["condition"]),
            tuple(tuple(p) for p in value["mode_choices"]), tuple(value["evidence_refs"]))


@dataclass(frozen=True)
class FunctionSeed:
    function_ref: str
    members: tuple[tuple[str, int], ...]
    functions: tuple[str, ...]
    conditions: tuple = ()
    mode_choices: tuple[tuple[str, str], ...] = ()
    confidence: float = 1.0
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self):
        text(self.function_ref, "seed function reference")
        _ref_amounts(self.members, "seed members")
        _functions(self.functions)
        _modes(self.mode_choices)
        from .functional_units import BranchConditions
        if not isinstance(self.conditions, tuple) or any(not isinstance(v, BranchConditions) for v in self.conditions):
            raise FactorContractError("typed seed conditions required")
        unit(self.confidence, "seed confidence")
        if not isinstance(self.evidence_refs, tuple):
            raise FactorContractError("immutable seed evidence required")
        for ref in self.evidence_refs:
            text(ref, "seed evidence")

    def to_dict(self):
        return dict(function_ref=self.function_ref, members=[list(v) for v in self.members],
                    functions=list(self.functions), conditions=[v.to_dict() for v in self.conditions],
                    mode_choices=[list(v) for v in self.mode_choices], confidence=self.confidence,
                    evidence_refs=list(self.evidence_refs))

    @classmethod
    def from_dict(cls, value):
        from .functional_units import BranchConditions
        fields(value, ("function_ref", "members", "functions", "conditions", "mode_choices", "confidence", "evidence_refs"))
        if any(not isinstance(value[k], list) for k in ("members", "functions", "conditions", "mode_choices", "evidence_refs")):
            raise FactorContractError("seed collections must be arrays")
        if any(not isinstance(v, list) or len(v) != 2 for v in value["members"] + value["mode_choices"]):
            raise FactorContractError("seed member/mode pairs required")
        return cls(value["function_ref"], tuple(tuple(v) for v in value["members"]), tuple(value["functions"]),
                   tuple(BranchConditions.from_dict(v) for v in value["conditions"]),
                   tuple(tuple(v) for v in value["mode_choices"]), value["confidence"], tuple(value["evidence_refs"]))


@dataclass(frozen=True)
class GraphNode:
    ref: str
    kind: str
    factors: Factors
    copies: tuple[int | None, int | None, int | None] = (None, None, None)
    functions: tuple[str, ...] = ()
    attributes: tuple[tuple[str, float | None], ...] = ()
    section: str | None = None
    empty_status: str = "not_applicable"
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self):
        text(self.ref, "graph node reference")
        if self.kind not in GRAPH_KINDS or self.section is not None and self.section not in DECK_SECTIONS:
            raise FactorContractError("unknown graph node kind/section")
        _factor_family(self.factors, "group")
        forbidden = ("goal_contribution", "engine_goal_share", "cross_context_utility")
        if any(k in forbidden or k.startswith(("plan_", "node_primary_plan", "node_plan_clause")) for k, _ in self.factors.items):
            raise FactorContractError("route/role proxies are not v3 graph observations")
        if not isinstance(self.copies, tuple) or len(self.copies) != 3 or any(v is not None and (type(v) is not int or not 0 <= v <= 1000000000) for v in self.copies):
            raise FactorContractError("graph copies require three nonnegative integer/null counts")
        _functions(self.functions)
        if not isinstance(self.attributes, tuple):
            raise FactorContractError("immutable graph numeric attributes required")
        seen = set()
        for pair in self.attributes:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise FactorContractError("graph attribute pairs required")
            key, value = pair
            if key not in GRAPH_ATTRIBUTES or key in seen or value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise FactorContractError("unknown/duplicate/nonfinite graph attribute")
            if key in ("quantity", "capacity", "min_count") and value is not None and value < 0:
                raise FactorContractError("graph count attributes cannot be negative")
            seen.add(key)
        if self.empty_status not in ("empty", "nonempty", "unknown", "not_applicable"):
            raise FactorContractError("unknown graph empty status")
        if not isinstance(self.evidence_refs, tuple):
            raise FactorContractError("immutable node evidence required")
        for ref in self.evidence_refs:
            text(ref, "node evidence")

    def numeric_values(self):
        attrs = dict(self.attributes)
        return (tuple(float(self.kind == k) for k in GRAPH_KINDS) +
                tuple(float(self.section == k) for k in DECK_SECTIONS) +
                tuple(v for count in self.copies for v in (0.0 if count is None else float(count), float(count is not None))) +
                tuple(float(self.empty_status == k) for k in ("empty", "nonempty", "unknown", "not_applicable")) +
                tuple(float(k in self.functions) for k in GRAPH_FUNCTIONS) +
                tuple(v for k in GRAPH_ATTRIBUTES for v in (float(attrs[k]) if attrs.get(k) is not None else 0.0, float(attrs.get(k) is not None))) +
                tuple(self.factors.channels()))

    def to_dict(self):
        return dict(ref=self.ref, kind=self.kind, factors=self.factors.to_dict(), copies=list(self.copies),
            functions=list(self.functions), attributes=dict(self.attributes), section=self.section,
            empty_status=self.empty_status, evidence_refs=list(self.evidence_refs))

    @classmethod
    def from_dict(cls, value):
        fields(value, ("ref", "kind", "factors", "copies", "functions", "attributes", "section", "empty_status", "evidence_refs"))
        if any(not isinstance(value[k], list) for k in ("copies", "functions", "evidence_refs")) or not isinstance(value["attributes"], dict):
            raise FactorContractError("graph node array/mapping fields required")
        return cls(value["ref"], value["kind"], Factors.from_dict(value["factors"]), tuple(value["copies"]),
                   tuple(value["functions"]), tuple(value["attributes"].items()), value["section"], value["empty_status"], tuple(value["evidence_refs"]))


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    kind: str
    quantity: int = 1
    confidence: float = 1.0
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self):
        for ref in (self.source, self.target):
            text(ref, "graph edge endpoint")
        if self.source == self.target or self.kind not in GRAPH_RELATIONS or type(self.quantity) is not int or not 1 <= self.quantity <= 1000000000:
            raise FactorContractError("typed graph relation/quantity required")
        unit(self.confidence, "edge confidence")
        if not isinstance(self.evidence_refs, tuple):
            raise FactorContractError("immutable edge evidence required")
        for ref in self.evidence_refs:
            text(ref, "edge evidence")

    def to_dict(self):
        return dict(source=self.source, target=self.target, kind=self.kind, quantity=self.quantity,
                    confidence=self.confidence, evidence_refs=list(self.evidence_refs))

    @classmethod
    def from_dict(cls, value):
        fields(value, ("source", "target", "kind", "quantity", "confidence", "evidence_refs"))
        if not isinstance(value["evidence_refs"], list):
            raise FactorContractError("edge evidence array required")
        return cls(value["source"], value["target"], value["kind"], value["quantity"], value["confidence"], tuple(value["evidence_refs"]))


@dataclass(frozen=True)
class AnalysisGraph:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    def __post_init__(self):
        if not isinstance(self.nodes, tuple) or len(self.nodes) > 16384 or any(not isinstance(v, GraphNode) for v in self.nodes):
            raise FactorContractError("graph: bounded typed nodes required; input is not truncated")
        if not isinstance(self.edges, tuple) or len(self.edges) > 131072 or any(not isinstance(v, GraphEdge) for v in self.edges):
            raise FactorContractError("graph: bounded typed edges required; input is not truncated")
        refs = {v.ref for v in self.nodes}
        if len(refs) != len(self.nodes) or any(e.source not in refs or e.target not in refs for e in self.edges):
            raise FactorContractError("graph: duplicate nodes or absent relation endpoints")

    def numeric_view(self):
        indices = {n.ref: i for i, n in enumerate(self.nodes)}
        return dict(schema_version=GRAPH_VERSION, nodes=tuple(n.numeric_values() for n in self.nodes),
                    edges=tuple((indices[e.source], indices[e.target], GRAPH_RELATIONS.index(e.kind), e.quantity, e.confidence) for e in self.edges))

    def numeric_blocks(self, *, node_budget=128, edge_budget=2048):
        if any(type(v) is not int or v < 1 for v in (node_budget, edge_budget)):
            raise FactorContractError("positive numeric block budgets required")
        view = self.numeric_view()
        # Global indices permit layer-wise cross-block messages in M5. Nodes
        # and edges are each owned once; padding never adds a real entity.
        width = len(self.nodes[0].numeric_values()) if self.nodes else 0
        blocks = []
        for kind, budget, padding in (("nodes", node_budget, (0.0,) * width), ("edges", edge_budget, (-1, -1, -1, 0, 0.0))):
            rows = view[kind]
            for start in range(0, len(rows), budget):
                values = rows[start:start + budget]
                blocks.append(dict(kind=kind, start=start, values=values + (padding,) * (budget - len(values)),
                                   mask=(True,) * len(values) + (False,) * (budget - len(values))))
        return tuple(blocks)

    def to_dict(self):
        return dict(schema_version=GRAPH_VERSION, nodes=[n.to_dict() for n in self.nodes], edges=[e.to_dict() for e in self.edges])

    @classmethod
    def from_dict(cls, value):
        fields(value, ("schema_version", "nodes", "edges"))
        if value["schema_version"] != GRAPH_VERSION or not isinstance(value["nodes"], list) or not isinstance(value["edges"], list):
            raise FactorContractError("versioned graph arrays required")
        return cls(tuple(GraphNode.from_dict(n) for n in value["nodes"]), tuple(GraphEdge.from_dict(e) for e in value["edges"]))


# Service DTOs do not extend the encoder, label schema or checkpoint protocol.
RECOGNITION_MODES = ("off", "observe", "assist")


@dataclass(frozen=True)
class AnalysisValue:
    status: str = "unknown"
    value: object = None
    reason_code: str = "INSUFFICIENT_EVIDENCE"
    producer: str = ""
    version: str = ""
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self):
        if self.status not in ("known", "unknown", "not_applicable", "conflict"):
            raise FactorContractError("invalid analysis value status")
        if (self.status == "known") != (self.value is not None):
            raise FactorContractError("only known analysis values carry a value")
        text(self.reason_code, "analysis reason")
        json.dumps(self.value, allow_nan=False)

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class CapabilityStatus:
    status: str = "unavailable"
    producer: str = ""
    version: str = ""
    evidence_refs: tuple[str, ...] = ()
    validated: bool = False
    calibrated: bool = False

    def __post_init__(self):
        if self.status not in ("unavailable", "disabled", "untrained", "engineering_only", "failed",
                               "trained_uncalibrated", "weakly_supervised_uncalibrated", "available", "deterministic_only"):
            raise FactorContractError("invalid capability status")
        if type(self.validated) is not bool or type(self.calibrated) is not bool:
            raise FactorContractError("explicit capability validation/calibration flags required")
        if not isinstance(self.evidence_refs, tuple) or any(not isinstance(r, str) or not r for r in self.evidence_refs):
            raise FactorContractError("capability evidence references required as tuple")
        if self.validated:
            text(self.producer, "validated capability producer")
            text(self.version, "validated capability version")
            if not self.evidence_refs:
                raise FactorContractError("validated capability requires evidence")
        if self.status == "available" and not (self.validated and self.calibrated):
            raise FactorContractError("available learned capability requires validation and calibration")

    @property
    def assist_available(self):
        return self.status == "available" or self.status == "deterministic_only" and self.validated

    def to_dict(self):
        return dict(asdict(self), assist_available=self.assist_available)


@dataclass(frozen=True)
class CopyChange:
    card_id: int
    section: str
    quantity: int = 1

    def __post_init__(self):
        if type(self.card_id) is not int or self.card_id <= 0 or self.section not in DECK_SECTIONS:
            raise FactorContractError("copy change requires card ID and actual deck section")
        if type(self.quantity) is not int or not 1 <= self.quantity <= 99:
            raise FactorContractError("copy change requires quantity 1..99")

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, ("card_id", "section", "quantity")))


@dataclass(frozen=True)
class SamplingSpec:
    section: str
    draws: int
    assumption: str = "uniform_initial_single_sample_without_prior_movement"

    def __post_init__(self):
        if self.section not in DECK_SECTIONS or type(self.draws) is not int or self.draws < 0:
            raise FactorContractError("sampling requires a deck section and nonnegative draws")
        if self.assumption != "uniform_initial_single_sample_without_prior_movement":
            raise FactorContractError("unsupported sampling assumption")


@dataclass(frozen=True)
class ExternalLegality:
    result: str
    subject_deck: DeckSpec
    context_ref: str
    producer: str
    version: str
    evidence_refs: tuple[str, ...]
    rules: AnalysisContext = field(default_factory=AnalysisContext)
    declared_goal: str = "unspecified"

    def __post_init__(self):
        if self.result not in ("pass", "fail") or not isinstance(self.subject_deck, DeckSpec):
            raise FactorContractError("external legality requires pass/fail and its exact deck")
        for name in ("context_ref", "producer", "version"):
            text(getattr(self, name), "legality." + name)
        if not isinstance(self.evidence_refs, tuple) or not self.evidence_refs:
            raise FactorContractError("external legality requires evidence references")
        for ref in self.evidence_refs:
            text(ref, "legality evidence")
        if not isinstance(self.rules, AnalysisContext):
            raise FactorContractError("external legality requires its exact rules")
        text(self.declared_goal, "external legality goal")


@dataclass(frozen=True)
class AnalysisRequestContext:
    context_ref: str = "analysis"
    rules: AnalysisContext = field(default_factory=AnalysisContext)
    mode: str = "observe"
    declared_goal: str = "unspecified"
    factors: Factors = field(default_factory=lambda: Factors("context"))
    visible_state: tuple | None = None
    resource_coverage: bool = False
    sampling: SamplingSpec | None = None
    external_legality: ExternalLegality | None = None

    def __post_init__(self):
        text(self.context_ref, "service context reference")
        text(self.declared_goal, "explicit declared goal")
        if not isinstance(self.rules, AnalysisContext) or self.mode not in RECOGNITION_MODES:
            raise FactorContractError("typed analysis rules and recognition mode required")
        _factor_family(self.factors, "context")
        visible_state(self.visible_state)
        if self.visible_state == ():
            raise FactorContractError("visible state must be nonempty or explicitly unknown (null)")
        if type(self.resource_coverage) is not bool:
            raise FactorContractError("explicit resource coverage required")
        if self.resource_coverage and self.rules.public_resources is None:
            raise FactorContractError("complete resource coverage cannot accompany unknown resources")
        if self.sampling is not None and not isinstance(self.sampling, SamplingSpec):
            raise FactorContractError("typed sampling declaration required")
        if self.external_legality is not None and not isinstance(self.external_legality, ExternalLegality):
            raise FactorContractError("typed producer/version-bound external legality required")

    def to_dict(self):
        return dict(context_ref=self.context_ref, rules=self.rules.to_dict(), mode=self.mode,
                    declared_goal=self.declared_goal, factors=self.factors.to_dict(),
                    visible_state=None if self.visible_state is None else [list(v) for v in self.visible_state],
                    resource_coverage=self.resource_coverage,
                    sampling=None if self.sampling is None else asdict(self.sampling),
                    external_legality=None if self.external_legality is None else dict(asdict(self.external_legality),
                        subject_deck=self.external_legality.subject_deck.to_dict(), rules=self.external_legality.rules.to_dict()))

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or not set(value) <= set(cls.__dataclass_fields__):
            raise FactorContractError("service context accepts observations only; unknown/label blocks rejected")
        value = dict(value)
        if "rules" in value:
            value["rules"] = AnalysisContext.from_dict(value["rules"])
        if "factors" in value:
            value["factors"] = Factors.from_dict(value["factors"])
        if value.get("visible_state") is not None:
            value["visible_state"] = tuple(tuple(v) for v in value["visible_state"])
        if value.get("sampling") is not None:
            value["sampling"] = SamplingSpec(**fields(value["sampling"], ("section", "draws", "assumption")))
        if value.get("external_legality") is not None:
            row = fields(value["external_legality"], ("result", "subject_deck", "context_ref", "producer", "version", "evidence_refs", "rules", "declared_goal"))
            value["external_legality"] = ExternalLegality(**dict(row, subject_deck=DeckSpec.from_dict(row["subject_deck"]),
                                                               rules=AnalysisContext.from_dict(row["rules"]),
                                                               evidence_refs=tuple(row["evidence_refs"])))
        return cls(**value)


@dataclass(frozen=True)
class DeckAnalysis:
    context_ref: str
    mode: str
    declared_goal: str
    capabilities: dict = field(default_factory=dict)
    deck_summary: dict = field(default_factory=dict)
    units: tuple = ()
    axis_memberships: tuple = ()
    functions: tuple = ()
    requirements: tuple = ()
    genericity: dict = field(default_factory=dict)
    raw_prediction: tuple = ()
    derived_summary: dict = field(default_factory=dict)
    requirement_assessment: tuple = ()
    calibrated_scores: tuple = ()
    applied_prediction: tuple = ()
    legality: AnalysisValue = field(default_factory=lambda: AnalysisValue(reason_code="NO_EXTERNAL_LEGALITY"))
    explanation_refs: tuple = ()
    unresolved: tuple = ()

    def to_dict(self):
        return dict(schema_version="axis-result-v3", kind="deck_analysis", **asdict(self))


@dataclass(frozen=True)
class UnitAssessment(DeckAnalysis):
    unit: UnitSpec | None = None
    requested_function: str = ""
    definition_assessment: tuple = ()

    def to_dict(self):
        return dict(super().to_dict(), kind="unit_assessment")


@dataclass(frozen=True)
class CopyComparison:
    before: DeckAnalysis
    after: DeckAnalysis
    operation: dict
    differences: dict
    functions: tuple[str, ...]
    preference: AnalysisValue = field(default_factory=lambda: AnalysisValue(reason_code="NO_VALIDATED_COMPARISON"))

    def to_dict(self):
        return dict(schema_version="axis-result-v3", kind="copy_comparison", before=self.before.to_dict(),
                    after=self.after.to_dict(), operation=self.operation, differences=asdict(self)['differences'],
                    functions=list(self.functions), preference=self.preference.to_dict())
