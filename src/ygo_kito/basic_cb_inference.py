"""Bounded basic-CB inference from a completed construction, never its constraint.

Public effects/material attributes propose routes. A route-search result is
conditional evidence, not an optimality claim or whole-graph acceptance gate.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from itertools import combinations_with_replacement, zip_longest
import math,re,time

from .build_contracts import BuildTask, EXTRA_ROUTE_GOALS, SUMMON_ROUTE_TYPES, digest
from .construction_binding import CardTagAssessment
from .construction_logic import LogicTag
from .effect_mechanisms import MechanismCatalog, SEMANTIC_VERSION
from .validation import ContractError, integer

EXTRA=0x40|0x2000|0x800000|0x4000000

# Symbolic routes precede concrete card binding. Conditions/materials are
# filled from the candidate; only the native result makes a route scoreable.
BLOCK_ROUTES = {
    'fusion_summon': ('fusion_access', 'extra_fusion'),
    'synchro_summon': ('body', 'extra_synchro'),
    'xyz_summon': ('body', 'extra_xyz'),
    'link_summon': ('body', 'extra_link'),
    'ritual_summon': ('ritual_access', 'ritual_summon'),
    'effect_resolution': ('effect_draw', 'effect_mill'),
}


def route_blocks(route):
    if route['kind'] == 'effect_resolution':
        return ['effect_' + route['effect_objective']['kind']]
    blocks=list(BLOCK_ROUTES[route['kind']])
    if 16 in route.get('fusion_witness',{}).get('required_source_zones',()):
        blocks=['targeted_send','grave_fusion','extra_fusion']
    return blocks


def fusion_material_moves(effect,card_type):
    """Material movements explicitly parsed in this particular effect.

    Also recognize the bounded generic hand/field material sentence on a
    Fusion spell, whose spell activation need not have a numbered trigger.
    A generic mention of Fusion Summon alone still supplies no witness.
    """
    moves=[o for o in effect.observed_operations
           if o['kind'] in ('return_fusion_materials','fusion_materials')]
    if moves or not card_type&2:return moves
    if not any(o['kind']=='fusion_summon' for o in effect.operations):return moves
    match=re.search(r'(?:\u4ece|\u5c06|\u628a)\u81ea\u5df1(?:\u7684)?'
        r'(?P<zones>\u624b\u5361(?:[\u00b7\u30fb\u3001\u548c\u53ca/]+\u573a\u4e0a)?|'
        r'\u573a\u4e0a(?:[\u00b7\u30fb\u3001\u548c\u53ca/]+\u624b\u5361)?)'
        r'(?:\u5c06|\u628a)?(?:\u878d\u5408\u602a\u517d\u5361\u51b3\u5b9a\u7684)?'
        r'\u878d\u5408\u7d20\u6750\u602a\u517d\u9001\u53bb\u5893\u5730',effect.text)
    if match and not re.search(r'\u4e0d\u80fd|\u65e0\u6cd5|\u4e0d\u53ef',effect.text[:match.start()]):
        sources=tuple(z for word,z in (('\u624b\u5361','hand'),('\u573a\u4e0a','field')) if word in match['zones'])
        moves.append(dict(kind='fusion_materials',from_zones=sources,to_zone='grave',source=match[0]))
    return moves


def inference_requirements(task,deck,goal):
    """Bind only an inferred route's already-present cards, preserving the task."""
    route=goal.get('route_goal')
    if not isinstance(route,dict):raise ContractError('basic CB requires its derived route goal')
    counts={zone:Counter(getattr(deck,zone)) for zone in ('main','extra','side')}
    needed={('main',code):n for code,n in Counter(route['starting_conditions']['requires_opening_hand']).items()}
    for code in (route['card_id'],*goal.get('required_activations',()),*goal.get('required_chain_resolutions',())):
        zones=[zone for zone in ('main','extra') if counts[zone][code]]
        if len(zones)!=1:raise ContractError('basic CB route card must belong to its constructed main or extra deck')
        key=(zones[0],code);needed[key]=max(1,needed.get(key,0))
    requirements={(r['zone'],r['card_id']):r for r in task.to_dict()['requirements']}
    for (zone,code),minimum in needed.items():
        key=(zone,code)
        if key in requirements:requirements[key]['minimum']=max(minimum,requirements[key]['minimum'])
        else:requirements[key]={'zone':zone,'card_id':code,'minimum':minimum,'maximum':3}
    if any(not r['minimum']<=counts[r['zone']][r['card_id']]<=r['maximum'] for r in requirements.values()):
        raise ContractError('basic CB derived requirements are not satisfied by its constructed deck')
    return list(requirements.values())


def _starting(cards):
    return {'player': 0, 'turn': 1, 'requires_opening_hand': list(cards)}


def _ritual_openings(record, counts, rows, inventory):
    from .construction_inventory import matches, selector, query_supported
    from .effect_records import operation_record
    from .effect_text import RITUAL_MATERIAL_RELEASE

    for operation in record['operations']:
        if operation['kind'] != 'ritual_summon' or operation.get('reason') != 'effect' or operation.get('from_zones') != ['hand']:
            continue
        scoped = operation_record(record, operation)
        if scoped['conditions']['status'] != 'recognized':
            continue
        exact = re.fullmatch(r'从手卡把(?:1只)?(「[^」]+」(?:仪式怪兽)?)仪式召唤', operation['source'])
        query = operation.get('selector_query') or (selector(exact[1]) if exact else None)
        payments = [RITUAL_MATERIAL_RELEASE.fullmatch(op['source']) for op in scoped['operations']
                    if op['kind'] == 'release']
        if not query_supported(query) or len(payments) != 1 or payments[0] is None:
            continue
        required, at_least = int(payments[0][1]), bool(payments[0][2])
        for target in counts:
            if not rows[target]['type'] & SUMMON_ROUTE_TYPES['ritual_summon'] or not matches(rows[target], query):
                continue
            eligible, _ = inventory.candidate_status(target, dict(category='operations', operation=operation))
            if eligible is not True:
                continue
            initial = (record['card_id'], target)
            stock = counts - Counter(initial)
            materials = [c for c in stock if rows[c]['type'] & 1 and 0 < (rows[c]['level'] & 255)]
            for size in (1, 2, 3):
                for cards in combinations_with_replacement(materials, size):
                    if Counter(cards) - stock:
                        continue
                    levels = [rows[c]['level'] & 255 for c in cards]
                    total = sum(levels)
                    if total == required or at_least and total >= required and total - min(levels) < required:
                        yield target, (*initial, *cards)


def _effect_objectives(record, deck, rows):
    from .effect_records import operation_record

    for op in record['operations']:
        kind, count = op['kind'], op.get('quantity')
        if (op.get('reason') != 'effect' or op.get('phase') != 'resolution' or op.get('owner') != 'self'
                or op.get('optional') or kind not in ('draw', 'mill', 'send_grave') or type(count) is not int
                or not 1 <= count <= 30):
            continue
        if kind != 'draw' and (op.get('from_zones') != ['deck'] or op.get('to_zone') != 'grave' or op.get('random') is not True):
            continue
        scoped = operation_record(record, op)
        if scoped['conditions']['status'] != 'recognized' or not rows[record['card_id']]['type'] & 2:
            continue
        costs = scoped['costs']
        if any(not (cost['kind'] == 'pay_lp' and type(cost.get('quantity')) is int and 0 < cost['quantity'] < 8000
                    or cost['kind'] == 'banish' and cost.get('from_zones') == ['extra']
                    and (cost.get('selector_query') or {}).keys() <= {'selector', 'face_up'}
                    and type(cost.get('quantity')) is int and 0 < cost['quantity'] <= len(deck.extra)) for cost in costs):
            continue
        if count < len(deck.main):
            yield dict(kind='draw' if kind == 'draw' else 'mill', effect_index=record['effect_index'], minimum=count)


def static_route_support(route, deck, catalog, *, required_effects=()):
    """Static configuration support for the newly expressed objective kinds."""
    from .construction_inventory import InventoryDependencies, matches, printed_link_material
    rows, target, kind = catalog.assets.rows, route['card_id'], route['kind']
    opening = Counter(route['starting_conditions']['requires_opening_hand'])
    if opening - Counter(deck.main) or target not in deck.main + deck.extra:
        return False
    inventory = InventoryDependencies(catalog)
    if kind == 'effect_resolution':
        if set(required_effects) - {target}:
            return None
        objective = route['effect_objective']
        for record in catalog.effect_records(target):
            for observed in _effect_objectives(record, deck, rows):
                if (observed['effect_index'] == objective['effect_index'] and observed['kind'] == objective['kind']
                        and observed['minimum'] >= objective['minimum']):
                    return True
    elif kind == 'link_summon':
        if required_effects:
            return None
        clause = printed_link_material(rows[target])
        if clause is None:
            return None
        if sum(opening.values()) != clause['rating'] or (clause['exact'] and clause['minimum'] != clause['rating']):
            return None
        if clause['normal_summoned'] and sum(opening.values()) != 1:
            return None
        if all(matches(rows[c], clause['query']) and inventory.candidate_status(c,
                dict(category='material', origin='field', summon_type='link'), target=target)[0] is True for c in opening):
            return True
    elif kind == 'ritual_summon':
        for code in opening:
            for record in catalog.effect_records(code):
                for found, cards in _ritual_openings(record, Counter(deck.main), rows, inventory):
                    if found == target and not Counter(cards) - opening and not set(required_effects) - {code}:
                        return True
    return None


def proposals(task,deck,assets,limit=8):
    integer(limit,'basic CB proposal limit',1,8)
    rows=assets.rows;counts=Counter(deck.main);result=[]
    catalog=MechanismCatalog(assets,tuple(set(deck.main+deck.extra)))
    profiles={c:catalog.card(c) for c in counts}
    starters=[c for c,p in profiles.items() if any(o['kind'] in ('mill','send_grave') and
        o.get('from_zones')==('deck',) and o.get('random') is False for e in p.effects for o in e.observed_operations)
        and rows[c]['type']&1 and not rows[c]['type']&EXTRA and rows[c]['level']&255<=4]
    def add(route,effect=None):
        if len(result)>=limit:return
        raw=task.to_dict();goal=deepcopy(raw['goal']);goal['route_goal']=route
        if effect is not None:
            for key in ('required_activations','required_chain_resolutions'):
                goal[key]=list(dict.fromkeys((*goal.get(key,()),effect)))
        # Only the derived inference task binds the already-present route cards.
        # The construction task has no fixed CB component requirement.
        raw['requirements']=inference_requirements(task,deck,goal)
        raw.update(task_id='basic-cb-'+digest({'construction':task.sha256,'route':route,'effect':effect})[:24],goal=goal)
        candidate=BuildTask.from_dict(raw)
        if candidate not in result:result.append(candidate)
    # An explicit construction objective is authoritative. Verify that same
    # route and its activation requirements instead of replacing its meaning.
    if isinstance(task.goal.get('route_goal'),dict):
        add(deepcopy(task.goal['route_goal']))
        return result
    groups={}
    from .construction_inventory import InventoryDependencies, matches, printed_link_material
    inventory = InventoryDependencies(catalog)
    zones={'deck':1,'deck_bottom':1,'hand':2,'field':4,'grave':16,'graveyard':16,'banished':32}
    mains=list(counts)
    pairs=[(a,b) for a,b in combinations_with_replacement(mains,2)
           if rows[a]['type']&1 and rows[b]['type']&1 and (a!=b or counts[a]>1)]
    # Bind each symbolic route to the candidate's matching extra-deck targets.
    # A target has its own quota: alternative sources for one expensive Fusion
    # must not exhaust every proposal before a shorter Fusion is considered.
    for kind,target in ((kind,target) for kind in EXTRA_ROUTE_GOALS
                        for target in dict.fromkeys(deck.extra) if rows[target]['type'] & SUMMON_ROUTE_TYPES[kind]):
        row=rows[target]
        bucket=groups.setdefault((kind,target),[])
        if kind=='fusion_summon':
            for code,profile in profiles.items():
                for effect in profile.effects:
                    if not any(o['kind']=='fusion_summon' for o in effect.operations):continue
                    # Only parsed material instructions establish sources and
                    # destinations; an unknown Fusion clause supplies neither.
                    for op in fusion_material_moves(effect,rows[code]['type']):
                        sources=op.get('from_zones',());destination=zones.get(op.get('to_zone'))
                        # An explicit self-in-grave material clause establishes
                        # the required source. Hand/field are optional other
                        # materials, not separate mandatory prerequisites.
                        if (effect.trigger.get('event')=='sent_to_grave' and
                                re.search(r'(?:包含|包括)墓地的这张卡',effect.text)):
                            sources=tuple(z for z in sources if z in ('grave','graveyard'))
                        if not sources or any(z not in zones for z in sources) or destination is None:continue
                        assessment=asdict(CardTagAssessment(code,LogicTag('effect_type','fusion_summon'),'satisfied',
                            profile.cards_sha256,profile.text_sha256,effect.text[:512],SEMANTIC_VERSION,
                            'Parsed material instruction in effect '+str(effect.index)+'; legality requires core execution.'))
                        openings=([s] for s in starters) if effect.trigger.get('event')=='sent_to_grave' else (
                            list((Counter((a,b))|Counter((code,))).elements()) for a,b in pairs)
                        for opening in openings:
                            if any(n>counts[c] for c,n in Counter(opening).items()):continue
                            # Each permitted source gets a bounded chance; the
                            # core decides which material combination is legal.
                            for source in sources:
                                if len(bucket)>=limit:break
                                bucket.append(({'kind':'fusion_summon','card_id':target,
                                    'starting_conditions':{'player':0,'turn':1,'requires_opening_hand':opening},
                                    'fusion_witness':{'minimum_materials':2,'required_source_zones':[zones[source]],
                                        'allowed_destination_zones':[destination],'effect_assessments':[assessment]}},code))
                            if len(bucket)>=limit:break
        elif kind == 'link_summon':
            clause = printed_link_material(row)
            if clause is None or not clause['minimum'] <= clause['rating'] <= 5:
                continue
            count = clause['rating']  # This opening branch uses Main Deck bodies, each worth one material.
            if clause['exact'] and count != clause['minimum'] or clause['normal_summoned'] and count != 1:
                continue
            materials = [c for c in mains if matches(rows[c], clause['query']) and inventory.candidate_status(c,
                dict(category='material', origin='field', summon_type='link'), target=target)[0] is True]
            if sum(counts[c] for c in materials) < count:
                continue
            for cards in combinations_with_replacement(materials, count):
                if not Counter(cards) - counts:
                    bucket.append((dict(kind=kind, card_id=target, starting_conditions=_starting(cards)), None))
                    if len(bucket) == limit:
                        break
        else:
            for a in mains:
                for b in mains:
                    if not rows[a]['type']&1 or not rows[b]['type']&1:continue
                    if a==b and counts[a]<2:continue
                    if row['type']&0x800000:
                        suitable=(rows[a]['level']&255)==(rows[b]['level']&255)==(row['level']&255)
                    else:
                        suitable=bool(rows[a]['type']&0x1000) and not rows[b]['type']&0x1000 and (rows[a]['level']&255)+(rows[b]['level']&255)==(row['level']&255)
                    if suitable:
                        if len(bucket)<limit:bucket.append(({'kind':kind,'card_id':target,
                             'starting_conditions':{'player':0,'turn':1,'requires_opening_hand':[a,b]}},None))
                        break
                if len(bucket)>=limit:break
    for code in mains:
        for record in catalog.effect_records(code):
            for target, opening in _ritual_openings(record, counts, rows, inventory):
                bucket = groups.setdefault(('ritual_summon', target), [])
                if len(bucket) == limit:
                    break
                bucket.append((dict(kind='ritual_summon', card_id=target, starting_conditions=_starting(opening)), code))
            for objective in _effect_objectives(record, deck, rows):
                bucket = groups.setdefault(('effect_resolution', code), [])
                if len(bucket) == limit:
                    break
                bucket.append((dict(kind='effect_resolution', card_id=code, starting_conditions=_starting((code,)),
                                    effect_objective=objective), None))
    for alternatives in zip_longest(*groups.values()):
        for proposal in alternatives:
            if proposal is not None:add(*proposal)
            if len(result)>=limit:return result
    return result


def infer_basic_cb(task,deck,assets,*,builder=None,seconds=20.,limit=8,verifier=None,budget=None,scoring_theme=None,
                   construction_gate=None, execution_authorized=False):
    from .construction_progress import GATE_VERSION, FUNCTIONAL_GATE_VERSION
    if (execution_authorized is not True or not isinstance(construction_gate,dict)
            or construction_gate.get('version') not in (GATE_VERSION, FUNCTIONAL_GATE_VERSION) or construction_gate.get('status') != 'passed'
            or construction_gate.get('task_sha256') != task.sha256
            or type(construction_gate.get('candidate_version')) is not int or construction_gate['candidate_version'] < 1
            or construction_gate.get('deck_sha256') != digest(deck.to_dict())):
        return dict(kind='basic_cb_inference_after_construction', status='not_run', routes=[],
            task_sha256=task.sha256, subject_deck_sha256=digest(deck.to_dict()), inference_completed=False,
            stop_reason='construction_pass_and_execution_authorization_required')
    from .build_pipeline import verify_goal
    from .build_semantics import accepted_status
    from .route_search import conditional_cb_search
    if budget is not None:seconds=min(seconds,budget.check('basic_cb_inference_start'))
    before=(task.sha256,digest(deck.to_dict()));assets.validate(task,deck)
    candidates=proposals(task,deck,assets,limit=limit)
    from .cb_effect_points import route_effect_points
    theme=scoring_theme or 'material_summon'
    points=route_effect_points(theme)
    scores=[0.]*len(candidates);ranking='bounded_public_effect_material_proposals'
    if builder is not None and candidates:
        import torch
        model=builder.models['build_goal'];mode=model.training;model.eval()
        try:
            with torch.no_grad():scores=[float(model(builder.encoder.batch(c,[deck])).item()) for c in candidates]
        finally:model.train(mode)
        if any(not math.isfinite(n) for n in scores):raise ContractError('Non-finite basic CB search ordering')
        ranking='existing_goal_model_search_order_uncalibrated_not_quality'
    def expanded(proof):
        native=proof.get('native_route',proof)
        if native.get('status')=='not_run' or native.get('search_started') is False:return False
        exploration=native.get('exploration',native.get('route_evidence',{}).get('exploration',{}))
        if 'nodes_expanded' in exploration:return exploration['nodes_expanded']>0
        return bool(native.get('responses'))  # legacy receipts need actual decisions
    attempts=[];routes=[];verify=verifier or verify_goal
    families={}
    for i,candidate in enumerate(candidates):
        route=candidate.goal['route_goal']
        families.setdefault((route['kind'],route['card_id']),[]).append(i)
    order=[i for group in zip_longest(*(sorted(indices,key=lambda i:-scores[i])
           for indices in families.values())) for i in group if i is not None]
    # Setup, including a cold torch import, is not action exploration time.
    started=time.monotonic()
    with conditional_cb_search():
        for i in order:
            remaining=seconds-(time.monotonic()-started)
            if budget is not None:remaining=min(remaining,budget.check('before_basic_cb_route'))
            if remaining<=0:break
            candidate=candidates[i]
            # Allow native startup and action exploration within the original
            # inference deadline; later interleaved proposals may remain untried.
            proof=verify(candidate,deck,assets,seconds=min(10.,remaining),attempts=16,decision_budget=100)
            if budget is not None:budget.check('after_basic_cb_route')
            attempts.append({'task':candidate.to_dict(),'task_sha256':candidate.sha256,'model_score_uncalibrated':scores[i],
                             'proof':proof,'unknown_used_as_negative_label':False})
            from .basic_cb_scope import VERSION
            scope = proof.get('native_route',proof).get('route_evidence',{}).get('basic_cb_scope',{})
            if (expanded(proof) and scope.get('version') == VERSION and not scope.get('unknown', [])
                    and scope.get('random_result_branches_expanded') is False
                    and proof.get('status')==accepted_status(candidate) and
                    proof.get('task_sha256')==candidate.sha256 and proof.get('deck_sha256')==before[1]):
                blocks=route_blocks(candidate.goal['route_goal'])
                breakdown=[{'kind':kind,'base':1.,'theme_adjustment':points[kind]-1.,
                            'points':points[kind]} for kind in blocks]
                routes.append({'task':candidate.to_dict(),'proof':proof,
                               'effect_blocks':blocks,'score':sum(b['points'] for b in breakdown),
                               'score_breakdown':breakdown,'score_after_legality':True,
                               'assumption':'conditional_own_opening_from_this_deck',
                               'mainline':deepcopy(scope),
                               'origin':'inferred_after_construction_gate'})
                break # One basic route suffices for this bounded inference; no optimality claim.
    if before!=(task.sha256,digest(deck.to_dict())):raise ContractError('Basic CB inference cannot modify construction or its goal')
    searched = any(expanded(attempt['proof']) for attempt in attempts)
    completed=bool(routes) or (searched and len(attempts)==len(candidates) and
        all(a['proof'].get('native_route',a['proof']).get('normal_completion') is True for a in attempts))
    from .basic_cb_scope import VERSION
    return {'schema_version':2,'scope_version':VERSION,'kind':'basic_cb_inference_after_construction','task_sha256':task.sha256,
        'construction_gate':deepcopy(construction_gate), 'execution_authorized':True,
        'candidate_version':construction_gate['candidate_version'],
        'subject_deck_sha256':before[1],'status':('routes_inferred' if routes else
            'no_route_found' if completed else 'bounded_inference_unknown' if searched else 'not_run'),
        'stop_reason':('route_inferred' if routes else 'no_supported_proposals' if not candidates else
            'completed_without_route' if completed else 'incomplete_route_search' if searched else 'no_action_expansion'),
        'candidate_generation':ranking,'candidate_count':len(candidates),'attempts':attempts,'routes':routes,
        'symbolic_route_templates':dict(BLOCK_ROUTES),'scoring_theme':theme,
        'initial_state_mode':'hypothetical_exact_hand_v1','opening_probability_evaluated':False,
        'public_card_names':{str(code):assets.rows[code]['name'] for code in sorted(set(deck.main+deck.extra+deck.side))
                             if isinstance(assets.rows.get(code,{}).get('name'),str)},
        'construction_modified':False,'preassigned_route_required_by_construction':False,'inference_completed':completed,
        'normal_completion':completed, 'failure_count_eligible':bool(completed and not routes),
        'unknown_is_not_negative':True,'optimal_cb_claimed':False,'whole_graph_execution_required':False,
        'capability_scope':'printed_summon_and_observable_effect_objectives_with_legal_core_search',
        'unsupported_effects_remain_unknown':True}
