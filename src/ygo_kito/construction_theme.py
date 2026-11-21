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


def configured_primary_goal(profile, code, semantic, outcomes, event, rows):
    """Match a sourced function and its available outcomes to the fixed theme."""
    if code in profile.get("required_card_ids", ()):
        return True
    route = profile.get("route_goal")
    if route and semantic["kind"] == route["kind"] and route["card_id"] in outcomes:
        return True
    if tags := profile.get("goal_tags"):
        from .effect_blocks import LABELS
        from .construction_effect_blocks import GRAVE_FUSION, MILL

        kind = semantic["kind"]
        names = {LABELS.get(kind)}
        if kind == "send_grave" and semantic["from_zones"] == ["deck"]:
            names.add(MILL.value)
        if kind == "fusion_summon" and event == 1014:  # EVENT_TO_GRAVE
            names.add(GRAVE_FUSION.value)
        if all(tag["dimension"] == "effect_type" and tag["value"] == kind
                or tag["dimension"] == "effect" and tag["value"] in names for tag in tags):
            return True
    if profile.get("predicates") and not any(matches(rows[code], {"predicate": predicate})
                                              for predicate in profile["predicates"]):
        return False
    for goal in profile["goals"]:
        expected = goal["function"]
        if any(expected.get(key) not in (None, "unknown", "either", semantic[key])
               for key in ("kind", "to_zone", "owner", "reason")):
            continue
        if expected.get("from_zones") and not set(semantic["from_zones"]) <= set(expected["from_zones"]):
            continue
        selector = expected.get("selector")
        if selector and not any(card in rows and matches(rows[card], selector) for card in outcomes):
            continue
        return True
    return False


def _movement_domain(source, dependencies, available, profile_cards, *, fusion_proof=None):
    from .effect_records import operation_record

    code, _, _, record, operation = source
    scoped = operation_record(record, operation)
    origins = operation.get('from_zones', ())
    gaps = []
    if operation.get('owner') != 'self':
        gaps.append('movement_owner')
    if operation.get('reason') not in ('effect', 'cost'):
        gaps.append('movement_reason')
    if (not origins or any(z not in ('hand', 'deck', 'grave', 'field', 'extra', 'banished', 'xyz_material')
            for z in origins) or type(operation.get('quantity')) is not int or operation['quantity'] < 1):
        gaps.append('movement_origin_or_quantity')
    query = dependencies.draft_operation_query(scoped, operation)

    if operation['kind'] == 'fusion_summon':
        if profile_cards is None:
            proof = fusion_proof or dependencies.fusion_check(available, code, scoped)
            known = {row['target'] for row in proof['options']} if proof else set()
            uncertain = set(proof['uncovered_targets']) - known if proof else set()
        else:
            # The fixed policy records theme goals by printed compatibility.
            # Distinct material copies are assigned only in a candidate view.
            known, uncertain = set(), set()
            selection = scoped.get('fusion_material_selection')
            if selection:
                for target in profile_cards.intersection(available.extra):
                    if not dependencies.rows[target]['type'] & 0x40:
                        continue
                    allowed, _ = dependencies.candidate_status(target, dict(category='operations', operation=operation))
                    if allowed is not True:
                        continue
                    _, materials = dependencies.specs(target)
                    if not materials or any(not query_supported(r['query']) for r in materials):
                        continue
                    if not selection['requires_this_card'] or any(matches(dependencies.rows[code], r['query'])
                            and dependencies.candidate_status(code, dict(r, origin='grave'), target=target)[0] is True
                            for r in materials):
                        known.add(target)
        cards = known | uncertain
    elif operation.get('generation'):
        return set(), set(), gaps  # A generated token is not a card in the inventory.
    elif operation.get('subject') == 'this_card':
        cards = known = {code}
    elif query is not None or (operation.get('random') and not (
            operation.get('selector') or operation.get('selector_query'))):
        cards = set(available.main + available.extra)
        if origins and set(origins) <= {'hand', 'deck'}:
            cards.intersection_update(available.main)
        elif list(origins) == ['extra']:
            cards.intersection_update(available.extra)
        known = cards
    else:
        # The source effect's selector gap is reported by its own coverage.
        # A movement with no recipient evidence cannot certify a theme pair.
        return set(), set(), ['complete_movement_selector', *gaps]
    if query is not None:
        cards = {c for c in cards if matches(dependencies.rows[c], query)}
    if profile_cards is None and operation.get('simultaneous_group'):
        # The recipient must fit the complete processing. A card matching
        # the target selector may still be the only legal summon candidate.
        proofs = {card_id: dependencies.simultaneous_processing(available, scoped, operation, card_id=card_id)
                  for card_id in sorted(cards)}
        if any(proof is not None for proof in proofs.values()):
            known = {card_id for card_id, proof in proofs.items()
                     if proof is not None and proof['status'] == 'inventory_present'}
            cards = {card_id for card_id, proof in proofs.items()
                     if proof is not None and proof['status'] != 'missing'}
    return cards, known, gaps


def direct_connection(source, receiver, dependencies, available, movement_domains, *, profile_cards=None):
    """Match a printed movement to a receiving effect in the available stock."""
    rc, ri, _, rr, result = receiver
    op = source[4]
    if op is result or source[:3] == receiver[:3]:
        return None
    zone = op.get('to_zone')
    if zone not in ('grave', 'banished', 'field') or op.get('owner') not in (None, 'unknown', 'self'):
        return None
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
    else:
        specs, materials = dependencies.specs(rc)
        requirements = [r for r in specs[ri]['requirements']
            if r['category'] == 'costs' or r.get('operation') == result]
        compatible = [r['query'] for r in (*requirements, *materials)
            if zone in r.get('origins', (r.get('origin'),)) and r.get('owner', 'self') == 'self']
        if not compatible:
            return None
    key = source[:3]
    if key not in movement_domains:
        movement_domains[key] = _movement_domain(source, dependencies, available, profile_cards)
    cards, known, gaps = movement_domains[key]
    gaps = list(gaps)
    if triggered:
        if rc not in cards:
            return None
        statuses = [dependencies.candidate_status(rc, dict(category='operations',
            operation=dict(op, from_zones=[origin])))[0] for origin in op.get('from_zones', ())]
        if statuses and all(status is False for status in statuses):
            return None
        if statuses and True not in statuses:
            gaps.append('recipient_summon_restriction')
        resources = [rc]
        kind = 'trigger'
    else:
        resources = sorted(c for c in cards if any(matches(dependencies.rows[c], query) for query in compatible))
        if not resources:
            return None
        kind = 'resource'
    confirmed = known.intersection(resources)
    if confirmed:
        resources = sorted(confirmed)
    elif op['kind'] == 'fusion_summon':
        gaps.append('fusion_material_configuration')
    elif op.get('simultaneous_group'):
        gaps.append('simultaneous_processing_configuration')
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
    """Fix the task's theme before candidate selection."""
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
    if getattr(catalog.assets, "rule_authority", None) == "locked_period_core":
        rows = catalog.assets.rows
        profile["rule_basis"] = "locked_period_core"
        if ((predicates and not any(any(public_matches(rows[c], p) for p in predicates)
                                    for c in task.pool if c in rows))
                or theme_id and not predicates and not explicit):
            profile["gaps"].append("theme_public_membership_required")
        if not set(task.pool) <= rows.keys():
            profile["gaps"].append("fixed_pool_card_facts_required")
        if profile["gaps"]:
            profile["status"] = "unknown"
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
    movement_domains = {}
    profile_cards = set(codes)
    # Some themes receive a resource from a generic support card. If the theme
    # itself supplies no observed connection, retrieve one actual counterpart;
    # do not make every unrelated legal card part of the policy's read budget.
    if not explicit and core and not any(
            (c := direct_connection(s, r, dependencies, available, movement_domains, profile_cards=profile_cards)) and not c['gaps']
            for s in entries for r in entries):
        for code in task.pool:
            if code in codes:
                continue
            specs, _ = dependencies.specs(code)
            extra = [(code, ri, oi, spec['record'], op) for ri,spec in enumerate(specs)
                     for oi,op in enumerate(spec['record']['operations'])]
            if not extra:
                continue
            probe_domains = dict(movement_domains)
            relevant = profile_cards | {code}
            if code in available.extra:
                probe_domains = {}
            if any((c := direct_connection(s, r, dependencies, available, probe_domains, profile_cards=relevant))
                    and not c['gaps'] for left, right in ((entries, extra), (extra, entries)) for s in left for r in right):
                entries += extra
                profile_cards = relevant
                movement_domains = probe_domains
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
            connection = direct_connection(source, receiver, dependencies, available, movement_domains, profile_cards=profile_cards)
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


def theme_pairs(operation_facts, records, dependencies, available, profile, budget, fusion_proofs,
                *, continuation=None, should_stop=None, work_state=None):
    """Collect static pairs without extending the resource graph."""
    entries = [(code, ri, oi, records[code][ri], records[code][ri]['operations'][oi])
        for code, ri, oi in operation_facts if oi is not None]
    preparations = {digest(p) for p in profile['preparations']}
    pairs, attempts = [], 0
    positions = [list(entry[:3]) for entry in entries]
    if continuation is not None and (continuation.get('version') != 'theme-pairs-v1'
            or continuation.get('operations') != positions):
        raise ContractError('theme pair continuation belongs to different operations')
    cursor = (continuation or {}).get('cursor', 0)
    accepted = dict((continuation or {}).get('accepted', {}))
    movement_domains = {entry[:3]: _movement_domain(entry, dependencies, available, None,
        fusion_proof=fusion_proofs[entry[:3]]) for entry in entries if entry[:3] in fusion_proofs}
    derive = profile.get("rule_basis") == "locked_period_core" and not profile["explicit_goals"]
    position = 0
    for receiver in entries:
        derived = derive and any(matches(dependencies.rows[receiver[0]], {"predicate": predicate})
                                 for predicate in profile["predicates"])
        if not derived and not primary_goal(profile, receiver[0], receiver[3], receiver[4], dependencies):
            continue
        goal = digest(function_goal(receiver[3], receiver[4]))
        for source in entries:
            if position < cursor:
                connection = accepted.get(str(position))
            else:
                if attempts >= budget.matches or should_stop is not None and should_stop():
                    return pairs, dict(version='theme-pairs-v1', operations=positions, cursor=position, accepted=accepted)
                attempts += 1
                connection = direct_connection(source, receiver, dependencies, available, movement_domains)
                if connection and not derived and not profile['explicit_goals'] and digest(dict(goal=goal, kind=connection['kind'],
                        zone=connection['zone'], event=connection['event'])) not in preparations:
                    connection = None
                if connection:
                    accepted[str(position)] = connection
            position += 1
            if connection:
                pair = dict(source=source[:3], receiver=receiver[:3], connection=connection)
                if derived:
                    pair["derived_goal"] = True
                pairs.append(pair)
    if work_state is not None:
        work_state.update(version='theme-pairs-v1', operations=positions, cursor=position, accepted=accepted)
    return pairs, None
