"""Local versioned JSON service for external tools. Not an MCP server or provider client.

Roles are host configuration, never request parameters. Opponent tools expose one
seat only; training requires an explicitly attached future backend, absent by default.
"""

import json
import math
from pathlib import Path
import queue
import sqlite3
import threading
import time
from typing import Protocol
from uuid import uuid4

from .agent_monitor import RunMonitor
from .agent_registry import OpponentRegistry, identifier
from .coding_agent import CodeBuddyCLIAdapter
from .contracts import ActionSelection, Versions
from .effect_duel import DEFAULT_PROFILE, choose_effect_duel_action, public_card_facts
from .engine import EngineUnavailable
from .native import NativeError, NativeNormalEngine
from .validation import ContractError, array, canonical_json, fields, integer, member, parse_json, read_json, text

READ = {"capabilities", "runs.list", "runs.read", "runs.metrics", "checkpoints.read", "opponents.summary"}
DUEL = {"duel.open", "duel.next", "duel.status", "duel.submit_action", "duel.close", "cards.lookup"}
ROLES = {"monitor": READ, "trainer": READ | {"training.prepare", "training.recover", "training.control"},
         "manager": READ | {"environment.runtime", "environment.register", "deck.import", "deck.read", "opponent.register", "coding.prepare_handoff", "construction.plan", "construction.run"},
         "opponent": {"capabilities"} | DUEL}


class TrainingBackend(Protocol):
    """Must atomically enforce expected_revision; no arbitrary command execution API."""
    def control(self, *, run_id: str, operation: str, expected_revision: int, request_id: str) -> dict: ...


class ApiError(ContractError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class AgentBridge:
    def __init__(self, workspace, state_root, native_root, *, role="monitor", seat=1, profile=None, seed=7,
                 training_backend=None, decision_timeout=30, max_decisions=3000, clock=time.monotonic,
                 controller_source="unverified_external", provider="unverified", model="unverified",
                 opponent_id=None, own_deck_id=None, construction_backend=None):
        member(role, "agent role", tuple(ROLES))
        integer(seat, "opponent seat", 0, 1)
        integer(max_decisions, "decision limit", 1, 10000)
        if type(decision_timeout) not in (int, float) or not 0 < decision_timeout <= 300:
            raise ContractError("decision timeout must be within 300 seconds")
        member(controller_source, "controller source", ("unverified_external", "local_contract_fixture"))
        self.workspace, self.native_root = Path(workspace).resolve(), Path(native_root).resolve()
        self.registry = OpponentRegistry(state_root, self.native_root)
        self.monitor = RunMonitor(state_root)
        self.coding = CodeBuddyCLIAdapter(self.workspace)
        self.role, self.seat, self.profile, self.seed = role, seat, profile, seed
        self.backend, self.clock, self.timeout, self.max_decisions = training_backend, clock, decision_timeout, max_decisions
        if construction_backend is not None:
            from .construction_service import HostConstructionBackend
            if not isinstance(construction_backend, HostConstructionBackend):
                raise ContractError("typed host construction backend required")
        self.construction_backend = construction_backend
        self.provenance = {"controller_source": controller_source, "provider": text(provider, "provider"),
                           "model": text(model, "model"), "provider_verified": False}
        self.bound_versions = None
        if (opponent_id is None) != (own_deck_id is None):
            raise ContractError("registered opponent requires both opponent and own deck IDs")
        if opponent_id is not None:
            match = self.registry.match_configuration(opponent_id, own_deck_id, seat)
            self.profile = match["profile"]
            self.bound_versions = Versions.from_dict(match["versions"])
            self.provenance.update(provider=match["opponent"]["provider"], model=match["opponent"]["model"],
                                   opponent_id=opponent_id, environment_id=match["opponent"]["environment_id"])
        self.engine, self.pending, self.facts = None, None, None
        self.version, self.version_key, self.deadline = None, None, None
        self.total, self.actor_decisions, self.terminal = 0, 0, None

    def dispatch(self, value):
        request_id = None
        try:
            d = fields(value, {"schema_version", "id", "method", "params"})
            integer(d["schema_version"], "agent API schema", 1, 1)
            request_id = identifier(d["id"])
            text(d["method"], "method")
            if d["method"] not in ROLES[self.role]:
                raise ApiError("PERMISSION_DENIED", "method unavailable to this fixed role")
            result = self._call(d["method"], d["params"], request_id)
            result = json.loads(canonical_json(result))  # Python callers see exactly the JSON wire types.
            return {"schema_version": 1, "id": request_id, "ok": True, "result": result}
        except ApiError as error:
            code, message = error.code, str(error)
        except ContractError as error:
            code, message = "INVALID_REQUEST", str(error)
        except NativeError:
            self.close()
            code, message = "NATIVE_ERROR", "real engine failed closed; no game result invented"
        except EngineUnavailable:
            code, message = "NATIVE_RESOURCES_UNAVAILABLE", "explicit native resources are not ready"
        except (OSError, sqlite3.Error, json.JSONDecodeError):
            code, message = "STATE_UNAVAILABLE", "registered state unavailable or malformed"
        return {"schema_version": 1, "id": request_id, "ok": False, "error": {"code": code, "message": message}}

    def _call(self, method, params, request_id):
        if method == "capabilities":
            fields(params, set())
            return {"api": "ygo-kito-local-json-v1", "transport": "json-lines-not-mcp", "role": self.role,
                    "methods": sorted(ROLES[self.role]), "training_backend_configured": self.backend is not None,
                    "construction_backend_configured": self.construction_backend is not None,
                    "provider_connected": False, "model_verified": False, "provider_invocation_implemented": False,
                    "cloud_resource_control_implemented": False}
        if method in ("construction.plan", "construction.run"):
            if self.construction_backend is None:
                raise ApiError("CONSTRUCTION_BACKEND_NOT_CONFIGURED", "explicit host construction backend required; no operation executed")
            from .construction_service import ConstructionUnavailable
            try:
                return (self.construction_backend.plan(params) if method == "construction.plan"
                        else self.construction_backend.run(params))
            except ConstructionUnavailable as error:
                raise ApiError("CONSTRUCTION_RESOURCES_UNAVAILABLE", str(error)) from error
        if method == "runs.list":
            fields(params, set())
            return self.monitor.runs()
        if method in ("runs.read", "runs.metrics"):
            d = fields(params, {"run_id"})
            row = self.monitor.snapshot(d["run_id"])
            return row if method == "runs.read" else {"run_id": row["run_id"], "revision": row["revision"], "metrics": row["metrics"], "source": row["source"]}
        if method == "checkpoints.read":
            d = fields(params, {"run_id", "checkpoint_id"})
            return self.monitor.checkpoint(d["run_id"], d["checkpoint_id"])
        if method == "opponents.summary":
            fields(params, set())
            rows = self.registry.records("opponent")
            return {"registered": len(rows), "training_ready": sum(bool(r["training_ready"]) for r in rows),
                    "external_end_to_end_verified": False}
        if method == "environment.runtime":
            fields(params, set())
            return self.registry.runtime_environment()
        if method == "environment.register":
            return self.registry.environment(params)
        if method == "deck.import":
            return self.registry.import_deck(params)
        if method == "deck.read":
            d = fields(params, {"deck_id"})
            return self.registry.get("deck", d["deck_id"])
        if method == "opponent.register":
            return self.registry.register_opponent(params)
        if method == "coding.prepare_handoff":
            return self.coding.prepare(params)
        if method == "training.control":
            return self._control(params, request_id)
        if method == "training.prepare":
            d = fields(params, {"run_id"})
            if self.backend is None or not hasattr(self.backend, "prepare"):
                raise ApiError("TRAINING_BACKEND_NOT_CONFIGURED", "explicit local CPU host backend required; no operation executed")
            return self.backend.prepare(identifier(d["run_id"]))
        if method == "training.recover":
            d = fields(params, {"run_id", "expected_revision"})
            identifier(d["run_id"])
            integer(d["expected_revision"], "recovery expected revision")
            if self.backend is None or not hasattr(self.backend, "recover"):
                raise ApiError("TRAINING_BACKEND_NOT_CONFIGURED", "explicit local CPU recovery backend required")
            return self.registry.control_once(request_id, dict(d, operation="recover"),
                lambda: {"execution": "applied", "scope": "managed-local-cpu", "snapshot": self.backend.recover(**d),
                         "cloud_billing_stopped": False})
        if method == "cards.lookup":
            d = fields(params, {"card_ids"})
            codes = array(d["card_ids"], "card IDs")
            if not 1 <= len(codes) <= 16:
                raise ContractError("catalogue lookup requires 1 to 16 IDs")
            self.registry._assets()
            result = []
            path = self.native_root / "engine-src/database/locales/zh-CN/cards.cdb"
            with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
                for code in codes:
                    integer(code, "card ID", 1, 2**32 - 1)
                    row = db.execute('SELECT name,desc FROM texts WHERE id=?', (code,)).fetchone()
                    if row is None:
                        raise ContractError("public catalogue card not found")
                    result.append({"card_id": code, "name": row[0], "text": row[1], "source": "pinned-public-catalogue"})
            return result
        if method == "duel.open":
            fields(params, set())
            if self.engine is not None:
                raise ContractError("duel already open")
            profile = self.profile if self.profile is not None else read_json(DEFAULT_PROFILE)
            self.engine = NativeNormalEngine(self.native_root, scenario="effect-duel", deck_profile=profile, seed=self.seed)
            if self.bound_versions is not None and self.engine.context.versions != self.bound_versions:
                self.close()
                raise ContractError("native resources changed after deck environment binding")
            self.facts = public_card_facts(self.native_root)
            self.pending, self.version_key, self.version, self.terminal = None, None, None, None
            self.total = self.actor_decisions = 0
            self._advance()
            self._refresh_version()
            return self._status()
        if method == "duel.status":
            fields(params, set())
            return self._status()
        if method == "duel.close":
            fields(params, set())
            self.close()
            return self._status()
        if method == "duel.next":
            fields(params, set())
            self._require_engine()
            self._advance()
            self._refresh_version()
            if self.pending is not None and self.clock() >= self.deadline:
                self._apply(choose_effect_duel_action(self.pending, self.facts), "timeout", {})
                self._refresh_version()
            if self.pending is None:
                return {"terminal": True, "public_state": self._status()}
            return {"terminal": False, "state_version": self.version, "timeout_seconds": max(0, self.deadline - self.clock()),
                    "request": self.pending.to_dict(), "provenance": self.provenance}
        if method == "duel.submit_action":
            d = fields(params, {"state_version", "action_id"}, {"usage"})
            text(d["state_version"], "state version")
            text(d["action_id"], "action ID")
            self._require_engine()
            if self.pending is None or d["state_version"] != self.version:
                raise ApiError("STALE_STATE", "stale or mismatched actor window; no action applied")
            usage = self._usage(d.get("usage", {}))
            action = next((a for a in self.pending.actions if a.action_id == d["action_id"]), None)
            reason = "timeout" if self.clock() >= self.deadline else "illegal_action" if action is None else "external_selection"
            if reason != "external_selection":
                action = choose_effect_duel_action(self.pending, self.facts)
            self._apply(action, reason, usage)
            return {"accepted": reason == "external_selection", "fallback_applied": reason != "external_selection",
                    "reason": reason, "public_state": self._status()}
        raise ContractError("unknown method")

    def _control(self, params, request_id):
        d = fields(params, {"run_id", "operation", "expected_revision"})
        identifier(d["run_id"])
        integer(d["expected_revision"], "expected revision")
        member(d["operation"], "training operation", ("start", "pause", "resume", "stop", "save_checkpoint"))
        if self.backend is None:
            raise ApiError("TRAINING_BACKEND_NOT_CONFIGURED", "no training backend; no operation executed")
        cached = self.registry.cached_control(request_id, d)
        if cached is not None:
            return cached
        run = self.monitor.snapshot(d["run_id"])
        if run["revision"] != d["expected_revision"]:
            raise ApiError("STALE_STATE", "training revision differs; no operation executed")
        valid = {"start": {"created"}, "pause": {"running"}, "resume": {"paused"},
                 "stop": {"created", "running", "paused"}, "save_checkpoint": {"running", "paused"}}
        if run["state"] not in valid[d["operation"]]:
            raise ContractError("training operation invalid for current state")
        if hasattr(self.backend, "validate_control"):
            self.backend.validate_control(**d)
        def execute():
            result = fields(self.backend.control(**d, request_id=request_id), {"applied", "revision"},
                            {"checkpoint_id", "state", "scope", "local_process_exited", "cloud_billing_stopped"})
            if type(result["applied"]) is not bool:
                raise ContractError("backend acknowledgement must be bool")
            integer(result["revision"], "backend revision")
            if result["applied"] and result["revision"] <= d["expected_revision"]:
                raise ContractError("applied backend operation must advance revision")
            if result.get("checkpoint_id") is not None:
                identifier(result["checkpoint_id"])
            return {"execution": "applied" if result["applied"] else "rejected", "backend_result": result,
                    "source": run["source"]}
        return self.registry.control_once(request_id, d, execute)

    def _require_engine(self):
        if self.engine is None:
            raise ApiError("DUEL_NOT_OPEN", "no active duel")

    def _advance(self):
        self._require_engine()
        if self.pending is None:
            self.pending = self.engine.next_decision()
        while self.pending is not None and self.pending.observation.observer != self.seat:
            self._limit()
            request = self.pending
            action = choose_effect_duel_action(request, self.facts)
            self.engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id))
            self.total += 1
            self.pending = self.engine.next_decision()
        if self.pending is None:
            self.terminal = self.engine.outcome

    def _refresh_version(self):
        if self.pending is None:
            self.version, self.version_key = None, None
        else:
            key = self.pending.context.run_id, self.pending.decision_id
            if key != self.version_key:
                self.version_key, self.version, self.deadline = key, uuid4().hex, self.clock() + self.timeout

    def _limit(self):
        if self.total >= self.max_decisions:
            self.close()
            raise ApiError("DECISION_BUDGET_EXHAUSTED", "duel closed without an invented result")

    def _apply(self, action, reason, usage):
        self._limit()
        request = self.pending
        event = dict(self.provenance, seat=self.seat, decision_id=request.decision_id,
                     action_id=action.action_id, reason=reason, usage=usage, billing_verified=False)
        self.registry.audit("opponent-action-submitted", event)
        self.engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id))
        self.total += 1
        self.actor_decisions += 1
        self.version, self.version_key = None, None
        self.pending = None
        self._advance()
        self._refresh_version()

    def poll_deadline(self):
        """Transport calls this without an LLM request while waiting for external input."""
        if self.engine is not None and self.pending is not None and self.version is not None and self.clock() >= self.deadline:
            self._apply(choose_effect_duel_action(self.pending, self.facts), "timeout", {})

    def _status(self):
        result = {"open": self.engine is not None, "terminal": self.terminal is not None, "outcome": self.terminal,
                  "actor_seat": self.seat, "actor_decisions": self.actor_decisions, "provider_verified": False}
        if self.engine is not None:
            result.update(turn=self.engine.turn, turn_player=self.engine.turn_player, phase=self.engine.phase,
                          life_points=list(self.engine.life_points))
        return result

    def _usage(self, value):
        d = fields(value, set(), {"input_tokens", "output_tokens", "amount", "currency", "provider_request_id"})
        for key in ("input_tokens", "output_tokens"):
            if key in d:
                integer(d[key], key)
        if d.get("amount") is not None:
            if type(d["amount"]) not in (int, float) or not math.isfinite(d["amount"]) or d["amount"] < 0:
                raise ContractError("reported cost must be finite and nonnegative")
        if "currency" in d:
            member(d["currency"], "cost currency", ("USD", "CNY", "credits", "unknown"))
        if "provider_request_id" in d:
            text(d["provider_request_id"], "provider request ID")
        return dict(d, amount=d.get("amount"), source="client-reported-unverified")

    def close(self):
        if self.engine is not None:
            self.terminal = self.engine.outcome
            self.engine.close()
            self.engine = None
        self.pending, self.version, self.version_key = None, None, None


def serve_bridge(bridge, source, destination):
    """One host-scoped role per process; EOF always releases the native lease."""
    inbox = queue.Queue(maxsize=16)
    def read_lines():
        try:
            while True:
                line = source.readline(1024 * 1024 + 1)
                if not line:
                    break
                inbox.put(line)
                if len(line) > 1024 * 1024:
                    break
        finally:
            inbox.put(None)
    threading.Thread(target=read_lines, daemon=True).start()
    def poll():
        try:
            bridge.poll_deadline()
        except (NativeError, ApiError, OSError, sqlite3.Error):
            bridge.close()
    try:
        while True:
            try:
                line = inbox.get(timeout=.25)
            except queue.Empty:
                poll()
                continue
            if line is None:
                break
            poll()
            try:
                if len(line) > 1024 * 1024:
                    raise ContractError("request exceeds line budget")
                response = bridge.dispatch(parse_json(line))
            except (ContractError, json.JSONDecodeError, RecursionError):
                response = {"schema_version": 1, "id": None, "ok": False,
                            "error": {"code": "INVALID_REQUEST", "message": "invalid JSON request"}}
            destination.write(canonical_json(response) + "\n")
            destination.flush()
            if len(line) > 1024 * 1024:
                break
    finally:
        bridge.close()
    return 0
