"""Explicit CPU BO1 timing pilot over a completed, frozen project snapshot.

This is inference-only sampling, not training, group/LoRA restore, formal
evaluation, or BO3. All cases must pass the real registry's constructor audit
gate before any engine/child process is created. Fixtures are test-only.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import math
from pathlib import Path
import pickle
import platform
import re
from types import SimpleNamespace
import time

import torch

from .agent_registry import identifier
from .bot_deployment import BotSourceRegistry
from .build_contracts import digest
from .build_pipeline import BuildAssets
from .contracts import Versions
from .cpu_training import CpuTrainer, config_from_dict, cpu_name
from .deck_profile import validate_deck_parts, validate_profile
from .device import checkpoint_execution
from .duel_model import FEATURE_VERSION, parameter_digest
from .implementation_identity import assert_source_tree, source_tree_snapshot
from .native import NativeNormalEngine
from .opponent_pool import PublicSnapshotPolicy
from .validation import ContractError, fields, integer, member, text
from .windbot_projection import WindBotOpponent


def _sha(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ContractError("explicit lowercase SHA256 required")


def _reference(value):
    fields(value, {"path", "sha256"})
    text(value["path"], "workspace artifact path"); _sha(value["sha256"])


def _inside(workspace, value, *, directory=False):
    text(value, "workspace path")
    path = (workspace / value).resolve(strict=True)
    if not path.is_relative_to(workspace) or (not path.is_dir() if directory else not path.is_file()):
        raise ContractError("pilot artifacts must remain inside the explicit workspace")
    return path


def _bytes(workspace, reference):
    path = _inside(workspace, reference["path"])
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ContractError("pilot artifact checksum differs")
    return path, raw


def validate_pilot_spec(value):
    """Strict host configuration, with explicit resources; never RPC options."""
    d = fields(value, {"schema_version", "kind", "mode", "snapshot", "bot_sources", "cases",
                       "limits", "reserved_evaluation_seeds"})
    integer(d["schema_version"], "pilot schema", 1, 1)
    member(d["kind"], "pilot kind", ("cpu-frozen-model-bot-timing-pilot",))
    member(d["mode"], "pilot mode (BO3 match runner is not implemented)", ("bo1",))
    snapshot = fields(d["snapshot"], {"path", "sha256", "kind", "source_binding_sha256", "model_sha256", "migration"})
    _reference({k: snapshot[k] for k in ("path", "sha256")})
    member(snapshot["kind"], "snapshot kind (group/LoRA artifacts are not accepted)", ("completed-duel-checkpoint",))
    member(snapshot["migration"], "snapshot inference migration", ("explicit-frozen-inference",))
    _sha(snapshot["source_binding_sha256"]); _sha(snapshot["model_sha256"])
    bot = fields(d["bot_sources"], {"lock", "installed_root", "mono", "audits"}, {"variant_root"})
    _reference(bot["lock"]); text(bot["installed_root"], "installed source directory")
    if not Path(text(bot["mono"], "explicit Mono executable")).is_absolute():
        raise ContractError("Mono executable must be explicit and absolute")
    if not isinstance(bot["audits"], dict) or not bot["audits"]:
        raise ContractError("actual source build audit references required")
    for key, audit in bot["audits"].items():
        member(key, "bot audit source", ("ice", "pure", "variant")); _reference(audit)
    if "variant_root" in bot: text(bot["variant_root"], "exact desktop overlay directory")
    limits = fields(d["limits"], {"episode_seconds", "native_decision_limit"})
    seconds = limits["episode_seconds"]
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 300:
        raise ContractError("pilot episode limit must be finite and within (0, 300] seconds")
    integer(limits["native_decision_limit"], "pilot native decision limit", 1, 3000)
    reserved = d["reserved_evaluation_seeds"]
    if not isinstance(reserved, list) or len(reserved) != len(set(reserved)):
        raise ContractError("reserved evaluation seeds must be a unique array")
    for seed in reserved: integer(seed, "reserved evaluation seed", 0, 2**32 - 8)
    if not isinstance(d["cases"], list) or not d["cases"]:
        raise ContractError("explicit nonempty pilot case list required")
    seen_ids, seen_seeds = set(), set(reserved)
    for case in d["cases"]:
        fields(case, {"case_id", "profile", "qualification", "actor_seat", "source_id", "executor_id", "seeds", "coverage", "evidence_source"},
               {"variant"})
        identifier(case["case_id"])
        if case["case_id"] in seen_ids: raise ContractError("duplicate pilot case ID")
        seen_ids.add(case["case_id"])
        _reference(case["profile"]); _reference(case["qualification"])
        integer(case["actor_seat"], "pilot actor seat", 0, 1)
        member(case["source_id"], "complete desktop bot source", ("ice", "pure"))
        text(case["executor_id"], "exact fixed-source Executor")
        member(case["evidence_source"], "deck evidence source", ("engineering_fixture", "user_provided", "external_submission"))
        if "variant" in case and (case["variant"] is not True or case["source_id"] != "pure" or "variant_root" not in bot):
            raise ContractError("variant requires the explicit Pure desktop overlay")
        audit_key = "variant" if case.get("variant") else case["source_id"]
        if audit_key not in bot["audits"]: raise ContractError("case lacks its actual source audit")
        if not isinstance(case["coverage"], list) or not case["coverage"] or len(case["coverage"]) != len(set(case["coverage"])):
            raise ContractError("case requires unique declared coverage labels")
        for label in case["coverage"]:
            if len(text(label, "coverage label")) > 128: raise ContractError("coverage label exceeds its bound")
        if not isinstance(case["seeds"], list) or not case["seeds"]: raise ContractError("explicit pilot seed pairs required")
        for pair in case["seeds"]:
            fields(pair, {"game_seed", "policy_seed"})
            for key in pair: integer(pair[key], "pilot " + key, 0, 2**32 - 8)
            if pair["game_seed"] in seen_seeds:
                raise ContractError("pilot game seed overlaps another case or reserved evaluation")
            seen_seeds.add(pair["game_seed"])
    return deepcopy(d)


def _check_qualification(workspace, case, profile, registry, adapter, adapter_options):
    """Verify an existing real normal-game receipt against today's exact host.

    A qualification's original adapter binding already includes the complete
    Python source map, source/assembly/audit/tools/catalog/profile. Reconstruct
    that *same* binding read-only; do not manufacture a new qualification from
    a constructor audit, or silently accept a receipt from older source bytes.
    """
    _, raw = _bytes(workspace, case["qualification"])
    from .validation import parse_json
    report = fields(parse_json(raw.decode("utf-8")), {"schema_version", "kind", "context", "resources",
        "source_lock_sha256", "inventory_sha256", "actor_profile_sha256", "variant", "actor_seat", "rows", "counts",
        "native_executed", "csharp_executed", "normal_duel_verified", "historical_qualified", "strength_qualified",
        "training_updates", "normal_game_seconds", "csharp_session_wall_seconds", "bound_scope", "all_selected_normal_verified"})
    if (type(report["schema_version"]) is not int or report["schema_version"] != 1 or
            report["kind"] != "all-source-bot-engineering-qualification-results" or
            report["context"] != "current-pinned-2026.10-engineering-resources-not-historical-course" or
            report["resources"] != adapter_options["receipt"] or report["source_lock_sha256"] != digest(registry.lock) or
            report["inventory_sha256"] != registry.inventory["inventory_sha256"] or
            report["actor_seat"] != case["actor_seat"] or report["native_executed"] is not True or
            report["csharp_executed"] is not True or report["normal_duel_verified"] is not True or
            type(report["training_updates"]) is not int or report["training_updates"] != 0 or
            report["historical_qualified"] is not False or report["strength_qualified"] is not False):
        raise ContractError("pilot requires a real, same-resource normal bot qualification, not a plan or fixture")
    seconds = report["normal_game_seconds"]
    if (type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 300 or
            report["csharp_session_wall_seconds"] != seconds):
        raise ContractError("qualification lacks its exact audited session limit")
    definitions = [r for r in registry.inventory["origins"] if r["source_id"] == case["source_id"] and
                   (r["bot_id"] == case["executor_id"] or r["class_name"] == case["executor_id"])]
    if len(definitions) != 1: raise ContractError("qualification Executor is absent or ambiguous")
    definition = definitions[0]
    if not isinstance(report["rows"], list): raise ContractError("qualification rows must be an array")
    variant = None
    if case.get("variant"):
        from .bot_overlay import runtime_overlay_identity
        variant = runtime_overlay_identity(registry.lock, adapter_options["variant_root"])
    rows = [r for r in report["rows"] if isinstance(r, dict) and r.get("runtime_source_id") == case["source_id"] and
            r.get("runtime_executor_id") == definition["class_name"] and r.get("variant") == variant and
            (variant is not None or r.get("bot_id") == definition["bot_id"])]
    if len(rows) != 1: raise ContractError("qualification lacks this exact bot/source/variant")
    row = rows[0]
    required = {"bot_id", "status", "list_legal", "runtime_candidate", "normal_duel_verified", "native_executed", "csharp_executed",
                "profile_sha256", "deck_sha256", "binding_sha256", "decisions", "bot_decisions", "outcome", "turns", "trajectory_sha256"}
    if required - row.keys():
        raise ContractError("qualification selected row missing fields: " + ", ".join(sorted(required - row.keys())))
    if (row["status"] != "normal_game_verified" or any(row[k] is not True for k in
            ("list_legal", "runtime_candidate", "normal_duel_verified", "native_executed", "csharp_executed")) or
            row["profile_sha256"] != digest(profile) or row["deck_sha256"] != adapter.binding["opponent_deck_sha256"]):
        raise ContractError("qualification is not a completed normal game for this exact profile and opponent deck")
    integer(row["bot_decisions"], "qualified actual bot decisions", 1)
    _sha(row["bot_id"])
    integer(row["decisions"], "qualified actual decisions", row["bot_decisions"])
    integer(row["turns"], "qualified terminal turns", 1)
    fields(row["outcome"], {"winner", "reason_code"})
    integer(row["outcome"]["winner"], "qualified winner", 0, 2)
    integer(row["outcome"]["reason_code"], "qualified outcome reason", 0, 255)
    _sha(row["trajectory_sha256"]); _sha(row["binding_sha256"])
    options = {k: v for k, v in adapter_options.items() if k != "receipt"}
    options.update(environment_id="bot-current-engineering-qualification", opponent_id="qual-" + row["bot_id"][:32],
                   source="engineering_fixture", session_seconds=seconds)
    qualified_adapter = registry.training_adapter(case["executor_id"], **options)
    if not isinstance(qualified_adapter, WindBotOpponent) or digest(qualified_adapter.binding) != row["binding_sha256"]:
        raise ContractError("qualification runtime binding changed (source/implementation/audit/tools/profile)")
    qualified_adapter.assert_runtime(options["native_root"], profile, case["actor_seat"])


def load_actor_snapshot(workspace, spec, receipt):
    """Load exact bytes once, inference only; no optimizer or RNG restoration."""
    _, raw = _bytes(workspace, spec)
    try:
        state = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
        fields(state, {"schema_version", "role", "boundary", "config", "binding", "card_ids", "vocab_sha256", "model",
                       "optimizer", "scheduler", "updates", "episode_cursor", "model_sha256", "rng"}, {"execution", "device_rng"})
        checkpoint_execution(state, requested="cpu")
        binding = fields(state["binding"], {"feature_version", "resources", "source_commits", "profile_sha256"},
                         {"python_implementation_sha256", "python", "torch", "registered_opponent_pool", "period_context", "versions"})
        if (type(state["schema_version"]) is not int or state["schema_version"] != 1 or state["role"] != "duel" or
                state["boundary"] != "complete-episode" or digest(binding) != spec["source_binding_sha256"] or
                binding["feature_version"] != FEATURE_VERSION or binding["resources"] != receipt["resources"] or
                binding["source_commits"] != receipt["source_commits"] or state["model_sha256"] != spec["model_sha256"]):
            raise ContractError("pilot requires an exact completed duel snapshot with compatible resources/features")
        config = config_from_dict(state["config"])
        if config.curriculum is not None:
            raise ContractError("scripted curriculum checkpoints are outside this unscripted pilot")
        integer(state["updates"], "snapshot completed updates", 1, len(config.game_seeds))
        integer(state["episode_cursor"], "snapshot cursor", state["updates"], state["updates"])
        if not isinstance(state["model"], dict) or not state["model"] or any(
                not isinstance(v, torch.Tensor) or v.dtype != torch.float32 or not torch.isfinite(v).all()
                for v in state["model"].values()):
            raise ContractError("snapshot model parameters must be finite FP32 tensors")
        # The existing frozen loader preserves CPU RNG and strictly loads all
        # model weights. No freshly initialized model may serve as a fallback.
        policy = PublicSnapshotPolicy(0, None, state)
        provenance = {"kind": spec["kind"], "artifact_sha256": spec["sha256"], "model_sha256": policy.model_sha256,
            "source_binding_sha256": digest(binding), "source_resources": deepcopy(binding["resources"]),
            "source_commits": deepcopy(binding["source_commits"]),
            "source_python_implementation_sha256": binding.get("python_implementation_sha256"),
            "source_period_context": deepcopy(binding.get("period_context")),
            "vocab_sha256": policy.encoder.vocab_sha256, "feature_version": FEATURE_VERSION,
            "completed_updates": state["updates"], "boundary": state["boundary"], "device": "cpu",
            "migration": spec["migration"], "source_training_ability_verified": False}
        return policy, config, provenance
    except ContractError:
        raise
    except (OSError, EOFError, pickle.UnpicklingError, KeyError, TypeError, ValueError, RuntimeError) as error:
        raise ContractError("pilot snapshot/model state is incompatible") from error


@dataclass(frozen=True)
class _SamplingView:
    """Only fields used by validation sampling, independent of training caps."""
    model: object
    actor_seat: int
    game_seeds: tuple
    episode_seconds: float
    native_decision_limit: int
    curriculum: None = None


class _ObservedEngine(NativeNormalEngine):
    """Normal Python API instrumentation; no binding or raw buffer access."""
    def __init__(self, *args, pilot_observations, **kwargs):
        self._pilot = pilot_observations
        self._pilot["engine_constructor_started"] = True
        super().__init__(*args, **kwargs)
        self._pilot["engine_constructor_completed"] = True

    def next_decision(self):
        request = super().next_decision()
        if request is not None:
            key = str(request.observation.observer) + ":" + str(request.prompt.message)
            self._pilot["seat_prompt_counts"][key] += 1
            self._pilot["decision_windows"] += 1
            if self._pilot["actual_first_player"] is None and request.observation.turn == 1:
                self._pilot["actual_first_player"] = request.observation.turn_player
        return request


def distribution(values):
    """Observed values only. Percentiles use linear interpolation."""
    if not values: return {"count": 0, "mean": None, "min": None, "p50": None, "p95": None, "p99": None, "max": None}
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
        raise ContractError("timings must be finite nonnegative observations")
    ordered = sorted(values)
    def percentile(q):
        offset = (len(ordered) - 1) * q
        low = math.floor(offset); high = math.ceil(offset)
        return ordered[low] + (ordered[high] - ordered[low]) * (offset - low)
    return {"count": len(values), "mean": sum(values) / len(values), "min": ordered[0],
            "p50": percentile(.5), "p95": percentile(.95), "p99": percentile(.99), "max": ordered[-1]}


def aggregate_attempts(attempts, *, planned):
    integer(planned, "declared pilot games", 0)
    if not isinstance(attempts, (list, tuple)) or len(attempts) > planned:
        raise ContractError("pilot attempt count exceeds the declared window")
    complete = [a for a in attempts if a["status"] == "completed"]
    game_times = [a["game_seconds"] for a in complete if type(a.get("game_seconds")) in (int, float)
                  and math.isfinite(a["game_seconds"]) and a["game_seconds"] > 0]
    result = {"planned_bo1": planned, "attempted_bo1": len(attempts), "completed_bo1": len(complete),
              "failed_or_uncertain_bo1": len(attempts) - len(complete), "unattempted_bo1": planned - len(attempts),
              "completed_bo3": 0, "counted_as_formal_games": 0,
              "completed_game_seconds": distribution(game_times), "unmeasured_completed_bo1": len(complete) - len(game_times),
              "completed_game_wall_seconds": distribution([a["wall_seconds"] for a in complete]),
              "all_attempt_wall_seconds": distribution([a["wall_seconds"] for a in attempts]),
              "actor_inference_ms": distribution([v for a in complete for v in a["actor_inference_ms"]]),
              "coverage": {}, "volume_advice": None, "volume_advice_requires_complete_declared_window": True}
    for row in attempts:
        for label in row["declared_coverage"]:
            counts = result["coverage"].setdefault(label, {"attempted": 0, "completed": 0, "failed_or_uncertain": 0})
            counts["attempted"] += 1
            counts["completed" if row["status"] == "completed" else "failed_or_uncertain"] += 1
    if (complete and len(complete) == len(attempts) == planned and len(game_times) == len(complete)):
        from .training_scenarios import volume_requirements
        result["volume_advice"] = {"requirements": volume_requirements(result["completed_game_seconds"]["mean"]),
            "timing_source": "CpuTrainer.sample_episode summary.elapsed_seconds",
            "scope": "these completed CPU snapshot/cases only; failed attempts retained separately",
            "representative_of_all_scenarios": False, "pilot_counts_toward_formal_volume": False}
    return result


class TrainingPilot:
    def __init__(self, workspace, native_root, spec):
        self.workspace = Path(workspace).resolve(strict=True)
        self.native_root = _inside(self.workspace, str(native_root), directory=True)
        self.spec = validate_pilot_spec(spec)
        self.spec_sha256 = digest(self.spec)
        self._prepared = None
        self._has_run = False

    def _prepare(self):
        if digest(self.spec) != self.spec_sha256: raise ContractError("pilot configuration changed after validation")
        package = Path(__file__).resolve().parent
        sources = source_tree_snapshot(package)
        assets = BuildAssets(self.native_root)  # Integrity + readonly CDB, no CDLL/game.
        policy, config, provenance = load_actor_snapshot(self.workspace, self.spec["snapshot"], assets.receipt)
        pilot_seeds = {p["game_seed"] for case in self.spec["cases"] for p in case["seeds"]}
        if pilot_seeds & set(config.game_seeds): raise ContractError("pilot seed overlaps snapshot training seeds")
        if set(self.spec["reserved_evaluation_seeds"]) & set(config.game_seeds):
            raise ContractError("reserved evaluation seed overlaps snapshot training seeds")
        bot = self.spec["bot_sources"]
        _, lock_raw = _bytes(self.workspace, bot["lock"])
        from .validation import parse_json
        registry = BotSourceRegistry(parse_json(lock_raw.decode("utf-8")), _inside(self.workspace, bot["installed_root"], directory=True))
        h = assets.receipt["resources"]
        versions = Versions(assets.receipt["source_commits"]["core"], h["scripts"], h["cards"],
                            h["client_protocol"], "native-private-knowledge-v5", "2026.10:" + h["banlist"])
        prepared = []
        for case in self.spec["cases"]:
            _, raw = _bytes(self.workspace, case["profile"])
            profile = parse_json(raw.decode("utf-8")); validate_profile(profile)
            if profile.get("adapter_revision") != 5:
                raise ContractError("pilot requires explicit v5 legal observations")
            for seat in (0, 1):
                parts = {z: profile[k][seat] for z, k in (("main", "decks"), ("extra", "extras"), ("side", "sides"))}
                validate_deck_parts(parts, assets.rows, assets.limits)
                if any(c not in policy.encoder.index for codes in parts.values() for c in codes):
                    raise ContractError("pilot card absent from frozen model vocabulary")
            audit = bot["audits"]["variant" if case.get("variant") else case["source_id"]]
            audit_path, _ = _bytes(self.workspace, audit)
            adapter_options = dict(source_id=case["source_id"],
                native_root=self.native_root, profile=profile, seat=1-case["actor_seat"], versions=versions,
                environment_id="pilot", opponent_id=case["case_id"], source=case["evidence_source"],
                build_audit_path=audit_path, build_audit_sha256=audit["sha256"], mono=bot["mono"], workspace=self.workspace,
                variant_root=_inside(self.workspace, bot["variant_root"], directory=True) if case.get("variant") else None,
                session_seconds=self.spec["limits"]["episode_seconds"])
            adapter = registry.training_adapter(case["executor_id"], **adapter_options)
            if not isinstance(adapter, WindBotOpponent): raise ContractError("actual audited typed bot adapter required")
            adapter.assert_runtime(self.native_root, profile, case["actor_seat"])
            _check_qualification(self.workspace, case, profile, registry, adapter, dict(adapter_options, receipt=assets.receipt))
            prepared.append((case, profile, adapter))
        assert_source_tree(package, sources)
        return policy, config, provenance, prepared, sources, assets.receipt

    def preflight(self):
        """Read/validate only; does not launch Mono, load native CDLL or sample."""
        report = {"schema_version": 1, "kind": "cpu-bo1-timing-pilot", "status": "blocked",
                  "spec_sha256": self.spec_sha256, "mode": "bo1", "device": "cpu", "training_updates": 0,
                  "partition": "timing_pilot", "optimizer_restored": False, "training_rng_restored": False,
                  "historical_pool_verified": False,
                  "native_executed": False, "csharp_execution_attempted": False, "formal_games": 0,
                  "bo3": {"supported": False, "reason": "no complete match/sideboarding/start-order runner"},
                  "blockers": [], "scope": "one explicit standalone snapshot and listed cases; no group/LoRA/GPU timing"}
        try:
            self._prepared = self._prepare()
            _, _, provenance, cases, sources, resources = self._prepared
            report.update(status="ready", model=provenance, implementation={"source_tree": sources, "sha256": digest(sources)},
                resources=resources, planned_bo1=sum(len(c["seeds"]) for c, _, _ in cases),
                cases=[{"case_id": c["case_id"], "profile_sha256": digest(p), "actor_seat": c["actor_seat"],
                        "qualification_sha256": c["qualification"]["sha256"],
                        "declared_coverage": c["coverage"], "opponent_binding": deepcopy(a.binding),
                        "games": len(c["seeds"])} for c, p, a in cases])
        except (ContractError, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            self._prepared = None
            report["blockers"].append({"stage": "all_cases_preflight", "error_type": type(error).__name__, "error": str(error)})
        return report

    def run(self, *, progress=None):
        """One inference-only pass; no retries. First error stops with partial data."""
        if self._has_run: raise ContractError("pilot already attempted; no implicit repeat or retry")
        self._has_run = True
        report = self.preflight()
        report["attempts"] = []
        if self._prepared is None: return report
        policy, config, provenance, cases, sources, resources = self._prepared
        report.update(status="running", started_utc=datetime.now(timezone.utc).isoformat(),
            hardware={"platform": platform.platform(), "cpu": cpu_name(), "torch": str(torch.__version__),
                      "torch_threads": torch.get_num_threads(), "cuda_used": False},
            timing_scope={"game_seconds": "sampler summary.elapsed_seconds: model/engine/bot lifecycle through terminal, before context cleanup",
                          "wall_seconds": "attempt including integrity rechecks, game and managed cleanup; initial preflight/model load excluded",
                          "volume_advice_uses": "game_seconds", "device_scope": "CPU standalone snapshot, not GPU/group/LoRA/BO3"})
        if progress is not None: progress(deepcopy(report))
        for case, profile, adapter in cases:
            for pair in case["seeds"]:
                observations = {"engine_constructor_started": False, "engine_constructor_completed": False, "actual_first_player": None,
                                "decision_windows": 0, "seat_prompt_counts": Counter()}
                row = {"case_id": case["case_id"], "seed_pair_sha256": digest(pair), "status": "failed_or_uncertain",
                    "declared_coverage": case["coverage"], "actor_seat": case["actor_seat"], "actor_inference_ms": [],
                    "retry_allowed": False, "game_seconds": None}
                started = time.perf_counter()
                try:
                    assert_source_tree(Path(__file__).resolve().parent, sources)
                    _bytes(self.workspace, self.spec["snapshot"]); _bytes(self.workspace, case["profile"])
                    _bytes(self.workspace, case["qualification"])
                    if parameter_digest(policy.model) != provenance["model_sha256"]:
                        raise ContractError("frozen pilot actor changed")
                    adapter.assert_runtime(self.native_root, profile, case["actor_seat"])
                    view = _SamplingView(config.model, case["actor_seat"], config.game_seeds,
                        self.spec["limits"]["episode_seconds"], self.spec["limits"]["native_decision_limit"])
                    sampler = SimpleNamespace(model=policy.model, encoder=policy.encoder, config=view, updates=provenance["completed_updates"])
                    def factory(*args, **kwargs):
                        return _ObservedEngine(*args, pilot_observations=observations, **kwargs)
                    # Persist dispatch before entering any native/managed-room
                    # context. If the process disappears, execution is unknown,
                    # never falsely reported as a fresh preflight failure.
                    report["in_flight"] = {"case_id": case["case_id"], "seed_pair_sha256": digest(pair)}
                    report["native_executed"] = None
                    report["csharp_execution_attempted"] = None
                    if progress is not None: progress(deepcopy(report))
                    episode = CpuTrainer.sample_episode(sampler, self.native_root, profile, purpose="validation",
                        seed=pair["game_seed"], policy_seed=pair["policy_seed"], opponent_adapter=adapter, engine_factory=factory)
                    if parameter_digest(policy.model) != provenance["model_sha256"]:
                        raise ContractError("pilot actor changed during inference-only sampling")
                    summary = episode["summary"]
                    game_seconds = summary.get("elapsed_seconds")
                    if (type(game_seconds) not in (int, float) or not math.isfinite(game_seconds) or game_seconds <= 0):
                        raise ContractError("completed pilot game lacks a positive finite sampler elapsed_seconds")
                    row.update(status="completed", outcome=summary["outcome"], turns=summary["turns"],
                        game_seconds=game_seconds,
                        actor_samples=summary["actor_samples"], native_decisions=summary["native_decisions"],
                        actor_inference_ms=summary["actor_inference_ms"], trajectory_sha256=summary["trajectory_sha256"])
                    # Never publish episode steps, private replay, engine seed,
                    # selection key, actions or hidden state.
                    del episode
                except (ContractError, OSError, ValueError, TypeError, RuntimeError, KeyboardInterrupt) as error:
                    row["error"] = {"type": type(error).__name__, "message": str(error)}
                row["wall_seconds"] = time.perf_counter() - started
                row["observations"] = dict(observations, seat_prompt_counts=dict(observations["seat_prompt_counts"]))
                first = observations["actual_first_player"]
                row["actual_start_order"] = None if first is None else ("first" if first == case["actor_seat"] else "second")
                report["attempts"].append(row)
                report.pop("in_flight", None)
                constructed = any(a["observations"]["engine_constructor_completed"] for a in report["attempts"])
                constructor_started = any(a["observations"]["engine_constructor_started"] for a in report["attempts"])
                report["native_executed"] = True if constructed else None if constructor_started else False
                report["csharp_execution_attempted"] = (True if any(a["status"] == "completed" for a in report["attempts"])
                    else None if constructor_started else False)
                report["summary"] = aggregate_attempts(report["attempts"], planned=report["planned_bo1"])
                if progress is not None: progress(deepcopy(report))
                if row["status"] != "completed":
                    report["status"] = "partial"
                    report["model_unchanged"] = parameter_digest(policy.model) == provenance["model_sha256"]
                    return report
        report["status"] = "completed"
        report["model_unchanged"] = parameter_digest(policy.model) == provenance["model_sha256"]
        return report


def prepare_pilot(workspace, native_root, spec):
    return TrainingPilot(workspace, native_root, spec)
