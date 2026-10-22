import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ygo_kito.config import load_config
from ygo_kito.validation import ContractError

from tests.fixtures import dataset, request, selection


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "cpu.toml"
        self.config.write_text('schema_version = 1\n[storage]\ndatabase = "local/index.sqlite3"\n[runtime]\ndevice = "cpu"\n[engine]\nbackend = "unconfigured"\n', encoding="utf-8")
        self.env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "ygo_kito", "--config", str(self.config), *args],
            cwd=self.root, env=self.env, capture_output=True, text=True, timeout=10,
        )

    def write_json(self, name, payload):
        path = self.root / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def test_config_paths_are_relative_to_config_and_status_is_read_only(self):
        self.assertEqual(load_config(self.config).database, self.root / "local/index.sqlite3")
        output = self.run_cli("status")
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertFalse(json.loads(output.stdout)["engine"]["ready"])
        self.assertFalse((self.root / "local").exists())

    def test_infrastructure_status_does_not_import_optional_torch(self):
        result = subprocess.run([sys.executable, "-c",
            'import sys; from ygo_kito.cli import main; main(["status"]); assert "torch" not in sys.modules'],
            cwd=self.root, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_cpu_training_with_missing_resources_fails_without_a_fake_run(self):
        repo = Path(__file__).resolve().parents[1]
        state = self.root / "training-state"
        result = self.run_cli("duel-train-cpu", "--run-id", "missing-assets", "--root", str(self.root / "missing-native"),
                              "--state-root", str(state), "--profile", str(repo / "configs/effect-duel-v1.json"),
                              "--training-config", str(repo / "configs/cpu-training-smoke.json"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(json.loads(result.stderr)["error"]["code"], "CPU_TRAINING_UNAVAILABLE")
        self.assertFalse(state.exists())

    def test_build_training_missing_resources_does_not_create_model_or_success(self):
        repo = Path(__file__).resolve().parents[1]
        state = self.root / "build-state"
        result = self.run_cli("build-train-cpu", "--run-id", "missing-build-assets", "--root", str(self.root / "missing-native"),
                              "--state-root", str(state), "--task", str(repo / "configs/build-engineering-v1.json"),
                              "--training-config", str(repo / "configs/build-training-smoke.json"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(json.loads(result.stderr)["error"]["code"], "CPU_TRAINING_UNAVAILABLE")
        self.assertFalse(state.exists())

    def test_build_listing_check_does_not_claim_a_route_when_native_assets_are_missing(self):
        repo = Path(__file__).resolve().parents[1]
        deck = self.write_json("candidate.json", {"main": list(range(1, 41)), "extra": [], "side": []})
        result = self.run_cli("build-check", "--root", str(self.root / "missing-native"),
                              "--task", str(repo / "configs/build-engineering-v1.json"), "--deck", deck)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stderr)["error"]["code"], "NATIVE_RESOURCES_UNAVAILABLE")

    def test_coordinator_readonly_missing_ledger_creates_no_fake_state(self):
        repo = Path(__file__).resolve().parents[1]
        ledger = self.root / "missing-ledger.sqlite3"
        payload = self.write_json("coord-read.json", {"schema_version": 1, "id": "read", "method": "status", "params": {}})
        result = self.run_cli("coordinator-call", payload, "--ledger", str(ledger), "--feedback-policy",
                              str(repo / "configs/coordinator-feedback-engineering.json"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(ledger.exists())

    def test_explicit_synthetic_coordinator_cli_is_marked_and_monitor_cannot_submit_results(self):
        repo = Path(__file__).resolve().parents[1]
        ledger = self.root / "contract-ledger.sqlite3"
        policy = str(repo / "configs/coordinator-feedback-engineering.json")
        payload = self.write_json("coord-create.json", {"schema_version": 1, "id": "create", "method": "status", "params": {}})
        result = self.run_cli("coordinator-call", payload, "--ledger", str(ledger), "--feedback-policy", policy,
                              "--source", "synthetic_contract_test", "--role", "coordinator", "--create")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"]["source"], "synthetic_contract_test")
        forbidden = self.write_json("coord-forbidden.json", {"schema_version": 1, "id": "forbidden", "method": "results.append", "params": {"results": []}})
        denied = self.run_cli("coordinator-call", forbidden, "--ledger", str(ledger), "--feedback-policy", policy, "--source", "synthetic_contract_test")
        self.assertEqual(denied.returncode, 2, denied.stderr)
        self.assertEqual(json.loads(denied.stdout)["error"]["code"], "PERMISSION_DENIED")

    def test_model_group_missing_native_assets_does_not_start_or_publish_a_result(self):
        repo = Path(__file__).resolve().parents[1]
        state = self.root / "group-state"
        result = self.run_cli("model-group-cpu", "--run-id", "missing-group", "--root", str(self.root / "missing-assets"),
                              "--state-root", str(state), "--task", str(repo / "configs/build-engineering-v1.json"),
                              "--feedback-policy", str(repo / "configs/coordinator-feedback-engineering.json"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stderr)["error"]["code"], "CPU_TRAINING_UNAVAILABLE")
        self.assertFalse(state.exists())

    def test_lora_missing_assets_does_not_initialize_a_fake_trainer(self):
        repo = Path(__file__).resolve().parents[1]
        state = self.root / "lora-state"
        result = self.run_cli("lora-group-cpu", "--run-id", "missing-lora", "--root", str(self.root / "missing-assets"),
                              "--state-root", str(state), "--task", str(repo / "configs/build-engineering-v1.json"),
                              "--lora-config", str(repo / "configs/lora-engineering-v1.json"),
                              "--feedback-policy", str(repo / "configs/coordinator-feedback-engineering.json"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stderr)["error"]["code"], "CPU_TRAINING_UNAVAILABLE")
        self.assertFalse(state.exists())

    def test_budget_read_missing_ledger_does_not_create_usage(self):
        repo = Path(__file__).resolve().parents[1]
        ledger = self.root / "missing-budget.sqlite3"
        request = self.write_json("budget-read.json", {"schema_version": 1, "id": "read", "method": "status", "params": {}})
        result = self.run_cli("budget-call", request, "--ledger", str(ledger), "--plan", str(repo / "configs/training-plan-v1.json"))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(ledger.exists())

    def test_preflight_missing_assets_reports_health_failure_without_creating_resources(self):
        repo = Path(__file__).resolve().parents[1]
        missing = self.root / "unprepared-native"
        result = self.run_cli("training-preflight", "--root", str(missing), "--plan", str(repo / "configs/training-plan-v1.json"))
        self.assertEqual(result.returncode, 2, result.stderr)
        status = json.loads(result.stdout)
        self.assertFalse(status["ok"])
        self.assertFalse(status["checks"]["locked_native_assets"]["passed"])
        self.assertFalse(status["formal_training"]["ready"])
        self.assertFalse(missing.exists())

    def test_budget_cli_is_marked_synthetic_rejects_launch_and_does_not_import_torch(self):
        repo = Path(__file__).resolve().parents[1]
        ledger = self.root / "contract-budget.sqlite3"
        plan = str(repo / "configs/training-plan-v1.json")
        request = self.write_json("budget-status.json", {"schema_version": 1, "id": "create", "method": "status", "params": {}})
        args = ["budget-call", request, "--ledger", str(ledger), "--plan", plan, "--source", "synthetic_contract_test", "--role", "trainer", "--create"]
        script = "import sys; from ygo_kito.cli import main; assert main(" + repr(args) + ") == 0; assert 'torch' not in sys.modules"
        created = subprocess.run([sys.executable, "-c", script], cwd=self.root, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(created.returncode, 0, created.stderr)
        status = json.loads(created.stdout)["result"]
        self.assertEqual(status["source"], "synthetic_contract_test")
        self.assertFalse(status["paid_launch_enabled"])
        denied = self.write_json("budget-denied.json", {"schema_version": 1, "id": "no-launch", "method": "training.start", "params": {}})
        output = self.run_cli("budget-call", denied, "--ledger", str(ledger), "--plan", plan, "--source", "synthetic_contract_test")
        self.assertEqual(output.returncode, 2, output.stderr)
        self.assertEqual(json.loads(output.stdout)["error"]["code"], "PERMISSION_DENIED")

    def test_cli_initialization_import_and_lookup_work_from_another_directory(self):
        for args in (("db-init",), ("db-init",), ("cards-import", self.write_json("cards.json", dataset())), ("card-show", "1")):
            output = self.run_cli(*args)
            self.assertEqual(output.returncode, 0, output.stderr)
            payload = json.loads(output.stdout)
        self.assertEqual(payload["card"]["names"]["zh"], "测试卡1")
        self.assertEqual(payload["annotations"][0]["layer"], "fact")

    def test_action_and_request_checks_are_explicitly_contract_only(self):
        request_path = self.write_json("request.json", request())
        selection_path = self.write_json("selection.json", selection())
        for args in (("request-check", request_path), ("action-check", request_path, selection_path)):
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["validation"], "contract_only")
            self.assertFalse(output["rules_verified"])
            self.assertNotIn("card_id", result.stdout)
        bad = selection()
        bad["decision_id"] = "expired"
        failure = self.run_cli("action-check", request_path, self.write_json("expired.json", bad))
        self.assertEqual(failure.returncode, 2)
        self.assertEqual(json.loads(failure.stderr)["error"]["code"], "INVALID_INPUT")

    def test_unimplemented_engine_returns_nonzero_without_creating_artifacts(self):
        result = self.run_cli("duel-run")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(json.loads(result.stderr)["error"]["code"], "ENGINE_NOT_IMPLEMENTED")
        self.assertFalse((self.root / "local").exists())

    def test_bad_files_and_unknown_card_have_machine_readable_errors(self):
        self.assertEqual(self.run_cli("db-init").returncode, 0)
        for args in (("cards-import", "missing.json"), ("card-show", "999"), ("card-show", str(2**63))):
            output = self.run_cli(*args)
            self.assertEqual(output.returncode, 2)
            self.assertFalse(json.loads(output.stderr)["ok"])

    def test_duplicate_json_keys_nonfinite_and_parser_errors_do_not_echo_contents(self):
        for content in ('{"schema_version":1,"schema_version":1}', '{"sensitive":"private-fragment",', '{"x":NaN}'):
            path = self.root / "bad.json"
            path.write_text(content, encoding="utf-8")
            result = self.run_cli("request-check", str(path))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stderr)["error"]["code"], "INVALID_INPUT")
            self.assertNotIn("private-fragment", result.stderr)

    def test_invalid_config_rejects_gpu_unknown_backend_and_unknown_options(self):
        original = self.config.read_text(encoding="utf-8")
        variants = (
            original.replace('device = "cpu"', 'device = "cuda"'),
            original.replace('backend = "unconfigured"', 'backend = "pretend-real"'),
            original.replace('schema_version = 1', 'schema_version = true'),
            original + '\napi_key = "not-a-real-secret"\n',
        )
        for content in variants:
            with self.subTest(content=content):
                self.config.write_text(content, encoding="utf-8")
                with self.assertRaises(ContractError):
                    load_config(self.config)
