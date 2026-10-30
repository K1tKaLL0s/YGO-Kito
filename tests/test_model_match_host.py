"""Functional CLI/host with real neural inference and an explicit fake engine.

All resources/decks, native windows and outcomes here are synthetic fixtures.
No core, C#, timing pilot, formal matches or weight training is run.
"""
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
from dataclasses import asdict, replace
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import torch

from tests.fixtures import request
import tests.test_course_game_adapter as fixtures
from ygo_kito import course_game_adapter as course, model_match_host as host, model_opponents as neural
from ygo_kito.contracts import DecisionRequest, validate_selection
from ygo_kito.cpu_training import CpuTrainer
from ygo_kito.duel_model import FEATURE_VERSION
from ygo_kito.lora import AdapterConfig, AdapterSession
from ygo_kito.validation import ContractError


class ModelMatchHostTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.CourseGameAdapterTests('test_base_two_fresh_ppo_games_sideboards_and_actual_seat_swap')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.root, self.assets = self.f.root, self.f.assets
        self.engines, self.selections, self.fail_game = [], [], None
        for target in (neural, course):
            mock = patch.object(target, 'verify_resources', return_value=self.assets.receipt)
            mock.start(); self.addCleanup(mock.stop)
        patcher = patch.object(host, 'BuildAssets', return_value=self.assets)
        patcher.start(); self.addCleanup(patcher.stop)
        self.snapshots = []
        for i, seed in enumerate((999, 998)):
            trainer = CpuTrainer(replace(self.f.config, model_seed=seed), list(range(1, 42)))
            snapshot = neural.FrozenDuelSnapshot.capture(trainer, assets=self.assets,
                source_binding={'fixture': 'initial-'+str(i)}, source_label='fixture initial CPU network')
            self.snapshots.append(snapshot)
        self.spec = {'schema_version': 1, 'kind': host.KIND, 'run_id': 'fixture-functional-match',
            'native_root': str(self.assets.root.relative_to(self.root)),
            'profile': self.f.helper.write_json('functional-profile.json', self.f.helper.profile),
            'snapshot_a': self.snapshots[0].save(self.root, 'snapshots/a.weights'),
            'snapshot_b': self.snapshots[1].save(self.root, 'snapshots/b.weights'),
            'migration_a': 'same-period-inference', 'migration_b': 'same-period-inference',
            'format': 'bo1', 'seed_pairs': [[100, 200]], 'episode_seconds': 120, 'native_decision_limit': 3000,
            'first_participant_id': 'model-a', 'first_order': {'model-a': 'always_first', 'model-b': 'always_first'},
            'sideboard_policy': 'keep_side_baseline', 'state_root': '.cache/functional-fixture'}

    @contextmanager
    def fake_engine(self):
        owner = self
        class NormalFixture:
            def __init__(self, root, **options):
                self.profile = options['deck_profile']; owner.engines.append(deepcopy(self.profile))
                self.number = int(self.profile['name'].rsplit('-', 1)[1])
                if self.number == owner.fail_game: raise RuntimeError('explicit fixture unsupported game')
                self.receipt = owner.assets.receipt; self._selection_seed = options['selection_key']
                self.events = []; self.outcome = None; self.turn = 1; self.life_points = [8000, 8000]
                self.cursor = 0; self.pending = None
                self.requests = []
                for seat in (0, 1):
                    d = request(); d['context']['seed'] = None
                    d['context']['versions'] = asdict(neural._versions(owner.assets))
                    d['observation'].update(observer=seat, turn_player=0)
                    d['observation']['cards'][0].update(owner=seat, controller=seat, card_id=seat+1)
                    d['observation']['cards'][1].update(owner=1-seat, controller=1-seat)
                    d['decision_id'] = 'functional-fake-seat-'+str(seat)
                    self.requests.append(DecisionRequest.from_dict(d))
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def next_decision(self):
                if self.cursor == 2:
                    self.events = [{'kind': 5}]
                    # Two actual typed small-game results for fixture A wins;
                    # the BO3 loser chooses B first for the second small game.
                    self.outcome = {'winner': 0 if self.number == 1 else 1, 'reason_code': 1}
                    self.pending = None; return None
                self.pending = self.requests[self.cursor]; self.cursor += 1
                return self.pending
            def submit(self, selected):
                validate_selection(self.pending, selected)
                owner.selections.append((self.pending.observation.observer, selected.action_id))
            def _observation(self, seat): return self.requests[seat].observation
        class Engine(course._FirstTurnObservation, NormalFixture): pass
        with patch.object(course, '_CourseNativeEngine', Engine), \
                patch('ygo_kito.cpu_training.public_card_facts', return_value={}), \
                patch('ygo_kito.training_admission.require_training_admission',
                      return_value={'status':'admitted','fixture':'synthetic-engine-only'}), \
                patch.object(CpuTrainer, 'update', side_effect=AssertionError('functional inference cannot train')), \
                patch.object(AdapterSession, 'step', side_effect=AssertionError('functional inference cannot adapt')):
            yield

    def test_default_preflight_reads_pins_but_never_starts_native_or_creates_index(self):
        before = torch.get_rng_state().clone()
        with patch.object(course, '_CourseNativeEngine', side_effect=AssertionError('no native')), \
                patch.object(host, 'DataIndex', side_effect=AssertionError('no DB')):
            report = host.preflight(self.root, self.spec)
        self.assertEqual(report['status'], 'ready'); self.assertFalse(report['native_executed'])
        self.assertFalse((self.root/self.spec['state_root']).exists())
        self.assertTrue(torch.equal(before, torch.get_rng_state()))
        self.assertEqual(report['snapshot_a']['provenance']['source_stage'], 'engineering_initial')
        self.assertFalse(report['weights_identical']); self.assertTrue(report['independent_network_objects'])
        self.assertNotIn('seed_pairs', json.dumps(report))

    def test_bo1_runs_actual_two_network_sampler_and_preserves_exact_weights_zero_updates(self):
        identities = [s.identity() for s in self.snapshots]
        with self.fake_engine(): report = host.run(self.root, self.spec)
        self.assertEqual(report['status'], 'completed'); self.assertEqual(report['completed_games'], 1)
        self.assertEqual(report['completed_functional_matches'], 1); self.assertEqual(len(self.engines), 1)
        self.assertEqual(len(self.selections), 2)
        self.assertTrue(report['actor_training_state_unchanged'])
        self.assertEqual(report['actor_shell']['model_sha256'], identities[0]['model_sha256'])
        self.assertEqual(report['execution_updates'], {'actor_base': 0, 'actor_adapter': 0, 'opponent': 0})
        self.assertEqual(report['formal_games'], 0); self.assertFalse(report['timing_pilot'])
        self.assertEqual(report['actual_first_game_counts'], {'model-a': 1, 'model-b': 0})
        self.assertEqual([s.identity() for s in self.snapshots], identities)
        private = self.root/self.spec['state_root']
        self.assertTrue((private/'data-index/data-index.sqlite3').is_file())
        self.assertTrue((private/'game-1-private.json').is_file())
        public = json.dumps(report)
        for secret in ('seed_pairs', 'seed_audit_only', 'selection_key_audit_only', 'old_log_prob', 'elapsed_seconds', 'actor_inference_ms'):
            self.assertNotIn(secret, public)
        with self.assertRaisesRegex(ContractError, 'already exists'): host.run(self.root, self.spec)

    def test_bo3_uses_loser_choice_and_explicit_unchanged_sideboards_across_two_games(self):
        spec = deepcopy(self.spec); spec.update(format='bo3', seed_pairs=[[100, 200], [101, 201], [102, 202]])
        with self.fake_engine(): report = host.run(self.root, spec)
        self.assertEqual(report['status'], 'completed'); self.assertEqual(report['completed_games'], 2)
        self.assertEqual(report['completed_functional_matches'], 1)
        self.assertEqual([g['selected_first_participant_id'] for g in report['games']], ['model-a', 'model-b'])
        self.assertEqual(report['actual_first_game_counts'], {'model-a': 1, 'model-b': 1})
        self.assertEqual(self.engines[1]['sides'], self.engines[0]['sides'])
        private = json.loads((self.root/spec['state_root']/'match-private.json').read_text())
        self.assertEqual([x['kind'] for x in private['transitions']], ['game', 'sideboards', 'first_choice', 'game'])
        self.assertEqual(report['sideboard_policy'], 'keep_side_baseline')

    def test_failure_keeps_first_game_and_uncertain_receipt_without_retry_or_formal_count(self):
        spec = deepcopy(self.spec); spec.update(format='bo3', seed_pairs=[[100, 200], [101, 201], [102, 202]])
        self.fail_game = 2
        with self.fake_engine(): report = host.run(self.root, spec)
        self.assertEqual(report['status'], 'failed_or_uncertain'); self.assertEqual(len(self.engines), 2)
        self.assertEqual(report['completed_games'], 1); self.assertEqual(report['completed_functional_matches'], 0)
        self.assertFalse(report['games'][1]['completed']); self.assertEqual(report['formal_matches'], 0)
        self.assertTrue((self.root/spec['state_root']/'game-2-host.json').is_file())
        self.assertTrue((self.root/spec['state_root']/'game-1-private.json').is_file())

    def test_identical_snapshot_allowed_but_two_independent_networks_are_explicit(self):
        spec = deepcopy(self.spec); spec['snapshot_b'] = spec['snapshot_a']
        report = host.preflight(self.root, spec)
        self.assertTrue(report['weights_identical']); self.assertTrue(report['snapshot_identities_equal'])
        self.assertTrue(report['independent_network_objects'])

    def test_updated_effective_lora_source_is_exact_and_not_restored_as_training_state(self):
        trainer = CpuTrainer(self.f.config, list(range(1, 42)))
        session = AdapterSession(trainer.model,
            AdapterConfig('fixture-source', 'duel', ('policy_head.2',), rank=1),
            {'base_version': 'fixture-base', 'feature_version': FEATURE_VERSION, 'context_sha256': 'a'*64})
        # Artificial tensor loss only; no claim of trained game capability.
        session.step(sum((v - .2).square().sum() for v in session.weights().values()))
        snapshot = neural.FrozenDuelSnapshot.capture(trainer, assets=self.assets, adapter_session=session,
            source_binding={'fixture': 'one-artificial-optimizer-step'}, source_label='artificial updated LoRA fixture')
        spec = deepcopy(self.spec); spec['snapshot_a'] = snapshot.save(self.root, 'snapshots/source-lora.weights')
        with self.fake_engine(): report = host.run(self.root, spec)
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['snapshot_a']['provenance']['adapter']['updates'], 1)
        self.assertEqual(report['snapshot_a']['provenance']['source_stage'], 'updated_weights')
        self.assertEqual(report['actor_shell']['model_sha256'], snapshot.identity()['model_sha256'])
        self.assertFalse(report['actor_shell']['source_training_state_restored'])
        self.assertEqual(report['actor_shell']['updates'], 0)
        self.assertEqual(report['training_updates'], 0)

    def test_bad_pin_profile_limits_unknown_fields_and_state_escape_fail_closed(self):
        bad_cases = []
        for key, value in (('episode_seconds', 301), ('native_decision_limit', 3001), ('seed_pairs', [[1, 2], [2, 3]]),
                           ('sideboard_policy', 'silent-random'), ('engine_factory', 'not-a-production-option'),
                           ('state_root', '../escape')):
            d = deepcopy(self.spec); d[key] = value; bad_cases.append(d)
        bad = deepcopy(self.spec); bad['snapshot_b']['sha256'] = '0'*64; bad_cases.append(bad)
        profile = deepcopy(self.f.helper.profile); profile['adapter_revision'] = 4
        bad = deepcopy(self.spec); bad['profile'] = self.f.helper.write_json('old-profile.json', profile); bad_cases.append(bad)
        with patch.object(course, '_CourseNativeEngine', side_effect=AssertionError('must not start')):
            for bad in bad_cases:
                with self.subTest(bad=next(k for k in bad if bad[k] != self.spec.get(k))), self.assertRaises(ContractError):
                    host.preflight(self.root, bad)
        self.assertFalse((self.root/self.spec['state_root']).exists())

    def test_sampled_opponent_modes_have_private_per_game_rng_and_no_public_seed_state(self):
        spec = deepcopy(self.spec)
        spec.update(format='bo3', seed_pairs=[[100, 200], [101, 201], [102, 202]],
            opponent_policy_mode='sample', opponent_policy_seeds=[600, 601, 602])
        with self.fake_engine(): report = host.run(self.root, spec)
        self.assertEqual(report['status'], 'completed'); self.assertEqual(report['opponent_policy_mode'], 'sample')
        private = self.root/spec['state_root']
        receipts = [json.loads((private/('game-'+str(i)+'-host.json')).read_text())['opponent_sampling'] for i in (1, 2)]
        for row in receipts:
            self.assertTrue(row['caller_rng_unchanged'])
            self.assertEqual(row['after']['decisions'], 1)
            self.assertNotEqual(row['before']['rng_state'], row['after']['rng_state'])
        self.assertNotEqual(receipts[0]['before']['rng_state'], receipts[1]['before']['rng_state'])
        public = json.dumps(report)
        for key in ('opponent_policy_seeds', 'rng_state', 'elapsed_seconds', 'actor_inference_ms'):
            self.assertNotIn(key, public)
        self.assertTrue(report['actor_training_state_unchanged']); self.assertEqual(report['training_updates'], 0)

    def test_budget_failure_persists_bounded_legal_diagnostics_without_episode_or_reward(self):
        spec = deepcopy(self.spec); spec.update(native_decision_limit=1, opponent_policy_mode='sample', opponent_policy_seeds=[600])
        with self.fake_engine(): report = host.run(self.root, spec)
        self.assertEqual(report['status'], 'failed_or_uncertain'); self.assertEqual(report['completed_games'], 0)
        private = self.root/spec['state_root']
        diagnostic = json.loads((private/'game-1-partial.json').read_text())
        self.assertEqual(diagnostic['windows'], 2); self.assertEqual(diagnostic['submit_returned'], 1)
        self.assertFalse(diagnostic['terminal_claimed']); self.assertFalse(diagnostic['training_eligible'])
        self.assertFalse((private/'game-1-private.json').exists())
        for key in ('card_id', 'seed', 'reward', 'private_reveals'):
            self.assertNotIn(key, json.dumps(diagnostic))
        self.assertEqual(report['training_updates'], 0)

    def test_sampling_config_requires_exact_private_seed_schedule_without_greedy_ignore(self):
        for extra in ({'opponent_policy_mode': 'sample'},
                      {'opponent_policy_mode': 'sample', 'opponent_policy_seeds': [1, 2]},
                      {'opponent_policy_mode': 'sample', 'opponent_policy_seeds': [True]},
                      {'opponent_policy_mode': 'greedy', 'opponent_policy_seeds': [1]},
                      {'opponent_policy_mode': 'random-fallback', 'opponent_policy_seeds': [1]}):
            with self.subTest(extra=extra), self.assertRaises(ContractError):
                host.validate_spec(dict(self.spec, **extra))

    def test_cli_default_is_preflight_and_run_is_explicit(self):
        path = self.root/'functional-spec.json'; path.write_text(json.dumps(self.spec))
        script = Path(__file__).resolve().parents[1]/'scripts/model_match.py'
        module_spec = importlib.util.spec_from_file_location('model_match_cli_fixture', script)
        cli = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(cli)
        buffer = io.StringIO()
        with redirect_stdout(buffer), patch.object(host, 'run', side_effect=AssertionError('no implicit run')):
            code = cli.main(['--workspace', str(self.root), '--spec', str(path)])
        self.assertEqual(code, 0); self.assertEqual(json.loads(buffer.getvalue())['status'], 'ready')
        buffer = io.StringIO()
        with redirect_stdout(buffer), self.fake_engine():
            code = cli.main(['--workspace', str(self.root), '--spec', str(path), '--run'])
        self.assertEqual(code, 0); self.assertEqual(json.loads(buffer.getvalue())['status'], 'completed')


if __name__ == '__main__': unittest.main()
