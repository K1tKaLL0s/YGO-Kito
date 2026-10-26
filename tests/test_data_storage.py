"""Small real SQLite limits/rollback tests; no model/core/training or large data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tests.fixtures import request
from ygo_kito.build_contracts import digest
from ygo_kito.data_isolation import DataIndex, validate_storage_limits
from ygo_kito.validation import ContractError


def dataset(name='train',purpose='train'):
    return {'dataset_id':name,'experiment_id':'storage-fixture','purpose':purpose,'family':'construction',
        'versions':request()['context']['versions'],'opponents':[],'task_sha256':'a'*64}


def envelope(artifact_id,data,payload):
    return {'artifact_id':artifact_id,'dataset_id':data['dataset_id'],'dataset_sha256':digest(data),
        'purpose':data['purpose'],'family':data['family'],'payload':payload,'payload_sha256':digest(payload)}


class DataStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        db=sqlite3.connect(':memory:')
        self.page_size=db.execute('PRAGMA page_size').fetchone()[0];db.close()

    def bounded(self,name='bounded',pages=16,artifact_bytes=200000):
        return DataIndex(self.root/name,storage_limits={'max_database_bytes':pages*self.page_size+123,
            'max_artifact_bytes':artifact_bytes})

    @staticmethod
    def counts(index):
        with index._connection() as db:
            return {table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                    for table in ('datasets','artifacts','seeds','contents')}

    def test_default_api_has_no_policy_and_preserves_unbounded_existing_semantics(self):
        index=DataIndex(self.root/'legacy')
        self.assertFalse(index.storage_policy_path.exists())
        self.assertIsNone(index.storage_limits);self.assertIsNone(index.storage_policy_sha256)
        d=index.freeze(dataset())
        index._store('legacy-artifact',d,{'blob':'x'*20000},(7,))
        self.assertEqual(index.summary()['artifacts'],1)
        self.assertEqual(DataIndex(index.root).artifact('legacy-artifact')['payload'],{'blob':'x'*20000})
        self.assertIsNone(index.storage_status()['effective_max_database_bytes'])

    def test_limits_persist_inherit_and_are_applied_on_every_controlled_connection(self):
        index=self.bounded();status=index.storage_status()
        self.assertEqual(status['effective_max_database_bytes'],16*self.page_size)
        self.assertEqual(status['journal_mode'],'delete');self.assertEqual(status['temp_store'],2)
        self.assertFalse(status['journal_temporary_and_whole_workspace_peak_verified'])
        self.assertFalse(status['deletion_enabled'])
        for _ in range(3):
            with index._connection() as db:
                self.assertEqual(db.execute('PRAGMA max_page_count').fetchone()[0],16)
                self.assertEqual(db.execute('PRAGMA temp_store').fetchone()[0],2)
        inherited=DataIndex(index.root)
        self.assertEqual(inherited.storage_limits,index.storage_limits)
        self.assertEqual(inherited.storage_policy_sha256,index.storage_policy_sha256)
        same=DataIndex(index.root,storage_limits=index.storage_limits)
        self.assertEqual(same.storage_status()['sqlite_max_page_count'],16)
        changed=index.storage_limits;changed['max_database_bytes']+=self.page_size
        with self.assertRaisesRegex(ContractError,'persistent policy'):DataIndex(index.root,storage_limits=changed)
        copy=index.storage_limits;copy['max_artifact_bytes']=1
        self.assertNotEqual(copy,index.storage_limits)

    def test_real_sqlite_full_rolls_back_artifact_seed_content_and_split_state(self):
        index=self.bounded();train=index.freeze(dataset())
        before=self.counts(index)
        with self.assertRaisesRegex(ContractError,'SQLITE_FULL'):
            index._store('cannot-fit',train,{'blob':'x'*120000},(123,))
        self.assertEqual(self.counts(index),before)
        self.assertLessEqual(index.path.stat().st_size,16*self.page_size)
        heldout=index.freeze(dataset('heldout','validation'))
        index._store('heldout-small',heldout,{'value':'small'},(123,))
        before=self.counts(index)
        with self.assertRaisesRegex(ContractError,'physical game seed'):
            index._store('train-must-stay-heldout',train,{'different':'payload'},(123,))
        self.assertEqual(self.counts(index),before)
        self.assertEqual(index.summary()['by_purpose'],{'train':0,'validation':1,'final_eval':0})
        with index._connection() as db:self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_exact_stored_utf8_envelope_cap_includes_metadata_and_unicode_encoding(self):
        d=dataset();payload={'unicode':'牌'*100}
        encoded=json.dumps(envelope('allowed',d,payload),sort_keys=True)
        maximum=len(encoded.encode('utf-8'))
        self.assertGreater(maximum,len(json.dumps(payload,sort_keys=True).encode('utf-8')))
        index=DataIndex(self.root/'exact',storage_limits={'max_artifact_bytes':maximum})
        frozen=index.freeze(d);index._store('allowed',frozen,payload,(7,))
        with index._connection() as db:
            actual=db.execute('SELECT payload FROM artifacts WHERE id=?',('allowed',)).fetchone()[0]
        self.assertEqual(actual,encoded)
        self.assertEqual(len(actual.encode('utf-8')),maximum)
        before=self.counts(index)
        with self.assertRaisesRegex(ContractError,'max_artifact_bytes'):
            index._store('another',frozen,{'unicode':'牌'*100+'x'},(8,))
        self.assertEqual(self.counts(index),before)

    def test_dataset_insert_envelope_is_also_limited(self):
        encoded=json.dumps(dataset(),sort_keys=True)
        index=DataIndex(self.root/'small-envelope',storage_limits={'max_artifact_bytes':len(encoded.encode())-1})
        with self.assertRaisesRegex(ContractError,'max_artifact_bytes'):index.freeze(dataset())
        self.assertEqual(self.counts(index),{'datasets':0,'artifacts':0,'seeds':0,'contents':0})

    def test_existing_oversized_database_is_rejected_without_policy_or_data_rewrite(self):
        index=DataIndex(self.root/'existing');d=index.freeze(dataset())
        index._store('existing-large',d,{'blob':'x'*20000},(7,))
        before=hashlib.sha256(index.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ContractError,'already exceeds'):
            DataIndex(index.root,storage_limits={'max_database_bytes':2*self.page_size})
        self.assertEqual(hashlib.sha256(index.path.read_bytes()).hexdigest(),before)
        self.assertFalse(index.storage_policy_path.exists())
        self.assertEqual(index.summary()['artifacts'],1)

    def test_wal_is_rejected_without_conversion_and_legacy_wal_remains_usable(self):
        index=DataIndex(self.root/'wal');index.freeze(dataset())
        db=sqlite3.connect(index.path)
        self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone()[0],'wal');db.close()
        with self.assertRaisesRegex(ContractError,'DELETE journal'):
            DataIndex(index.root,storage_limits={'max_database_bytes':32*self.page_size})
        self.assertFalse(index.storage_policy_path.exists())
        db=sqlite3.connect(index.path)
        self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'wal');db.close()
        self.assertEqual(index.summary()['datasets'],1)

    def test_policy_tamper_disappearance_and_symlinks_fail_closed(self):
        index=self.bounded();original=index.storage_policy_path.read_text()
        policy=json.loads(original);policy['storage_limits']['max_artifact_bytes']+=1
        index.storage_policy_path.write_text(json.dumps(policy))
        with self.assertRaisesRegex(ContractError,'policy hash'):index.summary()
        policy['policy_sha256']=digest({k:v for k,v in policy.items() if k!='policy_sha256'})
        index.storage_policy_path.write_text(json.dumps(policy))
        with self.assertRaisesRegex(ContractError,'changed after opening'):index.storage_status()
        index.storage_policy_path.write_text(original)
        copy=self.root/'saved-policy.json';copy.write_text(original)
        index.storage_policy_path.unlink()
        with self.assertRaisesRegex(ContractError,'disappeared'):index.summary()
        index.storage_policy_path.symlink_to(copy)
        with self.assertRaisesRegex(ContractError,'symlinks'):DataIndex(index.root)
        alias=self.root/'bounded-root-link';alias.symlink_to(index.root,target_is_directory=True)
        with self.assertRaises(ContractError):DataIndex(alias)

    def test_limits_validation_and_in_memory_policy_edits_cannot_bypass_persistence(self):
        for value in ({'other':1},{'max_database_bytes':0},{'max_artifact_bytes':True},[],{'max_database_bytes':1.2}):
            with self.subTest(value=value),self.assertRaises(ContractError):validate_storage_limits(value)
        index=self.bounded()
        index._storage_limits['max_artifact_bytes']+=1
        with self.assertRaisesRegex(ContractError,'changed after opening'):index.artifact('missing')
        plain=DataIndex(self.root/'later-policy')
        bounded=DataIndex(plain.root,storage_limits={'max_artifact_bytes':2000})
        with self.assertRaisesRegex(ContractError,'changed after opening'):plain.summary()
        self.assertEqual(DataIndex(plain.root).storage_limits,bounded.storage_limits)


if __name__=='__main__':unittest.main()
