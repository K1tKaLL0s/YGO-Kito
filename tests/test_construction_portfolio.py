"""Isolated synthetic cards/outcomes test mechanisms, never real duel ability.

No native engine, user/reference deck, formal course or external service runs.
The paired JSON below is an explicitly fabricated protocol consistency fixture.
"""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

import torch

from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.build_pipeline import DeckEdits, edit_candidates
from ygo_kito.build_training import BuildTrainer, BuildTrainingConfig
from ygo_kito.construction_binding import CatalogBindingAdapter, CardTagAssessment
from ygo_kito.construction_candidates import (changes, evidence_order, graph_signature,
    record_comparison, attributed_feedback)
from ygo_kito.construction_fill import (construction_cycle, existing_goal_verifier, evaluate_fill,
    FillProposal, NodeBinding, NodeTextReview, TextEvidence)
from ygo_kito.construction_logic import ConstructionLogic, LogicTag
from ygo_kito.construction_model import LogicCodec, LogicModelAdapter, rule_graph_candidates
from ygo_kito.validation import ContractError
from tests.test_construction_logic import fixture_assets, fixture_session
from tests.test_construction_model import graph_context


def catalog():
    original, assets = fixture_assets()
    for code in (20, 21, 22, 100, 101, 102, 103, 104, 105):
        assets.rows[code] = dict(assets.rows[1], id=code, name="synthetic-"+str(code))
    for code, row in assets.rows.items():
        row.update(setcode=0x222 if code in (20,21,22) else 0x111,
                   type=0x41 if code in (21,100,101,102,103,104,105) else 17)
    # Each new card conflicts with a full alias in the other region. These
    # cannot be legal independent single swaps, but a joint package can be.
    assets.rows[20]["alias"] = 100
    assets.rows[21]["alias"] = 2
    raw = original.to_dict();raw.update(schema_version=4,pool=sorted(assets.rows),candidate_budget=12,
        sizes={"main":40,"extra":15,"side":0})
    raw["environment"]["versions"]["card_pool"] = "native-private-knowledge-v5"
    raw["goal"] = {"kind":"deck_constraints","constraints":[{"id":"fixed-primary-axis","zones":["main"],
        "predicate":{"field":"setcode","value":0x111},"minimum":12,"maximum":40}],"preferences":[]}
    task = BuildTask.from_dict(raw);assets.environment = deepcopy(task.environment)
    assets.receipt = {"resources":{"cards":"a"*64}}
    base = DeckParts(tuple(c for c in range(1,14) for _ in range(3))+(14,),
                     tuple(c for c in range(100,105) for _ in range(3)))
    assets.validate(task,base)
    return task,assets,base


def paired_fixture(task, assets, decks, *, preferred=1):
    from ygo_kito.build_feedback import plan_for, descriptive_uncertainty
    from ygo_kito.duel_model import FEATURE_VERSION
    from ygo_kito.model_build_feedback import SOURCE, preference, profile_for_case
    seeds=(7,24)
    plan=plan_for(task,decks,decks[0],seeds,"construction_train")
    driver={"version":"frozen-learned-actor-audited-bot-v1","type":"actual_learned_neural_policy",
        "trained_policy":True,"policy_sha256":"a"*64,"policy_version":1,"feature_version":FEATURE_VERSION,
        "opponent_id":"synthetic-test-only","executor_id":"synthetic","source_id":"synthetic",
        "audit_sha256":"b"*64,"assembly_sha256":"c"*64,"policy_sampling":"private-paired-rng"}
    plan.update(driver=driver,format="BO1_frozen_model_audited_bot",adapter_revision=5)
    games=[]
    for i,deck in enumerate(decks):
        for seed in seeds:
            for seat in (0,1):
                wins=preferred is not None and preferred==i
                games.append({"candidate_index":i,"seed_audit_only":seed,"actor_seat":seat,
                    "outcome":{"winner":seat if wins else 1-seat},"score":float(wins),"turns":1,"decisions":1,
                    "trace_sha256":"d"*64,"profile_sha256":digest(profile_for_case(deck,decks[0],seat,5)),
                    "core_terminal_received":True,"replay_verified":True,"policy_sha256":driver["policy_sha256"],
                    "data_artifact_id":"explicit-synthetic-protocol-fixture"})
    means,differences,label=preference(games,seeds)
    value={"source":SOURCE,"plan":plan,"plan_sha256":digest(plan),"games":games,"mean_scores":means,
        "paired_differences":differences,"preferred_index":label,
        "status":"no_strict_label" if label is None else "paired_training_preference_observed",
        "uncertainty":descriptive_uncertainty(differences),"competitive_ability_validated":False}
    value["comparison_sha256"]=digest(value)
    return value


class ConstructionPortfolioTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.task,self.assets,self.base=catalog()
        self.tags=(LogicTag("effect","send"),LogicTag("effect","recover"))
        self.codec=LogicCodec((*self.tags,LogicTag("effect","draw")))
        self.session=fixture_session("堆墓",self.task)

    def rows(self, feedback=()):
        return edit_candidates(self.task,self.assets,self.base,feedback=feedback,return_portfolio=True)

    def graphs(self):
        return rule_graph_candidates(graph_context(self.session),self.codec,
            required_tags=self.tags,required_connector_kinds=("ss",))

    def axis(self):
        return next(r for r in self.rows() if r["strategy"]=="axis:setcode-222")

    def test_atomic_axis_spans_regions_and_preserves_all_constraints(self):
        rows=self.rows();axis=self.axis();deck=axis["deck"]
        self.assertIn(20,deck.main);self.assertIn(22,deck.main);self.assertIn(21,deck.extra)
        self.assertGreaterEqual(sum(len(v["added"]) for v in axis["changes"].values()),3)
        self.assertIn(self.base,[r["deck"] for r in rows])
        for row in rows:self.assets.validate(self.task,row["deck"])
        for zone,new,old in (("main",20,1),("extra",21,100)):
            parts=self.base.to_dict();parts[zone].remove(old);parts[zone].append(new)
            self.assertFalse(self.assets.accepts(self.task,DeckParts.from_dict(parts)))
        self.assertTrue(all(r["strength_status"]=="unknown" for r in rows))

    def test_small_budget_reserves_group_and_both_regions_without_forcing_edit(self):
        raw=self.task.to_dict();raw["candidate_budget"]=6;task=BuildTask.from_dict(raw)
        rows=edit_candidates(task,self.assets,self.base,return_portfolio=True)
        strategies={r["strategy"] for r in rows}
        self.assertTrue({"incumbent","axis:setcode-222","single:main","single:extra"}<=strategies)
        self.assertLessEqual(len(rows),6)

    def test_complete_lists_are_built_only_after_selection_in_each_round(self):
        actual = DeckEdits.materialize
        constructed = []
        def count(edits, change):
            deck = actual(edits, change)
            constructed.append(deck)
            return deck
        with patch.object(DeckEdits, 'materialize', count):
            for offset in (0, 5):
                trace = {}
                before = len(constructed)
                rows = edit_candidates(self.task, self.assets, self.base, return_portfolio=True,
                                       trace=trace, search_offset=offset)
                self.assertLessEqual(len(rows), 5)
                self.assertEqual(len(constructed) - before, trace['materialized_edit_count'])
                self.assertLessEqual(trace['materialized_edit_count'], 5)
                self.assertGreater(trace['legal_edit_ideas'], 5)
        self.assertGreater(len(constructed), 5)

    def test_sourced_mechanism_input_preserves_a_complete_package(self):
        self.assets.construction_mechanism_groups=[{"group_id":"synthetic-coupled","source":"synthetic-unit-facts",
            "zones":{"main":[20,22],"extra":[21],"side":[]}}]
        rows=self.rows()
        row=next(r for r in rows if r["strategy"]=="axis:mechanism:synthetic-coupled")
        self.assertTrue({20,22}<=set(row["deck"].main));self.assertIn(21,row["deck"].extra)
        self.assets.construction_mechanism_groups[0]["zones"]["main"].append(999)
        with self.assertRaises(ContractError):self.rows()

    def test_graph_options_change_topology_and_optional_resources(self):
        graphs=self.graphs()
        self.assertGreaterEqual(len(graphs),4)
        self.assertEqual(len(graphs),len({graph_signature(g) for g in graphs}))
        self.assertGreater(len({(len(g.nodes),len(g.connectors),len(g.entry_nodes)) for g in graphs}),2)
        self.assertTrue(any(LogicTag("effect","draw") in n.tags for g in graphs for n in g.nodes))
        for graph in graphs:
            changed=replace(graph,revision=1,parent_sha256=graph.sha256)
            self.assertEqual(graph_signature(graph),graph_signature(changed))

    def test_checked_whole_candidate_feedback_changes_order_and_next_graph(self):
        axis=self.axis()["deck"];graphs=self.graphs()
        contexts=[{"deck":d.to_dict(),"logic":g.to_dict()} for d,g in zip((self.base,axis),graphs[:2])]
        self.session.submit_logic(graphs[0],role="build_goal",reason="synthetic code path")
        comparison=paired_fixture(self.task,self.assets,[self.base,axis])
        receipt=record_comparison(self.session,self.assets,comparison,contexts)
        self.assertFalse(receipt["graph_quality_label"])
        rows=self.rows(attributed_feedback(self.session))
        self.assertEqual(rows[0]["deck"],axis)
        self.assertTrue(any(r["strategy"]=="observed-package" for r in rows))
        builder=BuildTrainer(self.task,self.assets,BuildTrainingConfig())
        adapter=LogicModelAdapter.from_builder(builder,self.codec,required_tags=self.tags,required_connector_kinds=("ss",))
        proposal=adapter.propose(graph_context(self.session,"build_optimizer"))
        graph=ConstructionLogic.from_dict(proposal["logic"])
        self.assertEqual(graph_signature(graph),graph_signature(graphs[1]))
        self.assertEqual(graph.parent_sha256,self.session.logic.sha256)
        saved=self.session.to_dict()
        restored=fixture_session("堆墓",self.task)
        for item in saved["feedback"]:restored.record_feedback(item["source"],item["message"])
        self.assertEqual(attributed_feedback(restored),[])
        restored.history=deepcopy(saved["history"])
        self.assertEqual([r["deck"] for r in rows],[r["deck"] for r in self.rows(attributed_feedback(restored))])

    def test_unknown_and_invalid_comparisons_never_create_quality_labels(self):
        axis=self.axis()["deck"];graphs=self.graphs()
        contexts=[{"deck":d.to_dict(),"logic":g.to_dict()} for d,g in zip((self.base,axis),graphs[:2])]
        unknown=paired_fixture(self.task,self.assets,[self.base,axis],preferred=None)
        receipt=record_comparison(self.session,self.assets,unknown,contexts)
        self.assertIsNone(receipt["preferred_index"])
        self.assertEqual(evidence_order(self.session.feedback,self.task.sha256,"deck"),{})
        self.assertEqual([r["deck"] for r in self.rows()],[r["deck"] for r in self.rows(self.session.feedback)])
        before=deepcopy(self.session.feedback)
        invalid=deepcopy(unknown);invalid["games"].pop()
        with self.assertRaises(ContractError):record_comparison(self.session,self.assets,invalid,contexts)
        wrong=deepcopy(contexts);wrong[1]["deck"]=self.base.to_dict()
        with self.assertRaises(ContractError):record_comparison(self.session,self.assets,unknown,wrong)
        self.assertEqual(before,self.session.feedback)

    def test_binding_counterexample_requests_a_new_plan_but_budget_exhaustion_is_unknown(self):
        graph=self.graphs()[0]
        self.session.submit_logic(graph,role="build_goal",reason="synthetic binding test")
        proposal=FillProposal(self.base,tuple(NodeBinding(n.node_id,(1,)) for n in graph.nodes),
            tuple(e.connector_id for e in graph.connectors),graph.sha256,self.task.sha256)
        def review(node,cards,status="satisfied"):
            return NodeTextReview(node.node_id,status,node.tags,
                (TextEvidence(1,digest(self.assets.rows[1]["desc"]),"Synthetic card text"),),
                "synthetic-source-bound-assessment","Isolated code path, no real card semantics")
        evaluate_fill(self.session,self.assets,proposal,text_reviewer=review,
            verifier=lambda *args:{"status":"not_found_within_budget"})
        builder=BuildTrainer(self.task,self.assets,BuildTrainingConfig())
        adapter=LogicModelAdapter.from_builder(builder,self.codec,required_tags=self.tags,required_connector_kinds=("ss",))
        adapter.propose(graph_context(self.session,"build_optimizer"))
        self.assertFalse(adapter.last_selection["build_optimizer"]["binding_counterexample_exploration"])
        evaluate_fill(self.session,self.assets,proposal,text_reviewer=lambda n,c:review(n,c,"unsatisfied"))
        revised=ConstructionLogic.from_dict(adapter.propose(graph_context(self.session,"build_optimizer"))["logic"])
        self.assertTrue(adapter.last_selection["build_optimizer"]["binding_counterexample_exploration"])
        self.assertNotEqual(graph_signature(revised),graph_signature(graph))
        self.assertEqual(revised.parent_sha256,graph.sha256)
        self.assertFalse(any(r.get("goal_impossible") for r in self.session.feedback))
