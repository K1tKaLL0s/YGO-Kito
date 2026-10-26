"""Immutable split index for local private engineering data and model admission.

Names and file paths cannot relabel an episode or an opponent version. This
is a trusted-host integrity boundary, not protection against a host rewriting
its own database. Private payloads remain local; public reports use aggregates.
"""
from dataclasses import dataclass
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import json
import os
import sqlite3

from .agent_registry import identifier
from .build_contracts import digest
from .contracts import Versions
from .validation import ContractError,fields,integer,array,canonical_json,read_json

APPLICATION_ID=0x59474449
PURPOSES=('train','validation','final_eval')


def validate_storage_limits(value):
    """Optional main-DB and serialized-envelope limits, not a workspace quota."""
    if value is None:return None
    d=fields(value,set(),{'max_database_bytes','max_artifact_bytes'})
    for key,n in d.items():integer(n,key,1)
    return deepcopy(d)


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
    def __init__(self,root,*,storage_limits=None):
        requested=validate_storage_limits(storage_limits)
        original=Path(root)
        if requested is not None and original.is_symlink():raise ContractError('bounded data index root symlinks unsupported')
        self.root=original.resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'data-index.sqlite3'
        if self.path.is_symlink():raise ContractError('data index symlinks unsupported')
        self.storage_policy_path=self.root/'data-storage-limits.json'
        stored=self._read_policy()
        if stored is not None:
            if requested is not None and requested!=stored['storage_limits']:
                raise ContractError('data index storage limits differ from its persistent policy')
            self._storage_limits=stored['storage_limits'];self._storage_policy_sha256=stored['policy_sha256']
        else:
            self._storage_limits=requested
            self._storage_policy_sha256=None if requested is None else digest(self._policy_body(requested))
        if self._storage_limits is not None and original.is_symlink():
            raise ContractError('bounded data index root symlinks unsupported')
        self._new_storage_policy=stored is None and requested is not None
        with self._connection() as db:
            if self._new_storage_policy:self._persist_policy()
            db.execute('BEGIN IMMEDIATE')
            db.execute(f'PRAGMA application_id={APPLICATION_ID}')
            db.execute('CREATE TABLE IF NOT EXISTS datasets(id TEXT PRIMARY KEY,payload TEXT NOT NULL,sha TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS seeds(scope TEXT,seed INTEGER,purpose TEXT,PRIMARY KEY(scope,seed))')
            db.execute('CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,dataset TEXT NOT NULL,payload TEXT NOT NULL,sha TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS contents(scope TEXT,hash TEXT,purpose TEXT,PRIMARY KEY(scope,hash))')

    @staticmethod
    def _policy_body(limits):
        return {'schema_version':1,'kind':'data-index-storage-limits-v1','storage_limits':deepcopy(limits)}

    def _read_policy(self):
        path=self.storage_policy_path
        if path.is_symlink():raise ContractError('data index storage policy symlinks unsupported')
        if not path.exists():return None
        value=fields(read_json(path),{'schema_version','kind','storage_limits','policy_sha256'})
        limits=validate_storage_limits(value['storage_limits'])
        if (type(value['schema_version']) is not int or value['schema_version']!=1 or limits is None or
                value['kind']!='data-index-storage-limits-v1' or
                value['policy_sha256']!=digest(self._policy_body(limits))):
            raise ContractError('data index storage policy hash/schema differs')
        return deepcopy(value)

    def _persist_policy(self):
        value=dict(self._policy_body(self._storage_limits),policy_sha256=self._storage_policy_sha256)
        with self.storage_policy_path.open('x',encoding='utf-8') as output:
            output.write(canonical_json(value)+'\n');output.flush();os.fsync(output.fileno())
        self._new_storage_policy=False

    @property
    def storage_limits(self):
        self._check_policy()
        return deepcopy(self._storage_limits)

    @property
    def storage_policy_sha256(self):
        self._check_policy()
        return self._storage_policy_sha256

    def _check_policy(self):
        stored=self._read_policy()
        if stored is None:
            if self._storage_limits is not None and not self._new_storage_policy:
                raise ContractError('data index persistent storage policy disappeared')
        elif (stored['storage_limits']!=self._storage_limits or
                stored['policy_sha256']!=self._storage_policy_sha256):
            raise ContractError('data index storage policy changed after opening; reopen explicitly')

    def _configure_storage(self,db):
        if self._storage_limits is None:return
        if str(db.execute('PRAGMA journal_mode').fetchone()[0]).lower()!='delete':
            raise ContractError('bounded data index requires existing DELETE journal mode; no conversion performed')
        db.execute('PRAGMA temp_store=MEMORY')
        if db.execute('PRAGMA temp_store').fetchone()[0]!=2:
            raise ContractError('SQLite did not accept memory-only temporary storage')
        maximum=self._storage_limits.get('max_database_bytes')
        if maximum is None:return
        page_size=db.execute('PRAGMA page_size').fetchone()[0]
        pages=maximum//page_size
        if (pages<1 or db.execute('PRAGMA page_count').fetchone()[0]>pages or
                self.path.stat().st_size>maximum):
            raise ContractError('data index main database already exceeds its configured page/byte cap')
        actual=db.execute(f'PRAGMA max_page_count={pages}').fetchone()[0]
        if actual!=pages:raise ContractError('SQLite max_page_count does not match the requested floor byte cap')

    @contextmanager
    def _connection(self):
        self._check_policy()
        if self.path.is_symlink():raise ContractError('data index symlinks unsupported')
        db=sqlite3.connect(self.path)
        try:
            app=db.execute('PRAGMA application_id').fetchone()[0]
            if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() and app!=APPLICATION_ID:
                raise ContractError('file is not a data isolation index')
            self._configure_storage(db)
            with db:yield db
        except sqlite3.Error as error:
            code=getattr(error,'sqlite_errorcode',None)
            if self._storage_limits is not None and code is not None and code&255==sqlite3.SQLITE_FULL:
                raise ContractError('data index storage exhausted (SQLITE_FULL); transaction rolled back') from error
            raise
        finally:db.close()

    def _insert(self,db,statement,values,serialized_envelope):
        maximum=None if self._storage_limits is None else self._storage_limits.get('max_artifact_bytes')
        if maximum is not None and len(serialized_envelope.encode('utf-8'))>maximum:
            raise ContractError('data index serialized envelope exceeds max_artifact_bytes')
        db.execute(statement,values)

    def storage_status(self):
        """Main DB cap only; rollback journals and the whole peak stay separate."""
        with self._connection() as db:
            page_size=db.execute('PRAGMA page_size').fetchone()[0]
            page_count=db.execute('PRAGMA page_count').fetchone()[0]
            max_pages=db.execute('PRAGMA max_page_count').fetchone()[0]
            journal=db.execute('PRAGMA journal_mode').fetchone()[0]
            temp_store=db.execute('PRAGMA temp_store').fetchone()[0]
        maximum=None if self._storage_limits is None else self._storage_limits.get('max_database_bytes')
        return {'storage_limits':self.storage_limits,'policy_sha256':self.storage_policy_sha256,
            'main_database_bytes':self.path.stat().st_size,'page_size':page_size,'page_count':page_count,
            'sqlite_max_page_count':max_pages,'effective_max_database_bytes':None if maximum is None else max_pages*page_size,
            'journal_mode':journal,'temp_store':temp_store,'deletion_enabled':False,
            'journal_temporary_and_whole_workspace_peak_verified':False}

    def dataset(self,dataset_id):
        identifier(dataset_id)
        with self._connection() as db:row=db.execute('SELECT payload,sha FROM datasets WHERE id=?',(dataset_id,)).fetchone()
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
        with self._connection() as db:
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
            encoded=json.dumps(d,sort_keys=True)
            self._insert(db,'INSERT INTO datasets VALUES(?,?,?)',(d['dataset_id'],encoded,digest(d)),encoded)
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
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT payload FROM artifacts WHERE id=?',(artifact_id,)).fetchone()
            if old:
                if json.loads(old[0])!=record:raise ContractError('artifact ID cannot be overwritten')
                return record
            for key in content_keys or [record['payload_sha256']]:
                old=db.execute('SELECT purpose FROM contents WHERE scope=? AND hash=?',(scope,key)).fetchone()
                if old and old[0]!=dataset['purpose']:raise ContractError('same payload cannot be relabeled into another split')
                values=(scope,key,dataset['purpose'])
                self._insert(db,'INSERT OR IGNORE INTO contents VALUES(?,?,?)',values,
                    json.dumps(dict(zip(('scope','hash','purpose'),values)),sort_keys=True))
            for seed in seeds:
                integer(seed,'private data seed',0,2**32-8)
                old=db.execute('SELECT purpose FROM seeds WHERE scope=? AND seed=?',(scope,seed)).fetchone()
                if old and old[0]!=dataset['purpose']:raise ContractError('physical game seed crosses data splits')
                values=(scope,seed,dataset['purpose'])
                self._insert(db,'INSERT OR IGNORE INTO seeds VALUES(?,?,?)',values,
                    json.dumps(dict(zip(('scope','seed','purpose'),values)),sort_keys=True))
            encoded=json.dumps(record,sort_keys=True)
            self._insert(db,'INSERT INTO artifacts VALUES(?,?,?,?)',(artifact_id,dataset['dataset_id'],encoded,digest(record)),encoded)
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
        with self._connection() as db:row=db.execute('SELECT payload,sha FROM artifacts WHERE id=?',(artifact_id,)).fetchone()
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
        with self._connection() as db:
            datasets=[json.loads(r[0]) for r in db.execute('SELECT payload FROM datasets')]
            artifacts=[json.loads(r[0]) for r in db.execute('SELECT payload FROM artifacts')]
        return {'datasets':len(datasets),'artifacts':len(artifacts),
                'by_purpose':{p:sum(a['purpose']==p for a in artifacts) for p in PURPOSES},
                'private_payloads_in_summary':False,'formal_training_ready':False}
