"""Indexed schema4 course on the existing four-role transaction runner.

Every checkpoint embeds its committed index snapshot. Uncommitted workers cannot
leave a newer training index behind for a recovered older model to consume.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4

from .build_contracts import BuildTask,DeckParts,digest
from .data_isolation import DataIndex
from .semantic_training import dataset,SOURCE
from .validation import ContractError,fields,integer,read_json

COURSE='indexed-semantic-course-v1'


def configured(recipe):
    from .group_runner import config_path
    return ('construction_curriculum' in recipe and
            read_json(config_path(recipe['construction_curriculum'])).get('source')==COURSE)


def inputs(recipe,task):
    from .group_runner import config_path
    cfg=read_json(config_path(recipe['construction_curriculum']))
    fields(cfg,{'schema_version','source','validation_task','period_id','environment','budget_seconds'})
    integer(cfg['schema_version'],'semantic course schema',1,1)
    if (cfg['source']!=COURSE or task.schema_version!=4 or task.goal['kind']!='deck_constraints'
        or cfg['environment']!=task.environment or cfg['period_id']!='engineering-custom'):
        raise ContractError('semantic course requires its exact custom environment; historical periods need independently prepared data')
    if type(cfg['budget_seconds']) not in (float,int) or not 0<cfg['budget_seconds']<=30:raise ContractError('semantic course budget invalid')
    val=BuildTask.from_dict(read_json(config_path(cfg['validation_task'])))
    if val.schema_version!=4 or val.environment!=task.environment or val.sha256==task.sha256:
        raise ContractError('semantic validation must reserve a different task in the same actual environment')
    return {'config':cfg,'validation_task':val,'binding_sha256':digest({'course':cfg,'train_task':task.to_dict(),'validation_task':val.to_dict()})}


def new_index(state):
    from .local_training import run_path
    return DataIndex(run_path(state.state_root,state.row['run_id'])/('index-working-'+uuid4().hex))


def snapshot_index(state):
    if state.data_index is None:return None
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'data-index.sqlite3'
        with sqlite3.connect(state.data_index.path) as source,sqlite3.connect(path) as dest:source.backup(dest)
        raw=path.read_bytes()
    return {'sha256':hashlib.sha256(raw).hexdigest(),'bytes':raw}


def restore_index(state,saved):
    state.data_index=None
    if saved is None:return
    fields(saved,{'sha256','bytes'})
    if not isinstance(saved['bytes'],bytes) or hashlib.sha256(saved['bytes']).hexdigest()!=saved['sha256']:
        raise ContractError('committed data index checksum differs')
    # New index directory for each restoration: a crashed attempt's SQL writes
    # cannot masquerade as committed data from the selected checkpoint.
    state.data_index=new_index(state)
    state.data_index.path.write_bytes(saved['bytes'])
    with sqlite3.connect(state.data_index.path) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ContractError('committed index is corrupt')


def freeze(state,ident,purpose,family,*,task=None,opponents=()):
    cfg=inputs(state.row['recipe'],state.task)
    return state.data_index.freeze({'dataset_id':ident,'experiment_id':cfg['config']['period_id'],'purpose':purpose,'family':family,
        'versions':state.task.environment['versions'],'opponents':list(opponents),'task_sha256':None if task is None else task.sha256})


def initialize(state,generation):
    from .local_training import run_path
    from .training_runner import atomic_json,file_receipt
    cfg=inputs(state.row['recipe'],state.task);state.data_index=new_index(state)
    train=dataset(state.task,state.assets);val=dataset(cfg['validation_task'],state.assets,purpose='validation')
    for purpose,task,data in [('train',state.task,train),('validation',cfg['validation_task'],val)]:
        freeze(state,'build-'+purpose,purpose,'construction',task=task)
        state.data_index.ingest_construction('build-'+purpose,'build-labels-'+purpose,task,state.assets,data,seeds=())
    run=run_path(state.state_root,state.row['run_id']);path=run/'data/construction_train'/f'bootstrap-{generation}.json'
    atomic_json(path,{'kind':'private-semantic-supervision','binding_sha256':cfg['binding_sha256'],'data':train})
    state.construction_state={'binding_sha256':cfg['binding_sha256'],'train_artifact':file_receipt(path,run),'consumed':[],'validation':[]}
    return train


def admission(state):
    if state.data_index is None:raise ContractError('semantic course has no committed training index')
    return state.data_index.admit_construction('build-labels-train',state.task,state.data)


def consume(state,role):
    admission(state)
    marker={'event_id':state.event_id(),'role':role,'partition':'construction_train',
            'supervision_sha256':state.data['supervision_sha256'],'artifact_sha256':state.construction_state['train_artifact']['sha256']}
    if marker in state.construction_state['consumed']:raise ContractError('construction stage already consumed indexed supervision')
    state.construction_state['consumed'].append(marker)


def opponent(state,profile,purpose):
    from .agent_registry import OpponentRegistry
    from .opponent_pool import FrozenOpponent
    from .group_runner import profile_deck
    registry=OpponentRegistry(state.data_index.root/'opponents',state.assets.root)
    env=registry.runtime_environment(5);registry.environment(env)
    own,other=(profile_deck(profile,p) for p in (0,1))
    own_id='actor-'+digest(own.to_dict())[:24];other_id='opponent-'+purpose
    for name,deck in ((own_id,own),(other_id,other)):
        registry.import_deck({'deck_id':name,'environment_id':env['environment_id'],'source':'engineering_fixture','format':'json','content':deck.to_dict()})
    registry.register_opponent({'opponent_id':purpose,'deck_id':other_id,'controller':'rule_baseline','provider':'local-python',
                                'model':'no-llm','driver_version':state.row['recipe'][purpose]['opponent']})
    return FrozenOpponent(registry,purpose,own_id,1)


def ingest_episode(state,episode):
    purpose=episode['purpose'];binding=episode['summary'].get('opponent_binding')
    if purpose not in ('train','validation') or not binding:raise ContractError('course episode lacks actual registered opponent')
    ident='duel-'+purpose+'-'+binding['own_deck_sha256'][:24]
    freeze(state,ident,purpose,'duel',opponents=(binding,))
    ordinal=sum(m['event_id']==state.event_id() for m in state.data_marks)
    artifact=state.event_id()+'-'+purpose+'-'+str(ordinal)
    state.data_index.ingest_episode(ident,artifact,episode)
    if purpose=='train':state.data_index.admit_episode(artifact,episode)
    return artifact


def evaluate(state,generation):
    import torch
    from torch.nn import functional as F
    cfg=inputs(state.row['recipe'],state.task);task=cfg['validation_task']
    data=state.data_index.artifact('build-labels-validation')['payload']
    from .semantic_training import validate
    validate(task,state.assets,data,for_training=False)
    # The train network's identity table cannot silently grow for evaluation.
    # Validation uses the same pool; actual held-out lists are constrained apart.
    if task.pool!=state.task.pool:raise ContractError('validation vocabulary requires an explicit model migration')
    metrics={}
    for role,model in state.builder.models.items():
        model.eval()
        with torch.no_grad():
            if role=='build_goal':
                logits=model(state.builder.encoder.batch(task,[DeckParts.from_dict(r['deck']) for r in data['goals']]))
                metrics['goal_bce']=float(F.binary_cross_entropy_with_logits(logits,torch.tensor([r['label'] for r in data['goals']])))
            else:
                logits=model(state.builder.encoder.batch(task,[DeckParts.from_dict(r[k]) for r in data['pairs'] for k in ('better','worse')])).reshape(-1,2)
                metrics['explicit_preference_pair_accuracy']=float((logits[:,0]>logits[:,1]).float().mean())
    marker={'event_id':state.event_id(),'partition':'construction_validation','task_sha256':task.sha256,
            'artifact_id':'build-labels-validation','metrics':metrics}
    state.construction_state['validation'].append(marker)
    return dict(marker,training_labels_created=False,competitive_ability_validated=False)


def validate_state(state,*,artifacts=False):
    from .local_training import run_path
    from .training_runner import read_artifact
    cfg=inputs(state.row['recipe'],state.task);warm='bootstrap' in state.consumed
    if not warm:
        if state.data_index is not None or state.construction_state is not None:raise ContractError('untrained course cannot claim committed data')
        return
    saved=fields(state.construction_state,{'binding_sha256','train_artifact','consumed','validation'})
    if saved['binding_sha256']!=cfg['binding_sha256'] or state.data['source']!=SOURCE:raise ContractError('semantic course source differs')
    admission(state)
    held=state.data_index.artifact('build-labels-validation')
    if held['purpose']!='validation':raise ContractError('semantic held-out split changed')
    expected=[('bootstrap',r) for r in ('build_goal','build_optimizer')]
    expected += [(e,r) for e in state.consumed[1:] for r in ('build_goal','build_optimizer') if e.endswith('-'+r)]
    if [(m['event_id'],m['role']) for m in saved['consumed']]!=expected:raise ContractError('semantic consumption cursor differs')
    for m in saved['consumed']:
        if (m['partition']!='construction_train' or m['supervision_sha256']!=state.data['supervision_sha256']
            or m['artifact_sha256']!=saved['train_artifact']['sha256']):raise ContractError('semantic consumed data binding differs')
    if [m['event_id'] for m in saved['validation']]!=[e for e in state.consumed if e.endswith('-evaluate')]:
        raise ContractError('semantic validation cursor differs')
    for m in state.data_marks:
        if 'indexed_artifact_id' not in m:raise ContractError('schema4 episode has no index receipt')
        a=state.data_index.artifact(m['indexed_artifact_id'])
        if a['purpose']!=m['partition']:raise ContractError('committed indexed episode purpose differs')
    if state.data_index.summary()['artifacts']!=2+len(state.data_marks):raise ContractError('index contains uncommitted or missing data')
    if artifacts:
        run=run_path(state.state_root,state.row['run_id']);a=read_artifact(run,saved['train_artifact'])
        if a!={'kind':'private-semantic-supervision','binding_sha256':cfg['binding_sha256'],'data':state.data}:
            raise ContractError('semantic checkpoint disagrees with persisted training labels')
        for mark in state.data_marks:
            trace=read_artifact(run,mark['private_audit'])
            if trace['kind']!='registered-opponent-private-replay-v1' or trace['resources']!=state.assets.receipt:
                raise ContractError('course private audit resource binding differs')
