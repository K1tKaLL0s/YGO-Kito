"""Local CPU health checks only; no credentials, login or resource launch."""

import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import tempfile

from .build_contracts import digest
from .deck_intake import cutoff_timing, validate_intake
from .engine import EngineUnavailable
from .training_plan import validate_plan, required_training_gates
from .validation import ContractError, read_json


def cpu_preflight(root, plan):
    plan = validate_plan(plan)
    from .build_pipeline import BuildAssets
    from .native import NativeError
    checks = {}
    try:
        import torch
        with torch.random.fork_rng(devices=[]):
            x = torch.arange(16, dtype=torch.float32, device="cpu").reshape(4, 4).requires_grad_()
            loss = ((x @ torch.eye(4)) ** 2).mean()
            loss.backward()
        checks["torch_cpu_forward_backward"] = {"passed": bool(torch.isfinite(x.grad).all() and torch.count_nonzero(x.grad)),
                                               "version": str(torch.__version__), "cuda_build": torch.version.cuda,
                                               "device": "cpu", "gradient_norm": float(x.grad.norm())}
    except ImportError:
        checks["torch_cpu_forward_backward"] = {"passed": False, "reason": "CPU PyTorch unavailable"}
    with tempfile.TemporaryDirectory(prefix="ygo-preflight-") as temporary:
        with sqlite3.connect(Path(temporary) / "scratch.sqlite3") as db:
            db.execute("CREATE TABLE scratch(value INTEGER)")
            db.commit()
            db.execute("INSERT INTO scratch VALUES(1)")
            db.rollback()
            checks["sqlite_rollback"] = {"passed": db.execute("SELECT COUNT(*) FROM scratch").fetchone()[0] == 0,
                                         "version": sqlite3.sqlite_version}
    try:
        assets = BuildAssets(root)
        checks["locked_native_assets"] = {"passed": True, "source_commits": assets.receipt["source_commits"],
                                         "resources": assets.receipt["resources"], "native_duel_executed": False}
    except (ContractError, EngineUnavailable, NativeError, OSError, sqlite3.Error):
        checks["locked_native_assets"] = {"passed": False, "reason": "locked native assets unavailable or incompatible"}
    repository = Path(__file__).resolve().parents[2]
    declared_periods = validate_intake(read_json(repository / "configs/user-deck-intake-template-v1.json"))["environments"]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repository, capture_output=True, text=True, check=False)
    disk = shutil.disk_usage(repository)
    return {"schema_version": 1, "ok": all(c["passed"] for c in checks.values()), "scope": "credential-free-local-cpu-preflight",
            "checks": checks, "plan_id": plan["plan_id"], "plan_sha256": digest(plan),
            "hardware": {"python": platform.python_version(), "logical_cpus": os.cpu_count(),
                         "affinity_cpus": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
                         "disk_free_bytes": disk.free},
            "local_commit": commit.stdout.strip() if commit.returncode == 0 else None,
            "toolchain_present": {name: shutil.which(name) is not None for name in ("git", "cmake", "g++")},
            "external_agent": {"codebuddy_executable_present": shutil.which("codebuddy") is not None,
                               "sdk_execution_verified": False,
                               "model_or_quota_checked": False, "credentials_read": False, "provider_called": False},
            "formal_training": {"ready": False, "gate_verification": "not_implemented_by_cpu_health_check",
                                "required_evidence": required_training_gates(plan), "paid_execution_authorized": False,
                                "pc_product_required": False, "external_llm_required": False,
                                "gpu_validation_phase": "stage2_training",
                                "gpu_checks_block_software_completion": False,
                                "declared_period_cutoffs": {period: {**cutoff_timing(env["release_cutoff"]),
                                    "banlist_effective": env["banlist_effective"], "banlist_section": env["banlist_section"]}
                                    for period, env in declared_periods.items()},
                                "resource_launch_implemented": False, "machine_selected": plan["machine_type"] is not None,
                                "instance_price_known": plan["instance_price_per_hour"] is not None,
                                "external_api_cap_known": plan["external_api_amount_limit"] is not None,
                                "environment_manifests_supplied": {k: v is not None for k, v in plan["environment_artifacts"].items()},
                                "stop_remaining_quota_percent": 20, "quota_reader_configured": False}}
