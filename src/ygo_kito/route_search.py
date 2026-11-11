"""Bounded replay-prefix exploration of actual core-offered player actions.

Search never receives an engine handle, seed, other hand or deck order in its
ranker. Static public-card facts only propose branches; the core proves routes.
The opponent passes in this conditional construction probe, not an ability test.
"""
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
import json
import math
import secrets
import time

from .build_contracts import DISCOVERY_GOALS, SUMMON_ROUTE_TYPES, digest
from .contracts import ActionSelection
from .extra_routes import completed_special_summon, completed_fusion_summon, profile_for
from .native import NativeError, NativeNormalEngine
from .normal_duel import request_digest
from .native_protocol import public_operation
from .validation import ContractError, array, canonical_json, fields, integer

DRIVER = "bounded-public-dto-route-search-v1"
_PROBE_SEEDS = tuple(dict.fromkeys((7, 24, 1724, *range(64))))
_SHARED_PROBE_SEEDS = ContextVar("route_search_probe_seeds", default=None)
_CONDITIONAL_CB = ContextVar("conditional_basic_cb_search", default=False)


@contextmanager
def shared_probe_seeds():
    """Share one finite audit-only probe cursor within a single CB inference."""
    token = _SHARED_PROBE_SEEDS.set(iter(_PROBE_SEEDS))
    try:
        yield
    finally:
        _SHARED_PROBE_SEEDS.reset(token)


@contextmanager
def conditional_cb_search():
    """Explore an explicitly hypothesized own hand, never opening probability."""
    token = _CONDITIONAL_CB.set(True)
    try:
        yield
    finally:
        _CONDITIONAL_CB.reset(token)


def action_intent(request, action, *, schema_version=2):
    """Public effect identity; version 1 remains readable for old receipts."""
    integer(schema_version, "discovered intent schema", 1, 2)
    identities = {c.ref: c.card_id for c in request.observation.cards}
    identities.update({c.ref: c.card_id for c in request.search_choices})
    identities.update({c.ref: c.card_id for c in request.selection_choices})
    operation = public_operation(request,action) if schema_version==2 else (
        'search' if request.search_choices and action.kind=='select' else action.kind)
    if schema_version == 1 and request.prompt.message == 12 and action.kind == 'activate':
        operation='yes'  # preserve pre-v2 discovery receipts on replay
    intent = {"operation": operation, "card_ids": [identities.get(r) for r in action.card_refs]}
    if schema_version == 2 and operation == "activate" and action.details and action.details.description is not None:
        intent["effect_description"] = action.details.description
    return intent


def resolved_chain_cards(events,player=0):
    """Only common-public CHAINING/SOLVED/NEGATED/DISABLED broadcasts.

    A processed, non-negated chain link is not itself evidence of its precise
    benefit. Separate final-state objectives still have to be proved by core.
    """
    links={};blocked=set();result=set()
    for event in events:
        kind=event['kind']
        if kind==70:links[event['link']]=(event['public_card'],event['player'])
        elif kind in (75,76):blocked.add(event['link'])
        elif kind==73 and event['link'] in links and event['link'] not in blocked:
            code,seat=links[event['link']]
            if seat==player:result.add(code)
        elif kind==74:links.clear();blocked.clear()
    return result


def effect_goal_witness(goal, events, *, exact_description=False):
    """Bind an identity-free effect quantity to its own solved public link."""
    objective = goal['effect_objective']
    known, blocked, active, quantity = {}, set(), None, 0
    for event in events:
        kind, link = event['kind'], event.get('link')
        if kind == 70:
            description = event.get('description') or 0
            index_ok = (description % 16 + 1 == objective['effect_index'] if description >= 10000
                        else not exact_description)
            known[link] = event.get('public_card') == goal['card_id'] and event.get('player') == 0 and index_ok
        elif kind in (75, 76):
            blocked.add(link)
        elif kind == 72:
            active, quantity = link, 0
        elif kind == 73:
            if active == link and known.get(link) and link not in blocked and quantity >= objective['minimum']:
                return dict(kind=objective['kind'], effect_index=objective['effect_index'], link=link, quantity=quantity)
            active, quantity = None, 0
        elif kind == 74:
            known.clear()
            blocked.clear()
            active, quantity = None, 0
        elif active is not None and known.get(active) and event.get('player') == 0:
            if objective['kind'] == 'draw' and kind == 90:
                quantity += event['count']
            if (objective['kind'] == 'mill' and kind == 50 and event.get('from_zone') == 1
                    and event.get('to_zone') == 16 and event.get('reason', 0) & 0x40):
                quantity += 1
    return None


def discovery_binding(task, deck, assets):
    """Check public card type or the exact printed effect before any search."""
    goal = task.goal
    if goal['kind'] in SUMMON_ROUTE_TYPES:
        return {} if assets.rows[goal['card_id']]['type'] & SUMMON_ROUTE_TYPES[goal['kind']] else None
    if goal['kind'] != 'effect_resolution':
        return None
    from .effect_mechanisms import MechanismCatalog
    from .basic_cb_inference import _effect_objectives
    records = MechanismCatalog(assets, task.pool).effect_records(goal['card_id'])
    objective = goal['effect_objective']
    matching = [r for r in records if r['effect_index'] == objective['effect_index']]
    if len(matching) == 1 and any(op['kind'] == objective['kind'] and op['minimum'] >= objective['minimum']
            for op in _effect_objectives(matching[0], deck, assets.rows)):
        return {'exact_description': len(records) > 1}
    return None


def route_witness(goal, events, observation, *, fusion_effects=None, exact_description=False):
    kind, target = goal['kind'], goal['card_id']
    if kind == 'effect_resolution':
        return effect_goal_witness(goal, events, exact_description=exact_description)
    if kind == 'fusion_summon':
        return completed_fusion_summon(events, observation, 0, target, fusion_effects)
    if not completed_special_summon(events, observation, 0, target):
        return None
    reason = {'link_summon': 0x10000000, 'ritual_summon': 0x100000}.get(kind)
    if reason is None:
        return dict(kind=kind)
    start = max(i for i, event in enumerate(events)
                if event['kind'] == 62 and event.get('public_summoning_card') == target and event.get('player') == 0)
    boundary = max((i for i, event in enumerate(events[:start]) if event['kind'] in (61, 62, 63, 72, 73, 74)), default=-1)
    complete = next(i for i in range(start + 1, len(events)) if events[i]['kind'] == 63)
    moves = [dict(from_zone=event['from_zone'], to_zone=event['to_zone'], reason=event['reason'])
             for event in events[boundary+1:complete] if event['kind'] == 50 and event.get('player') == 0
             and event.get('reason', 0) & (reason | 0x8) == reason | 0x8]
    return dict(kind=kind, material_moves=moves) if moves else None


def ranked_actions(request, goal, rows, *, width=4):
    """Pure observer DTO/public catalog function; no live-state oracle."""
    cards = {c.ref: c for c in request.observation.cards}
    identities = {r: c.card_id for r, c in cards.items()}
    identities.update({c.ref: c.card_id for c in request.search_choices})
    identities.update({c.ref: c.card_id for c in request.selection_choices})
    target_level = rows[goal["card_id"]]["level"] & 255
    def score(action):
        if request.observation.observer != 0:
            return 100 if action.kind == "pass" else 0
        ids = [identities.get(r) for r in action.card_refs]
        facts = [rows[c] for c in ids if c in rows]
        if action.details and action.details.operation == "shuffle":
            return -10000
        if action.details and action.details.operation in ("remove", "cancel"):
            return -20
        if action.details and action.details.operation == "finish":
            return 1100
        if goal["card_id"] in ids and action.kind in ("special_summon","select"):
            return 1000
        objectives=set(goal.get('_required_effects',()))
        if goal['kind'] == 'effect_resolution':
            objectives.add(goal['card_id'])
        opening=set(goal['starting_conditions']['requires_opening_hand'])
        if action.kind=='activate' and objectives.intersection(ids):return 900
        if action.kind=='summon' and opening.intersection(ids):return 850
        if (request.search_choices or request.prompt.message in (15,20,23,26)) and action.kind=='select' and objectives.intersection(ids):return 800
        if action.details and action.details.operation == "finish":
            return 100
        if action.kind == "activate":
            return 90
        if action.kind == "special_summon":
            return 80
        if action.kind == "summon":
            return 70 + sum(bool(r["type"] & 0x20) for r in facts)
        if request.search_choices or request.prompt.message in (15, 20, 23, 26):
            if action.details and action.details.operation in ("remove", "cancel"):
                return -20
            if action.kind == "select":
                value = 20 + len(ids)
                if goal["kind"] == "xyz_summon":
                    value += 10 * sum((r["level"] & 255) == target_level for r in facts)
                elif goal["kind"] == "synchro_summon":
                    field = [rows[c.card_id] for c in cards.values()
                             if c.zone == "monster" and c.controller == 0 and c.card_id in rows]
                    has_tuner = any(r["type"] & 0x1000 for r in field)
                    value += 10 * sum(bool(r["type"] & 0x1000) != has_tuner for r in facts)
                    field_levels = {r["level"] & 255 for r in field if bool(r["type"] & 0x1000) == has_tuner}
                    value += 12 * sum(any((r["level"] & 255) + n == target_level for n in field_levels) for r in facts)
                return value
        return {"yes": 15, "pass": 5, "select": 2, "position": 2}.get(action.kind, -10)
    ordered = sorted(request.actions, key=lambda a: (-score(a), a.action_id))
    ordered = [a for a in ordered if not (a.details and a.details.operation == "shuffle")]
    if request.observation.observer != 0 or request.prompt.message in (18, 19) or (
            request.prompt.message == 16 and all(a.kind == "pass" for a in ordered)):
        return ordered[:1]
    return ordered[:width]


def discover_goal(task, deck, assets, *, seconds=10., attempts=16, decision_budget=100, branch_budget=24, width=4,required_activations=(),required_chain_resolutions=()):
    assets.validate(task, deck)
    integer(attempts, "discovery attempts", 0, 64)
    integer(decision_budget, "discovery decisions per branch", 1, 100)
    integer(branch_budget, "discovery replay branch budget", 1, 64)
    integer(width, "discovery branch width", 1, 8)
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds <= 30:
        raise ContractError("discovery wall budget outside CPU range")
    if task.schema_version != 3 or "route" in task.goal or task.goal["kind"] not in DISCOVERY_GOALS:
        raise ContractError("discovery requires a version-3 goal without prewritten route")
    for values in (required_activations,required_chain_resolutions):
        if not isinstance(values,tuple) or len(values)>4:raise ContractError('bounded distinct effect objectives required')
        for code in values:
            integer(code,'effect objective card',1,2**32-1)
            if code not in task.pool:raise ContractError('effect objective outside public pool')
        if len(set(values))!=len(values):raise ContractError('effect objectives repeat')
    binding = discovery_binding(task, deck, assets)
    if binding is None:
        return {"status": "unsupported_route", "card_list_legal": True,
                "unmet": ["goal lacks its matching public card type or printed effect"], "core_attempts": []}
    witness=task.goal.get('fusion_witness')
    if task.goal['kind']=='fusion_summon':
        from .fusion_witness import validate_fusion_witness
        validate_fusion_witness(witness,task.pool,assets)
    fusion_effects=witness if task.goal['kind']=='fusion_summon' else None
    started, trials, branches, failures = time.monotonic(), [], 0, []
    branch_diagnostics=[]; expanded=0; incomplete=set(); pending=[]
    from .extra_routes import goal_profile_for
    selection_key = secrets.token_hex(16) if goal_profile_for(assets,deck).get("adapter_revision") in (4,5) else None
    required = Counter(task.goal["starting_conditions"]["requires_opening_hand"])
    controlled_hand = tuple(task.goal["starting_conditions"]["requires_opening_hand"]) if _CONDITIONAL_CB.get() else None
    assumption = ({"mode":"hypothetical_exact_hand_v1","player":0,"hand":list(controlled_hand),
                   "unspecified_hand_resources":0,"opening_probability_evaluated":False}
                  if controlled_hand is not None else None)
    # One controlled initial state; the seed only fixes effect randomness and
    # private remaining-deck order for reproducible branches. It never selects
    # whether the declared starter happens to be drawn.
    seeds = iter((7,)) if controlled_hand is not None else _SHARED_PROBE_SEEDS.get()
    if seeds is None:
        seeds = iter(_PROBE_SEEDS)
    for _ in range(attempts):
        # A timed-out candidate must leave untried seeds for the next candidate.
        if branches >= branch_budget or time.monotonic() - started >= seconds:
            break
        try:
            seed = next(seeds)
        except StopIteration:
            break
        pending = [()]
        while pending and branches < branch_budget and time.monotonic() - started < seconds:
            prefix = pending.pop()
            branches += 1
            audit, sums, intents = [], [], []
            activated=set()
            try:
                from .extra_routes import engine_for_goal
                options = {"cb_opening_hand":controlled_hand} if controlled_hand is not None else {}
                with engine_for_goal(assets,deck,seed,selection_key=selection_key,**options) as engine:
                    req = engine.next_decision()
                    linear = None
                    if controlled_hand is not None:
                        from .basic_cb_scope import LinearMainline
                        from .effect_mechanisms import MechanismCatalog
                        linear = LinearMainline(MechanismCatalog(assets, task.pool), controlled_hand, deck.extra)
                    opening = Counter(c.card_id for c in engine._observation(0).cards if c.zone == "hand")
                    present = all(opening[c] >= n for c, n in required.items())
                    if controlled_hand is not None and opening != required:
                        raise NativeError("controlled CB initial hand differs from the declared exact multiset")
                    if not prefix:
                        trials.append({"seed_audit_only": seed, "declared_opening_condition_met": present,
                                       **({"opening_assumption":assumption} if assumption is not None else {})})
                    if not present:
                        break
                    for depth in range(decision_budget):
                        if req is None or engine.turn > 1 or time.monotonic() - started >= seconds:
                            break
                        search_request = req
                        if linear is not None:
                            from dataclasses import replace
                            linear.observe(engine._observation(0), engine.events)
                            safe = tuple(a for a in req.actions if linear.allows(req, a))
                            if not safe:
                                if linear.unknown:incomplete.add('unknown_linear_conditions')
                                break
                            search_request = replace(req, actions=safe,
                                observation=replace(req.observation,cards=linear.known_cards(req.observation)))
                        choices = ranked_actions(search_request, dict(task.goal,_required_effects=tuple(set(required_activations)|set(required_chain_resolutions))), assets.rows, width=width)
                        if not choices:
                            break
                        fingerprint = request_digest(req)
                        if depth < len(prefix):
                            expected, chosen_id = prefix[depth]
                            action = next((a for a in req.actions if a.action_id == chosen_id), None)
                            if expected != fingerprint or action is None:
                                raise ContractError("replayed search prefix diverged from observer decision")
                            if linear is not None and not linear.allows(req, action):
                                break
                        else:
                            expanded += 1
                            action = choices[0]
                            for alternative in reversed(choices[1:]):
                                if len(pending) < branch_budget:
                                    pending.append(tuple((r["request_sha256"], r["action_id"]) for r in audit)
                                                   + ((fingerprint, alternative.action_id),))
                        identities = {c.ref: c.card_id for c in req.observation.cards}
                        identities.update({c.ref: c.card_id for c in req.search_choices})
                        if action.card_refs:
                            intents.append(action_intent(req, action))
                            if action.kind=='activate' and req.observation.observer==0:
                                activated.update(identities.get(r) for r in action.card_refs)
                        if req.sum_selection is not None:
                            window = json.loads(canonical_json(req.to_dict()))
                            window["context"]["run_id"] = "private-search-replay-audit"
                            sums.append({"request": window, "chosen_card_ids": [identities[r] for r in action.card_refs],
                                         "action_id": action.action_id})
                        audit.append({"player": req.observation.observer, "request_sha256": fingerprint, "action_id": action.action_id})
                        if linear is not None:
                            linear.select(req, action)
                        engine.submit(ActionSelection(req.context.run_id, req.duel_id, req.decision_id, action.action_id))
                        req = engine.next_decision()
                        own = engine._observation(0)
                        if linear is not None:
                            linear.observe(own, engine.events)
                        # Trigger effects can be accepted through YES/CHAIN prompts,
                        # not an action whose kind is literally "activate".
                        # Core CHAINING broadcasts establish actual activation.
                        activated={e['public_card'] for e in engine.events if e['kind']==70 and e.get('player')==0 and 'public_card' in e}
                        completed = route_witness(task.goal, engine.events, own, fusion_effects=fusion_effects, **binding)
                        if (completed is not None and (linear is None or linear.supports_goal(task.goal)) and set(required_activations)<=activated
                            and set(required_chain_resolutions)<=resolved_chain_cards(engine.events)):
                            return {"status": "verified_success", "card_list_legal": True, "task_sha256": task.sha256,
                                    "deck_sha256": digest(deck.to_dict()), "starting_condition": task.goal["starting_conditions"],
                                    "random_dependency": ("controlled declared hand; effect randomness not exhaustively explored; no opening probability or strength claim"
                                                          if assumption is not None else "actual declared opening; neutral opponent; no stability/probability claim"),
                                    "core_attempts": trials, "responses": audit, "core_event_kinds": [e["kind"] for e in engine.events],
                                    "trajectory_sha256": digest(audit), "elapsed_seconds": time.monotonic() - started, "unmet": [],
                                    "route_evidence": {"driver": DRIVER, "opponent": "neutral-pass-engineering-only", "conditional_only": True,
                                        **({'basic_cb_scope':linear.receipt()} if linear is not None else {}),
                                        **({"opening_assumption":assumption} if assumption is not None else {}),
                                        "material_preference": "public-fact-ranked", "sum_choices": sums,
                                        **({'fusion_summon_evidence':completed} if task.goal['kind'] == 'fusion_summon' else {}),
                                        **({'objective_evidence':completed} if task.goal['kind'] in ('link_summon','ritual_summon','effect_resolution') else {}),
                                        "final_observation": json.loads(canonical_json(asdict(own))),
                                        "core_event_audit_not_policy_input": list(engine.events), "versions": task.environment["versions"],
                                        **({"private_selection_key_audit_only":selection_key} if selection_key is not None else {}),
                                        "exploration": {"branches_executed": branches, "branch_budget": branch_budget,
                                                        "discovered_intents": intents, "intent_schema_version": 2,
                                                        "nodes_expanded": expanded, "prewritten_route_supplied": False,
                                                        "failed_branches": failures,
                                                        **({'required_activations':list(required_activations)} if required_activations else {}),
                                                        **({'required_chain_resolutions':list(required_chain_resolutions)} if required_chain_resolutions else {})}}}
                    if len(audit) >= decision_budget:incomplete.add('decision_budget_exhausted')
                    if linear is not None and linear.unknown:incomplete.add('unknown_linear_conditions')
                    branch_diagnostics.append({'seed_audit_only':seed,'decisions':len(audit),
                        'required_activations_seen':sorted(set(required_activations)&activated),
                        'required_resolutions_seen':sorted(set(required_chain_resolutions)&resolved_chain_cards(engine.events)),
                        'goal_special_summon_completed':task.goal['kind'] != 'effect_resolution' and completed_special_summon(
                            engine.events, engine._observation(0), 0, task.goal['card_id']),
                        'fusion_material_moves':[{k:e[k] for k in ('kind','from_zone','to_zone','reason','player') if k in e}
                            for e in engine.events if e['kind']==50 and e.get('reason',0)&0x40008==0x40008],
                        'last_own_legal_intents':intents[-20:],
                        'chain_and_summon_events':[e for e in engine.events if e['kind'] in (62,63,70,72,73,74,75,76)][-32:]})
                    branch_diagnostics=branch_diagnostics[-4:]
            except NativeError as error:
                # Unsupported messages terminate this branch; never replace a rule.
                failures.append({"status": "unsupported_native_branch", "reason": str(error)[:256]})
        if branches >= branch_budget:
            break
    if time.monotonic()-started >= seconds:incomplete.add('time_budget_exhausted')
    if pending:incomplete.add('search_frontier_pending')
    if failures:incomplete.add('unsupported_native_branch')
    normal = bool(expanded) and not incomplete
    return {"status": "not_found_within_budget" if expanded else "not_run", "card_list_legal": True, "core_attempts": trials,
            **({"opening_assumption":assumption} if assumption is not None else {}),
            "search_started": bool(expanded), "inference_completed": normal,
            'normal_completion':normal, 'incomplete_reasons':sorted(incomplete),
            "stop_reason": "bounded_exploration_finished" if normal else
                sorted(incomplete)[0] if incomplete else "no_action_expansion",
            "unmet": ["bounded actual-core action exploration exhausted; not impossibility"],
            "exploration": {"branches_executed": branches, "nodes_expanded": expanded,
                            "failed_branches": failures, "last_branches":branch_diagnostics}}


def replay_discovered_goal(task, deck, assets, proof,*,required_activations=(),required_chain_resolutions=()):
    assets.validate(task, deck)
    fields(proof, {"status", "card_list_legal", "task_sha256", "deck_sha256", "starting_condition", "random_dependency",
                   "core_attempts", "responses", "core_event_kinds", "trajectory_sha256", "elapsed_seconds", "unmet", "route_evidence"})
    evidence = fields(proof["route_evidence"], {"driver", "opponent", "conditional_only", "material_preference", "sum_choices",
        "final_observation", "core_event_audit_not_policy_input", "versions", "exploration"}, {"private_selection_key_audit_only","fusion_summon_evidence","opening_assumption","basic_cb_scope","objective_evidence"})
    exploration = fields(evidence["exploration"], {"branches_executed", "branch_budget", "discovered_intents", "prewritten_route_supplied", "failed_branches"},{'required_activations','required_chain_resolutions','intent_schema_version','nodes_expanded'})
    intent_schema=exploration.get('intent_schema_version',1)
    integer(intent_schema,'discovered intent schema',1,2)
    integer(exploration["branch_budget"], "replay branch budget", 1, 64)
    integer(exploration["branches_executed"], "replay branch count", 1, exploration["branch_budget"])
    binding = discovery_binding(task, deck, assets)
    if (task.schema_version != 3 or "route" in task.goal or binding is None
            or proof["status"] != "verified_success" or proof["task_sha256"] != task.sha256 or proof["deck_sha256"] != digest(deck.to_dict())
            or proof["starting_condition"] != task.goal["starting_conditions"] or proof["card_list_legal"] is not True
            or proof["trajectory_sha256"] != digest(proof["responses"]) or evidence["versions"] != task.environment["versions"]
            or evidence["driver"] != DRIVER or evidence["conditional_only"] is not True
            or evidence["exploration"].get("prewritten_route_supplied") is not False
            or tuple(exploration.get('required_activations',()))!=required_activations
            or tuple(exploration.get('required_chain_resolutions',()))!=required_chain_resolutions):
        raise ContractError("discovered route binding differs")
    witness=task.goal.get('fusion_witness')
    if task.goal['kind']=='fusion_summon':
        from .fusion_witness import validate_fusion_witness
        validate_fusion_witness(witness,task.pool,assets)
        if not evidence.get('fusion_summon_evidence'):raise ContractError('special summon alone cannot certify fusion')
    fusion_effects=witness if task.goal['kind']=='fusion_summon' else None
    responses = array(proof["responses"], "discovered responses")
    integer(len(responses), "discovered response count", 1, 100)
    attempts = array(proof["core_attempts"], "discovered attempts")
    integer(len(attempts), "discovered attempt count", 1, 64)
    seed = proof["core_attempts"][-1]["seed_audit_only"]
    integer(seed, "replay audit seed", 0, 2**32 - 8)
    from .extra_routes import engine_for_goal, route_selection_key
    selection_key=route_selection_key(assets,deck,evidence)
    assumption=evidence.get("opening_assumption")
    controlled_hand=None
    if assumption is not None:
        expected={"mode":"hypothetical_exact_hand_v1","player":0,
                  "hand":list(task.goal["starting_conditions"]["requires_opening_hand"]),
                  "unspecified_hand_resources":0,"opening_probability_evaluated":False}
        if assumption!=expected:raise ContractError("controlled replay opening assumption differs from the task")
        controlled_hand=tuple(expected['hand'])
    options={"cb_opening_hand":controlled_hand} if controlled_hand is not None else {}
    linear = None
    if evidence.get('basic_cb_scope') is not None:
        from .basic_cb_scope import LinearMainline, VERSION as SCOPE_VERSION
        from .effect_mechanisms import MechanismCatalog
        if controlled_hand is None or evidence['basic_cb_scope'].get('version') != SCOPE_VERSION:
            raise ContractError('linear basic CB replay requires its exact opening and scope')
        linear = LinearMainline(MechanismCatalog(assets, task.pool), controlled_hand, deck.extra)
    with engine_for_goal(assets,deck,seed,selection_key=selection_key,**options) as engine:
        req = engine.next_decision()
        opening = Counter(c.card_id for c in engine._observation(0).cards if c.zone == "hand")
        if controlled_hand is not None and opening!=Counter(controlled_hand):
            raise ContractError("controlled replay did not reproduce the exact hypothetical hand")
        if any(opening[c] < n for c, n in Counter(task.goal["starting_conditions"]["requires_opening_hand"]).items()):
            raise ContractError("discovered replay actual opening does not satisfy the task")
        activated=set();actual_intents=[]
        for row in responses:
            fields(row, {"player", "request_sha256", "action_id"})
            if (req is None or engine.turn != 1 or request_digest(req) != row["request_sha256"]
                    or req.observation.observer != row["player"]):
                raise ContractError("discovered route replay request diverged")
            action=next((a for a in req.actions if a.action_id==row['action_id']),None)
            if action is None:raise ContractError('discovered action not offered')
            if linear is not None:
                linear.observe(engine._observation(0), engine.events)
                if not linear.allows(req,action):
                    raise ContractError('replayed basic CB depends on an unconfirmed resource')
                linear.select(req,action)
            identities={c.ref:c.card_id for c in req.observation.cards}
            identities.update({c.ref:c.card_id for c in req.search_choices})
            if action.card_refs:
                ids=[identities.get(ref) for ref in action.card_refs]
                actual_intents.append(action_intent(req,action,schema_version=intent_schema))
                if action.kind=='activate' and row['player']==0:activated.update(ids)
            engine.submit(ActionSelection(req.context.run_id, req.duel_id, req.decision_id, row["action_id"]))
            req = engine.next_decision()
        if linear is not None:
            linear.observe(engine._observation(0), engine.events)
            if (not linear.supports_goal(task.goal)
                    or linear.receipt() != evidence['basic_cb_scope']):
                raise ContractError('replayed basic CB mainline scope differs')
        activated={e['public_card'] for e in engine.events if e['kind']==70 and e.get('player')==0 and 'public_card' in e}
        completed = route_witness(task.goal, engine.events, engine._observation(0), fusion_effects=fusion_effects, **binding)
        if task.goal['kind']=='fusion_summon':
            if completed is None or completed != evidence.get('fusion_summon_evidence'):
                raise ContractError('fusion replay lacks its resolved-effect/material-return/summon binding')
        elif task.goal['kind'] in ('link_summon','ritual_summon','effect_resolution') and completed != evidence.get('objective_evidence'):
            raise ContractError('replayed objective evidence differs')
        if (engine.turn != 1 or engine.events != evidence["core_event_audit_not_policy_input"]
                or [e["kind"] for e in engine.events] != proof["core_event_kinds"]
                or json.loads(canonical_json(asdict(engine._observation(0)))) != evidence["final_observation"]
                or actual_intents!=exploration['discovered_intents'] or not set(required_activations)<=activated
                or not set(required_chain_resolutions)<=resolved_chain_cards(engine.events)
                or completed is None):
            raise ContractError("discovered route replay did not reproduce its completed objective")
    return {"replay_verified": True, "trajectory_sha256": proof["trajectory_sha256"]}
