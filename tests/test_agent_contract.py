"""Vendor-neutral contract tests for the local JSON Lines agent interface.

These drive the production entry point (``AgentBridge.dispatch``) through the
reference client, so they exercise the real envelope, the real role table and the
real error mapping.  They need no rule core, no card database and no provider:
everything asserted here is engine-free by construction, which is also the limit
of what they prove.  Duel sequencing, stale actor windows and timeout fallbacks
require a prepared native engine and are listed as unverified in the delivery
notes instead of being simulated here.

Two of these tests are regressions for defects found by running the repository's
own ``tests/test_agent_tools.py`` on Windows: a leaked sqlite handle that made the
registry file undeletable, and a platform-default text decode that failed on a
UTF-8 checklist.
"""

import ast
from pathlib import Path
import io
import json
import os
import tempfile
import unittest

from ygo_kito.agent_bridge import ROLES, AgentBridge
from ygo_kito.agent_driver import (
    Client, LoopbackTransport, ProtocolError, RemoteError, REQUIRED_METRICS,
    StreamTransport, metric_gaps, parse_response, request,
)
from ygo_kito.agent_registry import OpponentRegistry
from ygo_kito.agent_monitor import RunMonitor
from ygo_kito.validation import ContractError

SOURCE = Path(__file__).resolve().parents[1] / "src/ygo_kito"
ROLE_METHODS = {role: sorted(methods) for role, methods in ROLES.items()}


def envelope_ok(request_id, result):
    return {"schema_version": 1, "id": request_id, "ok": True, "result": result}


def envelope_error(request_id, code, message="denied"):
    return {"schema_version": 1, "id": request_id, "ok": False,
            "error": {"code": code, "message": message}}


class EnvelopeTests(unittest.TestCase):
    def test_request_carries_the_declared_schema_and_id(self):
        message = request("capabilities", {}, "req-1")
        self.assertEqual(message, {"schema_version": 1, "id": "req-1", "method": "capabilities", "params": {}})

    def test_request_rejects_a_missing_method_or_non_object_params(self):
        for method, params in ((None, {}), ("", {}), ("runs.list", []), ("runs.list", "x")):
            with self.subTest(method=method, params=params), self.assertRaises(ProtocolError):
                request(method, params, "req-1")

    def test_response_envelope_rejects_drift_instead_of_ignoring_it(self):
        bad = [
            {"schema_version": 2, "id": "a", "ok": True, "result": 1},
            {"schema_version": 1, "id": "a", "ok": True, "result": 1, "extra": 1},
            {"schema_version": 1, "id": "a", "ok": "yes", "result": 1},
            {"schema_version": 1, "id": "a", "ok": True, "result": 1, "error": {"code": "X", "message": "y"}},
            {"schema_version": 1, "id": "a", "ok": False, "error": {"code": "X"}},
            {"schema_version": 1, "id": "a", "ok": False, "error": {"code": "X", "message": "y", "z": 1}},
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                parse_response(value, "a")

    def test_response_id_must_match_the_request(self):
        with self.assertRaises(ProtocolError):
            parse_response(envelope_ok("other", {"ok": 1}), "a")

    def test_a_server_error_becomes_a_typed_remote_error(self):
        with self.assertRaises(RemoteError) as raised:
            parse_response(envelope_error("a", "STALE_STATE", "stale window"), "a")
        self.assertEqual(raised.exception.code, "STALE_STATE")
        self.assertEqual(raised.exception.message, "stale window")

    def test_result_is_returned_unchanged_for_a_valid_envelope(self):
        self.assertEqual(parse_response(envelope_ok("a", {"k": [1, 2]}), "a"), {"k": [1, 2]})
        # A JSON text line is accepted too, which is what a stdio host reads.
        self.assertEqual(parse_response(json.dumps(envelope_ok("a", 7)), "a"), 7)


class RoleMatrixTests(unittest.TestCase):
    """The fixed role table, exercised through the real dispatch guard."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / "state").mkdir()
        (self.root / "native").mkdir()

    def bridge(self, role, **kwargs):
        return AgentBridge(self.root, self.root / "state", self.root / "native", role=role, **kwargs)

    def test_capability_discovery_reports_exactly_the_role_methods(self):
        for role in ROLES:
            with self.subTest(role=role):
                client = Client(LoopbackTransport(self.bridge(role).dispatch))
                capabilities = client.capabilities()
                self.assertEqual(capabilities["api"], "ygo-kito-local-json-v1")
                self.assertEqual(capabilities["transport"], "json-lines-not-mcp")
                self.assertEqual(capabilities["role"], role)
                self.assertEqual(sorted(capabilities["methods"]), ROLE_METHODS[role])
                self.assertFalse(capabilities["provider_connected"])
                self.assertFalse(capabilities["cloud_resource_control_implemented"])

    def test_no_role_reaches_a_method_it_does_not_own(self):
        # Every (role, method) pair outside the table must be refused, not merely undocumented.
        for role in ROLES:
            allowed = set(ROLES[role])
            for method in sorted(set().union(*ROLES.values())):
                if method in allowed:
                    continue
                with self.subTest(role=role, method=method):
                    client = Client(LoopbackTransport(self.bridge(role).dispatch))
                    with self.assertRaises(RemoteError) as raised:
                        client.call(method, {})
                    self.assertEqual(raised.exception.code, "PERMISSION_DENIED")

    def test_training_control_and_duel_are_disjoint_authorities(self):
        monitor = Client(LoopbackTransport(self.bridge("monitor").dispatch))
        trainer = Client(LoopbackTransport(self.bridge("trainer").dispatch))
        opponent = Client(LoopbackTransport(self.bridge("opponent").dispatch))
        self.assertFalse(monitor.has("training.control"))
        self.assertTrue(trainer.has("training.control"))
        self.assertFalse(trainer.has("duel.submit_action"))
        self.assertTrue(opponent.has("duel.submit_action"))
        self.assertFalse(opponent.has("runs.read"))
        with self.assertRaises(RemoteError):
            monitor.training_control("run-a", "start", 0, "ctl-1")

    def test_malformed_request_is_an_invalid_request_with_no_id(self):
        bridge = self.bridge("monitor")
        response = bridge.dispatch({"schema_version": 1, "method": "capabilities"})
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "INVALID_REQUEST")
        self.assertIsNone(response["id"])

    def test_unknown_method_is_refused_through_the_role_table(self):
        client = Client(LoopbackTransport(self.bridge("monitor").dispatch))
        with self.assertRaises(RemoteError) as raised:
            client.call("training.delete_everything", {})
        self.assertEqual(raised.exception.code, "PERMISSION_DENIED")

    def test_monitor_reads_an_empty_state_root_without_inventing_runs(self):
        client = Client(LoopbackTransport(self.bridge("monitor").dispatch))
        self.assertEqual(client.runs(), [])
        self.assertEqual(client.resumable_runs(), [])

    def test_training_control_without_a_backend_executes_nothing(self):
        # No paid resource and no local worker may be started by default.
        client = Client(LoopbackTransport(self.bridge("trainer").dispatch))
        with self.assertRaises(RemoteError) as raised:
            client.training_control("run-a", "start", 0, "ctl-1")
        self.assertIn(raised.exception.code, ("TRAINING_BACKEND_NOT_CONFIGURED", "STATE_UNAVAILABLE"))


class ClientHelperTests(unittest.TestCase):
    def test_resumable_runs_separates_direct_resume_from_recovery(self):
        def row(run_id, state, checkpoints, revision=3):
            return {"run_id": run_id, "state": state, "revision": revision,
                    "checkpoint_ids": checkpoints, "source": "trainer",
                    "schema_version": 1, "model_versions": {}, "metrics": {}}

        runs = [row("a-paused", "paused", ["step-2"]),
                row("b-running", "running", ["step-1"]),
                row("c-completed", "completed", ["step-9"], revision=9),
                row("d-failed-no-checkpoint", "failed", [], revision=1),
                row("e-failed-with-checkpoint", "failed", ["step-5"], revision=6),
                row("f-created", "created", ["initial", "step-1"], revision=2),
                row("g-stopped", "stopped", ["step-4"], revision=4)]

        def dispatch(message):
            self.assertEqual(message["method"], "runs.list")
            return envelope_ok(message["id"], runs)

        found = Client(LoopbackTransport(dispatch)).resumable_runs()
        by_id = {item["run_id"]: item for item in found}

        # Terminal and live-owned runs are not offered at all.
        self.assertEqual(set(by_id), {"a-paused", "e-failed-with-checkpoint", "f-created"})

        # A failed run needs training.recover first and must not claim to be resumable.
        failed = by_id["e-failed-with-checkpoint"]
        self.assertFalse(failed["resumable"])
        self.assertTrue(failed["requires_recovery"])
        self.assertEqual(failed["next_step"], {"method": "training.recover", "operation": None})
        self.assertEqual(failed["expected_revision"], 6)

        # Directly continuable runs name the control operation, not "resume" for created.
        self.assertEqual(by_id["a-paused"]["next_step"], {"method": "training.control", "operation": "resume"})
        self.assertTrue(by_id["a-paused"]["resumable"])
        self.assertFalse(by_id["a-paused"]["requires_recovery"])
        self.assertEqual(by_id["f-created"]["next_step"], {"method": "training.control", "operation": "start"})
        self.assertTrue(by_id["f-created"]["resumable"])

    def test_no_candidate_is_marked_resumable_when_it_needs_recovery(self):
        runs = [{"run_id": "only", "state": "failed", "revision": 1, "checkpoint_ids": ["step-1"],
                 "source": "trainer", "schema_version": 1, "model_versions": {}, "metrics": {}}]

        def dispatch(message):
            return envelope_ok(message["id"], runs)

        found = Client(LoopbackTransport(dispatch)).resumable_runs()
        self.assertEqual(len(found), 1)
        self.assertFalse(any(item["resumable"] for item in found))
        self.assertTrue(found[0]["requires_recovery"])

    def test_metric_gaps_separates_uncollected_from_zero(self):
        gaps = metric_gaps({"elapsed_seconds": 1.5, "samples_per_second": 0.0})
        self.assertEqual(gaps["present"], ["elapsed_seconds", "samples_per_second"])
        self.assertEqual(gaps["absent"], ["cpu_percent", "rss_bytes", "gpu_memory_bytes"])
        self.assertIn("not collected", gaps["note"])
        self.assertEqual(set(gaps["present"]) | set(gaps["absent"]), set(REQUIRED_METRICS))

    def test_metric_gaps_treats_a_zero_reading_as_present(self):
        gaps = metric_gaps({key: 0 for key in REQUIRED_METRICS})
        self.assertEqual(gaps["absent"], [])
        self.assertEqual(len(gaps["present"]), len(REQUIRED_METRICS))

    def test_passing_the_run_record_is_refused_instead_of_misreporting(self):
        # The wrapper carries no metric keys, so a lax implementation would report
        # every collected reading as absent.  Refuse it instead.
        record = {"run_id": "r", "revision": 3, "source": "trainer",
                  "metrics": {key: 0 for key in REQUIRED_METRICS}}
        with self.assertRaises(ProtocolError) as raised:
            metric_gaps(record)
        self.assertIn("metrics", str(raised.exception))

    def test_client_metric_gaps_unwraps_the_run_record(self):
        record = {"run_id": "r", "revision": 3, "source": "trainer",
                  "metrics": {"elapsed_seconds": 2.0, "gpu_memory_bytes": 0}}

        def dispatch(message):
            self.assertEqual(message["method"], "runs.metrics")
            return envelope_ok(message["id"], record)

        gaps = Client(LoopbackTransport(dispatch)).metric_gaps("r")
        self.assertEqual(gaps["present"], ["elapsed_seconds", "gpu_memory_bytes"])
        self.assertEqual(gaps["absent"], ["samples_per_second", "cpu_percent", "rss_bytes"])

    def test_client_metric_gaps_refuses_a_snapshot_without_readings(self):
        def dispatch(message):
            return envelope_ok(message["id"], {"run_id": "r", "revision": 1})

        with self.assertRaises(ProtocolError):
            Client(LoopbackTransport(dispatch)).metric_gaps("r")


class TransportRegressionTests(unittest.TestCase):
    def test_a_closed_peer_is_reported_rather_than_retried(self):
        transport = StreamTransport(io.StringIO(""), io.StringIO())
        with self.assertRaises(ProtocolError):
            transport.exchange(request("capabilities", {}, "r-1"))


class MalformedResponseTests(unittest.TestCase):
    """A bad line is a wire-format failure, never an escaping JSONDecodeError."""

    @staticmethod
    def exchange(line):
        return StreamTransport(io.StringIO(line), io.StringIO()).exchange(request("capabilities", {}, "r-1"))

    def test_a_line_that_is_not_json_becomes_a_protocol_error(self):
        for line in ("not json\n", "{'single': 'quotes'}\n", '{"a": \n', "\n", "\x00\x01\n"):
            with self.subTest(line=line), self.assertRaises(ProtocolError):
                self.exchange(line)

    def test_valid_json_of_the_wrong_shape_becomes_a_protocol_error(self):
        for line in ("[1,2]\n", '"text"\n', "null\n", "42\n"):
            with self.subTest(line=line):
                with self.assertRaises(ProtocolError):
                    Client(StreamTransport(io.StringIO(line), io.StringIO())).call("capabilities", {})

    def test_parse_response_also_normalises_a_bad_payload(self):
        for value in (b"\xff\xfe", "{", "[]"):
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                parse_response(value, "r-1")

    def test_a_read_pipe_that_is_not_utf8_becomes_a_protocol_error(self):
        # The text wrapper raises during readline(), before any JSON parsing, so
        # wrapping only json.loads would let a UnicodeDecodeError escape.
        source = io.TextIOWrapper(io.BytesIO(b'{"schema_version":1}\xff\xfe\n'), encoding="utf-8", errors="strict")
        self.addCleanup(source.detach)
        transport = StreamTransport(source, io.StringIO())
        with self.assertRaises(ProtocolError) as raised:
            transport.exchange(request("capabilities", {}, "r-1"))
        self.assertIn("UTF-8", str(raised.exception))

    def test_a_write_pipe_that_cannot_encode_the_request_becomes_a_protocol_error(self):
        destination = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict")
        self.addCleanup(destination.detach)
        transport = StreamTransport(io.StringIO(""), destination)
        with self.assertRaises(ProtocolError):
            transport.exchange(request("deck.import", {"name": "珠泪哀歌"}, "r-1"))


class RequestIdTests(unittest.TestCase):
    """The id is the server's idempotency key: the client must not reseat it."""

    def recorder(self, behaviour=None):
        seen = []

        def dispatch(message):
            seen.append(message)
            if behaviour is not None:
                return behaviour(message)
            return envelope_ok(message["id"], {"ok": 1})

        return seen, LoopbackTransport(dispatch)

    def test_an_explicit_request_id_is_sent_verbatim(self):
        seen, transport = self.recorder()
        Client(transport).call("runs.list", {}, request_id="retry-1")
        self.assertEqual([message["id"] for message in seen], ["retry-1"])

    def test_a_retry_with_the_same_id_addresses_the_same_operation(self):
        cache = {}

        def behaviour(message):
            if message["id"] not in cache:
                cache[message["id"]] = {"execution": "applied", "n": len(cache) + 1}
            return envelope_ok(message["id"], cache[message["id"]])

        seen, transport = self.recorder(behaviour)
        client = Client(transport)
        first = client.call("training.control", {"run_id": "r"}, request_id="ctl-1")
        second = client.call("training.control", {"run_id": "r"}, request_id="ctl-1")
        self.assertEqual(first, second)
        self.assertEqual([message["id"] for message in seen], ["ctl-1", "ctl-1"])

    def test_training_control_forwards_the_callers_request_id(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "state").mkdir()
            (root / "native").mkdir()
            bridge = AgentBridge(root, root / "state", root / "native", role="trainer")
            seen = []

            def dispatch(message):
                seen.append(message["id"])
                return bridge.dispatch(message)

            client = Client(LoopbackTransport(dispatch))
            with self.assertRaises(RemoteError):  # no backend attached: nothing executed
                client.training_control("run-a", "start", 0, "ctl-abc")
            self.assertEqual(seen, ["ctl-abc"])

    def test_default_ids_do_not_collide_between_clients(self):
        first_seen, first = self.recorder()
        second_seen, second = self.recorder()
        Client(first).call("runs.list", {})
        Client(second).call("runs.list", {})
        self.assertNotEqual(first_seen[0]["id"], second_seen[0]["id"])

    def test_default_ids_do_not_collide_between_calls(self):
        seen, transport = self.recorder()
        client = Client(transport)
        client.call("runs.list", {})
        client.call("runs.list", {})
        self.assertNotEqual(seen[0]["id"], seen[1]["id"])

    def test_an_id_the_server_would_refuse_is_rejected_locally(self):
        seen, transport = self.recorder()
        for bad in ("bad.id", "", "-leading", "with space", "x" * 65, 7):
            with self.subTest(bad=bad), self.assertRaises(ProtocolError):
                Client(transport).call("runs.list", {}, request_id=bad)
        self.assertEqual(seen, [], "an invalid id must not reach the transport")

    def test_request_rejects_an_invalid_id_too(self):
        with self.assertRaises(ProtocolError):
            request("runs.list", {}, "bad.id")


class WindowsResourceRegressionTests(unittest.TestCase):
    """Regressions found by running the repository's own agent tests on Windows."""

    def test_registry_connections_are_closed_so_the_file_can_be_renamed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            registry = OpponentRegistry(root, root)
            registry.put("deck", "deck-a", {"main": [1, 2]})
            registry.get("deck", "deck-a")
            registry.records("deck")
            registry.audit("deck-imported", {"deck_id": "deck-a"})
            moved = root / "registry.moved.sqlite3"
            # On Windows an open handle makes this raise PermissionError; that is
            # exactly the leak this fix removes.
            os.replace(registry.path, moved)
            self.assertTrue(moved.is_file())

    def test_conflicting_registry_payload_is_still_refused_after_the_fix(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            registry = OpponentRegistry(root, root)
            registry.put("deck", "deck-a", {"main": [1, 2]})
            registry.put("deck", "deck-a", {"main": [1, 2]})  # identical replay is fine
            with self.assertRaisesRegex(ContractError, "use a new version ID"):
                registry.put("deck", "deck-a", {"main": [1, 3]})

    def test_coding_handoff_reads_the_checklist_as_utf8(self):
        # A platform-default decode fails on a UTF-8 checklist host-side; the
        # source must pass an explicit encoding rather than rely on the locale.
        tree = ast.parse((SOURCE / "coding_agent.py").read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("read_text", "write_text")):
                if not any(keyword.arg == "encoding" for keyword in node.keywords):
                    offenders.append((node.lineno, node.func.attr))
        self.assertEqual(offenders, [], "text IO in the coding handoff must pin encoding")


class MonitorIsolationTests(unittest.TestCase):
    def test_run_identity_cannot_traverse_out_of_the_state_root(self):
        with tempfile.TemporaryDirectory() as folder:
            monitor = RunMonitor(Path(folder))
            # Traversal and separator characters must be refused by the identifier
            # rule before any path is formed.  ("A" is a legal id and is therefore
            # absent here: a legal id simply has no snapshot yet.)
            for bad in ("../escape", "..", "a/b", "", "a b", ".hidden"):
                with self.subTest(bad=bad), self.assertRaises(ContractError):
                    monitor.snapshot(bad)

    def test_a_legal_but_absent_run_id_is_a_lookup_miss_not_a_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            monitor = RunMonitor(Path(folder))
            with self.assertRaises(OSError):
                monitor.snapshot("absent-run")


if __name__ == "__main__":
    unittest.main()
