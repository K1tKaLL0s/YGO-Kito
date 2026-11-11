"""Task-owned goals inferred from direct, observed card-effect cooperation.

The declared goal and real theme cooperation determine the fixed policy. A
candidate supplies inventory and support; it cannot nominate goals or percentages.
This module consumes the existing effect records and selector checks.
"""
from copy import deepcopy
from types import SimpleNamespace

from .build_contracts import digest
from .construction_inventory import InventoryDependencies, effect_matches, matches, query_supported
from .construction_relations import RelationBudget
from .effect_mechanisms import EXTRA_TYPES
from .validation import ContractError


THEME_VERSION = 'construction-theme-goals-v1'
PRIMARY = 'task-primary'
SECONDARY = 'task-secondary'


def function_goal(record, operation):
    from .construction_layer_flow import _function_semantics
    trigger = record['trigger']
    resources = [{k: deepcopy(item[k]) for k in ('kind', 'from_zones', 'zones', 'to_zone',
        'owner', 'quantity', 'resource', 'selector_query', 'selector', 'reason') if k in item}
        for item in record['costs']]
    return dict(function=_function_semantics(record, operation),
        trigger={k: trigger.get(k) for k in ('event', 'zone', 'reason')},
        costs=resources, materials=deepcopy(record.get('printed_materials', [])))


def operation_query(operation, dependencies):
    req = dependencies.item_requirement(operation, 'operations')
    if req:
        return req['query']
    query = operation.get('selector_query')
    if query:
        query = dependencies.resolve_query(query)
        return query if query_supported(query) else None
    return None


def primary_goal(profile, code, record, operation, dependencies):
    """Explicit task functions match actual processing without preselecting cards."""
    from .construction_logic import LogicTag
    if operation is None:
        return False
    if digest(function_goal(record, operation)) in {g['goal_id'] for g in profile['goals']}:
        return True
    if code in profile.get('required_card_ids', ()):
        return True
    tags = tuple(LogicTag.from_dict(t) for t in profile.get('goal_tags', ()))
    if tags and effect_matches({**record,'operations':[operation]}, tags):
        return True
    route = profile.get('route_goal')
    if route and operation['kind'] == route['kind']:
        query = operation_query(operation, dependencies)
        return query is not None and matches(dependencies.rows[route['card_id']], query)
    return False


def direct_connection(source, receiver, dependencies, available):
    """A compatible transfer/recipient, not proof that an effect has resolved.

    Missing owner/reason/selectors are returned as a local gap. Actual costs,
    activation, quantities, limits and joint inventory are checked by the
    existing relation solver after this semantic match.
    """
    sc, _, _, sr, op = source
    rc, _, _, rr, result = receiver
    if op is result or source[:3] == receiver[:3]:
        return None
    zone = op.get('to_zone')
    # Searching a card does not inherit that card's later processing function.
    if zone not in ('grave', 'banished', 'field'):
        return None
    if op.get('owner') not in (None, 'unknown', 'self'):
        return None
    origins = op.get('from_zones', ())
    gaps = []
    if op.get('owner') != 'self':
        gaps.append('movement_owner')
    if op.get('reason') not in ('effect', 'cost'):
        gaps.append('movement_reason')
    if len(origins) != 1 or type(op.get('quantity')) is not int or op['quantity'] < 1:
        gaps.append('movement_origin_or_quantity')
    query = operation_query(op, dependencies)
    if query is None and not op.get('random'):
        gaps.append('complete_movement_selector')
    trigger = rr['trigger']
    event = ('sent_to_grave' if zone == 'grave' else
        'special_summon' if zone == 'field' and op['kind'] in (
            'special_summon', 'fusion_summon', 'synchro_summon', 'xyz_summon',
            'link_summon', 'ritual_summon', 'pendulum_summon') else
        'normal_summon' if zone == 'field' and op['kind'] in ('normal_summon', 'tribute_summon') else None)
    triggered = event and (trigger.get('event') == event or
        event in ('normal_summon', 'special_summon') and trigger.get('event') == 'normal_or_special_summon')
    if triggered:
        if trigger.get('reason') not in (None, 'not_applicable', op.get('reason')):
            return None
        if query is not None and not matches(dependencies.rows[rc], query):
            return None
        if origins == ['deck'] and rc not in available.main:
            return None
        resources = [rc]
        kind = 'trigger'
    else:
        # Only a resource directly used by the receiving processing counts.
        # Card presence and a shared zone word alone do not establish this.
        specs, materials = dependencies.specs(rc)
        requirements = [r for r in specs[receiver[1]]['requirements']
            if r['category'] == 'costs' or r.get('operation') == result]
        requirements.extend(materials)
        compatible = [r for r in requirements if r.get('origin') == zone and r.get('owner', 'self') == 'self']
        resources = sorted({c for c in (*available.main, *available.extra)
            if any(matches(dependencies.rows[c], req['query']) for req in compatible)
            and (query is None or matches(dependencies.rows[c], query))
            and (origins != ['deck'] or c in available.main)})
        if not resources:
            return None
        kind = 'resource'
    eligible, _ = dependencies.candidate_status(rc, dict(category='operations', operation=op)) if triggered else (True, [])
    if eligible is False:
        return None
    if eligible is None:
        gaps.append('recipient_summon_restriction')
    return dict(kind=kind, zone=zone, event=trigger.get('event') if triggered else None,
        resources=resources, gaps=gaps)


def _theme_predicates(task, theme, theme_id):
    if theme is not None:
        if not isinstance(theme, dict) or not {'field', 'value'} <= theme.keys():
            raise ContractError('automatic theme requires a public predicate')
        return [dict(field=theme['field'], value=deepcopy(theme['value']))]
    from .construction_logic import declared_theme_scopes
    predicates = [dict(field=s.field,value=s.value) for s in declared_theme_scopes(task)]
    if not predicates and theme_id and theme_id.startswith('setcode-'):
        try:
            predicates = [dict(field='setcode', value=int(theme_id.split('-', 1)[1], 16))]
        except ValueError:
            pass
    return predicates


def derive_theme_profile(task, catalog, *, theme=None, theme_id=None, goal_tags=(), budget=None):
    """Infer fixed primary results and their direct preparations, once per task."""
    from .build_semantics import matches as public_matches, validate_predicate
    from .construction_logic import LogicTag
    budget = budget or RelationBudget()
    predicates = _theme_predicates(task, theme, theme_id)
    for predicate in predicates:
        validate_predicate(predicate, task.pool)
    tags = tuple(t if isinstance(t, LogicTag) else LogicTag.from_dict(t) for t in goal_tags)
    functional_tags = tuple(t for t in tags if t.dimension in ('effect', 'effect_type', 'role'))
    route = task.goal.get('route_goal', task.goal if task.goal['kind'] != 'deck_constraints' else None)
    explicit = bool(functional_tags or route or task.goal.get('required_activations') or task.goal.get('required_chain_resolutions'))
    requested = bool(predicates or theme_id or explicit)
    profile = dict(version=THEME_VERSION, task_sha256=task.sha256, predicates=predicates,
        explicit_goals=explicit, goals=[], preparations=[], evidence=[], gaps=[],
        percentages={PRIMARY: 100, SECONDARY: 50}, status='evaluated' if requested else 'not_applicable',
        cards_sha256=getattr(catalog, 'cards_sha256', None), card_texts={})
    profile.update(goal_tags=[dict(dimension=t.dimension,value=t.value) for t in functional_tags],
        required_card_ids=sorted(set(task.goal.get('required_activations', ())) |
            set(task.goal.get('required_chain_resolutions', ()))), route_goal=deepcopy(route))
    if not requested:
        return profile
    if catalog is None:
        profile.update(status='unknown', gaps=['fixed_card_effects_required'])
        return profile
    dependencies = InventoryDependencies(catalog, requirement_limit=budget.facts)
    core = {c for c in task.pool if c in dependencies.rows
        and any(public_matches(dependencies.rows[c], p) for p in predicates)}
    if (predicates and not core) or theme_id and not predicates:
        profile['gaps'].append('theme_public_membership_required')
    if any(c not in dependencies.rows for c in task.pool):
        profile['gaps'].append('fixed_pool_card_facts_required')
    # The theme defines its mechanisms through its own actual cooperation.
    # Unrelated legal cards are retrieval resources, not an obligation to read
    # the entire environment before this fixed policy can be evaluated.
    required = set(task.goal.get('required_activations', ())) | set(task.goal.get('required_chain_resolutions', ()))
    codes = sorted(core | required | ({route['card_id']} if route else set()))
    if len(codes) > budget.cards:
        profile['gaps'].append('theme_card_budget')
    entries, work = [], 0
    for code in codes[:budget.cards]:
        if code not in dependencies.rows:
            continue
        specs, _ = dependencies.specs(code)
        profile['card_texts'][str(code)] = catalog.card(code).text_sha256
        for ri, spec in enumerate(specs):
            record = spec['record']
            for oi, op in enumerate(record['operations']):
                work += 1
                if work > budget.facts:
                    profile['gaps'].append('theme_fact_budget')
                    break
                entries.append((code, ri, oi, record, op))
    available = SimpleNamespace(main=tuple(c for c in task.pool if c in dependencies.rows
        and not dependencies.rows[c]['type'] & EXTRA_TYPES),
        extra=tuple(c for c in task.pool if c in dependencies.rows and dependencies.rows[c]['type'] & EXTRA_TYPES))
    # Some themes receive a resource from a generic support card. If the theme
    # itself supplies no observed connection, retrieve one actual counterpart;
    # do not make every unrelated legal card part of the policy's read budget.
    if not explicit and core and not any(
            (c := direct_connection(s, r, dependencies, available)) and not c['gaps']
            for s in entries for r in entries):
        for code in task.pool:
            if code in codes:
                continue
            specs, _ = dependencies.specs(code)
            extra = [(code, ri, oi, spec['record'], op) for ri,spec in enumerate(specs)
                     for oi,op in enumerate(spec['record']['operations'])]
            if any((c := direct_connection(s, r, dependencies, available)) and not c['gaps']
                   for left,right in ((entries,extra),(extra,entries)) for s in left for r in right):
                entries += extra
                profile['card_texts'][str(code)] = catalog.card(code).text_sha256
                break
    goals, preparations, evidence = {}, {}, {}
    def add_goal(entry, origin):
        goal = function_goal(entry[3], entry[4])
        key = digest(goal)
        goals[key] = goal
        evidence[digest((key, entry[:3], origin))] = dict(goal=key, card_id=entry[0],
            effect_index=entry[3]['effect_index'], origin=origin, text_sha256=entry[3]['text_sha256'])
        return key
    required = set(task.goal.get('required_activations', ())) | set(task.goal.get('required_chain_resolutions', ()))
    if explicit:
        for entry in entries:
            code, _, _, record, op = entry
            matched = bool(functional_tags and effect_matches({**record, 'operations': [op]}, functional_tags)) or code in required
            if route and op['kind'] == route.get('kind'):
                query = operation_query(op, dependencies)
                matched |= query is not None and matches(dependencies.rows[route['card_id']], query)
            if matched:
                add_goal(entry, 'explicit_task_goal')
        if not goals and not functional_tags:
            profile['gaps'].append('explicit_goal_processing_required')
    pairs, unresolved = 0, set()
    for receiver in entries:
        if explicit and digest(function_goal(receiver[3], receiver[4])) not in goals:
            continue
        for source in entries:
            pairs += 1
            if pairs > budget.matches:
                profile['gaps'].append('theme_pair_budget')
                break
            connection = direct_connection(source, receiver, dependencies, available)
            if not connection:
                continue
            if not explicit and not (source[0] in core or receiver[0] in core
                    or set(connection['resources']) & core):
                continue
            if connection['gaps']:
                unresolved.update('theme_relation:' + v for v in connection['gaps'])
                continue
            key = add_goal(receiver, 'explicit_task_goal' if explicit else 'observed_theme_cooperation')
            preparation = dict(goal=key, kind=connection['kind'], zone=connection['zone'], event=connection['event'])
            preparations[digest(preparation)] = preparation
            evidence[digest((source[:3], receiver[:3]))] = dict(goal=key,
                source_card_id=source[0], receiver_card_id=receiver[0], resources=connection['resources'],
                sources=[source[3]['text_sha256'], receiver[3]['text_sha256']], origin='direct_cooperation')
        if pairs > budget.matches:
            break
    if requested and not goals and not profile['gaps'] and not functional_tags:
        profile['gaps'].extend(sorted(unresolved) or ['theme_core_cooperation_required'])
    profile.update(goals=[dict(goal_id=k, **v) for k, v in sorted(goals.items())],
        preparations=[v for _, v in sorted(preparations.items())],
        evidence=[v for _, v in sorted(evidence.items())], gaps=sorted(set(profile['gaps'])),
        unresolved_optional_relations=sorted(unresolved))
    if profile['gaps']:
        profile['status'] = 'unknown'
    return profile


def automatic_rules(profile):
    if profile['status'] == 'not_applicable':
        return []
    return [dict(rule_id=rule, increment=percent / 100, percentage=percent,
        predicate={'task_goal': role}) for rule, role, percent in (
            (PRIMARY, 'primary', 100), (SECONDARY, 'secondary', 50))]


def add_theme_relations(facts, uses, operation_facts, records, dependencies, available, profile, budget,
                        *, continuation=None, should_stop=None, work_state=None):
    """Reuse the relation solver for availability and joint use of each pair.

    A private availability event asks whether the receiving effect can use a
    compatible transfer. It is never exported as an actual activation. The
    joint proof replaces it with the actual supplying operation, retaining
    costs, claims, choices, selectors and physical transfers from both effects.
    """
    from dataclasses import replace
    from .construction_relations import InputGroup, Need, RelationFact, Resource, UseRequirement
    by_fact = {f.fact_id: f for f in facts}
    entries = [(code, ri, oi, records[code][ri], records[code][ri]['operations'][oi])
        for code, ri, oi in operation_facts if oi is not None]
    goals = {g['goal_id'] for g in profile['goals']}
    preparations = {digest(p) for p in profile['preparations']}
    pairs, gaps, attempts = [], [], 0
    positions=[list(entry[:3]) for entry in entries]
    if continuation is not None and (continuation.get('version')!='theme-relations-v1' or continuation.get('operations')!=positions):
        raise ContractError('theme relation continuation belongs to different operations')
    cursor=(continuation or {}).get('cursor',0)
    accepted=deepcopy((continuation or {}).get('accepted',{}))
    position=0
    def replace_trigger(node, resource, code):
        if isinstance(node, Need):
            return replace(node, resource=resource, need_id=node.need_id + ':theme:' + resource.kind + ':' + digest(resource.attributes)) if node.resource.kind == 'activation' and (
                'card:' + str(code)) in node.resource.attributes else node
        return InputGroup(node.operator, tuple(replace_trigger(v, resource, code) for v in node.items))
    for receiver in entries:
        goal = digest(function_goal(receiver[3], receiver[4]))
        if not primary_goal(profile, receiver[0], receiver[3], receiver[4], dependencies):
            continue
        for source in entries:
            if position<cursor:
                connection=accepted.get(str(position))
            else:
                if attempts>=budget.matches or should_stop is not None and should_stop():
                    return pairs,dict(version='theme-relations-v1',operations=positions,cursor=position,accepted=accepted)
                attempts+=1
                connection=direct_connection(source,receiver,dependencies,available)
                if connection and not profile['explicit_goals'] and digest(dict(goal=goal,kind=connection['kind'],
                        zone=connection['zone'],event=connection['event'])) not in preparations:
                    connection=None
                if connection:accepted[str(position)]=deepcopy(connection)
            position+=1
            if not connection:continue
            source_fact = by_fact[operation_facts[source[:3]].removeprefix('functional:')]
            receiver_fact = by_fact[operation_facts[receiver[:3]].removeprefix('functional:')]
            key = 'theme:' + digest((source[:3], receiver[:3], goal))
            ready = Resource('theme_available', attributes=(key,))
            joint = Resource('theme_joint', attributes=(key,))
            if connection['kind'] == 'trigger':
                event = Resource('theme_event', attributes=(key,))
                facts.append(RelationFact(key + ':event', key + ':event', event,
                    'compatible receiving event; availability only'))
                own_inputs = replace_trigger(receiver_fact.inputs, event, receiver[0])
                joint_inputs = replace_trigger(receiver_fact.inputs, source_fact.output, receiver[0])
            else:
                own_inputs = receiver_fact.inputs
                additional = Need(key + ':preparation', source_fact.output, mode='presence')
                joint_inputs = InputGroup('all', (*own_inputs.items, additional)) if (
                    own_inputs is not None and own_inputs.operator == 'all') else InputGroup('all', tuple(
                        v for v in (own_inputs, additional) if v is not None))
            unknown = tuple(sorted(set((*receiver_fact.unknown, *connection['gaps']))))
            facts.extend((replace(receiver_fact, fact_id=key + ':available', output=ready,
                    inputs=own_inputs, output_pool=None, unknown=unknown),
                replace(receiver_fact, fact_id=key + ':joint', output=joint,
                    inputs=joint_inputs, output_pool=None, unknown=unknown)))
            for suffix, output in (('available', ready), ('joint', joint)):
                uid = key + ':' + suffix
                uses.append(UseRequirement(uid, InputGroup('all', (Need(uid, output, mode='presence'),)),
                    'direct task-goal cooperation', required=False))
            pairs.append(dict(source=source[:3], receiver=receiver[:3],
                available_use_id=key + ':available', joint_use_id=key + ':joint', connection=connection))
    if work_state is not None:
        work_state.update(version='theme-relations-v1',operations=positions,cursor=position,accepted=accepted)
    return pairs, gaps
