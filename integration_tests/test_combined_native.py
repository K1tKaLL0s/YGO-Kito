"""Catalog recall -> conditional conjunctive CB -> real model update/restore."""
import copy,json,tempfile,unittest
from pathlib import Path

from ygo_kito.build_contracts import BuildTask,DeckParts,digest
from ygo_kito.build_pipeline import BuildAssets,goal_candidates
from ygo_kito.build_semantics import route_task
from ygo_kito.build_training import BuildTrainer,BuildTrainingConfig,binding_for,save_checkpoint,load_checkpoint,supervision_projection
from ygo_kito.catalog_search import CatalogQuery,recall
from ygo_kito.data_isolation import DataIndex
from ygo_kito.duel_model import parameter_digest
from ygo_kito.route_search import replay_discovered_goal,resolved_chain_cards
from ygo_kito.semantic_training import dataset,validate
from ygo_kito.validation import ContractError,read_json
from ygo_kito.coordinator import Coordinator
from ygo_kito.coord_contracts import FeedbackPolicy
from ygo_kito.model_group import call

ROOT=Path(__file__).resolve().parents[1]


class CombinedNativeObjectiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.folder=Path(cls.temp.name)
        cls.assets=BuildAssets(ROOT/'.cache');cls.task=BuildTask.from_dict(read_json(ROOT/'configs/build-combined-native-v4.json'))
        cls.data=dataset(cls.task,cls.assets)
        cls.index=DataIndex(cls.folder/'index')
        cls.index.freeze({'dataset_id':'train','experiment_id':'engineering-combined','purpose':'train','family':'construction',
                          'versions':cls.task.environment['versions'],'opponents':[],'task_sha256':cls.task.sha256})
        cls.index.ingest_construction('train','labels',cls.task,cls.assets,cls.data,seeds=())
        cls.admission=cls.index.admit_construction('labels',cls.task,cls.data)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_public_catalog_evidence_and_actual_self_cost_chain_resolution_and_xyz(self):
        hits=recall(self.task,self.assets,CatalogQuery(theme_terms=('救援猫',),effect_terms=('特殊召唤',),context_terms=('兽族',),limit=32))
        cat=next(h for h in hits if h['card_id']==14878871)
        self.assertTrue(cat['axis_matches']['theme']);self.assertIsNotNone(cat['source']['script_sha256'])
        self.assertIn('lexical-and-static-fact',cat['semantic_inference'])
        for row in (r for r in self.data['goals'] if r['label']==1):
            combined=row['evidence'];self.assertEqual(combined['status'],'constraints_and_route_verified')
            native=combined['native_route'];events=native['route_evidence']['core_event_audit_not_policy_input']
            cost=next(i for i,e in enumerate(events) if e['kind']==50 and e.get('public_card')==14878871 and e['to_zone']==16 and e['reason']&128)
            resolved=next(i for i,e in enumerate(events) if e['kind']==73)
            self.assertLess(cost,resolved);self.assertIn(14878871,resolved_chain_cards(events))
            self.assertIn(63,native['core_event_kinds'])
            self.assertFalse(native['route_evidence']['exploration']['prewritten_route_supplied'])
            self.assertTrue(replay_discovered_goal(route_task(self.task),DeckParts.from_dict(row['deck']),self.assets,native,
                          required_activations=(14878871,),required_chain_resolutions=(14878871,))['replay_verified'])

    def test_both_independent_models_update_and_restored_next_batch_is_identical(self):
        trainer=BuildTrainer(self.task,self.assets,BuildTrainingConfig());first=trainer.step(self.data,data_admission=self.admission)
        self.assertTrue(all(u['changed_parameter_elements']>0 and u['head_delta_l2']>0 for u in first))
        binding=binding_for(self.task,self.assets,self.data);path=save_checkpoint(trainer,self.folder,'combined',binding)
        restored=load_checkpoint(path,self.assets,binding)
        self.assertEqual(trainer.step(self.data,data_admission=self.admission),restored.step(self.data,data_admission=self.admission))
        for role in trainer.models:self.assertEqual(parameter_digest(trainer.models[role]),parameter_digest(restored.models[role]))

    def test_independent_real_handoffs_keep_identical_ledger_identity_without_nested_timing(self):
        models=BuildTrainer(self.task,self.assets,BuildTrainingConfig()).models
        versions={r:parameter_digest(m) for r,m in models.items()};values=[];ledgers=[]
        for i in range(2):
            host=Coordinator(self.folder/f'conjunctive-{i}.sqlite3',FeedbackPolicy(),role='coordinator',source='real_engine',assets=self.assets,create=True)
            values.append(call(host,'handoff.submit',{'candidate_id':'same-goal','parent_candidate_id':None,'task':self.task.to_dict(),
                          'deck':self.data['goals'][0]['deck'],'build_models':versions}))
            ledgers.append(host.state_digest())
        self.assertEqual(values[0],values[1]);self.assertEqual(*ledgers)
        self.assertNotIn('elapsed_seconds',json.dumps(values[0]['validation']))

    def test_resolved_goal_cannot_be_laundered_from_just_a_matching_final_summon(self):
        raw=self.task.to_dict();raw['goal']['required_chain_resolutions']=[78156759];wrong=BuildTask.from_dict(raw)
        data=copy.deepcopy(self.data);data['task_sha256']=wrong.sha256
        for row in data['goals']:
            if row['label']!=1:continue
            p=row['evidence'];p['task_sha256']=p['constraints']['task_sha256']=wrong.sha256
            p['native_route']['route_evidence']['exploration']['required_chain_resolutions']=[78156759]
        data['supervision_sha256']=digest(supervision_projection(data))
        with self.assertRaisesRegex(ContractError,'did not reproduce'):validate(wrong,self.assets,data)

    def test_optimizer_comparisons_cannot_skip_the_actual_goal_witness(self):
        verified={digest(r['deck']) for r in self.data['goals'] if r['label']==1}
        other=next(d for d in goal_candidates(self.task,self.assets) if digest(d.to_dict()) not in verified)
        data=copy.deepcopy(self.data);data['pairs'][0]['better']=other.to_dict();data['supervision_sha256']=digest(supervision_projection(data))
        with self.assertRaisesRegex(ContractError,'both sides'):validate(self.task,self.assets,data)
