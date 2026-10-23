"""Explicit route intents executed only through real core-offered actions.

These are conditional engineering proofs with a passing opponent, not a combo
solver, opening-hand probability estimate, or demonstration of model ability.
"""
from collections import Counter
from dataclasses import asdict
import json
import math
import time

from .build_contracts import digest
from .contracts import ActionSelection
from .native import NativeNormalEngine
from .normal_duel import request_digest
from .validation import ContractError, canonical_json, integer, member


class RouteUnavailable(RuntimeError):
    pass


class RouteDriver:
    """Versioned public intent driver; has no handle to the engine or deck order."""
    version = "explicit-route-dto-v1"

    def __init__(self, route, *, player=0, material_preference="first"):
        member(material_preference, "material preference", ("first", "last"))
        self.route, self.player, self.preference, self.cursor = route, player, material_preference, 0

    def choose(self, request):
        cards = {c.ref: c.card_id for c in request.observation.cards}
        cards.update({c.ref: c.card_id for c in request.search_choices})
        step = self.route[self.cursor] if self.cursor < len(self.route) else None
        if request.observation.observer == self.player and step is not None:
            for action in request.actions:
                operation = "search" if request.search_choices and action.kind == "select" else action.kind
                if operation == step["operation"] and Counter(cards[r] for r in action.card_refs) == Counter(step["card_ids"]):
                    self.cursor += 1
                    return action
        if request.search_choices:
            raise RouteUnavailable("no offered deck selection matches the next declared route intent")
        if request.prompt.message in (15, 20, 23, 26):
            finished = next((a for a in request.actions if a.details and a.details.operation == "finish"), None)
            if finished is not None:
                return finished
            choices = [a for a in request.actions if a.kind == "select"]
            if choices:
                return choices[-1] if self.preference == "last" and request.prompt.message == 23 else choices[0]
        for kind in ("pass", "yes"):
            action = next((a for a in request.actions if a.kind == kind), None)
            if action is not None:
                return action
        if request.prompt.message in (14, 18, 19):
            return request.actions[0]
        raise RouteUnavailable("no supported neutral response while waiting for the declared route")


def completed_special_summon(events, observation, player, code):
    # Earlier SpecialSummonComplete events cannot certify a later pending summon.
    starts = [i for i, e in enumerate(events) if e["kind"] == 62 and e.get("public_summoning_card") == code and e.get("player") == player]
    return (bool(starts) and any(e["kind"] == 63 for e in events[starts[-1] + 1:])
            and any(c.zone == "monster" and c.controller == player and c.card_id == code and c.visibility == "public"
                    for c in observation.cards))


def profile_for(deck, *, opponent=None):
    opponent = deck if opponent is None else opponent
    return {"schema_version": 2, "name": "conditional-extra-goal-engineering-v2",
            "decks": [list(deck.main), list(opponent.main)],
            "extras": [list(deck.extra), list(opponent.extra)], "sides": [list(deck.side), list(opponent.side)]}


def verify_extra_goal(task, deck, assets, *, seconds=10., attempts=16, decision_budget=100, material_preference="first"):
    integer(attempts, "extra route attempts", 0, 64)
    integer(decision_budget, "extra route decision budget", 1, 100)
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds <= 30:
        raise ContractError("extra route time budget outside CPU proof range")
    member(material_preference, "material preference", ("first", "last"))
    assets.validate(task, deck)
    kind, goal = task.goal["kind"], task.goal["card_id"]
    mask = {"synchro_summon": 0x2000, "xyz_summon": 0x800000}.get(kind)
    if mask is None or not assets.rows[goal]["type"] & mask:
        return {"status": "unsupported_route", "card_list_legal": True, "unmet": ["goal kind and card type differ"], "core_attempts": []}
    started, trials = time.monotonic(), []
    required = Counter(task.goal["starting_conditions"]["requires_opening_hand"])
    last_unmet = "conditional route not found within the declared search budget; not impossibility"
    for seed in tuple(dict.fromkeys((7, 24, 1724, *range(64))))[:attempts]:
        if time.monotonic() - started >= seconds:
            break
        audit, sums = [], []
        driver = RouteDriver(task.goal["route"], material_preference=material_preference)
        with NativeNormalEngine(assets.root, scenario="effect-duel", deck_profile=profile_for(deck), seed=seed) as engine:
            request = engine.next_decision()
            own = engine._observation(0)
            opening = Counter(c.card_id for c in own.cards if c.zone == "hand")
            present = all(opening[c] >= n for c, n in required.items())
            trials.append({"seed_audit_only": seed, "declared_opening_condition_met": present})
            if not present:
                continue
            for _ in range(decision_budget):
                if request is None or engine.turn > 1 or time.monotonic() - started >= seconds:
                    break
                try:
                    action = driver.choose(request)
                except RouteUnavailable as error:
                    last_unmet = str(error)
                    break
                audit.append({"player": request.observation.observer, "request_sha256": request_digest(request),
                              "action_id": action.action_id})
                if request.sum_selection is not None:
                    cards = {c.ref: c.card_id for c in request.observation.cards}
                    sums.append({"request": json.loads(canonical_json(request.to_dict())), "chosen_card_ids": [cards[r] for r in action.card_refs],
                                 "action_id": action.action_id})
                engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id))
                request = engine.next_decision()
                own = engine._observation(0)
                if driver.cursor == len(driver.route) and completed_special_summon(engine.events, own, 0, goal):
                    return {"status": "verified_success", "card_list_legal": True,
                            "task_sha256": task.sha256, "deck_sha256": digest(deck.to_dict()),
                            "starting_condition": task.goal["starting_conditions"],
                            "random_dependency": "declared cards must actually be in the opening hand; no probability claim",
                            "core_attempts": trials, "responses": audit, "core_event_kinds": [e["kind"] for e in engine.events],
                            "trajectory_sha256": digest(audit), "elapsed_seconds": time.monotonic() - started, "unmet": [],
                            "route_evidence": {"driver": driver.version, "opponent": "neutral-pass-engineering-only",
                                               "conditional_only": True, "material_preference": material_preference,
                                               "sum_choices": sums, "final_observation": json.loads(canonical_json(asdict(own))),
                                               "core_event_audit_not_policy_input": list(engine.events), "versions": task.environment["versions"]}}
    return {"status": "not_found_within_budget", "card_list_legal": True, "core_attempts": trials, "unmet": [last_unmet]}
