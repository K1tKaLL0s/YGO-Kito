"""Project supported locked Lua callbacks into conditional construction uses."""

from collections import Counter

from .build_contracts import digest
from .construction_inventory import query_supported
from .effect_lua import (
    _binary, _call, _check_body, _children, _conjuncts, _integer_value,
    _literal_arguments, _literal_call, _local_value, _member_call, _name,
    _nonempty_group, _parse, _processing_statements, _return_expression,
    _selection_query, _text,
)

# Standard YGOPro core constants so mock _constants dicts work identically to full constant.lua.
_DEFAULT_CONSTANTS = {
    "EFFECT_TYPE_SINGLE": 0x1,
    "EFFECT_TYPE_FIELD": 0x2,
    "EFFECT_TYPE_EQUIP": 0x4,
    "EFFECT_TYPE_ACTIONS": 0x8,
    "EFFECT_TYPE_ACTIVATE": 0x10,
    "EFFECT_TYPE_FLIP": 0x20,
    "EFFECT_TYPE_IGNITION": 0x40,
    "EFFECT_TYPE_TRIGGER_O": 0x80,
    "EFFECT_TYPE_QUICK_O": 0x100,
    "EFFECT_TYPE_TRIGGER_F": 0x200,
    "EFFECT_TYPE_QUICK_F": 0x400,
    "EFFECT_TYPE_CONTINUOUS": 0x800,
    "EFFECT_TYPE_XMATERIAL": 0x1000,
    "EFFECT_TYPE_GRANT": 0x2000,
    "EFFECT_TYPE_TARGET": 0x4000,
    "EFFECT_FLAG_DELAY": 0x10000,
    "EFFECT_FLAG_OATH": 0x400,
    "EFFECT_FLAG_PLAYER_TARGET": 0x20000,
    "EFFECT_DISABLE": 0x2,
    "EFFECT_DISABLE_EFFECT": 0x3,
    "EFFECT_CANNOT_ACTIVATE": 0x6,
    "EFFECT_TRAP_ACT_IN_HAND": 0xf,
    "EFFECT_CANNOT_SUMMON": 0x14,
    "EFFECT_CANNOT_FLIP_SUMMON": 0x15,
    "EFFECT_CANNOT_SPECIAL_SUMMON": 0x16,
    "EFFECT_SPSUMMON_CONDITION": 0x1e,
    "EFFECT_SUMMON_PROC": 0x20,
    "EFFECT_LIMIT_SUMMON_PROC": 0x21,
    "EFFECT_SPSUMMON_PROC": 0x22,
    "EFFECT_SET_PROC": 0x24,
    "EFFECT_LIMIT_SET_PROC": 0x25,
    "EFFECT_INDESTRUCTABLE_EFFECT": 0x29,
    "EFFECT_INDESTRUCTABLE_BATTLE": 0x2a,
    "EFFECT_INDESTRUCTABLE_COUNT": 0x2b,
    "EFFECT_DESTROY_REPLACE": 0x32,
    "EFFECT_LEAVE_FIELD_REDIRECT": 0x3c,
    "EFFECT_TO_GRAVE_REDIRECT": 0x3f,
    "EFFECT_CANNOT_BE_BATTLE_TARGET": 0x46,
    "EFFECT_CANNOT_BE_EFFECT_TARGET": 0x47,
    "EFFECT_IMMUNE_EFFECT": 0x49,
    "EFFECT_DIRECT_ATTACK": 0x4a,
    "EFFECT_CANNOT_ATTACK": 0x55,
    "EFFECT_CANNOT_ATTACK_ANNOUNCE": 0x56,
    "EFFECT_MUST_ATTACK": 0x59,
    "EFFECT_UPDATE_ATTACK": 0x64,
    "EFFECT_SET_ATTACK": 0x65,
    "EFFECT_SET_ATTACK_FINAL": 0x66,
    "EFFECT_UPDATE_DEFENSE": 0x67,
    "EFFECT_SET_DEFENSE": 0x68,
    "EFFECT_SET_DEFENSE_FINAL": 0x69,
    "EFFECT_SET_POSITION": 0x8c,
    "EFFECT_SELF_DESTROY": 0x8d,
    "EFFECT_CANNOT_TO_HAND": 0x48,
    "EFFECT_CANNOT_DRAW": 0xc0,
    "EFFECT_EXTRA_ATTACK": 0xc2,
    "EFFECT_EXTRA_ATTACK_MONSTER": 0xc3,
    "EFFECT_NO_BATTLE_DAMAGE": 0xc8,
    "EFFECT_AVOID_BATTLE_DAMAGE": 0xc9,
    "EFFECT_PIERCE": 0xcb,
    "EFFECT_ALSO_BATTLE_DAMAGE": 0xcf,
    "EFFECT_CANNOT_MSET": 0x17,
    "EFFECT_UNSUMMONABLE_CARD": 0x1c,
    "EFFECT_REVIVE_LIMIT": 0x1f,
    "EFFECT_FUSION_SUBSTITUTE": 0xea,
    "EFFECT_CANNOT_BE_FUSION_MATERIAL": 0xeb,
    "EFFECT_CANNOT_BE_SYNCHRO_MATERIAL": 0xec,
    "EFFECT_CANNOT_BE_XYZ_MATERIAL": 0xed,
    "EFFECT_CANNOT_BE_RITUAL_MATERIAL": 0xee,
    "EFFECT_CANNOT_BE_LINK_MATERIAL": 0xef,
    "EFFECT_FUSION_MATERIAL": 0xfa,
    "EFFECT_MATERIAL_CHECK": 0xfb,
    "EFFECT_DRAW_COUNT": 0x10f,
    "EFFECT_CHAIN_MATERIAL": 0x120,
    "EFFECT_UNIQUE_CHECK": 0x129,
    "EFFECT_QP_ACT_IN_NTPHAND": 0x137,
    "EFFECT_SPSUMMON_PROC_G": 0x140,
    "EFFECT_SPSUMMON_COUNT_LIMIT": 0x14a,
    "EFFECT_EXTRA_LINK_MATERIAL": 0x166,
    "EFFECT_LIMIT_SPECIAL_SUMMON_POSITION": 0x170,
    "EFFECT_TRAP_ACT_IN_SET_TURN": 0x138,
    "EFFECT_QP_ACT_IN_SET_TURN": 0x139,
    "EFFECT_CANNOT_INACTIVATE": 0x110,
    "EFFECT_CANNOT_DISEFFECT": 0x111,
    "EFFECT_CANNOT_DISABLE_SUMMON": 0x112,
    "EFFECT_CANNOT_DISABLE_SPSUMMON": 0x113,
    "EFFECT_CANNOT_DISABLE": 0x1,
    "EFFECT_ACTIVATE_COST": 0x18,
    "EFFECT_UNRELEASABLE_SUM": 0x26,
    "EFFECT_UNRELEASABLE_NONSUM": 0x27,
    "EFFECT_CANNOT_CHANGE_CONTROL": 0x41,
    "EFFECT_DEFENSE_ATTACK": 0xd0,
    "EFFECT_ADD_SETCODE": 0xd5,
    "EFFECT_CHANGE_CODE": 0xd2,
    "EFFECT_ADD_CODE": 0xd3,
    "EFFECT_CHANGE_LEVEL": 0xd6,
    "EFFECT_UPDATE_LEVEL": 0xd7,
    "EFFECT_XYZ_LEVEL": 0xd9,
    "EFFECT_SYNCHRO_LEVEL": 0xda,
    "EFFECT_RITUAL_LEVEL": 0xdb,
    "EFFECT_DOUBLE_TRIBUTE": 0xdc,
    "EFFECT_EQUIP_LIMIT": 0x4b,
    "EFFECT_COUNTER_PERMIT": 0x10000,
    "EVENT_FLIP": 0x3e9,
    "EVENT_FREE_CHAIN": 0x3ea,
    "EVENT_TO_DECK": 0x3f5,
    "EVENT_TO_GRAVE": 0x3f6,
    "EVENT_LEAVE_FIELD": 0x3f7,
    "EVENT_CHANGE_POS": 0x3f8,
    "EVENT_RELEASE": 0x3f9,
    "EVENT_DRAW": 0x3fb,
    "EVENT_CHAIN_SOLVING": 0x3fc,
    "EVENT_CHAIN_SOLVED": 0x3fd,
    "EVENT_CHAINING": 0x403,
    "EVENT_DESTROYED": 0x405,
    "EVENT_ADJUST": 0x410,
    "EVENT_SUMMON_SUCCESS": 0x44c,
    "EVENT_FLIP_SUMMON_SUCCESS": 0x44d,
    "EVENT_SPSUMMON_SUCCESS": 0x44e,
    "EVENT_SUMMON": 0x44f,
    "EVENT_FLIP_SUMMON": 0x450,
    "EVENT_SPSUMMON": 0x451,
    "EVENT_BE_MATERIAL": 0x454,
    "EVENT_TO_HAND": 0x456,
    "EVENT_REMOVE": 0x457,
    "EVENT_PREDRAW": 0x459,
    "EVENT_ATTACK_ANNOUNCE": 0x46a,
    "EVENT_BATTLE_START": 0x46c,
    "EVENT_PRE_DAMAGE_CALCULATE": 0x46e,
    "EVENT_BATTLED": 0x472,
    "EVENT_BATTLE_DESTROYING": 0x473,
    "EVENT_BATTLE_DESTROYED": 0x474,
    "EVENT_DAMAGE_STEP_END": 0x475,
    "EVENT_PHASE": 0x1000,
    "CATEGORY_DESTROY": 0x1,
    "CATEGORY_RELEASE": 0x2,
    "CATEGORY_REMOVE": 0x4,
    "CATEGORY_TOHAND": 0x8,
    "CATEGORY_TODECK": 0x10,
    "CATEGORY_TOGRAVE": 0x20,
    "CATEGORY_DECKDES": 0x40,
    "CATEGORY_HANDES": 0x400000080,
    "CATEGORY_SUMMON": 0x100,
    "CATEGORY_SPECIAL_SUMMON": 0x200,
    "CATEGORY_TOKEN": 0x400,
    "CATEGORY_POSITION": 0x1000,
    "CATEGORY_CONTROL": 0x2000,
    "CATEGORY_DISABLE": 0x4000,
    "CATEGORY_DISABLE_SUMMON": 0x8000,
    "CATEGORY_DRAW": 0x10000,
    "CATEGORY_SEARCH": 0x20000,
    "CATEGORY_EQUIP": 0x40000,
    "CATEGORY_DAMAGE": 0x80000,
    "CATEGORY_RECOVER": 0x100000,
    "CATEGORY_COUNTER": 0x800000,
    "CATEGORY_GRAVE_ACTION": 0x800,
    "CATEGORY_NEGATE": 0x10000000,
    "CATEGORY_TOEXTRA": 0x80000000,
    "CATEGORY_FUSION_SUMMON": 0x40000000,
    "LOCATION_DECK": 0x1,
    "LOCATION_HAND": 0x2,
    "LOCATION_MZONE": 0x4,
    "LOCATION_SZONE": 0x8,
    "LOCATION_GRAVE": 0x10,
    "LOCATION_REMOVED": 0x20,
    "LOCATION_EXTRA": 0x40,
    "LOCATION_OVERLAY": 0x80,
    "LOCATION_FZONE": 0x100,
    "LOCATION_PZONE": 0x200,
    "LOCATION_ONFIELD": 0xc,
    "REASON_EFFECT": 0x40,
    "REASON_COST": 0x80,
    "REASON_RULE": 0x100,
    "SUMMON_TYPE_FUSION": 0x43000000,
    "SUMMON_TYPE_SYNCHRO": 0x45000000,
    "SUMMON_TYPE_XYZ": 0x46000000,
    "SUMMON_TYPE_LINK": 0x4c000000,
    "SUMMON_TYPE_RITUAL": 0x42000000,
    "SUMMON_TYPE_PENDULUM": 0x4a000000,
    "SUMMON_TYPE_ADVANCE": 0x11000000,
    "TYPE_MONSTER": 0x1,
    "TYPE_SPELL": 0x2,
    "TYPE_TRAP": 0x4,
    "TYPE_EFFECT": 0x20,
    "TYPE_FUSION": 0x40,
    "TYPE_RITUAL": 0x80,
    "TYPE_QUICKPLAY": 0x10000,
    "TYPE_SYNCHRO": 0x2000,
    "TYPE_PENDULUM": 0x1000000,
    "TYPE_XYZ": 0x800000,
    "TYPE_LINK": 0x4000000,
    "RESET_CHAIN": 0x40000000,
    "RESET_PHASE": 0x10000000,
    "PHASE_END": 0x200,
    "ACTIVITY_SPSUMMON": 2,
    "RACE_ALL": 0x3ffffff,
}

_SUMMON_PROCEDURE_NAMES = (
    "EFFECT_SPSUMMON_PROC",
    "EFFECT_SUMMON_PROC",
    "EFFECT_LIMIT_SUMMON_PROC",
    "EFFECT_SET_PROC",
    "EFFECT_LIMIT_SET_PROC",
    "EFFECT_SPSUMMON_PROC_G",
)
_SUMMON_RULE_NAMES = (
    "EFFECT_FUSION_MATERIAL",
    "EFFECT_REVIVE_LIMIT",
    "EFFECT_SPSUMMON_CONDITION",
    "EFFECT_CANNOT_BE_FUSION_MATERIAL",
    "EFFECT_CANNOT_BE_SYNCHRO_MATERIAL",
    "EFFECT_CANNOT_BE_XYZ_MATERIAL",
    "EFFECT_CANNOT_BE_LINK_MATERIAL",
    "EFFECT_CANNOT_BE_RITUAL_MATERIAL",
    "EFFECT_UNSUMMONABLE_CARD",
    "EFFECT_FUSION_SUBSTITUTE",
    "EFFECT_MATERIAL_CHECK",
    "EFFECT_EXTRA_LINK_MATERIAL",
    "EFFECT_ADD_SETCODE",
    "EFFECT_CHANGE_CODE",
    "EFFECT_ADD_CODE",
    "EFFECT_CHANGE_LEVEL",
    "EFFECT_UPDATE_LEVEL",
    "EFFECT_XYZ_LEVEL",
    "EFFECT_SYNCHRO_LEVEL",
    "EFFECT_RITUAL_LEVEL",
    "EFFECT_DOUBLE_TRIBUTE",
    "EFFECT_UNIQUE_CHECK",
    "EFFECT_CANNOT_MSET",
)
_ACTIVATION_RULE_NAMES = (
    "EFFECT_TRAP_ACT_IN_HAND",
    "EFFECT_QP_ACT_IN_NTPHAND",
    "EFFECT_TRAP_ACT_IN_SET_TURN",
    "EFFECT_QP_ACT_IN_SET_TURN",
    "EFFECT_ACTIVATE_COST",
    "EFFECT_CANNOT_INACTIVATE",
    "EFFECT_CANNOT_DISEFFECT",
    "EFFECT_CANNOT_DISABLE_SUMMON",
    "EFFECT_CANNOT_DISABLE_SPSUMMON",
)
_RESTRICTION_RULE_NAMES = (
    "EFFECT_CANNOT_FLIP_SUMMON",
    "EFFECT_LIMIT_SPECIAL_SUMMON_POSITION",
    "EFFECT_LEAVE_FIELD_REDIRECT",
    "EFFECT_CANNOT_ATTACK",
    "EFFECT_CANNOT_ATTACK_ANNOUNCE",
    "EFFECT_MUST_ATTACK",
    "EFFECT_UNRELEASABLE_SUM",
    "EFFECT_UNRELEASABLE_NONSUM",
    "EFFECT_CANNOT_CHANGE_CONTROL",
)
_UTILITY_RULE_NAMES = (
    "EFFECT_INDESTRUCTABLE_EFFECT",
    "EFFECT_INDESTRUCTABLE_BATTLE",
    "EFFECT_INDESTRUCTABLE_COUNT",
    "EFFECT_CANNOT_BE_BATTLE_TARGET",
    "EFFECT_CANNOT_BE_EFFECT_TARGET",
    "EFFECT_IMMUNE_EFFECT",
    "EFFECT_DESTROY_REPLACE",
    "EFFECT_UPDATE_ATTACK",
    "EFFECT_SET_ATTACK",
    "EFFECT_SET_ATTACK_FINAL",
    "EFFECT_UPDATE_DEFENSE",
    "EFFECT_SET_DEFENSE",
    "EFFECT_SET_DEFENSE_FINAL",
    "EFFECT_DIRECT_ATTACK",
    "EFFECT_EXTRA_ATTACK",
    "EFFECT_EXTRA_ATTACK_MONSTER",
    "EFFECT_NO_BATTLE_DAMAGE",
    "EFFECT_AVOID_BATTLE_DAMAGE",
    "EFFECT_PIERCE",
    "EFFECT_ALSO_BATTLE_DAMAGE",
    "EFFECT_DEFENSE_ATTACK",
    "EFFECT_SELF_DESTROY",
    "EFFECT_DRAW_COUNT",
    "EFFECT_EQUIP_LIMIT",
    "EFFECT_CANNOT_DISABLE",
)
_FLOODGATE_EVENTS = {
    "EFFECT_SPSUMMON_COUNT_LIMIT": "special_summon_limit",
    "EFFECT_CANNOT_ACTIVATE": "prevent_activation",
    "EFFECT_CANNOT_SPECIAL_SUMMON": "prevent_special_summon",
    "EFFECT_CANNOT_SUMMON": "prevent_summon",
    "EFFECT_DISABLE": "negate_effect",
    "EFFECT_DISABLE_EFFECT": "negate_effect",
    "EFFECT_SET_POSITION": "change_position",
    "EFFECT_TO_GRAVE_REDIRECT": "banish_replacement",
    "EFFECT_CANNOT_DRAW": "prevent_draw",
    "EFFECT_CANNOT_TO_HAND": "prevent_search",
}


def _const(constants, name):
    return constants.get(name, _DEFAULT_CONSTANTS.get(name, 0))


def _call_parts(node):
    """Extract (callable_name, args) including chained receivers like `e:GetHandler():Method(...)`."""
    name, args = _call(node)
    if name:
        return name, args
    if node is not None and node.type == "function_call":
        fn = node.child_by_field_name("name")
        if fn is not None and fn.type == "method_index_expression":
            tbl = fn.child_by_field_name("table")
            mtd = fn.child_by_field_name("method")
            if tbl is not None and mtd is not None:
                return f"{_text(tbl)}:{_text(mtd)}", args
    return name, args


def _builtin_card_query(fn_name, extra_args, constants, env=None):
    """Map built-in `Card.Is*` predicates with extra args to inventory queries."""
    vals = [v for a in extra_args if (v := _eval_int(a, constants, env)) is not None]
    if not vals:
        return None
    if fn_name in ("Card.IsCode", "Card.IsOriginalCodeRule"):
        return {"predicate": {"field": "card_ids", "value": vals}}
    if fn_name in ("Card.IsSetCard", "Card.IsLinkSetCard"):
        return {"setcode": vals[0]} if len(vals) == 1 else {"any": [{"setcode": v} for v in vals]}
    if fn_name == "Card.IsType":
        t = vals[0]
        return {"type": t} if t in (1, 2, 4, 6) else {"type_all": t}
    if fn_name == "Card.IsRace":
        return {"race_any": vals[0]}
    if fn_name == "Card.IsAttribute":
        return {"attribute_any": vals[0]}
    if fn_name == "Card.IsLevel":
        return {"level": vals[0]}
    if fn_name == "Card.IsLevelBelow":
        return {"level_between": [1, vals[0]]}
    if fn_name == "Card.IsLevelAbove":
        return {"level_between": [vals[0], 13]}
    if fn_name == "Card.IsRank":
        return {"rank": vals[0]}
    return None


def _body(node):
    if node is None:
        return (), []
    params = tuple(map(_text, node.child_by_field_name("parameters").children_by_field_name("name")))
    if set(params) & {"Card", "Duel", "Effect", "Group"}:
        return (), []
    return params, _children(node.child_by_field_name("body"))


def _walk(node):
    if node is None:
        return
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        children = list(getattr(current, "children", ()))
        if children:
            stack.extend(reversed(children))


def _eval_int(node, constants, env=None):
    val = _integer_value(node, constants)
    if val is not None:
        return val
    if node is None:
        return None
    if node.type == "unary_expression" and _text(node.child_by_field_name("operator")) == "-":
        inner = _eval_int(node.child_by_field_name("operand"), constants, env)
        return -inner if inner is not None else None
    if node.type == "binary_expression":
        op = _text(node.child_by_field_name("operator"))
        left = _eval_int(node.child_by_field_name("left"), constants, env)
        right = _eval_int(node.child_by_field_name("right"), constants, env)
        if left is not None and right is not None:
            if op == "+":
                return left + right
            if op == "-":
                return left - right
            if op == "|":
                return left | right
            if op == "&":
                return left & right
            if op == "*":
                return left * right
    if node.type == "parenthesized_expression":
        for child in node.children:
            if child.type not in ("(", ")"):
                return _eval_int(child, constants, env)
    name, args = _call(node)
    if name and name.endswith(":GetLabel") and not args and env and env.get("labels"):
        return env["labels"][0]
    if env and node.type == "identifier" and _text(node) in env:
        return env[_text(node)]
    return None


def _resolve_fn_name(node, constants=None):
    """Unwrap helper callback wrappers like aux.NecroValleyFilter(fn) or aux.FilterBoolFunction(fn, val)."""
    if node is None:
        return None, ()
    text = _name(node)
    if text:
        return text, ()
    name, args = _call(node)
    if not name or not args:
        return None, ()
    if name in ("aux.NecroValleyFilter", "Auxiliary.NecroValleyFilter") and len(args) == 1:
        return _resolve_fn_name(args[0], constants)
    if name in ("aux.FilterBoolFunction", "Auxiliary.FilterBoolFunction", "aux.TargetBoolFunction"):
        inner = _name(args[0])
        return (inner, tuple(args[1:])) if inner else (None, ())
    return None, ()


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
            and _integer_value(paid[1], constants) == _const(constants, "REASON_COST"))


def _deck_output(node, constants):
    params, body = _body(node)
    if len(params) not in (2, 8) or len(body) != 1:
        return None
    name, args = _call(body[0])
    destinations = {"Duel.Draw": ("draw", "hand"), "Duel.DiscardDeck": ("send_grave", "grave")}
    if name not in destinations or len(args) != 3 or _name(args[0]) != params[1]:
        return None
    count = _integer_value(args[1], constants)
    if count and count > 0 and _integer_value(args[2], constants) == _const(constants, "REASON_EFFECT"):
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
                    or settings.get("SetType") != _const(constants, "EFFECT_TYPE_FIELD") | _const(constants, "EFFECT_TYPE_CONTINUOUS")
                    or settings.get("SetReset") != _const(constants, "RESET_PHASE") | _const(constants, "PHASE_END")
                    or settings.get("SetProperty", 0) not in (0, _const(constants, "EFFECT_FLAG_DELAY"))
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
    if len(filter_params) != 2 or not _literal_call(
            _return_expression(filter_body), constants, f"{filter_params[0]}:IsSummonPlayer", filter_params[1]):
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
            args, constants, (params[1], flag, _const(constants, "RESET_CHAIN"), 0, 1)):
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
                and _literal_call(body[2], constants, "Duel.Draw", player, count, _const(constants, "REASON_EFFECT")))


def _summon_draw(operation, functions, constants):
    """Recognize one draw per matching event, including flag counts within a chain."""
    by_window = {}
    for listener in _listeners(operation, constants):
        event = listener["SetCode"]
        condition, processing = (functions.get(listener[key]) for key in ("SetCondition", "SetOperation"))
        if event == _const(constants, "EVENT_SPSUMMON_SUCCESS"):
            window = _summon_condition(condition, functions, constants)
        elif event == _const(constants, "EVENT_CHAIN_SOLVED"):
            window = "chain_solved"
        else:
            return None
        if (not window or window in by_window or listener.get("SetProperty", 0) !=
                (_const(constants, "EFFECT_FLAG_DELAY") if window == "outside_chain" else 0)):
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


def _mask_zones(mask, constants, *, normalize_field=False):
    zones = []
    for key, name in (
        ("LOCATION_DECK", "deck"),
        ("LOCATION_HAND", "hand"),
        ("LOCATION_MZONE", "field"),
        ("LOCATION_SZONE", "field" if normalize_field else "spell_trap"),
        ("LOCATION_FZONE", "field" if normalize_field else "spell_trap"),
        ("LOCATION_PZONE", "field" if normalize_field else "pzone"),
        ("LOCATION_GRAVE", "grave"),
        ("LOCATION_REMOVED", "banished"),
        ("LOCATION_EXTRA", "extra"),
    ):
        bit = _const(constants, key)
        if bit and (mask & bit) and name not in zones:
            zones.append(name)
    return zones


def _merge_queries(left, right):
    if not left:
        return dict(right) if right else {}
    if not right:
        return dict(left)
    merged = dict(left)
    for k, v in right.items():
        if k == "predicate" and "predicate" in merged:
            if merged["predicate"] != v:
                merged["predicate"] = {"all": [merged["predicate"], v]}
        elif k == "any" and "any" in merged:
            # Conjunction of two separate 'or' clauses can be represented via nested any only inside predicate,
            # so avoid dropping either side: keep left if identical, else prefer more specific side.
            if merged["any"] != v:
                return None
        elif k in merged and merged[k] != v:
            if k in ("type", "race", "attribute_any", "type_all") and isinstance(merged[k], int) and isinstance(v, int):
                merged[k] = merged[k] | v
            elif k == "level_between" and isinstance(v, list):
                merged[k] = [max(merged[k][0], v[0]), min(merged[k][1], v[1])]
                if merged[k][0] > merged[k][1]:
                    return None
            else:
                return None
        else:
            merged[k] = v
    return merged


def _strip_parens(node):
    while node is not None and node.type == "parenthesized_expression":
        inner = next((c for c in node.children if c.type not in ("(", ")")), None)
        if inner is None:
            break
        node = inner
    return node


def _extract_filter_expr(expr, card_param, functions, constants, code, meta, *, env=None, depth=0):
    """Extract an inventory query dict from a Lua boolean expression over `card_param`."""
    expr = _strip_parens(expr)
    if expr is None or depth > 6:
        return {}
    if expr.type == "unary_expression" and _text(expr.child_by_field_name("operator")) == "not":
        inner = _strip_parens(expr.child_by_field_name("operand"))
        name, args = _call_parts(inner)
        if name == f"{card_param}:IsCode" and args:
            codes = [v for a in args if (v := _eval_int(a, constants, env)) is not None]
            if code is not None and codes == [code]:
                meta["exclude_this_card"] = True
                return {}
            if codes:
                return {"predicate": {"not": {"field": "card_ids", "value": codes}}}
        if name == f"{card_param}:IsType" and len(args) == 1:
            t = _eval_int(args[0], constants, env)
            if t:
                return {"predicate": {"not": {"field": "type_all", "value": t}}}
        if name == f"{card_param}:IsSetCard" and args:
            sc = _eval_int(args[0], constants, env)
            if sc is not None:
                return {"predicate": {"not": {"field": "setcode", "value": sc}}}
        if name == f"{card_param}:IsAttribute" and len(args) == 1:
            attr = _eval_int(args[0], constants, env)
            if attr:
                return {"predicate": {"not": {"field": "attribute_any", "value": attr}}}
        if name == f"{card_param}:IsRace" and len(args) == 1:
            rc = _eval_int(args[0], constants, env)
            if rc:
                return {"predicate": {"not": {"field": "race_any", "value": rc}}}
        return {}
    if expr.type == "binary_expression":
        op = _text(expr.child_by_field_name("operator"))
        left_n = expr.child_by_field_name("left")
        right_n = expr.child_by_field_name("right")
        if op == "and":
            lq = _extract_filter_expr(left_n, card_param, functions, constants, code, meta, env=env, depth=depth + 1)
            rq = _extract_filter_expr(right_n, card_param, functions, constants, code, meta, env=env, depth=depth + 1)
            if lq is None or rq is None:
                return None
            return _merge_queries(lq, rq)
        if op == "or":
            lq = _extract_filter_expr(left_n, card_param, functions, constants, code, meta, env=env, depth=depth + 1)
            rq = _extract_filter_expr(right_n, card_param, functions, constants, code, meta, env=env, depth=depth + 1)
            if lq and rq:
                items = [*(lq["any"] if list(lq.keys()) == ["any"] else [lq]),
                         *(rq["any"] if list(rq.keys()) == ["any"] else [rq])]
                return {"any": items}
            return lq or rq or {}

    part = _selection_query(expr, card_param, constants)
    if part:
        return dict(part)

    name, args = _call_parts(expr)
    if name and args:
        if name == f"{card_param}:IsCode":
            codes = [v for a in args if (v := _eval_int(a, constants, env)) is not None]
            if codes:
                return {"predicate": {"field": "card_ids", "value": codes}}
        if name == f"{card_param}:IsLevel" and len(args) == 1:
            lv = _eval_int(args[0], constants, env)
            if lv is not None and 1 <= lv <= 13:
                return {"level": lv}
        if name == f"{card_param}:IsLevelBelow" and len(args) == 1:
            lv = _eval_int(args[0], constants, env)
            if lv is not None and 1 <= lv <= 13:
                return {"level_between": [1, lv]}
        if name == f"{card_param}:IsLevelAbove" and len(args) == 1:
            lv = _eval_int(args[0], constants, env)
            if lv is not None and 1 <= lv <= 13:
                return {"level_between": [lv, 13]}
        if name == f"{card_param}:IsRank" and len(args) == 1:
            rk = _eval_int(args[0], constants, env)
            if rk is not None and 1 <= rk <= 13:
                return {"rank": rk}
        if name == f"{card_param}:IsLink" and len(args) == 1:
            lk = _eval_int(args[0], constants, env)
            if lk is not None and 1 <= lk <= 8:
                return {"link_rating": lk}
        if name == f"{card_param}:IsAttackAbove" and len(args) == 1:
            v = _eval_int(args[0], constants, env)
            if v is not None:
                return {"atk_min": v}
        if name == f"{card_param}:IsAttackBelow" and len(args) == 1:
            v = _eval_int(args[0], constants, env)
            if v is not None:
                return {"atk_max": v}
        if name == f"{card_param}:IsDefenseAbove" and len(args) == 1:
            v = _eval_int(args[0], constants, env)
            if v is not None:
                return {"def_min": v}
        if name == f"{card_param}:IsDefenseBelow" and len(args) == 1:
            v = _eval_int(args[0], constants, env)
            if v is not None:
                return {"def_max": v}
        if name == f"{card_param}:IsFaceup":
            meta["face_up"] = True
            return {}
        if name == f"{card_param}:IsFacedown":
            meta["face_up"] = False
            return {}
        if name == f"{card_param}:IsPreviousLocation" and len(args) == 1:
            loc = _eval_int(args[0], constants, env)
            if loc:
                meta["previous_locations"] = _mask_zones(loc, constants)
            return {}
        if name == f"{card_param}:IsLocation" and len(args) == 1:
            loc = _eval_int(args[0], constants, env)
            if loc:
                meta["filter_locations"] = _mask_zones(loc, constants)
            return {}
        if name == f"{card_param}:IsSummonType" and len(args) == 1:
            st = _eval_int(args[0], constants, env)
            if st is not None:
                meta["summon_type_code"] = st
            return {}
        if name == f"{card_param}:IsSetCard" and args:
            vals = [v for a in args if (v := _eval_int(a, constants, env)) is not None]
            if len(vals) == 1:
                return {"setcode": vals[0]}
            if len(vals) > 1:
                return {"any": [{"setcode": v} for v in vals]}
        if name == f"{card_param}:IsType" and len(args) == 1:
            t = _eval_int(args[0], constants, env)
            if t:
                return {"type": t} if t in (1, 2, 4, 6) else {"type_all": t}
        if name == f"{card_param}:IsRace" and len(args) == 1:
            r = _eval_int(args[0], constants, env)
            if r:
                return {"race_any": r}
        if name == f"{card_param}:IsAttribute" and len(args) == 1:
            a = _eval_int(args[0], constants, env)
            if a:
                return {"attribute_any": a}
        # Helper card predicate call: e.g. c123.spfilter(c, ...)
        if name in functions and _name(args[0]) == card_param:
            h_query, h_meta = _extract_filter_query(functions[name], functions, constants, code,
                                                    extra_args=tuple(args[1:]), depth=depth + 1)
            meta.update(h_meta)
            return h_query or {}
    return {}


def _extract_filter_query(fn_node, functions, constants, code, *, extra_args=(), env=None, depth=0):
    """Parse a Lua filter callback AST into (query_dict, metadata)."""
    meta = {}
    if fn_node is None or depth > 6:
        return None, meta
    params, body = _body(fn_node)
    if not params:
        return None, meta
    # Effect target callbacks often take `(e, c)` where `c` is params[1].
    if params[0] in ("e", "te") and len(params) >= 2:
        card_param = params[1]
        bind_params = params[2:]
    else:
        card_param = params[0]
        bind_params = params[1:]
    local_env = dict(env or {})
    for pname, arg in zip(bind_params, extra_args):
        val = _eval_int(arg, constants, local_env)
        if val is not None:
            local_env[pname] = val

    queries = []
    # Collect top-level early negative guards (`if not c:IsType(...) then return false end`) + final return
    ret_expr = _return_expression(body)
    if body:
        for stmt in body:
            if stmt.type == "if_statement":
                cond = stmt.child_by_field_name("condition")
                then_b = _check_body(stmt)
                r = _return_expression(then_b)
                if r is not None and _text(r) == "false" and cond is not None:
                    guard_q = _extract_filter_expr(cond, card_param, functions, constants, code, meta,
                                                   env=local_env, depth=depth + 1)
                    if guard_q:
                        queries.append(guard_q)
    if ret_expr is not None:
        rq = _extract_filter_expr(ret_expr, card_param, functions, constants, code, meta,
                                  env=local_env, depth=depth + 1)
        if rq:
            queries.append(rq)

    merged = {}
    for q in queries:
        merged = _merge_queries(merged, q)
        if merged is None:
            return None, meta
    return (merged or {"type": 7}), meta


def _parse_script_root(lua, filename):
    scripts = getattr(lua, "_scripts", None)
    if not isinstance(scripts, dict) or filename not in scripts:
        return None
    cache = getattr(lua, "_static_ast_cache", None)
    if cache is None:
        cache = {}
        try:
            lua._static_ast_cache = cache
        except Exception:
            cache = {}
    if filename in cache:
        return cache[filename]
    source_bytes = scripts[filename][0]
    if isinstance(source_bytes, str):
        source_bytes = source_bytes.encode("utf-8")
    root = _parse(source_bytes)
    cache[filename] = root
    return root


def _initial_effect_field_info(lua, rule, code, constants):
    """Inspect initial_effect for SetTargetRange / SetValue on field continuous rules."""
    cbs = rule.get("callbacks", {})
    filename = next((v["file"] for v in cbs.values() if isinstance(v, dict) and v.get("file")), f"c{code}.lua")
    root = _parse_script_root(lua, filename)
    if root is None:
        return None
    target_event = rule["event"]
    # Collect effect creation blocks inside initial_effect
    blocks = []
    current = None
    for node in _walk(root):
        if node.type == "function_declaration":
            fname = _text(node.child_by_field_name("name")) or ""
            if not fname.endswith(".initial_effect"):
                continue
            _, body = _body(node)
            for stmt in body:
                v, val = _local_value(stmt)
                name, args = _call(val if v else stmt)
                if name == "Effect.CreateEffect":
                    current = {"var": v, "code": None, "ranges": None, "calls": [], "has_handler_self_target": False}
                    blocks.append(current)
                    continue
                if name == "Effect.Clone" or (val is not None and (_text(val) or "").endswith(":Clone()")):
                    if blocks:
                        prev = dict(blocks[-1])
                        prev["var"] = v
                        blocks.append(prev)
                        current = prev
                    continue
                if current is not None and name and current["var"] and name.startswith(current["var"] + ":"):
                    method = name.split(":", 1)[1]
                    if method == "SetCode" and len(args) == 1:
                        current["code"] = _eval_int(args[0], constants)
                    elif method == "SetTargetRange" and len(args) == 2:
                        current["ranges"] = (_eval_int(args[0], constants), _eval_int(args[1], constants))
                    current["calls"].append(method)
                elif current is not None:
                    # Handle Clone nested inside if blocks (like global_check / sub-blocks)
                    pass
    matched = [b for b in blocks if b["code"] == target_event]
    if not matched:
        return None
    # Disambiguate by target/condition/value presence if multiple
    if len(matched) > 1:
        want = set(cbs)
        best = max(matched, key=lambda b: len(want & {k.removeprefix("Set").lower() for k in b["calls"]}))
        info = best
    else:
        info = matched[0]
    if info["ranges"] is not None:
        return dict(s_range=info["ranges"][0], o_range=info["ranges"][1])
    return {}


def _is_self_protection_target(lua, rule):
    """Detect field protection rules (e.g. Ancient Gear Engineer) that only target cards targeting self."""
    cbs = rule.get("callbacks", {})
    if "target" not in cbs:
        return False
    node, _ = lua.registered_callback(cbs["target"])
    if node is None:
        return False
    for call_node in _walk(node):
        name, _ = _call(call_node)
        if name and ("GetCardTarget" in name or "GetHandler" in name):
            for other in _walk(node):
                oname, _ = _call(other)
                if oname and oname.endswith(":IsContains"):
                    return True
    return False


def _named_const_match(constants, names, value):
    return any(_const(constants, n) == value for n in names if _const(constants, n))


def _classify_non_scoring(lua, rule, code, constants):
    """Classify non-scoring `scope='card'` registrations cleanly."""
    if rule["scope"] != "card":
        return None
    kind, event, category = rule["type"], rule["event"], rule["category"]
    cbs = rule.get("callbacks", {})
    activatable = (
        _const(constants, "EFFECT_TYPE_ACTIVATE")
        | _const(constants, "EFFECT_TYPE_IGNITION")
        | _const(constants, "EFFECT_TYPE_TRIGGER_O")
        | _const(constants, "EFFECT_TYPE_TRIGGER_F")
        | _const(constants, "EFFECT_TYPE_QUICK_O")
        | _const(constants, "EFFECT_TYPE_QUICK_F")
    )
    if category == 0 and not (kind & activatable):
        if _named_const_match(constants, _SUMMON_PROCEDURE_NAMES, event):
            return dict(rule=rule, status="summon_procedure")
        if event == code:
            return dict(rule=rule, status="restriction_rule")
        if _named_const_match(constants, _SUMMON_RULE_NAMES, event) or (event & 0xffff0000) == 0x10000:
            return dict(rule=rule, status="summon_rule")
        if _named_const_match(constants, _ACTIVATION_RULE_NAMES, event):
            return dict(rule=rule, status="activation_rule")
        if _named_const_match(constants, _RESTRICTION_RULE_NAMES, event):
            return dict(rule=rule, status="restriction_rule")
        if _named_const_match(constants, _UTILITY_RULE_NAMES, event):
            return dict(rule=rule, status="continuous_utility")

        floodgate_op = next((v for k, v in _FLOODGATE_EVENTS.items() if _const(constants, k) == event), None)
        if floodgate_op is not None and (kind & _const(constants, "EFFECT_TYPE_FIELD")):
            if _is_self_protection_target(lua, rule):
                return dict(rule=rule, status="continuous_utility")
            ranges = _initial_effect_field_info(lua, rule, code, constants)
            if ranges and ranges.get("o_range") == 0:
                return dict(rule=rule, status="restriction_rule")
            # Genuine opponent/field continuous floodgate — scored downstream!
            return "floodgate:" + floodgate_op
        if floodgate_op is not None:
            return dict(rule=rule, status="restriction_rule")
        if kind & _const(constants, "EFFECT_TYPE_CONTINUOUS"):
            return dict(rule=rule, status="continuous_utility")
        if kind & (_const(constants, "EFFECT_TYPE_SINGLE") | _const(constants, "EFFECT_TYPE_EQUIP") | _const(constants, "EFFECT_TYPE_FIELD")):
            return dict(rule=rule, status="continuous_utility")

    if (kind & _const(constants, "EFFECT_TYPE_ACTIVATE")) and event == _const(constants, "EVENT_FREE_CHAIN") and category == 0:
        if "operation" not in cbs:
            return dict(rule=rule, status="activation_only")
    return None


def _zone_from_range(area, constants):
    zones = _mask_zones(area, constants)
    for preferred in ("hand", "pzone", "field", "spell_trap", "grave", "banished", "extra"):
        if preferred in zones:
            return preferred
    return None


def _analyze_condition(lua, rule, code, constants, functions):
    """Extract condition-derived gates: summon type, previous location, reason, class counts, own presence."""
    info = {
        "previous_location": None,
        "hand_deck_controller": None,
        "required_reason": None,
        "required_summon_type": None,
        "distinct_name_requirements": [],
        "presence_requirements": [],
        "event_group_query": None,
        "status": "recognized",
    }
    cbs = rule.get("callbacks", {})
    if "condition" not in cbs:
        return info
    cond_node, cond_funcs = lua.registered_callback(cbs["condition"])
    all_funcs = {**functions, **cond_funcs}
    if cond_node is None:
        return info
    ref = f"{cbs['condition']['file']}:{cbs['condition']['lines'][0]}"
    env = {"labels": tuple(rule.get("labels") or ())}

    # Collect local variable assignments (e.g. local g=Duel.GetMatchingGroup(...))
    locals_map = {}
    for node in _walk(cond_node):
        v, val = _local_value(node)
        if v and val is not None:
            locals_map[v] = val

    summon_map = {
        _const(constants, "SUMMON_TYPE_FUSION"): "fusion",
        _const(constants, "SUMMON_TYPE_SYNCHRO"): "synchro",
        _const(constants, "SUMMON_TYPE_XYZ"): "xyz",
        _const(constants, "SUMMON_TYPE_LINK"): "link",
        _const(constants, "SUMMON_TYPE_RITUAL"): "ritual",
        _const(constants, "SUMMON_TYPE_PENDULUM"): "pendulum",
        _const(constants, "SUMMON_TYPE_ADVANCE"): "tribute",
    }

    visited_calls = set()
    nodes_to_scan = [cond_node]
    while nodes_to_scan:
        root_n = nodes_to_scan.pop()
        for node in _walk(root_n):
            name, args = _call_parts(node)
            if not name:
                continue
            if name in all_funcs and name not in visited_calls and len(visited_calls) < 8:
                visited_calls.add(name)
                nodes_to_scan.append(all_funcs[name])
            if name.endswith(":IsSummonType") and len(args) == 1:
                st = _eval_int(args[0], constants, env)
                if st in summon_map:
                    info["required_summon_type"] = summon_map[st]
            elif name.endswith(":IsPreviousLocation") and len(args) == 1:
                loc = _eval_int(args[0], constants, env)
                # Only treat as handler's own previous location when called on c / e:GetHandler()
                recv = name.rsplit(":", 1)[0]
                if "GetHandler" in _text(node) or recv in ("c", "hc"):
                    deck_hand = _const(constants, "LOCATION_DECK") | _const(constants, "LOCATION_HAND")
                    onfield = _const(constants, "LOCATION_ONFIELD")
                    if loc == deck_hand:
                        info["previous_location"] = "hand_or_deck"
                        info["hand_deck_controller"] = "self"
                    elif loc and (loc & onfield) and not (loc & _const(constants, "LOCATION_DECK")):
                        info["previous_location"] = "field"
                    elif loc and (loc & _const(constants, "LOCATION_GRAVE")):
                        info["previous_location"] = "grave"
            elif name.endswith(":IsReason") and len(args) == 1:
                rs = _eval_int(args[0], constants, env)
                if rs == _const(constants, "REASON_EFFECT"):
                    # Make sure not inside `not e:GetHandler():IsReason(...)`
                    parent = node.parent
                    negated = parent is not None and parent.type == "unary_expression"
                    if not negated:
                        info["required_reason"] = "effect"
            elif name == "Duel.IsExistingMatchingCard" and len(args) >= 5:
                s_loc = _eval_int(args[2], constants, env) or 0
                o_loc = _eval_int(args[3], constants, env) or 0
                min_ct = _eval_int(args[4], constants, env) or 1
                parent = node.parent
                negated = parent is not None and parent.type == "unary_expression"
                if s_loc != 0 and o_loc == 0 and not negated and min_ct >= 1:
                    fn_name, extra = _resolve_fn_name(args[0], constants)
                    call_extras = (*extra, *args[6:]) if not extra else extra
                    query = (
                        _extract_filter_query(all_funcs[fn_name], all_funcs, constants, code,
                                              extra_args=call_extras, env=env)[0]
                        if fn_name in all_funcs
                        else (_builtin_card_query(fn_name, call_extras, constants, env) if fn_name else None)
                    )
                    zones = _mask_zones(s_loc, constants, normalize_field=True)
                    # Only gate static inventory on deck/grave/extra/banished/field own requirements;
                    # skip opponent-only or purely positional field states if query is empty.
                    if query and query != {"type": 7} and zones and query_supported(query):
                        # Only require card identity presence for grave/field/banished/deck/hand/extra checks
                        if any(z in ("grave", "deck", "hand", "extra", "banished", "field") for z in zones):
                            # Check whether inside an `or` clause; if inside top-level `and` / direct return, enforce!
                            anc = node.parent
                            in_or = False
                            while anc is not None and anc != root_n:
                                if anc.type == "binary_expression" and _text(anc.child_by_field_name("operator")) == "or":
                                    in_or = True
                                    break
                                anc = anc.parent
                            if not in_or:
                                info["presence_requirements"].append(dict(
                                    query=query, quantity=min_ct, minimum=min_ct, from_zones=zones, owner="self",
                                    source=ref, category="conditions", origin=zones[0] if len(zones) == 1 else "choice",
                                    origins=zones, selector_query=query))
            elif name.endswith(":GetClassCount"):
                # e.g., g:GetClassCount(Card.GetCode) >= e:GetLabel() or == 12
                gvar = name.rsplit(":", 1)[0]
                gdef = locals_map.get(gvar)
                gname, gargs = _call(gdef)
                if gname == "Duel.GetMatchingGroup" and len(gargs) >= 4:
                    s_loc = _eval_int(gargs[2], constants, env) or 0
                    o_loc = _eval_int(gargs[3], constants, env) or 0
                    parent = node.parent
                    threshold = None
                    if parent is not None and parent.type == "binary_expression":
                        op = _text(parent.child_by_field_name("operator"))
                        if op in (">=", "==", ">"):
                            other = parent.child_by_field_name("right")
                            val = _eval_int(other, constants, env)
                            if val is not None:
                                threshold = val + 1 if op == ">" else val
                    fn_name, extra = _resolve_fn_name(gargs[0], constants)
                    query, _ = (_extract_filter_query(all_funcs.get(fn_name), all_funcs, constants, code,
                                                      extra_args=extra, env=env)
                                if fn_name in all_funcs else (None, {}))
                    zones = _mask_zones(s_loc, constants, normalize_field=True)
                    if s_loc != 0 and o_loc == 0 and threshold and threshold > 0 and query and query_supported(query) and zones:
                        info["distinct_name_requirements"].append(dict(
                            query=query, selector_query=query, quantity=threshold, minimum=threshold,
                            distinct_names=True, from_zones=zones,
                            origin=zones[0] if len(zones) == 1 else "choice",
                            origins=zones, owner="self", category="conditions", source=ref))
            elif name.endswith(":IsExists") and len(args) >= 3:
                gvar = name.rsplit(":", 1)[0]
                # Check event group (eg:IsExists)
                if gvar == "eg" or "eg" in gvar:
                    fn_name, extra = _resolve_fn_name(args[0], constants)
                    if fn_name in all_funcs:
                        q, _ = _extract_filter_query(all_funcs[fn_name], all_funcs, constants, code,
                                                     extra_args=extra, env=env)
                        if q and q != {"type": 7} and query_supported(q):
                            info["event_group_query"] = q
    return info


def _analyze_cost(lua, rule, code, constants, functions):
    """Extract Xyz detach, LP payments, oaths, self-moves, and filtered own-card costs."""
    costs = []
    restrictions = []
    cbs = rule.get("callbacks", {})
    if "cost" not in cbs:
        return costs, restrictions
    cost_source = cbs["cost"]
    cost_node, cost_funcs = lua.registered_callback(cost_source)
    all_funcs = {**functions, **cost_funcs}
    if cost_node is None:
        return costs, restrictions
    ref = f"{cost_source['file']}:{cost_source['lines'][0]}"
    params, _ = _body(cost_node)
    player = params[1] if len(params) >= 2 else "tp"

    if _handler_send_cost(cost_node, constants):
        costs.append(dict(
            kind="send_grave", from_zones=["hand"], to_zone="grave", reason="cost",
            quantity=1, owner="self", subject="this_card", source_card_id=code,
            selector_query={"predicate": {"field": "card_ids", "value": [code]}}, source=ref,
        ))
        return costs, restrictions

    visited = set()
    to_scan = [cost_node]
    while to_scan:
        root_n = to_scan.pop()
        for node in _walk(root_n):
            name, args = _call_parts(node)
            if not name:
                continue
            if name in all_funcs and name not in visited and len(visited) < 8:
                visited.add(name)
                to_scan.append(all_funcs[name])
            if name.endswith(":RemoveOverlayCard") and len(args) >= 2:
                qty = _eval_int(args[1], constants) or 1
                costs.append(dict(
                    kind="xyz_detach", from_zones=["xyz_material"], to_zone="grave", reason="cost",
                    quantity=max(1, qty), owner="self", subject="this_card", source=ref,
                ))
            elif name == "Duel.PayLPCost" and len(args) >= 2:
                amt = _eval_int(args[1], constants)
                if amt and amt > 0:
                    costs.append(dict(resource="lp", quantity=amt, reason="cost", owner="self", source=ref))
                elif "GetLP" in _text(args[1]) and ("/2" in _text(args[1]) or "2" in _text(args[1])):
                    costs.append(dict(resource="lp", lp_divisor=2, quantity=1, reason="cost", owner="self", source=ref))
            elif name == "Duel.RemoveCounter" and len(args) >= 5:
                costs.append(dict(resource="counter", quantity=_eval_int(args[4], constants) or 1,
                                  reason="cost", owner="self", source=ref))
            elif name == "Duel.DiscardHand" and len(args) >= 4:
                qty = _eval_int(args[2], constants) or 1
                fn_name, extra = _resolve_fn_name(args[1], constants)
                query = ({"type": 7} if fn_name is None else
                         (_extract_filter_query(all_funcs.get(fn_name), all_funcs, constants, code, extra_args=extra)[0]
                          if fn_name in all_funcs else {"type": 7}))
                if query and query_supported(query):
                    costs.append(dict(
                        kind="discard", from_zones=["hand"], to_zone="grave", reason="cost",
                        quantity=qty, owner="self", selector_query=query,
                        exclude_source_copy=True, source_card_id=code, source=ref,
                    ))
            elif name == "Duel.SelectMatchingCard" and len(args) >= 6:
                s_loc = _eval_int(args[2], constants) or 0
                o_loc = _eval_int(args[3], constants) or 0
                qty = _eval_int(args[4], constants) or 1
                zones = _mask_zones(s_loc, constants, normalize_field=True)
                fn_name, extra = _resolve_fn_name(args[0], constants)
                query = (_extract_filter_query(all_funcs.get(fn_name), all_funcs, constants, code, extra_args=extra)[0]
                         if fn_name in all_funcs else {"type": 7})
                if s_loc != 0 and o_loc == 0 and zones and query and query_supported(query):
                    costs.append(dict(
                        kind="send_grave", from_zones=zones, to_zone="grave", reason="cost",
                        quantity=qty, owner="self", selector_query=query,
                        exclude_source_copy=True, source_card_id=code, source=ref,
                    ))
            elif name == "Duel.SelectReleaseGroup" and len(args) >= 3:
                qty = _eval_int(args[2], constants) or 1
                fn_name, extra = _resolve_fn_name(args[1], constants)
                query = (_extract_filter_query(all_funcs.get(fn_name), all_funcs, constants, code, extra_args=extra)[0]
                         if fn_name in all_funcs else {"type": 1})
                if query and query_supported(query):
                    costs.append(dict(
                        kind="release", from_zones=["field"], to_zone="grave", reason="cost",
                        quantity=qty, owner="self", selector_query=query,
                        exclude_source_copy=True, source_card_id=code, source=ref,
                    ))
            elif name.endswith(":IsAbleToRemoveAsCost") or (name == "aux.bfgcost" or name == "Auxiliary.bfgcost"):
                costs.append(dict(
                    kind="banish", from_zones=["grave"], to_zone="banished", reason="cost",
                    quantity=1, owner="self", subject="this_card", source_card_id=code,
                    selector_query={"predicate": {"field": "card_ids", "value": [code]}}, source=ref,
                ))
            elif name == "Duel.SendtoGrave" and len(args) >= 2 and "GetHandler" in _text(args[0]):
                costs.append(dict(
                    kind="send_grave", from_zones=[_zone_from_range(rule["range"], constants) or "hand"],
                    to_zone="grave", reason="cost", quantity=1, owner="self", subject="this_card",
                    source_card_id=code, selector_query={"predicate": {"field": "card_ids", "value": [code]}},
                    source=ref,
                ))
            elif name == "Duel.Remove" and len(args) >= 2 and "GetHandler" in _text(args[0]):
                costs.append(dict(
                    kind="banish", from_zones=[_zone_from_range(rule["range"], constants) or "grave"],
                    to_zone="banished", reason="cost", quantity=1, owner="self", subject="this_card",
                    source_card_id=code, selector_query={"predicate": {"field": "card_ids", "value": [code]}},
                    source=ref,
                ))
            elif name == "Duel.RegisterEffect":
                # Check oath summon lock (e.g., Robina / Pot of Duality / Extravagance)
                txt = _text(root_n)
                if "EFFECT_CANNOT_SPECIAL_SUMMON" in txt:
                    restrictions.append(dict(
                        kind="cannot_special_summon", scope="player", controller="self", owner="self",
                        condition="effect_activation", duration="turn", whole_turn=True, source=ref,
                    ))
                elif "EFFECT_CANNOT_DRAW" in txt:
                    restrictions.append(dict(
                        kind="cannot_draw", scope="player", controller="self", owner="self",
                        condition="effect_activation", duration="turn", whole_turn=True, source=ref,
                    ))
    # Deduplicate self costs if Check + Payment both scanned
    if any(c.get("subject") == "this_card" and c.get("kind") != "xyz_detach" for c in costs):
        seen = set()
        deduped = []
        for c in costs:
            k = (c.get("kind"), c.get("resource"), tuple(c.get("from_zones", ())))
            if k not in seen:
                seen.add(k)
                deduped.append(c)
        costs = deduped
    return costs, restrictions


def _extract_restrictions_in_op(op_node, functions, constants, code, ref):
    """Extract self restrictions registered inside operation (e.g. Gilgamesh D/D-only rest-of-turn lock)."""
    restrictions = []
    txt = _text(op_node)
    if "Duel.RegisterEffect" not in txt:
        return restrictions
    locals_map = {}
    eff_props = {}
    for node in _walk(op_node):
        v, val = _local_value(node)
        if v and val is not None:
            locals_map[v] = val
            n, _ = _call_parts(val)
            if n == "Effect.CreateEffect":
                eff_props[v] = {}
        name, args = _call_parts(node)
        if name and ":" in name:
            var, method = name.split(":", 1)
            if var in eff_props and len(args) >= 1:
                if method == "SetCode":
                    eff_props[var]["code"] = _eval_int(args[0], constants)
                elif method == "SetTargetRange" and len(args) == 2:
                    eff_props[var]["ranges"] = (_eval_int(args[0], constants), _eval_int(args[1], constants))
                elif method == "SetTarget":
                    fn_name, _ = _resolve_fn_name(args[0], constants)
                    eff_props[var]["target_fn"] = fn_name
                elif method == "SetReset":
                    eff_props[var]["reset"] = _eval_int(args[0], constants)
                elif method == "SetValue":
                    fn_name, _ = _resolve_fn_name(args[0], constants)
                    eff_props[var]["value_fn"] = fn_name
    for props in eff_props.values():
        s_r, o_r = props.get("ranges") or (None, None)
        if props.get("code") == _const(constants, "EFFECT_CANNOT_SPECIAL_SUMMON") and s_r and o_r == 0:
            allowed_pred = None
            tfn = functions.get(props.get("target_fn"))
            if tfn is not None:
                _, tbody = _body(tfn)
                ret = _return_expression(tbody)
                # Typical Lua: `return not c:IsSetCard(0xaf)` -> allowed_summons is `setcode == 0xaf`
                if ret is not None and ret.type == "unary_expression" and _text(ret.child_by_field_name("operator")) == "not":
                    inner_q, _ = _extract_filter_query(tfn, functions, constants, code)
                    if inner_q and isinstance(inner_q.get("predicate"), dict) and "not" in inner_q["predicate"]:
                        allowed_pred = inner_q["predicate"]["not"]
            r = dict(
                kind="cannot_special_summon", scope="player", controller="self", owner="self",
                condition="effect_use", duration="turn", whole_turn=False, source=ref,
            )
            if allowed_pred:
                r["allowed_summons"] = allowed_pred
                r["lua_summon_lock"] = dict(duration="turn", controller="self", from_zones=[], allowed_summons=allowed_pred)
            restrictions.append(r)
    return restrictions


def _extract_filter_from_selection(sel_node, all_funcs, constants, code, env):
    name, args = _call_parts(sel_node)
    if name in ("Duel.SelectMatchingCard", "Duel.GetMatchingGroup", "Duel.SelectTarget", "Duel.IsExistingMatchingCard"):
        fn_arg = args[0] if name == "Duel.GetMatchingGroup" else args[1] if name == "Duel.SelectMatchingCard" else (
            args[1] if len(args) >= 6 and name in ("Duel.SelectTarget", "Duel.IsExistingMatchingCard") else None)
        # Wait: signature check!
        # Duel.SelectMatchingCard(sel_player, f, player, s, o, min, max, ex, ...) -> f is args[1], player args[2], s args[3], o args[4], min args[5]
        # Duel.SelectTarget(sel_player, f, player, s, o, min, max, ex, ...) -> f is args[1], player args[2], s args[3], o args[4], min args[5]
        # Duel.GetMatchingGroup(f, player, s, o, ex, ...) -> f is args[0], player args[1], s args[2], o args[3]
        if name in ("Duel.SelectMatchingCard", "Duel.SelectTarget") and len(args) >= 6:
            fn_node, s_arg, o_arg, qty_arg = args[1], args[3], args[4], args[5]
        elif name == "Duel.GetMatchingGroup" and len(args) >= 4:
            fn_node, s_arg, o_arg, qty_arg = args[0], args[2], args[3], None
        elif name == "Duel.IsExistingMatchingCard" and len(args) >= 5:
            fn_node, s_arg, o_arg, qty_arg = args[0], args[2], args[3], args[4]
        else:
            return None, [], [], 1
        s_loc = _eval_int(s_arg, constants, env) or 0
        o_loc = _eval_int(o_arg, constants, env) or 0
        qty = _eval_int(qty_arg, constants, env) or 1 if qty_arg is not None else 1
        fn_name, extra = _resolve_fn_name(fn_node, constants)
        query = None
        if fn_name and fn_name in all_funcs:
            query, _ = _extract_filter_query(all_funcs[fn_name], all_funcs, constants, code, extra_args=extra, env=env)
        elif _text(fn_node) == "aux.TRUE":
            query = {"type": 7}
        if query and not query_supported(query):
            query = None
        return query, _mask_zones(s_loc, constants, normalize_field=True), _mask_zones(o_loc, constants, normalize_field=True), max(1, qty)
    return None, [], [], 1


def _collect_selections(roots, all_funcs, constants, code, env):
    """Collect all own/opponent group selections in `target` and `operation` (and SubGroups)."""
    own_sels = []
    opp_sels = []
    for root_n in roots:
        locals_map = {}
        for node in _walk(root_n):
            v, val = _local_value(node)
            if v and val is not None:
                locals_map[v] = val
            name, args = _call_parts(node)
            if not name:
                continue
            if name in ("Duel.SelectMatchingCard", "Duel.GetMatchingGroup", "Duel.SelectTarget"):
                q, sz, oz, qty = _extract_filter_from_selection(node, all_funcs, constants, code, env)
                if sz and not oz:
                    own_sels.append(dict(query=q or {"type": 7}, from_zones=sz, quantity=qty, var=v))
                elif oz:
                    opp_sels.append(dict(query=q or {"type": 7}, from_zones=oz, quantity=qty, own_also=bool(sz), var=v))
            elif name.endswith(":SelectSubGroup") and len(args) >= 4:
                qty = _eval_int(args[3], constants, env) or 2
                base_var = name.rsplit(":", 1)[0]
                if base_var in locals_map:
                    q, sz, _, _ = _extract_filter_from_selection(locals_map[base_var], all_funcs, constants, code, env)
                    if sz:
                        # Replace the raw GetMatchingGroup placeholder with the refined SelectSubGroup count/uniqueness
                        own_sels[:] = [s for s in own_sels if s.get("var") != base_var]
                        own_sels.append(dict(query=q or {"type": 7}, from_zones=sz, quantity=qty, distinct_names=True, var=v))
    return own_sels, opp_sels


def _collect_roots_and_calls(op_node, tgt_node, all_funcs):
    """Expand helper functions and registered SetOperation callbacks into flat calls list."""
    roots = [op_node] + ([tgt_node] if tgt_node is not None else [])
    visited = set()
    scan = list(roots)
    while scan and len(visited) < 16:
        n = scan.pop()
        for call_n in _walk(n):
            cname, cargs = _call_parts(call_n)
            if not cname:
                continue
            if cname in all_funcs and cname not in visited:
                visited.add(cname)
                scan.append(all_funcs[cname])
                roots.append(all_funcs[cname])
            if cname.endswith(":SetOperation") and len(cargs) == 1:
                fn_name, _ = _resolve_fn_name(cargs[0])
                if fn_name and fn_name in all_funcs and fn_name not in visited:
                    visited.add(fn_name)
                    scan.append(all_funcs[fn_name])
                    roots.append(all_funcs[fn_name])
    op_roots = [op_node] + [all_funcs[f] for f in visited if f in all_funcs]
    calls = []
    for r in op_roots:
        for n in _walk(r):
            cname, args = _call_parts(n)
            if cname:
                calls.append((cname, args, n))
    return roots, op_roots, calls


def _destroy_recipient(operation, target, functions, constants, code, env):
    """Follow the destroyed group to its producer before assigning an owner."""
    locals_ = {}
    recipients = []
    for node in _walk(operation):
        var, value = _local_value(node)
        if var:
            locals_[var] = value
        name, args = _call_parts(node)
        if name != "Duel.Destroy" or not args:
            continue
        obj = locals_.get(_name(args[0]), args[0])
        producer, inputs = _call_parts(obj)
        if producer == "Duel.GetFirstTarget" and target is not None:
            choices = [n for n in _walk(target) if _call_parts(n)[0] == "Duel.SelectTarget"]
            if len(choices) == 1:
                obj = choices[0]
                producer, inputs = _call_parts(obj)
        if producer and producer.endswith(":GetHandler"):
            recipients.append(("self", {"subject": "this_card"}))
            continue
        if producer and producer.endswith(":GetBattleTarget"):
            receiver = obj.child_by_field_name("name").child_by_field_name("table")
            handler = locals_.get(_name(receiver), receiver)
            handler_call, _ = _call_parts(handler)
            if handler_call and handler_call.endswith(":GetHandler"):
                recipients.append(("opponent", {"subject": "battle_target"}))
                continue
        if producer not in ("Duel.GetMatchingGroup", "Duel.SelectTarget", "Duel.SelectMatchingCard"):
            return None
        query, own, opp, qty = _extract_filter_from_selection(obj, functions, constants, code, env)
        player = _text(inputs[1 if producer == "Duel.GetMatchingGroup" else 2])
        if player.replace(" ", "") == "1-tp":
            own, opp = opp, own
        elif player != "tp":
            return None
        if not own and not opp:
            return None
        owner = "both" if own and opp else "self" if own else "opponent"
        details = dict(from_zones=own or opp, quantity=qty, whole_group=producer == "Duel.GetMatchingGroup")
        predicate = inputs[0 if producer == "Duel.GetMatchingGroup" else 1]
        details['unfiltered_group'] = _text(predicate) in ('nil', 'aux.TRUE', 'Auxiliary.TRUE')
        own_index = 2 if producer == "Duel.GetMatchingGroup" else 3
        if player != 'tp':
            own_index += 1
        details['own_location_mask'] = _eval_int(inputs[own_index], constants, env)
        if query:
            details['selector_query'] = query
        recipients.append((owner, details))
    if recipients and all(r == recipients[0] for r in recipients):
        return recipients[0]
    return None


def _extract_general_operations(lua, rule, code, constants, trigger, cost_info):
    """Analyze `operation` + `target` ASTs to emit exact operations, targets, and extra requirements."""
    cbs = rule.get("callbacks", {})
    op_source = cbs.get("operation")
    if not op_source:
        return None
    ref = f"{op_source['file']}:{op_source['lines'][0]}"
    # Check Ritual procedures first: Aux.AddRitualProc* points operation into utility.lua!
    if (rule["category"] & _const(constants, "CATEGORY_SPECIAL_SUMMON")) and lua.uses_ritual_procedure(rule):
        return dict(
            operations=[dict(kind="ritual_summon", from_zones=["hand"], to_zone="field", quantity=1, random=False,
                             ritual_stock_query=True)],
            extra_reqs=[], restrictions=[], fusion=False, ritual=True,
        )

    op_node, op_funcs = lua.registered_callback(op_source)
    tgt_node, tgt_funcs = lua.registered_callback(cbs["target"]) if "target" in cbs else (None, {})
    all_funcs = {**tgt_funcs, **op_funcs}
    if op_node is None:
        return None

    # 1. Existing exact detectors
    if tgt_node is not None:
        exact = _checked_deck_output(op_node, tgt_node, constants) or _legacy_deck_selection(op_node, tgt_node, all_funcs, constants)
        if exact:
            return dict(operations=[exact], extra_reqs=[], restrictions=[], fusion=False, ritual=False)
    else:
        exact = _deck_output(op_node, constants) or _summon_draw(op_node, all_funcs, constants)
        if exact:
            return dict(operations=[exact], extra_reqs=[], restrictions=[], fusion=False, ritual=False)

    env = {"labels": tuple(rule.get("labels") or ())}
    roots, op_roots, calls = _collect_roots_and_calls(op_node, tgt_node, all_funcs)
    op_text = "\n".join(_text(r) for r in op_roots)
    tgt_text = _text(tgt_node) if tgt_node else ""
    call_names = {c for c, _, _ in calls}
    own_sels, opp_sels = _collect_selections(roots, all_funcs, constants, code, env)
    restrictions = _extract_restrictions_in_op(op_node, all_funcs, constants, code, ref)
    extra_reqs = []
    target_param = None
    if tgt_node is not None:
        for tnode in _walk(tgt_node):
            tname, targs = _call_parts(tnode)
            if tname == "Duel.SetTargetParam" and len(targs) == 1:
                pval = _eval_int(targs[0], constants, env)
                if pval and pval > 0:
                    target_param = pval

    def _is_self_expr(arg_node):
        txt = _text(arg_node)
        return "GetHandler" in txt or txt in ("c", "e:GetHandler()")

    # 2. Check Fusion summon inside operation
    if (rule["category"] & _const(constants, "CATEGORY_FUSION_SUMMON")) or (
            "SUMMON_TYPE_FUSION" in op_text and ("Duel.SpecialSummon" in call_names or "Duel.SpecialSummonStep" in call_names)):
        return dict(
            operations=[dict(kind="fusion_summon", from_zones=["extra"], to_zone="field", quantity=1, random=False)],
            extra_reqs=[], restrictions=restrictions, fusion=True,
            fusion_returns_to_deck=("SendtoDeck" in op_text or "PlaceCardsOnDeck" in op_text), ritual=False,
        )

    # 3. Check Ritual summon
    if (rule["category"] & _const(constants, "CATEGORY_SPECIAL_SUMMON")) and (
            "SUMMON_TYPE_RITUAL" in op_text or "SUMMON_TYPE_RITUAL" in tgt_text):
        return dict(
            operations=[dict(kind="ritual_summon", from_zones=["hand"], to_zone="field", quantity=1, random=False,
                             ritual_stock_query=True)],
            extra_reqs=[], restrictions=restrictions, fusion=False, ritual=True,
        )

    # 4. Check Pendulum scale placement (e.g., D/D/D Gilgamesh)
    if "Duel.MoveToField" in call_names and "LOCATION_PZONE" in op_text:
        sel = (
            next((s for s in own_sels if s["from_zones"] == ["deck"] and s.get("distinct_names")), None)
            or next((s for s in own_sels if s["from_zones"] == ["deck"]), None)
            or (own_sels[0] if own_sels else None)
        )
        qty = (sel["quantity"] if sel else 2)
        op = dict(
            kind="place_pendulum_scales", from_zones=sel["from_zones"] if sel else ["deck"],
            to_zone="pzone", quantity=qty, random=False,
            distinct_names=bool(sel and sel.get("distinct_names")) or "GetClassCount" in tgt_text or "GetClassCount" in op_text,
            selector_query=(sel["query"] if sel else {"type": 1}),
        )
        return dict(operations=[op], extra_reqs=[], restrictions=restrictions, fusion=False, ritual=False)

    # 5. Check Lingering operation-registered floodgates / maintenance / self protection
    has_ss_or_move = bool(call_names & {
        "Duel.SpecialSummon", "Duel.SpecialSummonStep", "Duel.SendtoHand", "Duel.SendtoGrave",
        "Duel.SendtoDeck", "Duel.Destroy", "Duel.Remove", "Duel.Draw", "Duel.DiscardDeck",
        "Duel.NegateActivation", "Duel.NegateEffect", "Duel.NegateSummon", "Duel.ChangeChainOperation",
        "Duel.Summon", "Duel.LinkSummon",
    })
    if "Duel.RegisterEffect" in call_names and rule["category"] == 0 and not has_ss_or_move:
        if "EFFECT_CANNOT_ACTIVATE" in op_text and "LOCATION_GRAVE" in op_text:
            return dict(
                operations=[dict(kind="prevent_activation", from_zones=["grave"], to_zone=None, owner="opponent",
                                 quantity=1, random=False)],
                extra_reqs=[], restrictions=restrictions, fusion=False, ritual=False,
            )
        if "EFFECT_CANNOT_ACTIVATE" in op_text:
            return dict(
                operations=[dict(kind="prevent_activation", from_zones=[], to_zone=None, owner="opponent",
                                 quantity=1, random=False)],
                extra_reqs=[], restrictions=restrictions, fusion=False, ritual=False,
            )
        if "EFFECT_TO_GRAVE_REDIRECT" in op_text:
            return dict(
                operations=[dict(kind="banish_replacement", from_zones=["field", "hand", "deck"], to_zone="banished",
                                 owner="opponent", quantity=1, random=False)],
                extra_reqs=[], restrictions=restrictions, fusion=False, ritual=False,
            )
        if "EFFECT_CANNOT_SPECIAL_SUMMON" in op_text:
            return dict(
                operations=[dict(kind="prevent_special_summon", from_zones=[], to_zone=None, owner="opponent",
                                 quantity=1, random=False)],
                extra_reqs=[], restrictions=restrictions, fusion=False, ritual=False,
            )
        if "EFFECT_DISABLE" in op_text:
            return dict(
                operations=[dict(kind="negate_effect", from_zones=[], to_zone=None, owner="opponent",
                                 quantity=1, random=False)],
                extra_reqs=[], restrictions=restrictions, fusion=False, ritual=False,
            )
        if any(tok in op_text for tok in ("EFFECT_INDESTRUCTABLE", "EFFECT_AVOID_BATTLE_DAMAGE")):
            return dict(utility_only=True, status="continuous_utility")

    # Non-scoring lingering self-stat / overlay maintenance (e.g. Mudragon attribute shift, Downerd detach)
    if rule["category"] == 0 and not has_ss_or_move and not opp_sels:
        if any(tok in op_text for tok in ("EFFECT_CHANGE_ATTRIBUTE", "EFFECT_INDESTRUCTABLE", "RemoveOverlayCard")):
            return dict(utility_only=True, status="continuous_utility")
        if any(tok in op_text for tok in ("EFFECT_DISABLE", "EFFECT_SET_ATTACK_FINAL")):
            return dict(
                operations=[dict(kind="negate_effect", from_zones=[], to_zone=None, owner="opponent",
                                 quantity=1, random=False)],
                extra_reqs=[], restrictions=restrictions, fusion=False, ritual=False,
            )
    if rule["category"] == 0 and "equip_monster" in op_text and opp_sels:
        return dict(
            operations=[dict(kind="control_change", from_zones=["field"], to_zone="field", quantity=1,
                             random=False, owner="opponent")],
            extra_reqs=[], restrictions=restrictions, fusion=False, ritual=False,
        )

    def pick_own(preferred=()):
        for s in own_sels:
            if not preferred or any(z in s["from_zones"] for z in preferred):
                return s
        return own_sels[0] if own_sels else None

    # 6. Extra Normal Summon support (either primary like Map/Dreaming Town or auxiliary alongside Robina search)
    extra_ns_ops = []
    if "Duel.Summon" in call_names:
        ns_sel = pick_own(("hand",)) or pick_own(("field", "deck"))
        extra_ns_ops.append(dict(
            kind="extra_normal_summon_supply", from_zones=["hand"], to_zone="field", owner="self",
            quantity=1, random=False, processing_role="auxiliary",
            selector_query=(ns_sel["query"] if ns_sel else {"type": 1}),
        ))

    ss_calls = {"Duel.SpecialSummon", "Duel.SpecialSummonStep"}
    # 7. Opponent negation (NegateActivation / NegateEffect / ChangeChainOperation / registered NegateEffect helper)
    if call_names & {"Duel.NegateActivation", "Duel.NegateEffect", "Duel.NegateSummon", "Duel.ChangeChainOperation"}:
        kind_neg = "negate_activation" if "Duel.NegateActivation" in call_names else (
            "negate_summon" if "Duel.NegateSummon" in call_names else "negate_effect")
        op = dict(kind=kind_neg, from_zones=[], to_zone=None, owner="opponent", quantity=1, random=False)
        has_companion_ss = (
            "Duel.SelectYesNo" not in call_names
            and any(cn in ss_calls and args and not _is_self_expr(args[0]) for cn, args, _ in calls)
        )
        if has_companion_ss:
            for ss_sel in own_sels:
                zones = ss_sel.get("from_zones", ())
                if (zones and set(zones) & {"hand", "deck", "grave"} and "field" not in zones
                        and ss_sel.get("query") and query_supported(ss_sel["query"])):
                    extra_reqs.append(dict(
                        category="operations", kind="special_summon",
                        query=ss_sel["query"], selector_query=ss_sel["query"],
                        quantity=ss_sel["quantity"], minimum=ss_sel["quantity"],
                        from_zones=zones,
                        origin=zones[0], origins=zones,
                        owner="self", exclude_source_copy=True,
                        source_card_id=code, source=ref,
                    ))
                    break
        return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    # 8. Mill / Deck-to-Grave (`Duel.DiscardDeck` or `Duel.GetDecktopGroup` + `SendtoGrave`)
    self_ss = any(cn in ss_calls and args and _is_self_expr(args[0]) for cn, args, _ in calls)
    for cn, args, cnode in calls:
        if cn == "Duel.DiscardDeck" and len(args) >= 3:
            qty = _eval_int(args[1], constants, env) or target_param or 1
            player_is_opp = "1-" in _text(args[0])
            ops_out = [dict(kind="send_grave", from_zones=["deck"], to_zone="grave", quantity=qty, random=True,
                            owner="opponent" if player_is_opp and "Merge" not in call_names else "self")]
            # e.g., Tearlaments Scheiren: Special Summons self from Hand + sends 1 monster from Hand to GY + mills 3
            if self_ss and not player_is_opp:
                if "Duel.SendtoGrave" in call_names and (hand_sel := pick_own(("hand",))):
                    extra_reqs.append(dict(
                        category="operations", kind="send_grave", query=hand_sel["query"], selector_query=hand_sel["query"],
                        quantity=hand_sel["quantity"], minimum=hand_sel["quantity"], from_zones=["hand"],
                        origin="hand", origins=["hand"], owner="self", exclude_source_copy=True,
                        source_card_id=code, source=ref,
                    ))
                ops_out.append(dict(
                    kind="special_summon", from_zones=[trigger["zone"] if trigger["zone"] in ("hand", "grave", "banished") else "hand"],
                    to_zone="field", quantity=1, random=False, owner="self", subject="this_card",
                    processing_role="auxiliary",
                ))
            ops_out.extend(extra_ns_ops)
            return dict(operations=ops_out, extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)
    if "Duel.GetDecktopGroup" in call_names and "Duel.SendtoGrave" in call_names:
        qty = 1
        for cn, args, _ in calls:
            if cn == "Duel.GetDecktopGroup" and len(args) >= 2 and "1-" not in _text(args[0]):
                qty = _eval_int(args[1], constants, env) or qty
        op = dict(kind="send_grave", from_zones=["deck"], to_zone="grave", quantity=qty, random=True, owner="self")
        return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    # 9. Recycle + Draw (`SendtoDeck` from GY + `Draw`, e.g., Runick Fountain, Keldo/Mudora)
    if "Duel.Draw" in call_names and not (rule["category"] & _const(constants, "CATEGORY_DISABLE")):
        draw_qty = 1
        for cn, args, _ in calls:
            if cn == "Duel.Draw" and len(args) >= 2:
                q_val = _eval_int(args[1], constants, env) or target_param
                if q_val and q_val > 0:
                    draw_qty = q_val
        if "Duel.SendtoDeck" in call_names and (sel := pick_own(("grave", "banished"))):
            extra_reqs.append(dict(
                category="operations", kind="return_deck", query=sel["query"], selector_query=sel["query"],
                quantity=sel["quantity"], minimum=sel["quantity"], from_zones=sel["from_zones"],
                origin=sel["from_zones"][0], origins=sel["from_zones"], owner="self", source=ref,
            ))
        op = dict(kind="draw", from_zones=["deck"], to_zone="hand", quantity=draw_qty, random=True, owner="self")
        return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    # 10. Speedroid Hound-style Recycle from GY to Deck -> Special Summon from Extra (skip self-return like Baronne!)
    non_self_send_deck = any(cn == "Duel.SendtoDeck" and args and not _is_self_expr(args[0]) for cn, args, _ in calls)
    if non_self_send_deck and (call_names & ss_calls):
        gy_sel = pick_own(("grave", "banished"))
        ex_sel = pick_own(("extra",))
        if gy_sel and ex_sel and "extra" not in gy_sel["from_zones"]:
            extra_reqs.append(dict(
                category="operations", kind="return_deck", query=gy_sel["query"], selector_query=gy_sel["query"],
                quantity=gy_sel["quantity"], minimum=gy_sel["quantity"], from_zones=gy_sel["from_zones"],
                origin=gy_sel["from_zones"][0], origins=gy_sel["from_zones"], owner="self", source=ref,
            ))
            op = dict(kind="special_summon", from_zones=["extra"], to_zone="field", quantity=ex_sel["quantity"],
                      random=False, owner="self", selector_query=ex_sel["query"])
            return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    # 11. Primary Search / Foolish / Recovery (`SendtoHand`, `SendtoGrave`, `SendtoDeck`, `Remove`, `SpecialSummon`, `LinkSummon`)
    if "Duel.LinkSummon" in call_names:
        op = dict(kind="link_summon", from_zones=["extra"], to_zone="field", quantity=1, random=False,
                  owner="self", selector_query={"type_all": _const(constants, "TYPE_LINK") | _const(constants, "TYPE_MONSTER")})
        return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    if "Duel.SendtoHand" in call_names:
        own_sel = pick_own(("deck", "grave", "banished", "field"))
        self_move = any(cn == "Duel.SendtoHand" and args and _is_self_expr(args[0]) and not own_sel
                        for cn, args, _ in calls)
        if self_move:
            src_zone = trigger["zone"] if trigger["zone"] in ("grave", "banished", "field") else "grave"
            op = dict(kind="recover", from_zones=[src_zone], to_zone="hand", quantity=1, random=False,
                      owner="self", subject="this_card")
            return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)
        if own_sel and not (opp_sels and not own_sel):
            fz = own_sel["from_zones"]
            kind_h = "search" if "deck" in fz else "recover" if ("grave" in fz or "banished" in fz) else "return_hand"
            alts = []
            if "Duel.SendtoGrave" in call_names and "SelectOption" in op_text:
                alts.append(dict(kind="send_grave", from_zones=fz, to_zone="grave", quantity=own_sel["quantity"],
                                 random=False, owner="self", selector_query=own_sel["query"]))
            op = dict(kind=kind_h, from_zones=fz, to_zone="hand", quantity=own_sel["quantity"], random=False,
                      owner="self", selector_query=own_sel["query"])
            if alts:
                op["alternative_operations"] = alts
            return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)
        if opp_sels or (rule["category"] & _const(constants, "CATEGORY_TOHAND")):
            op = dict(kind="return_hand", from_zones=["field"], to_zone="hand", quantity=1, random=False, owner="opponent")
            return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    if "Duel.SendtoGrave" in call_names:
        own_sel = pick_own(("deck", "extra", "hand", "field"))
        if (call_names & ss_calls) and (ss_sel := pick_own(("hand", "grave"))):
            op = dict(kind="special_summon", from_zones=ss_sel["from_zones"], to_zone="field",
                      quantity=ss_sel["quantity"], random=False, owner="self", selector_query=ss_sel["query"])
            return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)
        if own_sel and any(z in own_sel["from_zones"] for z in ("deck", "extra", "hand")):
            op = dict(kind="send_grave", from_zones=own_sel["from_zones"], to_zone="grave",
                      quantity=own_sel["quantity"], random=False, owner="self", selector_query=own_sel["query"])
            return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)
        op = dict(kind="send_grave", from_zones=["field"], to_zone="grave", quantity=1, random=False, owner="opponent")
        return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    if call_names & ss_calls:
        ex_sel = pick_own(("extra",))
        own_sel = pick_own(("hand", "deck", "grave", "banished", "extra"))
        if opp_sels and ex_sel and "Duel.SelectOption" in op_text:
            opp_op = dict(kind="banish" if "Duel.Remove" in call_names else "destroy",
                          from_zones=["field", "deck"], to_zone="banished" if "Duel.Remove" in call_names else "grave",
                          quantity=1, random=False, owner="opponent",
                          alternative_operations=[dict(
                              kind="special_summon", from_zones=["extra"], to_zone="field",
                              quantity=1, random=False, owner="self", selector_query=ex_sel["query"],
                          )])
            return dict(operations=[opp_op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)
        self_ss = any(cn in ss_calls and args and _is_self_expr(args[0]) and not own_sel for cn, args, _ in calls)
        ignore_cond = any(cn in ss_calls and len(args) >= 4 and _text(args[3]) == "true" for cn, args, _ in calls)
        if self_ss:
            src = trigger["zone"] if trigger["zone"] in ("hand", "grave", "banished", "pzone") else "grave"
            op = dict(kind="special_summon", from_zones=[src], to_zone="field", quantity=1, random=False,
                      owner="self", subject="this_card", ignore_summoning_conditions=ignore_cond)
            return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)
        if own_sel:
            op = dict(kind="special_summon", from_zones=own_sel["from_zones"], to_zone="field",
                      quantity=own_sel["quantity"], random=False, owner="self",
                      selector_query=own_sel["query"], ignore_summoning_conditions=ignore_cond)
            return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)
        if rule["category"] & _const(constants, "CATEGORY_SPECIAL_SUMMON"):
            src_z = (opp_sels[0]["from_zones"] if opp_sels else ["grave"])
            op = dict(kind="special_summon", from_zones=src_z, to_zone="field", quantity=1, random=False,
                      owner="self", selector_query=(opp_sels[0]["query"] if opp_sels else {"type": 1}),
                      ignore_summoning_conditions=ignore_cond)
            return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    if extra_ns_ops:
        primary_ns = dict(extra_ns_ops[0])
        primary_ns.pop("processing_role", None)
        primary_ns["grants_extra_normal_summon"] = True
        return dict(operations=[primary_ns], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    if "Duel.Destroy" in call_names:
        recipient = _destroy_recipient(op_node, tgt_node, all_funcs, constants, code, env)
        if recipient is None:
            return None
        owner, details = recipient
        op = dict(kind="destroy", from_zones=["field"], to_zone="grave", quantity=1, random=False, owner=owner)
        op.update(details)
        if owner == "self" or owner == "both" and details.get("whole_group"):
            op["own_destruction"] = True
            forced = _const(constants, "EFFECT_TYPE_TRIGGER_F") | _const(constants, "EFFECT_TYPE_QUICK_F")
            op["mandatory_trigger"] = bool(rule["type"] & forced)
        return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    if "Duel.Remove" in call_names:
        op = dict(kind="banish", from_zones=["field", "grave"], to_zone="banished", quantity=1, random=False, owner="opponent")
        return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    if "Duel.SendtoDeck" in call_names:
        if own_sels and not opp_sels:
            sel = own_sels[0]
            # Wait: Ishizu shufflers (`Keldo`/`Mudora`) target cards in EITHER GY (own or opponent's)
            is_either_gy = "PLAYER_ALL" in tgt_text or ("LOCATION_GRAVE" in tgt_text and "0,LOCATION_GRAVE" not in tgt_text)
            if is_either_gy:
                op = dict(kind="return_deck", from_zones=["grave"], to_zone="deck", quantity=1, random=False, owner="opponent")
            else:
                op = dict(kind="return_deck", from_zones=sel["from_zones"], to_zone="deck", quantity=sel["quantity"],
                          random=False, owner="self", selector_query=sel["query"])
        else:
            op = dict(kind="return_deck", from_zones=["field", "grave"], to_zone="deck", quantity=1, random=False, owner="opponent")
        return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    if "Duel.ChangePosition" in call_names:
        op = dict(kind="change_position", from_zones=["field"], to_zone="field", quantity=1, random=False, owner="opponent")
        return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    if "Duel.GetControl" in call_names:
        op = dict(kind="control_change", from_zones=["field"], to_zone="field", quantity=1, random=False, owner="opponent")
        return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    if "Duel.SwapDeckAndGrave" in call_names:
        op = dict(kind="swap_deck_grave", from_zones=["deck", "grave"], to_zone="grave", quantity=1, random=False, owner="self")
        return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    if call_names & {"Duel.Damage", "Duel.Recover"}:
        kind_lp = "damage" if "Duel.Damage" in call_names else "recover_lp"
        op = dict(kind=kind_lp, from_zones=[], to_zone=None, quantity=1, random=False,
                  owner="opponent" if kind_lp == "damage" else "self")
        return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    if call_names & {"Duel.SSet", "Duel.Overlay", "Duel.DisableShuffleCheck", "Duel.ConfirmDecktop", "Duel.SortDecktop"} or (
            "Duel.AnnounceCard" in call_names):
        if "Duel.SSet" in call_names and own_sels:
            sel = own_sels[0]
            op = dict(kind="set_card", from_zones=sel["from_zones"], to_zone="spell_trap",
                      quantity=sel["quantity"], random=False, owner="self", selector_query=sel["query"])
        elif "Duel.AnnounceCard" in call_names and "Duel.SendtoGrave" in op_text:
            op = dict(kind="send_grave", from_zones=["deck"], to_zone="grave", quantity=1, random=False, owner="opponent")
        elif "Duel.Overlay" in call_names:
            op = dict(kind="attach_xyz_material", from_zones=["hand", "deck", "grave"], to_zone="xyz_material",
                      quantity=1, random=False, owner="self")
        else:
            op = dict(kind="search" if "CATEGORY_SEARCH" in op_text else "inspect", from_zones=["deck"],
                      to_zone="hand" if "CATEGORY_SEARCH" in op_text else None, quantity=1, random=False, owner="self")
        return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)

    # 12. Fallback by non-zero CATEGORY flags when callbacks use compact helpers
    cat = rule["category"]
    if cat:
        cat_map = (
            ("CATEGORY_NEGATE", "negate_activation", [], None, "opponent"),
            ("CATEGORY_DISABLE_SUMMON", "negate_summon", [], None, "opponent"),
            ("CATEGORY_DISABLE", "negate_effect", [], None, "opponent"),
            ("CATEGORY_DESTROY", "destroy", ["field"], "grave", "opponent"),
            ("CATEGORY_REMOVE", "banish", ["field", "grave"], "banished", "opponent"),
            ("CATEGORY_POSITION", "change_position", ["field"], "field", "opponent"),
            ("CATEGORY_ATKCHANGE", "stat_change", ["field"], "field", "self"),
            ("CATEGORY_DRAW", "draw", ["deck"], "hand", "self"),
            ("CATEGORY_SEARCH", "search", ["deck"], "hand", "self"),
            ("CATEGORY_TOHAND", "recover", ["grave"], "hand", "self"),
            ("CATEGORY_TODECK", "return_deck", ["grave"], "deck", "opponent"),
            ("CATEGORY_TOGRAVE", "send_grave", ["deck"], "grave", "self"),
            ("CATEGORY_COUNTER", "counter_change", ["field"], None, "self"),
        )
        for cname, okind, fz, tz, owner in cat_map:
            if cat & _const(constants, cname):
                op = dict(kind=okind, from_zones=fz, to_zone=tz, quantity=1, random=(okind == "draw"), owner=owner)
                if owner == "self" and fz == ["deck"] and okind in ("search", "send_grave"):
                    sel = pick_own(("deck",))
                    op["selector_query"] = sel["query"] if sel else {"type": 7}
                return dict(operations=[op, *extra_ns_ops], extra_reqs=extra_reqs, restrictions=restrictions, fusion=False, ritual=False)
    return None


def _legacy_deck_selection(operation, target, functions, constants):
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
    deck = _const(constants, "LOCATION_DECK")
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
    reason = _const(constants, "REASON_EFFECT")
    if _literal_call(processing[0], constants, "Duel.SendtoHand", group, None, reason):
        kind, destination, ability = "search", "hand", "IsAbleToHand"
        if len(processing) > 2:
            return None
        if len(processing) == 2:
            call, operands = _call(processing[1])
            if (call != "Duel.ConfirmCards" or len(operands) != 2 or _name(operands[1]) != group
                    or not _opponent(operands[0], constants, player)):
                return None
    elif len(processing) == 1 and _literal_call(processing[0], constants, "Duel.SendtoGrave", group, reason):
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


def _extract_trigger(rule, constants, code, rows, cond_info):
    kind, event = rule["type"], rule["event"]
    events = {
        _const(constants, "EVENT_TO_GRAVE"): ("sent_to_grave", "grave"),
        _const(constants, "EVENT_SUMMON_SUCCESS"): ("normal_summon", "field"),
        _const(constants, "EVENT_SPSUMMON_SUCCESS"): ("special_summon", "field"),
        _const(constants, "EVENT_FLIP"): ("flip", "field"),
        _const(constants, "EVENT_FLIP_SUMMON_SUCCESS"): ("flip", "field"),
        _const(constants, "EVENT_DESTROYED"): ("destroyed", "grave"),
        _const(constants, "EVENT_BATTLE_DESTROYED"): ("battle_destroyed", "grave"),
        _const(constants, "EVENT_LEAVE_FIELD"): ("leave_field", "field"),
        _const(constants, "EVENT_REMOVE"): ("banished", "banished"),
        _const(constants, "EVENT_TO_DECK"): ("return_to_deck", "field"),
        _const(constants, "EVENT_TO_HAND"): ("to_hand", "hand"),
        _const(constants, "EVENT_RELEASE"): ("released", "grave"),
        _const(constants, "EVENT_BE_MATERIAL"): ("be_material", "grave"),
        _const(constants, "EVENT_CHAINING"): ("chaining", "field"),
        _const(constants, "EVENT_ATTACK_ANNOUNCE"): ("attack_announce", "field"),
        _const(constants, "EVENT_BATTLE_START"): ("battle_start", "field"),
        _const(constants, "EVENT_PRE_DAMAGE_CALCULATE"): ("battle_damage_calc", "field"),
        _const(constants, "EVENT_DAMAGE_STEP_END"): ("damage_step_end", "field"),
        _const(constants, "EVENT_PREDRAW"): ("predraw", "spell_trap"),
        _const(constants, "EVENT_DRAW"): ("draw_phase", "hand"),
        _const(constants, "EVENT_FREE_CHAIN"): ("free_chain", "field"),
    }
    range_zone = _zone_from_range(rule["range"], constants)
    if kind & _const(constants, "EFFECT_TYPE_ACTIVATE"):
        name = "spell_trap_activation" if event == _const(constants, "EVENT_FREE_CHAIN") else events.get(event, ("spell_trap_activation",))[0]
        zone = "spell_trap"
    elif kind & _const(constants, "EFFECT_TYPE_FLIP") and event == _const(constants, "EVENT_FLIP"):
        name, zone = "flip", "field"
    elif kind & _const(constants, "EFFECT_TYPE_SINGLE"):
        default_ev = events.get(event, ("registered_effect", range_zone or "field"))
        name = default_ev[0]
        zone = range_zone or default_ev[1]
        if event == _const(constants, "EVENT_DESTROYED") and cond_info.get("previous_location") == "field":
            zone = "grave"
    elif kind & _const(constants, "EFFECT_TYPE_IGNITION"):
        name = "ignition"
        zone = range_zone or "field"
        # Dual range like LOCATION_MZONE + LOCATION_GRAVE on quick/ignition effects with GY banish cost
        if rule["range"] & _const(constants, "LOCATION_GRAVE") and rule["range"] & _const(constants, "LOCATION_MZONE"):
            zone = "field"
    elif kind & (_const(constants, "EFFECT_TYPE_QUICK_O") | _const(constants, "EFFECT_TYPE_QUICK_F")):
        ev_name = events.get(event, ("quick_effect",))[0]
        name = "quick_effect" if event == _const(constants, "EVENT_FREE_CHAIN") else ev_name
        zone = range_zone or "field"
    elif kind & (_const(constants, "EFFECT_TYPE_TRIGGER_O") | _const(constants, "EFFECT_TYPE_TRIGGER_F")):
        if (event & 0xf000) == _const(constants, "EVENT_PHASE") and _const(constants, "EVENT_PHASE"):
            name = "phase_trigger"
        else:
            name = events.get(event, ("triggered_effect",))[0]
        zone = range_zone or events.get(event, (None, "field"))[1]
    elif kind & _const(constants, "EFFECT_TYPE_FIELD"):
        name, zone = "continuous", range_zone or "field"
    else:
        return None
    if not zone:
        return None
    cbs = rule.get("callbacks", {})
    source_cb = cbs.get("operation") or next(iter(cbs.values()), None)
    ref = f"{source_cb['file']}:{source_cb['lines'][0]}" if source_cb else f"c{code}.lua:1"
    trig = dict(event=name, zone=zone, event_code=event, rule_condition=cbs.get("condition"), source=ref)
    for k in ("previous_location", "hand_deck_controller", "required_reason", "required_summon_type", "event_group_query"):
        if cond_info.get(k) is not None:
            trig[k] = cond_info[k]
    return trig


def _static_record(lua, rule, code, ordinal, rows, cards_sha256, *, floodgate_op=None):
    constants, cbs = lua._constants, rule["callbacks"]
    if rule["scope"] != "card":
        return None

    # Continuous opponent floodgate without operation callback
    if floodgate_op is not None:
        cond_info = _analyze_condition(lua, rule, code, constants, {})
        zone = _zone_from_range(rule["range"], constants) or "field"
        first_cb = next(iter(cbs.values()), None)
        ref = f"{first_cb['file']}:{first_cb['lines'][0]}" if first_cb else f"c{code}.lua:1"
        rule_id = "native-static:" + digest((code, rule))
        output = dict(kind=floodgate_op, from_zones=[], to_zone=None, owner="opponent",
                      reason="effect", quantity=1, random=False, source=ref, phase="continuous",
                      block_id=rule_id + ":operation:0")
        trigger = dict(event="continuous", zone=zone, event_code=rule["event"],
                       rule_condition=cbs.get("condition"), source=ref)
        return dict(
            record_version="native-construction-static-v2",
            semantic_version="native-construction-static-v2",
            card_id=code, cards_sha256=cards_sha256, text_sha256=digest(rule),
            effect_index=ordinal, effect_key=rule_id, relation_ref=rule_id, source_text=ref,
            scope="spell_trap" if zone == "spell_trap" else "monster",
            trigger=trigger,
            conditions={
                "source": ref,
                "status": "recognized",
                "presence_requirements": cond_info["presence_requirements"],
                "distinct_name_requirements": cond_info["distinct_name_requirements"],
            },
            costs=[], targets=[], operations=[output],
            count_limits=[], restrictions=[], card_restrictions=[], printed_materials=[],
            unknown=[], block_view={"status": "native_static", "blocks": [], "unknown": []},
            rule_registration=rule,
        )

    source = cbs.get("operation")
    if not source:
        return None
    ref = f"{source['file']}:{source['lines'][0]}"
    op_node, op_funcs = lua.registered_callback(source)
    cond_info = _analyze_condition(lua, rule, code, constants, op_funcs)
    trigger = _extract_trigger(rule, constants, code, rows, cond_info)
    if trigger is None:
        return None
    cost_rows, cost_restrictions = _analyze_cost(lua, rule, code, constants, op_funcs)
    matched = None
    if (trigger["zone"] == "hand" and rule["type"] & _const(constants, "EFFECT_TYPE_IGNITION")
            and rule["category"] & _const(constants, "CATEGORY_TOGRAVE")
            and rule["category"] & _const(constants, "CATEGORY_SPECIAL_SUMMON")):
        script_id = source["file"].removesuffix(".lua").removeprefix("c")
        summary = lua.summarize_effects(int(script_id) if script_id.isdecimal() else code,
            deck_send_indices=(rule.get("description", 0) % 16, None), summon_locks=True)
        matched = next((r["type_matched_deck_send"] for r in summary["registrations"]
            if r.get("type_matched_deck_send") and
            lua.callback_location(r["operation"]["definition"]) == source and
            lua.callback_location(r["target"]["definition"]) == cbs.get("target")), None)
    if matched:
        query = matched["selector_query"]
        operations = [
            dict(kind="send_grave", from_zones=["deck"], to_zone="grave", quantity=1,
                 random=False, selector_query=query, requires_arrival=True),
            dict(kind="special_summon", from_zones=["hand"], to_zone="field", quantity=1,
                 random=False, subject="this_card", source_card_id=code,
                 selector_query={"predicate": {"field": "card_ids", "value": [code]}}),
        ]
        if revival := matched.get("revival"):
            operations.append(dict(kind="special_summon", from_zones=["grave"], to_zone="field",
                quantity=1, random=False, optional=True, selector_query=revival["selector_query"],
                position=revival["position"], effects_disabled=revival["effects_disabled"]))
        extracted = dict(operations=operations, extra_reqs=[], fusion=False, ritual=False,
            restrictions=_extract_restrictions_in_op(op_node, op_funcs, constants, code, ref))
    else:
        extracted = _extract_general_operations(lua, rule, code, constants, trigger, cost_rows)
    if extracted is None or extracted.get("utility_only"):
        return dict(_utility_status=extracted["status"]) if extracted and extracted.get("utility_only") else None

    rule_id = "native-static:" + digest((code, rule))
    ops = []
    for idx, op in enumerate(extracted["operations"]):
        item = dict(op)
        if "selector_query" in item and not query_supported(item["selector_query"]):
            q = lua.inventory_query(item["selector_query"], rows)
            if q is None:
                return None
            item["selector_query"] = q
        item.setdefault("owner", "self")
        item.setdefault("reason", "effect")
        item.setdefault("source", ref)
        item.setdefault("phase", "resolution")
        item["block_id"] = f"{rule_id}:operation:{idx}"
        ops.append(item)
    if not ops:
        return None

    count = [dict(code=rule["count_code"], maximum=rule["count_maximum"], persistent=rule["count_persistent"],
                  source=ref)] if rule["count_maximum"] else []
    kind = rule["type"]
    scope_label = "spell_trap" if kind & _const(constants, "EFFECT_TYPE_ACTIVATE") else (
        "pzone" if trigger["zone"] == "pzone" else "monster")
    record = dict(
        record_version="native-construction-static-v2",
        semantic_version="native-construction-static-v2",
        card_id=code, cards_sha256=cards_sha256, text_sha256=digest(rule),
        effect_index=ordinal, effect_key=rule_id, relation_ref=rule_id, source_text=ref,
        scope=scope_label, trigger=trigger,
        conditions={
            "source": ref,
            "status": "recognized",
            "presence_requirements": cond_info["presence_requirements"],
            "distinct_name_requirements": cond_info["distinct_name_requirements"],
        },
        costs=cost_rows, targets=[], operations=ops,
        extra_operation_requirements=extracted["extra_reqs"],
        count_limits=count,
        restrictions=[*cost_restrictions, *extracted["restrictions"]],
        card_restrictions=[], printed_materials=[],
        unknown=[], block_view={"status": "native_static", "blocks": [], "unknown": []},
        rule_registration=rule,
    )
    if matched:
        record["targets"] = [dict(zones=["field"], owner="self", face_up=True, quantity=1,
            timing="activation", source=ref, selector_query=matched["selector_query"])]
        send, handler, *revival = ops
        handler["depends_on"] = [send["block_id"]]
        binding = dict(send=send["block_id"], handler=handler["block_id"], base_type_mask=matched["base_type_mask"])
        if revival:
            revival[0]["depends_on"] = [handler["block_id"]]
            binding["revival"] = revival[0]["block_id"]
        record["type_matched_deck_send"] = binding
    if extracted["fusion"]:
        loc_map = {
            "spell_trap": _const(constants, "LOCATION_SZONE"),
            "hand": _const(constants, "LOCATION_HAND"),
            "field": _const(constants, "LOCATION_MZONE"),
            "grave": _const(constants, "LOCATION_GRAVE"),
            "banished": _const(constants, "LOCATION_REMOVED"),
            "pzone": _const(constants, "LOCATION_SZONE"),
        }
        record["fusion_stock_location"] = loc_map.get(trigger["zone"], _const(constants, "LOCATION_SZONE"))
        if extracted.get("fusion_returns_to_deck"):
            record["fusion_returns_to_deck"] = True
    return record


def _build_requirements(code, record, dependencies):
    """Build inventory requirements cleanly without inventing fake deck needs for opponent effects."""
    reqs = []
    # 1. Card costs (skip non-card LP, counter, and xyz_detach — those bind to pools/xyz_materials)
    card_costs = [c for c in record["costs"] if c.get("resource") not in ("lp", "counter") and c.get("kind") != "xyz_detach"]
    self_paid = any(c.get("subject") == "this_card" for c in card_costs)
    for cost in card_costs:
        req = dependencies.item_requirement(cost, "costs")
        if req is None:
            return None
        reqs.append(req)
    # 2. Host copy ownership check when no self-cost already checked it
    if not self_paid:
        host_zone = record["trigger"]["zone"].replace("spell_trap", "field").replace("pzone", "field").replace("banished", "field")
        if host_zone not in ("hand", "deck", "grave", "field", "extra"):
            host_zone = "field"
        host_item = dict(source=record["source_text"], quantity=1, owner="self", from_zones=[host_zone],
                         selector_query={"predicate": {"field": "card_ids", "value": [code]}})
        req = dependencies.item_requirement(host_item, "source")
        if req is None:
            return None
        reqs.append(req)
    # 3. Condition requirements (`distinct_name_requirements` like Round Table, `presence_requirements` like Exchange in GY)
    conds = record.get("conditions", {})
    for cond_item in (*conds.get("distinct_name_requirements", ()), *conds.get("presence_requirements", ())):
        req = dependencies.item_requirement(cond_item, "conditions")
        if req is None:
            return None
        if cond_item.get("distinct_names"):
            req["distinct_names"] = True
        reqs.append(req)
    # 4. Extra operation prerequisites (e.g. Runick Fountain GY recycle, Speedroid Hound GY-to-Deck recycle)
    for extra in record.get("extra_operation_requirements", ()):
        req = dependencies.item_requirement(extra, "operations")
        if req is None:
            return None
        reqs.append(req)
    # 5. Primary scoring operations (only own-deck/hand/grave/extra selections; never opponent payoffs or fusion/ritual stock)
    for op in record["operations"]:
        if op.get("processing_role") == "auxiliary":
            continue
        if op["kind"] in ("fusion_summon", "ritual_summon"):
            continue
        if op.get("owner") != "self" or not op.get("from_zones") or op.get("subject") == "this_card":
            continue
        query = op.get("selector_query") or ({"type": 7} if op.get("random") else None)
        if not query:
            continue
        item = dict(op, selector_query=query, exclude_source_copy=True, source_card_id=code)
        req = dependencies.item_requirement(item, "operations")
        if req is None:
            return None
        if op.get("distinct_names"):
            req["distinct_names"] = True
        req["operation"] = op
        reqs.append(req)
    return reqs


def static_rule_specs(assets, code, initialized, dependencies):
    """Return the scoreable rule records and the remaining source questions."""
    lua = assets.effect_lua_source
    constants = lua._constants
    effects, sources = [], []
    rules = initialized["native"]
    counts = Counter(map(digest, rules))
    alternate_index = {}
    alternate_pending = []
    for ordinal, rule in enumerate(rules):
        classified = _classify_non_scoring(lua, rule, code, constants)
        if isinstance(classified, dict):
            sources.append(classified)
            continue
        if counts[digest(rule)] > 1:
            sources.append(dict(rule=rule, status="unknown", reason="ambiguous_registration"))
            continue
        floodgate_op = classified.split(":", 1)[1] if isinstance(classified, str) and classified.startswith("floodgate:") else None
        record = _static_record(lua, rule, code, ordinal, assets.rows, assets.receipt["resources"]["cards"],
                                floodgate_op=floodgate_op)
        if isinstance(record, dict) and "_utility_status" in record:
            sources.append(dict(rule=rule, status=record["_utility_status"]))
            continue
        if record is not None:
            requirements = _build_requirements(code, record, dependencies)
            if requirements is not None:
                effects.append(dict(record=record, requirements=requirements, unknown=[]))
                sources.append(dict(rule=rule, status="function", effect=record["effect_key"]))
                shared_count = rule["count_maximum"] and rule["count_code"] & 0x0fffffff not in (0, 1)
                if shared_count and rule["event"] == _const(constants, "EVENT_SUMMON_SUCCESS"):
                    alternate_index[digest(dict(rule, event=_const(constants, "EVENT_SPSUMMON_SUCCESS")))] = (record, "special_summon")
                if shared_count and rule["event"] == _const(constants, "EVENT_SPSUMMON_SUCCESS"):
                    alternate_index[digest(dict(rule, event=_const(constants, "EVENT_SUMMON_SUCCESS")))] = (record, "normal_summon")
                continue
        if (not rule["callbacks"] and not rule["category"]
                and (rule["type"] & _const(constants, "EFFECT_TYPE_ACTIVATE"))
                and rule["event"] == _const(constants, "EVENT_FREE_CHAIN")):
            sources.append(dict(rule=rule, status="activation_only"))
        else:
            sources.append(dict(rule=rule, status="unknown", reason="unmapped_static_rule"))
            if rule["event"] in (_const(constants, "EVENT_SPSUMMON_SUCCESS"), _const(constants, "EVENT_SUMMON_SUCCESS")):
                alternate_pending.append(sources[-1])
    for row in alternate_pending:
        hit = alternate_index.get(digest(row["rule"]))
        if hit is not None:
            record, ev_label = hit
            row.update(status="alternate_trigger", effect=record["effect_key"])
            row.pop("reason", None)
            alts = record["trigger"].setdefault("alternative_events", [])
            if ev_label not in alts:
                alts.append(ev_label)
    return effects, dict(diagnostics=initialized["diagnostics"], registrations=sources)
