"""Read effect registrations and supported callbacks from locked mycard Lua sources."""

from collections import defaultdict
from dataclasses import dataclass, field
from functools import cache
from hashlib import sha256
from operator import add, and_, lt, mul, or_, sub
from pathlib import Path
import re

from .validation import ContractError


LUA_EFFECT_VERSION = "mycard-effect-registration-v10"
_TABLE, _CARD = object(), object()
_CALLBACKS = {
    "SetCondition": "condition", "SetCost": "cost", "SetTarget": "target",
    "SetOperation": "operation", "SetValue": "value",
}
_NUMERIC = {
    "SetType": "type", "SetCode": "event_code", "SetRange": "range",
    "SetProperty": "property", "SetCategory": "category", "SetReset": "reset",
}
_METADATA = {
    "SetLabel", "SetLabelObject", "SetHintTiming", "SetTargetRange",
    "SetAbsoluteRange", "SetOwnerPlayer",
}
_EVENTS = {
    "EVENT_SUMMON_SUCCESS": "normal_summon",
    "EVENT_SPSUMMON_SUCCESS": "special_summon",
    "EVENT_TO_GRAVE": "sent_to_grave",
}
_OPERATORS = {"+": add, "-": sub, "*": mul, "|": or_, "&": and_, "<": lt}


@cache
def _lua_language():
    from tree_sitter import Language
    from tree_sitter_lua import language

    return Language(language())


def _parse(source):
    from tree_sitter import Parser

    return Parser(_lua_language()).parse(source).root_node


def _text(node):
    return node.text.decode("utf-8", errors="replace") if node is not None else ""


def _children(node):
    return [child for child in node.named_children if child.type != "comment"] if node else []


def _name(node):
    if node is None:
        return ""
    if node.type == "identifier":
        return _text(node)
    if node.type in ("dot_index_expression", "method_index_expression"):
        table = node.child_by_field_name("table")
        base = _text(table) if table and table.type == "identifier" else ""
        member = node.child_by_field_name("field") or node.child_by_field_name("method")
        if base and member:
            separator = "." if node.type == "dot_index_expression" else ":"
            return base + separator + _text(member)
    return ""


def _table_field(node, bindings):
    prefix, dot, field_name = _name(node).partition(".")
    return dot and "." not in field_name and bindings.get(prefix) is _TABLE


def _span(node):
    return [node.start_byte, node.end_byte]


def _call(node):
    if node is None or node.type != "function_call":
        return "", []
    return _name(node.child_by_field_name("name")), _children(node.child_by_field_name("arguments"))


def _assignment(node):
    local = node.type == "variable_declaration"
    if local:
        children = _children(node)
        node = children[0] if children else node
    if node.type == "variable_list":
        return local, node.children_by_field_name("name"), []
    if node.type == "assignment_statement":
        names, *values = _children(node)
        return local, names.children_by_field_name("name"), values[0].children_by_field_name("value") if values else []
    return local, [], []


def _value(node, bindings, depth=0):
    if node is None or depth > 24:
        return None
    if node.type == "identifier":
        return bindings.get(_text(node))
    if node.type in ("true", "false"):
        return node.type == "true"
    if node.type == "number":
        value = _text(node)
        try:
            return int(value, 16 if value.lower().startswith("0x") else 10)
        except ValueError:
            return None
    if node.type == "parenthesized_expression":
        return _value(_children(node)[0], bindings, depth + 1)
    if node.type == "binary_expression":
        left = _value(node.child_by_field_name("left"), bindings, depth + 1)
        op = _text(node.child_by_field_name("operator"))
        if (op == "and" and left is False) or (op == "or" and left is not None and left is not False):
            return left
        right = _value(node.child_by_field_name("right"), bindings, depth + 1)
        if op in ("and", "or") and left is not None:
            return right
        if op in _OPERATORS and type(left) is int and type(right) is int:
            return _OPERATORS[op](left, right)
    return None


def _unwrapped(node):
    while node is not None and node.type == "parenthesized_expression":
        node, = _children(node)
    return node


def _return_expression(statements):
    if len(statements) == 1 and statements[0].type == "return_statement":
        values = _children(statements[0])
        if len(values) == 1:
            expressions = _children(values[0])
            if len(expressions) == 1:
                return expressions[0]
    return None


def _binary(node, operator):
    node = _unwrapped(node)
    if (node is not None and node.type == "binary_expression"
            and _text(node.child_by_field_name("operator")) == operator):
        return node.child_by_field_name("left"), node.child_by_field_name("right")
    return None, None


def _conjuncts(node, depth=0):
    left, right = _binary(node, "and")
    if left is None:
        return [_unwrapped(node)]
    if depth == 8:
        return []
    a, b = _conjuncts(left, depth + 1), _conjuncts(right, depth + 1)
    return a + b if a and b else []


def _integer_value(node, bindings):
    value = _value(node, bindings)
    return value if type(value) is int else None


def _selection_query(node, card, constants, depth=0):
    if node is None or depth > 8:
        return None
    node = _unwrapped(node)
    for operator in ("and", "or"):
        left, right = _binary(node, operator)
        if left is None:
            continue
        a, b = (_selection_query(item, card, constants, depth + 1) for item in (left, right))
        if not a or not b:
            return None
        if operator == "or":
            return {"any": [a, b]}
        return dict(a, **b) if not a.keys() & b.keys() else None
    if node.type == "unary_expression" and _text(node.child_by_field_name("operator")) == "not":
        name, args = _call(_unwrapped(node.child_by_field_name("operand")))
        ids = [_integer_value(arg, constants) for arg in args]
        if name == f"{card}:IsCode" and 1 <= len(ids) <= 4 and all(
                code is not None and 0 < code < 2**32 for code in ids):
            return {"exclude_rule_codes": sorted(set(ids))}
        if name == f"{card}:IsLevel" and len(ids) == 1 and ids[0] is not None and 1 <= ids[0] <= 255:
            return {"exclude_level": ids[0]}
        return None
    name, args = _call(node)
    receiver, _, method = name.partition(":")
    if receiver != card:
        return None
    values = [_value(arg, constants) for arg in args]
    if not values or not all(type(value) is int and 0 < value < 2**32 for value in values):
        return None
    if method == "IsSetCard" and len(values) <= 4 and all(v <= 0xffff and v & 0xfff for v in values):
        options = [{"setcode": value} for value in dict.fromkeys(values)]
        return options[0] if len(options) == 1 else {"any": options}
    if len(values) == 1:
        value, = values
        fields = {"IsType": "type", "IsRace": "race_any", "IsAttribute": "attribute_any"}
        if method in fields:
            return {fields[method]: value}
        if method == "IsLevelBelow" and value <= 255:
            return {"level_between": [1, value]}
    return None


def _check_body(statement):
    return (_children(statement.child_by_field_name("consequence"))
            if statement.type == "if_statement" and not statement.child_by_field_name("alternative") else [])


def _nonempty_group(node, group, constants):
    left, right = _binary(node, ">")
    if left is None or _integer_value(right, constants) != 0:
        return False
    left = _unwrapped(left)
    if left.type == "unary_expression" and _text(left.child_by_field_name("operator")) == "#":
        return _name(left.child_by_field_name("operand")) == group
    return _call(left) == (f"{group}:GetCount", [])


def _callback(registration, role, functions, tables):
    reference = registration.get(role, {})
    name = reference.get("reference", "")
    namespace, dot, _ = name.partition(".")
    node = functions.get(name) if reference.get("definition") and dot and namespace in tables else None
    return name, node, reference.get("byte_span", registration["registration_span"])


def _skip_unused_handler(statements, effect, reserved):
    """Ignore a handler read only when its local name never reaches processing."""
    if not statements:
        return statements
    name, value = _local_value(statements[0])
    if (not name or _call(value) != (f"{effect}:GetHandler", []) or name in (effect, "Card", "Duel")
            or name in reserved):
        return statements
    pending = list(statements[1:])
    while pending:
        node = pending.pop()
        if node.type == "identifier" and _text(node) == name:
            return statements
        pending.extend(_children(node))
    return statements[1:]


def _chosen_object_available(test, truth, group, subject, constants):
    if test is None:
        return False
    if _name(test) == subject and subject != group:
        return truth is True
    if _nonempty_group(test, group, constants):
        return truth is True
    for operator, when in (("==", False), ("<=", False), ("<", False), ("~=", True), (">=", True)):
        left, right = _binary(test, operator)
        if left is None or truth is not when:
            continue
        left = _unwrapped(left)
        size = (_call(left) == (f"{group}:GetCount", []) or left.type == "unary_expression"
                and _text(left.child_by_field_name("operator")) == "#"
                and _name(left.child_by_field_name("operand")) == group)
        if size and _integer_value(right, constants) == (1 if operator in ("<", ">=") else 0):
            return True
    return False


def _deck_send(registration, functions, constants, tables, shadowed, local_ids):
    """Recognize the one direct, fixed-count Deck-to-GY selection at resolution."""
    operation, body, binding = _callback(registration, "operation", functions, tables)
    target, check, check_binding = _callback(registration, "target", functions, tables)

    def unresolved(reason, function, node, span):
        return dict(status="unresolved", reason=reason, function=function,
                    byte_span=_span(node) if node is not None else span)

    if body is None:
        return unresolved("unresolved_operation_callback", operation, body, binding)
    flag, property_flags = constants.get("EFFECT_FLAG_CARD_TARGET"), registration.get("property", 0)
    if type(flag) is not int or type(property_flags) is not int or property_flags & flag:
        return unresolved("card_targeting_or_unresolved_property", operation, body, binding)
    params = list(map(_text, body.child_by_field_name("parameters").children_by_field_name("name")))
    if len(params) < 2 or len(params) != len(set(params)) or {"Duel", "Card"} & (set(params) | shadowed):
        return unresolved("unsupported_operation_parameters", operation, body, binding)
    player = params[1]
    local_constants = {key: value for key, value in constants.items() if key not in params}
    deck, by_effect = constants.get("LOCATION_DECK"), constants.get("REASON_EFFECT")
    effect = params[0]
    statements = list(_processing_statements(_children(body.child_by_field_name("body")),
                                             local_constants, player, effect))
    statements = _skip_unused_handler(statements, effect, set(params) | set(local_constants) | tables)
    if not statements:
        return unresolved("unsupported_operation_flow", operation, body, binding)
    selected, *remaining = statements
    group, selection = _local_value(selected)
    call, args = _call(selection)
    first = False
    if call != "Duel.SelectMatchingCard":
        receiver = _member_call(selection, "GetFirst", local_constants)
        call, args = _call(receiver)
        if call == "Duel.SelectMatchingCard":
            selection, first = receiver, True
    if call != "Duel.SelectMatchingCard" or not group:
        return unresolved("unsupported_resolution_selection", operation, selected, binding)
    filter_arg = args[1] if len(args) == 8 else None
    filter_name = _name(filter_arg)
    namespace = filter_name.partition(".")[0]
    reserved = set(params) | set(local_constants) | tables | {"Duel", "Card"}
    if not (len(args) == 8 and _name(args[0]) == _name(args[2]) == player
            and filter_name and namespace not in params
            and type(deck) is int and _integer_value(args[3], local_constants) == deck
            and _integer_value(args[4], local_constants) == 0 and args[7].type == "nil"
            and group not in reserved):
        return unresolved("unsupported_selection_arguments", operation, selection, binding)
    quantity, maximum = [_value(arg, local_constants) for arg in args[5:7]]
    if (type(quantity) is not int or type(maximum) is not int or not 1 <= quantity == maximum <= 255
            or first and quantity != 1):
        return unresolved("variable_or_unresolved_selection_count", operation, selection, binding)

    # The shared guard reader distinguishes real early returns from client hints.
    # This operation can transfer the whole selected group, or its only member.
    steps = _processing_steps(remaining, local_constants, player, effect)
    if not steps:
        reason = "unsupported_send_branch" if remaining and remaining[0].type == "if_statement" else "unsupported_operation_flow"
        return unresolved(reason, operation, remaining[0] if remaining else body, binding)
    subject = group
    if len(steps) >= 2 and steps[0][1] is None:
        alias, value = _local_value(steps[0][0])
        if (alias and alias not in reserved and alias != group and not first and quantity == 1
                and _literal_call(value, local_constants, f"{group}:GetFirst")):
            subject = alias
            steps = steps[1:]
    *guards, (send, direct) = steps
    if (direct is not None or len(guards) > 1
            or any(not (first and _name(test) == group and truth is True
                        or _chosen_object_available(test, truth, group, subject, local_constants))
                   for test, truth in guards)):
        return unresolved("unsupported_send_branch", operation, steps[0][0], binding)
    call, movement = _call(send)
    same_object = len(movement) == 2 and (
        _name(movement[0]) == subject if subject != group or first
        else _name(movement[0]) == group or quantity == 1 and _literal_call(
            movement[0], local_constants, f"{group}:GetFirst"))
    if (call != "Duel.SendtoGrave" or not same_object
            or type(by_effect) is not int or _integer_value(movement[1], local_constants) != by_effect):
        return unresolved("not_the_selected_group_sent_by_effect", operation, send, binding)

    if check is None:
        return unresolved("unresolved_activation_check_callback", target, check, check_binding)
    params = list(map(_text, check.child_by_field_name("parameters").children_by_field_name("name")))
    check_constants = {key: value for key, value in constants.items() if key not in params}
    if len(params) not in (9, 10) or {"Duel", "Card", namespace} & set(params) or len(set(params)) != len(params):
        return unresolved("unsupported_or_different_activation_check", target, check, check_binding)
    statements = list(_processing_statements(_children(check.child_by_field_name("body")),
                                             check_constants, params[1], params[0]))
    statements = _skip_unused_handler(statements, params[0], set(params) | set(check_constants) | tables)
    guard = statements[0] if statements else check
    left, right = _binary(guard.child_by_field_name("condition"), "==")
    exists = _return_expression(_check_body(guard))
    call, args = _call(exists)
    if not (_name(left) == params[8] and _integer_value(right, check_constants) == 0
            and call == "Duel.IsExistingMatchingCard" and len(args) == 6 and _name(args[0]) == filter_name
            and _name(args[1]) == params[1] and _integer_value(args[2], check_constants) == deck
            and _integer_value(args[3], check_constants) == 0 and _integer_value(args[4], check_constants) == quantity
            and args[5].type == "nil"):
        return unresolved("unsupported_or_different_activation_check", target, guard, check_binding)
    if statements[1:]:
        metadata = statements[1]
        call, args = _call(metadata)
        if (len(statements) != 2 or call != "Duel.SetOperationInfo" or len(args) != 6
                or args[2].type != "nil" or _name(args[4]) != params[1]
                or any(type(_value(args[i], check_constants)) is not int for i in (0, 1, 3, 5))):
            return unresolved("additional_activation_processing", target, metadata, check_binding)

    if filter_name == "Card.IsAbleToGrave":
        query, filter_span = {"selector": "卡"}, _span(filter_arg)
    else:
        definition = functions.get(filter_name) if filter_name.partition(".")[0] in tables else None
        if definition is None:
            return unresolved("unresolved_selection_filter", filter_name, filter_arg, binding)
        params = definition.child_by_field_name("parameters").children_by_field_name("name")
        expr = _return_expression(_children(definition.child_by_field_name("body")))
        if len(params) != 1 or expr is None:
            return unresolved("unsupported_filter_body", filter_name, definition, binding)
        card = _text(params[0])
        filter_constants = {key: value for key, value in constants.items() if key != card}
        filter_constants.update({key: value for key, (value, start) in local_ids.items()
                                 if key != card and start < definition.start_byte})
        query, able = {}, False
        for term in _conjuncts(expr):
            if _call(term) == (f"{card}:IsAbleToGrave", []):
                able = True
                continue
            predicate = _selection_query(term, card, filter_constants)
            if not predicate or query.keys() & predicate.keys():
                return unresolved("unsupported_filter_predicate", filter_name, term, binding)
            query.update(predicate)
        if not able:
            return unresolved("missing_send_eligibility_check", filter_name, expr, binding)
        query = query or {"selector": "卡"}
        filter_span = _span(expr)
    return dict(status="resolved", selector_query=query, quantity=quantity,
                selection=dict(function=operation, byte_span=_span(selection), phase="resolution",
                               owner="self", from_zones=["deck"], targets=False),
                activation_check=dict(function=target, byte_span=_span(exists), minimum=quantity),
                transfer=dict(function=operation, byte_span=_span(send), to_zone="grave", reason="effect"),
                filter=dict(function=filter_name, byte_span=filter_span, runtime_check="Card.IsAbleToGrave"))


_COST_LOCATIONS = {"HAND": "hand", "MZONE": "field", "SZONE": "field",
                   "FZONE": "field", "PZONE": "field"}


def _cost_locations(mask, constants):
    if type(mask) is not int or mask <= 0:
        return []
    locations = []
    for name in _COST_LOCATIONS:
        bit = constants.get("LOCATION_" + name)
        if type(bit) is int and mask & bit:
            locations.append(name)
            mask &= ~bit
    return locations if mask == 0 else []


def _self_send_group(steps, checks, handler, player, functions, constants, reserved, tables):
    """Read a fixed companion selection explicitly excluding the handler."""
    if len(steps) not in (2, 3):
        return None
    group, selection = _local_value(steps[0])
    companions, attached = _binary(selection, "+")
    if not group or group in reserved or group in constants:
        return None
    if len(steps) == 2:
        if not handler(attached):
            return None
        selection = companions
    else:
        name, args = _call(steps[1])
        if name != f"{group}:AddCard" or len(args) != 1 or not handler(args[0]):
            return None
    name, args = _call(_unwrapped(selection))
    if (name != "Duel.SelectMatchingCard" or len(args) < 8
            or _name(args[0]) != player or _name(args[2]) != player or not handler(args[7])):
        return None
    mask, opponent, minimum, maximum = (_integer_value(arg, constants) for arg in args[3:7])
    locations = _cost_locations(mask, constants)
    zones = list(dict.fromkeys(_COST_LOCATIONS[name] for name in locations))
    if not zones or opponent != 0 or minimum is None or minimum <= 0 or minimum != maximum:
        return None
    ref = _name(args[1])
    if len(checks) != 1 or any(not (handler(arg) or _name(arg) == player) for arg in args[8:]):
        return None
    check, checked = _call(_unwrapped(checks[0]))
    if (check != "Duel.IsExistingMatchingCard" or len(checked) != len(args) - 2
            or _name(checked[0]) != ref or _name(checked[1]) != player
            or [_integer_value(arg, constants) for arg in checked[2:5]] != [mask, 0, minimum]
            or not handler(checked[5])
            or any(not (handler(a) and handler(b) or _name(a) == _name(b) == player)
                   for a, b in zip(checked[6:], args[8:]))
            or not _literal_call(steps[-1], constants, "Duel.SendtoGrave", group, constants["REASON_COST"])):
        return None

    free_zone = None
    if ref == "Card.IsAbleToGraveAsCost":
        if len(args) != 8:
            return None
        query, filter_span = {"selector": "卡"}, None
    else:
        definition = functions.get(ref) if ref.partition(".")[0] in tables else None
        if definition is None:
            return None
        params = list(map(_text, definition.child_by_field_name("parameters").children_by_field_name("name")))
        if (len(params) != len(args) - 7 or not params or len(set(params)) != len(params)
                or set(params) & {"Duel", "Card", "Group"}):
            return None
        card = params[0]
        filters = _conjuncts(_return_expression(_children(definition.child_by_field_name("body"))))
        if not any(_literal_call(term, constants, f"{card}:IsAbleToGraveAsCost") for term in filters):
            return None
        query = {}
        local = {key: value for key, value in constants.items() if key not in params}
        for term in filters:
            if _literal_call(term, local, f"{card}:IsAbleToGraveAsCost"):
                continue
            if _literal_call(term, local, f"{card}:IsFaceup"):
                query["face_up"] = True
                continue
            lhs, rhs = _binary(term, ">")
            call, supplied = _call(_unwrapped(lhs))
            if (len(params) == 3 and handler(args[8]) and _name(args[9]) == player
                    and call == "Duel.GetMZoneCount" and len(supplied) == 2
                    and _name(supplied[0]) == params[2] and _integer_value(rhs, local) == 0
                    and _literal_call(supplied[1], local, "Group.FromCards", card, params[1])):
                free_zone = _span(term)
                continue
            filter_query = _selection_query(term, card, local)
            if filter_query is None or query.keys() & filter_query.keys():
                return None
            query.update(filter_query)
        if not query:
            query["selector"] = "卡"
        filter_span = _span(definition)
    return dict(kind="send_grave", quantity=minimum, from_zones=zones, range=mask,
                selector_query=query, filter_span=filter_span, check_span=_span(checks[0]),
                selection_span=_span(selection), requires_arrival=True, free_zone_check_span=free_zone)


def _payment_target_check(registration, functions, constants, tables):
    _, body, _ = _callback(registration, "target", functions, tables)
    if body is None:
        return None
    params = list(map(_text, body.child_by_field_name("parameters").children_by_field_name("name")))
    if len(params) not in (9, 10) or len(set(params)) != len(params) or "Duel" in params:
        return None
    effect, player, chk = params[0], params[1], params[8]
    local = {key: value for key, value in constants.items() if key not in params}
    checks, selections = [], []
    statements = _children(body.child_by_field_name("body"))
    for statement in _processing_statements(statements, local, player, effect):
        _, names, _ = _assignment(statement)
        if any(_name(name).split(".", 1)[0] in {"Duel", effect, player, chk, *local} for name in names):
            return None
        left, right = _binary(statement.child_by_field_name("condition"), "==")
        if _name(left) == chk and _integer_value(right, local) == 0:
            checks.extend(_conjuncts(_return_expression(_check_body(statement))))
        alias, value = _local_value(statement)
        call, args = _call(_unwrapped(value) if alias else statement)
        if call == "Duel.SelectTarget":
            selections.append((value if alias else statement, args))
    if len(selections) != 1:
        return None
    selection, args = selections[0]
    if len(args) < 8 or _name(args[0]) != player or _name(args[2]) != player:
        return None
    count = _integer_value(args[5], local)
    if count is None or count <= 0 or count != _integer_value(args[6], local):
        return None
    for test in checks:
        call, available = _call(test)
        if (call == "Duel.IsExistingTarget" and len(available) == len(args) - 2
                and _text(available[0]) == _text(args[1]) and _name(available[1]) == player
                and all(_integer_value(x, local) is not None and _integer_value(x, local) == _integer_value(y, local)
                        for x, y in zip(available[2:5], args[3:6]))
                and [_text(x) for x in available[6:]] == [_text(x) for x in args[8:]]):
            masks = [_integer_value(arg, local) for arg in args[3:5]]
            grave = local.get("LOCATION_GRAVE")
            self_grave = type(grave) is int and masks == [grave, 0]
            nil_exceptions = available[5].type == args[7].type == "nil"
            return dict(quantity=count, availability_span=_span(test), selection_span=_span(selection),
                        may_select_payment=self_grave and nil_exceptions)
    return None


def _self_send_cost(registration, functions, constants, tables, shadowed):
    """Follow the handler through precheck and payment in its SetCost callback."""
    name, body, binding = _callback(registration, "cost", functions, tables)

    def unresolved(reason, node=None):
        return dict(status="unresolved", reason=reason, function=name,
                    byte_span=_span(node) if node is not None else binding)

    if body is None:
        return unresolved("unresolved_cost_callback")
    mask = registration.get("range")
    locations = _cost_locations(mask, constants)
    if "range" not in registration and registration["event"] in ("normal_summon", "special_summon"):
        locations = ["MZONE"]
    zones = list(dict.fromkeys(_COST_LOCATIONS[name] for name in locations))
    if not zones:
        return unresolved("unsupported_cost_activation_range", body)
    params = list(map(_text, body.child_by_field_name("parameters").children_by_field_name("name")))
    if len(params) not in (9, 10) or len(set(params)) != len(params) or (
            {"Card", "Duel", "Group"} & (set(params) | shadowed)):
        return unresolved("unsupported_cost_parameters", body)
    effect, player, chk = params[0], params[1], params[8]
    local = {key: value for key, value in constants.items() if key not in params}
    by_cost = local.get("REASON_COST")
    if type(by_cost) is not int:
        return unresolved("unsupported_cost_reason", body)

    statements = list(_processing_statements(_children(body.child_by_field_name("body")), local, player, effect))
    aliases = set()

    def handler(node):
        return (_name(_unwrapped(node)) in aliases
                or _literal_call(node, local, f"{effect}:GetHandler"))

    while statements and statements[0].type == "variable_declaration":
        alias, value = _local_value(statements[0])
        if (not alias or alias in set(params) | aliases | tables | {"Duel", "Card", "Group"}
                or not handler(value)):
            return unresolved("unsupported_cost_handler_binding", statements[0])
        local.pop(alias, None)
        aliases.add(alias)
        statements.pop(0)
    if len(statements) < 2:
        return unresolved("unsupported_cost_flow", body)
    guard, *steps = statements
    left, right = _binary(guard.child_by_field_name("condition"), "==")
    if _name(right) == chk:
        left, right = right, left
    if _name(left) != chk or _integer_value(right, local) != 0:
        return unresolved("unsupported_cost_feasibility_check", guard)
    checks = _conjuncts(_return_expression(_check_body(guard)))
    able = [test for test in checks if handler(_member_call(test, "IsAbleToGraveAsCost", local))]
    if not able:
        return unresolved("unsupported_cost_feasibility_check", guard)

    companions = []
    tests = [test for test in checks if test not in able]
    movements = []
    extras = []
    for step in steps:
        call, args = _call(step)
        if call == "Duel.SendtoGrave" and len(args) == 2 and handler(args[0]):
            reason = _integer_value(args[1], local)
            if reason == by_cost:
                movements.append(step)
                continue
        extras.append(step)
    if len(movements) == 1:
        movement, = movements
        for step in extras:
            call, args = _call(step)
            if call == "Duel.PayLPCost" and len(args) == 2:
                amount = _integer_value(args[1], local)
                test = next((term for term in tests if _literal_call(term, local, "Duel.CheckLPCost", player, amount)), None)
                if (amount is not None and amount > 0 and _name(args[0]) == player and test is not None):
                    companions.append(dict(kind="pay_lp", quantity=amount, payment_span=_span(step)))
                    tests.remove(test)
                    continue
            if call == "Duel.DiscardHand" and len(args) == 5 and step.start_byte > movement.start_byte:
                amount = _integer_value(args[2], local)
                hand, discard = local.get("LOCATION_HAND"), local.get("REASON_DISCARD")
                test = next((term for term in tests if (pair := _call(term))[0] == "Duel.IsExistingMatchingCard"
                             and len(pair[1]) == 6 and handler(pair[1][-1])
                             and _name(pair[1][0]) == "Card.IsDiscardable" and _name(pair[1][1]) == player
                             and [_integer_value(arg, local) for arg in pair[1][2:5]] == [hand, 0, amount]), None)
                if (amount is not None and amount > 0 and type(discard) is int and type(hand) is int
                        and test is not None and _literal_call(step, local, "Duel.DiscardHand", player,
                                "Card.IsDiscardable", amount, amount, by_cost | discard)):
                    companions.append(dict(kind="discard", quantity=amount, from_zones=["hand"], payment_span=_span(step)))
                    tests.remove(test)
                    continue
            label, values = _call(step)
            if label == f"{effect}:SetLabelObject" and len(values) == 1 and (
                    handler(_member_call(values[0], "GetEquipTarget", local))):
                continue  # Preserve the reference to the equipped monster in the callback evidence.
            return unresolved("unsupported_cost_flow", step)
        for test in tests:
            if (handler(_member_call(test, "IsDiscardable", local))
                    or type(status := local.get("STATUS_EFFECT_ENABLED")) is int
                    and handler(_member_call(test, "IsStatus", local, status))):
                continue
            return unresolved("unsupported_cost_feasibility_check", guard)
    elif not movements:
        reserved = set(params) | aliases | tables | {"Duel", "Card", "Group"}
        companion = _self_send_group(steps, tests, handler, player, functions, local, reserved, tables)
        if companion is None:
            return unresolved("handler_not_sent_as_cost", steps[-1])
        companions.append(companion)
        movement = steps[-1]
    else:
        return unresolved("unsupported_cost_flow", body)

    return dict(status="resolved", function=name, byte_span=_span(body), subject="this_card", owner="self",
                quantity=1, range=mask, locations=locations, from_zones=zones,
                phase="activation_payment", to_zone="grave",
                reason="cost", requires_arrival=True, companions=companions,
                activation_check=dict(byte_span=_span(able[0]), runtime_check="Card.IsAbleToGraveAsCost"),
                transfer=dict(byte_span=_span(movement)))


def _literal_call(node, constants, name, *arguments):
    call, args = _call(_unwrapped(node))
    if call != name or len(args) != len(arguments):
        return False
    for arg, expected in zip(args, arguments):
        if expected is None:
            if arg.type != "nil":
                return False
        elif isinstance(expected, str):
            if _name(arg) != expected:
                return False
        else:
            actual = _value(arg, constants)
            if type(actual) is not type(expected) or actual != expected:
                return False
    return True


def _local_value(statement):
    local, names, values = _assignment(statement)
    if local and len(names) == len(values) == 1 and names[0].type == "identifier":
        return _text(names[0]), values[0]
    return "", None


def _early_return(statement):
    branch = _check_body(statement)
    if len(branch) == 1 and branch[0].type == "return_statement" and not _children(branch[0]):
        return statement.child_by_field_name("condition")
    return None


def _member_call(node, method, constants, *arguments):
    """Return the receiver of a chained method call with the given arguments."""
    node = _unwrapped(node)
    if node is None or node.type != "function_call":
        return None
    name = node.child_by_field_name("name")
    args = _children(node.child_by_field_name("arguments"))
    if (name is not None and name.type == "method_index_expression"
            and _text(name.child_by_field_name("method")) == method and len(args) == len(arguments)
            and all(type(_value(arg, constants)) is int and _value(arg, constants) == value
                    for arg, value in zip(args, arguments))):
        return name.child_by_field_name("table")
    return None


def _summon_chain_response(registration, functions, constants, tables):
    """Identify a direct response to a negatable opponent summon effect."""
    window = {"type": "EFFECT_TYPE_QUICK_O", "event_code": "EVENT_CHAINING", "range": "LOCATION_MZONE"}
    if any(symbol not in constants or registration.get(field) != constants[symbol]
           for field, symbol in window.items()):
        return False
    _, callback, _ = _callback(registration, "condition", functions, tables)
    if callback is None or "STATUS_BATTLE_DESTROYED" not in constants or "CATEGORY_SPECIAL_SUMMON" not in constants:
        return False
    params = callback.child_by_field_name("parameters").children_by_field_name("name")
    steps = _children(callback.child_by_field_name("body"))
    if len(params) != 8 or len(steps) != 2:
        return False
    effect, player, _, chain_player, link, chain_effect, _, _ = map(_text, params)
    guard, result = steps
    if _text(_return_expression(_check_body(guard))) != "false":
        return False
    battle, negatable = _binary(guard.child_by_field_name("condition"), "or")
    handler = _member_call(battle, "IsStatus", constants, constants["STATUS_BATTLE_DESTROYED"])
    negatable = _unwrapped(negatable)
    if (_call(handler) != (f"{effect}:GetHandler", []) or negatable is None
            or negatable.type != "unary_expression"
            or _text(negatable.child_by_field_name("operator")) != "not"
            or not _literal_call(negatable.child_by_field_name("operand"), constants, "Duel.IsChainNegatable", link)):
        return False
    category, opponent = _binary(_return_expression([result]), "and")
    left, right = _binary(opponent, "~=")
    return ({_name(left), _name(right)} == {chain_player, player}
            and _name(_member_call(category, "IsHasCategory", constants, constants["CATEGORY_SPECIAL_SUMMON"])) == chain_effect)


def _own_effect_sent_race(registration, functions, constants, tables):
    """Read a field trigger matching a race in the controller's sent group."""
    field, optional = (constants.get(key) for key in ("EFFECT_TYPE_FIELD", "EFFECT_TYPE_TRIGGER_O"))
    if (type(field) is not int or type(optional) is not int
            or registration.get("type") != (field | optional)
            or registration.get("event_code") != constants.get("EVENT_TO_GRAVE")
            or registration.get("range") != constants.get("LOCATION_MZONE")
            or not all(key in constants for key in ("EVENT_TO_GRAVE", "LOCATION_MZONE", "REASON_EFFECT"))):
        return None
    _, callback, _ = _callback(registration, "condition", functions, tables)
    if callback is None:
        return None
    params = callback.child_by_field_name("parameters").children_by_field_name("name")
    if len(params) < 3:
        return None
    _, player, event_group = map(_text, params[:3])
    exists = _return_expression(_children(callback.child_by_field_name("body")))
    name, args = _call(exists)
    if name != f"{event_group}:IsExists" or len(args) != 4:
        return None
    filter_name = _name(args[0])
    predicate = functions.get(filter_name)
    if (predicate is None or filter_name.partition(".")[0] not in tables
            or not _literal_call(exists, constants, name, filter_name, 1, None, player)):
        return None
    filter_params = predicate.child_by_field_name("parameters").children_by_field_name("name")
    if len(filter_params) != 2:
        return None
    card, controller = map(_text, filter_params)
    checks = _conjuncts(_return_expression(_children(predicate.child_by_field_name("body"))))
    if len(checks) != 3:
        return None
    reason = [node for node in checks if _literal_call(node, constants, f"{card}:IsReason", constants["REASON_EFFECT"])]
    controlled = [node for node in checks if any(_literal_call(node, constants, f"{card}:{method}", controller)
                  for method in ("IsControler", "IsController"))]
    if len(reason) != 1 or len(controlled) != 1:
        return None
    race_node, = [node for node in checks if node not in (*reason, *controlled)]
    method, args = _call(race_node)
    mask = _integer_value(args[0], constants) if len(args) == 1 else None
    if method == f"{card}:IsRace" and type(mask) is int and mask > 0 and mask & (mask - 1) == 0:
        return dict(race=mask, predicate_span=_span(predicate))
    return None


def _processing_statements(statements, constants, player, effect=None):
    """Remove client hints and operation announcements with simple arguments."""
    for statement in statements:
        name, args = _call(statement)
        if name == "Duel.Hint" and len(args) == 3:
            other, seat = _binary(args[1], "-")
            addressed = (_name(args[1]) == player or _integer_value(args[1], constants) in (0, 1)
                         or _integer_value(other, constants) == 1 and _name(seat) == player)
            description = (_integer_value(args[2], constants) is not None
                           or effect is not None and _literal_call(args[2], constants, f"{effect}:GetDescription"))
            if addressed and description and _integer_value(args[0], constants) is not None:
                continue
        if (name == "Duel.SetOperationInfo" and len(args) == 6
                and all(_integer_value(args[i], constants) is not None for i in (0, 1, 3, 5))
                and (args[2].type in ("nil", "identifier")
                     or effect is not None and _literal_call(args[2], constants, f"{effect}:GetHandler"))
                and (_integer_value(args[4], constants) is not None or _name(args[4]) == player)):
            continue
        yield statement


def _processing_steps(statements, constants, player, effect, depth=0):
    """Read the successful path through tail branches and early-return guards."""
    if depth == 8:
        return []

    def guard(node, truth, depth=0):
        node = _unwrapped(node)
        if node is None or depth == 8:
            return [(node, truth)]
        if node.type == "unary_expression" and _text(node.child_by_field_name("operator")) == "not":
            return guard(node.child_by_field_name("operand"), not truth, depth + 1)
        left, right = _binary(node, "and" if truth else "or")
        if left is not None:
            return guard(left, truth, depth + 1) + guard(right, truth, depth + 1)
        return [(node, truth)]

    steps = []
    statements = list(_processing_statements(statements, constants, player, effect))
    for position, statement in enumerate(statements):
        condition = _early_return(statement)
        if condition is not None:
            steps.extend(guard(condition, False))
        elif statement.type != "if_statement":
            steps.append((statement, None))
        elif position == len(statements) - 1 and (branch := _check_body(statement)):
            steps.extend(guard(statement.child_by_field_name("condition"), True))
            body = _processing_steps(branch, constants, player, effect, depth + 1)
            if not body:
                return []
            steps.extend(body)
        else:
            return []
    return steps


def _hand_send_before_summon(statements, variant, constants, effect, player):
    """Recognize the movement and the guard that tests its actual destination."""
    hand = constants["LOCATION_HAND"]
    grave = constants["LOCATION_GRAVE"]
    reason = constants["REASON_EFFECT"]

    def call(node, name, *args):
        return _literal_call(node, constants, name, *args)

    statements = list(_processing_statements(statements, constants, player))
    if variant == "discard_hand" and len(statements) == 3:
        send, moved, arrived = statements
        card, result = _local_value(moved)
        if not card or card in (effect, player, "Duel", "Card"):
            return None
        movement, shortfall = _binary(_early_return(send), "<")
        first = _member_call(result, "GetFirst", constants)
        location = _unwrapped(_early_return(arrived))
        if (call(movement, "Duel.DiscardHand", player, "Card.IsAbleToGrave", 1, 1, reason)
                and _integer_value(shortfall, constants) == 1
                and call(first, "Duel.GetOperatedGroup")
                and location is not None and location.type == "unary_expression"
                and _text(location.child_by_field_name("operator")) == "not"
                and call(location.child_by_field_name("operand"), f"{card}:IsLocation", grave)):
            return dict(selection_span=_span(movement), movement_span=_span(movement), arrival_span=_span(arrived))
    if variant == "select_and_send" and len(statements) == 4:
        available, selected, nonempty, send = statements
        group, selection = _local_value(selected)
        if not group or group in (effect, player, "Duel", "Card"):
            return None
        count, threshold = _binary(_early_return(available), "<=")
        size, empty = _binary(_early_return(nonempty), "==")
        failed, replaced = _binary(_early_return(send), "or")
        movement, zero = _binary(failed, "==")
        replaced = _unwrapped(replaced)
        first = (_member_call(replaced.child_by_field_name("operand"), "IsLocation", constants, grave)
                 if replaced is not None and replaced.type == "unary_expression"
                 and _text(replaced.child_by_field_name("operator")) == "not" else None)
        if (call(count, "Duel.GetFieldGroupCount", player, hand, 0) and _integer_value(threshold, constants) == 0
                and call(selection, "Duel.SelectMatchingCard", player, "Card.IsAbleToGrave", player, hand, 0, 1, 1, None)
                and call(size, f"{group}:GetCount") and _integer_value(empty, constants) == 0
                and call(movement, "Duel.SendtoGrave", group, reason) and _integer_value(zero, constants) == 0
                and call(first, f"{group}:GetFirst")):
            return dict(selection_span=_span(selection), movement_span=_span(movement), arrival_span=_span(replaced))
    return None


def _hand_send_cost(body, constants, tables):
    if body is None:
        return None
    params = tuple(map(_text, body.child_by_field_name("parameters").children_by_field_name("name")))
    if len(params) != 9 or len(set(params)) != 9 or set(params) & (tables | {"Card", "Duel"}):
        return None
    player, chk = params[1], params[-1]
    local = {key: value for key, value in constants.items() if key not in params}
    statements = list(_processing_statements(_children(body.child_by_field_name("body")), local, player))
    if len(statements) not in (2, 3) or not {"LOCATION_HAND", "REASON_COST"} <= local.keys():
        return None
    guard, *payment = statements
    movement = payment[-1]
    left, right = _binary(guard.child_by_field_name("condition"), "==")
    available = _return_expression(_check_body(guard))
    eligible = "Card.IsAbleToGraveAsCost"
    hand, cost = local["LOCATION_HAND"], local["REASON_COST"]
    if (_name(left) != chk or _integer_value(right, local) != 0
            or not _literal_call(available, local, "Duel.IsExistingMatchingCard", eligible, player, hand, 0, 1, None)):
        return None
    if len(payment) == 1:
        if not _literal_call(movement, local, "Duel.DiscardHand", player, eligible, 1, 1, cost):
            return None
    else:
        group, selection = _local_value(payment[0])
        if (not group or group in params or group in local or group in {"Card", "Duel"}
                or not _literal_call(selection, local, "Duel.SelectMatchingCard", player, eligible, player,
                                     hand, 0, 1, 1, None)
                or not _literal_call(movement, local, "Duel.SendtoGrave", group, cost)):
            return None
    return dict(phase="activation_payment", owner="self", from_zones=["hand"], to_zone="grave",
                quantity=1, reason="cost", requires_arrival=True,
                availability_span=_span(available), movement_span=_span(movement))


def _handler_grave_availability(checks, constants, effect, player):
    """Read the free-zone check and the same handler's ability to be sent."""
    def is_handler(node):
        return _literal_call(node, constants, f"{effect}:GetHandler")

    zone_check = [node for node in checks
                  if not is_handler(_member_call(node, "IsAbleToGrave", constants))]
    if len(zone_check) != 1:
        return False
    count, threshold = _binary(zone_check[0], ">")
    name, args = _call(_unwrapped(count))
    if (name == "Duel.GetMZoneCount" and len(args) == 2 and _name(args[0]) == player
            and is_handler(args[1]) and _integer_value(threshold, constants) == 0):
        return True
    threshold = _unwrapped(threshold)
    return (_literal_call(count, constants, "Duel.GetLocationCount", player, constants["LOCATION_MZONE"])
            and threshold is not None and threshold.type == "unary_expression"
            and _text(threshold.child_by_field_name("operator")) == "-"
            and _integer_value(threshold.child_by_field_name("operand"), constants) == 1)


def _grave_summon_target(body, functions, constants, tables, *, handler_send=False):
    params = tuple(map(_text, body.child_by_field_name("parameters").children_by_field_name("name")))
    if len(params) not in (9, 10) or len(set(params)) != len(params) or set(params) & (tables | {"Card", "Duel"}):
        return None
    effect, player, chk = params[0], params[1], params[8]
    local = {key: value for key, value in constants.items() if key not in params}
    zones = ("LOCATION_GRAVE", "LOCATION_HAND", "LOCATION_MZONE")
    if not all(key in local for key in zones):
        return None
    grave, hand, field = (local[key] for key in zones)

    def call(node, name, *args):
        return _literal_call(node, local, name, *args)

    statements = list(_processing_statements(_children(body.child_by_field_name("body")), local, player, effect))
    if len(statements) not in (2, 3):
        return None
    *redirect, check, chosen = statements
    group, selection = _local_value(chosen)
    _, args = _call(selection)
    filter_name = _name(args[1]) if len(args) == 10 else ""
    if (filter_name.partition(".")[0] not in tables or not group
            or group in params or group in local or group in {"Duel", "Card"}
            or not call(selection, "Duel.SelectTarget", player, filter_name, player, grave, 0, 1, 1, None, effect, player)):
        return None
    if redirect:
        if len(params) != 10:
            return None
        chkc = params[-1]
        redirect, = redirect
        change = _conjuncts(_return_expression(_check_body(redirect)))
        if (_name(redirect.child_by_field_name("condition")) != chkc or len(change) != 3
                or not any(call(term, f"{chkc}:IsLocation", grave) for term in change)
                or not any(call(term, f"{chkc}:IsControler", player) for term in change)
                or not any(call(term, filter_name, chkc, effect, player) for term in change)):
            return None
    left, right = _binary(check.child_by_field_name("condition"), "==")
    checks = _conjuncts(_return_expression(_check_body(check)))
    if _name(left) != chk or _integer_value(right, local) != 0 or len(checks) != 3:
        return None
    existing = [term for term in checks if call(term, "Duel.IsExistingTarget",
                filter_name, player, grave, 0, 1, None, effect, player)]
    if len(existing) != 1:
        return None
    other = [term for term in checks if term != existing[0]]
    if handler_send:
        if not _handler_grave_availability(other, local, effect, player):
            return None
        variant = "handler"
    else:
        slots = [term for term in other
                 if call(_binary(term, ">")[0], "Duel.GetLocationCount", player, field)
                 and _integer_value(_binary(term, ">")[1], local) == 0]
        if len(slots) != 1:
            return None
        term = next(term for term in other if term != slots[0])
        a, b = _binary(term, ">")
        name, args = _call(term)
        if call(a, "Duel.GetFieldGroupCount", player, hand, 0) and _integer_value(b, local) == 0:
            variant = "select_and_send"
        elif (name == "Duel.IsExistingMatchingCard" and len(args) == 6
                and call(args[5], f"{effect}:GetHandler") and _name(args[0]) == "Card.IsAbleToGrave"
                and _name(args[1]) == player and [_integer_value(arg, local) for arg in args[2:5]] == [hand, 0, 1]):
            variant = "discard_hand"
        else:
            return None

    definition = functions.get(filter_name)
    if definition is None:
        return None
    filter_params = tuple(map(_text, definition.child_by_field_name("parameters").children_by_field_name("name")))
    if len(filter_params) != 3 or len(set(filter_params)) != 3:
        return None
    card, e, tp = filter_params
    filter_constants = {key: value for key, value in constants.items() if key not in filter_params}
    expr = _return_expression(_children(definition.child_by_field_name("body")))
    terms = _conjuncts(expr)
    eligibility = [term for term in terms if _literal_call(term, filter_constants,
                   f"{card}:IsCanBeSpecialSummoned", e, 0, tp, False, False)]
    if len(eligibility) != 1:
        return None
    query = dict(type=1)
    for predicate in (term for term in terms if term != eligibility[0]):
        term = _selection_query(predicate, card, filter_constants)
        if term is None and handler_send:
            name, args = _call(_unwrapped(predicate))
            if name == f"{card}:IsLevel" and 1 <= len(args) <= 4:
                levels = [_integer_value(arg, filter_constants) for arg in args]
                if all(level is not None and 1 <= level <= 255 for level in levels):
                    ordered = sorted(set(levels))
                    if ordered == list(range(ordered[0], ordered[-1] + 1)):
                        term = {"level_between": [ordered[0], ordered[-1]]}
        if not term or term.keys() & query.keys():
            return None
        query.update(term)
    return variant, dict(selector_query=query, quantity=1, owner="self", zone="grave",
                         timing="activation", selection_span=_span(selection),
                         availability_span=_span(existing[0]), filter_span=_span(expr))


def _first_target_summon(steps, constants, effect, player):
    if len(steps) != 3:
        return None
    (evaluated, bound), (related, expected), (movement, done) = steps
    card, first = _local_value(evaluated)
    if (bound is not None or expected is not True or done is not None or not card
            or card in constants or card in {"Duel", "Card", effect, player}
            or not _literal_call(first, constants, "Duel.GetFirstTarget")
            or not _literal_call(related, constants, f"{card}:IsRelateToEffect", effect)
            or not _literal_call(movement, constants, "Duel.SpecialSummon", card, 0, player, player, False, False,
                                 constants["POS_FACEUP"])):
        return None
    # Use the surrounding guard's span, as in other callback evidence.
    relation = related
    while relation.parent is not None and relation.type != "if_statement":
        relation = relation.parent
    return dict(target_span=_span(evaluated), relation_span=_span(relation), movement_span=_span(movement))


def _handler_send_before_summon(steps, constants, effect, player):
    handler = None
    if steps and steps[0][1] is None:
        variable, value = _local_value(steps[0][0])
        if (variable and variable not in constants and variable not in (effect, player, "Duel", "Card")
                and _literal_call(value, constants, f"{effect}:GetHandler")):
            handler = variable
            steps = steps[1:]

    def is_handler(node):
        if handler is not None:
            return _name(node) == handler
        return _literal_call(node, constants, f"{effect}:GetHandler")

    def checks_handler(node, method, argument):
        if handler is not None:
            return _literal_call(node, constants, f"{handler}:{method}", argument)
        node = _unwrapped(node)
        if node is None or node.type != "function_call":
            return False
        name = node.child_by_field_name("name")
        args = _children(node.child_by_field_name("arguments"))
        return (name is not None and name.type == "method_index_expression" and _text(name.child_by_field_name("method")) == method
                and is_handler(name.child_by_field_name("table")) and len(args) == 1
                and (_name(args[0]) == argument if isinstance(argument, str)
                     else _integer_value(args[0], constants) == argument))

    # Reading the chosen card is safe on either side of the movement. Checking
    # its association must still follow the required movement and actual arrival.
    first = next((i for i, (node, truth) in enumerate(steps) if truth is None
                  and _literal_call(_local_value(node)[1], constants, "Duel.GetFirstTarget")), None)
    if first is None or first >= len(steps) - 2:
        return None
    target, _ = _local_value(steps[first][0])
    if target == handler:
        return None
    summon = _first_target_summon([steps[first], *steps[-2:]], constants, effect, player)
    guards = [step for i, step in enumerate(steps[:-2]) if i != first]
    if summon is None or len(guards) not in (3, 4):
        return None
    (related, required), *send, (arrived, arrived_expected) = guards
    if (required is not True or not checks_handler(related, "IsRelateToEffect", effect)
            or arrived_expected is not True
            or not checks_handler(arrived, "IsLocation", constants["LOCATION_GRAVE"])):
        return None

    comparison, truth = send[-1]
    operation, zero = _binary(comparison, "~=" if truth else "==")
    if operation is None and truth is True:
        operation, zero = _binary(comparison, ">")
    if truth is None or _integer_value(zero, constants) != 0:
        return None
    movement = operation
    if len(send) == 2:
        assignment, assigned = send[0]
        count, movement = _local_value(assignment)
        if (assigned is not None or not count or _name(operation) != count
                or count in constants or count in {handler, effect, player, "Duel", "Card"}):
            return None
    name, args = _call(_unwrapped(movement))
    if (name != "Duel.SendtoGrave" or len(args) != 2 or not is_handler(args[0])
            or _integer_value(args[1], constants) != constants["REASON_EFFECT"]):
        return None
    return dict(subject="this_card", phase="resolution", owner="self", from_zones=["field"],
                to_zone="grave", quantity=1, reason="effect", requires_arrival=True,
                relation_span=_span(related), movement_span=_span(movement), arrival_span=_span(arrived)), summon


def _preselected_grave_summon(registration, functions, constants, tables, shadowed):
    required = ("LOCATION_HAND", "LOCATION_GRAVE", "LOCATION_MZONE", "REASON_EFFECT",
                "EFFECT_FLAG_CARD_TARGET", "POS_FACEUP", "EFFECT_TYPE_ACTIVATE", "EVENT_FREE_CHAIN")
    if shadowed or any(type(constants.get(name)) is not int for name in required):
        return None
    event = registration["event"]
    if (registration.get("type") == constants["EFFECT_TYPE_ACTIVATE"]
            and registration.get("event_code") == constants["EVENT_FREE_CHAIN"] and "range" not in registration):
        event = "card_activation"
    elif event != "own_main_phase" or registration.get("range") != constants["LOCATION_MZONE"]:
        return None
    if (registration.get("property") != constants["EFFECT_FLAG_CARD_TARGET"]
            or any(role in registration for role in ("condition", "value"))):
        return None
    handler_send = "cost" in registration
    if handler_send and (event != "own_main_phase" or type(constants.get("REASON_COST")) is not int):
        return None
    _, target, _ = _callback(registration, "target", functions, tables)
    _, operation, _ = _callback(registration, "operation", functions, tables)
    if target is None or operation is None:
        return None
    observed = _grave_summon_target(target, functions, constants, tables, handler_send=handler_send)
    if observed is None:
        return None
    variant, selection = observed
    params = tuple(map(_text, operation.child_by_field_name("parameters").children_by_field_name("name")))
    if len(params) != 8 or len(set(params)) != 8 or set(params) & {"Duel", "Card"}:
        return None
    effect, player = params[:2]
    local = {key: value for key, value in constants.items() if key not in params}
    statements = list(_processing_statements(_children(operation.child_by_field_name("body")), local, player))
    if not all(key in local for key in required):
        return None
    if handler_send:
        _, cost, _ = _callback(registration, "cost", functions, tables)
        payment = _hand_send_cost(cost, constants, tables)
        processing = _handler_send_before_summon(_processing_steps(statements, local, player, effect), local, effect, player)
        if payment is None or processing is None:
            return None
        movement, summon = processing
        selection["availability_timing"] = "before_activation_payment"
        return dict(event=event, target=selection, hand_cost=payment, handler_send=movement, summon=summon)
    movement = _hand_send_before_summon(statements[:-2], variant, local, effect, player)
    summon = _first_target_summon(_processing_steps(statements[-2:], local, player, effect), local, effect, player)
    if movement is None or summon is None:
        return None
    return dict(event=event, target=selection, hand_send=dict(movement, phase="resolution",
        owner="self", from_zones=["hand"], to_zone="grave", quantity=1, reason="effect",
        requires_arrival=True), summon=summon)


def _intrinsic_grave_summon_lock(registration, constants):
    fields = {"type": "EFFECT_TYPE_SINGLE", "range": "LOCATION_GRAVE", "event_code": "EFFECT_SPSUMMON_CONDITION"}
    uncopyable, cannot_disable, single_range = (
        constants.get(name) for name in ("EFFECT_FLAG_UNCOPYABLE", "EFFECT_FLAG_CANNOT_DISABLE", "EFFECT_FLAG_SINGLE_RANGE"))
    if not all(type(flag) is int for flag in (uncopyable, cannot_disable, single_range)):
        return False
    if registration.get("property") != uncopyable | cannot_disable | single_range:
        return False
    return (all(type(constants.get(key)) is int and registration.get(field) == constants[key]
                for field, key in fields.items())
            and not any(role in registration for role in ("condition", "cost", "target", "operation", "value", "count_limit")))


def _summon_predicate(node, card, constants, depth=0):
    """Translate a pure card-property test for the printed-inventory view."""
    node = _unwrapped(node)
    if node is None or depth > 5:
        return None
    for operator, group in (("and", "all"), ("or", "any")):
        left, right = _binary(node, operator)
        if left is not None:
            terms = [_summon_predicate(term, card, constants, depth + 1) for term in (left, right)]
            return {group: terms} if all(terms) else None
    if node.type == "unary_expression" and _text(node.child_by_field_name("operator")) == "not":
        term = _summon_predicate(node.child_by_field_name("operand"), card, constants, depth + 1)
        if term:
            return term["not"] if "not" in term else {"not": term}
        return None
    name, args = _call(node)
    receiver, _, method = name.partition(":")
    value = _integer_value(args[0], constants) if len(args) == 1 else None
    if receiver != card or value is None or not 0 < value < 2**32:
        return None
    if method == "IsType" and value & (value - 1) == 0:
        return dict(field="type_all", value=value)
    if method in ("IsRace", "IsAttribute"):
        return dict(field={"IsRace": "race_any", "IsAttribute": "attribute_any"}[method], value=value)
    xyz_type, link_type = constants.get("TYPE_XYZ"), constants.get("TYPE_LINK")
    if method in ("IsLevelAbove", "IsRankAbove") and value <= 255 and xyz_type and link_type:
        xyz = dict(field="type_all", value=xyz_type)
        link = dict(field="type_all", value=link_type)
        kind = xyz if method == "IsRankAbove" else {"not": {"any": [xyz, link]}}
        return {"all": [kind, dict(field="level_between", value=[value, 255])]}
    return None


def _resolution_summon_lock(operation, definitions, constants, files):
    """Read a single player lock registered at the end of a resolution."""
    required = {"SetType": "EFFECT_TYPE_FIELD", "SetProperty": "EFFECT_FLAG_PLAYER_TARGET",
                "SetCode": "EFFECT_CANNOT_SPECIAL_SUMMON"}
    if any(type(constants.get(symbol)) is not int
           for symbol in (*required.values(), "RESET_PHASE", "PHASE_END", "LOCATION_EXTRA")):
        return None
    params = tuple(map(_text, operation.child_by_field_name("parameters").children_by_field_name("name")))
    statements = _children(operation.child_by_field_name("body"))
    if len(params) < 2 or len(statements) < 8:
        return None
    effect, player = params[:2]
    create, *settings, register = statements[-8:]
    lock, constructor = _local_value(create)
    name, args = _call(constructor)
    if not lock or name != "Effect.CreateEffect" or len(args) != 1:
        return None
    handler = _name(args[0])
    handler_call = (f"{effect}:GetHandler", [])
    if _call(args[0]) != handler_call and not handler:
        return None
    if not _literal_call(register, constants, "Duel.RegisterEffect", lock, player):
        return None
    # A guard that exits before this tail makes registration conditional.
    # No proof is emitted until its condition has its own binding.
    handler_binding = None
    pending = list(reversed(statements[:-8]))
    while pending:
        node = pending.pop()
        if node.type in ("return_statement", "goto_statement", "function_declaration"):
            return None
        local, names, values = _assignment(node)
        if names:
            for index, variable in enumerate(map(_name, names)):
                if variable in (effect, player, "Effect", "Duel"):
                    return None
                if variable == handler:
                    if handler_binding is not None or not local or node.parent != operation.child_by_field_name("body"):
                        return None
                    handler_binding = _call(values[index]) if index < len(values) else ("", [])
            continue
        pending.extend(reversed(_children(node)))
    if handler and handler_binding != handler_call:
        return None
    calls = {}
    for statement in settings:
        name, args = _call(statement)
        receiver, _, method = name.partition(":")
        if receiver != lock or method in calls:
            return None
        calls[method] = args
    if calls.keys() != required.keys() | {"SetTargetRange", "SetReset", "SetTarget"}:
        return None
    if any(len(calls[key]) != 1 or _integer_value(calls[key][0], constants) != constants[symbol]
           for key, symbol in required.items()):
        return None
    target_range = [_integer_value(arg, constants) for arg in calls["SetTargetRange"]]
    controller = {(1, 0): "self", (0, 1): "opponent", (1, 1): "both"}.get(tuple(target_range))
    reset = [_integer_value(arg, constants) for arg in calls["SetReset"]]
    if controller is None or reset != [constants["RESET_PHASE"] | constants["PHASE_END"]]:
        return None
    target_args = calls["SetTarget"]
    target_name = _name(target_args[0]) if len(target_args) == 1 else ""
    target_name = target_name.replace("aux.", "Auxiliary.", 1) if target_name.startswith("aux.") else target_name
    target = definitions.get(target_name)
    if target is None:
        return None
    target_params = target.child_by_field_name("parameters").children_by_field_name("name")
    if len(target_params) < 2:
        return None
    card = _text(target_params[1])
    expression = _return_expression(_children(target.child_by_field_name("body")))
    origins, terms = [], []
    if expression is None:
        return None
    for term in _conjuncts(expression):
        if _literal_call(term, constants, f"{card}:IsLocation", constants["LOCATION_EXTRA"]):
            origins.append("extra")
        else:
            predicate = _summon_predicate(term, card, constants)
            if predicate is None:
                return None
            terms.append(predicate)
    if not terms or len(origins) > 1:
        return None
    forbidden = terms[0] if len(terms) == 1 else {"all": terms}
    allowed = forbidden["not"] if "not" in forbidden else {"not": forbidden}
    operation_name = _name(operation.child_by_field_name("name"))
    return dict(controller=controller, from_zones=origins, allowed_summons=allowed,
                applies_after="resolution", duration="turn", reset=reset[0],
                property_scope="printed_card_configuration",
                operation=dict(files[operation_name], byte_span=_span(operation)),
                target=dict(files[target_name], byte_span=_span(target)), registration_span=_span(register))


def _helper_return(function, bindings):
    """Read the simple assignment/return form used by GetID and Stringid."""
    if function is None:
        return []
    bindings = dict(bindings)
    for statement in _children(function.child_by_field_name("body")):
        if statement.type == "return_statement":
            values = _children(statement)
            return [_value(v, bindings) for v in _children(values[0])] if values else []
        local, names, values = _assignment(statement)
        if not local or len(names) != len(values) or any(name.type != "identifier" for name in names):
            break
        bindings.update(zip(map(_text, names), [_value(v, bindings) for v in values], strict=True))
    return []


def _unmodified_locals(root, candidates):
    """Retain immutable top-level identifiers when callbacks have no writes to them."""
    remaining = dict(candidates)
    nodes = _children(root)
    while nodes and remaining:
        node = nodes.pop()
        if (node.type == "variable_declaration" or node.type == "assignment_statement"
                and node.parent.type != "variable_declaration"):
            _, names, _ = _assignment(node)
            for name in names:
                key = _name(name)
                if key in remaining and node.start_byte != remaining[key][1]:
                    del remaining[key]
        if node.type == "function_declaration":
            remaining.pop(_name(node.child_by_field_name("name")), None)
        nodes.extend(_children(node))
    return remaining


def _functions(root):
    return {_name(node.child_by_field_name("name")): node for node in _children(root)
            if node.type == "function_declaration"}


@dataclass(eq=False)
class _Effect:
    creation: list
    family: int
    clone_from: int | None = None
    settings: dict = field(default_factory=dict)
    registration: list | None = None


def _second_rule_codes(header):
    # The locked core adds these rule names to the CDB alias, with rule_code=0.
    table = re.search(r"\bsecond_code\s*=\s*\{([^;]*)\}\s*;", header)
    if table is None:
        return None
    constants = {name: int(value) for name, value in re.findall(
        r"\bconstexpr\s+uint32_t\s+(\w+)\s*=\s*(\d+)[uU]?\s*;", header)}
    entries = r"\{\s*(\w+)\s*,\s*(\d+)[uU]?\s*\}"
    if not re.fullmatch(rf"\s*(?:{entries}\s*,\s*)*", table[1]):
        return None
    result = {}
    for name, code in re.findall(entries, table[1]):
        original = int(name) if name.isdecimal() else constants.get(name)
        if original is None or original in result:
            return None
        result[original] = int(code)
    return result


class LuaEffectSource:
    """One receipt-bound byte snapshot shared by all catalogs for the asset instance."""

    def __init__(self, root, receipt):
        directory = (Path(root) / "engine-src/scripts").resolve()
        self._scripts = {}
        hashes = sha256()
        for path in sorted(directory.rglob("*.lua")):
            relative = path.relative_to(directory).as_posix()
            if not path.resolve().is_relative_to(directory):
                raise ContractError("Lua script resolves outside the locked source directory")
            content = path.read_bytes()
            checksum = sha256(content)
            self._scripts[relative] = (content, checksum.hexdigest())
            hashes.update(relative.encode() + b"\0" + checksum.digest())
        resources = receipt["resources"]
        if hashes.hexdigest() != resources["scripts"]:
            raise ContractError("Lua scripts differ from the asset receipt")
        self._receipt_binding = self._receipt_identity(root, receipt)
        card_data = (Path(root) / "engine-src/core/card_data.h").read_bytes()
        if sha256(card_data).hexdigest() != resources["card_data_abi"]:
            raise ContractError("Core card data differs from the asset receipt")
        self._second_codes = _second_rule_codes(card_data.decode("utf-8"))
        commits = receipt["source_commits"]
        self._binding = dict(extractor=LUA_EFFECT_VERSION, scripts_sha256=resources["scripts"],
                             script_commit=commits["scripts"], core_commit=commits["core"],
                             source_lock_sha256=receipt["source_lock_sha256"], card_data_sha256=resources["card_data_abi"])

        self._constants = {}
        try:
            constant_root, utility_root = (_parse(self._scripts[name][0]) for name in ("constant.lua", "utility.lua"))
        except KeyError as error:
            raise ContractError("locked Lua constants or utility is missing") from error
        if constant_root.has_error or utility_root.has_error:
            raise ContractError("locked Lua constants or utility has invalid syntax")
        for statement in _children(constant_root):
            _, names, values = _assignment(statement)
            if len(names) == len(values) == 1 and names[0].type == "identifier":
                self._constants[_text(names[0])] = _value(values[0], self._constants)
        self._utility = _functions(utility_root)

    @property
    def binding(self):
        return dict(self._binding)

    @staticmethod
    def _receipt_identity(root, receipt):
        commits = receipt["source_commits"]
        resources = receipt["resources"]
        return (Path(root), resources["scripts"], resources["card_data_abi"],
                commits["scripts"], commits["core"], receipt["source_lock_sha256"])

    def assert_binding(self, root, receipt):
        if self._receipt_binding != self._receipt_identity(root, receipt):
            raise ContractError("Lua resources changed; reload BuildAssets for the new receipt")

    def inventory_query(self, observed, rows):
        """Project static rule names using locked core data and existing ID predicates."""
        query = dict(observed)
        if "any" in query:
            options = [self.inventory_query(option, rows) for option in query["any"]]
            if any(option is None for option in options):
                return None
            query["any"] = options
        excluded = set(query.pop("exclude_rule_codes", ()))
        if excluded:
            if self._second_codes is None or "predicate" in query:
                return None
            original = ((code, row.get("alias") or code) for code, row in rows.items())
            ids = sorted(code for code, canonical in original
                         if canonical in excluded or self._second_codes.get(canonical) in excluded)
            if ids:
                query["predicate"] = {"not": {"field": "card_ids", "value": ids}}
            else:
                # With no locked rows to exclude, this part is true for all cards.
                query.setdefault("selector", "卡")
        return query

    @property
    def card_script_ids(self):
        return tuple(int(name[1:-4]) for name in self._scripts
                     if name.startswith("c") and name[1:-4].isascii() and name[1:-4].isdigit())

    def _helper(self, name):
        node = self._utility.get(name)
        return dict(file="utility.lua", sha256=self._scripts["utility.lua"][1],
                    byte_span=_span(node), function=name) if node else None

    def summarize_effects(self, code, *, deck_send_indices=(), self_send_costs=False,
                          preselected_grave_summons=False, summon_locks=False, summon_chain_response=False,
                          summon_grave_clone=False):
        """Report registrations and requested callback facts for printed effects."""
        filename = f"c{code}.lua"
        result = dict(status="missing_script", file=filename, registrations=[], unknown=[],
                      script_card_id=code, extractor=LUA_EFFECT_VERSION, helpers=[])
        if filename not in self._scripts:
            return result
        source, checksum = self._scripts[filename]
        result.update(status="parsed", sha256=checksum, scripts_sha256=self._binding["scripts_sha256"])
        root = _parse(source)
        if root.has_error:
            result["status"] = "syntax_error"
            pending = [root]
            while pending:
                node = pending.pop()
                if node.is_error or node.is_missing:
                    result["unknown"].append(dict(reason="invalid_lua_syntax", byte_span=_span(node)))
                else:
                    pending.extend(c for c in reversed(node.children) if c.has_error)
            return result

        def unresolved(reason, node):
            result["unknown"].append(dict(reason=reason, byte_span=_span(node)))

        constants = dict(self._constants, **{f"c{code}": _TABLE})
        initial, initial_bindings, functions = None, {}, _functions(root)
        assignments = defaultdict(int)
        local_ids = {}
        overwritten_functions = set()
        for node in _children(root):
            if node.type == "function_declaration":
                name = _name(node.child_by_field_name("name"))
                prefix, _, field_name = name.rpartition(".")
                if field_name == "initial_effect" and constants.get(prefix) is _TABLE:
                    if initial is not None:
                        unresolved("multiple_initial_effect_declarations", node)
                    initial, initial_bindings = node, dict(constants)
                continue
            local, names, values = _assignment(node)
            if names and all(n.type == "identifier" for n in names):
                call, args = _call(values[0] if len(values) == 1 else None)
                if local and call == "GetID" and not args and "GetID" not in constants:
                    values = _helper_return(self._utility.get("GetID"), {"self_table": _TABLE, "self_code": code})
                    helper = self._helper("GetID")
                    if helper and helper not in result["helpers"]:
                        result["helpers"].append(helper)
                    if not values or values[0] is not _TABLE:
                        unresolved("unsupported_get_id", node)
                    elif deck_send_indices and len(names) >= 2 and values[1:2] == [code]:
                        local_ids[_name(names[1])] = (code, node.start_byte)
                else:
                    if any(_call(value)[0] for value in values):
                        unresolved("unsupported_top_level_assignment", node)
                    values = [_value(value, constants) for value in values]
                for i, name in enumerate(map(_text, names)):
                    assignments[name] += 1
                    if (not local and initial is not None
                            and (name in initial_bindings or name in ("Effect", "aux"))):
                        unresolved("assignment_after_initial_effect_declaration", node)
                    constants[name] = values[i] if i < len(values) else None
            elif names and all(_table_field(n, constants) for n in names):
                for name in map(_name, names):
                    if name.endswith(".initial_effect"):
                        unresolved("dynamic_initial_effect_declaration", node)
                    overwritten_functions.add(name)
                    functions.pop(name, None)
            else:
                unresolved("unsupported_top_level_statement", node)
        if initial is None:
            result["status"] = "missing_initial_effect"
            return result

        params = initial.child_by_field_name("parameters").children_by_field_name("name")
        if len(params) != 1:
            unresolved("unsupported_initial_effect_parameters", initial)
        else:
            initial_bindings[_text(params[0])] = _CARD
            self._registrations(initial, initial_bindings, functions, result, unresolved)
        if result["unknown"]:
            result["status"] = "partial"
        if (deck_send_indices or self_send_costs or preselected_grave_summons or summon_locks
                or summon_chain_response or summon_grave_clone):
            # Callback domains use unshadowed core constants and the card's namespace.
            # Deck filters can also read an unchanged local GetID result.
            tables = {name for name, value in constants.items()
                      if value is _TABLE and assignments[name] == (0 if name == f"c{code}" else 1)
                      and name not in functions}
            static_constants = {k: v for k, v in self._constants.items() if not assignments[k] and k not in functions}
            core_tables = {"Duel", "Card"}
            function_namespaces = {name.partition(".")[0] for name in functions}
            shadowed = {name for name in core_tables if assignments[name]} | (function_namespaces & core_tables)
            cost_shadowed = shadowed | ({"Group"} if assignments["Group"] or "Group" in function_namespaces else set())
            callbacks = {name: node for name, node in functions.items() if name not in overwritten_functions}
            if summon_locks and result["status"] == "parsed" and not shadowed and not assignments["Effect"]:
                self._summon_locks(result, callbacks, tables, static_constants,
                                   use_utility=not (assignments["aux"] or assignments["Auxiliary"]))
            observations = {}
            local_ids = _unmodified_locals(root, local_ids)
            # These initial-effect helpers may add independent registrations.
            # Preserve their script diagnostics while using explicit callbacks.
            deck_scope = deck_send_indices and self._registered_callback_scope_known(
                result["unknown"], initial, initial_bindings)
            payment_scope = self_send_costs and self._registered_callback_scope_known(
                result["unknown"], initial, initial_bindings, grave_check=True)
            if preselected_grave_summons and result["status"] == "parsed":
                for registration in result["registrations"]:
                    if _intrinsic_grave_summon_lock(registration, static_constants):
                        registration["intrinsic_grave_summon_lock"] = True
            for registration in result["registrations"]:
                index = registration.get("description_index")
                if summon_chain_response and not shadowed and _summon_chain_response(
                        registration, callbacks, static_constants, tables):
                    registration["summon_chain_response"] = True
                if summon_grave_clone and not shadowed and not assignments["Effect"] and registration["clone_from"] is not None:
                    grave_trigger = _own_effect_sent_race(registration, callbacks, static_constants, tables)
                    if grave_trigger is not None:
                        registration["own_effect_sent_race"] = grave_trigger
                if payment_scope:
                    observed = _self_send_cost(registration, callbacks, static_constants, tables, cost_shadowed)
                    if observed["status"] == "resolved":
                        flags = registration.get("property", 0)
                        target_flag = static_constants.get("EFFECT_FLAG_CARD_TARGET")
                        observed["targets"] = (bool(flags & target_flag)
                                               if type(flags) is int and type(target_flag) is int else None)
                        observed["window"] = next((window for window, symbols in (
                            ("ignition", ("EFFECT_TYPE_IGNITION",)),
                            ("quick", ("EFFECT_TYPE_QUICK_O", "EFFECT_TYPE_QUICK_F")),
                            ("spell_trap_activation", ("EFFECT_TYPE_ACTIVATE",)),
                        ) if registration.get("type") in {static_constants[key] for key in symbols
                                                          if type(static_constants.get(key)) is int}), "trigger")
                        if observed["targets"]:
                            observed["target_check"] = _payment_target_check(
                                registration, callbacks, static_constants, tables)
                    registration["self_send_cost"] = observed
                if preselected_grave_summons and result["status"] == "parsed":
                    observed = _preselected_grave_summon(
                        registration, callbacks, static_constants, tables, shadowed)
                    if observed:
                        registration["preselected_grave_summon"] = observed
                if index not in deck_send_indices or not deck_scope:
                    continue
                operation, target = (registration.get(role, {}) for role in ("operation", "target"))
                key = (registration["family"], registration.get("property", 0),
                       operation.get("reference"), target.get("reference"),
                       tuple(operation.get("byte_span", registration["registration_span"])),
                       tuple(target.get("byte_span", registration["registration_span"])))
                if key not in observations:
                    observations[key] = _deck_send(registration, callbacks, static_constants, tables, shadowed,
                                                   local_ids)
                registration["deck_send"] = observations[key]
        return result

    def _summon_locks(self, result, callbacks, tables, constants, *, use_utility):
        definitions = {name: node for name, node in callbacks.items() if name.partition(".")[0] in tables}
        files = {name: {key: result[key] for key in ("file", "sha256")} for name in definitions}
        if use_utility:
            for name, node in self._utility.items():
                if name.startswith("Auxiliary.") and name not in callbacks:
                    definitions[name] = node
                    files[name] = self._helper(name)
        for registration in result["registrations"]:
            reference = registration.get("operation", {}).get("reference", "")
            if reference.startswith("aux."):
                reference = reference.replace("aux.", "Auxiliary.", 1)
            if reference in definitions:
                observed = _resolution_summon_lock(definitions[reference], definitions, constants, files)
                if observed is not None:
                    registration["resolution_summon_lock"] = observed

    def _registered_callback_scope_known(self, gaps, initial, bindings, *, grave_check=False):
        if not gaps:
            return True
        params = initial.child_by_field_name("parameters").children_by_field_name("name")
        if len(params) != 1:
            return False
        card = _text(params[0])
        statements = {}
        for node in _children(initial.child_by_field_name("body")):
            statements[tuple(_span(node))] = node
            local, names, values = _assignment(node)
            if local and len(names) == len(values) == 1:
                statements[tuple(_span(values[0]))] = values[0]
        for gap in gaps:
            name, args = _call(statements.get(tuple(gap["byte_span"])))
            if (grave_check and gap["reason"] == "unresolved_initial_effect_assignment"
                    and name == "aux.AddThisCardInGraveAlreadyCheck" and len(args) == 1
                    and "aux" not in bindings and _name(args[0]) == card
                    and "Auxiliary.AddThisCardInGraveAlreadyCheck" in self._utility):
                continue
            if gap["reason"] != "unsupported_initial_effect_statement":
                return False
            if name == f"{card}:EnableReviveLimit" and not args:
                continue
            if (name == "aux.AddCodeList" and "Auxiliary.AddCodeList" in self._utility
                    and "aux" not in bindings and len(args) >= 2
                    and _name(args[0]) == card
                    and all(_integer_value(arg, bindings) is not None for arg in args[1:])):
                continue
            return False
        return True

    def _registrations(self, initial, bindings, functions, result, unresolved):
        effects = []
        for node in _children(initial.child_by_field_name("body")):
            _, names, values = _assignment(node)
            if names and all(name.type == "identifier" for name in names):
                assigned = []
                for value in values:
                    name, args = _call(value)
                    receiver, _, method = name.partition(":")
                    target = bindings.get(receiver)
                    if (name == "Effect.CreateEffect" and "Effect" not in bindings
                            and len(args) == 1 and _value(args[0], bindings) is _CARD):
                        assigned.append(_Effect(_span(value), value.start_byte))
                    elif method == "Clone" and isinstance(target, _Effect) and not args:
                        assigned.append(_Effect(_span(value), target.family, target.creation[0], dict(target.settings)))
                    else:
                        assigned.append(_value(value, bindings))
                        if name or value.type not in ("identifier", "number", "parenthesized_expression",
                                                      "binary_expression", "nil", "string", "true", "false"):
                            unresolved("unresolved_initial_effect_assignment", value)
                for i, name in enumerate(map(_text, names)):
                    bindings[name] = assigned[i] if i < len(assigned) else None
                continue

            name, args = _call(node)
            receiver, _, method = name.partition(":")
            target = bindings.get(receiver)
            if method == "RegisterEffect" and target is _CARD and 1 <= len(args) <= 2:
                effect = _value(args[0], bindings)
                if not isinstance(effect, _Effect) or effect.registration is not None:
                    unresolved("unresolved_or_duplicate_registration", node)
                else:
                    effect.registration = _span(node)
                    effects.append(effect)
            elif isinstance(target, _Effect) and target.registration is None:
                self._setter(target, method, args, node, bindings, functions, result, unresolved)
            else:
                unresolved("unsupported_initial_effect_statement", node)

        constants = self._constants
        events = {constants[k]: v for k, v in _EVENTS.items() if type(constants.get(k)) is int}
        for effect in effects:
            settings = effect.settings
            kind, event = settings.get("type"), settings.get("event_code")
            single = constants.get("EFFECT_TYPE_SINGLE")
            triggers = (constants.get("EFFECT_TYPE_TRIGGER_O"), constants.get("EFFECT_TYPE_TRIGGER_F"))
            own_trigger = (type(kind) is int and type(single) is int
                           and any(kind == (single | flag) for flag in triggers if type(flag) is int))
            event_name = events.get(event) if own_trigger else None
            if event_name is None and type(kind) is int and kind == constants.get("EFFECT_TYPE_IGNITION"):
                event_name = "own_main_phase"
            result["registrations"].append(dict(creation_span=effect.creation, family=effect.family,
                clone_from=effect.clone_from, registration_span=effect.registration, event=event_name, **settings))

    def _setter(self, effect, method, args, node, bindings, functions, result, unresolved):
        settings = effect.settings
        if method == "SetDescription":
            call, values = _call(args[0] if len(args) == 1 else None)
            if call == "aux.Stringid" and "aux" not in bindings and len(values) == 2:
                code, index = [_value(value, bindings) for value in values]
                stringid = self._utility.get("Auxiliary.Stringid")
                params = stringid.child_by_field_name("parameters").children_by_field_name("name") if stringid else []
                if (code == result["script_card_id"] and type(index) is int and 0 <= index < 16
                        and len(params) == 2
                        and _helper_return(stringid, dict(zip(map(_text, params), (code, index)))) == [code * 16 + index]):
                    settings["description_index"] = index
                    helper = self._helper("Auxiliary.Stringid")
                    if helper not in result["helpers"]:
                        result["helpers"].append(helper)
                    return
            settings["description_index"] = None
        elif method == "SetCountLimit":
            values = [_value(a, bindings) for a in args]
            settings["count_limit"] = dict(values=[v if type(v) is int else None for v in values],
                                           byte_span=_span(node))
        elif method in _NUMERIC:
            value = _value(args[0], bindings) if args else None
            settings[_NUMERIC[method]] = value if type(value) is int else None
        elif method in _CALLBACKS:
            name = _name(args[0]) if len(args) == 1 else ""
            helper = self._helper(name.replace("aux.", "Auxiliary.", 1)) if name.startswith("aux.") else None
            if helper and helper not in result["helpers"]:
                result["helpers"].append(helper)
            definition = functions.get(name)
            namespace = name.partition(".")[0]
            if (helper is None and definition is not None
                    and (namespace not in bindings or bindings[namespace] is _TABLE)):
                helper = dict(file=result["file"], sha256=result["sha256"],
                              byte_span=_span(definition), function=name)
            settings[_CALLBACKS[method]] = dict(reference=name, byte_span=_span(node),
                                                definition=helper)
        elif method not in _METADATA:
            unresolved("unsupported_effect_setter", node)

    def intrinsic_attack_obligation(self, registration):
        """Recognize the unconditional registration on the effect's own card."""
        single = self._constants.get("EFFECT_TYPE_SINGLE")
        must_attack = self._constants.get("EFFECT_MUST_ATTACK")
        return (type(single) is int and type(must_attack) is int
                and registration.get("type") == single and registration.get("event_code") == must_attack
                and registration.get("property", 0) == 0
                and not {"range", "reset", "count_limit", *_CALLBACKS.values()} & registration.keys())

    def turn_count(self, registration):
        """Ordinary named, player-scoped counters in the pinned core's two-argument API."""
        limit = registration.get("count_limit")
        property_flags = registration.get("property", 0)
        no_reset = self._constants.get("EFFECT_FLAG_NO_TURN_RESET")
        if (not limit or len(limit["values"]) != 2 or type(property_flags) is not int
                or type(no_reset) is not int or property_flags & no_reset or "reset" in registration):
            return None
        maximum, code = limit["values"]
        if type(maximum) is int and 0 < maximum <= 255 and type(code) is int and 1 < code <= 0x0fffffff:
            return maximum, code
