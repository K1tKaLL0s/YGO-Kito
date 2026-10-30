import importlib.util
import json
from pathlib import Path
import sys
import unittest
from copy import deepcopy


_PATH = Path(__file__).parents[1] / "src" / "ygo_kito" / "reference_hints.py"
_SPEC = importlib.util.spec_from_file_location("reference_hints_test_target", _PATH)
hints = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = hints
_SPEC.loader.exec_module(hints)


class ReferenceHintsTest(unittest.TestCase):
    def setUp(self):
        self.tracker = hints.ReferenceHintTracker(templates=hints.DEFAULT_HINT_TEMPLATES)

    def evaluate(self, index, score=50, **changes):
        row = dict(evaluation_id=f"evaluation-{index}", candidate_digest=f"candidate-{index}",
                   cycle_id=f"cycle-{index}", goal_id="goal", period_id="2022-07", score=score)
        row.update(changes)
        return self.tracker.evaluate(**row)

    def test_exact_threshold_and_finite_score_validation(self):
        result = self.evaluate(1, 56)
        self.assertFalse(result["force_optimization"])
        self.assertEqual(result["failure_streak"], 0)
        self.assertTrue(self.evaluate(2, 55.999)["force_optimization"])
        for invalid in (float("nan"), float("inf"), -float("inf"), -1, 101, True, "55", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.evaluate("bad", invalid)
        self.assertEqual(self.tracker.to_dict()["scopes"][0]["evaluations_counted"], 2)

    def test_each_pair_releases_one_stage_and_never_a_fourth(self):
        stages = [self.evaluate(i)["hint_stage"] for i in range(1, 9)]
        self.assertEqual(stages, [None, "main_axis", None, "secondary_axes", None, "generic_tools", None, None])
        self.assertEqual([row["stage"] for row in self.tracker.released_hints(goal_id="goal", period_id="2022-07")], list(hints.HINT_STAGES))

    def test_pass_resets_streak_without_relocking_authorized_stage(self):
        self.evaluate(1)
        self.evaluate(2)
        self.evaluate(3)
        self.assertEqual(self.evaluate(4, 56)["failure_streak"], 0)
        self.assertIsNone(self.evaluate(5)["hint_stage"])
        self.assertEqual(self.evaluate(6)["hint_stage"], "secondary_axes")

    def test_candidate_change_does_not_reset_streak(self):
        self.evaluate(1, candidate_digest="first-deck")
        self.assertEqual(self.evaluate(2, candidate_digest="changed-deck")["hint_stage"], "main_axis")

    def test_evaluation_replay_is_not_counted_or_redelivered(self):
        self.evaluate(1)
        original = self.evaluate(2)
        replay = self.evaluate(2)
        self.assertEqual(original["hint_stage"], "main_axis")
        self.assertFalse(replay["counted"])
        self.assertTrue(replay["duplicate"])
        self.assertIsNone(replay["hint"])
        self.assertEqual(replay["evaluations_counted"], 2)
        with self.assertRaises(ValueError):
            self.evaluate(2, 49)
        with self.assertRaises(ValueError):
            self.evaluate(2, period_id="2022-10")

    def test_same_cycle_candidate_new_id_is_duplicate_and_score_is_bound(self):
        self.evaluate(1, cycle_id="same-cycle", candidate_digest="same-candidate")
        replay = self.evaluate(2, cycle_id="same-cycle", candidate_digest="same-candidate")
        self.assertFalse(replay["counted"])
        self.assertEqual(replay["failure_streak"], 1)
        with self.assertRaises(ValueError):
            self.evaluate(3, 60, cycle_id="same-cycle", candidate_digest="same-candidate")
        self.assertEqual(self.evaluate(4)["hint_stage"], "main_axis")

    def test_same_candidate_new_cycle_counts_as_new_failed_attempt(self):
        self.evaluate(1, candidate_digest="same-candidate")
        self.assertEqual(self.evaluate(2, candidate_digest="same-candidate")["hint_stage"], "main_axis")

    def test_scope_isolation(self):
        self.evaluate(1)
        self.assertIsNone(self.evaluate(2, goal_id="another-goal")["hint_stage"])
        self.assertIsNone(self.evaluate(3, period_id="2022-10")["hint_stage"])
        self.assertEqual(self.evaluate(4)["hint_stage"], "main_axis")
        self.assertEqual(self.tracker.released_hints(goal_id="another-goal", period_id="2022-07"), [])

    def test_json_restart_preserves_idempotency_and_stage(self):
        self.evaluate(1)
        self.evaluate(2, cycle_id="cycle-1", candidate_digest="candidate-1")
        state = json.loads(json.dumps(self.tracker.to_dict()))
        restored = hints.ReferenceHintTracker.from_dict(state)
        self.assertEqual(restored.to_dict(), state)
        self.tracker = restored
        self.assertFalse(self.evaluate(1)["counted"])
        self.assertEqual(self.evaluate(3)["hint_stage"], "main_axis")
        self.assertIsNone(self.evaluate(4)["hint_stage"])
        self.assertEqual(self.evaluate(5)["hint_stage"], "secondary_axes")

    def test_state_tampering_rejected(self):
        self.evaluate(1)
        for mutate in (
            lambda s: s["scopes"][0].update(hints_released=3),
            lambda s: s["evaluations"].append(dict(s["evaluations"][0])),
            lambda s: s["evaluations"][0].update(score=float("nan")),
            lambda s: s.update(unknown="field"),
            lambda s: s["policy"].update(unrecognized=True),
            lambda s: s["scopes"][0].update(failure_streak=True),
            lambda s: s["evaluations"][0].update(evaluation_id=[]),
        ):
            state = deepcopy(self.tracker.to_dict())
            mutate(state)
            with self.assertRaises(ValueError):
                hints.ReferenceHintTracker.from_dict(state)

    def test_templates_reject_card_names_ids_quotes_quantities_and_metadata(self):
        mutations = (
            lambda t: t.update(card_id=572850),
            lambda t: t.update(card_name="珠泪哀歌族·塞壬人鱼"),
            lambda t: t.update(source_text="This is a card text quotation"),
            lambda t: t["blocks"][0].update(quantity=3),
            lambda t: t["blocks"][0].update(role="psy_framegear_gamma"),
            lambda t: t["blocks"][0]["functions"].append("572850"),
            lambda t: t["conditions"].append("珠泪哀歌族"),
            lambda t: t["edges"].append(dict(source="access", target="unknown", relation="feeds")),
        )
        for mutate in mutations:
            templates = deepcopy(hints.DEFAULT_HINT_TEMPLATES)
            mutate(templates["main_axis"])
            with self.assertRaises(ValueError):
                hints.ReferenceHintTracker(templates=templates)

    def test_host_templates_detached_and_allowlisted(self):
        templates = deepcopy(hints.DEFAULT_HINT_TEMPLATES)
        tracker = hints.ReferenceHintTracker(templates=templates)
        templates["main_axis"]["risks"].clear()
        self.tracker = tracker
        self.evaluate(1)
        emitted = self.evaluate(2)
        self.assertTrue(emitted["hint"]["risks"])
        emitted["hint"]["risks"].clear()
        self.assertTrue(tracker.released_hints(goal_id="goal", period_id="2022-07")[0]["hint"]["risks"])

    def test_configurable_pair_length_and_policy_validation(self):
        self.tracker = hints.ReferenceHintTracker(policy=hints.HintPolicy(failures_per_hint=3),
                                                  templates=hints.DEFAULT_HINT_TEMPLATES)
        self.assertIsNone(self.evaluate(1)["hint_stage"])
        self.assertIsNone(self.evaluate(2)["hint_stage"])
        self.assertEqual(self.evaluate(3)["hint_stage"], "main_axis")
        for kwargs in (dict(failures_per_hint=True), dict(failures_per_hint=0),
                       dict(reference_score=0), dict(minimum_ratio=float("nan")), dict(minimum_ratio=2)):
            with self.assertRaises(ValueError):
                hints.HintPolicy(**kwargs)


if __name__ == "__main__":
    unittest.main()
