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


NATIVE_RULE_VERSION = "construction-native-rules-v4"
_DECISION_BUDGET = 100
_DECK_DESTINATIONS = {2: "hand", 16: "grave"}
_OPERATIONS = frozenset(("search_or_recover", "search", "add_hand", "send_grave"))
_SETUP_EVENTS = {
    "normal_summon": {"normal_summon", "normal_or_special_summon", "own_main_phase"},
    "hand": {"own_main_phase", "card_activation"},
}


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


def planned_queries(deck, records, assets):
    planned, excluded = [], []
    lua = assets.effect_lua_source
    for code, card_records in sorted(records.items()):
        effects = [(record, _deck_operations(record)) for record in card_records]
        unresolved = [(r, ops) for r, ops in effects if ops and
                      (r["conditions"]["status"] != "recognized" or any(not o.get("selector_query") for o in ops))]
        if not unresolved:
            continue
        row = assets.rows[code]
        setup_effects = {}
        for record, ops in unresolved:
            zone, event = (record["trigger"].get(key) for key in ("zone", "event"))
            setup = ("hand" if zone == "hand" else "normal_summon") if record["scope"] == "monster" else "spell"
            possible = (code in deck.main and (
                setup == "hand" and bool(row["type"] & 1) or
                setup == "normal_summon" and bool(row["type"] & 1) and 1 <= (row["level"] & 255) <= 4
                and zone in (None, "field") or
                setup == "spell" and record["scope"] == "spell_trap" and bool(row["type"] & 2)
                and zone in (None, "hand", "spell_trap")
            ))
            if not possible or (event not in (None, "unknown") and event not in
                                _SETUP_EVENTS.get(setup, {"card_activation", "own_main_phase"})):
                excluded.append(dict(card=code, effect_key=record["effect_key"],
                                     operations=[o["block_id"] for o in ops],
                                     reason="native_preparation_unsupported"))
                continue
            setup_effects.setdefault(setup, set()).add(record["effect_key"])
        if not setup_effects:
            continue
        script = lua.summarize_effects(row.get("alias") or code) if lua is not None else {"registrations": []}
        for setup, wanted in sorted(setup_effects.items()):
            relevant = []
            for record, ops in effects:
                if not ops:
                    continue
                source = record.get("lua_source", {})
                matched = source.get("registrations", []) if source.get("alignment") == "matched" else []
                relevant.append(dict(key=record["effect_key"], trigger=record["trigger"].get("event"),
                                     scopes=record["scope"], zone=record["trigger"].get("zone"),
                                     spans=[reg["registration_span"] for reg in matched],
                                     operations=[dict(block=o["block_id"], destination=o["to_zone"],
                                                      selector=o.get("selector_query")) for o in ops]))
            registrations = _registration_choices(script, setup)
            planned.append(dict(card=code, effects=relevant, wanted=sorted(wanted), setup=setup,
                seat=0, opening=[code], summons=[code] if setup == "normal_summon" else [],
                registration_source={k: script[k] for k in ("file", "sha256", "helpers") if k in script},
                registrations=registrations, destinations=sorted({o["destination"] for e in relevant
                    if e["key"] in wanted for o in e["operations"]}), seed=7, path=[]))
    return planned, excluded


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


def _resolved_deck_moves(events, selections, own_hand_gains, query, offered_description):
    """Require the selected effect's actual resolving link and selected Deck entity."""
    activations = [e for e in events if e["kind"] == 70]
    if len(activations) != 1:
        return []
    activation, = activations
    link = activation.get("link")
    if (activation.get("public_card") != query["card"] or activation.get("player") != query["seat"]
            or offered_description is not None and activation.get("description") != offered_description
            or any(e["kind"] in (75, 76) and e.get("link") == link for e in events)):
        return []
    begins = [i for i, e in enumerate(events) if e["kind"] == 72 and e.get("link") == link]
    ends = [i for i, e in enumerate(events) if e["kind"] == 73 and e.get("link") == link]
    if len(begins) != 1 or len(ends) != 1 or begins[0] >= ends[0]:
        return []
    moves = []
    for event in events[begins[0] + 1:ends[0]]:
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
                              link=link, activation=activation))
    return moves


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
                None, "field" if query["setup"] == "normal_summon" else "hand"):
            continue
        for operation in effect["operations"]:
            if operation["destination"] == move["destination"] and (
                    not operation["selector"] or matches(rows[move["card"]], operation["selector"])):
                candidates.append((effect["key"], operation["block"]))
    if len(candidates) != 1 or candidates[0][0] not in query["wanted"]:
        return dict(status="printed_use_ambiguous", candidates=candidates, source=registrations)
    effect, block = candidates[0]
    return dict(status="bound", effect_key=effect, block=block, source=registrations)


def run_window(assets, deck, query, *, selection_key, decision_budget, should_stop=None, counters=None):
    """Replay a deterministic legal prefix and collect each distinct offered alternative."""
    setup = deque(query["summons"])
    trace, selections, path, alternatives = [], set(), [], []
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
            active = own and not setup and event_start is None
            actor_zone = "monster" if query["setup"] == "normal_summon" else "hand"
            offers = [item for item in menu if active and item["kind"] in ("activate", "yes") and
                      any(ref in own_cards and own_cards[ref].zone == actor_zone and known.get(ref) == subject
                          for ref in item["refs"])]
            descriptions = {r["description"] for r in query["registrations"] if r["description"] is not None}
            source_offers = [item for item in offers if item["description"] in descriptions]
            offers = source_offers or offers
            if event_start is not None and msg in (10, 11):
                status = "settled"
                break
            if active and not offers and msg == 11:
                activation = dict(turn=request.observation.turn, phase=request.observation.phase, menu=menu)
                status = "not_offered"
                break

            refs = _deck_refs(request, seat) if own else set()
            tokens = (_choice_tokens(offers, msg, refs, activation=True) if offers else
                      _choice_tokens(menu, msg, refs) if own and event_start is not None else {})
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
                if sum(item["description"] == chosen["description"] for item in offers) != 1:
                    status = "activation_ambiguous"
                    activation = dict(turn=request.observation.turn, phase=request.observation.phase, menu=menu)
                    break
                before_hand = hand
                activation = dict(turn=request.observation.turn, phase=request.observation.phase,
                                  prompt=msg, menu=menu, selection=chosen)
                event_start = len(engine.events)
            if own and event_start is not None and chosen["kind"] == "select":
                selections.update(code for ref, code in zip(chosen["refs"], chosen["cards"])
                                  if ref in refs and code is not None)
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
    payments = [e for e in action_events if e["kind"] == 100 or e["kind"] == 50 and e.get("reason", 0) & 0x80]
    return dict(status=status, offered=event_start is not None, window=activation, trace=trace, events=events,
                moves=moves, payments=payments, selected_deck_cards=sorted(selections), decisions=len(trace),
                alternatives=alternatives, identity=_bind_movement(query, moves, assets.rows),
                **metadata)


class NativeRuleChecks:
    """Budget legal windows together and reuse only identical task/stock/scope receipts."""

    def __init__(self, assets):
        self.assets = assets
        self.directory = assets.workspace / "construction-native-rules"
        self.counts = Counter()
        self.attempts = []
        self.inventories = []

    def evaluate(self, task, deck, records, *, role, should_stop=None, queries=None):
        initial, excluded = planned_queries(deck, records, self.assets) if queries is None else (queries, [])
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
            for alternative in row["alternatives"]:
                branch = dict(query, path=alternative["path"])
                key = digest(branch)
                if key not in seen:
                    seen.add(key)
                    queue.append(branch)
        pending = [dict(card=q["card"], wanted=q["wanted"], setup=q["setup"], path=q["path"],
                        reason="native_decision_budget" if status == "decision_budget" else "construction_deadline")
                   for q in queue]
        exhausted = [row["receipt"] for row in receipts if row["status"] == "decision_budget"]
        if exhausted and status == "complete":
            status = "decision_budget"
        result = dict(status=status, eligible_uses=sum(len(q["wanted"]) for q in initial),
                      eligible_operations=sum(len(e["operations"]) for q in initial for e in q["effects"]
                                              if e["key"] in q["wanted"]),
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
        return dict(receipt=row["id"], status=result["status"], offered=result.get("offered"),
                    query=binding["query"], decisions=result["decisions"], moves=result.get("moves", []),
                    payments=result.get("payments", []), alternatives=result.get("alternatives", []),
                    identity=result.get("identity", {}), error=result.get("error"),
                    deck_sha256=digest(binding["deck"]))
