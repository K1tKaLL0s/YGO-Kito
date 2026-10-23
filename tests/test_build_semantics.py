"""Constraint language and split-integrity contracts, not real game tests."""
import copy,json,sqlite3,tempfile,unittest
from unittest.mock import patch
from pathlib import Path

from ygo_kito.build_contracts import BuildTask
from ygo_kito.build_semantics import matches,validate_predicate
from ygo_kito.contracts import Versions
from dataclasses import asdict
from ygo_kito.data_isolation import DataIndex
from ygo_kito.validation import ContractError

TASK=json.loads((Path(__file__).resolve().parents[1]/'configs/build-semantic-engineering-v4.json').read_text())

class SemanticContracts(unittest.TestCase):
    def test_custom_course_cannot_relabel_current_resources_as_a_historical_period(self):
        from ygo_kito.semantic_curriculum import inputs
        cfg=json.loads((Path(__file__).resolve().parents[1]/'configs/construction-semantic-v1.json').read_text())
        cfg['period_id']='2022-07'
        with patch('ygo_kito.semantic_curriculum.read_json',return_value=cfg):
            with self.assertRaisesRegex(ContractError,'historical'):
                inputs({'construction_curriculum':'configs/construction-semantic-v1.json'},BuildTask.from_dict(TASK))

    def test_general_goal_has_no_synthetic_summon_or_opening_condition(self):
        t=BuildTask.from_dict(TASK);self.assertEqual(BuildTask.from_dict(t.to_dict()),t)
        self.assertNotIn('card_id',t.goal);self.assertNotIn('starting_conditions',t.goal)
        for mutation in ('schema','hidden-field','unknown-predicate','empty','mask-bool','duplicate-id','unknown-zone','weight','foreign-card'):
            v=copy.deepcopy(TASK)
            if mutation=='schema':v['schema_version']=3
            elif mutation=='hidden-field':v['goal']['seed']=7
            elif mutation=='unknown-predicate':v['goal']['constraints'][0]['predicate']={'field':'predicted_winrate','value':99}
            elif mutation=='empty':v['goal']['constraints']=[]
            elif mutation=='mask-bool':v['goal']['constraints'][0]['predicate']={'field':'type_all','value':True}
            elif mutation=='duplicate-id':v['goal']['preferences'][0]['id']=v['goal']['constraints'][0]['id']
            elif mutation=='unknown-zone':v['goal']['constraints'][0]['zones']=['hidden-deck']
            elif mutation=='weight':v['goal']['preferences'][0]['weight']=float('inf')
            else:v['goal']['constraints'][0]['predicate']={'field':'card_ids','value':[999999999]}
            with self.subTest(mutation=mutation),self.assertRaises(ContractError):BuildTask.from_dict(v)

    def test_public_predicate_boolean_and_setcode_subtypes_are_not_name_matching(self):
        row={'id':1,'type':0x21,'setcode':0x206e<<16|0x106e,'race':0x4000,'attribute':1,'level':3}
        self.assertTrue(matches(row,{'field':'setcode','value':0x106e}))
        self.assertTrue(matches(row,{'field':'setcode','value':0x6e}))
        self.assertFalse(matches(row,{'field':'setcode','value':0x406e}))
        self.assertTrue(matches(row,{'all':[{'field':'type_all','value':1},{'not':{'field':'type_all','value':2}}]}))
        self.assertTrue(matches(row,{'any':[{'field':'attribute_any','value':2},{'field':'level_between','value':[3,4]}]}))
        p={'field':'card_ids','value':[1]}
        for _ in range(5):p={'not':p}
        with self.assertRaises(ContractError):validate_predicate(p,[1])


def opponent(deck='a',driver='x',ident='unit'):
    return {'opponent_id':ident,'opponent_deck_content_sha256':deck*64,'driver_implementation_sha256':driver*64,'driver_version':'unit-fixture'}

class DataSplitContracts(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.index=DataIndex(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def freeze(self,ident,purpose='train',binding=None):
        return self.index.freeze({'dataset_id':ident,'experiment_id':'unit-experiment','purpose':purpose,'family':'duel',
                                  'versions':asdict(Versions(*(['synthetic-unit-version']*6))),'opponents':[binding or opponent()], 'task_sha256':None})

    def test_opponent_cosmetic_renaming_does_not_create_a_new_heldout_version(self):
        self.freeze('train')
        with self.assertRaisesRegex(ContractError,'actual opponent'):self.freeze('validation','validation',opponent(ident='renamed'))
        other=self.freeze('validation','validation',opponent(deck='b'));self.assertEqual(other['purpose'],'validation')

    def test_seed_and_payload_cannot_be_relabeled_by_dataset_or_artifact_names(self):
        train=self.freeze('train');validation=self.freeze('validation','validation',opponent(deck='b'))
        self.index._store('a',train,{'synthetic':'one'},(7,))
        with self.assertRaisesRegex(ContractError,'seed'):self.index._store('b',validation,{'synthetic':'two'},(7,))
        with self.assertRaisesRegex(ContractError,'relabeled'):self.index._store('c',validation,{'synthetic':'one'},(8,))
        self.index._store('good',validation,{'synthetic':'two'},(8,))
        with self.assertRaisesRegex(ContractError,'held-out'):self.index.artifact('good',for_training=True)
        self.assertEqual(self.index.summary()['by_purpose'],{'train':1,'validation':1,'final_eval':0})

    def test_immutable_freeze_idempotency_and_database_tamper_fail_closed(self):
        ds=self.freeze('train');self.assertEqual(self.freeze('train'),ds)
        with self.assertRaises(ContractError):self.freeze('train',binding=opponent(deck='c'))
        record=self.index._store('a',ds,{'synthetic':True},(9,))
        self.assertEqual(self.index._store('a',ds,{'synthetic':True},(9,)),record)
        with self.assertRaises(ContractError):self.index._store('a',ds,{'synthetic':False},(9,))
        with sqlite3.connect(self.index.path) as db:db.execute("UPDATE datasets SET payload=? WHERE id='train'",(json.dumps(dict(ds,purpose='validation')),))
        with self.assertRaisesRegex(ContractError,'binding changed'):self.index.artifact('a')

    def test_nested_dto_tuple_json_roundtrip_is_idempotent_but_changes_still_fail(self):
        ds=self.freeze('train')
        first=self.index._store('dto',ds,{'refs':('one','two'),'nested':{'bounds':(1,3)}},())
        self.assertEqual(first,self.index._store('dto',ds,{'refs':['one','two'],'nested':{'bounds':[1,3]}},()))
        with self.assertRaisesRegex(ContractError,'overwritten'):
            self.index._store('dto',ds,{'refs':['one','different'],'nested':{'bounds':[1,3]}},())
