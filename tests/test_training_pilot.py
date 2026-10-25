"""Synthetic snapshot/engine/room fixtures only; no C#, core or real timing.

The tiny saved model gets one artificial tensor-loss update solely to exercise
the completed-checkpoint loader. It is not a trained game policy or capability
evidence. Sampler wiring still executes the real neural inference function.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from tests.fixtures import request
from tests.test_windbot_projection import fixture_engine, draw, idle
from ygo_kito import training_pilot as pilot
from ygo_kito.build_contracts import digest
from ygo_kito.contracts import DecisionRequest, Versions
from ygo_kito.cpu_training import CpuTrainer, CpuTrainingConfig, save_checkpoint
from ygo_kito.duel_model import DuelModelConfig, FEATURE_VERSION, parameter_digest
from ygo_kito.hierarchical_policy import score_requests
from ygo_kito.validation import ContractError
from ygo_kito.windbot_projection import WindBotOpponent


class TrainingPilotTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = self.root / 'native'; self.native.mkdir()
        (self.root / 'sources').mkdir()
        self.profile = {'schema_version': 2, 'name': 'synthetic-not-user-deck', 'adapter_revision': 5,
                        'decks': [list(range(1, 41)), list(range(1, 41))], 'extras': [[], []], 'sides': [[], []]}
        self.receipt = {'source_commits': {'core': 'fixture-core'}, 'resources': {
            'scripts': 'fixture-scripts', 'cards': 'fixture-cards', 'client_protocol': 'fixture-protocol', 'banlist': 'fixture-banlist'}}
        self.binding = dict(self.receipt, feature_version=FEATURE_VERSION, profile_sha256=digest(self.profile))
        trainer = CpuTrainer(CpuTrainingConfig(model=DuelModelConfig(width=8, card_width=4, heads=2, feedforward=16),
                                               game_seeds=(10, 11)), list(range(1, 41)))
        # Artificial engineering-only tensor update, no duel/sample/ability.
        loss = trainer.model.policy_head[0].weight.square().sum()
        loss.backward(); trainer.optimizer.step(); trainer.optimizer.zero_grad(); trainer.scheduler.step()
        trainer.updates = trainer.episode_cursor = 1
        checkpoint = save_checkpoint(trainer, self.root, 'synthetic-completed', self.binding)
        self.snapshot_state = torch.load(checkpoint, weights_only=True)
        self.spec = {'schema_version': 1, 'kind': 'cpu-frozen-model-bot-timing-pilot', 'mode': 'bo1',
            'snapshot': dict(self.reference(checkpoint), kind='completed-duel-checkpoint', source_binding_sha256=digest(self.binding),
                             model_sha256=parameter_digest(trainer.model), migration='explicit-frozen-inference'),
            'bot_sources': {'lock': self.write_json('lock.json', {'fixture': 'no-real-bot-sources'}),
                            'installed_root': 'sources', 'mono': '/fixture/not-installed/mono',
                            'audits': {'ice': self.write_json('audit.json', {'fixture': 'not-an-actual-audit'})}},
            'cases': [{'case_id': 'synthetic-case', 'profile': self.write_json('profile.json', self.profile),
                       'actor_seat': 0, 'source_id': 'ice', 'executor_id': 'FixtureExecutor',
                       'seeds': [{'game_seed': 100, 'policy_seed': 200}], 'coverage': ['fixture-only'],
                       'evidence_source': 'engineering_fixture'}],
            'limits': {'episode_seconds': 120, 'native_decision_limit': 100}, 'reserved_evaluation_seeds': [900]}
        self.assets = SimpleNamespace(receipt=self.receipt,
            rows={c: {'id': c, 'ot': 1, 'type': 17, 'alias': 0} for c in range(1, 41)}, limits={})
        self.versions = Versions('fixture-core', 'fixture-scripts', 'fixture-cards', 'fixture-protocol',
                                 'native-private-knowledge-v5', '2026.10:fixture-banlist')
        self.registry_inventory = {'inventory_sha256': digest('synthetic-inventory'), 'origins': [
            {'bot_id': 'f'*64, 'source_id': 'ice', 'class_name': 'FixtureExecutor'}]}
        qualification_binding = self.fixture_binding(profile=self.profile, environment_id='bot-current-engineering-qualification',
            opponent_id='qual-'+'f'*32, source='engineering_fixture', session_seconds=120)
        self.qualification = {'schema_version': 1, 'kind': 'all-source-bot-engineering-qualification-results',
            'context': 'current-pinned-2026.10-engineering-resources-not-historical-course', 'resources': self.receipt,
            'source_lock_sha256': digest({'fixture': 'no-real-bot-sources'}),
            'inventory_sha256': self.registry_inventory['inventory_sha256'], 'actor_profile_sha256': digest(self.profile),
            'variant': None, 'actor_seat': 0, 'counts': {'normal_game_verified': 1},
            'native_executed': True, 'csharp_executed': True, 'normal_duel_verified': True,
            'historical_qualified': False, 'strength_qualified': False, 'training_updates': 0,
            'normal_game_seconds': 120, 'csharp_session_wall_seconds': 120, 'bound_scope': 'fixture-only',
            'all_selected_normal_verified': True, 'rows': [{
                'bot_id': 'f'*64, 'runtime_source_id': 'ice', 'runtime_executor_id': 'FixtureExecutor',
                'status': 'normal_game_verified', 'list_legal': True, 'runtime_candidate': True,
                'normal_duel_verified': True, 'native_executed': True, 'csharp_executed': True,
                'profile_sha256': digest(self.profile), 'deck_sha256': qualification_binding['opponent_deck_sha256'],
                'binding_sha256': digest(qualification_binding), 'decisions': 2, 'bot_decisions': 1, 'turns': 1,
                'outcome': {'winner': 0, 'reason_code': 1}, 'trajectory_sha256': 'a'*64}]}
        self.spec['cases'][0]['qualification'] = self.write_json('qualification-fixture.json', self.qualification)

    def fixture_binding(self, **kwargs):
        profile = kwargs['profile']
        other = {'main': profile['decks'][1], 'extra': profile['extras'][1], 'side': profile['sides'][1]}
        return {'profile_sha256': digest(profile), 'driver_version': 'explicit-fixture-not-csharp',
                'opponent_deck_sha256': digest(other),
                'registered_record_sha256': digest({k: kwargs[k] for k in ('environment_id', 'opponent_id', 'source', 'session_seconds')})}

    def reference(self, path):
        return {'path': str(path.relative_to(self.root)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def write_json(self, name, value):
        path = self.root / name; path.write_text(json.dumps(value))
        return self.reference(path)

    def save_changed(self, state):
        path = self.root / 'changed.weights'; torch.save(state, path)
        spec = deepcopy(self.spec['snapshot']); spec.update(self.reference(path))
        return spec

    @contextmanager
    def patched_assets(self, adapter_factory=None):
        captured = []
        def construct(executor, **kwargs):
            captured.append(kwargs)
            if adapter_factory is not None: return adapter_factory(executor, **kwargs)
            return WindBotOpponent(root=self.native, profile=kwargs['profile'], seat=kwargs['seat'], versions=kwargs['versions'],
                binding=self.fixture_binding(**kwargs),
                runtime_validator=lambda: None, room_factory=lambda _: None)
        registry = SimpleNamespace(training_adapter=construct, lock={'fixture': 'no-real-bot-sources'}, inventory=self.registry_inventory)
        with patch.object(pilot, 'BuildAssets', return_value=self.assets), patch.object(pilot, 'BotSourceRegistry', return_value=registry):
            yield captured

    def test_strict_mode_snapshot_and_null_resource_rejection(self):
        for path, value in ((('mode',), 'bo3'), (('snapshot', 'kind'), 'group'), (('snapshot', 'path'), None),
                            (('limits', 'episode_seconds'), 301), (('limits', 'native_decision_limit'), 3001),
                            (('bot_sources', 'room_factory'), 'fallback')):
            spec = deepcopy(self.spec); target = spec
            for key in path[:-1]: target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(ContractError): pilot.validate_pilot_spec(spec)

    def test_completed_snapshot_exact_weights_neural_forward_and_rng_preserved(self):
        rng = torch.get_rng_state().clone()
        frozen, config, provenance = pilot.load_actor_snapshot(self.root, self.spec['snapshot'], self.receipt)
        self.assertTrue(torch.equal(rng, torch.get_rng_state()))
        self.assertEqual(parameter_digest(frozen.model), self.spec['snapshot']['model_sha256'])
        self.assertEqual(provenance['completed_updates'], 1)
        self.assertFalse(any(p.requires_grad for p in frozen.model.parameters()))
        payload = request(); payload['context']['seed'] = None
        with torch.no_grad(): logits, values = score_requests(frozen.model, frozen.encoder, [DecisionRequest.from_dict(payload)])
        self.assertEqual(tuple(logits.shape), (1, 2)); self.assertTrue(torch.isfinite(values).all())
        self.assertEqual(config.game_seeds, (10, 11))
        self.assertFalse(provenance['source_training_ability_verified'])

    def test_initial_corrupt_nonfinite_and_wrong_feature_snapshots_rejected(self):
        changes = [('boundary', 'initial'), ('updates', 0), ('role', 'build_goal'), ('model_sha256', '0'*64)]
        for key, value in changes:
            state = deepcopy(self.snapshot_state); state[key] = value
            with self.subTest(key=key), self.assertRaises(ContractError):
                pilot.load_actor_snapshot(self.root, self.save_changed(state), self.receipt)
        state = deepcopy(self.snapshot_state); next(iter(state['model'].values())).fill_(float('nan'))
        with self.assertRaisesRegex(ContractError, 'finite'): pilot.load_actor_snapshot(self.root, self.save_changed(state), self.receipt)
        receipt = deepcopy(self.receipt); receipt['resources']['cards'] = 'different'
        with self.assertRaisesRegex(ContractError, 'compatible'): pilot.load_actor_snapshot(self.root, self.spec['snapshot'], receipt)
        spec = deepcopy(self.spec['snapshot']); spec['sha256'] = '0'*64
        with self.assertRaisesRegex(ContractError, 'checksum'): pilot.load_actor_snapshot(self.root, spec, self.receipt)

    def test_seed_isolation_before_registry_or_engine_creation(self):
        for seed in (10, 900):
            spec = deepcopy(self.spec); spec['cases'][0]['seeds'][0]['game_seed'] = seed
            if seed == 900:
                with self.assertRaisesRegex(ContractError, 'reserved'): pilot.validate_pilot_spec(spec)
            else:
                with patch.object(pilot, 'BuildAssets', return_value=self.assets), patch.object(pilot, 'BotSourceRegistry') as registry:
                    result = pilot.TrainingPilot(self.root, self.native, spec).preflight()
                self.assertEqual(result['status'], 'blocked'); registry.assert_not_called()
                self.assertIn('training seeds', result['blockers'][0]['error'])

    def test_all_cases_must_pass_actual_audit_adapter_gate_before_sampling(self):
        spec = deepcopy(self.spec); second = deepcopy(spec['cases'][0]); second['case_id'] = 'second-case'
        second['seeds'][0]['game_seed'] = 101; spec['cases'].append(second)
        def adapters(executor, **kwargs):
            if kwargs['opponent_id'] == 'second-case': raise ContractError('actual full audit is missing (fixture)')
            return WindBotOpponent(root=self.native, profile=kwargs['profile'], seat=kwargs['seat'], versions=kwargs['versions'],
                binding=self.fixture_binding(**kwargs),
                runtime_validator=lambda: None, room_factory=lambda _: None)
        with self.patched_assets(adapters) as captured, patch.object(pilot.CpuTrainer, 'sample_episode') as sample:
            result = pilot.TrainingPilot(self.root, self.native, spec).run()
        self.assertEqual(len(captured), 3); sample.assert_not_called()
        self.assertEqual(result['status'], 'blocked'); self.assertFalse(result['native_executed'])
        self.assertEqual(result['attempts'], [])
        self.assertEqual(captured[0]['session_seconds'], 120)

    def test_bad_profile_vocabulary_and_non_typed_bot_fail_closed(self):
        self.assets.rows[40]['type'] = 0x40
        with self.patched_assets(), patch.object(pilot.CpuTrainer, 'sample_episode') as sample:
            result = pilot.TrainingPilot(self.root, self.native, self.spec).run()
        self.assertEqual(result['status'], 'blocked'); sample.assert_not_called()
        self.assets.rows[40]['type'] = 17
        spec = deepcopy(self.spec); profile = deepcopy(self.profile)
        profile['decks'][0][-1] = 41; self.assets.rows[41] = {'id': 41, 'ot': 1, 'type': 17, 'alias': 0}
        spec['cases'][0]['profile'] = self.write_json('unseen-profile.json', profile)
        with self.patched_assets(): result = pilot.TrainingPilot(self.root, self.native, spec).preflight()
        self.assertEqual(result['status'], 'blocked'); self.assertIn('vocabulary', result['blockers'][0]['error'])
        with self.patched_assets(lambda *a, **k: SimpleNamespace()) as captured:
            result = pilot.TrainingPilot(self.root, self.native, self.spec).preflight()
        self.assertEqual(result['status'], 'blocked'); self.assertIn('typed', result['blockers'][0]['error'])

    def test_normal_qualification_rejects_plan_fixture_unexecuted_or_changed_runtime(self):
        variants = []
        for key, value in [('kind', 'all-source-bot-engineering-qualification-plan'),
                           ('csharp_executed', False), ('native_executed', None), ('normal_duel_verified', False),
                           ('evidence_source', 'local_contract_fixture')]:
            report = deepcopy(self.qualification); report[key] = value; variants.append(report)
        for key, value in [('binding_sha256', '0'*64), ('deck_sha256', '0'*64), ('bot_decisions', 0),
                           ('status', 'terminal_without_bot_decision'), ('runtime_executor_id', 'AnotherExecutor')]:
            report = deepcopy(self.qualification); report['rows'][0][key] = value; variants.append(report)
        report = deepcopy(self.qualification); del report['rows'][0]['binding_sha256']; variants.append(report)
        report = deepcopy(self.qualification); report['resources']['resources']['cards'] = 'changed'; variants.append(report)
        for index, report in enumerate(variants):
            spec = deepcopy(self.spec)
            spec['cases'][0]['qualification'] = self.write_json('invalid-qualification.json', report)
            with self.subTest(index=index), self.patched_assets(), patch.object(CpuTrainer, 'sample_episode') as sample:
                result = pilot.TrainingPilot(self.root, self.native, spec).run()
            self.assertEqual(result['status'], 'blocked'); sample.assert_not_called()
            self.assertFalse(result['native_executed'])

    def test_real_sampler_and_neural_model_execute_only_explicit_host_room_fixtures(self):
        # No native/C# calls: the real sampler sees two legal fixture windows.
        # The real frozen Transformer is scored once; no optimizer exists here.
        payload = request(); payload['context']['seed'] = None
        payload['context']['versions'] = asdict(self.versions); payload['observation']['cards'] = []
        payload['prompt'] = {'message': 11}; payload['actions'] = [dict(action_id='fixture-pass', kind='pass', card_refs=[], value=7)]
        actor = DecisionRequest.from_dict(payload)
        other = deepcopy(payload); other['decision_id'] = 'fixture-other'; other['observation']['observer'] = 1
        opponent_request = DecisionRequest.from_dict(other)
        seen, closed, forwards = [], [], []
        class Room:
            observer = 1; duel_rule = 5
            def choose(self, req, frame): seen.append(frame); return req.actions[0]
        @contextmanager
        def room(_):
            try: yield Room()
            finally: closed.append('fixture-room')
        def adapter(executor, **kwargs):
            return WindBotOpponent(root=self.native, profile=kwargs['profile'], seat=1, versions=self.versions,
                binding=self.fixture_binding(**kwargs),
                runtime_validator=lambda: None, room_factory=room)
        def engine(*args, pilot_observations, **kwargs):
            e, _ = fixture_engine(); del e._transport; del e._transport_sent
            e.closed = False; e.modern_actions = True; e.window = 0; e.pending = None
            e.player_decks = (tuple(range(1, 41)),)*2; e.player_extras = ((), ())
            e.context = actor.context; e.receipt = self.receipt; e._selection_seed = None
            e.outcome = None; e.events = []; e.turn = 1; e.life_points = [8000, 0]
            windows = iter((actor, opponent_request)); pilot_observations['engine_constructor_started'] = True
            pilot_observations['engine_constructor_completed'] = True
            def next_decision():
                req = next(windows, None)
                if e.window == 0: e._transport.consume(draw(0, (999999999,))+draw(1, (1,))+idle())
                elif req is not None: e._transport.consume(bytes((11, 1))+idle()[2:])
                e.window += 1; e.pending = req
                if req is None: e.outcome = {'winner': 0, 'reason_code': 1}; e.events = [{'kind': 5}]
                else:
                    pilot_observations['decision_windows'] += 1
                    pilot_observations['actual_first_player'] = req.observation.turn_player
                    pilot_observations['seat_prompt_counts'][str(req.observation.observer)+':11'] += 1
                return req
            e.next_decision = next_decision; e.submit = lambda _: None
            e._observation = lambda p: actor.observation if p == 0 else opponent_request.observation
            e.close = lambda: closed.append('fixture-engine')
            return e
        with self.patched_assets(adapter), patch.object(pilot, '_ObservedEngine', side_effect=engine), \
                patch('ygo_kito.cpu_training.public_card_facts', return_value={}), \
                patch.object(CpuTrainer, 'update', side_effect=AssertionError('no update allowed')):
            prepared = pilot.TrainingPilot(self.root, self.native, self.spec)
            preflight = prepared.preflight(); self.assertEqual(preflight['status'], 'ready')
            model = prepared._prepared[0].model
            # run intentionally preflights again; monitor the class forward.
            original = type(model).forward
            def forward(model, *args, **kwargs): forwards.append(1); return original(model, *args, **kwargs)
            with patch.object(type(model), 'forward', forward): result = prepared.run()
        self.assertEqual(result['status'], 'completed', result.get('attempts')); self.assertEqual(len(forwards), 1)
        self.assertEqual(result['summary']['completed_bo1'], 1); self.assertTrue(result['model_unchanged'])
        self.assertEqual(result['attempts'][0]['actual_start_order'], 'first')
        self.assertEqual(result['training_updates'], 0); self.assertEqual(result['summary']['counted_as_formal_games'], 0)
        self.assertEqual(len(seen), 1); self.assertEqual(closed, ['fixture-room', 'fixture-engine'])
        encoded = json.dumps(result)
        for key in ('_private_audit', 'seed_audit_only', 'selection_key_audit_only', 'responses', 'steps'):
            self.assertNotIn('"'+key+'"', encoded)

    def test_unknown_failure_is_retained_partial_without_retry_or_fast_sample_filter(self):
        spec = deepcopy(self.spec); spec['cases'][0]['seeds'].append({'game_seed': 101, 'policy_seed': 201})
        with self.patched_assets(), patch.object(CpuTrainer, 'sample_episode', side_effect=RuntimeError('unsupported fixture prompt')) as sample:
            prepared = pilot.TrainingPilot(self.root, self.native, spec)
            result = prepared.run()
            with self.assertRaisesRegex(ContractError, 'repeat'): prepared.run()
        self.assertEqual(sample.call_count, 1); self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['summary']['failed_or_uncertain_bo1'], 1)
        self.assertEqual(result['summary']['unattempted_bo1'], 1)
        self.assertIsNone(result['summary']['completed_game_wall_seconds']['mean'])
        self.assertIsNone(result['summary']['volume_advice'])
        self.assertIsNone(result['attempts'][0]['actual_start_order'])
        self.assertFalse(result['attempts'][0]['retry_allowed'])

    def test_interrupt_saves_inflight_and_partial_receipts_without_retry(self):
        writes = []
        with self.patched_assets(), patch.object(CpuTrainer, 'sample_episode', side_effect=KeyboardInterrupt()):
            result = pilot.TrainingPilot(self.root, self.native, self.spec).run(progress=writes.append)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['attempts'][0]['error']['type'], 'KeyboardInterrupt')
        dispatched = [r for r in writes if 'in_flight' in r]
        self.assertEqual(len(dispatched), 1)
        self.assertIsNone(dispatched[0]['native_executed'])
        self.assertIsNone(dispatched[0]['csharp_execution_attempted'])
        self.assertFalse(result['native_executed'])  # Fixture threw before engine factory.
        self.assertEqual(result['summary']['failed_or_uncertain_bo1'], 1)

    def test_distributions_keep_failures_coverage_and_do_not_claim_bo3_or_formal_volume(self):
        rows = [{'status': status, 'wall_seconds': wall, 'game_seconds': wall, 'actor_inference_ms': [1, 2], 'declared_coverage': ['one-case']}
                for status, wall in [('completed', 30), ('failed_or_uncertain', 200), ('completed', 90)]]
        result = pilot.aggregate_attempts(rows, planned=4)
        self.assertEqual(result['completed_game_wall_seconds']['mean'], 60)
        self.assertEqual(result['all_attempt_wall_seconds']['max'], 200)
        self.assertEqual(result['coverage']['one-case']['failed_or_uncertain'], 1)
        self.assertEqual(result['completed_bo3'], 0)
        self.assertIsNone(result['volume_advice'])  # Do not select fast successes from a failed/partial window.
        completed = [r for r in rows if r['status'] == 'completed']
        result = pilot.aggregate_attempts(completed, planned=2)
        self.assertEqual(result['volume_advice']['requirements']['bo1_min'], 1000)
        self.assertFalse(result['volume_advice']['representative_of_all_scenarios'])
        completed[0]['game_seconds'] = 31
        self.assertEqual(pilot.aggregate_attempts(completed, planned=2)['volume_advice']['requirements']['minimum_bo1'], 600)
        self.assertEqual(pilot.distribution([1, 3])['p95'], 2.9)
        for values in ([float('nan')], [-1]):
            with self.assertRaises(ContractError): pilot.distribution(values)

    def test_volume_uses_sampler_game_time_not_outer_wall_and_requires_valid_complete_window(self):
        row = {'status': 'completed', 'wall_seconds': 80, 'game_seconds': 60,
               'actor_inference_ms': [2], 'declared_coverage': ['timing-fixture']}
        result = pilot.aggregate_attempts([row], planned=1)
        self.assertEqual(result['completed_game_seconds']['mean'], 60)
        self.assertEqual(result['completed_game_wall_seconds']['mean'], 80)
        self.assertEqual(result['volume_advice']['requirements']['bo1_min'], 1000)
        failed = dict(row, status='failed_or_uncertain', wall_seconds=200, game_seconds=None)
        with self.assertRaisesRegex(ContractError, 'exceeds'):
            pilot.aggregate_attempts([row, failed, row], planned=2)
        for value in (None, 0, -1, float('nan')):
            result = pilot.aggregate_attempts([dict(row, game_seconds=value)], planned=1)
            self.assertIsNone(result['volume_advice'])
            self.assertEqual(result['unmeasured_completed_bo1'], 1)

    def test_default_script_template_is_blocked_and_output_never_overwritten(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/training_pilot.py'
        module_spec = importlib.util.spec_from_file_location('pilot_script_fixture', path)
        script = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(script)
        template_path, output = self.root / 'template.json', self.root / 'blocked.json'
        self.assertEqual(script.main(['--template', '--output', str(template_path)]), 0)
        args = ['--workspace', str(self.root), '--native-root', str(self.native), '--config', str(template_path), '--output', str(output)]
        with patch.object(pilot, 'BuildAssets', side_effect=AssertionError('no execution for null template')):
            self.assertEqual(script.main(args), 2)
        original = output.read_bytes(); self.assertEqual(json.loads(original)['status'], 'blocked')
        self.assertEqual(script.main(args), 2); self.assertEqual(output.read_bytes(), original)

    def test_script_unexpected_runtime_error_keeps_latest_unknown_execution_state(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/training_pilot.py'
        module_spec = importlib.util.spec_from_file_location('pilot_script_error_fixture', path)
        script = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(script)
        spec_path = self.root / 'spec.json'; spec_path.write_text(json.dumps(self.spec))
        report_path = self.root / 'partial.json'
        def run(*, progress):
            progress({'status': 'running', 'native_executed': None, 'csharp_execution_attempted': None,
                      'training_updates': 0, 'formal_games': 0, 'in_flight': {'case_id': 'fixture'}})
            raise RuntimeError('unexpected aggregation failure fixture')
        with patch.object(script, 'prepare_pilot', return_value=SimpleNamespace(run=run)):
            self.assertEqual(script.main(['--config', str(spec_path), '--output', str(report_path), '--run']), 2)
        result = json.loads(report_path.read_text())
        self.assertEqual(result['status'], 'partial'); self.assertIsNone(result['native_executed'])
        self.assertEqual(result['in_flight']['case_id'], 'fixture')


if __name__ == '__main__': unittest.main()
