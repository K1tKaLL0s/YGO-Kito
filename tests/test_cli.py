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
