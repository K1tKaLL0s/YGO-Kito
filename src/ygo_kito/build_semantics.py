"""General count/predicate building goals over pinned public card facts.

This is a constraint compiler, not a card-effect parser or strength model.
MILP only proposes lists; the independent listing/semantic checks decide
acceptance. Exhausted solving is unknown, never a negative ability label.
"""
from collections import Counter
import math
import time

from .validation import ContractError,array,fields,integer,member

PREDICATES=('card_ids','setcode','type_all','race_any','attribute_any','level_between')


def validate_predicate(value,pool,depth=0):
    if depth>3:raise ContractError('semantic predicate nesting exceeds budget')
    if isinstance(value,dict) and len(value)==1 and next(iter(value)) in ('all','any','not'):
        key=next(iter(value))
        children=[value[key]] if key=='not' else array(value[key],'predicate children')
        integer(len(children),'predicate width',1,4)
        for child in children:validate_predicate(child,pool,depth+1)
        return
    d=fields(value,{'field','value'});member(d['field'],'semantic public fact',PREDICATES)
    if d['field']=='card_ids':
        ids=array(d['value'],'predicate card IDs');integer(len(ids),'predicate card count',1,128)
        for code in ids:
            integer(code,'predicate card ID',1,2**32-1)
            if code not in pool:raise ContractError('predicate identity absent from task pool')
        if len(set(ids))!=len(ids):raise ContractError('duplicate predicate identities')
    elif d['field']=='level_between':
        bounds=array(d['value'],'level bounds')
        if len(bounds)!=2:raise ContractError('two level bounds required')
        integer(bounds[0],'level minimum',0,255);integer(bounds[1],'level maximum',bounds[0],255)
    else:integer(d['value'],'public fact mask',1,65535 if d['field']=='setcode' else 2**32-1)


def validate_goal(goal,pool):
    d=fields(goal,{'kind','constraints','preferences'},{'route_goal','required_activations','required_chain_resolutions'})
    if d['kind']!='deck_constraints':raise ContractError('unsupported semantic goal')
    for key in ('required_activations','required_chain_resolutions'):
        if key not in d:continue
        values=array(d[key],'required public effect objectives')
        if 'route_goal' not in d or not 1<=len(values)<=4:
            raise ContractError('bounded distinct effect objectives require a native route goal')
        for code in values:
            integer(code,'required activation',1,2**32-1)
            if code not in pool:raise ContractError('required activation outside public pool')
        if len(set(values))!=len(values):raise ContractError('effect objectives repeat')
    constraints=array(d['constraints'],'hard count constraints');preferences=array(d['preferences'],'soft preferences')
    integer(len(constraints),'hard semantic constraint count',1,12);integer(len(preferences),'preference count',0,8)
    seen=set()
    from .agent_registry import identifier
    for hard,items in ((True,constraints),(False,preferences)):
        for item in items:
            fields(item,{'id','zones','predicate'}|({'minimum','maximum'} if hard else {'weight'}))
            identifier(item['id'])
            if item['id'] in seen:raise ContractError('semantic constraint IDs repeat')
            seen.add(item['id']);zones=array(item['zones'],'semantic zones')
            integer(len(zones),'semantic zone count',1,3)
            if len(set(zones))!=len(zones) or any(z not in ('main','extra','side') for z in zones):
                raise ContractError('unknown or duplicate semantic zone')
            validate_predicate(item['predicate'],pool)
            if hard:
                integer(item['minimum'],'semantic minimum',0,90);integer(item['maximum'],'semantic maximum',item['minimum'],90)
            elif type(item['weight']) not in (int,float) or not math.isfinite(item['weight']) or not 0<abs(item['weight'])<=100:
                raise ContractError('preference weight must be finite, nonzero and bounded')


def matches(row,predicate):
    if 'all' in predicate:return all(matches(row,p) for p in predicate['all'])
    if 'any' in predicate:return any(matches(row,p) for p in predicate['any'])
    if 'not' in predicate:return not matches(row,predicate['not'])
    key,value=predicate['field'],predicate['value']
    if key=='card_ids':return row['id'] in value
    if key=='setcode':
        packed=row['setcode']%(1<<64)
        # Pinned card::is_set_card: low 12 bits match, requested subtype bits
        # must all be present. A substring/name match is not a theme fact.
        return any((part&0xfff)==(value&0xfff) and (part&value&0xf000)==(value&0xf000)
                   for part in ((packed>>n)&0xffff for n in range(0,64,16)))
    if key=='type_all':return row['type']&value==value
    if key=='race_any':return bool(row['race']&value)
    if key=='attribute_any':return bool(row['attribute']&value)
    return value[0]<=row['level']&255<=value[1]


def count(deck,item,rows):
    return sum(matches(rows[c],item['predicate']) for zone in item['zones'] for c in getattr(deck,zone))


def validate_counts(task,deck,assets):
    result=[]
    for item in task.goal['constraints']:
        actual=count(deck,item,assets.rows)
        if not item['minimum']<=actual<=item['maximum']:
            raise ContractError('deck violates semantic count constraint: '+item['id'])
        result.append({'id':item['id'],'actual':actual,'minimum':item['minimum'],'maximum':item['maximum']})
    return result


def preference_value(task,deck,assets):
    return sum(item['weight']*count(deck,item,assets.rows) for item in task.goal['preferences'])


def _draft_priorities(assets, graph, catalog, pool, variables, skeleton):
    """Use printed functions and compatible stock to propose complete lists."""
    from .construction_inventory import InventoryDependencies, effect_matches, matches as stock_matches
    from .effect_blocks import functional_tags
    from .effect_mechanisms import MechanismCatalog

    catalog = catalog or MechanismCatalog(assets, pool)
    inventory = InventoryDependencies(catalog)
    node_demands = {node.node_id: tuple(tag for tag in node.tags if tag.dimension in ('effect', 'effect_type'))
                    for node in graph.nodes}
    demands = tuple(dict.fromkeys(tags for tags in node_demands.values() if tags))
    effects = {code: catalog.effect_records(code) for code in pool}
    draft_hits = {code: tuple(i for i, tags in enumerate(demands)
                             if any(effect_matches(record, tags) for record in effects[code]))
                  for code in pool}
    useful = {'检索', '抽卡', '回收', '特召', '破坏', '除外', '回手', '效果无效', '发动无效', '召唤无效'}
    interaction = {'破坏', '除外', '回手', '效果无效', '发动无效', '召唤无效'}
    functions = {code: {row['tag']['value'] for row in functional_tags(catalog.effect_blocks(code))}
                 for code in pool}
    groups = {}
    for i in range(len(demands)):
        eligible = tuple(j for j, (zone, code) in enumerate(variables) if zone != 'side' and i in draft_hits[code])
        if eligible:
            groups[(eligible, 1)] = 32.
    if skeleton is not None:
        from types import SimpleNamespace
        from .build_pipeline import EXTRA_TYPES
        from .construction_theme import operation_query

        # These are potential resource domains, not a proposed deck. Fusion
        # eligibility uses the existing distinct-material and restriction check.
        stock = {z: [] for z in ('main', 'extra')}
        seen = set()
        for code in (*skeleton.main, *skeleton.extra, *pool):
            alias = assets.rows[code]['alias'] or code
            if alias in seen:
                continue
            seen.add(alias)
            zone = 'extra' if assets.rows[code]['type'] & EXTRA_TYPES else 'main'
            stock[zone].extend([code] * assets.limits.get(alias, 3))
        available = SimpleNamespace(**stock)
        for code in sorted(set(skeleton.main + skeleton.extra)):
            specs, materials = inventory.specs(code)
            for spec in specs:
                record = spec['record']
                if any(effect_matches(record, tags) for tags in demands):
                    for req in spec['requirements']:
                        if req.get('choice'):
                            continue  # Alternatives must not be treated as joint requirements.
                        _add_stock_priority(groups, variables, inventory, code, req)
                    if record.get('fusion_material_selection') and code in (*available.main, *available.extra):
                        fusion = inventory.fusion_check(available, code, record)
                        targets = {option['target'] for option in fusion['options']}
                        eligible = tuple(i for i, (zone, card) in enumerate(variables)
                                         if zone == 'extra' and card in targets)
                        if eligible:
                            groups[(eligible, 1)] = max(12., groups.get((eligible, 1), 0.))
                for edge in graph.connectors:
                    if edge.kind != '送墓时发动' or not effect_matches(record, node_demands[edge.source]):
                        continue
                    target = node_demands[edge.target]
                    for operation in record['operations']:
                        if (operation.get('reason') != 'effect' or operation.get('owner') != 'self'
                                or operation.get('from_zones') != ['deck'] or operation.get('to_zone') != 'grave'):
                            continue
                        query = operation_query(operation, inventory)
                        if query is None and not operation.get('random'):
                            continue
                        eligible = tuple(i for i, (zone, card) in enumerate(variables)
                            if zone == 'main' and (query is None or stock_matches(assets.rows[card], query))
                            and any(r['trigger'].get('event') == 'sent_to_grave'
                                    and r['trigger'].get('reason') in ('effect', 'not_applicable')
                                    and effect_matches(r, target) for r in effects[card]))
                        if eligible:
                            groups[(eligible, 1)] = max(12., groups.get((eligible, 1), 0.))
            for req in materials:
                _add_stock_priority(groups, variables, inventory, code, req)
    priorities = [
        (len(draft_hits[code]), min(3, len(functions[code] & useful)),
         min(3, len(functions[code] & interaction)))
        for _, code in variables
    ]
    return priorities, groups


def _add_stock_priority(groups, variables, inventory, source, req):
    from .construction_inventory import matches, query_supported

    if (req.get('owner', 'self') != 'self' or not query_supported(req['query'])
            or type(req.get('minimum')) is not int or req['minimum'] < 1):
        return
    # Unknown face-up state is not a printed match. Printed material identities
    # and selectors use the same restriction checks as the inventory evaluator.
    if 'face_up' in req['query']:
        return
    material = req['category'] == 'material'
    allowed = []
    for i, (zone, code) in enumerate(variables):
        row = inventory.rows[code]
        if (zone == 'side' or (req['origin'] in ('hand', 'deck') and zone != 'main')
                or (req['origin'] == 'extra' and zone != 'extra')
                or (material and (not row['type'] & 1 or code == source))
                or (req.get('exclude_source_copy') and code == source)
                or not matches(row, req['query'])):
            continue
        if inventory.candidate_status(code, req, target=source if material else None)[0] is True:
            allowed.append(i)
    if allowed:
        key = tuple(allowed), req['minimum']
        groups[key] = max(8., groups.get(key, 0.))


def solve_candidates(task,assets,base=None,*,max_edits=None,seconds=3.,candidate_count=None,skeleton=None,candidate_ids=None,
                     draft_graph=None,catalog=None):
    from .build_contracts import DeckParts,ZONES
    from .deck_profile import validate_deck_parts
    from .build_pipeline import EXTRA_TYPES, candidate_limit
    assets.check_task(task)
    if task.goal['kind']!='deck_constraints':raise ContractError('semantic task required')
    if type(seconds) not in (int,float) or not math.isfinite(seconds) or not 0<=seconds<=10:
        raise ContractError('semantic solver time budget outside CPU range')
    if max_edits is not None:
        integer(max_edits,'maximum replacements',0,30)
        if base is None:raise ContractError('edit budget requires an existing listing')
    if base is not None:
        validate_deck_parts(base.to_dict(),assets.rows,assets.limits,allowed=set(task.pool))
        if any(len(getattr(base,z))!=task.sizes[z] for z in ZONES):raise ContractError('existing section sizes differ')
    if skeleton is not None:
        assets.validate_skeleton(task, skeleton)
    limit = candidate_limit(task)
    wanted = limit if candidate_count is None else integer(candidate_count, 'semantic candidates', 1, limit)
    if not seconds:return {'status':'not_found_within_budget','candidates':[],'solver_calls':0,'solver_statuses':[]}
    try:
        import numpy as np
        from scipy.optimize import Bounds,LinearConstraint,milp
        from scipy.sparse import coo_matrix
    except ImportError as error:raise ContractError('semantic construction requires the pinned CPU scipy extra') from error
    pool = task.pool if candidate_ids is None else tuple(candidate_ids)
    starting_cards = {c for deck in (base, skeleton) if deck is not None for z in ZONES for c in getattr(deck, z)}
    if not set(pool) <= set(task.pool) or not starting_cards <= set(pool):
        raise ContractError('solver query exceeds task pool or omits its input inventory')
    variables=[(z,c) for z in ZONES for c in pool
               if z=='side' or bool(assets.rows[c]['type']&EXTRA_TYPES)==(z=='extra')]
    size = len(variables)
    overlap = size if base is not None and max_edits is not None else 0
    if draft_graph is None:
        priorities, groups = [(0, 0, 0)] * size, {}
    else:
        priorities, groups = _draft_priorities(assets, draft_graph, catalog, pool, variables, skeleton)
    dimensions = size + overlap + len(groups)
    low = np.zeros(dimensions)
    high = np.full(dimensions, 3.)
    coefficients, lower, upper = [], [], []

    def constraint(values, lo, hi):
        coefficients.append(values)
        lower.append(lo)
        upper.append(hi)

    for zone in ZONES:constraint({i:1 for i,(z,c) in enumerate(variables) if z==zone},task.sizes[zone],task.sizes[zone])
    for alias in sorted({assets.rows[c]['alias'] or c for z,c in variables}):
        constraint({i:1 for i,(z,c) in enumerate(variables) if (assets.rows[c]['alias'] or c)==alias},0,assets.limits.get(alias,3))
    for req in task.requirements:
        indices=[i for i,v in enumerate(variables) if v==(req['zone'],req['card_id'])]
        if not indices:
            if req['minimum']:return {'status':'infeasible_declared_list_constraints','candidates':[],'solver_calls':0,'solver_statuses':[]}
            continue
        low[indices[0]],high[indices[0]]=req['minimum'],req['maximum']
    for item in task.goal['constraints']:
        constraint({i:1 for i,(z,c) in enumerate(variables) if z in item['zones'] and matches(assets.rows[c],item['predicate'])},item['minimum'],item['maximum'])
    if skeleton is not None:
        for i, (zone, code) in enumerate(variables):
            low[i] = max(low[i], getattr(skeleton, zone).count(code))
    if overlap:
        for i,(z,c) in enumerate(variables):
            high[size+i]=getattr(base,z).count(c)
            constraint({size+i:1,i:-1},-np.inf,0)
        constraint({size+i:1 for i in range(size)},sum(task.sizes.values())-max_edits,np.inf)
    # Reward each distinct supported demand once, up to its printed stock
    # quantity. A side-deck copy cannot cover a main/extra dependency.
    group_weights = []
    for (eligible, amount), reward in groups.items():
        index = size + overlap + len(group_weights)
        high[index] = amount
        constraint({**dict.fromkeys(eligible, 1), index: -1}, 0, np.inf)
        group_weights.append(reward)
    row_indices, column_indices, values = [], [], []
    for row, entries in enumerate(coefficients):
        row_indices.extend([row] * len(entries))
        column_indices.extend(entries)
        values.extend(entries.values())
    matrix = coo_matrix((values, (row_indices, column_indices)), shape=(len(coefficients), dimensions)).tocsc()
    restrictions = LinearConstraint(matrix, lower, upper)
    integrality = np.r_[np.ones(size), np.zeros(dimensions - size)]
    preferred = [sum(item['weight'] for item in task.goal['preferences']
                     if zone in item['zones'] and matches(assets.rows[code], item['predicate']))
                 for zone, code in variables]

    # Each direction spends one solver slot. Ties in printed evidence and
    # explicit preferences use a stable order, without random card weights.
    directions = ((2, 2, 1), (1, 1, 3), (3, 1, 2), (1, 3, 1), (2, 1, 2))
    found=[];statuses=[];started=time.monotonic()
    for variant in range(wanted):
        remaining=seconds-(time.monotonic()-started)
        if remaining<=0:break
        effect_weight, utility_weight, side_weight = directions[variant]
        objective = np.zeros(dimensions)
        for i, (zone, _) in enumerate(variables):
            draft, useful, response = priorities[i]
            strength = side_weight * response if zone == 'side' else effect_weight * draft + utility_weight * useful
            order = i if variant % 2 == 0 else size - i
            objective[i] = -(strength + preferred[i]) + order * (1e-4 / max(1, size))
        objective[size + overlap:] = -np.array(group_weights)
        result=milp(objective, integrality=integrality, bounds=Bounds(low,high),
                    constraints=restrictions,
                    options={'time_limit':remaining,'node_limit':10000,'mip_rel_gap':0.})
        statuses.append(int(result.status))
        if result.x is None:
            if result.status==2:break
            continue
        values=result.x[:size]
        if not np.isfinite(values).all() or np.max(np.abs(values-np.rint(values)))>1e-6:continue
        parts={z:[] for z in ZONES}
        for (z,c),n in zip(variables,np.rint(values).astype(int)):parts[z].extend([c]*int(n))
        deck=DeckParts(*(tuple(sorted(parts[z])) for z in ZONES))
        assets.validate(task,deck)
        if max_edits is not None and replacements(base,deck)>max_edits:raise ContractError('solver edit distance failed independent check')
        if deck not in found:found.append(deck)
    status='verified_list_candidates' if found else 'infeasible_declared_list_constraints' if statuses and statuses[-1]==2 else 'not_found_within_budget'
    return {'status':status,'candidates':found,'solver_calls':len(statuses),'solver_statuses':statuses}


def replacements(before,after):
    return sum(sum((Counter(getattr(after,z))-Counter(getattr(before,z))).values()) for z in ('main','extra','side'))


def proof(task,deck,assets):
    from .build_contracts import digest
    assets.validate(task,deck)
    return {'status':'constraints_satisfied','task_sha256':task.sha256,'deck_sha256':digest(deck.to_dict()),
            'counts':validate_counts(task,deck,assets),'versions':task.environment['versions'],
            'effect_execution_verified':False,'competitive_strength_verified':False}


def route_task(task):
    """Explicit observer/schema projection for existing real v3 route discovery.

    Physical core/scripts/cards/banlist stay identical. The v2 route probe and
    v5 general-duel DTOs remain separately labelled, never silently interchanged.
    """
    from .build_contracts import BuildTask, DISCOVERY_GOALS
    goal=fields(task.goal.get('route_goal'),{'kind','card_id','starting_conditions'},{'route','fusion_witness','effect_objective'})
    if goal['kind'] not in DISCOVERY_GOALS:
        raise ContractError('combined goal requires a supported conditional discovery objective')
    raw=task.to_dict();raw['schema_version']=3;raw['goal']=raw['goal']['route_goal']
    if 'route' in raw['goal']:raise ContractError('combined objective uses core discovery, not a prewritten route')
    if raw['environment']['release_cutoff'] is None:
        raw['environment']['versions']['card_pool']='native-extra-material-v2'
    return BuildTask.from_dict(raw)


def verify_combined(task,deck,assets,*,seconds=10.,attempts=16,decision_budget=100):
    from .route_search import discover_goal
    counts=proof(task,deck,assets);native=route_task(task)
    route=discover_goal(native,deck,assets,seconds=seconds,attempts=attempts,decision_budget=decision_budget,
                        required_activations=tuple(task.goal.get('required_activations',())),
                        required_chain_resolutions=tuple(task.goal.get('required_chain_resolutions',())))
    return {'status':'constraints_and_route_verified' if route['status']=='verified_success' else route['status'],
            'task_sha256':task.sha256,'deck_sha256':counts['deck_sha256'],'constraints':counts,'native_route':route,
            'effect_execution_verified':route['status']=='verified_success','competitive_strength_verified':False,
            'unmet':route.get('unmet',[])}


def accepted_status(task):
    if task.goal['kind']!='deck_constraints':return 'verified_success'
    return 'constraints_and_route_verified' if 'route_goal' in task.goal else 'constraints_satisfied'
