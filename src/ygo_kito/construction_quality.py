"""Functional log2 construction quality, bound to the host task and policy.

The evaluator computes P, V1, V2 and S from surviving physical inputs.
Archived scalar records are handled by continuation migration, never by an
alternative evaluator or a legacy scoring record type.
"""

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite

from .build_contracts import digest
from .validation import ContractError, integer, member, text

# All active consumers use this contract. Legacy types are archive inputs only.
FUNCTIONAL_QUALITY_VERSION = "construction-quality-evaluation-v4-functional-log2"
FUNCTION_DICTIONARY_VERSION = "construction-functions-v1"
FUNCTIONAL_SCOPE = ("functions", "self", "joint", "impacts", "generic", "side")


def functional_quality_config(value):
    """Validate host-owned functional units; legacy units cannot be inferred."""
    if not isinstance(value, dict):
        raise ContractError("explicit functional quality configuration required")
    required = {"evaluator_version", "function_dictionary_version", "theme_rules",
                "side_directions", "required_scope"}
    if set(value) - required - {"completion_budget", "theme_profile"} or required - set(value):
        raise ContractError("functional quality configuration fields differ")
    if value["evaluator_version"] != FUNCTIONAL_QUALITY_VERSION:
        raise ContractError("functional evaluator version differs")
    if value["function_dictionary_version"] != FUNCTION_DICTIONARY_VERSION:
        raise ContractError("functional dictionary version differs")
    rules = value["theme_rules"]
    if not isinstance(rules, list):
        raise ContractError("theme rules must be a list")
    seen = set()
    for rule in rules:
        if (not isinstance(rule, dict) or set(rule) - {"rule_id", "increment", "predicate", "percentage"}
                or {"rule_id", "increment", "predicate"} - set(rule)):
            raise ContractError("theme rules require distinct identities and explicit predicates")
        text(rule["rule_id"], "theme rule ID")
        if rule["rule_id"] in seen:
            raise ContractError("theme rule identities must be distinct")
        _positive(rule["increment"], "theme increment")
        if 'percentage' in rule:
            _positive(rule['percentage'], 'theme percentage')
            if abs(rule['increment'] - rule['percentage'] / 100) > 1e-12:
                raise ContractError('theme percentage must use the existing increment scale')
        predicate = rule["predicate"]
        if not isinstance(predicate, dict) or not predicate:
            raise ContractError("theme predicate must name trusted semantic fields")
        allowed = {"kind", "from_zone", "to_zone", "owner", "reason", "grave_related", "task_goal"}
        if set(predicate) - allowed:
            raise ContractError("theme predicate names an unimplemented semantic field")
        for key, expected in predicate.items():
            if key == "grave_related":
                if type(expected) is not bool:
                    raise ContractError("grave_related predicate must be boolean")
            elif not isinstance(expected, (str, list)) or not expected or (
                    isinstance(expected, str) and not expected.strip()) or (
                    isinstance(expected, list) and any(not isinstance(v, str) or not v.strip() for v in expected)):
                raise ContractError("semantic predicate requires text or a nonempty text list")
        seen.add(rule["rule_id"])
    automatic = [r for r in rules if 'task_goal' in r['predicate']]
    profile = value.get('theme_profile')
    if profile is not None:
        from .construction_theme import THEME_VERSION, PRIMARY, SECONDARY
        if (not isinstance(profile, dict) or profile.get('version') != THEME_VERSION
                or not isinstance(profile.get('task_sha256'), str)
                or profile.get('status') not in ('evaluated', 'unknown', 'not_applicable')
                or not isinstance(profile.get('goals'), list) or not isinstance(profile.get('preparations'), list)
                or not isinstance(profile.get('gaps'), list)
                or profile.get('percentages') != {PRIMARY:100, SECONDARY:50}):
            raise ContractError('automatic theme profile requires fixed task-bound goals and percentages')
    if automatic:
        from .construction_theme import automatic_rules
        if profile is None or automatic != automatic_rules(profile):
            raise ContractError('automatic goal rules must be derived from the bound task profile')
    directions = value["side_directions"]
    if (not isinstance(directions, dict) or not directions
            or set(directions) - {"going_first", "going_second"}
            or any(type(v) not in (int, float) or not isfinite(v) or v <= 0
                   for v in directions.values()) or abs(sum(directions.values()) - 1) > 1e-12):
        raise ContractError("Side directions require positive fixed weights summing to one")
    scope = value["required_scope"]
    if (not isinstance(scope, list) or any(not isinstance(v, str) for v in scope)
            or len(scope) != len(set(scope))
            or set(scope) - set(FUNCTIONAL_SCOPE)
            or not {"functions", "self", "joint", "impacts"} <= set(scope)):
        raise ContractError("functional scope must retain its required static checks")
    budget = value.get("completion_budget", 4096)
    integer(budget, "consistent fact completions", 1, 65536)
    return {**deepcopy(value), "completion_budget": budget}


def functional_pass_policy(value):
    """A reference descriptor contains no score or recursively bound result."""
    if not isinstance(value, dict):
        raise ContractError("explicit functional pass mode required")
    if value == {"mode": "none"}:
        return deepcopy(value)
    if set(value) != {"mode", "minimum_reference_ratio", "reference"} or value["mode"] != "reference_ratio":
        raise ContractError("functional pass mode must be none or reference_ratio")
    ratio = value["minimum_reference_ratio"]
    if type(ratio) not in (int, float) or not isfinite(ratio) or not 0 < ratio <= 1:
        raise ContractError("reference ratio must lie in (0, 1]")
    reference = value["reference"]
    if not isinstance(reference, dict) or set(reference) != {"reference_id", "deck_sha256", "source"}:
        raise ContractError("reference requires identity, deck binding and source; no bare score")
    for key in reference:
        text(reference[key], "reference " + key)
    if len(reference["deck_sha256"]) != 64 or any(c not in "0123456789abcdef" for c in reference["deck_sha256"]):
        raise ContractError("reference deck binding must be a canonical digest")
    return deepcopy(value)


def validate_support(expression, *, depth=0):
    """Boolean/static-fact expressions, independent of effect parsing and price."""
    if depth > 16:
        raise ContractError("support expression exceeds structural bound")
    if type(expression) is bool:
        return
    if isinstance(expression, str):
        text(expression, "support fact ID")
        return
    if not isinstance(expression, dict) or len(expression) != 1:
        raise ContractError("support must be a boolean, fact ID, all, any or not")
    operator, items = next(iter(expression.items()))
    if operator == "not":
        validate_support(items, depth=depth + 1)
    elif operator in ("all", "any") and isinstance(items, (list, tuple)) and 0 < len(items) <= 128:
        for item in items:
            validate_support(item, depth=depth + 1)
    else:
        raise ContractError("support requires an explicit nonempty Boolean group")


def support_facts(expression):
    validate_support(expression)
    return _support_facts(expression)


def _support_facts(expression):
    if type(expression) is bool:
        return set()
    if isinstance(expression, str):
        return {expression}
    operator, items = next(iter(expression.items()))
    if operator == "not":
        return _support_facts(items)
    return set().union(*(_support_facts(item) for item in items))


def support_value(expression, completion):
    """Evaluate one consistent completion; absent facts are never false by default."""
    validate_support(expression)
    return _support_value(expression, completion)


def _support_value(expression, completion):
    if type(expression) is bool:
        return expression
    if isinstance(expression, str):
        if expression not in completion or type(completion[expression]) is not bool:
            raise ContractError("support fact has no Boolean completion: " + expression)
        return completion[expression]
    operator, items = next(iter(expression.items()))
    if operator == "not":
        return not _support_value(items, completion)
    values = [_support_value(item, completion) for item in items]
    return all(values) if operator == "all" else any(values)


def support_state(expression, variables):
    """Read known support without choosing values for missing facts."""
    validate_support(expression)
    return _support_state(expression, variables)


def _support_state(expression, variables):
    if type(expression) is bool:
        return expression
    if isinstance(expression, str):
        return variables.get(expression)
    operator, items = next(iter(expression.items()))
    if operator == "not":
        value = _support_state(items, variables)
        return None if value is None else not value
    values = [_support_state(item, variables) for item in items]
    if operator == "all":
        return False if False in values else None if None in values else True
    return True if True in values else None if None in values else False


def _condition_program(expression, known):
    """Fold known facts once and make equivalent conditions shareable."""
    if type(expression) is bool:
        return expression
    if isinstance(expression, str):
        return known.get(expression, expression)
    operator, items = next(iter(expression.items()))
    if operator == 'not':
        child = _condition_program(items, known)
        return not child if type(child) is bool else ('not', child)
    identity = operator == 'all'
    children = tuple(dict.fromkeys(_condition_program(item, known) for item in items))
    if (not identity) in children:
        return not identity
    children = tuple(child for child in children if child is not identity)
    if not children:
        return identity
    return children[0] if len(children) == 1 else (operator, children)


def _condition_truth(program, completion):
    if type(program) is bool:
        return program
    if isinstance(program, str):
        return completion.get(program)
    operator, children = program
    if operator == 'not':
        value = _condition_truth(children, completion)
        return None if value is None else not value
    identity = operator == 'all'
    result = identity
    for child in children:
        value = _condition_truth(child, completion)
        if value is (not identity):
            return value
        if value is None:
            result = None
    return result


@dataclass(frozen=True)
class FunctionalUse:
    """A trusted use of physical sources; alternative proofs earn no new copies."""
    use_id: str
    effect_id: str
    function_id: str
    score_family_id: str
    source_ids: tuple[str, ...]
    valuation_mode: str
    evidence_refs: tuple[str, ...]
    self_condition: object
    joint_condition: object = True
    scope_id: str = "resident"
    theme_conditions: tuple = ()
    theme_eligible: tuple[str, ...] = ()
    required: bool = False
    requirement_origin: str | None = None
    contributes: bool = True
    theme_joint_conditions: tuple = ()

    def __post_init__(self):
        for key in ("use_id", "effect_id", "function_id", "score_family_id", "scope_id"):
            text(getattr(self, key), key)
        object.__setattr__(self, "source_ids", _texts(self.source_ids, "functional sources"))
        object.__setattr__(self, "evidence_refs", _texts(self.evidence_refs, "functional evidence"))
        member(self.valuation_mode, "valuation mode", ("main_density", "called"))
        validate_support(self.self_condition)
        validate_support(self.joint_condition)
        if type(self.required) is not bool or (self.required and not self.requirement_origin):
            raise ContractError("required use must bind its original requirement")
        if self.requirement_origin is not None:
            text(self.requirement_origin, "requirement origin")
        if type(self.contributes) is not bool:
            raise ContractError("functional contribution flag must be Boolean")
        if not isinstance(self.theme_conditions, tuple):
            raise ContractError("theme conditions require explicit rule/expression pairs")
        seen = set()
        for pair in self.theme_conditions:
            if not isinstance(pair, tuple) or len(pair) != 2 or pair[0] in seen:
                raise ContractError("theme condition identities must be distinct")
            text(pair[0], "theme condition ID")
            validate_support(pair[1])
            seen.add(pair[0])
        _texts(self.theme_eligible, "eligible theme rules", empty=True)
        if seen != set(self.theme_eligible):
            raise ContractError("every eligible theme rule requires its support condition")
        if not self.contributes and self.theme_eligible:
            raise ContractError("non-scoring adoption cannot declare theme benefits")
        if not isinstance(self.theme_joint_conditions, tuple):
            raise ContractError('joint theme conditions require explicit rule/expression pairs')
        joint_seen = set()
        for pair in self.theme_joint_conditions:
            if (not isinstance(pair, tuple) or len(pair) != 2 or pair[0] in joint_seen
                    or pair[0] not in seen):
                raise ContractError('joint theme conditions require distinct eligible rules')
            validate_support(pair[1])
            joint_seen.add(pair[0])
        for key in ("self_condition", "joint_condition", "theme_conditions", "theme_joint_conditions"):
            object.__setattr__(self, key, deepcopy(getattr(self, key)))


@dataclass(frozen=True)
class UseImpact:
    """A mandatory consequence withdraws specific supported proofs, never points."""
    impact_id: str
    source_use_id: str
    affected_use_ids: tuple[str, ...]
    channels: tuple[str, ...]
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    condition: object = True
    scope_id: str = "resident"
    affected_source_ids: tuple[str, ...] = ()

    def __post_init__(self):
        for key in ("impact_id", "source_use_id", "scope_id"):
            text(getattr(self, key), key)
        for key in ("affected_use_ids", "channels", "reason_codes", "evidence_refs"):
            object.__setattr__(self, key, _texts(getattr(self, key), key))
        object.__setattr__(self, "affected_source_ids", _texts(self.affected_source_ids, "impact sources", empty=True))
        validate_support(self.condition)
        object.__setattr__(self, "condition", deepcopy(self.condition))

ZONE_ORDER = ("main", "extra", "side")


def _positive(value, label):
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise ContractError(label + " must be a positive finite number")
    return float(value)


def _texts(value, label, *, empty=False):
    if not isinstance(value, (tuple, list)) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise ContractError(label + " must be a sequence of non-empty strings")
    if not value and not empty:
        raise ContractError(label + " cannot be empty")
    if len(set(value)) != len(value):
        raise ContractError(label + " must be distinct")
    return tuple(value)


def quality_config(value):
    """Only the current functional units can configure an active evaluator."""
    return functional_quality_config(value)


def pass_policy(value):
    return functional_pass_policy(value)


def evaluate_quality(evaluation, *, policy, facts):
    """Evaluate current candidate-bound facts in the sole active score unit."""
    functional_quality_config(policy.get('quality'))
    return evaluate_functional_quality(evaluation, policy=policy, facts=facts)


def compare_quality(before, after):
    return compare_functional_quality(before, after)


def physical_sources(inventory, aliases=None, extra_card_ids=()):
    """Stable identities for actual copies, independent of graph/report order."""
    aliases = aliases or {}
    if not isinstance(aliases, dict):
        raise ContractError("physical source aliases must be a mapping")
    extra_card_ids = set(extra_card_ids)
    sources = {}
    for zone in ZONE_ORDER:
        for code, count in sorted(Counter(inventory[zone]).items()):
            for copy in range(1, count + 1):
                sources[f"{zone}:{code}:{copy}"] = dict(card_id=code,
                    name_key=aliases.get(str(code), aliases.get(code, code)), zone=zone,
                    destination="extra" if zone == "extra" or code in extra_card_ids else "main")
    return sources


def _price_family(bins, capacity, main_size, rules):
    from math import fsum, log2

    candidates, channels = {}, {}
    for (channel, _, destination, mode), count in bins:
        factor = 40 / main_size if mode == 'main_density' else 1.
        increments = [factor] + [factor * (.8 if destination == 'extra' else .9)] * (count - 1)
        candidates.setdefault((channel, destination), []).extend(increments)
    for (channel, destination), increments in sorted(candidates.items()):
        limit = capacity.get(destination, len(increments)) if capacity is not None else len(increments)
        channels[channel] = channels.get(channel, 0.) + fsum(sorted(increments, reverse=True)[:limit])
    value = fsum((1 if channel == 'base' else rules[channel]) * log2(1 + amount)
                 for channel, amount in sorted(channels.items()))
    return channels, value


def _functional_inputs(uses, sources, config, completion, stage, scenario, impacts, *, family_prices=None):
    """Merge surviving proofs before discounting each physical source once."""
    from math import fsum
    active, modes = {}, {}
    rules = {r["rule_id"]: r["increment"] for r in config["theme_rules"]}
    automatic = {r['rule_id'] for r in config['theme_rules'] if 'task_goal' in r['predicate']}
    overrides = {(u.effect_id, u.score_family_id, source) for u in uses if u.scope_id == scenario
                 and scenario != "resident" for source in u.source_ids}
    for use in uses:
        if use.scope_id not in ("resident", scenario):
            continue
        if not use.contributes:
            continue
        if stage >= 1 and not support_value(use.self_condition, completion):
            continue
        if stage >= 2 and not support_value(use.joint_condition, completion):
            continue
        for channel in ("base", *use.theme_eligible):
            if channel != "base" and stage >= 1 and not support_value(dict(use.theme_conditions)[channel], completion):
                continue
            if channel != 'base' and stage >= 2 and not support_value(dict(use.theme_joint_conditions).get(channel, True), completion):
                continue
            for source in use.source_ids:
                if use.scope_id == "resident" and (use.effect_id, use.score_family_id, source) in overrides:
                    continue
                if scenario == "resident" and sources[source]["zone"] == "side":
                    continue
                key = use.score_family_id, channel, source
                mode_key = use.score_family_id, source
                if mode_key in modes and modes[mode_key] != use.valuation_mode:
                    raise ContractError("one source/function has conflicting valuation modes")
                modes[mode_key] = use.valuation_mode
                active.setdefault(key, set()).add(use.use_id)
    admitted = set().union(*active.values()) if active else set()
    required = [u for u in uses if u.required and u.scope_id in ("resident", scenario)
        and (stage < 1 or support_value(u.self_condition, completion))
        and (stage < 2 or support_value(u.joint_condition, completion))
        and any(not (scenario == "resident" and sources[s]["zone"] == "side")
                and not (u.scope_id == "resident" and (u.effect_id, u.score_family_id, s) in overrides)
                for s in u.source_ids)]
    admitted.update(u.use_id for u in required)
    adoptions = {u.use_id: {s for s in u.source_ids
        if not (u.scope_id == "resident" and (u.effect_id, u.score_family_id, s) in overrides)}
        for u in required if not u.contributes}
    if stage == 3:
        for impact in impacts:
            if (impact.scope_id not in ("resident", scenario)
                    or impact.source_use_id not in admitted
                    or not support_value(impact.condition, completion)):
                continue
            affected = set(impact.affected_use_ids)
            if "base" in impact.channels:
                for uid, retained in adoptions.items():
                    if uid in affected:
                        retained.difference_update(impact.affected_source_ids or set(retained))
            for key, proofs in active.items():
                if key[1] in impact.channels and (not impact.affected_source_ids or key[2] in impact.affected_source_ids):
                    proofs.difference_update(affected)
        # Preparations require a usable counterpart, even when a random transfer
        # has not proved that this specific receiving effect actually activated.
        from .construction_theme import SECONDARY
        for key, proofs in active.items():
            if key[1] != SECONDARY or SECONDARY not in automatic:
                continue
            for uid in tuple(proofs):
                witnesses = config.get('_theme_witnesses', {}).get(uid, ())
                retained = False
                for witness in witnesses:
                    if not support_value(witness['joint_condition'], completion):
                        continue
                    remaining = set(witness['receiver_source_ids'])
                    for impact in impacts:
                        if (impact.scope_id in ('resident', scenario) and impact.source_use_id in admitted
                                and 'base' in impact.channels and witness['receiver_use_id'] in impact.affected_use_ids
                                and support_value(impact.condition, completion)):
                            remaining.difference_update(impact.affected_source_ids or remaining)
                    if remaining:
                        retained = True
                        break
                if not retained:
                    proofs.discard(uid)
    bins = {}
    for (family, channel, source), proofs in active.items():
        if not proofs:
            continue
        item = sources[source]
        mode = modes[family, source]
        if mode == "main_density" and item["destination"] != "main":
            raise ContractError("Main density cannot price an Extra source")
        key = family, channel, str(item["name_key"]), item["destination"], mode
        bins[key] = bins.get(key, 0) + 1
    family_bins = {}
    for (family, *key), count in sorted(bins.items()):
        family_bins.setdefault(family, []).append((tuple(key), count))
    channels, values = {}, {}
    capacity = config['_capacity'] if scenario != 'resident' else None
    main_size = config['_main_size']
    pricing = main_size, tuple(sorted(capacity.items())) if capacity is not None else None, tuple(sorted(rules.items()))
    for family, entries in family_bins.items():
        if family_prices is None:
            channels[family], values[family] = _price_family(entries, capacity, main_size, rules)
        else:
            inputs, values[family] = _remember(family_prices, (pricing, tuple(entries)),
                lambda: _price_family(entries, capacity, main_size, rules), limit=128)
            channels[family] = dict(inputs)
    surviving = set().union(*active.values()) if active else set()
    surviving.update(uid for uid, retained in adoptions.items() if retained)
    return dict(value=fsum(values.values()), functions=values, inputs=channels,
                benefits=[dict(benefit_id=digest((f, s)), family=f, channel=c, source_id=s,
                               use_ids=sorted(proofs)) for (f, c, s), proofs in sorted(active.items()) if proofs],
                surviving_uses=sorted(surviving), admitted_uses=sorted(admitted))


def _score_programs(uses, impacts, witnesses, known, stage, scenario):
    expressions = []
    if stage >= 1:
        for use in uses:
            if use.scope_id not in ('resident', scenario) or not (use.contributes or use.required):
                continue
            expressions.extend((use.self_condition, *(condition for _, condition in use.theme_conditions)))
            if stage >= 2:
                expressions.extend((use.joint_condition, *(condition for _, condition in use.theme_joint_conditions)))
            if stage == 3:
                expressions.extend(row['joint_condition'] for row in witnesses.get(use.use_id, ()))
    if stage == 3:
        expressions.extend(impact.condition for impact in impacts if impact.scope_id in ('resident', scenario))
    programs = dict.fromkeys(_condition_program(expression, known) for expression in expressions)
    return tuple(program for program in programs if type(program) is not bool)


def _remember(cache, key, compute, *, limit=8):
    if key not in cache:
        if len(cache) == limit:
            del cache[next(iter(cache))]
        cache[key] = compute()
    return cache[key]


def _extend_bound(bounds, value):
    if bounds is None:
        return [value, value]
    bounds[0] = min(bounds[0], value)
    bounds[1] = max(bounds[1], value)
    return bounds


def _accumulate_functional_losses(outcome, by_id, impacts, facts, directions, weights, records):
    """Explain one consistent completion using the original effective inputs."""
    from math import log2
    for stage, name in enumerate(("self", "joint", "mandatory_impact"), 1):
        for direction, weight in directions.items():
            before = outcome["stages"][stage-1]["contexts"][direction]
            after = outcome["stages"][stage]["contexts"][direction]
            surviving = {(b["family"], b["channel"], b["source_id"]) for b in after["benefits"]}
            lost = [b for b in before["benefits"] if (b["family"], b["channel"], b["source_id"]) not in surviving]
            for family, channel in sorted({(b["family"], b["channel"]) for b in lost}):
                key = stage, direction, family, channel
                row = records.setdefault(digest(key), dict(key=list(key), stage=name, scope_id=direction,
                    score_family_id=family, channel_id=channel, source_ids={}, benefit_ids={}, use_ids={},
                    reason_codes={}, evidence_refs={}, repair_conditions={}, amounts=None,
                    input_before=None, input_after=None, count=0))
                x = before["inputs"].get(family, {}).get(channel, 0.)
                y = after["inputs"].get(family, {}).get(channel, 0.)
                amount = weight * weights[channel] * (log2(1+x)-log2(1+y))
                row["amounts"] = _extend_bound(row["amounts"], amount)
                row["input_before"] = _extend_bound(row["input_before"], x)
                row["input_after"] = _extend_bound(row["input_after"], y)
                row["count"] += 1
                for benefit in lost:
                    if (benefit["family"], benefit["channel"]) != (family, channel):
                        continue
                    row["source_ids"][benefit["source_id"]] = None
                    row["benefit_ids"][benefit["benefit_id"]] = None
                    for uid in benefit["use_ids"]:
                        use = by_id[uid]
                        row["use_ids"][uid] = None
                        row["evidence_refs"].update(dict.fromkeys(use.evidence_refs))
                        expressions = ([use.self_condition] + ([dict(use.theme_conditions)[channel]] if channel != "base" else [])
                                       if stage == 1 else [use.joint_condition,
                                           dict(use.theme_joint_conditions).get(channel, True)] if stage == 2 else [])
                        details = facts.get("use_details", {}).get(uid, {})
                        specific_repair = False
                        if stage == 1:
                            for check in details.get("inventory_checks", {}).values():
                                if check and check.get("status") == "missing":
                                    row["reason_codes"]["complete_inventory_requirement"] = None
                                    for requirement in check.get("requirements", ()):
                                        if requirement.get("shortfall") or check.get("shortfall"):
                                            repair = {k: requirement[k] for k in ("query", "minimum", "origin", "category") if k in requirement}
                                            row["repair_conditions"][digest(repair)] = repair
                                            reason = requirement.get("category", "inventory") + ":" + requirement.get("source", "required resource")
                                            row["reason_codes"][reason] = None
                                            specific_repair = True
                            row["reason_codes"].update(dict.fromkeys(details.get("self_reason_codes", ())))
                        if stage == 2:
                            for group in details.get("joint_groups", ()):
                                row["reason_codes"].update(dict.fromkeys(group.get("gaps", ())))
                                row["reason_codes"].update(dict.fromkeys(
                                    "resource:" + c["pool"] for c in group.get("conflicts", ()) if "pool" in c))
                        for expression in expressions:
                            # A blocked use may retain diagnostic-only theme
                            # unknowns omitted from this score completion.
                            # Record proved failures without inventing values.
                            if support_state(expression, outcome["completion"]) is not False or expression is False and specific_repair:
                                continue
                            repair_id = digest(expression) if type(expression) is not bool else digest((uid, stage, channel))
                            row["repair_conditions"][repair_id] = dict(use_id=uid, expression=expression)
                            for fact_id in support_facts(expression):
                                detail = facts.get("fact_details", {}).get(fact_id, {})
                                row["reason_codes"][detail.get("reason_code", fact_id)] = None
                                row["evidence_refs"].update(dict.fromkeys(detail.get("evidence_refs", ())))
                        if stage == 3:
                            for impact in impacts:
                                direct = (uid in impact.affected_use_ids and channel in impact.channels
                                    and (not impact.affected_source_ids or benefit['source_id'] in impact.affected_source_ids))
                                inherited = (channel == 'task-secondary' and 'base' in impact.channels and any(
                                    w['receiver_use_id'] in impact.affected_use_ids and (
                                        not impact.affected_source_ids or set(w['receiver_source_ids']) & set(impact.affected_source_ids))
                                    for w in facts.get('theme_witnesses', {}).get(uid, ())))
                                if ((direct or inherited)
                                        and impact.scope_id in ("resident", direction)
                                        and impact.source_use_id in before["admitted_uses"]
                                        and support_value(impact.condition, outcome["completion"])):
                                    row["reason_codes"].update(dict.fromkeys(impact.reason_codes))
                                    row["evidence_refs"].update(dict.fromkeys(impact.evidence_refs))
                                    row["repair_conditions"][impact.impact_id] = {"not": impact.condition}


def _functional_loss_records(records, outcome_count, *, exact):
    """Render the accumulated losses with zero for completions without a loss."""
    output = []
    for saved in sorted(records.values(), key=lambda row: row["key"]):
        row = dict(saved)
        key = row.pop("key")
        amounts = list(row.pop("amounts"))
        if row.pop("count") < outcome_count:
            _extend_bound(amounts, 0.)
        repair = row.pop("repair_conditions")
        for field in ("source_ids", "benefit_ids", "use_ids", "reason_codes", "evidence_refs"):
            row[field] = sorted(row[field])
        row["reason_codes"] = row["reason_codes"] or [row["stage"] + "_support"]
        lower, upper = amounts if exact else (0., None)
        row.update(loss_id="loss:" + digest(key), lower=lower, upper=upper,
            accounted_by="effective_inputs", repair_conditions=list(repair.values()),
            repair_group_id="repair:" + digest(sorted(repair)),
            repair_mode="restore_any_proof_per_source",
            recoverable=dict(lower=lower, upper=upper, basis="restore_withdrawn_inputs_at_this_stage"))
        output.append(row)
    return output


def _merge_completion_losses(records, incoming):
    for identity, row in incoming.items():
        if identity not in records:
            records[identity] = deepcopy(row)
            continue
        saved = records[identity]
        saved['count'] += row['count']
        for name in ('amounts', 'input_before', 'input_after'):
            _extend_bound(saved[name], row[name][0])
            _extend_bound(saved[name], row[name][1])
        for name in ('source_ids', 'benefit_ids', 'use_ids', 'reason_codes', 'evidence_refs', 'repair_conditions'):
            saved[name].update(row[name])


def evaluate_functional_quality(evaluation, *, policy, facts, should_stop=None, continuation=None, resumable=False,
                                family_prices=None):
    """Pure v4 evaluation; v3 shares/budgets cannot enter this computation."""
    from dataclasses import asdict
    config = functional_quality_config(policy.get("quality"))
    functional_pass_policy(policy.get("pass"))
    if not isinstance(facts, dict):
        raise ContractError("explicit candidate-bound functional facts required")
    required = {"version", "task_sha256", "deck_sha256", "asset_version", "uses", "impacts",
                "variables", "constraints", "coverage", "scope_status"}
    optional = {"source_aliases", "extra_card_ids", "unpriced_effects", "unknown_scope",
                "normalization_version", "coverage_details", "use_details", "fact_details", "hard_requirements", "side_contexts",
                "theme_witnesses"}
    if required - set(facts) or set(facts) - required - optional or facts["version"] != "construction-quality-facts-v1":
        raise ContractError("functional facts contract differs")
    axis = evaluation["axis"]
    inventory = axis["inventory"]
    task_sha, deck_sha = digest(axis["task"]), digest(inventory)
    if facts["task_sha256"] != task_sha or facts["deck_sha256"] != deck_sha:
        raise ContractError("functional facts belong to another task/candidate")
    if config.get('theme_profile') and config['theme_profile']['task_sha256'] != task_sha:
        raise ContractError('automatic theme profile belongs to another task')
    text(facts["asset_version"], "functional asset version")
    main_size = len(inventory["main"])
    if not main_size:
        raise ContractError("full functional evaluation requires a nonempty Main")
    sources = physical_sources(inventory, facts.get("source_aliases"), facts.get("extra_card_ids", ()))
    uses, impacts = tuple(facts["uses"]), tuple(facts["impacts"])
    if any(not isinstance(u, FunctionalUse) for u in uses) or any(not isinstance(i, UseImpact) for i in impacts):
        raise ContractError("functional uses and impacts must be typed")
    by_id = {u.use_id: u for u in uses}
    if len(by_id) != len(uses) or len({i.impact_id for i in impacts}) != len(impacts):
        raise ContractError("use/impact identities must be distinct")
    rules = {r["rule_id"] for r in config["theme_rules"]}
    scopes = {"resident", *config["side_directions"]}
    if not isinstance(facts["constraints"], (list, tuple)):
        raise ContractError("consistent constraints must be an expression sequence")
    expressions = list(facts["constraints"])
    requirements = facts.get("hard_requirements", [])
    if (not isinstance(requirements, (list, tuple)) or any(not isinstance(r, dict)
            or set(r) != {"requirement_id", "origin", "condition"} for r in requirements)):
        raise ContractError("hard requirements require identity, original source and support")
    requirement_ids = set()
    for requirement in requirements:
        text(requirement["requirement_id"], "hard requirement identity")
        text(requirement["origin"], "hard requirement origin")
        if requirement["requirement_id"] in requirement_ids:
            raise ContractError("duplicate hard requirement identity")
        requirement_ids.add(requirement["requirement_id"])
        expressions.append(requirement["condition"])
    if not isinstance(facts["variables"], dict) or any(
            not isinstance(k, str) or not k or v is not None and type(v) is not bool
            for k, v in facts["variables"].items()):
        raise ContractError("support facts require explicit Boolean/unknown values")
    checked_expressions = list(expressions)
    relevant = {u.use_id for u in uses if (u.contributes or u.required)
                and support_state(u.self_condition, facts["variables"]) is not False
                and support_state(u.joint_condition, facts["variables"]) is not False}
    group_modes = {}
    for use in uses:
        if set(use.source_ids) - set(sources) or use.scope_id not in scopes:
            raise ContractError("use source/scope is outside this candidate")
        if not set(use.theme_eligible) <= rules:
            raise ContractError("use names an unconfigured theme rule")
        if use.scope_id == "resident" and any(sources[s]["zone"] == "side" for s in use.source_ids):
            raise ContractError("Side cannot supply resident resources")
        for source in use.source_ids:
            item = sources[source]
            group = use.scope_id, use.score_family_id, str(item["name_key"]), item["destination"]
            previous = group_modes.setdefault(group, use.valuation_mode)
            if previous != use.valuation_mode:
                raise ContractError("one same-name function group cannot reset discounts across modes")
        checked_expressions.extend((use.self_condition, use.joint_condition,
            *(p[1] for p in use.theme_conditions), *(p[1] for p in use.theme_joint_conditions)))
        if use.contributes or use.required:
            expressions.append(use.self_condition)
            if support_state(use.self_condition, facts["variables"]) is not False:
                expressions.append(use.joint_condition)
                if use.use_id in relevant:
                    expressions.extend(p[1] for p in use.theme_conditions)
                    expressions.extend(p[1] for p in use.theme_joint_conditions)
    witnesses = facts.get('theme_witnesses', {})
    if not isinstance(witnesses, dict) or set(witnesses) - set(by_id):
        raise ContractError('theme witnesses must bind existing functional uses')
    counterpart_ids = set()
    for uid, rows in witnesses.items():
        for row in rows:
            if (set(row) != {'receiver_use_id', 'receiver_source_ids', 'joint_condition'}
                    or row['receiver_use_id'] not in by_id
                    or set(row['receiver_source_ids']) - set(by_id[row['receiver_use_id']].source_ids)
                    or by_id[row['receiver_use_id']].scope_id != by_id[uid].scope_id):
                raise ContractError('theme counterpart witness differs from its actual source/scope')
            checked_expressions.append(row['joint_condition'])
            if uid in relevant:
                expressions.append(row['joint_condition'])
                counterpart_ids.add(row['receiver_use_id'])
    effective_impacts = []
    for impact in impacts:
        if ({impact.source_use_id, *impact.affected_use_ids} - set(by_id)
                or set(impact.channels) - {"base", *rules} or impact.scope_id not in scopes):
            raise ContractError("impact must bind existing uses, channels and scope")
        source_scope = by_id[impact.source_use_id].scope_id
        if source_scope != "resident" and source_scope != impact.scope_id:
            raise ContractError("impact cannot escape its source direction")
        if set(impact.affected_source_ids) - {s for uid in impact.affected_use_ids for s in by_id[uid].source_ids}:
            raise ContractError("impact sources must belong to its affected uses")
        if any(by_id[uid].scope_id not in ("resident", impact.scope_id) for uid in impact.affected_use_ids):
            raise ContractError("impact targets escape their direction")
        checked_expressions.append(impact.condition)
        if impact.source_use_id in relevant and any(uid in relevant | counterpart_ids and (
                "base" in impact.channels or set(by_id[uid].theme_eligible) & set(impact.channels))
                for uid in impact.affected_use_ids):
            expressions.append(impact.condition)
            effective_impacts.append(impact)
    referenced = set().union(*(support_facts(e) for e in expressions)) if expressions else set()
    checked = set().union(*(support_facts(e) for e in checked_expressions)) if checked_expressions else set()
    variables = facts["variables"]
    if (not isinstance(variables, dict) or checked - set(variables)
            or any(not isinstance(k, str) or not k or v is not None and type(v) is not bool
                   for k, v in variables.items())):
        raise ContractError("support facts require explicit Boolean/unknown values")
    impacts = tuple(effective_impacts)
    status = facts["scope_status"]
    if (not isinstance(status, dict) or set(status) - set(FUNCTIONAL_SCOPE)
            or any(v not in ("evaluated", "deferred", "not_applicable") for v in status.values())
            or any(status.get(k) == "not_applicable" for k in ("functions", "self", "joint", "impacts"))):
        raise ContractError("static scope cannot discard required evaluation")
    # Host support may resolve an activation after normalization. Only an
    # actually relevant use may carry an unimplemented restriction gap into
    # the final evaluation; inactive records remain in the diagnostics.
    status = dict(status)
    if any(check.get("status") == "unmapped" for uid in relevant
           for check in facts.get("use_details", {}).get(uid, {}).get("restriction_checks", ())):
        status["impacts"] = "deferred"
    deferred = [k for k in config["required_scope"] if status.get(k) != "evaluated"]
    if "side" not in config["required_scope"] and any(u.scope_id != "resident" for u in uses):
        raise ContractError("Side uses supplied outside the fixed task scope")
    coverage = facts["coverage"]
    expected = {f"{zone}:{code}" for zone in ZONE_ORDER for code in inventory[zone]}
    if (not isinstance(coverage, dict) or set(coverage) != expected
            or any(v not in ("evaluated", "unknown", "deferred") for v in coverage.values())):
        raise ContractError("coverage must account for every actual card and zone")
    unknown_coverage = sorted(k for k, v in coverage.items() if v != "evaluated")
    unknown = sorted(k for k in referenced if variables[k] is None)
    known = {k: v for k, v in variables.items() if v is not None}
    runtime = {**config, "_main_size": main_size, '_capacity':axis['task'].get('sizes',{}), '_theme_witnesses':witnesses}
    directions = config["side_directions"] if "side" in config["required_scope"] else {"resident": 1.}
    budget = config["completion_budget"]
    full_count = 1 << len(unknown)
    upper_unknown = bool(facts.get("unknown_scope") or unknown_coverage or deferred)
    fits_slice = len(unknown) <= 16 and full_count <= budget
    # Exhausting Boolean cases cannot recover a missing card or scoring scope.
    exact_search = fits_slice or (not upper_unknown and (resumable or continuation is not None))
    case_count = full_count if exact_search else min(2, budget)
    facts_sha = digest({**facts, "uses": [asdict(u) for u in uses], "impacts": [asdict(i) for i in facts["impacts"]]})
    policy_sha, logic_sha = digest(policy), digest(axis.get("logic"))
    binding = digest((FUNCTIONAL_QUALITY_VERSION, task_sha, deck_sha, policy_sha, logic_sha, facts_sha))
    if continuation is not None and (not isinstance(continuation, dict)
            or continuation.get('version') != 'functional-quality-work-v1' or continuation.get('binding') != binding):
        raise ContractError('quality continuation belongs to different inputs')
    work = deepcopy(continuation) if continuation is not None else dict(version='functional-quality-work-v1',
        binding=binding, next_completion=0, next_loss=0, active_outcome=None, completion_scores=[],
        stages=[None] * 4, losses=[None] * 3, hard={}, side={}, loss_records={}, details=None)

    def completion_at(index):
        return {**known, **{key: bool(index & (1 << (len(unknown) - position - 1)))
                            for position, key in enumerate(unknown)}}

    bit_positions = {key: len(unknown) - position - 1 for position, key in enumerate(unknown)}
    constraints = [(_condition_program(expression, known), min(
        (bit_positions[key] for key in _support_facts(expression) if key in bit_positions), default=len(unknown)))
        for expression in facts['constraints']]
    constraints.sort(key=lambda item: -item[1])
    input_programs, input_cache, loss_cache = {}, {}, {}
    loss_programs = ()
    if unknown:
        for stage in range(4):
            for scenario in ('resident', *(d for d in directions if d != 'resident')):
                key = stage, scenario
                input_programs[key] = _score_programs(uses, impacts, witnesses, known, stage, scenario)
                input_cache[key] = {}
        loss_programs = tuple(program for program in dict.fromkeys(
            _condition_program(expression, known) for expression in checked_expressions) if type(program) is not bool)

    weights = {"base": 1., **{r["rule_id"]: r["increment"] for r in config["theme_rules"]}}
    completed_here, timed_out = 0, False
    while work['active_outcome'] is not None or work['next_completion'] < case_count:
        if should_stop is not None and should_stop():
            timed_out = True
            break
        if work['active_outcome'] is not None:
            outcome = work['active_outcome']
            if unknown:
                signature = tuple(_condition_truth(program, outcome['completion']) for program in loss_programs)

                def completion_losses():
                    records = {}
                    _accumulate_functional_losses(outcome, by_id, impacts, facts, directions, weights, records)
                    return records

                _merge_completion_losses(work['loss_records'], _remember(loss_cache, signature, completion_losses))
            else:
                _accumulate_functional_losses(outcome, by_id, impacts, facts, directions, weights, work['loss_records'])
            work['next_loss'] += 1
            work['active_outcome'] = None
            continue
        if completed_here >= budget:
            break
        ordinal = work['next_completion']
        index = ordinal if exact_search or ordinal == 0 else full_count - 1
        work['next_completion'] += 1
        completed_here += 1
        completion = completion_at(index)
        failed_span = next((shift for program, shift in constraints if not _condition_truth(program, completion)), None)
        if failed_span is not None:
            if exact_search:
                # The lower bits belong to facts outside this failed constraint.
                work['next_completion'] = ((index >> failed_span) + 1) << failed_span
            continue
        truths = {}

        def scored(stage, scenario):
            if not unknown:
                return _functional_inputs(uses, sources, runtime, completion, stage, scenario, impacts,
                                          family_prices=family_prices)
            key = stage, scenario
            programs = input_programs[key]
            for program in programs:
                if program not in truths:
                    truths[program] = _condition_truth(program, completion)
            signature = tuple(truths[program] for program in programs)
            return _remember(input_cache[key], signature,
                lambda: _functional_inputs(uses, sources, runtime, completion, stage, scenario, impacts,
                                           family_prices=family_prices))

        stages = []
        for stage in range(4):
            resident = scored(stage, 'resident')
            contexts = {d: resident if d == 'resident' else scored(stage, d) for d in directions}
            stages.append(dict(value=sum(directions[d] * row["value"] for d, row in contexts.items()),
                               resident=resident, contexts=contexts))
        hard = {u.use_id: support_value(u.self_condition, completion)
                and support_value(u.joint_condition, completion)
                and u.use_id in stages[-1]["resident"]["surviving_uses"]
                for u in uses if u.required and u.scope_id == "resident"}
        if set(hard) & requirement_ids:
            raise ContractError("use and independent hard requirement identities collide")
        hard.update({r["requirement_id"]: support_value(r["condition"], completion) for r in requirements})
        for key, value in hard.items():
            work['hard'][key] = _extend_bound(work['hard'].get(key), value)
        for stage, row in enumerate(stages):
            work['stages'][stage] = _extend_bound(work['stages'][stage], row['value'])
            if stage:
                loss = stages[stage - 1]['value'] - row['value']
                work['losses'][stage - 1] = _extend_bound(work['losses'][stage - 1], loss)
        final = stages[-1]
        resident_value = final['resident']['value']
        for direction in directions:
            combined_value = final['contexts'][direction]['value']
            bounds = work['side'].setdefault(direction, {})
            for field, value in (('resident', resident_value), ('combined', combined_value),
                                 ('delta', combined_value - resident_value)):
                bounds[field] = _extend_bound(bounds.get(field), value)
        work['completion_scores'].append([index, final['value']])
        work['active_outcome'] = dict(stages=stages, completion=completion)
        if not unknown and not upper_unknown:
            work['details'] = stages

    pending = work['next_completion'] < case_count or work['active_outcome'] is not None
    exhaustive = exact_search and not pending
    count = len(work['completion_scores'])
    if not count and exhaustive:
        raise ContractError("static facts have no consistent completion")
    exact_bounds = exhaustive and not upper_unknown
    potential = None if exhaustive or upper_unknown else sum(
        weight * _functional_inputs(uses, sources, runtime, known, 0, d, ())["value"] for d, weight in directions.items())
    stage_ranges = [dict(lower=bounds[0] if exact_bounds else 0.,
        upper=None if upper_unknown else bounds[1] if exhaustive else potential) for bounds in work['stages']]
    score = dict(stage_ranges[3], unit="functional_log2", value=None,
                 bound_kind="exact" if exact_bounds else "conservative")
    if exact_bounds and score["lower"] == score["upper"]:
        score["value"] = score["lower"]
    complete = exact_bounds and not unknown
    hard = [dict(requirement_id=u.use_id, origin=u.requirement_origin) for u in uses
            if u.required and u.scope_id == 'resident'] + [
        dict(requirement_id=r['requirement_id'], origin=r['origin']) for r in requirements]
    for row in hard:
        bounds = work['hard'].get(row['requirement_id'])
        row['status'] = 'unknown'
        if exhaustive and bounds and bounds[0] == bounds[1]:
            row['status'] = 'satisfied' if bounds[0] else 'failed'
    losses = [dict(stage=name, lower=bounds[0] if exact_bounds else 0.,
        upper=bounds[1] if exact_bounds else None, accounted_by='effective_inputs')
        for name, bounds in zip(('self', 'joint', 'mandatory_impact'), work['losses'])]
    loss_records = _functional_loss_records(work['loss_records'], count, exact=exact_bounds)
    completion_results = []
    if exhaustive:
        ordered_facts = sorted(referenced)
        for index, value in work['completion_scores']:
            completion = completion_at(index)
            completion_results.append(dict(facts={key: completion[key] for key in ordered_facts}, value=value))
    body = dict(version=FUNCTIONAL_QUALITY_VERSION, layer="quality", policy_version=policy["version"],
        policy_source=policy["source"], policy_sha256=policy_sha, quality_config_sha256=digest(config),
        task_sha256=task_sha, deck_sha256=deck_sha, logic_sha256=logic_sha, asset_version=facts["asset_version"],
        inventory=deepcopy(inventory),
        facts_sha256=facts_sha,
        normalization_version=facts.get("normalization_version", "explicit-functional-facts-v1"),
        function_dictionary_version=config["function_dictionary_version"],
        scope=list(config["required_scope"]), score=score, scope_complete=not upper_unknown,
        complete=complete, hard_requirements=hard, stages=dict(zip(("P", "V1", "V2", "S"), stage_ranges)),
        losses=losses, unknowns=unknown, deferred=deferred, coverage=deepcopy(coverage),
        loss_records=loss_records, evaluation_timed_out=timed_out,
        completion_evaluated_count=count,
        side_contexts=deepcopy(facts.get("side_contexts", {})),
        theme_profile=deepcopy(config.get('theme_profile')),
        theme_witnesses=deepcopy(witnesses), unknown_scope=deepcopy(facts.get('unknown_scope', [])),
        side_directions={d: dict(weight=w, **{key: work['side'][d][key] if exact_bounds else None
            for key in ('resident', 'combined', 'delta')}) for d, w in directions.items()},
        coverage_details=deepcopy(facts.get("coverage_details", {})),
        use_details=deepcopy(facts.get("use_details", {})), fact_details=deepcopy(facts.get("fact_details", {})),
        unpriced_effects=deepcopy(facts.get("unpriced_effects", [])),
        completion_results=completion_results, details=work['details'] if complete else None)
    body["total"] = dict(value=score["value"], min=score["lower"], max=score["upper"],
        complete=complete, scope_complete=body["scope_complete"], status="known" if complete else "unknown",
        deferred=deferred, unknown_items=unknown, partial_items=unknown_coverage, unit="functional_log2")
    if pending and (exact_search or resumable):
        body['calculation_pending'] = work
    elif not pending:
        body['evaluation_id'] = digest(body)
    return body


@dataclass(frozen=True, slots=True)
class _ComparisonInput:
    evaluation_id: str
    deck_sha256: str
    task_sha256: str
    scope: tuple
    lower: float
    upper: float | None
    value: float | None
    exact: bool
    eligible: bool
    facts: tuple
    completions: tuple


def validate_evaluation(row):
    if (not isinstance(row, dict) or row.get('version') != FUNCTIONAL_QUALITY_VERSION
            or row.get('evaluation_id') != digest({k: v for k, v in row.items() if k != 'evaluation_id'})):
        raise ContractError('functional comparison requires a bound evaluation')


def restore_comparison_progress(progress):
    if not isinstance(progress, dict):
        raise ContractError('invalid saved candidate comparison progress')
    saved = {k: v for k, v in progress.items() if k != 'sha256'}
    order, pairs, cursor = saved.get('order'), saved.get('pairs'), saved.get('next_pair')
    if (saved.get('version') != 'functional-comparison-progress-v1' or progress.get('sha256') != digest(saved)
            or not isinstance(order, list) or not isinstance(pairs, list) or type(cursor) is not int
            or cursor != len(pairs) or cursor > len(order) * (len(order) - 1) // 2):
        raise ContractError('invalid saved candidate comparison progress')
    return order, pairs


class EvaluationComparisons:
    """Reuse verified inputs and pair results within a construction or import."""

    def __init__(self):
        self.inputs = {}
        self.pairs = {}

    def bind(self, row):
        identity = id(row)
        if identity not in self.inputs:
            validate_evaluation(row)
            score = row['score']
            outcomes = row.get('completion_results') or ()
            facts = tuple(sorted(outcomes[0]['facts'])) if outcomes else ()
            completions = tuple((tuple(outcome['facts'][key] for key in facts), outcome['value'])
                                for outcome in outcomes)
            scope = (row['policy_sha256'], row['task_sha256'], row['asset_version'], tuple(row['scope']),
                     row['normalization_version'], row['function_dictionary_version'])
            eligible = row['complete'] and all(r['status'] == 'satisfied' for r in row['hard_requirements'])
            self.inputs[identity] = (row, _ComparisonInput(row['evaluation_id'], row['deck_sha256'],
                row['task_sha256'], scope, score['lower'], score['upper'], score['value'],
                score['bound_kind'] == 'exact', eligible, facts, completions))
        return self.inputs[identity][1]

    def release_candidates(self, *keep):
        """Release evaluated inventories once the round has saved its decision."""
        self.inputs = {id(row): self.inputs[id(row)] for row in keep if id(row) in self.inputs}
        self.pairs.clear()

    def compare(self, before, after):
        a, b = self.bind(before), self.bind(after)
        key = (a.evaluation_id, b.evaluation_id)
        if key not in self.pairs:
            self.pairs[key] = _comparison_record(a, b, _delta(a, b, 1.))
        return self.pairs[key]

    def delta(self, before, after, ratio):
        return _delta(self.bind(before), self.bind(after), ratio)

    def restore_pair(self, before, after, result):
        a, b = self.bind(before), self.bind(after)
        _check_scope(a, b)
        if not isinstance(result, dict) or not isinstance(result.get('delta_range'), list) or len(result['delta_range']) != 2:
            raise ContractError('invalid saved comparison bounds')
        lower, upper = result['delta_range']
        bounds = dict(lower=lower, upper=upper, bound_kind=result.get('bound_kind'))
        if (bounds['bound_kind'] not in ('joint', 'conservative')
                or any(v is not None and (type(v) not in (float, int) or not isfinite(v)) for v in (lower, upper))
                or (lower is not None and upper is not None and lower > upper)
                or result != _comparison_record(a, b, bounds)):
            raise ContractError('saved comparison differs from its bound evaluations')
        self.pairs[a.evaluation_id, b.evaluation_id] = result


def _check_scope(before, after):
    if before.scope != after.scope:
        raise ContractError("functional comparison changes its task/policy/asset scope")


def _delta(before, after, ratio):
    _check_scope(before, after)
    _positive(ratio, "comparison ratio")
    low = after.lower - ratio * before.upper if before.upper is not None else None
    high = after.upper - ratio * before.lower if after.upper is not None else None
    joint = False
    if before.completions and after.completions and before.exact and after.exact:
        shared = sorted(set(before.facts) & set(after.facts))
        if shared:
            def groups(value):
                columns = [value.facts.index(fact) for fact in shared]
                result = {}
                for facts, score in value.completions:
                    key = tuple(facts[i] for i in columns)
                    lo, hi = result.get(key, (score, score))
                    result[key] = min(lo, score), max(hi, score)
                return result
            left, right = groups(before), groups(after)
            keys = left.keys() & right.keys()
            if not keys:
                raise ContractError("candidate/reference shared facts have no consistent completion")
            low = min(right[k][0] - ratio * left[k][1] for k in keys)
            high = max(right[k][1] - ratio * left[k][0] for k in keys)
            joint = True
    return dict(lower=low, upper=high, bound_kind="joint" if joint else "conservative",
                ratio=ratio, before_evaluation_id=before.evaluation_id, after_evaluation_id=after.evaluation_id)


def _comparison_record(before, after, bounds):
    eligible = before.eligible and after.eligible
    preferred, status = None, "unresolved"
    if eligible:
        delta = after.value - before.value
        preferred = "after" if delta > 0 else "before" if delta < 0 else None
        status = "preferred" if preferred else "equivalent"
    return dict(status=status, preferred=preferred, task_sha256=before.task_sha256,
        before_deck_sha256=before.deck_sha256, after_deck_sha256=after.deck_sha256,
        before_evaluation_id=before.evaluation_id, after_evaluation_id=after.evaluation_id,
        delta_range=[bounds["lower"], bounds["upper"]], bound_kind=bounds["bound_kind"],
        hard_constraints_checked=eligible)


def functional_delta(before, after, *, ratio=1.):
    """Joint after - ratio*before bounds, sharing only identical fact identities."""
    return EvaluationComparisons().delta(before, after, ratio)


def compare_functional_quality(before, after):
    """A strict quality preference requires complete, comparable effective scores."""
    return EvaluationComparisons().compare(before, after)
