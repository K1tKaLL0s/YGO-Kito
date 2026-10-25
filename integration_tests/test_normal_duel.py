"""Real core completion/replay checks, without replacement engines or skipped cases."""

import copy
from pathlib import Path
import unittest

from ygo_kito.contracts import ActionSelection
from ygo_kito.native import NativeError, NativeNormalEngine
from ygo_kito.normal_duel import choose_normal_action, run_normal_duel
from ygo_kito.validation import ContractError

CACHE = Path(__file__).resolve().parents[1] / ".cache"


class RealNormalDuelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary, cls.trace = run_normal_duel(CACHE, seed=7)

    def test_real_game_reaches_native_win_and_replays_all_events_and_responses(self):
        self.assertGreater(self.summary["turns"], 1)
        self.assertIn(110, {e["kind"] for e in self.trace["events"]})
        self.assertIn(91, {e["kind"] for e in self.trace["events"]})
        self.assertEqual(self.trace["events"][-1]["kind"], 5)
        self.assertIn(0, self.trace["life_points"])
        replay_summary, replay_trace = run_normal_duel(CACHE, replay=self.trace)
        self.assertEqual(replay_trace, self.trace)
        self.assertEqual(replay_summary["trace_sha256"], self.summary["trace_sha256"])
        self.assertTrue(replay_summary["replay_verified"])
        _, other_seed = run_normal_duel(CACHE, seed=42)
        self.assertNotEqual(other_seed["responses"][0]["request_sha256"], self.trace["responses"][0]["request_sha256"])

    def test_modified_or_truncated_replay_is_rejected_by_real_execution(self):
        for mutation in ("request", "response", "events", "truncate"):
            bad = copy.deepcopy(self.trace)
            if mutation == "request":
                bad["responses"][0]["request_sha256"] = "0" * 64
            elif mutation == "response":
                bad["responses"][0]["response"] = {"integer": 999999}
            elif mutation == "events":
                bad["events"][-1]["winner"] = 2
            else:
                bad["responses"] = bad["responses"][:-1]
            with self.subTest(mutation=mutation), self.assertRaises(NativeError):
                run_normal_duel(CACHE, replay=bad)

    def test_both_players_receive_only_own_hand_and_public_state_until_terminal(self):
        players, last = set(), None
        with NativeNormalEngine(CACHE, seed=42) as engine:
            for _ in range(2000):
                request = engine.next_decision()
                if request is None:
                    break
                players.add(request.observation.observer)
                self.assertIsNone(request.context.seed)
                for card in request.observation.cards:
                    if card.zone == "hand":
                        self.assertEqual(card.owner, request.observation.observer)
                    if card.visibility == "hidden":
                        self.assertIsNone(card.card_id)
                    self.assertNotEqual(card.zone, "deck")
                action = choose_normal_action(request)
                last = ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id)
                engine.submit(last)
            else:
                self.fail("real duel failed to terminate within decision bound")
            self.assertEqual(players, {0, 1})
            self.assertIsNotNone(engine.outcome)
            self.assertIsNone(engine.next_decision())
            with self.assertRaises(ContractError):
                engine.submit(last)

    def test_real_set_card_is_hidden_from_next_player(self):
        with NativeNormalEngine(CACHE) as engine:
            request = engine.next_decision()
            action = next(a for a in request.actions if a.kind == "set")
            for step in range(60):
                engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id))
                request = engine.next_decision()
                if request.observation.observer == 1:
                    hidden = [c for c in request.observation.cards if c.owner == 0 and c.zone == "monster"]
                    self.assertEqual(len(hidden), 1)
                    self.assertEqual(hidden[0].visibility, "hidden")
                    self.assertIsNone(hidden[0].card_id)
                    break
                action = choose_normal_action(request)
            else:
                self.fail("real set did not advance to opponent's legal view")

    def test_budget_abort_is_not_a_fabricated_win(self):
        with self.assertRaisesRegex(NativeError, "budget exhausted"):
            run_normal_duel(CACHE, max_decisions=1)
