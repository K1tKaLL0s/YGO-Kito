"""Host boundary/CLI fixtures only: no core, C#, optimizer or cloud calls."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ygo_kito import scenario_course_host as host
from ygo_kito.build_contracts import DeckParts
from ygo_kito.implementation_identity import source_tree_snapshot
from ygo_kito.training_pilot import aggregate_attempts
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]


def filled_spec():
    d = json.loads((ROOT / 'configs/scenario-course-template-v1.json').read_text())
    for key in ('active_environment', 'bootstrap_task', 'duel_config', 'adapter_configs', 'available_cards', 'course'):
        d[key] = {'path': 'explicit-fixture.json', 'sha256': 'a'*64}
    d['native_root'] = 'native-fixture'
    d['source_group'] = {'path': 'completed-fixture.weights', 'sha256': 'b'*64,
                         'weights': 'effective', 'source_binding_sha256': 'c'*64}
    for b in d['bots']:
        b.update(executor_id='SyntheticExecutor', installed_root='sources-fixture', mono='/fixture/no-real-mono')
        for key in ('lock', 'audit', 'qualification', 'qualification_profile', 'deck'):
            b[key] = {'path': key+'-fixture.json', 'sha256': 'd'*64}
    return d


class ScenarioHostTests(unittest.TestCase):
    def test_formal_seed_and_duel_adapter_capacity_reject_short_engineering_defaults(self):
        for mean, required in ((60, 1300), (60.001, 1800)):
            cfg = {'pilot_mean_seconds': mean}
            duel = SimpleNamespace(game_seeds=tuple(range(required)))
            adapters = [SimpleNamespace(role='duel', max_updates=required)]
            self.assertEqual(host.check_training_capacity(cfg, duel, adapters), required)
            with self.assertRaises(ContractError):
                host.check_training_capacity(cfg, SimpleNamespace(game_seeds=duel.game_seeds[:-1]), adapters)
            with self.assertRaises(ContractError):
                host.check_training_capacity(cfg, duel, [SimpleNamespace(role='duel', max_updates=2)])

    def test_template_and_source_group_do_not_enable_fresh_random_fallback(self):
        template = json.loads((ROOT / 'configs/scenario-course-template-v1.json').read_text())
        with self.assertRaises(ContractError): host.validate_host_spec(template)
        value = filled_spec(); host.validate_host_spec(value)
        for key, invalid in (('source_group', None), ('device', 'auto'), ('resume', 1)):
            bad = deepcopy(value); bad[key] = invalid
            with self.subTest(key=key), self.assertRaises(ContractError): host.validate_host_spec(bad)
        value['device'] = 'cuda:7'; host.validate_host_spec(value)

    def test_pilot_schedule_is_explicit_unique_and_bounded(self):
        for pairs in ([], [[1, 2], [1, 3]], [[True, 2]], [[1]], [[1, 2]]*101):
            value = filled_spec(); value['pilot_pairs'] = pairs
            with self.subTest(pairs=pairs[:2]), self.assertRaises(ContractError): host.validate_host_spec(value)

    def test_active_subset_keeps_target_and_rejects_future_or_historical_drift(self):
        env = dict(release_cutoff='2026-10-01', banlist_effective='2026-10-01', banlist_section='2026.10',
                   catalog=None, releases=None, banlist=None)
        self.assertTrue(host._active_cutoff('2026-10', '2026-11-01', env)['cutoff_reached'])
        with self.assertRaises(ContractError): host._active_cutoff('2026-10', '2026-11-01', dict(env, release_cutoff='2099-01-01'))
        with self.assertRaises(ContractError): host._active_cutoff('2022-07', '2022-09-30', dict(env, release_cutoff='2022-09-01'))

    def test_real_file_checksum_and_workspace_escape_are_checked(self):
        with TemporaryDirectory() as t:
            root = Path(t); p = root/'a.json'; p.write_text('{"fixture":true}')
            ref = {'path': 'a.json', 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            self.assertTrue(host._json(root, ref)['fixture'])
            with self.assertRaises(ContractError): host._json(root, dict(ref, sha256='0'*64))
            with self.assertRaises(ContractError): host._inside(root, '/etc/passwd')

    def test_available_cards_exclude_only_missing_or_illegal_actual_candidates(self):
        with TemporaryDirectory() as t:
            root = Path(t); scripts = root/'engine-src/scripts'; scripts.mkdir(parents=True)
            (scripts/'c2.lua').write_text('-- passive fixture, never executed')
            rows = {i: {'ot': 1, 'type': 17 if i == 1 else 33, 'alias': 0} for i in range(1, 5)}
            assets = SimpleNamespace(root=root, rows=rows, limits={4: 0}, allowed_card_ids=frozenset(rows))
            p = root/'available.json'; p.write_text(json.dumps({'schema_version': 1, 'card_ids': [1, 2, 3, 4, 5]}))
            ref = {'path': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            available, excluded = host._availability(root, ref, assets)
            self.assertEqual(available, [1, 2]); self.assertEqual(len(excluded), 3)

    def test_self_contained_resume_pointer_and_existing_index_are_read_only(self):
        import torch
        from ygo_kito.data_isolation import DataIndex
        from ygo_kito.scenario_course import index_identity
        with TemporaryDirectory() as t:
            state = Path(t); course = state/'course'; course.mkdir()
            index = DataIndex(state/'data-index')
            payload = {'kind': 'ordered-course-game-boundary-v1', 'revision': 1, 'active_seconds': 0.,
                       'data_index_sha256': index_identity(index), 'models': {'synthetic_tensor': torch.ones(1)}}
            cp = course/'checkpoint-1.weights'; torch.save(payload, cp)
            pointer = {'path': cp.name, 'sha256': hashlib.sha256(cp.read_bytes()).hexdigest(), 'revision': 1, 'active_seconds': 0.}
            latest = course/'latest.json'; latest.write_text(json.dumps(pointer))
            before = {p.name: p.read_bytes() for p in course.iterdir()}
            restored = host._resume_payload(state)
            self.assertEqual(restored['revision'], 1)
            self.assertEqual(before, {p.name: p.read_bytes() for p in course.iterdir()})
            # No old source-initialization artifact exists or is read.
            latest.write_text(json.dumps(dict(pointer, sha256='0'*64)))
            with self.assertRaises(ContractError): host._resume_payload(state)
            latest.write_text(json.dumps(pointer)); (course/'in-flight.json').write_text('{}')
            with self.assertRaisesRegex(ContractError, 'in-flight'): host._resume_payload(state)

    def test_group_pilot_exact_execution_cases_and_full_window_required(self):
        runtime = SimpleNamespace(source_id='ice', executor_id='SyntheticExecutor', audit={'fixture': 'audit'},
            qualification={'fixture': 'normal'}, qualification_profile={'fixture': 'profile'}, session_seconds=60,
            mono='/fixture/mono', registry=SimpleNamespace(lock={'fixture': True}, inventory={'inventory_sha256': 'a'*64}))
        bots = {'fixture-bot': {'runtime': runtime, 'deck': DeckParts((1,)*40, (), ()), 'stage': 'bots-bo1',
            'purpose': 'train', 'first_order': 'always_first', 'source': 'engineering_fixture', 'coverage_label': 'synthetic_only'}}
        assets = SimpleNamespace(receipt={'fixture': 'resources'}, period_context={'fixture': 'period'})
        execution = {'fixture': 'same-four-models-and-lora'}
        attempts = [{'case_id': 'fixture-bot', 'status': 'completed', 'game_seconds': 60, 'wall_seconds': 80,
            'actor_inference_ms': [1], 'declared_coverage': ['synthetic_only'],
            'evidence_source': 'live-core-neural-policy-registered-bot'}]
        report = {'kind': 'course-group-bo1-timing-pilot-v1', 'partition': 'timing_pilot', 'status': 'completed',
            'native_executed': True, 'csharp_execution_attempted': True, 'all_models_unchanged': True,
            'training_updates': 0, 'formal_matches': 0, 'resources': assets.receipt, 'period_context': assets.period_context,
            'implementation': source_tree_snapshot(ROOT/'src/ygo_kito'), 'model_execution': execution,
            'seed_schedule': [[50, 60]], 'planned_games': 1, 'attempts': attempts,
            'summary': aggregate_attempts(attempts, planned=1), 'case_bindings': host.case_bindings(bots)}
        def check(value):
            return host.check_timing_pilot(value, assets=assets, execution=execution, pilot_pairs=[[50, 60]], bots=bots)
        self.assertEqual(check(report), 60)
        for key, value in (('kind', 'cpu-bo1-timing-pilot'), ('all_models_unchanged', False),
                           ('model_execution', {'fixture': 'another-device'}), ('case_bindings', {}),
                           ('planned_games', 2), ('implementation', {}), ('status', 'partial')):
            bad = deepcopy(report); bad[key] = value
            with self.subTest(key=key), self.assertRaises(ContractError): check(bad)
        bad = deepcopy(report); bad['attempts'][0]['status'] = 'failed_or_uncertain'
        bad['summary'] = aggregate_attempts(bad['attempts'], planned=1)
        with self.assertRaises(ContractError): check(bad)

    def test_cli_defaults_only_preflight_and_dispatch_is_explicit(self):
        spec = importlib.util.spec_from_file_location('course_cli_fixture', ROOT/'scripts/scenario_course.py')
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        calls = []
        fake = SimpleNamespace(preflight=lambda: calls.append('preflight') or {'status': 'ready'},
            run=lambda **kw: calls.append('run') or {'status': 'bounded_invocation_finished'},
            timing_pilot=lambda **kw: calls.append('pilot') or {'status': 'completed'})
        with TemporaryDirectory() as t:
            root = Path(t); config = root/'host.json'; config.write_text('{}')
            with patch.object(host, 'prepare_course', return_value=fake) as prepare:
                base = ['--config', str(config)]
                self.assertEqual(cli.main(base+['--output', str(root/'preflight.json')]), 0)
                self.assertEqual(calls, ['preflight'])
                self.assertEqual(cli.main(base+['--output', str(root/'pilot.json'), '--pilot']), 0)
                self.assertEqual(cli.main(base+['--output', str(root/'run.json'), '--run', '--max-matches', '1']), 0)
                self.assertEqual(calls, ['preflight', 'pilot', 'run'])
                count = prepare.call_count
                self.assertEqual(cli.main(base+['--output', str(root/'run.json'), '--run']), 2)
                self.assertEqual(prepare.call_count, count)


if __name__ == '__main__': unittest.main()
