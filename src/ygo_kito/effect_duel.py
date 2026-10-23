"""Complete games for explicit effect-deck profiles, using only visible DTOs and public facts.

The baseline is a protocol driver, not a trained model or a strength benchmark.
Replay artifacts include private audit metadata and must not become policy inputs.
"""

from collections import Counter
import hashlib
import math
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import time

from .contracts import ActionSelection
from .deck_profile import validate_profile
from .native import NativeError, NativeNormalEngine
from .normal_duel import request_digest
from .validation import ContractError, array, canonical_json, fields, integer

DEFAULT_PROFILE = Path(__file__).resolve().parents[2] / "configs/effect-duel-v1.json"


def public_card_facts(root):
    """Static card catalogue; this contains no duel state, decks or RNG values."""
    path = root / "engine-src/database/locales/zh-CN/cards.cdb"
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        return {code: {"type": kind, "level": level & 0xff, "attack": attack, "defense": defense}
                for code, kind, level, attack, defense in db.execute("SELECT id,type,level,atk,def FROM datas")}


def choose_effect_duel_action(request, facts):
    """A deterministic, intentionally simple policy; core alone decides what is legal."""
    cards = {c.ref: c for c in request.observation.cards}
    player = request.observation.observer

    def strength(card):
        if card.card_id is None:
            return 0  # Never substitute the true identity of an opponent's set card.
        return card.attack if card.attack is not None else facts[card.card_id]["attack"]

    if request.search_choices:
        target = max(request.search_choices, key=lambda c: (facts[c.card_id]["attack"], -c.card_id))
        return next(a for a in request.actions if target.ref in a.card_refs)
    if request.prompt.message == 26:
        finished = next((a for a in request.actions if a.details.operation == "finish"), None)
        if finished:
            return finished
        added = [a for a in request.actions if a.details.operation == "add"]
        if added:
            return min(added, key=lambda a: (strength(cards[a.card_refs[0]]), a.action_id))
    selected = [a for a in request.actions if a.kind == "select" and a.card_refs]
    if selected:
        def score(action):
            targets = [cards[r] for r in action.card_refs]
            if request.prompt.message == 20 or all(c.zone == "hand" for c in targets):
                return (-sum(strength(c) for c in targets), -len(targets))
            return (sum(c.controller != player for c in targets), len(targets))
        return max(selected, key=score)
    if request.prompt.message in (12, 13):
        return next(a for a in request.actions if a.kind == "yes")
    if request.prompt.message in (14, 18, 19):
        return request.actions[0]
    # Prefer establishing monsters, then actually use offered effects and set backrow.
    if request.prompt.message == 11:
        specials = [a for a in request.actions if a.kind == "special_summon"]
        summons = [a for a in request.actions if a.kind == "summon" and not facts[cards[a.card_refs[0]].card_id]["type"] & 0x200000]
        if specials or summons:
            return max(specials or summons, key=lambda a: strength(cards[a.card_refs[0]]))
    activations = [a for a in request.actions if a.kind == "activate"]
    if activations:
        return activations[0]
    for kind in ("set", "position", "attack"):
        candidates = [a for a in request.actions if a.kind == kind]
        if kind == "position":
            candidates = [a for a in candidates if cards[a.card_refs[0]].position != 1]
        if candidates:
            return max(candidates, key=lambda a: strength(cards[a.card_refs[0]]))
    for value in (6, 7, 3, 2, None):
        choice = next((a for a in request.actions if a.kind == "pass" and a.value == value), None)
        if choice:
            return choice
    return request.actions[0]


def run_effect_duel(root, profile, *, seed=7, replay=None, max_decisions=3000, budget_seconds=60, option_preference="first", route_task=None):
    integer(max_decisions, "max_decisions", 1, 10000)
    if type(budget_seconds) not in (int, float) or not 0 < budget_seconds <= 300:
        raise ContractError("effect duel budget must be within 300 seconds")
    if replay is not None:
        fields(replay, {"schema_version", "kind", "seed", "versions", "profile", "responses", "events", "outcome", "turns", "life_points"}, {"route_task"})
        integer(replay["schema_version"], "effect duel replay schema", 1, 2)
        if (replay["schema_version"] == 2) != ("route_task" in replay):
            raise ContractError("routed replay schema differs")
        if replay["kind"] != "effect-duel-replay-not-policy-input":
            raise ContractError("unsupported effect duel replay")
        for row in array(replay["responses"], "responses"):
            fields(row, {"player", "decision_id", "prompt", "action_id", "request_sha256", "response"})
        seed, profile = replay["seed"], replay["profile"]
        route_task = replay.get("route_task")
        fields(replay["versions"], {"source_commits", "resources", "adapter_schema", "python", "policy", "option_preference"}, {"route_task_sha256"})
        option_preference = replay["versions"]["option_preference"]
    if option_preference not in ("first", "last"):
        raise ContractError("option preference must be first or last")
    validate_profile(profile)
    route_driver, route_verified = None, False
    if route_task is not None:
        from .build_contracts import BuildTask, DeckParts
        from .build_pipeline import BuildAssets
        from .extra_routes import RouteDriver, completed_special_summon
        route_task = route_task if isinstance(route_task, BuildTask) else BuildTask.from_dict(route_task)
        if profile["schema_version"] != 2 or route_task.goal["kind"] == "normal_summon":
            raise ContractError("routed effect game requires a version-2 extra goal/profile")
        assets = BuildAssets(root)
        assets.validate(route_task, DeckParts(tuple(profile["decks"][0]), tuple(profile["extras"][0]), tuple(profile["sides"][0])))
        route_driver = RouteDriver(route_task.goal["route"], material_preference=option_preference)
    started, cpu_started = time.monotonic(), time.process_time()
    latencies, responses = [], []
    with NativeNormalEngine(root, seed=seed, scenario="effect-duel", deck_profile=profile) as engine:
        facts = public_card_facts(root)
        versions = {"source_commits": engine.receipt["source_commits"], "resources": engine.receipt["resources"],
                    "adapter_schema": "native-extra-material-v2" if engine.extended_actions else "native-effect-duel-v1-general-actions", "python": platform.python_version(),
                    "policy": "declared-route-then-visible-baseline-v2" if route_driver else "visible-dto-effect-protocol-baseline-v1", "option_preference": option_preference}
        if route_driver:
            versions["route_task_sha256"] = route_task.sha256
        if replay is not None and replay["versions"] != versions:
            raise ContractError("effect duel replay resources differ")
        request = engine.next_decision()
        if route_driver:
            opening = Counter(c.card_id for c in request.observation.cards if c.zone == "hand")
            if any(opening[c] < n for c, n in Counter(route_task.goal["starting_conditions"]["requires_opening_hand"]).items()):
                raise ContractError("routed engineering game's actual opening condition was not met")
        while request is not None:
            if len(responses) >= max_decisions or time.monotonic() - started >= budget_seconds:
                raise NativeError("effect duel budget exhausted; no natural result claimed")
            tick = time.perf_counter()
            action = route_driver.choose(request) if route_driver and not route_verified else choose_effect_duel_action(request, facts)
            if request.prompt.message == 14 and option_preference == "last" and not (route_driver and not route_verified):
                action = request.actions[-1]
            if replay is not None:
                if len(responses) >= len(replay["responses"]):
                    raise NativeError("effect duel replay truncated")
                saved = replay["responses"][len(responses)]
                if route_driver and not route_verified and saved["action_id"] != action.action_id:
                    raise NativeError("routed effect replay differs from the declared driver")
                action = next((a for a in request.actions if a.action_id == saved["action_id"]), None)
                if action is None:
                    raise NativeError("effect duel replay action unavailable")
            raw = engine._responses[action.action_id]
            row = {"player": request.observation.observer, "decision_id": request.decision_id,
                   "prompt": engine.pending_kind, "action_id": action.action_id, "request_sha256": request_digest(request),
                   "response": {"bytes_hex": raw.hex()} if isinstance(raw, bytes) else {"integer": raw}}
            if replay is not None and row != saved:
                raise NativeError("effect duel replay decision divergence")
            responses.append(row)
            engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id))
            request = engine.next_decision()
            if route_driver and not route_verified:
                route_verified = completed_special_summon(engine.events, engine._observation(0), 0, route_task.goal["card_id"])
                if engine.turn > 1 and not route_verified:
                    raise NativeError("declared extra goal did not complete in its required turn")
            latencies.append((time.perf_counter() - tick) * 1000)
        if engine.outcome is None or 5 not in engine.messages or engine.callback_errors:
            raise NativeError("effect duel lacks clean core terminal result")
        if route_driver and not route_verified:
            raise NativeError("routed game ended without its verified goal")
        trace = {"schema_version": 2 if route_driver else 1, "kind": "effect-duel-replay-not-policy-input", "seed": seed,
                 "versions": versions, "profile": profile, "responses": responses, "events": engine.events,
                 "outcome": engine.outcome, "turns": engine.turn, "life_points": engine.life_points}
        if route_driver:
            trace["route_task"] = route_task.to_dict()
        if replay is not None and trace != replay:
            raise NativeError("effect duel replay events/result divergence")
        import resource
        ordered = sorted(latencies)
        cpu_info = Path("/proc/cpuinfo")
        processor = next((line.partition(":")[2].strip() for line in cpu_info.read_text().splitlines()
                          if line.startswith("model name")), "unknown") if cpu_info.exists() else platform.processor()
        summary = {"ok": True, "engine": "real-ygopro-core-and-upstream-lua", "scope": "explicit-effect-extra-decks" if engine.extended_actions else "explicit-effect-main-decks",
                   "general_card_pool_supported": False, "trained_model": False, "seed": seed,
                   "turns": engine.turn, "outcome": engine.outcome, "decisions": len(responses),
                   "prompt_counts": dict(sorted(Counter(r["prompt"] for r in responses).items())),
                   "activation_count": sum(e["kind"] == 70 for e in engine.events),
                   "loaded_scripts": sorted(engine.loaded_scripts), "replay_verified": replay is not None,
                   "trace_sha256": hashlib.sha256(canonical_json(trace).encode()).hexdigest(),
                   "metrics": {"elapsed_seconds": time.monotonic() - started, "cpu_seconds": time.process_time() - cpu_started,
                               "hardware": {"machine": platform.machine(), "logical_cpus": os.cpu_count(), "processor": processor},
                               "process_peak_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                               "decision_cycle_median_ms": statistics.median(latencies),
                               "decision_cycle_p95_ms": ordered[max(0, math.ceil(len(ordered) * .95) - 1)],
                               "decision_cycle_p99_ms": ordered[max(0, math.ceil(len(ordered) * .99) - 1)],
                               "decision_cycle_samples_ms": latencies}}
        if route_driver:
            summary.update(conditional_route_verified=route_verified, opening_condition=route_task.goal["starting_conditions"],
                           route_driver="declared-route-then-visible-baseline-v2")
        return summary, trace
