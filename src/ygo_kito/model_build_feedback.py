"""Paired actual games with a frozen learned actor and one audited C# opponent.

The preference is a multi-case training signal, not independent acceptance or
an attribution of a lone loss to a card. Ties and insufficient support stay open.
"""
from copy import copy
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import time

import torch

from .build_contracts import DeckParts, digest
from .build_feedback import plan_for as old_plan_for, outcome_score, descriptive_uncertainty
from .contracts import Versions
from .cpu_training import CpuTrainer
from .duel_model import parameter_digest, FEATURE_VERSION
from .extra_routes import profile_for
from .opponent_pool import replay_private
from .validation import ContractError, fields

SOURCE='real_core_paired_frozen_neural_audited_bot_v1'


def profile_for_case(candidate,opponent,seat,revision):
    p=profile_for(candidate,opponent=opponent) if seat==0 else profile_for(opponent,opponent=candidate)
    p['name']='frozen-neural-construction-pair';p['adapter_revision']=revision
    return p


def preference(games,seeds):
    lookup={(g['candidate_index'],g['seed_audit_only'],g['actor_seat']):g['score'] for g in games}
    differences=[lookup[1,s,p]-lookup[0,s,p] for s in seeds for p in (0,1)]
    means=[sum(g['score'] for g in games if g['candidate_index']==i)/(len(seeds)*2) for i in (0,1)]
    direction=0 if means[0]==means[1] else 1 if means[1]>means[0] else -1
    support={s for s in seeds if any(direction*(lookup[1,s,p]-lookup[0,s,p])>0 for p in (0,1))}
    # No label from one seed/one win, and no claim that uncertainty disappeared.
    preferred=(int(direction>0) if direction and len(support)>=2 and all(direction*d>=0 for d in differences) else None)
    return means,differences,preferred


def validate_model_comparison(task,assets,value):
    fields(value,{'source','plan','plan_sha256','games','mean_scores','paired_differences','preferred_index',
                  'status','uncertainty','competitive_ability_validated','comparison_sha256'})
    plan=value['plan']
    fields(plan,{'task_sha256','candidates','opponent','paired_seeds_audit_only','actor_seats','purpose','format','driver','versions','adapter_revision'})
    driver=fields(plan['driver'],{'version','type','trained_policy','policy_sha256','policy_version','feature_version','opponent_id','executor_id','source_id','audit_sha256','assembly_sha256','policy_sampling'})
    if (value['source']!=SOURCE or plan['format']!='BO1_frozen_model_audited_bot' or
            driver['version']!='frozen-learned-actor-audited-bot-v1' or driver['type']!='actual_learned_neural_policy' or
            driver['trained_policy'] is not True or driver['policy_sampling']!='private-paired-rng' or
            driver['feature_version']!=FEATURE_VERSION or value['competitive_ability_validated'] is not False):
        raise ContractError('actual frozen neural comparison identity required')
    for k in ('policy_sha256','audit_sha256','assembly_sha256'):
        if not isinstance(driver[k],str) or len(driver[k])!=64:raise ContractError('frozen model/bot hash missing')
    candidates=[DeckParts.from_dict(d) for d in plan['candidates']];opponent=DeckParts.from_dict(plan['opponent'])
    expected=old_plan_for(task,candidates,opponent,tuple(plan['paired_seeds_audit_only']),plan['purpose'])
    expected.update(driver=driver,format=plan['format'],adapter_revision=plan['adapter_revision'])
    if plan!=expected or digest(plan)!=value['plan_sha256']:raise ContractError('frozen pair plan changed')
    for candidate in candidates:assets.validate(task,candidate)
    keys={(i,s,p) for i in (0,1) for s in plan['paired_seeds_audit_only'] for p in (0,1)}
    actual=set()
    for game in value['games']:
        fields(game,{'candidate_index','seed_audit_only','actor_seat','outcome','score','turns','decisions','trace_sha256','profile_sha256','core_terminal_received','replay_verified','policy_sha256','data_artifact_id'})
        key=game['candidate_index'],game['seed_audit_only'],game['actor_seat']
        if key not in keys or key in actual:raise ContractError('repeated/out-of-plan model comparison game')
        actual.add(key)
        profile=profile_for_case(candidates[key[0]],opponent,key[2],plan['adapter_revision'])
        if (game['profile_sha256']!=digest(profile) or game['policy_sha256']!=driver['policy_sha256'] or
                game['core_terminal_received'] is not True or game['replay_verified'] is not True or
                game['score']!=outcome_score(game['outcome'],key[2]) or game['decisions']<1 or game['turns']<1):
            raise ContractError('model comparison lacks its actual natural-terminal/replay/policy binding')
    if actual!=keys:raise ContractError('incomplete comparison cannot train optimizer')
    means,differences,preferred=preference(value['games'],plan['paired_seeds_audit_only'])
    if (value['mean_scores']!=means or value['paired_differences']!=differences or value['preferred_index']!=preferred or
            value['status']!=('no_strict_label' if preferred is None else 'paired_training_preference_observed') or
            value['uncertainty']!=descriptive_uncertainty(differences) or
            value['comparison_sha256']!=digest({k:v for k,v in value.items() if k!='comparison_sha256'})):
        raise ContractError('paired model comparison summary differs')
    return candidates


def comparison_case_id(plan,index,seed,seat,namespace=None):
    key=[digest(plan),index,seed,seat]
    return 'cmp-'+digest(key if namespace is None else [namespace,*key])[:40]


def comparison_dataset_id(binding,namespace=None):
    return 'construction-eval-'+digest(binding if namespace is None else {'cycle':namespace,'binding':binding})[:24]


def compare_model_candidates(task,assets,candidates,opponent,*,trainer,registry,bot,audit,workspace,
                             seeds,directory,data_index,experiment_id,stop,status,seconds=7200.,artifact_namespace=None,budget=None,
                             comparison_policy=None,candidate_basic_cbs=None):
    from .training_admission import require_training_admission
    if candidate_basic_cbs is not None and not isinstance(candidate_basic_cbs,dict):
        raise ContractError('candidate basic CB evidence must be keyed by exact deck digest')
    admissions=[]
    for deck in candidates:
        basic_cb=(candidate_basic_cbs or {}).get(digest(deck.to_dict()))
        verdict=require_training_admission(task=task,deck=deck,basic_cb=basic_cb,assets=assets,
            purpose='construction_comparison',comparison_policy=comparison_policy)
        if verdict['status']!='admitted':
            raise ContractError('Candidate comparison deferred by training admission: '+str(verdict.get('reasons',[])))
        admissions.append(verdict)
    if len({row['policy_epoch'] for row in admissions})!=1:
        raise ContractError('Candidate comparison requires one bound training policy epoch')
    if not isinstance(trainer,CpuTrainer) or trainer.updates<1:raise ContractError('actual separately started duel base required')
    if budget is not None:budget.check('paired_comparison_start')
    if artifact_namespace is not None and (not isinstance(artifact_namespace,str) or not 1<=len(artifact_namespace)<=128):
        raise ContractError('bounded comparison artifact namespace required')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    model_sha=parameter_digest(trainer.model)
    driver={'version':'frozen-learned-actor-audited-bot-v1','type':'actual_learned_neural_policy','trained_policy':True,
            'policy_sha256':model_sha,'policy_version':trainer.updates,'feature_version':FEATURE_VERSION,
            'opponent_id':bot['bot_id'],'executor_id':bot['executor_id'],'source_id':bot['source_id'],
            'audit_sha256':hashlib.sha256(Path(audit['path']).read_bytes()).hexdigest(),
            'assembly_sha256':audit['assembly_sha256'],'policy_sampling':'private-paired-rng'}
    plan=old_plan_for(task,candidates,opponent,seeds,'construction_train')
    plan.update(driver=driver,format='BO1_frozen_model_audited_bot',adapter_revision=assets.adapter_revision)
    def write(p,value):
        temp=p.with_name(p.name+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temp.replace(p)
    plan_path=directory/'plan.json'
    if plan_path.exists() and json.loads(plan_path.read_text())!=plan:raise ContractError('existing frozen comparison plan differs')
    admission_path=directory/'training-admission.json'
    admission={'task_sha256':task.sha256,'purpose':'construction_comparison','candidates':admissions}
    if admission_path.exists():
        if json.loads(admission_path.read_text())!=admission:
            raise ContractError('Existing comparison training admission differs')
    elif any(directory.glob('candidate-*-seed-*-seat-*.json')):
        raise ContractError('Existing comparison cases predate the required training admission; no retrospective relabelling')
    else:
        write(admission_path,admission)
    write(plan_path,plan)
    original_rng=torch.get_rng_state().clone();modes=[(m,m.training) for m in trainer.model.modules()]
    original_cursor=(trainer.updates,trainer.episode_cursor,trainer._pending_episode_digest)
    original_policy_rng=trainer.policy_rng.get_state().clone();started=time.monotonic();games=[]
    engine_factory=assets.engine_factory
    if budget is not None:
        from contextlib import contextmanager
        from .native import NativeNormalEngine
        base_factory=engine_factory or NativeNormalEngine
        @contextmanager
        def engine_factory(*args,**kwargs):
            with base_factory(*args,**kwargs) as engine:
                original_next,original_submit=engine.next_decision,engine.submit
                def next_decision(*a,**k):
                    budget.check('paired_native_boundary')
                    return original_next(*a,**k)
                def submit(*a,**k):
                    budget.check('paired_response_boundary')
                    return original_submit(*a,**k)
                engine.next_decision,engine.submit=next_decision,submit
                try:yield engine
                finally:engine.next_decision,engine.submit=original_next,original_submit

    try:
        for seed in seeds:
            for seat in (0,1):
                for index,candidate in enumerate(candidates):
                    if stop.exists():raise RuntimeError('Safe stop before next complete paired case')
                    if time.monotonic()-started>=seconds:raise RuntimeError('Actual comparison time allocation exhausted; no label')
                    name='candidate-'+str(index)+'-seed-'+str(seed)+'-seat-'+str(seat)
                    artifact_id=comparison_case_id(plan,index,seed,seat,artifact_namespace)
                    receipt_path=directory/(name+'.json');flight=directory/(name+'.in-flight.json')
                    if receipt_path.exists():
                        game=json.loads(receipt_path.read_text())
                        if game.get('data_artifact_id')!=artifact_id:raise ContractError('saved comparison cycle identity differs')
                        closed=directory/(name+'.closed-flight.json')
                        if not closed.exists() or json.loads(closed.read_text()).get('receipt_sha256')!=digest(game):raise RuntimeError('Completed case lacks its closed immutable boundary')
                        data_index.artifact(game['data_artifact_id'],for_training=True)
                        games.append(game);continue
                    if flight.exists():raise RuntimeError('Uncertain case preserved; no automatic replay: '+name)
                    if budget is not None:budget.check('paired_case_boundary',required=2*trainer.config.episode_seconds,allowance=seconds-(time.monotonic()-started))
                    status('paired_actual_frozen_model_game',case=name,completed_cases=len(games),total_cases=len(seeds)*4)
                    profile=profile_for_case(candidate,opponent,seat,assets.adapter_revision);assets.validate_profile(profile)
                    adapter=registry.training_adapter(bot['executor_id'],source_id=bot['source_id'],native_root=assets.root,profile=profile,
                        seat=1-seat,versions=Versions.from_dict(task.environment['versions']),environment_id=task.environment['environment_id'],
                        opponent_id=bot['bot_id'],source=bot['source'],build_audit_path=Path(audit['path']),build_audit_sha256=driver['audit_sha256'],
                        mono=bot['mono'],workspace=workspace,period_context=assets.period_context,session_seconds=300)
                    current=copy(trainer);current.config=replace(trainer.config,actor_seat=seat)
                    if seed not in trainer.config.game_seeds:raise ContractError('Comparison seed is not in the declared training schedule')
                    current.episode_cursor=trainer.config.game_seeds.index(seed);current._pending_episode_digest=None
                    rng_seed=int(digest({'seed':seed,'seat':seat,'model':model_sha,'purpose':'construction_train'})[:16],16)%(2**63-1)
                    current.policy_rng=torch.Generator(device='cpu').manual_seed(rng_seed)
                    if budget is not None:budget.in_flight=True
                    write(flight,{'plan_sha256':digest(plan),'status':'sampling_no_automatic_replay'})
                    episode=current.sample_episode(assets.root,profile,purpose='train',opponent_adapter=adapter,engine_factory=engine_factory)
                    trace=episode['_private_audit'];write(directory/(name+'.private-replay.json'),trace)
                    replay=replay_private(assets.root,trace,engine_factory=engine_factory)
                    binding=episode['summary']['opponent_binding'];dataset_id=comparison_dataset_id(binding,artifact_namespace)
                    data_index.freeze({'dataset_id':dataset_id,'experiment_id':experiment_id,'purpose':'train','family':'duel',
                        'versions':task.environment['versions'],'opponents':[binding],'task_sha256':None})
                    data_index.ingest_episode(dataset_id,artifact_id,episode);data_index.admit_episode(artifact_id,episode)
                    summary=episode['summary']
                    game={'candidate_index':index,'seed_audit_only':seed,'actor_seat':seat,'outcome':trace['outcome'],
                          'score':outcome_score(trace['outcome'],seat),'turns':summary['turns'],'decisions':summary['native_decisions'],
                          'trace_sha256':digest(trace),'profile_sha256':digest(profile),'core_terminal_received':trace['events'][-1]['kind']==5,
                          'replay_verified':replay['replay_verified'],'policy_sha256':model_sha,'data_artifact_id':artifact_id}
                    write(receipt_path,game);write(flight,{'plan_sha256':digest(plan),'receipt_sha256':digest(game),'private_trace_sha256':digest(trace),'replay_verified':True})
                    flight.rename(directory/(name+'.closed-flight.json'));games.append(game)
                    if budget is not None:budget.in_flight=False
                    write(directory/'progress.json',{'completed_cases':len(games),'total_cases':len(seeds)*4,'last_case':name,'formal_course_credit':False})
        if parameter_digest(trainer.model)!=model_sha or original_cursor!=(trainer.updates,trainer.episode_cursor,trainer._pending_episode_digest):
            raise ContractError('frozen comparison changed actual driver weights/cursors')
        if not torch.equal(trainer.policy_rng.get_state(),original_policy_rng):raise ContractError('frozen comparison consumed the training sampler stream')
        means,differences,preferred=preference(games,seeds)
        value={'source':SOURCE,'plan':plan,'plan_sha256':digest(plan),'games':games,'mean_scores':means,'paired_differences':differences,
               'preferred_index':preferred,'status':'no_strict_label' if preferred is None else 'paired_training_preference_observed',
               'uncertainty':descriptive_uncertainty(differences),'competitive_ability_validated':False}
        value['comparison_sha256']=digest(value);validate_model_comparison(task,assets,value)
        write(directory/'comparison.json',value);return value
    finally:
        for module,training in modes:module.train(training)
        torch.set_rng_state(original_rng)
