"""One bounded CPU command: semantic lists, indexed updates, real opponents.

All full trajectories, datasets and weights are private local artifacts. Only
identical PublicEvents and deliberately selected aggregate proof leave private/.
No provider, cloud API or credential handling exists in this runner.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import time

import torch

from .agent_registry import OpponentRegistry
from .build_contracts import BuildTask,DeckParts
from .build_pipeline import BuildAssets
from .build_semantics import proof,solve_candidates,replacements
from .build_training import run_build_training_smoke
from .cpu_training import CpuTrainer,CpuTrainingConfig,cpu_name,resource_binding,save_checkpoint,load_checkpoint
from .data_isolation import DataIndex
from .duel_model import DuelModelConfig,parameter_digest
from .effect_duel import public_card_facts
from .knowledge_acceptance import public_projection
from .opponent_pool import FrozenOpponent,FrozenOpponentPool,replay_private,SNAPSHOT_DRIVER
from .place_classification import verify_multi_zone
from .training_runner import atomic_json,file_receipt
from .validation import ContractError

CONFIGS=Path(__file__).resolve().parents[2]/'configs'


def engineering_opponents(state_root,native_root,assets,own):
    """Explicit fixtures, not user lists, historical answers or qualified bots."""
    registry=OpponentRegistry(state_root,native_root)
    env=registry.runtime_environment(5);registry.environment(env)
    registry.import_deck({'deck_id':'semantic-own','environment_id':env['environment_id'],'source':'engineering_fixture',
                          'format':'json','content':own.to_dict()})
    normal=json.loads((CONFIGS/'private-selection-engineering-v4.json').read_text())['cases']['chosen-blind']['profile']['decks'][1]
    spare=[c for c,r in sorted(assets.rows.items()) if c not in normal and r['type']==17 and r['ot']&1 and r['alias']==0
           and 1<=r['level']&255<=4 and assets.limits.get(c,3)>=1][:3]
    if len(spare)!=3:raise ContractError('engineering opponent variant pool is unavailable')
    opponents=[]
    for i in range(4):
        cards=list(normal)
        if i:cards[0]=spare[i-1]
        registry.import_deck({'deck_id':f'op-deck-{i}','environment_id':env['environment_id'],'source':'engineering_fixture',
                              'format':'json','content':{'main':cards,'extra':[78156759],'side':[]}})
        registry.register_opponent({'opponent_id':f'op-{i}','deck_id':f'op-deck-{i}','controller':'rule_baseline','provider':'local-python',
                                    'model':'no-llm','driver_version':'visible-effects-first-v1' if i%2==0 else 'visible-effects-last-option-v1'})
        opponents.append(FrozenOpponent(registry,f'op-{i}','semantic-own',1))
    return registry,opponents


def must_reject(operation):
    try:operation()
    except ContractError:return True
    raise ContractError('required admission rejection did not occur')


def run_foundation_acceptance(root,output):
    import scipy
    root,output=Path(root).resolve(),Path(output).resolve()
    if output.exists():raise ContractError('foundation acceptance requires new output; private evidence is never overwritten')
    private,public=output/'private',output/'public';private.mkdir(parents=True);public.mkdir()
    started,cpu=time.monotonic(),time.process_time();torch.set_num_threads(1)
    task=BuildTask.from_dict(json.loads((CONFIGS/'build-semantic-engineering-v4.json').read_text()));assets=BuildAssets(root)
    built=run_build_training_smoke(root,private/'construction','semantic-build',task)
    own=DeckParts.from_dict(built['alternation']['best_deck']);semantic=proof(task,own,assets)
    if semantic['effect_execution_verified'] or any(s['validation']['status']!='constraints_satisfied' for s in built['alternation']['stages']):
        raise ContractError('catalog constraints were misrepresented as effect execution')
    edits=solve_candidates(task,assets,own,max_edits=1)
    if not edits['candidates'] or any(replacements(own,d)>1 for d in edits['candidates']):raise ContractError('bounded semantic edits failed')
    registry,opponents=engineering_opponents(private/'registry',root,assets,own);pool=FrozenOpponentPool(opponents[:2])
    index=DataIndex(private/'duel-data')
    def split(target,ident,purpose,versions):
        return target.freeze({'dataset_id':ident,'experiment_id':'foundation-engineering','purpose':purpose,'family':'duel',
                              'versions':task.environment['versions'],'opponents':[o.binding for o in versions],'task_sha256':None})
    split(index,'duel-train','train',opponents[:2]);split(index,'duel-validation','validation',opponents[2:3])
    split(index,'duel-final','final_eval',opponents[3:])
    must_reject(lambda:split(index,'renamed-training-opponent','validation',opponents[:1]))
    config=CpuTrainingConfig(model=DuelModelConfig(width=16,card_width=8,heads=2,feedforward=32,max_tokens=256,history_events=2),game_seeds=(7,24))
    trainer=CpuTrainer(config,sorted(public_card_facts(root)));receipts=[];games=[]

    def export(name,trace,checked):
        if not checked['replay_verified'] or checked.get('callback_errors',0):raise ContractError('real replay failed before safe export')
        raw_path=private/'traces'/f'{name}.trace.json';raw_path.parent.mkdir(exist_ok=True)
        atomic_json(raw_path,trace);receipt=file_receipt(raw_path,private)
        path=public/f'{name}.public-history.json';atomic_json(path,public_projection(trace,receipt))
        receipts.append(file_receipt(path,public))

    def audit(name,episode):
        checked=replay_private(root,episode['_private_audit'])
        if not checked['natural_terminal'] or not checked['public_histories_equal']:raise ContractError('registered duel/replay did not complete')
        export(name,episode['_private_audit'],checked)
        games.append({'case':name,'purpose':episode['purpose'],'driver_version':episode['summary']['opponent_binding']['driver_version'],
                      'trajectory_sha256':episode['summary']['trajectory_sha256'],'actor_samples':len(episode['steps']),**checked})

    first=trainer.sample_episode(root,pool.choose(0).profile,opponent_adapter=pool.choose(0));audit('train-first',first)
    index.ingest_episode('duel-train','first',first);index.admit_episode('first',first);update1=trainer.update(first)
    binding=resource_binding(root,pool.choose(0).profile)|{'registered_opponent_pool':pool.manifest()}
    checkpoint=save_checkpoint(trainer,registry.root/'snapshots','first-complete-update',binding)
    restored=load_checkpoint(checkpoint,binding)
    op=pool.choose(restored.episode_cursor)
    second=trainer.sample_episode(root,op.profile,opponent_adapter=op)
    repeated=restored.sample_episode(root,op.profile,opponent_adapter=op)
    if second['summary']['trajectory_sha256']!=repeated['summary']['trajectory_sha256']:raise ContractError('checkpoint next real sample diverged')
    index.ingest_episode('duel-train','second',second);index.admit_episode('second',second)
    # Recovery verification has a separate ledger; it is not a third canonical
    # training episode or a source of additional optimizer steps for the run.
    recovery=DataIndex(private/'recovery-verification-data');split(recovery,'duel-train','train',opponents[:2])
    recovery.ingest_episode('duel-train','second',repeated);recovery.admit_episode('second',repeated)
    update2=trainer.update(second);again=restored.update(repeated)
    if update2!=again or parameter_digest(trainer.model)!=parameter_digest(restored.model):raise ContractError('checkpoint next update diverged')
    audit('train-second',second);audit('recovery-second',repeated)
    validation=trainer.sample_episode(root,opponents[2].profile,purpose='validation',seed=1701,policy_seed=500,opponent_adapter=opponents[2])
    index.ingest_episode('duel-validation','validation',validation);audit('validation',validation)
    final=trainer.sample_episode(root,opponents[3].profile,purpose='final_eval',seed=1800,policy_seed=600,opponent_adapter=opponents[3])
    index.ingest_episode('duel-final','final',final);audit('final',final)
    before=parameter_digest(trainer.model)
    must_reject(lambda:index.admit_episode('validation',validation));must_reject(lambda:index.artifact('final',for_training=True))
    bad=copy.deepcopy(validation);bad['purpose']=bad['summary']['purpose']='train';must_reject(lambda:trainer.update(bad))
    if parameter_digest(trainer.model)!=before:raise ContractError('held-out rejection altered model weights')
    snapshot_sha=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    registry.register_opponent({'opponent_id':'frozen-snapshot','deck_id':'op-deck-0','controller':'local_snapshot','provider':'local-pytorch-cpu',
                                'model':update1['after_sha256'],'driver_version':SNAPSHOT_DRIVER})
    frozen=FrozenOpponent(registry,'frozen-snapshot','semantic-own',1,checkpoint=checkpoint,checkpoint_sha256=snapshot_sha)
    split(index,'snapshot-validation','validation',[frozen]);frozen_hash=parameter_digest(frozen.policy.model)
    snapshot=trainer.sample_episode(root,frozen.profile,purpose='validation',seed=1900,policy_seed=700,opponent_adapter=frozen)
    index.ingest_episode('snapshot-validation','snapshot',snapshot);audit('snapshot-validation',snapshot)
    if (parameter_digest(frozen.policy.model)!=frozen_hash or any(p.requires_grad for p in frozen.policy.model.parameters())
        or parameter_digest(trainer.model)!=before):raise ContractError('frozen opponent/evaluation altered weights')
    classification,traces=verify_multi_zone(root)
    for i,trace in enumerate(traces):export(f'msg24-{i}',trace,{'replay_verified':True})
    for receipt in receipts:
        if file_receipt(public/receipt['path'],public)!=receipt:raise ContractError('public projection receipt changed')
    result={'schema_version':1,'kind':'nonpaid-semantic-indexed-opponent-engineering','ok':True,
            'implementation_sha256':binding['python_implementation_sha256'],'resources':assets.receipt,
            'python':platform.python_version(),'torch':str(torch.__version__),'scipy':scipy.__version__,
            'build':{'task_sha256':task.sha256,'feature_version':built['binding']['feature_version'],'source':built['source'],
                     'independent_weights':True,'parameter_counts':built['parameter_counts'],'updates':built['updates'],
                     'restore_verified':built['restore_verified'],'canonical_updates_per_role':2,'physical_optimizer_calls_including_recovery':6,
                     'semantic_constraints':semantic['counts'],'alternating_roles':[s['role'] for s in built['alternation']['stages']],
                     'effect_execution_verified':False,'edit_limit':1,'verified_edit_candidates':len(edits['candidates']),
                     'data_index':built['data_index'],'strength_labels_used':False},
            'duel':{'canonical_updates':2,'physical_updates_including_recovery':3,'updates':[update1,update2],
                    'registered_pool':pool.manifest(),'snapshot_model_sha256':frozen_hash,'snapshot_weights_frozen':True,
                    'restore_next_sample_and_update_identical':True,'games':games},
            'data_index':index.summary(),'recovery_verification_index':recovery.summary(),
            'heldout_relabel_and_admission_rejected_before_update':True,'place_classification':classification,'public_projections':receipts,
            'measured':{'wall_seconds':time.monotonic()-started,'process_cpu_seconds':time.process_time()-cpu,
                        'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'processor':cpu_name(),'logical_cpu_count':os.cpu_count(),
                        'torch_threads':torch.get_num_threads(),'cuda_build':torch.version.cuda},
            'scope':{'engineering_lists_only':True,'user_decks_received':False,'qualified_bot_transport_verified':False,
                     'external_provider_end_to_end_verified':False,'three_period_training_verified':False,
                     'full_phase_1_delivered':False,'formal_training_ready':False,'competitive_ability_verified':False,
                     'paid_resources_started':False,'external_provider_calls':0},
            'export_boundary':'Common-public projection and aggregates only; complete private replay, weights, data index and labels remain cloud-local.'}
    atomic_json(public/'delivery-proof.json',result)
    return result
