"""Read-only, source-bound auxiliary evaluation of closed actual model games.

No model update, engine run, reference deck, ATK ranking or field-count reward.
"""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import hashlib,json,sqlite3,sys
from pathlib import Path

VERSION='actual-declared-goal-auxiliary-v1.1'
SOURCE='actual_public_engine_paired_auxiliary_v1_1'
METRICS=('terminal_goal_attained','declared_effect_requirements_satisfied','first_actor_turn_goal_attained')
canon=lambda v:json.dumps(v,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':'))
digest=lambda v:hashlib.sha256(canon(v).encode()).hexdigest()
read=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))


def auxiliary_capability(task):
    """Classify the declared objective without inventing a ranking metric."""
    goal=task['goal'];kind=goal.get('route_goal',goal).get('kind')
    supported=kind in ('fusion_summon','normal_summon')
    return {'goal_kind':kind,'supported':supported,
        'status':'requires_registered_policy' if supported else 'not_applicable',
        'reason':('declared_proper_summon_objective' if supported else
                  'declared_auxiliary_objective_absent' if kind=='deck_constraints' else
                  'unsupported_declared_goal')}


def request_sha(value):
    value=deepcopy(value);value['context']['run_id']='native-smoke'
    return digest(value)


def align_observations(trace,episode,actor):
    """Link authentic serialized actor DTOs to exact replay response prefixes."""
    events=trace['events'];responses=trace['responses']
    prompts=[i for i,e in enumerate(events) if 10<=e['kind']<=26 and e['kind']!=17]
    if len(prompts)!=len(responses):raise ValueError('Public prompt/response coverage is incomplete')
    positions={}
    for event_index,response in zip(prompts,responses):
        event=events[event_index]
        if event.get('player')!=response['player']:raise ValueError('Prompt player and recorded response differ')
        if response['player']==actor:
            if response['request_sha256'] in positions:raise ValueError('Ambiguous repeated request fingerprint')
            positions[response['request_sha256']]=event_index
    frames=[]
    for step in episode['steps']:
        request=step['request'];identity=request_sha(request)
        if identity not in positions or request['observation']['observer']!=actor:
            raise ValueError('A stored actor observation is not linked to its native replay')
        index=positions.pop(identity)
        if events[index]['kind']!=request['prompt']['message']:
            raise ValueError('Stored DTO prompt differs from replay event')
        frames.append((index,request['observation'],identity))
    if positions:raise ValueError('Some actor responses have no stored legal observation')
    frames.sort(key=lambda row:row[0])
    frames.append((len(events)-1,trace['final_observations'][actor],None))
    return frames


def negation_evidence(events,actor):
    """Only an opponent's actively resolving link can attribute interruption."""
    links={};resolving=None;rows=[]
    for i,e in enumerate(events):
        if e['kind']==70:links[e['link']]=(e['player'],e.get('public_card'),i)
        elif e['kind']==72:resolving=e['link']
        elif e['kind'] in (75,76):
            own=links.get(e['link']);cause=links.get(resolving)
            if own and cause and own[0]==actor and cause[0]!=actor:
                rows.append({'event_index':i,'own_link':e['link'],'own_public_card':own[1],
                    'opponent_resolving_link':resolving,'opponent_public_card':cause[1]})
        elif e['kind']==73 and e['link']==resolving:resolving=None
        elif e['kind']==74:links.clear();resolving=None
    return rows


def evaluate_game(task,trace,episode,actor):
    from .contracts import Observation
    from .extra_routes import completed_fusion_summon
    from .route_search import resolved_chain_cards
    events=trace['events'];goal=task['goal'];route=goal.get('route_goal',goal)
    target=route.get('card_id');kind=route.get('kind')
    frames=align_observations(trace,episode,actor)
    if not auxiliary_capability(task)['supported']:
        return {'status':'unsupported_proper_summon_witness','metrics':{k:None for k in METRICS},'goal_kind':kind}
    relevant_kind=62 if kind=='fusion_summon' else 60
    starts=[i for i,e in enumerate(events) if e['kind']==relevant_kind and e.get('player')==actor
            and e.get('public_summoning_card')==target]
    own_turn=next((i for i,e in enumerate(events) if e['kind']==40 and e['player']==actor),None)
    cutoff=next((i for i in range((own_turn or 0)+1,len(events)) if own_turn is not None and events[i]['kind']==40),len(events)-1)
    hits=[]
    for index,raw_observation,identity in frames:
        if not any(c['controller']==actor and c['zone']=='monster' and c['card_id']==target
                   and c['visibility']=='public' for c in raw_observation['cards']):continue
        observation=Observation.from_dict(raw_observation)
        if not any(c.controller==actor and c.zone=='monster' and c.card_id==target and c.visibility=='public' for c in observation.cards):continue
        prefix=events[:index+1]
        if kind=='fusion_summon':
            proof=completed_fusion_summon(prefix,observation,actor,target,route['fusion_witness'])
        else:
            start=next((i for i in reversed(starts) if i<index),None)
            end=next((i for i in range((start or 0)+1,index+1) if events[i]['kind']==61),None) if start is not None else None
            if end is not None and any(e['kind'] in (60,62) for e in events[start+1:end]):end=None
            proof=None if end is None else {'kind':'public-normal-summon-complete','summon_start_event_index':start,'summon_complete_event_index':end}
        if proof is None:continue
        activated={e['public_card'] for e in prefix if e['kind']==70 and e.get('player')==actor}
        resolved=resolved_chain_cards(prefix,actor)
        sequence=(set(goal.get('required_activations',()))<=activated and set(goal.get('required_chain_resolutions',()))<=resolved)
        completed=max(proof['summon_complete_event_index'],proof.get('chain_solved_event_index',0))
        hits.append({'observation_event_index':index,'goal_completion_event_index':completed,
                     'request_sha256':identity,'proof':proof,'declared_effect_requirements_satisfied':sequence})
    # Absence of any target summon in a complete replay is a verified miss.
    # A target attempt without a linked public-state witness remains unknown.
    terminal=1 if hits else None if starts else 0
    early_hits=[h for h in hits if h['goal_completion_event_index']<=cutoff]
    early_starts=[i for i in starts if i<=cutoff]
    early=1 if early_hits else None if early_starts else 0
    sequence=1 if any(h['declared_effect_requirements_satisfied'] for h in hits) else None if starts and not hits else 0
    disruptions=negation_evidence(events,actor)
    recovery=[]
    for interruption in disruptions:
        later=[h for h in hits if h['goal_completion_event_index']>interruption['event_index']]
        if later:
            hit=min(later,key=lambda h:h['goal_completion_event_index'])
            recovery.append({'interruption':interruption,'goal_completion_event_index':hit['goal_completion_event_index'],
                             'goal_observation_event_index':hit['observation_event_index']})
    first_hit=min(h['goal_completion_event_index'] for h in hits) if hits else None
    costs=[{'event_index':i,'from_zone':e.get('from_zone'),'to_zone':e.get('to_zone'),'reason':e['reason']}
           for i,e in enumerate(events) if first_hit is not None and i<=first_hit and e['kind']==50
           and e.get('player')==actor and e.get('reason',0)&0x80]
    return {'status':'measured_from_linked_actual_public_dtos','metrics':dict(zip(METRICS,(terminal,sequence,early))),
        'actor_observation_frames':len(frames),'natural_opening_condition_verified':None,
        'conditional_full_route_goal_verified':False,'terminal_subgoal_only':True,'goal_witnesses':hits,
        'first_actor_turn_started':own_turn is not None,'first_actor_turn_cutoff_event':cutoff,
        'opponent_attributed_chain_negations':disruptions,'verified_goal_recovery_after_negation':recovery,
        'undeclared_fallback_goal':'not_defined_not_scored',
        'resource_cost_events_to_goal':costs,'resource_recovery_accounting':'not_complete_collection_only',
        'resource_quality_preference_used':False,'whole_graph_execution_verified':False}


def auxiliary_preference(rows,plan):
    expected={(i,s,p) for i in (0,1) for s in plan['paired_seeds_audit_only'] for p in (0,1)}
    lookup={(r['candidate_index'],r['seed_audit_only'],r['actor_seat']):r for r in rows}
    if set(lookup)!=expected:return None,'incomplete_comparison'
    keys=[(s,p) for s in plan['paired_seeds_audit_only'] for p in (0,1)]
    if any(lookup[0,s,p]['score']!=lookup[1,s,p]['score'] for s,p in keys):return None,'primary_outcomes_not_matchwise_tied_use_original_win_evaluation'
    if any(r['auxiliary']['metrics'][m] is None for r in rows for m in METRICS):return None,'unknown_auxiliary_coverage_not_negative'
    for better in (0,1):
        support=set();dominates=True
        for seed,seat in keys:
            a=lookup[better,seed,seat]['auxiliary']['metrics'];b=lookup[1-better,seed,seat]['auxiliary']['metrics']
            if any(a[m]<b[m] for m in METRICS):dominates=False;break
            if any(a[m]>b[m] for m in METRICS):support.add(seed)
        if dominates and len(support)>=2:return better,'paired_declared_goal_auxiliary_pareto_only'
    return None,'no_strict_supported_auxiliary_dominance'


def prerequisites(task):
    route=task['goal'].get('route_goal',{})
    witness=route.get('fusion_witness',{})
    return tuple((r['card_id'],z) for r in witness.get('effect_assessments',())
                 for z in witness.get('required_source_zones',()))

def benefits(task,events,actor):
    required=set(task['goal'].get('required_chain_resolutions',()))
    requested=set(prerequisites(task));links={};blocked=set();pending={};resolving=None;found=[]
    for index,event in enumerate(events):
        kind=event['kind']
        if kind==70:links[event['link']]=(event['player'],event.get('public_card'),index)
        elif kind==72:resolving=event['link']
        elif kind in (75,76):blocked.add(event['link'])
        elif kind==50 and resolving in links:
            player,card,start=links[resolving]
            if (player==actor and card in required and event.get('player')==actor
                    and (event.get('public_card'),event.get('to_zone')) in requested
                    and event.get('reason',0)&0x40):
                pending.setdefault(resolving,[]).append({'move_event_index':index,'move':event,
                    'resolving_link':resolving,'required_effect_card':card,'chaining_event_index':start})
        elif kind==73:
            if event['link'] not in blocked:
                for row in pending.pop(event['link'],[]):found.append(dict(row,solved_event_index=index))
            if resolving==event['link']:resolving=None
        elif kind==74:links.clear();blocked.clear();pending.clear();resolving=None
    return found,bool(required)


import base64,zlib
from .validation import ContractError,fields

SOURCE_V2='actual_public_engine_paired_auxiliary_v2'
SOURCES=(SOURCE,SOURCE_V2)
MAX_REQUEST_JSON_BYTES=256*1024*1024

def pack_requests(episode):
    requests=[s['request'] for s in episode['steps']]
    raw=canon(requests).encode()
    if len(raw)>MAX_REQUEST_JSON_BYTES:raise ContractError('Auxiliary observation proof exceeds its bound')
    return {'codec':'zlib-json-v1','raw_bytes':len(raw),'raw_sha256':hashlib.sha256(raw).hexdigest(),
            'payload_b64':base64.b64encode(zlib.compress(raw,6)).decode()}

def unpack_requests(proof):
    fields(proof,{'codec','raw_bytes','raw_sha256','payload_b64'})
    if proof['codec']!='zlib-json-v1' or type(proof['raw_bytes']) is not int or not 0<proof['raw_bytes']<=MAX_REQUEST_JSON_BYTES:
        raise ContractError('Unsupported auxiliary observation proof encoding/bound')
    try:
        compressed=base64.b64decode(proof['payload_b64'],validate=True)
        decoder=zlib.decompressobj();raw=decoder.decompress(compressed,proof['raw_bytes']+1)
        if not decoder.eof or decoder.unused_data or len(raw)!=proof['raw_bytes'] or hashlib.sha256(raw).hexdigest()!=proof['raw_sha256']:
            raise ValueError('Auxiliary observation bytes differ')
        requests=json.loads(raw)
    except (ValueError,TypeError,zlib.error) as error:
        raise ContractError('Auxiliary observation proof is corrupt') from error
    if not isinstance(requests,list) or not 1<=len(requests)<=10000:
        raise ContractError('Bounded actual actor observations required')
    return requests

def metric_names(task,version):
    if version=='actual-declared-goal-auxiliary-v1.1':return METRICS
    if version!='actual-declared-goal-auxiliary-v2':raise ContractError('Unsupported auxiliary metric version')
    return (*METRICS,*(name for card,zone in prerequisites(task) for name in
        (f'goal_effect_card_{card}_available_zone_{zone}',f'first_actor_turn_goal_effect_card_{card}_available_zone_{zone}')))

def analyze_case(task,trace,request_proof,actor,version):
    requests=unpack_requests(request_proof)
    # These are exact native-fingerprinted request DTOs, not invented observations.
    result=evaluate_game(task,trace,{'steps':[{'request':q} for q in requests]},actor)
    if version=='actual-declared-goal-auxiliary-v2':
        rows,attributable=benefits(task,trace['events'],actor)
        cutoff=result.get('first_actor_turn_cutoff_event',len(trace['events'])-1)
        for card,zone in prerequisites(task):
            hits=[r for r in rows if r['move']['public_card']==card and r['move']['to_zone']==zone]
            result['metrics'][f'goal_effect_card_{card}_available_zone_{zone}']=int(bool(hits)) if attributable else None
            result['metrics'][f'first_actor_turn_goal_effect_card_{card}_available_zone_{zone}']=int(any(r['solved_event_index']<=cutoff for r in hits)) if attributable else None
        result['actual_declared_prerequisite_benefits']=rows
        result['activation_or_resolution_without_observed_benefit_is_not_quality']=True
    return result

def choose_auxiliary(rows,plan,names):
    expected={(i,s,p) for i in (0,1) for s in plan['paired_seeds_audit_only'] for p in (0,1)}
    lookup={(r['candidate_index'],r['seed_audit_only'],r['actor_seat']):r for r in rows}
    if set(lookup)!=expected:return None,'incomplete_comparison'
    keys=[(s,p) for s in plan['paired_seeds_audit_only'] for p in (0,1)]
    if any(lookup[0,s,p]['score']!=lookup[1,s,p]['score'] for s,p in keys):
        return None,'primary_outcomes_not_matchwise_tied_use_original_win_evaluation'
    if any(r['auxiliary']['metrics'].get(m) is None for r in rows for m in names):
        return None,'unknown_auxiliary_coverage_not_negative'
    for better in (0,1):
        support=set();dominates=True
        for seed,seat in keys:
            a=lookup[better,seed,seat]['auxiliary']['metrics'];b=lookup[1-better,seed,seat]['auxiliary']['metrics']
            if any(a[m]<b[m] for m in names):dominates=False;break
            if any(a[m]>b[m] for m in names):support.add(seed)
        if dominates and len(support)>=2:return better,'paired_declared_goal_auxiliary_pareto_only'
    return None,'no_strict_supported_auxiliary_dominance'

def _analyze(task,assets,comparison,policy,inputs,formal_matches):
    from .model_build_feedback import validate_model_comparison
    candidates=validate_model_comparison(task,assets,comparison)
    if policy.get('plan_sha256')!=digest({k:v for k,v in policy.items() if k!='plan_sha256'}):
        raise ContractError('Registered auxiliary metric plan differs')
    if (policy.get('task_sha256')!=task.sha256 or policy.get('declared_goal')!=task.goal
            or policy.get('field_count_or_atk_quality_labels') is not False
            or policy.get('unknown_is_not_negative') is not True or policy.get('unsupported_is_not_zero') is not True
            or policy.get('primary_outcome_unchanged') is not True or policy.get('reference_decks_used') is not False):
        raise ContractError('Auxiliary goal/proxy/unknown boundary differs')
    version=policy['version'];names=metric_names(task.to_dict(),version)
    if type(formal_matches) is not int or formal_matches<0:
        raise ContractError('Actual completed formal match count required')
    if version.endswith('v2'):
        minimum=policy.get('minimum_complete_formal_matches_before_comparison')
        if (type(minimum) is not int or minimum<32 or formal_matches<minimum
                or policy.get('registration_scope')!='future_comparisons_only_no_retrospective_metric_selection'):
            raise ContractError('Future-only auxiliary policy cannot relabel earlier games')
    if len(inputs)!=len(comparison['games']):raise ContractError('Full paired auxiliary inputs required')
    rows=[]
    for game,proof in zip(comparison['games'],inputs):
        fields(proof,{'candidate_index','seed_audit_only','actor_seat','trace','actor_requests','episode_artifact_sha256'})
        if any(proof[k]!=game[k] for k in ('candidate_index','seed_audit_only','actor_seat')):
            raise ContractError('Auxiliary cases are not in the frozen paired plan order')
        trace=proof['trace']
        if (digest(trace)!=game['trace_sha256'] or digest(trace['profile'])!=game['profile_sha256']
                or trace['outcome']!=game['outcome'] or not trace['events'] or trace['events'][-1]['kind']!=5):
            raise ContractError('Auxiliary evidence differs from its actual closed replay')
        if len(trace['events'])>100000 or len(trace['responses'])>10000:
            raise ContractError('Auxiliary native event/decision proof exceeds its bound')
        cards=trace.get('resources',{}).get('resources',{}).get('cards')
        if cards!=assets.receipt['resources']['cards']:
            raise ContractError('Auxiliary native card resource differs')
        auxiliary=analyze_case(task.to_dict(),trace,proof['actor_requests'],game['actor_seat'],version)
        rows.append({**game,'episode_artifact_sha256':proof['episode_artifact_sha256'],'auxiliary':auxiliary})
    preferred,reason=choose_auxiliary(rows,comparison['plan'],names)
    return candidates,rows,list(names),preferred,reason

def make_auxiliary_comparison(task,assets,comparison,policy,inputs,formal_matches):
    _,rows,names,preferred,reason=_analyze(task,assets,comparison,policy,inputs,formal_matches)
    value={'schema_version':1,'source':SOURCE_V2 if policy['version'].endswith('v2') else SOURCE,
        'metric_policy':policy,'original_win_comparison':comparison,'inputs':inputs,'cases':rows,'metrics':names,
        'formal_matches_before_comparison':formal_matches,'preferred_index':preferred,'preference_reason':reason,
        'primary_win_comparison_changed':False,'competitive_ability_validated':False,
        'preference_values_kind':'ordinal_rank_encoding_not_winrate_or_program_quality_score'}
    value['auxiliary_sha256']=digest(value)
    return value

def validate_auxiliary_comparison(task,assets,value):
    fields(value,{'schema_version','source','metric_policy','original_win_comparison','inputs','cases','metrics',
        'formal_matches_before_comparison','preferred_index','preference_reason','primary_win_comparison_changed',
        'competitive_ability_validated','preference_values_kind','auxiliary_sha256'})
    if (value['schema_version']!=1 or value['source'] not in SOURCES
            or value['primary_win_comparison_changed'] is not False or value['competitive_ability_validated'] is not False
            or value['preference_values_kind']!='ordinal_rank_encoding_not_winrate_or_program_quality_score'):
        raise ContractError('Actual goal auxiliary evidence is required; it is not competitive acceptance')
    expected=make_auxiliary_comparison(task,assets,value['original_win_comparison'],value['metric_policy'],value['inputs'],value['formal_matches_before_comparison'])
    if value!=expected:raise ContractError('Auxiliary metrics/preference or proof summary differs')
    from .build_contracts import DeckParts
    return [DeckParts.from_dict(d) for d in value['original_win_comparison']['plan']['candidates']]
