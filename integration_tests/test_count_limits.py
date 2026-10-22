"""Two physical copies and a turn boundary, all executed by the real core."""

from pathlib import Path
import unittest

from ygo_kito.search_cases import SANGAN, run_search_case

CACHE = Path(__file__).resolve().parents[1] / ".cache"


class RealCountLimitTests(unittest.TestCase):
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
