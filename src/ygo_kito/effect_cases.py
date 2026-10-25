"""Two fixed real-script cases; the policy plans choices, never implements effects."""

import hashlib
from pathlib import Path
import platform
import time

from .contracts import ActionSelection
from .native import NativeError, NativeNormalEngine, public_event_projection
from .normal_duel import request_digest
from .validation import ContractError, array, canonical_json, fields

TWISTERS, JAMMER, CYCLONE = 43898403, 77414722, 5318639


def choose_effect_action(request, route):
    cards = {c.ref: c for c in request.observation.cards}
    player = request.observation.observer
    for action in request.actions:
        if not action.card_refs:
            continue
        identities = [cards[ref].card_id for ref in action.card_refs]
        if player == 0 and request.observation.turn == 1 and action.kind == "set" and identities[0] in (JAMMER, CYCLONE):
            return action
        if action.kind == "activate":
            if player == 1 and request.observation.phase == "main1" and identities[0] == TWISTERS:
                return action
            if player == 0 and route == "negate" and identities[0] == JAMMER:
                return action
    selections = [a for a in request.actions if a.kind == "select" and a.card_refs]
    if selections:
        # Choose targets by publicly visible zone/slot, not the identities of set cards.
        return max(selections, key=lambda a: len(a.card_refs))
    if all(a.kind in ("select", "pass") for a in request.actions):
        place = next((a for a in request.actions if a.kind == "select"), None)
        if place is not None:
            return place
    for value in (7, None):
        for action in request.actions:
            if action.kind == "pass" and action.value == value:
                return action
    return request.actions[0]


def effect_result(engine, route):
    if not any(e["kind"] == 74 for e in engine.events):
        raise NativeError("real chain did not finish")
    views = [engine._observation(p) for p in (0, 1)]
    graves = [{c.card_id for c in v.cards if c.zone == "graveyard" and c.owner == p} for p, v in enumerate(views)]
    costs = [e for e in engine.events if e["kind"] == 50 and e.get("reason", 0) & 0x80]
    activations = [e["public_card"] for e in engine.events if e["kind"] == 70]
    negated = [e["link"] for e in engine.events if e["kind"] == 75]
    first_solving = next((i for i, e in enumerate(engine.events) if e["kind"] == 72), -1)
    if first_solving < 0 or any(i >= first_solving for i, e in enumerate(engine.events) if e in costs):
        raise NativeError("discard cost was not paid before chain resolution")
    effect_destructions = [e for e in engine.events if e["kind"] == 50 and e.get("reason", 0) & 0x41 == 0x41]
    if TWISTERS not in graves[1] or TWISTERS not in activations:
        raise NativeError("Twisters activation/cleanup absent")
    if route == "negate":
        if JAMMER not in activations or 1 not in negated or len(costs) != 2 or CYCLONE in graves[0]:
            raise NativeError("negated spell/cost/remaining target mismatch")
        hidden = [c for c in views[1].cards if c.zone == "spell_trap" and c.owner == 0]
        if len(hidden) != 1 or hidden[0].visibility != "hidden" or hidden[0].card_id is not None:
            raise NativeError("unrevealed target identity leaked")
    elif negated or len(costs) != 1 or not {JAMMER, CYCLONE}.issubset(graves[0]) or not {JAMMER, CYCLONE}.issubset({e.get("public_card") for e in effect_destructions}):
        raise NativeError("resolved destruction/cost mismatch")
    return {"route": route, "activations": activations, "negated_links": negated,
            "cost_moves": costs, "costs_before_resolution": True, "effect_destructions": effect_destructions,
            "hand_counts": list(views[0].hand_counts),
            "graveyard_ids": [sorted(ids) for ids in graves], "public_history_equal": views[0].public_history == views[1].public_history,
            "public_events": public_event_projection(engine.events), "loaded_scripts": sorted(engine.loaded_scripts)}


def run_effect_case(root: Path, *, route="negate", seed=1724, replay=None):
    if route not in ("negate", "resolve"):
        raise ContractError("effect route must be negate or resolve")
    if replay is not None:
        fields(replay, {"schema_version", "kind", "route", "seed", "versions", "decks", "responses", "events", "result", "eligibility"})
        if replay["kind"] != "selected-effects-replay-not-policy-input" or type(replay["schema_version"]) is not int or replay["schema_version"] != 1:
            raise ContractError("unsupported effect replay")
        for row in array(replay["responses"], "responses"):
            fields(row, {"decision_id", "player", "prompt", "action_id", "request_sha256", "response"})
        route, seed = replay["route"], replay["seed"]
        if route not in ("negate", "resolve"):
            raise ContractError("unsupported effect route")
    started = time.monotonic()
    with NativeNormalEngine(root, seed=seed, scenario="effects-counter") as engine:
        versions = {"resources": engine.receipt["resources"], "source_commits": engine.receipt["source_commits"],
                    "python": platform.python_version(), "adapter_schema": "selected-effects-v1-observer-windows"}
        if replay is not None and replay["versions"] != versions:
            raise ContractError("effect replay versions differ")
        rows, eligibility = [], {"initial_no_target_spell_unavailable": False, "same_turn_jammer_unavailable": True}
        request = engine.next_decision()
        own = {c.card_id for c in request.observation.cards if c.zone == "hand"}
        if not {JAMMER, CYCLONE}.issubset(own):
            raise NativeError("seed does not supply the declared starting hand")
        eligibility["initial_no_target_spell_unavailable"] = not any(a.kind == "activate" for a in request.actions)
        for step in range(100):
            if time.monotonic() - started > 20 or request is None:
                raise NativeError("effect scenario stopped before completion")
            ids = {c.ref: c.card_id for c in request.observation.cards}
            if request.observation.turn == 1 and request.observation.observer == 0:
                if any(a.kind == "activate" and any(ids[r] == JAMMER for r in a.card_refs) for a in request.actions):
                    eligibility["same_turn_jammer_unavailable"] = False
            action = choose_effect_action(request, route)
            if replay is not None:
                if step >= len(replay["responses"]):
                    raise NativeError("effect replay ended before real chain")
                action = next((a for a in request.actions if a.action_id == replay["responses"][step]["action_id"]), None)
                if action is None:
                    raise NativeError("effect replay action absent from native candidates")
            raw = engine._responses[action.action_id]
            row = {"decision_id": request.decision_id, "player": request.observation.observer,
                   "prompt": engine.pending_kind, "action_id": action.action_id, "request_sha256": request_digest(request),
                   "response": {"bytes_hex": raw.hex()} if isinstance(raw, bytes) else {"integer": raw}}
            if replay is not None and (step >= len(replay["responses"]) or row != replay["responses"][step]):
                raise NativeError("effect replay decision divergence")
            rows.append(row)
            engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id))
            request = engine.next_decision()
            if any(e["kind"] == 74 for e in engine.events):
                result = effect_result(engine, route)
                if not all(eligibility.values()) or engine.callback_errors:
                    raise NativeError("real activation eligibility/script diagnostics failed")
                trace = {"schema_version": 1, "kind": "selected-effects-replay-not-policy-input", "route": route,
                         "seed": seed, "versions": versions, "decks": [list(d) for d in engine.player_decks],
                         "responses": rows, "events": engine.events, "result": result, "eligibility": eligibility}
                if replay is not None and trace != replay:
                    raise NativeError("effect replay event/result divergence")
                return {"ok": True, "route": route, "engine": "real-ygopro-core-and-upstream-lua", "seed": seed,
                        "scope": "three selected effect cards; not full effect support", "responses": len(rows),
                        "elapsed_seconds": time.monotonic() - started, "replay_verified": replay is not None,
                        "trace_sha256": hashlib.sha256(canonical_json(trace).encode()).hexdigest(),
                        "eligibility": eligibility, "result": result}, trace
        raise NativeError("effect response budget exhausted")
