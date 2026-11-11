"""M3 graph/candidate regressions. Source only until test execution is allowed."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from ygo_kito.multifactor import (AnalysisContext, AnalysisGraph, AxisCandidate, CandidateBudget,
    DeckSpec, FactorContractError, Factors, FunctionSeed, GraphBudget, Group, Resource, RoleInput,
    StructureLink, build_analysis_graph, generate_axis_candidates)
from ygo_kito.multifactor.contracts import GRAPH_VERSION
from ygo_kito.multifactor.functional_units import Dependency, FunctionalContract, KnownCondition, MemberAmount
from ygo_kito.multifactor.functional_units import BranchConditions
from ygo_kito.multifactor.conditions import Condition


def input_for(deck, *, context=None):
    return RoleInput("input", Factors("context"), (), analysis_mode="deck_analysis",
                     analysis_context=context or AnalysisContext(), deck=deck)


def seed(ref="A", scope="function", members=None):
    return FunctionSeed(scope, members or ((ref, 1),), ("search",), evidence_refs=("supplied facts",))


def training_module():
    root = Path(__file__).resolve().parents[1] / "training" / "axis_generic"
    spec = importlib.util.spec_from_file_location("axis_generic_m3_test_module", root / "features_graph.py")
    module = importlib.util.module_from_spec(spec)
    # Restore both module registry and path so legacy absolute training imports
    # cannot change the environment seen by another test.
    with patch.dict(sys.modules), patch.object(sys, "path", [str(root)] + sys.path):
        spec.loader.exec_module(module)
    return module


class CandidateGenerationTests(unittest.TestCase):
    def test_independent_card_is_a_unit_and_axes_can_overlap(self):
        result = generate_axis_candidates((seed("X"), seed(members=(("A", 1), ("B", 1)), scope="first"),
                                           seed(members=(("B", 1), ("C", 1)), scope="second")), ())
        self.assertEqual({frozenset(dict(v.members)) for v in result.candidates},
                         {frozenset(("A", "B")), frozenset(("B", "C"))})
        self.assertEqual([v.members for v in result.units], [(("X", 1),)])
        self.assertFalse(any(len(v.members) == 3 for v in result.candidates))

    def test_named_closure_continues_past_expansion_rounds_and_cycles(self):
        links = tuple(StructureLink(a, b, "requires", required=True) for a, b in
                      (("A", "B"), ("B", "C"), ("C", "D"), ("D", "A")))
        result = generate_axis_candidates((seed(),), links, budget=CandidateBudget(rounds=1))
        self.assertEqual({frozenset(dict(v.members)) for v in result.candidates}, {frozenset("ABCD")})

    def test_cooccurrence_and_contains_do_not_generate_an_axis(self):
        result = generate_axis_candidates((seed(),), (StructureLink("A", "B", "contains"),))
        self.assertEqual(result.candidates, ())

    def test_mutually_exclusive_modes_cannot_be_combined(self):
        query = replace(seed(), mode_choices=(("effect", "one"),))
        link = StructureLink("A", "B", "calls", ("search",), "function", mode_choices=(("effect", "two"),))
        self.assertEqual(generate_axis_candidates((query,), (link,)).candidates, ())

    def test_explicit_cross_supply_can_form_large_parent(self):
        result = generate_axis_candidates((seed(members=(("A", 1), ("B", 1))),
                                           seed(members=(("C", 1), ("D", 1)))),
            (StructureLink("A", "D", "provides", ("search",), "function"),))
        parents = [v for v in result.candidates if set(dict(v.members)) == set("ABCD")]
        self.assertTrue(parents)
        self.assertTrue(any(len(v.parent_ids) == 2 for v in parents))

    def test_all_candidates_are_queried_in_blocks_of_32(self):
        seeds = tuple(seed(scope=f"f:{i}", members=((f"a:{i}", 1), (f"b:{i}", 1))) for i in range(40))
        result = generate_axis_candidates(seeds, ())
        self.assertEqual(len(result.candidates), 40)
        self.assertEqual([len(v) for v in result.batches()], [32, 8])

    def test_opaque_renaming_does_not_choose_a_tied_prefix(self):
        links = tuple(StructureLink("A", f"target:{i}", "calls", ("search",), "function",
                                   mode_choices=(("target_choice", f"target:{i}"),)) for i in range(10))
        result = generate_axis_candidates((seed(),), links)
        renamed = tuple(replace(v, source="renamed_root", target=f"other:{9-i}",
                                mode_choices=(("other_choice", f"other:{9-i}"),)) for i, v in enumerate(links))
        other = generate_axis_candidates((seed("renamed_root"),), renamed)
        self.assertEqual(len(result.candidates), 10)
        self.assertEqual(len(other.candidates), 10)
        self.assertIn("per_seed_beam", result.reasons)

    def test_hard_budget_reports_incomplete_search(self):
        result = generate_axis_candidates((seed(), seed("B")), (), budget=CandidateBudget(checks=1))
        self.assertTrue(result.overflow)
        self.assertEqual(result.candidates, ())
        self.assertEqual(result.units, ())


class SharedGraphTests(unittest.TestCase):
    def test_90_cards_and_cross_block_edges_are_retained(self):
        deck = DeckSpec(tuple((i, 1) for i in range(1, 61)), tuple((i, 1) for i in range(61, 76)),
                        tuple((i, 1) for i in range(76, 91)))
        result = build_analysis_graph(input_for(deck), budget=GraphBudget(node_block=16, edge_block=17))
        self.assertEqual(sum(v.kind == "card" for v in result.graph.nodes), 90)
        blocks = result.numeric_blocks()
        for kind, expected in (("nodes", len(result.graph.nodes)), ("edges", len(result.graph.edges))):
            self.assertEqual(sum(sum(b["mask"]) for b in blocks if b["kind"] == kind), expected)
        restored = [row for b in blocks if b["kind"] == "edges" for row, keep in zip(b["values"], b["mask"]) if keep]
        self.assertEqual(tuple(restored), result.graph.numeric_view()["edges"])
        self.assertEqual(AnalysisGraph.from_dict(result.graph.to_dict()), result.graph)

    def test_empty_extra_and_unknown_side_remain_distinct(self):
        result = build_analysis_graph(input_for(DeckSpec(((1, 3),), (), None)))
        nodes = {v.ref: v for v in result.graph.nodes}
        self.assertEqual(nodes["card:1"].copies, (3, 0, None))
        self.assertEqual(nodes["section:extra"].empty_status, "empty")
        self.assertEqual(nodes["section:side"].empty_status, "unknown")
        self.assertNotEqual(nodes["section:extra"].numeric_values(), nodes["section:side"].numeric_values())

    def test_card_identity_renaming_preserves_numeric_graph_structure(self):
        first = build_analysis_graph(input_for(DeckSpec(((1, 1), (2, 1)), (), ())),
            function_seeds=(seed("card:1"),), structure_links=(StructureLink("card:1", "card:2", "calls", ("search",), "function"),))
        second = build_analysis_graph(input_for(DeckSpec(((73, 1), (14, 1)), (), ())),
            function_seeds=(seed("card:73"),), structure_links=(StructureLink("card:73", "card:14", "calls", ("search",), "function"),))
        def shape(result):
            values = {n.ref: n.numeric_values() for n in result.graph.nodes}
            return (Counter(values.values()), Counter((values[e.source], values[e.target], e.kind, e.quantity, e.confidence) for e in result.graph.edges))
        self.assertEqual(shape(first), shape(second))

    def test_shared_resource_pool_aliases_are_not_extra_capacity(self):
        stock = (Resource("card", "card:1", resource_id="first", pool_id="same"),
                 Resource("card", "other_selector", resource_id="alias", pool_id="same"))
        result = build_analysis_graph(input_for(DeckSpec(((1, 1),), (), ()), context=AnalysisContext(public_resources=stock)))
        pools = [v for v in result.graph.nodes if v.ref.startswith("resource_pool:")]
        self.assertEqual(len(pools), 1)
        self.assertEqual(dict(pools[0].attributes)["capacity"], 1)

    def test_provenance_and_legacy_role_fields_do_not_enter_new_features(self):
        example = input_for(DeckSpec(((1, 1), (2, 1)), (), ()))
        original = build_analysis_graph(example)
        role_proxy = Group("arbitrary_reference", Factors.observed("group", {"goal_contribution": 1}, source="label-like legacy metadata"))
        changed = build_analysis_graph(replace(example, context_ref="changed_reference", groups=(role_proxy,)), source_ref="changed_source")
        self.assertEqual(original.graph.numeric_view(), changed.graph.numeric_view())
        self.assertEqual(original.candidates, changed.candidates)

    def test_extra_evidence_does_not_duplicate_conditional_fact_nodes(self):
        example = input_for(DeckSpec(((1, 1), (2, 1)), (), ()))
        link = StructureLink("card:1", "card:2", "calls", ("search",), "function",
            condition=BranchConditions(structure=Condition("counter", "slot")), evidence_refs=("one",))
        first = build_analysis_graph(example, function_seeds=(seed("card:1"),), structure_links=(link,))
        second = build_analysis_graph(example, function_seeds=(seed("card:1"),),
            structure_links=(link, replace(link, evidence_refs=("second",))))
        self.assertEqual(first.graph.numeric_view(), second.graph.numeric_view())

    def test_named_combination_branches_preserve_their_own_members(self):
        contract = FunctionalContract("template", "input", "function", (MemberAmount("card:1"),),
            (Dependency("card:1", (), "effect-backed dependency", ((MemberAmount("card:2"),), (MemberAmount("card:3"),))),),
            ("card:1", "card:2", "card:3"), (KnownCondition("window", "unknown", "not observed"),),
            "effect facts", function_tags=("search",))
        result = build_analysis_graph(input_for(DeckSpec(((1, 1), (2, 1), (3, 1)), (), ())), unit_contracts=(contract,))
        self.assertEqual({frozenset(dict(v.members)) for v in result.candidates.candidates},
                         {frozenset(("card:1", "card:2")), frozenset(("card:1", "card:3"))})

    def test_printed_modes_and_target_options_remain_separate(self):
        snapshot = dict(semantic_version="public-effect-clauses-v2", card_id=1, text_sha256=None, restrictions=[],
            materials=[], unknown=[], effects=[dict(index=1, text="从以下效果选择1个发动。●搜寻B。●特殊召唤C。",
                costs=[], targets=[], count_limits=[], unknown=[], operations=[
                    dict(kind="search_or_recover", reason="effect", from_zones=["deck"], to_zone="hand",
                         selector="「B」", source="搜寻B", quantity=1),
                    dict(kind="special_summon", reason="effect", from_zones=["deck"], to_zone="field",
                         selector="「C」", source="特殊召唤C", quantity=1)])])
        before = deepcopy(snapshot)
        result = build_analysis_graph(input_for(DeckSpec(((1, 1), (2, 1), (3, 1)), (), ())),
            effect_snapshots={1: snapshot}, card_rows={1: {"id": 1, "name": "A"}, 2: {"id": 2, "name": "B"}, 3: {"id": 3, "name": "C"}})
        self.assertEqual(snapshot, before)
        self.assertEqual({frozenset(dict(v.members)) for v in result.candidates.candidates},
                         {frozenset(("card:1", "card:2")), frozenset(("card:1", "card:3"))})
        self.assertTrue(all(len(v.mode_choices) >= 1 for v in result.candidates.candidates))

    def test_graph_limit_raises_instead_of_returning_a_truncated_input(self):
        with self.assertRaisesRegex(FactorContractError, "no truncated graph"):
            build_analysis_graph(input_for(DeckSpec(((1, 1), (2, 1)), (), ())), budget=GraphBudget(nodes=4))

    def test_relation_budget_withholds_partial_target_prefix(self):
        snapshot = dict(semantic_version="public-effect-clauses-v2", card_id=1, text_sha256=None,
            restrictions=[], materials=[], unknown=[], effects=[dict(index=1, text="搜寻目标", costs=[], targets=[],
                count_limits=[], unknown=[], operations=[dict(kind="search_or_recover", reason="effect", from_zones=["deck"],
                    to_zone="hand", selector="「目标」", source="搜寻目标", quantity=1)])])
        result = build_analysis_graph(input_for(DeckSpec(((1, 1), (2, 1), (3, 1)), (), ())),
            effect_snapshots={1: snapshot}, card_rows={1: {"id": 1, "name": "来源"}, 2: {"id": 2, "name": "目标"}, 3: {"id": 3, "name": "目标"}},
            budget=GraphBudget(relation_checks=1))
        self.assertEqual(result.candidates.candidates, ())
        self.assertIn("fact_relation_budget", result.candidates.reasons)
        self.assertFalse(any(e.kind == "calls" for e in result.graph.edges))
        self.assertEqual(sum(n.kind == "card" for n in result.graph.nodes), 3)


class TrainingDelegationTests(unittest.TestCase):
    def test_training_v3_delegates_and_ignores_labels_routes_and_families(self):
        module = training_module()
        features = module.Features.__new__(module.Features)
        features.rows, features.digest, features.feature_schema = {}, "", GRAPH_VERSION
        case = dict(main=[[1, 1], [2, 1]], extra=[], side=[], labels=[1, 0, 1], family="ignored",
                    primary_plan={"not": "an observation"}, mechanism={"invalid": "supervision"})
        result = features.make(case)
        case.update(labels=[0, 1, 0], family="different", reference="different", primary_plan=None, mechanism=None)
        self.assertEqual(result.graph.numeric_view(), features.make(case).graph.numeric_view())
        direct = build_analysis_graph(result.input, source_ref="configured_catalog_facts")
        self.assertEqual(result.graph.to_dict(), direct.graph.to_dict())

    def test_injected_query_is_training_only_and_has_no_gold_confidence(self):
        module = training_module()
        result = build_analysis_graph(input_for(DeckSpec(((1, 1), (2, 1), (3, 1)), (), ())),
            function_seeds=(seed("card:1"),), structure_links=(StructureLink("card:1", "card:2", "calls", ("search",), "function"),))
        original = result.candidates.to_dict()
        injected = AxisCandidate("function", (("card:1", 1), ("card:3", 1)), ("draw",), confidence=0.01)
        view = module.training_candidate_view(result, (injected,))
        self.assertEqual(original, result.candidates.to_dict())
        self.assertTrue(view["provenance"]["injected_query_ids"])
        ids = set(view["provenance"]["injected_query_ids"])
        query = next(v for v in view["observations"]["queries"] if v["candidate_id"] in ids)
        self.assertEqual(query["functions"], ["search"])
        self.assertEqual(query["confidence"], 1.0)
        self.assertNotIn("injected", query)
        self.assertNotIn("injected_query_ids", view["observations"])


if __name__ == "__main__":
    unittest.main()
