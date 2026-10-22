"""Complete duels for the explicit normal-monster pool, using a deterministic rule baseline.

Replay artifacts contain RNG seeds and both players' response metadata. They are
reproduction records, never policy inputs or mixed-player training observations.
"""

import hashlib
import math
import os
from pathlib import Path
import platform
import statistics
import time

from .contracts import ActionSelection
from .native import NativeError, NativeNormalEngine
from .validation import ContractError, array, canonical_json, fields, integer


def choose_normal_action(request):
    """Only player-visible DTOs enter this baseline; no engine/deck/RNG access."""
    for kind in ("summon", "attack"):
        for action in request.actions:
            if action.kind == kind:
                return action
    for value in (6, 7, 3, 2):
        for action in request.actions:
            if action.kind == "pass" and action.value == value:
                return action
    return request.actions[0]


def request_digest(request):
    return hashlib.sha256(canonical_json(request.to_dict()).encode()).hexdigest()


def run_normal_duel(root: Path, *, seed=7, replay=None, max_decisions=2000, budget_seconds=30):
    integer(max_decisions, "max_decisions", 1, 10000)
    if not 0 < budget_seconds <= 300:
        raise ContractError("normal duel runtime budget must be within 300 seconds")
    if replay is not None:
        fields(replay, {"schema_version", "kind", "seed", "versions", "custom_pool", "responses", "events", "outcome", "turns", "life_points"})
        if type(replay["schema_version"]) is not int or replay["schema_version"] != 1 or replay["kind"] != "normal-duel-replay-not-policy-input":
            raise ContractError("unsupported normal duel replay")
        array(replay["responses"], "responses")
        array(replay["events"], "events")
        for response in replay["responses"]:
            fields(response, {"decision_id", "player", "prompt", "request_sha256", "action_id", "response"})
        seed = replay["seed"]
    start, cpu_start = time.monotonic(), time.process_time()
    latencies = []
    legacy = replay is not None and replay["versions"].get("adapter_schema") == "native-normal-v1-shuffled-deal"
    with NativeNormalEngine(root, seed=seed, legacy_request_ids=legacy) as engine:
        versions = {"source_commits": engine.receipt["source_commits"], "resources": engine.receipt["resources"],
                    "adapter_schema": "native-normal-v1-shuffled-deal" if legacy else "native-normal-v2-observer-windows", "python": platform.python_version(),
                    "initial_order": "host random.Random(seed*2+player).shuffle; native insertion sequence 0"}
        if replay is not None and replay["versions"] != versions:
            raise ContractError("replay native versions/resources differ")
        responses = []
        request = engine.next_decision()
        while request is not None:
            if len(responses) >= max_decisions or time.monotonic() - start >= budget_seconds:
                raise NativeError("normal duel budget exhausted; no natural game result claimed")
            tick = time.perf_counter()
            fingerprint = request_digest(request)
            if replay is not None:
                if len(responses) >= len(replay["responses"]):
                    raise NativeError("replay ended before native duel")
                saved = replay["responses"][len(responses)]
                if fingerprint != saved["request_sha256"]:
                    raise NativeError("replay observation/candidate divergence")
                action = next((a for a in request.actions if a.action_id == saved["action_id"]), None)
                if action is None:
                    raise NativeError("replay action absent from native candidates")
            else:
                action = choose_normal_action(request)
            raw = engine._responses[action.action_id]
            row = {"decision_id": request.decision_id, "player": request.observation.observer,
                   "prompt": engine.pending_kind, "request_sha256": fingerprint, "action_id": action.action_id,
                   "response": {"bytes_hex": raw.hex()} if isinstance(raw, bytes) else {"integer": raw}}
            if replay is not None and row != saved:
                raise NativeError("replay response divergence")
            responses.append(row)
            engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id))
            request = engine.next_decision()
            latencies.append((time.perf_counter() - tick) * 1000)
        if engine.outcome is None or 5 not in engine.messages or engine.callback_errors:
            raise NativeError("native duel lacks a clean terminal result")
        if engine.next_decision() is not None:
            raise NativeError("terminal duel reopened")
        trace = {"schema_version": 1, "kind": "normal-duel-replay-not-policy-input", "seed": seed,
                 "versions": versions, "custom_pool": list(engine.deck), "responses": responses,
                 "events": engine.events, "outcome": engine.outcome, "turns": engine.turn,
                 "life_points": engine.life_points}
        if replay is not None and trace != replay:
            raise NativeError("replay event/result divergence")
        elapsed = time.monotonic() - start
        ordered = sorted(latencies)
        def percentile(q):
            return ordered[max(0, math.ceil(len(ordered) * q) - 1)]
        try:
            import resource
            peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        except ImportError:
            peak_rss = None
        cpu_model = platform.processor()
        cpu_info = Path("/proc/cpuinfo")
        if cpu_info.exists():
            cpu_model = next((line.partition(":")[2].strip() for line in cpu_info.read_text().splitlines() if line.startswith("model name")), cpu_model)
        metrics = {"hardware": {"machine": platform.machine(), "processor": cpu_model, "logical_cpus": os.cpu_count()},
                   "os": platform.system(), "kernel": platform.release(), "elapsed_seconds": elapsed,
                   "cpu_seconds": time.process_time() - cpu_start, "process_peak_rss_native_units": peak_rss,
                   "rss_units": "KiB on Linux; bytes on macOS", "decisions_per_second": len(responses) / elapsed,
                   "decision_cycle_ms": {"median": statistics.median(latencies), "p95": percentile(.95), "p99": percentile(.99)},
                   "decision_cycle_samples_ms": latencies,
                   "definition": "rule selection + submit + next native prompt/projection; elapsed also includes resource verification/setup"}
        summary = {"ok": True, "engine": "real-ygopro-core", "scope": "explicit-normal-monster-pool",
                   "general_effect_duels_supported": False, "policy": "deterministic-rule-baseline-not-a-model",
                   "seed": seed, "turns": engine.turn, "decisions": len(responses), "events": len(engine.events),
                   "outcome": engine.outcome, "life_points": engine.life_points, "replay_verified": replay is not None,
                   "trace_sha256": hashlib.sha256(canonical_json(trace).encode()).hexdigest(), "metrics": metrics}
    return summary, trace
