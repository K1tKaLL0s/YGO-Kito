"""Execute scoped construction questions through the period core's legal decisions."""

from collections import Counter, deque
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from .build_contracts import DeckParts, digest
from .build_pipeline import EXTRA_TYPES
from .card_identity import native_card_identity
from .construction_checkpoint import write_json
from .construction_inventory import matches
from .construction_native_evidence import (SUMMON_RESPONSE_EVENTS, admission_effects, chain_links,
    pending_summons, replay_steps, selected_objects, stock_prefix, window_link, window_priority, witnessed_rule)
from .contracts import ActionSelection
from .deck_profile import validate_sideboard_stock
from .effect_duel import choose_effect_duel_action
from .effect_records import operation_record
from .extra_routes import engine_for_goal
from .native import NativeError
from .normal_duel import request_digest
from .validation import ContractError


NATIVE_RULE_VERSION = "construction-native-rules-v5"
NATIVE_EVIDENCE_VERSION = "construction-native-evidence-v8"
_QUERY_WORK_VERSION = "construction-native-query-work-v1"
_DECISION_BUDGET = 100
_DECK_DESTINATIONS = {2: "hand", 16: "grave"}
_OPERATIONS = frozenset(("search_or_recover", "search", "add_hand", "send_grave"))


def _deck_operations(record):
    return [op for op in record["operations"] if op["kind"] in _OPERATIONS
            and op.get("from_zones") == ["deck"] and op.get("to_zone") in _DECK_DESTINATIONS.values()
            and op.get("owner") == "self" and op.get("reason") == "effect"
            and op.get("quantity") == 1 and not op.get("random")]


def _registration_choices(script, setup, *, response_event=1027):
    choices = []
    for reg in script["registrations"]:
        if not reg.get("operation"):
            continue
        location, event = reg.get("range"), reg.get("event")
        spell_activation = setup == "spell" and reg.get("type") == 16
        normal_trigger = setup == "normal_summon" and event == "normal_summon" and location in (None, 4)
        ignition = event == "own_main_phase" and location == {"hand": 2, "normal_summon": 4}.get(setup, -1)
        response = setup == "response" and reg.get("event_code") == response_event
        if not (spell_activation or normal_trigger or ignition or response):
            continue
        index = reg.get("description_index")
        description = script["script_card_id"] * 16 + index if index is not None else (
            None if "description_index" in reg else 0
        )
        item = dict(description=description, family=reg["family"], span=reg["registration_span"],
                    event="card_activation" if spell_activation else "chain_response" if response else event,
                    operation=reg["operation"])
        if response and response_event in SUMMON_RESPONSE_EVENTS:
            item["event"] = "summon_response"
            if "direct_summon_negation" in reg:
                item["direct_summon_negation"] = reg["direct_summon_negation"]
        choices.append(item)
    return choices


def _main_queries(deck, assets, subject=None):
    planned, excluded = [], []
    lua = assets.effect_lua_source
    counts = Counter(deck.main)
    for code in sorted(counts) if subject is None else (subject,):
        row = assets.rows[code]
        monster = bool(row["type"] & 1)
        can_normal = monster and 1 <= (row["level"] & 255) <= 4 and not row["type"] & 0x80
        setups = (["normal_summon"] if can_normal else []) + (
            ["hand"] if monster else ["spell"] if row["type"] & 2 else [])
        script_code, _ = native_card_identity(assets.rows, code)
        settable_response = bool(row["type"] & (0x4 | 0x10000))  # Trap or Quick-Play Spell.
        script = (lua.summarize_effects(script_code, summon_responses=True) if settable_response else
                  lua.summarize_effects(script_code)) if lua is not None else {"registrations": []}
        source = {key: script[key] for key in ("file", "sha256", "helpers") if key in script}
        has_response = False
        response_events = (1027, *SUMMON_RESPONSE_EVENTS) if settable_response else (1027,) if monster else ()
        for response_event in response_events:
            registrations = _response_registrations(script, response_event, prepare_set=settable_response)
            if not registrations:
                continue
            has_response = True
            response = (dict(summon_message=SUMMON_RESPONSE_EVENTS[response_event])
                        if response_event in SUMMON_RESPONSE_EVENTS else dict(any_opponent_activation=True))
            query = dict(card=code, seat=0, setup="response", opening=[code],
                summons=[], response_to=response, registrations=registrations,
                destinations=["grave", "hand"], registration_source=source, priority=1, seed=7, path=[])
            if settable_response:
                query["prepare_set"] = True
            planned.append(query)
            spans = {tuple(r["span"]) for r in registrations}
            if any("cost" in reg and tuple(reg["registration_span"]) in spans for reg in script["registrations"]):
                spare = next((card for card in deck.main if card != code or counts[card] >= 2), None)
                if spare is not None:
                    planned.append(dict(query, opening=[code, spare], priority=2))
        if not setups and not has_response:
            excluded.append(dict(card=code, reason="needs_set_or_other_preparation"))
        windows = {setup: _registration_choices(script, setup) for setup in setups}
        for setup, registrations in windows.items():
            field = [r for r in registrations if r["event"] == "own_main_phase"] if (
                setup == "normal_summon" and counts[code] >= 3
            ) else []
            planned.append(dict(card=code, seat=0, setup=setup, opening=[code],
                summons=[code] if setup == "normal_summon" else [], registrations=registrations,
                field_followup=field, registration_source=source, destinations=["grave", "hand"],
                priority=0 if registrations and setup == "normal_summon" else 1 if registrations else 2,
                seed=7, path=[]))
    return planned, excluded


def _side_inventory(deck, swaps):
    if not swaps:
        return deck
    parts = deck.to_dict()
    for move in swaps:
        incoming, outgoing, zone = (move[key] for key in ("incoming", "outgoing", "zone"))
        if zone not in ("main", "extra") or incoming not in parts["side"] or outgoing not in parts[zone]:
            raise ContractError("a native preparation requires an actual side and active-deck copy")
        parts["side"][parts["side"].index(incoming)] = outgoing
        parts[zone][parts[zone].index(outgoing)] = incoming
    proposal = DeckParts.from_dict(parts)
    validate_sideboard_stock(deck, proposal)
    return proposal


def planned_queries(deck, assets, *, include_side=True):
    """Plan reachable starts from the resident stock and legal Side exchanges."""
    planned, excluded = _main_queries(deck, assets)
    if include_side and isinstance(deck, DeckParts):
        for incoming in sorted(set(deck.side)):
            if assets.rows[incoming]["type"] & EXTRA_TYPES:
                excluded.append(dict(card=incoming, zone="side", reason="needs_extra_preparation"))
                continue
            outgoing = next((card for card in deck.main if card != incoming), None)
            if outgoing is None:
                continue
            swaps = [dict(zone="main", incoming=incoming, outgoing=outgoing)]
            active = _side_inventory(deck, swaps)
            queries, skipped = _main_queries(active, assets, subject=incoming)
            planned.extend(dict(query, side_swaps=swaps) for query in queries)
            excluded.extend(dict(item, zone="side") for item in skipped)
    return sorted(planned, key=lambda q: (q["priority"], q["card"], q["setup"])), excluded


def _response_registrations(script, event, *, prepare_set):
    if prepare_set:
        activations = {tuple(r["registration_span"]) for r in script["registrations"] if r.get("type") == 16}
    else:
        activations = {tuple(r["registration_span"]) for r in script["registrations"] if (r.get("range") or 0) & 2}
    return [r for r in _registration_choices(script, "response", response_event=event)
            if tuple(r["span"]) in activations]


def _effect_projection(query, records):
    effects = []
    for root in records.get(query["card"], ()):
        selections = root["operations"] if query["setup"] == "response" and root.get("branch_records") else [None]
        scopes = {}
        for operation in selections:
            scopes.setdefault((operation or {}).get("choice"), operation_record(root, operation) if operation else root)
        for record in scopes.values():
            projected = _project_operations(query, record)
            if projected:
                effects.append(projected)
    return dict(query, effects=effects, wanted=[e["key"] for e in effects])


def _project_operations(query, record):
    ops = _deck_operations(record)
    if query["setup"] in ("field_after_summons", "normal_summon"):
        ops += [op for op in record["operations"] if op["kind"] in ("destroy", "special_summon")]
    ops += [op for op in record["operations"] if op.get("phase") != "delayed" and (
        op["kind"] == "special_summon" and op.get("from_zones") == ["extra"]
        or op["kind"] == "fusion_summon" and op.get("summon_method") == "effect"
        and op.get("materials_required") is False
        or query["setup"] == "response" and op["kind"] in ("negate", "negate_summon", "destroy"))]
    if not ops:
        return None
    source = record.get("lua_source", {})
    matched = source.get("registrations", []) if source.get("alignment") == "matched" else []
    return dict(key=record["effect_key"], trigger=record["trigger"].get("event"),
        scopes=record["scope"], zone=record["trigger"].get("zone"),
        spans=[reg["registration_span"] for reg in matched] or (
            source.get("candidate_spans", []) if query["setup"] == "response" else []),
        operations=[dict(block=op["block_id"], kind=op["kind"], origin=op.get("from_zones", []),
            destination=op.get("to_zone"), quantity=op.get("quantity"),
            selector=op.get("selector_query"), negation=op.get("negation"), choice=op.get("choice"))
            for op in ops])


def bind_observations(observed, records, rows, *, lua=None):
    """Project an already executed window to any uniquely corresponding stock uses."""
    for receipt in observed["receipts"]:
        query = _effect_projection(receipt["query"], records)
        identity = _bind_movement(query, receipt["moves"], rows)
        if receipt["field_moves"]:
            identity = _bind_processing(query, receipt["field_moves"], rows)
        receipt["identity"] = identity
        receipt["rule_status"] = ("bound" if identity.get("status") == "bound" and receipt.get("stock_prefix")
            else "unbound_stock_prefix" if identity.get("status") == "bound"
            else "resolved_use_unbound" if receipt.get("activation_event") and receipt.get("resolved")
            else receipt["status"])
        if receipt["rule_status"] == "bound":
            receipt.update(witnessed_rule(receipt))
    if lua is not None:
        responses = []
        for code, effects in records.items():
            script_code, _ = native_card_identity(rows, code)
            for registration in lua.summarize_effects(script_code)["registrations"]:
                if registration.get("event_code") != 1027:  # EVENT_CHAINING
                    continue
                location = registration.get("range")
                prior = ("prepare_response_entity_in_monster_zone" if location == 4 else
                         "prepare_response_entity_in_grave" if location == 16 else
                         "prepare_legal_set_or_faceup_card_activation" if registration.get("type") == 16 else None)
                candidates = [r for r in effects if registration["registration_span"] in (
                    r.get("lua_source", {}).get("candidate_spans", []) + [r["registration_span"] for r in
                    r.get("lua_source", {}).get("registrations", [])])]
                responses.append(dict(card=code, registration=registration["registration_span"],
                    effects=[r["effect_key"] for r in candidates],
                    prerequisites=[p for p in (prior, "eligible_effect_in_open_chain") if p],
                    observed=[dict(receipt=r["receipt"], status=r["rule_status"]) for r in observed["receipts"]
                              if r["query"]["card"] == code and r["query"]["setup"] == "response"]))
        observed["response_windows"] = responses
    return observed


def _visible(request):
    cards = {card.ref: card.card_id for card in request.observation.cards}
    for option in (*request.selection_choices, *request.search_choices):
        if option.card_id is not None:
            cards[option.ref] = option.card_id
    return cards


def _menu(request):
    known = _visible(request)
    return [dict(action_id=action.action_id, kind=action.kind, cards=[known.get(ref) for ref in action.card_refs],
                 refs=list(action.card_refs), value=action.value,
                 description=action.details.description if action.details else None)
            for action in request.actions]


def _deck_refs(request, seat):
    refs = {c.ref for c in request.search_choices if c.owner == seat and c.scope == "search"}
    refs.update(c.ref for c in request.selection_choices
                if c.controller == seat and c.zone == "deck" and c.card_id is not None)
    return refs


def _choice_tokens(menu, message, deck_refs, *, activation=False):
    tokens = {}
    for row in menu:
        item = row["action_id"]
        if activation:
            tokens[item] = ["activate", row["description"]]
        elif message in (13, 14):
            tokens[item] = [row["kind"], row["value"]]
        elif message == 15 and row["kind"] == "select":
            objects = row["cards"] if row["refs"] and set(row["refs"]) <= deck_refs else row["refs"]
            tokens[item] = [row["kind"], sorted(objects)]
    # Physical copies with equal card codes are equivalent for this directed one-card query.
    return tokens if len({digest(token) for token in tokens.values()}) > 1 else {}


def _resolved_chain(events, query, offered_description):
    candidates = [link for link in chain_links(events) if link["activation"]["public_card"] == query["card"]
                  and link["activation"]["player"] == query["seat"] and (offered_description is None
                  or link["activation"]["description"] == offered_description)]
    if len(candidates) != 1 or not candidates[0]["resolved"]:
        return None, []
    link, = candidates
    return link["activation"], events[link["solving"] + 1:link["solved"]]


def _resolved_deck_moves(events, selections, own_hand_gains, query, offered_description):
    """Require the selected effect's actual resolving link and selected Deck entity."""
    activation, resolved = _resolved_chain(events, query, offered_description)
    if activation is None:
        return []
    moves = []
    for event in resolved:
        dest = _DECK_DESTINATIONS.get(event.get("to_zone"))
        if (event["kind"] != 50 or event.get("from_zone") != 1 or dest not in query["destinations"]
                or event.get("player") != query["seat"] or event.get("reason", 0) & 0xc0 != 0x40):
            continue
        code = event.get("public_card")
        if code is None and dest == "hand" and len(selections) == 1:
            chosen, = selections
            if chosen in own_hand_gains:
                code = chosen
        if code in selections:
            moves.append(dict(card=code, origin="deck", destination=dest, reason="effect",
                              link=activation["link"], activation=activation))
    return moves


def _field_moves(activation, resolved, selected, seat):
    if activation is None:
        return []
    result = []
    for position, event in enumerate(resolved):
        if event["kind"] != 50 or event.get("player") != seat:
            continue
        card = event.get("public_card")
        reason = event.get("reason", 0)
        route = (event.get("from_zone"), event.get("to_zone"))
        if route == (4, 16) and reason & 0xc1 == 0x41 and ("monster", card) in selected:
            result.append(dict(card=card, kind="destroy", origin="field", destination="grave",
                               reason="effect", activation=activation))
        announcement = next((i for i in range(position + 1, len(resolved)) if resolved[i]["kind"] == 62
                             and resolved[i].get("player") == seat
                             and resolved[i].get("public_summoning_card") == card), None)
        origin = {16: ("graveyard", "grave"), 64: ("extra", "extra")}.get(route[0])
        if (origin and route[1] == 4 and reason & 0x800 and (origin[0], card) in selected
                and announcement is not None and any(e["kind"] == 63 for e in resolved[announcement + 1:])):
            result.append(dict(card=card, kind="special_summon", origin=origin[1], destination="field",
                               reason="effect", activation=activation))
    return result


def _bind_movement(query, moves, rows):
    """Disambiguate the printed use by the source registration and the observed branch."""
    if len(moves) != 1:
        return dict(status="movement_unmatched")
    move, = moves
    description = move["activation"].get("description")
    registrations = [r for r in query["registrations"] if r["description"] == description]
    if len({r["family"] for r in registrations}) != 1:
        return dict(status="registration_ambiguous", candidates=registrations)
    events = {r["event"] for r in registrations}
    if "normal_summon" in events:
        events.add("normal_or_special_summon")
    spans = [r["span"] for r in registrations]
    candidates = []
    for effect in query["effects"]:
        if effect["spans"] and not any(span in spans for span in effect["spans"]):
            continue
        if effect["trigger"] not in events | {None, "unknown"}:
            continue
        if query["setup"] == "spell":
            if effect["scopes"] != "spell_trap":
                continue
        elif effect["scopes"] != "monster" or effect["zone"] not in (
                None, "hand" if query["setup"] == "hand" else "field"):
            continue
        for operation in effect["operations"]:
            if "deck" in operation.get("origin", ["deck"]) and operation["destination"] == move["destination"] and (
                    not operation["selector"] or matches(rows[move["card"]], operation["selector"])):
                candidates.append((effect["key"], operation["block"]))
    if len(candidates) != 1 or candidates[0][0] not in query["wanted"]:
        return dict(status="printed_use_ambiguous", candidates=candidates, source=registrations)
    effect, block = candidates[0]
    return dict(status="bound", effect_key=effect, block=block, source=registrations)


def _bind_processing(query, moves, rows):
    description = moves[0]["activation"]["description"]
    registrations = [r for r in query["registrations"] if r["description"] == description]
    if len({r["family"] for r in registrations}) != 1:
        return dict(status="registration_ambiguous")
    events = {r["event"] for r in registrations} | {None, "unknown"}
    if query["setup"] == "response":
        events |= {"opponent_monster_effect", "card_activation"}
        target = moves[0].get("response")
        if target and target["zone"] in (8, 256) and rows[target["public_card"]]["type"] & (2 | 4):
            events.add("spell_trap_activation")
    candidates = []
    for effect in query["effects"]:
        if effect["trigger"] not in events or (query["setup"] == "spell" and effect["scopes"] != "spell_trap"):
            continue
        zone = {2: "hand", 4: "field", 8: "field", 16: "grave"}.get(moves[0]["activation"]["zone"])
        if effect["zone"] not in (None, zone):
            continue
        if effect["trigger"] == "opponent_monster_effect":
            response = moves[0].get("response")
            if not response or response["zone"] in (8, 256) or not rows[response["public_card"]]["type"] & 1:
                continue
        if effect["spans"] and not any(r["span"] in effect["spans"] for r in registrations):
            continue
        parts = []
        for move in moves:
            choices = [operation["block"] for operation in effect["operations"]
                       if (operation["kind"] == move["kind"] or operation["kind"] == "fusion_summon"
                           and move["kind"] == "special_summon" and move["origin"] == "extra")
                       and (operation["quantity"] == 1 or move.get("response") and operation["quantity"] is None)
                       and (move["origin"] in operation["origin"] or move.get("response") and not operation["origin"])
                       and (operation["destination"] in (None, move["destination"])
                            or move["kind"] == "negate_summon" and operation["destination"] == "field")
                       and operation["negation"] in (None, move.get("negation"))
                       and (not operation["selector"] or matches(rows[move["card"]], operation["selector"]))]
            if len(choices) == 1:
                parts.extend(choices)
        branches = {operation["choice"] for operation in effect["operations"] if operation["block"] in parts}
        if len(parts) == len(set(parts)) == len(moves) and len(branches - {None}) <= 1:
            candidates.append((effect["key"], parts))
    if len(candidates) != 1:
        return dict(status="printed_use_ambiguous", candidates=candidates, source=registrations)
    effect, blocks = candidates[0]
    return dict(status="bound", effect_key=effect, blocks=blocks, source=registrations)


def _response_moves(link, resolved):
    source = link["activation"]
    target = link["response_to"]
    if not target or target["player"] == source["player"]:
        return []
    negations = [e for e in resolved if e["kind"] in (75, 76) and e.get("link") == target["link"]]
    if len(negations) != 1:
        return []
    moves = [dict(card=target["public_card"], kind="negate", origin="chain", destination=None,
                  reason="effect", activation=source, response=target,
                  negation="activation" if negations[0]["kind"] == 75 else "effect")]
    destroyed = [e for e in resolved if e["kind"] == 50 and e.get("public_card") == target["public_card"]
                 and e.get("player") == target["player"] and e["from_zone"] == target["zone"]
                 and e["to_zone"] == 16 and e.get("reason", 0) & 0xc1 == 0x41]
    if len(destroyed) == 1:
        moves.append(dict(card=target["public_card"], kind="destroy", origin="field" if target["zone"] in (4, 8)
                          else "hand" if target["zone"] == 2 else "grave" if target["zone"] == 16 else "chain",
                          destination="grave", reason="effect", activation=source, response=target))
    return moves


def _summon_response_moves(link, events, query):
    source = link["activation"]
    message = query["response_to"]["summon_message"]
    registrations = [r for r in query["registrations"] if r["description"] == source["description"]]
    attempts = pending_summons(events[:link["opened"]])
    if (link["response_to"] or len(registrations) != 1 or not registrations[0].get("direct_summon_negation")
            or len(attempts) != 1):
        return []
    attempt, = attempts
    card = attempt.get("public_summoning_card")
    if (card is None or attempt["kind"] != message or attempt["player"] == source["player"]
            or any(e["kind"] == message + 1 for e in events[link["opened"]:])):
        return []
    common = dict(card=card, reason="effect", origin="field", activation=source,
                  response=dict(attempt, public_card=card), summon_attempt=attempt)
    moves = [dict(common, kind="negate_summon", destination=None)]
    resolution = events[link["solving"] + 1:link["solved"]]
    destroyed = [e for e in resolution if e["kind"] == 50 and e.get("public_card") == card
                 and e.get("player") == attempt["player"] and e["from_zone"] == 4
                 and e["to_zone"] == 16 and e.get("reason", 0) & 0xc1 == 0x41]
    if len(destroyed) == 1 and registrations[0]["direct_summon_negation"]["attempts_destroy"]:
        moves.append(dict(common, kind="destroy", destination="grave"))
    return moves


def run_window(assets, deck, query, *, selection_key, decision_budget, should_stop=None, counters=None):
    """Replay a deterministic legal prefix and collect each distinct offered alternative."""
    active_deck = _side_inventory(deck, query.get("side_swaps"))
    lua = getattr(assets, "effect_lua_source", None)
    if lua is not None:
        missing = [script for code in sorted(set(active_deck.main + active_deck.extra))
                   if (script := lua.missing_required_card_script(assets.rows, code)) is not None]
        if missing:
            return dict(status="missing_rule_source", missing_scripts=missing, decisions=0)
    setup = deque(query["summons"])
    trace, selections, path, alternatives = [], set(), [], []
    selected = set()
    prepared_moves = []
    preparations = bool(query.get("prelude"))
    preparing = False
    field_window = query["setup"] == "field_after_summons"
    activation = event_start = None
    before_hand, own_hand_gains = Counter(), set()
    status = "decision_budget"
    seat, subject = query["seat"], query["card"]
    response_source = query.get("response_to")
    summon_message = (response_source or {}).get("summon_message")
    response_started = response_seen = False
    waiting_to_set = query.get("prepare_set", False)
    source_summoned = False
    public = {code: {"type": row["type"], "attack": row.get("atk", 0)} for code, row in assets.rows.items()}
    with engine_for_goal(assets, active_deck, query["seed"], selection_key=selection_key,
                         cb_opening_hand=tuple(query["opening"])) as engine:
        if counters is not None:
            counters["sessions"] += 1
        request = engine.next_decision()
        for _ in range(decision_budget):
            if should_stop is not None and should_stop():
                status = "paused"
                break
            if request is None:
                status = "ended"
                break
            msg = request.prompt.message
            own = request.observation.observer == seat
            known, menu = _visible(request), _menu(request)
            own_cards = {c.ref: c for c in request.observation.cards if c.controller == seat}
            hand = Counter(c.card_id for c in own_cards.values() if c.zone == "hand" and c.card_id)
            if own and event_start is not None:
                own_hand_gains.update((hand - before_hand).keys())
            if event_start is not None and msg in (10, 11):
                if not preparing:
                    status = "settled"
                    break
                prepared_moves = _resolved_deck_moves(engine.events[event_start:], selections,
                                                       own_hand_gains, query, None)
                if not any(move["destination"] == "grave" for move in prepared_moves):
                    status = "preparation_unmatched"
                    break
                preparing = preparations = False
                activation = event_start = None
                selections.clear()
                selected.clear()
                own_hand_gains.clear()
            early = preparations and len(setup) == 1 and msg in (12, 16)
            if response_source:
                reply_open = False
                if own and msg == 16 and response_started:
                    if summon_message:
                        attempts = pending_summons(engine.events)
                        reply_open = bool(attempts) and all(e["kind"] == summon_message and e["player"] != seat
                                                            for e in attempts)
                    else:
                        boundary = max((i for i, e in enumerate(engine.events) if e["kind"] == 74), default=-1)
                        chain = [e for e in engine.events[boundary + 1:] if e["kind"] == 70]
                        reply_open = bool(chain) and chain[-1]["player"] != seat and (
                            response_source.get("any_opponent_activation") or chain[-1]["public_card"] == response_source["card"])
                response_seen = response_seen or reply_open
                if response_started and msg in (10, 11) and event_start is None:
                    status = "response_not_offered" if response_seen else "response_precondition_unreached"
                    break
            active = own and event_start is None and (reply_open if response_source else
                early or not setup and (not field_window or msg == 11))
            actor_zone = ("spell_trap" if query.get("prepare_set") else "monster"
                          if query["setup"] in ("normal_summon", "field_after_summons") else "hand")
            offers = [item for item in menu if active and item["kind"] in ("activate", "yes") and
                      any(ref in own_cards and own_cards[ref].zone == actor_zone and known.get(ref) == subject
                          for ref in item["refs"])]
            descriptions = {r["description"] for r in query["registrations"] if r["description"] is not None}
            offers.sort(key=lambda item: item["description"] not in descriptions)
            if active and not offers and msg == 11:
                activation = dict(turn=request.observation.turn, phase=request.observation.phase, menu=menu)
                status = "not_offered"
                break

            refs = _deck_refs(request, seat) if own else set()
            tokens = (_choice_tokens(offers, msg, refs, activation=True) if offers else
                      _choice_tokens(menu, msg, refs) if event_start is not None else {})
            default = offers[0]["action_id"] if offers else None
            if response_source and not own and not response_started and not waiting_to_set:
                if response_source.get("any_opponent_activation") or summon_message:
                    kind = {60: "summon", 62: "special_summon", 64: "position"}.get(summon_message, "activate")
                    choices = [item for item in menu if msg == 11 and item["kind"] == kind
                               and any(card is not None for card in item["cards"])]
                    if summon_message == 64:
                        facedown = {c.ref for c in request.observation.cards
                                    if c.zone == "monster" and c.position is not None and c.position & 10}
                        choices = [item for item in choices if any(ref in facedown for ref in item["refs"])]
                        if not choices and not source_summoned and msg == 11:
                            choices = [item for item in menu if item["kind"] == "set"
                                       and any(c in public and public[c]["type"] & 1 for c in item["cards"])]
                    # The preceding choice is part of the proof, independently
                    # of the response card's own activation and option choices.
                    if choices:
                        entry = choices[0]
                        tokens = {a["action_id"]: [
                            "opponent:" + a["kind"] if summon_message else "opponent_activation",
                            a["description"], a["cards"]] for a in choices}
                    else:
                        entry = None
                else:
                    source = response_source["card"]
                    kinds = ("summon",) if response_source.get("summon") and not source_summoned else ("activate", "yes")
                    entry = next((item for item in menu if item["kind"] in kinds and source in item["cards"]), None)
                if entry:
                    default = entry["action_id"]
                    source_summoned = source_summoned or entry["kind"] in ("summon", "set")
                    response_started = entry["kind"] != "set" and (bool(summon_message) or entry["kind"] != "summon")
                elif not summon_message and source_summoned and msg == 11:
                    status = "response_precondition_unreached"
                    break
            preferred = query.get("preferred_selection")
            if own and event_start is not None and preferred is not None and default is None:
                default = next((item["action_id"] for item in menu if item["kind"] == "select"
                               and preferred in item["cards"]), None)
            if tokens:
                depth = len(path)
                choice = query["path"][depth] if depth < len(query["path"]) else None
                if choice is not None:
                    default = next((action_id for action_id, token in tokens.items() if token == choice), None)
                    if default is None:
                        status = "branch_unavailable"
                        break
                default = default if default in tokens else next(iter(tokens))
                selected_token = tokens[default]
                if depth >= len(query["path"]):
                    distinct = {digest(token): token for token in tokens.values()}
                    alternatives.extend(dict(path=[*path, token], prompt=msg)
                                        for token in distinct.values() if token != selected_token)
                path.append(selected_token)
            if default is None:
                if own and msg == 11 and setup:
                    default = next((item["action_id"] for item in menu
                                    if item["kind"] == "summon" and setup[0] in item["cards"]), None)
                    if default is not None:
                        setup.popleft()
                if default is None and own and msg == 11 and waiting_to_set:
                    setting = next((item for item in menu if item["kind"] == "set"
                                    and subject in item["cards"]), None)
                    if setting is None:
                        status = "set_preparation_not_offered"
                        break
                    default, waiting_to_set = setting["action_id"], False
                if default is None and msg in (10, 11, 12, 13, 16):
                    defaults = [item["action_id"] for item in menu if item["kind"] in ("pass", "no")]
                    default = defaults[-1] if defaults else None
            action_id = default if default is not None else choose_effect_duel_action(request, public).action_id
            chosen = next(item for item in menu if item["action_id"] == action_id)
            if offers:
                if sum(item["description"] == chosen["description"] and item["refs"] == chosen["refs"]
                       for item in offers) != 1:
                    status = "activation_ambiguous"
                    activation = dict(turn=request.observation.turn, phase=request.observation.phase, menu=menu)
                    break
                before_hand = hand
                activation = dict(turn=request.observation.turn, phase=request.observation.phase,
                                  prompt=msg, menu=menu, selection=chosen)
                event_start = len(engine.events)
                preparing = early
            if own and event_start is not None and chosen["kind"] == "select":
                selections.update(code for ref, code in zip(chosen["refs"], chosen["cards"])
                                  if ref in refs and code is not None)
                selected.update((own_cards[ref].zone, known[ref]) for ref in chosen["refs"]
                                if ref in own_cards and known.get(ref) is not None)
            trace.append(dict(request=request_digest(request), seat=request.observation.observer,
                              turn=request.observation.turn, phase=request.observation.phase,
                              prompt=msg, menu=menu, selection=action_id))
            engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action_id))
            if counters is not None:
                counters["submitted_decisions"] += 1
            request = engine.next_decision()
        events = list(engine.events)
        metadata = dict(period=engine.period_context, scripts=sorted(engine.loaded_scripts))
        if hasattr(engine, "_catalog_assets"):
            metadata["native_code_projection"] = digest(engine._catalog_assets.native_code_overrides)
    if status == "settled" and len(path) < len(query["path"]):
        status = "branch_unavailable"
    action_events = events[event_start:] if event_start is not None and status == "settled" else []
    # The pinned core can offer its generic confirmation string here.
    # MSG_CHAINING carries the native effect identity after acceptance.
    description = (activation or {}).get("selection", {}).get("description") if (
        activation and activation.get("prompt") != 12
    ) else None
    moves = _resolved_deck_moves(action_events, selections, own_hand_gains, query, description)
    activation_event, resolved_events = _resolved_chain(action_events, query, description)
    field_moves = _field_moves(activation_event, resolved_events, selected, seat)
    if field_window and activation_event is not None:
        handler_refs = activation["selection"]["refs"]
        expected = f"p{seat}.monster.{activation_event['slot']}"
        if expected not in handler_refs:
            field_moves = []
    payments = [e for e in action_events if e["kind"] == 100 or e["kind"] == 50 and e.get("reason", 0) & 0x80]
    missing = None
    if response_source and event_start is None:
        missing = ("matching_chain_response_not_offered" if response_seen else
                   "opposing_effect_must_activate_before_response")
    return dict(status=status, offered=event_start is not None, window=activation, trace=trace, events=events,
                moves=moves, payments=payments, field_moves=field_moves, prepared_moves=prepared_moves,
                activation_event=activation_event, resolution=resolved_events,
                selected_deck_cards=sorted(selections), selected_objects=sorted(selected), decisions=len(trace),
                alternatives=alternatives, path=path, unmet_precondition=missing,
                identity=_bind_movement(query, moves, assets.rows) if "effects" in query else {},
                **metadata)


class NativeRuleChecks:
    """Run a bounded frontier of legal windows for one task and physical stock."""

    def __init__(self, assets):
        self.assets = assets
        self.directory = assets.workspace / "construction-native-rules"
        self.counts = Counter()
        self.attempts = []
        self.inventories = []
        self.frontiers = {}
        self.admission = {}

    def load_frontier(self, report):
        """Read a prior report as a query agenda. Facts come only from raw replays."""
        if not isinstance(report, dict) or report.get("version") != NATIVE_RULE_VERSION:
            raise ContractError("native query frontier version differs")
        entries = report.get("inventories")
        if not isinstance(entries, list):
            raise ContractError("native query frontier requires inventory reports")
        for row in entries:
            if (not isinstance(row, dict) or row.get("role") not in ("candidate", "reference")
                    or not isinstance(row.get("status"), str)
                    or any(not isinstance(row.get(k), str) for k in ("task", "deck"))
                    or any(not isinstance(row.get(k), list) for k in ("receipts", "pending", "exhausted_receipts"))):
                raise ContractError("native query frontier has an invalid inventory report")
            key = (row["task"], row["deck"], row["role"], row.get("policy"))
            if row["status"] != "paused" or key not in self.frontiers:
                self.frontiers[key] = deepcopy(row), digest(row)

    def _frontier(self, task_sha, deck_sha, role, policy_sha):
        key = (task_sha, deck_sha, role)
        return self.frontiers.get((*key, policy_sha), self.frontiers.get((*key, None), (None, None)))

    def frontier_binding(self, task, deck, role, policy):
        _, entry = self._frontier(task.sha256, digest(deck.to_dict()), role, digest(policy))
        return entry

    def record_quality(self, quality, role):
        key = (quality["task_sha256"], quality["deck_sha256"], role, quality["policy_sha256"])
        previous = self.admission.get(key)
        if previous is None or previous["evaluation"] != quality["evaluation_id"]:
            self.admission[key] = dict(evaluation=quality["evaluation_id"], policy=quality["policy_sha256"],
                                       effects=admission_effects(quality), comparisons={})

    def record_comparison(self, candidate, reference, bounds):
        for role, quality, peer in (("candidate", candidate, reference), ("reference", reference, candidate)):
            self.record_quality(quality, role)
            key = (quality["task_sha256"], quality["deck_sha256"], role, quality["policy_sha256"])
            self.admission[key]["comparisons"][peer["deck_sha256"]] = dict(
                delta=bounds, ratio=bounds["ratio"])

    def _read_receipt(self, key, binding):
        if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            return None
        for suffix in (".json", ".engine_error.json"):
            path = self.directory / (key + suffix)
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(saved, dict) or saved.get("id") != key:
                continue
            saved_binding, result = saved.get("binding"), saved.get("result")
            if (isinstance(saved_binding, dict) and digest(saved_binding) == key
                    and all(saved_binding.get(k) == v for k, v in binding.items())
                    and isinstance(saved_binding.get("query"), dict) and isinstance(result, dict)
                    and type(saved_binding.get("decision_limit")) is int
                    and type(result.get("decisions")) is int
                    and 0 <= result["decisions"] <= saved_binding["decision_limit"]
                    and isinstance(result.get("status"), str)):
                return saved
        return None

    def _binding(self, task, deck):
        inventory = deck.to_dict()
        binding = dict(version=NATIVE_RULE_VERSION, task=task.sha256, deck=inventory,
                       resources=self.assets.receipt, period=self.assets.period_context, adapter=self.assets.adapter_revision)
        if projection := self._inventory_code_projection(inventory):
            binding["native_code_projection"] = projection
        return binding

    def _inventory_code_projection(self, inventory):
        overrides = getattr(self.assets, "native_code_overrides", {})
        if not overrides:
            return None
        codes = {c for section in inventory.values() for c in section}
        projected = {c: overrides[c] for c in sorted(codes & overrides.keys())}
        return digest(projected) if projected else None

    def _current_card_sources(self, result):
        overrides = getattr(self.assets, "native_code_overrides", {})
        if not overrides:
            return True
        if "native_code_projection" in result:
            return result["native_code_projection"] == digest(overrides)
        # Old raw replays may also have introduced a rule-name card during
        # processing, even when it was absent from both starting decks.
        former_scripts = {f"c{self.assets.rows[c]['alias']}.lua" for c in overrides}
        return not former_scripts.intersection(result.get("scripts", ()))

    def _initial_work(self, task, deck, role, previous, queries, *, include_side):
        if previous is None:
            initial, excluded = planned_queries(deck, self.assets, include_side=include_side) if queries is None else (list(queries), [])
            return dict(initial=initial, excluded=excluded, queue=list(initial),
                        seen=sorted({digest(q) for q in initial}), receipts=[], history=[])
        binding = self._binding(task, deck)
        queue, seen, receipts, history = {}, set(), [], []
        for key in dict.fromkeys((*previous["receipts"], *previous["exhausted_receipts"])):
            raw = self._read_receipt(key, binding)
            if raw is None:
                raise ContractError("native query frontier replay is missing or belongs to different inputs: " + str(key))
            row = self._evidence(raw)
            if not include_side and row["query"].get("side_swaps"):
                continue
            identity = digest(row["query"])
            seen.add(identity)
            if not self._current_card_sources(raw["result"]):
                queue[identity] = row["query"]
                continue
            history.append(key)
            self.counts["frontier_reads"] += 1
            self.counts["frontier_replayed_decisions"] += row["decisions"]
            self.attempts.append(dict(role=role, receipt=key, acquisition="frontier", status=row["status"],
                                      decisions=row["decisions"]))
            if row["status"] in ("decision_budget", "engine_error"):
                queue[identity] = row["query"]
            else:
                receipts.append(row)
        for query in [*(item["query"] for item in previous["pending"]), *previous.get("additional_windows", ())]:
            if not include_side and query.get("side_swaps"):
                continue
            identity = digest(query)
            if identity not in seen:
                queue[identity] = query
            seen.add(identity)
        excluded = previous.get("excluded", [])
        if getattr(self.assets, "effect_lua_source", None) is not None:
            planned, current_excluded = planned_queries(deck, self.assets, include_side=include_side)
            prepared = [q for q in planned if q["setup"] == "response" or q.get("side_swaps")]
            for query in prepared:
                identity = digest(query)
                if identity not in seen:
                    queue[identity] = query
                    seen.add(identity)
            prepared_cards = {q["card"] for q in prepared if not q.get("side_swaps")}
            excluded = [row for row in excluded if row["card"] not in prepared_cards and row.get("zone") != "side"]
            excluded.extend(row for row in current_excluded if row.get("zone") == "side")
        initial = [*(r["query"] for r in receipts), *queue.values()]
        return dict(initial=initial, excluded=excluded, queue=list(queue.values()),
                    seen=sorted(seen), receipts=receipts, history=history)

    def evaluate(self, task, deck, *, role, should_stop=None, queries=None, policy=None, continuation=None):
        deck_sha = digest(deck.to_dict())
        policy_sha = digest(policy) if policy is not None else None
        previous, frontier = self._frontier(task.sha256, deck_sha, role, policy_sha)
        projection = self._inventory_code_projection(deck.to_dict())
        if previous is not None and previous.get("native_code_projection") != projection:
            previous = frontier = None
        if queries is not None:
            previous = frontier = None
        required_scope = (policy or {}).get("quality", {}).get("required_scope")
        include_side = required_scope is None or "side" in required_scope
        admission = (previous or {}).get("admission") or {}
        if admission.get("policy") != policy_sha:
            admission = {}
        work_binding = digest((NATIVE_EVIDENCE_VERSION, task.sha256, deck_sha, role, policy_sha, frontier, queries,
                               getattr(self.assets, "period_context", None), getattr(self.assets, "receipt", None),
                               getattr(self.assets, "adapter_revision", None)))
        if continuation is not None:
            if (continuation.get("version") != _QUERY_WORK_VERSION
                    or continuation.get("binding") != work_binding):
                raise ContractError("native query continuation belongs to different inputs")
            work = deepcopy(continuation)
        else:
            work = self._initial_work(task, deck, role, previous, queries, include_side=include_side)
            work.update(version=_QUERY_WORK_VERSION, binding=work_binding, decisions=0)
        receipts, charged, seen = work["receipts"], work["decisions"], set(work["seen"])
        priority = lambda q: window_priority(q, admission, role)
        queue = deque(sorted(work["queue"], key=priority) if previous is not None else work["queue"])
        status = "complete"
        while queue:
            if should_stop is not None and should_stop():
                status = "paused"
                break
            if charged >= _DECISION_BUDGET:
                status = "decision_budget"
                break
            query = queue.popleft()
            attempt_start = len(self.attempts)
            row = self._ask(task, deck, query, role, _DECISION_BUDGET - charged, should_stop)
            if admission and len(self.attempts) > attempt_start:
                self.attempts[-1]["admission_priority"] = list(priority(query))
            charged += row["decisions"]
            if row["status"] == "paused":
                queue.appendleft(query)
                status = "paused"
                break
            receipts.append(row)
            branches = [dict(query, path=alternative["path"], priority=0 if alternative.get("prompt") == 14
                             else query.get("priority", 0) + 1) for alternative in row["alternatives"]]
            if query.get("field_followup") and any(move["destination"] == "grave" for move in row["moves"]):
                card = query["card"]
                branches.append(dict(query, setup="field_after_summons", opening=[card, card],
                    summons=[card, card], prelude=True, path=row["path"], field_followup=[],
                    registrations=query["field_followup"], priority=1))
            for branch in branches:
                key = digest(branch)
                if key not in seen:
                    seen.add(key)
                    queue.append(branch)
            queue = deque(sorted(queue, key=priority))
        pending = [dict(card=q["card"], wanted=q.get("wanted", []), setup=q["setup"], path=q["path"], query=q,
                        reason="native_decision_budget" if status == "decision_budget" else "construction_deadline")
                   for q in queue]
        exhausted = [row["receipt"] for row in receipts if row["status"] == "decision_budget"]
        engine_errors = [row["receipt"] for row in receipts if row["status"] == "engine_error"]
        missing_sources = [row["receipt"] for row in receipts if row["status"] == "missing_rule_source"]
        if status == "complete":
            status = ("decision_budget" if exhausted else "engine_error" if engine_errors else
                      "missing_rule_source" if missing_sources else status)
        initial = work["initial"]
        result = dict(status=status, eligible_cards=len({q["card"] for q in initial}), initial_windows=len(initial),
                      known_windows=len(seen), completed_windows=len(receipts), decisions=charged,
                      decision_budget=_DECISION_BUDGET, excluded=work["excluded"], pending=pending,
                      exhausted_receipts=exhausted, engine_error_receipts=engine_errors,
                      missing_source_receipts=missing_sources, receipts=receipts, frontier=frontier,
                      replayed_receipts=work["history"], admission_evaluation=admission.get("evaluation"))
        if status == "paused":
            work.update(queue=list(queue), seen=sorted(seen), decisions=charged)
            result["continuation"] = work
        self.inventories.append(dict(role=role, task=task.sha256, deck=deck_sha, policy=policy_sha,
                                     native_code_projection=projection,
                                     **{k: v for k, v in result.items() if k not in ("receipts", "continuation")},
                                     receipts=[r["receipt"] for r in receipts]))
        return result

    def _ask(self, task, deck, query, role, budget, should_stop):
        binding = dict(self._binding(task, deck), decision_limit=budget, query=query)
        key = digest(binding)
        path = self.directory / (key + ".json")
        self.counts["requests"] += 1
        cached = self._read_receipt(key, binding)
        if cached is not None and not self._current_card_sources(cached["result"]):
            binding["runtime_code_projection"] = digest(self.assets.native_code_overrides)
            key = digest(binding)
            path = self.directory / (key + ".json")
            cached = self._read_receipt(key, binding)
        if cached is not None and cached["result"]["status"] != "engine_error":
            result = cached["result"]
            self.counts["cache_hits"] += 1
            self.counts["cache_replayed_decisions"] += result["decisions"]
            self.attempts.append(dict(role=role, receipt=key, acquisition="cache", status=result["status"],
                                      decisions=result["decisions"]))
            return self._evidence(cached)
        start = perf_counter()
        selection_key = key[:32]
        self.counts["engine_attempts"] += 1
        previous = self.counts["submitted_decisions"]
        try:
            result = run_window(self.assets, deck, query, selection_key=selection_key, decision_budget=budget,
                                should_stop=should_stop, counters=self.counts)
        except (NativeError, ContractError, OSError) as error:
            result = dict(status="engine_error", error_type=type(error).__name__, error=str(error),
                          decisions=self.counts["submitted_decisions"] - previous)
            self.counts["engine_errors"] += 1
        self.attempts.append(dict(role=role, receipt=key, acquisition="engine", status=result["status"],
                                  decisions=result["decisions"], seconds=round(perf_counter() - start, 6)))
        row = dict(id=key, binding=binding, selection_key_audit_only=selection_key, result=result)
        status = result["status"]
        destination = path if status not in ("engine_error", "paused") else (
            self.directory / (key + "." + status + ".json")
        )
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(dir=self.directory, prefix="pending-") as scratch:
                staged = Path(scratch) / destination.name
                write_json(staged, row)
                staged.replace(destination)
        except OSError as error:
            self.counts["receipt_write_errors"] += 1
            self.attempts[-1]["artifact_error"] = str(error)
        return self._evidence(row)

    def report(self):
        inventories = []
        for row in self.inventories:
            admission = self.admission.get((row["task"], row["deck"], row["role"], row["policy"]))
            inventories.append(dict(row, admission=admission))
        return dict(version=NATIVE_RULE_VERSION, cache=str(self.directory), counts=dict(self.counts),
                    inventories=inventories, attempts=self.attempts)

    @staticmethod
    def _evidence(row):
        result, binding = row["result"], row["binding"]
        query = binding["query"]
        events = result.get("events", ())
        links = chain_links(events)
        steps = replay_steps(events, result.get("trace", ()))
        link = window_link(links, steps, query, result.get("window"))
        activation = link["activation"] if link else None
        payments = link["payments"] if link else []
        prepared = result.get("prepared_moves", [])
        field_moves, prefix = [], None
        resolved = bool(link and link["resolved"] and link["opened"] < link.get("chained", -1) < link["solving"])
        if resolved:
            resolution = events[link["solving"] + 1:link["solved"]]
            field_moves = _field_moves(activation, resolution, selected_objects(steps, link), query["seat"])
            if query.get("setup") == "field_after_summons":
                expected = f"p{query['seat']}.monster.{activation['slot']}"
                if expected not in result["window"]["selection"]["refs"]:
                    field_moves = []
            summon_response = query.get("setup") == "response" and query.get("response_to", {}).get("summon_message")
            if summon_response:
                field_moves = _summon_response_moves(link, events, query)
            elif query.get("setup") == "response":
                field_moves = _response_moves(link, resolution)
            chain_start = max((i for i in range(link["opened"]) if events[i]["kind"] == 74), default=-1)
            # The supported prefix carries either an isolated activation or
            # one explicitly requested answer to an opponent's open link.
            chain_size = sum(e["kind"] == 70 for e in events[chain_start + 1:link["solved"]])
            if chain_size == (2 if query.get("setup") == "response" and not summon_response else 1):
                prefix = stock_prefix(events, steps, link, query, prepared, payments)
        return dict(receipt=row["id"], status=result["status"], offered=result.get("offered"),
                    query=query, decisions=result["decisions"], moves=result.get("moves", []) if resolved else [],
                    field_moves=field_moves, prepared_moves=prepared, stock_prefix=prefix,
                    activation_event=activation, chain_links=links, resolved=resolved,
                    chain=link, path=result.get("path", []), payments=payments,
                    unmet_precondition=result.get("unmet_precondition"), alternatives=result.get("alternatives", []),
                    identity=result.get("identity", {}), error=result.get("error"),
                    **({"missing_scripts": result["missing_scripts"]} if "missing_scripts" in result else {}),
                    rule_resources=digest((binding.get("resources"), binding.get("period"), binding.get("adapter"))),
                    deck_sha256=digest(binding["deck"]))
