"""CPU contract checks with inert sources/tools and an injected process runner.

No C# compiler/Mono, SQLite DLL or third-party constructor is executed here.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import unittest

from tests import test_bot_deployment as source_fixtures
from ygo_kito.bot_build_audit import BuildAuditError, execute_plan, file_sha, prepare_plan, validate_audit_result
from ygo_kito.validation import ContractError


class BotBuildAuditTests(unittest.TestCase):
    def setUp(self):
        fixture = source_fixtures.BotDeploymentTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture, self.root, self.roots, self.lock = fixture, fixture.root, fixture.roots, fixture.lock
        self.cards = self.root / "fixture-catalog-not-real-cdb"
        self.cards.write_bytes(b"Explicit inert catalog fixture; never passed to SQLite or .NET.")
        self.plan = prepare_plan(self.lock, self.roots, "ice", self.cards, file_sha(self.cards), self.root / "build")

    def result(self, *, construct=True):
        return {"schema_version": 1, "assembly_loaded": True, "constructor_execution_requested": construct,
            "all_expected_executors_matched": True, "all_resources_verified": True,
            "assembly_sha256": file_sha(self.plan["assembly_path"]), "error": None,
            "bots": [{"full_type": b["full_type"], "deck_name": b["deck_name"], "metadata_matched": True,
                      "resource_verified": construct, "constructed": construct, "error": None} for b in self.plan["bots"]],
            "normal_duel_verified": False, "strength_verified": False, "history_verified": False, "training_connected": False}

    def tools(self):
        result = {}
        for name in ("mono", "compiler", "msbuild"):
            path = self.root / (name + "-inert-never-executed")
            path.write_bytes(b"Not an executable tool. Injected runner only.")
            path.chmod(0o700)
            result[name] = path
        return result

    def test_full_plan_preserves_exact_type_deck_resources_and_all_origins(self):
        self.assertEqual(len(self.plan["bots"]), 1)
        row = self.plan["bots"][0]
        self.assertEqual(row["full_type"], "WindBot.Game.AI.Decks.AlphaExecutor")
        self.assertEqual(row["level"], "Normal")
        self.assertEqual(row["selected_deck_source_id"], "ice")
        self.assertEqual(row["selected_deck"]["sha256"], file_sha(row["selected_deck"]["path"]))
        self.assertFalse(self.plan["executed"])
        self.assertFalse(self.plan["runtime_loaded"])

    def test_missing_tools_do_not_create_outputs_or_invoke_runner(self):
        calls = []
        with self.assertRaisesRegex(ContractError, "unavailable; no build"):
            execute_plan(self.lock, self.plan, mono="/absent/mono", compiler="/absent/mcs", msbuild="/absent/msbuild",
                         runner=lambda *a, **kw: calls.append(a))
        self.assertEqual(calls, [])
        self.assertFalse(Path(self.plan["output_directory"]).exists())

    def test_preflight_failure_reports_not_executed_steps_and_no_private_payload(self):
        with self.assertRaises(BuildAuditError) as caught:
            execute_plan(self.lock, self.plan, mono="/absent/mono", compiler="/absent/mcs", msbuild="/absent/msbuild")
        report = caught.exception.report
        self.assertEqual((report["stage"], report["outcome"]), ("preflight", "not_executed"))
        self.assertEqual(report["steps"], [])
        self.assertFalse(report["execution_attempted"])
        self.assertEqual(len(report["not_executed_steps"]), 3)
        self.assertNotIn(self.cards.read_text(), json.dumps(report))

    def test_injected_timeout_is_structured_without_claiming_process_reaped(self):
        def runner(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"], output=b"PRIVATE_OUTPUT_MUST_NOT_BE_COPIED")
        with self.assertRaises(BuildAuditError) as caught:
            execute_plan(self.lock, self.plan, **self.tools(), runner=runner, timeout=0.01)
        report = caught.exception.report
        self.assertEqual((report["stage"], report["outcome"]), ("desktop_build", "timeout"))
        self.assertEqual(report["evidence_source"], "injected_process_contract_check")
        row = report["steps"][0]
        self.assertIsNone(row["reaped"])
        self.assertTrue(row["process_started"])
        self.assertEqual(row["timeout_seconds"], 0.01)
        self.assertEqual(row["log_sha256"], file_sha(row["log_path"]))
        self.assertFalse(report["runtime_loaded"])
        self.assertNotIn("PRIVATE_OUTPUT", json.dumps(report))

    def test_real_harmless_false_process_is_reaped_and_never_loads_csharp(self):
        # Executes the existing OS false utility, not source/toolchain fixtures.
        tool = Path(shutil.which("false")).resolve()
        with self.assertRaises(BuildAuditError) as caught:
            execute_plan(self.lock, self.plan, mono=tool, compiler=tool, msbuild=tool)
        report = caught.exception.report
        self.assertEqual(report["outcome"], "nonzero_exit")
        self.assertTrue(report["steps"][0]["reaped"])
        self.assertEqual(report["steps"][0]["returncode"], 1)
        self.assertFalse(report["runtime_loaded"])

    def test_spawn_failure_and_missing_assembly_stop_before_reflection(self):
        def missing(argv, **kwargs):
            raise FileNotFoundError("fixture process not spawned")
        with self.assertRaises(BuildAuditError) as caught:
            execute_plan(self.lock, self.plan, **self.tools(), runner=missing)
        self.assertFalse(caught.exception.report["steps"][0]["process_started"])
        # New output directory: the previous failed check retains its own log.
        self.plan = prepare_plan(self.lock, self.roots, "ice", self.cards, file_sha(self.cards), self.root / "missing-assembly")
        with self.assertRaises(BuildAuditError) as caught:
            execute_plan(self.lock, self.plan, **self.tools(), runner=lambda *a, **kw: SimpleNamespace(returncode=0))
        report = caught.exception.report
        self.assertEqual((report["stage"], report["outcome"]), ("assembly_input", "artifact_unavailable"))
        self.assertEqual(len(report["steps"]), 2)
        self.assertIn("assembly_audit", report["not_executed_steps"])

    def test_malformed_and_incomplete_reflection_outputs_preserve_completed_steps(self):
        for variant in ("missing", "json", "constructor"):
            with self.subTest(variant=variant):
                self.plan = prepare_plan(self.lock, self.roots, "ice", self.cards, file_sha(self.cards), self.root / variant)
                calls = []
                def runner(argv, **kwargs):
                    calls.append(argv)
                    if len(calls) == 1:
                        p = Path(self.plan["assembly_path"]); p.parent.mkdir(parents=True); p.write_bytes(b"inert")
                    if len(calls) == 3 and variant != "missing":
                        raw = "{not JSON"
                        if variant == "constructor":
                            audit = self.result(); audit["bots"][0]["constructed"] = False; raw = json.dumps(audit)
                        Path(argv[-2]).write_text(raw)
                    return SimpleNamespace(returncode=0)
                with self.assertRaises(BuildAuditError) as caught:
                    execute_plan(self.lock, self.plan, **self.tools(), runner=runner)
                report = caught.exception.report
                self.assertEqual((report["stage"], report["outcome"]), ("audit_output_validation", "audit_rejected"))
                self.assertEqual(len(report["steps"]), 3)
                self.assertTrue(all(s["returncode"] == 0 for s in report["steps"]))
                self.assertFalse(report["runtime_loaded"])

    def test_cli_input_failure_writes_structured_report_and_never_overwrites_it(self):
        script = Path(__file__).resolve().parents[1] / "scripts/bot_build_check.py"
        target = self.root / "cli-failure.json"
        argv = [sys.executable, str(script), "--roots", str(self.root / "missing-roots.json"),
            "--source-id", "ice", "--cards-cdb", str(self.cards), "--cards-sha256", file_sha(self.cards),
            "--build-directory", str(self.root / "not-created"), "--report", str(target)]
        result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 2)
        report = json.loads(target.read_text())
        self.assertEqual((report["stage"], report["outcome"]), ("prepare", "not_executed"))
        self.assertFalse(report["execution_attempted"])
        self.assertFalse((self.root / "not-created").exists())
        raw = target.read_bytes()
        retry = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        self.assertEqual(retry.returncode, 2)
        self.assertEqual(json.loads(retry.stdout)["stage"], "report_setup")
        self.assertEqual(target.read_bytes(), raw)

    def test_disappearing_log_preserves_completed_build_and_audit_steps(self):
        for fail_at in (1,3):
            with self.subTest(fail_at=fail_at):
                self.plan = prepare_plan(self.lock, self.roots, "ice", self.cards, file_sha(self.cards), self.root / ("lost-log-" + str(fail_at)))
                calls = []
                def runner(argv, **kwargs):
                    calls.append(argv)
                    if len(calls) == 1:
                        p = Path(self.plan["assembly_path"]); p.parent.mkdir(parents=True); p.write_bytes(b"inert")
                    if len(calls) == fail_at:
                        Path(kwargs["stdout"].name).unlink()
                    return SimpleNamespace(returncode=0)
                with self.assertRaises(BuildAuditError) as caught:
                    execute_plan(self.lock, self.plan, **self.tools(), runner=runner)
                report = caught.exception.report
                self.assertEqual(report["stage"], "desktop_build" if fail_at == 1 else "assembly_audit")
                self.assertEqual(report["outcome"], "log_unavailable")
                self.assertEqual(len(report["steps"]), fail_at)
                row = report["steps"][-1]
                self.assertEqual((row["outcome"], row["returncode"]), ("completed", 0))
                self.assertTrue(row["process_started"])
                self.assertIsNone(row["log_sha256"])
                self.assertEqual(row["log_error"], "FileNotFoundError")
                self.assertEqual(report["evidence_source"], "injected_process_contract_check")
                self.assertFalse(report["runtime_loaded"])

    def test_disappearing_timeout_log_keeps_timeout_and_started_state(self):
        def runner(argv, **kwargs):
            Path(kwargs["stdout"].name).unlink()
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        with self.assertRaises(BuildAuditError) as caught:
            execute_plan(self.lock, self.plan, **self.tools(), runner=runner)
        report = caught.exception.report
        self.assertEqual((report["stage"], report["outcome"]), ("desktop_build", "timeout"))
        self.assertTrue(report["execution_attempted"])
        row = report["steps"][0]
        self.assertEqual(row["outcome"], "timeout")
        self.assertTrue(row["process_started"])
        self.assertEqual(row["log_error"], "FileNotFoundError")
        self.assertIsNone(row["log_sha256"])

    def test_changed_cards_output_within_source_and_android_plan_are_rejected(self):
        with self.assertRaises(ContractError):
            prepare_plan(self.lock, self.roots, "ice", self.cards, "0" * 64, self.root / "out")
        with self.assertRaisesRegex(ContractError, "immutable"):
            prepare_plan(self.lock, self.roots, "ice", self.cards, file_sha(self.cards), self.roots["ice"] / "out")
        with self.assertRaisesRegex(ContractError, "Android/library"):
            prepare_plan(self.lock, self.roots, "library", self.cards, file_sha(self.cards), self.root / "out")

    def test_injected_complete_build_contract_is_never_runtime_evidence(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            self.assertEqual(kwargs["cwd"], self.plan["source_root"])
            self.assertEqual(kwargs["timeout"], 180)
            self.assertFalse(kwargs["check"])
            if len(calls) == 1:
                self.assertIn("/p:ExternalPolicyOnly=false", argv)
                path = Path(self.plan["assembly_path"])
                path.parent.mkdir(parents=True)
                path.write_bytes(b"Not a compiled assembly; explicit fixture.")
            elif len(calls) == 2:
                self.assertIn("-r:System.Runtime.Serialization", argv)
            else:
                self.assertEqual(argv[-1], "--construct")
                Path(argv[-2]).write_text(json.dumps(self.result()))
            return SimpleNamespace(returncode=0)
        receipt = execute_plan(self.lock, self.plan, **self.tools(), runner=runner)
        self.assertEqual(len(calls), 3)
        self.assertEqual(receipt["evidence_source"], "injected_process_contract_check")
        self.assertFalse(receipt["runtime_loaded"])
        self.assertFalse(receipt["constructors_verified"])
        self.assertFalse(receipt["training_connected"])
        self.assertEqual(set(receipt["toolchain"]), {"mono", "compiler", "msbuild"})

    def test_audit_rejects_missing_extra_type_failed_constructor_hash_and_false_qualification(self):
        assembly = Path(self.plan["assembly_path"])
        assembly.parent.mkdir(parents=True)
        assembly.write_bytes(b"Inert assembly fixture.")
        bads = []
        for key, value in (("all_resources_verified", False), ("assembly_sha256", "0" * 64), ("normal_duel_verified", True)):
            d = self.result(); d[key] = value; bads.append(d)
        for key, value in (("constructed", False), ("metadata_matched", False), ("error", "Fixture constructor rejected")):
            d = self.result(); d["bots"][0][key] = value; bads.append(d)
        d = self.result(); d["bots"] = []; bads.append(d)
        d = self.result(); d["bots"].append(deepcopy(d["bots"][0])); bads.append(d)
        for d in bads:
            with self.subTest(audit=d), self.assertRaises(ContractError): validate_audit_result(self.plan, d, construct=True)
        self.assertEqual(validate_audit_result(self.plan, self.result(), construct=True)["bots"][0]["deck_name"], "Alpha")


if __name__ == "__main__":
    unittest.main()
