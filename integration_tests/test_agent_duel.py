"""Real-core opponent-seat API checks; local driver, never a connected external LLM."""

import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

from ygo_kito.agent_bridge import AgentBridge, serve_bridge
from ygo_kito.contracts import DecisionRequest
from ygo_kito.effect_duel import choose_effect_duel_action, public_card_facts
from ygo_kito.native import NativeSmokeEngine

ROOT = Path(__file__).resolve().parents[1]


def rpc(bridge, method, params=None):
    return bridge.dispatch({"schema_version": 1, "id": "test-request", "method": method, "params": params or {}})


class RealAgentDuelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = AgentBridge(ROOT, Path(self.temp.name), ROOT / ".cache", role="opponent", seat=1,
                                  controller_source="local_contract_fixture", seed=1724)

    def tearDown(self):
        self.bridge.close()
        self.temp.cleanup()

    def test_opponent_only_sees_own_legal_requests_and_can_complete_real_game(self):
        self.assertTrue(rpc(self.bridge, "duel.open")["ok"])
        facts = public_card_facts(ROOT / ".cache")
        for _ in range(1500):
            result = rpc(self.bridge, "duel.next")
            self.assertTrue(result["ok"], result)
            if result["result"]["terminal"]:
                break
            result = result["result"]
            req = DecisionRequest.from_dict(result["request"])
            self.assertEqual(req.observation.observer, 1)
            self.assertIsNone(req.context.seed)
            self.assertTrue(all(c.visibility != "observer" or c.controller == 1 for c in req.observation.cards))
            self.assertNotIn("profile", result)
            self.assertNotIn("responses", result)
            self.assertEqual(result["provenance"]["controller_source"], "local_contract_fixture")
            self.assertFalse(result["provenance"]["provider_verified"])
            a = choose_effect_duel_action(req, facts)
            response = rpc(self.bridge, "duel.submit_action", {"state_version": result["state_version"], "action_id": a.action_id})
            self.assertTrue(response["ok"], response)
            self.assertTrue(response["result"]["accepted"])
        else:
            self.fail("actual core game did not reach terminal result")
        self.assertIn(self.bridge.terminal["winner"], (0, 1))
        self.assertEqual(self.bridge.engine.events[-1]["kind"], 5)

    def test_current_illegal_action_uses_legal_fallback_but_old_window_cannot_advance(self):
        rpc(self.bridge, "duel.open")
        first = rpc(self.bridge, "duel.next")["result"]
        wrong = {"state_version": first["state_version"], "action_id": "not-in-real-candidates"}
        response = rpc(self.bridge, "duel.submit_action", wrong)
        self.assertTrue(response["result"]["fallback_applied"])
        self.assertEqual(response["result"]["reason"], "illegal_action")
        used = self.bridge.actor_decisions
        stale = rpc(self.bridge, "duel.submit_action", wrong)
        self.assertEqual(stale["error"]["code"], "STALE_STATE")
        self.assertEqual(self.bridge.actor_decisions, used)

    def test_deadline_poll_applies_real_legal_fallback_without_an_external_call(self):
        now = [0.0]
        self.bridge.clock = lambda: now[0]
        self.bridge.timeout = 1
        rpc(self.bridge, "duel.open")
        first = rpc(self.bridge, "duel.next")["result"]
        now[0] = 2
        self.bridge.poll_deadline()
        self.assertEqual(self.bridge.actor_decisions, 1)
        self.assertNotEqual(self.bridge.version, first["state_version"])
        with sqlite3.connect(self.bridge.registry.path) as db:
            event = json.loads(db.execute("SELECT payload FROM audit ORDER BY id DESC LIMIT 1").fetchone()[0])
        self.assertEqual(event["reason"], "timeout")
        self.assertFalse(event["billing_verified"])
        self.assertNotIn("amount", event["usage"])  # Unknown usage is not a free API claim.

    def test_role_seat_and_raw_response_overrides_are_rejected(self):
        self.assertFalse(rpc(self.bridge, "duel.open", {"seat": 0})["ok"])
        self.assertFalse(rpc(self.bridge, "runs.list")["ok"])
        rpc(self.bridge, "duel.open")
        own = rpc(self.bridge, "duel.next")["result"]
        bad = rpc(self.bridge, "duel.submit_action", {"state_version": own["state_version"], "action_id": "choice-0", "response": {"integer": 0}})
        self.assertFalse(bad["ok"])
        lookup = rpc(self.bridge, "cards.lookup", {"card_ids": [5318639]})
        self.assertEqual(lookup["result"][0]["source"], "pinned-public-catalogue")

    def test_eof_closes_actual_native_engine_and_cli_transport_has_no_extra_stdout(self):
        source = io.StringIO(json.dumps({"schema_version": 1, "id": "open", "method": "duel.open", "params": {}}) + "\n")
        output = io.StringIO()
        serve_bridge(self.bridge, source, output)
        self.assertTrue(json.loads(output.getvalue())["ok"])
        with NativeSmokeEngine(ROOT / ".cache") as replacement:
            self.assertIsNotNone(replacement.next_decision())
        payload = json.dumps({"schema_version": 1, "id": "caps", "method": "capabilities", "params": {}}) + "\n"
        child = subprocess.run([sys.executable, "-m", "ygo_kito", "agent-serve", "--state-root", self.temp.name],
                               input=payload, capture_output=True, text=True, cwd=ROOT, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(len(child.stdout.splitlines()), 1)
        self.assertEqual(json.loads(child.stdout)["result"]["role"], "monitor")

    def test_stdio_deadline_progresses_while_external_client_sends_nothing(self):
        delivered = threading.Event()
        lines = iter(json.dumps({"schema_version": 1, "id": method.split(".")[-1], "method": method, "params": {}}) + "\n"
                     for method in ("duel.open", "duel.next"))
        class Source:
            def readline(self, _limit):
                try:
                    return next(lines)
                except StopIteration:
                    delivered.wait(5)
                    threading.Event().wait(.4)
                    return ""
        class Output(io.StringIO):
            writes = 0
            def write(self, value):
                count = super().write(value)
                self.writes += 1
                if self.writes == 2:
                    delivered.set()
                return count
        self.bridge.timeout = .02
        serve_bridge(self.bridge, Source(), Output())
        self.assertGreaterEqual(self.bridge.actor_decisions, 1)
        self.assertIsNone(self.bridge.engine)
