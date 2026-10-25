"""Deterministic, allowlisted monitor data. No LLM calls or weight deserialization."""

import hashlib
import math
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

from .agent_registry import identifier
from .validation import ContractError, array, fields, integer, member, read_json, text

METRICS = {"steps", "episodes", "loss", "reward_mean", "samples_per_second", "elapsed_seconds",
           "cpu_percent", "rss_bytes", "gpu_memory_bytes", "budget_instance_hours", "process_cpu_seconds", "process_peak_rss_bytes",
           "time_limit_seconds", "budget_seconds_remaining", "discarded_episodes", "recovery_count",
           "setup_process_cpu_seconds", "unmeasured_worker_segments", "validation_episodes", "committed_rounds",
           "usage_segments", "usage_wall_seconds", "optimizer_updates", "cycles_completed", "committed_stages"}


class RunMonitor:
    def __init__(self, state_root):
        state = Path(state_root).resolve()
        self.root = (state / "runs").resolve()
        if not self.root.is_relative_to(state):
            raise ContractError("run directory outside configured state root")

    def _path(self, run_id, child):
        identifier(run_id)
        path = self.root / run_id / child
        if not path.resolve().is_relative_to(self.root):
            raise ContractError("monitor path outside registered runs")
        return path

    def runs(self):
        if not self.root.exists():
            return []
        return [self.snapshot(p.name) for p in sorted(self.root.iterdir()) if p.is_dir() and (p / "status.json").is_file()]

    def snapshot(self, run_id):
        identifier(run_id)
        from .local_training import local_snapshot
        managed = local_snapshot(self.root.parent, run_id)
        if managed is not None:
            return self.validate_snapshot(managed, run_id)
        return self.validate_snapshot(read_json(self._path(run_id, "status.json")), run_id)

    @staticmethod
    def validate_snapshot(value, run_id):
        d = fields(value,
            {"schema_version", "run_id", "state", "revision", "model_versions", "metrics", "checkpoint_ids", "source"})
        integer(d["schema_version"], "run schema", 1, 1)
        if d["run_id"] != run_id:
            raise ContractError("run identity mismatch")
        member(d["state"], "run state", ("created", "running", "paused", "completed", "failed", "stopped"))
        member(d["source"], "run evidence source", ("trainer", "local_contract_fixture"))
        integer(d["revision"], "run revision")
        fields(d["model_versions"], set(), {"duel", "build_goal", "build_optimizer", "coordinator"})
        for value in d["model_versions"].values():
            text(value, "model version")
        fields(d["metrics"], set(), METRICS)
        for key, value in d["metrics"].items():
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ContractError("metric must be a finite number")
            if key in ("steps", "episodes", "rss_bytes", "gpu_memory_bytes", "process_peak_rss_bytes"):
                integer(value, key)
            if key not in ("loss", "reward_mean") and value < 0:
                raise ContractError("count/resource metric cannot be negative")
        for checkpoint_id in array(d["checkpoint_ids"], "checkpoint IDs"):
            identifier(checkpoint_id)
        return d

    def checkpoint(self, run_id, checkpoint_id):
        identifier(checkpoint_id)
        run = self.snapshot(run_id)
        if checkpoint_id not in run["checkpoint_ids"]:
            raise ContractError("checkpoint not registered to run")
        d = fields(read_json(self._path(run_id, f"checkpoints/{checkpoint_id}.json")),
            {"schema_version", "run_id", "checkpoint_id", "artifact_sha256", "artifact_bytes", "step"})
        integer(d["schema_version"], "checkpoint schema", 1, 1)
        integer(d["artifact_bytes"], "artifact bytes")
        integer(d["step"], "checkpoint step")
        if d["run_id"] != run_id or d["checkpoint_id"] != checkpoint_id:
            raise ContractError("checkpoint identity mismatch")
        artifact = self._path(run_id, f"checkpoints/{checkpoint_id}.weights")
        if not artifact.is_file() or artifact.stat().st_size != d["artifact_bytes"]:
            raise ContractError("checkpoint artifact missing or size differs")
        digest = hashlib.sha256()
        with artifact.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != d["artifact_sha256"]:
            raise ContractError("checkpoint artifact checksum differs")
        return dict(d, integrity_verified=True, deserialized=False, source=run["source"])


class RunReporter(RunMonitor):
    """Trusted trainer-side hook, deliberately not exposed as an external-agent write tool."""
    def __init__(self, state_root):
        super().__init__(state_root)
        self.started, self.cpu_started = time.monotonic(), time.process_time()

    def resources(self):
        metrics = {"elapsed_seconds": time.monotonic() - self.started,
                   "process_cpu_seconds": time.process_time() - self.cpu_started}
        try:
            import resource
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            metrics["process_peak_rss_bytes"] = int(rss if sys.platform == "darwin" else rss * 1024)
        except ImportError:
            pass
        return metrics  # No fabricated GPU reading and no provider/LLM call.

    def publish(self, value):
        if not isinstance(value, dict):
            raise ContractError("snapshot must be an object")
        run_id = identifier(value.get("run_id"))
        snapshot = self.validate_snapshot(value, run_id)
        destination = self._path(run_id, "status.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        lock = destination.parent / ".publish-lock"
        try:
            lock.mkdir()
        except FileExistsError:
            raise ContractError("snapshot writer busy; inspect before retrying") from None
        temporary = destination.parent / f".snapshot-{uuid4().hex}.json"
        try:
            if destination.exists() and self.snapshot(run_id)["revision"] >= snapshot["revision"]:
                raise ContractError("snapshot revision must advance")
            from .validation import canonical_json
            with temporary.open("x", encoding="utf-8") as output:
                output.write(canonical_json(snapshot) + "\n")
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(destination)
        finally:
            if temporary.exists():
                temporary.unlink()
            lock.rmdir()
        return snapshot
