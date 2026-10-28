"""Actual course/model/checkpoint wiring with an explicitly fake native/bot host.

The adapter performs its real neural inference, indexed admission and LoRA PPO
step. The engine and C# room come from the existing CPU fixture; these results
are not core/C# execution, historical qualification or training ability.
"""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import torch

from tests.test_autonomous_construction import fixture
import tests.test_course_game_adapter as adapter_fixtures
from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.contracts import DecisionRequest, validate_selection
from tests.fixtures import request as decision_payload
from ygo_kito.course_game_adapter import CourseTrainingConfig
from ygo_kito.course_models import CourseModels
from ygo_kito.duel_model import DuelModelConfig
from ygo_kito.lora import AdapterConfig
from ygo_kito.match_runner import GameResult
from ygo_kito.scenario_course import ScenarioCourse
from ygo_kito.validation import ContractError


class ScenarioConstructionCompletionTests(unittest.TestCase):
    """Actual course admission with synthetic kernel results; no games/updates."""
    def course(self, status, *, completed=True, cb_verified=False):
        course = object.__new__(ScenarioCourse)
        deck = DeckParts((1,)*40)
        result = {'best': {'deck': deck.to_dict()}, 'task_verified': True, 'alternation_completed': True,
            'cb_verified': cb_verified, 'basic_cb': {'status': status, 'inference_completed': completed,
                'routes': [{'fixture': 'synthetic-route-only'}] if cb_verified else []}}
        selection = {'status': 'model_selected_task', 'candidate_id': 'first-model-choice'}
        kernel = Mock()
        kernel.propose_tasks.return_value = {'candidates': [selection, {'candidate_id': 'alternative'}]}
        kernel.select_task.return_value = selection
        kernel.run_selected.side_effect = lambda *args, **kwargs: deepcopy(result)
        course.models = SimpleNamespace(kernel=kernel)
        course.rules = SimpleNamespace(validate=Mock())
        course.selection, course.deck, course.events = None, None, []
        return course, kernel, result, selection, deck

    def test_unknown_inference_keeps_first_model_goal_and_is_not_a_failed_construction(self):
        c, kernel, _, selection, deck = self.course('bounded_inference_unknown')
        c._construct()
        self.assertEqual(c.selection, selection); self.assertEqual(c.deck, deck)
        self.assertTrue(c.construction['task_verified']); self.assertFalse(c.construction['cb_verified'])
        self.assertEqual(c.construction['basic_cb']['routes'], [])
        kernel.run_selected.assert_called_once_with(selection, feedback=())
        self.assertEqual(c.events, [])
        c._construct(feedback=({'source': 'duel', 'message': 'synthetic feedback'},))
        kernel.select_task.assert_called_once()
        self.assertEqual(kernel.run_selected.call_args.kwargs['base'], deck)
        self.assertEqual(c.selection, selection)

    def test_not_run_cannot_be_admitted_by_a_route_success_flag(self):
        for selected in (False, True):
            c, _, _, selection, _ = self.course('not_run', completed=False, cb_verified=True)
            if selected: c.selection = selection
            with self.subTest(selected=selected), self.assertRaisesRegex(ContractError, 'basic CB inference'):
                c._construct()
            self.assertIsNone(c.deck)

    def test_routes_found_remain_distinct_from_completed_unknown(self):
        c, _, _, _, deck = self.course('routes_inferred', cb_verified=True)
        c._construct()
        self.assertEqual(c.deck, deck); self.assertTrue(c.construction['cb_verified'])
        self.assertTrue(c.construction['basic_cb']['routes'])

    def test_task_validation_and_four_handoffs_are_required_even_with_route_evidence(self):
        for missing in ('task_verified', 'alternation_completed'):
            c, _, result, selection, _ = self.course('routes_inferred', cb_verified=True)
            c.selection = selection; result[missing] = False
            with self.subTest(missing=missing), self.assertRaises(ContractError): c._construct()
            self.assertIsNone(c.deck)


class ScenarioCourseTests(unittest.TestCase):
    def setUp(self):
        self.host = adapter_fixtures.CourseGameAdapterTests('test_base_two_fresh_ppo_games_sideboards_and_actual_seat_swap')
        self.host.setUp(); self.addCleanup(self.host.doCleanups)
        h = self.host
        task, catalog, _, _ = fixture(41, initialize=False)
        h.assets.rows = deepcopy(catalog.rows)
        for row in h.assets.rows.values(): row['setcode'] = 0x181
        h.assets.rows[42] = dict(h.assets.rows[1], id=42, type=0x800001,
                                name='synthetic-xyz-contract-only')
        # Exercise model generation and the normal discovery/replay contract.
        # This is an explicitly fake offered-action engine, never native CB proof.
        h.assets.receipt = deepcopy(h.assets.receipt)
        h.assets.receipt['resources']['cards'] = digest(h.assets.rows)
        q = json.loads((h.root/h.qualification['path']).read_text())
        q['resources'] = deepcopy(h.assets.receipt)
        h.qualification = h.helper.write_json('scenario-qualification-fixture.json', q)
        h.runtime = replace(h.runtime, qualification=h.qualification)
        assets = h.assets
        class SyntheticGoalEngine:
            def __init__(self, *args, **kwargs):
                self.turn, self.events, self.done = 1, [], False
                # A deterministic offered-action fixture over this constructed
                # deck, not a native shuffle or a preassigned construction CB.
                opening = kwargs['deck_profile']['decks'][0][:5]
                self.extra = kwargs['deck_profile']['extras'][0]
                assert self.extra == [42], 'synthetic target must belong to the constructed extra deck'
                payload = decision_payload()
                payload['context']['seed'] = None
                payload['context']['versions'] = assets.environment_for('deck_constraints')['versions']
                payload['observation']['cards'] = [
                    dict(ref='fixture-opening-'+str(i), owner=0, controller=0,
                         zone='hand', visibility='observer', card_id=c) for i, c in enumerate(opening)] + [
                    dict(ref='fixture-target', owner=0, controller=0, zone='extra',
                         visibility='observer', card_id=42)]
                payload['prompt'] = {'message': 11}
                payload['actions'] = [dict(action_id='fixture-special', kind='special_summon', card_refs=['fixture-target'])]
                self.request = DecisionRequest.from_dict(payload)
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def _observation(self, player):
                if not self.done: return self.request.observation
                payload = json.loads(json.dumps(self.request.to_dict()))
                payload['observation']['cards'] = [dict(ref='fixture-result', owner=0, controller=0,
                    zone='monster', visibility='public', card_id=42)]
                payload['actions'] = [dict(action_id='fixture-pass', kind='pass', card_refs=[])]
                return DecisionRequest.from_dict(payload).observation
            def next_decision(self): return None if self.done else self.request
            def submit(self, selection):
                validate_selection(self.request, selection)
                self.done = True
                self.events = [{'kind': 62, 'player': 0, 'public_summoning_card': 42}, {'kind': 63}]
        h.assets.engine_factory = SyntheticGoalEngine
        h.assets.period_id = '2022-07'
        h.assets.period_context = {'kind': 'synthetic-period-not-historical', 'period_id': '2022-07'}
        h.assets.adapter_revision = 5
        raw = task.to_dict()
        raw.update(pool=list(range(1, 43)), sizes={'main': 40, 'extra': 1, 'side': 1},
                   environment=h.assets.environment_for('deck_constraints'))
        task = BuildTask.from_dict(raw)
        adapters = {r: AdapterConfig('course-' + r, r,
            ('head.0',) if r.startswith('build_') else ('value_head.2',) if r == 'duel' else ('route_head',),
            rank=1, max_updates=8) for r in ('build_goal', 'build_optimizer', 'duel', 'coordinator')}
        cfg = CourseTrainingConfig(model=DuelModelConfig(width=8, card_width=4, heads=2, feedforward=16),
            game_seeds=(100, 101, 102), batch_size=1, episode_seconds=30)
        self.models = CourseModels.initialize(task, h.assets, cfg, adapters, h.root, None,
            h.assets.rows, {'kind': 'synthetic-fresh-course-not-trained', 'fixture': 'actual-models-fake-core',
                            'basic_cb_stage': 'after_construction',
                            'construction_theme_ids': ['setcode-181']})
        self.deck = h.parts(h.helper.profile, 0)
        self.config = {'course_id': 'synthetic-course-test', 'period_id': '2022-07', 'mode': 'fixed_theme',
            'pilot_mean_seconds': 60, 'training_seeds': [100, 101, 102],
            'evaluation_pairs': {'validation': [[200, 201], [202, 203]], 'final_eval': [[300, 301], [302, 303]]},
            'matches_per_invocation': 3, 'wall_seconds': 3600, 'allocated_gpu_count': 0,
            'fixed_deck': None, 'construction_theme_ids': ['setcode-181'], 'initial_first': 'alternate', 'evaluation_matches': 1,
            'opponent_side': 'keep_original_baseline'}
        self.bots = {stage: {'runtime': h.runtime, 'deck': self.deck, 'stage': stage, 'purpose': 'train',
            'first_order': 'always_first', 'source': 'engineering_fixture', 'coverage_label': 'fake-room-only'}
            for stage in ('bots-bo1', 'common-decks-bo3')}
        self.bots['heldout-common'] = dict(self.bots['common-decks-bo3'], purpose='final_eval')
        self.course = self.new_course()

    def new_course(self):
        return ScenarioCourse(self.models, assets=self.host.assets, data_index=self.host.index,
            config=self.config, state_root=self.host.root/'scenario-state', bots=self.bots)

    def test_route_free_task_passes_actual_handoffs_and_inferred_route_to_the_planner(self):
        from ygo_kito.duel_planning import plans_from_construction
        self.course._construct()
        result=self.course.construction;task=self.course._task()
        self.assertNotIn('route_goal',task.goal);self.assertEqual(task.requirements,())
        self.assertTrue(result['task_verified']);self.assertTrue(result['alternation_completed'])
        self.assertTrue(result['basic_cb_inference_performed'])
        self.assertEqual(result['basic_cb']['status'],'routes_inferred')
        self.assertEqual(result['task_goal_sha256'],digest(task.goal))
        self.assertNotEqual(result['goal_sha256'],result['task_goal_sha256'])
        self.assertTrue(plans_from_construction(task,result,deck=self.course.deck))
        self.assertEqual([p['role'] for p in result['phases']],['build_goal','build_optimizer']*2)
        for before,after in zip(result['phases'],result['phases'][1:]):
            self.assertEqual(before['proposal_deck'],after['input_deck'])
        self.assertEqual(result['best']['deck'],result['phases'][-1]['proposal_deck'])

    def test_real_adapter_updates_same_lora_and_pause_restore_resumes_next_bo1(self):
        base = self.models.sessions['duel'].verify_base()
        with self.host.fake_execution():
            status = self.course.run(1)
        self.assertEqual(status['complete_training_matches'], {'bo1': 1, 'bo3': 0})
        self.assertEqual(self.models.duel.episode_cursor, 0)  # LoRA owns this course's training cursor.
        self.assertEqual(self.models.sessions['duel'].updates, 1)
        self.assertEqual(self.models.sessions['duel'].verify_base(), base)
        policy = self.course.records[0]['receipts'][-1]['before']['planning']
        self.assertGreater(policy['combo_plan_count'],0)
        from collections import Counter
        inferred=self.course.construction['basic_cb']
        self.assertEqual(inferred['status'],'routes_inferred')
        self.assertNotIn('route_goal',self.course._task().goal)
        self.assertEqual(self.course._task().requirements,())
        needed=Counter(inferred['routes'][0]['task']['goal']['route_goal']['starting_conditions']['requires_opening_hand'])
        self.assertFalse(needed-Counter(self.course.deck.main[:5]))
        self.assertEqual(policy['version'],'player-view-cb-expectimax-v1')
        self.assertEqual(self.course.records[0]['games'][0]['actual_first_participant_id'], 'actor')
        self.assertFalse((self.course.root/'in-flight.json').exists())
        before, seconds = self.models.fingerprint(), self.course.active_seconds
        resumed = self.new_course(); resumed.restore_latest()
        self.assertEqual(self.models.fingerprint(), before)
        self.assertEqual(resumed.active_seconds, seconds)
        (resumed.root/'pause.request').write_text('host pause')
        self.assertEqual(resumed.run(1)['desired'], 'paused')
        self.assertEqual(self.models.sessions['duel'].updates, 1)
        (resumed.root/'pause.request').unlink()
        with self.host.fake_execution():
            resumed.run(1)
        self.assertEqual(resumed.counts(), {'bo1': 2, 'bo3': 0})
        self.assertEqual(self.models.duel.episode_cursor, 0)
        self.assertEqual(self.models.sessions['duel'].updates, 2)
        self.assertEqual(resumed.records[1]['games'][0]['actual_first_participant_id'], 'opponent')
        self.assertEqual(self.host.index.summary()['by_purpose']['train'], 2)

    def test_already_checkpointed_bo1_draw_closes_once_without_sampling_again(self):
        c = self.course; c._start_match('train')
        state = c.pending['state']; spec = state.issue_game_spec()
        state.record_game(spec, GameResult(1, 2, 0, True, 'synthetic_contract_fixture', 1., 2))
        c.save()  # Crash boundary after game commit, before match-close projection.
        resumed = self.new_course(); resumed.restore_latest()
        with patch('ygo_kito.scenario_course.CourseGameAdapter', side_effect=AssertionError('must not replay')):
            resumed.run(1)
        self.assertEqual(resumed.counts(), {'bo1': 1, 'bo3': 0})
        self.assertEqual(len(resumed.records), 1)
        self.assertIsNone(resumed.records[0]['winner'])
        self.assertTrue(resumed.records[0]['games'][0]['draw'])
        self.assertEqual(self.models.duel.episode_cursor, 0)

    def test_bo3_requires_two_wins_and_draw_is_pending_not_completed_match(self):
        c = self.course
        # Explicit counter fixture only: no claim these minima were played.
        c.records = [{'complete': True, 'purpose': 'train', 'format': 'bo1'} for _ in range(1000)]
        self.assertEqual(c.stage(), 'common-decks-bo3')
        c._start_match('train'); state = c.pending['state']
        first = state.issue_game_spec()
        state.record_game(first, GameResult(1, first.seat_of('actor'), 0, True, 'synthetic_contract_fixture', 1., 2))
        self.assertFalse(c._close())
        self.assertEqual(c.counts()['bo3'], 0)
        state.submit_sideboards({'actor': c.deck, 'opponent': self.deck})
        state.choose_next_first('opponent', 'opponent')
        second = state.issue_game_spec()
        state.record_game(second, GameResult(2, 2, 0, True, 'synthetic_contract_fixture', 1., 2))
        self.assertTrue(c._close())
        self.assertEqual(c.records[-1]['status'], 'pending_draw_policy')
        self.assertFalse(c.records[-1]['complete'])
        self.assertEqual(c.counts()['bo3'], 0)
        self.assertEqual(c.desired, 'needs_inspection')

    def test_actual_model_side_ranking_and_two_adapter_games_close_only_one_bo3(self):
        c = self.course
        c.records = [{'complete': True, 'purpose': 'train', 'format': 'bo1', 'games': []}
                     for _ in range(1000)]  # Counter fixture; not played volume.
        with self.host.fake_execution():
            status = c.run(1)
        self.assertEqual(status['complete_training_matches'], {'bo1': 1000, 'bo3': 1})
        self.assertEqual(len(c.records[-1]['games']), 2)
        self.assertEqual([g['actual_first_participant_id'] for g in c.records[-1]['games']], ['actor', 'opponent'])
        receipts = c.records[-1]['receipts']
        side = next(r['receipt'] for r in receipts if r.get('kind') == 'actor_side_selection')
        self.assertGreater(side['candidate_count'], 1)
        self.assertEqual(self.models.sessions['duel'].updates, 2)
        self.assertEqual(self.models.sessions['build_optimizer'].updates, 0)
        self.assertEqual(self.host.index.summary()['by_purpose']['train'], 2)

    def test_frozen_context_restores_actual_model_rng_modes_and_rejects_weight_update(self):
        before = self.models.fingerprint()
        with self.course._frozen():
            self.assertTrue(all(not m.training for m in self.models.models().values()))
            torch.rand(4); torch.rand(4, generator=self.models.policy_rng)
        self.assertEqual(self.models.fingerprint(), before)
        with self.assertRaises(ContractError):
            with self.course._frozen():
                with torch.no_grad(): next(self.models.duel.model.parameters()).add_(.01)

    def test_actual_frozen_adapter_evaluation_has_separate_data_and_zero_training_credit(self):
        c = self.course
        c.records = [{'complete': True, 'purpose': 'train', 'format': kind, 'games': []}
                     for kind, count in (('bo1', 1000), ('bo3', 100)) for _ in range(count)]
        c._construct()  # Counter fixture, not a claim that these minima were played.
        before = self.models.fingerprint()
        with self.host.fake_execution():
            status = c.run(1, purpose='final_eval')
        self.assertEqual(self.models.fingerprint(), before)
        self.assertEqual(status['complete_training_matches'], {'bo1': 1000, 'bo3': 100})
        self.assertEqual(c.records[-1]['purpose'], 'final_eval')
        self.assertTrue(c.records[-1]['complete'])
        self.assertEqual(c.evaluation_cursor['final_eval'], 2)
        self.assertEqual(self.host.index.summary()['by_purpose']['final_eval'], 2)
        self.assertTrue(all(s.updates == 0 for s in self.models.sessions.values()))
        self.assertEqual(c.rates()['completed_first_games'], 1)
        self.assertEqual(c.rates()['completed_second_games'], 1)
        with self.assertRaisesRegex(ContractError, 'frozen evaluation has begun'):
            c.run(1, purpose='train')

    def test_uncertain_half_game_and_stale_index_refuse_automatic_resume(self):
        self.course.save()
        (self.course.root/'in-flight.json').write_text('{}')
        with self.assertRaisesRegex(ContractError, 'uncertain'):
            self.new_course().restore_latest()
        with self.assertRaisesRegex(ContractError, 'in-flight'):
            self.course.run(1)
        (self.course.root/'in-flight.json').unlink()
        with patch('ygo_kito.scenario_course.index_identity', return_value='changed'):
            with self.assertRaisesRegex(ContractError, 'stale'):
                self.new_course().restore_latest()

    def test_rates_use_observed_first_and_heldout_only_no_training_credit(self):
        common = {'purpose': 'final_eval', 'stage': 'common-decks-bo3', 'format': 'bo3', 'complete': True,
                  'bot_id': 'common-decks-bo3', 'winner': 'actor'}
        game = {'completed': True, 'actual_first_participant_id': 'actor', 'winner_participant_id': 'actor', 'draw': False}
        self.course.records = [dict(common, games=[game, dict(game, actual_first_participant_id='opponent', winner_participant_id='opponent')]),
            dict(common, purpose='train', games=[game])]
        rates = self.course.rates()
        self.assertEqual((rates['completed_first_games'], rates['completed_second_games']), (1, 1))
        self.assertEqual((rates['first_wins'], rates['second_wins']), (1, 0))
        self.assertEqual(self.course.counts(), {'bo1': 0, 'bo3': 1})


if __name__ == '__main__': unittest.main()
