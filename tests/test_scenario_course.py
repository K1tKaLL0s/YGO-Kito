"""Actual course/model/checkpoint wiring with an explicitly fake native/bot host.

The adapter performs its real neural inference, indexed admission and LoRA PPO
step. The engine and C# room come from the existing CPU fixture; these results
are not core/C# execution, historical qualification or training ability.
"""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

import torch

from tests.test_autonomous_construction import fixture
import tests.test_course_game_adapter as adapter_fixtures
from ygo_kito.build_contracts import BuildTask, DeckParts
from ygo_kito.course_game_adapter import CourseTrainingConfig
from ygo_kito.course_models import CourseModels
from ygo_kito.duel_model import DuelModelConfig
from ygo_kito.lora import AdapterConfig
from ygo_kito.match_runner import GameResult
from ygo_kito.scenario_course import ScenarioCourse
from ygo_kito.validation import ContractError


class ScenarioCourseTests(unittest.TestCase):
    def setUp(self):
        self.host = adapter_fixtures.CourseGameAdapterTests('test_base_two_fresh_ppo_games_sideboards_and_actual_seat_swap')
        self.host.setUp(); self.addCleanup(self.host.doCleanups)
        h = self.host
        task, catalog, _, _ = fixture(41, initialize=False)
        h.assets.rows = deepcopy(catalog.rows)
        h.assets.period_id = '2022-07'
        h.assets.period_context = {'kind': 'synthetic-period-not-historical', 'period_id': '2022-07'}
        h.assets.adapter_revision = 5
        raw = task.to_dict()
        raw.update(pool=list(range(1, 42)), sizes={'main': 40, 'extra': 0, 'side': 1},
                   environment=h.assets.environment_for('deck_constraints'))
        task = BuildTask.from_dict(raw)
        adapters = {r: AdapterConfig('course-' + r, r,
            ('head.0',) if r.startswith('build_') else ('value_head.2',) if r == 'duel' else ('route_head',),
            rank=1, max_updates=8) for r in ('build_goal', 'build_optimizer', 'duel', 'coordinator')}
        cfg = CourseTrainingConfig(model=DuelModelConfig(width=8, card_width=4, heads=2, feedforward=16),
            game_seeds=(100, 101, 102), batch_size=1, episode_seconds=30)
        self.models = CourseModels.initialize(task, h.assets, cfg, adapters, h.root, None,
            h.assets.rows, {'kind': 'synthetic-fresh-course-not-trained', 'fixture': 'actual-models-fake-core'})
        self.deck = h.parts(h.helper.profile, 0)
        self.config = {'course_id': 'synthetic-course-test', 'period_id': '2022-07', 'mode': 'fixed_theme',
            'pilot_mean_seconds': 60, 'training_seeds': [100, 101, 102],
            'evaluation_pairs': {'validation': [[200, 201], [202, 203]], 'final_eval': [[300, 301], [302, 303]]},
            'matches_per_invocation': 3, 'wall_seconds': 3600, 'allocated_gpu_count': 0,
            'fixed_deck': self.deck.to_dict(), 'initial_first': 'alternate', 'evaluation_matches': 1,
            'opponent_side': 'keep_original_baseline'}
        self.bots = {stage: {'runtime': h.runtime, 'deck': self.deck, 'stage': stage, 'purpose': 'train',
            'first_order': 'always_first', 'source': 'engineering_fixture', 'coverage_label': 'fake-room-only'}
            for stage in ('bots-bo1', 'common-decks-bo3')}
        self.bots['heldout-common'] = dict(self.bots['common-decks-bo3'], purpose='final_eval')
        self.course = self.new_course()

    def new_course(self):
        return ScenarioCourse(self.models, assets=self.host.assets, data_index=self.host.index,
            config=self.config, state_root=self.host.root/'scenario-state', bots=self.bots)

    def test_real_adapter_updates_same_lora_and_pause_restore_resumes_next_bo1(self):
        base = self.models.sessions['duel'].verify_base()
        with self.host.fake_execution():
            status = self.course.run(1)
        self.assertEqual(status['complete_training_matches'], {'bo1': 1, 'bo3': 0})
        self.assertEqual(self.models.duel.episode_cursor, 0)  # LoRA owns this course's training cursor.
        self.assertEqual(self.models.sessions['duel'].updates, 1)
        self.assertEqual(self.models.sessions['duel'].verify_base(), base)
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
        state.submit_sideboards({'actor': self.deck, 'opponent': self.deck})
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
