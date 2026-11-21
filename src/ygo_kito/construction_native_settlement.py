"""Project completed native links to operations and physical stock requirements."""

from collections import Counter, defaultdict

from .build_contracts import digest
from .native_registrations import NativeRegistryError


_ZONES = {1: "deck", 2: "hand", 4: "field", 8: "field", 16: "grave", 32: "banished", 64: "extra",
          0x80: "overlay", 0x100: "field", 0x200: "field", 0x400: "field"}
_SUMMON_TYPES = {0x43000000: "fusion_summon", 0x46000000: "synchro_summon",
                 0x49000000: "xyz_summon", 0x45000000: "ritual_summon",
                 0x4a000000: "pendulum_summon", 0x4c000000: "link_summon"}
_LIFECYCLE = {70: "opened", 71: "chained", 72: "solving", 73: "solved"}
_COST, _EFFECT, _SPECIAL_SUMMON, _MATERIAL = 0x80, 0x40, 0x800, 0x8


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
                owner="self" if motion["owner"] == seat else "opponent", reason="effect")


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


_EQUIVALENT = {
    "add_hand": {"add_hand", "search", "search_or_recover", "recover"},
    "send_grave": {"send_grave", "mill"},
    "return_deck": {"return_deck", "return"},
    "return_extra": {"return_extra", "return"},
}


def operation_groups(execution):
    """Keep one actual operation over a group of simultaneously selected copies."""
    groups = {}
    for operation in execution["operations"]:
        identity = tuple(operation.get(key) for key in ("kind", "origin", "destination", "owner", "negation"))
        groups.setdefault(identity, []).append(operation)
    return list(groups.values())


def matching_records(execution, records, lua):
    """Find historical labels using only their linked Lua callback provenance."""
    actual = execution["registration"]
    callbacks = actual["callbacks"]
    result = []
    for record in records:
        for registration in record.get("lua_source", {}).get("registrations", ()):
            if registration.get("event_code") != actual["event"] or "operation" not in callbacks:
                continue
            if all(lua.callback_location(registration.get(role, {}).get("definition")) == observed
                   for role, observed in callbacks.items()):
                result.append(record)
                break
    return result


def _historic_label(receipt, execution, records):
    """Retain a proven historical label when its original link has this exact declaration."""
    if (receipt.get("chain") or {}).get("opened") != execution["opened"]:
        return []
    identity = receipt["identity"]
    if identity.get("status") != "bound":
        return []
    actual = execution["registration"]
    for source in identity["source"]:
        declared = source.get("initialized")
        if declared and all(declared.get(key) == actual[key] for key in (
                "scope", "type", "event", "range", "description", "category", "count_code", "callbacks")):
            return [record for record in records if record["effect_key"] == identity["effect_key"]]
    return []


def _historical_blocks(record, groups):
    for group in groups:
        observed = group[0]
        choices = [operation for operation in record["operations"] if operation.get("phase") not in ("delayed", "replacement")
                   and operation["kind"] in _EQUIVALENT.get(observed["kind"], {observed["kind"]})
                   and (not operation.get("from_zones") or observed.get("origin") in operation["from_zones"])
                   and operation.get("to_zone") in (None, observed.get("destination"))
                   and operation.get("owner") in (None, "unknown", "either", observed["owner"])
                   and operation.get("negation") in (None, observed.get("negation"))]
        if len(choices) == 1:
            yield choices[0]["block_id"], group


def _native_record(execution, groups, ordinal, cards_sha256):
    rule = execution["rule_id"]
    registration = execution["registration"]
    callback = registration["callbacks"]["operation"]
    source = f"{callback['file']}:{callback['lines'][0]}"
    zone = _ZONES.get(execution["actor"]["zone"])
    trigger = dict(event="native_event:" + str(execution["event"]), zone=zone, source=source)
    ops = []
    for group in groups:
        observed = group[0]
        cards = sorted({value["card"] for value in group if value.get("card")})
        values = dict(kind=observed["kind"], owner=observed["owner"], reason="effect",
            from_zones=[observed["origin"]] if observed.get("origin") else [], to_zone=observed.get("destination"),
            quantity=sum(row.get("quantity", 1) for row in group), source=source, phase="resolution",
            block_id=rule + ":operation:" + str(len(ops)))
        if cards and observed["owner"] == "self":
            values.update(selector_query={"predicate": {"field": "card_ids", "value": cards}}, random=False)
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
    return record, [(operation["block_id"], group) for operation, group in zip(ops, groups)]


def install_execution_contracts(observed, specifications, assets, contracts):
    """Supply S3 with results owned by native registrations, even without a printed record."""
    lua = assets.effect_lua_source
    if lua is None:
        return
    added = defaultdict(dict)
    native_sources = getattr(assets, "native_registration_source", None)
    initialized = {}
    for receipt in observed["receipts"]:
        for execution in receipt.get("native_executions", ()):
            code = execution["card"]
            if (execution["status"] != "observed" or code not in specifications
                    or "operation" not in execution["registration"]["callbacks"]):
                continue
            effects, materials = specifications[code]
            groups = operation_groups(execution)
            records = [effect["record"] for effect in effects]
            linked = matching_records(execution, records, lua)
            if not linked:
                linked = _historic_label(receipt, execution, records)
            if not linked and len(records) == 1 and native_sources is not None:
                if code not in initialized:
                    try:
                        initialized[code] = [row for row in native_sources.for_cards((code,))[code]["native"]
                                             if row["type"] & 0x8 and "operation" in row["callbacks"]]
                    except NativeRegistryError:
                        initialized[code] = []
                if initialized[code] == [execution["registration"]]:
                    linked = records
            if len(linked) == 1:
                record, = linked
                blocks = list(_historical_blocks(record, groups))
            elif not linked and not any(r["operations"] or r.get("costs") or r.get("restrictions") for r in records):
                branch_id = digest((execution["rule_id"], [tuple(group[0].get(field) for field in (
                    "kind", "origin", "destination", "owner", "negation")) for group in groups]))
                branch = added[code].get(branch_id)
                if branch is None:
                    ordinal = min((r["effect_index"] for r in records), default=0) - len(added[code]) - 1
                    effect, pairs = _native_record(execution, groups, ordinal, assets.receipt["resources"]["cards"])
                    effect["effect_key"] += ":" + branch_id
                    effect["relation_ref"] = effect["effect_key"]
                    branch = added[code][branch_id] = effect, pairs
                record, previous = branch
                blocks = [(block, group) for (block, _), group in zip(previous, groups)]
            else:
                continue
            for block, operations in blocks:
                contracts.setdefault((code, record["effect_key"], block), []).append(dict(
                    execution=execution, receipt=receipt["receipt"], deck=receipt["deck_sha256"], query=receipt["query"],
                    active_deck=receipt.get("active_deck"), resources=receipt["rule_resources"], operations=operations,
                    prepared=receipt.get("condition", {}) if (receipt.get("chain") or {}).get("opened") == execution["opened"] else {},
                    chain=next(link for link in receipt["chain_links"] if link["opened"] == execution["opened"])))
    for code, branches in added.items():
        effects, materials = specifications[code]
        specifications[code] = [*effects, *(dict(record=record, requirements=[], unknown=[])
                                 for record, _ in branches.values())], materials


def registration_coverage(declarations, observed, contracts):
    """Track every initialized rule to its planned window, checked result and S3 port."""
    executions = defaultdict(list)
    consumed = defaultdict(set)
    planned = defaultdict(set)
    trajectories = defaultdict(set)
    for receipt in observed["receipts"]:
        for case in receipt.get("native_executions", ()):
            key = case["card"], digest(case["registration"])
            executions[key].append(dict(status=case["status"], receipt=receipt["receipt"],
                                        result=[operation["kind"] for operation in case["operations"]]))
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
            elif active:
                status = "native_window_unreached" if windows else "native_preparation_unavailable"
            else:
                status = "native_modifier_unverified"
            rows.append(dict(ordinal=ordinal, rule=rule, status=status, windows=sorted(windows),
                             executions=executions[key], uses=uses))
        dynamic = {signature: cases for (actor, signature), cases in executions.items()
                   if actor == code and signature not in signatures and cases}
        result[code] = dict(registrations=rows, diagnostics=source["diagnostics"], runtime_only=dynamic)
    return result
