"""Explicit route intents executed only through real core-offered actions.

These are conditional engineering proofs with a passing opponent, not a combo
solver, opening-hand probability estimate, or demonstration of model ability.
"""
from collections import Counter
from dataclasses import asdict
import json
import math
import secrets
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


def completed_fusion_summon(events, observation, player, code, fusion_effects):
    """Bind a reviewed fusion effect, Fusion-reason materials and target summon.

    MSG62/63 alone proves only Special Summon. Material moves are public zone/
    reason facts; this function never reads identities returned to a hidden deck.
    Core constants: REASON_MATERIAL=0x8, REASON_FUSION=0x40000.
    """
    if not completed_special_summon(events, observation, player, code):
        return None
    witness=fusion_effects
    effect_ids={r['card_id'] for r in witness['effect_assessments']}
    starts=[i for i,e in enumerate(events) if e['kind']==62 and
            e.get('public_summoning_card')==code and e.get('player')==player]
    start=starts[-1]
    complete=next((i for i in range(start+1,len(events)) if events[i]['kind']==63),None)
    solved=next((i for i in range((complete or start)+1,len(events)) if events[i]['kind'] in (73,74)),None)
    if complete is None or solved is None or events[solved]['kind']!=73:
        return None
    boundary=max((i for i in range(start) if events[i]['kind']==74),default=-1)
    link=events[solved].get('link')
    chained=next((i for i in range(start-1,boundary,-1) if events[i]['kind']==70 and
                  events[i].get('link')==link and events[i].get('player')==player and
                  events[i].get('public_card') in effect_ids),None)
    if chained is None or any(e['kind'] in (75,76) and e.get('link')==link for e in events[chained:solved+1]):
        return None
    # The next solved link owns this resolution window. Exclude earlier links.
    window=max([chained]+[i for i in range(chained+1,start) if events[i]['kind'] in (72,73)])
    materials=[{'event_index':i,**e} for i,e in enumerate(events[window+1:start],window+1)
               if e['kind']==50 and e.get('player')==player and e.get('reason',0)&0x40008==0x40008 and
               e.get('from_zone') in (1,2,4,8,16,32,64) and e.get('to_zone') in witness['allowed_destination_zones']]
    if len(materials)<witness['minimum_materials'] or any(not any(e['from_zone']==z for e in materials) for z in witness['required_source_zones']):
        return None
    return {'kind':'resolved-fusion-effect-and-materials-v1','witness_sha256':digest(witness),'fusion_effect_card':events[chained]['public_card'],
            'chain_link':link,'chaining_event_index':chained,'chain_solved_event_index':solved,
            'target_card':code,'summon_start_event_index':start,'summon_complete_event_index':complete,
            'materials':materials,'material_identity_in_hidden_deck_read':False,
            'conditional_only':True,'whole_graph_execution_verified':False}


def profile_for(deck, *, opponent=None):
    opponent = deck if opponent is None else opponent
    return {"schema_version": 2, "name": "conditional-extra-goal-engineering-v2",
            "decks": [list(deck.main), list(opponent.main)],
            "extras": [list(deck.extra), list(opponent.extra)], "sides": [list(deck.side), list(opponent.side)]}


def goal_profile_for(assets, deck):
    profile=profile_for(deck)
    if hasattr(assets,"adapt_goal_profile"):profile=assets.adapt_goal_profile(profile)
    return profile


def validate_goal_selection_key(profile, selection_key, *, required=False):
    private = profile.get("adapter_revision") in (4, 5)
    if selection_key is None:
        if private and required:
            raise ContractError("private route replay requires its audit selection key")
        return
    if not private:
        raise ContractError("route audit selection key requires a private adapter")
    try:
        if not isinstance(selection_key, str) or len(selection_key) != 32 or len(bytes.fromhex(selection_key)) != 16:
            raise ValueError()
    except ValueError as error:
        raise ContractError("invalid private route audit selection key") from error


def route_selection_key(assets, deck, evidence):
    """Validate private audit framing before opening a replay engine."""
    key = evidence.get("private_selection_key_audit_only")
    validate_goal_selection_key(goal_profile_for(assets, deck), key, required=True)
    return key


def engine_for_goal(assets,deck,seed,*,selection_key=None,cb_opening_hand=None):
    profile=goal_profile_for(assets,deck)
    validate_goal_selection_key(profile, selection_key)
    options = {"selection_key": selection_key} if selection_key is not None else {}
    if cb_opening_hand is not None:options['cb_opening_hand']=cb_opening_hand
    return getattr(assets,"engine_factory",NativeNormalEngine)(assets.root,
        scenario="conditional-cb" if cb_opening_hand is not None else "effect-duel",deck_profile=profile,seed=seed,**options)


def verify_extra_goal(task, deck, assets, *, seconds=10., attempts=16, decision_budget=100, material_preference="first"):
    integer(attempts, "extra route attempts", 0, 64)
    integer(decision_budget, "extra route decision budget", 1, 100)
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds <= 30:
        raise ContractError("extra route time budget outside CPU proof range")
    member(material_preference, "material preference", ("first", "last"))
    assets.validate(task, deck)
    kind, goal = task.goal["kind"], task.goal["card_id"]
    if kind == "fusion_summon":
        return {"status":"unsupported_route", "card_list_legal":True, "core_attempts":[],
                "unmet":["fusion requires v3 discovery with resolved-effect/material-return witness"]}
    mask = {"synchro_summon": 0x2000, "xyz_summon": 0x800000, "fusion_summon": 0x40}.get(kind)
    if mask is None or not assets.rows[goal]["type"] & mask:
        return {"status": "unsupported_route", "card_list_legal": True, "unmet": ["goal kind and card type differ"], "core_attempts": []}
    started, trials = time.monotonic(), []
    required = Counter(task.goal["starting_conditions"]["requires_opening_hand"])
    last_unmet = "conditional route not found within the declared search budget; not impossibility"
    selection_key = secrets.token_hex(16) if goal_profile_for(assets,deck).get("adapter_revision") in (4,5) else None
    for seed in tuple(dict.fromkeys((7, 24, 1724, *range(64))))[:attempts]:
        if time.monotonic() - started >= seconds:
            break
        audit, sums = [], []
        driver = RouteDriver(task.goal["route"], material_preference=material_preference)
        with engine_for_goal(assets,deck,seed,selection_key=selection_key) as engine:
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
                    window = json.loads(canonical_json(request.to_dict()))
                    # Live run IDs bind submissions; persisted receipt equality
                    # describes decisions and must not depend on random sessions.
                    window["context"]["run_id"] = "private-route-replay-audit"
                    sums.append({"request": window, "chosen_card_ids": [cards[r] for r in action.card_refs],
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
                                               "core_event_audit_not_policy_input": list(engine.events), "versions": task.environment["versions"],
                                               **({"private_selection_key_audit_only":selection_key} if selection_key is not None else {})}}
    return {"status": "not_found_within_budget", "card_list_legal": True, "core_attempts": trials, "unmet": [last_unmet]}
