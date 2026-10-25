"""Vendor-neutral lifecycle engineering through the production agent protocol.

The backend below only publishes explicitly labelled fixture states and inert
checkpoint bytes. It never starts a worker, trains a model, loads native rules,
or calls a provider. Pipe tests exercise real UTF-8 JSON Lines in this process;
they do not claim an external agent/provider was connected.
"""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

from ygo_kito.agent_bridge import AgentBridge, serve_bridge
from ygo_kito.agent_driver import Client, LoopbackTransport, ProtocolError, RemoteError, StreamTransport
from ygo_kito.agent_monitor import RunReporter
from ygo_kito.validation import ContractError


class FixtureLifecycleBackend:
    """No-training state-machine fixture behind the actual Bridge interface."""

    def __init__(self, state_root):
        self.root = Path(state_root)
        self.reporter = RunReporter(self.root)
        self.prepare_calls = 0
        self.controls = []
        self.recoveries = []
        self.uncertain_next = False
        self.reject_next = False

    def prepare(self, run_id):
        self.prepare_calls += 1
        if (self.root / "runs" / run_id / "status.json").exists():
            raise ContractError("fixture run exists; no overwrite")
        return self.reporter.publish({"schema_version": 1, "run_id": run_id, "state": "created", "revision": 0,
            "model_versions": {}, "metrics": {"steps": 0}, "checkpoint_ids": [], "source": "local_contract_fixture"})

    def _checkpoint(self, snapshot):
        folder = self.root / "runs" / snapshot["run_id"] / "checkpoints"
        folder.mkdir(exist_ok=True)
        ident = "fixture-inert-0"
        artifact = b"Lifecycle fixture only: not weights, no training was performed."
        (folder / (ident + ".weights")).write_bytes(artifact)
        (folder / (ident + ".json")).write_text(json.dumps({"schema_version": 1, "run_id": snapshot["run_id"],
            "checkpoint_id": ident, "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
            "artifact_bytes": len(artifact), "step": 0}), encoding="utf-8")
        snapshot["checkpoint_ids"] = [ident]
        return ident

    def control(self, *, run_id, operation, expected_revision, request_id):
        self.controls.append((run_id, operation, expected_revision, request_id))
        if self.uncertain_next:
            self.uncertain_next = False
            raise RuntimeError("Fixture acknowledgement unavailable; outcome must remain uncertain")
        if self.reject_next:
            self.reject_next = False
            return {"applied": False, "revision": expected_revision}
        snapshot = self.reporter.snapshot(run_id)
        if snapshot["revision"] != expected_revision:
            raise ContractError("fixture revision changed")
        snapshot["revision"] += 1
        snapshot["state"] = {"start": "running", "pause": "paused", "resume": "running",
                             "stop": "stopped", "save_checkpoint": snapshot["state"]}[operation]
        acknowledgement = {"applied": True, "revision": snapshot["revision"], "state": snapshot["state"]}
        if operation == "save_checkpoint":
            acknowledgement["checkpoint_id"] = self._checkpoint(snapshot)
        self.reporter.publish(snapshot)
        return acknowledgement

    def mark_failed_fixture(self, run_id):
        snapshot = self.reporter.snapshot(run_id)
        snapshot.update(state="failed", revision=snapshot["revision"] + 1)
        return self.reporter.publish(snapshot)

    def recover(self, *, run_id, expected_revision):
        snapshot = self.reporter.snapshot(run_id)
        if snapshot["state"] != "failed" or snapshot["revision"] != expected_revision:
            raise ContractError("fixture recovery needs the inspected failed revision")
        self.recoveries.append((run_id, expected_revision))
        snapshot.update(state="paused", revision=expected_revision + 1)
        return self.reporter.publish(snapshot)


class AgentLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.state = self.root / "state"
        self.backend = FixtureLifecycleBackend(self.state)

    def bridge(self):
        return AgentBridge(self.root, self.state, self.root / "absent-native", role="trainer",
                           training_backend=self.backend)

    def loopback(self):
        bridge = self.bridge()
        self.addCleanup(bridge.close)
        return Client(LoopbackTransport(bridge.dispatch))

    @contextmanager
    def stdio_client(self):
        request_read, request_write = os.pipe()
        response_read, response_write = os.pipe()
        destination = os.fdopen(request_write, "w", encoding="utf-8")
        source = os.fdopen(response_read, "r", encoding="utf-8")
        failures = []
        bridge = self.bridge()
        def host():
            try:
                with os.fdopen(request_read, "r", encoding="utf-8") as incoming, os.fdopen(response_write, "w", encoding="utf-8") as outgoing:
                    serve_bridge(bridge, incoming, outgoing)
            except Exception as error:
                failures.append(error)
        worker = threading.Thread(target=host, daemon=True)
        worker.start()
        try:
            yield Client(StreamTransport(source, destination))
        finally:
            destination.close()  # EOF ends this connection; registered state persists.
            worker.join(timeout=3)
            source.close()
            self.assertFalse(worker.is_alive(), "fixture stdio host did not finish at EOF")
            self.assertEqual(failures, [])

    def test_prepare_start_checkpoint_pause_reconnect_resume_stop_over_json_lines(self):
        with self.stdio_client() as client:
            self.assertTrue(client.has("training.prepare"))
            prepared = client.call("training.prepare", {"run_id": "fixture-life"}, "prepare-1")
            self.assertEqual((prepared["state"], prepared["revision"], prepared["source"]), ("created", 0, "local_contract_fixture"))
            for operation, revision in (("start", 0), ("save_checkpoint", 1), ("pause", 2), ("resume", 3), ("pause", 4)):
                result = client.training_control("fixture-life", operation, revision, "ctl-" + str(revision))
                self.assertEqual(result["execution"], "applied")
                self.assertEqual(result["backend_result"]["revision"], revision + 1)
            checkpoint = client.checkpoint("fixture-life", "fixture-inert-0")
            self.assertTrue(checkpoint["integrity_verified"])
            self.assertFalse(checkpoint["deserialized"])
            self.assertEqual(checkpoint["step"], 0)
        with self.stdio_client() as reconnected:
            candidate = reconnected.resumable_runs()[0]
            self.assertEqual(candidate["state"], "paused")
            self.assertEqual(candidate["next_step"], {"method": "training.control", "operation": "resume"})
            self.assertEqual(candidate["expected_revision"], 5)
            reconnected.training_control("fixture-life", "resume", 5, "resume-after-reconnect")
            reconnected.training_control("fixture-life", "stop", 6, "stop-after-reconnect")
            final = reconnected.run("fixture-life")
            self.assertEqual((final["state"], final["revision"], final["metrics"]["steps"]), ("stopped", 7, 0))
            self.assertEqual(reconnected.resumable_runs(), [])
        self.assertEqual(self.backend.prepare_calls, 1)
        self.assertEqual([row[1] for row in self.backend.controls], ["start", "save_checkpoint", "pause", "resume", "pause", "resume", "stop"])

    def test_lost_reply_same_id_retry_across_new_bridge_executes_control_once(self):
        client = self.loopback()
        client.call("training.prepare", {"run_id": "fixture-retry"})
        bridge = self.bridge()
        class LostFixtureReply:
            calls = 0
            def exchange(self, message):
                self.calls += 1
                bridge.dispatch(message)  # The local operation completed, but its reply is lost.
                raise ProtocolError("fixture connection closed after dispatch")
        lost = LostFixtureReply()
        with self.assertRaises(ProtocolError):
            Client(lost).training_control("fixture-retry", "start", 0, "stable-start")
        self.assertEqual(lost.calls, 1)  # Client does not automatically repeat an uncertain transport call.
        bridge.close()
        replacement = self.loopback()
        recovered_reply = replacement.training_control("fixture-retry", "start", 0, "stable-start")
        self.assertEqual(recovered_reply["execution"], "applied")
        self.assertEqual(replacement.run("fixture-retry")["revision"], 1)
        self.assertEqual(len(self.backend.controls), 1)
        with self.assertRaises(RemoteError) as raised:
            replacement.training_control("fixture-retry", "pause", 1, "stable-start")
        self.assertEqual(raised.exception.code, "INVALID_REQUEST")
        self.assertEqual(len(self.backend.controls), 1)

    def test_uncertain_and_rejected_acknowledgements_are_not_reexecuted(self):
        for run_id, failure in (("fixture-uncertain", "uncertain_next"), ("fixture-rejected", "reject_next")):
            with self.subTest(outcome=run_id):
                client = self.loopback()
                client.call("training.prepare", {"run_id": run_id})
                setattr(self.backend, failure, True)
                before = len(self.backend.controls)
                result = client.training_control(run_id, "start", 0, run_id + "-start")
                self.assertEqual(result["execution"], "uncertain" if failure == "uncertain_next" else "rejected")
                if failure == "uncertain_next":
                    self.assertFalse(result["retry_allowed"])
                replacement = self.loopback()
                self.assertEqual(replacement.training_control(run_id, "start", 0, run_id + "-start"), result)
                with self.assertRaises(RemoteError):
                    replacement.training_control(run_id, "start", 0, run_id + "-changed-id")
                self.assertEqual(len(self.backend.controls), before + 1)
                self.assertEqual(replacement.run(run_id)["revision"], 0)

    def test_failed_fixture_requires_recovery_before_resume_and_recovery_is_deduplicated(self):
        client = self.loopback()
        client.call("training.prepare", {"run_id": "fixture-recover"})
        client.training_control("fixture-recover", "start", 0, "recover-start")
        client.training_control("fixture-recover", "save_checkpoint", 1, "recover-save")
        failed = self.backend.mark_failed_fixture("fixture-recover")
        candidate = client.resumable_runs()[0]
        self.assertFalse(candidate["resumable"])
        self.assertTrue(candidate["requires_recovery"])
        with self.assertRaises(RemoteError):
            client.training_control("fixture-recover", "resume", failed["revision"], "premature-resume")
        params = {"run_id": "fixture-recover", "expected_revision": failed["revision"]}
        result = client.call("training.recover", params, "stable-recovery")
        self.assertEqual(result["snapshot"]["state"], "paused")
        replacement = self.loopback()
        self.assertEqual(replacement.call("training.recover", params, "stable-recovery"), result)
        self.assertEqual(len(self.backend.recoveries), 1)
        snapshot = replacement.run("fixture-recover")
        replacement.training_control("fixture-recover", "resume", snapshot["revision"], "resume-recovered")
        self.assertEqual(replacement.run("fixture-recover")["state"], "running")

    def test_stale_remote_error_is_reported_once_without_backend_execution(self):
        client = self.loopback()
        client.call("training.prepare", {"run_id": "fixture-stale"})
        client.training_control("fixture-stale", "start", 0, "stale-start")
        before = len(self.backend.controls)
        transport = client.transport
        before_exchanges = transport.exchanges
        with self.assertRaises(RemoteError) as raised:
            client.training_control("fixture-stale", "pause", 0, "stale-pause")
        self.assertEqual(raised.exception.code, "STALE_STATE")
        self.assertEqual(transport.exchanges, before_exchanges + 1)
        self.assertEqual(len(self.backend.controls), before)


if __name__ == "__main__":
    unittest.main()
