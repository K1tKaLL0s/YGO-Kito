"""Two real model groups, snapshot policies/PPO/SQLite; fake native engine only.

No C#, core rule claim, formal course training, speed measurement or ability
claim. Counter tests never project self-play onto the old course requirements.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import torch

from tests.test_autonomous_construction import fixture
import tests.test_course_game_adapter as adapter_fixtures
from ygo_kito import selfplay_series as series_module
from ygo_kito.build_contracts import BuildTask, digest
from ygo_kito.course_game_adapter import CourseGameAdapter, CourseTrainingConfig
from ygo_kito.course_models import CourseModels
from ygo_kito.data_isolation import DataIndex
from ygo_kito.duel_model import DuelModelConfig
from ygo_kito.group_runner import tree_digest
from ygo_kito.lora import AdapterConfig
from ygo_kito.selfplay_series import FrozenModelPool, SelfPlayPlayer, SelfPlaySeries
from ygo_kito.validation import ContractError


class SelfPlaySeriesTests(unittest.TestCase):
    def setUp(self):
        self.f = adapter_fixtures.CourseGameAdapterTests('test_base_two_fresh_ppo_games_sideboards_and_actual_seat_swap')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.assets = self.f.assets
        task, catalog, _, _ = fixture(41, initialize=False)
        self.assets.rows = deepcopy(catalog.rows)
        self.assets.period_context = None; self.assets.adapter_revision = 5
        raw = task.to_dict(); raw.update(pool=list(range(1,42)), sizes={'main':40,'extra':0,'side':1},
            environment=self.assets.environment_for('deck_constraints'))
        task = BuildTask.from_dict(raw)
        configs = {r: AdapterConfig('series-'+r, r, ('head.0',) if r.startswith('build_') else
            ('value_head.2',) if r=='duel' else ('route_head',), rank=1, max_updates=8)
            for r in ('build_goal','build_optimizer','duel','coordinator')}
        self.players = []
        for name, start, model_seed in (('actor',100,31),('other',400,47)):
            cfg = CourseTrainingConfig(model=DuelModelConfig(width=8,card_width=4,heads=2,feedforward=16),
                game_seeds=tuple(range(start,start+6)), model_seed=model_seed, policy_seed=start+10, batch_size=1)
            model = CourseModels.initialize(task,self.assets,cfg,configs,self.f.root,None,self.assets.rows,
                {'kind':'synthetic-independent-course-fixture','player_id':name})
            self.players.append(SelfPlayPlayer(name, model, self.f.parts(self.f.helper.profile,0)))
        self.verify = patch('ygo_kito.model_opponents.verify_resources',return_value=self.assets.receipt)
        self.verify.start(); self.addCleanup(self.verify.stop)
        self.config = {'series_id':'synthetic-two-models'}
        self.adapter_options=[]
        self.series = self.new_series()

    def new_series(self):
        return SelfPlaySeries(players=tuple(self.players),assets=self.assets,data_index=self.f.index,
            state_root=self.f.root/'series',config=self.config)

    @contextmanager
    def execution(self, after_game=None):
        owner = self
        def construct(**kwargs):
            owner.f.state = kwargs['match_state']
            owner.adapter_options.append(kwargs)
            actual = CourseGameAdapter(**kwargs)
            class Forward:
                def __call__(self, spec):
                    result=actual(spec)
                    if after_game is not None: after_game(spec)
                    return result
                def __getattr__(self,key):return getattr(actual,key)
            return Forward()
        with self.f.fake_model_execution(),patch.object(series_module,'CourseGameAdapter',construct):yield

    def training_series(self):
        self.config.update(training_enabled=True,ratio=.25,allocation={'max_matches':2,
            'max_small_games_per_player':{'actor':3,'other':3}, 'wall_seconds':3600, 'prior_budget_seconds':0})
        return self.new_series()

    def test_initial_pool_actual_independent_groups_and_disabled_training(self):
        self.assertEqual(len(self.series.pool.manifest()['initial']),2)
        for row in self.series.pool.manifest()['history'].values():
            self.assertEqual(row['identity']['provenance']['source_stage'],'engineering_initial')
            self.assertFalse(row['identity']['provenance']['ability_verified'])
        with self.assertRaisesRegex(ContractError,'disabled'):self.series.train_match()
        duplicate=SelfPlayPlayer('duplicate',self.players[0].models,self.players[0].deck)
        with self.assertRaisesRegex(ContractError,'alias'):
            SelfPlaySeries(players=(self.players[0],duplicate),assets=self.assets,data_index=self.f.index,
                state_root=self.f.root/'duplicate',config={'series_id':'duplicate'})
        self.players[1].models.duel.config=replace(self.players[1].models.duel.config,game_seeds=(100,101))
        with self.assertRaisesRegex(ContractError,'distinct physical'):self.new_series()

    def test_functional_bo3_calls_both_neural_models_and_both_side_rankers_without_updates(self):
        before=[p.models.fingerprint() for p in self.players]
        with self.execution():
            result=self.series.functional_match(format='bo3',actor_id='actor',seed_pairs=((700,701),(702,703),(704,705)))
        self.assertEqual(result['functional_matches'],1)
        self.assertEqual(result['formal_training_matches'],0)
        self.assertEqual(result['selfplay_training_matches'],0)
        self.assertFalse(result['common_deck_coverage_qualified'])
        self.assertEqual(before,[p.models.fingerprint() for p in self.players])
        record=self.series.records[0]
        self.assertEqual(len(record['summary']['games']),2)
        self.assertEqual([g['actual_first_participant_id'] for g in record['summary']['games']],['actor','other'])
        side=[r for r in record['receipts'] if r.get('kind')=='own-model-side-selection']
        self.assertEqual({r['player_id'] for r in side},{'actor','other'})
        self.assertTrue(all(r['receipt']['candidate_count']>1 for r in side))
        self.assertTrue(all(s.updates==0 for p in self.players for s in p.models.sessions.values()))
        self.assertEqual(self.f.index.summary()['by_purpose']['validation'],2)
        self.assertEqual(record['match_state']['binding']['model_opponent'],
            self.series.pool.runtime(record['snapshot_id'],'validation').identity())

    def test_explicit_small_cpu_training_rotates_actor_and_retains_initial_and_updated_snapshots(self):
        series=self.training_series()
        before_other=self.players[1].models.versions()
        with self.execution():first=series.train_match()
        self.assertEqual(first['selfplay_training_matches'],1)
        self.assertEqual(self.players[0].models.sessions['duel'].updates,1)
        self.assertEqual(self.players[1].models.versions(),before_other)
        frozen=series.pool.snapshot(series.records[0]['snapshot_id']).identity()
        with self.assertRaisesRegex(ContractError,'rotate'):series.train_match(actor_id='actor')
        with self.execution():second=series.train_match()
        self.assertEqual(second['selfplay_training_matches'],2)
        self.assertEqual(second['formal_training_matches'],0)
        self.assertEqual([p.models.sessions['duel'].updates for p in self.players],[1,1])
        self.assertEqual([r['actor_id'] for r in series.records],['actor','other'])
        self.assertEqual(series.pool.snapshot(series.records[0]['snapshot_id']).identity(),frozen)
        self.assertEqual(len(series.pool.manifest()['initial']),2)
        updated=series.pool.snapshot(series.records[1]['snapshot_id']).identity()
        self.assertEqual(updated['provenance']['source_stage'],'updated_weights')
        self.assertNotEqual(updated['state_sha256'],series.pool.snapshot(series.pool.manifest()['initial']['actor']).identity()['state_sha256'])
        before=[p.models.fingerprint() for p in self.players]
        restored=self.new_series();restored.restore_latest()
        self.assertEqual(restored.status()['selfplay_training_matches'],2)
        self.assertEqual([p.models.fingerprint() for p in self.players],before)
        self.assertEqual(restored.pool.manifest(),series.pool.manifest())
        with self.assertRaisesRegex(ContractError,'allocation exhausted'):series.train_match()

    def test_pause_restore_keeps_both_groups_pool_match_and_consumed_games_without_replay(self):
        pairs=((700,701),(702,703),(704,705))
        def pause(spec):
            if spec.game_number==1:(self.series.root/'pause.request').write_text('pause after a closed small game')
        with self.execution(pause):
            result=self.series.functional_match(format='bo3',actor_id='actor',seed_pairs=pairs)
        self.assertEqual(result['desired'],'paused')
        self.assertEqual(result['small_game_attempts'],1)
        before=[p.models.fingerprint() for p in self.players]; pool=self.series.pool.manifest()
        resumed=self.new_series();resumed.restore_latest()
        self.assertEqual([p.models.fingerprint() for p in self.players],before)
        self.assertEqual(resumed.pool.manifest(),pool)
        (resumed.root/'pause.request').unlink()
        with self.execution():result=resumed.functional_match(format='bo3',actor_id='actor',seed_pairs=pairs)
        self.assertEqual(result['functional_matches'],1)
        self.assertEqual(result['small_game_attempts'],2)
        self.assertEqual(self.f.index.summary()['by_purpose']['validation'],2)

    def test_inflight_and_changed_index_reject_before_either_model_restore(self):
        self.series.save(); before=[p.models.fingerprint() for p in self.players]
        marker=self.series.root/'in-flight.json';marker.write_text('{}')
        with self.assertRaisesRegex(ContractError,'half-game'):self.series.restore_latest()
        with self.assertRaisesRegex(ContractError,'half-game'):
            self.series.functional_match(actor_id='actor',seed_pairs=((700,701),))
        marker.unlink()
        with patch.object(self.series,'_index_sha',return_value='changed'):
            with self.assertRaisesRegex(ContractError,'binding/data'):self.series.restore_latest()
        self.assertEqual([p.models.fingerprint() for p in self.players],before)

    def test_corrupt_second_model_rejected_without_publishing_first(self):
        pointer=self.series.save();path=self.series.root/pointer['path']
        saved=torch.load(path,weights_only=True,map_location='cpu')
        bad=saved['models']['other']
        next(iter(bad['components']['models']['duel'].values())).fill_(float('nan'))
        bad['state_sha256']=tree_digest({k:v for k,v in bad.items() if k!='state_sha256'})
        saved['state_sha256']=tree_digest({k:v for k,v in saved.items() if k!='state_sha256'})
        torch.save(saved,path);pointer['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        (self.series.root/'latest.json').write_text(json.dumps(pointer))
        manifest=json.loads((self.series.root/'storage-manifest.json').read_text())
        manifest['files'][pointer['path']].update(sha256=pointer['sha256'],bytes=path.stat().st_size)
        manifest['state_sha256']=digest({k:v for k,v in manifest.items() if k!='state_sha256'})
        (self.series.root/'storage-manifest.json').write_text(json.dumps(manifest))
        before=[p.models.fingerprint() for p in self.players]
        with self.assertRaisesRegex(ContractError,'nonfinite'):self.new_series().restore_latest()
        self.assertEqual([p.models.fingerprint() for p in self.players],before)

    def test_pool_partition_is_actual_model_identity_and_initial_history_survives_roundtrip(self):
        pool=self.series.pool;key=pool.manifest()['initial']['actor']
        pool.assign(key,'validation')
        with self.assertRaisesRegex(ContractError,'cross'):pool.assign(key,'train')
        with self.assertRaisesRegex(ContractError,'replaced'):pool.capture(self.players[0],self.assets,initial=True)
        restored=FrozenModelPool.from_state(pool.state_dict())
        self.assertEqual(restored.manifest(),pool.manifest())
        broken=pool.state_dict();broken['initial']['actor']=broken['initial']['other']
        broken['state_sha256']=tree_digest({k:v for k,v in broken.items() if k!='state_sha256'})
        with self.assertRaisesRegex(ContractError,'player binding'):FrozenModelPool.from_state(broken)

    def test_functional_seed_overlap_and_evaluation_retraining_are_rejected(self):
        with self.assertRaisesRegex(ContractError,'both learners'):
            self.series.functional_match(actor_id='actor',seed_pairs=((400,701),))
        with self.execution():self.series.functional_match(actor_id='actor',seed_pairs=((700,701),))
        with self.assertRaisesRegex(ContractError,'disabled'):self.series.train_match()
        with self.assertRaisesRegex(ContractError,'separate experiment/index'):self.training_series()
        config=deepcopy(self.config);config['series_id']='separate-training'
        fresh=SelfPlaySeries(players=tuple(self.players),assets=self.assets,
            data_index=DataIndex(self.f.root/'fresh-training-index'),state_root=self.f.root/'fresh-training-state',config=config)
        with self.assertRaisesRegex(ContractError,'separate disabled'):
            fresh.functional_match(actor_id='actor',seed_pairs=((700,701),))
        with self.execution():result=fresh.train_match()
        self.assertEqual(result['selfplay_training_matches'],1)
        self.assertEqual(result['formal_training_matches'],0)

    def test_activity_cap_and_prior_budget_are_explicit_and_survive_restore(self):
        config={'series_id':'explicit-cap','training_enabled':True,'ratio':.25,'allocation':{
            'max_matches':2,'max_small_games_per_player':{'actor':3,'other':3},'wall_seconds':10,'prior_budget_seconds':0}}
        for prior,wall in ((None,10),(359999,10)):
            bad=deepcopy(config);bad['allocation'].update(prior_budget_seconds=prior,wall_seconds=wall)
            with self.assertRaises(ContractError):
                SelfPlaySeries(players=tuple(self.players),assets=self.assets,data_index=self.f.index,
                    state_root=self.f.root/'bad-allocation',config=bad)
        self.config=config;series=self.new_series()
        ticks=iter(range(100))
        with patch.object(series_module,'time',SimpleNamespace(monotonic=lambda:next(ticks))), \
                patch.object(series_module,'CourseGameAdapter',side_effect=AssertionError('no game reserve')):
            result=series.train_match()
        self.assertEqual(result['desired'],'budget_insufficient_for_next_game')
        self.assertEqual(result['small_game_attempts'],0)
        self.assertGreater(result['active_seconds'],0)
        resumed=self.new_series();resumed.restore_latest()
        self.assertEqual(resumed.active_seconds,result['active_seconds'])
        self.assertTrue(all(p.models.sessions['duel'].updates==0 for p in self.players))

    def test_two_restored_readers_must_recheck_latest_under_the_operation_lock(self):
        with self.execution():self.series.functional_match(actor_id='actor',seed_pairs=((700,701),))
        first=self.new_series();second=self.new_series()
        first.restore_latest();second.restore_latest()
        with self.execution():first.functional_match(actor_id='actor',seed_pairs=((702,703),))
        with patch.object(series_module,'CourseGameAdapter',side_effect=AssertionError('stale reader must not sample')):
            with self.assertRaisesRegex(ContractError,'stale self-play reader'):
                second.functional_match(actor_id='actor',seed_pairs=((704,705),))
        self.assertEqual(self.f.index.summary()['by_purpose']['validation'],2)

    def test_sample_opponent_stream_is_private_independent_and_reconstructed_after_pause(self):
        self.config['opponent_policy_mode']='sample';series=self.new_series()
        pairs=((700,701),(702,703),(704,705))
        (series.root/'pause.request').write_text('pause before the first small game')
        result=series.functional_match(format='bo3',actor_id='actor',seed_pairs=pairs)
        self.assertEqual(result['desired'],'paused')
        state=series.pending['state']
        before=[p.models.fingerprint() for p in self.players]
        global_rng=torch.get_rng_state().clone()
        rng1=series._opponent_rng(state,'other');rng2=series._opponent_rng(state,'other')
        expected=rng1.get_state().clone()
        self.assertTrue(torch.equal(torch.rand(5,generator=rng1),torch.rand(5,generator=rng2)))
        self.assertTrue(torch.equal(torch.get_rng_state(),global_rng))
        self.assertIsNot(rng1,self.players[0].models.policy_rng)
        self.assertIsNot(rng1,self.players[1].models.duel.policy_rng)
        runtime=series.pool.runtime(series.pending['snapshot_id'],'validation',policy_mode='sample')
        self.assertEqual(runtime.identity()['policy_mode'],'sample')
        self.assertNotIn('policy_seed',json.dumps(runtime.identity()))
        with self.assertRaisesRegex(ContractError,'cross'):
            series.pool.runtime(series.pending['snapshot_id'],'train',policy_mode='greedy')
        resumed=self.new_series();resumed.restore_latest()
        self.assertTrue(torch.equal(resumed._opponent_rng(resumed.pending['state'],'other').get_state(),expected))
        (resumed.root/'pause.request').unlink()
        with self.execution():result=resumed.functional_match(format='bo3',actor_id='actor',seed_pairs=pairs)
        self.assertEqual(result['functional_matches'],1)
        self.assertEqual(result['formal_training_matches'],0)
        self.assertEqual([p.models.fingerprint() for p in self.players],before)
        self.assertEqual(len(self.adapter_options),2)
        streams=[v['opponent_policy_rng'] for v in self.adapter_options]
        self.assertIsNot(streams[0],streams[1])
        self.assertTrue(all(v['model_runtime'].policy_mode=='sample' for v in self.adapter_options))
        self.assertTrue(all(v['opponent_policy_rng'] is not v['policy_rng'] for v in self.adapter_options))
        self.assertTrue(torch.equal(streams[0].get_state(),expected))
        self.assertFalse(torch.equal(streams[0].get_state(),streams[1].get_state()))
        self.assertEqual(resumed.records[0]['match_state']['binding']['model_opponent']['policy_mode'],'sample')

    def test_explicit_initial_history_is_really_used_after_peer_updates_and_cannot_change_mid_match(self):
        series=self.training_series()
        # Separate explicit engineering allocation, not a formal curriculum ratio.
        self.config['allocation'].update(max_matches=3,max_small_games_per_player={'actor':5,'other':3})
        series=self.new_series()
        initial=series.pool.manifest()['initial']['other']
        with self.execution():series.train_match()
        with self.execution():series.train_match()
        latest=series.pool.capture(self.players[1],self.assets)
        self.assertNotEqual(initial,latest)
        self.assertEqual(series.pool.snapshot(latest).identity()['provenance']['source_stage'],'updated_weights')
        with self.assertRaisesRegex(ContractError,'other player'):
            series.train_match(format='bo3',opponent_snapshot_id=series.pool.manifest()['initial']['actor'])
        def pause(spec):
            if spec.game_number==1:(series.root/'pause.request').write_text('closed game')
        with self.execution(pause):result=series.train_match(format='bo3',opponent_snapshot_id=initial)
        self.assertEqual(result['desired'],'paused')
        with self.assertRaisesRegex(ContractError,'cannot change its frozen'):
            series.train_match(format='bo3',opponent_snapshot_id=latest)
        (series.root/'pause.request').unlink()
        with self.execution():result=series.train_match(format='bo3',opponent_snapshot_id=initial)
        self.assertEqual(result['selfplay_training_matches'],3)
        record=series.records[-1]
        self.assertEqual(record['snapshot_id'],initial)
        self.assertEqual(len(record['summary']['games']),2)
        actual=[r['before']['model_opponent']['snapshot']['state_sha256'] for r in record['receipts']
                if r.get('kind')=='course-small-game-host-receipt']
        self.assertEqual(actual,[series.pool.snapshot(initial).identity()['state_sha256']]*2)
        self.assertEqual([p.models.sessions['duel'].updates for p in self.players],[3,1])
        with self.assertRaisesRegex(ContractError,'cross'):series.pool.runtime(initial,'final_eval')

    def test_v2_checkpoints_reference_deduplicated_model_blobs_and_closed_matches(self):
        with self.execution():self.series.functional_match(actor_id='actor',seed_pairs=((700,701),))
        with self.execution():self.series.functional_match(actor_id='actor',seed_pairs=((702,703),))
        pointer=json.loads((self.series.root/'latest.json').read_text())
        saved=torch.load(self.series.root/pointer['path'],weights_only=True,map_location='cpu')
        self.assertEqual(saved['schema_version'],2)
        self.assertNotIn('pool',saved)
        self.assertEqual(len(saved['pool_refs']['entries']),2)
        self.assertEqual(len(list((self.series.root/'snapshots').glob('*.weights'))),2)
        self.assertEqual(len(list((self.series.root/'matches').glob('*.json'))),2)
        self.assertTrue(all(set(r)=={'match_id','path','sha256'} for r in saved['records']))
        self.assertEqual(saved['consumed_counts']['complete_matches']['validation'],2)
        self.assertEqual(saved['consumed_counts']['formal_training_matches'],0)
        self.assertGreater(len(list(self.series.root.glob('checkpoint-*.weights'))),2)  # Default never prunes.
        restored=self.new_series();restored.restore_latest()
        self.assertEqual(restored.status()['functional_matches'],2)
        self.assertFalse(restored.status()['storage']['all_assets_trajectories_and_temporary_peak_under_30GB_verified'])

    def test_explicit_retention_only_prunes_manifest_owned_noninitial_nonmilestone_checkpoints(self):
        self.config['checkpoint_policy']={'keep_last':1,'milestone_every':3,'min_free_bytes':0,'max_state_bytes':64*1024*1024}
        series=self.new_series()
        sentinel=series.root/'checkpoint-999.weights';sentinel.write_bytes(b'user-owned-not-a-generated-checkpoint')
        with self.execution():series.functional_match(actor_id='actor',seed_pairs=((700,701),))
        with self.execution():series.functional_match(actor_id='actor',seed_pairs=((702,703),))
        manifest=json.loads((series.root/'storage-manifest.json').read_text())
        self.assertEqual(sentinel.read_bytes(),b'user-owned-not-a-generated-checkpoint')
        self.assertTrue((series.root/'checkpoint-1.weights').is_file())
        self.assertTrue((series.root/series._last_checkpoint['path']).is_file())
        deleted=[]
        for name,row in manifest['files'].items():
            if row['kind']=='checkpoint':
                if row['deleted']:deleted.append(name);self.assertFalse((series.root/name).exists())
                else:self.assertTrue(row['revision']==1 or row['revision']==series.revision or row['revision']%3==0)
            else:self.assertFalse(row['deleted']);self.assertTrue((series.root/name).is_file())
        self.assertTrue(deleted)
        restored=self.new_series();restored.restore_latest()
        self.assertEqual(restored.status()['functional_matches'],2)

    def test_disk_low_water_and_total_series_cap_pause_before_any_sampling(self):
        self.config['checkpoint_policy']={'keep_last':None,'milestone_every':None,'min_free_bytes':0,'max_state_bytes':1}
        series=self.new_series();before=[p.models.fingerprint() for p in self.players]
        with patch.object(series_module,'CourseGameAdapter',side_effect=AssertionError('must not sample')):
            result=series.functional_match(actor_id='actor',seed_pairs=((700,701),))
        self.assertEqual(result['desired'],'storage_blocked')
        self.assertEqual(result['small_game_attempts'],0)
        self.assertFalse(list(series.root.glob('checkpoint-*.weights')))
        self.assertEqual([p.models.fingerprint() for p in self.players],before)
        self.config['checkpoint_policy']['max_state_bytes']=None
        free_series=self.new_series()
        with patch.object(series_module,'shutil',SimpleNamespace(disk_usage=lambda _:SimpleNamespace(free=0))), \
                patch.object(series_module,'CourseGameAdapter',side_effect=AssertionError('must not sample')):
            result=free_series.functional_match(actor_id='actor',seed_pairs=((700,701),))
        self.assertEqual(result['desired'],'storage_blocked')
        self.assertEqual(result['small_game_attempts'],0)

    def test_restore_reads_all_retained_blobs_and_closed_match_documents(self):
        with self.execution():self.series.functional_match(actor_id='actor',seed_pairs=((700,701),))
        pointer=json.loads((self.series.root/'latest.json').read_text())
        saved=torch.load(self.series.root/pointer['path'],weights_only=True,map_location='cpu')
        blob=self.series.root/next(iter(saved['pool_refs']['entries'].values()))['path']
        original=blob.read_bytes();blob.write_bytes(b'bad retained history bytes')
        before=[p.models.fingerprint() for p in self.players]
        with self.assertRaisesRegex(ContractError,'bytes differ'):self.new_series().restore_latest()
        blob.write_bytes(original)
        match=self.series.root/saved['records'][0]['path'];original=match.read_bytes();match.unlink()
        with self.assertRaisesRegex(ContractError,'missing'):self.new_series().restore_latest()
        match.write_bytes(original)
        self.assertEqual([p.models.fingerprint() for p in self.players],before)

    def test_restore_replays_referenced_records_before_accepting_complete_counters(self):
        with self.execution():self.series.functional_match(actor_id='actor',seed_pairs=((700,701),))
        pointer=json.loads((self.series.root/'latest.json').read_text());path=self.series.root/pointer['path']
        saved=torch.load(path,weights_only=True,map_location='cpu')
        saved['consumed_counts']['complete_matches']['validation']+=1
        saved['state_sha256']=tree_digest({k:v for k,v in saved.items() if k!='state_sha256'})
        torch.save(saved,path);pointer['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        (self.series.root/'latest.json').write_text(json.dumps(pointer))
        manifest=json.loads((self.series.root/'storage-manifest.json').read_text())
        manifest['files'][pointer['path']].update(sha256=pointer['sha256'],bytes=path.stat().st_size)
        manifest['state_sha256']=digest({k:v for k,v in manifest.items() if k!='state_sha256'})
        (self.series.root/'storage-manifest.json').write_text(json.dumps(manifest))
        before=[p.models.fingerprint() for p in self.players]
        with self.assertRaisesRegex(ContractError,'counters/cursor'):self.new_series().restore_latest()
        self.assertEqual([p.models.fingerprint() for p in self.players],before)


if __name__=='__main__':unittest.main()
