"""The autonomous 2610 course must not inherit the historical Pearl reference."""
from hashlib import sha256
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ygo_kito.reference_scoring import (
    Block, CardReview, PEARL_PRIORS, Policy, calibrate_reference, inventory_digest, score_construction,
)
from ygo_kito.reference_hints import ReferenceHintTracker
from ygo_kito.reference_hint_templates import templates_for_period
from ygo_kito.reference_scoring_feedback import record_scoring_feedback


def cards():
    text = "anonymous search operation; unrelated grave-fusion operation"
    reviewed = CardReview("engine", "engine", "main", 1, text, sha256(text.encode()).hexdigest(), (
        Block("search", "search-effect", "anonymous search operation"),
        Block("grave_fusion", "different-effect", "unrelated grave-fusion operation"),
    ))
    filler = [CardReview(f"filler-{i}", f"filler-{i}", "main", 1,
                        "unreviewed filler", sha256(b"unreviewed filler").hexdigest()) for i in range(39)]
    return [reviewed, *filler]


def pearl_policy(period="2022-07", **changes):
    values = dict(theme="pearl_grave_fusion", priors=PEARL_PRIORS.copy(), reference_score=70,
                  reference_period_id=period, calibration_scope=f"{period}/historical-pearl-v1")
    values.update(changes)
    return Policy(**values)


class ReferenceScopeRevisionTest(unittest.TestCase):
    def test_missing_theme_or_priors_cannot_silently_use_pearl(self):
        for values in (
            dict(calibration_scope="scope"),
            dict(theme="pearl_grave_fusion", calibration_scope="scope"),
            dict(priors=PEARL_PRIORS.copy(), calibration_scope="scope"),
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Policy(**values).validate()

    def test_pearl_priors_and_historical_period_are_explicit(self):
        rows = cards()
        p = pearl_policy()
        audit = score_construction(rows, policy=p, legality="legal", scope=p.calibration_scope,
                                   evaluation_context={"goal_id": "goal", "period_id": "2022-07"})
        self.assertAlmostEqual(audit["raw_score"], 2.5)
        self.assertIsNone(audit["score"])
        self.assertFalse(audit["calibrated"])

    def test_other_theme_uses_only_explicit_custom_priors_and_has_no_reference_grade(self):
        p = Policy(theme="autonomous_search_theme", priors={"search": (2.0, "custom_search", 5.0)},
                   calibration_scope="2026-10/autonomous-construction")
        audit = score_construction(cards(), policy=p, legality="legal", scope=p.calibration_scope,
                                   evaluation_context={"goal_id": "self-selected-theme", "period_id": "2026-10"})
        self.assertAlmostEqual(audit["raw_score"], 2.0)
        self.assertIsNone(audit["score"])
        self.assertFalse(audit["calibrated"])
        self.assertIsNone(audit["reference_score"])
        self.assertIsNone(audit["threshold"])
        self.assertFalse(audit["force_optimization"])
        self.assertTrue(any("unpriced:grave_fusion" in item for item in audit["unknowns"]))
        with self.assertRaises(ValueError):
            Policy(theme="autonomous_search_theme", priors=PEARL_PRIORS.copy(),
                   calibration_scope="custom-theme").validate()

    def test_2610_cannot_calibrate_a_historical_reference_or_reuse_its_grade(self):
        rows = cards()
        with self.assertRaises(ValueError):
            p = pearl_policy("2026-10")
            calibrate_reference(rows, policy=p, legality="legal", scope=p.calibration_scope,
                                expected_inventory_digest=inventory_digest(rows))
        historical = pearl_policy(reference_raw=2.5)
        with self.assertRaises(ValueError):
            score_construction(rows, policy=historical, legality="legal", scope=historical.calibration_scope,
                               evaluation_context={"goal_id": "autonomous-goal", "period_id": "2026-10"})

    def test_2610_reference_hint_and_feedback_are_rejected_without_state_change(self):
        with self.assertRaises(ValueError):
            templates_for_period("2026-10")
        tracker = ReferenceHintTracker(templates=templates_for_period("2022-07"))
        audit = dict(version="test", theme="pearl_grave_fusion", scope="old-reference", score=55,
                     evaluation_context={"goal_id": "autonomous-goal", "period_id": "2026-10"},
                     reference_score=70, threshold=56, calibrated=True, legality="unknown",
                     force_optimization=True, score_threshold_met=False, basic_cb_verified=None,
                     interpretation="historical reference prior")
        before = tracker.to_dict()
        with self.assertRaises(ValueError):
            tracker.evaluate(evaluation_id="direct-rejected-event", candidate_digest="candidate", cycle_id="cycle",
                             goal_id="autonomous-goal", period_id="2026-10", score=55)
        with self.assertRaises(ValueError):
            ReferenceHintTracker()
        with self.assertRaises(ValueError):
            record_scoring_feedback(audit, tracker, evaluation_id="rejected-event", candidate_digest="candidate",
                                    cycle_id="cycle", goal_id="autonomous-goal", period_id="2026-10")
        self.assertEqual(tracker.to_dict(), before)

    def test_2207_and_2210_reference_calibration_and_hint_feedback_remain_available(self):
        rows = cards()
        for period in ("2022-07", "2022-10"):
            with self.subTest(period=period):
                p = pearl_policy(period)
                p = calibrate_reference(rows, policy=p, legality="legal", scope=p.calibration_scope,
                                        expected_inventory_digest=inventory_digest(rows))
                audit = score_construction(rows, policy=p, legality="legal", scope=p.calibration_scope,
                                           evaluation_context={"goal_id": "historical-goal", "period_id": period})
                self.assertEqual(audit["score"], 70)
                self.assertEqual(audit["threshold"], 56)
                tracker = ReferenceHintTracker(templates=templates_for_period(period))
                low = dict(audit, score=55, force_optimization=True, score_threshold_met=False)
                for index in (1, 2):
                    result = record_scoring_feedback(low, tracker, evaluation_id=f"{period}-{index}",
                                                     candidate_digest="candidate", cycle_id=str(index),
                                                     goal_id="historical-goal", period_id=period)
                self.assertEqual(result["hint_event"]["hint_stage"], "main_axis")


if __name__ == "__main__":
    unittest.main()
