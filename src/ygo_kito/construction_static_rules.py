"""Project supported locked Lua callbacks into conditional construction uses."""

from collections import Counter

from .build_contracts import digest
from .effect_lua import (
    _binary, _call, _check_body, _children, _conjuncts, _integer_value,
    _literal_arguments, _literal_call, _local_value, _member_call, _name, _nonempty_group,
    _processing_statements, _return_expression, _selection_query, _text,
)


def _body(node):
    if node is None:
        return (), []
    params = tuple(map(_text, node.child_by_field_name("parameters").children_by_field_name("name")))
    if set(params) & {"Card", "Duel", "Effect", "Group"}:
        return (), []
    return params, _children(node.child_by_field_name("body"))


def _handler_send_cost(node, constants):
    params, body = _body(node)
    if len(params) < 9:
        return False
    effect, player, check = params[0], params[1], params[8]
    body = list(_processing_statements(body, constants, player, effect))
    if len(body) != 2:
        return False
    guard, payment = body
    left, right = _binary(guard.child_by_field_name("condition"), "==")
    condition = _return_expression(_check_body(guard))
    action, paid = _call(payment)
    return (_name(left) == check and _integer_value(right, constants) == 0
            and _literal_call(_member_call(condition, "IsAbleToGraveAsCost", constants),
                              constants, f"{effect}:GetHandler")
            and action == "Duel.SendtoGrave" and len(paid) == 2
            and _literal_call(paid[0], constants, f"{effect}:GetHandler")
            and _integer_value(paid[1], constants) == constants["REASON_COST"])


def _deck_output(node, constants):
    params, body = _body(node)
    if len(params) not in (2, 8) or len(body) != 1:
        return None
    name, args = _call(body[0])
    destinations = {"Duel.Draw": ("draw", "hand"), "Duel.DiscardDeck": ("send_grave", "grave")}
    if name not in destinations or len(args) != 3 or _name(args[0]) != params[1]:
        return None
    count = _integer_value(args[1], constants)
    if count and count > 0 and _integer_value(args[2], constants) == constants["REASON_EFFECT"]:
        kind, destination = destinations[name]
        return dict(kind=kind, from_zones=["deck"], to_zone=destination, quantity=count, random=True)
    return None


def _activation_check(node, constants):
    params, body = _body(node)
    if len(params) != 9:
        return (), None
    body = list(_processing_statements(body, constants, params[1], params[0]))
    if len(body) != 1:
        return (), None
    guard, = body
    left, right = _binary(guard.child_by_field_name("condition"), "==")
    if _name(left) != params[8] or _integer_value(right, constants) != 0:
        return (), None
    return params, _return_expression(_check_body(guard))


def _checked_deck_output(operation, target, constants):
    result = _deck_output(operation, constants)
    if result is not None:
        params, check = _activation_check(target, constants)
        predicate = "Duel.IsPlayerCanDraw" if result["kind"] == "draw" else "Duel.IsPlayerCanDiscardDeck"
        if params and _literal_call(check, constants, predicate, params[1], result["quantity"]):
            return result
    return None


def _deck_selection(operation, target, functions, constants):
    params, body = _body(operation)
    if len(params) != 8:
        return None
    effect, player = params[:2]
    body = list(_processing_statements(body, constants, player, effect))
    if len(body) != 2:
        return None
    group, selection = _local_value(body[0])
    select, args = _call(selection)
    if select != "Duel.SelectMatchingCard" or not group or group in params or len(args) != 8:
        return None
    filter_name = _name(args[1])
    count = _integer_value(args[5], constants)
    deck = constants["LOCATION_DECK"]
    if not filter_name or not count or count < 1 or not _literal_arguments(
            args, constants, (player, filter_name, player, deck, 0, count, count, None)):
        return None
    checker, check = _activation_check(target, constants)
    if not checker or not _literal_call(check, constants, "Duel.IsExistingMatchingCard",
                                       filter_name, checker[1], deck, 0, count, None):
        return None
    guard = body[1]
    if not _nonempty_group(guard.child_by_field_name("condition"), group, constants):
        return None
    processing = _check_body(guard)
    if not processing:
        return None
    reason = constants["REASON_EFFECT"]
    if _literal_call(processing[0], constants, "Duel.SendtoHand", group, None, reason):
        kind, destination, ability = "search", "hand", "IsAbleToHand"
        if len(processing) > 2:
            return None
        if len(processing) == 2:
            call, operands = _call(processing[1])
            if (call != "Duel.ConfirmCards" or len(operands) != 2 or _name(operands[1]) != group
                    or not _opponent(operands[0], constants, player)):
                return None
    elif len(processing) == 1 and _literal_call(
            processing[0], constants, "Duel.SendtoGrave", group, reason):
        kind, destination, ability = "send_grave", "grave", "IsAbleToGrave"
    else:
        return None
    filter_params, filter_body = _body(functions.get(filter_name))
    if len(filter_params) != 1:
        return None
    card, = filter_params
    terms = _conjuncts(_return_expression(filter_body))
    if not any(_literal_call(term, constants, f"{card}:{ability}") for term in terms):
        return None
    filters = [term for term in terms if not _literal_call(term, constants, f"{card}:{ability}")]
    query = {}
    for term in filters:
        part = _selection_query(term, card, constants)
        if not part or part.keys() & query.keys():
            return None
        query.update(part)
    return dict(kind=kind, from_zones=["deck"], to_zone=destination, quantity=count,
                random=False, selector_query=query or {"type": 7})


def _opponent(node, constants, player):
    left, right = _binary(node, "-")
    return _integer_value(left, constants) == 1 and _name(right) == player


def _listeners(node, constants):
    """Read effect objects registered by resolution, including their reset."""
    params, body = _body(node)
    if len(params) != 8 or not body:
        return []
    effect, player = params[:2]
    handler, value = _local_value(body[0])
    if not handler or not _literal_call(value, constants, f"{effect}:GetHandler"):
        return []
    listeners = []
    current = None
    for step in body[1:]:
        variable, value = _local_value(step)
        if variable and current is None and variable != handler and _literal_call(
                value, constants, "Effect.CreateEffect", handler):
            current, settings = variable, {}
            continue
        if current is None:
            return []
        if _literal_call(step, constants, "Duel.RegisterEffect", current, player):
            if (set(settings) - {"SetType", "SetProperty", "SetCode", "SetCondition", "SetOperation", "SetReset"}
                    or settings.get("SetType") != constants["EFFECT_TYPE_FIELD"] | constants["EFFECT_TYPE_CONTINUOUS"]
                    or settings.get("SetReset") != constants["RESET_PHASE"] | constants["PHASE_END"]
                    or settings.get("SetProperty", 0) not in (0, constants["EFFECT_FLAG_DELAY"])
                    or not all(settings.get(key) for key in ("SetCode", "SetCondition", "SetOperation"))):
                return []
            listeners.append(settings)
            current = None
            continue
        name, args = _call(step)
        prefix = current + ":"
        if not name.startswith(prefix) or len(args) != 1 or name[len(prefix):] in settings:
            return []
        key = name[len(prefix):]
        settings[key] = (_name(args[0]) if key in ("SetCondition", "SetOperation")
                         else _integer_value(args[0], constants))
    return listeners if current is None else []


def _summon_condition(node, functions, constants):
    params, body = _body(node)
    if len(params) != 8:
        return None
    _, player, group = params[:3]
    selection, chain = _binary(_return_expression(body), "and")
    name, args = _call(selection)
    if (name != f"{group}:IsExists" or len(args) != 4
            or not _literal_arguments(args[1:3], constants, (1, None))
            or not _opponent(args[3], constants, player)):
        return None
    filter_params, filter_body = _body(functions.get(_name(args[0])))
    if len(filter_params) != 2 or not _literal_call(_return_expression(filter_body), constants,
            f"{filter_params[0]}:IsSummonPlayer", filter_params[1]):
        return None
    if _literal_call(chain, constants, "Duel.IsChainSolving"):
        return "chain_solving"
    if (chain is not None and chain.type == "unary_expression" and _text(chain.child_by_field_name("operator")) == "not"
            and _literal_call(chain.child_by_field_name("operand"), constants, "Duel.IsChainSolving")):
        return "outside_chain"
    return None


def _chain_flag(node, constants):
    params, body = _body(node)
    if len(params) != 8 or len(body) != 1:
        return None
    name, args = _call(body[0])
    flag = _integer_value(args[1], constants) if len(args) == 5 else None
    if flag and name == "Duel.RegisterFlagEffect" and _literal_arguments(
            args, constants, (params[1], flag, constants["RESET_CHAIN"], 0, 1)):
        return flag
    return None


def _draw_flag(condition, operation, flag, constants):
    params, body = _body(condition)
    if len(params) != 8:
        return False
    left, right = _binary(_return_expression(body), ">")
    if (not _literal_call(left, constants, "Duel.GetFlagEffect", params[1], flag)
            or _integer_value(right, constants) != 0):
        return False
    params, body = _body(operation)
    if len(params) != 8 or len(body) != 3:
        return False
    count, value = _local_value(body[0])
    player = params[1]
    return bool(count and _literal_call(value, constants, "Duel.GetFlagEffect", player, flag)
        and _literal_call(body[1], constants, "Duel.ResetFlagEffect", player, flag)
        and _literal_call(body[2], constants, "Duel.Draw", player, count, constants["REASON_EFFECT"]))


def _summon_draw(operation, functions, constants):
    """Recognize one draw per matching event, including flag counts within a chain."""
    by_window = {}
    for listener in _listeners(operation, constants):
        event = listener["SetCode"]
        condition, processing = (functions.get(listener[key]) for key in ("SetCondition", "SetOperation"))
        if event == constants["EVENT_SPSUMMON_SUCCESS"]:
            window = _summon_condition(condition, functions, constants)
        elif event == constants["EVENT_CHAIN_SOLVED"]:
            window = "chain_solved"
        else:
            return None
        if (not window or window in by_window or listener.get("SetProperty", 0) !=
                (constants["EFFECT_FLAG_DELAY"] if window == "outside_chain" else 0)):
            return None
        by_window[window] = condition, processing
    if set(by_window) != {"outside_chain", "chain_solving", "chain_solved"}:
        return None
    draw = _deck_output(by_window["outside_chain"][1], constants)
    flag = _chain_flag(by_window["chain_solving"][1], constants)
    if (draw and draw["kind"] == "draw" and draw["quantity"] == 1 and flag
            and _draw_flag(*by_window["chain_solved"], flag, constants)):
        return dict(draw, event_condition=dict(event="special_summon_success", player="opponent",
                    duration="through_end_phase", quantity_basis="per_event"))
    return None


def _fusion_trigger(rule, constants):
    event = rule["event"]
    events = {constants[key]: (name, zone) for key, name, zone in (
        ("EVENT_TO_GRAVE", "sent_to_grave", "grave"),
        ("EVENT_SUMMON_SUCCESS", "normal_summon", "field"),
        ("EVENT_SPSUMMON_SUCCESS", "special_summon", "field"),
        ("EVENT_FLIP", "flip", "field"),
    )}
    if rule["type"] & constants["EFFECT_TYPE_ACTIVATE"]:
        name, zone = "spell_trap_activation", "spell_trap"
    elif rule["type"] & constants["EFFECT_TYPE_SINGLE"] and event in events:
        name, zone = events[event]
    else:
        areas = {constants[key]: area for key, area in (("LOCATION_HAND", "hand"), ("LOCATION_MZONE", "field"),
                 ("LOCATION_SZONE", "spell_trap"), ("LOCATION_GRAVE", "grave"), ("LOCATION_REMOVED", "banished"))}
        name, zone = "registered_effect", areas.get(rule["range"])
    return dict(event=name, zone=zone, event_code=event, rule_condition=rule["callbacks"].get("condition")) if zone else None


def _static_record(lua, rule, code, ordinal, rows, cards_sha256):
    constants, callbacks = lua._constants, rule["callbacks"]
    source = callbacks.get("operation")
    if not source or rule["scope"] != "card":
        return None
    kind, event, area = rule["type"], rule["event"], rule["range"]
    fusion = (rule["category"] & constants.get("CATEGORY_FUSION_SUMMON", 0)
              and "target" in callbacks and "cost" not in callbacks)
    if "condition" in callbacks and not fusion:
        return None
    if fusion:
        trigger = _fusion_trigger(rule, constants)
        if trigger is None:
            return None
    elif kind & constants["EFFECT_TYPE_ACTIVATE"] and event == constants["EVENT_FREE_CHAIN"]:
        trigger = dict(event="spell_trap_activation", zone="spell_trap")
    elif (kind & constants["EFFECT_TYPE_QUICK_O"] and event == constants["EVENT_FREE_CHAIN"]
          and area == constants["LOCATION_HAND"]):
        trigger = dict(event="quick_effect", zone="hand")
    elif (kind & constants["EFFECT_TYPE_SINGLE"] and event in (
            constants["EVENT_SUMMON_SUCCESS"], constants["EVENT_FLIP"])
          and rows[code]["type"] & constants["TYPE_MONSTER"] and 1 <= rows[code]["level"] <= 4):
        trigger = dict(event="normal_summon" if event == constants["EVENT_SUMMON_SUCCESS"] else "flip",
                       zone="field")
    else:
        return None
    ref = f"{source['file']}:{source['lines'][0]}"
    cost_rows = []
    if "cost" in callbacks:
        cost_source = callbacks["cost"]
        cost, _ = lua.registered_callback(cost_source)
        if trigger["zone"] != "hand" or not _handler_send_cost(cost, constants):
            return None
        cost_rows.append(dict(kind="send_grave", from_zones=["hand"], to_zone="grave", reason="cost",
            quantity=1, owner="self", subject="this_card", source_card_id=code,
            selector_query={"predicate": {"field": "card_ids", "value": [code]}},
            source=f"{cost_source['file']}:{cost_source['lines'][0]}"))
    if fusion:
        output = dict(kind="fusion_summon", from_zones=["extra"], to_zone="field", quantity=1, random=False)
    else:
        operation, functions = lua.registered_callback(source)
        if "target" in callbacks:
            target, _ = lua.registered_callback(callbacks["target"])
            output = _checked_deck_output(operation, target, constants) or _deck_selection(
                operation, target, functions, constants)
        else:
            output = _deck_output(operation, constants) or _summon_draw(operation, functions, constants)
    if output is None:
        return None
    if "selector_query" in output:
        output["selector_query"] = lua.inventory_query(output["selector_query"], rows)
        if output["selector_query"] is None:
            return None
    rule_id = "native-static:" + digest((code, rule))
    count = [dict(code=rule["count_code"], maximum=rule["count_maximum"], persistent=rule["count_persistent"],
                  source=ref)] if rule["count_maximum"] else []
    record = dict(record_version="native-construction-static-v1", semantic_version="native-construction-static-v1",
        card_id=code, cards_sha256=cards_sha256, text_sha256=digest(rule), effect_index=ordinal,
        effect_key=rule_id, relation_ref=rule_id, source_text=ref,
        scope="spell_trap" if kind & constants["EFFECT_TYPE_ACTIVATE"] else "monster",
        trigger=dict(trigger, source=ref), conditions={"source": ref, "status": "recognized"},
        costs=cost_rows, targets=[], operations=[dict(output, owner="self", reason="effect",
            source=ref, phase="resolution", block_id=rule_id + ":operation:0")],
        count_limits=count, restrictions=[], card_restrictions=[], printed_materials=[],
        unknown=[], block_view={"status": "native_static", "blocks": [], "unknown": []},
        rule_registration=rule)
    if fusion:
        record["fusion_stock_location"] = constants[{"spell_trap": "LOCATION_SZONE", "hand": "LOCATION_HAND",
            "field": "LOCATION_MZONE", "grave": "LOCATION_GRAVE", "banished": "LOCATION_REMOVED"}[trigger["zone"]]]
    return record


def static_rule_specs(assets, code, initialized, dependencies):
    """Return the scoreable rule records and the remaining source questions."""
    lua = assets.effect_lua_source
    constants = lua._constants
    effects, sources = [], []
    rules = initialized["native"]
    counts = Counter(map(digest, rules))
    normal = {}
    alternate = []
    for ordinal, rule in enumerate(rules):
        if (rule["scope"] == "card" and rule["type"] == constants["EFFECT_TYPE_SINGLE"] and not rule["category"]
                and rule["event"] in (constants.get("EFFECT_FUSION_MATERIAL"), constants.get("EFFECT_REVIVE_LIMIT"))):
            sources.append(dict(rule=rule, status="summon_rule"))
            continue
        if counts[digest(rule)] > 1:
            sources.append(dict(rule=rule, status="unknown", reason="ambiguous_registration"))
            continue
        record = _static_record(lua, rule, code, ordinal, assets.rows, assets.receipt["resources"]["cards"])
        if record is not None:
            if "fusion_stock_location" in record:
                effects.append(dict(record=record, requirements=[], unknown=[]))
                sources.append(dict(rule=rule, effect=record["effect_key"], status="unknown",
                                    reason="fusion_operation_scope_unreviewed"))
                continue
            operation, = record["operations"]
            spent = record["costs"] or [dict(source=record["source_text"], quantity=1,
                owner="self", from_zones=[record["trigger"]["zone"].replace("spell_trap", "field")],
                selector_query={"predicate": {"field": "card_ids", "value": [code]}})]
            result = dict(operation, selector_query=operation.get("selector_query", {"type": 7}),
                          exclude_source_copy=True, source_card_id=code)
            requirements = [dependencies.item_requirement(item, "costs" if record["costs"] else "source")
                            for item in spent]
            requirements.append(dependencies.item_requirement(result, "operations"))
            if all(requirements):
                effects.append(dict(record=record, requirements=requirements, unknown=[]))
                sources.append(dict(rule=rule, status="function", effect=record["effect_key"]))
                shared_count = rule["count_maximum"] and rule["count_code"] & 0x0fffffff not in (0, 1)
                if shared_count and rule["event"] == constants["EVENT_SUMMON_SUCCESS"]:
                    normal[digest(dict(rule, event=constants["EVENT_SPSUMMON_SUCCESS"]))] = record
                continue
        if (not rule["callbacks"] and not rule["category"]
                and rule["type"] & constants["EFFECT_TYPE_ACTIVATE"] and rule["event"] == constants["EVENT_FREE_CHAIN"]):
            sources.append(dict(rule=rule, status="activation_only"))
        else:
            sources.append(dict(rule=rule, status="unknown", reason="unmapped_static_rule"))
            if rule["event"] == constants["EVENT_SPSUMMON_SUCCESS"]:
                alternate.append(sources[-1])
    for row in alternate:
        if (record := normal.get(digest(row["rule"]))) is not None:
            row.update(status="alternate_trigger", effect=record["effect_key"])
            row.pop("reason")
            record["trigger"]["alternative_events"] = ["special_summon"]
    return effects, dict(diagnostics=initialized["diagnostics"], registrations=sources)
