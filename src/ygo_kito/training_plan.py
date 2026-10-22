"""Credential-free planning and host-reported instance-hour accounting.

No method launches a process, cloud instance, paid training or external API.
Admission checks are estimates, not reservations or permission to spend.
"""

from contextlib import closing
from decimal import Decimal
import json
import math
from pathlib import Path
import re
import sqlite3

from .agent_registry import identifier
from .build_contracts import digest
from .validation import ContractError, canonical_json, fields, integer

APPLICATION_ID = 0x59474247
STAGES = ("throughput-small-train", "ocg-2022-07", "ocg-2022-10", "ocg-2026-10",
          "lora-final-evaluation", "failure-revalidation-reserve")
GATES = ("G-01", "G-02", "P-01", "Q-02", "Q-03", "Q-04", "Q-05")
SOURCES = ("synthetic_contract_test", "host_reported_unverified")
ACTIVITIES = ("setup", "download", "train", "evaluate", "idle", "checkpoint", "awaiting_stop_confirmation")


def number(value, label, *, minimum=0., maximum=1e9):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ContractError(label + " must be finite and within its range")
    return value


def amount(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9][0-9]{0,8})(\.[0-9]{1,8})?", value):
        raise ContractError("money must be a bounded decimal string or unknown")
    return Decimal(value)


def validate_plan(value):
    fields(value, {"schema_version", "plan_id", "provider", "billing_unit", "gpu_hours_limit", "stages", "roles",
                   "stop_remaining_quota_percent", "machine_type", "gpu_count", "instance_price_per_hour", "currency",
                   "external_api_amount_limit", "paid_execution_authorized", "calibration", "required_gates", "environment_artifacts"})
    integer(value["schema_version"], "training plan schema", 1, 1)
    identifier(value["plan_id"])
    if (value["provider"] != "tencent" or value["billing_unit"] != "gpu_instance_hours" or
            value["paid_execution_authorized"] is not False or value["calibration"] != "pending"):
        raise ContractError("this planning interface cannot grant paid execution or freeze calibration")
    number(value["gpu_hours_limit"], "GPU-hour limit", minimum=.001, maximum=100)
    if not isinstance(value["stages"], list) or len(value["stages"]) != len(STAGES):
        raise ContractError("all six budget stages required")
    limits = {}
    for row in value["stages"]:
        fields(row, {"stage_id", "gpu_hours"})
        if row["stage_id"] not in STAGES or row["stage_id"] in limits:
            raise ContractError("unknown/duplicate training stage")
        number(row["gpu_hours"], "stage GPU hours", maximum=100)
        limits[row["stage_id"]] = Decimal(str(row["gpu_hours"]))
    if sum(limits.values()) > Decimal(str(value["gpu_hours_limit"])):
        raise ContractError("stage budgets exceed the total cap")
    if value["roles"] != ["duel", "build_goal", "build_optimizer", "coordinator"] or value["required_gates"] != list(GATES):
        raise ContractError("model roles and required gates cannot be omitted")
    integer(value["stop_remaining_quota_percent"], "quota stop threshold", 20, 20)
    if value["machine_type"] is not None:
        identifier(value["machine_type"])
    if value["gpu_count"] is not None:
        integer(value["gpu_count"], "planned GPUs", 1, 8)
    for key in ("instance_price_per_hour", "external_api_amount_limit"):
        amount(value[key])
    currency = value["currency"]
    if currency is not None and (not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency)):
        raise ContractError("currency must be explicit or unknown")
    if (value["instance_price_per_hour"] is not None or value["external_api_amount_limit"] is not None) != (currency is not None):
        raise ContractError("configured money requires an explicit currency")
    fields(value["environment_artifacts"], set(STAGES[1:4]))
    for artifact in value["environment_artifacts"].values():
        if artifact is not None:
            fields(artifact, {"manifest_sha256", "evidence_path"})
            from .coord_contracts import sha256
            sha256(artifact["manifest_sha256"])
            if not isinstance(artifact["evidence_path"], str) or not artifact["evidence_path"]:
                raise ContractError("environment evidence path required")
    return json.loads(canonical_json(value))


class BudgetBook:
    def __init__(self, path, plan, *, role="monitor", source="host_reported_unverified", create=False):
        if role not in ("monitor", "trainer") or source not in SOURCES:
            raise ContractError("fixed budget role/source required")
        self.plan, self.role, self.source = validate_plan(plan), role, source
        path = Path(path).absolute()
        if path.is_symlink():
            raise ContractError("budget database symlinks unsupported")
        self.path = path.resolve()
        binding = {"schema_version": 1, "plan_sha256": digest(self.plan), "source": source}
        if not path.exists():
            if not create or role != "trainer":
                raise ContractError("budget ledger unavailable; no fake usage created")
            path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                    raise ContractError("refusing existing foreign budget database")
                db.execute("CREATE TABLE meta(id INTEGER PRIMARY KEY,payload TEXT NOT NULL,revision INTEGER NOT NULL)")
                db.execute("CREATE TABLE events(id TEXT PRIMARY KEY,seq INTEGER UNIQUE NOT NULL,payload TEXT NOT NULL)")
                db.execute("INSERT INTO meta VALUES(1,?,0)", (canonical_json(binding),))
                db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                db.execute("PRAGMA user_version=1")
        with self._db() as db:
            if json.loads(db.execute("SELECT payload FROM meta WHERE id=1").fetchone()[0]) != binding:
                raise ContractError("budget plan/source immutable; preserve old ledger")

    def _db(self):
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True)
        if db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID or db.execute("PRAGMA user_version").fetchone()[0] != 1:
            db.close()
            raise ContractError("foreign/incompatible budget database")
        return closing(db)

    def history(self):
        with self._db() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload FROM events ORDER BY seq")]

    def status(self):
        with self._db() as db, db:
            db.execute("BEGIN")
            revision = db.execute("SELECT revision FROM meta WHERE id=1").fetchone()[0]
            events = [json.loads(r[0]) for r in db.execute("SELECT payload FROM events ORDER BY seq")]
        by_stage = {s: Decimal(0) for s in STAGES}
        totals, unknown, cpu_seconds = {}, 0, Decimal(0)
        for event in events:
            by_stage[event["stage_id"]] += Decimal(str(event["wall_seconds"])) * event["gpu_count"] / 3600
            if not event["gpu_count"]:
                cpu_seconds += Decimal(str(event["wall_seconds"]))
            if event["amount"] is None:
                unknown += 1
            else:
                currency = event["currency"]
                totals[currency] = totals.get(currency, Decimal(0)) + Decimal(event["amount"])
        used = sum(by_stage.values())
        limits = {s["stage_id"]: Decimal(str(s["gpu_hours"])) for s in self.plan["stages"]}
        return {"plan_id": self.plan["plan_id"], "plan_sha256": digest(self.plan), "revision": revision, "source": self.source,
                "events": len(events), "gpu_instance_hours_used": float(used),
                "gpu_instance_hours_remaining": float(Decimal(str(self.plan["gpu_hours_limit"])) - used),
                "by_stage_gpu_hours": {s: float(v) for s, v in by_stage.items()},
                "over_budget": used > Decimal(str(self.plan["gpu_hours_limit"])) or any(by_stage[s] > limits[s] for s in STAGES),
                "cpu_wall_seconds_reported_separately": float(cpu_seconds),
                "reported_amounts_by_currency": {c: str(v) for c, v in totals.items()},
                "unknown_amount_events": unknown, "billing_verified": False, "paid_launch_enabled": False,
                "cloud_stop_confirmed": False}

    def check(self, params):
        fields(params, {"stage_id", "gpu_count", "max_wall_seconds", "expected_revision"})
        if params["stage_id"] not in STAGES:
            raise ContractError("unknown budget stage")
        integer(params["gpu_count"], "admission GPU count", 1, 8)
        number(params["max_wall_seconds"], "bounded wall seconds", minimum=.001, maximum=604800)
        integer(params["expected_revision"], "budget revision", 0)
        status = self.status()
        if status["revision"] != params["expected_revision"]:
            raise ContractError("budget revision changed; reread before admission")
        requested = Decimal(str(params["max_wall_seconds"])) * params["gpu_count"] / 3600
        stage = next(r for r in self.plan["stages"] if r["stage_id"] == params["stage_id"])
        stage_remaining = Decimal(str(stage["gpu_hours"])) - Decimal(str(status["by_stage_gpu_hours"][params["stage_id"]]))
        within = not status["over_budget"] and requested <= stage_remaining and requested <= Decimal(str(status["gpu_instance_hours_remaining"]))
        return {"within_recorded_budget": within, "requested_gpu_instance_hours": float(requested),
                "expected_revision": status["revision"], "execution_authorized": False,
                "reservation_created": False, "reason": "planning_only_no_resource_launch_or_reservation"}

    def record(self, params):
        if self.role != "trainer":
            raise ContractError("budget monitor cannot record usage")
        fields(params, {"event_id", "stage_id", "gpu_count", "wall_seconds", "activity", "outcome", "amount", "currency", "expected_revision"})
        identifier(params["event_id"])
        if params["stage_id"] not in STAGES or params["activity"] not in ACTIVITIES or params["outcome"] not in ("completed", "failed", "timeout", "interrupted", "uncertain"):
            raise ContractError("explicit stage/activity/outcome required")
        integer(params["gpu_count"], "reported GPU count", 0, 8)
        number(params["wall_seconds"], "reported wall seconds", minimum=.001, maximum=604800)
        integer(params["expected_revision"], "budget revision", 0)
        cost = amount(params["amount"])
        if (cost is None) != (params["currency"] is None) or (cost is not None and (not isinstance(params["currency"], str) or not re.fullmatch(r"[A-Z]{3}", params["currency"]))):
            raise ContractError("reported amount requires matching explicit currency")
        event = dict(params, source=self.source, billing_verified=False)
        encoded = canonical_json(event)
        with self._db() as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT payload FROM events WHERE id=?", (params["event_id"],)).fetchone()
            if old:
                if old[0] != encoded:
                    raise ContractError("budget event identity conflict")
            else:
                revision = db.execute("SELECT revision FROM meta WHERE id=1").fetchone()[0]
                if revision != params["expected_revision"]:
                    raise ContractError("budget revision changed; inspect before retry")
                # Retain actual reported overruns; do not discard failed or
                # over-cap usage to make the budget appear healthier.
                db.execute("INSERT INTO events VALUES(?,?,?)", (params["event_id"], revision + 1, encoded))
                db.execute("UPDATE meta SET revision=? WHERE id=1", (revision + 1,))
        return self.status()

    def dispatch(self, request):
        ident = None
        try:
            fields(request, {"schema_version", "id", "method", "params"})
            integer(request["schema_version"], "budget API schema", 1, 1)
            ident = identifier(request["id"])
            method = request["method"]
            if method not in ("status", "history", "budget.check", "usage.record") or (method == "usage.record" and self.role != "trainer"):
                return {"schema_version": 1, "id": ident, "ok": False, "error": {"code": "PERMISSION_DENIED", "message": "method unavailable to budget host role"}}
            if method in ("status", "history"):
                fields(request["params"], set())
                result = self.status() if method == "status" else self.history()
            else:
                result = self.check(request["params"]) if method == "budget.check" else self.record(request["params"])
            return {"schema_version": 1, "id": ident, "ok": True, "result": result}
        except ContractError as error:
            return {"schema_version": 1, "id": ident, "ok": False, "error": {"code": "INVALID_INPUT", "message": str(error)}}
        except (OSError, sqlite3.Error):
            return {"schema_version": 1, "id": ident, "ok": False, "error": {"code": "STORAGE_ERROR", "message": "budget ledger unavailable"}}
