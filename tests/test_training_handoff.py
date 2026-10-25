"""Read-only handoff inventory, including corrupt checkpoint fail-closed evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.training_handoff import checkpoint_inventory, collect, startup_probe
from ygo_kito.agent_monitor import RunReporter


class TrainingHandoffTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def fixture(self):
        reporter = RunReporter(self.root)
        reporter.publish({"schema_version": 1, "run_id": "handoff-fixture", "state": "paused", "revision": 1,
            "model_versions": {}, "metrics": {}, "checkpoint_ids": ["fixture-checkpoint"], "source": "local_contract_fixture"})
        folder = self.root / "runs/handoff-fixture/checkpoints"
        folder.mkdir()
        payload = b"not-pickle-fixture-bytes"
        (folder / "fixture-checkpoint.weights").write_bytes(payload)
        (folder / "fixture-checkpoint.json").write_text(json.dumps({"schema_version": 1, "run_id": "handoff-fixture",
            "checkpoint_id": "fixture-checkpoint", "artifact_sha256": hashlib.sha256(payload).hexdigest(),
            "artifact_bytes": len(payload), "step": 0}), encoding="utf-8")
        return folder

    def test_missing_resources_and_no_checkpoints_never_report_training_ready(self):
        result = collect(self.root, probe=False)
        self.assertFalse(result["native_resources"]["hash_receipt_verified"])
        self.assertIn("engine-src/database/locales/zh-CN/cards.cdb", result["native_resources"]["required"])
        self.assertFalse(result["formal_training_ready"])
        self.assertFalse(result["training_started"])
        self.assertIsNone(result["checkpoints"]["all_registered_bytes_verified"])
        self.assertIsNone(result["dependencies"]["lock_matches_installed"])

    def test_registered_bytes_verified_without_deserializing_or_changing_files(self):
        self.fixture()
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = checkpoint_inventory(self.root)
        self.assertTrue(result["all_registered_bytes_verified"])
        self.assertFalse(result["resume_executed"])
        record = result["runs"][0]["checkpoints"][0]
        self.assertFalse(record["deserialized"])
        self.assertEqual(result["runs"][0]["source"], "local_contract_fixture")
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_changed_checkpoint_is_reported_invalid(self):
        folder = self.fixture()
        (folder / "fixture-checkpoint.weights").write_bytes(b"bad")
        result = checkpoint_inventory(self.root)
        self.assertFalse(result["all_registered_bytes_verified"])
        self.assertFalse(result["runs"][0]["checkpoints"][0]["integrity_verified"])

    def test_empty_checkpoint_with_matching_receipt_is_still_rejected(self):
        folder = self.fixture()
        artifact = folder / "fixture-checkpoint.weights"
        artifact.write_bytes(b"")
        sidecar = folder / "fixture-checkpoint.json"
        receipt = json.loads(sidecar.read_text(encoding="utf-8"))
        receipt.update(artifact_bytes=0, artifact_sha256=hashlib.sha256(b"").hexdigest())
        sidecar.write_text(json.dumps(receipt), encoding="utf-8")
        self.assertFalse(checkpoint_inventory(self.root)["all_registered_bytes_verified"])

    def test_empty_state_is_unknown_and_is_not_created(self):
        result = checkpoint_inventory(self.root / "absent")
        self.assertIsNone(result["all_registered_bytes_verified"])
        self.assertFalse((self.root / "absent").exists())

    def test_fixed_startup_commands_work_outside_checkout(self):
        probes = startup_probe()
        self.assertEqual([p["operation"] for p in probes], ["status", "--help"])
        self.assertTrue(all(p["passed"] for p in probes))
        self.assertTrue(all(p["elapsed_seconds"] > 0 for p in probes))
