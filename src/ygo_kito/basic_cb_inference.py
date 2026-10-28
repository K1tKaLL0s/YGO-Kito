"""Bounded basic-CB inference from a completed construction, never its constraint.

Public effects/material attributes propose routes. A route-search result is
conditional evidence, not an optimality claim or whole-graph acceptance gate.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import math,time

from .build_contracts import BuildTask,digest
from .construction_effect_blocks import MILL,GRAVE_FUSION,reviewed_effect_blocks
from .validation import ContractError

EXTRA=0x40|0x2000|0x800000|0x4000000


def proposals(task,deck,assets,limit=8):
    rows=assets.rows;counts=Counter(deck.main);result=[]
    _,reviews=reviewed_effect_blocks(assets,tuple(set(deck.main+deck.extra)))
    starters=[r.card_id for r in reviews if r.tag==MILL and r.card_id in counts
              and rows[r.card_id]['type']&1 and not rows[r.card_id]['type']&EXTRA and rows[r.card_id]['level']&255<=4]
    def add(route,effect=None):
        raw=task.to_dict();goal=deepcopy(raw['goal']);goal['route_goal']=route
        if effect is not None:goal.update(required_activations=[effect],required_chain_resolutions=[effect])
        # Only the derived inference task binds the already-present route cards.
        # The construction task has no fixed CB component requirement.
        needed=Counter(route['starting_conditions']['requires_opening_hand'])
        needed[route['card_id']]=max(1,needed[route['card_id']])
        if effect is not None:needed[effect]=max(1,needed[effect])
        requirements={(r['zone'],r['card_id']):r for r in raw['requirements']}
        for code,minimum in needed.items():
            zone='extra' if rows[code]['type']&EXTRA else 'main'
            key=(zone,code)
            if key in requirements:requirements[key]['minimum']=max(minimum,requirements[key]['minimum'])
            else:requirements[key]={'zone':zone,'card_id':code,'minimum':minimum,'maximum':3}
        raw['requirements']=list(requirements.values())
        raw.update(task_id='basic-cb-'+digest({'construction':task.sha256,'route':route,'effect':effect})[:24],goal=goal)
        candidate=BuildTask.from_dict(raw)
        if candidate not in result:result.append(candidate)
    for target in dict.fromkeys(deck.extra):
        row=rows[target]
        if row['type']&0x40:
            for effect in (r for r in reviews if r.tag==GRAVE_FUSION and r.card_id in counts):
                assessment=asdict(effect);assessment['tag']={'dimension':'effect_type','value':'fusion_summon'}
                for starter in dict.fromkeys(starters):
                    add({'kind':'fusion_summon','card_id':target,
                        'starting_conditions':{'player':0,'turn':1,'requires_opening_hand':[starter]},
                        'fusion_witness':{'minimum_materials':2,'required_source_zones':[16],'allowed_destination_zones':[1],
                                          'effect_assessments':[assessment]}},effect.card_id)
                    if len(result)>=limit:return result
        elif row['type']&(0x2000|0x800000):
            mains=list(counts)
            for a in mains:
                for b in mains:
                    if a==b and counts[a]<2:continue
                    if row['type']&0x800000:
                        suitable=(rows[a]['level']&255)==(rows[b]['level']&255)==(row['level']&255)
                    else:
                        suitable=bool(rows[a]['type']&0x1000) and not rows[b]['type']&0x1000 and (rows[a]['level']&255)+(rows[b]['level']&255)==(row['level']&255)
                    if suitable:
                        add({'kind':'xyz_summon' if row['type']&0x800000 else 'synchro_summon','card_id':target,
                             'starting_conditions':{'player':0,'turn':1,'requires_opening_hand':[a,b]}})
                        break
                if len(result)>=limit:return result
    return result


def infer_basic_cb(task,deck,assets,*,builder=None,seconds=20.,limit=8,verifier=None,budget=None):
    from .build_pipeline import verify_goal
    from .build_semantics import accepted_status
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
    attempts=[];routes=[];verify=verifier or verify_goal
    for i in sorted(range(len(candidates)),key=lambda i:-scores[i]):
        remaining=seconds-(time.monotonic()-started)
        if budget is not None:remaining=min(remaining,budget.check('before_basic_cb_route'))
        if remaining<=0:break
        candidate=candidates[i]
        proof=verify(candidate,deck,assets,seconds=min(10.,remaining),attempts=16,decision_budget=100)
        if budget is not None:budget.check('after_basic_cb_route')
        attempts.append({'task':candidate.to_dict(),'task_sha256':candidate.sha256,'model_score_uncalibrated':scores[i],
                         'proof':proof,'unknown_used_as_negative_label':False})
        if proof.get('status')==accepted_status(candidate) and proof.get('task_sha256')==candidate.sha256 and proof.get('deck_sha256')==before[1]:
            routes.append({'task':candidate.to_dict(),'proof':proof,'assumption':'conditional_own_opening_from_this_deck',
                           'origin':'inferred_after_four_concrete_handoffs'})
            break # One basic route suffices for this bounded inference; no optimality claim.
    if before!=(task.sha256,digest(deck.to_dict())):raise ContractError('Basic CB inference cannot modify construction or its goal')
    return {'schema_version':1,'kind':'basic_cb_inference_after_construction','task_sha256':task.sha256,
        'subject_deck_sha256':before[1],'status':'routes_inferred' if routes else 'bounded_inference_unknown',
        'candidate_generation':ranking,'candidate_count':len(candidates),'attempts':attempts,'routes':routes,
        'construction_modified':False,'preassigned_route_required_by_construction':False,'inference_completed':True,
        'unknown_is_not_negative':True,'optimal_cb_claimed':False,'whole_graph_execution_required':False,
        'capability_scope':'reviewed_effect_fusion_and_public_material_synchro_xyz_candidates_with_legal_core_search',
        'unsupported_effects_remain_unknown':True}
