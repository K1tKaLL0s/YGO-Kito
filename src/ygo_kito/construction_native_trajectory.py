"""Follow complete legal choice sequences through the shared construction oracle."""

from collections import Counter

from .build_contracts import digest
from .contracts import ActionSelection
from .effect_duel import choose_effect_duel_action
from .normal_duel import request_digest


def trajectory_queries(main, extra, initialized, rows):
    """Prepare legal hands from each resident action source and compatible stock."""
    actions = {code for code in main if any(
        rule["type"] & 0x8 or "operation" in rule["callbacks"] for rule in initialized.get(code, {}).get("native", ()))}
    if not actions and not extra:
        return []
    stock = Counter(main)

    def sets(code):
        packed = rows[code].get("setcode", 0)
        return {packed >> shift & 0xfff for shift in (0, 16, 32, 48) if packed >> shift & 0xfff}

    archetypes = {code: sets(code) for code in stock}
    spells = {code for code in stock if rows[code]["type"] & 2}
    active = sorted(actions or stock.keys())
    openings = set()
    queries = []
    for code in active:
        remaining = stock.copy()
        remaining[code] -= 1
        candidates = sorted((other for other in remaining if remaining[other] and other != code),
            key=lambda other: (not bool(archetypes[other] & archetypes[code]), other not in actions,
                               other not in spells, other))
        opening = tuple(sorted((code, *candidates[:4])))
        if opening in openings:
            continue
        openings.add(opening)
        queries.append(dict(setup="trajectory", card=code, scope_cards=sorted(actions.intersection(opening) | set(extra)),
            seat=0, seed=7, opening=list(opening), summons=[], registrations=[], destinations=[],
            through_turn=3 if extra else 2 if any(rows[c]["type"] & 4 for c in opening) else 1, path=[], priority=1))
    return queries


def _action_tokens(request, menu):
    """Use stable positions in the native menu, independent of private request IDs."""
    return dict((row["action_id"], [request.observation.observer, request.prompt.message, index,
        row["kind"], row["description"], row.get("operation"), row["value"], row["cards"]])
        for index, row in enumerate(menu))


def play_trajectory(engine, query, public, menu_for, read_trace, *, decision_budget, should_stop, counters):
    """Return a real trajectory and its alternative legal decisions for S3."""
    trace, alternatives, path = [], [], []
    branch = query["path"]
    request = engine.next_decision()
    status = "decision_budget"
    for _ in range(decision_budget):
        if should_stop is not None and should_stop():
            status = "paused"
            break
        if request is None:
            status = "ended"
            break
        if request.observation.turn > query["through_turn"]:
            status = "trajectory_complete"
            break
        menu = menu_for(request)
        if len(menu) == 1:
            chosen = menu[0]["action_id"]
        else:
            tokens = _action_tokens(request, menu)
            depth = len(path)
            if depth < len(branch):
                chosen = next((action_id for action_id, token in tokens.items() if token == branch[depth]), None)
                if chosen is None:
                    status = "branch_unavailable"
                    break
            else:
                chosen = choose_effect_duel_action(request, public).action_id
                alternatives.extend(dict(path=[*path, token], prompt=request.prompt.message)
                                    for action_id, token in tokens.items() if action_id != chosen)
            path.append(tokens[chosen])
        trace.append(dict(request=request_digest(request), seat=request.observation.observer,
                          turn=request.observation.turn, phase=request.observation.phase,
                          prompt=request.prompt.message, menu=menu, selection=chosen))
        engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, chosen))
        if counters is not None:
            counters["submitted_decisions"] += 1
        request = engine.next_decision()
    if status in ("trajectory_complete", "ended") and len(path) < len(branch):
        status = "branch_unavailable"
    events = list(engine.events)
    result = dict(status=status, trace=trace, events=events, decisions=len(trace), alternatives=alternatives,
                  path=path, period=engine.period_context, scripts=sorted(engine.loaded_scripts))
    if read_trace is not None:
        result["rule_trace"] = read_trace(events)
    if hasattr(engine, "_catalog_assets"):
        result["native_code_projection"] = digest(engine._catalog_assets.native_code_overrides)
    return result
