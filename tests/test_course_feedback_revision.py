"""Course-level post-admission feedback revision entry.

Covers the formal run/resume entry built on the existing fixture course:
queued revision adopted by ``run``, retained incumbent, budget exhaustion kept
as a pending verification, and restart continuation of that pending state.
Static scoring calls stay at zero throughout.
"""
from unittest.mock import patch
import types
import unittest

from ygo_kito.build_contracts import DeckParts, digest
from ygo_kito.build_feedback import FeedbackComparisonPending
from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
from ygo_kito.scenario_course import ScenarioCourse
from ygo_kito.validation import ContractError

from tests import test_scenario_course as _course_harness


NO_STATIC_SCORING = (
    patch.object(ConstructionLayerAdapter, "evaluate_inventory",
                 side_effect=AssertionError("static scoring is forbidden after admission")),
    patch("ygo_kito.construction_quality.evaluate_functional_quality",
          side_effect=AssertionError("static scoring is forbidden after admission")),
    patch("ygo_kito.construction_progress.construction_gate",
          side_effect=AssertionError("static scoring is forbidden after admission")),
)


def _comparison(preferred, status="engineering_preference_observed"):
    def compare(task, assets, candidates, opponent, **kwargs):
        return ({"preferred_index": preferred, "status": status, "mean_scores": [0.5, 0.5]}, [])
    return compare


class CourseFeedbackRevisionEntryTests(unittest.TestCase):
    def setUp(self):
        self.harness = _course_harness.ScenarioCourseTests(
            "test_real_adapter_updates_same_lora_and_pause_restore_resumes_next_bo1")
        self.harness.setUp()
        self.addCleanup(self.harness.doCleanups)
        self.host = self.harness.host
        self.course = self.harness.course
        with self.host.fake_execution():
            self.course.run(1)  # initial admission plus one fixture match at a clean boundary
        self.assertIsNotNone(self.course.deck)
        self.assertIsNotNone(self.course.construction)

    def revised_deck(self):
        deck = self.course.deck
        unused = sorted(set(range(1, 42)) - set(deck.main))
        self.assertTrue(unused, "fixture pool must leave one legal replacement card")
        main = list(deck.main)
        main[0] = unused[0]
        return DeckParts(tuple(sorted(main)), deck.extra, deck.side)

    def feedback(self, revision, issue="actual duel exposed an unusable card slot"):
        return {"source": "duel", "trigger_kind": "duel", "issue": issue,
                "revised_deck": revision.to_dict()}

    def test_queued_revision_is_adopted_by_normal_run_with_zero_static_scoring(self):
        incumbent = self.course.deck
        revision = self.revised_deck()
        self.course.queue_feedback_revision([self.feedback(revision)])
        with NO_STATIC_SCORING[0], NO_STATIC_SCORING[1], NO_STATIC_SCORING[2], \
                patch("ygo_kito.build_feedback.compare_candidates", side_effect=_comparison(1)), \
                self.host.fake_execution():
            self.course.run(1)
        record = self.course.feedback_revision_record()
        self.assertEqual(record["status"], "adopted")
        self.assertEqual(record["attempts"], 1)
        self.assertEqual(record["static_scoring_calls"], 0)
        self.assertEqual(record["incumbent_deck_sha256"], digest(incumbent.to_dict()))
        self.assertEqual(self.course.deck, revision)
        self.assertTrue(any(e.get("kind") == "post_admission_feedback_adopted" for e in self.course.events))

    def test_comparison_that_does_not_support_the_revision_retains_the_incumbent(self):
        incumbent = self.course.deck
        revision = self.revised_deck()
        self.course.queue_feedback_revision([self.feedback(revision)])
        with NO_STATIC_SCORING[0], NO_STATIC_SCORING[1], NO_STATIC_SCORING[2], \
                patch("ygo_kito.build_feedback.compare_candidates", side_effect=_comparison(0)), \
                self.host.fake_execution():
            self.course.run(1)
        record = self.course.feedback_revision_record()
        self.assertEqual(record["status"], "retained_incumbent")
        self.assertEqual(record["stop_reason"], "feedback_duel_not_adopted")
        self.assertEqual(record["active_deck_sha256"], digest(incumbent.to_dict()))
        self.assertEqual(self.course.deck, incumbent)

    def test_budget_exhaustion_saves_a_pending_verification_and_survives_restart(self):
        incumbent = self.course.deck
        revision = self.revised_deck()
        self.course.queue_feedback_revision([self.feedback(revision)])
        with NO_STATIC_SCORING[0], NO_STATIC_SCORING[1], NO_STATIC_SCORING[2], \
                patch("ygo_kito.build_feedback.compare_candidates",
                      side_effect=FeedbackComparisonPending("paired comparison budget exhausted",
                                                            stage="comparison")), \
                self.host.fake_execution():
            self.course.run(1)
        record = self.course.feedback_revision_record()
        self.assertEqual(record["status"], "pending_verification")
        self.assertEqual(record["stop_reason"], "feedback_duel_comparison_pending")
        self.assertEqual(record["verification"]["stage"], "comparison")
        self.assertEqual(record["active_deck_sha256"], digest(incumbent.to_dict()))
        self.assertEqual(self.course.deck, incumbent)
        sessions = list(self.course.models.kernel.sessions.values())
        self.assertTrue(any((session.construction_progress or {}).get("pending_duel_revision")
                            for session in sessions))

        resumed = self.harness.new_course()
        resumed.restore_latest()
        self.assertIsNotNone(resumed.feedback_revision_record())
        with NO_STATIC_SCORING[0], NO_STATIC_SCORING[1], NO_STATIC_SCORING[2], \
                patch("ygo_kito.build_feedback.compare_candidates", side_effect=_comparison(1)), \
                self.host.fake_execution():
            resumed.run(1)
        final = resumed.feedback_revision_record()
        self.assertEqual(final["status"], "adopted")
        self.assertEqual(final["attempts"], 2)
        self.assertEqual(final["static_scoring_calls"], 0)
        self.assertEqual(resumed.deck, revision)

    def test_revision_requires_a_closed_match_boundary_and_an_admitted_deck(self):
        revision = self.revised_deck()
        self.course._start_match("train")
        with self.assertRaisesRegex(ContractError, "closed match boundary"):
            self.course.queue_feedback_revision([self.feedback(revision)])
        self.course.pending = None
        stub = types.SimpleNamespace(deck=None, selection=object(), construction={},
                                     root=self.course.root, binding=self.course.binding)
        with self.assertRaisesRegex(ContractError, "initially admitted deck"):
            ScenarioCourse.queue_feedback_revision(stub, [self.feedback(revision)])


if __name__ == "__main__":
    unittest.main()
