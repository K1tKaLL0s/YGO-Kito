"""MSG26 tests execute pinned upstream Lua and core; no protocol fixture success."""
import copy
import json
from pathlib import Path
import unittest

from ygo_kito.contracts import ActionSelection, DecisionRequest
from ygo_kito.native import NativeError, NativeNormalEngine
from ygo_kito.normal_duel import request_digest
from ygo_kito.unselect_case import run_unselect_case
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"


class RealUnselectCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.summary, cls.trace = run_unselect_case(CACHE)

    def test_real_cancel_add_remove_finish_complete_and_json_replay(self):
        verified, again = run_unselect_case(CACHE, replay=json.loads(json.dumps(self.trace)))
        self.assertTrue(verified["replay_verified"])
        self.assertEqual(self.trace, again)
        self.assertTrue(self.summary["result"]["cancel_did_not_consume_procedure"])
        self.assertTrue(self.summary["result"]["goal_special_summon_completed"])
        self.assertEqual(self.summary["result"]["callback_errors"], 0)
        self.assertIn("c18738846.lua", self.summary["result"]["scripts"])
        windows = self.trace["windows"]
        self.assertEqual([w["operation"] for w in windows], ["cancel", "add", "remove", "add", "finish"])
        self.assertEqual([(w["request"]["prompt"]["finishable"], w["request"]["prompt"]["cancelable"]) for w in windows],
                         [(False, True), (False, True), (True, False), (False, True), (True, False)])
        self.assertTrue(all(DecisionRequest.from_dict(w["request"]).context.seed is None for w in windows))

    def test_real_window_rejects_unknown_stale_and_corrupted_native_response(self):
        with NativeNormalEngine(CACHE, scenario="effect-duel", deck_profile=self.trace["profile"], seed=17) as engine:
            req = engine.next_decision()
            previous = None
            for row in self.trace["responses"]:
                self.assertEqual(request_digest(req), row["request_sha256"])
                if req.prompt.message == 26:
                    break
                previous = ActionSelection(req.context.run_id, req.duel_id, req.decision_id, row["action_id"])
                engine.submit(previous)
                req = engine.next_decision()
            with self.assertRaises(ContractError):
                engine.submit(ActionSelection(req.context.run_id, req.duel_id, req.decision_id, "invented"))
            with self.assertRaises(ContractError):
                engine.submit(previous)
            self.assertIs(engine.pending, req)
            chosen = next(a for a in req.actions if a.kind == "select")
            # Deliberate adapter bypass is only a negative native validation test.
            engine._responses[chosen.action_id] = b"\x00"
            engine.submit(ActionSelection(req.context.run_id, req.duel_id, req.decision_id, chosen.action_id))
            with self.assertRaisesRegex(NativeError, "MSG_RETRY"):
                engine.next_decision()

    def test_mutated_replay_fails_before_claiming_success(self):
        bad = copy.deepcopy(self.trace)
        bad["responses"][0]["action_id"] = "not-offered"
        with self.assertRaisesRegex(NativeError, "response diverged"):
            run_unselect_case(CACHE, replay=bad)


if __name__ == "__main__":
    unittest.main()
