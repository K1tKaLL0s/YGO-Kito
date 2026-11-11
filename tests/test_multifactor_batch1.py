"""M0–M2 semantic regressions. Added as source; execution is separately gated."""
from collections import Counter
from dataclasses import replace
from types import SimpleNamespace
import unittest

from ygo_kito.multifactor import (CandidateInsert, Condition, ConditionGroup, DeckSpec,
    FactorContractError, Factors, Group, LabelCell, LabelSet, Resource, RoleInput,
    SolverBudget, UnitSpec, migrate_v2_input, solve_requirements)
from ygo_kito.multifactor.functional_units import (BranchConditions, Dependency, FunctionalContract,
    KnownCondition, MemberAmount, assess_unit, minimum_member_branches, minimum_members)


def legacy():
    return RoleInput("context", Factors("context"), (Group("unit", Factors("group")),))


def unit_contract():
    return FunctionalContract("unit", "context", "search", (MemberAmount("A"),),
        (Dependency("A", (), "root", ((MemberAmount("B"),), (MemberAmount("C"),))),
         Dependency("B", (MemberAmount("D"),), "recursive companion")),
        ("A", "B", "C", "D"), (KnownCondition("window", "unknown", "not observed"),),
        "fixture", function_tags=("search",))


class V3ContractTests(unittest.TestCase):
    def test_empty_missing_and_four_modes_roundtrip(self):
        deck = DeckSpec(((1, 1),), (), None)
        self.assertEqual(deck.section_counts(), dict(main=1, extra=0, side=None))
        focus = UnitSpec("u", ((1, 1),), "search")
        for kwargs in (dict(analysis_mode="unit_analysis", unit=focus),
                       dict(analysis_mode="deck_analysis", deck=deck),
                       dict(analysis_mode="state_evaluation", unit=focus, visible_state=(("phase", "main"),)),
                       dict(analysis_mode="candidate_insert", deck=DeckSpec(((1, 1),), (), ()), unit=focus,
                            insertion=CandidateInsert(DeckSpec(((1, 1),), (), ()), DeckSpec((), (), ()),
                                                      (("main", 2), ("extra", 0), ("side", 0))))):
            parsed = RoleInput.from_dict(migrate_v2_input(legacy().to_dict(), **kwargs))
            self.assertEqual(RoleInput.from_dict(parsed.to_dict()), parsed)

    def test_insertion_requires_real_removal_and_declared_unit(self):
        change = CandidateInsert(DeckSpec((), (), ()), DeckSpec(((2, 1),), (), ()),
                                 (("main", 40), ("extra", 15), ("side", 15)))
        with self.assertRaises(FactorContractError):
            change.apply(DeckSpec(((1, 1),), (), ()))

    def test_partial_annotations_and_categorical_domains(self):
        labels = LabelSet("axis_membership", ("axis",), (("A", LabelCell(True, "known")),))
        self.assertEqual(LabelSet.from_dict(labels.to_dict()), labels)
        self.assertEqual(labels.get("B").status, "unknown")
        for status in ("unknown", "conflict", "not_applicable"):
            self.assertFalse(LabelCell(status=status).known)
        with self.assertRaises(FactorContractError):
            LabelSet("transferability", ("u",), (("class", LabelCell("arbitrary", "known")),))
        with self.assertRaises(FactorContractError):
            LabelCell(0, "unknown")

    def test_provenance_is_not_retained_as_observation(self):
        value = migrate_v2_input(legacy().to_dict(), analysis_mode="deck_analysis", deck=DeckSpec((), (), ()))
        expected = RoleInput.from_dict(value).to_dict()
        value["provenance"] = {"reference": "changed", "labels": "not observations"}
        self.assertEqual(RoleInput.from_dict(value).to_dict(), expected)

    def test_targets_keep_cells_and_unknown_masks(self):
        from ygo_kito.multifactor.training import Targets
        labels = (LabelCell(0, "known"), LabelCell(), LabelCell(status="conflict"),
                  LabelCell(status="not_applicable"), LabelCell())
        target = Targets(roles=(("unit", labels),), task_labels=(
            LabelSet("transferability", ("unit",), (("class", LabelCell("conditional", "known")),)),))
        self.assertEqual(Targets.from_dict(target.to_dict()), target)
        self.assertEqual([c.known for c in target.roles[0][1]], [True, False, False, False, False])


class AllocationTests(unittest.TestCase):
    def test_aggregated_supply_and_backtracking(self):
        self.assertTrue(solve_requirements(Condition("x", "s", 2),
            (Resource("x", "s"), Resource("x", "s")), coverage=True)["satisfied"])
        tree = ConditionGroup("all", (ConditionGroup("any", (Condition("x", "A"), Condition("x", "B"))), Condition("x", "A")))
        result = solve_requirements(tree, (Resource("x", "A"), Resource("x", "B")), coverage=True)
        self.assertTrue(result["satisfied"])
        for branch in result["branches"]:
            if branch["satisfied"]:
                self.assertEqual(len({tuple(v["slot"]) for v in branch["consumed"]}), 2)

    def test_at_least_k_and_pool_aliases_share_stock(self):
        tree = ConditionGroup("at_least_k", (Condition("x", "A"), Condition("x", "B")), 2)
        stock = (Resource("x", "A", pool_id="same"), Resource("x", "B", pool_id="same"))
        self.assertIs(solve_requirements(tree, stock, coverage=True)["satisfied"], False)

    def test_not_unknown_and_invalid_shape(self):
        absent = ConditionGroup("not", (Condition("x", "A", consume_mode="reusable"),))
        self.assertIsNone(solve_requirements(absent, ())["satisfied"])
        self.assertIs(solve_requirements(absent, (), coverage=True)["satisfied"], True)
        with self.assertRaises(FactorContractError):
            ConditionGroup("not", (Condition("x", "A"),))
        with self.assertRaises(FactorContractError):
            ConditionGroup("not", (Condition("x", "A", consume_mode="reusable"),) * 2)

    def test_occupancy_retention_and_distinctness(self):
        stock = (Resource("x", "A", available_until="post_resolution"),)
        retain = Condition("x", "A", consume_mode="retain", until_stage="resolution")
        during = Condition("x", "A", stage="resolution")
        after = Condition("x", "A", stage="post_resolution")
        self.assertFalse(solve_requirements(ConditionGroup("all", (retain, during)), stock, coverage=True)["satisfied"])
        self.assertTrue(solve_requirements(ConditionGroup("all", (retain, after)), stock, coverage=True)["satisfied"])
        distinct = Condition("x", "A", consume_mode="reusable", distinct_group="materials")
        self.assertFalse(solve_requirements(ConditionGroup("all", (distinct, distinct)), stock, coverage=True)["satisfied"])

    def test_unknown_stock_and_overflow_do_not_become_failure(self):
        atom = Condition("x", "A")
        self.assertIsNone(solve_requirements(atom, (Resource("x", "A", known=False),), coverage=True)["satisfied"])
        result = solve_requirements(atom, (Resource("x", "A"),), coverage=True, budget=SolverBudget(max_states=1))
        self.assertTrue(result["overflow"])
        self.assertIsNone(result["satisfied"])

    def test_side_is_not_current_game_supply(self):
        self.assertFalse(solve_requirements(Condition("x", "A"),
            (Resource("x", "A", deck_section="side"),), coverage=True)["satisfied"])


class FunctionalBranchTests(unittest.TestCase):
    def test_v11_fifteen_extra_cards_are_cost_resources_not_members(self):
        deck = DeckSpec(((1, 1),), tuple((code, 1) for code in range(101, 116)), ())
        contract = FunctionalContract("extra-cost-only", "context", "draw", (MemberAmount("A"),),
            (), ("A",), (KnownCondition("cost_window", "unknown", "fixture"),), "fixture",
            function_tags=("draw",),
            requirements=Condition("extra_cost", "any_extra", 15, deck_section="extra"))
        stock = tuple(Resource("extra_cost", "any_extra", amount, deck_section="extra",
                               resource_id="extra:" + str(code), source="fixture:extra-cost")
                      for code, amount in deck.extra)
        self.assertEqual(deck.section_counts()["extra"], 15)
        ready = assess_unit(contract, ("A",), resources=stock, coverage=True)
        self.assertTrue(ready["membership_ready"])
        self.assertTrue(ready["exact_minimum"])
        self.assertEqual(ready["minimum_members"], {"A": 1})
        self.assertEqual(ready["excess_members"], {})
        self.assertEqual([role["member_ref"] for role in ready["member_roles"]], ["A"])
        self.assertEqual(ready["genericity_scope"], "single_card")
        self.assertEqual(ready["state_readiness"], "unknown")
        self.assertFalse(ready["overflow"])
        witnesses = [branch for branch in ready["branches"][0]["requirement_assessment"]["branches"]
                     if branch["satisfied"] is True]
        self.assertEqual(len(witnesses), 1)
        self.assertEqual(len(witnesses[0]["consumed"]), 15)
        self.assertEqual({item["resource_id"] for item in witnesses[0]["consumed"]},
                         {resource.resource_id for resource in stock})
        self.assertEqual(len({tuple(item["slot"]) for item in witnesses[0]["consumed"]}), 15)
        for name, resources in (("empty_extra", ()), ("fourteen_extra", stock[:-1]),
                                ("side_only", tuple(replace(r, deck_section="side") for r in stock))):
            with self.subTest(resources=name):
                missing = assess_unit(contract, ("A",), resources=resources, coverage=True)
                self.assertFalse(missing["membership_ready"])
                self.assertEqual(missing["structural_status"], "partial")
                self.assertEqual(missing["minimum_members"], {"A": 1})
        independent = assess_unit(replace(contract, requirements=None), ("A",), coverage=True)
        self.assertTrue(independent["exact_minimum"])
        self.assertEqual(independent["minimum_members"], {"A": 1})

    def test_v12_removing_extension_keeps_base_function_complete(self):
        base = FunctionalContract("base", "context", "search", (MemberAmount("A"),),
            (Dependency("A", (MemberAmount("B"),), "fixture:base"),), ("A", "B"),
            (KnownCondition("window", "unknown", "fixture"),), "fixture", function_tags=("search",))
        extension = replace(base, key="extension", function_ref="draw", function_tags=("draw",),
            dependencies=(Dependency("A", (MemberAmount("B"), MemberAmount("C")), "fixture:extension"),),
            reviewed_members=("A", "B", "C"), requirements=Condition("extension_cost", "boost"))
        functions = {"base": base, "extension": extension}
        stock = (Resource("extension_cost", "boost"),)
        before = {key: assess_unit(value, ("A", "B", "C"), resources=stock, coverage=True)
                  for key, value in functions.items()}
        self.assertTrue(all(value["membership_ready"] for value in before.values()))
        self.assertEqual(before["extension"]["minimum_members"], {"A": 1, "B": 1, "C": 1})
        self.assertEqual(before["base"]["minimum_members"], {"A": 1, "B": 1})
        still_requested = assess_unit(extension, ("A", "B"), coverage=True)
        self.assertFalse(still_requested["membership_ready"])
        self.assertEqual(still_requested["missing_members"], {"C": 1})
        remaining = {key: value for key, value in functions.items() if key != "extension"}
        after = {key: assess_unit(value, ("A", "B"), coverage=True) for key, value in remaining.items()}
        self.assertEqual(set(after), {"base"})
        self.assertTrue(after["base"]["exact_minimum"])
        self.assertEqual(after["base"]["structural_status"], "complete")
        self.assertEqual(after["base"]["missing_members"], {})
        self.assertEqual(after["base"]["excess_members"], {})
        for field in ("minimum_members", "member_roles", "function_tags", "genericity_scope",
                      "structural_status", "state_readiness"):
            with self.subTest(field=field):
                self.assertEqual(after["base"][field], before["base"][field])
        self.assertEqual(after["base"]["function_tags"], ["search"])
        self.assertEqual(after["base"]["state_readiness"], "unknown")

    def test_recursive_alternatives_and_explicit_selection(self):
        contract = unit_contract()
        result = minimum_member_branches(contract)
        self.assertEqual({frozenset(b["members"]) for b in result["branches"]},
                         {frozenset(("A", "B", "D")), frozenset(("A", "C"))})
        with self.assertRaises(FactorContractError):
            minimum_members(contract)
        selected = assess_unit(contract, ("A", "B", "D"))
        self.assertTrue(selected["membership_ready"])
        self.assertEqual(selected["state_readiness"], "unknown")
        self.assertFalse(assess_unit(contract, ("A", "B"))["membership_ready"])

    def test_two_complete_branches_are_not_merged(self):
        result = assess_unit(unit_contract(), ("A", "B", "C", "D"))
        self.assertEqual(len(result["branches"]), 2)
        self.assertIsNone(result["minimum_members"])
        self.assertIsNone(result["chosen_branch"])

    def test_alternative_resource_conditions_stay_with_their_members(self):
        contract = unit_contract()
        first = replace(contract.dependencies[0], alternative_conditions=(
            BranchConditions(structure=Condition("supply", "X")),
            BranchConditions(structure=Condition("supply", "Y"))))
        contract = replace(contract, dependencies=(first,) + contract.dependencies[1:])
        wrong = assess_unit(contract, ("A", "B", "D"), resources=(Resource("supply", "Y"),), coverage=True)
        self.assertFalse(wrong["membership_ready"])
        right = assess_unit(contract, ("A", "B", "D"), resources=(Resource("supply", "X"),), coverage=True)
        self.assertTrue(right["membership_ready"])

    def test_default_candidate_rechecks_recursive_companion(self):
        from ygo_kito.multifactor.scoring import prepare_function_candidate
        calls = []
        result = prepare_function_candidate(legacy(), unit_contract(), ("A", "B", "D"),
            candidate_ref="candidate", target_key="inserted", recall_source="fixture",
            factor_provider=lambda members: calls.append(members) or Factors("group"))
        self.assertEqual(result["status"], "unit_prepared")
        self.assertEqual(set(calls[0]), {"A", "B", "D"})

    def test_structural_requirements_and_state_are_separate(self):
        contract = replace(unit_contract(), requirements=Condition("normal_summon", "slot"))
        result = assess_unit(contract, ("A", "C"))
        self.assertFalse(result["membership_ready"])
        self.assertEqual(result["structural_status"], "unknown")


class SharedConstructionTests(unittest.TestCase):
    def test_constructed_group_uses_same_allocation_core(self):
        from ygo_kito.construction_recognition import allocate_relation_group
        from ygo_kito.construction_relations import Resource as R, Need, InputGroup, RelationFact, _blank
        output = R("token")
        fact = RelationFact("f", "effect", output, "fixture")
        group = InputGroup("all", (Need("a", output), Need("b", output)))
        index = SimpleNamespace(incomplete_needs=set(), unresolved_cards=set(),
            matches={"a": ("f",), "b": ("f",)}, facts={"f": fact}, pools={})
        result = allocate_relation_group(group, index, {"f": _blank("supported")}, Counter(), {"output:effect:token": 1}, "fixture")
        self.assertEqual(result["status"], "missing")
        self.assertEqual(result["allocation_producer"], "multifactor.conditions")


if __name__ == "__main__":
    unittest.main()
