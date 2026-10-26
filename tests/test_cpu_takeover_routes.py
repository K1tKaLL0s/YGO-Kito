"""CPU takeover routing only; no game, optimizer step, network or timing run.

Host physical resources/model initialization/C# qualification are explicitly
patched fixtures in the routing test. Separate snapshot tests use real fresh
CPU tensors and static legal-list checks, without sampling or updating them.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from tests.test_autonomous_construction import fixture
from tests.test_scenario_course_host import filled_spec
from ygo_kito import model_opponents as neural
from ygo_kito import scenario_course_host as host
from ygo_kito.bot_deployment import BotSourceRegistry
from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.cpu_training import CpuTrainer, CpuTrainingConfig
from ygo_kito.duel_model import DuelModelConfig
from ygo_kito.scenario_course import ScenarioCourse, validate_config, validate_common_deck_evidence
from ygo_kito.training_scenarios import (validate_timing_basis, course_volume_requirements,
    course_volume_met, check_2610_rates, validate_scenarios)
from ygo_kito.validation import ContractError
from ygo_kito.windbot_projection import WindBotOpponent

ROOT = Path(__file__).resolve().parents[1]


def slow_basis():
    return {'kind': 'user_confirmed_slow_branch', 'branch': 'slow',
        'source': 'explicit user confirmation; synthetic route test, no speed measurement',
        'observed_mean_seconds': None, 'retiming_requested': False, 'current_device_measured': False}


def config(period='2026-10'):
    deck = DeckParts(tuple([c for c in range(1, 14) for _ in range(3)] + [14]))
    return {'course_id': 'cpu-takeover-route-fixture', 'period_id': period,
        'mode': 'autonomous' if period == '2026-10' else 'fixed_theme',
        'pilot_mean_seconds': None, 'timing_basis': slow_basis(), 'training_seeds': list(range(1800)),
        'evaluation_pairs': {'validation': [[3000, 4000]], 'final_eval': [[3001, 4001]]},
        'matches_per_invocation': 1, 'wall_seconds': 60, 'allocated_gpu_count': 0,
        'fixed_deck': None if period == '2026-10' else deck.to_dict(), 'initial_first': 'alternate',
        'evaluation_matches': 1, 'opponent_side': 'keep_original_baseline'}


def reviewed(deck, period='2026-10'):
    return {'kind': 'user_provided_common_deck', 'source': 'synthetic explicit user-deck review fixture',
        'reviewed_at': '2026-10-26', 'period_id': period, 'format': 'OCG',
        'banlist_effective': period+'-01', 'deck_sha256': digest(deck.to_dict())}


@contextmanager
def route_fixture():
    """Exercise the actual host control flow, never its physical execution."""
    with TemporaryDirectory() as t:
        root = Path(t); native = root/'native'; native.mkdir()
        task, assets, _, _ = fixture(41, initialize=False)
        raw_task = task.to_dict(); raw_task['environment']['release_cutoff'] = '2026-10-01'
        task = BuildTask.from_dict(raw_task)
        assets.root = native; assets.environment = deepcopy(task.environment)
        v = task.environment['versions']
        assets.receipt = {'source_commits': {'core': v['core']}, 'resources': {'cards': v['cards'],
            'scripts': v['scripts'], 'client_protocol': v['protocol'], 'banlist': v['banlist'].split(':')[-1]}}
        assets.period_id = '2026-10'; assets.adapter_revision = 5
        assets.allowed_card_ids = frozenset(assets.rows)
        assets.period_context = {'period_id': '2026-10', 'release_cutoff': '2026-10-01',
            'catalog_sha256': v['cards'], 'release_manifest_sha256': 'a'*64,
            'banlist_sha256': assets.receipt['resources']['banlist'], 'banlist_section': '2026.10'}
        spec = filled_spec(); spec['native_root'] = 'native'
        def save(name, value):
            path = root/name; path.write_text(json.dumps(value))
            return {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        spec['active_environment'] = save('environment.json', {'release_cutoff': '2026-10-01',
            'banlist_effective': '2026-10-01', 'banlist_section': '2026.10', 'catalog': None, 'releases': None, 'banlist': None})
        spec['bootstrap_task'] = save('task.json', task.to_dict())
        spec['duel_config'] = save('duel.json', {'game_seeds': list(range(1800)), 'episode_seconds': 30})
        roles = ('duel', 'build_goal', 'build_optimizer', 'coordinator')
        from ygo_kito.lora import AdapterConfig
        spec['adapter_configs'] = save('adapters.json', {'adapters': [AdapterConfig('route-'+r, r,
            ('head.0',), rank=1, max_updates=1800).to_dict() for r in roles]})
        spec['available_cards'] = save('available.json', {'schema_version': 1, 'card_ids': list(assets.rows)})
        course = config(); spec['course'] = save('course.json', course)
        source = root/'source.weights'; source.write_bytes(b'explicit fixture: initializer patched, never deserialized')
        spec['source_group'].update(path=source.name, sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        deck = DeckParts(tuple([c for c in range(1, 14) for _ in range(3)] + [14]))
        profile = {'schema_version': 2, 'adapter_revision': 5, 'name': 'synthetic-route-only',
            'decks': [list(deck.main), list(deck.main)], 'extras': [[], []], 'sides': [[], []]}
        registry = object.__new__(BotSourceRegistry)
        registry.lock = {'fixture': 'no-real-source-tree'}
        registry.inventory = {'inventory_sha256': 'a'*64}
        def adapter(executor, **options):
            return WindBotOpponent(root=native, profile=options['profile'], seat=options['seat'], versions=options['versions'],
                binding={'profile_sha256': digest(profile), 'opponent_deck_sha256': digest(deck.to_dict()),
                         'driver_version': 'explicit-router-fixture-not-csharp'},
                runtime_validator=lambda: None, room_factory=lambda _: None)
        registry.training_adapter = adapter
        for b in spec['bots']:
            (root/'sources').mkdir(exist_ok=True); b['installed_root'] = 'sources'; b['source'] = 'engineering_fixture'
            b['lock'] = save('lock.json', registry.lock)
            b['deck'] = save('deck.json', deck.to_dict())
            b['qualification_profile'] = save('profile.json', profile)
            b['qualification'] = save('qualification.json', {'actor_seat': 0, 'fixture': 'not-an-actual-qualification'})
            b['audit'] = save('audit.json', {'fixture': 'not-an-actual-audit'})
        models = SimpleNamespace(versions=lambda: {r: 'f'*64 for r in roles})
        with patch.object(host, 'PeriodBuildAssets', return_value=assets), \
                patch('ygo_kito.bot_deployment.BotSourceRegistry', return_value=registry), \
                patch('ygo_kito.course_models.CourseModels.initialize', return_value=models), \
                patch.object(host, '_check_qualification'), \
                patch.object(host, 'check_timing_pilot', side_effect=AssertionError('no new timing is allowed')) as timing:
            yield root, spec, course, save, timing


class ConfirmedSlowRouteTests(unittest.TestCase):
    def test_explicit_branch_preserves_unknown_speed_and_exact_completed_match_ratio(self):
        c = config(); validate_config(c); validate_timing_basis(c['timing_basis'])
        rule = course_volume_requirements(c)
        self.assertEqual((rule['minimum_bo1'], rule['minimum_bo3']), (600, 400))
        self.assertTrue(course_volume_met(c, 600, 400)); self.assertTrue(course_volume_met(c, 660, 440))
        for counts in ((599, 400), (600, 399), (601, 400), (1000, 100)):
            self.assertFalse(course_volume_met(c, *counts))
        self.assertIsNone(c['pilot_mean_seconds']); self.assertIsNone(c['timing_basis']['observed_mean_seconds'])
        self.assertFalse(c['timing_basis']['current_device_measured'])

    def test_unconfirmed_source_new_measurement_and_fabricated_61_are_rejected(self):
        for key, value in (('kind', 'unconfirmed'), ('branch', 'fast'), ('source', ''), ('source', ' '),
                           ('observed_mean_seconds', 61), ('retiming_requested', True), ('current_device_measured', True)):
            bad = config(); bad['timing_basis'][key] = value
            with self.subTest(key=key), self.assertRaises(ContractError): validate_config(bad)
        bad = config(); bad['pilot_mean_seconds'] = 61
        with self.assertRaises(ContractError): validate_config(bad)
        missing = config(); missing.pop('timing_basis')
        with self.assertRaises(ContractError): course_volume_requirements(missing)

    def test_capacity_and_stage_counters_keep_pilot_eval_and_incomplete_out(self):
        c = config(); adapters = [SimpleNamespace(role='duel', max_updates=1800)]
        self.assertEqual(host.check_training_capacity(c, SimpleNamespace(game_seeds=range(1800)), adapters), 1800)
        with self.assertRaises(ContractError): host.check_training_capacity(c, SimpleNamespace(game_seeds=range(1799)), adapters)
        with self.assertRaises(ContractError): host.check_training_capacity(c, SimpleNamespace(game_seeds=range(1800)),
            [SimpleNamespace(role='duel', max_updates=1799)])
        course = object.__new__(ScenarioCourse); course.config = c
        course.records = [{'complete': True, 'purpose': 'train', 'format': 'bo1'} for _ in range(599)]
        course.records += [{'complete': True, 'purpose': 'train', 'format': 'bo3'} for _ in range(400)]
        course.records += [{'complete': True, 'purpose': p, 'format': 'bo1'} for p in ('validation', 'final_eval', 'timing_pilot')]
        course.records.append({'complete': False, 'purpose': 'train', 'format': 'bo1'})
        self.assertEqual(course.stage(), 'bots-bo1')
        course.records.append({'complete': True, 'purpose': 'train', 'format': 'bo1'})
        self.assertEqual(course.stage(), 'complete')

    def test_historical_reference_acceptance_is_not_replaced_by_2610_rates(self):
        scenarios = json.loads((ROOT/'configs/training-scenarios-v1.json').read_text()); validate_scenarios(scenarios)
        for period in ('2022-07', '2022-10'):
            validate_config(config(period))
            acceptance = scenarios['periods'][period]['acceptance']
            self.assertEqual(acceptance['external_at_least'], .6)
            self.assertEqual(acceptance['mirror_target'], .5)
            self.assertEqual((acceptance['frozen_external_bo3_min'], acceptance['frozen_mirror_bo3_min']), (200, 200))
            self.assertIsNone(acceptance['confidence_decision_rule'])
            with self.assertRaises(ContractError): check_2610_rates(period, 100, 100, 100, 100)

    def test_real_host_route_skips_retiming_only_for_explicit_valid_basis(self):
        with route_fixture() as (root, spec, course, save, timing):
            result = host.prepare_course(root, spec).preflight()
            self.assertEqual(result['status'], 'ready', result['blockers']); timing.assert_not_called()
            self.assertIsNone(result['pilot_mean_seconds']); self.assertFalse(result['timing_basis']['current_device_measured'])
            self.assertFalse((root/'.cache').exists())
            without = deepcopy(course); without.pop('timing_basis')
            spec['course'] = save('without-basis.json', without)
            result = host.prepare_course(root, spec).preflight()
            self.assertEqual(result['status'], 'blocked'); self.assertFalse(result['native_executed'])
            bad = deepcopy(course); bad['pilot_mean_seconds'] = 61
            spec['course'] = save('invented-mean.json', bad)
            self.assertEqual(host.prepare_course(root, spec).preflight()['status'], 'blocked')


class StageTwoModelPolicyTests(unittest.TestCase):
    def test_model_schema_cannot_replace_stage_one_or_omit_deck_review(self):
        spec = filled_spec(); deck = DeckParts(tuple([c for c in range(1, 14) for _ in range(3)] + [14]))
        model = {'driver': 'local_model_snapshot', 'bot_id': 'reviewed-model-fixture',
            'model': {'path': 'snapshot.weights', 'sha256': 'f'*64}, 'migration': 'same-period-inference',
            'deck': {'path': 'deck.json', 'sha256': 'e'*64}, 'source': 'user_provided',
            'stage': 'common-decks-bo3', 'purpose': 'train', 'first_order': 'always_first',
            'coverage_label': 'explicit_common_deck_fixture', 'common_deck_evidence': reviewed(deck)}
        spec['bots'][1] = model; host.validate_host_spec(spec)
        for key, value in (('stage', 'bots-bo1'), ('migration', None), ('driver', 'unknown_model_driver')):
            bad = deepcopy(spec); bad['bots'][1][key] = value
            with self.subTest(key=key), self.assertRaises(ContractError): host.validate_host_spec(bad)
        bad = deepcopy(spec); del bad['bots'][1]['common_deck_evidence']
        with self.assertRaises(ContractError): host.validate_host_spec(bad)
        for key, value in (('period_id', '2022-07'), ('format', 'MD'), ('banlist_effective', '2026-07-01'),
                           ('deck_sha256', '0'*64), ('source', ''), ('reviewed_at', 'not-a-date')):
            evidence = reviewed(deck); evidence[key] = value
            with self.subTest(key=key), self.assertRaises(ContractError): validate_common_deck_evidence(evidence, deck, '2026-10')
        with self.assertRaises(ContractError): validate_common_deck_evidence(None, deck, '2026-10')

    def test_actual_frozen_model_static_profile_context_and_vocabulary_gates(self):
        task, assets, _, _ = fixture(41, initialize=False)
        v = task.environment['versions']
        assets.receipt = {'source_commits': {'core': v['core']}, 'resources': {'cards': v['cards'], 'scripts': v['scripts'],
            'client_protocol': v['protocol'], 'banlist': v['banlist'].split(':')[-1]}}
        cfg = CpuTrainingConfig(model=DuelModelConfig(width=8, card_width=4, heads=2, feedforward=16), game_seeds=(10, 11))
        trainer = CpuTrainer(cfg, list(assets.rows))
        with patch.object(neural, 'verify_resources', return_value=assets.receipt):
            snapshot = neural.FrozenDuelSnapshot.capture(trainer, assets=assets, source_binding={'fixture': 'no-training'},
                source_label='fresh synthetic CPU tensors, not user skill or strategy evidence')
            runtime = neural.ModelOpponentRuntime(snapshot, 'synthetic-common-model')
            runtime.assert_assets(assets)
            deck = [c for c in range(1, 14) for _ in range(3)] + [14]
            profile = {'schema_version': 2, 'adapter_revision': 5, 'name': 'legal-static-fixture',
                'decks': [deck, deck], 'extras': [[], []], 'sides': [[], []]}
            opponent = runtime.bind(assets, profile, 1)
            opponent.assert_runtime(assets.root, profile, 0)
            bad = deepcopy(profile); bad['extras'][1] = [1]
            with self.assertRaises(ContractError): runtime.bind(assets, bad, 1)
            assets.period_context = {'fixture': 'different-target-period'}
            with self.assertRaisesRegex(ContractError, 'context'): runtime.assert_assets(assets)
            del assets.period_context
            assets.rows[999] = {'id': 999}
            with self.assertRaisesRegex(ContractError, 'vocabulary'): runtime.assert_assets(assets)
        self.assertEqual(trainer.updates, 0); self.assertEqual(trainer.episode_cursor, 0)
        self.assertFalse(snapshot.identity()['provenance']['ability_verified'])


if __name__ == '__main__': unittest.main()
