"""Synthetic listing/selection regressions; no duel or strength evidence.

The score stub reports an explicit vector. These tests do not train a model,
invoke a native engine, or use a reference construction.
"""
from collections import Counter
from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

import torch

from ygo_kito.build_contracts import BuildTask, DeckParts
from ygo_kito.build_intent import IntentClassification
from ygo_kito.build_pipeline import edit_candidates
from ygo_kito.construction_candidates import portfolio, retained_order
from ygo_kito.construction_fill import FillProposal, NodeBinding, fill_with_existing
from ygo_kito.construction_logic import ConstructionLogic, ConstructionSession, LogicNode, LogicTag
from ygo_kito.validation import ContractError
from tests.test_construction_logic import fixture_assets, text_review


def saturated_sections(*, budget=16):
    original, assets = fixture_assets()
    template = deepcopy(assets.rows[1])
    ids = tuple(range(1, 25)) + tuple(range(101, 108))
    assets.rows = {c: dict(template, id=c, alias=0, setcode=0,
        type=0x41 if c >= 101 else 17, name="synthetic-"+str(c)) for c in ids}
    raw = original.to_dict()
    raw.update(schema_version=4, pool=list(ids), candidate_budget=budget,
        sizes={"main":40,"extra":15,"side":15},
        requirements=[{"zone":"main","card_id":1,"minimum":3,"maximum":3}],
        goal={"kind":"deck_constraints","constraints":[{"id":"main-listing",
            "zones":["main"],"predicate":{"field":"type_all","value":17},
            "minimum":40,"maximum":40}],"preferences":[]})
    raw["environment"]["versions"]["card_pool"] = "native-private-knowledge-v5"
    task = BuildTask.from_dict(raw)
    assets.environment = deepcopy(task.environment)
    assets.receipt = {"resources":{"cards":"a"*64}}
    base = DeckParts(tuple(c for c in range(1, 14) for _ in range(3))+(14,),
        tuple(c for c in range(101, 106) for _ in range(3)),
        tuple(c for c in range(20, 24) for _ in range(3))+(106,)*3)
    assets.validate(task, base)
    return task, assets, base


def replacement(base, zone, old, new):
    parts = base.to_dict()
    parts[zone].remove(old)
    parts[zone].append(new)
    return DeckParts(*(tuple(sorted(parts[z])) for z in ("main","extra","side")))


def fill_session(task):
    # Static intent fixture: avoid the trained intent-classifier test helper.
    with patch("ygo_kito.build_intent.classify_build_intent", return_value=IntentClassification("broad", 1.)), \
            patch("ygo_kito.intent_model.LinearIntentClassifier"):
        session = ConstructionSession("synthetic broad construction", task)
    graph = ConstructionLogic("trace-graph", (LogicNode("goal", (LogicTag("effect","send"),)),),
        (), ("goal",), ("goal",))
    session.submit_logic(graph, role="user", reason="explicit synthetic graph")
    return session


def bind_one(graph, task, deck):
    return FillProposal(deck, (NodeBinding("goal", (1,)),), (), graph.sha256, task.sha256)


class ConstructionEditTraceTests(unittest.TestCase):
    def test_saturated_side_copy_can_enter_main_only_as_a_legal_atomic_exchange(self):
        task, assets, base = saturated_sections()
        # All three copies of 20 are already in Side. A standalone Main add
        # fails the same global cap that the atomic exchange must preserve.
        self.assertEqual(base.side.count(20), 3)
        self.assertFalse(assets.accepts(task, replacement(base,"main",2,20)))
        trace = {}
        rows = edit_candidates(task,assets,base,return_portfolio=True,trace=trace)
        exchanges = [r for r in rows if r.get("generation",{}).get("kind")=="atomic_cross_zone_exchange"
            and r["deck"].main.count(20)>base.main.count(20)]
        self.assertTrue(exchanges)
        inventory = Counter(base.main+base.extra+base.side)
        for row in exchanges:
            self.assertEqual(row["strategy"], "transfer:main+side")
            self.assertEqual(Counter(row["deck"].main+row["deck"].extra+row["deck"].side), inventory)
            self.assertEqual([len(getattr(row["deck"],z)) for z in ("main","extra","side")], [40,15,15])
        for row in rows:
            assets.validate(task,row["deck"])
            self.assertEqual(row["deck"].main.count(1),3)
            self.assertTrue(set(row["deck"].main+row["deck"].extra+row["deck"].side)<=set(task.pool))
        failures = [reason for family in trace["families"].values() for reason in family["filtered"]]
        self.assertTrue(any("copy" in reason or "alias" in reason for reason in failures))
        self.assertIn("combined_alias_copy_limits",trace["constraints_checked"])

    def test_small_budget_shares_a_round_with_axis_and_each_edit_region_without_score_bonus(self):
        task, assets, base = saturated_sections(budget=5)
        singles = [replacement(base,"main",2,15),replacement(base,"extra",101,107),replacement(base,"side",20,15)]
        axes = [{"deck":replacement(base,"main",old,new),"strategy":"axis:mechanism:synthetic-"+str(new),
            "proposal_basis":"explicit_synthetic_public_package","proposal_source":"synthetic-unit"}
            for old,new in ((3,16),(4,17),(5,18),(6,19))]
        with patch("ygo_kito.construction_candidates.axis_edits",return_value=iter(axes)):
            rows = portfolio(task,assets,base=base,singles=singles)
        strategies = {r["strategy"] for r in rows}
        self.assertEqual(len(rows),5)
        self.assertTrue({"incumbent","single:main","single:extra","single:side"}<=strategies)
        self.assertTrue(any(s.startswith("axis:") for s in strategies))
        scores = [10. if r["strategy"]=="single:extra" else float(i)/10 for i,r in enumerate(rows)]
        order = retained_order(rows,scores,(),task.sha256)
        self.assertEqual(rows[order[0]]["strategy"],"single:extra")
        self.assertTrue(all(r["strength_status"]=="unknown" for r in rows))

    def test_trace_keeps_every_budgeted_score_and_actual_attempt_and_effect_links(self):
        task, assets, base = saturated_sections(budget=8)
        candidates = edit_candidates(task,assets,base,return_portfolio=True)
        scores = [float(i) for i in range(len(candidates))]
        model = Mock(return_value=torch.tensor(scores))
        encoder = Mock()
        encoder.batch.return_value = {"synthetic_bound_batch":True}
        session = fill_session(task)
        attempted = []
        def bind(graph, task, deck):
            attempted.append(deck)
            if len(attempted)==1:
                raise ContractError("synthetic first binding has no witness")
            return bind_one(graph,task,deck)
        result = fill_with_existing(session,assets,role="build_optimizer",base=base,
            models={"build_optimizer":model},encoder=encoder,binding_provider=bind,
            text_reviewer=text_review,defer_engine=True)
        trace = result["candidate_trace"]
        self.assertEqual(len(trace["candidates"]),len(candidates))
        self.assertEqual([r["model_score_uncalibrated"] for r in trace["candidates"]],scores)
        self.assertTrue(all(r["score_available"] for r in trace["candidates"]))
        self.assertEqual(trace["calibration_status"],"uncalibrated")
        self.assertEqual(trace["candidate_order"][0],len(candidates)-1)
        self.assertEqual(trace["candidates"][len(candidates)-1]["status"],"binding_unmatched")
        self.assertTrue(any(r["status"]=="not_attempted" for r in trace["candidates"]))
        selected = trace["candidates"][trace["selected_candidate_index"]]
        self.assertTrue(selected["selected"])
        self.assertEqual(selected["attempt_index"],trace["selected_attempt_index"])
        evidence = selected["public_effect_evidence"]
        attempt = result["attempts"][evidence["text_reviews_attempt_index"]]
        self.assertIn(1,evidence["reviewed_card_ids"])
        self.assertEqual(evidence["bindings"],[{"node_id":"goal","card_ids":[1]}])
        self.assertEqual(attempt["text_reviews"][0]["evidence"][0]["card_id"],1)
        self.assertEqual(attempt["text_reviews"][0]["evidence"][0]["quote"],"Synthetic card text")
        model.assert_called_once_with(encoder.batch.return_value)
        encoder.batch.assert_called_once()
        self.assertFalse(result["graph_execution_verified"])

    def test_absent_model_reports_no_score_instead_of_the_sorting_placeholder(self):
        task, assets, base = saturated_sections(budget=8)
        result = fill_with_existing(fill_session(task),assets,role="build_optimizer",base=base,
            binding_provider=bind_one,text_reviewer=text_review,defer_engine=True)
        trace = result["candidate_trace"]
        self.assertEqual(trace["calibration_status"],"no_model_score")
        self.assertTrue(all(not r["score_available"] and r["model_score_uncalibrated"] is None
            for r in trace["candidates"]))
        self.assertTrue(all(r["model_score_uncalibrated"] is None for r in result["portfolio"]))
        self.assertEqual(trace["strength_status"],"unknown")


if __name__ == "__main__":
    unittest.main()
