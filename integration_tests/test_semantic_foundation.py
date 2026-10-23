"""Real assets/core/sampling/updates: ordinary engineering lists, no user decks."""
import copy,json,sqlite3,tempfile,unittest
import hashlib
from dataclasses import asdict
from pathlib import Path
import torch

from ygo_kito.agent_registry import OpponentRegistry
from ygo_kito.build_contracts import BuildTask,DeckParts,digest
from ygo_kito.build_model import BuildEncoder,BuildModelConfig
from ygo_kito.build_pipeline import BuildAssets,alternate_build,apply_changes
from ygo_kito.build_semantics import solve_candidates,proof,replacements
from ygo_kito.build_training import BuildTrainer,BuildTrainingConfig,binding_for,save_checkpoint as save_build,load_checkpoint as load_build
from ygo_kito.cpu_training import CpuTrainer,CpuTrainingConfig,resource_binding,save_checkpoint,load_checkpoint
from ygo_kito.data_isolation import DataIndex
from ygo_kito.duel_model import DuelModelConfig,parameter_digest
from ygo_kito.effect_duel import public_card_facts
from ygo_kito.knowledge_acceptance import audit_place_calls
from ygo_kito.opponent_pool import FrozenOpponent,FrozenOpponentPool,replay_private
from ygo_kito.protocol_cases import run_protocol_case
from ygo_kito.place_classification import verify_multi_zone
from ygo_kito.semantic_training import dataset,validate
from ygo_kito.validation import ContractError

ROOT=Path(__file__).resolve().parents[1];CACHE=ROOT/'.cache'


def setup_registered(root,assets,own):
    registry=OpponentRegistry(root,CACHE);env=registry.runtime_environment(5);registry.environment(env)
    registry.import_deck({'deck_id':'semantic-own','environment_id':env['environment_id'],'source':'engineering_fixture','format':'json','content':own.to_dict()})
    normal=json.loads((ROOT/'configs/private-selection-engineering-v4.json').read_text())['cases']['chosen-blind']['profile']['decks'][1]
    spare=[c for c,r in sorted(assets.rows.items()) if c not in normal and r['type']==17 and r['ot']&1 and r['alias']==0 and 1<=r['level']&255<=4 and assets.limits.get(c,3)>=1][:3]
    opponents=[]
    for i in range(4):
        cards=list(normal)
        if i:cards[0]=spare[i-1]
        registry.import_deck({'deck_id':f'op-deck-{i}','environment_id':env['environment_id'],'source':'engineering_fixture','format':'json',
                              'content':{'main':cards,'extra':[78156759],'side':[]}})
        registry.register_opponent({'opponent_id':f'op-{i}','deck_id':f'op-deck-{i}','controller':'rule_baseline','provider':'local-python',
                                    'model':'no-llm','driver_version':'visible-effects-first-v1' if i%2==0 else 'visible-effects-last-option-v1'})
        opponents.append(FrozenOpponent(registry,f'op-{i}','semantic-own',1))
    return registry,opponents


class SemanticFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1);cls.temp=tempfile.TemporaryDirectory();cls.folder=Path(cls.temp.name)
        cls.assets=BuildAssets(CACHE);cls.task=BuildTask.from_dict(json.loads((ROOT/'configs/build-semantic-engineering-v4.json').read_text()))
        cls.solved=solve_candidates(cls.task,cls.assets);cls.deck=cls.solved['candidates'][0];cls.data=dataset(cls.task,cls.assets)
        cls.construction_index=DataIndex(cls.folder/'construction-index')
        cls.construction_index.freeze({'dataset_id':'construct-train','experiment_id':'semantic-tasks','purpose':'train','family':'construction',
                                       'versions':cls.task.environment['versions'],'opponents':[],'task_sha256':cls.task.sha256})
        cls.construction_index.ingest_construction('construct-train','semantic-labels',cls.task,cls.assets,cls.data,seeds=())
        cls.build_admission=cls.construction_index.admit_construction('semantic-labels',cls.task,cls.data)
        cls.build=BuildTrainer(cls.task,cls.assets,BuildTrainingConfig());cls.build_updates=cls.build.step(cls.data,data_admission=cls.build_admission)
        cls.build_binding=binding_for(cls.task,cls.assets,cls.data)
        cls.build_checkpoint=save_build(cls.build,cls.folder,'semantic-first',cls.build_binding)
        cls.build_restored=load_build(cls.build_checkpoint,cls.assets,cls.build_binding)
        cls.registry,cls.opponents=setup_registered(cls.folder/'registry',cls.assets,cls.deck)
        cls.pool=FrozenOpponentPool(cls.opponents[:2]);cls.index=DataIndex(cls.folder/'index')
        for purpose,opponents in [('train',cls.opponents[:2]),('validation',cls.opponents[2:3]),('final_eval',cls.opponents[3:])]:
            cls.index.freeze({'dataset_id':purpose,'experiment_id':'semantic-foundation','purpose':purpose,'family':'duel',
                              'versions':cls.task.environment['versions'],'opponents':[o.binding for o in opponents],'task_sha256':None})
        cfg=CpuTrainingConfig(model=DuelModelConfig(width=16,card_width=8,heads=2,feedforward=32,max_tokens=256,history_events=2),game_seeds=(7,24))
        cls.trainer=CpuTrainer(cfg,sorted(public_card_facts(CACHE)))
        first=cls.pool.choose(0);cls.train=cls.trainer.sample_episode(CACHE,first.profile,opponent_adapter=first)
        cls.validation=cls.trainer.sample_episode(CACHE,cls.opponents[2].profile,purpose='validation',seed=1701,policy_seed=500,opponent_adapter=cls.opponents[2])
        cls.index.ingest_episode('train','first',cls.train);cls.index.ingest_episode('validation','held-out',cls.validation)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_general_predicates_solve_all_sections_and_optimization_edit_budget_independently(self):
        self.assertEqual(self.solved['status'],'verified_list_candidates')
        for deck in self.solved['candidates']:
            self.assertTrue(self.assets.validate(self.task,deck)['hard_constraints_preserved'])
            p=proof(self.task,deck,self.assets);self.assertEqual(p['status'],'constraints_satisfied');self.assertFalse(p['effect_execution_verified'])
            counts={c['id']:c['actual'] for c in p['counts']};self.assertTrue(4<=counts['spellbook-spells']<=6)
        edits=solve_candidates(self.task,self.assets,self.deck,max_edits=1)
        self.assertTrue(edits['candidates']);self.assertTrue(all(replacements(self.deck,d)<=1 for d in edits['candidates']))
        self.assertEqual(solve_candidates(self.task,self.assets,seconds=0)['status'],'not_found_within_budget')
        raw=self.task.to_dict();raw['goal']['constraints'].append({'id':'contradiction','zones':['main'],'predicate':{'field':'type_all','value':2},'minimum':40,'maximum':40})
        impossible=BuildTask.from_dict(raw)
        self.assertEqual(solve_candidates(impossible,self.assets)['status'],'infeasible_declared_list_constraints')

    def test_semantics_reach_network_and_independent_role_update_restore_next_batch(self):
        encoder=BuildEncoder(self.task,self.assets,BuildModelConfig());original=encoder.batch(self.task,[self.deck])
        raw=self.task.to_dict();raw['goal']['constraints'][0]['minimum']=3;changed=BuildTask.from_dict(raw)
        altered=encoder.batch(changed,[self.deck]);self.assertFalse(torch.equal(original['numbers'],altered['numbers']))
        raw=self.task.to_dict()
        for item in raw['goal']['constraints']+raw['goal']['preferences']:item['id']='renamed-'+item['id']
        renamed=encoder.batch(BuildTask.from_dict(raw),[self.deck]);self.assertTrue(all(torch.equal(original[k],renamed[k]) for k in original))
        for update in self.build_updates:self.assertGreater(update['changed_parameter_elements'],0);self.assertGreater(update['head_delta_l2'],0)
        left=load_build(self.build_checkpoint,self.assets,self.build_binding);right=load_build(self.build_checkpoint,self.assets,self.build_binding)
        self.assertEqual(left.step(self.data,data_admission=self.build_admission),right.step(self.data,data_admission=self.build_admission))
        for role in ('build_goal','build_optimizer'):self.assertEqual(parameter_digest(left.models[role]),parameter_digest(right.models[role]))
        bad=copy.deepcopy(self.data);bad['competitive_quality_labels']=True
        with self.assertRaises(ContractError):validate(self.task,self.assets,bad)

    def test_goal_optimizer_alternates_without_pretending_constraints_are_summon_proof(self):
        result=alternate_build(self.task,self.assets,self.build.models,self.build.encoder,stages=4)
        self.assertEqual([s['role'] for s in result['stages']],['build_goal','build_optimizer']*2)
        previous=DeckParts(())
        for stage in result['stages']:
            deck=DeckParts.from_dict(stage['deck']);self.assets.validate(self.task,deck)
            self.assertEqual(apply_changes(previous,stage['changes']),deck);previous=deck
            self.assertEqual(stage['validation']['status'],'constraints_satisfied')
        self.assertFalse(result['competitive_ability_validated'])

    def test_construction_validation_and_cosmetic_task_rename_cannot_enter_training(self):
        trainer=BuildTrainer(self.task,self.assets,BuildTrainingConfig());before=parameter_digest(trainer.models['build_goal'])
        with self.assertRaisesRegex(ContractError,'indexed training'):trainer.step(self.data)
        raw=self.task.to_dict();raw['task_id']='renamed-semantic-task'
        for item in raw['goal']['constraints']+raw['goal']['preferences']:item['id']='alias-'+item['id']
        alias=BuildTask.from_dict(raw);held=dataset(alias,self.assets,purpose='validation')
        self.construction_index.freeze({'dataset_id':'construct-validation','experiment_id':'semantic-tasks','purpose':'validation',
                                       'family':'construction','versions':alias.environment['versions'],'opponents':[],'task_sha256':alias.sha256})
        with self.assertRaisesRegex(ContractError,'relabeled'):
            self.construction_index.ingest_construction('construct-validation','renamed-eval',alias,self.assets,held,seeds=())
        with self.assertRaisesRegex(ContractError,'held-out'):trainer.step(held,data_admission=self.build_admission)
        self.assertEqual(parameter_digest(trainer.models['build_goal']),before)

    def test_registered_extra_side_match_and_policy_privacy_and_real_replay(self):
        self.assertEqual(self.opponents[0].profile['extras'][0],[78156759]);self.assertEqual(len(self.opponents[0].profile['sides'][0]),2)
        self.assertEqual(self.opponents[0].profile['adapter_revision'],5)
        self.assertNotIn('profile',vars(self.opponents[0].policy));self.assertNotIn('registry',vars(self.opponents[0].policy))
        for episode in (self.train,self.validation):
            result=replay_private(CACHE,episode['_private_audit']);self.assertTrue(result['replay_verified']);self.assertEqual(result['callback_errors'],0)
            for step in episode['steps']:
                self.assertIsNone(step['request'].context.seed);self.assertEqual(step['request'].observation.observer,0)
        self.assertFalse(self.pool.manifest()['strength_qualified'])
        self.assertNotEqual(self.pool.choose(0).binding,self.pool.choose(1).binding)
        record=self.registry.get('opponent','op-0');record['driver_version']='stale-driver'
        with sqlite3.connect(self.registry.path) as db:db.execute("UPDATE records SET payload=? WHERE kind='opponent' AND id='op-0'",(json.dumps(record),))
        try:
            with self.assertRaises(ContractError):self.opponents[0].assert_runtime(CACHE,self.opponents[0].profile,0)
        finally:
            record['driver_version']='visible-effects-first-v1'
            with sqlite3.connect(self.registry.path) as db:db.execute("UPDATE records SET payload=? WHERE kind='opponent' AND id='op-0'",(json.dumps(record),))

    def test_validation_relabel_and_index_admission_rejected_before_actual_ppo_update(self):
        # New trainer reproduces the real first sample: class fixtures stay
        # immutable across test ordering and no validation weight update occurs.
        trainer=CpuTrainer(self.trainer.config,sorted(public_card_facts(CACHE)));op=self.opponents[0]
        train=trainer.sample_episode(CACHE,op.profile,opponent_adapter=op)
        validation=trainer.sample_episode(CACHE,self.opponents[2].profile,purpose='validation',seed=1702,policy_seed=501,opponent_adapter=self.opponents[2])
        bad=copy.deepcopy(validation);bad['purpose']=bad['summary']['purpose']='train';before=parameter_digest(trainer.model)
        with self.assertRaisesRegex(ContractError,'fresh training sample'):trainer.update(bad)
        self.assertEqual(parameter_digest(trainer.model),before)
        with self.assertRaisesRegex(ContractError,'held-out'):self.index.admit_episode('held-out',self.validation)
        self.index.ingest_episode('train','actual-update',train);self.index.admit_episode('actual-update',train)
        update=trainer.update(train);self.assertGreater(update['policy_head_delta_l2'],0)
        binding=resource_binding(CACHE,op.profile)|{'registered_opponent_pool':self.pool.manifest()}
        checkpoint=save_checkpoint(trainer,self.folder,'actual-registered-update',binding);restored=load_checkpoint(checkpoint,binding)
        next_op=self.pool.choose(restored.episode_cursor)
        continuous=trainer.sample_episode(CACHE,next_op.profile,opponent_adapter=next_op)
        resumed=restored.sample_episode(CACHE,next_op.profile,opponent_adapter=next_op)
        self.assertEqual(continuous['summary']['trajectory_sha256'],resumed['summary']['trajectory_sha256'])
        self.assertEqual(trainer.update(continuous),restored.update(resumed))
        final=trainer.sample_episode(CACHE,self.opponents[3].profile,purpose='final_eval',seed=1800,policy_seed=600,opponent_adapter=self.opponents[3])
        self.index.ingest_episode('final_eval','final-heldout',final)
        with self.assertRaisesRegex(ContractError,'held-out'):self.index.artifact('final-heldout',for_training=True)
        self.assertTrue(replay_private(CACHE,final['_private_audit'])['natural_terminal'])

    def test_msg18_classification_is_version_limited_and_msg24_two_zones_are_real(self):
        evidence,traces=verify_multi_zone(CACHE)
        self.assertTrue(evidence['pinned_core_checkout_verified'])
        self.assertFalse(evidence['msg18']['current_pinned_ordinary_bo1_multizone_caller_present'])
        self.assertFalse(evidence['msg18']['real_multizone_case_verified'])
        self.assertTrue(evidence['msg24']['real_multizone_case_verified']);self.assertEqual(len(traces),2)
        self.assertTrue(all(p['actual_message']==24 and p['zones_selected']==2 and p['field_disabled_mask'].bit_count()==2
                            and p['replay_verified'] for p in evidence['msg24']['proofs']))

    def test_local_snapshot_is_a_real_frozen_opponent_and_private_checkpoint_state_is_not_in_policy(self):
        trainer=CpuTrainer(self.trainer.config,sorted(public_card_facts(CACHE)));op=self.opponents[0]
        episode=trainer.sample_episode(CACHE,op.profile,opponent_adapter=op);trainer.update(episode)
        binding=resource_binding(CACHE,op.profile)
        path=save_checkpoint(trainer,self.registry.root/'snapshots','real-frozen-duel',binding)
        sha=hashlib.sha256(path.read_bytes()).hexdigest();model_hash=parameter_digest(trainer.model)
        self.registry.register_opponent({'opponent_id':'snapshot-op','deck_id':'op-deck-0','controller':'local_snapshot','provider':'local-pytorch-cpu',
                                         'model':model_hash,'driver_version':'frozen-duel-greedy-v1'})
        rng=torch.get_rng_state().clone()
        frozen=FrozenOpponent(self.registry,'snapshot-op','semantic-own',1,checkpoint=path,checkpoint_sha256=sha)
        self.assertTrue(torch.equal(torch.get_rng_state(),rng))
        self.assertEqual(frozen.binding['model_sha256'],model_hash)
        for key in ('config','game_seeds','optimizer','registry','profile','policy_rng'):
            self.assertNotIn(key,vars(frozen.policy))
        before=parameter_digest(frozen.policy.model)
        result=trainer.sample_episode(CACHE,frozen.profile,purpose='validation',seed=1900,policy_seed=700,opponent_adapter=frozen)
        self.assertEqual(parameter_digest(frozen.policy.model),before)
        self.assertTrue(all(not p.requires_grad for p in frozen.policy.model.parameters()))
        self.assertTrue(torch.equal(torch.get_rng_state(),rng))
        self.assertTrue(replay_private(CACHE,result['_private_audit'])['natural_terminal'])
        with self.assertRaisesRegex(ContractError,'checksum'):FrozenOpponent(self.registry,'snapshot-op','semantic-own',1,checkpoint=path,checkpoint_sha256='0'*64)
        state=torch.load(path,map_location='cpu',weights_only=True);state['binding']['feature_version']='incompatible-feature'
        broken=path.with_name('incompatible.weights');torch.save(state,broken)
        with self.assertRaisesRegex(ContractError,'compatible'):
            FrozenOpponent(self.registry,'snapshot-op','semantic-own',1,checkpoint=broken,checkpoint_sha256=hashlib.sha256(broken.read_bytes()).hexdigest())
        state.pop('boundary');torch.save(state,broken)
        with self.assertRaises(ContractError):
            FrozenOpponent(self.registry,'snapshot-op','semantic-own',1,checkpoint=broken,checkpoint_sha256=hashlib.sha256(broken.read_bytes()).hexdigest())
