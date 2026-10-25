"""Inert exact-overlay/CLI/process contracts; no third-party code execution."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace
import unittest

from tests import test_bot_deployment as source_fixtures
from ygo_kito import bot_overlay as overlay
from ygo_kito.bot_build_audit import execute_plan, file_sha, prepare_overlay_plan
from ygo_kito.contracts import Versions
from ygo_kito.validation import ContractError


class BotOverlayTests(unittest.TestCase):
    def setUp(self):
        fixture = source_fixtures.BotDeploymentTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture, self.root, self.roots, self.lock = fixture, fixture.root, fixture.roots, fixture.lock
        for sid, prefix in (("pure", ""), ("library", "libWindbot/")):
            old = prefix + "Game/AI/Decks/AlphaExecutor.cs"
            (self.roots[sid] / old).unlink()
            source = next(s for s in self.lock["sources"] if s["source_id"] == sid)
            source["files"] = [f for f in source["files"] if f["path"] != old]
            assignment = overlay.PURE_ASSIGNMENT if sid == "pure" else overlay.LIBRARY_ASSIGNMENT
            fixture.write(sid, prefix + overlay.TARGET,
                b'[Deck("Monarch506", "AI_Alpha")] class Monarch506Executor : DefaultExecutor {\n' + assignment + b'\n}\n')
        self.destination = self.root / "separate-variant"

    def prepare(self):
        return overlay.prepare_overlay(self.lock, self.roots, self.destination)

    def test_complete_exact_overlay_retains_both_notices_and_original_roots(self):
        original = (self.roots["pure"] / overlay.TARGET).read_bytes()
        receipt = self.prepare()
        self.assertFalse(receipt["runtime_loaded"])
        self.assertEqual((self.roots["pure"] / overlay.TARGET).read_bytes(), original)
        self.assertEqual((self.destination / overlay.TARGET).read_bytes(), (self.roots["library"] / overlay.DONOR).read_bytes())
        self.assertTrue((self.destination / "LICENSE").is_file())
        self.assertTrue((self.destination / overlay.NOTICE).is_file())
        self.assertEqual(overlay.verify_overlay(self.lock, self.destination)["variant_sha256"], receipt["variant_sha256"])
        with self.assertRaises(ContractError): self.prepare()
        with self.assertRaises(ContractError): overlay.prepare_overlay(self.lock, self.roots, self.roots["pure"] / "nested")

    def test_bounded_bundle_is_deterministic_verifiable_and_installable(self):
        self.prepare()
        a, b = self.root / "a.tar.gz", self.root / "b.tar.gz"
        overlay.bundle_overlay(self.lock, self.destination, a)
        overlay.bundle_overlay(self.lock, self.destination, b)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertTrue(overlay.verify_overlay_bundle(self.lock, a)["verified"])
        installed = self.root / "installed"
        overlay.install_overlay_bundle(self.lock, a, installed)
        self.assertEqual(overlay.verify_overlay(self.lock, installed)["variant_sha256"], overlay.verify_overlay(self.lock, self.destination)["variant_sha256"])

    def test_manifest_source_and_extra_file_changes_are_rejected(self):
        self.prepare()
        path = self.destination / overlay.TARGET
        original = path.read_bytes(); path.write_bytes(original + b" ")
        with self.assertRaises(ContractError): overlay.verify_overlay(self.lock, self.destination)
        path.write_bytes(original)
        extra = self.destination / "SecretExecutor.cs"; extra.write_text("inert")
        with self.assertRaises(ContractError): overlay.verify_overlay(self.lock, self.destination)
        extra.unlink()
        manifest = self.destination / overlay.MANIFEST
        data = json.loads(manifest.read_text()); data["donor"]["commit"] = "0" * 40
        manifest.write_text(json.dumps(data))
        with self.assertRaises(ContractError): overlay.verify_overlay(self.lock, self.destination)

    def test_archive_link_duplicate_and_wrong_bytes_are_rejected(self):
        for kind in ("link", "duplicate", "bytes"):
            with self.subTest(kind=kind):
                archive = self.root / (kind + ".tar.gz")
                with tarfile.open(archive, "w:gz") as handle:
                    row = tarfile.TarInfo("LICENSE")
                    if kind == "link": row.type = tarfile.SYMTYPE; row.linkname = "../outside"; handle.addfile(row)
                    else:
                        raw = b"wrong bytes"; row.size = len(raw); handle.addfile(row, io.BytesIO(raw))
                        if kind == "duplicate": handle.addfile(row, io.BytesIO(raw))
                with self.assertRaises(ContractError): overlay.verify_overlay_bundle(self.lock, archive)

    def test_unreviewed_extra_source_difference_fails_before_install(self):
        self.fixture.write("library", overlay.DONOR, (self.roots["library"] / overlay.DONOR).read_bytes() + b"// another change")
        with self.assertRaisesRegex(ContractError, "differ beyond"): self.prepare()
        self.assertFalse(self.destination.exists())

    def test_full_variant_plan_and_injected_execution_keep_distinct_identity(self):
        self.prepare()
        cards = self.root / "inert-catalog"; cards.write_bytes(b"Never loaded as SQLite")
        plan = prepare_overlay_plan(self.lock, self.roots, self.destination, cards, file_sha(cards), self.root / "build-variant")
        self.assertEqual(plan["kind"], "complete-desktop-bot-overlay-build-plan")
        self.assertEqual(plan["bots"][0]["full_type"], "WindBot.Game.AI.Decks.Monarch506Executor")
        self.assertEqual(plan["variant"]["donor"]["commit"], overlay.sources.PINS["library"][1])
        self.assertIn(str(self.destination / overlay.NOTICE), [r["path"] for r in plan["resources"]])
        tools = {}
        for name in ("mono", "compiler", "msbuild"):
            p = self.root / (name + "-inert"); p.write_bytes(b"Not a tool; injected only"); p.chmod(0o700); tools[name] = p
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            self.assertEqual(kwargs["cwd"], str(self.destination))
            if len(calls) == 1:
                p = Path(plan["assembly_path"]); p.parent.mkdir(parents=True); p.write_bytes(b"inert assembly")
            if len(calls) == 3:
                audit = {"schema_version":1,"assembly_loaded":True,"constructor_execution_requested":True,
                    "all_expected_executors_matched":True,"all_resources_verified":True,"error":None,
                    "assembly_sha256":file_sha(plan["assembly_path"]),"bots":[{"full_type":plan["bots"][0]["full_type"],"deck_name":"Monarch506","metadata_matched":True,"resource_verified":True,"constructed":True,"error":None}],
                    "normal_duel_verified":False,"strength_verified":False,"history_verified":False,"training_connected":False}
                Path(argv[-2]).write_text(json.dumps(audit))
            return SimpleNamespace(returncode=0)
        receipt = execute_plan(self.lock, plan, **tools, runner=runner)
        self.assertEqual(receipt["kind"], "complete-desktop-bot-overlay-build-audit")
        self.assertEqual(receipt["variant"], plan["variant"])
        self.assertFalse(receipt["runtime_loaded"])
        self.assertEqual(receipt["evidence_source"], "injected_process_contract_check")
        # A synthetic wire-format example of a *future* actual audit exercises
        # the registry validator without entering its real process factory.
        # These edited fixture bytes are not an actual .NET audit or proof.
        registry = overlay.sources.BotSourceRegistry(self.lock, self.root)
        audit_path = self.root / "synthetic-audit-validator-input.json"
        fixture_receipt = deepcopy(receipt)
        fixture_receipt.update(evidence_source="actual_complete_assembly_audit", runtime_loaded=True, constructors_verified=True)
        audit_path.write_text(json.dumps(fixture_receipt))
        kwargs = {"source_id":"pure", "native_root":self.root / "unopened-native", "workspace":self.root,
            "profile":{"schema_version":1,"name":"inert validator fixture","decks":[[123],[123]]},
            "versions":Versions("fixture-core","fixture-scripts",file_sha(cards),"fixture-protocol","fixture-pool","fixture-banlist"),
            "environment_id":"fixture-period", "opponent_id":"fixture-monarch", "source":"engineering_fixture",
            "build_audit_path":audit_path,"build_audit_sha256":file_sha(audit_path),"mono":tools["mono"],
            "variant_root":self.destination,"session_seconds":30}
        adapter = registry.training_adapter("Monarch506Executor", **kwargs)
        self.assertTrue(adapter.binding["driver_version"].startswith("windbot-pure-overlay-"))
        self.assertFalse(adapter.binding["strength_qualified"])
        reprofile = deepcopy(kwargs["profile"]); reprofile["name"] = "another actor fixture"
        rebound = adapter.rebind(reprofile)
        self.assertEqual(rebound.binding["driver_version"], adapter.binding["driver_version"])
        changed_limit = registry.training_adapter("Monarch506Executor", **{**kwargs,"session_seconds":31})
        self.assertNotEqual(changed_limit.binding["registered_record_sha256"], adapter.binding["registered_record_sha256"])
        without_variant = {k:v for k,v in kwargs.items() if k != "variant_root"}
        with self.assertRaises(ContractError): registry.training_adapter("Monarch506Executor", **without_variant)
        for bad in (0,301,True,float("nan")):
            with self.subTest(limit=bad), self.assertRaises(ContractError):
                registry.training_adapter("Monarch506Executor", **{**kwargs,"session_seconds":bad})
        changed = self.destination / overlay.TARGET
        changed.write_bytes(changed.read_bytes() + b" ")
        with self.assertRaises(ContractError): adapter.assert_runtime(kwargs["native_root"],kwargs["profile"],0)


if __name__ == "__main__": unittest.main()
