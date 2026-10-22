"""Local contracts/fixtures only; no external model, provider or training success claims."""

import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ygo_kito.agent_bridge import AgentBridge, serve_bridge
from ygo_kito.agent_monitor import RunMonitor, RunReporter
from ygo_kito.coding_agent import CodeBuddyCLIAdapter
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]


def message(method, params=None, request_id="request-1"):
    return {"schema_version": 1, "id": request_id, "method": method, "params": params or {}}


def fixture_run(state_root, *, revision=0, state="running"):
    run = Path(state_root) / "runs" / "fixture-run"
    run.mkdir(parents=True, exist_ok=True)
    d = {"schema_version": 1, "run_id": "fixture-run", "state": state, "revision": revision,
         "model_versions": {}, "metrics": {"steps": 12, "loss": .5}, "checkpoint_ids": [], "source": "local_contract_fixture"}
    (run / "status.json").write_text(json.dumps(d))
    return run, d


class AgentContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def bridge(self, **kwargs):
        return AgentBridge(ROOT, self.state, ROOT / ".cache", **kwargs)

    def test_empty_monitor_has_no_fake_training_runs_or_provider_connection(self):
        b = self.bridge()
        self.assertEqual(b.dispatch(message("runs.list"))["result"], [])
        caps = b.dispatch(message("capabilities"))["result"]
        self.assertFalse(caps["provider_connected"])
        self.assertFalse(caps["training_backend_configured"])
        self.assertEqual(caps["transport"], "json-lines-not-mcp")

    def test_fixed_roles_reject_control_decks_and_role_override(self):
        for role, method in (("monitor", "training.control"), ("manager", "training.control"),
                             ("opponent", "runs.read"), ("opponent", "deck.read"), ("trainer", "deck.import")):
            response = self.bridge(role=role).dispatch(message(method))
            self.assertEqual(response["error"]["code"], "PERMISSION_DENIED")
        bad = message("capabilities")
        bad["role"] = "manager"
        self.assertFalse(self.bridge().dispatch(bad)["ok"])

    def test_training_control_without_backend_reports_not_executed(self):
        r = self.bridge(role="trainer").dispatch(message("training.control", {"run_id": "fixture-run", "operation": "start", "expected_revision": 0}))
        self.assertEqual(r["error"]["code"], "TRAINING_BACKEND_NOT_CONFIGURED")

    def test_monitor_reads_finite_metrics_and_rejects_hidden_or_malformed_fields(self):
        run, data = fixture_run(self.state)
        b = self.bridge()
        self.assertEqual(b.dispatch(message("runs.metrics", {"run_id": "fixture-run"}))["result"]["metrics"]["steps"], 12)
        for mutation in ("private", "float-count", "nonfinite"):
            bad = json.loads(json.dumps(data))
            if mutation == "private":
                bad["metrics"]["hidden_card"] = 1
            elif mutation == "float-count":
                bad["metrics"]["steps"] = 1.5
            else:
                bad["metrics"]["loss"] = float("nan")
            (run / "status.json").write_text(json.dumps(bad))
            self.assertFalse(b.dispatch(message("runs.read", {"run_id": "fixture-run"}))["ok"])

    def test_registered_checkpoint_verifies_bytes_without_deserializing_weights(self):
        run, data = fixture_run(self.state)
        data["checkpoint_ids"] = ["fixture-ckpt"]
        (run / "status.json").write_text(json.dumps(data))
        folder = run / "checkpoints"
        folder.mkdir()
        blob = b"local contract fixture, not trained weights"
        (folder / "fixture-ckpt.weights").write_bytes(blob)
        (folder / "fixture-ckpt.json").write_text(json.dumps({"schema_version": 1, "run_id": "fixture-run",
            "checkpoint_id": "fixture-ckpt", "artifact_sha256": hashlib.sha256(blob).hexdigest(), "artifact_bytes": len(blob), "step": 12}))
        m = RunMonitor(self.state)
        self.assertFalse(m.checkpoint("fixture-run", "fixture-ckpt")["deserialized"])
        (folder / "fixture-ckpt.weights").write_bytes(b"changed")
        with self.assertRaises(ContractError):
            m.checkpoint("fixture-run", "fixture-ckpt")

    def test_monitor_rejects_traversal_and_symlink_escape(self):
        m = RunMonitor(self.state)
        with self.assertRaises(ContractError):
            m.snapshot("../other")
        external = self.state / "outside.json"
        external.write_text("{}")
        folder = self.state / "runs" / "escape"
        folder.mkdir(parents=True)
        (folder / "status.json").symlink_to(external)
        with self.assertRaises(ContractError):
            m.snapshot("escape")

    def test_control_revisions_idempotency_and_uncertain_result_do_not_retry(self):
        run, data = fixture_run(self.state)
        class Backend:
            calls = 0
            fail = False
            def control(self, **kwargs):
                self.calls += 1
                if self.fail:
                    raise RuntimeError("fixture outcome uncertain")
                data["revision"] += 1
                data["state"] = "paused"
                (run / "status.json").write_text(json.dumps(data))
                return {"applied": True, "revision": data["revision"]}
        backend = Backend()
        b = self.bridge(role="trainer", training_backend=backend)
        request = message("training.control", {"run_id": "fixture-run", "operation": "pause", "expected_revision": 0})
        first = b.dispatch(request)
        self.assertTrue(first["ok"])
        self.assertEqual(first, b.dispatch(request))
        self.assertEqual(backend.calls, 1)
        backend.fail = True
        unsure = message("training.control", {"run_id": "fixture-run", "operation": "resume", "expected_revision": 1}, "uncertain-1")
        self.assertEqual(b.dispatch(unsure)["result"]["execution"], "uncertain")
        self.assertFalse(b.dispatch(unsure)["result"]["retry_allowed"])
        changed_id = dict(unsure, id="uncertain-2")
        self.assertFalse(b.dispatch(changed_id)["ok"])
        self.assertEqual(backend.calls, 2)

    def test_coding_handoff_is_prepared_only_with_explicit_model_and_work_branch(self):
        adapter = CodeBuddyCLIAdapter(ROOT)
        r = adapter.prepare({"task_id": "fixture-task", "checklist_ids": ["EA-01"], "goal": "--not-an-option", "model": "explicit-target-model"})
        self.assertFalse(r["executed"])
        self.assertFalse(r["model_verified"])
        self.assertTrue(r["suggested_argv"][-1].startswith("{"))
        self.assertIn("20 percent", " ".join(r["constraints"]))
        with self.assertRaises(ContractError):
            adapter.prepare({"task_id": "x", "checklist_ids": ["EA-01"], "goal": "fix", "model": "--skip-permissions"})

    def test_json_lines_reject_duplicate_keys_without_executing_request(self):
        b = self.bridge()
        source = io.StringIO('{"schema_version":1,"id":"x","id":"y","method":"capabilities","params":{}}\n' + json.dumps(message("runs.list")) + '\n')
        output = io.StringIO()
        serve_bridge(b, source, output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertFalse(responses[0]["ok"])
        self.assertEqual(responses[1]["result"], [])

    def test_trainer_hook_collects_local_resources_and_atomically_publishes_validated_revision(self):
        _run, snapshot = fixture_run(self.state)
        reporter = RunReporter(self.state)
        snapshot["revision"] = 1
        snapshot["metrics"].update(reporter.resources())
        reporter.publish(snapshot)
        self.assertGreaterEqual(reporter.snapshot("fixture-run")["metrics"]["process_cpu_seconds"], 0)
        with self.assertRaisesRegex(ContractError, "advance"):
            reporter.publish(snapshot)
        snapshot["revision"] = 2
        snapshot["metrics"]["raw_hidden_state"] = 42
        with self.assertRaises(ContractError):
            reporter.publish(snapshot)
        self.assertEqual(reporter.snapshot("fixture-run")["revision"], 1)
