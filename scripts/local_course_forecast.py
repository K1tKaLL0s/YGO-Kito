"""Prospective scoped forecasts; learned decisions at complete-cycle boundaries.

Legacy forecasts are preserved. Monitoring uses held-out seeds without PPO;
only pre-recorded training samples can supervise the prediction model.
"""
from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import time

from ygo_kito.build_contracts import DeckParts, digest
from ygo_kito.coord_contracts import FeedbackPolicy
from ygo_kito.coordinator import Coordinator
from ygo_kito.coordinator_model import public_scope_features
from ygo_kito.model_group import call, route_with_model
from ygo_kito.validation import ContractError


def canonical_deck(deck):
    return DeckParts(*(tuple(sorted(getattr(deck, z))) for z in ("main", "extra", "side")))


class CourseForecast:
    def __init__(self, course, target, stop=None, *, host=None, evaluation_runner=None, snapshot_factory=None):
        self.course, self.target, self.stop = course, Path(target), stop
        self.path = self.target / "scoped-forecast-controller.json"
        self.policy = FeedbackPolicy()
        self.host = host or Coordinator(self.target / "coordinator-scoped.sqlite3", self.policy,
            role="coordinator", source="real_engine", assets=course.assets, create=True,
            candidate_verifier=self._existing_candidate_proof)
        self.evaluation_runner = evaluation_runner or self._run_monitor_job
        self.snapshot_factory = snapshot_factory
        self._snapshots = {}
        if self.path.exists():
            self.value = json.loads(self.path.read_text(encoding="utf-8"))
            if self.value["policy"] != self.policy.to_dict():
                raise ContractError("scoped policy changed; explicit migration required")
        else:
            legacy = self.target / "actual-forecast-ledger.json"
            self.value = {"kind": "scoped-course-controller-v3", "policy": self.policy.to_dict(),
                "calibration": "pending", "legacy": {"path": legacy.name,
                    "sha256": hashlib.sha256(legacy.read_bytes()).hexdigest()} if legacy.exists() else None,
                "candidates": {}, "forecasts": {}, "active_candidate": None, "active_forecast": None,
                "pending_training": None, "pending_evaluation": None, "monitor_cursor": 0,
                "trained_artifacts": [], "decisions": [], "ability_verified": False}
            if legacy.exists() and json.loads(legacy.read_text())["alerts"]:
                raise ContractError("unresolved legacy alerts need explicit reconciliation before continuation")
        pending = self.value["pending_evaluation"]
        if pending is not None:
            job = call(self.host, "job.read", {"job_id": pending["job_id"]})
            if job["state"] != "completed":
                raise ContractError("uncertain monitoring job preserved; inspect rather than replay")
            self.value["pending_evaluation"] = None
        self.save()

    def save(self):
        temp = self.path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(self.value, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.path)

    def _existing_candidate_proof(self, task, deck, assets):
        from ygo_kito.build_semantics import accepted_status
        result = self.course.construction
        if not isinstance(result,dict) or not result.get('alternation_completed'):
            raise ContractError('handoff needs the completed four-step candidate')
        assets.check_task(task)
        assets.validate(task, deck)
        best=result.get('best')
        for candidate in ([best] if isinstance(best,dict) else [])+list(result.get('retained_candidates',())):
            if not isinstance(candidate,dict) or not isinstance(candidate.get('deck'),dict):continue
            constructed=candidate['deck']
            if canonical_deck(DeckParts.from_dict(constructed))!=deck:continue
            subject=digest(constructed)
            basic=candidate.get('basic_cb') or (result.get('basic_cb') if candidate is best else None)
            if (not isinstance(basic,dict) or basic.get('task_sha256')!=task.sha256 or
                    basic.get('subject_deck_sha256')!=subject):
                raise ContractError('basic CB subject differs from its exact task/deck')
            for attempt in candidate.get('validation',{}).get('attempts',()):
                proof=attempt.get('engine_validation',attempt) if isinstance(attempt,dict) else {}
                if (isinstance(proof,dict) and proof.get('status')==accepted_status(task) and
                        proof.get('task_sha256')==task.sha256 and proof.get('deck_sha256')==subject):
                    return deepcopy(proof)
            raise ContractError('matching candidate lacks its own task proof')
        raise ContractError('handoff needs the candidate-owned task proof, separate from basic CB inference')

    def _actor_identity(self, models=None):
        from dataclasses import asdict
        models = self.course.models if models is None else models
        versions = models.versions()
        return digest({"weights": versions["duel"], "sideboard_policy": versions["build_optimizer"],
                       "sampler": asdict(models.duel.config)})

    def _capture_window(self, forecast_id):
        if self.snapshot_factory is not None:
            self._snapshots[forecast_id] = self.snapshot_factory(forecast_id, None)
            return {"injected_fixture": True}
        import torch
        state = self.course.models.save_state()
        path = self.target / (forecast_id + ".weights")
        if path.exists():
            raise ContractError("frozen monitor snapshot exists without its registration; inspect before retry")
        with path.open("xb") as output:
            torch.save(state, output)
        return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "state_sha256": state["state_sha256"]}

    def _window_models(self, forecast_id):
        if forecast_id in self._snapshots:
            return self._snapshots[forecast_id]
        window = next(v for v in self.value["forecasts"].values() if v["id"] == forecast_id)
        receipt = window["snapshot"]
        if self.snapshot_factory is not None:
            models = self.snapshot_factory(forecast_id, receipt)
        else:
            import torch
            from ygo_kito.course_models import CourseModels
            name = receipt["path"]
            if Path(name).name != name:
                raise ContractError("monitor snapshot path escapes its owned directory")
            path = self.target / name
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != receipt["sha256"]:
                raise ContractError("frozen monitor snapshot changed")
            state = torch.load(path, weights_only=True, map_location="cpu")
            if state["state_sha256"] != receipt["state_sha256"]:
                raise ContractError("monitor snapshot state differs")
            live_rng = self.course.models.rng_state()
            try:
                models = CourseModels.from_state(state, assets=self.course.assets, expected_binding=state["binding"])
            finally:
                self.course.models.restore_rng(live_rng)
        self._snapshots[forecast_id] = models
        return models

    @staticmethod
    @contextmanager
    def _frozen_models(models):
        before, rng = models.fingerprint(), models.rng_state()
        modes = [(module, module.training) for model in models.models().values() for module in model.modules()]
        try:
            for module, _ in modes: module.training = False
            yield
        finally:
            models.restore_rng(rng)
            for module, mode in modes: module.training = mode
            if models.fingerprint() != before:
                raise ContractError("monitoring changed its frozen models, optimizer or cursors")

    def _scope(self):
        from ygo_kito.scenario_course import bot_binding
        stage = self.course.stage()
        bots = {key: bot for key, bot in self.course.bots.items() if bot["stage"] == stage and bot["purpose"] == "train"}
        if not bots:
            raise ContractError("no concrete opponent pool for prospective forecast")
        opponents = [{"opponent_id": key, "deck_sha256": digest(canonical_deck(bot["deck"]).to_dict()),
                      "driver_sha256": digest(bot_binding(bot)), "weight": 1 / len(bots)} for key, bot in sorted(bots.items())]
        session = self.course.models.sessions.get("duel")
        scope = {"actor_policy_sha256": self._actor_identity(), "duel_lora": None if session is None else session.config.adapter_id,
            "opponents": opponents, "initiative_weights": [.5, .5], "unit": "BO1" if stage == "bots-bo1" else "BO3",
            "prediction_target": "win_rate", "versions": self.course._task().environment["versions"]}
        return scope, {key: canonical_deck(bot["deck"]) for key, bot in bots.items()}

    def before(self):
        task, deck = self.course._task(), canonical_deck(self.course.deck)
        key = digest({"task": task.sha256, "deck": deck.to_dict()})
        if key not in self.value["candidates"]:
            candidate_id = "candidate-" + key[:40]
            candidate = call(self.host, "handoff.submit", {"candidate_id": candidate_id,
                "parent_candidate_id": self.value["active_candidate"], "task": task.to_dict(), "deck": deck.to_dict(),
                "build_models": {r: self.course.models.versions()[r] for r in ("build_goal", "build_optimizer")}})
            self.value["candidates"][key] = candidate["candidate_id"]
        candidate_id = self.value["candidates"][key]
        active = self.value["active_forecast"]
        if active is not None and self.value["active_candidate"] == candidate_id:
            status = self.host.forecast_status(active)
            # Live PPO/optimizer updates never abandon this frozen cohort.
            if status["matches"] < 1000 or status["pending_review"]:
                window = next(v for v in self.value["forecasts"].values() if v["id"] == active)
                return window["features"]
        scope, opponents = self._scope()
        features = public_scope_features(self.course.models.builder, task, deck, scope, opponents)
        scope_key = digest({"candidate": candidate_id, "scope": scope})
        if scope_key not in self.value["forecasts"]:
            context = call(self.host, "route", {"candidate_id": candidate_id, "forecast_id": None,
                "remaining_tasks": 1, "advisory": None})["context"]
            prediction = self.course.models.coordinator.forecast(context, features)
            forecast = call(self.host, "forecast.register", {"forecast_id": "forecast-" + scope_key[:40],
                "candidate_id": candidate_id, "probability": prediction["probability"], "origin_role": "coordinator",
                "model_sha256": prediction["model_sha256"], "calibration": "pending", "scope": scope})
            self.value["forecasts"][scope_key] = {"id": forecast["forecast_id"], "features": features,
                "stage": self.course.stage(),
                "snapshot": self._capture_window(forecast["forecast_id"]),
                "registered_before_games": True, "training_matches_credited": 0}
        self.value["active_candidate"] = candidate_id
        self.value["active_forecast"] = self.value["forecasts"][scope_key]["id"]
        self.save()
        return features

    def status(self):
        return self.host.forecast_status(self.value["active_forecast"])

    def decide(self, max_units):
        features = self.before()
        allowed = ["build_goal", "build_optimizer", "train_duel", "stop"]
        if self.status()["matches"] < 1000:
            allowed.append("evaluate_duel")
        decision, inference = route_with_model(self.host, self.course.models.coordinator,
            self.value["active_candidate"], self.value["active_forecast"], max_units,
            features=features, allowed_routes=allowed, max_units=max_units)
        self.value["decisions"].append({"decision": decision, "inference": inference})
        self.save()
        return decision

    def before_training(self):
        self.before()
        scope, opponents = self._scope()
        features = public_scope_features(self.course.models.builder, self.course._task(), canonical_deck(self.course.deck), scope, opponents)
        if self.status()["mandatory_rebuild"]:
            raise ContractError("mandatory reconstruction blocks ordinary training")
        if self.value["pending_training"] is not None:
            if self.course.pending is not None and self.course.pending["state"].match_id == self.value["pending_training"]["match_id"]:
                return  # Resume the already sealed course transaction exactly once.
            raise ContractError("unclosed training observation preserved")
        match_id = (self.course.pending["state"].match_id if self.course.pending else
            self.course.config["course_id"] + "-train-" + str(sum(r["purpose"] == "train" for r in self.course.records) + 1))
        context = call(self.host, "route", {"candidate_id": self.value["active_candidate"],
            "forecast_id": self.value["active_forecast"], "remaining_tasks": 1, "advisory": None})["context"]
        self.value["pending_training"] = {"match_id": match_id, "features": features, "context": context,
            "scope": scope, "duel_model_sha256": self.course.models.versions()["duel"]}
        self.save()

    def train_closed_outcomes(self):
        """Only a pre-recorded training sample, never a held-out monitor game."""
        pending = self.value["pending_training"]
        if pending is None:
            return
        record = next((r for r in self.course.records if r["match_id"] == pending["match_id"]), None)
        if record is None:
            return
        if not record["complete"]:
            self.value.setdefault("failed_training_observations", []).append(pending)
        else:
            if record["purpose"] != "train" or record["format"] != "bo1":
                raise ContractError("prediction target needs an exact completed BO1 training sample")
            receipt = next(r for r in record["receipts"] if r.get("kind") == "course-small-game-host-receipt")
            artifact_id = receipt["data"]["artifact_id"]
            if receipt["status"] != "completed" or not receipt["model_update_completed"]:
                raise ContractError("closed actual training receipt required")
            if receipt["sample_policy_sha256"] != pending["duel_model_sha256"]:
                raise ContractError("training label actor differs from the pre-game scope")
            artifact = self.course.data_index.artifact(artifact_id, for_training=True)
            if artifact_id not in self.value["trained_artifacts"]:
                row = {"context": pending["context"], "scope_features": pending["features"], "route_label": None,
                    "forecast_target": float(record["winner"] == "actor"), "provenance": {
                        "dataset_id": artifact["dataset_id"], "record_id": artifact_id,
                        "source": "prospectively_scoped_actual_training_sample_not_calibration", "evidence_sha256": artifact["payload_sha256"]}}
                examples = {"source": "host_logged_supervision_v1", "records": [row],
                    "real_win_rate_supervision": False, "sha256": digest([row])}
                feedback_id = "scoped-outcome-" + artifact_id
                if not any(r["feedback_id"] == feedback_id for r in self.course.feedback.consumed):
                    self.course.apply_feedback(feedback_id, artifact_id, kind="coordinator", examples=examples)
                self.value["trained_artifacts"].append(artifact_id)
        self.value["pending_training"] = None
        self.save()

    def construction_completed(self, *, review=None):
        self.before()  # A construction call cannot acknowledge/erase an alert.
        if review is not None and not self.status()['mandatory_rebuild']:
            closed=self.host.record_construction_review(self.value['active_candidate'],review)
            if closed['closed']:
                self.value.setdefault('reviews',[]).append(closed);self.save()
        self._try_resolve()

    def _try_resolve(self):
        if self.status()["matches"] < self.policy.minimum_matches:
            return
        result = self.host.dispatch({"schema_version": 1, "id": "resolve-scoped-rebuild", "method": "rebuild.resolve",
            "params": {"candidate_id": self.value["active_candidate"], "validation_forecast_id": self.value["active_forecast"]}})
        if result["ok"] and result["result"]["closed"]:
            self.value.setdefault("resolutions", []).append(result["result"])
            self.save()

    def evaluate(self, max_matches, *, budget=None):
        completed = 0
        for _ in range(max_matches):
            if self.stop is not None and self.stop.exists():
                break
            self.before()
            status = self.status()
            if status["matches"] >= 1000:
                self.value["monitoring_state"] = "exhausted_with_pending_review" if status["pending_review"] else "window_complete"
                self.save()
                break
            if status["own_pending_review"]:
                break
            models = self._window_models(self.value["active_forecast"])
            if budget is not None:
                games = 1 if status["forecast"]["scope"]["unit"] == "BO1" else 3
                budget.check("before_monitor_match", required=games * models.duel.config.episode_seconds)
            if self.value["pending_evaluation"] is not None:
                raise ContractError("uncertain monitoring job cannot be replayed")
            forecast_id = self.value["active_forecast"]
            job_id = "monitor-" + digest({"forecast": forecast_id, "n": status["matches"]})[:40]
            job = call(self.host, "job.schedule", {"job_id": job_id, "forecast_id": forecast_id,
                "seed": self.value["monitor_cursor"], "purpose": "rebuild_validation" if status["mandatory_rebuild"] else "evaluation"})
            self.value["pending_evaluation"] = {"job_id": job_id}
            self.save()
            worker = Coordinator(self.host.path, self.policy, role="duel_worker", source=self.host.source, assets=self.host.assets)
            job = call(worker, "job.claim", {"job_id": job_id, "worker_id": "course-monitor"})
            self._evaluation_budget = budget
            result = self.evaluation_runner(job)
            row = {"result_id": job_id + "-result", "job_id": job_id, "worker_id": "course-monitor",
                "forecast_id": forecast_id, "candidate_id": job["candidate_id"], "scope_sha256": job["scope_sha256"],
                "source": self.host.source, "unit": job["scope"]["unit"], **result}
            call(worker, "results.append", {"results": [row]})
            self.value["pending_evaluation"] = None
            completed += 1
            self.save()
            self._try_resolve()
            status = self.status()
            if status["own_pending_review"] or (status["mandatory_rebuild"] and not status["rebuild_validation_eligible"]):
                break
        return completed

    def _run_monitor_job(self, job):
        """Existing frozen adapter; no training credit and no prediction labels."""
        from ygo_kito.course_game_adapter import CourseGameAdapter, CourseBotRuntime
        from ygo_kito.match_runner import MatchState, MatchParticipant, ModelSideboardPolicy, keep_side, FirstOrderPolicy
        models = self._window_models(job["forecast_id"])
        if self._actor_identity(models) != job["scope"]["actor_policy_sha256"]:
            raise ContractError("monitor actor/candidate changed after registration")
        bot = self.course.bots[job["opponent"]["opponent_id"]]
        from ygo_kito.scenario_course import bot_binding
        if (digest(bot_binding(bot)) != job["opponent"]["driver_sha256"] or
                digest(canonical_deck(bot["deck"]).to_dict()) != job["opponent"]["deck_sha256"]):
            raise ContractError("monitor opponent differs from the frozen scope")
        from ygo_kito.build_contracts import BuildTask
        task = BuildTask.from_dict(call(self.host, "candidate.read", {"candidate_id":job["candidate_id"]})["task"])
        window=next(v for v in self.value['forecasts'].values() if v['id']==job['forecast_id'])
        binding = {"course_binding_sha256":digest(self.course.binding), "scope_sha256":job["scope_sha256"],
                   "purpose":"validation", "stage":window["stage"], "bot_id":job["opponent"]["opponent_id"]}
        if not isinstance(bot["runtime"], CourseBotRuntime):
            binding["model_opponent"] = bot["runtime"].identity()
        match = MatchState(job["job_id"], (MatchParticipant("actor", DeckParts.from_dict(job["deck"])),
            MatchParticipant("opponent", canonical_deck(bot["deck"]))), self.course.rules,
            binding,
            "actor" if job["actor_seat"] == 0 else "opponent", adapter_revision=self.course.assets.adapter_revision)
        receipts, started = [], time.monotonic()
        with self._frozen_models(models):
            while True:
                if match.status == "awaiting_sideboards":
                    side = ModelSideboardPolicy(models.builder.models["build_optimizer"], models.builder.encoder,
                        task, self.course.assets, self.course.rules)
                    match.submit_sideboards({"actor": side(match.intermission_request("actor")), "opponent": keep_side(match.intermission_request("opponent"))})
                if match.status == "awaiting_first_choice":
                    loser = match._loser
                    match.choose_next_first(loser, FirstOrderPolicy("always_first" if loser == "actor" else bot["first_order"])(match.intermission_request(loser)))
                if match.status != "ready":
                    break
                budget = getattr(self,"_evaluation_budget",None)
                if budget is not None: budget.check("before_monitor_small_game", required=models.duel.config.episode_seconds)
                runtime = {"bot_runtime": bot["runtime"]} if isinstance(bot["runtime"], CourseBotRuntime) else {"model_runtime": bot["runtime"]}
                if "model_runtime" in runtime and bot["runtime"].policy_mode == "sample":
                    import torch
                    runtime["opponent_policy_rng"] = torch.Generator(device="cpu").manual_seed(int(digest(job)[:16], 16) % (2**63-1))
                adapter = CourseGameAdapter(assets=self.course.assets, match_state=match, actor_participant_id="actor",
                    trainer=models.duel, adapter_session=models.sessions.get("duel"), **runtime,
                    data_index=self.course.data_index, experiment_id=self.course.config["course_id"], purpose="validation",
                    policy_rng=models.policy_rng, evaluation_pairs=tuple(map(tuple, self.course.config["evaluation_pairs"]["validation"])),
                    evaluation_cursor=self.value["monitor_cursor"])
                spec = match.issue_game_spec()
                result = adapter(spec)
                match.record_game(spec, result)
                receipts.append(deepcopy(adapter.last_receipt))
                self.value["monitor_cursor"] += 1  # Failed attempts cannot reuse seeds.
                self.save()
                if job["scope"]["unit"] == "BO1":
                    break
        self.course.active_seconds += time.monotonic() - started
        self.course.save()
        view = match.summary()
        if any(r["status"] != "completed" for r in receipts):
            outcome, diagnosis = "crash", "system_error"
        elif job["scope"]["unit"] == "BO1":
            winner = view["games"][0]["winner_participant_id"]
            outcome, diagnosis = ("win" if winner == "actor" else "draw" if winner is None else "loss"), "none"
        elif view["status"] == "complete":
            outcome, diagnosis = ("win" if view["match_winner"] == "actor" else "loss"), "none"
        else:
            outcome, diagnosis = "draw", "unknown"
        audit = {"job": job, "receipts": receipts, "match": view, "formal_training_credit": 0, "forecast_supervision": False}
        (self.target / (job["job_id"] + ".json")).write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
        return {"outcome": outcome, "diagnosis": diagnosis, "audit_sha256": digest(audit)}
