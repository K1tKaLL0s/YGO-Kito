"""Nonpaid CPU proof: real hidden selections, full-action learning and recovery."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import resource
import time

import torch

from .cpu_training import CpuTrainer,CpuTrainingConfig,resource_binding,save_checkpoint,load_checkpoint
from .duel_model import DuelModelConfig,parameter_digest
from .effect_duel import public_card_facts,run_effect_duel
from .hierarchical_policy import POLICY_VERSION
from .private_cases import CASES_PATH,REQUIRED,read_case,run_private_case
from .training_runner import atomic_json,file_receipt
from .validation import ContractError


def identical(left,right):
    if isinstance(left,torch.Tensor):return isinstance(right,torch.Tensor) and torch.equal(left,right)
    if type(left)!=type(right):return False
    if isinstance(left,dict):return left.keys()==right.keys() and all(identical(left[k],right[k]) for k in left)
    if isinstance(left,(tuple,list)):return len(left)==len(right) and all(identical(a,b) for a,b in zip(left,right))
    return left==right


def run_private_acceptance(root,output):
    root,output=Path(root),Path(output).resolve()
    if output.exists():raise ContractError('private acceptance needs a fresh directory; prior evidence is preserved')
    output.mkdir(parents=True)
    wall,cpu=time.monotonic(),time.process_time()
    traces,results=[],[]
    plans=[(name,'first',False) for name in REQUIRED]+[(name,'last',False) for name in ('chosen-blind','mixed-teleport')]+[('chosen-blind','first',True)]
    for name,preference,complete in plans:
        proof,trace=run_private_case(root,name,preference=preference,complete=complete)
        checked,again=run_private_case(root,name,preference=preference,complete=complete,replay=json.loads(json.dumps(trace)))
        if trace!=again or proof['trace_sha256']!=checked['trace_sha256']:
            raise ContractError('real private case replay diverged')
        path=output/f'{name}-{preference}{"-complete" if complete else ""}.trace.json'
        atomic_json(path,trace);traces.append(file_receipt(path,output));results.append({**proof,'replay_verified':True,'preference':preference,'complete':complete})
    generic,trace=run_effect_duel(root,read_case('chosen-blind')['profile'],seed=90,budget_seconds=30)
    checked,again=run_effect_duel(root,trace['profile'],replay=json.loads(json.dumps(trace)),budget_seconds=30)
    if trace!=again or not checked['replay_verified']:raise ContractError('generic revision-4 duel replay diverged')
    path=output/'generic-private-v4.trace.json';atomic_json(path,trace);traces.append(file_receipt(path,output))
    config=CpuTrainingConfig(model=DuelModelConfig(width=16,card_width=8,heads=2,feedforward=32,history_events=2,max_tokens=128),
                             game_seeds=(0,3),curriculum='large-declaration')
    profile=read_case('large-declaration')['profile'];binding=resource_binding(root,profile)
    trainer=CpuTrainer(config,sorted(public_card_facts(root)))
    first=trainer.sample_episode(root,profile)
    before=parameter_digest(trainer.model);first_update=trainer.update(first)
    checkpoint=save_checkpoint(trainer,output,'large-action-first',binding)
    restored=load_checkpoint(checkpoint,binding)
    continuous=trainer.sample_episode(root,profile);resumed=restored.sample_episode(root,profile)
    for key in ('trajectory_sha256','real_core_events_sha256','outcome'):
        if continuous['summary'][key]!=resumed['summary'][key]:raise ContractError('real resumed sample differs')
    update=trainer.update(continuous);resumed_update=restored.update(resumed)
    if update!=resumed_update or parameter_digest(trainer.model)!=parameter_digest(restored.model):
        raise ContractError('resumed hierarchical update differs')
    left=save_checkpoint(trainer,output,'large-action-continuous',binding)
    right=save_checkpoint(restored,output,'large-action-resumed',binding)
    if not identical(torch.load(left,weights_only=True,map_location='cpu'),torch.load(right,weights_only=True,map_location='cpu')):
        raise ContractError('full model/optimizer/scheduler/cursor/RNG checkpoint state differs')
    samples=[]
    for episode in (first,continuous,resumed):
        rows=[]
        for step in episode['steps']:
            req=step['request'];chosen=req.actions[step['action_index']]
            if req.prompt.message!=142 or len(req.actions)<=2048 or req.context.seed is not None:
                raise ContractError('real full-action curriculum was not actually reached')
            if step['hierarchy']['leaf_count']!=len(req.actions) or len(step['hierarchy']['path'])<2:
                raise ContractError('hierarchical action list was truncated or bypassed')
            rows.append({'native_message':142,'legal_candidates':len(req.actions),'chosen_card':chosen.value,
                         'old_log_prob':step['old_log_prob'],'hierarchy':step['hierarchy']})
        samples.append({'summary':episode['summary'],'policy_decisions':rows})
    updates={'source':'real-core-engineering-prompt-curriculum-not-competitive-evaluation','config':asdict(config),
             'binding':binding,'initial_model_sha256':before,'samples':samples,
             'updates':[first_update,update,resumed_update],'canonical_updates':2,'physical_updates_including_recovery_control':3,
             'complete_state_restore_equal':True,'parameter_count':sum(p.numel() for p in trainer.model.parameters())}
    path=output/'training-metrics.json';atomic_json(path,updates)
    metrics_receipt=file_receipt(path,output)
    for rec in traces+[metrics_receipt]:
        raw=(output/rec['path']).read_bytes()
        if len(raw)!=rec['bytes'] or hashlib.sha256(raw).hexdigest()!=rec['sha256']:
            raise ContractError('saved public evidence receipt differs')
    result={'schema_version':1,'kind':'nonpaid-real-private-selection-and-hierarchy-v4','ok':True,
            'binding':binding,'cases_sha256':hashlib.sha256(CASES_PATH.read_bytes()).hexdigest(),
            'policy_version':POLICY_VERSION,'cases':results,'generic_effect_duel':generic,
            'trace_receipts':traces,'training_metrics':metrics_receipt,
            'checkpoint_receipts':[file_receipt(p,output) for p in (checkpoint,left,right)],
            'canonical_parameter_updates':2,'physical_parameter_updates':3,'complete_state_restore_equal':True,
            'measured':{'wall_seconds':time.monotonic()-wall,'process_cpu_seconds':time.process_time()-cpu,
                        'parent_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
            'scope':{'real_engine':True,'paid_resources_started':False,'provider_calls':0,'full_phase_1_delivered':False,
                     'formal_training_ready':False,'competitive_ability_verified':False,'pc_compatibility_verified':False,
                     'opponent_deck_blind_selection_real_case_verified':False,'hidden_unselect_26_real_case_verified':False,
                     'all_cards_and_mechanisms_verified':False,'prompt_curriculum_is_standalone_engineering_only':True},
            'limits':{'kernel_cli_wall_seconds':120,'complete_legal_actions':50000,'neural_scoring_page':2048,'hierarchy_fanout':128}}
    atomic_json(output/'proof.json',result)
    return result
