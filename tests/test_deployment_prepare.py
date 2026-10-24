"""Source packet and existing-host deployment fixtures; no cloud/native/training."""
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts.deployment_prepare import (MANIFEST, REQUIRED_FILES, fingerprint, hardware,
    pinned_dependencies_match, prepare_bundle, preflight, verify_bundle)
from ygo_kito.engine import EngineUnavailable
from ygo_kito.agent_monitor import RunReporter
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]


class DeploymentPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "checkout"
        self.root.mkdir()
        self.git("init", "--quiet", "-b", "fixture-work")
        for name in REQUIRED_FILES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Explicit source bundle fixture\n", encoding="utf-8")
        lock = self.root / "requirements/ci-cpu.txt"
        lock.write_text((ROOT / "requirements/ci-cpu.txt").read_text(), encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "inert source fixture")

    def git(self, *args):
        return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
            "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *args],
            cwd=self.root, text=True).strip()

    def config(self):
        return {"schema_version": 1, "expected_source_commit": self.git("rev-parse", "HEAD"),
            "dependency_lock": {"path": "requirements/ci-cpu.txt",
                "sha256": fingerprint((self.root / "requirements/ci-cpu.txt").read_bytes()),
                "python": "3.12.14", "torch": "2.9.1+cpu"}, "runtime_device": "cpu",
            "minimum_hardware": {"cpu_cores": 2, "memory_bytes": 4096, "disk_free_bytes": 4096,
                                 "cuda_devices": 0, "cuda_device_memory_bytes": 0},
            "native_root": ".cache", "log_directory": ".cache/logs",
            "resume": {"mode": "fresh", "state_root": None, "run_id": None, "checkpoint_id": None},
            "evidence": []}

    def host(self):
        return {"python": "3.12.14", "torch": "2.9.1+cpu", "available_cpu_cores": 4,
            "memory_limit_bytes": 8192, "disk_free_bytes": 8192, "cuda_available": False,
            "visible_cuda_devices": 0, "cuda_device_memory_bytes": [], "cuda_build": None}

    def test_bundle_is_reproducible_and_omits_runtime_and_private_paths(self):
        for name in (".cache/private.weights", "docs/reports/private.json", "private-decks/user.json"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("not source", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "excluded fixture files")
        first, second = Path(self.temporary.name) / "a.tar.gz", Path(self.temporary.name) / "b.tar.gz"
        result = prepare_bundle(self.root, first)
        prepare_bundle(self.root, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertFalse(result["runtime_assets_included"])
        verified = verify_bundle(first)
        self.assertTrue(verified["verified"])
        self.assertFalse(verified["extracted"])
        with tarfile.open(first) as archive:
            self.assertEqual(set(archive.getnames()), REQUIRED_FILES | {MANIFEST})

    def test_dirty_source_or_symlink_is_not_packaged(self):
        output = Path(self.temporary.name) / "packet.tar.gz"
        source = self.root / "src/ygo_kito/cli.py"
        source.write_text("modified fixture", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "commit"):
            prepare_bundle(self.root, output)
        self.git("checkout", "--", "src/ygo_kito/cli.py")
        source.unlink()
        source.symlink_to(self.root / "README.md")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "source symlink fixture")
        with self.assertRaisesRegex(ContractError, "regular"):
            prepare_bundle(self.root, output)

    def test_archive_traversal_and_links_are_rejected_without_extraction(self):
        for member_name, kind in (("../outside", tarfile.REGTYPE), ("src/link.py", tarfile.SYMTYPE)):
            path = Path(self.temporary.name) / ("link.tar.gz" if kind == tarfile.SYMTYPE else "path.tar.gz")
            with tarfile.open(path, "w:gz") as archive:
                member = tarfile.TarInfo(member_name)
                member.type, member.linkname = kind, "../outside"
                archive.addfile(member)
            with self.assertRaises(ContractError):
                verify_bundle(path)
        self.assertFalse((Path(self.temporary.name) / "outside").exists())

    def test_modified_source_member_is_rejected(self):
        first, changed = Path(self.temporary.name) / "a.tar.gz", Path(self.temporary.name) / "changed.tar.gz"
        prepare_bundle(self.root, first)
        with tarfile.open(first) as source, tarfile.open(changed, "w:gz") as target:
            for member in source:
                blob = source.extractfile(member).read()
                if member.name == "README.md":
                    blob += b"tampered"
                    member.size = len(blob)
                target.addfile(member, io.BytesIO(blob))
        with self.assertRaisesRegex(ContractError, "checksum"):
            verify_bundle(changed)

    def test_manifest_checkout_inside_parent_git_uses_its_own_files(self):
        packet = Path(self.temporary.name) / "source.tar.gz"
        prepare_bundle(self.root, packet)
        unpacked = self.root / ".cache/extracted-fixture"
        unpacked.mkdir(parents=True)
        # The package implementation never extracts. This test writes already
        # verified regular bytes to model a separate user's source installation.
        with tarfile.open(packet) as archive:
            for member in archive:
                target = unpacked / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
        config = self.config()
        with patch("scripts.deployment_prepare.verify_resources", return_value={"fixture": True}):
            result = preflight(unpacked, config, observed_hardware=self.host())
            self.assertTrue(result["checks"]["source_commit_and_clean_files"])
            (unpacked / "src/ygo_kito/cli.py").write_text("altered package", encoding="utf-8")
            changed = preflight(unpacked, config, observed_hardware=self.host())
            self.assertFalse(changed["checks"]["source_commit_and_clean_files"])

    def test_cpu_static_checks_are_not_training_readiness(self):
        with patch("scripts.deployment_prepare.verify_resources", return_value={"fixture": "hash only"}):
            result = preflight(self.root, self.config(), observed_hardware=self.host())
        self.assertTrue(result["deployment_checks_passed"], result["blockers"])
        self.assertEqual(result["hardware_source"], "injected_engineering_fixture")
        for key in ("formal_training_ready", "native_loaded", "model_deserialized", "cloud_resources_created", "training_started"):
            self.assertFalse(result[key])
        self.assertFalse((self.root / ".cache/logs").exists())

    def test_cuda_request_on_cpu_lock_and_no_gpu_fails_closed(self):
        config = self.config()
        config["runtime_device"] = "cuda"
        config["minimum_hardware"].update(cuda_devices=1, cuda_device_memory_bytes=4096)
        result = preflight(self.root, config, observed_hardware=self.host())
        self.assertFalse(result["deployment_checks_passed"])
        self.assertTrue({"visible_cuda_hardware", "minimum_cuda_device_memory", "cuda_dependency_build",
                         "cuda_dependency_lock", "native_resource_hashes"}.issubset(result["blockers"]))
        self.assertFalse(result["formal_training_ready"])

    def test_missing_thresholds_hashes_dependencies_and_resume_are_blocked(self):
        config = self.config()
        config["minimum_hardware"]["memory_bytes"] = None
        config["dependency_lock"]["sha256"] = None
        config["resume"].update(mode="resume", state_root="missing-state", run_id="missing-run", checkpoint_id="missing-checkpoint")
        result = preflight(self.root, config, observed_hardware=self.host())
        self.assertTrue({"minimum_memory_bytes", "dependency_lock_hash", "selected_recovery_checkpoint_bytes"}.issubset(result["blockers"]))
        self.assertFalse((self.root / "missing-state").exists())
        with patch("scripts.deployment_prepare.importlib.metadata.version", side_effect=importlib_missing):
            self.assertFalse(pinned_dependencies_match(self.root / "requirements/ci-cpu.txt"))

    def test_resume_bytes_are_separate_from_fixture_and_model_compatibility(self):
        state = self.root / ".cache/state"
        reporter = RunReporter(state)
        snapshot = {"schema_version": 1, "run_id": "resume-fixture", "state": "paused", "revision": 1,
            "model_versions": {}, "metrics": {}, "checkpoint_ids": ["inert"], "source": "local_contract_fixture"}
        reporter.publish(snapshot)
        folder = state / "runs/resume-fixture/checkpoints"
        folder.mkdir()
        payload = b"inert test bytes, never deserialized"
        artifact = folder / "inert.weights"
        artifact.write_bytes(payload)
        receipt = {"schema_version": 1, "run_id": "resume-fixture", "checkpoint_id": "inert",
            "artifact_bytes": len(payload), "artifact_sha256": fingerprint(payload), "step": 0}
        (folder / "inert.json").write_text(json.dumps(receipt), encoding="utf-8")
        config = self.config()
        config["resume"].update(mode="resume", state_root=".cache/state", run_id="resume-fixture", checkpoint_id="inert")
        result = preflight(self.root, config, observed_hardware=self.host())
        self.assertFalse(result["recovery"]["bytes_verified"])
        # Explicitly emulate a trainer-origin receipt to exercise byte checks;
        # these fixture bytes are still not trained weights or a recovery test.
        reporter.publish(dict(snapshot, source="trainer", revision=2))
        result = preflight(self.root, config, observed_hardware=self.host())
        self.assertTrue(result["recovery"]["bytes_verified"])
        self.assertFalse(result["recovery"]["binding_verified"])
        self.assertFalse(result["formal_training_ready"])
        artifact.write_bytes(b"")
        receipt.update(artifact_bytes=0, artifact_sha256=fingerprint(b""))
        (folder / "inert.json").write_text(json.dumps(receipt), encoding="utf-8")
        self.assertFalse(preflight(self.root, config, observed_hardware=self.host())["recovery"]["bytes_verified"])

    def test_evidence_is_hash_only_and_escape_or_duplicate_ids_rejected(self):
        path = self.root / "report.json"
        path.write_text('{"passed":true}', encoding="utf-8")
        config = self.config()
        entry = {"id": "P-01", "path": "report.json", "sha256": fingerprint(path.read_bytes())}
        config["evidence"] = [entry]
        result = preflight(self.root, config, observed_hardware=self.host())
        self.assertTrue(result["evidence"][0]["bytes_verified"])
        self.assertFalse(result["evidence"][0]["capability_verified"])
        config["evidence"] = [entry, copy.deepcopy(entry)]
        with self.assertRaisesRegex(ContractError, "unique"):
            preflight(self.root, config, observed_hardware=self.host())
        config["evidence"] = [dict(entry, path="../outside")]
        with self.assertRaisesRegex(ContractError, "outside"):
            preflight(self.root, config, observed_hardware=self.host())

    def test_actual_cpu_host_inventory_has_no_fabricated_gpu_numbers(self):
        facts = hardware(self.root)
        self.assertIn("disk_free_bytes", facts)
        if not facts["cuda_available"]:
            self.assertEqual(facts["visible_cuda_devices"], 0)
            self.assertEqual(facts["cuda_device_memory_bytes"], [])

    def test_direct_torch_wheel_checks_actual_installed_distribution_version(self):
        import importlib.metadata
        installed = importlib.metadata.version
        lock = self.root / "requirements/ci-cpu.txt"
        self.assertTrue(pinned_dependencies_match(lock))
        seen = []
        def wrong_torch(name):
            seen.append(name)
            return "0.0.0-wrong-fixture" if name == "torch" else installed(name)
        with patch("scripts.deployment_prepare.importlib.metadata.version", side_effect=wrong_torch):
            self.assertFalse(pinned_dependencies_match(lock))
        self.assertIn("torch", seen)

    def test_direct_torch_url_requires_a_real_wheel_name_and_matching_decoded_version(self):
        lock = self.root / "requirements/fixture-lock.txt"
        for filename in ("arbitrary-prefix", "torch-fake-cp312-cp312-linux_x86_64.whl",
                         "torch-0.0.0%2Bwrong-cp312-cp312-linux_x86_64.whl"):
            with self.subTest(filename=filename):
                lock.write_text("torch @ https://download-r2.pytorch.org/whl/cpu/" + filename +
                                " --hash=sha256:" + "0" * 64 + "\n", encoding="utf-8")
                self.assertFalse(pinned_dependencies_match(lock))


def importlib_missing(_):
    from importlib.metadata import PackageNotFoundError
    raise PackageNotFoundError("fixture missing package")
