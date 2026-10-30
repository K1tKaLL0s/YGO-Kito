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
from .proof_visibility import without_private_selection_key
from .validation import ContractError, array, canonical_json, fields, integer, member, text

APPLICATION_ID = 0x59474F43
READ = {"status", "history", "candidate.read", "forecast.read", "job.read"}
PERMISSIONS = {"monitor": READ,
               "build_goal": READ | {"handoff.submit", "forecast.register"},
               "build_optimizer": READ | {"handoff.submit", "forecast.register"},
               "coordinator": READ | {"handoff.submit", "forecast.register", "job.schedule", "route", "rebuild.resolve"},
               "duel_worker": {"job.read", "job.claim", "results.append"}}


def versioned_proof(value):
    """Timing is measured in private run receipts, not candidate identity."""
    def without_timing(item):
        if isinstance(item, dict):
            return {k: without_timing(v) for k, v in item.items() if k != "elapsed_seconds"}
        if isinstance(item, list):
            return [without_timing(v) for v in item]
        return item
    return without_private_selection_key(without_timing(value))


class Coordinator:
    def __init__(self, path, policy, *, role="monitor", source="real_engine", assets=None, create=False, candidate_verifier=None):
        member(role, "coordinator role", tuple(PERMISSIONS))
        member(source, "coordinator evidence source", SOURCES)
        if not isinstance(policy, FeedbackPolicy):
            raise ContractError("typed feedback policy required")
        if not policy.definitions_ready:raise ContractError('forecast policy definitions missing: '+','.join(policy.missing_definitions))
        requested = Path(path).absolute()
        if requested.is_symlink():
            raise ContractError("coordinator database symlinks unsupported")
        self.path, self.policy = requested.resolve(), policy
        self.role, self.source, self.assets = role, source, assets
        self.candidate_verifier = candidate_verifier  # Trusted host callback, never an RPC field.
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
        return bool(self._unresolved_forecasts(db, candidate_id, kind))

    def _unresolved_forecasts(self, db, candidate_id, kind):
        root = self._row(db, "candidates", candidate_id)["root"]
        resolved = (" AND NOT EXISTS(SELECT 1 FROM resolutions r WHERE r.forecast_id=a.forecast_id AND r.kind=a.kind)"
                    if db.execute("SELECT 1 FROM sqlite_master WHERE name='resolutions'").fetchone() else "")
        return [r[0] for r in db.execute("SELECT a.forecast_id FROM alerts a JOIN forecasts f ON f.id=a.forecast_id "
            "JOIN candidates c ON c.id=f.candidate_id WHERE c.root=? AND a.kind=?" + resolved + " ORDER BY a.forecast_id", (root, kind))]

    def _required(self, db, candidate_id):
        return self._has_alert(db, candidate_id, "mandatory_rebuild")

    def _own_pending_review(self, db, candidate_id):
        pending = set(self._unresolved_forecasts(db, candidate_id, "reevaluate"))
        return any(r[0] in pending for r in db.execute("SELECT id FROM forecasts WHERE candidate_id=?", (candidate_id,)))

    def _review_validation_eligible(self, db, candidate_id):
        payload = json.loads(self._row(db,"candidates",candidate_id)["payload"])
        reviews = self._unresolved_forecasts(db,candidate_id,"reevaluate")
        return bool(reviews) and payload.get("review_after_forecasts") == reviews and not self._own_pending_review(db,candidate_id)

    def _mandatory_forecasts(self, db, candidate_id):
        return self._unresolved_forecasts(db, candidate_id, "mandatory_rebuild")

    def _rebuild_validation_eligible(self, db, candidate_id):
        candidate = self._row(db, "candidates", candidate_id)
        payload = json.loads(candidate["payload"])
        if payload["parent_candidate_id"] is None:
            return False
        parent = self._row(db, "candidates", payload["parent_candidate_id"])
        if candidate["deck_sha"] == parent["deck_sha"]:
            return False  # Changing environment, driver or parent is not reconstruction.
        mandatory = self._mandatory_forecasts(db, candidate_id)
        failed_decks = {row[0] for row in db.execute(
            "SELECT c.deck_sha FROM alerts a JOIN forecasts f ON f.id=a.forecast_id "
            "JOIN candidates c ON c.id=f.candidate_id WHERE c.root=? AND a.kind='mandatory_rebuild'",
            (candidate["root"],))}
        # This host-owned anchor is fixed at first acceptance. Existing/legacy
        # candidates and handoff retries cannot become a new response to a
        # later mandatory alert. Historical warnings and counts stay intact.
        return (bool(mandatory) and payload.get("rebuild_after_forecasts") == mandatory
                and candidate["deck_sha"] not in failed_decks)

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
        submission = dict(d, deck=deck.to_dict())

        def existing_receipt(row):
            saved = json.loads(row["payload"])
            # A retry identifies the submitted candidate, not a fresh private
            # verification trajectory. Keep the first accepted proof immutable.
            if (any(key not in saved for key in submission)
                    or canonical_json({key: saved[key] for key in submission}) != canonical_json(submission)
                    or saved.get("source") != self.source or saved.get("task_sha256") != task.sha256
                    or saved.get("deck_sha256") != deck_hash or saved.get("goal_key") != goal_key
                    or row["deck_sha"] != deck_hash or row["env_sha"] != env_hash or row["goal_key"] != goal_key):
                raise ContractError("candidate identity conflict; preserve lineage")
            if self.source == "real_engine":
                if self.assets is None:
                    raise ContractError("real handoff requires explicit locked assets")
                integrity = getattr(self.assets, "assert_integrity", None)
                if integrity is not None:
                    integrity()
                self.assets.check_task(task)
                self.assets.validate(task, deck)
            return saved

        with self._db() as db:
            old = db.execute("SELECT payload,deck_sha,env_sha,goal_key FROM candidates WHERE id=?", (d["candidate_id"],)).fetchone()
            if old:
                return existing_receipt(old)
        # Source is host configuration, never a request override.
        if self.source == "real_engine":
            if self.assets is None:
                raise ContractError("real handoff requires explicit locked assets")
            validation = (self.candidate_verifier(task, deck, self.assets) if self.candidate_verifier is not None
                          else verify_goal(task, deck, self.assets))
            from .build_semantics import accepted_status
            if validation["status"] != accepted_status(task):
                raise ContractError("handoff goal route not verified; not accepted as valid")
            validation = versioned_proof(validation)
        else:
            validation = {"status": "synthetic_contract_only", "card_list_legal": None, "core_executed": False}
        payload = dict(submission, source=self.source, task_sha256=task.sha256, goal_key=goal_key, deck_sha256=deck_hash,
                       validation=validation, candidate_quality_validated=False)
        with self._db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT payload,deck_sha,env_sha,goal_key FROM candidates WHERE id=?", (d["candidate_id"],)).fetchone()
            if old:
                return existing_receipt(old)
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
            payload["rebuild_after_forecasts"] = (self._mandatory_forecasts(db, d["parent_candidate_id"])
                                                    if d["parent_candidate_id"] is not None else [])
            payload["review_after_forecasts"] = (self._unresolved_forecasts(db, d["parent_candidate_id"], "reevaluate")
                                                  if d["parent_candidate_id"] is not None else [])
            db.execute("INSERT INTO candidates VALUES(?,?,?,?,?,?,?)", (d["candidate_id"], root, d["parent_candidate_id"], goal_key, deck_hash, env_hash, canonical_json(payload)))
            self._event(db, {"event": "handoff_accepted", "candidate_id": d["candidate_id"], "root": root, "source": self.source})
        return payload

    def _resolve_rebuild(self, params):
        d = fields(params, {"candidate_id", "validation_forecast_id"})
        with self._db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            candidate = self._row(db, "candidates", d["candidate_id"])
            payload = json.loads(candidate["payload"])
            validation = self._row(db, "forecasts", d["validation_forecast_id"])
            if validation["candidate_id"] != d["candidate_id"] or validation["n"] < self.policy.minimum_matches:
                raise ContractError("reconstruction requires its own scoped validation window")
            mandatory = self._mandatory_forecasts(db, d["candidate_id"])
            reviews = self._unresolved_forecasts(db, d["candidate_id"], "reevaluate")
            if not mandatory and not reviews:
                return {"closed":[], "history_preserved":True}
            latest = db.execute("SELECT payload FROM checks WHERE forecast_id=? ORDER BY n DESC LIMIT 1", (validation["id"],)).fetchone()
            if latest is not None and json.loads(latest[0])["low"]:
                raise ContractError("underperforming reconstruction cannot close alerts")
            if self._own_pending_review(db,d["candidate_id"]):
                raise ContractError("new candidate has its own unresolved warning; reconstruct again")
            if mandatory and not self._rebuild_validation_eligible(db, d["candidate_id"]):
                raise ContractError("calling construction is not a newly verified reconstruction")
            if not mandatory and reviews:
                parent_id = payload["parent_candidate_id"]
                if (not parent_id or candidate["deck_sha"] == self._row(db, "candidates", parent_id)["deck_sha"] or
                        payload.get("review_after_forecasts") != reviews):
                    raise ContractError("reevaluation needs the changed candidate accepted after its alerts")
            db.execute("CREATE TABLE IF NOT EXISTS resolutions(forecast_id TEXT NOT NULL,kind TEXT NOT NULL,candidate_id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(forecast_id,kind))")
            closed = []
            for kind, forecasts in (("mandatory_rebuild", mandatory), ("reevaluate", reviews)):
                for forecast_id in forecasts:
                    receipt = dict(d, forecast_id=forecast_id, kind=kind, validation_matches=validation["n"])
                    db.execute("INSERT INTO resolutions VALUES(?,?,?,?)", (forecast_id, kind, d["candidate_id"], canonical_json(receipt)))
                    closed.append(receipt)
            self._event(db, {"event": "reconstruction_validated", **d, "closed": closed})
            return {"closed": closed, "history_preserved": True}

    def record_construction_review(self, candidate_id, receipt):
        """Trusted host-only completion, deliberately absent from the RPC methods.

        A warning requests reassessment; it does not force a different deck.
        Mandatory reconstruction still requires its changed child/validation.
        """
        if self.role!='coordinator':raise ContractError('construction review is a host operation')
        fields(receipt,{'kind','cycle_id','task_sha256','deployed_deck_sha256','trace_sha256',
                        'roles','task_verified','basic_cb_inference_performed','reviewed_forecasts'})
        if (receipt['kind']!='completed_four_step_construction_review_v2' or receipt['task_verified'] is not True or
                receipt['basic_cb_inference_performed'] is not True or
                receipt['roles']!=['build_goal','build_optimizer','build_goal','build_optimizer']):
            raise ContractError('a complete actual four-step/basic-CB review is required')
        for key in ('task_sha256','deployed_deck_sha256','trace_sha256'):sha256(receipt[key])
        identifier(receipt['cycle_id'])
        with self._db() as db,db:
            db.execute('BEGIN IMMEDIATE')
            candidate=self._row(db,'candidates',candidate_id);payload=json.loads(candidate['payload'])
            if payload['task_sha256']!=receipt['task_sha256'] or candidate['deck_sha']!=receipt['deployed_deck_sha256']:
                raise ContractError('review is not for the deployed task/deck')
            if self._required(db,candidate_id):raise ContractError('review cannot waive mandatory reconstruction')
            pending=self._unresolved_forecasts(db,candidate_id,'reevaluate')
            if receipt['reviewed_forecasts']!=pending:raise ContractError('review scope differs from the pending alerts')
            if not pending:return {'closed':[],'history_preserved':True}
            db.execute('CREATE TABLE IF NOT EXISTS resolutions(forecast_id TEXT NOT NULL,kind TEXT NOT NULL,candidate_id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(forecast_id,kind))')
            for forecast_id in pending:
                db.execute('INSERT INTO resolutions VALUES(?,?,?,?)',(forecast_id,'reevaluate',candidate_id,canonical_json(receipt)))
            self._event(db,{'event':'construction_reassessed','candidate_id':candidate_id,'receipt':receipt})
            return {'closed':pending,'history_preserved':True}

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
            if required and d["purpose"] != "rebuild_validation":
                raise ContractError("mandatory reconstruction blocks further ordinary duel jobs")
            if required and not self._rebuild_validation_eligible(db, f["candidate_id"]):
                raise ContractError("mandatory reconstruction requires a changed child accepted after the current mandatory alerts")
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
                                    "source", "unit", "outcome", "audit_sha256", "diagnosis"},
                    {'core_terminal_received','termination_kind','sample_completed','model_update_started','model_update_completed'}
                    if self.policy.terminal_matches_only else set())
                identifier(d["result_id"])
                member(d["outcome"], "duel outcome", OUTCOMES + (('compute_truncated',) if self.policy.terminal_matches_only else ()))
                member(d["diagnosis"], "duel diagnosis", ("none", "unknown", "operation_error", "system_error", "construction_unstable"))
                sha256(d["audit_sha256"])
                if self.policy.terminal_matches_only:
                    if type(d.get('core_terminal_received')) is not bool:
                        raise ContractError('new policy results require an explicit native terminal boundary')
                    if d['outcome'] in ('win','loss','draw') and d['diagnosis']=='none' and d['core_terminal_received'] is not True:
                        raise ContractError('a completed match outcome requires a native terminal event')
                    if d['outcome']=='compute_truncated' and (d['core_terminal_received'] is not False or
                            d.get('termination_kind')!='compute_budget' or
                            any(d.get(flag) is not False for flag in ('sample_completed','model_update_started','model_update_completed'))):
                        raise ContractError('compute truncation requires an explicit nonterminal no-update boundary')
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
                counted=(not self.policy.terminal_matches_only or
                    (d['core_terminal_received'] is True and d['outcome'] in ('win','loss','draw') and d['diagnosis']=='none'))
                n, wins = f["n"] + int(counted), f["wins"] + int(counted and d["outcome"] == "win")
                score = (1. if d["outcome"] == "win" else self.policy.draw_score if d["outcome"] == "draw" else 0.) if counted else 0.
                total = f["score_sum"] + score
                counts = json.loads(f["counts"])
                counts[d["outcome"]] = counts.get(d["outcome"], 0) + 1
                db.execute("INSERT INTO results VALUES(?,?,?,?)", (d["result_id"], d["job_id"], d["forecast_id"], encoded))
                db.execute("UPDATE jobs SET state='completed' WHERE id=?", (d["job_id"],))
                db.execute("UPDATE forecasts SET n=?,wins=?,score_sum=?,counts=? WHERE id=?", (n, wins, total, canonical_json(counts), d["forecast_id"]))
                check = self.policy.assess(n, total, json.loads(f["payload"])["probability"], f["ordinal"]) if counted else None
                if check is not None:
                    db.execute("INSERT INTO checks VALUES(?,?,?)", (d["forecast_id"], n, canonical_json(check)))
                    for kind in self.policy.alert_kinds(check):
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
                    "rebuild_validation_eligible": self._rebuild_validation_eligible(db, f["candidate_id"]),
                    "pending_review": self._has_alert(db,f["candidate_id"],"reevaluate"),
                    "pending_review_forecasts": self._unresolved_forecasts(db,f["candidate_id"],"reevaluate"),
                    "own_pending_review": self._own_pending_review(db,f["candidate_id"]),
                    "source": self.source, "calibration": "pending"}

    def _route(self, params):
        d = fields(params, {"candidate_id", "forecast_id", "remaining_tasks", "advisory"}, {"allowed_routes", "max_units"})
        integer(d["remaining_tasks"], "remaining tasks", 0, 10000)
        with self._db() as db:
            candidate = json.loads(self._row(db, "candidates", d["candidate_id"])["payload"])
            required = self._required(db, d["candidate_id"])
            warning = self._has_alert(db, d["candidate_id"], "reevaluate")
            rebuild_eligible = self._rebuild_validation_eligible(db, d["candidate_id"]) if required else False
            own_review = self._own_pending_review(db,d["candidate_id"])
            review_eligible = self._review_validation_eligible(db,d["candidate_id"])
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
        mode, units = "rule_authoritative", min(1, d["remaining_tasks"])
        if d["advisory"] is not None:
            fields(d["advisory"], {"route", "model_sha256", "calibration"}, {"mode", "budget_units", "features_sha256"})
            member(d["advisory"]["route"], "model advisory route", ("build_goal", "build_optimizer", "register_forecast", "evaluate_duel", "train_duel", "diagnose", "stop"))
            sha256(d["advisory"]["model_sha256"])
            if d["advisory"]["calibration"] != "pending":
                raise ContractError("advisory model calibration is pending")
            if d["advisory"].get("mode") == "learned_control":
                integer(d["advisory"].get("budget_units"), "learned task allocation", 0, 10000)
                sha256(d["advisory"].get("features_sha256"))
                cap = integer(d.get("max_units", d["remaining_tasks"]), "host allocation cap", 0, d["remaining_tasks"])
                allowed = d.get("allowed_routes", ["build_goal", "build_optimizer", "evaluate_duel", "train_duel", "stop"])
                if not allowed or any(r not in ("build_goal", "build_optimizer", "evaluate_duel", "train_duel", "stop") for r in allowed):
                    raise ContractError("invalid complete-cycle action mask")
                # All mandatory conditions remain host decisions. A verified new
                # child may only validate, never resume ordinary training yet.
                if not cap:
                    action, reason = "stop", "host_allocation_exhausted; required rebuild stays queued"
                elif required and rebuild_eligible and not own_review and status is not None and status["matches"] < self.policy.rebuild_horizon and context["goal_valid"] and not context["system_error"] and not context["operation_error"]:
                    action, reason = "evaluate_duel", "new_reconstruction_requires_scoped_validation"
                elif (warning and not required and cap and context["goal_valid"] and not context["system_error"] and
                      not context["operation_error"] and review_eligible and status is not None and status["matches"] < self.policy.rebuild_horizon):
                    action, reason = "evaluate_duel", "new_reevaluation_candidate_requires_scoped_validation"
                elif (cap and context["goal_valid"] and not required and not warning and not context["operation_error"]
                      and not context["system_error"] and context["has_forecast"]):
                    if d["advisory"]["route"] not in allowed:
                        raise ContractError("learned action outside host eligibility mask")
                    action, reason, mode = d["advisory"]["route"], "learned_complete_cycle_choice", "learned_control"
                    if action == "evaluate_duel" and status["matches"] >= self.policy.rebuild_horizon:
                        action, reason, mode = "stop", "monitor_window_exhausted; choose a new complete-cycle action", "rule_authoritative"
                units = 0 if action == "stop" or not cap else max(1, min(cap, d["advisory"]["budget_units"]))
        event = {"event": "route_decision", "candidate_id": d["candidate_id"], "forecast_id": d["forecast_id"],
                 "source": self.source, "mode": mode, "budget_units": 0 if action == "stop" else units, "context": context,
                 "action": action, "reason": reason, "advisory": d["advisory"], "rebuild_required": required,
                 "rebuild_validation_eligible": rebuild_eligible}
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
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='resolutions'").fetchone():
                rows["resolutions"] = [dict(row) for row in db.execute("SELECT * FROM resolutions ORDER BY 1,2")]
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
            if method in ("handoff.submit", "forecast.register", "job.schedule", "job.claim", "results.append", "route", "rebuild.resolve"):
                result = {"handoff.submit": self._candidate, "forecast.register": self._forecast, "job.schedule": self._schedule,
                          "job.claim": self._claim, "results.append": self._results, "route": self._route,
                          "rebuild.resolve": self._resolve_rebuild}[method](params)
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
