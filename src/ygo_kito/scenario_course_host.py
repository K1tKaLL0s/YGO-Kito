"""Explicit host artifacts for the scenario course; preflight never samples.

The host owns paths, model inheritance and runtime qualification. Neither a
template nor a source registry can enable games without the pinned evidence.
"""
from copy import deepcopy
from dataclasses import asdict
import math
from pathlib import Path
import re
import secrets
import sqlite3
import hashlib
import io
import pickle

from .agent_registry import parse_ydk
from .build_contracts import BuildTask, DeckParts, digest
from .contracts import Versions
from .deck_intake import cutoff_timing
from .deck_profile import validate_deck_parts, validate_profile
from .group_initialization import validate_initialization_spec
from .implementation_identity import source_tree_snapshot
from .lora import AdapterConfig, ROLES
from .period_runtime import PeriodBuildAssets
from .training_pilot import _bytes, _check_qualification, _inside, _reference, aggregate_attempts
from .validation import ContractError, fields, integer, member, parse_json, text

TARGETS = {"2022-07": "2022-09-30", "2022-10": "2022-12-31", "2026-10": "2026-11-01"}


def validate_host_spec(value):
    d = fields(value, {"schema_version", "kind", "period_id", "selected_target_cutoff", "active_environment",
        "native_root", "source_group", "bootstrap_task", "duel_config", "adapter_configs", "available_cards",
        "timing_pilot", "pilot_pairs", "bots", "course", "state_root", "resume", "device"}, {"storage_envelope", "learning_stage", "initialization_mode"})
    integer(d["schema_version"], "course host schema", 1, 1)
    member(d["kind"], "course host kind", ("scenario-course-host-v1",))
    member(d["period_id"], "course period", tuple(TARGETS))
    if d["selected_target_cutoff"] != TARGETS[d["period_id"]]:
        raise ContractError("selected design cutoff must retain its confirmed date")
    if not isinstance(d["device"], str) or re.fullmatch(r"cpu|cuda:[0-7]", d["device"]) is None:
        raise ContractError("explicit CPU or indexed CUDA course device required")
    if type(d["resume"]) is not bool: raise ContractError("explicit resume boolean required")
    for key in ("native_root", "state_root"): text(d[key], "explicit " + key)
    stage = d.get("learning_stage", "lora_adaptation")
    member(stage, "learning stage", ("base", "lora_adaptation"))
    mode = d.get("initialization_mode", "source_group")
    member(mode, "initialization mode", ("source_group", "fresh"))
    if mode == "fresh":
        if d["source_group"] is not None or stage != "base":
            raise ContractError("fresh initialization requires explicit base stage and no source checkpoint")
    else:
        validate_initialization_spec(d["source_group"])
    for key in ("active_environment", "bootstrap_task", "duel_config", "adapter_configs", "available_cards", "course"):
        _reference(d[key])
    if d["timing_pilot"] is not None: _reference(d["timing_pilot"])
    if d.get("storage_envelope") is not None: _reference(d["storage_envelope"])
    pairs = d["pilot_pairs"]
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 100:
        raise ContractError("explicit bounded private pilot seed schedule required")
    seen_seeds = set()
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2: raise ContractError("pilot seed/policy pair required")
        for seed in pair: integer(seed, "pilot seed", 0, 2**32-8)
        if pair[0] in seen_seeds: raise ContractError("pilot physical seeds must be unique")
        seen_seeds.add(pair[0])
    if not isinstance(d["bots"], list) or not d["bots"]:
        raise ContractError("explicit nonempty qualified bot roster required")
    seen = set()
    from .agent_registry import identifier
    for b in d["bots"]:
        model_driver = b.get("driver") == "local_model_snapshot"
        if model_driver:
            fields(b, {"driver", "bot_id", "model", "migration", "deck", "source", "stage", "purpose",
                       "first_order", "coverage_label", "common_deck_evidence"}, {"policy_mode", "opponent_policy_seed"})
            _reference(b["model"])
            member(b["migration"], "explicit snapshot inference transfer", ("same-period-inference", "explicit-inference-migration"))
            if b["stage"] != "common-decks-bo3":
                raise ContractError("new model snapshots do not replace the existing-bot first stage")
            member(b.get("policy_mode", "greedy"), "model policy mode", ("greedy", "sample"))
            if b.get("policy_mode", "greedy") == "sample":
                integer(b.get("opponent_policy_seed"), "private opponent policy seed", 0, 2**32-8)
            elif b.get("opponent_policy_seed") is not None:
                raise ContractError("greedy model opponent cannot consume a sampling seed")
        else:
            fields(b, {"bot_id", "source_id", "executor_id", "lock", "installed_root", "mono", "audit", "qualification",
                "qualification_profile", "deck", "source", "session_seconds", "stage", "purpose", "first_order", "coverage_label"}, {"variant_root"})
        identifier(b["bot_id"])
        if b["bot_id"] in seen: raise ContractError("duplicate host bot ID")
        seen.add(b["bot_id"])
        member(b["source"], "bot source", ("engineering_fixture", "user_provided", "external_submission"))
        member(b["stage"], "course stage", ("bots-bo1", "common-decks-bo3"))
        member(b["purpose"], "course partition", ("train", "validation", "final_eval"))
        member(b["first_order"], "declared order policy", ("always_first", "always_second"))
        text(b["coverage_label"], "host declared coverage label")
        if model_driver:
            _reference(b["deck"])
            continue
        member(b["source_id"], "desktop source", ("ice", "pure"))
        for key in ("executor_id", "installed_root", "mono"): text(b[key], "explicit bot " + key)
        if not Path(b["mono"]).is_absolute(): raise ContractError("Mono requires an explicit absolute path")
        for key in ("lock", "audit", "qualification", "qualification_profile", "deck"): _reference(b[key])
        seconds = b["session_seconds"]
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 300:
            raise ContractError("bot session bound must be within (0,300] seconds")
        if "variant_root" in b:
            text(b["variant_root"], "explicit variant tree")
            if b["source_id"] != "pure": raise ContractError("desktop variant requires Pure")
    return deepcopy(d)


def _json(workspace, reference):
    _, raw = _bytes(workspace, reference)
    return parse_json(raw.decode("utf-8"))


def _state_root(workspace, value):
    state = (workspace / value).resolve()
    if not state.is_relative_to(workspace / ".cache") or state == workspace / ".cache":
        raise ContractError("private course state must stay in a dedicated workspace .cache directory")
    return state


def _resume_payload(state):
    """Read a self-contained course boundary and its existing index, no writes."""
    root = state / "course"
    if any((root / p).exists() for p in ("in-flight.json", "feedback-in-flight.json")):
        raise ContractError("uncertain in-flight course requires inspection, never automatic replay")
    pointer_path = root / "latest.json"
    if pointer_path.is_symlink(): raise ContractError("course checkpoint pointer symlinks unsupported")
    pointer = fields(parse_json(pointer_path.read_text()), {"path", "sha256", "revision", "active_seconds"})
    _reference({k: pointer[k] for k in ("path", "sha256")})
    if Path(pointer["path"]).name != pointer["path"]: raise ContractError("course checkpoint pointer escapes its root")
    integer(pointer["revision"], "checkpoint revision", 1)
    seconds = pointer["active_seconds"]
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        raise ContractError("checkpoint active duration is invalid")
    path = root / pointer["path"]
    if path.is_symlink(): raise ContractError("course checkpoint symlinks unsupported")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pointer["sha256"]: raise ContractError("course checkpoint bytes differ")
    import torch
    try:
        saved = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
    except (EOFError, pickle.UnpicklingError, RuntimeError, TypeError, ValueError) as error:
        raise ContractError("saved course tensor envelope is invalid") from error
    if (not isinstance(saved, dict) or saved.get("kind") != "ordered-course-game-boundary-v1" or
        saved.get("revision") != pointer["revision"] or saved.get("active_seconds") != pointer["active_seconds"]):
        raise ContractError("course pointer and complete boundary differ")
    index = state / "data-index/data-index.sqlite3"
    if index.is_symlink() or not index.is_file(): raise ContractError("existing private course index required")
    from .data_isolation import APPLICATION_ID
    with sqlite3.connect(index.as_uri()+"?mode=ro", uri=True) as db:
        if db.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
            raise ContractError("existing index application differs")
        logical = {table: db.execute('SELECT * FROM '+table+' ORDER BY 1,2').fetchall()
                   for table in ('datasets', 'seeds', 'artifacts', 'contents')}
    if digest(logical) != saved.get("data_index_sha256"):
        raise ContractError("checkpoint and existing data index differ")
    return saved


def _active_cutoff(period, selected, environment):
    fields(environment, {"release_cutoff", "banlist_effective", "banlist_section", "catalog", "releases", "banlist"})
    timing = cutoff_timing(environment["release_cutoff"])
    if not timing["cutoff_reached"] or environment["release_cutoff"] > selected:
        raise ContractError("active subset cutoff must be reached in JST and no later than the selected design cutoff")
    if period != "2026-10" and environment["release_cutoff"] != selected:
        raise ContractError("historical reference course retains its confirmed cutoff")
    return timing


def _availability(workspace, reference, assets):
    value = fields(_json(workspace, reference), {"schema_version", "card_ids"})
    integer(value["schema_version"], "availability schema", 1, 1)
    codes = value["card_ids"]
    if not isinstance(codes, list) or not codes: raise ContractError("explicit available card candidates required")
    for code in codes: integer(code, "available card ID", 1, 2**32-1)
    if len(codes) != len(set(codes)): raise ContractError("duplicate availability candidate")
    # Match the pinned core interpreter::is_load_script: normal tuners need no
    # Lua script; normal Pendulum monsters still do. Missing effects stay closed.
    script_names = {p.name for p in (assets.root / "engine-src/scripts").rglob("c*.lua") if p.is_file()}
    available, excluded = [], []
    for code in codes:
        row = assets.rows.get(code)
        reason = ("outside_period_catalog" if code not in assets.allowed_card_ids or row is None else
            "non_ocg_or_token" if not row["ot"] & 1 or row["type"] & 0x4000 else
            "forbidden" if assets.limits.get(row["alias"] or code, 3) == 0 else
            "script_missing" if (not row["type"] & 0x10 or row["type"] & 0x1000000) and f"c{code}.lua" not in script_names else None)
        if reason: excluded.append({"card_id": code, "reason": reason})
        else: available.append(code)
    if not available: raise ContractError("no actually available card remains")
    return sorted(available), excluded


def model_execution(models):
    return {"versions": models.versions(), "device": str(models.duel.device),
        "duel_vocabulary_sha256": models.duel.encoder.vocab_sha256,
        "duel_config_sha256": digest(asdict(models.duel.config)),
        "adapters": {r: {"enabled": s.enabled, "base_sha256": s.verify_base(), "config": s.config.to_dict()}
            for r, s in models.sessions.items()}}


def check_training_capacity(course, duel, adapters):
    from .training_scenarios import course_volume_requirements
    rule = course_volume_requirements(course)
    small_games = (rule.get("bo1_min", rule.get("minimum_bo1")) +
                   3 * rule.get("bo3_min", rule.get("minimum_bo3")))
    if len(duel.game_seeds) < small_games:
        raise ContractError("training seeds cannot cover the required complete BO1/BO3 worst-case small games")
    selected = next(a for a in adapters if a.role == "duel")
    if selected.max_updates < small_games:
        raise ContractError("duel LoRA update budget cannot cover the declared formal volume; proof max_updates=2 is insufficient")
    return small_games


def case_bindings(bots):
    from .scenario_course import bot_binding
    return {ident: bot_binding(b) for ident, b in bots.items() if b["purpose"] == "train"}


def check_timing_pilot(report, *, assets, execution, pilot_pairs, bots):
    """Accept a complete observed same-effective-group/device/period window."""
    if not isinstance(report, dict) or any(report.get(k) is not v for k, v in
        (("native_executed", True), ("csharp_execution_attempted", True), ("all_models_unchanged", True))):
        raise ContractError("actual unchanged-model native/bot timing evidence required")
    if (report.get("kind") != "course-group-bo1-timing-pilot-v1" or report.get("status") != "completed" or
        report.get("partition") != "timing_pilot" or report.get("training_updates") != 0 or
        report.get("formal_matches") != 0 or report.get("resources") != assets.receipt):
        raise ContractError("pilot is not a complete same-group timing window for these resources")
    if report.get("model_execution") != execution or report.get("period_context") != assets.period_context:
        raise ContractError("pilot effective model or active period differs from this course")
    current = source_tree_snapshot(Path(__file__).resolve().parent)
    if report.get("implementation") != current:
        raise ContractError("pilot implementation differs; preserve the old receipt and measure an explicit new window")
    if report.get("seed_schedule") != pilot_pairs or report.get("case_bindings") != case_bindings(bots):
        raise ContractError("pilot seeds or actual bot cases differ from this declared window")
    planned = report.get("planned_games")
    integer(planned, "pilot declared games", 1)
    if planned != len(pilot_pairs): raise ContractError("pilot declared window size differs")
    attempts = report.get("attempts")
    if not isinstance(attempts, list): raise ContractError("pilot attempt records required")
    observed = aggregate_attempts(attempts, planned=planned)
    if observed["volume_advice"] is None or observed != report.get("summary"):
        raise ContractError("pilot contains failed, unmeasured, partial or inconsistent attempts")
    if any(a.get("evidence_source") != "live-core-neural-policy-registered-bot" or a.get("case_id") not in bots for a in attempts):
        raise ContractError("pilot attempt lacks its actual course game adapter/case identity")
    return observed["completed_game_seconds"]["mean"]


class ScenarioCourseHost:
    def __init__(self, workspace, spec):
        self.workspace = Path(workspace).resolve(strict=True)
        self.spec = validate_host_spec(spec)
        self.spec_sha256 = digest(self.spec)
        self._prepared = None
        self._storage_envelope = None

    def _prepare(self, *, require_pilot=True):
        if digest(self.spec) != self.spec_sha256: raise ContractError("host configuration changed")
        d, w = self.spec, self.workspace
        self._storage_envelope = None
        if d.get("storage_envelope") is not None:
            from .storage_envelope import StorageEnvelope
            envelope_config = fields(_json(w, d["storage_envelope"]), set(),
                {"state_roots", "temporary_roots", "limit_bytes", "outside_bytes", "min_free_bytes", "safety_margin_bytes"})
            self._storage_envelope = StorageEnvelope(w, **envelope_config)
            self._storage_envelope.guard()  # Read-only; unknown outside usage fails closed.
        environment = _json(w, d["active_environment"])
        timing = _active_cutoff(d["period_id"], d["selected_target_cutoff"], environment)
        assets = PeriodBuildAssets(_inside(w, d["native_root"], directory=True), d["period_id"], environment, w,
            adapter_revision=5, evidence_source="user_supplied")
        task = BuildTask.from_dict(_json(w, d["bootstrap_task"])); assets.check_task(task)
        if task.goal["kind"] != "deck_constraints": raise ContractError("semantic bootstrap task required")
        raw_duel = _json(w, d["duel_config"])
        if not isinstance(raw_duel, dict) or not raw_duel.get("game_seeds"):
            raise ContractError("complete explicit course training seed schedule required")
        from .course_game_adapter import course_config_from_dict
        duel = course_config_from_dict(raw_duel)
        adapter_file = _json(w, d["adapter_configs"])
        if not isinstance(adapter_file, dict) or not isinstance(adapter_file.get("adapters"), list):
            raise ContractError("explicit four-role adapter configuration required")
        adapters = [AdapterConfig.from_dict(x) for x in adapter_file["adapters"]]
        if len(adapters) != 4 or {a.role for a in adapters} != set(ROLES):
            raise ContractError("exactly the existing four adapter roles required")
        available, excluded = _availability(w, d["available_cards"], assets)
        if not set(task.pool) <= set(available): raise ContractError("bootstrap task contains an unavailable card")
        from .scenario_course import validate_config
        course = validate_config(_json(w, d["course"]))
        if course.get("period_id") != d["period_id"] or course.get("training_seeds") != list(duel.game_seeds):
            raise ContractError("host/course period or training seed schedule differs")
        if (d["device"] == "cpu") != (course["allocated_gpu_count"] == 0):
            raise ContractError("explicit execution device differs from declared GPU allocation")
        formal_seeds = set(duel.game_seeds) | {p[0] for pairs in course["evaluation_pairs"].values() for p in pairs}
        if {p[0] for p in d["pilot_pairs"]} & formal_seeds:
            raise ContractError("pilot physical seeds overlap formal training/evaluation")
        state = _state_root(w, d["state_root"])
        if self._storage_envelope is not None:
            self._storage_envelope.require_controlled_directory(state / "course" if require_pilot else state)
        model_inputs = {k: v for k, v in d.items() if k not in ("timing_pilot", "course", "resume", "pilot_pairs", "state_root")}
        source_binding = {"host_model_inputs_sha256": digest(model_inputs), "period_context": deepcopy(assets.period_context),
            "selected_target_cutoff": d["selected_target_cutoff"],
            "resources": deepcopy(assets.receipt), "availability_artifact": deepcopy(d["available_cards"]),
            "available_ids_sha256": digest(available), "learning_stage": d.get("learning_stage", "lora_adaptation"),
            "basic_cb_stage": "after_construction",
            "construction_theme_ids": course.get("construction_theme_ids")}
        from .course_models import CourseModels
        saved = None
        if d["resume"]:
            saved = _resume_payload(state)
            if saved.get("binding", {}).get("config") != course:
                raise ContractError("saved course configuration differs")
            models = CourseModels.from_state(saved["models"], assets=assets, expected_binding=source_binding)
            if (models.builder.task.to_dict() != task.to_dict() or asdict(models.duel.config) != asdict(duel) or
                models.available_ids != tuple(available) or str(models.duel.device) != d["device"] or
                {r: c.to_dict() for r, c in models.adapter_configs.items()} != {a.role: a.to_dict() for a in adapters}):
                raise ContractError("self-contained saved model/task/config differs from explicit host artifacts")
        else:
            if d.get("initialization_mode", "source_group") == "source_group": _bytes(w, d["source_group"])
            models = CourseModels.initialize(task, assets, duel, adapters, workspace=w, initialization=d["source_group"],
                available_ids=available, source_binding=source_binding, device=d["device"])
        from .bot_deployment import BotSourceRegistry
        from .course_game_adapter import CourseBotRuntime
        bots = {}
        for b in d["bots"]:
            if b.get("driver") == "local_model_snapshot":
                from .model_opponents import FrozenDuelSnapshot, ModelOpponentRuntime
                from .scenario_course import validate_common_deck_evidence
                snapshot = FrozenDuelSnapshot.load(w, b["model"]["path"], b["model"]["sha256"])
                runtime = ModelOpponentRuntime(snapshot, b["bot_id"], source=b["source"], migration=b["migration"],
                    policy_mode=b.get("policy_mode", "greedy"))
                deck_path, deck_raw = _bytes(w, b["deck"])
                deck = DeckParts.from_dict(parse_ydk(deck_raw.decode("utf-8"))) if deck_path.suffix.lower() == ".ydk" else DeckParts.from_dict(parse_json(deck_raw.decode("utf-8")))
                validate_deck_parts(deck.to_dict(), assets.rows, assets.limits, allowed=assets.allowed_card_ids)
                evidence = validate_common_deck_evidence(b["common_deck_evidence"], deck, d["period_id"])
                # Static snapshot/resource admission only; this does not claim
                # strategy strength, a prior C# run, or a paid external model.
                runtime.assert_assets(assets)
                bots[b["bot_id"]] = {"runtime": runtime, "deck": deck, "common_deck_evidence": evidence,
                    **({"opponent_policy_seed": b["opponent_policy_seed"]} if "opponent_policy_seed" in b else {}),
                    **{k:b[k] for k in ("stage", "purpose", "first_order", "source", "coverage_label")}}
                continue
            registry = BotSourceRegistry(_json(w, b["lock"]), _inside(w, b["installed_root"], directory=True))
            runtime = CourseBotRuntime(registry=registry, workspace=w, source_id=b["source_id"], executor_id=b["executor_id"],
                audit=b["audit"], qualification=b["qualification"], qualification_profile=b["qualification_profile"],
                mono=b["mono"], opponent_id=b["bot_id"], source=b["source"], session_seconds=b["session_seconds"],
                variant_root=_inside(w, b["variant_root"], directory=True) if "variant_root" in b else None)
            deck_path, deck_raw = _bytes(w, b["deck"])
            deck = DeckParts.from_dict(parse_ydk(deck_raw.decode("utf-8"))) if deck_path.suffix.lower() == ".ydk" else DeckParts.from_dict(parse_json(deck_raw.decode("utf-8")))
            validate_deck_parts(deck.to_dict(), assets.rows, assets.limits, allowed=set(available))
            profile = _json(w, b["qualification_profile"]); validate_profile(profile)
            proof = _json(w, b["qualification"]); seat = integer(proof.get("actor_seat"), "qualified actor seat", 0, 1)
            h = assets.receipt["resources"]
            versions = Versions(assets.receipt["source_commits"]["core"], h["scripts"], h["cards"], h["client_protocol"],
                "native-private-knowledge-v5", "2026.10:" + h["banlist"])
            audit_path, _ = _bytes(w, b["audit"])
            options = dict(source_id=b["source_id"], native_root=assets.root, profile=profile, seat=1-seat, versions=versions,
                environment_id="course", opponent_id=b["bot_id"], source=b["source"], build_audit_path=audit_path,
                build_audit_sha256=b["audit"]["sha256"], mono=b["mono"], workspace=w, variant_root=runtime.variant_root,
                session_seconds=b["session_seconds"])
            adapter = registry.training_adapter(b["executor_id"], **options)
            case = {"source_id": b["source_id"], "executor_id": b["executor_id"], "actor_seat": seat, "qualification": b["qualification"]}
            if runtime.variant_root is not None: case["variant"] = True
            _check_qualification(w, case, profile, registry, adapter, dict(options, receipt=assets.receipt))
            qualified = {"main": profile["decks"][1-seat], "extra": profile.get("extras", [[], []])[1-seat], "side": profile.get("sides", [[], []])[1-seat]}
            from collections import Counter
            if any(Counter(qualified[z]) != Counter(getattr(deck, z)) for z in ("main", "extra", "side")):
                raise ContractError("course bot deck differs from its actual normal qualification")
            bots[b["bot_id"]] = {"runtime": runtime, "deck": deck, **{k: b[k] for k in ("stage", "purpose", "first_order", "source", "coverage_label")}}
        for stage in ("bots-bo1", "common-decks-bo3"):
            if not any(b["stage"] == stage and b["purpose"] == "train" for b in bots.values()):
                raise ContractError("both ordered training stages require actual qualified bots")
        if require_pilot and course.get("timing_basis") is None:
            _reference(d["timing_pilot"])
            execution = model_execution(models)
            if saved is not None:
                initial = saved.get("initial_model_execution")
                if (not isinstance(initial, dict) or {k: v for k,v in initial.items() if k != "versions"} !=
                    {k: v for k,v in execution.items() if k != "versions"} or set(initial.get("versions", {})) != set(ROLES) or
                    any(not isinstance(v, str) or re.fullmatch(r'[0-9a-f]{64}', v) is None for v in initial["versions"].values())):
                    raise ContractError("saved initial timing execution identity differs from this restored model layout")
                execution = initial
            mean = check_timing_pilot(_json(w, d["timing_pilot"]), assets=assets, execution=execution,
                pilot_pairs=d["pilot_pairs"], bots=bots)
            if course["pilot_mean_seconds"] != mean: raise ContractError("course mean must equal its pinned actual pilot window")
        if require_pilot:
            # An explicit user choice of the already confirmed slow branch
            # does not claim a fresh measurement, and requires no re-timing.
            check_training_capacity(course, duel, adapters)
        return models, assets, course, bots, state, excluded

    def preflight(self):
        report = {"schema_version": 1, "kind": "scenario-course-host-preflight", "status": "blocked",
            "native_executed": False, "csharp_executed": False, "training_updates": 0,
            "formal_training_success_verified": False, "host_config_sha256": self.spec_sha256, "blockers": []}
        try:
            self._prepared = self._prepare()
            models, assets, course, bots, _, excluded = self._prepared
            report.update(status="ready", period_id=self.spec["period_id"], selected_target_cutoff=self.spec["selected_target_cutoff"],
                active_period_context=deepcopy(assets.period_context), effective_models=models.versions(),
                bot_ids=list(bots), pilot_mean_seconds=course["pilot_mean_seconds"],
                timing_basis=deepcopy(course.get("timing_basis")), excluded_cards=excluded)
            report["whole_training_storage_peak_under_30GB_verified"] = False
            if self._storage_envelope is not None:
                report["storage_envelope"] = self._storage_envelope.audit()
        except (ContractError, OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError, sqlite3.Error) as error:
            self._prepared = None
            report["blockers"].append({"type": type(error).__name__, "message": str(error)})
        return report

    def run(self, *, purpose="train", max_matches=None, progress=None):
        report = self.preflight()
        if self._prepared is None: return report
        models, assets, config, bots, state, _ = self._prepared
        if not self.spec["resume"] and state.exists() and any(state.iterdir()):
            raise ContractError("existing private course state requires explicit resume")
        from .data_isolation import DataIndex
        from .scenario_course import ScenarioCourse
        course = ScenarioCourse(models, assets=assets,
            data_index=DataIndex(state / "data-index", storage_limits=config.get("data_index_storage")),
            config=config, state_root=state / "course", bots=bots, storage_envelope=self._storage_envelope)
        if self.spec["resume"]: course.restore_latest()
        if progress is not None:
            progress({"kind": "scenario-course-host-run", "status": "running", "native_executed": None,
                "csharp_executed": None, "formal_training_success_verified": False, "host_config_sha256": self.spec_sha256})
        result = course.run(max_matches=max_matches, purpose=purpose)
        desired = result.get("desired")
        status = "partial" if desired == "needs_inspection" else "paused" if desired == "paused" else "bounded_invocation_finished"
        return {"kind": "scenario-course-host-run", "status": status, "result": result,
            "native_executed": None, "csharp_executed": None, "formal_training_success_verified": False}

    def timing_pilot(self, *, progress=None):
        if self.spec["resume"]: raise ContractError("timing requires fresh source initialization, not formal resume")
        models, assets, config, bots, state, _ = self._prepare(require_pilot=False)
        from .data_isolation import DataIndex
        from .scenario_course import ScenarioCourse
        root = state / ("timing-pilot-" + secrets.token_hex(12))
        course = ScenarioCourse(models, assets=assets,
            data_index=DataIndex(root / "private-index", storage_limits=config.get("data_index_storage")),
            config=config, state_root=root / "course", bots=bots, storage_envelope=self._storage_envelope)
        if progress is not None:
            progress({"kind": "course-group-bo1-timing-pilot-v1", "status": "running", "native_executed": None,
                "csharp_execution_attempted": None, "training_updates": 0, "formal_matches": 0})
        return course.timing_pilot(self.spec["pilot_pairs"], progress=progress)


def prepare_course(workspace, spec):
    return ScenarioCourseHost(workspace, spec)
