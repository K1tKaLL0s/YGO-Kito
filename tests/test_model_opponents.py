"""Actual CPU neural snapshot mechanics, with synthetic resource/deck fixtures.

No engine, C#, ability training, timing pilot or external provider is executed.
"""
from copy import deepcopy
from dataclasses import asdict
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import torch

from tests.fixtures import request
import tests.test_course_game_adapter as course_fixtures
from ygo_kito import model_opponents as models
from ygo_kito.contracts import DecisionRequest, Versions
from ygo_kito.cpu_training import CpuTrainer
from ygo_kito.duel_model import FEATURE_VERSION, parameter_digest
from ygo_kito.hierarchical_policy import score_requests
from ygo_kito.lora import AdapterConfig, AdapterSession
from ygo_kito.opponent_pool import FrozenOpponent, FrozenOpponentPool
from ygo_kito.data_isolation import opponent_identity
from ygo_kito.validation import ContractError


class ModelOpponentTests(unittest.TestCase):
    def setUp(self):
        self.f = course_fixtures.CourseGameAdapterTests('test_base_two_fresh_ppo_games_sideboards_and_actual_seat_swap')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.assets, self.trainer = self.f.assets, self.f.trainer
        p = patch.object(models, 'verify_resources', return_value=self.assets.receipt)
        p.start(); self.addCleanup(p.stop)

    def capture(self, trainer=None, session=None):
        return models.FrozenDuelSnapshot.capture(self.trainer if trainer is None else trainer,
            assets=self.assets, adapter_session=session, source_binding={'fixture': 'not-certified-training'},
            source_label='explicit synthetic CPU source, no game capability claim')

    def runtime(self, snapshot=None):
        return models.ModelOpponentRuntime(self.capture() if snapshot is None else snapshot, 'fixture-neural')

    def req(self, seat=1):
        d = request(); d['context']['seed'] = None
        d['context']['versions'] = asdict(models._versions(self.assets))
        d['observation']['observer'] = seat
        d['observation']['cards'][0].update(owner=seat, controller=seat)
        d['observation']['cards'][1].update(owner=1-seat, controller=1-seat)
        return DecisionRequest.from_dict(d)

    def test_initial_network_is_explicit_frozen_inference_and_preserves_rng(self):
        before = torch.get_rng_state().clone(); source = parameter_digest(self.trainer.model)
        snap = self.capture(); opponent = self.runtime(snap).bind(self.assets, self.f.helper.profile, 1)
        self.assertTrue(torch.equal(before, torch.get_rng_state()))
        self.assertIsInstance(opponent, FrozenOpponent)
        self.assertEqual(snap.identity()['provenance']['source_stage'], 'engineering_initial')
        self.assertFalse(snap.identity()['provenance']['ability_verified'])
        self.assertFalse(any(p.requires_grad for p in opponent.policy.model.parameters()))
        self.assertFalse(opponent.policy.model.training)
        self.assertEqual(source, parameter_digest(opponent.policy.model))
        self.assertFalse({p.data_ptr() for p in self.trainer.model.parameters()} &
                         {p.data_ptr() for p in opponent.policy.model.parameters()})
        opponent.assert_runtime(self.assets.root, self.f.helper.profile, 0)
        action = opponent.policy.choose(self.req())
        self.assertIn(action, self.req().actions)
        self.assertEqual(source, parameter_digest(self.trainer.model))

    def test_effective_lora_exact_logits_materialize_without_touching_learner(self):
        session = AdapterSession(self.trainer.model,
            AdapterConfig('fixture-freeze', 'duel', ('policy_head.2', 'value_head.2'), rank=1, max_updates=3),
            {'base_version': 'fixture-base', 'feature_version': FEATURE_VERSION, 'context_sha256': 'a'*64})
        # A real CPU optimizer step on artificial parameter loss; no duel training.
        loss = sum((v - .2).square().sum() for v in session.weights().values())
        session.step(loss)
        self.trainer.model.eval()
        before = parameter_digest(self.trainer.model)
        rng = torch.get_rng_state().clone(); flags = [m.training for m in self.trainer.model.modules()]
        original = [p.data_ptr() for p in session.parameters()]
        snap = self.capture(session=session)
        opponent = self.runtime(snap).bind(self.assets, self.f.helper.profile, 1)
        with torch.no_grad():
            expected = score_requests(self.trainer.model, self.trainer.encoder, [self.req()])
            actual = score_requests(opponent.policy.model, opponent.policy.encoder, [self.req()])
        for a, b in zip(actual, expected): self.assertTrue(torch.equal(a, b))
        self.assertEqual(parameter_digest(self.trainer.model), before)
        self.assertEqual([p.data_ptr() for p in session.parameters()], original)
        self.assertEqual([m.training for m in self.trainer.model.modules()], flags)
        self.assertTrue(torch.equal(rng, torch.get_rng_state()))
        proof = snap.identity()['provenance']
        self.assertEqual(proof['source_model_sha256'], before)
        self.assertEqual(proof['adapter']['version'], session.version_id())
        self.assertEqual(proof['materialization'], 'exact-effective-lora-to-cpu')
        self.assertEqual(proof['source_stage'], 'updated_weights')
        self.assertNotEqual(snap.identity()['model_sha256'], before)  # distinct representation SHA
        frozen = parameter_digest(opponent.policy.model)
        session.step(sum((v + .1).square().sum() for v in session.weights().values()))
        self.assertEqual(parameter_digest(opponent.policy.model), frozen)
        opponent.assert_runtime(self.assets.root, self.f.helper.profile, 0)

    def test_omitted_disabled_wrong_adapter_and_pending_source_refused(self):
        self.trainer._pending_episode_digest = 'a'*64
        with self.assertRaisesRegex(ContractError, 'boundary'): self.capture()
        self.trainer._pending_episode_digest = None
        session = AdapterSession(self.trainer.model,
            AdapterConfig('fixture-freeze', 'duel', ('value_head.2',), rank=1),
            {'base_version': 'fixture-base', 'feature_version': FEATURE_VERSION, 'context_sha256': 'a'*64})
        with self.assertRaisesRegex(ContractError, 'supplied explicitly'): self.capture()
        session.set_enabled(False)
        with self.assertRaisesRegex(ContractError, 'enabled'): self.capture(session=session)
        session.set_enabled(True)
        other = CpuTrainer(self.f.config, list(range(1, 42)))
        with self.assertRaisesRegex(ContractError, 'same actual'): self.capture(other, session)

    def test_pinned_save_load_no_overwrite_bad_sha_and_workspace_escape(self):
        snap = self.capture(); ref = snap.save(self.f.root, 'snapshots/frozen.weights')
        loaded = models.FrozenDuelSnapshot.load(self.f.root, **ref)
        self.assertEqual(loaded.identity(), snap.identity())
        self.assertEqual(loaded.to_state()['state_sha256'], snap.to_state()['state_sha256'])
        with self.assertRaises(FileExistsError): snap.save(self.f.root, ref['path'])
        with self.assertRaisesRegex(ContractError, 'checksum'):
            models.FrozenDuelSnapshot.load(self.f.root, ref['path'], '0'*64)
        with tempfile.TemporaryDirectory() as outside:
            with self.assertRaisesRegex(ContractError, 'workspace'): snap.save(self.f.root, Path(outside)/'escape.weights')

    def test_corrupt_metadata_weights_vocab_and_nonfinite_closed(self):
        state = self.capture().to_state()
        for key, value in (('feature_version', 'old'), ('vocab_sha256', '0'*64), ('model_sha256', '0'*64)):
            bad = deepcopy(state); bad[key] = value
            with self.assertRaises(ContractError): models.FrozenDuelSnapshot.from_state(bad)
        bad = deepcopy(state); next(iter(bad['model'].values())).fill_(float('nan'))
        bad['state_sha256'] = models._tree({k: v for k, v in bad.items() if k != 'state_sha256'})
        with self.assertRaisesRegex(ContractError, 'finite'): models.FrozenDuelSnapshot.from_state(bad)
        bad = deepcopy(state); bad['provenance']['source_stage'] = 'updated_weights'
        with self.assertRaisesRegex(ContractError, 'counters'): models.FrozenDuelSnapshot.from_state(bad)

    def test_snapshot_model_seat_profile_and_policy_mutations_are_detected(self):
        runtime = self.runtime(); opponent = runtime.bind(self.assets, self.f.helper.profile, 1)
        with self.assertRaisesRegex(ContractError, 'seat/version'): opponent.policy.choose(self.req(0))
        d = self.req().to_dict(); d['context']['seed'] = 7
        with self.assertRaises(ContractError): opponent.policy.choose(DecisionRequest.from_dict(d))
        opponent.seat = 0
        with self.assertRaisesRegex(ContractError, 'changed'): opponent.assert_runtime(self.assets.root, self.f.helper.profile, 1)
        opponent.seat = 1
        with torch.no_grad(): next(opponent.policy.model.parameters()).add_(1)
        with self.assertRaisesRegex(ContractError, 'changed'): opponent.assert_runtime(self.assets.root, self.f.helper.profile, 0)
        runtime.snapshot._state['provenance']['source_label'] = 'changed'
        with self.assertRaisesRegex(ContractError, 'changed'): runtime.assert_integrity()

    def test_hidden_worlds_give_identical_tensors_and_policy_contains_no_host_state(self):
        opponent = self.runtime().bind(self.assets, self.f.helper.profile, 1)
        safe_names = set(vars(opponent.policy))
        self.assertEqual(safe_names, {'seat', 'versions', 'encoder', 'model', 'model_sha256'})
        for world in ({'hidden_hand': [40], 'seed': 1}, {'hidden_hand': [41], 'seed': 2}):
            req = self.req()  # same legal observer DTO from either hidden world
            tensors = opponent.policy.encoder.batch([req])
            if world['seed'] == 1: first = tensors; chosen = opponent.policy.choose(req)
            else:
                for name in tensors: self.assertTrue(torch.equal(tensors[name], first[name]))
                self.assertEqual(chosen.action_id, opponent.policy.choose(req).action_id)

    def test_existing_frozen_pool_accepts_exact_model_versions_without_alias_promotion(self):
        first = self.runtime().bind(self.assets, self.f.helper.profile, 1)
        with self.assertRaisesRegex(ContractError, 'duplicate'): FrozenOpponentPool((first, first))
        second_trainer = CpuTrainer(self.f.config.__class__(**dict(self.f.config.__dict__, model_seed=999)), list(range(1, 42)))
        second = self.runtime(self.capture(second_trainer)).bind(self.assets, self.f.helper.profile, 1)
        pool = FrozenOpponentPool((first, second))
        self.assertIs(pool.choose(0), first); self.assertIs(pool.choose(1), second)
        self.assertFalse(pool.manifest()['formal_training_ready'])

    def test_static_asset_preflight_rejects_resources_context_and_missing_target_vocab(self):
        runtime = self.runtime(); runtime.assert_assets(self.assets)
        self.assets.receipt = deepcopy(self.assets.receipt)
        self.assets.receipt['resources']['cards'] = 'changed-catalog'
        with self.assertRaisesRegex(ContractError, 'resources'): runtime.assert_assets(self.assets)
        self.assets.receipt = self.f.helper.receipt
        self.assets.period_context = {'explicit': 'new-target-context'}
        with self.assertRaisesRegex(ContractError, 'context'): runtime.assert_assets(self.assets)
        migrated = models.ModelOpponentRuntime(runtime.snapshot, 'explicit-migration', migration='explicit-inference-migration')
        migrated.assert_assets(self.assets)
        del self.assets.period_context
        self.assets.rows[42] = {'id': 42}
        with self.assertRaisesRegex(ContractError, 'vocabulary'): runtime.assert_assets(self.assets)

    def test_sample_mode_uses_exact_nn_logits_and_private_rng_roundtrips(self):
        from ygo_kito.hierarchical_policy import sample_index
        runtime = models.ModelOpponentRuntime(self.capture(), 'sampled-fixture', policy_mode='sample')
        generator = torch.Generator(device='cpu').manual_seed(700)
        opponent = runtime.bind(self.assets, self.f.helper.profile, 1, policy_rng=generator)
        policy = opponent.policy; req = self.req()
        original = policy.sampling_state(); global_rng = torch.get_rng_state().clone()
        weights = parameter_digest(policy.model)
        with torch.no_grad(): logits, _ = score_requests(policy.model, policy.encoder, [req])
        mirror = torch.Generator(device='cpu').set_state(generator.get_state())
        expected = [req.actions[sample_index(logits[0], generator=mirror, max_actions=policy.encoder.config.max_actions)[0]].action_id for _ in range(32)]
        actual = [policy.choose(req).action_id for _ in range(32)]
        self.assertEqual(actual, expected); self.assertGreater(len(set(actual)), 1)
        saved = policy.sampling_state()
        policy.restore_sampling_state(original)
        self.assertEqual([policy.choose(req).action_id for _ in range(32)], actual)
        self.assertEqual(policy.sampling_state(), saved)
        bad = deepcopy(saved); bad['model_sha256'] = '0'*64
        with self.assertRaisesRegex(ContractError, 'another snapshot'): policy.restore_sampling_state(bad)
        bad = deepcopy(saved); bad['rng_state'] = [0]
        with self.assertRaisesRegex(ContractError, 'byte state'): policy.restore_sampling_state(bad)
        self.assertEqual(policy.sampling_state(), saved)
        self.assertEqual(parameter_digest(policy.model), weights)
        self.assertTrue(torch.equal(torch.get_rng_state(), global_rng))
        self.assertNotIn('policy_rng', vars(policy.model)); self.assertNotIn('rng_state', req.to_dict())

    def test_mode_seed_and_labels_cannot_create_independent_data_split(self):
        snapshot = self.capture()
        greedy = models.ModelOpponentRuntime(snapshot, 'greedy-fixture')
        sampled = models.ModelOpponentRuntime(snapshot, 'sampled-fixture', policy_mode='sample')
        with self.assertRaisesRegex(ContractError, 'owned CPU'): sampled.bind(self.assets, self.f.helper.profile, 1)
        with self.assertRaisesRegex(ContractError, 'does not consume'):
            greedy.bind(self.assets, self.f.helper.profile, 1, policy_rng=torch.Generator())
        first = greedy.bind(self.assets, self.f.helper.profile, 1)
        others = [sampled.bind(self.assets, self.f.helper.profile, 1, policy_rng=torch.Generator().manual_seed(seed)) for seed in (800, 900)]
        for other in others:
            self.assertEqual(opponent_identity(first.binding), opponent_identity(other.binding))
            self.assertEqual(first.binding['driver_version'], other.binding['driver_version'])
        row = {'dataset_id': 'sample-train', 'experiment_id': 'same-model-isolation', 'purpose': 'train', 'family': 'duel',
            'versions': asdict(first.versions), 'opponents': [first.binding], 'task_sha256': None}
        self.f.index.freeze(row)
        with self.assertRaisesRegex(ContractError, 'crosses train/validation/final'):
            self.f.index.freeze(dict(row, dataset_id='sample-final', purpose='final_eval', opponents=[others[1].binding]))


if __name__ == '__main__': unittest.main()
