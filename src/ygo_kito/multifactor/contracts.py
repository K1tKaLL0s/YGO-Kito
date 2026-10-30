"""Versioned, bounded observations. IDs, names and sources never become features."""

from dataclasses import dataclass
import hashlib
import json
import math

INPUT_VERSION = "multifactor-input-v2"
FEATURE_VERSION = "multifactor-functional-unit-v2"
ROLES = ("large_axis", "small_axis", "strategic_core", "support_role", "generic_utility")
DEFAULT_LABEL_RUBRIC = {
    "version": "user-confirmed-functional-unit-v2",
    "large_axis": "relatively substantial investment or relatively complete linked mechanism package; need not be the main core",
    "small_axis": "compact functional chain or mechanism package; need not be strategically secondary",
    "strategic_core": "carries the current main plan and has substantial measured goal loss under removal",
    "support_role": "contributes complementary capability while another group carries the main plan; may be large",
    "generic_utility": "utility of the minimum usable unit for the explicit function, context and dependency set; single-card and strict-joint utility are distinct",
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
)
CONTEXT_FACTORS = (
    "goal_engine_weight", "goal_interaction_weight", "goal_board_break_weight",
    "goal_recovery_weight", "goal_consistency_weight", "remaining_main_space",
    "remaining_extra_space", "normal_summon_headroom", "starter_gap",
    "interaction_gap", "board_break_gap", "recovery_gap", "going_first_weight",
)
RELATION_FACTORS = (
    "enables", "requires", "searches", "recovers", "competes_normal_summon",
    "summon_lock_conflict", "resource_competition", "goal_complementarity", "loop_closure",
)
FAMILIES = {"group": GROUP_FACTORS, "context": CONTEXT_FACTORS, "relation": RELATION_FACTORS}


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


@dataclass(frozen=True)
class RoleInput:
    context_ref: str
    context: Factors
    groups: tuple[Group, ...]
    relations: tuple[Relation, ...] = ()

    def __post_init__(self):
        text(self.context_ref, "context reference")
        _factor_family(self.context, "context")
        if (not isinstance(self.groups, tuple) or not 1 <= len(self.groups) <= 64
                or any(not isinstance(group, Group) for group in self.groups)):
            raise FactorContractError("1..64 typed groups required")
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
        return dict(schema_version=INPUT_VERSION, context_ref=self.context_ref, context=self.context.to_dict(),
                    groups=[group.to_dict() for group in self.groups], relations=[edge.to_dict() for edge in self.relations])

    @classmethod
    def from_dict(cls, value):
        fields(value, ("schema_version", "context_ref", "context", "groups", "relations"))
        if value["schema_version"] != INPUT_VERSION:
            raise FactorContractError("unsupported role input version")
        if not isinstance(value["groups"], list) or not isinstance(value["relations"], list):
            raise FactorContractError("groups and relations must be JSON arrays")
        return cls(value["context_ref"], Factors.from_dict(value["context"]),
                   tuple(Group.from_dict(group) for group in value["groups"]),
                   tuple(Relation.from_dict(edge) for edge in value["relations"]))


def schema_fingerprint():
    return digest(dict(input_version=INPUT_VERSION, feature_version=FEATURE_VERSION,
                       families=FAMILIES, roles=ROLES, channels=("value*confidence", "known", "confidence", "uncertainty")))
