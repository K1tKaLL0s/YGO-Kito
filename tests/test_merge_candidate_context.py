"""Offline source provenance and byte audits; no native code is imported/run."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.check_merge_candidate import (DP_HASHES, LIMIT_HOOK, LIMIT_READ,
    approved_period_hook, audit_native_pair, checkout_context)
from scripts.deployment_prepare import MANIFEST, REQUIRED_FILES, fingerprint
from ygo_kito.validation import ContractError

ROOT=Path(__file__).resolve().parents[1]


class MergeCandidateSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)/"source"
        self.root.mkdir()
        self.names=REQUIRED_FILES|set(DP_HASHES)
        for name in self.names:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes((ROOT/name).read_bytes())
        self.write_manifest()

    def write_manifest(self):
        manifest={"schema_version":1,"kind":"source-only-no-runtime-data","source_commit":"a"*40,
            "files":{name:{"sha256":fingerprint((self.root/name).read_bytes()),"bytes":(self.root/name).stat().st_size}
                     for name in self.names},"runtime_assets_included":False,"checkpoints_included":False,
            "credentials_read":False,"training_started":False}
        (self.root/MANIFEST).write_text(json.dumps(manifest),encoding="utf-8")

    def git(self,folder,*args):
        return subprocess.check_output(["git","-c","core.hooksPath=/dev/null","-c","commit.gpgsign=false",
            "-c","user.name=Fixture","-c","user.email=fixture@example.invalid",*args],cwd=folder,text=True).strip()

    def test_verified_archive_is_not_reported_as_local_git_evidence(self):
        context=checkout_context(self.root)
        self.assertEqual(context,{"checkout_kind":"source_archive","tested_head":None,"source_archive_commit":"a"*40})
        pair=audit_native_pair(self.root,context)
        self.assertTrue(pair["src/ygo_kito/native_response_guard.py"]["matches_pinned_dp_sha256"])
        self.assertTrue(pair["src/ygo_kito/native.py"]["matches_reviewed_period_hook"])
        self.assertTrue(all(item["matches_dp_commit"] is None for item in pair.values()))

    def test_parent_git_does_not_supply_archive_head(self):
        parent=self.root.parent
        self.git(parent,"init","--quiet","-b","fixture-parent")
        self.git(parent,"commit","--quiet","--allow-empty","-m","unrelated parent Git fixture")
        context=checkout_context(self.root)
        self.assertEqual(context["checkout_kind"],"source_archive")
        self.assertIsNone(context["tested_head"])
        self.assertEqual(context["source_archive_commit"],"a"*40)

    def test_actual_git_root_keeps_real_git_head(self):
        self.git(self.root,"init","--quiet","-b","fixture-work")
        self.git(self.root,"commit","--quiet","--allow-empty","-m","Git identity fixture")
        context=checkout_context(self.root)
        self.assertEqual(context["checkout_kind"],"git")
        self.assertEqual(context["tested_head"],self.git(self.root,"rev-parse","HEAD"))
        self.assertIsNone(context["source_archive_commit"])

    def test_missing_manifest_changed_or_added_source_is_rejected(self):
        (self.root/"src/ygo_kito/cli.py").write_text("altered source",encoding="utf-8")
        with self.assertRaisesRegex(ContractError,"checksum"):
            checkout_context(self.root)
        self.write_manifest()
        extra=self.root/"src/ygo_kito/unmanifested.py";extra.write_text("# extra code",encoding="utf-8")
        with self.assertRaisesRegex(ContractError,"membership"):
            checkout_context(self.root)
        extra.unlink();(self.root/MANIFEST).unlink()
        with self.assertRaisesRegex(ContractError,"manifest"):
            checkout_context(self.root)

    def test_original_and_only_the_exact_approved_hook_pass_pinned_audit(self):
        name="src/ygo_kito/native.py"
        current=(self.root/name).read_bytes()
        original=current.decode("utf-8").replace(LIMIT_HOOK,"").replace('limits = self._deck_limits()',LIMIT_READ).encode("utf-8")
        self.assertEqual(fingerprint(original),DP_HASHES[name])
        self.assertEqual(approved_period_hook(original),current)
        (self.root/name).write_bytes(original);self.write_manifest()
        pair=audit_native_pair(self.root,checkout_context(self.root))
        self.assertTrue(pair[name]["matches_pinned_dp_sha256"])
        self.assertFalse(pair[name]["matches_reviewed_period_hook"])

    def test_archive_native_or_guard_change_cannot_hide_behind_updated_manifest(self):
        for name in DP_HASHES:
            with self.subTest(file=name):
                original=(self.root/name).read_bytes()
                (self.root/name).write_bytes(original+b"\n# unapproved native/guard edit fixture\n")
                self.write_manifest()
                context=checkout_context(self.root)
                with self.assertRaisesRegex(SystemExit,"differs"):
                    audit_native_pair(self.root,context)
                (self.root/name).write_bytes(original);self.write_manifest()


if __name__=="__main__":
    unittest.main()
