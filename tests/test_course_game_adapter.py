"""CPU model/PPO/SQLite tests with explicitly fake native host and bot room.

These test real model inference, base/LoRA updates and match transitions, not
C#, core rules, actual bot qualification, game strength or formal training.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

import tests.test_training_pilot as pilot_fixtures
from tests.fixtures import request
from tests.test_windbot_projection import fixture_engine, draw, idle
from ygo_kito import course_game_adapter as course
from ygo_kito.bot_deployment import BotSourceRegistry
from ygo_kito.build_contracts import DeckParts, digest
from ygo_kito.build_pipeline import BuildAssets
from ygo_kito.contracts import DecisionRequest, Versions
from ygo_kito.cpu_training import CpuTrainer, CpuTrainingConfig
from ygo_kito.data_isolation import DataIndex
from ygo_kito.duel_model import DuelModelConfig, FEATURE_VERSION, parameter_digest
from ygo_kito.group_runner import GroupState
from ygo_kito.lora import AdapterConfig, AdapterSession
from ygo_kito.match_runner import MatchParticipant, MatchRules, MatchState, MatchRunner, GameSpec, FirstOrderPolicy
from ygo_kito.validation import ContractError
from ygo_kito.windbot_projection import WindBotOpponent


class CourseGameAdapterTests(unittest.TestCase):
    def setUp(self):
        self.helper = pilot_fixtures.TrainingPilotTests('test_completed_snapshot_exact_weights_neural_forward_and_rng_preserved')
        self.helper.setUp(); self.addCleanup(self.helper.doCleanups)
        h = self.helper; self.root = h.root
        h.profile['sides'] = [[41], [41]]
        h.assets.rows[41] = {'id': 41, 'ot': 1, 'type': 17, 'alias': 0}
        self.assets = object.__new__(BuildAssets)
        self.assets.root, self.assets.rows, self.assets.limits, self.assets.receipt = h.native, h.assets.rows, {}, h.receipt
        self.assets.environment = {'environment_id': 'fixture-course', 'versions': asdict(h.versions), 'authority': 'custom', 'release_cutoff': None}
        self.registry = object.__new__(BotSourceRegistry)
        self.registry.lock, self.registry.inventory = {'fixture': 'no-real-bot-sources'}, h.registry_inventory
        self.versions = h.versions
        self.qual_profile = h.write_json('course-qualification-profile.json', h.profile)
        q = deepcopy(h.qualification)
        q['rows'][0].update(profile_sha256=digest(h.profile), deck_sha256=digest(self.parts(h.profile, 1).to_dict()))
        options = dict(profile=h.profile, environment_id='bot-current-engineering-qualification', opponent_id='qual-'+'f'*32,
                       source='engineering_fixture', session_seconds=120, seat=1)
        q['rows'][0]['binding_sha256'] = digest(self.binding(options))
        self.qualification = h.write_json('course-qualification.json', q)
        self.runtime = course.CourseBotRuntime(self.registry, self.root, 'ice', 'FixtureExecutor',
            h.spec['bot_sources']['audits']['ice'], self.qualification, self.qual_profile, '/fixture/mono',
            'fixture-opponent', source='engineering_fixture')
        self.config = CpuTrainingConfig(model=DuelModelConfig(width=8, card_width=4, heads=2, feedforward=16),
                                       game_seeds=(100, 101, 102), batch_size=1, episode_seconds=30)
        self.trainer = CpuTrainer(self.config, list(range(1, 42)))
        self.index = DataIndex(self.root/'course-index')
        self.rules = MatchRules(self.assets.rows, {}, set(self.assets.rows))
        self.participants = (MatchParticipant('actor', self.parts(h.profile, 0)), MatchParticipant('bot', self.parts(h.profile, 1)))
        self.state = MatchState('fixture-match', self.participants, self.rules, {'fixture': 'not-a-real-resource-lock'}, 'actor')
        self.bindings, self.frames, self.close_calls = [], [], []
        self.actual_first = 0

    @staticmethod
    def parts(profile, seat):
        return DeckParts(tuple(profile['decks'][seat]), tuple(profile['extras'][seat]), tuple(profile['sides'][seat]))

    def binding(self, options):
        seat = options.get('seat', 1)
        other = self.parts(options['profile'], seat).to_dict()
        return {'profile_sha256': digest(options['profile']), 'driver_version': 'explicit-fixture-not-csharp',
            'opponent_deck_sha256': digest(other), 'own_deck_sha256': digest(self.parts(options['profile'], 1-seat).to_dict()),
            'opponent_deck_content_sha256': digest({k: sorted(v) for k, v in other.items()}),
            'driver_implementation_sha256': digest('fake-room-driver'), 'model_sha256': None,
            'registered_record_sha256': digest({k: options[k] for k in ('environment_id', 'opponent_id', 'source', 'session_seconds')})}

    def adapter(self, **options):
        return course.CourseGameAdapter(assets=self.assets, match_state=self.state, actor_participant_id='actor',
            trainer=self.trainer, bot_runtime=self.runtime, data_index=self.index, experiment_id='fixture-course',
            purpose=options.pop('purpose', 'train'), **options)

    @contextmanager
    def fake_execution(self):
        current = {}
        frames, closed = self.frames, self.close_calls
        def construct(registry, executor_id, **options):
            self.bindings.append(deepcopy(options)); current.clear(); current.update(options)
            @contextmanager
            def room(opponent):
                def choose(req, frame): frames.append(frame); return req.actions[0]
                try: yield SimpleNamespace(observer=opponent.seat, duel_rule=5, choose=choose)
                finally: closed.append('fake-room')
            return WindBotOpponent(root=self.assets.root, profile=options['profile'], seat=options['seat'], versions=options['versions'],
                binding=self.binding(options), runtime_validator=lambda: None, room_factory=room)
        def engine(root, *, course_observations, **options):
            actor_seat = 1-current['seat']; bot_seat = current['seat']
            payload = request(); payload['context']['seed'] = None; payload['context']['versions'] = asdict(current['versions'])
            payload['observation'].update(observer=actor_seat, cards=[])
            payload['prompt'] = {'message': 11}; payload['actions'] = [dict(action_id='fake-pass', kind='pass', card_refs=[], value=7)]
            actor = DecisionRequest.from_dict(payload)
            other = deepcopy(payload); other['decision_id'] = 'fake-bot-window'; other['observation']['observer'] = bot_seat
            bot = DecisionRequest.from_dict(other)
            e, _ = fixture_engine(); del e._transport; del e._transport_sent
            e.window = 0; e.pending = None; e.closed = False; e.modern_actions = True
            profile = options['deck_profile']; e.player_decks = tuple(tuple(d) for d in profile['decks'])
            e.player_extras = tuple(tuple(d) for d in profile['extras']); e.context = actor.context
            e.receipt = self.assets.receipt; e._selection_seed = options.get('selection_key')
            e.outcome = None; e.events = []; e.turn = 1; e.life_points = [8000, 0]
            windows = iter((actor, bot))
            course_observations.update(constructor_started=True, constructor_completed=True)
            def next_decision():
                req = next(windows, None)
                if e.window == 0:
                    codes = [999999999, 999999999]; codes[bot_seat] = 1
                    e._transport.consume(draw(0, (codes[0],))+draw(1, (codes[1],))+bytes((11, actor_seat))+idle()[2:])
                elif req is not None: e._transport.consume(bytes((11, bot_seat))+idle()[2:])
                e.window += 1; e.pending = req
                if req is None: e.outcome = {'winner': actor_seat, 'reason_code': 1}; e.events = [{'kind': 5}]
                else:
                    course_observations['decision_windows'] += 1
                    course_observations['actual_first_core_seat'] = self.actual_first
                return req
            e.next_decision = next_decision; e.submit = lambda _: None
            e._observation = lambda p: actor.observation if p == actor_seat else bot.observation
            e.close = lambda: closed.append('fake-engine')
            return e
        with patch.object(BotSourceRegistry, 'training_adapter', construct), \
                patch.object(course, '_CourseNativeEngine', side_effect=engine), \
                patch.object(course, 'verify_resources', return_value=self.assets.receipt), \
                patch('ygo_kito.cpu_training.public_card_facts', return_value={}):
            yield

    @staticmethod
    def sided(request):
        d = request.own_current_deck.to_dict()
        d['main'][0], d['side'][0] = d['side'][0], d['main'][0]
        return DeckParts.from_dict(d)

    def run_two_game_match(self, adapter):
        return MatchRunner(self.state, adapter, {'actor': self.sided, 'bot': self.sided},
            {'actor': FirstOrderPolicy('always_first'), 'bot': FirstOrderPolicy('always_first')}).run()

    def test_base_two_fresh_ppo_games_sideboards_and_actual_seat_swap(self):
        original = parameter_digest(self.trainer.model)
        with self.fake_execution():
            adapter = self.adapter(); result = self.run_two_game_match(adapter)
        self.assertEqual(self.state.status, 'complete')
        self.assertEqual(self.state.summary()['complete_matches'], 1)
        self.assertEqual(self.trainer.updates, 2); self.assertEqual(self.trainer.episode_cursor, 2)
        self.assertNotEqual(parameter_digest(self.trainer.model), original)
        self.assertEqual(self.index.summary()['by_purpose']['train'], 2)
        self.assertEqual(adapter.last_episode['policy_version'], 1)
        self.assertTrue(adapter.last_receipt['model_update_completed'])
        self.assertEqual(adapter.last_receipt['actor_core_seat'], 1)
        game_bindings = [b for b in self.bindings if b['environment_id'] == 'fixture-course']
        self.assertEqual([b['seat'] for b in game_bindings], [1, 0])
        self.assertEqual(game_bindings[1]['profile']['decks'][0][0], 41)
        self.assertEqual(game_bindings[1]['profile']['sides'][0], [1])
        self.assertEqual([g['actual_first_participant_id'] for g in self.state.summary()['games']], ['actor', 'bot'])
        self.assertEqual(len(self.frames), 2)
        self.assertEqual(self.close_calls, ['fake-room', 'fake-engine']*2)

    def test_from_group_keeps_live_effective_lora_and_updates_only_adapter_each_game(self):
        session = AdapterSession(self.trainer.model, AdapterConfig('fixture-duel', 'duel', ('value_head.2',), rank=1, max_updates=3),
            {'base_version': 'fixture-base', 'feature_version': FEATURE_VERSION, 'context_sha256': 'a'*64})
        base = session.verify_base(); before_version = session.version_id()
        group = object.__new__(GroupState); group.duel = self.trainer
        group.sessions = {'duel': session}; group.policy_rng = self.trainer.policy_rng
        self.trainer.config = replace(self.config, game_seeds=(17,))  # Existing group's bootstrap-only base config.
        with self.fake_execution():
            adapter = course.CourseGameAdapter.from_group(group, assets=self.assets, match_state=self.state,
                actor_participant_id='actor', bot_runtime=self.runtime, data_index=self.index, experiment_id='fixture-course',
                purpose='train', config=self.config)
            self.assertIs(adapter.trainer.model, group.duel.model); self.assertIs(adapter.session, session)
            self.run_two_game_match(adapter)
        self.assertEqual(session.updates, 2); self.assertEqual(self.trainer.updates, 0)
        self.assertEqual(session.verify_base(), base); self.assertNotEqual(session.version_id(), before_version)
        self.assertEqual(adapter.last_episode['policy_version'], 1)
        self.assertEqual(adapter.state_metadata()['lora']['version'], session.version_id())
        self.assertEqual(self.trainer.config.game_seeds, (17,))
        with self.assertRaisesRegex(ContractError, 'initial live policy'):
            course.ppo_inputs(adapter.last_episode, self.trainer, session)

    def test_frozen_group_evaluation_uses_same_adapter_and_keeps_all_training_state(self):
        session = AdapterSession(self.trainer.model, AdapterConfig('fixture-duel', 'duel', ('value_head.2',), rank=1, max_updates=3),
            {'base_version': 'fixture-base', 'feature_version': FEATURE_VERSION, 'context_sha256': 'a'*64})
        with self.fake_execution(), patch.object(AdapterSession, 'step', side_effect=AssertionError('evaluation must not update')):
            adapter = self.adapter(purpose='final_eval', adapter_session=session, evaluation_pairs=((800, 900), (801, 901)))
            before = adapter.training_fingerprint()
            self.run_two_game_match(adapter)
            self.assertEqual(before, adapter.training_fingerprint())
        self.assertEqual(session.updates, 0); self.assertEqual(adapter.evaluation_cursor, 2)
        self.assertTrue(adapter.last_receipt['frozen_training_state_unchanged'])
        self.assertEqual(self.index.summary()['by_purpose']['final_eval'], 2)

    def test_unissued_spec_and_missing_real_qualification_stop_before_sampling(self):
        with self.fake_execution():
            adapter = self.adapter()
            with self.assertRaisesRegex(ContractError, 'issued'):
                adapter(GameSpec(self.state.match_id, 1, self.participants, 'actor'))
        with patch.object(BotSourceRegistry, 'training_adapter', side_effect=ContractError('actual constructor audit missing')), \
                patch.object(CpuTrainer, 'sample_episode') as sample:
            with self.assertRaisesRegex(ContractError, 'audit'): self.adapter()
        sample.assert_not_called()

    def test_observed_first_player_required_and_failure_retains_actual_sampling(self):
        self.actual_first = None
        before = parameter_digest(self.trainer.model)
        with self.fake_execution():
            adapter = self.adapter(); spec = self.state.issue_game_spec(); result = adapter(spec)
        self.assertFalse(result.terminal); self.assertIsNone(result.actual_first_core_seat)
        self.assertFalse(adapter.last_receipt['model_update_started'])
        self.assertTrue(adapter.last_receipt['sample_completed'])
        self.assertEqual(parameter_digest(self.trainer.model), before)
        self.assertEqual(self.trainer.updates, 0)

    def test_post_update_error_reports_changed_model_and_observed_optimizer_counter(self):
        original_update = CpuTrainer.update
        def fail_after_step(trainer, episode):
            original_update(trainer, episode)
            raise RuntimeError('fixture post-update publication error')
        before = parameter_digest(self.trainer.model)
        with self.fake_execution(), patch.object(CpuTrainer, 'update', fail_after_step):
            adapter = self.adapter(); result = adapter(self.state.issue_game_spec())
        self.assertFalse(result.terminal); self.assertTrue(adapter.last_receipt['model_update_started'])
        self.assertFalse(adapter.last_receipt['model_update_completed'])
        self.assertEqual(self.trainer.updates, 1)
        self.assertEqual(adapter.last_receipt['after']['observed_optimizer_step_max'], 1)
        self.assertNotEqual(parameter_digest(self.trainer.model), before)
        self.assertEqual(adapter.last_receipt['observed_sampler_updates'], 1)

    def test_attached_lora_cannot_be_omitted_and_base_course_seeds_must_match_saved_config(self):
        bad = CpuTrainingConfig(model=self.config.model, game_seeds=(200, 201), batch_size=1, episode_seconds=30)
        with self.fake_execution(), self.assertRaisesRegex(ContractError, 'complete saved'): self.adapter(config=bad)
        session = AdapterSession(self.trainer.model, AdapterConfig('fixture-duel', 'duel', ('value_head.2',), rank=1, max_updates=3),
            {'base_version': 'fixture-base', 'feature_version': FEATURE_VERSION, 'context_sha256': 'a'*64})
        with self.fake_execution(), self.assertRaisesRegex(ContractError, 'explicitly'): self.adapter()

    def test_runtime_source_identity_cannot_change_between_games_or_inject_an_engine(self):
        with self.fake_execution():
            with self.assertRaises(TypeError): self.adapter(engine_factory=lambda *a, **k: None)
            adapter = self.adapter(); self.runtime.audit['sha256'] = '0'*64
            with patch.object(CpuTrainer, 'sample_episode') as sample:
                result = adapter(self.state.issue_game_spec())
        sample.assert_not_called(); self.assertFalse(result.terminal)
        self.assertIn('source/Executor/audit', adapter.last_receipt['error']['message'])
        self.assertFalse(adapter.last_receipt['observations']['constructor_started'])

    def test_heldout_same_opponent_version_cannot_enter_training_index_split(self):
        with self.fake_execution():
            trained = self.adapter(); self.run_two_game_match(trained)
            self.state = MatchState('fixture-heldout', self.participants, self.rules, {'fixture': 'same-lock'}, 'actor')
            frozen = self.adapter(purpose='final_eval', evaluation_pairs=((800, 900),))
            before = frozen.training_fingerprint()
            result = frozen(self.state.issue_game_spec())
            self.assertEqual(before, frozen.training_fingerprint())
        self.assertFalse(result.terminal)
        self.assertIn('crosses train/validation/final', frozen.last_receipt['error']['message'])
        self.assertFalse(frozen.last_receipt['model_update_started'])
        self.assertEqual(self.index.summary()['by_purpose']['final_eval'], 0)

    def test_course_long_game_cap_reaches_actual_sampler_and_legacy_limit_stays_strict(self):
        requested = course.CourseTrainingConfig(**dict(self.config.__dict__, episode_seconds=120))
        self.trainer = CpuTrainer(requested, list(range(1, 42)))
        seen = []; original = CpuTrainer.sample_episode
        def sample(trainer, *args, **kwargs):
            seen.append(trainer.config.episode_seconds)
            return original(trainer, *args, **kwargs)
        with self.fake_execution(), patch.object(CpuTrainer, 'sample_episode', sample):
            result = self.adapter()(self.state.issue_game_spec())
        self.assertTrue(result.terminal); self.assertEqual(seen, [120])
        with self.assertRaises(ContractError): CpuTrainingConfig(episode_seconds=120)
        with self.assertRaises(ContractError): course.CourseTrainingConfig(episode_seconds=301)


if __name__ == '__main__': unittest.main()
