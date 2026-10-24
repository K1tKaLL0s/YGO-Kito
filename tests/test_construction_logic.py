"""CPU engineering behavior only; synthetic cards/reviews are not real CBs."""

from dataclasses import asdict, replace
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.build_intent import IntentClassification, classify_build_intent
from ygo_kito.build_pipeline import BuildAssets, goal_candidates
from ygo_kito.construction_logic import (
    ConstructionLogic, ConstructionSession, LogicConnector, LogicMetadata,
    LogicNode, LogicTag, ThemeScope, revise_logic, select_main_axes, stage_route,
)
from ygo_kito.construction_fill import (
    FillProposal, NodeBinding, NodeTextReview, TextEvidence, evaluate_fill,
    construction_cycle, existing_goal_verifier, fill_with_existing,
)
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]


def fixture_session(request, task, **kwargs):
    return ConstructionSession(request, task, classifier=fixture_classifier(), **kwargs)


from functools import lru_cache


@lru_cache(maxsize=1)
def fixture_classifier():
    from ygo_kito.intent_model import LinearIntentClassifier
    rows = [("narrow", "植物族堆墓"), ("narrow", "植物堆墓"), ("narrow", "星河织梦主题"),
            ("broad", "堆墓"), ("broad", "不要珠泪，只要堆墓"), ("broad", "我要堆墓"),
            ("ambiguous", "植物还是堆墓"), ("ambiguous", "未知裸名"), ("ambiguous", "植物族或者龙族堆墓")]
    model = LinearIntentClassifier()
    model.fit([{"text":text,"label":label} for label,text in rows],epochs=160,learning_rate=3.)
    return model


def fixture_assets():
    raw = json.loads((ROOT / "configs/build-engineering-v1.json").read_text())
    raw["pool"] = list(range(1, 19))
    raw["goal"]["card_id"] = 1
    raw["goal"]["starting_conditions"]["requires_opening_hand"] = [1]
    raw["requirements"] = [{"zone": "main", "card_id": 1, "minimum": 1, "maximum": 3}]
    raw["sizes"]["side"] = 0
    task = BuildTask.from_dict(raw)
    # Exercise existing BuildAssets.check_task/validate/facts without resource
    # loading, native libraries, fake native responses or training updates.
    assets = BuildAssets.__new__(BuildAssets)
    assets.environment = task.environment
    assets.limits = {}
    assets.rows = {c: {"id": c, "alias": 0, "ot": 1, "type": 17,
                       "race": 0x4000 if c <= 4 else 1, "setcode": 0x123 if c <= 4 else 0,
                       "level": 4, "attribute": 1, "atk": c * 100, "def": 0,
                       "name": f"fixture-{c}", "desc": "Synthetic card text: send and recover. No real effect."}
                   for c in task.pool}
    return task, assets


def example_graph():
    nodes = tuple(LogicNode(name, (LogicTag("effect", tag),)) for name, tag in
                  (("start", "启动"), ("grave", "送墓"), ("other", "替代资源"), ("finish", "回收")))
    edges = (LogicConnector("ns", "start", "grave", "ns"),
             LogicConnector("ss", "start", "other", "ss"),
             LogicConnector("trigger", "grave", "finish", "送墓时发动"),
             LogicConnector("alternative", "other", "finish", "ss"))
    return ConstructionLogic("fixture-logic", nodes, edges, ("start",), ("finish",))


def text_review(node, cards):
    return NodeTextReview(node.node_id, "satisfied", node.tags,
                         tuple(TextEvidence(c["id"], digest(c["desc"]), "Synthetic card text") for c in cards),
                         "synthetic-unit-review", "Fixture assessment, not real card semantics.")


def goal_proof(task, deck, assets):
    return {"status": "verified_success", "task_sha256": task.sha256, "deck_sha256": digest(deck.to_dict()),
            "source": "synthetic-unit-verifier-not-engine-evidence"}


def binding(graph, task, deck, path=("ns", "trigger")):
    active = ("start", "grave", "finish") if path == ("ns", "trigger") else ("start", "other", "finish")
    return FillProposal(deck, tuple(NodeBinding(n, (1,)) for n in active), path, graph.sha256, task.sha256)


class LogicGraphTests(unittest.TestCase):
    def test_basic_identity_is_separate_from_notes_and_joint_display(self):
        n = LogicNode("n", (LogicTag("effect", "送墓"), LogicTag("race", "植物族")))
        revised = replace(n, metadata=(LogicMetadata("human", "human", "Different context"),))
        self.assertEqual(n.tag_identity, revised.tag_identity)
        self.assertEqual(n.display_label, "送墓·植物族")
        with self.assertRaises(ContractError):
            LogicTag("effect", "送墓·特召")

    def test_graph_roundtrip_branch_merge_alternative_and_no_card_identity_field(self):
        graph = example_graph()
        self.assertEqual(ConstructionLogic.from_dict(graph.to_dict()), graph)
        example = ConstructionLogic.from_dict(json.loads((ROOT / "configs/construction-logic-example-v1.json").read_text()))
        self.assertEqual(len(example.connectors), 4)
        raw = graph.to_dict()
        raw["nodes"][0]["card_id"] = 123
        with self.assertRaises(ContractError):
            ConstructionLogic.from_dict(raw)
        for edges in ((LogicConnector("x", "missing", "finish", "ss"),),
                      (graph.connectors[0], graph.connectors[0]), ()):
            with self.subTest(edges=edges), self.assertRaises(ContractError):
                replace(graph, connectors=edges)

    def test_stage_routes_always_retain_logic_and_ambiguity_never_forces_stage_two(self):
        for request, expected in (("植物族堆墓", [1, 2, 3]), ("不要珠泪，只要堆墓", [1, 3]),
                                  ("星河织梦主题", [1, 2, 3]), ("植物还是堆墓", [1]), ("未知裸名", [1])):
            with self.subTest(request=request):
                self.assertEqual(stage_route(classify_build_intent(request))["stages"], expected)
        uncertain = IntentClassification("narrow", .6, narrow_terms=("植物族",))
        self.assertEqual(stage_route(uncertain)["stages"], [1])

    def test_feedback_and_complete_reconstruction_keep_goal_and_lineage(self):
        task, _ = fixture_assets()
        session = fixture_session("堆墓", task)
        session.submit_logic(example_graph(), role="build_goal", reason="candidate")
        original = session.goal_sha256
        session.record_feedback("duel", "current path failed; try another resource")
        session.record_feedback("fill", "card text did not satisfy the first candidate")
        replacement_node = LogicNode("new", (LogicTag("effect", "资源循环"),))
        rebuilt = revise_logic(session.logic, nodes=(replacement_node,), connectors=(), entry_nodes=("new",), goal_nodes=("new",))
        session.submit_logic(rebuilt, role="build_optimizer", reason="reconstruct from feedback")
        self.assertEqual(session.goal_sha256, original)
        self.assertEqual(session.history[-1]["logic"]["nodes"][0]["node_id"], "new")
        self.assertEqual(len(session.history[-1]["feedback"]), 2)
        with self.assertRaisesRegex(ContractError, "stale"):
            session.submit_logic(rebuilt, role="build_goal", reason="stale")
        session.request = "silently changed user goal"
        with self.assertRaisesRegex(ContractError, "goal changed"):
            session.submit_logic(revise_logic(rebuilt), role="build_goal", reason="bad")

    def test_target_optimizer_cycle_has_no_rule_template_or_training_claim(self):
        task, _ = fixture_assets()
        session = fixture_session("堆墓", task)
        self.assertEqual(session.logic_cycle({})["status"], "graph_provider_unavailable")
        calls = []
        def propose(context):
            calls.append(context["role"])
            graph = example_graph() if context["logic"] is None else revise_logic(ConstructionLogic.from_dict(context["logic"]))
            # Providers receive a detached task and cannot mutate the user goal.
            context["task"]["goal"]["card_id"] = 999
            return {"logic": graph.to_dict(), "reason": "provider fixture"}
        out = session.logic_cycle({"build_goal": propose, "build_optimizer": propose})
        self.assertEqual(calls, ["build_goal", "build_optimizer"])
        self.assertEqual(out["status"], "logic_revised")
        self.assertEqual(session.task.sha256, task.sha256)

    def test_stage_two_uses_sourced_public_facts_and_keeps_generic_pool(self):
        task, assets = fixture_assets()
        intent = classify_build_intent("植物堆墓")
        self.assertEqual(select_main_axes(task, assets, intent)["status"], "unresolved_theme_facts")
        scopes = (ThemeScope("植物族", "race_any", 0x4000, "synthetic-public-facts", 2),)
        selected = select_main_axes(task, assets, intent, scopes)
        self.assertEqual(selected["axes"][0]["card_ids"], [1, 2, 3, 4])
        self.assertEqual(len(task.pool), 18)
        with self.assertRaises(ContractError):
            select_main_axes(task, assets, classify_build_intent("堆墓"), scopes)


class ConcreteFillTests(unittest.TestCase):
    def setUp(self):
        self.task, self.assets = fixture_assets()
        self.session = fixture_session("堆墓", self.task)
        self.session.submit_logic(example_graph(), role="build_goal", reason="synthetic candidate")
        self.deck = goal_candidates(self.task, self.assets)[0]
        self.proposal = binding(self.session.logic, self.task, self.deck)

    def evaluate(self, **kwargs):
        return evaluate_fill(self.session, self.assets, self.proposal,
                             text_reviewer=kwargs.pop("text_reviewer", text_review),
                             verifier=kwargs.pop("verifier", goal_proof), **kwargs)

    def test_public_fill_and_fallback_hide_private_key_but_retain_private_replay_proof(self):
        private = dict(goal_proof(self.task, self.deck, self.assets), elapsed_seconds=.25,
            route_evidence={"private_selection_key_audit_only": "private-route",
                "steps": [{"private_selection_key_audit_only": "private-step", "public": [1]}]})
        before = deepcopy(private)
        output = self.evaluate(verifier=lambda *args: private)
        public = output["engine_validation"]
        self.assertEqual(output["status"], "task_goal_verified_logic_unproven")
        self.assertEqual(public["route_evidence"], {"steps": [{"public": [1]}]})
        self.assertEqual(public["elapsed_seconds"], .25)
        self.assertEqual(private, before)
        self.assertEqual(self.session._accepted_fill["engine_validation"], before)
        public["route_evidence"]["steps"][0]["public"].clear()
        fallback = self.evaluate(text_reviewer=None)["fallback"]["engine_validation"]
        self.assertEqual(fallback["route_evidence"], {"steps": [{"public": [1]}]})
        self.assertEqual(self.session._accepted_fill["engine_validation"], before)
        self.assertEqual(private, before)

    def test_public_projection_removes_only_exact_key_without_mutating_original(self):
        from ygo_kito.coordinator import versioned_proof
        from ygo_kito.proof_visibility import without_private_selection_key
        private = {"private_selection_key_audit_only": "private-root", "elapsed_seconds": 1.,
            "selection_key": "unrelated-public-field", "steps": [{"private_selection_key_audit_only": "private-step",
                "elapsed_seconds": 2., "private_selection_key_audit_only_suffix": "keep", "status": "verified"}],
            "route": {"child": {"private_selection_key_audit_only": "private-child", "public": [1, 2]}}}
        before = deepcopy(private)
        public = without_private_selection_key(private)
        self.assertNotIn("private_selection_key_audit_only", public)
        self.assertNotIn("private_selection_key_audit_only", public["steps"][0])
        self.assertNotIn("private_selection_key_audit_only", public["route"]["child"])
        self.assertEqual(public["elapsed_seconds"], 1.)
        self.assertEqual(public["selection_key"], "unrelated-public-field")
        self.assertEqual(public["steps"][0]["private_selection_key_audit_only_suffix"], "keep")
        stable = versioned_proof(private)
        self.assertNotIn("elapsed_seconds", stable)
        self.assertNotIn("elapsed_seconds", stable["steps"][0])
        self.assertNotIn("private_selection_key_audit_only", stable["steps"][0])
        public["route"]["child"]["public"].clear()
        self.assertEqual(private, before)

    def test_candidate_retry_returns_original_public_proof_once_and_rechecks_current_assets(self):
        from unittest.mock import Mock
        from ygo_kito.coordinator import Coordinator
        from ygo_kito.coord_contracts import FeedbackPolicy
        private = dict(goal_proof(self.task, self.deck, self.assets), elapsed_seconds=.2,
            responses=[{"request_sha256": "1" * 64, "action_id": "private-key-derived-choice"}],
            route_evidence=[{"private_selection_key_audit_only": "private-replay", "public": True}])
        before = deepcopy(private)
        params = {"candidate_id": "candidate", "parent_candidate_id": None, "task": self.task.to_dict(),
                  "deck": self.deck.to_dict(), "build_models": {"build_goal": "1" * 64, "build_optimizer": "2" * 64}}
        integrity = Mock()
        self.assets.assert_integrity = integrity
        with tempfile.TemporaryDirectory() as temporary:
            coord = Coordinator(Path(temporary) / "public.sqlite3", FeedbackPolicy(), role="coordinator",
                                source="real_engine", assets=self.assets, create=True)
            # Explicit verifier fixture: actual SQLite publication/retry only,
            # not native goal execution or a real private-route trajectory.
            with patch("ygo_kito.coordinator.verify_goal", return_value=private) as verifier:
                first = coord._candidate(params)
                reordered = deepcopy(params); reordered["deck"]["main"].reverse()
                retry = coord._candidate(reordered)
                self.assertEqual(first, retry)
                verifier.assert_called_once()
                integrity.assert_called_once()
                self.assertEqual(retry["validation"]["route_evidence"], [{"public": True}])
                self.assertEqual(retry["validation"]["responses"], private["responses"])
                self.assertNotIn("elapsed_seconds", retry["validation"])
                for key, value in (("parent_candidate_id", "different-parent"),
                                   ("build_models", dict(params["build_models"], build_goal="3" * 64))):
                    with self.subTest(key=key), self.assertRaisesRegex(ContractError, "identity conflict"):
                        coord._candidate(dict(params, **{key: value}))
                # A changed live banlist must still prevent reuse of an accepted
                # receipt; no second verifier call or replacement proof occurs.
                self.assets.limits[1] = 0
                with self.assertRaises(ContractError): coord._candidate(params)
                verifier.assert_called_once()
            self.assertEqual(private, before)

    def test_candidate_inserted_during_verification_keeps_first_receipt_without_audit_identity_conflict(self):
        from ygo_kito.coordinator import Coordinator
        from ygo_kito.coord_contracts import FeedbackPolicy
        params = {"candidate_id": "concurrent-candidate", "parent_candidate_id": None, "task": self.task.to_dict(),
                  "deck": self.deck.to_dict(), "build_models": {"build_goal": "1" * 64, "build_optimizer": "2" * 64}}
        first_proof = dict(goal_proof(self.task, self.deck, self.assets), trajectory_sha256="a" * 64,
                           route_evidence={"private_selection_key_audit_only": "first-private-key"})
        later_proof = dict(first_proof, trajectory_sha256="b" * 64,
                           route_evidence={"private_selection_key_audit_only": "second-private-key"})
        with tempfile.TemporaryDirectory() as temporary:
            coord = Coordinator(Path(temporary) / "race.sqlite3", FeedbackPolicy(), role="coordinator",
                                source="real_engine", assets=self.assets, create=True)
            accepted = []
            def interleaved_verifier(*args):
                # Explicit race fixture: insert the winner after the outer read
                # and before its transaction. No native engine or threads.
                with patch("ygo_kito.coordinator.verify_goal", return_value=first_proof):
                    accepted.append(coord._candidate(params))
                return later_proof
            with patch("ygo_kito.coordinator.verify_goal", side_effect=interleaved_verifier):
                result = coord._candidate(params)
            self.assertEqual(result, accepted[0])
            self.assertEqual(result["validation"]["trajectory_sha256"], "a" * 64)
            with coord._db() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 1)

    def test_alternative_binding_paths_and_quantities_use_legacy_validation(self):
        for path in (("ns", "trigger"), ("ss", "alternative")):
            self.proposal = binding(self.session.logic, self.task, self.deck, path)
            out = self.evaluate()
            self.assertTrue(out["card_list_legal"])
            self.assertFalse(out["graph_execution_verified"])
            self.assertEqual(out["status"], "task_goal_verified_logic_unproven")
            self.assertEqual(len(out["best_deck"]["main"]), 40)

    def test_unknown_or_unsatisfied_text_rejected_before_engine_and_can_fall_back(self):
        self.assertEqual(self.evaluate()["best_deck"], self.deck.to_dict())
        # A different card-to-node binding fails. The old binding remains valid.
        self.proposal = replace(self.proposal, bindings=tuple(NodeBinding(b.node_id, (2,)) for b in self.proposal.bindings))
        def bad(node, cards):
            return replace(text_review(node, cards), status="unsatisfied", note="actual text cannot supply this effect")
        verifier = unittest.mock.Mock(side_effect=AssertionError("must not invoke engine after bad text"))
        out = self.evaluate(text_reviewer=bad, verifier=verifier)
        self.assertEqual(out["status"], "text_review_unsatisfied")
        self.assertEqual(out["best_deck"], self.deck.to_dict())
        self.assertEqual(out["fallback"]["engine_validation"]["source"], "synthetic-unit-verifier-not-engine-evidence")
        verifier.assert_not_called()
        self.session.submit_logic(revise_logic(self.session.logic), role="build_optimizer", reason="respond to fill feedback")
        self.proposal = binding(self.session.logic, self.task, self.deck)
        out = self.evaluate(text_reviewer=None)
        self.assertEqual(out["status"], "text_review_unknown")
        self.assertIsNone(out["best_deck"])

    def test_corrected_same_binding_invalidates_cache_and_returned_values_are_detached(self):
        accepted = self.evaluate()
        accepted["best_deck"]["main"].clear()
        accepted["text_reviews"][0]["note"] = "caller mutation"
        fallback = self.evaluate(text_reviewer=None)
        self.assertEqual(fallback["best_deck"], self.deck.to_dict())
        self.assertNotEqual(fallback["fallback"]["text_reviews"][0]["note"], "caller mutation")
        fallback["fallback"]["deck"]["main"].clear()
        self.assertEqual(self.evaluate(text_reviewer=None)["best_deck"], self.deck.to_dict())
        def corrected(node, cards):
            return replace(text_review(node, cards), status="unsatisfied", note="earlier text assessment was incorrect")
        rejected = self.evaluate(text_reviewer=corrected)
        self.assertEqual(rejected["status"], "text_review_unsatisfied")
        self.assertIsNone(rejected["best_deck"])
        self.assertIsNone(self.evaluate(text_reviewer=None)["best_deck"])

    def test_fallback_does_not_cross_theme_minimum_or_intent_boundaries(self):
        self.session.classification = classify_build_intent("植物族堆墓")
        scope = ThemeScope("植物族", "race_any", 0x4000, "synthetic", 1)
        self.assertIsNotNone(self.evaluate(scopes=(scope,))["best_deck"])
        tightened = replace(scope, minimum=40)
        rejected = self.evaluate(scopes=(tightened,))
        self.assertEqual(rejected["status"], "theme_axis_not_satisfied")
        self.assertIsNone(rejected["best_deck"])
        self.session.classification = classify_build_intent("植物还是堆墓")
        self.assertIsNone(self.evaluate()["best_deck"])

    def test_same_binding_correction_is_order_independent_for_multiple_cards(self):
        self.proposal = replace(self.proposal, bindings=tuple(NodeBinding(b.node_id, (1, 2)) for b in self.proposal.bindings))
        self.assertIsNotNone(self.evaluate()["best_deck"])
        self.proposal = replace(self.proposal, bindings=tuple(NodeBinding(b.node_id, (2, 1)) for b in self.proposal.bindings))
        def corrected(node, cards):
            return replace(text_review(node, cards), status="unsatisfied", note="same group cannot supply effect")
        self.assertIsNone(self.evaluate(text_reviewer=corrected)["best_deck"])

    def test_real_text_source_and_all_tags_are_required_not_just_any_keyword(self):
        for mutation in ("stale-text", "wrong-quote", "missing-card", "missing-tag"):
            def altered(node, cards):
                review = text_review(node, cards)
                if mutation == "missing-tag":
                    return replace(review, reviewed_tags=())
                if mutation == "missing-card":
                    return replace(review, evidence=())
                ev = replace(review.evidence[0], **({"effect_text_sha256": "0" * 64} if mutation == "stale-text" else {"quote": "not present"}))
                return replace(review, evidence=(ev,))
            with self.subTest(mutation=mutation):
                out = self.evaluate(text_reviewer=altered, verifier=None)
                self.assertIsNone(out["best_deck"])
                self.assertIn(out["status"], ("text_review_unknown", "text_evidence_mismatch"))

    def test_ambiguous_intent_cannot_fill_and_theme_minimum_is_preserved(self):
        self.session.classification = classify_build_intent("植物还是堆墓")
        self.assertEqual(self.evaluate()["status"], "needs_clarification")
        self.session.classification = classify_build_intent("植物堆墓")
        scope = ThemeScope("植物族", "race_any", 0x4000, "synthetic", 40)
        self.assertEqual(self.evaluate(scopes=(scope,))["status"], "theme_axis_not_satisfied")

    def test_stale_foreign_missing_and_disconnected_bindings_fail(self):
        for proposal in (replace(self.proposal, task_sha256="0" * 64),
                         replace(self.proposal, logic_sha256="0" * 64),
                         replace(self.proposal, bindings=(NodeBinding("finish", (1,)),), connector_ids=()),
                         replace(self.proposal, bindings=(NodeBinding("start", (999,)), *self.proposal.bindings[1:]))):
            with self.subTest(proposal=proposal), self.assertRaises(ContractError):
                evaluate_fill(self.session, self.assets, proposal, text_reviewer=text_review, verifier=goal_proof)

    def test_list_legality_and_engine_receipts_are_independent_from_text(self):
        self.proposal = replace(self.proposal, deck=DeckParts(self.deck.main[:-1]))
        self.assertEqual(self.evaluate()["status"], "hard_constraint_failure")
        self.proposal = binding(self.session.logic, self.task, self.deck)
        self.assertEqual(self.evaluate(verifier=None)["status"], "engine_validation_not_run")
        from ygo_kito.engine import EngineUnavailable
        def unavailable(*args):
            raise EngineUnavailable("unavailable test interface")
        self.assertEqual(self.evaluate(verifier=unavailable)["status"], "engine_unavailable")
        self.assertEqual(self.evaluate(verifier=lambda *args: {"status": "unsupported_route"})["status"], "existing_goal_unverified")
        self.assertEqual(self.evaluate(verifier=lambda *args: {"status": "verified_success"})["status"], "engine_receipt_mismatch")

    def test_existing_goal_adapter_delegates_without_native_execution_in_test(self):
        with patch("ygo_kito.build_pipeline.verify_goal", return_value={"status": "fixture"}) as verify:
            self.assertEqual(existing_goal_verifier(self.task, self.deck, self.assets)["status"], "fixture")
            verify.assert_called_once_with(self.task, self.deck, self.assets)

    def test_existing_count_only_goal_interface_does_not_claim_effect_execution(self):
        raw = self.task.to_dict()
        raw["schema_version"] = 4
        raw["goal"] = {"kind": "deck_constraints", "constraints": [
            {"id": "normal-monsters", "zones": ["main"], "predicate": {"field": "type_all", "value": 17},
             "minimum": 40, "maximum": 40}], "preferences": []}
        raw["environment"]["versions"]["card_pool"] = "native-private-knowledge-v5"
        task = BuildTask.from_dict(raw)
        session = fixture_session("堆墓", task)
        session.submit_logic(example_graph(), role="user", reason="count-only engineering fixture")
        out = evaluate_fill(session, self.assets, binding(session.logic, task, self.deck), text_reviewer=text_review)
        self.assertEqual(out["status"], "list_constraints_verified_logic_unproven")
        self.assertFalse(out["engine_validation"]["effect_execution_verified"])
        self.assertFalse(out["graph_execution_verified"])

    def test_coordinator_runs_target_then_optimizer_with_feedback_and_stage_history(self):
        calls = []
        def provider(context):
            calls.append(context)
            graph = example_graph() if context["logic"] is None else revise_logic(ConstructionLogic.from_dict(context["logic"]))
            return {"logic": graph.to_dict(), "reason": "synthetic role proposal"}
        session = fixture_session("堆墓", self.task)
        providers = {role: provider for role in ("build_goal", "build_optimizer")}
        out = construction_cycle(session, self.assets, providers, binding_provider=binding,
                                 text_reviewer=text_review, verifier=goal_proof)
        self.assertEqual(out["status"], "task_checked_candidate")
        self.assertEqual([c["role"] for c in calls], ["build_goal", "build_optimizer"])
        self.assertTrue(calls[1]["feedback"])
        self.assertEqual([h["stage"] for h in session.history], [1, 2, 3, 1, 2, 3])
        self.assertEqual(out["phases"][0]["stage_2"]["status"], "skipped_broad")
        self.assertEqual(out["best"]["logic_sha256"], session.logic.sha256)
        detached = session.to_dict()
        detached["task"]["goal"]["card_id"] = 999
        self.assertEqual(session.task.sha256, self.task.sha256)

    def test_failed_optimizer_graph_returns_old_candidate_with_its_original_graph(self):
        def provider(context):
            graph = example_graph() if context["logic"] is None else revise_logic(ConstructionLogic.from_dict(context["logic"]))
            return {"logic": graph.to_dict(), "reason": "synthetic revision"}
        session = fixture_session("堆墓", self.task)
        def review(node, cards):
            answer = text_review(node, cards)
            return replace(answer, status="unsatisfied", note="new graph cannot be filled") if session.logic.revision else answer
        out = construction_cycle(session, self.assets, {r: provider for r in ("build_goal", "build_optimizer")},
                                 binding_provider=binding, text_reviewer=review, verifier=goal_proof)
        self.assertEqual(out["best"]["logic"]["revision"], 0)
        self.assertNotEqual(out["best"]["logic_sha256"], out["latest_logic_sha256"])
        self.assertFalse(out["graph_execution_verified"])

    def test_existing_candidate_generator_and_independent_ranker_forward_remain_compatible(self):
        import torch
        from ygo_kito.build_model import BuildEncoder, BuildModelConfig, BuildRanker
        torch.set_num_threads(1)
        config = BuildModelConfig()
        encoder = BuildEncoder(self.task, self.assets, config)
        models = {role: BuildRanker(config, len(self.task.pool), len(encoder.tags))
                  for role in ("build_goal", "build_optimizer")}
        self.assertTrue({id(p) for p in models["build_goal"].parameters()}.isdisjoint(
            {id(p) for p in models["build_optimizer"].parameters()}))
        for role in models:
            with self.subTest(role=role):
                out = fill_with_existing(self.session, self.assets, role=role, base=self.deck if role == "build_optimizer" else None,
                    models=models, encoder=encoder, binding_provider=binding, text_reviewer=text_review, verifier=goal_proof)
                self.assertEqual(out["status"], "task_goal_verified_logic_unproven")
                self.assertEqual(out["ranking"], "existing_role_model_uncalibrated")
                self.assertFalse(out["graph_execution_verified"])
        self.assertEqual(fill_with_existing(self.session, self.assets)["status"], "binding_provider_unavailable")


if __name__ == "__main__":
    unittest.main()
