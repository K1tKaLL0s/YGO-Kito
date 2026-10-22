"""Two physical copies and a turn boundary, all executed by the real core."""

from pathlib import Path
import unittest

from ygo_kito.search_cases import SANGAN, run_search_case

CACHE = Path(__file__).resolve().parents[1] / ".cache"


class RealCountLimitTests(unittest.TestCase):
    def test_searched_card_activation_lock_has_real_unlocked_control(self):
        locked, trace = run_search_case(CACHE, route="activation-lock")
        control, _ = run_search_case(CACHE, route="activation-control")
        self.assertFalse(locked["result"]["cardcar_d_activation_available"])
        self.assertTrue(control["result"]["cardcar_d_activation_available"])
        self.assertFalse(locked["result"]["cardcar_d_effect_resolved"])
        self.assertEqual(locked["result"]["confirmations"][0]["revealed_ids"], [45812361])
        self.assertFalse(any(e["kind"] == 62 for e in trace["events"]))  # No special summon blocks the control cost.
        replay, actual = run_search_case(CACHE, replay=trace)
        self.assertTrue(replay["replay_verified"])
        self.assertEqual(actual, trace)

    def test_cross_turn_resets_and_both_real_searches_replay(self):
        summary, trace = run_search_case(CACHE, route="cross-turn")
        self.assertEqual(summary["result"]["sangan_activation_turns"], [1, 3])
        self.assertEqual(summary["result"]["sangan_activations"], 2)
        replay, actual = run_search_case(CACHE, replay=trace)
        self.assertTrue(replay["replay_verified"])
        self.assertEqual(actual, trace)

    def test_two_same_name_copies_share_limit_with_no_searched_name_confound(self):
        summary, trace = run_search_case(CACHE, route="shared-name")
        result = summary["result"]
        self.assertEqual(result["maximum_sangan_on_field"], 2)
        self.assertEqual(result["sangan_field_to_grave"], 2)
        self.assertEqual(result["sangan_activation_turns"], [1])
        self.assertEqual(sum(e["kind"] == 60 and e.get("public_summoning_card") == SANGAN for e in trace["events"]), 2)
        self.assertNotIn(SANGAN, result["confirmations"][0]["revealed_ids"])
        replay, actual = run_search_case(CACHE, replay=trace)
        self.assertTrue(replay["replay_verified"])
        self.assertEqual(actual, trace)
