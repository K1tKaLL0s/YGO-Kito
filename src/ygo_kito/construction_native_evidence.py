"""Attribute the public messages of a construction replay to their chain links."""

from collections import Counter, defaultdict

from .build_contracts import digest


SUMMON_RESPONSE_EVENTS = {1103: 60, 1104: 64, 1105: 62}


def pending_summons(events):
    """Recover starts still pending at a native summon-response window."""
    pending = []
    for event in reversed(events):
        kind = event["kind"]
        if kind in (40, 61, 63, 65, 70, 71, 72, 73, 74):
            break
        if kind in SUMMON_RESPONSE_EVENTS.values():
            pending.append(event)
    return list(reversed(pending))


def flip_completion(events, start, seat, code):
    announced = False
    for i in range(start, len(events)):
        event = events[i]
        if event["kind"] == 64:
            if announced or event["player"] != seat or event.get("public_summoning_card") != code:
                return None
            announced = True
        elif event["kind"] == 65:
            return i if announced else None
    return None


def admission_effects(quality):
    """Index the S3 obligations that can be traced to a printed effect."""
    facts_by_source = defaultdict(set)
    for fact in quality.get("unknowns", ()):
        for source in quality["fact_details"].get(fact, {}).get("evidence_refs", ()):
            facts_by_source[source].add(fact)
    width_by_fact = defaultdict(float)
    for component in quality.get("score_components", ()):
        values = component["rows"]
        width = max(value[2] for value in values) - min(value[1] for value in values)
        for fact in component["facts"]:
            width_by_fact[fact] = max(width_by_fact[fact], width)
    details = quality.get("use_details", {})
    hard_effects = {details[row["requirement_id"]]["effect_id"] for row in quality.get("hard_requirements", ())
                    if row["status"] == "unknown" and row["requirement_id"] in details}
    hard_facts = {fact for requirement in quality.get("hard_requirements", ())
                  for fact in requirement.get("unresolved_facts", ())}
    responses = {(row["card"], effect) for row in quality.get("native_rule_evidence", {}).get("response_windows", ())
                 for effect in row["effects"]}
    result = {}
    for coverage in quality.get("coverage_details", {}).values():
        for effect in coverage.get("effects", ()):
            ref = effect["effect_ref"]
            unknowns = facts_by_source[ref]
            partial = effect["status"] != "evaluated"
            hard = effect["effect_id"] in hard_effects or bool(unknowns & hard_facts)
            if not (unknowns or partial or hard) or ref in result:
                continue
            record = effect["record"]
            lua = record.get("lua_source", {})
            spans = [reg["registration_span"] for reg in lua.get("registrations", ())]
            result[ref] = dict(card=record["card_id"], effect=record["effect_key"], source=ref,
                facts=sorted(unknowns), partial=partial, hard=hard, spans=spans or lua.get("candidate_spans", []),
                response=(record["card_id"], record["effect_key"]) in responses,
                width=max((width_by_fact[f] for f in unknowns), default=0.))
    return list(result.values())


def window_priority(query, admission, role):
    """Prefer verified dependencies of the Gate, then its unresolved score line."""
    spans = [r["span"] for r in (*query.get("registrations", ()), *query.get("attached", ()))
             if r["span"] is not None]
    scope = query.get("scope_cards", (query["card"],))
    related = [effect for effect in admission.get("effects", ()) if effect["card"] in scope
               and (not effect.get("response") or query["setup"] in ("response", "trajectory"))
               and (not spans or not effect["spans"] or any(span in effect["spans"] for span in spans))]
    aligned = [effect for effect in related if any(span in effect["spans"] for span in spans)]
    affected = aligned or related
    facts = {fact for effect in affected for fact in effect["facts"]}
    width = max((effect["width"] for effect in affected), default=0.)
    unresolved = [row for row in admission.get("comparisons", {}).values()
                  if (row["delta"]["lower"] is None or row["delta"]["lower"] < 0)
                  and (row["delta"]["upper"] is None or row["delta"]["upper"] >= 0)]
    coefficient = max((row["ratio"] if role == "reference" else 1. for row in unresolved), default=0.)
    return (-sum(effect["hard"] for effect in affected), -int(bool(affected)),
            -int(bool(aligned)), -width * coefficient, -len(facts),
            -sum(effect["partial"] for effect in affected), -width, query.get("priority", 0), query["card"])


def witnessed_rule(receipt):
    """Identify the observed conditional rule separately from its stock allocation."""
    chain = receipt["chain"]
    preceding = chain.get("response_to")
    activation = chain["activation"]
    identity = receipt["identity"]
    condition = dict(zone=activation["zone"], phase=chain["phase"], turn_player=chain["turn_player"],
                     preparation=receipt["query"]["setup"],
                     response_to={k: preceding[k] for k in ("public_card", "zone", "description")}
                     if preceding is not None else None,
                     selection=receipt["path"])
    if receipt["stock_prefix"].get("set_preparation"):
        condition["set_preparation"] = receipt["stock_prefix"]["set_preparation"]
    if receipt["stock_prefix"].get("opposing_normal_summon"):
        condition["opposing_normal_summon"] = receipt["stock_prefix"]["opposing_normal_summon"]
    if receipt["stock_prefix"].get("flip_preparation"):
        condition["flip_preparation"] = receipt["stock_prefix"]["flip_preparation"]
    if receipt["query"].get("side_swaps"):
        condition["side_swaps"] = receipt["query"]["side_swaps"]
    if receipt["field_moves"] and (attempt := receipt["field_moves"][0].get("summon_attempt")):
        condition["summon_attempt"] = attempt
    proposition = dict(resources=receipt.get("rule_resources"), card=receipt["query"]["card"], effect=identity["effect_key"],
        registration=identity["source"], blocks=identity.get("blocks") or [identity["block"]],
        description=activation["description"])
    return dict(rule_id="native-rule:" + digest(proposition), condition=condition)


def chain_links(events):
    links, result = {}, []
    turn, turn_player, phase = None, None, None
    for index, event in enumerate(events):
        kind = event["kind"]
        link = event.get("link")
        if kind == 40:
            turn, turn_player = event["turn"], event["player"]
        elif kind == 41:
            phase = event["phase"]
        elif kind == 70:
            previous = links.get(link - 1)
            row = dict(activation=event, opened=index, turn=turn, turn_player=turn_player,
                       phase=phase, response_to=previous["activation"] if previous else None)
            if link in links:
                # No attribution through a reused link number without CHAIN_END.
                links[link]["ambiguous"] = row["ambiguous"] = True
            links[link] = row
            result.append(row)
        elif kind in (71, 72, 73, 75, 76) and link in links:
            key = {71: "chained", 72: "solving", 73: "solved", 75: "negated", 76: "disabled"}[kind]
            row = links[link]
            if key in row:
                row["ambiguous"] = True
            row[key] = index
        elif kind == 74:
            links.clear()

    for row in result:
        opened = row["opened"]
        chained, solving, solved = (row.get(k, -1) for k in ("chained", "solving", "solved"))
        seat = row["activation"]["player"]
        row["payments"] = []
        if opened < chained and not row.get("ambiguous"):
            for index in range(opened + 1, chained):
                event = events[index]
                if event["kind"] == 70:
                    row["payments"].clear()
                    row["ambiguous"] = True
                    break
                if event.get("player") == seat and (event["kind"] == 100
                        or event["kind"] == 50 and event.get("reason", 0) & 0x80):
                    row["payments"].append(dict(event, event_index=index))
        row["resolved"] = (not row.get("ambiguous") and opened < solving < solved
                           and "negated" not in row and "disabled" not in row
                           and not any(event["kind"] in (70, 72, 73, 74)
                                       for event in events[solving + 1:solved]))
    return result


def replay_steps(events, trace):
    """Recover decision boundaries in receipts written before event indexes were stored."""
    prompts = ((i, e) for i, e in enumerate(events) if "choices" in e)
    steps = []
    for row in trace:
        index, event = next(prompts, (None, {}))
        if (event.get("kind"), event.get("player")) != (row["prompt"], row["seat"]):
            return []
        chosen = next((action for action in row["menu"] if action["action_id"] == row["selection"]), None)
        if chosen is None:
            return []
        steps.append((index, row, chosen))
    return steps


def window_link(links, steps, query, window, *, events=()):
    if query.get("prepare_flip") and (window or {}).get("automatic"):
        seat, code = query["seat"], query["card"]
        start, opened = window["flip_start"], window["opened"]
        completion = flip_completion(events, start, seat, code)
        forced = [r for r in query["registrations"] if r.get("forced") and r["description"] == window["description"]]
        flips = [i for i, row, chosen in steps if i < start and row["seat"] == seat
                 and row["prompt"] == 11 and chosen["kind"] == "position" and chosen["cards"] == [code]]
        if completion is None or not completion < opened or len(forced) != 1 or len(flips) != 1:
            return None
        return next((link for link in links if link["opened"] == opened
                     and link["activation"]["public_card"] == code and link["activation"]["player"] == seat
                     and link["activation"]["zone"] == 4 and link["activation"]["description"] == window["description"]), None)
    selection = (window or {}).get("selection")
    if not selection:
        return None
    for index, row, chosen in reversed(steps):
        if (row["seat"] != query["seat"] or chosen != selection
                or any(row[k] != window[k] for k in ("turn", "phase", "prompt", "menu"))):
            continue
        next_action = next((i for i, step, action in steps if i > index and action["kind"] in
                            ("activate", "yes", "no", "pass", "summon", "special_summon", "set")
                            and not (step["prompt"] == 12 and step["seat"] == query["seat"]
                                     and action["kind"] in ("yes", "no") and action["refs"] == selection["refs"])),
                           float("inf"))
        link = next((link for link in links if index < link["opened"] < next_action
                     and link["activation"]["player"] == query["seat"]
                     and link["activation"]["public_card"] == query["card"]
                     and (row["prompt"] == 12 or selection["description"] is None
                          or link["activation"]["description"] == selection["description"])), None)
        return dict(link, selected_at=index) if link and query.get("attached") else link
    return None


def selected_objects(steps, link):
    seat = link["activation"]["player"]
    prefix = f"p{seat}."
    return {(ref[len(prefix):].split(".")[0], code)
            for index, row, chosen in steps if link["opened"] < index < link["solved"]
            and row["seat"] == seat and chosen["kind"] == "select"
            and (row["prompt"] != 26 or chosen.get("operation") == "add")
            for ref, code in zip(chosen["refs"], chosen["cards"]) if ref.startswith(prefix) and code is not None}


def stock_prefix(events, steps, link, query, prepared_moves, own_payments):
    """Identify initial entities for the supported replay prefix.

    The executor can leave incidental drawn cards unused. Stock reused here
    consists of the controlled opening, explicit Deck picks and Extra picks.
    Hidden/random selections and other preparation actions require their own
    stock evidence before they can supply a different inventory.
    """
    seat = query["seat"]
    # The existing conditional-CB driver injects a controlled opening at seat 0.
    if seat != 0 or link["turn"] is None or link["phase"] is None:
        return None
    opening = Counter(query["opening"])
    summons = Counter(query["summons"])
    if summons - opening:
        return None
    before = events[:link["opened"]]
    draws = [event for event in before if event["kind"] == 90 and event["player"] == seat]
    if not draws or draws[0]["count"] != sum(opening.values()):
        return None
    normal_summons = Counter(e.get("public_summoning_card") for e in before
                             if e["kind"] == 60 and e["player"] == seat)
    if normal_summons != summons:
        return None
    source = link["activation"]
    settings = [(index, row, chosen) for index, row, chosen in steps if index < link["opened"]
                and row["seat"] == seat and chosen["kind"] == "set"]
    preparation = flip_preparation = None
    set_move = None
    if query.get("prepare_set") or query.get("prepare_flip"):
        flipping = query.get("prepare_flip")
        area = 4 if flipping else 8
        if len(settings) != 1 or source["zone"] != area:
            return None
        index, setting, choice = settings[0]
        if choice["cards"] != [source["public_card"]] or not all(
                ref.startswith(f"p{seat}.hand.") for ref in choice["refs"]):
            return None
        transfers = [(i, e) for i, e in enumerate(before) if e["kind"] == 50
                     and e["player"] == seat and e["from_zone"] == 2 and e["to_zone"] == area
                     and (not flipping or e.get("public_card") in (None, source["public_card"]))]
        if len(transfers) != 1 or not index < transfers[0][0] or setting["turn"] >= link["turn"]:
            return None
        move_index, set_move = transfers[0]
        if (set_move.get("public_card") not in (None, source["public_card"])
                or not any(e["kind"] == 54 for e in before[move_index + 1:])):
            return None
        preparation = dict(card=source["public_card"], turn=setting["turn"],
                           activation_turn=link["turn"], zone="monster" if flipping else "spell_trap")
        if flipping:
            flips = [(i, row) for i, row, chosen in steps if move_index < i < link["opened"] and row["seat"] == seat
                     and row["prompt"] == 11 and chosen["kind"] == "position" and chosen["cards"] == [source["public_card"]]]
            if len(flips) != 1:
                return None
            at, turned = flips[0]
            if turned["turn"] <= setting["turn"] or flip_completion(before, at, seat, source["public_card"]) is None:
                return None
            announcements = [e for e in before if e["kind"] == 64 and e["player"] == seat]
            if len(announcements) != 1 or announcements[0]["slot"] != source["slot"]:
                return None
            flip_preparation = dict(preparation, flip_turn=turned["turn"])
    elif settings:
        return None
    if source["zone"] == 4:
        if not (summons[source["public_card"]] or flip_preparation):
            return None
    elif source["zone"] not in (2, 8) or not opening[source["public_card"]]:
        return None
    spent_hand = Counter(e.get("public_card") for e in (*before, *own_payments)
                         if e is not set_move and e["kind"] == 50 and e["player"] == seat and e["from_zone"] == 2)
    if preparation:
        spent_hand[preparation["card"]] += 1
    if spent_hand - opening:
        return None
    # Other actions require a traceable preparation. A responding opponent
    # stays an external branch; their cards do not become our stock.
    active = [e for e in before if e["kind"] == 70 and e["player"] == seat]
    excluded_summons = (62,) if flip_preparation else (62, 64)
    if len(active) != len(prepared_moves) or any(e["kind"] in excluded_summons and e["player"] == seat for e in before):
        return None
    prefix_deck = Counter(e.get("public_card") for e in before
                          if e["kind"] == 50 and e["player"] == seat and e["from_zone"] == 1
                          and e["to_zone"] != 1)
    if prefix_deck != Counter(move["card"] for move in prepared_moves):
        return None
    # Paid costs must come from those same opened copies, and any transfer
    # building the local field/grave state has to be part of this prefix.
    if any(e["kind"] == 50 and e["player"] == seat
           and (e["from_zone"], e["to_zone"]) not in ((1, 1), (1, 16), (2, 4), (2, 8)) for e in before):
        return None
    if any(row["seat"] == seat and index < link["opened"] and chosen["kind"] == "special_summon"
           for index, row, chosen in steps):
        return None
    summon_turns = [row["turn"] for i, row, chosen in steps if row["seat"] == seat
                    and i < link["opened"] and chosen["kind"] == "summon"]
    if len(summon_turns) != len(set(summon_turns)):
        return None
    prefix = dict(opening=list(query["opening"]), summons=list(query["summons"]),
                  prepared_moves=prepared_moves, normal_summon_turns=summon_turns)
    if preparation:
        prefix["set_preparation"] = preparation
    if flip_preparation:
        prefix["flip_preparation"] = flip_preparation
    return prefix
