"""Read static effect registrations from the locked mycard Lua sources."""

from collections import defaultdict
from dataclasses import dataclass, field
from functools import cache
from hashlib import sha256
from operator import add, and_, lt, mul, or_, sub
from pathlib import Path

from .validation import ContractError


LUA_EFFECT_VERSION = "mycard-effect-registration-v1"
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
        commits = receipt["source_commits"]
        self._binding = dict(extractor=LUA_EFFECT_VERSION, scripts_sha256=resources["scripts"],
                             script_commit=commits["scripts"], core_commit=commits["core"],
                             source_lock_sha256=receipt["source_lock_sha256"])

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
        return (Path(root), receipt["resources"]["scripts"], commits["scripts"], commits["core"],
                receipt["source_lock_sha256"])

    def assert_binding(self, root, receipt):
        if self._receipt_binding != self._receipt_identity(root, receipt):
            raise ContractError("Lua resources changed; reload BuildAssets for the new receipt")

    @property
    def card_script_ids(self):
        return tuple(int(name[1:-4]) for name in self._scripts
                     if name.startswith("c") and name[1:-4].isascii() and name[1:-4].isdigit())

    def _helper(self, name):
        node = self._utility.get(name)
        return dict(file="utility.lua", sha256=self._scripts["utility.lua"][1],
                    byte_span=_span(node), function=name) if node else None

    def summarize_effects(self, code):
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
                else:
                    if any(_call(value)[0] for value in values):
                        unresolved("unsupported_top_level_assignment", node)
                    values = [_value(value, constants) for value in values]
                for i, name in enumerate(map(_text, names)):
                    if (not local and initial is not None
                            and (name in initial_bindings or name in ("Effect", "aux"))):
                        unresolved("assignment_after_initial_effect_declaration", node)
                    constants[name] = values[i] if i < len(values) else None
            elif names and all(_table_field(n, constants) for n in names):
                for name in map(_name, names):
                    if name.endswith(".initial_effect"):
                        unresolved("dynamic_initial_effect_declaration", node)
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
        return result

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
            if helper is None and definition is not None:
                helper = dict(file=result["file"], sha256=result["sha256"],
                              byte_span=_span(definition), function=name)
            settings[_CALLBACKS[method]] = dict(reference=name, byte_span=_span(node),
                                                definition=helper)
        elif method not in _METADATA:
            unresolved("unsupported_effect_setter", node)

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
