"""Attribute the public messages of a construction replay to their chain links."""

from collections import Counter


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


def window_link(links, steps, query, window):
    selection = (window or {}).get("selection")
    if not selection:
        return None
    for index, row, chosen in reversed(steps):
        if (row["seat"] != query["seat"] or chosen != selection
                or any(row[k] != window[k] for k in ("turn", "phase", "prompt", "menu"))):
            continue
        next_action = next((i for i, _, action in steps if i > index and action["kind"] in
                            ("activate", "yes", "no", "pass", "summon", "special_summon", "set")), float("inf"))
        return next((link for link in links if index < link["opened"] < next_action
                     and link["activation"]["player"] == query["seat"]
                     and link["activation"]["public_card"] == query["card"]
                     and (row["prompt"] == 12 or selection["description"] is None
                          or link["activation"]["description"] == selection["description"])), None)
    return None


def selected_objects(steps, link):
    seat = link["activation"]["player"]
    prefix = f"p{seat}."
    return {(ref[len(prefix):].split(".")[0], code)
            for index, row, chosen in steps if link["opened"] < index < link["solved"]
            and row["seat"] == seat and chosen["kind"] == "select"
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
    if source["zone"] == 4:
        if not summons[source["public_card"]]:
            return None
    elif source["zone"] not in (2, 8) or not opening[source["public_card"]]:
        return None
    spent_hand = Counter(e.get("public_card") for e in (*before, *own_payments)
                         if e["kind"] == 50 and e["player"] == seat and e["from_zone"] == 2)
    if spent_hand - opening:
        return None
    # Other actions require a traceable preparation. A responding opponent
    # stays an external branch; their cards do not become our stock.
    active = [e for e in before if e["kind"] == 70 and e["player"] == seat]
    if len(active) != len(prepared_moves) or any(e["kind"] in (62, 64) and e["player"] == seat for e in before):
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
    if any(row["seat"] == seat and index < link["opened"] and chosen["kind"] in ("set", "special_summon")
           for index, row, chosen in steps):
        return None
    summon_turns = [row["turn"] for i, row, chosen in steps if row["seat"] == seat
                    and i < link["opened"] and chosen["kind"] == "summon"]
    if len(summon_turns) != len(set(summon_turns)):
        return None
    return dict(opening=list(query["opening"]), summons=list(query["summons"]),
                prepared_moves=prepared_moves, normal_summon_turns=summon_turns)
