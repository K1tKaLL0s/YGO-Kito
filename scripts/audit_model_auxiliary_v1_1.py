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
    from ygo_kito.contracts import Observation
    from ygo_kito.extra_routes import completed_fusion_summon
    from ygo_kito.route_search import resolved_chain_cards
    events=trace['events'];goal=task['goal'];route=goal.get('route_goal',goal)
    target=route.get('card_id');kind=route.get('kind')
    frames=align_observations(trace,episode,actor)
    if kind not in ('fusion_summon','normal_summon'):
        return {'status':'unsupported_proper_summon_witness','metrics':{k:None for k in METRICS},'goal_kind':kind}
    relevant_kind=62 if kind=='fusion_summon' else 60
    starts=[i for i,e in enumerate(events) if e['kind']==relevant_kind and e.get('player')==actor
            and e.get('public_summoning_card')==target]
    own_turn=next((i for i,e in enumerate(events) if e['kind']==40 and e['player']==actor),None)
    cutoff=next((i for i in range((own_turn or 0)+1,len(events)) if own_turn is not None and events[i]['kind']==40),len(events)-1)
    hits=[]
    for index,raw_observation,identity in frames:
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


def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime-source',type=Path,required=True);p.add_argument('--metric-plan',type=Path,required=True)
    p.add_argument('--comparison',type=Path,required=True);p.add_argument('--index',type=Path,required=True)
    p.add_argument('--task',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    sys.path.insert(0,str(a.runtime_source/'src'))
    metric_plan=read(a.metric_plan);plan=read(a.comparison/'plan.json');task=read(a.task);task=task.get('task',task)
    if metric_plan['version']!=VERSION or metric_plan['plan_sha256']!=digest({k:v for k,v in metric_plan.items() if k!='plan_sha256'}):raise ValueError('Metric plan changed')
    if digest(task)!=plan['task_sha256'] or plan['task_sha256']!=metric_plan['task_sha256']:raise ValueError('The exact declared task differs')
    if plan['purpose']!='construction_train' or plan['driver']['type']!='actual_learned_neural_policy':raise ValueError('Frozen actual training comparison required')
    rows=[]
    with sqlite3.connect('file:'+a.index.as_posix()+'?mode=ro',uri=True) as db:
        for seed in plan['paired_seeds_audit_only']:
            for seat in (0,1):
                for candidate in (0,1):
                    name=f'candidate-{candidate}-seed-{seed}-seat-{seat}';path=a.comparison/(name+'.json');closed=a.comparison/(name+'.closed-flight.json')
                    if not path.exists() or not closed.exists():continue
                    case=read(path);boundary=read(closed)
                    if boundary['receipt_sha256']!=digest(case) or case['replay_verified'] is not True or case['core_terminal_received'] is not True:raise ValueError('Case is not a verified closed native boundary')
                    trace=read(a.comparison/(name+'.private-replay.json'))
                    if digest(trace)!=case['trace_sha256'] or digest(trace['profile'])!=case['profile_sha256']:raise ValueError('Actual replay identity differs')
                    record=db.execute('SELECT payload,sha FROM artifacts WHERE id=?',(case['data_artifact_id'],)).fetchone()
                    if record is None:raise ValueError('Closed case has no admitted real episode')
                    envelope=json.loads(record[0]);episode=envelope['payload']
                    if digest(envelope)!=record[1] or digest(episode)!=envelope['payload_sha256']:raise ValueError('Admitted episode identity differs')
                    if episode['policy_sha256']!=plan['driver']['policy_sha256'] or episode['summary']['actor_seat']!=seat:raise ValueError('Frozen driver/seat differs')
                    if episode['summary']['opponent_binding']!=trace['opponent_binding'] or episode['summary']['outcome']!=case['outcome']:raise ValueError('Actual opponent/outcome differs')
                    auxiliary=evaluate_game(task,trace,episode,seat)
                    rows.append({**case,'episode_artifact_sha256':record[1],'auxiliary':auxiliary})
    preferred,reason=auxiliary_preference(rows,plan)
    result={'source':SOURCE,'metric_version':VERSION,'metric_plan_sha256':metric_plan['plan_sha256'],'comparison_plan':plan,
        'comparison_plan_sha256':digest(plan),'created_utc':datetime.now(timezone.utc).isoformat(),'metrics':list(METRICS),
        'cases':rows,'complete_cases':len(rows),'total_cases':len(plan['paired_seeds_audit_only'])*4,
        'preferred_index':preferred,'preference_reason':reason,'original_win_comparison_changed':False,
        'new_native_games_executed':0,'model_updates':0,'formal_course_credit':0,'competitive_improvement_verified':False}
    result['auxiliary_sha256']=digest(result)
    if a.out.exists():
        old=read(a.out);prior={(r['candidate_index'],r['seed_audit_only'],r['actor_seat']):r for r in old['cases']}
        for row in rows:
            key=row['candidate_index'],row['seed_audit_only'],row['actor_seat']
            if key in prior and row!=prior[key]:raise ValueError('An earlier auxiliary case would change')
        backup=a.out.with_name(a.out.stem+'-'+old['auxiliary_sha256'][:16]+a.out.suffix)
        if not backup.exists():backup.write_bytes(a.out.read_bytes())
    a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:result[k] for k in ('source','complete_cases','total_cases','preferred_index','preference_reason','auxiliary_sha256','model_updates')}))
if __name__=='__main__':main()
