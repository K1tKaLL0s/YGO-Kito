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
import json
import math
import os
from pathlib import Path
import sqlite3
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
from .training_scenarios import check_2610_rates, volume_met, volume_requirements
from .validation import ContractError, canonical_json, fields, integer


def validate_config(value):
    d = fields(value, {"course_id", "period_id", "mode", "pilot_mean_seconds", "training_seeds",
        "evaluation_pairs", "matches_per_invocation", "wall_seconds", "allocated_gpu_count", "fixed_deck",
        "initial_first", "evaluation_matches", "opponent_side"})
    identifier(d["course_id"])
    if d["period_id"] not in ("2022-07", "2022-10", "2026-10"):
        raise ContractError("explicit supported period required")
    if d["mode"] != ("autonomous" if d["period_id"] == "2026-10" else "fixed_theme"):
        raise ContractError("autonomous selection is scoped to 2610; historical themes stay fixed")
    if (d["mode"] == "autonomous") != (d["fixed_deck"] is None):
        raise ContractError("autonomous mode cannot require the reference Tear deck")
    if d["fixed_deck"] is not None: DeckParts.from_dict(d["fixed_deck"])
    if d["pilot_mean_seconds"] is not None: volume_requirements(d["pilot_mean_seconds"])
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


def bot_binding(bot):
    runtime = bot["runtime"]
    return {"deck": bot["deck"].to_dict(), "stage": bot["stage"], "purpose": bot["purpose"],
        "first_order": bot["first_order"], "coverage_label": bot["coverage_label"], "source": bot["source"],
        "runtime": {"source_id": runtime.source_id, "executor_id": runtime.executor_id,
            "audit": deepcopy(runtime.audit), "qualification": deepcopy(runtime.qualification),
            "qualification_profile": deepcopy(runtime.qualification_profile),
            "source_lock_sha256": digest(runtime.registry.lock),
            "inventory_sha256": runtime.registry.inventory["inventory_sha256"],
            "session_seconds": runtime.session_seconds, "mono": runtime.mono}}


class ScenarioCourse:
    """Concrete caller, retaining the existing four networks and LoRA modules."""
    def __init__(self, models, *, assets, data_index, config, state_root, bots):
        from .course_models import CourseModels
        if not isinstance(models, CourseModels) or not isinstance(data_index, DataIndex):
            raise ContractError("actual course models and data index required")
        self.models, self.assets, self.data_index = models, assets, data_index
        self.config = validate_config(config)
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
        self.bots = dict(bots)
        required = {"runtime", "deck", "stage", "purpose", "first_order", "source", "coverage_label"}
        for ident, bot in self.bots.items():
            identifier(ident); fields(bot, required)
            if (not isinstance(bot["runtime"], CourseBotRuntime) or not isinstance(bot["deck"], DeckParts)
                    or bot["stage"] not in ("bots-bo1", "common-decks-bo3") or
                    bot["purpose"] not in ("train", "validation", "final_eval")):
                raise ContractError("explicit typed qualified bot, stage and split required")
            FirstOrderPolicy(bot["first_order"])
            if not isinstance(bot["coverage_label"], str) or not bot["coverage_label"].strip():
                raise ContractError("host must declare actual opponent coverage, not infer from source availability")
        for stage in ("bots-bo1", "common-decks-bo3"):
            if not any(b["stage"] == stage and b["purpose"] == "train" for b in self.bots.values()):
                raise ContractError("both ordered training stages require actual available opponents")
        self.rules = MatchRules(assets.rows, assets.limits, models.builder.encoder.available_ids)
        for bot in self.bots.values(): self.rules.validate(bot["deck"])
        self.binding = {"kind": "ordered-scenario-course-v1", "config": self.config, "models": models.binding,
            "source_map": source_tree_snapshot(Path(__file__).resolve().parent),
            "period_context": deepcopy(assets.period_context), "rules_sha256": self.rules.sha256,
            "bots": {i: bot_binding(b) for i, b in self.bots.items()}}
        self.records, self.events, self.active_seconds = [], [], 0.
        self.selection = self.deck = self.construction = None
        self.pending = None
        self.evaluation_cursor = {"validation": 0, "final_eval": 0}
        self.frozen_evaluation = None
        self.revision, self.desired = 0, "ready"
        self._last_checkpoint = None
        self._config_sha256 = digest(self.config)
        self._binding_sha256 = digest(self.binding)
        from .course_feedback import CourseFeedbackUpdater
        self.feedback = CourseFeedbackUpdater(models, data_index, config["course_id"])
        self.initial_model_execution = self.model_execution()

    def counts(self):
        return {kind: sum(r["complete"] and r["purpose"] == "train" and r["format"] == kind
                          for r in self.records) for kind in ("bo1", "bo3")}

    def stage(self):
        if self.config["pilot_mean_seconds"] is None: return "timing_required"
        counts, rule = self.counts(), volume_requirements(self.config["pilot_mean_seconds"])
        first = rule.get("bo1_min", rule.get("minimum_bo1"))
        if counts["bo1"] < first: return "bots-bo1"
        return "complete" if volume_met(self.config["pilot_mean_seconds"], counts["bo1"], counts["bo3"]) else "common-decks-bo3"

    def status(self):
        counts = self.counts()
        return {"kind": "ordered-scenario-course-status", "course_id": self.config["course_id"],
            "period_id": self.config["period_id"], "stage": self.stage(), "desired": self.desired,
            "complete_training_matches": counts, "actual_small_game_attempts": sum(len(r["games"]) for r in self.records),
            "anomalous_matches": sum(not r["complete"] for r in self.records),
            "active_seconds": self.active_seconds, "wall_limit_seconds": self.config["wall_seconds"],
            "pilot_matches_credited": 0, "evaluation_matches_credited": 0,
            "pending_match": None if self.pending is None else self.pending["state"].summary(),
            "formal_training_success_verified": False, "events": deepcopy(self.events[-8:])}

    def _construct(self, *, feedback=()):
        if self.config["mode"] == "fixed_theme":
            self.deck = DeckParts.from_dict(self.config["fixed_deck"])
            self.assets.validate(self.models.builder.task, self.deck)
            self.construction = {"kind": "preserved_historical_theme", "task_sha256": self.models.builder.task.sha256,
                                 "cb_verified": False}
            return
        kernel = self.models.kernel
        if self.selection is None:
            proposals = kernel.propose_tasks()
            result = None
            # The user's autonomous objective is still open here. Reject an
            # unverified fill without globally blocking other model-ranked
            # themes. Once a concrete goal is accepted, later revisions below
            # must preserve it rather than silently selecting a new theme.
            for rank in range(min(8, len(proposals.get("candidates", [])))):
                candidate = kernel.select_task(proposals, rank=rank)
                if candidate.get("status") != "model_selected_task": break
                attempt = kernel.run_selected(candidate, feedback=feedback)
                if attempt.get("best") and attempt.get("cb_verified"):
                    self.selection, result = candidate, attempt
                    break
                self.events.append({"kind": "autonomous_candidate_unverified", "candidate_id": candidate["candidate_id"],
                    "model_rank": rank, "unknown_is_negative_training_label": False})
            if result is None:
                raise ContractError("bounded model-ranked candidates have no concrete verified CB; preserve unknown and supply feedback")
        else:
            result = kernel.run_selected(self.selection, feedback=feedback, base=self.deck)
        if not result.get("best") or not result.get("cb_verified"):
            raise ContractError("concrete text/engine CB verification has not accepted the selected logic")
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
        choices = sorted(i for i, b in self.bots.items() if b["stage"] == stage and b["purpose"] == purpose)
        if not choices: raise ContractError("no actual qualified opponents for this stage and partition")
        ordinal = sum(r["purpose"] == purpose for r in self.records)
        bot_id = choices[ordinal % len(choices)]; bot = self.bots[bot_id]
        match_id = self.config["course_id"] + "-" + purpose + "-" + str(ordinal + 1)
        initial = "actor" if ordinal % 2 == 0 else "opponent"
        state = MatchState(match_id, (MatchParticipant("actor", self.deck), MatchParticipant("opponent", bot["deck"])),
            self.rules, {"course_binding_sha256": digest(self.binding), "purpose": purpose,
                         "stage": stage, "bot_id": bot_id}, initial, adapter_revision=self.assets.adapter_revision)
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

    def _game(self):
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
        adapter = CourseGameAdapter(assets=self.assets, match_state=match, actor_participant_id="actor",
            trainer=self.models.duel, adapter_session=self.models.sessions.get("duel"),
            bot_runtime=bot["runtime"], data_index=self.data_index, experiment_id=self.config["course_id"],
            purpose=purpose, policy_rng=self.models.policy_rng,
            evaluation_pairs=tuple(tuple(v) for v in self.config["evaluation_pairs"].get(purpose, [])),
            evaluation_cursor=self.evaluation_cursor.get(purpose, 0))
        spec = match.issue_game_spec()
        _exclusive_json(self.root / "in-flight.json", {"course_binding_sha256": digest(self.binding),
            "revision": self.revision, "match_id": spec.match_id, "game": spec.game_number,
            "purpose": purpose, "status": "execution_started_no_automatic_replay"})
        started = time.monotonic()
        result = adapter(spec)
        self.active_seconds += time.monotonic() - started
        match.record_game(spec, result)
        p["receipts"].append(deepcopy(adapter.last_receipt))
        if purpose != "train": self.evaluation_cursor[purpose] = adapter.evaluation_cursor
        self.save()  # weights, data admission, score and cursor close together
        (self.root / "in-flight.json").unlink()

    def _close(self):
        p = self.pending; view = p["state"].summary()
        bo1_done = (p["format"] == "bo1" and len(view["games"]) == 1 and view["games"][0]["completed"])
        complete = bo1_done or p["format"] == "bo3" and view["status"] == "complete"
        terminal = complete or view["status"] in ("aborted", "pending_draw_policy")
        if not terminal: return False
        self.records.append({"match_id": view["match_id"], "format": p["format"], "stage": p["stage"],
            "purpose": p["purpose"], "bot_id": p["bot_id"], "complete": bool(complete),
            "status": "complete" if complete else view["status"], "games": deepcopy(view["games"]),
            "winner": view["games"][0]["winner_participant_id"] if bo1_done else view["match_winner"],
            "match_state": p["state"].to_dict(), "receipts": p["receipts"]})
        self.pending = None
        if not complete:
            self.desired = "needs_inspection"
            self.events.append({"kind": "unresolved_match", "status": view["status"], "automatic_retry": False})
        if complete and p["purpose"] == "train":
            n = sum(self.counts().values())
            if n and n % 100 == 0:
                self.events.append({"kind": "hundred_match_review", "complete_matches": n})
            if n and n % 1000 == 0 and self.config["mode"] == "autonomous":
                self._construct(feedback=({"source": "duel", "message": "1000 complete training matches: reconsider and reconstruct logic while retaining the chosen goal"},))
                self.events.append({"kind": "thousand_match_logic_reconstruction", "complete_matches": n,
                                    "goal_preserved": True})
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
                source_tree_snapshot(Path(__file__).resolve().parent) != self.binding["source_map"]):
            raise ContractError("course configuration changed after binding")
        if self.config["pilot_mean_seconds"] is None:
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
            if purpose != "train" and sum(r["purpose"] == purpose for r in self.records) >= self.config["evaluation_matches"]: break
            if self.active_seconds + self.models.duel.config.episode_seconds > self.config["wall_seconds"]:
                self.desired = "budget_insufficient_for_next_game"; break
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
                       proposals=None, preferred_id=None, preferred_index=None):
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
                result = self.feedback.apply_construction(feedback_id, artifact_id, task or self._task())
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
        pilot_index = DataIndex(self.root / "timing-data")
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

    def save(self):
        if self.pending is not None: match = self.pending["state"].to_dict()
        else: match = None
        self.revision += 1
        payload = {"kind": "ordered-course-game-boundary-v1", "binding": self.binding,
            "revision": self.revision, "models": self.models.save_state(),
            "records": self.records, "events": self.events, "active_seconds": self.active_seconds,
            "selection": self.selection, "deck": None if self.deck is None else self.deck.to_dict(),
            "initial_model_execution": deepcopy(self.initial_model_execution),
            "construction": self.construction, "pending": None if self.pending is None else {
                **{k:v for k,v in self.pending.items() if k != "state"}, "state": match},
            "evaluation_cursor": self.evaluation_cursor, "frozen_evaluation": self.frozen_evaluation,
            "desired": self.desired, "feedback": self.feedback.state_dict(),
            "data_index_sha256": index_identity(self.data_index)}
        path = self.root / ("checkpoint-" + str(self.revision) + ".weights")
        with path.open("xb") as output:
            torch.save(payload, output); output.flush(); os.fsync(output.fileno())
        pointer = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "revision": self.revision, "active_seconds": self.active_seconds}
        temporary = self.root / ("latest-" + str(self.revision) + ".json")
        _exclusive_json(temporary, pointer); os.replace(temporary, self.root / "latest.json")
        self._last_checkpoint = deepcopy(pointer)
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
        self.models.restore_state(saved["models"], assets=self.assets, expected_binding=self.models.binding)
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
        return self.status()
