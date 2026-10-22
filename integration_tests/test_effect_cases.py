"""Pinned real scripts, real costs and a real opposing counter-trap; no mock core."""

import copy
import ctypes as C
import json
from pathlib import Path
import unittest

from ygo_kito.contracts import ActionSelection
from ygo_kito.effect_cases import CYCLONE, JAMMER, TWISTERS, choose_effect_action, run_effect_case
from ygo_kito.native import NativeNormalEngine
from ygo_kito.normal_duel import run_normal_duel
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"


class RealEffectCasesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.negate, cls.negate_trace = run_effect_case(CACHE, route="negate")
        cls.resolve, cls.resolve_trace = run_effect_case(CACHE, route="resolve")

    def test_actual_counter_chain_retains_paid_cost_and_prevents_target_destruction(self):
        r = self.negate["result"]
        self.assertEqual(r["activations"], [TWISTERS, JAMMER])
        self.assertEqual(r["negated_links"], [1])
        self.assertEqual(len(r["cost_moves"]), 2)
        self.assertTrue(all(e["reason"] & 0x4080 == 0x4080 for e in r["cost_moves"]))
        self.assertTrue(r["costs_before_resolution"])
        self.assertNotIn(CYCLONE, r["graveyard_ids"][0])
        self.assertEqual(r["hand_counts"], [2, 4])
        self.assertTrue(all(self.negate["eligibility"].values()))

    def test_actual_uncountered_resolution_destroys_both_selected_targets(self):
        r = self.resolve["result"]
        self.assertEqual(r["activations"], [TWISTERS])
        self.assertEqual(len(r["cost_moves"]), 1)
        self.assertTrue({CYCLONE, JAMMER}.issubset(r["graveyard_ids"][0]))
        self.assertTrue({CYCLONE, JAMMER}.issubset({e["public_card"] for e in r["effect_destructions"]}))
        self.assertEqual(r["hand_counts"], [3, 4])

    def test_real_response_replay_and_old_normal_replay_still_work(self):
        for trace in (self.negate_trace, self.resolve_trace):
            summary, actual = run_effect_case(CACHE, replay=trace)
            self.assertTrue(summary["replay_verified"])
            self.assertEqual(actual, trace)
        old = json.loads((ROOT / "docs/reports/2026-10-22-normal-m2b.trace.json").read_text())
        summary, _ = run_normal_duel(CACHE, replay=old)
        self.assertTrue(summary["replay_verified"])

    def test_observer_local_windows_do_not_encode_opponent_private_window_count(self):
        for trace in (self.negate_trace, self.resolve_trace):
            for player in (0, 1):
                windows = [r["decision_id"] for r in trace["responses"] if r["player"] == player]
                self.assertEqual(windows, [f"p{player}-window-{i}" for i in range(1, len(windows) + 1)])

    def test_hidden_target_identity_and_private_prompt_data_are_not_in_player_view(self):
        with NativeNormalEngine(CACHE, seed=1724, scenario="effects-counter") as engine:
            for _ in range(60):
                r = engine.next_decision()
                view = {c.ref: c for c in r.observation.cards}
                targets = [a for a in r.actions if a.kind == "select" and a.card_refs and
                           all(view[ref].zone == "spell_trap" and view[ref].owner == 0 for ref in a.card_refs)]
                if r.observation.observer == 1 and targets:
                    self.assertTrue(all(view[ref].card_id is None for a in targets for ref in a.card_refs))
                    self.assertTrue(any(len(a.card_refs) == 2 for a in targets))
                    public_ids = {code for event in r.observation.public_history for code in event.card_ids}
                    self.assertTrue({JAMMER, CYCLONE}.isdisjoint(public_ids))
                    self.assertEqual([e.event_id for e in r.observation.public_history],
                                     [f"public-{i}" for i in range(len(r.observation.public_history))])
                    break
                a = choose_effect_action(r, "negate")
                engine.submit(ActionSelection(r.context.run_id, r.duel_id, r.decision_id, a.action_id))
            else:
                self.fail("real hidden target prompt was not reached")

    def test_real_core_rejects_empty_discard_cost(self):
        with NativeNormalEngine(CACHE, seed=1724, scenario="effects-counter") as engine:
            for _ in range(60):
                r = engine.next_decision()
                view = {c.ref: c for c in r.observation.cards}
                cost = engine.pending_kind == 15 and any(a.card_refs and all(view[ref].zone == "hand" for ref in a.card_refs) for a in r.actions)
                if cost:
                    with self.assertRaises(ContractError):
                        engine.submit(ActionSelection(r.context.run_id, r.duel_id, r.decision_id, "invented-cost"))
                    # Fault injection bypasses our guard only to test the real core's rejection.
                    empty = (C.c_uint8 * 64)()
                    engine.lib.set_responseb(engine.handle, empty)
                    engine.lib.process(engine.handle)
                    data = (C.c_uint8 * 65536)()
                    n = engine.lib.get_message(engine.handle, data)
                    self.assertGreater(n, 0)
                    self.assertEqual(data[0], 1)  # Actual MSG_RETRY, not a simulated response.
                    break
                a = choose_effect_action(r, "negate")
                engine.submit(ActionSelection(r.context.run_id, r.duel_id, r.decision_id, a.action_id))
            else:
                self.fail("real discard-cost prompt was not reached")
