"""Read-only source/dependency/resource/checkpoint inventory; never starts training.

Only fixed project status/help subprocesses run. Native resources are hashed by
the existing verifier, never loaded. Checkpoint bytes are checked, not unpickled.
"""
import argparse
import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "src"))

from ygo_kito.agent_monitor import RunMonitor
from ygo_kito.engine import EngineUnavailable
from ygo_kito.native_assets import verify_resources
from ygo_kito.validation import ContractError


def dependencies():
    installed = {}
    for name in ("torch", "numpy", "scipy", "setuptools"):
        try:
            installed[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed[name] = None
    locks = {}
    for path in sorted((ROOT / "requirements").glob("*.txt")):
        locks[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"installed": installed, "requirement_sha256": locks,
            "lock_matches_installed": None,
            "note": "Installed versions are observations; use the locked CI environment for reproducible checks. SciPy is optional for the legacy empty-deck solver."}


def checkpoint_inventory(state_root):
    if state_root is None:
        return {"requested": False, "runs": [], "all_registered_bytes_verified": None,
                "resume_executed": False}
    monitor = RunMonitor(state_root)
    found = []
    # Use the existing authoritative snapshot lookup (managed SQLite is read-only).
    for snapshot in monitor.runs():
        records = []
        for checkpoint_id in snapshot["checkpoint_ids"]:
            try:
                receipt = monitor.checkpoint(snapshot["run_id"], checkpoint_id)
                if receipt["artifact_bytes"] <= 0:
                    raise ContractError("empty checkpoint artifact cannot be a recovery candidate")
                records.append({k: receipt[k] for k in ("checkpoint_id", "artifact_sha256", "artifact_bytes", "step", "integrity_verified", "deserialized")})
            except (ContractError, OSError, ValueError, sqlite3.Error):
                records.append({"checkpoint_id": checkpoint_id, "integrity_verified": False,
                                "deserialized": False, "reason": "registered checkpoint bytes/receipt unavailable or inconsistent"})
        found.append({"run_id": snapshot["run_id"], "state": snapshot["state"],
                      "revision": snapshot["revision"], "source": snapshot["source"], "checkpoints": records})
    records = [item for run in found for item in run["checkpoints"]]
    return {"requested": True, "runs": found,
            "all_registered_bytes_verified": all(item["integrity_verified"] for item in records) if records else None,
            "resume_executed": False,
            "note": "Byte integrity does not establish model/source/data compatibility or successful recovery. No checkpoints is unknown, not a pass."}


def startup_probe():
    result = []
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1",
               OMP_NUM_THREADS="2", MKL_NUM_THREADS="2")
    with tempfile.TemporaryDirectory(prefix="ygo-handoff-startup-") as temporary:
        for operation in ("status", "--help"):
            started = time.monotonic()
            try:
                process = subprocess.run([sys.executable, "-m", "ygo_kito", operation],
                    cwd=temporary, env=env, capture_output=True, text=True, timeout=20)
                item = {"operation": operation, "exit_code": process.returncode,
                        "passed": process.returncode == 0, "elapsed_seconds": time.monotonic() - started}
                if operation == "status" and item["passed"]:
                    try:
                        item["engine_ready_reported"] = json.loads(process.stdout)["engine"]["ready"]
                    except (ValueError, KeyError, TypeError):
                        item.update(passed=False, reason="invalid project status response")
            except (OSError, subprocess.TimeoutExpired):
                item = {"operation": operation, "passed": False, "elapsed_seconds": time.monotonic() - started,
                        "reason": "fixed startup command unavailable or timed out"}
            result.append(item)
    return result


def resource_metrics():
    metrics = {"controller_cpu_seconds": time.process_time()}
    try:
        import resource
        own = resource.getrusage(resource.RUSAGE_SELF)
        child = resource.getrusage(resource.RUSAGE_CHILDREN)
        scale = 1 if sys.platform == "darwin" else 1024
        metrics.update(controller_peak_rss_bytes=int(own.ru_maxrss * scale),
                       reaped_children_cpu_seconds=child.ru_utime + child.ru_stime,
                       reaped_children_max_peak_rss_bytes=int(child.ru_maxrss * scale))
    except ImportError:
        pass
    return metrics


def collect(native_root, state_root=None, *, probe=True):
    started = time.monotonic()
    try:
        receipt = verify_resources(Path(native_root).resolve())
        native = {"hash_receipt_verified": True, "source_commits": receipt["source_commits"],
                  "native_loaded": False, "rules_verified": False}
    except (EngineUnavailable, OSError, KeyError, TypeError, ValueError):
        native = {"hash_receipt_verified": False, "native_loaded": False, "rules_verified": False,
                  "required": ["engine-build/receipt.json", "engine-build/libocgcore.so",
                               "engine-src/database/locales/zh-CN/cards.cdb", "engine-src/client/lflist.conf",
                               "locked core/scripts/client source tree"],
                  "reason": "locked resource receipt absent or hashes inconsistent; no build/download attempted"}
    try:
        checkpoints = checkpoint_inventory(state_root)
    except (ContractError, OSError, ValueError, sqlite3.Error):
        checkpoints = {"requested": state_root is not None, "runs": [],
                       "all_registered_bytes_verified": False, "resume_executed": False,
                       "reason": "state root unavailable or snapshot invalid"}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True)
    probes = startup_probe() if probe else []
    return {"schema_version": 1, "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "scope": "source-handoff-inventory-and-fixed-startup-only", "commit": commit.stdout.strip() or None,
            "dependencies": dependencies(), "native_resources": native, "checkpoints": checkpoints,
            "startup": probes, "hardware": {"python": platform.python_version(), "platform": platform.system(),
                "logical_cpus": os.cpu_count(),
                "affinity_cpus": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None},
            "resources": dict(resource_metrics(), elapsed_seconds=time.monotonic() - started),
            "missing_measurements": ["GPU memory/utilization", "native games per second", "training samples per second", "PC inference latency"],
            "training_started": False, "external_provider_called": False, "formal_training_ready": False,
            "note": "This inventory never authorizes or starts training. Startup speed is not game/training throughput. Native and model capability gates remain separate."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / ".cache")
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = collect(args.root, args.state_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0  # Inventory generated; readiness is deliberately never inferred.


if __name__ == "__main__":
    raise SystemExit(main())
