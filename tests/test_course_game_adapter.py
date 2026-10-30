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
from ygo_kito.contracts import ActionSelection, DecisionRequest, Versions
from ygo_kito.cpu_training import CpuTrainer, CpuTrainingConfig, SampleBudgetExceeded
from ygo_kito.data_isolation import DataIndex
from ygo_kito.duel_model import DuelModelConfig, FEATURE_VERSION, parameter_digest
from ygo_kito.duel_effect_limits import EffectLimitBinding
from ygo_kito.group_runner import GroupState
from ygo_kito.lora import AdapterConfig, AdapterSession
from ygo_kito.match_runner import MatchParticipant, MatchRules, MatchState, MatchRunner, GameSpec, FirstOrderPolicy
from ygo_kito import model_opponents as neural
from ygo_kito.native import NativeError
from ygo_kito.contracts import validate_selection
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
            h.spec['bot_sources']['audits']['ice'], self.qualification, self.qual_profile, str(self.root/'fixture-mono'),
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

    def test_exact_effect_limit_binding_reaches_actual_sampler_without_automatic_card_guessing(self):
        # Synthetic identity/description binding exercises host plumbing only;
        # it is not an assertion that fixture card 1 is the official named card.
        binding=EffectLimitBinding('fixture-count','qa17200','fixture:shared-name:effect-1',
            ((1,17),),((1,digest(self.assets.rows[1].get('desc',''))),),scope_complete=True)
        with self.fake_execution():
            adapter=self.adapter(effect_limit_bindings=(binding,))
            result=adapter(self.state.issue_game_spec())
        self.assertTrue(result.terminal)
        self.assertEqual(adapter.last_receipt['before']['planning']['effect_limit_binding_count'],1)
        view=adapter.last_episode['steps'][0]['planning']['interruption_rules']['counter_queries']
        self.assertEqual(view[0]['rule_id'],'qa17200');self.assertEqual(view[0]['remaining'],3)

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

    @patch('ygo_kito.training_admission.require_training_admission', new=lambda **_: {'status': 'admitted'})
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
        self.assertEqual(adapter.last_receipt['sampling_attempt_cursor'], 0)
        self.assertEqual(adapter.last_receipt['next_sampling_attempt_cursor'], 0)

    @patch('ygo_kito.training_admission.require_training_admission',new=lambda **kwargs:{'status':'admitted'})
    def test_decision_budget_preserves_partial_without_index_update_or_terminal_result(self):
        self.config = replace(self.config, native_decision_limit=1)
        self.trainer = CpuTrainer(self.config, list(range(1, 42)))
        before = parameter_digest(self.trainer.model)
        rng_before = self.trainer.policy_rng.get_state().tolist()
        with self.fake_execution():
            adapter = self.adapter(training_attempt_cursor=0)
            with patch.object(adapter, '_index', side_effect=AssertionError('partial must not enter the data index')) as index_episode, \
                    patch.object(CpuTrainer, 'update', side_effect=AssertionError('partial must not update')) as update:
                result = adapter(self.state.issue_game_spec())
        index_episode.assert_not_called(); update.assert_not_called()
        self.assertFalse(result.terminal); self.assertIsNone(result.winner_core_seat)
        self.assertEqual(result.anomaly, 'compute_budget_exhausted')
        receipt = adapter.last_receipt; partial = adapter.last_partial_sample
        self.assertEqual(receipt['status'], 'compute_truncated')
        self.assertEqual(receipt['error']['type'], SampleBudgetExceeded.__name__)
        self.assertEqual(receipt['sampling_attempt_cursor'], 0)
        self.assertEqual(receipt['next_sampling_attempt_cursor'], 1)
        self.assertFalse(receipt['sample_completed']); self.assertFalse(receipt['model_update_started'])
        self.assertFalse(receipt['model_update_completed']); self.assertIsNone(adapter.last_episode)
        self.assertFalse(partial['terminal']); self.assertTrue(partial['truncated'])
        self.assertFalse(partial['training_eligible']); self.assertIsNone(partial['terminal_reward'])
        self.assertIsNone(partial['outcome']); self.assertFalse(partial['native_continuation_available'])
        self.assertEqual(partial['seed_audit_only'], 100)
        self.assertEqual(len(partial['steps']), 1); self.assertEqual(partial['steps'][0]['reward'], 0.)
        self.assertIsInstance(partial['steps'][0]['request'], dict)
        self.assertEqual(partial['next_request']['decision_id'], 'fake-bot-window')
        self.assertEqual(len(partial['responses']), 1)
        self.assertEqual(partial['sampler_rng_before'], rng_before)
        self.assertEqual(partial['sampler_rng_after'], self.trainer.policy_rng.get_state().tolist())
        self.assertEqual(partial['resources'], self.assets.receipt)
        boundary = partial['resource_boundary']
        self.assertEqual(boundary['kind'], 'compute_budget')
        self.assertEqual(boundary['limits_reached'], ['native_decision_limit'])
        self.assertEqual(boundary['native_decision_limit'], 1)
        self.assertEqual(boundary['native_decisions'], 1); self.assertEqual(boundary['actor_samples'], 1)
        self.assertEqual(boundary['episode_seconds'], self.config.episode_seconds)
        self.assertGreater(boundary['elapsed_seconds'], 0)
        self.assertEqual(receipt['resource_boundary'], boundary)
        self.assertEqual(parameter_digest(self.trainer.model), before)
        self.assertEqual((self.trainer.updates, self.trainer.episode_cursor), (0, 0))
        self.assertIsNone(self.trainer._pending_episode_digest)
        self.assertEqual(self.index.summary()['by_purpose']['train'], 0)
        self.assertEqual(self.close_calls, ['fake-room', 'fake-engine'])

    @patch('ygo_kito.training_admission.require_training_admission',new=lambda **kwargs:{'status':'admitted'})
    def test_native_error_remains_failed_or_uncertain_without_budget_reclassification(self):
        before = parameter_digest(self.trainer.model)
        with self.fake_execution(), patch.object(CpuTrainer, 'sample_episode', side_effect=NativeError('fixture genuine native failure')):
            adapter = self.adapter()
            with patch.object(adapter, '_index') as index_episode, patch.object(CpuTrainer, 'update') as update:
                result = adapter(self.state.issue_game_spec())
        index_episode.assert_not_called(); update.assert_not_called()
        self.assertFalse(result.terminal); self.assertIsNone(result.winner_core_seat)
        self.assertEqual(result.anomaly, NativeError.__name__, adapter.last_receipt.get('error'))
        self.assertEqual(adapter.last_receipt['status'], 'failed_or_uncertain')
        self.assertEqual(adapter.last_receipt['error']['type'], NativeError.__name__)
        self.assertFalse(adapter.last_receipt['retry_allowed'])
        self.assertFalse(adapter.last_receipt['sample_completed'])
        self.assertFalse(adapter.last_receipt['model_update_started'])
        self.assertIsNone(adapter.last_partial_sample); self.assertIsNone(adapter.last_episode)
        self.assertEqual(parameter_digest(self.trainer.model), before)
        self.assertEqual((self.trainer.updates, self.trainer.episode_cursor), (0, 0))
        self.assertEqual(self.index.summary()['by_purpose']['train'], 0)

    @patch('ygo_kito.training_admission.require_training_admission',new=lambda **kwargs:{'status':'admitted'})
    def test_training_attempt_cursor_uses_next_declared_seed_without_advancing_update_cursor(self):
        original_sample = CpuTrainer.sample_episode
        seen_cursors, seen_seeds = [], []
        def sample(trainer, *args, **kwargs):
            seen_cursors.append((trainer.updates, trainer.episode_cursor))
            factory = kwargs['engine_factory']
            def engine(root, **options):
                seen_seeds.append(options['seed'])
                return factory(root, **options)
            return original_sample(trainer, *args, **dict(kwargs, engine_factory=engine))
        with self.fake_execution(), patch.object(CpuTrainer, 'sample_episode', sample):
            adapter = self.adapter(training_attempt_cursor=1)
            result = adapter(self.state.issue_game_spec())
        self.assertEqual(seen_cursors, [(0, 0)])
        self.assertEqual(seen_seeds, [101])
        self.assertTrue(result.terminal)
        self.assertEqual(adapter.last_episode['summary']['seed_audit_only'], 101)
        self.assertEqual(adapter.last_receipt['sampling_attempt_cursor'], 1)
        self.assertEqual(adapter.last_receipt['next_sampling_attempt_cursor'], 2)
        self.assertTrue(adapter.last_receipt['model_update_completed'])
        self.assertEqual((self.trainer.updates, self.trainer.episode_cursor), (1, 1))
        self.assertEqual(self.index.summary()['by_purpose']['train'], 1)

    @patch('ygo_kito.training_admission.require_training_admission',new=lambda **kwargs:{'status':'admitted'})
    def test_ppo_rejects_preserved_compute_partial_before_optimizer_step(self):
        self.config = replace(self.config, native_decision_limit=1)
        self.trainer = CpuTrainer(self.config, list(range(1, 42)))
        with self.fake_execution():
            adapter = self.adapter(training_attempt_cursor=0)
            result = adapter(self.state.issue_game_spec())
        self.assertEqual(result.anomaly, 'compute_budget_exhausted')
        before = parameter_digest(self.trainer.model)
        with patch.object(self.trainer.optimizer, 'step', side_effect=AssertionError('partial must not reach optimizer')) as step:
            with self.assertRaisesRegex(ContractError, 'incomplete.*terminal target'):
                self.trainer.update(adapter.last_partial_sample)
        step.assert_not_called()
        self.assertEqual(parameter_digest(self.trainer.model), before)
        self.assertEqual((self.trainer.updates, self.trainer.episode_cursor), (0, 0))

    @patch('ygo_kito.training_admission.require_training_admission',new=lambda **kwargs:{'status':'admitted'})
    def test_pre_update_failure_does_not_consume_attempt_or_publish_temporary_sample_cursor(self):
        before = parameter_digest(self.trainer.model)
        with self.fake_execution(), patch.object(CpuTrainer, 'update', side_effect=RuntimeError('fixture before optimizer step')):
            adapter = self.adapter(training_attempt_cursor=0)
            result = adapter(self.state.issue_game_spec())
        receipt = adapter.last_receipt
        self.assertFalse(result.terminal)
        self.assertTrue(receipt['sample_completed']); self.assertTrue(receipt['model_update_started'])
        self.assertFalse(receipt['model_update_completed'])
        self.assertEqual(receipt['observed_sampler_cursor'], 1)
        self.assertEqual(receipt['observed_sampler_updates'], 0)
        self.assertEqual(receipt['sampling_attempt_cursor'], 0)
        self.assertEqual(receipt['next_sampling_attempt_cursor'], 0)
        self.assertEqual(receipt['after']['training_updates'], 0)
        self.assertEqual((self.trainer.updates, self.trainer.episode_cursor), (0, 0))
        self.assertEqual(parameter_digest(self.trainer.model), before)
        self.assertEqual(receipt['status'], 'failed_or_uncertain')

    @patch('ygo_kito.training_admission.require_training_admission', new=lambda **_: {'status': 'admitted'})
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
        self.assertEqual(adapter.last_receipt['sampling_attempt_cursor'], 0)
        self.assertEqual(adapter.last_receipt['next_sampling_attempt_cursor'], 1)

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

    def model_runtime(self):
        source = CpuTrainer(replace(self.config, model_seed=999), list(range(1, 42)))
        snapshot = neural.FrozenDuelSnapshot.capture(source, assets=self.assets, source_binding={'fixture': 'initial-other-model'},
            source_label='synthetic initial network; not trained ability')
        return neural.ModelOpponentRuntime(snapshot, 'fixture-initial-model')

    def model_adapter(self, runtime, **options):
        return course.CourseGameAdapter(assets=self.assets, match_state=self.state, actor_participant_id='actor',
            trainer=self.trainer, model_runtime=runtime, data_index=self.index, experiment_id='fixture-course',
            purpose=options.pop('purpose', 'train'), **options)

    def model_match(self, runtime, name='fixture-model-match'):
        return MatchState(name, self.participants, self.rules, {'fixture': 'fake-engine-only', 'model_opponent': runtime.identity()}, 'actor')

    @contextmanager
    def fake_model_execution(self):
        """Actual two-network scoring/PPO; explicitly fake engine, no C#/core."""
        owner = self
        class Engine:
            def __init__(self, root, *, course_observations, **options):
                self.receipt = owner.assets.receipt; self._selection_seed = options.get('selection_key')
                self.turn = 1; self.life_points = [8000, 8000]; self.events = []; self.outcome = None
                self.pending = None; self.cursor = 0; self.watched = course_observations
                self.requests = []
                for seat in (0, 1):
                    payload = request(); payload['context']['seed'] = None
                    payload['context']['versions'] = asdict(neural._versions(owner.assets, options['deck_profile']['adapter_revision']))
                    payload['observation'].update(observer=seat, turn_player=0)
                    payload['observation']['cards'][0].update(owner=seat, controller=seat, card_id=seat+1)
                    payload['observation']['cards'][1].update(owner=1-seat, controller=1-seat)
                    payload['decision_id'] = 'fake-model-seat-'+str(seat)
                    self.requests.append(DecisionRequest.from_dict(payload))
                self.watched.update(constructor_started=True, constructor_completed=True)
            def __enter__(self): return self
            def __exit__(self, *args): owner.close_calls.append('fake-model-engine')
            def next_decision(self):
                if self.cursor == 2:
                    self.pending = None; self.events = [{'kind': 5}]
                    self.outcome = {'winner': owner.state._pending.seat_of('actor'), 'reason_code': 1}
                    return None
                self.pending = self.requests[self.cursor]; self.cursor += 1
                self.watched['actual_first_core_seat'] = owner.actual_first
                self.watched['decision_windows'] += 1
                return self.pending
            def submit(self, selected): validate_selection(self.pending, selected)
            def _observation(self, seat): return self.requests[seat].observation
        with patch.object(neural, 'verify_resources', return_value=self.assets.receipt), \
                patch.object(course, 'verify_resources', return_value=self.assets.receipt), \
                patch.object(course, '_CourseNativeEngine', Engine), \
                patch('ygo_kito.cpu_training.public_card_facts', return_value={}):
            yield

    def test_two_neural_initial_models_use_actual_sampler_fresh_base_ppo_and_bo3_siding(self):
        before = parameter_digest(self.trainer.model)
        with self.fake_model_execution(), patch.object(BotSourceRegistry, 'training_adapter', side_effect=AssertionError('no C# path')):
            runtime = self.model_runtime(); frozen = runtime.identity()
            self.state = self.model_match(runtime)
            adapter = self.model_adapter(runtime)
            result = self.run_two_game_match(adapter)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['complete_matches'], 1)
        self.assertEqual(self.trainer.updates, 2); self.assertEqual(self.trainer.episode_cursor, 2)
        self.assertNotEqual(parameter_digest(self.trainer.model), before)
        self.assertEqual(runtime.identity(), frozen)
        self.assertEqual(adapter.last_receipt['actor_core_seat'], 1)
        self.assertEqual(adapter.last_episode['policy_version'], 1)
        self.assertEqual(adapter.last_episode['steps'][0]['request'].observation.observer, 1)
        self.assertEqual(adapter.last_receipt['opponent_binding']['controller'], 'local_snapshot')
        self.assertEqual(adapter.last_receipt['opponent_binding']['model_sha256'], frozen['snapshot']['model_sha256'])
        self.assertEqual(adapter.state_metadata()['kind'], 'course-live-model-self-play-game-adapter')
        self.assertNotIn('qualification_sha256', adapter.state_metadata())
        self.assertEqual([g['actual_first_participant_id'] for g in result['games']], ['actor', 'bot'])
        self.assertEqual(self.index.summary()['by_purpose']['train'], 2)

    def test_model_opponent_effective_actor_lora_and_frozen_eval_keep_same_update_path(self):
        session = AdapterSession(self.trainer.model, AdapterConfig('fixture-actor-duel', 'duel', ('value_head.2',), rank=1, max_updates=3),
            {'base_version': 'fixture-base', 'feature_version': FEATURE_VERSION, 'context_sha256': 'a'*64})
        base = session.verify_base()
        with self.fake_model_execution():
            runtime = self.model_runtime(); self.state = self.model_match(runtime)
            adapter = self.model_adapter(runtime, adapter_session=session)
            self.run_two_game_match(adapter)
            self.assertEqual(session.updates, 2); self.assertEqual(session.verify_base(), base)
            # Independent eval index/models opponent version to retain actual
            # DataIndex split guards; no relabeling of the training opponent.
            source = CpuTrainer(replace(self.config, model_seed=998), list(range(1, 42)))
            frozen = neural.FrozenDuelSnapshot.capture(source, assets=self.assets, source_binding={'fixture': 'heldout'}, source_label='heldout initial fixture')
            heldout = neural.ModelOpponentRuntime(frozen, 'fixture-heldout-model')
            self.state = self.model_match(heldout, 'fixture-model-eval')
            evaluation = self.model_adapter(heldout, purpose='final_eval', adapter_session=session, evaluation_pairs=((800, 900), (801, 901)))
            before = evaluation.training_fingerprint()
            with patch.object(AdapterSession, 'step', side_effect=AssertionError('frozen eval must not update')):
                self.run_two_game_match(evaluation)
            self.assertEqual(evaluation.training_fingerprint(), before)
        self.assertEqual(evaluation.evaluation_cursor, 2)
        self.assertTrue(evaluation.last_receipt['frozen_training_state_unchanged'])

    def test_model_runtime_xor_exact_match_snapshot_and_same_split_guards(self):
        with self.fake_model_execution():
            runtime = self.model_runtime()
            with self.assertRaisesRegex(ContractError, 'exactly one'):
                self.adapter(model_runtime=runtime)
            with self.assertRaisesRegex(ContractError, 'match must bind'): self.model_adapter(runtime)
            self.state = self.model_match(runtime)
            trained = self.model_adapter(runtime); self.run_two_game_match(trained)
            self.state = self.model_match(runtime, 'fixture-model-heldout')
            evaluated = self.model_adapter(runtime, purpose='final_eval', evaluation_pairs=((800, 900),))
            before = evaluated.training_fingerprint()
            result = evaluated(self.state.issue_game_spec())
            self.assertFalse(result.terminal); self.assertEqual(before, evaluated.training_fingerprint())
            self.assertIn('crosses train/validation/final', evaluated.last_receipt['error']['message'])
            other = neural.ModelOpponentRuntime(runtime.snapshot, 'another-opponent-id')
            with self.assertRaisesRegex(ContractError, 'match must bind'): self.model_adapter(other)

    def test_sampled_model_uses_a_per_game_rng_fork_and_rejects_actor_rng_aliases(self):
        with self.fake_model_execution():
            runtime = replace(self.model_runtime(), policy_mode='sample')
            self.state = self.model_match(runtime)
            for alias in (self.trainer.policy_rng, self.trainer.batch_rng):
                with self.assertRaisesRegex(ContractError, 'independent owned'):
                    self.model_adapter(runtime, opponent_policy_rng=alias)
            with self.assertRaisesRegex(ContractError, 'independent owned'): self.model_adapter(runtime)
            generator = torch.Generator(device='cpu').manual_seed(700)
            initial = generator.get_state().clone()
            adapter = self.model_adapter(runtime, opponent_policy_rng=generator)
            self.run_two_game_match(adapter)
        self.assertEqual(self.trainer.updates, 2)
        self.assertTrue(torch.equal(generator.get_state(), initial))
        private = adapter.last_receipt['opponent_sampling']
        self.assertTrue(private['caller_rng_unchanged']); self.assertEqual(private['after']['decisions'], 1)
        self.assertNotEqual(private['before']['rng_state'], private['after']['rng_state'])
        self.assertEqual(adapter.state_metadata()['model_opponent']['policy_mode'], 'sample')
        self.assertNotIn('rng_state', str(adapter.state_metadata()))

    def test_normal_python_diagnostic_ring_is_bounded_and_never_copies_private_dto(self):
        d = request(); d['context']['seed'] = None; d['prompt'] = {'message': 11}
        req = DecisionRequest.from_dict(d)
        class NormalFixture:
            def __init__(self): self.pending = None
            def next_decision(self): self.pending = req; return req
            def submit(self, selection): validate_selection(self.pending, selection)
        class Observed(course._FirstTurnObservation, NormalFixture): pass
        watched = {'decision_windows': 0, 'actual_first_core_seat': None}
        engine = Observed(course_observations=watched)
        for _ in range(150):
            current = engine.next_decision()
            engine.submit(ActionSelection(current.context.run_id, current.duel_id, current.decision_id, current.actions[0].action_id))
        with self.assertRaises(ContractError):
            engine.submit(ActionSelection(req.context.run_id, req.duel_id, req.decision_id, 'not-legal'))
        diagnostics = watched['private_diagnostics']
        self.assertEqual(diagnostics['windows'], 150); self.assertEqual(diagnostics['submit_returned'], 150)
        self.assertEqual(diagnostics['submit_rejected'], 1); self.assertEqual(len(diagnostics['ring']), 128)
        self.assertEqual(diagnostics['prompt_counts'], {'11': 150})
        self.assertFalse(diagnostics['ring'][-1]['accepted']); self.assertFalse(diagnostics['training_eligible'])
        for secret in ('card_id', 'card_refs', 'seed', 'private_reveals', 'old_log_prob'):
            self.assertNotIn(secret, str(diagnostics))


if __name__ == '__main__': unittest.main()
