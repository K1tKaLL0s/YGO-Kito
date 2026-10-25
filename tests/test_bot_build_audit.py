"""CPU contract checks with inert sources/tools and an injected process runner.

No C# compiler/Mono, SQLite DLL or third-party constructor is executed here.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from tests import test_bot_deployment as source_fixtures
from ygo_kito.bot_build_audit import execute_plan, file_sha, prepare_plan, validate_audit_result
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
