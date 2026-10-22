"""Real Sangan search/trigger cases; all conditions and count limits are native."""

import hashlib
from pathlib import Path
import platform
import time

from .contracts import ActionSelection
from .native import NativeError, NativeNormalEngine
from .normal_duel import request_digest
from .validation import ContractError, array, canonical_json, fields

SANGAN, HOLE, REBORN, FOOLISH = 26202165, 53129443, 83764718, 81439173


def choose_search_action(request, route):
    cards = {c.ref: c for c in request.observation.cards}
    if request.search_choices:
        wanted = SANGAN if route == "deck-grave" else None
        chosen = next((c for c in request.search_choices if c.card_id == wanted), request.search_choices[0])
        return next(a for a in request.actions if chosen.ref in a.card_refs)
    for action in request.actions:
        ids = [cards[r].card_id for r in action.card_refs]
        if route == "field-twice" and action.kind == "summon" and SANGAN in ids:
            return action
        if action.kind == "activate" and any(code in ids for code in (SANGAN, HOLE, REBORN, FOOLISH)):
            return action
    selected = [a for a in request.actions if a.kind == "select"]
    if selected:
        return next((a for a in selected if any(cards[r].card_id == SANGAN for r in a.card_refs)), selected[0])
    for value in (7, None):
        for action in request.actions:
            if action.kind == "pass" and action.value == value:
                return action
    return request.actions[0]


def run_search_case(root: Path, *, route="field-twice", seed=None, replay=None):
    if replay is not None:
        fields(replay, {"schema_version", "kind", "route", "seed", "versions", "decks", "responses", "events", "result"})
        if replay["kind"] != "search-trigger-replay-not-policy-input" or type(replay["schema_version"]) is not int or replay["schema_version"] != 1:
            raise ContractError("unsupported search replay")
        for row in array(replay["responses"], "responses"):
            fields(row, {"player", "decision_id", "prompt", "action_id", "request_sha256", "response"})
        route, seed = replay["route"], replay["seed"]
    if route not in ("field-twice", "deck-grave"):
        raise ContractError("unknown search route")
    if seed is None:
        seed = 9154 if route == "field-twice" else 24
    scenario = "search-trigger" if route == "field-twice" else "search-condition"
    started = time.monotonic()
    with NativeNormalEngine(root, scenario=scenario, seed=seed) as engine:
        versions = {"resources": engine.receipt["resources"], "source_commits": engine.receipt["source_commits"],
                    "python": platform.python_version(), "adapter_schema": "native-search-v1"}
        if replay is not None and replay["versions"] != versions:
            raise ContractError("search replay versions differ")
        rows, search_windows, confirmation_checks = [], [], []
        request = engine.next_decision()
        initial_hand = [c.card_id for c in request.observation.cards if c.zone == "hand"]
        if route == "field-twice":
            if initial_hand.count(HOLE) != 2 or not {SANGAN, REBORN}.issubset(initial_hand):
                raise NativeError("seed lacks declared double-send starting hand")
        elif FOOLISH not in initial_hand or SANGAN in initial_hand:
            raise NativeError("seed lacks declared deck-to-grave starting conditions")
        seen_confirmations = 0
        for step in range(150):
            if request is None or time.monotonic() - started > 20:
                raise NativeError("search scenario stopped before checkpoint")
            if request.search_choices:
                if request.observation.observer != 0 or any(c.zone == "deck" for c in request.observation.cards):
                    raise NativeError("search visibility contract violated")
                other = engine._observation(1)
                if any(c.zone == "deck" for c in other.cards):
                    raise NativeError("deck order leaked into opponent projection")
                search_windows.append({"player": 0, "candidate_count": len(request.search_choices),
                                       "candidate_ids": [c.card_id for c in request.search_choices],
                                       "opponent_public_history_ids": [code for e in other.public_history for code in e.card_ids]})
            action = choose_search_action(request, route)
            if replay is not None:
                if step >= len(replay["responses"]):
                    raise NativeError("search replay truncated")
                action = next((a for a in request.actions if a.action_id == replay["responses"][step]["action_id"]), None)
                if action is None:
                    raise NativeError("search replay action unavailable")
            raw = engine._responses[action.action_id]
            row = {"player": request.observation.observer, "decision_id": request.decision_id,
                   "prompt": engine.pending_kind, "action_id": action.action_id, "request_sha256": request_digest(request),
                   "response": {"bytes_hex": raw.hex()} if isinstance(raw, bytes) else {"integer": raw}}
            if replay is not None and row != replay["responses"][step]:
                raise NativeError("search replay decision divergence")
            rows.append(row)
            engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id))
            request = engine.next_decision()
            confirmations = [e for e in engine.events if e["kind"] == 31]
            if len(confirmations) > seen_confirmations:
                revealed = confirmations[-1]["public_cards"]
                views = [engine._observation(p) for p in (0, 1)]
                if any(not set(revealed).issubset({code for e in view.public_history for code in e.card_ids}) for view in views):
                    raise NativeError("confirmed search card missing from public history")
                confirmation_checks.append({"revealed_ids": revealed, "both_public_histories_agree": views[0].public_history == views[1].public_history,
                                            "opponent_public_hand_ids": [c.card_id for c in views[1].cards if c.owner == 0 and c.zone == "hand"]})
                seen_confirmations = len(confirmations)
            field_sends = [e for e in engine.events if e["kind"] == 50 and e.get("public_card") == SANGAN and e["from_zone"] == 4 and e["to_zone"] == 16]
            chains_done = sum(e["kind"] == 74 for e in engine.events)
            done = (len(field_sends) == 2 and chains_done >= 4) if route == "field-twice" else (chains_done >= 1 and any(e["kind"] == 50 and e.get("public_card") == SANGAN and e["from_zone"] == 1 and e["to_zone"] == 16 for e in engine.events))
            if done:
                activations = [e["public_card"] for e in engine.events if e["kind"] == 70]
                expected = 1 if route == "field-twice" else 0
                if engine.turn != 1 or activations.count(SANGAN) != expected or len(confirmation_checks) != expected or engine.callback_errors:
                    raise NativeError("real trigger condition/count-limit result mismatch")
                result = {"route": route, "turns": engine.turn, "activations": activations, "sangan_field_to_grave": len(field_sends),
                          "sangan_activations": expected, "search_windows": search_windows, "confirmations": confirmation_checks,
                          "hand_counts": list(engine._observation(0).hand_counts), "loaded_scripts": sorted(engine.loaded_scripts)}
                trace = {"schema_version": 1, "kind": "search-trigger-replay-not-policy-input", "route": route, "seed": seed,
                         "versions": versions, "decks": [list(d) for d in engine.player_decks], "responses": rows,
                         "events": engine.events, "result": result}
                if replay is not None and trace != replay:
                    raise NativeError("search replay event/result divergence")
                return {"ok": True, "engine": "real-ygopro-core-and-upstream-lua", "route": route, "seed": seed,
                        "responses": len(rows), "elapsed_seconds": time.monotonic() - started, "replay_verified": replay is not None,
                        "trace_sha256": hashlib.sha256(canonical_json(trace).encode()).hexdigest(), "result": result}, trace
        raise NativeError("search scenario response budget exhausted")
