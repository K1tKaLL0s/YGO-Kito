"""Bounded basic-CB inference from a completed construction, never its constraint.

Public effects/material attributes propose routes. A route-search result is
conditional evidence, not an optimality claim or whole-graph acceptance gate.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from itertools import combinations_with_replacement, zip_longest
import math,re,time

from .build_contracts import BuildTask,digest
from .construction_binding import CardTagAssessment
from .construction_logic import LogicTag
from .effect_mechanisms import MechanismCatalog, SEMANTIC_VERSION
from .validation import ContractError, integer

EXTRA=0x40|0x2000|0x800000|0x4000000


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


def proposals(task,deck,assets,limit=8):
    integer(limit,'basic CB proposal limit',1,8)
    rows=assets.rows;counts=Counter(deck.main);result=[]
    catalog=MechanismCatalog(assets,tuple(set(deck.main+deck.extra)))
    profiles={c:catalog.card(c) for c in counts}
    starters=[c for c,p in profiles.items() if any(o['kind'] in ('mill','send_grave') and
        o.get('from_zones')==('deck',) for e in p.effects for o in e.observed_operations)
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
    groups={kind:[] for kind in ('fusion_summon','synchro_summon','xyz_summon')}
    zones={'deck':1,'deck_bottom':1,'hand':2,'field':4,'grave':16,'graveyard':16,'banished':32}
    mains=list(counts)
    pairs=[(a,b) for a,b in combinations_with_replacement(mains,2)
           if rows[a]['type']&1 and rows[b]['type']&1 and (a!=b or counts[a]>1)]
    for target in dict.fromkeys(deck.extra):
        row=rows[target]
        if row['type']&0x40:
            bucket=groups['fusion_summon']
            for code,profile in profiles.items():
                for effect in profile.effects:
                    if not any(o['kind']=='fusion_summon' for o in effect.operations):continue
                    # Only parsed material instructions establish sources and
                    # destinations; an unknown Fusion clause supplies neither.
                    for op in fusion_material_moves(effect,rows[code]['type']):
                        sources=op.get('from_zones',());destination=zones.get(op.get('to_zone'))
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
        elif row['type']&(0x2000|0x800000):
            kind='xyz_summon' if row['type']&0x800000 else 'synchro_summon'
            bucket=groups[kind]
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
    for alternatives in zip_longest(*groups.values()):
        for proposal in alternatives:
            if proposal is not None:add(*proposal)
            if len(result)>=limit:return result
    return result


def infer_basic_cb(task,deck,assets,*,builder=None,seconds=20.,limit=8,verifier=None,budget=None):
    from .build_pipeline import verify_goal
    from .build_semantics import accepted_status
    from .route_search import conditional_cb_search
    if budget is not None:seconds=min(seconds,budget.check('basic_cb_inference_start'))
    started=time.monotonic()
    before=(task.sha256,digest(deck.to_dict()));assets.validate(task,deck)
    candidates=proposals(task,deck,assets,limit=limit)
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
        families.setdefault(candidate.goal['route_goal']['kind'],[]).append(i)
    order=[i for group in zip_longest(*(sorted(indices,key=lambda i:-scores[i])
           for indices in families.values())) for i in group if i is not None]
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
            if (expanded(proof) and proof.get('status')==accepted_status(candidate) and
                    proof.get('task_sha256')==candidate.sha256 and proof.get('deck_sha256')==before[1]):
                routes.append({'task':candidate.to_dict(),'proof':proof,'assumption':'conditional_own_opening_from_this_deck',
                               'origin':'inferred_after_four_concrete_handoffs'})
                break # One basic route suffices for this bounded inference; no optimality claim.
    if before!=(task.sha256,digest(deck.to_dict())):raise ContractError('Basic CB inference cannot modify construction or its goal')
    completed=bool(routes) or not candidates or any(expanded(a['proof']) for a in attempts)
    return {'schema_version':1,'kind':'basic_cb_inference_after_construction','task_sha256':task.sha256,
        'subject_deck_sha256':before[1],'status':('routes_inferred' if routes else
            'bounded_inference_unknown' if completed else 'not_run'),
        'stop_reason':('route_inferred' if routes else 'no_supported_proposals' if not candidates else
            'bounded_action_exploration' if completed else 'no_action_expansion'),
        'candidate_generation':ranking,'candidate_count':len(candidates),'attempts':attempts,'routes':routes,
        'initial_state_mode':'hypothetical_exact_hand_v1','opening_probability_evaluated':False,
        'public_card_names':{str(code):assets.rows[code]['name'] for code in sorted(set(deck.main+deck.extra+deck.side))
                             if isinstance(assets.rows.get(code,{}).get('name'),str)},
        'construction_modified':False,'preassigned_route_required_by_construction':False,'inference_completed':completed,
        'unknown_is_not_negative':True,'optimal_cb_claimed':False,'whole_graph_execution_required':False,
        'capability_scope':'parsed_effect_material_fusion_and_public_material_synchro_xyz_candidates_with_legal_core_search',
        'unsupported_effects_remain_unknown':True}
