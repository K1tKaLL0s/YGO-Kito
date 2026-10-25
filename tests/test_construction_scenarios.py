"""Open-theme routing and repeated-graph scenarios, entirely engineering fixtures.

Scope-helper examples test intent evidence and stage contracts, not a trained
classifier's language accuracy. Untrained production routing is checked with the
actual classifier. No fit, model update, native rule call or provider is run.
"""

from dataclasses import replace
import unittest

from ygo_kito.build_intent import DEFAULT_LEXICON, DomainTerm, IntentClassification, classify_build_intent
from ygo_kito.construction_logic import (
    ConstructionLogic, ConstructionSession, LogicConnector, LogicMetadata, LogicNode,
    LogicTag, ThemeScope, revise_logic, select_main_axes, stage_route,
)
from ygo_kito.construction_service import HostConstructionBackend
from ygo_kito.intent_model import LinearIntentClassifier
from ygo_kito.validation import ContractError
from tests.test_construction_logic import example_graph, fixture_assets


def open_lexicon():
    return DEFAULT_LEXICON.extended(
        DomainTerm("雾海编织", "theme", ("雾织", "mistweavers")),
        DomainTerm("资源改写", "mechanism", ("resource rewrite",)),
    )


class ConstructionScenarioTests(unittest.TestCase):
    def test_open_theme_alias_and_multiple_functional_goals_do_not_define_a_closed_topic_list(self):
        lexicon = open_lexicon()
        for request in ("雾织卡组，堆墓后资源改写", "mistweavers for milling and resource rewrite"):
            with self.subTest(request=request):
                evidence = classify_build_intent(request, lexicon)
                self.assertEqual(evidence.narrow_terms, ("雾海编织",))
                self.assertEqual(set(evidence.broad_terms), {"堆墓", "资源改写"})
                self.assertEqual(stage_route(evidence)["stages"], [1, 2, 3])
        functional = classify_build_intent("资源改写并除外", lexicon)
        self.assertEqual(stage_route(functional)["stages"], [1, 3])
        self.assertEqual(classify_build_intent("mistweavers", DEFAULT_LEXICON).kind, "ambiguous")
        unseen = classify_build_intent("以晨光织梦主题做堆墓", DEFAULT_LEXICON)
        self.assertEqual(unseen.narrow_terms, ("晨光织梦",))
        self.assertEqual(stage_route(unseen)["stages"], [1, 2, 3])

    def test_joint_race_and_new_theme_have_separate_sourced_axes_without_shrinking_generic_pool(self):
        task, assets = fixture_assets()
        evidence = classify_build_intent("雾织植物族堆墓", open_lexicon())
        self.assertEqual(set(evidence.narrow_terms), {"雾海编织", "植物族"})
        scopes = (ThemeScope("雾海编织", "setcode", 0x123, "synthetic-public-field", 2),
                  ThemeScope("植物族", "race_any", 0x4000, "synthetic-public-race", 3))
        before = task.to_dict()
        result = select_main_axes(task, assets, evidence, scopes)
        self.assertEqual(result["status"], "selected")
        self.assertEqual({axis["term"] for axis in result["axes"]}, {"雾海编织", "植物族"})
        self.assertEqual({axis["term"]: axis["minimum"] for axis in result["axes"]}, {"雾海编织": 2, "植物族": 3})
        self.assertTrue(all(axis["card_ids"] == [1, 2, 3, 4] for axis in result["axes"]))
        self.assertEqual(task.to_dict(), before)
        self.assertIn(18, task.pool)  # Generic/support candidates survive main-axis selection.
        unresolved = select_main_axes(task, assets, evidence, scopes[:1])
        self.assertEqual(unresolved["status"], "unresolved_theme_facts")
        missing = select_main_axes(task, assets, evidence, (replace(scopes[0], value=0x777), scopes[1]))
        self.assertEqual(missing["status"], "no_axis_candidates")

    def test_combined_optional_excluded_and_alternative_theme_roles_remain_distinct(self):
        lexicon = open_lexicon()
        for request, expected in (("雾织加堆墓", [1, 2, 3]), ("雾织可选，以堆墓为主", [1, 3]),
                                  ("不要雾织和神碑，只要资源改写", [1, 3]),
                                  ("雾织或者资源改写", [1]), ("雾织或者植物族堆墓", [1])):
            with self.subTest(request=request):
                self.assertEqual(stage_route(classify_build_intent(request, lexicon))["stages"], expected)
        excluded = classify_build_intent("不要雾织和神碑，只要资源改写", lexicon)
        self.assertEqual(set(excluded.excluded_terms), {"雾海编织", "神碑"})
        self.assertFalse(excluded.narrow_terms)

    def test_low_confidence_for_either_route_and_untrained_model_keep_only_logic_stage(self):
        task, assets = fixture_assets()
        for kind, terms in (("narrow", {"narrow_terms": ("植物族",)}), ("broad", {"broad_terms": ("堆墓",)})):
            # Explicit router DTO fixture, not a claimed learned prediction.
            low = IntentClassification(kind, 0.699999, **terms)
            self.assertEqual(stage_route(low)["stages"], [1])
            self.assertEqual(select_main_axes(task, assets, low)["status"], "needs_clarification")
        backend = HostConstructionBackend(LinearIntentClassifier())
        for request in ("植物族堆墓", "资源改写", "雾织或者堆墓"):
            with self.subTest(request=request):
                plan = backend.plan({"request": request})
                self.assertEqual(plan["classification"]["kind"], "ambiguous")
                self.assertEqual(plan["route"]["stages"], [1])
                self.assertIn("untrained_classifier", plan["classification"]["reasons"])

    def test_all_feedback_sources_survive_repeated_target_optimizer_reconstruction(self):
        task, _ = fixture_assets()
        session = ConstructionSession("保留回收目标，可按反馈重构", task)
        session.submit_logic(example_graph(), role="build_goal", reason="explicit graph fixture")
        goal_sha, task_sha = session.goal_sha256, session.task.sha256
        initial_graph = session.logic.sha256
        sources = ("user", "fill", "duel", "build_goal", "build_optimizer", "coordinator")
        for source in sources:
            session.record_feedback(source, source + " fixture feedback; not a duel result")
        observed = []
        def proposal(context):
            observed.append({"role": context["role"], "feedback": context["feedback"], "goal": context["goal_sha256"]})
            old = ConstructionLogic.from_dict(context["logic"])
            start = LogicNode("resource", (LogicTag("effect", "资源准备"),),
                              (LogicMetadata("fixture-feedback", "engineering", "Rebuilt route, unchanged request"),))
            finish = LogicNode("recover", (LogicTag("effect", "回收"),))
            kind = "ss" if context["role"] == "build_goal" else "送墓时发动"
            graph = revise_logic(old, nodes=(start, finish), connectors=(LogicConnector("link", "resource", "recover", kind),),
                                 entry_nodes=("resource",), goal_nodes=("recover",))
            # Provider context is detached; an edit here cannot change the task.
            context["task"]["goal"]["card_id"] = 999999
            return {"logic": graph.to_dict(), "reason": "explicit synthetic provider restructuring"}
        providers = {role: proposal for role in ("build_goal", "build_optimizer")}
        self.assertEqual(session.logic_cycle(providers)["status"], "logic_revised")
        session.record_feedback("user", "Another fixture revision is requested")
        self.assertEqual(session.logic_cycle(providers)["status"], "logic_revised")
        self.assertEqual([row["role"] for row in observed], ["build_goal", "build_optimizer"] * 2)
        self.assertEqual(session.logic.revision, 4)
        self.assertNotEqual(session.logic.sha256, initial_graph)
        self.assertTrue(all(row["goal"] == goal_sha for row in observed))
        self.assertEqual({item["source"] for item in observed[-1]["feedback"]}, set(sources))
        self.assertEqual(session.goal_sha256, goal_sha)
        self.assertEqual(session.task.sha256, task_sha)
        self.assertEqual(len(session.history), 5)
        self.assertTrue(all(item["logic_sha256"] == initial_graph for item in session.feedback[:len(sources)]))
        detached = session.to_dict()
        detached["feedback"][0]["message"] = "outside mutation"
        self.assertNotEqual(session.feedback[0]["message"], "outside mutation")

    def test_rewiring_coarse_connectors_does_not_change_basic_tag_identity_or_card_binding(self):
        graph = example_graph()
        identities = {node.node_id: node.tag_identity for node in graph.nodes}
        rewired = revise_logic(graph, connectors=tuple(replace(edge, kind="ss") for edge in graph.connectors))
        self.assertEqual({node.node_id: node.tag_identity for node in rewired.nodes}, identities)
        self.assertNotEqual(graph.sha256, rewired.sha256)
        raw = rewired.to_dict()
        self.assertTrue(all("card_id" not in node for node in raw["nodes"]))
        self.assertTrue(all(set(edge) == {"connector_id", "source", "target", "kind"} for edge in raw["connectors"]))
        with self.assertRaises(ContractError):
            LogicTag("effect", "送墓·ss")
        annotated = replace(graph.nodes[0], metadata=(LogicMetadata("fixture", "engineering", "Source notes remain metadata"),))
        self.assertEqual(annotated.tag_identity, graph.nodes[0].tag_identity)


if __name__ == "__main__":
    unittest.main()
