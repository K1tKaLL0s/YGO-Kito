"""Representative complete effect games execute the fixed native core and scripts."""

import copy
import json
from pathlib import Path
import unittest

from ygo_kito.contracts import ActionSelection
from ygo_kito.effect_duel import run_effect_duel, public_card_facts
from ygo_kito.native import NativeError, NativeNormalEngine
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"
PROFILE = json.loads((ROOT / "configs/effect-duel-v1.json").read_text())


class RealCompleteEffectDuelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.games = [run_effect_duel(CACHE, PROFILE, seed=seed, option_preference=preference)
                     for seed, preference in ((7, "first"), (24, "first"), (1724, "first"), (1724, "last"))]

    def test_all_four_games_reach_real_terminal_result_and_exact_replay(self):
        for summary, trace in self.games:
            with self.subTest(seed=summary["seed"], preference=trace["versions"]["option_preference"]):
                self.assertGreater(summary["activation_count"], 0)
                self.assertEqual(trace["events"][-1]["kind"], 5)
                self.assertNotIn(1, [e["kind"] for e in trace["events"]])
                self.assertTrue(any(e["kind"] == 72 for e in trace["events"]))
                replay, actual = run_effect_duel(CACHE, {}, replay=trace)
                self.assertTrue(replay["replay_verified"])
                self.assertEqual(actual, trace)

    def test_protocol_coverage_comes_from_real_games(self):
        prompts = {r["prompt"] for _, trace in self.games for r in trace["responses"]}
        kinds = {e["kind"] for _, trace in self.games for e in trace["events"]}
        self.assertTrue({10, 11, 14, 15, 16, 18, 19, 20}.issubset(prompts))
        self.assertTrue({31, 64, 65, 75, 101, 102, 110}.issubset(kinds))
        self.assertTrue({0, 1}.issubset({r["player"] for _, t in self.games for r in t["responses"] if r["prompt"] == 16}))

    def test_replay_mutations_are_rejected_by_actual_execution(self):
        for target in ("request", "response", "events", "truncate"):
            bad = copy.deepcopy(self.games[0][1])
            if target == "request":
                bad["responses"][0]["request_sha256"] = "0" * 64
            elif target == "response":
                bad["responses"][0]["response"] = {"integer": -99}
            elif target == "events":
                bad["events"].pop()
            else:
                bad["responses"].pop()
            with self.subTest(target=target), self.assertRaises(NativeError):
                run_effect_duel(CACHE, {}, replay=bad)

    def test_live_player_views_mask_hidden_cards_and_preserve_actual_ownership(self):
        trace = self.games[-1][1]
        cross_owner = False
        with NativeNormalEngine(CACHE, seed=1724, scenario="effect-duel", deck_profile=PROFILE) as engine:
            request = engine.next_decision()
            for row in trace["responses"]:
                for observer in (0, 1):
                    view = engine._observation(observer)
                    self.assertTrue(all(c.zone != "deck" for c in view.cards))
                    for c in view.cards:
                        if c.visibility == "hidden":
                            self.assertIsNone(c.card_id)
                            self.assertIsNone(c.attack)
                            self.assertIsNone(c.defense)
                            self.assertIsNone(c.owner)
                        if c.visibility == "observer":
                            self.assertEqual(c.controller, observer)
                        cross_owner |= c.owner is not None and c.owner != c.controller
                self.assertIsNone(request.context.seed)
                engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, row["action_id"]))
                request = engine.next_decision()
            self.assertIsNone(request)
            self.assertTrue(cross_owner)  # Real Enemy Controller / revival, not a constructed CardView.

    def test_main_deck_profile_rejects_unknown_extra_cards_and_wrong_sizes(self):
        extra = next(code for code, facts in public_card_facts(CACHE).items() if facts["type"] & 0x40)
        for code in (999999999, extra, None):
            bad = copy.deepcopy(PROFILE)
            if code is None:
                bad["decks"][0] = bad["decks"][0][:39]
            else:
                bad["decks"][0][0] = code
            with self.assertRaises(ContractError):
                NativeNormalEngine(CACHE, scenario="effect-duel", deck_profile=bad)
