"""Actual fill/selection on anonymous source-bound lists; no training or CB."""

from dataclasses import replace
import unittest
from unittest.mock import patch

from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.build_intent import IntentClassification
from ygo_kito.construction_binding import CatalogBindingAdapter
from ygo_kito.construction_fill import fill_with_existing
from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
from ygo_kito.construction_layers import FunctionEvidence, FunctionRequirement, LayerContext, RoleAssessment
from ygo_kito.construction_logic import ConstructionSession
from ygo_kito.construction_relations import (
    InputGroup, Need, ProbabilityRequest, RelationBudget, RelationContext,
    RelationFact, Resource, ResourcePool, UseRequirement,
)
from ygo_kito.validation import ContractError
from tests.test_construction_binding import catalog, assessment, one_node
from ygo_kito.construction_logic import LogicTag


def flow_fixture(*, budget=4, unknown=False, optional=False):
    task, assets = catalog()
    raw = task.to_dict()
    raw["candidate_budget"] = budget
    task = BuildTask.from_dict(raw)
    tag = LogicTag("effect", "anonymous-purpose")
    graph = one_node(tag)
    binder = CatalogBindingAdapter(assets, assessments=(assessment(assets, 1, tag),))
    # Four valid 40-card configurations; material stock is an actual integer.
    core = (1,) + tuple(c for c in range(4, 16) for _ in range(3))
    decks = [DeckParts(tuple(sorted(core + (2,) * count + (3,) * (3-count)))) for count in range(4)]
    for deck in decks:
        assets.validate(task, deck)
    requirement = FunctionRequirement("prepare", "main", "synthetic original purpose", ("goal",), ("supply",))
    role = RoleAssessment("supply", "main", 2, 1, "synthetic material role",
        (FunctionEvidence("prepare", "covered", "synthetic material role"),))
    stock = Resource("stock", zone="grave", reason="effect")
    pool = ResourcePool("material-stock", "synthetic physical supply", inventory=(("main", 2),))
    fact = RelationFact("material", "material", stock, "explicit synthetic access condition", 2,
        output_pool=pool.pool_id, inventory_scaled=True,
        unknown=("access_unknown",) if unknown else ())
    uses = [UseRequirement("two-materials", InputGroup("all", (Need("two", stock, 2),)),
        "original synthetic purpose", priority=2)]
    facts = [fact]
    if optional:
        uses.append(UseRequirement("other-purpose", InputGroup("all", (Need("other", Resource("other")),)),
            "optional synthetic purpose", required=False))
        facts.append(RelationFact("other", "other", Resource("other"), "synthetic other", 3))
    relations = RelationContext(tuple(uses), tuple(facts), (pool,), probabilities=(
        ProbabilityRequest("material", (2,), 5, "explicit single initial draw", ("acquired", "retained")),))
    context = LayerContext(task, graph, (requirement,), (role,), relations=relations)
    return task, assets, graph, binder, decks, context


def session_for(task, graph):
    with patch("ygo_kito.build_intent.classify_build_intent", return_value=IntentClassification("broad", 1.)):
        session = ConstructionSession("anonymous functional construction", task)
    session.submit_logic(graph, role="build_goal", reason="synthetic selected graph")
    return session


def rows_for(task, decks):
    from ygo_kito.construction_candidates import changes
    return [{"deck": deck, "deck_sha256": digest(deck.to_dict()), "strategy": "synthetic-stock",
        "changes": changes(decks[0], deck), "goal_preserved": True} for deck in decks]


def run_fill(fixture, *, adapter=None, models=None, encoder=None, decks=None, role="build_optimizer"):
    task, assets, graph, binder, original, _ = fixture
    decks = original if decks is None else decks
    rows = rows_for(task, decks)
    def candidates(*args, trace=None, **kwargs):
        if trace is not None:
            trace.update(generator="synthetic_already_generated", attempted=53, portfolio_candidates=len(rows))
        return rows
    with patch("ygo_kito.build_pipeline.edit_candidates", side_effect=candidates):
        return fill_with_existing(session_for(task, graph), assets, role=role, base=decks[0],
            models=models, encoder=encoder, binding_provider=binder, text_reviewer=binder.reviewer,
            verifier=None, defer_engine=True, layer_adapter=adapter)


class ConstructionLayerFlowTests(unittest.TestCase):





    def test_static_theme_facts_do_not_supply_functional_q_one(self):
        fixture = list(flow_fixture())
        fixture[2] = one_node(LogicTag("race", "植物族"))
        fixture[3] = CatalogBindingAdapter(fixture[1])
        result = run_fill(fixture)
        roles = result["layer_evaluation"]["axis"]["overview"]["roles"]
        self.assertTrue(roles)
        self.assertTrue(all(r["q"] == .5 for r in roles))
        self.assertFalse(result["layer_evaluation"]["axis"]["overview"]["functions"])

    def test_automatic_effect_mapping_preserves_cost_target_and_known_boundary(self):
        fixture = list(flow_fixture())
        fixture[1].rows[1]["desc"] = "①：丢弃1张手卡，以自己场上1只怪兽为对象才能发动。从自己卡组上面把3张卡送去墓地。"
        fixture[2] = one_node(LogicTag("effect", "卡组送墓"))
        fixture[3] = CatalogBindingAdapter(fixture[1])
        result = run_fill(fixture)
        value = result["layer_evaluation"]
        self.assertEqual(value["axis"]["overview"]["functions"]["node:goal:main"]["status"], "covered")
        facts = value["relations"]["fact_records"]
        mapped = [f for key, f in facts.items() if key.startswith("flow:goal:catalog:1:")]
        self.assertTrue(mapped)
        kinds = {n["resource"]["kind"] for f in mapped for n in f["inputs"]["items"]}
        self.assertTrue({"payment", "target"} <= kinds)
        self.assertFalse(any("activation_condition_unknown" in f["unknown"] for f in mapped))
        self.assertTrue(any(n['resource']['kind']=='activation' and n['resource']['event']=='own_main_phase'
            for f in mapped for n in f['inputs']['items']))
        self.assertEqual(value["relations"]["joint_required"]["status"], "supported")
        fixture[1].rows[1]['desc']=fixture[1].rows[1]['desc'].replace('才能发动','且满足未识别条件才能发动')
        fixture[3]=CatalogBindingAdapter(fixture[1])
        unresolved=run_fill(fixture)['layer_evaluation']['relations']
        self.assertEqual(unresolved['joint_required']['status'],'unknown')

    def test_repeated_effect_numbers_keep_distinct_ports_and_unknown_scope(self):
        fixture = list(flow_fixture())
        fixture[1].rows[1]["desc"] = (
            "这个卡名的①效果1回合只能使用1次。"
            "①：丢弃1张手卡才能发动。从自己卡组上面把3张卡送去墓地。"
            "【怪兽效果】这个卡名的①效果1回合只能使用1次。"
            "①：丢弃2张手卡才能发动。从自己卡组上面把2张卡送去墓地。")
        fixture[2] = one_node(LogicTag("effect", "卡组送墓"))
        fixture[3] = CatalogBindingAdapter(fixture[1])
        result = run_fill(fixture)
        facts = result["layer_evaluation"]["relations"]["fact_records"]
        observed = [f for key, f in facts.items() if key.startswith("catalog:1:1:record:")]
        self.assertEqual(len(observed), 2)
        self.assertEqual(len({f["effect_ref"] for f in observed}), 2)
        self.assertEqual({f["quantity"] for f in observed}, {2, 3})
        costs = [n for f in observed for n in f["inputs"]["items"] if n["resource"]["kind"] == "payment"]
        self.assertEqual({n["quantity"] for n in costs}, {1, 2})
        self.assertEqual(len({n["need_id"] for n in costs}), 2)
        self.assertTrue(all("repeated_effect_number_scope_unresolved" in f["unknown"] for f in observed))
        pools = [{c["pool_id"] for c in f["claims"]} for f in observed]
        self.assertTrue(all(pools))
        self.assertTrue(pools[0].isdisjoint(pools[1]))
        self.assertEqual(result["layer_evaluation"]["relations"]["joint_required"]["status"], "unknown")




    def test_one_candidate_budget_is_applied_before_source_reads(self):
        fixture = flow_fixture()
        binder, decks, context = fixture[3:]
        adapter = ConstructionLayerAdapter(binder, context_provider=lambda *_: context, budget=RelationBudget(candidates=1))
        result = run_fill(fixture, adapter=adapter)
        self.assertEqual(result["candidate_trace"]["layers"]["evaluated_indices"], [0])
        self.assertEqual(result["candidate_trace"]["layers"]["uncovered_indices"], [1, 2, 3])

    def test_zero_fact_budget_does_not_parse_effects_or_invent_negative_coverage(self):
        fixture = flow_fixture()
        binder = fixture[3]
        adapter = ConstructionLayerAdapter(binder, budget=RelationBudget(facts=0))
        with patch.object(binder.semantic_catalog, "effect_records", side_effect=AssertionError("no fact reads")):
            result = run_fill(fixture, adapter=adapter)
        self.assertEqual(result['status'],'quality_evaluation_pending')
        self.assertEqual(result['pending_quality']['evaluations'],{})
        self.assertEqual(result['pending_quality']['calculation_progress']['0']['read_cursor'],0)

    def test_wrong_task_or_graph_context_is_rejected(self):
        fixture = flow_fixture()
        context = replace(fixture[5], task=replace(fixture[0], task_id="other-task"))
        with self.assertRaisesRegex(ContractError, "original task or logic"):
            run_fill(fixture, adapter=ConstructionLayerAdapter(fixture[3], context_provider=lambda *_: context))

    def test_host_callback_cannot_mutate_task_then_rebind_its_context(self):
        fixture = flow_fixture()
        def mutate(task, graph):
            task.goal["preferences"] = [{"invalid": True}]
            return fixture[5]
        with self.assertRaisesRegex(ContractError, "original task or logic"):
            run_fill(fixture, adapter=ConstructionLayerAdapter(fixture[3], context_provider=mutate))








if __name__ == "__main__":
    unittest.main()
