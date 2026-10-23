"""Immutable split index for local private engineering data and model admission.

Names and file paths cannot relabel an episode or an opponent version. This
is a trusted-host integrity boundary, not protection against a host rewriting
its own database. Private payloads remain local; public reports use aggregates.
"""
from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3

from .agent_registry import identifier
from .build_contracts import digest
from .contracts import Versions
from .validation import ContractError,fields,integer,array

APPLICATION_ID=0x59474449
PURPOSES=('train','validation','final_eval')


def episode_projection(episode):
    return {k:episode[k] for k in ('source','policy_version','policy_sha256','purpose','summary')}|{
        'steps':[{k:(v.to_dict() if k=='request' else v) for k,v in step.items()} for step in episode['steps']]}


def episode_digest(episode):return digest(episode_projection(episode))


def opponent_identity(binding):
    return digest({k:binding[k] for k in ('opponent_deck_content_sha256','driver_implementation_sha256','driver_version')}|
                  {'model_sha256':binding.get('model_sha256')})


@dataclass(frozen=True)
class DataAdmission:
    index: object
    artifact_id: str

    def assert_episode(self,episode):
        artifact=self.index.artifact(self.artifact_id,for_training=True)
        if artifact['family']!='duel' or artifact['payload_sha256']!=episode_digest(episode):
            raise ContractError('indexed episode differs from admitted training data')


@dataclass(frozen=True)
class ConstructionAdmission:
    index: object
    artifact_id: str

    def assert_data(self,task,data):
        artifact=self.index.artifact(self.artifact_id,for_training=True)
        dataset=self.index.dataset(artifact['dataset_id'])
        if artifact['family']!='construction' or dataset['task_sha256']!=task.sha256 or artifact['payload_sha256']!=digest(data):
            raise ContractError('construction data differs from its admitted training split')


class DataIndex:
    def __init__(self,root):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'data-index.sqlite3'
        if self.path.is_symlink():raise ContractError('data index symlinks unsupported')
        with sqlite3.connect(self.path) as db:
            app=db.execute('PRAGMA application_id').fetchone()[0]
            if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() and app!=APPLICATION_ID:
                raise ContractError('file is not a data isolation index')
            db.execute(f'PRAGMA application_id={APPLICATION_ID}')
            db.execute('CREATE TABLE IF NOT EXISTS datasets(id TEXT PRIMARY KEY,payload TEXT NOT NULL,sha TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS seeds(scope TEXT,seed INTEGER,purpose TEXT,PRIMARY KEY(scope,seed))')
            db.execute('CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,dataset TEXT NOT NULL,payload TEXT NOT NULL,sha TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS contents(scope TEXT,hash TEXT,purpose TEXT,PRIMARY KEY(scope,hash))')

    def dataset(self,dataset_id):
        identifier(dataset_id)
        with sqlite3.connect(self.path) as db:row=db.execute('SELECT payload,sha FROM datasets WHERE id=?',(dataset_id,)).fetchone()
        if row is None:raise ContractError('dataset not found')
        value=json.loads(row[0])
        if digest(value)!=row[1] or value['dataset_id']!=dataset_id:raise ContractError('immutable dataset binding changed')
        return value

    def freeze(self,value):
        d=dict(fields(value,{'dataset_id','experiment_id','purpose','family','versions','opponents','task_sha256'}))
        identifier(d['dataset_id']);identifier(d['experiment_id']);Versions.from_dict(d['versions'])
        if d['purpose'] not in PURPOSES or d['family'] not in ('duel','construction'):raise ContractError('unknown data split/family')
        if d['family']=='construction':
            if not isinstance(d['task_sha256'],str) or len(d['task_sha256'])!=64:raise ContractError('construction task hash required')
        elif d['task_sha256'] is not None:raise ContractError('duel data cannot claim a construction goal')
        opponents=array(d['opponents'],'frozen data opponents')
        if not (0 if d['family']=='construction' else 1)<=len(opponents)<=32:raise ContractError('bounded actual opponent versions required')
        identities=[opponent_identity(o) for o in opponents]
        if len(identities)!=len(set(identities)):raise ContractError('opponent aliases repeat the same actual version')
        d=json.loads(json.dumps(d))
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT payload FROM datasets WHERE id=?',(d['dataset_id'],)).fetchone()
            if old:
                if json.loads(old[0])!=d:raise ContractError('dataset already frozen with another binding')
                return d
            for raw, in db.execute('SELECT payload FROM datasets'):
                other=json.loads(raw)
                if other['experiment_id']==d['experiment_id'] and other['purpose']!=d['purpose']:
                    if set(identities)&{opponent_identity(o) for o in other['opponents']}:
                        raise ContractError('same actual opponent version crosses train/validation/final splits')
            db.execute('INSERT INTO datasets VALUES(?,?,?)',(d['dataset_id'],json.dumps(d,sort_keys=True),digest(d)))
        return d

    def _store(self,artifact_id,dataset,payload,seeds,*,content_keys=None):
        identifier(artifact_id)
        # Exclude cosmetic card-pool/adapter labels from the physical RNG
        # scope: changing an ID or protocol label cannot recycle held-out seeds.
        scope=digest({k:dataset['versions'][k] for k in ('core','scripts','cards','protocol','banlist')})
        record={'artifact_id':artifact_id,'dataset_id':dataset['dataset_id'],'dataset_sha256':digest(dataset),
                'purpose':dataset['purpose'],'family':dataset['family'],'payload':payload,'payload_sha256':digest(payload)}
        # DTOs may contain tuples; compare the persisted JSON representation on
        # retries instead of rejecting its equivalent list representation.
        record=json.loads(json.dumps(record,sort_keys=True))
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT payload FROM artifacts WHERE id=?',(artifact_id,)).fetchone()
            if old:
                if json.loads(old[0])!=record:raise ContractError('artifact ID cannot be overwritten')
                return record
            for key in content_keys or [record['payload_sha256']]:
                old=db.execute('SELECT purpose FROM contents WHERE scope=? AND hash=?',(scope,key)).fetchone()
                if old and old[0]!=dataset['purpose']:raise ContractError('same payload cannot be relabeled into another split')
                db.execute('INSERT OR IGNORE INTO contents VALUES(?,?,?)',(scope,key,dataset['purpose']))
            for seed in seeds:
                integer(seed,'private data seed',0,2**32-8)
                old=db.execute('SELECT purpose FROM seeds WHERE scope=? AND seed=?',(scope,seed)).fetchone()
                if old and old[0]!=dataset['purpose']:raise ContractError('physical game seed crosses data splits')
                db.execute('INSERT OR IGNORE INTO seeds VALUES(?,?,?)',(scope,seed,dataset['purpose']))
            db.execute('INSERT INTO artifacts VALUES(?,?,?,?)',(artifact_id,dataset['dataset_id'],json.dumps(record,sort_keys=True),digest(record)))
        return record

    def ingest_episode(self,dataset_id,artifact_id,episode):
        dataset=self.dataset(dataset_id);summary=episode['summary']
        if (dataset['family']!='duel' or episode['purpose']!=dataset['purpose'] or summary['purpose']!=dataset['purpose']
            or summary.get('opponent_binding') not in dataset['opponents'] or not episode['steps']):
            raise ContractError('episode purpose or actual frozen opponent differs from dataset')
        if any(step['request'].context.versions!=Versions.from_dict(dataset['versions']) for step in episode['steps']):
            raise ContractError('episode environment differs from dataset')
        result=self._store(artifact_id,dataset,episode_projection(episode),(summary['seed_audit_only'],))
        return result

    def ingest_construction(self,dataset_id,artifact_id,task,assets,data,*,seeds):
        from .build_training import validate_supervision
        dataset=self.dataset(dataset_id)
        if (dataset['family']!='construction' or dataset['task_sha256']!=task.sha256 or dataset['versions']!=task.environment['versions']):
            raise ContractError('construction task or version differs from dataset')
        from .semantic_training import SOURCE,validate
        if data['source']==SOURCE:
            validate(task,assets,data,for_training=False)
            if data['purpose']!=dataset['purpose']:raise ContractError('construction payload purpose differs from frozen split')
        else:validate_supervision(task,assets,data)
        # Identity removes task/constraint display IDs. Individual examples are
        # checked, so adding more examples cannot conceal a shared held-out row.
        goal=json.loads(json.dumps(task.goal))
        for name in ('constraints','preferences'):
            if name in goal:goal[name]=sorted([{k:v for k,v in item.items() if k!='id'} for item in goal[name]],key=digest)
        intent={'goal':goal,'sizes':task.sizes,'requirements':sorted(task.requirements,key=digest),'pool':task.pool}
        normalize=lambda deck:{z:sorted(v) for z,v in deck.items()}
        keys=[digest({'intent':intent,'example':{'deck':normalize(row['deck']),'label':row['label']}}) for row in data['goals']]
        keys += [digest({'intent':intent,'pair':{k:normalize(row[k]) for k in ('better','worse')}}) for row in data['pairs']]
        # A held-out list stays held out even under a genuinely different goal.
        decks=[row['deck'] for row in data['goals']]+[row[k] for row in data['pairs'] for k in ('better','worse')]
        keys += [digest({'construction_deck':normalize(deck)}) for deck in decks]
        return self._store(artifact_id,dataset,data,seeds,content_keys=keys)

    def admit_construction(self,artifact_id,task,data):
        admission=ConstructionAdmission(self,artifact_id);admission.assert_data(task,data)
        return admission

    def artifact(self,artifact_id,*,for_training=False):
        identifier(artifact_id)
        with sqlite3.connect(self.path) as db:row=db.execute('SELECT payload,sha FROM artifacts WHERE id=?',(artifact_id,)).fetchone()
        if row is None:raise ContractError('data artifact not found')
        value=json.loads(row[0]);dataset=self.dataset(value['dataset_id'])
        if (digest(value)!=row[1] or value['dataset_sha256']!=digest(dataset) or value['purpose']!=dataset['purpose']
            or value['payload_sha256']!=digest(value['payload'])):raise ContractError('artifact or frozen binding was modified')
        if for_training and value['purpose']!='train':raise ContractError('held-out data cannot be admitted for model training')
        return value

    def admit_episode(self,artifact_id,episode):
        admission=DataAdmission(self,artifact_id);admission.assert_episode(episode)
        episode['_data_admission']=admission
        return episode

    def summary(self):
        with sqlite3.connect(self.path) as db:
            datasets=[json.loads(r[0]) for r in db.execute('SELECT payload FROM datasets')]
            artifacts=[json.loads(r[0]) for r in db.execute('SELECT payload FROM artifacts')]
        return {'datasets':len(datasets),'artifacts':len(artifacts),
                'by_purpose':{p:sum(a['purpose']==p for a in artifacts) for p in PURPOSES},
                'private_payloads_in_summary':False,'formal_training_ready':False}
