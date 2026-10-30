"""Explicitly artificial observations; no real-card role labels live here."""

from pathlib import Path
import tempfile

from ygo_kito.multifactor import Factors, Group, Relation, RoleInput
from ygo_kito.multifactor.functional_units import FunctionalContract, Dependency, KnownCondition, MemberAmount


def synthetic_contract(context_ref, members, *, key="synthetic-function"):
    return FunctionalContract(key, context_ref, "synthetic specified function", (MemberAmount(members[0]),),
                              () if len(members) == 1 else (Dependency(members[0], tuple(MemberAmount(ref) for ref in members[1:]), "synthetic necessary companions"),),
                              tuple(members), (KnownCondition("synthetic window", "satisfied", "synthetic assumption"),),
                              "synthetic dependency review", function_tags=("negate_activation",))


def task_temporary_directory():
    # The Windows sandbox can redirect system TEMP outside granted roots.
    # Test artifacts belong to this checkout, whose write permission is explicit.
    root = Path(__file__).resolve().parents[1] / ".cache" / "multifactor-test-temp"
    root.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=root)


def synthetic_example(*, context_ref="synthetic-goal-v1", interaction_gap=0.8, conflict=0.1):
    context = Factors.observed("context", {
        "goal_engine_weight": 0.7, "goal_interaction_weight": 0.6,
        "interaction_gap": interaction_gap, "starter_gap": 0.2,
        "remaining_main_space": 0.2, "remaining_extra_space": 0.3,
        "normal_summon_headroom": 0.1,
    }, source="synthetic engineering factors; no semantic capability evidence")
    groups = (
        Group("core", Factors.observed("group", {
            "activation_access": 0.7, "goal_contribution": 0.8, "engine_goal_share": 0.9,
            "main_space": 0.3, "normal_summon_load": 0.8, "summon_lock_risk": 0.1,
        }, source="synthetic-core"), ("synthetic-card:17", "synthetic-card:18"),
              unit=synthetic_contract(context_ref, ("synthetic-card:17", "synthetic-card:18"), key="core-function")),
        Group("package", Factors.observed("group", {
            "activation_access": 0.6, "one_card_independence": 0.2,
            "external_dependency": 0.4, "internal_dependency": 0.7,
            "required_brick_fraction": 0.2, "goal_contribution": 0.6,
            "interaction_utility": 0.8, "resource_cost": 0.3,
            "main_space": 0.1, "extra_space": 0.1, "summon_lock_risk": conflict,
        }, source="synthetic-package"), ("synthetic-card:51", "synthetic-card:52"),
              unit=synthetic_contract(context_ref, ("synthetic-card:51", "synthetic-card:52"), key="package-function")),
        Group("single", Factors.observed("group", {
            "activation_access": 0.5, "one_card_independence": 0.8,
            "external_dependency": 0.1, "goal_contribution": 0.4,
            "main_space": 0.025, "summon_lock_risk": 0.0,
        }, source="synthetic-single"), ("synthetic-card:77",), unit=synthetic_contract(context_ref, ("synthetic-card:77",), key="single-function")),
    )
    relations = (
        Relation("core", "package", Factors.observed("relation", {"enables": 0.8, "resource_competition": 0.2}, source="synthetic-edge-a")),
        Relation("package", "core", Factors.observed("relation", {"requires": 0.7, "summon_lock_conflict": conflict}, source="synthetic-edge-b")),
    )
    return RoleInput(context_ref, context, groups, relations)
