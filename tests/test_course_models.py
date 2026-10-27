"""Own CPU tensors and synthetic semantic catalog only, not training ability.

Small artificial weight losses verify actual LoRA/Adam checkpoint persistence.
No rule engine, native response, external bot, paid model or formal course runs.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

import torch

from tests.test_autonomous_construction import fixture
from ygo_kito.course_models import CourseModels
from ygo_kito.build_contracts import digest
from ygo_kito.course_game_adapter import CourseTrainingConfig, course_config_from_dict
from ygo_kito.cpu_training import CpuTrainingConfig
from ygo_kito.duel_model import DuelModelConfig, parameter_digest
from ygo_kito.group_runner import tree_digest
from ygo_kito.lora import AdapterConfig
from ygo_kito.validation import ContractError
from ygo_kito import course_models as actual_models


def models_fixture(root):
    task, assets, _, _ = fixture(initialize=False)
    configs = {r: AdapterConfig('course-' + r, r,
        ('head.0',) if r.startswith('build_') else ('policy_head.0',) if r == 'duel' else ('route_head',),
        rank=1, max_updates=4) for r in ('build_goal', 'build_optimizer', 'duel', 'coordinator')}
    cfg = CourseTrainingConfig(model=DuelModelConfig(width=8, card_width=4, heads=2, feedforward=16),
                               game_seeds=(100, 101, 102), episode_seconds=120)
    binding = {'kind': 'synthetic-course-model-fixture-not-trained', 'host_config_sha256': 'a'*64}
    models = CourseModels.initialize(task, assets, cfg, configs, root, None, assets.rows, binding)
    return models, assets


def artificial_steps(models):
    for role, session in models.sessions.items():
        before = parameter_digest(session.model)
        # Explicit synthetic tensor loss, not real labels or played episodes.
        loss = session.model.get_submodule(session.config.targets[0]).weight.square().sum()
        session.step(loss)
        if role.startswith('build_'):
            models.kernel.record_update(role, before_sha256=before, after_sha256=parameter_digest(session.model))


class CourseModelsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.models, self.assets = models_fixture(self.root)

    def test_existing_four_models_global_vocabulary_and_actual_sessions(self):
        self.assertEqual(set(self.models.models()), {'build_goal', 'build_optimizer', 'duel', 'coordinator'})
        self.assertEqual(self.models.builder.encoder.card_ids, tuple(range(1, 37)))
        self.assertEqual(self.models.duel.encoder.card_ids, tuple(range(1, 37)))
        self.assertEqual(self.models.initialization_provenance['kind'], 'explicit-fresh-untrained-course-models')
        self.assertFalse(self.models.initialization_provenance['ability_verified'])
        for role, model in self.models.models().items():
            self.assertIs(model, self.models.sessions[role].model)
            self.models.sessions[role].verify_base()

    def test_four_actual_adapter_updates_save_restore_all_weights_optimizers_and_rng(self):
        artificial_steps(self.models)
        before = self.models.fingerprint()
        state = self.models.save_state()
        versions = self.models.versions()
        # The returned dictionary is a snapshot, not live tensor references.
        artificial_steps(self.models)
        torch.rand(5); random.random(); self.models.policy_rng.get_state()
        restored = self.models.restore_state(state, assets=self.assets, expected_binding=self.models.binding)
        self.assertIs(restored, self.models)
        self.assertEqual(self.models.fingerprint(), before)
        self.assertEqual(self.models.versions(), versions)
        self.assertEqual(self.models.kernel.updates, {'build_goal': 1, 'build_optimizer': 1})
        for session in self.models.sessions.values():
            self.assertEqual(session.updates, 1)
            self.assertTrue(session.optimizer.state)
            self.assertEqual(session.scheduler.last_epoch, 1)

    def test_weights_only_roundtrip_and_fresh_process_needs_no_source_artifact(self):
        artificial_steps(self.models)
        state = self.models.save_state()
        path = self.root / 'course.weights'; torch.save(state, path)
        loaded = torch.load(path, weights_only=True, map_location='cpu')
        rebuilt = CourseModels.from_state(loaded, assets=self.assets, expected_binding=self.models.binding)
        self.assertEqual(rebuilt.fingerprint(), state['state_sha256'])
        self.assertEqual(rebuilt.builder.encoder.binding(), state['vocabulary']['build'])
        self.assertEqual(rebuilt.duel.config.episode_seconds, 120)

    def test_bad_hash_binding_nan_vocabulary_and_kernel_restore_leave_live_bundle_unchanged(self):
        artificial_steps(self.models); state = self.models.save_state(); before = self.models.fingerprint()
        cases = []
        bad = deepcopy(state); bad['binding']['host_config_sha256'] = 'b'*64; cases.append(bad)
        bad = deepcopy(state); next(iter(bad['components']['models']['duel'].values())).fill_(float('nan')); cases.append(bad)
        bad = deepcopy(state); bad['vocabulary']['build']['cards'][-1] = 9999
        bad['state_sha256'] = tree_digest({k:v for k,v in bad.items() if k != 'state_sha256'}); cases.append(bad)
        bad = deepcopy(state); bad['kernel']['updates']['build_goal'] = -1
        bad['state_sha256'] = tree_digest({k:v for k,v in bad.items() if k != 'state_sha256'}); cases.append(bad)
        for index, bad in enumerate(cases):
            with self.subTest(index=index), self.assertRaises((ContractError, RuntimeError)):
                self.models.restore_state(bad, assets=self.assets, expected_binding=self.models.binding)
            self.assertEqual(self.models.fingerprint(), before)

    def test_wrong_optimizer_moment_shape_rejected_before_publishing_candidate(self):
        artificial_steps(self.models); state = self.models.save_state(); before = self.models.fingerprint()
        optimizer = state['adapters']['duel']['optimizer']
        next(iter(optimizer['state'].values()))['exp_avg'] = torch.ones(1)
        state['state_sha256'] = tree_digest({k:v for k,v in state.items() if k != 'state_sha256'})
        with self.assertRaisesRegex(ContractError, 'optimizer moments'):
            self.models.restore_state(state, assets=self.assets, expected_binding=self.models.binding)
        self.assertEqual(self.models.fingerprint(), before)

    def test_rng_and_module_modes_restore_without_erasing_external_course_state(self):
        before = self.models.fingerprint(); state = self.models.rng_state()
        for model in self.models.models().values(): model.eval()
        torch.rand(4); random.random()
        torch.rand(4, generator=self.models.policy_rng)
        self.models.restore_rng(state)
        self.assertEqual(self.models.fingerprint(), before)

    def test_missing_explicit_source_is_rejected_without_fresh_fallback(self):
        m = self.models
        with self.assertRaisesRegex(ContractError, 'regular file'):
            CourseModels.initialize(m.builder.task, self.assets, m.duel.config, m.adapter_configs, self.root,
                {'path': 'missing.weights', 'sha256': 'a'*64, 'weights': 'effective', 'source_binding_sha256': 'b'*64},
                self.assets.rows, m.binding)

    def test_new_course_timeout_does_not_weaken_legacy_and_roundtrips_config(self):
        value = asdict(self.models.duel.config)
        self.assertIsInstance(course_config_from_dict(value), CourseTrainingConfig)
        self.assertEqual(course_config_from_dict(value).episode_seconds, 120)
        with self.assertRaises(ContractError): CpuTrainingConfig(episode_seconds=120)
        for seconds in (301, 0, float('nan')):
            with self.assertRaises(ContractError): course_config_from_dict(dict(value, episode_seconds=seconds))

    def test_real_existing_source_materializes_all_roles_then_source_can_be_removed(self):
        # This is the existing initializer's own synthetic complete-shape
        # artifact, not a claim that its declared cursors came from games.
        from tests.test_group_initialization import own_source, trainers
        from ygo_kito.build_contracts import BuildTask
        from ygo_kito.coordinator_model import CoordinatorTrainer, CoordinatorModelConfig
        import hashlib
        source = own_source(self.root)
        old_builder, old_duel, _, _ = trainers()
        raw = old_builder.task.to_dict(); raw['schema_version'] = 4
        raw['environment']['versions']['card_pool'] = 'native-private-knowledge-v5'
        raw['goal'] = {'kind': 'deck_constraints', 'constraints': [
            {'id': 'monsters', 'zones': ['main'], 'predicate': {'field': 'type_all', 'value': 1}, 'minimum': 40, 'maximum': 40}],
            'preferences': []}
        task = BuildTask.from_dict(raw); assets = old_builder.encoder.assets
        path = self.root / 'source-group.weights'; torch.save(source, path)
        spec = {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'weights': 'effective', 'source_binding_sha256': digest(source['binding'])}
        coordinator_factory = lambda config=None, **kwargs: CoordinatorTrainer(config or CoordinatorModelConfig(hidden=4), **kwargs)
        with patch.object(actual_models, 'BuildTrainingConfig', return_value=old_builder.config), \
                patch.object(actual_models, 'CoordinatorModelConfig', side_effect=lambda **kw: CoordinatorModelConfig(hidden=4, **kw)), \
                patch.object(actual_models, 'CoordinatorTrainer', side_effect=coordinator_factory):
            inherited = CourseModels.initialize(task, assets, old_duel.config, self.models.adapter_configs, self.root,
                spec, assets.rows, {'kind': 'own-source-shape-fixture'})
        for role, model in inherited.models().items():
            component = source['components']['build']['models'][role] if role.startswith('build_') else source['components'][role]['model']
            adapter = source['adapters'][role]; target = adapter['compatibility']['config']['targets'][0]
            a, b = adapter['weights'][target+'.a'], adapter['weights'][target+'.b']
            expected = component[target+'.weight'] + (b @ a)*2
            self.assertTrue(torch.equal(model.get_submodule(target).weight.detach(), expected))
        saved = inherited.save_state(); path.unlink()
        recovered = CourseModels.from_state(saved, assets=assets, expected_binding=inherited.binding)
        self.assertEqual(recovered.fingerprint(), saved['state_sha256'])
        self.assertEqual(recovered.initialization_provenance['materialization'], 'cpu-fp32-base-plus-saved-lora')


if __name__ == '__main__': unittest.main()
