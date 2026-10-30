"""Host-owned ordered course over actual model/core/bot adapters.

Complete matches and actual small games have separate ledgers. A checkpoint is
legal only between small games; an interrupted in-flight transaction requires
inspection, never automatic replay. Pilots and held-out games earn no training
volume. This module does not launch resources or grant paid-run permission.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sqlite3
import shutil
import time
import fcntl

import torch

from .agent_registry import identifier
from .build_contracts import BuildTask, DeckParts, digest
from .course_game_adapter import CourseBotRuntime, CourseGameAdapter, REAL_GAME_SOURCE
from .data_isolation import DataIndex
from .duel_model import parameter_digest
from .implementation_identity import source_tree_snapshot
from .match_runner import (FirstOrderPolicy, GameResult, MatchParticipant, MatchRules,
                           MatchState, ModelSideboardPolicy, keep_side)
from .training_scenarios import (check_2610_rates, volume_requirements, validate_timing_basis,
                                 course_volume_requirements, course_volume_met)
from .validation import ContractError, canonical_json, fields, integer


def validate_config(value):
    d = fields(value, {"course_id", "period_id", "mode", "pilot_mean_seconds", "training_seeds",
        "evaluation_pairs", "matches_per_invocation", "wall_seconds", "allocated_gpu_count", "fixed_deck",
        "initial_first", "evaluation_matches", "opponent_side"}, {"timing_basis", "checkpoint_policy", "data_index_storage", "construction_theme_ids", "training_record_offset"})
    identifier(d["course_id"])
    if d["period_id"] not in ("2022-07", "2022-10", "2026-10"):
        raise ContractError("explicit supported period required")
    if d["mode"] != ("autonomous" if d["period_id"] == "2026-10" else "fixed_theme"):
        raise ContractError("autonomous selection is scoped to 2610; historical themes stay fixed")
    if d["fixed_deck"] is not None:
        raise ContractError("reference decks belong to independent evaluation, never the learner")
    if d["mode"] == "fixed_theme" and d.get("construction_theme_ids") != ["setcode-181"]:
        raise ContractError("historical construction requires the Pearl theme and model-generated deck")
    integer(d.get("training_record_offset",0), "archived prior-flow record offset",0,1000000)
    checkpoint_policy(d.get("checkpoint_policy"))
    if "data_index_storage" in d:
        from .data_isolation import validate_storage_limits
        validate_storage_limits(d["data_index_storage"])
    if d["pilot_mean_seconds"] is not None: volume_requirements(d["pilot_mean_seconds"])
    if d.get("timing_basis") is not None:
        validate_timing_basis(d["timing_basis"])
        course_volume_requirements(d)
    seeds = d["training_seeds"]
    if not isinstance(seeds, list) or not seeds or len(seeds) != len(set(seeds)):
        raise ContractError("explicit unique complete course training seed schedule required")
    for seed in seeds: integer(seed, "course training seed", 0, 2**32-8)
    pairs = fields(d["evaluation_pairs"], {"validation", "final_eval"})
    occupied = set(seeds)
    for purpose in ("validation", "final_eval"):
        if not isinstance(pairs[purpose], list): raise ContractError("explicit held-out pairs required")
        for pair in pairs[purpose]:
            if not isinstance(pair, list) or len(pair) != 2: raise ContractError("seed and policy-seed pair required")
            for seed in pair: integer(seed, "held-out seed", 0, 2**32-8)
            if pair[0] in occupied: raise ContractError("physical seed crosses or repeats a partition")
            occupied.add(pair[0])
    integer(d["matches_per_invocation"], "bounded invocation matches", 1, 100)
    integer(d["evaluation_matches"], "declared frozen evaluation matches", 1, 100000)
    integer(d["allocated_gpu_count"], "host allocated GPU count", 0, 8)
    seconds = d["wall_seconds"]
    allocation = 20 if d["period_id"] == "2026-10" else 25
    if (type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0 or
            seconds * max(1, d["allocated_gpu_count"]) > allocation * 3600):
        raise ContractError("course wall allocation exceeds the unchanged period budget")
    if d["initial_first"] != "alternate" or d["opponent_side"] != "keep_original_baseline":
        raise ContractError("explicit supported opening-order and opponent-side baseline required")
    return json.loads(canonical_json(d))


def index_identity(index):
    """Logical DB identity, independent of SQLite page/WAL layout."""
    with sqlite3.connect(index.path) as db:
        return digest({table: db.execute("SELECT * FROM " + table + " ORDER BY 1,2").fetchall()
                       for table in ("datasets", "seeds", "artifacts", "contents")})


def _exclusive_json(path, value):
    with Path(path).open("x", encoding="utf-8") as output:
        output.write(canonical_json(value) + "\n"); output.flush(); os.fsync(output.fileno())


def current_course_records(saved):
    """The corrected-flow boundary archives old failures without relabeling them."""
    records = saved["records"]
    offset = saved.get("binding", {}).get("config", {}).get("training_record_offset", 0)
    integer(offset, "saved corrected-flow record offset", 0, len(records))
    return records[offset:]


def _legacy_compute_acknowledgment(record, cursor):
    receipts = record.get("receipts", [])
    receipt = receipts[-1] if receipts else {}
    before, after = receipt.get("before", {}), receipt.get("after", {})
    if (record.get("purpose") != "train" or record.get("complete") is not False or
            record.get("winner") is not None or not record.get("games") or
            any(g.get("terminal") is not False or g.get("completed") is not False or
                g.get("winner_participant_id") is not None for g in record["games"][-1:]) or
            receipt.get("status") != "failed_or_uncertain" or
            receipt.get("error") != {"type": "NativeError", "message": "CPU sample budget exhausted; no terminal reward/update claimed"} or
            receipt.get("sample_completed") is not False or receipt.get("model_update_started") is not False or
            receipt.get("model_update_completed") is not False or receipt.get("retry_allowed") is not False or
            receipt.get("observations", {}).get("constructor_completed") is not True or
            receipt.get("observed_sampler_cursor") != cursor or receipt.get("observed_sampler_updates") != cursor or
            before.get("training_cursor") != cursor or after.get("training_cursor") != cursor or
            any(key not in before or key not in after or before[key] != after[key]
                for key in ("model_sha256", "lora", "observed_optimizer_step_max"))):
        raise ContractError("legacy attempt is not a proven pre-update compute truncation; no replay or skip authorized")
    return {"match_id": record["match_id"], "record_sha256": digest(record),
        "sampling_attempt_cursor": cursor, "next_sampling_attempt_cursor": cursor + 1,
        "kind": "explicit-legacy-compute-truncation-acknowledgment-v1",
        "original_record_preserved": True, "partial_game_available": False,
        "model_update_claimed": False, "automatic_replay": False}


def _saved_successful_duel_updates(state):
    if "duel" in state["adapters"]:
        return state["adapters"]["duel"]["updates"]
    updates = state["cursors"]["duel_updates"]
    if state["cursors"]["duel_episodes"] != updates:
        raise ContractError("saved duel episode cursor is not an actual update boundary")
    return updates


def migrate_training_attempt_state(saved, *, acknowledged_compute_truncations=()):
    """Explicit metadata-only migration; original records are never rewritten.

    The old sampler advanced only on a complete sample. An old incomplete
    transaction cannot be inferred safe from its cursor. Only the exact old
    budget error with observed unchanged update/model evidence may be
    acknowledged as a consumed attempt; all other failures remain blocked.
    """
    if "training_attempts" in saved:
        raise ContractError("course already has an explicit training-attempt ledger")
    if not isinstance(acknowledged_compute_truncations, (tuple, list)) or len(set(acknowledged_compute_truncations)) != len(acknowledged_compute_truncations):
        raise ContractError("explicit unique legacy compute-truncation match IDs required")
    model_state = saved["models"]
    cursor = _saved_successful_duel_updates(model_state)
    integer(cursor, "legacy successful sample cursor", 0)
    unresolved = [r for r in current_course_records(saved) if r["purpose"] == "train" and not r["complete"]]
    if {r["match_id"] for r in unresolved} != set(acknowledged_compute_truncations):
        raise ContractError("legacy incomplete training attempts require exact explicit acknowledgments")
    acknowledgments = []
    for record in unresolved:
        if len(unresolved) != 1 or record is not saved["records"][-1] or saved.get("pending") is not None:
            raise ContractError("legacy attempt is not a proven pre-update compute truncation; no replay or skip authorized")
        acknowledgments.append(_legacy_compute_acknowledgment(record, cursor))
    return {"schema_version": 1, "next_cursor": cursor + len(acknowledgments),
        "legacy_acknowledgments": acknowledgments}


def validate_training_attempt_state(saved, attempts, *, max_attempts):
    """Prove the next declared seed from actual updates and censored attempts."""
    current_course_records(saved)  # Validate the archive boundary even when every receipt is retained below.
    fields(attempts, {"schema_version", "next_cursor", "legacy_acknowledgments"})
    integer(attempts["schema_version"], "training attempt ledger schema", 1, 1)
    state = saved["models"]
    successful = _saved_successful_duel_updates(state)
    integer(successful, "saved successful sample cursor", 0, max_attempts)
    integer(attempts["next_cursor"], "next training attempt cursor", successful, max_attempts)
    acknowledgments = attempts["legacy_acknowledgments"]
    if not isinstance(acknowledgments, list): raise ContractError("legacy attempt acknowledgments must be a list")
    consumed, ack_ids, receipt_ids = set(), set(), set()
    for acknowledgment in acknowledgments:
        matches = [r for r in saved["records"] if r["match_id"] == acknowledgment["match_id"]]
        cursor = acknowledgment["sampling_attempt_cursor"]
        integer(cursor, "acknowledged sampling attempt cursor", 0, max_attempts-1)
        if (len(matches) != 1 or acknowledgment["match_id"] in ack_ids or cursor in consumed or
                acknowledgment != _legacy_compute_acknowledgment(matches[0], cursor)):
            raise ContractError("acknowledged legacy compute-truncation record or semantics changed")
        ack_ids.add(acknowledgment["match_id"]); consumed.add(cursor)
    truncated = 0
    boundaries = list(saved["records"]) + ([] if saved.get("pending") is None else [saved["pending"]])
    for boundary in boundaries:
        if boundary["purpose"] != "train": continue
        for receipt in boundary.get("receipts", []):
            if receipt.get("kind") != "course-small-game-host-receipt": continue
            if "sampling_attempt_cursor" not in receipt and "next_sampling_attempt_cursor" not in receipt: continue
            cursor, following = receipt["sampling_attempt_cursor"], receipt["next_sampling_attempt_cursor"]
            integer(cursor, "receipt sampling attempt cursor", 0, max_attempts-1)
            integer(following, "receipt next sampling attempt cursor", cursor, cursor+1)
            if following == cursor:
                if receipt.get("status") in ("completed", "compute_truncated"):
                    raise ContractError("completed or compute-truncated sample did not consume its declared attempt")
                continue  # A true fault may stop before a consumed sample/update.
            if cursor in consumed: raise ContractError("declared training attempt was consumed more than once")
            identity = (boundary.get("match_id", boundary.get("state", {}).get("match_id")), receipt.get("game_number"))
            integer(receipt.get("game_number"), "receipt small game number", 1, 3)
            if identity in receipt_ids: raise ContractError("small-game attempt receipt was counted more than once")
            receipt_ids.add(identity)
            consumed.add(cursor)
            if receipt.get("status") == "compute_truncated":
                before, after = receipt.get("before", {}), receipt.get("after", {})
                if (receipt.get("termination_kind") != "compute_budget" or receipt.get("partial_game") is None or
                        receipt.get("resource_boundary", {}).get("kind") != "compute_budget" or
                        any(receipt.get(key) is not False for key in ("sample_completed", "model_update_started", "model_update_completed")) or
                        type(before.get("training_cursor")) is not int or not 0 <= before["training_cursor"] <= successful or
                        receipt.get("observed_sampler_cursor") != before["training_cursor"] or
                        receipt.get("observed_sampler_updates") != before["training_cursor"] or
                        any(key not in before or key not in after or before[key] != after[key]
                            for key in ("training_cursor", "model_sha256", "lora", "observed_optimizer_step_max"))):
                    raise ContractError("compute-truncated receipt lacks its unchanged pre-update boundary")
                truncated += 1
            else:
                before, after = receipt.get("before", {}), receipt.get("after", {})
                if (receipt.get("model_update_started") is not True or
                        type(before.get("training_cursor")) is not int or
                        after.get("training_cursor") != before["training_cursor"]+1 or after["training_cursor"] > successful):
                    raise ContractError("consumed training attempt has neither an observed update nor a proven compute truncation")
    expected = successful + len(acknowledgments) + truncated
    if attempts["next_cursor"] != expected or any(cursor >= expected for cursor in consumed):
        raise ContractError("next training attempt cursor is not proven by successful updates and preserved truncations")
    if consumed and consumed != set(range(min(consumed), expected)):
        raise ContractError("explicit training attempt ledger contains a skipped declared seed")
    return attempts


def verify_partial_game_artifact(root, artifact):
    """Validate the retained private evidence before accepting its checkpoint."""
    fields(artifact, {"path", "bytes", "sha256", "training_eligible", "native_continuation_available"})
    name = artifact["path"]
    if (not isinstance(name, str) or Path(name).name != name or not name.startswith("partial-game-") or not name.endswith(".json") or
            artifact["training_eligible"] is not False or artifact["native_continuation_available"] is not False):
        raise ContractError("private partial-game evidence path or eligibility differs")
    integer(artifact["bytes"], "private partial-game bytes", 1)
    path = Path(root) / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size != artifact["bytes"]:
        raise ContractError("private partial-game evidence is missing or its bytes differ")
    actual = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""): actual.update(chunk)
    if actual.hexdigest() != artifact["sha256"]:
        raise ContractError("private partial-game evidence hash differs")
    return path


def checkpoint_policy(value=None):
    """Explicit per-course retention; absent/null means no deletion or quota."""
    policy={"keep_last":None,"milestone_every":None,"min_free_bytes":0,"max_state_bytes":None}
    if value is not None:policy.update(fields(value,set(),set(policy)))
    for key in ("keep_last","milestone_every","max_state_bytes"):
        if policy[key] is not None:integer(policy[key],"checkpoint policy "+key,1)
    integer(policy["min_free_bytes"],"checkpoint minimum free bytes",0)
    return policy


def bot_binding(bot):
    runtime = bot["runtime"]
    from .model_opponents import ModelOpponentRuntime
    if isinstance(runtime, ModelOpponentRuntime):
        return {"deck": bot["deck"].to_dict(), "stage": bot["stage"], "purpose": bot["purpose"],
            "first_order": bot["first_order"], "coverage_label": bot["coverage_label"], "source": bot["source"],
            "runtime": runtime.identity(), "common_deck_evidence": deepcopy(bot["common_deck_evidence"]),
            "private_sampling_binding_sha256": digest({"seed": bot.get("opponent_policy_seed")})}
    return {"deck": bot["deck"].to_dict(), "stage": bot["stage"], "purpose": bot["purpose"],
        "first_order": bot["first_order"], "coverage_label": bot["coverage_label"], "source": bot["source"],
        "runtime": {"source_id": runtime.source_id, "executor_id": runtime.executor_id,
            "audit": deepcopy(runtime.audit), "qualification": deepcopy(runtime.qualification),
            "qualification_profile": deepcopy(runtime.qualification_profile),
            "source_lock_sha256": digest(runtime.registry.lock),
            "inventory_sha256": runtime.registry.inventory["inventory_sha256"],
            "session_seconds": runtime.session_seconds, "mono": runtime.mono}}


def validate_common_deck_evidence(evidence, deck, period):
    """An explicit reviewed deck is distinct from arbitrary self-play coverage."""
    from datetime import date
    e = fields(evidence, {"kind", "source", "reviewed_at", "period_id", "format", "banlist_effective", "deck_sha256"})
    if (e["kind"] not in ("user_provided_common_deck", "host_reviewed_common_deck") or
            e["format"] != "OCG" or e["period_id"] != period or e["banlist_effective"] != period + "-01" or
            e["deck_sha256"] != digest(deck.to_dict()) or not isinstance(e["source"], str) or not e["source"].strip()):
        raise ContractError("model-driven common deck requires explicit same-period review and exact legal deck identity")
    try:
        if date.fromisoformat(e["reviewed_at"]).isoformat() != e["reviewed_at"]: raise ValueError()
    except (TypeError, ValueError) as error:
        raise ContractError("common deck review date must be explicit ISO date") from error
    return deepcopy(e)


class ScenarioCourse:
    """Concrete caller, retaining the existing four networks and LoRA modules."""
    def __init__(self, models, *, assets, data_index, config, state_root, bots, storage_envelope=None,comparison_policy=None):
        from .course_models import CourseModels
        if not isinstance(models, CourseModels) or not isinstance(data_index, DataIndex):
            raise ContractError("actual course models and data index required")
        self.models, self.assets, self.data_index = models, assets, data_index
        self.comparison_policy=comparison_policy
        self.config = validate_config(config)
        if config.get("data_index_storage") is not None:
            from .data_isolation import validate_storage_limits
            if data_index.storage_limits != validate_storage_limits(config["data_index_storage"]):
                raise ContractError("actual data-index storage policy differs from the declared course")
        from .storage_envelope import StorageEnvelope
        if storage_envelope is not None and not isinstance(storage_envelope, StorageEnvelope):
            raise ContractError("actual host storage envelope required")
        self.storage_envelope = storage_envelope
        self._bound_storage_envelope = storage_envelope
        if tuple(config["training_seeds"]) != models.duel.config.game_seeds:
            raise ContractError("actual actor does not own the full course seed schedule")
        if getattr(assets, "period_id", None) != config["period_id"]:
            raise ContractError("actual period assets differ from the course")
        if models.builder.encoder.assets is not assets:
            raise ContractError("construction and duel must share the actual period assets")
        if (str(models.duel.device).startswith("cuda")) != (config["allocated_gpu_count"] > 0):
            raise ContractError("numerical device and allocated GPU count differ")
        self.root = Path(state_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if storage_envelope is not None: storage_envelope.require_controlled_directory(self.root)
        self.bots = dict(bots)
        from .model_opponents import ModelOpponentRuntime
        required = {"runtime", "deck", "stage", "purpose", "first_order", "source", "coverage_label"}
        for ident, bot in self.bots.items():
            identifier(ident); fields(bot, required, {"common_deck_evidence", "opponent_policy_seed"})
            if (not isinstance(bot["runtime"], (CourseBotRuntime, ModelOpponentRuntime)) or not isinstance(bot["deck"], DeckParts)
                    or bot["stage"] not in ("bots-bo1", "common-decks-bo3") or
                    bot["purpose"] not in ("train", "validation", "final_eval")):
                raise ContractError("explicit typed qualified bot, stage and split required")
            if isinstance(bot["runtime"], ModelOpponentRuntime):
                if bot["stage"] != "common-decks-bo3":
                    raise ContractError("new self-play models cannot replace the existing-bot first stage")
                validate_common_deck_evidence(bot.get("common_deck_evidence"), bot["deck"], config["period_id"])
                bot["runtime"].assert_assets(assets)
                if bot["runtime"].policy_mode == "sample":
                    integer(bot.get("opponent_policy_seed"), "private opponent sampling seed", 0, 2**32-8)
                elif bot.get("opponent_policy_seed") is not None:
                    raise ContractError("greedy model opponent cannot consume a sampling seed")
            FirstOrderPolicy(bot["first_order"])
            if not isinstance(bot["coverage_label"], str) or not bot["coverage_label"].strip():
                raise ContractError("host must declare actual opponent coverage, not infer from source availability")
        if not any(b["stage"] == "bots-bo1" and b["purpose"] == "train" for b in self.bots.values()):
            raise ContractError("the existing-bot first stage requires an actual available opponent")
        # Later coverage remains mandatory at its execution boundary. Its
        # absence cannot prevent already supplied first-stage base learning.
        self.rules = MatchRules(assets.rows, assets.limits, models.builder.encoder.available_ids)
        for bot in self.bots.values(): self.rules.validate(bot["deck"])
        self.binding = {"kind": "ordered-scenario-course-v1", "config": self.config, "models": models.binding,
            "source_map": source_tree_snapshot(Path(__file__).resolve().parent),
            "period_context": deepcopy(assets.period_context), "rules_sha256": self.rules.sha256,
            "bots": {i: bot_binding(b) for i, b in self.bots.items()}}
        if storage_envelope is not None:
            self.binding["storage_envelope"] = deepcopy(storage_envelope.binding)
        if data_index.storage_limits is not None:
            self.binding["data_index_storage_sha256"] = data_index.storage_policy_sha256
        self.records, self.events, self.active_seconds = [], [], 0.
        self.selection = self.deck = self.construction = None
        self.pending = None
        self.training_attempt_cursor = (models.sessions["duel"].updates if "duel" in models.sessions
            else models.duel.episode_cursor)
        self._legacy_attempt_acknowledgments = []
        self.evaluation_cursor = {"validation": 0, "final_eval": 0}
        self.frozen_evaluation = None
        self.revision, self.desired = 0, "ready"
        self._last_checkpoint = None
        self.checkpoint_policy=checkpoint_policy(self.config.get("checkpoint_policy"))
        self._checkpoint_entries=[]
        self._config_sha256 = digest(self.config)
        self._binding_sha256 = digest(self.binding)
        from .course_feedback import CourseFeedbackUpdater
        self.feedback = CourseFeedbackUpdater(models, data_index, config["course_id"])
        self.initial_model_execution = self.model_execution()
        self._admission_state_reference = None
        self._admission_reference_validated = False

    def bind_admission_policy(self, policy):
        """Attach the private host ledger without embedding its counters in models."""
        previous=getattr(self,'_admission_state_reference',None)
        descriptor=getattr(policy,'checkpoint_descriptor',None)
        if previous is not None:
            validate=getattr(policy,'validate_checkpoint_descriptor',None)
            if not callable(validate):
                raise ContractError('saved private admission ledger requires its original host provider')
            validate(previous)  # Missing, rolled-back, changed or ahead private state needs inspection.
        if callable(descriptor):
            reference=descriptor()
            if previous is None:
                self.events.append({'kind':'explicit-prospective-admission-policy-epoch-boundary-v1',
                    'admission_state_reference':deepcopy(reference),'legacy_failure_counts_imported':False,
                    'historical_unknowns_counted':False})
            self._admission_state_reference=deepcopy(reference)
        self.comparison_policy=policy
        self._admission_reference_validated=True

    def _admission_checkpoint_reference(self):
        previous=getattr(self,'_admission_state_reference',None)
        if previous is not None and not getattr(self,'_admission_reference_validated',False):
            raise ContractError('saved private admission ledger must be validated before another checkpoint')
        descriptor=getattr(getattr(self,'comparison_policy',None),'checkpoint_descriptor',None)
        if callable(descriptor):
            return deepcopy(descriptor())
        return deepcopy(previous)

    def counts(self):
        # Earlier real engine records remain intact but cannot silently
        # satisfy a corrected construction curriculum's mandatory volume.
        active=self.records[self.config.get("training_record_offset",0):]
        return {kind: sum(r["complete"] and r["purpose"] == "train" and r["format"] == kind
                          for r in active) for kind in ("bo1", "bo3")}

    def stage(self):
        if self.config["pilot_mean_seconds"] is None and self.config.get("timing_basis") is None: return "timing_required"
        counts, rule = self.counts(), course_volume_requirements(self.config)
        first = rule.get("bo1_min", rule.get("minimum_bo1"))
        if counts["bo1"] < first: return "bots-bo1"
        return "complete" if course_volume_met(self.config, counts["bo1"], counts["bo3"]) else "common-decks-bo3"

    def status(self):
        counts = self.counts()
        return {"kind": "ordered-scenario-course-status", "course_id": self.config["course_id"],
            "period_id": self.config["period_id"], "stage": self.stage(), "desired": self.desired,
            "complete_training_matches": counts,
            "prior_flow_training_matches": {kind:sum(r["complete"] and r["purpose"]=="train" and r["format"]==kind
                for r in self.records[:self.config.get("training_record_offset",0)]) for kind in ("bo1","bo3")},
            "training_record_offset":self.config.get("training_record_offset",0), "actual_small_game_attempts": sum(len(r["games"]) for r in self.records),
            "anomalous_matches": sum(not r["complete"] for r in self.records),
            "compute_truncated_matches": sum(r.get("status") == "compute_truncated" for r in self.records),
            "next_training_attempt_cursor": self.training_attempt_cursor,
            "active_seconds": self.active_seconds, "wall_limit_seconds": self.config["wall_seconds"],
            "pilot_matches_credited": 0, "evaluation_matches_credited": 0,
            "timing_basis": deepcopy(self.config.get("timing_basis")),
            "pending_match": None if self.pending is None else self.pending["state"].summary(),
            "formal_training_success_verified": False, "events": deepcopy(self.events[-8:])}

    def _construct(self, *, feedback=()):
        kernel = self.models.kernel
        def completed(result):
            cb = result.get("basic_cb") or {}
            return (bool(result.get("best")) and result.get("task_verified") is True and
                    result.get("alternation_completed") is True and cb.get("inference_completed") is True and
                    cb.get("status") in ("routes_inferred", "bounded_inference_unknown"))
        if self.selection is None:
            proposals = kernel.propose_tasks()
            result = None
            # Construction must finish its four concrete handoffs and task
            # check, then actually perform basic CB inference. A bounded
            # unknown is completed inference, never a failed construction or
            # a reason to replace the selected goal with a different theme.
            for rank in range(min(8, len(proposals.get("candidates", [])))):
                candidate = kernel.select_task(proposals, rank=rank)
                if candidate.get("status") != "model_selected_task": break
                attempt = kernel.run_selected(candidate, feedback=feedback)
                if completed(attempt):
                    self.selection, result = candidate, attempt
                    break
                self.events.append({"kind": "autonomous_candidate_unverified", "candidate_id": candidate["candidate_id"],
                    "model_rank": rank, "task_verified": attempt.get("task_verified", False),
                    "basic_cb_status": (attempt.get("basic_cb") or {}).get("status", "not_run"),
                    "unknown_is_negative_training_label": False})
            if result is None:
                raise ContractError("bounded model-ranked candidates have no task-checked construction with completed basic CB inference")
        else:
            result = kernel.run_selected(self.selection, feedback=feedback, base=self.deck)
        if not completed(result):
            raise ContractError("selected construction task or post-construction basic CB inference is incomplete")
        self.deck = DeckParts.from_dict(result["best"]["deck"])
        self.rules.validate(self.deck)
        self.construction = deepcopy(result)

    def _task(self):
        return self.models.builder.task if self.selection is None else BuildTask.from_dict(self.selection["task"])

    def _start_match(self, purpose):
        if self.pending is not None: return
        stage = self.stage() if purpose == "train" else "common-decks-bo3"
        if stage == "complete": return
        if self.deck is None: self._construct()
        self._require_training_admission(self.deck,purpose)
        choices = sorted(i for i, b in self.bots.items() if b["stage"] == stage and b["purpose"] == purpose)
        if not choices: raise ContractError("no actual qualified opponents for this stage and partition")
        ordinal = sum(r["purpose"] == purpose for r in self.records)
        bot_id = choices[ordinal % len(choices)]; bot = self.bots[bot_id]
        match_id = self.config["course_id"] + "-" + purpose + "-" + str(ordinal + 1)
        initial = "actor" if ordinal % 2 == 0 else "opponent"
        state = MatchState(match_id, (MatchParticipant("actor", self.deck), MatchParticipant("opponent", bot["deck"])),
            self.rules, {"course_binding_sha256": digest(self.binding), "purpose": purpose,
                         "stage": stage, "bot_id": bot_id,
                         **({"model_opponent": bot["runtime"].identity()} if not isinstance(bot["runtime"], CourseBotRuntime) else {})},
            initial, adapter_revision=self.assets.adapter_revision)
        self.pending = {"state": state, "bot_id": bot_id, "purpose": purpose, "stage": stage,
                        "format": "bo1" if stage == "bots-bo1" else "bo3", "receipts": []}

    @contextmanager
    def _frozen(self):
        modes = [(m, m.training) for model in self.models.models().values() for m in model.modules()]
        state = self.models.rng_state()
        before = self.models.fingerprint()
        try:
            for module, _ in modes: module.training = False
            yield
        finally:
            self.models.restore_rng(state)
            for module, mode in modes: module.training = mode
            if self.models.fingerprint() != before:
                raise ContractError("frozen evaluation changed a model, optimizer or training cursor")

    def _require_training_admission(self,deck,purpose):
        from .training_admission import require_training_admission,TrainingAdmissionDeferred
        if (getattr(self,'_admission_state_reference',None) is not None and
                not getattr(self,'_admission_reference_validated',False)):
            raise TrainingAdmissionDeferred({'reasons':['saved_private_admission_ledger_requires_host_validation']})
        best=(self.construction or {}).get('best') or {}
        cb=best.get('basic_cb') if best.get('deck')==deck.to_dict() else None
        verdict=require_training_admission(task=self._task(),deck=deck,basic_cb=cb,assets=self.assets,
            purpose=purpose,comparison_policy=self.comparison_policy)
        if verdict['status']!='admitted':
            error=TrainingAdmissionDeferred(verdict)
            if not any((self.root/name).exists() for name in ('in-flight.json','feedback-in-flight.json')):
                self.desired='paused'
                self.save()
                error.safe_boundary_saved=True;error.pause_requested=True
            raise error
        return verdict

    def _game(self):
        from .duel_planning import plans_from_construction
        self._storage_guard()
        p = self.pending; match = p["state"]; bot = self.bots[p["bot_id"]]; purpose = p["purpose"]
        try:
            if match.status == "awaiting_sideboards":
                side = ModelSideboardPolicy(self.models.builder.models["build_optimizer"], self.models.builder.encoder,
                    self._task(), self.assets, self.rules)
                # Opponent unchanged-side baseline is explicit. The actor executes
                # actual optimizer-ranked, goal-preserving legal swap candidates.
                match.submit_sideboards({"actor": side(match.intermission_request("actor")),
                    "opponent": keep_side(match.intermission_request("opponent"))})
                p["receipts"].append({"kind": "actor_side_selection", "receipt": side.last_receipt})
            if match.status == "awaiting_first_choice":
                loser = match._loser
                policy = FirstOrderPolicy("always_first" if loser == "actor" else bot["first_order"])
                match.choose_next_first(loser, policy(match.intermission_request(loser)))
        except (ContractError, ValueError, RuntimeError) as error:
            match.abort_intermission(type(error).__name__)
            return
        if match.status != "ready": return
        self._require_training_admission(match._current['actor'],purpose)
        runtime_options = ({"bot_runtime": bot["runtime"]} if isinstance(bot["runtime"], CourseBotRuntime)
                           else {"model_runtime": bot["runtime"]})
        if not isinstance(bot["runtime"], CourseBotRuntime) and bot["runtime"].policy_mode == "sample":
            secret = digest({"seed": bot["opponent_policy_seed"], "match_id": match.match_id,
                             "game_number": len(match.summary()["games"]) + 1})
            runtime_options["opponent_policy_rng"] = torch.Generator(device="cpu").manual_seed(int(secret[:16],16) % (2**63-1))
        adapter = CourseGameAdapter(assets=self.assets, match_state=match, actor_participant_id="actor",
            trainer=self.models.duel, adapter_session=self.models.sessions.get("duel"),
            **runtime_options, data_index=self.data_index, experiment_id=self.config["course_id"],
            purpose=purpose, policy_rng=self.models.policy_rng,
            evaluation_pairs=tuple(tuple(v) for v in self.config["evaluation_pairs"].get(purpose, [])),
            evaluation_cursor=self.evaluation_cursor.get(purpose, 0),
            combo_plans=plans_from_construction(self._task(),self.construction,deck=self.deck),
            observed_bot_source_review=self.models.binding.get('observed_bot_source_review'),
            training_attempt_cursor=self.training_attempt_cursor if purpose == "train" else None,
            admission_task=self._task(),admission_basic_cb=(self.construction or {}).get('best',{}).get('basic_cb'),
            comparison_policy=self.comparison_policy)
        spec = match.issue_game_spec()
        _exclusive_json(self.root / "in-flight.json", {"course_binding_sha256": digest(self.binding),
            "revision": self.revision, "match_id": spec.match_id, "game": spec.game_number,
            "purpose": purpose, "status": "execution_started_no_automatic_replay"})
        started = time.monotonic()
        result = adapter(spec)
        self.active_seconds += time.monotonic() - started
        if adapter.last_partial_sample is not None:
            # Persist private incomplete evidence before closing the durable
            # host boundary. Failure leaves in-flight.json in place, so neither
            # an uncertain write nor a half-game can be replayed automatically.
            payload = {"kind": "course-private-compute-truncation-v1",
                "course_binding_sha256": digest(self.binding), "match_id": spec.match_id,
                "game_number": spec.game_number, "game_spec_sha256": spec.sha256,
                "partial": adapter.last_partial_sample, "diagnostics": adapter.last_partial_diagnostics}
            raw = (canonical_json(payload) + "\n").encode("utf-8")
            name = "partial-game-" + digest([spec.match_id, spec.game_number, purpose])[:40] + ".json"
            path = self.root / name
            block = max(1, os.statvfs(self.root).f_frsize)
            self._storage_guard(((len(raw)+block-1)//block)*block+8*block)
            if self.storage_envelope is None:
                with path.open("xb") as output:
                    output.write(raw); output.flush(); os.fsync(output.fileno())
            else:
                reservation = "partial-" + digest([self._binding_sha256, name])[:40]
                with self.storage_envelope.reserve_file(reservation, path, len(raw), purpose="trajectory") as output:
                    output.write(raw); output.commit()
            adapter.last_receipt["partial_game"] = {"path": name, "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(), "training_eligible": False,
                "native_continuation_available": False}
        match.record_game(spec, result)
        p["receipts"].append(deepcopy(adapter.last_receipt))
        if purpose == "train":
            receipt = adapter.last_receipt
            if receipt.get("sampling_attempt_cursor") != self.training_attempt_cursor:
                raise ContractError("course sampling-attempt ledger changed during a game")
            following = receipt.get("next_sampling_attempt_cursor")
            integer(following, "next declared training attempt", self.training_attempt_cursor, self.training_attempt_cursor+1)
            self.training_attempt_cursor = following
        if purpose != "train": self.evaluation_cursor[purpose] = adapter.evaluation_cursor
        self.save()  # weights, data admission, score and cursor close together
        (self.root / "in-flight.json").unlink()

    def _close(self):
        p = self.pending; view = p["state"].summary()
        bo1_done = (p["format"] == "bo1" and len(view["games"]) == 1 and view["games"][0]["completed"])
        complete = bo1_done or p["format"] == "bo3" and view["status"] == "complete"
        terminal = complete or view["status"] in ("aborted", "pending_draw_policy")
        if not terminal: return False
        receipt = p["receipts"][-1] if p["receipts"] else {}
        compute_truncated = (not complete and receipt.get("status") == "compute_truncated" and
            receipt.get("sample_completed") is False and receipt.get("model_update_started") is False and
            receipt.get("model_update_completed") is False and receipt.get("partial_game") is not None)
        self.records.append({"match_id": view["match_id"], "format": p["format"], "stage": p["stage"],
            "purpose": p["purpose"], "bot_id": p["bot_id"], "complete": bool(complete),
            "status": "complete" if complete else "compute_truncated" if compute_truncated else view["status"], "games": deepcopy(view["games"]),
            "winner": view["games"][0]["winner_participant_id"] if bo1_done else view["match_winner"],
            "match_state": p["state"].to_dict(), "receipts": p["receipts"]})
        self.pending = None
        if not complete:
            # A known resource boundary consumes its predeclared attempt, not
            # an optimizer step. The invocation may use its remaining bounded
            # allocation on the next scheduled seed. Genuine faults still stop.
            if not compute_truncated: self.desired = "needs_inspection"
            self.events.append({"kind": "compute_truncated_match" if compute_truncated else "unresolved_match",
                "status": self.records[-1]["status"], "automatic_retry": False,
                "same_seed_recovery_requires_explicit_host_decision": compute_truncated})
        # Real prediction discrepancies are handled with their registered scope
        # and actual outcomes by the host; a round number alone is no review or
        # evidence that reconstruction is warranted.
        self.save()
        return True

    def run(self, max_matches=None, *, purpose="train"):
        with (self.root / ".course.lock").open("a") as lock:
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ContractError("another course worker owns this state root") from error
            return self._run(max_matches, purpose=purpose)

    def _run(self, max_matches=None, *, purpose="train"):
        if purpose not in ("train", "validation", "final_eval"): raise ContractError("explicit course partition required")
        limit = self.config["matches_per_invocation"] if max_matches is None else max_matches
        integer(limit, "bounded invocation match limit", 1, self.config["matches_per_invocation"])
        if (digest(self.config) != self._config_sha256 or self.config != self.binding["config"] or
                digest(self.binding) != self._binding_sha256 or
                {i: bot_binding(b) for i, b in self.bots.items()} != self.binding["bots"] or
                source_tree_snapshot(Path(__file__).resolve().parent) != self.binding["source_map"]):
            raise ContractError("course configuration changed after binding")
        if self.config["pilot_mean_seconds"] is None and self.config.get("timing_basis") is None:
            raise ContractError("real timing pilot must determine the volume branch before formal execution")
        if self.revision == 0 and (self.root / "latest.json").exists():
            raise ContractError("existing course must be restored before executing another game")
        latest = self.root / "latest.json"
        if (latest.exists() and json.loads(latest.read_text()) != self._last_checkpoint or
                not latest.exists() and self._last_checkpoint is not None):
            raise ContractError("course advanced in another worker; restore its latest boundary before executing")
        if (self.root / "in-flight.json").exists() or (self.root / "feedback-in-flight.json").exists():
            raise ContractError("uncertain in-flight game exists; inspect, do not replay or reset counters")
        if self.desired == "needs_inspection": raise ContractError("unresolved match requires an explicit host decision")
        if purpose != "train" and self.stage() != "complete":
            raise ContractError("frozen stage2 evaluation requires both ordered training minima")
        if self.pending is not None and self.pending["purpose"] != purpose:
            raise ContractError("cannot cross data partitions within an unfinished match")
        if purpose != "train":
            frozen = {"versions": self.models.versions(), "deck": self.deck.to_dict(),
                      "binding_sha256": digest(self.binding)}
            if self.frozen_evaluation not in (None, frozen):
                raise ContractError("frozen evaluation model/deck changed; preserve the old window")
            self.frozen_evaluation = frozen
        elif self.frozen_evaluation is not None:
            raise ContractError("frozen evaluation has begun; do not train on or overwrite its window")
        closed = 0; self.desired = "running"
        while closed < limit and self.active_seconds < self.config["wall_seconds"]:
            # The most recent durable checkpoint may already contain a fully
            # sampled last game but not yet its match-close projection. Close
            # that boundary before issuing any new spec (especially BO1).
            if self.pending is not None and self._close():
                closed += 1
                if self.desired == "needs_inspection" or closed >= limit: break
            if (self.root / "pause.request").exists(): self.desired = "paused"; break
            if purpose == "train" and self.stage() == "complete": break
            if purpose == "train" and self.training_attempt_cursor >= len(self.config["training_seeds"]):
                self.desired = "training_seed_schedule_exhausted"; break
            if purpose != "train" and sum(r["purpose"] == purpose for r in self.records) >= self.config["evaluation_matches"]: break
            if self.active_seconds + self.models.duel.config.episode_seconds > self.config["wall_seconds"]:
                self.desired = "budget_insufficient_for_next_game"; break
            self._storage_guard()
            started, accounted = time.monotonic(), self.active_seconds
            try:
                self._start_match(purpose)
                if purpose == "train": self._game()
                else:
                    with self._frozen(): self._game()
            finally:
                # Include construction, siding and bookkeeping overhead as well
                # as the adapter's actual model/core small-game time.
                self.active_seconds += max(0., time.monotonic()-started-(self.active_seconds-accounted))
            if self._close(): closed += 1
            if self.desired == "needs_inspection": break
        if self.active_seconds >= self.config["wall_seconds"]:
            self.desired = "budget_exhausted"
        elif self.desired == "running": self.desired = "ready"
        self.save()
        return self.status()

    def rates(self, purpose="final_eval"):
        records = [r for r in self.records if r["purpose"] == purpose and r["stage"] == "common-decks-bo3"]
        games = [g for r in records for g in r["games"]]
        first = [g for g in games if g["completed"] and g["actual_first_participant_id"] == "actor"]
        second = [g for g in games if g["completed"] and g["actual_first_participant_id"] == "opponent"]
        result = {"completed_first_games": len(first), "completed_second_games": len(second),
            "first_wins": sum(g["winner_participant_id"] == "actor" for g in first),
            "second_wins": sum(g["winner_participant_id"] == "actor" for g in second),
            "draws": sum(g["draw"] for g in games), "anomalies": sum(not g["completed"] for g in games),
            "unresolved_matches": sum(not r["complete"] for r in records),
            "declared_window_complete": len(records) == self.config["evaluation_matches"] and self.pending is None,
            "frozen_models": deepcopy(self.frozen_evaluation), "training_results_included": False}
        if self.config["period_id"] == "2026-10":
            result["thresholds"] = check_2610_rates("2026-10", result["first_wins"], len(first),
                result["second_wins"], len(second), partition=purpose,
                anomalies=result["anomalies"] + result["unresolved_matches"] + int(not result["declared_window_complete"]))
        else:
            groups = {}
            for group in ("external", "mirror"):
                rows = [r for r in records if self.bots[r["bot_id"]]["coverage_label"] == group]
                n = sum(r["complete"] for r in rows)
                w = sum(r["complete"] and r["winner"] == "actor" for r in rows)
                rate = w/n if n else None
                if n:
                    z = 1.959963984540054
                    center = (rate + z*z/(2*n))/(1+z*z/n)
                    half = z*math.sqrt(rate*(1-rate)/n + z*z/(4*n*n))/(1+z*z/n)
                    interval = [max(0., center-half), min(1., center+half)]
                else: interval = None
                groups[group] = {"completed_bo3_matches": n, "wins": w, "rate": rate,
                    "wilson_95_interval": interval, "sample_minimum_met": n >= 200}
            result["thresholds"] = {"kind": "historical_external_bo3_60_mirror_near_50",
                "source": "docs/plans/2026-10-22-unified-development-spec.md#12.1",
                "groups": groups, "external_at_least_60_met": groups["external"]["rate"] is not None and groups["external"]["rate"] >= .6,
                "mirror_target": .5, "ci_decision_rule_unconfirmed": True,
                "mirror_tolerance_unconfirmed": True, "formal_training_success_verified": False}
        return result

    def apply_feedback(self, feedback_id, artifact_id, *, kind, examples=None, task=None,
                       proposals=None, preferred_id=None, preferred_index=None, roles=None):
        """Host-only indexed labels; frozen evaluation never trains any role.

        The existing DataIndex owns artifact admission. A single duel is not
        silently relabelled as a construction-quality or forecast target.
        """
        if self.pending is not None or self.frozen_evaluation is not None:
            raise ContractError("model feedback requires a clean training boundary, outside frozen evaluation")
        marker = self.root / "feedback-in-flight.json"
        _exclusive_json(marker, {"feedback_id": feedback_id, "artifact_id": artifact_id,
            "kind": kind, "automatic_retry": False})
        started = time.monotonic()
        try:
            if kind == "construction":
                result = self.feedback.apply_construction(feedback_id, artifact_id, task or self._task(), roles=roles if roles is not None else ("build_goal","build_optimizer"))
            elif kind == "coordinator":
                result = self.feedback.apply_coordinator(feedback_id, artifact_id, examples)
            elif kind == "task_preference":
                result = self.feedback.apply_task_preference(feedback_id, artifact_id, proposals, preferred_id)
            elif kind == "graph_preference":
                result = self.feedback.apply_graph_preference(feedback_id, artifact_id, self.selection, preferred_index)
            else: raise ContractError("unknown indexed course feedback kind")
            self.events.append({"kind": "indexed_feedback_applied", "feedback_id": feedback_id,
                "artifact_id": artifact_id, "quality_inferred_from_single_duel": False})
            self.active_seconds += time.monotonic()-started
            self.save(); marker.unlink()
            return result
        except Exception:
            self.active_seconds += time.monotonic()-started
            self.desired = "needs_inspection"
            # Keep durable uncertainty evidence even if an optimizer performed
            # only part of a multi-role request. Never replay it automatically.
            raise

    def model_execution(self):
        """Execution identity excludes cosmetic adapter-context/report paths."""
        return {"versions": self.models.versions(), "device": str(self.models.duel.device),
            "duel_vocabulary_sha256": self.models.duel.encoder.vocab_sha256,
            "duel_config_sha256": digest(asdict(self.models.duel.config)),
            "adapters": {r: {"enabled": s.enabled, "base_sha256": s.verify_base(),
                "config": s.config.to_dict()} for r, s in self.models.sessions.items()}}

    def timing_pilot(self, seed_pairs, *, progress=None):
        """Explicit real, frozen group/LoRA BO1 pre-run; no PPO or match credit.

        This invokes the same normal core and qualified bot adapter as formal
        execution. It has its own data index/experiment and disjoint seeds.
        The recommended twelve games are a sample recommendation, not a
        fabricated confidence/representativeness guarantee.
        """
        from .training_pilot import aggregate_attempts
        if self.revision or self.records or self.pending is not None or self.frozen_evaluation is not None:
            raise ContractError("pilot requires a separate fresh course instance/state root")
        if not isinstance(seed_pairs, (list, tuple)) or not 1 <= len(seed_pairs) <= 100:
            raise ContractError("bounded predeclared pilot window required")
        reserved = set(self.config["training_seeds"])
        reserved.update(p[0] for pairs in self.config["evaluation_pairs"].values() for p in pairs)
        pairs = []
        for pair in seed_pairs:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2: raise ContractError("pilot seed pair required")
            for value in pair: integer(value, "pilot seed", 0, 2**32-8)
            if pair[0] in reserved: raise ContractError("pilot physical seed overlaps formal training/evaluation")
            reserved.add(pair[0]); pairs.append(tuple(pair))
        marker = self.root / "timing-pilot-started.json"
        _exclusive_json(marker, {"planned_games": len(pairs), "seed_schedule_sha256": digest(pairs),
                                 "automatic_retry": False})
        choices = sorted(i for i, b in self.bots.items() if b["purpose"] == "train")
        if any(not isinstance(self.bots[i]["runtime"], CourseBotRuntime) for i in choices):
            raise ContractError("legacy bot timing protocol does not measure mixed model opponents; retain the declared prior branch")
        if not choices: raise ContractError("real qualified pilot bot cases required")
        if self.deck is None: self._construct()
        execution = self.model_execution(); frozen = self.models.fingerprint()
        report = {"kind": "course-group-bo1-timing-pilot-v1", "partition": "timing_pilot", "status": "started",
            "planned_games": len(pairs), "seed_schedule": [list(p) for p in pairs], "attempts": [],
            "model_execution": execution, "resources": deepcopy(self.assets.receipt),
            "case_bindings": {i: deepcopy(self.binding["bots"][i]) for i in choices},
            "actor_deck_sha256": digest(self.deck.to_dict()),
            "period_context": deepcopy(self.assets.period_context),
            "implementation": source_tree_snapshot(Path(__file__).resolve().parent),
            "training_updates": 0, "formal_matches": 0, "native_executed": False,
            "csharp_execution_attempted": False, "all_models_unchanged": False,
            "bo3_timing_verified": False, "general_speed_verified": False}
        pilot_index = DataIndex(self.root / "timing-data", storage_limits=self.data_index.storage_limits)
        for ordinal, pair in enumerate(pairs):
            bot_id = choices[(ordinal // 2) % len(choices)]; bot = self.bots[bot_id]
            initial = "actor" if ordinal % 2 == 0 else "opponent"
            match = MatchState("pilot-" + str(ordinal+1),
                (MatchParticipant("actor", self.deck), MatchParticipant("opponent", bot["deck"])), self.rules,
                {"kind": "separate_timing_pilot_not_formal", "model_execution": execution}, initial,
                adapter_revision=self.assets.adapter_revision)
            adapter = CourseGameAdapter(assets=self.assets, match_state=match, actor_participant_id="actor",
                trainer=self.models.duel, adapter_session=self.models.sessions.get("duel"), bot_runtime=bot["runtime"],
                data_index=pilot_index, experiment_id="timing-" + self.config["course_id"], purpose="validation",
                policy_rng=self.models.policy_rng, evaluation_pairs=(pair,))
            spec = match.issue_game_spec(); started = time.monotonic()
            with self._frozen(): result = adapter(spec)
            match.record_game(spec, result)
            receipt = adapter.last_receipt or {}; observations = receipt.get("observations", {})
            report["native_executed"] |= observations.get("constructor_started") is True
            report["csharp_execution_attempted"] |= observations.get("constructor_completed") is True
            completed = result.terminal and result.anomaly is None and result.evidence_source == REAL_GAME_SOURCE
            episode = adapter.last_episode
            row = {"case_id": bot_id, "status": "completed" if completed else "failed_or_uncertain",
                "game_seconds": result.elapsed_seconds if completed else None,
                "wall_seconds": time.monotonic()-started, "actor_inference_ms": [] if episode is None else episode["summary"]["actor_inference_ms"],
                "declared_coverage": [bot["stage"], bot["coverage_label"], "actor_" + ("first" if initial == "actor" else "second")],
                "actual_first_participant_id": match.summary()["games"][0]["actual_first_participant_id"],
                "evidence_source": result.evidence_source, "anomaly": result.anomaly, "retry_allowed": False}
            report["attempts"].append(row)
            report["summary"] = aggregate_attempts(report["attempts"], planned=len(pairs))
            if progress is not None: progress(deepcopy(report))
            if not completed: break  # Retain the full declared incomplete window.
        report["all_models_unchanged"] = self.models.fingerprint() == frozen
        report["status"] = "completed" if (len(report["attempts"]) == len(pairs) and
            report["summary"]["volume_advice"] is not None and report["all_models_unchanged"]) else "partial_or_failed"
        if progress is not None: progress(deepcopy(report))
        return report

    def _storage_bytes(self):
        # The index is normally a sibling of course/, so include its complete
        # directory (including SQLite journals), without deleting any of it.
        roots=[self.root]
        index_root=Path(self.data_index.root).resolve()
        if self.root.is_relative_to(index_root):roots=[index_root]
        elif not index_root.is_relative_to(self.root):roots.append(index_root)
        total=0
        for root in roots:
            for path in root.rglob("*"):
                if path.is_symlink():raise ContractError("course storage inventory does not follow symlinks")
                if path.is_file():
                    stat=path.stat()
                    total+=max(stat.st_size,getattr(stat,"st_blocks",0)*512)
        return total

    def _storage_guard(self, additional_bytes=0):
        integer(additional_bytes,"additional checkpoint storage bytes",0)
        if self.storage_envelope is not self._bound_storage_envelope:
            raise ContractError("course storage envelope instance changed after binding")
        policy=checkpoint_policy(self.config.get("checkpoint_policy"))
        if policy!=self.checkpoint_policy:raise ContractError("checkpoint policy changed after course binding")
        if self.storage_envelope is not None:
            if self.binding.get("storage_envelope") != self.storage_envelope.binding:
                raise ContractError("course workspace storage envelope changed")
            self.storage_envelope.guard(additional_bytes)
        used=self._storage_bytes()
        if policy["max_state_bytes"] is not None and used+additional_bytes>policy["max_state_bytes"]:
            raise ContractError("course state storage limit would be exceeded; no game or checkpoint started")
        if shutil.disk_usage(self.root).free<policy["min_free_bytes"]+additional_bytes:
            raise ContractError("course minimum free disk reserve is unavailable")
        index_root=Path(self.data_index.root).resolve()
        if index_root.stat().st_dev!=self.root.stat().st_dev and shutil.disk_usage(index_root).free<policy["min_free_bytes"]:
            raise ContractError("course data-index disk reserve is unavailable")
        return used

    def storage_status(self):
        return {"checkpoint_policy":deepcopy(self.checkpoint_policy),"state_and_index_bytes":self._storage_bytes(),
            "manifest_entries":len(self._checkpoint_entries),"records_and_index_still_grow":True,
            "whole_environment_under_30GB_proven":False,"training_authorized_by_storage_check":False}

    def _registry(self,entries):
        return {"schema_version":1,"kind":"course-owned-checkpoint-manifest-v1",
            "course_binding_sha256":digest(self.binding),"entries":deepcopy(entries)}

    def _validate_entries(self,entries):
        if not isinstance(entries,list):raise ContractError("course checkpoint manifest entries must be a list")
        last=0
        every=self.checkpoint_policy["milestone_every"]
        for i,e in enumerate(entries):
            fields(e,{"path","sha256","bytes","revision","initial","milestone","course_binding_sha256"})
            integer(e["revision"],"owned checkpoint revision",last+1)
            integer(e["bytes"],"owned checkpoint bytes",1)
            if (e["path"]!="checkpoint-"+str(e["revision"])+".weights" or
                    not isinstance(e["sha256"],str) or len(e["sha256"])!=64 or any(c not in "0123456789abcdef" for c in e["sha256"]) or
                    e["initial"] is not (i==0) or e["milestone"] is not bool(every and e["revision"]%every==0) or
                    e["course_binding_sha256"]!=digest(self.binding)):
                raise ContractError("owned checkpoint manifest identity differs")
            last=e["revision"]
        return entries

    def _protected_checkpoints(self,entries):
        keep=self.checkpoint_policy["keep_last"]
        if keep is None:return {e["path"] for e in entries}
        return {e["path"] for e in entries if e["initial"] or e["milestone"]} | {e["path"] for e in entries[-keep:]}

    def _verify_owned_files(self,entries):
        protected=self._protected_checkpoints(entries)
        for e in entries:
            path=self.root/e["path"]
            if path.is_symlink():raise ContractError("owned checkpoint cannot be a symlink")
            if not path.exists():
                if e["path"] in protected:raise ContractError("protected owned checkpoint is missing")
                continue  # An already-pruned manifest entry remains an audit record.
            if (not path.is_file() or path.stat().st_size!=e["bytes"] or
                    hashlib.sha256(path.read_bytes()).hexdigest()!=e["sha256"]):
                raise ContractError("owned checkpoint bytes changed; pruning is refused")

    def _assert_registry(self):
        path=self.root/"checkpoint-manifest.json"
        self._validate_entries(self._checkpoint_entries)
        if path.is_symlink():raise ContractError("course checkpoint manifest symlinks unsupported")
        if self._checkpoint_entries:
            if not path.is_file() or digest(json.loads(path.read_text()))!=digest(self._registry(self._checkpoint_entries)):
                raise ContractError("course checkpoint manifest changed or disappeared")
            self._verify_owned_files(self._checkpoint_entries)
        elif path.exists():raise ContractError("existing checkpoint manifest requires explicit course restore")
        if self._last_checkpoint is not None:
            latest=self.root/"latest.json"
            if latest.is_symlink() or digest(json.loads(latest.read_text()))!=digest(self._last_checkpoint):
                raise ContractError("course checkpoint pointer advanced; restore before saving")

    def _restored_entries(self,saved,pointer):
        storage=saved.get("checkpoint_storage")
        if storage is None:
            if (self.root/"checkpoint-manifest.json").exists():raise ContractError("legacy checkpoint has no owned manifest binding")
            return []  # Existing unregistered files will never become pruning targets.
        fields(storage,{"schema_version","policy","prior_entries"})
        integer(storage["schema_version"],"checkpoint storage schema",1,1)
        if storage["policy"]!=self.checkpoint_policy:raise ContractError("restored checkpoint retention policy differs")
        entries=deepcopy(self._validate_entries(storage["prior_entries"]))
        if entries and entries[-1]["revision"]>=pointer["revision"]:raise ContractError("restored checkpoint manifest ancestry differs")
        entries.append(self._checkpoint_entry(pointer,entries))
        self._validate_entries(entries)
        path=self.root/"checkpoint-manifest.json"
        if path.is_symlink() or not path.is_file() or digest(json.loads(path.read_text()))!=digest(self._registry(entries)):
            raise ContractError("restored checkpoint manifest is not anchored by the current checkpoint")
        self._verify_owned_files(entries)
        return entries

    def _checkpoint_entry(self,pointer,prior):
        every=self.checkpoint_policy["milestone_every"]
        return {"path":pointer["path"],"sha256":pointer["sha256"],"bytes":(self.root/pointer["path"]).stat().st_size,
            "revision":pointer["revision"],"initial":not prior,"milestone":bool(every and pointer["revision"]%every==0),
            "course_binding_sha256":digest(self.binding)}

    def _prune_checkpoints(self):
        # Validate the complete ownership registry and every extant file before
        # the first unlink. Unknown files, data/index, markers and receipts are
        # never candidates, even if their filenames resemble checkpoints.
        self._assert_registry()
        if self._last_checkpoint is None:return
        protected=self._protected_checkpoints(self._checkpoint_entries)
        protected.add(self._last_checkpoint["path"])
        for e in self._checkpoint_entries:
            path=self.root/e["path"]
            if e["path"] not in protected and path.exists():
                if path.is_symlink() or path.stat().st_size!=e["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest()!=e["sha256"]:
                    raise ContractError("owned checkpoint changed during pruning")
                path.unlink()

    def save(self):
        self._assert_registry()
        self._storage_guard()
        admission_reference=self._admission_checkpoint_reference()
        if self.pending is not None: match = self.pending["state"].to_dict()
        else: match = None
        revision=self.revision+1
        payload = {"kind": "ordered-course-game-boundary-v1", "binding": self.binding,
            "revision": revision, "models": self.models.save_state(),
            "records": self.records, "events": self.events, "active_seconds": self.active_seconds,
            "selection": self.selection, "deck": None if self.deck is None else self.deck.to_dict(),
            "initial_model_execution": deepcopy(self.initial_model_execution),
            "construction": self.construction, "pending": None if self.pending is None else {
                **{k:v for k,v in self.pending.items() if k != "state"}, "state": match},
            "evaluation_cursor": self.evaluation_cursor, "frozen_evaluation": self.frozen_evaluation,
            "training_attempts": {"schema_version": 1, "next_cursor": self.training_attempt_cursor,
                "legacy_acknowledgments": deepcopy(self._legacy_attempt_acknowledgments)},
            "desired": self.desired, "feedback": self.feedback.state_dict(),
            "data_index_sha256": index_identity(self.data_index),
            "checkpoint_storage":{"schema_version":1,"policy":deepcopy(self.checkpoint_policy),
                "prior_entries":deepcopy(self._checkpoint_entries)}}
        if admission_reference is not None:
            payload['admission_state_reference']=admission_reference
        # Know the serialized byte count before writing disk. This is an actual
        # envelope size, not an estimate from neural tensor parameters.
        buffer=io.BytesIO();torch.save(payload,buffer);raw=buffer.getbuffer()
        path = self.root / ("checkpoint-" + str(revision) + ".weights")
        pointer = {"path": path.name, "sha256":hashlib.sha256(raw).hexdigest(),
                   "revision":revision,"active_seconds":self.active_seconds}
        every=self.checkpoint_policy["milestone_every"]
        entry={"path":path.name,"sha256":pointer["sha256"],"bytes":len(raw),"revision":revision,
            "initial":not self._checkpoint_entries,"milestone":bool(every and revision%every==0),"course_binding_sha256":digest(self.binding)}
        entries=self._checkpoint_entries+[entry]
        manifest=self._registry(entries)
        temporary = self.root / ("latest-" + str(revision) + ".json")
        manifest_temporary=self.root/("checkpoint-manifest-"+str(revision)+".json")
        if any(p.exists() or p.is_symlink() for p in (path,temporary,manifest_temporary)):
            raise ContractError("checkpoint output exists; it will not be overwritten or adopted")
        block=max(1,os.statvfs(self.root).f_frsize)
        sizes=(len(raw),len(canonical_json(manifest).encode())+1,len(canonical_json(pointer).encode())+1)
        extra=sum(((size+block-1)//block)*block for size in sizes)+2*block
        self._storage_guard(extra)
        if self.storage_envelope is None:
            with path.open("xb") as output:
                output.write(raw); output.flush(); os.fsync(output.fileno())
        else:
            reservation = "course-" + digest({"binding": self._binding_sha256, "path": path.name})[:40]
            with self.storage_envelope.reserve_file(reservation, path, len(raw), purpose="checkpoint") as output:
                output.write(raw); output.commit()
        _exclusive_json(manifest_temporary,manifest);os.replace(manifest_temporary,self.root/"checkpoint-manifest.json")
        _exclusive_json(temporary, pointer); os.replace(temporary, self.root / "latest.json")
        self.revision=revision
        self._checkpoint_entries=entries
        self._last_checkpoint = deepcopy(pointer)
        self._admission_state_reference=deepcopy(admission_reference)
        self._prune_checkpoints()
        return pointer

    def restore_latest(self):
        if (self.root / "in-flight.json").exists() or (self.root / "feedback-in-flight.json").exists():
            raise ContractError("uncertain native/model transaction cannot be automatically resumed")
        pointer = json.loads((self.root / "latest.json").read_text())
        name = pointer["path"]
        if Path(name).name != name: raise ContractError("checkpoint pointer escapes state root")
        path = self.root / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != pointer["sha256"]:
            raise ContractError("course checkpoint artifact differs")
        saved = torch.load(path, weights_only=True, map_location="cpu")
        if (saved["kind"] != "ordered-course-game-boundary-v1" or saved["binding"] != self.binding or
                saved["revision"] != pointer["revision"] or saved["active_seconds"] != pointer["active_seconds"] or
                saved["data_index_sha256"] != index_identity(self.data_index)):
            raise ContractError("checkpoint binding/accounting/data is stale; no automatic rollback")
        self._admission_state_reference=deepcopy(saved.get('admission_state_reference'))
        self._admission_reference_validated=False
        if self._admission_state_reference is not None and getattr(self,'comparison_policy',None) is not None:
            self.bind_admission_policy(self.comparison_policy)
        entries=self._restored_entries(saved,pointer)
        attempts = saved.get("training_attempts")
        if attempts is None: attempts = migrate_training_attempt_state(saved)
        validate_training_attempt_state(saved, attempts, max_attempts=len(self.config["training_seeds"]))
        boundaries = list(saved["records"]) + ([] if saved.get("pending") is None else [saved["pending"]])
        for boundary in boundaries:
            for receipt in boundary.get("receipts", []):
                if receipt.get("partial_game") is not None: verify_partial_game_artifact(self.root, receipt["partial_game"])
        self.models.restore_state(saved["models"], assets=self.assets, expected_binding=self.models.binding)
        self.training_attempt_cursor = attempts["next_cursor"]
        self._legacy_attempt_acknowledgments = deepcopy(attempts["legacy_acknowledgments"])
        from .course_feedback import CourseFeedbackUpdater
        self.feedback = CourseFeedbackUpdater(self.models, self.data_index, self.config["course_id"])
        self.feedback.load_state_dict(saved["feedback"])
        for key in ("revision", "records", "events", "active_seconds", "selection", "construction",
                    "evaluation_cursor", "frozen_evaluation", "desired", "initial_model_execution"):
            setattr(self, key, deepcopy(saved[key]))
        self.deck = None if saved["deck"] is None else DeckParts.from_dict(saved["deck"])
        self.pending = deepcopy(saved["pending"])
        if self.pending is not None:
            value = self.pending["state"]
            self.pending["state"] = MatchState.from_dict(value, rules=self.rules, expected_binding=value["binding"])
            if value["binding"]["course_binding_sha256"] != digest(self.binding):
                raise ContractError("pending match belongs to another course")
        self._last_checkpoint = deepcopy(pointer)
        self._checkpoint_entries=entries
        return self.status()
