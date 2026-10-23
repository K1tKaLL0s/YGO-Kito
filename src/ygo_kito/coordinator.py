"""Role-scoped rule control and append-only forecast/result history.

Forecasts precede jobs; repeated observations use a frozen engineering policy.
No method clears warnings, erases results, or bypasses required reconstruction.
"""

from contextlib import closing
import json
from pathlib import Path
import random
import sqlite3

from .agent_registry import identifier
from .build_contracts import BuildTask, DeckParts, digest
from .build_pipeline import verify_goal
from .coord_contracts import (FeedbackPolicy, OUTCOMES, SOURCES, evaluation_scope, probability, rule_route, sha256)
from .validation import ContractError, array, canonical_json, fields, integer, member, text

APPLICATION_ID = 0x59474F43
READ = {"status", "history", "candidate.read", "forecast.read", "job.read"}
PERMISSIONS = {"monitor": READ,
               "build_goal": READ | {"handoff.submit", "forecast.register"},
               "build_optimizer": READ | {"handoff.submit", "forecast.register"},
               "coordinator": READ | {"handoff.submit", "forecast.register", "job.schedule", "route"},
               "duel_worker": {"job.read", "job.claim", "results.append"}}


def versioned_proof(value):
    """Timing is measured in private run receipts, not candidate identity."""
    if isinstance(value,dict):return {k:versioned_proof(v) for k,v in value.items() if k!='elapsed_seconds'}
    if isinstance(value,list):return [versioned_proof(v) for v in value]
    return value


class Coordinator:
    def __init__(self, path, policy, *, role="monitor", source="real_engine", assets=None, create=False):
        member(role, "coordinator role", tuple(PERMISSIONS))
        member(source, "coordinator evidence source", SOURCES)
        if not isinstance(policy, FeedbackPolicy):
            raise ContractError("typed feedback policy required")
        requested = Path(path).absolute()
        if requested.is_symlink():
            raise ContractError("coordinator database symlinks unsupported")
        self.path, self.policy = requested.resolve(), policy
        self.role, self.source, self.assets = role, source, assets
        if not self.path.exists():
            if not create or role == "monitor":
                raise ContractError("coordinator ledger unavailable; no synthetic state created")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                    raise ContractError("refusing to initialize an existing foreign database")
                db.execute("CREATE TABLE meta(key TEXT PRIMARY KEY,payload TEXT NOT NULL)")
                db.execute("CREATE TABLE candidates(id TEXT PRIMARY KEY,root TEXT NOT NULL,parent TEXT,goal_key TEXT NOT NULL,deck_sha TEXT NOT NULL,env_sha TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(goal_key,deck_sha,env_sha))")
                db.execute("CREATE TABLE forecasts(id TEXT PRIMARY KEY,candidate_id TEXT NOT NULL REFERENCES candidates(id),scope_key TEXT UNIQUE NOT NULL,ordinal INTEGER UNIQUE NOT NULL,payload TEXT NOT NULL,n INTEGER NOT NULL DEFAULT 0,wins INTEGER NOT NULL DEFAULT 0,score_sum REAL NOT NULL DEFAULT 0,counts TEXT NOT NULL DEFAULT '{}')")
                db.execute("CREATE TABLE jobs(id TEXT PRIMARY KEY,forecast_id TEXT NOT NULL REFERENCES forecasts(id),payload TEXT NOT NULL,state TEXT NOT NULL,worker TEXT)")
                db.execute("CREATE TABLE results(id TEXT PRIMARY KEY,job_id TEXT UNIQUE NOT NULL REFERENCES jobs(id),forecast_id TEXT NOT NULL REFERENCES forecasts(id),payload TEXT NOT NULL)")
                db.execute("CREATE TABLE checks(forecast_id TEXT NOT NULL,n INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(forecast_id,n))")
                db.execute("CREATE TABLE alerts(forecast_id TEXT NOT NULL,kind TEXT NOT NULL,n INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(forecast_id,kind))")
                db.execute("CREATE TABLE decisions(seq INTEGER PRIMARY KEY,payload TEXT NOT NULL)")
                db.execute("INSERT INTO meta VALUES('binding',?)", (canonical_json({"schema_version": 1, "source": source, "policy": policy.to_dict()}),))
                db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                db.execute("PRAGMA user_version=1")
        with self._db() as db:
            meta = json.loads(db.execute("SELECT payload FROM meta WHERE key='binding'").fetchone()[0])
            if meta != {"schema_version": 1, "source": source, "policy": policy.to_dict()}:
                raise ContractError("ledger source/policy immutable; inspect old strata rather than resetting")

    def _db(self):
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        if db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID or db.execute("PRAGMA user_version").fetchone()[0] != 1:
            db.close()
            raise ContractError("foreign/incompatible coordinator database")
        return closing(db)

    @staticmethod
    def _row(db, table, record_id):
        identifier(record_id)
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise ContractError("coordinator record not found")
        return row

    @staticmethod
    def _event(db, payload):
        db.execute("INSERT INTO decisions(payload) VALUES(?)", (canonical_json(payload),))

    def _has_alert(self, db, candidate_id, kind):
        root = self._row(db, "candidates", candidate_id)["root"]
        return bool(db.execute("SELECT 1 FROM alerts a JOIN forecasts f ON f.id=a.forecast_id JOIN candidates c ON c.id=f.candidate_id WHERE c.root=? AND a.kind=? LIMIT 1", (root, kind)).fetchone())

    def _required(self, db, candidate_id):
        return self._has_alert(db, candidate_id, "mandatory_rebuild")

    def _candidate(self, params):
        d = fields(params, {"candidate_id", "parent_candidate_id", "task", "deck", "build_models"})
        identifier(d["candidate_id"])
        if d["parent_candidate_id"] is not None:
            identifier(d["parent_candidate_id"])
        fields(d["build_models"], {"build_goal", "build_optimizer"})
        for value in d["build_models"].values():
            sha256(value)
        task, deck = BuildTask.from_dict(d["task"]), DeckParts.from_dict(d["deck"])
        deck = DeckParts(*(tuple(sorted(getattr(deck, zone))) for zone in ("main", "extra", "side")))
        goal_key = digest({"goal": task.goal, "requirements": task.requirements, "sizes": task.sizes})
        deck_hash, env_hash = digest(deck.to_dict()), digest(task.environment)
        # Source is host configuration, never a request override.
        if self.source == "real_engine":
            if self.assets is None:
                raise ContractError("real handoff requires explicit locked assets")
            validation = verify_goal(task, deck, self.assets)
            from .build_semantics import accepted_status
            if validation["status"] != accepted_status(task):
                raise ContractError("handoff goal route not verified; not accepted as valid")
            validation = versioned_proof(validation)
        else:
            validation = {"status": "synthetic_contract_only", "card_list_legal": None, "core_executed": False}
        payload = dict(d, deck=deck.to_dict(), source=self.source, task_sha256=task.sha256, goal_key=goal_key, deck_sha256=deck_hash,
                       validation=validation, candidate_quality_validated=False)
        with self._db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT payload FROM candidates WHERE id=?", (d["candidate_id"],)).fetchone()
            if old:
                if old[0] != canonical_json(payload):
                    raise ContractError("candidate identity conflict; preserve lineage")
                return json.loads(old[0])
            if d["parent_candidate_id"] is not None:
                parent = self._row(db, "candidates", d["parent_candidate_id"])
                if parent["goal_key"] != goal_key:
                    raise ContractError("reconstruction must preserve original hard goal")
                root = parent["root"]
            else:
                if db.execute("SELECT 1 FROM candidates WHERE goal_key=?", (goal_key,)).fetchone():
                    raise ContractError("new candidate version must retain its parent lineage")
                root = d["candidate_id"]
            if db.execute("SELECT 1 FROM candidates WHERE goal_key=? AND deck_sha=? AND env_sha=?", (goal_key, deck_hash, env_hash)).fetchone():
                raise ContractError("same deck cannot be renamed to reset feedback")
            db.execute("INSERT INTO candidates VALUES(?,?,?,?,?,?,?)", (d["candidate_id"], root, d["parent_candidate_id"], goal_key, deck_hash, env_hash, canonical_json(payload)))
            self._event(db, {"event": "handoff_accepted", "candidate_id": d["candidate_id"], "root": root, "source": self.source})
        return payload

    def _forecast(self, params):
        d = fields(params, {"forecast_id", "candidate_id", "probability", "origin_role", "model_sha256", "calibration", "scope"})
        identifier(d["forecast_id"])
        probability(d["probability"], "predicted rate")
        member(d["origin_role"], "prediction origin", ("build_goal", "build_optimizer", "coordinator"))
        if self.role != "coordinator" and self.role != d["origin_role"]:
            raise ContractError("builder cannot impersonate another prediction role")
        sha256(d["model_sha256"])
        if d["calibration"] != "pending":
            raise ContractError("prediction calibration not established by this prototype")
        with self._db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            candidate = json.loads(self._row(db, "candidates", d["candidate_id"])["payload"])
            scope = evaluation_scope(d["scope"], candidate, self.policy)
            if d["origin_role"] != "coordinator" and d["model_sha256"] != candidate["build_models"][d["origin_role"]]:
                raise ContractError("prediction builder model differs from handoff")
            payload = dict(d, probability=float(d["probability"]), scope=scope, source=self.source, policy=self.policy.to_dict())
            encoded = canonical_json(payload)
            old = db.execute("SELECT payload FROM forecasts WHERE id=?", (d["forecast_id"],)).fetchone()
            if old:
                if old[0] != encoded:
                    raise ContractError("forecast immutable; cannot lower prediction/reset warning")
                return json.loads(old[0])
            scope_key = digest({"goal_key": candidate["goal_key"], "deck_sha256": candidate["deck_sha256"], "scope": scope, "source": self.source})
            if db.execute("SELECT 1 FROM forecasts WHERE scope_key=?", (scope_key,)).fetchone():
                raise ContractError("scope already has a prediction; new ID cannot reset its history")
            ordinal = db.execute("SELECT COUNT(*)+1 FROM forecasts").fetchone()[0]
            db.execute("INSERT INTO forecasts(id,candidate_id,scope_key,ordinal,payload) VALUES(?,?,?,?,?)", (d["forecast_id"], d["candidate_id"], scope_key, ordinal, encoded))
            self._event(db, {"event": "prediction_registered_before_games", "forecast_id": d["forecast_id"], "ordinal": ordinal, "scope_sha256": scope_key, "source": self.source})
        return payload

    def _schedule(self, params):
        d = fields(params, {"job_id", "forecast_id", "seed", "purpose"})
        identifier(d["job_id"])
        integer(d["seed"], "controller seed", 0, 2**32 - 8)
        member(d["purpose"], "job purpose", ("engineering_validation", "evaluation", "rebuild_validation"))
        with self._db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            f = self._row(db, "forecasts", d["forecast_id"])
            candidate = json.loads(self._row(db, "candidates", f["candidate_id"])["payload"])
            required = self._required(db, f["candidate_id"])
            if required and (d["purpose"] != "rebuild_validation" or candidate["parent_candidate_id"] is None):
                raise ContractError("mandatory reconstruction blocks further ordinary duel jobs")
            scope = json.loads(f["payload"])["scope"]
            rng = random.Random(d["seed"])
            opponent = rng.choices(scope["opponents"], [o["weight"] for o in scope["opponents"]])[0]
            seat = rng.choices((0, 1), scope["initiative_weights"])[0]
            payload = dict(d, candidate_id=f["candidate_id"], source=self.source, scope_sha256=f["scope_key"], scope=scope,
                           deck=candidate["deck"], task_sha256=candidate["task_sha256"], opponent=opponent, actor_seat=seat)
            encoded = canonical_json(payload)
            old = db.execute("SELECT payload FROM jobs WHERE id=?", (d["job_id"],)).fetchone()
            if old:
                if old[0] != encoded:
                    raise ContractError("job ID conflict")
                return json.loads(old[0])
            if db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('pending','leased')").fetchone()[0] >= 1:
                raise ContractError("one outstanding job budget reached; collect or inspect it before scheduling")
            db.execute("INSERT INTO jobs VALUES(?,?,?,'pending',NULL)", (d["job_id"], d["forecast_id"], encoded))
            self._event(db, {"event": "duel_job_allocated", "job_id": d["job_id"], "forecast_id": d["forecast_id"], "source": self.source})
        return payload

    def _claim(self, params):
        d = fields(params, {"job_id", "worker_id"})
        identifier(d["worker_id"])
        with self._db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            job = self._row(db, "jobs", d["job_id"])
            if job["state"] != "pending":
                raise ContractError("job already leased/completed; inspect before retrying")
            db.execute("UPDATE jobs SET state='leased',worker=? WHERE id=?", (d["worker_id"], d["job_id"]))
            return dict(json.loads(job["payload"]), worker_id=d["worker_id"], state="leased")

    def _results(self, params):
        fields(params, {"results"})
        rows = array(params["results"], "results")
        integer(len(rows), "result batch size", 1, 1000)
        affected = set()
        with self._db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            for result in rows:
                d = fields(result, {"result_id", "job_id", "worker_id", "forecast_id", "candidate_id", "scope_sha256",
                                    "source", "unit", "outcome", "audit_sha256", "diagnosis"})
                identifier(d["result_id"])
                member(d["outcome"], "duel outcome", OUTCOMES)
                member(d["diagnosis"], "duel diagnosis", ("none", "unknown", "operation_error", "system_error", "construction_unstable"))
                sha256(d["audit_sha256"])
                encoded = canonical_json(d)
                old = db.execute("SELECT payload FROM results WHERE id=? OR job_id=?", (d["result_id"], d["job_id"])).fetchone()
                if old:
                    if old[0] != encoded:
                        raise ContractError("result ID/job conflict; cannot rewrite evidence")
                    affected.add(d["forecast_id"])
                    continue
                job = self._row(db, "jobs", d["job_id"])
                info = json.loads(job["payload"])
                if (job["state"] != "leased" or job["worker"] != d["worker_id"] or d["source"] != self.source or
                        any(d[k] != info[k] for k in ("forecast_id", "candidate_id", "scope_sha256")) or d["unit"] != info["scope"]["unit"]):
                    raise ContractError("result differs from leased source/version/seat/unit scope")
                f = self._row(db, "forecasts", d["forecast_id"])
                n, wins = f["n"] + 1, f["wins"] + int(d["outcome"] == "win")
                score = 1. if d["outcome"] == "win" else self.policy.draw_score if d["outcome"] == "draw" else 0.
                total = f["score_sum"] + score
                counts = json.loads(f["counts"])
                counts[d["outcome"]] = counts.get(d["outcome"], 0) + 1
                db.execute("INSERT INTO results VALUES(?,?,?,?)", (d["result_id"], d["job_id"], d["forecast_id"], encoded))
                db.execute("UPDATE jobs SET state='completed' WHERE id=?", (d["job_id"],))
                db.execute("UPDATE forecasts SET n=?,wins=?,score_sum=?,counts=? WHERE id=?", (n, wins, total, canonical_json(counts), d["forecast_id"]))
                check = self.policy.assess(n, total, json.loads(f["payload"])["probability"], f["ordinal"])
                if check is not None:
                    db.execute("INSERT INTO checks VALUES(?,?,?)", (d["forecast_id"], n, canonical_json(check)))
                    if check["low"]:
                        kinds = ("reevaluate",) if n <= 100 else ("reevaluate", "mandatory_rebuild")
                        for kind in kinds:
                            db.execute("INSERT OR IGNORE INTO alerts VALUES(?,?,?,?)", (d["forecast_id"], kind, n, canonical_json(dict(check, source=self.source))))
                affected.add(d["forecast_id"])
        return {fid: self.forecast_status(fid) for fid in sorted(affected)}

    def forecast_status(self, forecast_id):
        with self._db() as db:
            f = self._row(db, "forecasts", forecast_id)
            alerts = [dict(row, payload=json.loads(row["payload"])) for row in db.execute("SELECT kind,n,payload FROM alerts WHERE forecast_id=? ORDER BY n,kind", (forecast_id,))]
            checks = [json.loads(r[0]) for r in db.execute("SELECT payload FROM checks WHERE forecast_id=? ORDER BY n", (forecast_id,))]
            return {"forecast": json.loads(f["payload"]), "scope_sha256": f["scope_key"], "forecast_ordinal": f["ordinal"],
                    "matches": f["n"], "wins": f["wins"], "observed_win_rate": f["wins"] / f["n"] if f["n"] else None,
                    "score_mean": f["score_sum"] / f["n"] if f["n"] else None, "outcome_counts": json.loads(f["counts"]),
                    "alerts": alerts, "checks": checks, "mandatory_rebuild": self._required(db, f["candidate_id"]),
                    "source": self.source, "calibration": "pending"}

    def _route(self, params):
        d = fields(params, {"candidate_id", "forecast_id", "remaining_tasks", "advisory"})
        integer(d["remaining_tasks"], "remaining tasks", 0, 10000)
        with self._db() as db:
            candidate = json.loads(self._row(db, "candidates", d["candidate_id"])["payload"])
            required = self._required(db, d["candidate_id"])
            warning = self._has_alert(db, d["candidate_id"], "reevaluate")
        status = self.forecast_status(d["forecast_id"]) if d["forecast_id"] is not None else None
        if status and status["forecast"]["candidate_id"] != d["candidate_id"]:
            raise ContractError("route forecast belongs to another candidate")
        context = {"goal_valid": candidate["validation"]["status"] in ("verified_success", "constraints_satisfied", "constraints_and_route_verified", "synthetic_contract_only"),
                   "card_list_valid": True, "has_forecast": status is not None, "warning": warning,
                   "rebuild_required": required, "operation_error": bool(status and status["outcome_counts"].get("invalid_action")),
                   "system_error": bool(status and any(status["outcome_counts"].get(k) for k in ("timeout", "crash"))),
                   "remaining_tasks": d["remaining_tasks"], "completed_matches": status["matches"] if status else 0,
                   "score_mean": status["score_mean"] if status else None,
                   "forecast": status["forecast"]["probability"] if status else None}
        action, reason = rule_route(context)
        if d["advisory"] is not None:
            fields(d["advisory"], {"route", "model_sha256", "calibration"})
            member(d["advisory"]["route"], "model advisory route", ("build_goal", "build_optimizer", "register_forecast", "evaluate_duel", "train_duel", "diagnose", "stop"))
            sha256(d["advisory"]["model_sha256"])
            if d["advisory"]["calibration"] != "pending":
                raise ContractError("advisory model calibration is pending")
        event = {"event": "route_decision", "candidate_id": d["candidate_id"], "forecast_id": d["forecast_id"],
                 "source": self.source, "mode": "rule_authoritative", "context": context,
                 "action": action, "reason": reason, "advisory": d["advisory"], "rebuild_required": required}
        with self._db() as db, db:
            self._event(db, event)
        return event

    def history(self):
        with self._db() as db:
            return [dict(seq=r[0], **json.loads(r[1])) for r in db.execute("SELECT seq,payload FROM decisions ORDER BY seq")]

    def state_digest(self):
        with self._db() as db:
            rows = {table: [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY 1,2")]
                    for table in ("meta", "candidates", "forecasts", "jobs", "results", "checks", "alerts", "decisions")}
        return digest(rows)

    def dispatch(self, request):
        ident = None
        try:
            d = fields(request, {"schema_version", "id", "method", "params"})
            integer(d["schema_version"], "coordinator API schema", 1, 1)
            ident = identifier(d["id"])
            text(d["method"], "coordinator method")
            if d["method"] not in PERMISSIONS[self.role]:
                return {"schema_version": 1, "id": ident, "ok": False, "error": {"code": "PERMISSION_DENIED", "message": "method unavailable to fixed host role"}}
            method, params = d["method"], d["params"]
            if method in ("handoff.submit", "forecast.register", "job.schedule", "job.claim", "results.append", "route"):
                result = {"handoff.submit": self._candidate, "forecast.register": self._forecast, "job.schedule": self._schedule,
                          "job.claim": self._claim, "results.append": self._results, "route": self._route}[method](params)
            elif method == "forecast.read":
                fields(params, {"forecast_id"})
                result = self.forecast_status(params["forecast_id"])
            elif method in ("candidate.read", "job.read"):
                key, table = ("candidate_id", "candidates") if method == "candidate.read" else ("job_id", "jobs")
                fields(params, {key})
                with self._db() as db:
                    row = self._row(db, table, params[key])
                    result = dict(json.loads(row["payload"]), **({"state": row["state"]} if table == "jobs" else {}))
            elif method == "history":
                fields(params, set())
                result = self.history()
            else:
                fields(params, set())
                with self._db() as db:
                    result = {"source": self.source, "policy": self.policy.to_dict(), "role": self.role,
                              "counts": {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("candidates", "forecasts", "jobs", "results", "alerts")},
                              "mode": "rule_authoritative", "statistics_calibrated": False}
            return {"schema_version": 1, "id": ident, "ok": True, "result": json.loads(canonical_json(result))}
        except ContractError as error:
            return {"schema_version": 1, "id": ident, "ok": False, "error": {"code": "INVALID_INPUT", "message": str(error)}}
        except (sqlite3.Error, OSError):
            return {"schema_version": 1, "id": ident, "ok": False, "error": {"code": "STORAGE_ERROR", "message": "coordinator storage unavailable"}}
