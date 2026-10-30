"""Private-evaluator hint release policy; no reference card list is required.

Only completed, uniquely identified construction evaluations are submitted here.
The caller remains responsible for computing the score and persisting ``to_dict``
atomically alongside its construction-cycle record. A low score is an optimization
signal, not a certificate about the execution or legality of any combo.

Hints deliberately use a closed mechanism vocabulary. Neither free-form card text,
card names/IDs, exact list quantities nor arbitrary metadata can enter a hint.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from collections.abc import Mapping


STATE_VERSION = 1
HINT_STAGES = ("main_axis", "secondary_axes", "generic_tools")

_ROLES = frozenset(("access", "grave_trigger", "fusion", "recycle", "secondary",
                    "interaction", "protection", "material", "recovery", "bridge", "side_plan"))
_FUNCTIONS = frozenset((
    "normal_summon_access", "self_special_summon", "deck_to_grave_by_effect",
    "grave_trigger", "fusion_from_grave", "shuffle_fusion_materials", "search",
    "recovery", "draw", "special_summon", "negate_monster_effect", "negate_activation",
    "destroy", "banish", "return_to_hand", "flip_face_down", "remove_backrow",
    "board_break", "material_substitute", "level_bridge", "grave_disruption",
    "resource_recycling", "body_generation", "opponent_turn_interaction",
    "ritual_access", "ritual_summon",
))
_CONDITIONS = frozenset((
    "sent_to_grave_by_effect", "empty_own_monster_field", "opponent_activates_monster_effect",
    "another_fairy_in_hand", "required_partner_available", "materials_compatible",
    "timing_window", "can_pay_cost", "need_targets", "grave_resources_available",
    "theme_resource_available", "sideboarding_plan", "access_route_verified",
    "not_yet_used_this_turn", "own_main_phase", "opponent_controls_relevant_card",
    "required_hand_ritual_monster", "ritual_materials_available",
))
_REQUIREMENTS = frozenset((
    "partner_required", "source_text_review_required", "legal_in_environment",
    "supported_effect_evidence", "extra_deck_destination", "compatible_materials",
    "preserve_main_axis", "route_evidence", "engine_validation", "available_cost_resource",
    "separate_effect_from_cost", "respect_shared_limits", "complete_functional_unit",
))
_LIMITS = frozenset((
    "once_per_effect", "shared_name_limit", "normal_summon_lock", "extra_deck_lock",
    "summon_count_lock", "end_phase_banish", "both_players_affected", "cost_not_effect",
    "targeting_required", "non_targeting", "battle_damage_zero", "resource_competition",
    "summon_material_restriction", "activation_window", "shared_activation_limit",
))
_RISKS = frozenset((
    "random_dependency", "brick_when_drawn", "opponent_benefits", "self_conflict",
    "shared_grave_resource", "unproven_edge", "missing_partner", "unknown_effect",
    "side_only", "once_per_turn_collision", "normal_summon_competition",
    "unavailable_extra_resource", "unavailable_cost_resource", "mirror_match_conflict",
))
_RELATIONS = frozenset(("enables", "feeds", "recovers", "converts", "protects", "competes", "requires"))
_TEMPLATE_FIELDS = frozenset(("blocks", "edges", "conditions", "requirements", "limits", "risks"))
_BLOCK_FIELDS = frozenset(("role", "functions", "conditions", "requirements", "limits", "risks"))


def _block(role, functions, *, conditions=(), requirements=(), limits=(), risks=()):
    return dict(role=role, functions=list(functions), conditions=list(conditions),
                requirements=list(requirements), limits=list(limits), risks=list(risks))


def _template(blocks, edges=(), *, conditions=(), requirements=(), limits=(), risks=()):
    return dict(blocks=list(blocks), edges=list(edges), conditions=list(conditions),
                requirements=list(requirements), limits=list(limits), risks=list(risks))


DEFAULT_HINT_TEMPLATES = {
    "main_axis": _template([
        _block("access", ("normal_summon_access", "deck_to_grave_by_effect"),
               requirements=("separate_effect_from_cost",), risks=("random_dependency",)),
        _block("grave_trigger", ("grave_trigger", "fusion_from_grave"),
               conditions=("sent_to_grave_by_effect", "materials_compatible"),
               requirements=("compatible_materials", "extra_deck_destination"),
               limits=("shared_name_limit",)),
        _block("recycle", ("shuffle_fusion_materials", "resource_recycling")),
    ], [dict(source="access", target="grave_trigger", relation="feeds"),
        dict(source="grave_trigger", target="recycle", relation="enables")],
        requirements=("preserve_main_axis", "route_evidence", "legal_in_environment"),
        risks=("unknown_effect", "unproven_edge")),
    "secondary_axes": _template([
        _block("secondary", ("deck_to_grave_by_effect", "body_generation"),
               requirements=("supported_effect_evidence",), risks=("opponent_benefits",)),
        _block("recovery", ("resource_recycling", "grave_disruption"),
               conditions=("can_pay_cost", "need_targets"),
               risks=("shared_grave_resource",)),
        _block("bridge", ("material_substitute", "level_bridge"),
               requirements=("compatible_materials", "extra_deck_destination", "route_evidence"),
               risks=("normal_summon_competition",)),
    ], [dict(source="secondary", target="recovery", relation="feeds"),
        dict(source="secondary", target="bridge", relation="enables")],
        requirements=("preserve_main_axis", "complete_functional_unit"),
        limits=("resource_competition", "summon_material_restriction"),
        risks=("self_conflict", "unproven_edge")),
    "generic_tools": _template([
        _block("interaction", ("negate_monster_effect", "opponent_turn_interaction"),
               conditions=("required_partner_available", "can_pay_cost", "timing_window"),
               requirements=("partner_required", "complete_functional_unit"),
               risks=("missing_partner", "brick_when_drawn")),
        _block("protection", ("negate_activation", "grave_disruption"),
               conditions=("need_targets", "timing_window"),
               risks=("mirror_match_conflict",)),
        _block("side_plan", ("board_break", "remove_backrow"),
               conditions=("sideboarding_plan", "opponent_controls_relevant_card"),
               limits=("activation_window", "both_players_affected"), risks=("side_only",)),
    ], requirements=("legal_in_environment", "available_cost_resource", "respect_shared_limits"),
        risks=("self_conflict", "unavailable_cost_resource")),
}


def _number(value, name, *, minimum=0, maximum=100):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        value = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}]")
    return value


def _identifier(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"{name} must be a nonempty string of at most 512 characters")
    return value


def _tokens(value, vocabulary, name):
    if not isinstance(value, (list, tuple)) or any(not isinstance(x, str) or x not in vocabulary for x in value):
        raise ValueError(f"{name} accepts only the documented mechanism vocabulary")
    if len(value) != len(set(value)):
        raise ValueError(f"{name} contains duplicate tokens")
    return list(value)


def validate_hint_template(value):
    """Return a detached allowlisted template or reject unknown/free-form fields."""
    if not isinstance(value, Mapping) or set(value) != _TEMPLATE_FIELDS:
        raise ValueError("hint template fields must be blocks/edges/conditions/requirements/limits/risks")
    result = {}
    for name, vocabulary in (("conditions", _CONDITIONS), ("requirements", _REQUIREMENTS),
                             ("limits", _LIMITS), ("risks", _RISKS)):
        result[name] = _tokens(value[name], vocabulary, name)
    blocks = value["blocks"]
    if not isinstance(blocks, (list, tuple)):
        raise ValueError("blocks must be a list")
    result["blocks"] = []
    roles = set()
    for block in blocks:
        if not isinstance(block, Mapping) or set(block) != _BLOCK_FIELDS:
            raise ValueError("block contains unsupported fields")
        role = block["role"]
        if not isinstance(role, str) or role not in _ROLES or role in roles:
            raise ValueError("block role must be a unique anonymous mechanism role")
        roles.add(role)
        item = {"role": role, "functions": _tokens(block["functions"], _FUNCTIONS, "functions")}
        for name, vocabulary in (("conditions", _CONDITIONS), ("requirements", _REQUIREMENTS),
                                 ("limits", _LIMITS), ("risks", _RISKS)):
            item[name] = _tokens(block[name], vocabulary, name)
        result["blocks"].append(item)
    edges = value["edges"]
    if not isinstance(edges, (list, tuple)):
        raise ValueError("edges must be a list")
    result["edges"] = []
    seen = set()
    for edge in edges:
        if not isinstance(edge, Mapping) or set(edge) != {"source", "target", "relation"}:
            raise ValueError("edge contains unsupported fields")
        source, target, relation = edge["source"], edge["target"], edge["relation"]
        if not all(isinstance(x, str) for x in (source, target, relation)) or source not in roles or target not in roles or relation not in _RELATIONS:
            raise ValueError("edge must connect existing anonymous roles with a known relation")
        identity = (source, target, relation)
        if identity in seen:
            raise ValueError("duplicate edge")
        seen.add(identity)
        result["edges"].append(dict(source=source, target=target, relation=relation))
    return result


@dataclass(frozen=True)
class HintPolicy:
    reference_score: float = 70.0
    minimum_ratio: float = 0.8
    failures_per_hint: int = 2

    def __post_init__(self):
        _number(self.reference_score, "reference_score", minimum=0.000001)
        _number(self.minimum_ratio, "minimum_ratio", minimum=0.000001, maximum=1)
        if isinstance(self.failures_per_hint, bool) or not isinstance(self.failures_per_hint, int) or self.failures_per_hint < 1:
            raise ValueError("failures_per_hint must be a positive integer")

    @property
    def threshold(self):
        return float(self.reference_score) * float(self.minimum_ratio)

    def to_dict(self):
        return dict(reference_score=float(self.reference_score), minimum_ratio=float(self.minimum_ratio),
                    failures_per_hint=self.failures_per_hint)


class ReferenceHintTracker:
    """Count distinct evaluated construction cycles, independently per goal/period.

    Each distinct ``evaluation_id`` binds its entire input permanently. A new ID
    for the same (scope, cycle, candidate) is a read of the same failure and does
    not count. The same candidate in a *new* optimization cycle does count: it is
    evidence of another completed attempt, not a fresh read of the old result.
    Changing the candidate never resets a scope's consecutive-failure counter.

    A duplicate returns no new ``hint``; ``released_hints`` can retrieve already
    authorized hints after a lost response. The host must save this state to keep
    these guarantees across restarts.
    """

    def __init__(self, *, policy=None, templates=None):
        self.policy = policy or HintPolicy()
        if not isinstance(self.policy, HintPolicy):
            raise ValueError("policy must be HintPolicy")
        if templates is None:
            raise ValueError("explicit theme/goal-specific reference templates are required")
        if not isinstance(templates, Mapping) or set(templates) != set(HINT_STAGES):
            raise ValueError("templates must define exactly the three hint stages")
        self._templates = {stage: validate_hint_template(templates[stage]) for stage in HINT_STAGES}
        self._scopes = {}
        self._evaluations = {}
        self._attempts = {}

    @staticmethod
    def _scope(goal_id, period_id):
        if period_id == "2026-10":
            raise ValueError("2610 is autonomous and cannot receive old reference hints")
        return (_identifier(goal_id, "goal_id"), _identifier(period_id, "period_id"))

    def evaluate(self, *, evaluation_id, candidate_digest, cycle_id, goal_id, period_id, score):
        evaluation_id = _identifier(evaluation_id, "evaluation_id")
        candidate_digest = _identifier(candidate_digest, "candidate_digest")
        cycle_id = _identifier(cycle_id, "cycle_id")
        scope = self._scope(goal_id, period_id)
        score = _number(score, "score")
        row = dict(evaluation_id=evaluation_id, candidate_digest=candidate_digest, cycle_id=cycle_id,
                   goal_id=scope[0], period_id=scope[1], score=score)
        prior = self._evaluations.get(evaluation_id)
        if prior is not None:
            if prior != row:
                raise ValueError("evaluation_id was already bound to different evaluation data")
            return self._result(scope, score, counted=False, duplicate=True)
        attempt = (*scope, cycle_id, candidate_digest)
        if attempt in self._attempts:
            if self._attempts[attempt] != score:
                raise ValueError("the same cycle/candidate was already evaluated with a different score")
            self._evaluations[evaluation_id] = row
            return self._result(scope, score, counted=False, duplicate=True)
        state = self._scopes.setdefault(scope, dict(failure_streak=0, hints_released=0, evaluations_counted=0))
        state["evaluations_counted"] += 1
        stage = None
        if score < self.policy.threshold:
            state["failure_streak"] += 1
            if state["failure_streak"] % self.policy.failures_per_hint == 0 and state["hints_released"] < len(HINT_STAGES):
                stage = HINT_STAGES[state["hints_released"]]
                state["hints_released"] += 1
        else:
            state["failure_streak"] = 0
        self._attempts[attempt] = score
        self._evaluations[evaluation_id] = row
        return self._result(scope, score, counted=True, duplicate=False, stage=stage)

    def _result(self, scope, score, *, counted, duplicate, stage=None):
        state = self._scopes[scope]
        return dict(score=score, threshold=self.policy.threshold, force_optimization=score < self.policy.threshold,
                    counted=counted, duplicate=duplicate, failure_streak=state["failure_streak"],
                    evaluations_counted=state["evaluations_counted"], hints_released=state["hints_released"],
                    hint_stage=stage, hint=deepcopy(self._templates[stage]) if stage else None)

    def released_hints(self, *, goal_id, period_id):
        """Read only the stages already authorized in this scope; never advance it."""
        state = self._scopes.get(self._scope(goal_id, period_id), {"hints_released": 0})
        return [dict(stage=stage, hint=deepcopy(self._templates[stage]))
                for stage in HINT_STAGES[:state["hints_released"]]]

    def to_dict(self):
        return dict(schema_version=STATE_VERSION, policy=self.policy.to_dict(), templates=deepcopy(self._templates),
                    evaluations=deepcopy(list(self._evaluations.values())), scopes=[
                        dict(goal_id=goal, period_id=period, **deepcopy(state))
                        for (goal, period), state in sorted(self._scopes.items())])

    @classmethod
    def from_dict(cls, value):
        """Recompute all counters from persisted evaluations; reject corrupt state."""
        if not isinstance(value, Mapping) or set(value) != {"schema_version", "policy", "templates", "evaluations", "scopes"} or type(value["schema_version"]) is not int or value["schema_version"] != STATE_VERSION:
            raise ValueError("unsupported hint state schema")
        policy = value["policy"]
        if not isinstance(policy, Mapping) or set(policy) != {"reference_score", "minimum_ratio", "failures_per_hint"}:
            raise ValueError("invalid hint policy state")
        result = cls(policy=HintPolicy(**policy), templates=value["templates"])
        rows = value["evaluations"]
        if not isinstance(rows, list) or not isinstance(value["scopes"], list):
            raise ValueError("evaluations and scopes must be lists")
        for state in value["scopes"]:
            if not isinstance(state, Mapping) or set(state) != {"goal_id", "period_id", "failure_streak", "hints_released", "evaluations_counted"}:
                raise ValueError("invalid persisted scope")
            cls._scope(state["goal_id"], state["period_id"])
            for name in ("failure_streak", "hints_released", "evaluations_counted"):
                if type(state[name]) is not int or state[name] < 0:
                    raise ValueError("persisted counters must be nonnegative integers")
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != {"evaluation_id", "candidate_digest", "cycle_id", "goal_id", "period_id", "score"}:
                raise ValueError("invalid persisted evaluation")
            evaluation_id = _identifier(row["evaluation_id"], "evaluation_id")
            if evaluation_id in result._evaluations:
                raise ValueError("duplicate evaluation_id in persisted state")
            result.evaluate(**row)
        # Strict structural comparison also rejects unknown fields and altered counters.
        if result.to_dict()["scopes"] != value["scopes"]:
            raise ValueError("persisted scope counters disagree with evaluation history")
        return result
