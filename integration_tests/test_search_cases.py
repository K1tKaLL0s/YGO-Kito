"""All positive evidence here is obtained from the pinned native core and Lua."""

import copy
from pathlib import Path
import unittest

from ygo_kito.contracts import ActionSelection
from ygo_kito.native import NativeError, NativeNormalEngine
from ygo_kito.search_cases import SANGAN, choose_search_action, run_search_case

CACHE = Path(__file__).resolve().parents[1] / ".cache"


class RealSearchCasesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.positive, cls.positive_trace = run_search_case(CACHE)
        cls.negative, cls.negative_trace = run_search_case(CACHE, route="deck-grave")

    def test_real_trigger_search_confirm_and_once_per_turn_after_revival(self):
        r = self.positive["result"]
        self.assertEqual(r["turns"], 1)
        self.assertEqual(r["sangan_field_to_grave"], 2)
        self.assertEqual(r["sangan_activations"], 1)
        self.assertEqual(r["activations"].count(SANGAN), 1)
        self.assertEqual(len(r["search_windows"]), 1)
        self.assertEqual(len(r["confirmations"]), 1)
        self.assertTrue(r["confirmations"][0]["both_public_histories_agree"])
        self.assertTrue(r["confirmations"][0]["revealed_ids"])
        for window in r["search_windows"]:
            self.assertTrue(set(window["candidate_ids"]).isdisjoint(window["opponent_public_history_ids"]))

    def test_real_deck_to_grave_does_not_satisfy_on_field_trigger(self):
        r = self.negative["result"]
        self.assertEqual(r["sangan_field_to_grave"], 0)
        self.assertEqual(r["sangan_activations"], 0)
        self.assertEqual(r["confirmations"], [])
        self.assertTrue(any(e["kind"] == 50 and e.get("public_card") == SANGAN and e["from_zone"] == 1 and e["to_zone"] == 16 for e in self.negative_trace["events"]))

    def test_real_replay_both_routes_and_changed_selection_is_rejected(self):
        for trace in (self.positive_trace, self.negative_trace):
            s, actual = run_search_case(CACHE, replay=trace)
            self.assertTrue(s["replay_verified"])
            self.assertEqual(actual, trace)
        bad = copy.deepcopy(self.positive_trace)
        next(row for row in bad["responses"] if row["prompt"] == 15)["response"] = {"bytes_hex": "00"}
        with self.assertRaises(NativeError):
            run_search_case(CACHE, replay=bad)

    def test_live_search_does_not_query_deck_order_or_expose_choices_to_opponent(self):
        with NativeNormalEngine(CACHE, scenario="search-trigger", seed=9154) as engine:
            for _ in range(80):
                r = engine.next_decision()
                if r.search_choices:
                    self.assertEqual(r.observation.observer, 0)
                    self.assertTrue(all(c.owner == 0 for c in r.search_choices))
                    self.assertTrue(all(not hasattr(c, "sequence") for c in r.search_choices))
                    self.assertTrue(all(engine._rows[c.card_id]["atk"] <= 1500 for c in r.search_choices))
                    opponent = engine._observation(1)
                    public = {code for h in opponent.public_history for code in h.card_ids}
                    self.assertTrue({c.card_id for c in r.search_choices}.isdisjoint(public))
                    with self.assertRaises(NativeError):
                        engine._query(0, 1, 0, 1)
                    a = choose_search_action(r, "field-twice")
                    engine.submit(ActionSelection(r.context.run_id, r.duel_id, r.decision_id, a.action_id))
                    following = engine.next_decision()
                    self.assertEqual(following.search_choices, ())
                    return
                a = choose_search_action(r, "field-twice")
                engine.submit(ActionSelection(r.context.run_id, r.duel_id, r.decision_id, a.action_id))
            self.fail("real deck search was not reached")
