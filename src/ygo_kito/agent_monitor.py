"""Deterministic, allowlisted monitor data. No LLM calls or weight deserialization."""

import hashlib
import csv
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
from uuid import uuid4

from .agent_registry import identifier
from .validation import ContractError, array, fields, integer, member, read_json, text

METRICS = {"steps", "episodes", "loss", "reward_mean", "samples_per_second", "elapsed_seconds",
           "cpu_percent", "rss_bytes", "gpu_memory_bytes", "budget_instance_hours", "process_cpu_seconds", "process_peak_rss_bytes",
           "time_limit_seconds", "budget_seconds_remaining", "discarded_episodes", "recovery_count",
           "setup_process_cpu_seconds", "unmeasured_worker_segments", "validation_episodes", "committed_rounds",
           "usage_segments", "usage_wall_seconds", "optimizer_updates", "cycles_completed", "committed_stages",
           "process_read_bytes", "process_write_bytes", "gpu_utilization_percent", "gpu_memory_total_bytes",
           "decisions_per_second"}

PROCESS_COUNTERS = ('rss_bytes', 'process_peak_rss_bytes', 'process_read_bytes', 'process_write_bytes')
GPU_COUNTERS = ('gpu_utilization_percent', 'gpu_memory_bytes', 'gpu_memory_total_bytes')


def _windows_counters():
    import ctypes
    from ctypes import wintypes

    class MemoryCounters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (field, ctypes.c_size_t) for field in ('peak', 'current', 'quota_peak_paged', 'quota_paged',
                                                   'quota_peak_nonpaged', 'quota_nonpaged', 'pagefile', 'peak_pagefile')]

    class IOCounters(ctypes.Structure):
        _fields_ = [(field, ctypes.c_uint64) for field in ('reads', 'writes', 'others', 'read_bytes', 'write_bytes', 'other_bytes')]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessIoCounters.argtypes = [wintypes.HANDLE, ctypes.POINTER(IOCounters)]
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
    handle = kernel.GetCurrentProcess()
    memory = MemoryCounters()
    memory.cb = ctypes.sizeof(memory)
    io = IOCounters()
    values = {}
    if psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
        values.update(rss_bytes=int(memory.current), process_peak_rss_bytes=int(memory.peak))
    if kernel.GetProcessIoCounters(handle, ctypes.byref(io)):
        values.update(process_read_bytes=int(io.read_bytes), process_write_bytes=int(io.write_bytes))
    return values, 'Windows process working-set and I/O transfer counters'


def _process_counters():
    if os.name == 'nt':
        try:
            return _windows_counters()
        except OSError:
            return {}, 'Windows process counters unavailable'
    values = {}
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        values['process_peak_rss_bytes'] = int(rss if sys.platform == 'darwin' else rss * 1024)
    except (ImportError, OSError):
        pass
    for filename, mapping in (('status', {'VmRSS': ('rss_bytes', 1024)}), ('io', {
            'read_bytes': ('process_read_bytes', 1), 'write_bytes': ('process_write_bytes', 1)})):
        try:
            for line in Path('/proc/self', filename).read_text(encoding='ascii').splitlines():
                key, _, value = line.partition(':')
                if key in mapping:
                    field, scale = mapping[key]
                    values[field] = int(value.split()[0]) * scale
        except (OSError, UnicodeError):
            pass
    return values, 'POSIX getrusage and Linux /proc/self process counters'


def nvidia_device_sample(device_index=0):
    """Opt-in device counters for the selected host GPU."""
    integer(device_index, 'GPU device index', 0)
    executable = shutil.which('nvidia-smi')
    if executable is None:
        return None
    try:
        sample = subprocess.run([executable, '-i', str(device_index),
            '--query-gpu=uuid,name,driver_version,utilization.gpu,memory.used,memory.total', '--format=csv,noheader,nounits'],
            text=True, capture_output=True, check=True, timeout=2,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        identity, name, driver, utilization, used, capacity = [value.strip() for value in next(csv.reader(sample.stdout.splitlines()))]
    except (OSError, subprocess.SubprocessError, StopIteration, ValueError):
        return None
    metrics = {key: int(raw)*scale for key, raw, scale in zip(GPU_COUNTERS, (utilization, used, capacity), (1, 2**20, 2**20))
               if raw.isdecimal()}
    return dict(device=dict(uuid=identity, name=name, driver=driver), metrics=metrics, source='nvidia-smi device counters')


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
            if key in ("steps", "episodes", "gpu_memory_bytes", "gpu_memory_total_bytes", *PROCESS_COUNTERS):
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

    def _sample(self):
        elapsed, cpu = time.monotonic() - self.started, time.process_time() - self.cpu_started
        metrics = dict(elapsed_seconds=elapsed, process_cpu_seconds=cpu)
        if elapsed > 0:
            metrics['cpu_percent'] = 100 * cpu / elapsed
        counters, source = _process_counters()
        metrics.update(counters)
        return metrics, {key: source if key in counters else 'process CPU and monotonic clocks' for key in metrics}

    def resources(self):
        return self._sample()[0]

    def resource_snapshot(self, *, binding, stage_seconds=None, gpu_sampler=None):
        metrics, sources = self._sample()
        gpu = gpu_sampler() if gpu_sampler is not None else None
        if gpu is not None:
            values = fields(gpu['metrics'], set(), set(GPU_COUNTERS))
            if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in values.values()):
                raise ContractError('GPU sample must contain finite measured counters')
            metrics.update(values)
            sources.update({key: gpu['source'] for key in values})
        stages = dict(stage_seconds or {})
        if any(value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0)
               for value in stages.values()):
            raise ContractError('stage latency must be a finite duration or null')
        for key in ('cpu_percent', *PROCESS_COUNTERS, *GPU_COUNTERS):
            metrics.setdefault(key, None)
            sources.setdefault(key, None)
        return dict(binding=binding, hardware=dict(system=platform.system(), architecture=platform.machine(),
            logical_cpu_count=os.cpu_count(), gpu=gpu['device'] if gpu else None), metrics=metrics,
            metric_sources=sources, stage_seconds=stages)

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
