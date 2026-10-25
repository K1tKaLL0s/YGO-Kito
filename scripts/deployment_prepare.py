"""Prepare/verify a local source bundle and inspect an existing training host.

No extraction, shell, cloud API, credentials, training, native rules or model
deserialization. CUDA queries only inventory the current host's visible devices.
"""
import argparse
import gzip
import hashlib
import importlib.metadata
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.training_handoff import checkpoint_inventory
from ygo_kito.engine import EngineUnavailable
from ygo_kito.native_assets import verify_resources
from ygo_kito.validation import ContractError, fields, parse_json

MANIFEST = "deployment-manifest.json"
PREFIXES = ("src/", "scripts/", "tests/", "integration_tests/", "configs/", "requirements/",
            "docs/development/", "docs/plans/")
ROOT_FILES = {"README.md", "AGENTS.md", "pyproject.toml"}
REQUIRED_FILES = ROOT_FILES | {"src/ygo_kito/__main__.py", "src/ygo_kito/cli.py",
    "scripts/deployment_prepare.py", "scripts/training_handoff.py", "scripts/check_merge_candidate.py",
    "requirements/ci-cpu.txt", "configs/deployment-host-template-v1.json"}
SHA = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
MAX_FILE_BYTES = 16 * 1024 * 1024


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def allowed(name):
    path = PurePosixPath(name)
    return (not path.is_absolute() and str(path) == name and ".." not in path.parts
            and not any(part.startswith(".") or part in ("__pycache__", "node_modules") for part in path.parts)
            and path.suffix in (".py", ".cs", ".md", ".toml", ".json", ".txt", ".yaml", ".yml", ".sql", ".sh")
            and (name in ROOT_FILES or name.startswith(PREFIXES)))


def git(workspace, *args):
    return subprocess.check_output(["git", *args], cwd=workspace, text=True).strip()


def selected_dirty(workspace):
    tracked = git(workspace, "diff", "--name-only", "-z", "HEAD").split("\0")
    untracked = git(workspace, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    return any(allowed(name) for name in tracked + untracked)


def source_files(workspace):
    workspace = Path(workspace).resolve()
    if Path(git(workspace, "rev-parse", "--show-toplevel")).resolve() != workspace:
        raise ContractError("workspace must be the complete repository root")
    names = sorted(name for name in git(workspace, "ls-files", "-z").split("\0") if allowed(name))
    if not REQUIRED_FILES.issubset(names):
        raise ContractError("full tracked source checkout required")
    # A packet must identify the committed source it actually contains. Do not
    # silently drop uncommitted code, including a newly added script or config.
    if selected_dirty(workspace):
        raise ContractError("commit selected source changes before packaging")
    result = {}
    for name in names:
        path = workspace / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(workspace):
            raise ContractError("source bundle requires regular files inside checkout")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ContractError("source file exceeds source-only bundle limit")
        result[name] = path.read_bytes()
    return result


def prepare_bundle(workspace, output):
    workspace = Path(workspace).resolve()
    output = Path(output)
    data = source_files(workspace)
    commit = git(workspace, "rev-parse", "HEAD")
    manifest = {"schema_version": 1, "kind": "source-only-no-runtime-data", "source_commit": commit,
                "files": {name: {"sha256": fingerprint(blob), "bytes": len(blob)} for name, blob in data.items()},
                "runtime_assets_included": False, "checkpoints_included": False,
                "credentials_read": False, "training_started": False}
    data[MANIFEST] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as destination:
        with gzip.GzipFile(filename="", fileobj=destination, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for name, blob in sorted(data.items()):
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = len(blob), 0o644
                    archive.addfile(info, io.BytesIO(blob))
    return {"source_commit": commit, "bundle_sha256": fingerprint(output.read_bytes()),
            "bundle_bytes": output.stat().st_size, "files": len(manifest["files"]),
            "runtime_assets_included": False, "training_started": False}


def validate_manifest(manifest):
    d = fields(manifest, {"schema_version", "kind", "source_commit", "files", "runtime_assets_included",
                          "checkpoints_included", "credentials_read", "training_started"})
    if (type(d["schema_version"]) is not int or d["schema_version"] != 1 or d["kind"] != "source-only-no-runtime-data"
            or not isinstance(d["source_commit"], str) or not COMMIT.fullmatch(d["source_commit"])
            or any(d[key] is not False for key in ("runtime_assets_included", "checkpoints_included", "credentials_read", "training_started"))
            or not isinstance(d["files"], dict) or not REQUIRED_FILES.issubset(d["files"])):
        raise ContractError("invalid source bundle manifest")
    for name, value in d["files"].items():
        fields(value, {"sha256", "bytes"})
        if (not allowed(name) or type(value["bytes"]) is not int or not 0 <= value["bytes"] <= MAX_FILE_BYTES
                or not isinstance(value["sha256"], str) or not SHA.fullmatch(value["sha256"])):
            raise ContractError("invalid source file manifest")
    return d


def verify_bundle(path):
    # Inspect regular member bytes only. No archive path is extracted or executed.
    members = {}
    total = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            if (not member.isfile() or member.name in members or member.size > MAX_FILE_BYTES
                    or (member.name != MANIFEST and not allowed(member.name))):
                raise ContractError("unsafe or duplicate source archive member")
            total += member.size
            if total > 128 * 1024 * 1024:
                raise ContractError("source archive exceeds total size limit")
            members[member.name] = archive.extractfile(member).read()
    if MANIFEST not in members:
        raise ContractError("source manifest missing")
    manifest = validate_manifest(parse_json(members.pop(MANIFEST).decode("utf-8")))
    if set(members) != set(manifest["files"]):
        raise ContractError("source archive membership differs")
    for name, blob in members.items():
        if {"sha256": fingerprint(blob), "bytes": len(blob)} != manifest["files"][name]:
            raise ContractError("source archive checksum differs")
    return {"verified": True, "source_commit": manifest["source_commit"], "files": len(members),
            "bundle_sha256": fingerprint(Path(path).read_bytes()), "extracted": False,
            "note": "Integrity only; an unsigned hash does not authenticate a publisher or establish training readiness."}


def verify_source_tree(workspace):
    """Validate an installed source-only packet without trusting a parent Git repo."""
    workspace = Path(workspace).resolve()
    manifest_file = workspace / MANIFEST
    if not manifest_file.is_file() or manifest_file.is_symlink():
        raise ContractError("regular installed-source manifest required")
    manifest = validate_manifest(parse_json(manifest_file.read_text(encoding="utf-8")))
    selected = set()
    for path in workspace.rglob("*"):
        name = path.relative_to(workspace).as_posix()
        if path.is_symlink() and (name in ROOT_FILES or name.startswith(PREFIXES)):
            raise ContractError("installed source tree contains a symlink")
        if path.is_file() and allowed(name):
            selected.add(name)
    if selected != set(manifest["files"]):
        raise ContractError("installed source membership differs from manifest")
    for name, receipt in manifest["files"].items():
        path = workspace / name
        if (not path.resolve().is_relative_to(workspace) or path.stat().st_size != receipt["bytes"]
                or fingerprint(path.read_bytes()) != receipt["sha256"]):
            raise ContractError("installed source checksum differs from manifest")
    return manifest


def hardware(workspace):
    observed = {"python": platform.python_version(), "platform": platform.system(),
                "architecture": platform.machine(), "logical_cpus": os.cpu_count(),
                "memory_limit_bytes": None, "disk_free_bytes": shutil.disk_usage(workspace).free,
                "torch": None, "cuda_available": False, "visible_cuda_devices": 0,
                "cuda_device_memory_bytes": [], "gpu_probe_error": None}
    try:
        cores = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
        quota = Path("/sys/fs/cgroup/cpu.max")
        if quota.is_file():
            amount, period = quota.read_text().split()
            if amount != "max":
                cores = min(cores, int(amount) / int(period))
        observed["available_cpu_cores"] = cores
    except (OSError, ValueError, TypeError):
        observed["available_cpu_cores"] = None
    try:
        memory = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        cap = Path("/sys/fs/cgroup/memory.max")
        if cap.is_file() and cap.read_text().strip() != "max":
            memory = min(memory, int(cap.read_text()))
        observed["memory_limit_bytes"] = memory
    except (OSError, ValueError, AttributeError):
        pass
    try:
        import torch
        observed.update(torch=str(torch.__version__), cuda_build=torch.version.cuda)
        observed["cuda_available"] = torch.cuda.is_available()
        if observed["cuda_available"]:
            observed["visible_cuda_devices"] = torch.cuda.device_count()
            observed["cuda_device_memory_bytes"] = [torch.cuda.get_device_properties(i).total_memory
                                                       for i in range(observed["visible_cuda_devices"])]
    except (ImportError, RuntimeError, OSError):
        observed["gpu_probe_error"] = "Torch/CUDA inventory unavailable; no device or training test executed"
    return observed


def local_path(workspace, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ContractError("deployment paths must be explicit relative paths")
    path = (workspace / value).resolve()
    if not path.is_relative_to(workspace):
        raise ContractError("deployment path outside workspace")
    return path


def pinned_dependencies_match(path):
    count = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not re.search(r"--hash=sha256:[0-9a-f]{64}(?:\s|$)", line):
            return False
        match = re.match(r"([A-Za-z0-9_.-]+)==([^\s]+)\s", line)
        if match:
            count += 1
            try:
                if importlib.metadata.version(match[1]) != match[2]:
                    return False
            except importlib.metadata.PackageNotFoundError:
                return False
        elif line.startswith("torch @ https://download-r2.pytorch.org/whl/"):
            # Bind the direct wheel requirement to the installed distribution,
            # not a separately supplied host-config version. Keep the existing
            # approved URL origin/path policy and perform no network access.
            direct = re.fullmatch(r"torch @ (\S+) --hash=sha256:[0-9a-f]{64}", line)
            if direct is None:
                return False
            filename = unquote(PurePosixPath(urlsplit(direct[1]).path).name)
            wheel = re.fullmatch(r"torch-(\d+\.\d+\.\d+(?:\+[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*)?)-"
                                 r"cp\d+-cp\d+-[A-Za-z0-9_.]+\.whl", filename)
            if wheel is None:
                return False
            count += 1
            try:
                if importlib.metadata.version("torch") != wheel[1]:
                    return False
            except importlib.metadata.PackageNotFoundError:
                return False
        else:
            return False
    return count > 0


def preflight(workspace, config, *, observed_hardware=None):
    workspace = Path(workspace).resolve()
    d = fields(config, {"schema_version", "expected_source_commit", "dependency_lock", "runtime_device",
                        "minimum_hardware", "native_root", "log_directory", "resume", "evidence"})
    if type(d["schema_version"]) is not int or d["schema_version"] != 1 or d["runtime_device"] not in ("cpu", "cuda"):
        raise ContractError("unsupported deployment schema/device")
    lock = fields(d["dependency_lock"], {"path", "sha256", "python", "torch"})
    minimum = fields(d["minimum_hardware"], {"cpu_cores", "memory_bytes", "disk_free_bytes",
                                             "cuda_devices", "cuda_device_memory_bytes"})
    resume = fields(d["resume"], {"mode", "state_root", "run_id", "checkpoint_id"})
    if resume["mode"] not in ("fresh", "resume") or not isinstance(d["evidence"], list):
        raise ContractError("invalid resume mode/evidence list")
    facts = hardware(workspace) if observed_hardware is None else dict(observed_hardware)
    blockers, checks = [], {}
    def check(name, passed):
        checks[name] = bool(passed)
        if not passed:
            blockers.append(name)
    try:
        if Path(git(workspace, "rev-parse", "--show-toplevel")).resolve() != workspace:
            raise subprocess.CalledProcessError(1, "git workspace root differs")
        actual_commit = git(workspace, "rev-parse", "HEAD")
        clean = not selected_dirty(workspace)
    except subprocess.CalledProcessError:
        actual_commit, clean = None, False
        manifest_file = workspace / MANIFEST
        if manifest_file.is_file() and not manifest_file.is_symlink():
            try:
                manifest = verify_source_tree(workspace)
                actual_commit, clean = manifest["source_commit"], True
            except (ContractError, OSError, ValueError):
                pass  # A modified packet is a failed check, never a verified source.
    check("source_commit_and_clean_files", isinstance(d["expected_source_commit"], str)
          and COMMIT.fullmatch(d["expected_source_commit"]) and actual_commit == d["expected_source_commit"] and clean)
    lock_path = local_path(workspace, lock["path"])
    check("dependency_lock_hash", isinstance(lock["sha256"], str) and SHA.fullmatch(lock["sha256"])
          and lock_path.is_file() and fingerprint(lock_path.read_bytes()) == lock["sha256"])
    check("pinned_dependency_versions", lock_path.is_file() and pinned_dependencies_match(lock_path))
    check("python_version", isinstance(lock["python"], str) and facts.get("python") == lock["python"])
    check("torch_version", isinstance(lock["torch"], str) and facts.get("torch") == lock["torch"])
    for key, fact in (("cpu_cores", "available_cpu_cores"), ("memory_bytes", "memory_limit_bytes"),
                      ("disk_free_bytes", "disk_free_bytes")):
        value = minimum[key]
        check("minimum_" + key, type(value) in (int, float) and 0 < value < 2 ** 63 and math.isfinite(value)
              and type(facts.get(fact)) in (int, float) and facts[fact] >= value)
    if d["runtime_device"] == "cuda":
        count, memory = minimum["cuda_devices"], minimum["cuda_device_memory_bytes"]
        check("visible_cuda_hardware", facts.get("cuda_available") is True and type(count) is int and count > 0
              and facts.get("visible_cuda_devices", 0) >= count)
        capacities = facts.get("cuda_device_memory_bytes", [])
        check("minimum_cuda_device_memory", type(memory) is int and memory > 0 and type(count) is int and count > 0
              and len(capacities) >= count and all(size >= memory for size in capacities[:count]))
        check("cuda_dependency_build", bool(facts.get("cuda_build")) and "+cpu" not in (facts.get("torch") or ""))
        check("cuda_dependency_lock", lock_path.is_file() and "%2bcpu" not in lock_path.read_text().lower()
              and "+cpu" not in lock_path.read_text().lower())
    else:
        check("cpu_hardware_requirements", type(minimum["cuda_devices"]) is int and minimum["cuda_devices"] == 0
              and type(minimum["cuda_device_memory_bytes"]) is int and minimum["cuda_device_memory_bytes"] == 0)
    try:
        receipt = verify_resources(local_path(workspace, d["native_root"]))
        check("native_resource_hashes", bool(receipt))
    except (EngineUnavailable, OSError, ValueError, TypeError):
        check("native_resource_hashes", False)
    log = local_path(workspace, d["log_directory"])
    ancestor = log
    while not ancestor.exists():
        ancestor = ancestor.parent
    check("log_location_writable", (not log.exists() or log.is_dir()) and os.access(ancestor, os.W_OK))
    evidence, ids = [], set()
    for entry in d["evidence"]:
        item = fields(entry, {"id", "path", "sha256"})
        if not isinstance(item["id"], str) or not item["id"] or item["id"] in ids:
            raise ContractError("evidence IDs must be nonempty and unique")
        ids.add(item["id"])
        path = local_path(workspace, item["path"])
        verified = (isinstance(item["sha256"], str) and SHA.fullmatch(item["sha256"])
                    and path.is_file() and path.stat().st_size > 0 and fingerprint(path.read_bytes()) == item["sha256"])
        check("evidence_bytes:" + str(item["id"]), verified)
        evidence.append({"id": item["id"], "bytes_verified": bool(verified), "capability_verified": False})
    recovery = {"requested": resume["mode"] == "resume", "bytes_verified": None,
                "binding_verified": False, "resume_executed": False}
    if resume["mode"] == "resume":
        try:
            inventory = checkpoint_inventory(local_path(workspace, resume["state_root"]))
            candidates = [checkpoint for run in inventory["runs"] if run["run_id"] == resume["run_id"]
                          and run["source"] == "trainer" and run["state"] in ("paused", "failed", "created")
                          for checkpoint in run["checkpoints"] if checkpoint["checkpoint_id"] == resume["checkpoint_id"]]
            recovery["bytes_verified"] = len(candidates) == 1 and candidates[0]["integrity_verified"]
        except (ContractError, OSError, ValueError):
            recovery["bytes_verified"] = False
        check("selected_recovery_checkpoint_bytes", recovery["bytes_verified"])
    else:
        check("fresh_run_has_no_recovery_inputs", all(resume[k] is None for k in ("state_root", "run_id", "checkpoint_id")))
    return {"schema_version": 1, "scope": "existing-host-static-deployment-preparation",
            "deployment_checks_passed": not blockers, "checks": checks, "blockers": blockers,
            "source_commit": actual_commit, "hardware": facts, "evidence": evidence, "recovery": recovery,
            "hardware_source": "actual_host" if observed_hardware is None else "injected_engineering_fixture",
            "formal_training_ready": False, "native_loaded": False, "model_deserialized": False,
            "cloud_resources_created": False, "provider_called": False, "training_started": False,
            "note": "Static deployment checks do not verify stage gates, GPU execution, checkpoint compatibility, or authorize paid training."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    pack = sub.add_parser("bundle")
    pack.add_argument("--workspace", type=Path, default=ROOT)
    pack.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("bundle", type=Path)
    check = sub.add_parser("preflight")
    check.add_argument("--workspace", type=Path, default=ROOT)
    check.add_argument("--config", type=Path, required=True)
    check.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "bundle":
            result = prepare_bundle(args.workspace, args.output)
        elif args.operation == "verify":
            result = verify_bundle(args.bundle)
        else:
            result = preflight(args.workspace, parse_json(args.config.read_text(encoding="utf-8")))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("deployment_checks_passed", True) else 2
    except (ContractError, OSError, ValueError, TypeError, subprocess.SubprocessError, tarfile.TarError) as error:
        print(json.dumps({"error": str(error), "training_started": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
