"""Mandatory real-engine checks. Missing resources fail, never skip or use a mock.

Prepare explicitly, then: .venv/bin/python -m unittest discover -s integration_tests -v
"""

import ctypes
import json
from pathlib import Path
import subprocess
import sys
import unittest

from ygo_kito.contracts import ActionSelection
from ygo_kito.engine import EngineUnavailable
from ygo_kito.native import CardData, NativeSmokeEngine, run_native_smoke
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"


class RealNativeEngineTests(unittest.TestCase):
    def test_closed_engine_selection_cannot_be_reused_in_fresh_instance(self):
        with NativeSmokeEngine(CACHE) as first:
            request = first.next_decision()
            action = next(a for a in request.actions if a.kind == "summon")
            old = ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id)
        with NativeSmokeEngine(CACHE) as second:
            fresh = second.next_decision()
            self.assertNotEqual(old.run_id, fresh.context.run_id)
            with self.assertRaises(ContractError):
                second.submit(old)
            self.assertIs(second.pending, fresh)
            new = next(a for a in fresh.actions if a.kind == "summon")
            second.submit(ActionSelection(fresh.context.run_id, fresh.duel_id, fresh.decision_id, new.action_id))
            self.assertIsNotNone(second.next_decision())

    def test_real_summon_repeats_from_seed_with_database_and_upstream_scripts(self):
        first = run_native_smoke(CACHE, 7)
        second = run_native_smoke(CACHE, 7)
        self.assertEqual(first, second)
        self.assertEqual(first["engine"], "real-ygopro-core")
        self.assertEqual((first["own_hand_before"], first["own_hand_after"], first["summoned"]), (5, 4, 1))
        self.assertIn(11, first["message_ids"])
        self.assertIn(61, first["message_ids"])
        self.assertNotIn(1, first["message_ids"])
        self.assertGreater(first["response_count"], 1)
        self.assertEqual(first["callback_errors"], 0)
        self.assertTrue({"constant.lua", "utility.lua", "procedure.lua"}.issubset(first["loaded_scripts"]))
        self.assertFalse(first["full_duel_supported"])

    def test_real_observation_and_stale_duplicate_or_invented_responses(self):
        with NativeSmokeEngine(CACHE) as engine:
            request = engine.next_decision()
            self.assertEqual(ctypes.sizeof(CardData), 80)
            self.assertEqual(request.observation.observer, 0)
            self.assertIsNone(request.context.seed)  # Actual RNG seed is evaluation metadata, not policy input.
            self.assertEqual(len(request.observation.cards), 5)
            self.assertTrue(all(c.owner == 0 and c.zone == "hand" for c in request.observation.cards))
            self.assertEqual(request.observation.hand_counts, (5, 5))
            chosen = next(a for a in request.actions if a.kind == "summon")
            good = ActionSelection(request.context.run_id, request.duel_id, request.decision_id, chosen.action_id)
            for bad in (ActionSelection(good.run_id, good.duel_id, "stale", good.action_id),
                        ActionSelection(good.run_id, good.duel_id, good.decision_id, "invented")):
                with self.assertRaises(ContractError):
                    engine.submit(bad)
                self.assertIs(engine.pending, request)
            engine.submit(good)
            with self.assertRaises(ContractError):
                engine.submit(good)
            next_request = engine.next_decision()
            self.assertNotEqual(next_request.decision_id, good.decision_id)
            with self.assertRaises(ContractError):
                engine.submit(good)

    def test_real_pool_limits_and_single_process_lifecycle(self):
        with NativeSmokeEngine(CACHE) as engine:
            self.assertEqual(len(set(engine.deck)), 40)
            with self.assertRaises(ContractError):
                engine.validate_deck(engine.deck[:39])
            with self.assertRaises(ContractError):
                engine.validate_deck([engine.deck[0]] * 40)
            with self.assertRaises(ContractError):
                engine.validate_deck([999999999] + list(engine.deck[1:]))
            with self.assertRaises(EngineUnavailable):
                NativeSmokeEngine(CACHE)
        # The rejected second instance must not release the first instance's lease.
        with NativeSmokeEngine(CACHE) as replacement:
            self.assertIsNotNone(replacement.next_decision())

    def test_cli_uses_real_engine_in_child_process(self):
        result = subprocess.run([sys.executable, "-m", "ygo_kito", "native-smoke", "--root", str(CACHE)],
                                cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["summoned"], 1)
