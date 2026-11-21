"""Execute scoped construction questions through the period core's legal decisions."""

from collections import Counter, deque
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from .build_contracts import digest
from .construction_checkpoint import write_json
from .construction_inventory import matches
from .contracts import ActionSelection
from .effect_duel import choose_effect_duel_action
from .extra_routes import engine_for_goal
from .native import NativeError
from .normal_duel import request_digest
from .validation import ContractError


NATIVE_RULE_VERSION = "construction-native-rules-v5"
_DECISION_BUDGET = 100
_DECK_DESTINATIONS = {2: "hand", 16: "grave"}
_OPERATIONS = frozenset(("search_or_recover", "search", "add_hand", "send_grave"))


def _deck_operations(record):
    return [op for op in record["operations"] if op["kind"] in _OPERATIONS
            and op.get("from_zones") == ["deck"] and op.get("to_zone") in _DECK_DESTINATIONS.values()
            and op.get("owner") == "self" and op.get("reason") == "effect"
            and op.get("quantity") == 1 and not op.get("random")]


def _registration_choices(script, setup):
    choices = []
    for reg in script["registrations"]:
        if not reg.get("operation"):
            continue
        location, event = reg.get("range"), reg.get("event")
        spell_activation = setup == "spell" and reg.get("type") == 16
        normal_trigger = setup == "normal_summon" and event == "normal_summon" and location in (None, 4)
        ignition = event == "own_main_phase" and location == {"hand": 2, "normal_summon": 4}.get(setup, -1)
        if not (spell_activation or normal_trigger or ignition):
            continue
        index = reg.get("description_index")
        description = script["script_card_id"] * 16 + index if index is not None else (
            None if "description_index" in reg else 0
        )
        choices.append(dict(description=description, family=reg["family"], span=reg["registration_span"],
                            event="card_activation" if spell_activation else event,
                            operation=reg["operation"]))
    return choices


def planned_queries(deck, assets):
    """Plan reachable starts using physical stock and registration metadata only."""
    planned, excluded = [], []
    lua = assets.effect_lua_source
    counts = Counter(deck.main)
    for code in sorted(counts):
        row = assets.rows[code]
        monster = bool(row["type"] & 1)
        can_normal = monster and 1 <= (row["level"] & 255) <= 4 and not row["type"] & 0x80
        setups = (["normal_summon"] if can_normal else []) + (
            ["hand"] if monster else ["spell"] if row["type"] & 2 else [])
        if not setups:
            excluded.append(dict(card=code, reason="needs_set_or_other_preparation"))
            continue
        script = lua.summarize_effects(row.get("alias") or code) if lua is not None else {"registrations": []}
        source = {key: script[key] for key in ("file", "sha256", "helpers") if key in script}
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
    return sorted(planned, key=lambda q: (q["priority"], q["card"], q["setup"])), excluded


def _effect_projection(query, records):
    effects = []
    for record in records.get(query["card"], ()):
        ops = _deck_operations(record)
        if query["setup"] in ("field_after_summons", "normal_summon"):
            ops += [op for op in record["operations"] if op["kind"] in ("destroy", "special_summon")]
        if not ops:
            continue
        source = record.get("lua_source", {})
        matched = source.get("registrations", []) if source.get("alignment") == "matched" else []
        effects.append(dict(key=record["effect_key"], trigger=record["trigger"].get("event"),
            scopes=record["scope"], zone=record["trigger"].get("zone"),
            spans=[reg["registration_span"] for reg in matched],
            operations=[dict(block=op["block_id"], kind=op["kind"], origin=op.get("from_zones", []),
                destination=op.get("to_zone"), quantity=op.get("quantity"),
                selector=op.get("selector_query")) for op in ops]))
    return dict(query, effects=effects, wanted=[e["key"] for e in effects])


def bind_observations(observed, records, rows):
    """Project an already executed window to any uniquely corresponding stock uses."""
    for receipt in observed["receipts"]:
        query = _effect_projection(receipt["query"], records)
        identity = _bind_movement(query, receipt["moves"], rows)
        if receipt["field_moves"]:
            identity = _bind_field_processing(query, receipt["field_moves"], rows)
        receipt["identity"] = identity
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
    activations = [e for e in events if e["kind"] == 70]
    if len(activations) != 1:
        return None, []
    activation, = activations
    link = activation.get("link")
    if (activation.get("public_card") != query["card"] or activation.get("player") != query["seat"]
            or offered_description is not None and activation.get("description") != offered_description
            or any(e["kind"] in (75, 76) and e.get("link") == link for e in events)):
        return None, []
    begins = [i for i, e in enumerate(events) if e["kind"] == 72 and e.get("link") == link]
    ends = [i for i, e in enumerate(events) if e["kind"] == 73 and e.get("link") == link]
    if len(begins) != 1 or len(ends) != 1 or begins[0] >= ends[0]:
        return None, []
    return activation, events[begins[0] + 1:ends[0]]


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
        if (route == (16, 4) and reason & 0x800 and ("graveyard", card) in selected
                and announcement is not None and any(e["kind"] == 63 for e in resolved[announcement + 1:])):
            result.append(dict(card=card, kind="special_summon", origin="grave", destination="field",
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


def _bind_field_processing(query, moves, rows):
    if [m["kind"] for m in moves] != ["destroy", "special_summon"]:
        return dict(status="movement_unmatched")
    description = moves[0]["activation"]["description"]
    registrations = [r for r in query["registrations"] if r["description"] == description
                     and r["event"] == "own_main_phase"]
    if len({r["family"] for r in registrations}) != 1:
        return dict(status="registration_ambiguous")
    candidates = []
    for effect in query["effects"]:
        if effect["trigger"] not in (None, "unknown", "own_main_phase") or effect["scopes"] != "monster":
            continue
        if effect["spans"] and not any(r["span"] in effect["spans"] for r in registrations):
            continue
        parts = []
        for move in moves:
            choices = [operation["block"] for operation in effect["operations"]
                       if operation["kind"] == move["kind"] and operation["quantity"] == 1
                       and move["origin"] in operation["origin"]
                       and operation["destination"] in (None, move["destination"])
                       and (not operation["selector"] or matches(rows[move["card"]], operation["selector"]))]
            parts.extend(choices if len(choices) == 1 else ())
        if len(parts) == len(moves):
            candidates.append((effect["key"], parts))
    if len(candidates) != 1:
        return dict(status="printed_use_ambiguous", candidates=candidates, source=registrations)
    effect, blocks = candidates[0]
    return dict(status="bound", effect_key=effect, blocks=blocks, source=registrations)


def run_window(assets, deck, query, *, selection_key, decision_budget, should_stop=None, counters=None):
    """Replay a deterministic legal prefix and collect each distinct offered alternative."""
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
    public = {code: {"type": row["type"], "attack": row.get("atk", 0)} for code, row in assets.rows.items()}
    with engine_for_goal(assets, deck, query["seed"], selection_key=selection_key,
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
            active = own and event_start is None and (
                early or not setup and (not field_window or msg == 11))
            actor_zone = "monster" if query["setup"] in ("normal_summon", "field_after_summons") else "hand"
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
    return dict(status=status, offered=event_start is not None, window=activation, trace=trace, events=events,
                moves=moves, payments=payments, field_moves=field_moves, prepared_moves=prepared_moves,
                activation_event=activation_event, resolution=resolved_events,
                selected_deck_cards=sorted(selections), selected_objects=sorted(selected), decisions=len(trace),
                alternatives=alternatives, path=path,
                identity=_bind_movement(query, moves, assets.rows) if "effects" in query else {},
                **metadata)


class NativeRuleChecks:
    """Budget legal windows together and reuse only identical task/stock/scope receipts."""

    def __init__(self, assets):
        self.assets = assets
        self.directory = assets.workspace / "construction-native-rules"
        self.counts = Counter()
        self.attempts = []
        self.inventories = []

    def evaluate(self, task, deck, *, role, should_stop=None, queries=None):
        initial, excluded = planned_queries(deck, self.assets) if queries is None else (queries, [])
        queue = deque(initial)
        seen = {digest(query) for query in initial}
        receipts, charged = [], 0
        status = "complete"
        while queue:
            if should_stop is not None and should_stop():
                status = "paused"
                break
            if charged >= _DECISION_BUDGET:
                status = "decision_budget"
                break
            query = queue.popleft()
            row = self._ask(task, deck, query, role, _DECISION_BUDGET - charged, should_stop)
            if row["status"] == "paused":
                queue.appendleft(query)
                status = "paused"
                break
            receipts.append(row)
            charged += row["decisions"]
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
            queue = deque(sorted(queue, key=lambda q: (q.get("priority", 0), q["card"])))
        pending = [dict(card=q["card"], wanted=q.get("wanted", []), setup=q["setup"], path=q["path"],
                        reason="native_decision_budget" if status == "decision_budget" else "construction_deadline")
                   for q in queue]
        exhausted = [row["receipt"] for row in receipts if row["status"] == "decision_budget"]
        if exhausted and status == "complete":
            status = "decision_budget"
        result = dict(status=status, eligible_cards=len({q["card"] for q in initial}),
                      initial_windows=len(initial), known_windows=len(seen), completed_windows=len(receipts),
                      decisions=charged, decision_budget=_DECISION_BUDGET, excluded=excluded,
                      pending=pending, exhausted_receipts=exhausted, receipts=receipts)
        self.inventories.append(dict(role=role, task=task.sha256, deck=digest(deck.to_dict()),
                                     **{k: v for k, v in result.items() if k != "receipts"},
                                     receipts=[r["receipt"] for r in receipts]))
        return result

    def _ask(self, task, deck, query, role, budget, should_stop):
        binding = dict(version=NATIVE_RULE_VERSION, task=task.sha256, deck=deck.to_dict(),
                       resources=self.assets.receipt, period=self.assets.period_context,
                       adapter=self.assets.adapter_revision, decision_limit=budget, query=query)
        key = digest(binding)
        path = self.directory / (key + ".json")
        self.counts["requests"] += 1
        if path.is_file():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cached = {}
            result = cached.get("result") if isinstance(cached, dict) else None
            if (isinstance(result, dict) and cached.get("binding") == binding and cached.get("id") == key
                    and isinstance(result.get("decisions"), int) and 0 <= result["decisions"] <= budget
                    and "status" in result):
                self.counts["cache_hits"] += 1
                self.attempts.append(dict(role=role, receipt=key, acquisition="cache", status=result["status"]))
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
        return dict(version=NATIVE_RULE_VERSION, cache=str(self.directory), counts=dict(self.counts),
                    inventories=self.inventories, attempts=self.attempts)

    @staticmethod
    def _evidence(row):
        result, binding = row["result"], row["binding"]
        query = binding["query"]
        activation = result.get("activation_event")
        field_moves = _field_moves(activation, result.get("resolution", []),
                                   {tuple(v) for v in result.get("selected_objects", [])}, query["seat"])
        if activation and query.get("setup") == "field_after_summons":
            expected = f"p{query['seat']}.monster.{activation['slot']}"
            if expected not in result["window"]["selection"]["refs"]:
                field_moves = []
        return dict(receipt=row["id"], status=result["status"], offered=result.get("offered"),
                    query=query, decisions=result["decisions"], moves=result.get("moves", []),
                    field_moves=field_moves, prepared_moves=result.get("prepared_moves", []),
                    activation_event=activation, path=result.get("path", []),
                    payments=result.get("payments", []), alternatives=result.get("alternatives", []),
                    identity=result.get("identity", {}), error=result.get("error"),
                    deck_sha256=digest(binding["deck"]))
