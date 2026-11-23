"""Bounds on functional score components, using the existing input pricing."""

from collections import defaultdict
from itertools import product
from math import fsum

from .construction_quality import (
    _condition_program, _condition_truth, _extend_bound, _functional_inputs, _side_overrides,
    _support_facts, _support_state,
)
from .validation import ContractError


def _connected(fact_sets):
    """Connect score families and constraints through their common facts."""
    owners = defaultdict(list)
    for index, facts in enumerate(fact_sets):
        for fact in facts:
            owners[fact].append(index)
    seen, expanded = set(), set()
    for index in range(len(fact_sets)):
        if index in seen:
            continue
        group, queue = [], [index]
        seen.add(index)
        while queue:
            member = queue.pop()
            group.append(member)
            for fact in fact_sets[member] - expanded:
                expanded.add(fact)
                for neighbor in owners[fact]:
                    if neighbor not in seen:
                        seen.add(neighbor)
                        queue.append(neighbor)
        yield sorted(group)


def _units(uses, impacts, witnesses, constraints, known, unknown, limit, *, sources=None, interruption_bonus=None):
    by_family, by_target = defaultdict(list), defaultdict(set)
    by_int_group = defaultdict(list)
    for use in uses:
        if use.contributes:
            by_family[use.score_family_id].append(use)
            if interruption_bonus is not None and sources is not None and use.is_interruption:
                seen_groups = set()
                for s in use.source_ids:
                    item = sources[s]
                    gkey = (str(item["name_key"]), item["destination"])
                    if gkey not in seen_groups:
                        seen_groups.add(gkey)
                        by_int_group[gkey].append(use)
    for index, impact in enumerate(impacts):
        for target in impact.affected_use_ids:
            by_target[target].add(index)

    def dependencies(expressions):
        return {fact for expr in expressions if _support_state(expr, known) is None
                for fact in _support_facts(expr) if fact in unknown}

    terms = []
    by_id = {use.use_id: use for use in uses}
    for family, priced in sorted(by_family.items()):
        receivers = [w for use in priced for w in witnesses.get(use.use_id, ())]
        targets = {use.use_id for use in priced} | {w['receiver_use_id'] for w in receivers}
        impact_ids = set().union(*(by_target[target] for target in targets))
        use_ids = {use.use_id for use in priced} | {impacts[i].source_use_id for i in impact_ids}
        expressions = [c for uid in use_ids for c in (by_id[uid].self_condition, by_id[uid].joint_condition)]
        expressions.extend(c for use in priced for _, c in (*use.theme_conditions, *use.theme_joint_conditions))
        expressions.extend(w['joint_condition'] for w in receivers)
        expressions.extend(impacts[i].condition for i in impact_ids)
        terms.append((dependencies(expressions), {family}, use_ids, impact_ids, ()))
    for (nk, dest), int_uses in sorted(by_int_group.items()):
        gid = f"__interruption__:{nk}:{dest}"
        targets = {use.use_id for use in int_uses}
        impact_ids = set().union(*(by_target[target] for target in targets))
        use_ids = targets | {impacts[i].source_use_id for i in impact_ids}
        expressions = [c for uid in use_ids for c in (by_id[uid].self_condition, by_id[uid].joint_condition)]
        expressions.extend(impacts[i].condition for i in impact_ids)
        terms.append((dependencies(expressions), {gid}, use_ids, impact_ids, ()))
    for expression in constraints:
        terms.append((dependencies((expression,)), set(), set(), set(), (_condition_program(expression, known),)))

    groups = list(_connected([term[0] for term in terms]))
    constants = [index for index, term in enumerate(terms) if not term[0]]
    if constants:
        groups = [group for group in groups if terms[group[0]][0]] + [constants]
    for group in groups:
        fact_ids = set().union(*(terms[i][0] for i in group))
        if 1 << len(fact_ids) > limit and len(group) > 1:
            # Relax dependencies between families inside a large component.
            # Each family keeps all its proofs, prices and affecting uses.
            for i in group:
                yield (*terms[i], False)
            continue
        yield (fact_ids, *(set().union(*(terms[i][column] for i in group)) for column in (1, 2, 3)),
               tuple(p for i in group for p in terms[i][4]), True)


def _public(fact):
    # Production appends the inventory identity to applicability and stock
    # facts. Explicit host facts have the scope chosen by their provider.
    return ':candidate:' not in fact


def evaluate_components(uses, impacts, sources, runtime, directions, known, unknown, constraints,
                        components, *, should_stop, family_prices):
    """Complete small components and condition larger envelopes on shared facts."""
    limit = min(32, runtime['completion_budget'])
    scenarios = ('resident', *(direction for direction in directions if direction != 'resident'))
    overrides = {scenario: _side_overrides(uses, scenario) for scenario in scenarios}
    for position, (facts, families, members, impact_ids, programs, independent) in enumerate(
            _units(uses, impacts, runtime['_theme_witnesses'], constraints, known, set(unknown), limit,
                   sources=sources, interruption_bonus=runtime.get('interruption_bonus'))):
        if position < len(components):
            continue
        if should_stop is not None and should_stop():
            return False
        columns = sorted(facts, key=lambda fact: (not _public(fact), fact))[:limit.bit_length() - 1]
        closed = len(columns) == len(facts)
        local_uses = [use for use in uses if use.use_id in members]
        local_impacts = [impacts[index] for index in sorted(impact_ids)]
        rows, side = [], {d: {} for d in directions}

        def score(completion, optimistic):
            values = {}
            for scenario in scenarios:
                result = _functional_inputs(local_uses, sources, runtime, completion, 3, scenario, local_impacts,
                    optimistic=optimistic, overrides=overrides[scenario], family_prices=family_prices)
                int_groups = result.get('interruption_groups', {})
                values[scenario] = fsum(result['functions'].get(family, 0.) + int_groups.get(family, 0.)
                                        for family in sorted(families))
            return values

        for bits in product((False, True), repeat=len(columns)):
            completion = dict(known)
            completion.update(zip(columns, bits))
            if any(_condition_truth(program, completion) is False for program in programs):
                continue
            low = score(completion, False) if families else dict.fromkeys(scenarios, 0.)
            high = low if closed or not families else score(completion, True)
            rows.append([list(bits), fsum(w * low[d] for d, w in directions.items()),
                         fsum(w * high[d] for d, w in directions.items())])
            for direction, bounds in side.items():
                delta = (0., 0.) if direction == 'resident' else (
                    low[direction] - high['resident'], high[direction] - low['resident'])
                for field, endpoints in (('resident', (low['resident'], high['resident'])),
                                         ('combined', (low[direction], high[direction])), ('delta', delta)):
                    bounds[field] = _extend_bound(_extend_bound(bounds.get(field), endpoints[0]), endpoints[1])
        if not rows:
            raise ContractError('static facts have no consistent completion')
        components.append(dict(facts=columns, rows=rows, exact=closed and independent, side=side,
                               families=sorted(families), unknown_count=len(facts)))
    return True


def component_ranges(components, directions):
    score = dict(lower=fsum(min(row[1] for row in c['rows']) for c in components),
                 upper=fsum(max(row[2] for row in c['rows']) for c in components))
    side = {d: {k: [fsum(c['side'][d][k][i] for c in components) for i in (0, 1)]
                for k in ('resident', 'combined', 'delta')} for d in directions}
    return score, side


def _project(component, columns, coefficient):
    indices = [component['facts'].index(fact) for fact in columns]
    projected = {}
    for bits, lower, upper in component['rows']:
        key = tuple(bits[i] for i in indices)
        if coefficient < 0:
            lower, upper = upper, lower
        lower, upper = lower * coefficient, upper * coefficient
        projected[key] = _extend_bound(_extend_bound(projected.get(key), lower), upper)
    return projected


def compare_components(before, after, ratio, sound_bounds):
    """Optimize a signed sum over common assignments and separate deck choices."""
    def terms(value):
        if value.components:
            known = tuple(dict(facts=(key,), exact=True, rows=[((known_value,), 0., 0.)])
                          for key, known_value in value.known_facts.items())
            return (*value.components, *known)
        if value.exact and value.completions:
            return (dict(facts=value.facts, exact=True, rows=[(bits, v, v) for bits, v in value.completions]),)
        return ()

    left, right = terms(before), terms(after)
    if not left or not right:
        return
    common = (set().union(*(c['facts'] for c in left)) & set().union(*(c['facts'] for c in right)))
    if not common:
        return
    components = (*left, *right)
    fact_sets = [common.intersection(c['facts']) for c in components]
    lows, highs, retained, exact = [], [], set(), all(c['exact'] for c in components)
    for group in _connected(fact_sets):
        facts = set().union(*(fact_sets[i] for i in group))
        columns = sorted(facts)[:10]
        retained.update(columns)
        exact &= len(columns) == len(facts)
        terms_by_group = []
        for index in group:
            component = components[index]
            positions = [i for i, column in enumerate(columns) if column in fact_sets[index]]
            table = _project(component, [columns[i] for i in positions], -ratio if index < len(left) else 1.)
            terms_by_group.append((positions, table))
        bounds = None
        for bits in product((False, True), repeat=len(columns)):
            ranges = [table.get(tuple(bits[i] for i in positions)) for positions, table in terms_by_group]
            if any(span is None for span in ranges):
                continue
            bounds = _extend_bound(_extend_bound(bounds, fsum(span[0] for span in ranges)),
                                   fsum(span[1] for span in ranges))
        if bounds is None:
            raise ContractError('candidate/reference shared facts have no consistent completion')
        lows.append(bounds[0])
        highs.append(bounds[1])
    return (max(sound_bounds[0], fsum(lows)), min(sound_bounds[1], fsum(highs)), exact, sorted(retained))
