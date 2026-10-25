"""A real SelectSubGroup cancel/add/remove/finish receipt, never card rules.

The pinned c18738846.lua procedure decides eligibility and moves the cards.
This small driver only chooses operations offered in observer-safe core DTOs.
Full replays are private audit artifacts, not training/player observations.
"""
import json
from pathlib import Path
import time

from .build_contracts import digest
from .contracts import ActionSelection
from .extra_routes import completed_special_summon
from .native import NativeError, NativeNormalEngine
from .normal_duel import request_digest
from .validation import ContractError, canonical_json, fields

PHOTON, NORMAL, GOAL = 65367484, 32864, 18738846
OPERATIONS = ("cancel", "add", "remove", "add", "finish")
ROOT = Path(__file__).resolve().parents[2]


def run_unselect_case(root, *, replay=None):
    profile = json.loads((ROOT / "configs/unselect-engineering-v1.json").read_text())
    seed, started = 17, time.monotonic()
    if replay is not None:
        fields(replay, {"schema_version", "kind", "seed_audit_only", "profile", "resources", "responses", "windows", "events", "result"})
        if (replay["schema_version"] != 1 or replay["kind"] != "real-unselect-private-audit-v1"
                or replay["seed_audit_only"] != seed or replay["profile"] != profile):
            raise ContractError("unselect replay scenario differs")
    with NativeNormalEngine(Path(root), scenario="effect-duel", deck_profile=profile, seed=seed) as engine:
        if replay is not None and replay["resources"] != engine.receipt:
            raise ContractError("unselect replay resource versions differ")
        req = engine.next_decision()
        own = engine._observation(0)
        if not {PHOTON, NORMAL, GOAL} <= {c.card_id for c in own.cards if c.zone == "hand"}:
            raise NativeError("actual opening hand does not satisfy the declared engineering case")
        setup = [("special_summon", PHOTON), ("summon", NORMAL)]
        setup_cursor, op_cursor, selected, rows, windows = 0, 0, None, [], []
        cancelled = False
        for step in range(80):
            if req is None or engine.turn != 1 or time.monotonic() - started > 20:
                raise NativeError("unselect case stopped before a completed real summon")
            identities = {c.ref: c.card_id for c in req.observation.cards}
            action = None
            if req.prompt.message == 26:
                if op_cursor >= len(OPERATIONS):
                    raise NativeError("unexpected further unselect window")
                operation = OPERATIONS[op_cursor]
                expected_flags = (False, True) if op_cursor in (0, 1, 3) else (True, False)
                if ((req.prompt.finishable, req.prompt.cancelable) != expected_flags
                        or (req.prompt.minimum, req.prompt.maximum) != (1, 2)):
                    raise NativeError("real SelectSubGroup state differs")
                action = next((a for a in req.actions if a.details and a.details.operation == operation
                               and (operation not in ("add", "remove") or selected is None
                                    or identities[a.card_refs[0]] == selected)), None)
                if action is None:
                    raise NativeError("required subgroup operation not offered by core")
                if operation == "add" and selected is None:
                    selected = identities[action.card_refs[0]]
                # Adding/removing affects only the Lua subgroup, not live cards.
                own = engine._observation(0)
                field = {c.card_id for c in own.cards if c.zone == "monster" and c.controller == 0}
                if field != {PHOTON, NORMAL} or not any(c.card_id == GOAL and c.zone == "hand" for c in own.cards):
                    raise NativeError("subgroup edits moved live cards before completion")
                window = json.loads(canonical_json(req.to_dict()))
                window["context"]["run_id"] = "private-replay-audit"
                windows.append({"operation": operation, "request": window, "selected_card_audit_only": selected})
                op_cursor += 1
            elif req.observation.observer == 0 and req.prompt.message == 11:
                if setup_cursor < len(setup):
                    kind, code = setup[setup_cursor]
                    action = next((a for a in req.actions if a.kind == kind and any(identities[r] == code for r in a.card_refs)), None)
                    if action is not None:
                        setup_cursor += 1
                elif op_cursor in (0, 1):
                    if op_cursor == 1:
                        cancelled = True
                    action = next((a for a in req.actions if a.kind == "special_summon" and any(identities[r] == GOAL for r in a.card_refs)), None)
                    if action is None:
                        raise NativeError("cancel consumed the real procedure or removed its candidates")
            if action is None:
                action = next((a for a in req.actions if a.kind == "pass"), req.actions[0])
            raw = engine._responses[action.action_id]
            row = {"player": req.observation.observer, "request_sha256": request_digest(req), "action_id": action.action_id,
                   "wire_response_audit_only": {"bytes_hex": raw.hex()} if isinstance(raw, bytes) else {"integer": raw}}
            if replay is not None and (step >= len(replay["responses"]) or row != replay["responses"][step]):
                raise NativeError("unselect replay response diverged")
            rows.append(row)
            engine.submit(ActionSelection(req.context.run_id, req.duel_id, req.decision_id, action.action_id))
            req = engine.next_decision()
            own = engine._observation(0)
            if op_cursor == len(OPERATIONS) and completed_special_summon(engine.events, own, 0, GOAL):
                field = {c.card_id for c in own.cards if c.zone == "monster" and c.controller == 0}
                returned = any(c.card_id == selected and c.zone == "hand" for c in own.cards)
                if not cancelled or not returned or field != ({PHOTON, NORMAL} - {selected}) | {GOAL}:
                    raise NativeError("real procedure did not return exactly the selected monster")
                other = engine._observation(1)
                if any(c.card_id is not None or c.owner is not None for c in other.cards if c.controller == 0 and c.zone == "hand"):
                    raise NativeError("opponent observation exposes hidden hand identity")
                result = {"cancel_did_not_consume_procedure": cancelled, "operations": list(OPERATIONS),
                          "returned_card_audit_only": selected, "goal_special_summon_completed": True,
                          "field_public": sorted(field), "hidden_hand_isolated": True,
                          "scripts": sorted(engine.loaded_scripts), "callback_errors": len(engine.callback_errors)}
                trace = {"schema_version": 1, "kind": "real-unselect-private-audit-v1", "seed_audit_only": seed,
                         "profile": profile, "resources": engine.receipt, "responses": rows,
                         "windows": windows, "events": engine.events, "result": result}
                if replay is not None and trace != replay:
                    raise NativeError("unselect replay events/result diverged")
                return {"ok": True, "replay_verified": replay is not None, "trace_sha256": digest(trace),
                        "elapsed_seconds": time.monotonic() - started, "result": result}, trace
        raise NativeError("unselect decision budget exhausted")
