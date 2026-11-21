"""Project completed native links to operations and physical stock requirements."""

from collections import Counter, defaultdict

from .build_contracts import digest


_ZONES = {1: "deck", 2: "hand", 4: "field", 8: "field", 16: "grave", 32: "banished", 64: "extra",
          0x80: "overlay", 0x100: "field", 0x200: "field", 0x400: "field"}
_SUMMON_TYPES = {0x43000000: "fusion_summon", 0x46000000: "synchro_summon",
                 0x49000000: "xyz_summon", 0x45000000: "ritual_summon",
                 0x4a000000: "pendulum_summon", 0x4c000000: "link_summon"}
_LIFECYCLE = {70: "opened", 71: "chained", 72: "solving", 73: "solved"}
_COST, _EFFECT, _SPECIAL_SUMMON, _MATERIAL = 0x80, 0x40, 0x800, 0x8


def observed_applicability(trace, *, resources, query):
    """Read eligibility outcomes for the actual state visited by a legal replay."""
    result = []
    seen = set()
    for row in trace.get("guards", ()):
        role = row["role"]
        source = row["declaration"]["callbacks"].get(role, {})
        if row["seat"] != query["seat"] or "sha256" not in source:
            continue
        predicate = "native-check:" + digest((resources, row["card"], row["declaration"], role))
        key = (predicate, row["index"], row["entity"], row["turn"], row["phase"], row["zone"], row["passed"])
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(row, predicate=predicate, callback=source,
            status="satisfied" if row["passed"] else f"native_{role}_failed"))
    return result


def observed_goal_receipt(route, goal, evidence):
    """Return the actual first-turn replay proving the original goal and required links."""
    from .route_search import effect_goal_witness, resolved_chain_cards

    start = route["starting_conditions"]
    for receipt in evidence["receipts"]:
        query = receipt["query"]
        if (query.get("side_swaps") or query["seat"] != start["player"]
                or Counter(start["requires_opening_hand"]) - Counter(query["opening"])):
            continue
        events = receipt.get("goal_timeline", ())
        activated = {e["public_card"] for e in events if e["kind"] == 70 and e["player"] == 0}
        if not set(goal.get("required_activations", ())) <= activated or not set(
                goal.get("required_chain_resolutions", ())) <= resolved_chain_cards(events):
            continue
        if route["kind"] == "effect_resolution" and effect_goal_witness(route, events, exact_description=True):
            return receipt["receipt"]
        if route["kind"] == "normal_summon":
            if any(event["kind"] == 60 and event.get("player") == 0 and
                    event.get("public_summoning_card") == route["card_id"] and
                    i + 1 < len(events) and events[i + 1]["kind"] == 61 for i, event in enumerate(events)):
                return receipt["receipt"]
        for case in receipt.get("native_executions", ()):
            if (case["status"] != "observed" or case["solved"] >= receipt["first_turn_end"]
                    or not any(move["kind"] == route["kind"] and move.get("card") == route["card_id"]
                               and move["owner"] == "self" for move in case["operations"])):
                continue
            fusion = route.get("fusion_witness")
            if fusion:
                materials = [move for move in case["movements"]
                             if move["owner"] == start["player"] and move["reason"] & 0x40008 == 0x40008
                             and move["destination"][1] in fusion["allowed_destination_zones"]]
                if (case["card"] not in {row["card_id"] for row in fusion["effect_assessments"]}
                        or len({move["entity"] for move in materials}) < fusion["minimum_materials"]
                        or not set(fusion["required_source_zones"]) <= {move["origin"][1] for move in materials}):
                    continue
            return receipt["receipt"]
    return None


def effect_movement(motion, seat, resolution):
    """Describe the actual movement using core zones and reason flags."""
    reason = motion["reason"]
    origin = _ZONES.get(motion["origin"][1])
    destination = _ZONES.get(motion["destination"][1])
    if not origin or not destination or not motion["card"] or reason & _COST:
        return None
    if reason & _MATERIAL:
        return None  # Source entities for a summon, represented in its stock.
    if reason & _SPECIAL_SUMMON:
        if destination != "field" or not any(
                e["kind"] == 62 and e.get("public_summoning_card") == motion["card"]
                and e["player"] == motion["destination"][0] and any(
                    later["kind"] == 63 for later in resolution[index + 1:])
                for index, e in enumerate(resolution)):
            return None
        kind = _SUMMON_TYPES.get(motion["summon_type"] & 0xff000000, "special_summon")
    elif not reason & _EFFECT:
        return None
    elif reason & 0x1:
        kind = "destroy"
    elif reason & 0x2:
        kind = "release"
    elif reason & 0x4000:
        kind = "discard"
    elif destination == "field" and origin == "field" and motion["origin"][0] != motion["destination"][0]:
        kind = "take_control"
    else:
        kind = {"deck": "return_deck", "hand": "add_hand", "grave": "send_grave",
                "banished": "banish", "extra": "return_extra", "overlay": "attach_material"}.get(destination)
    if not kind:
        return None
    return dict(kind=kind, origin=origin, destination=destination, card=motion["card"], entity=motion["entity"],
                owner="self" if motion["owner"] == seat else "opponent", reason="effect",
                **({"native_call": dict(motion["operation"], id=motion["call"])} if motion.get("operation") else {}))


def _scalar_operations(link, events, declaration, seat):
    """Read scalar effects for which the activated declaration and messages agree."""
    category = declaration["category"]
    for i in range(link["solving"] + 1, link["solved"]):
        event = events[i]
        if event["kind"] == 90 and category & 0x800000 and event["count"]:
            yield dict(kind="draw", origin="deck", destination="hand", owner=(
                "self" if event["player"] == seat else "opponent"), quantity=event["count"], reason="effect")
        elif event["kind"] in (91, 92) and event["amount"] > 0:
            kind, bit = ("damage", 0x100000) if event["kind"] == 91 else ("recover_lp", 0x200000)
            if category & bit:
                yield dict(kind=kind, owner="self" if event["player"] == seat else "opponent",
                           quantity=event["amount"], reason="effect")
        elif event["kind"] in (75, 76) and link["response_to"] and event["link"] == link["response_to"]["link"]:
            target = link["response_to"]
            yield dict(kind="negate", owner="self" if target["player"] == seat else "opponent",
                card=target["public_card"], origin=_ZONES.get(target["zone"]), negation=(
                    "activation" if event["kind"] == 75 else "effect"), reason="effect")


def _physical_requirements(opened, targets, moves, seat):
    """Count physical entities once even when they move more than once."""
    entities = {}
    for entry in (opened, *targets, *moves):
        if entry["owner"] == seat and entry["stock"] in (1, 64) and entry["card"]:
            value = (entry["stock"], entry["card"])
            previous = entities.setdefault(entry["entity"], value)
            if previous != value:
                return None
    return [dict(zone="main" if zone == 1 else "extra", card=code, quantity=count)
            for (zone, code), count in sorted(Counter(entities.values()).items())]


def settled_executions(events, links, trace, *, seat, resources):
    """Build contracts from the exact rule and the entities in its settled window."""
    observed = trace.get("observations", {})
    movements = {int(index): row for index, row in trace.get("moves", {}).items()}
    executions = []
    deck_order = set(trace.get("deck_order_notices", ()))
    for link in links:
        snapshots = {key: observed[str(link[key])] for key in _LIFECYCLE.values()
                     if key in link and str(link[key]) in observed}
        if snapshots:
            link["registration_observed"] = snapshots
        if not link["resolved"] or len(snapshots) != len(_LIFECYCLE):
            continue
        opened, committed, solving, settled = (snapshots[key] for key in _LIFECYCLE.values())
        if (opened["seat"] != seat or opened["owner"] != seat or solving["replaced"]
                or len({row["chain_id"] for row in snapshots.values()}) != 1
                or len({row["entity"] for row in snapshots.values()}) != 1
                or committed["declaration"] != solving["declaration"] or solving["declaration"] != settled["declaration"]):
            continue
        declaration = solving["declaration"]
        if not declaration["callbacks"] or any("sha256" not in item for item in declaration["callbacks"].values()):
            continue
        chain_id = solving["chain_id"]
        costs = [motion for i, motion in movements.items() if link["opened"] < i < link["chained"]
                 and motion["chain_id"] == chain_id and motion["reason"] & _COST]
        payments = [dict(payment, owner=seat) for payment in link["payments"] if payment["kind"] == 100]
        unbound_payments = len(costs) != sum(payment["kind"] == 50 for payment in link["payments"])
        resolution = events[link["solving"] + 1:link["solved"]]
        motion = [row for i, row in movements.items() if link["solving"] < i < link["solved"]
                  and row["chain_id"] == chain_id]
        operations = [operation for row in motion if (operation := effect_movement(row, seat, resolution))]
        operations.extend(_scalar_operations(link, events, declaration, seat))
        unresolved_moves = [i for i in range(link["solving"] + 1, link["solved"]) if events[i]["kind"] == 50
                            and i not in deck_order
                            and events[i]["reason"] & (_EFFECT | _SPECIAL_SUMMON) and (
                                i not in movements or not movements[i]["chain_id"])]
        target = committed.get("targets", [])
        stock = _physical_requirements(opened, target, [*costs, *motion], seat)
        rule_id = "native-effect:" + digest((resources, solving["issuer"], declaration))
        executions.append(dict(rule_id=rule_id, card=opened["card"], registration=declaration,
            actor=opened, resolved_registration=solving, targets=target, stock=stock,
            opened=link["opened"], solved=link["solved"], event=solving["event"], operations=operations,
            payments=payments, card_payments=costs, movements=motion,
            status="partial" if unresolved_moves or unbound_payments or stock is None else
                   "observed" if operations else "settled_without_projected_operation",
            unbound_payments=unbound_payments, unresolved_moves=unresolved_moves))
    return executions


def operation_groups(execution):
    """Keep one actual operation over a group of simultaneously selected copies."""
    groups = {}
    for operation in execution["operations"]:
        identity = (operation.get("native_call", {}).get("id"), *(operation.get(key)
                    for key in ("kind", "origin", "destination", "owner", "negation")))
        groups.setdefault(identity, []).append(operation)
    return list(groups.values())


def _native_record(execution, branch, groups, ordinal, cards_sha256):
    rule = execution["rule_id"] + ":" + branch
    registration = execution["registration"]
    callback = registration["callbacks"]["operation"]
    source = f"{callback['file']}:{callback['lines'][0]}"
    zone = _ZONES.get(execution["actor"]["zone"])
    trigger = dict(event="native_event:" + str(execution["event"]), zone=zone, source=source)
    ops = []
    for group in groups:
        observed = group[0]
        values = dict(kind=observed["kind"], owner=observed["owner"], reason="effect",
            from_zones=[observed["origin"]] if observed.get("origin") else [], to_zone=observed.get("destination"),
            quantity=sum(row.get("quantity", 1) for row in group), source=source, phase="resolution",
            block_id=rule + ":operation:" + str(len(ops)))
        if observed.get("native_call", {}).get("method") == "DiscardDeck":
            values["random"] = True
        if observed.get("negation"):
            values["negation"] = observed["negation"]
        ops.append(values)
    record = dict(record_version="native-construction-effect-v1", semantic_version="native-construction-effect-v1",
        card_id=execution["card"], cards_sha256=cards_sha256, text_sha256=digest(registration),
        effect_index=ordinal, effect_key=rule, source_text=source, scope="spell_trap" if registration["type"] & 0x10 else "monster",
        relation_ref=rule, trigger=trigger, conditions={"source": source, "status": "recognized"},
        costs=[], targets=[], operations=ops, count_limits=[], restrictions=[], card_restrictions=[],
        printed_materials=[], unknown=[], block_view={"status": "native", "blocks": [], "unknown": []},
        rule_registration=registration)
    return record


def install_execution_contracts(observed, specifications, assets, contracts):
    """Translate each settled native branch into the physical inventory contract."""
    added = defaultdict(dict)
    for receipt in observed["receipts"]:
        for execution in receipt.get("native_executions", ()):
            code = execution["card"]
            if (execution["status"] != "observed" or code not in specifications
                    or "operation" not in execution["registration"]["callbacks"]):
                continue
            groups = operation_groups(execution)
            branch_id = digest((execution["rule_id"], [tuple(group[0].get(field) for field in (
                "kind", "origin", "destination", "owner", "negation")) for group in groups]))
            record = added[code].get(branch_id)
            if record is None:
                ordinal = -len(added[code]) - 1
                record = _native_record(execution, branch_id, groups, ordinal, assets.receipt["resources"]["cards"])
                added[code][branch_id] = record
            for operation, processing in zip(record["operations"], groups):
                contracts.setdefault((code, record["effect_key"], operation["block_id"]), []).append(dict(
                    execution=execution, receipt=receipt["receipt"], deck=receipt["deck_sha256"], query=receipt["query"],
                    active_deck=receipt.get("active_deck"), resources=receipt["rule_resources"], operations=processing,
                    prepared=receipt.get("condition", {}) if (receipt.get("chain") or {}).get("opened") == execution["opened"] else {},
                    evaluated_conditions=[row for row in receipt.get("native_applicability", ())
                        if row["entity"] == execution["actor"]["entity"] and row["index"] <= execution["opened"]
                        and row["declaration"] == execution["registration"]],
                    chain=next(link for link in receipt["chain_links"] if link["opened"] == execution["opened"])))
    for code, branches in added.items():
        effects, materials = specifications[code]
        specifications[code] = [*effects, *(dict(record=record, requirements=[], unknown=[])
                                 for record in branches.values())], materials


def registration_coverage(declarations, observed, contracts):
    """Track every initialized rule to its planned window, checked result and S3 port."""
    executions = defaultdict(list)
    consumed = defaultdict(set)
    planned = defaultdict(set)
    trajectories = defaultdict(set)
    checks = defaultdict(list)
    for receipt in observed["receipts"]:
        for case in receipt.get("native_executions", ()):
            key = case["card"], digest(case["registration"])
            executions[key].append(dict(status=case["status"], receipt=receipt["receipt"],
                                        result=[operation["kind"] for operation in case["operations"]]))
        for outcome in receipt.get("native_applicability", ()):
            checks[outcome["card"], digest(outcome["declaration"])].append(dict(
                receipt=receipt["receipt"], predicate=outcome["predicate"], role=outcome["role"],
                index=outcome["index"], entity=outcome["entity"], status=outcome["status"],
                turn=outcome["turn"], phase=outcome["phase"], zone=outcome["zone"]))
    for (_, effect, block), rows in contracts.items():
        for row in rows:
            case = row["execution"]
            consumed[case["card"], digest(case["registration"])].add((effect, block))
    queries = [r["query"] for r in observed["receipts"]] + [r["query"] for r in observed.get("pending", ())]
    for query in queries:
        if query["setup"] == "trajectory":
            for code in query["scope_cards"]:
                trajectories[code].add(query["setup"])
        else:
            for window in (*query["registrations"], *query.get("attached", ())):
                if registration := window.get("initialized"):
                    planned[query["card"], digest(registration)].add(query["setup"])
    result = {}
    for code, source in declarations.items():
        rows = []
        signatures = Counter(digest(rule) for rule in source["native"])
        for ordinal, rule in enumerate(source["native"]):
            signature = digest(rule)
            key = code, signature
            uses = [dict(effect=effect, block=block) for effect, block in sorted(consumed[key])]
            active = rule["type"] & 0x8 or rule["event"] in (34, 320)
            windows = planned[key] | trajectories[code]
            if (uses or executions[key]) and signatures[signature] > 1:
                status = "native_registration_identity_ambiguous"
            elif uses:
                status = "observed_use"
            elif executions[key]:
                status = "native_settlement_unconsumed"
            elif checks[key]:
                status = "native_precondition_checked"
            elif active:
                status = "native_window_unreached" if windows else "native_preparation_unavailable"
            else:
                status = "native_modifier_unverified"
            rows.append(dict(ordinal=ordinal, rule=rule, status=status, windows=sorted(windows), checks=checks[key],
                             executions=executions[key], uses=uses))
        dynamic = {signature: cases for (actor, signature), cases in executions.items()
                   if actor == code and signature not in signatures and cases}
        result[code] = dict(registrations=rows, diagnostics=source["diagnostics"], runtime_only=dynamic)
    return result
