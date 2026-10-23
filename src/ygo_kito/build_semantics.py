"""General count/predicate building goals over pinned public card facts.

This is a constraint compiler, not a card-effect parser or strength model.
MILP only proposes lists; the independent listing/semantic checks decide
acceptance. Exhausted solving is unknown, never a negative ability label.
"""
from collections import Counter
import math
import random
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


def solve_candidates(task,assets,base=None,*,max_edits=None,seconds=3.,candidate_count=None):
    from .build_contracts import DeckParts,ZONES
    from .deck_profile import validate_deck_parts
    from .build_pipeline import EXTRA_TYPES
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
    wanted=min(task.candidate_budget,8) if candidate_count is None else integer(candidate_count,'semantic candidates',1,min(task.candidate_budget,8))
    if not seconds:return {'status':'not_found_within_budget','candidates':[],'solver_calls':0,'solver_statuses':[]}
    try:
        import numpy as np
        from scipy.optimize import Bounds,LinearConstraint,milp
    except ImportError as error:raise ContractError('semantic construction requires the pinned CPU scipy extra') from error
    variables=[(z,c) for z in ZONES for c in task.pool
               if z=='side' or bool(assets.rows[c]['type']&EXTRA_TYPES)==(z=='extra')]
    size=len(variables);overlap=size if base is not None and max_edits is not None else 0
    low=np.zeros(size+overlap);high=np.full(size+overlap,3.)
    coefficients=[];lower=[];upper=[]
    def constraint(values,lo,hi):
        row=np.zeros(size+overlap)
        for i,value in values.items():row[i]=value
        coefficients.append(row);lower.append(lo);upper.append(hi)
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
    if overlap:
        for i,(z,c) in enumerate(variables):
            high[size+i]=getattr(base,z).count(c)
            constraint({size+i:1,i:-1},-np.inf,0)
        constraint({size+i:1 for i in range(size)},sum(task.sizes.values())-max_edits,np.inf)
    found=[];statuses=[];started=time.monotonic()
    for variant in range(wanted):
        remaining=seconds-(time.monotonic()-started)
        if remaining<=0:break
        rng=random.Random(variant);objective=np.zeros(size+overlap)
        objective[:size]=[rng.uniform(-1,1) for _ in variables]
        result=milp(objective,integrality=np.r_[np.ones(size),np.zeros(overlap)],bounds=Bounds(low,high),
                    constraints=LinearConstraint(np.array(coefficients),lower,upper),
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
    from .build_contracts import BuildTask
    goal=fields(task.goal.get('route_goal'),{'kind','card_id','starting_conditions'},{'route'})
    if goal['kind'] not in ('synchro_summon','xyz_summon'):
        raise ContractError('combined goal supports explicit conditional synchro/xyz objectives')
    raw=task.to_dict();raw['schema_version']=3;raw['goal']=raw['goal']['route_goal']
    if 'route' in raw['goal']:raise ContractError('combined objective uses core discovery, not a prewritten route')
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
