"""Pure caller contracts for prospective admission and frozen observation flow."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock,patch

from scripts.local_course_forecast import CourseForecast,record_conditional_cb_signal
from scripts.local_foundation_course import execute_cycle
from ygo_kito.build_contracts import DeckParts,digest
from ygo_kito.coord_contracts import FeedbackPolicy


class AdmissionLoopContracts(unittest.TestCase):
    def test_only_completed_candidate_owned_inference_can_publish_a_failure(self):
        task=SimpleNamespace(sha256='a'*64);deck=DeckParts((1,))
        inference={'task_sha256':task.sha256,'subject_deck_sha256':digest(deck.to_dict()),
            'initial_state_mode':'hypothetical_exact_hand_v1','opening_probability_evaluated':False,
            'inference_completed':True,'status':'bounded_inference_unknown'}
        consume=Mock()
        with patch('scripts.local_course_forecast.verified_conditional_basic_cb',return_value=False):
            record_conditional_cb_signal(consume,'actual-attempt',task,deck,inference)
            record_conditional_cb_signal(consume,'guard-only',task,deck,dict(inference,inference_completed=False))
            record_conditional_cb_signal(consume,'other-deck',task,deck,dict(inference,subject_deck_sha256='b'*64))
        signals=[entry.args[0] for entry in consume.call_args_list]
        self.assertEqual([row.failure_count_eligible for row in signals],[True,False,False])
        self.assertEqual(signals[0].attempt_id,'actual-attempt')

    def controller(self,*,signals=None,due=False,review=False,mandatory=False):
        controller=object.__new__(CourseForecast)
        controller.policy=FeedbackPolicy.twenty_fifty();controller.comparison_policy=Mock()
        controller.host=object()  # route_with_model is replaced by an explicit caller-contract fixture.
        controller.course=SimpleNamespace(models=SimpleNamespace(coordinator=object()))
        controller.value={'decisions':[],'active_candidate':'candidate','active_forecast':'forecast'}
        verdict={'status':'admitted','reasons':[],'evidence_refs':[],
            'signals':{'optimization_requested':False,'mandatory_rebuild':False,'hint_permission':False}}
        verdict['signals'].update(signals or {})
        controller.training_admission=Mock(return_value=verdict)
        controller.before=Mock(return_value=[0.]*64)
        controller.status=Mock(return_value={'matches':0,'mandatory_rebuild':mandatory,
            'pending_review':review,'own_pending_review':review,'rebuild_validation_eligible':False})
        controller.pending_training_feedback=Mock(return_value={'match_ids':['actual-loss']})
        controller.monitoring_due=Mock(return_value=due);controller.save=Mock()
        return controller

    def test_due_observation_cannot_be_starved_by_repeated_training_choices(self):
        controller=self.controller(due=True)
        def route(*args,**kwargs):
            self.assertEqual(kwargs['allowed_routes'],['evaluate_duel','stop'])
            return {'action':'evaluate_duel','budget_units':1},{'route':'evaluate_duel'}
        with patch('scripts.local_course_forecast.route_with_model',side_effect=route):
            plan=controller.decide(8)
        self.assertTrue(plan['eligibility']['frozen_observation_due'])
        self.assertEqual(plan['action'],'evaluate_duel')

    def test_an_individual_loss_does_not_force_construction(self):
        controller=self.controller()
        with patch('scripts.local_course_forecast.route_with_model',return_value=
                ({'action':'train_duel','budget_units':1},{'route':'train_duel'})) as route:
            controller.decide(1)
        self.assertIn('train_duel',route.call_args.kwargs['allowed_routes'])
        self.assertIn('evaluate_duel',route.call_args.kwargs['allowed_routes'])

    def test_real_optimization_signal_and_mandatory_forecast_return_to_construction(self):
        cases=[({'optimization_requested':True},False,'build_optimizer'),({},True,'build_goal')]
        for signals,mandatory,expected in cases:
            with self.subTest(expected=expected):
                controller=self.controller(signals=signals,mandatory=mandatory)
                with patch('scripts.local_course_forecast.route_with_model',return_value=
                        ({'action':expected,'budget_units':1},{'route':expected})) as route:
                    controller.decide(1)
                self.assertEqual(route.call_args.kwargs['allowed_routes'],[expected,'stop'])

    def test_training_allocation_yields_after_sample_when_observation_is_due(self):
        with tempfile.TemporaryDirectory() as temp:
            course=SimpleNamespace(root=Path(temp),active_seconds=0.,config={'wall_seconds':100.},
                desired='ready',save=Mock(),run=Mock(),stage=lambda:'bots-bo1',
                models=SimpleNamespace(duel=SimpleNamespace(config=SimpleNamespace(episode_seconds=1.))))
            forecast=SimpleNamespace(decide=Mock(return_value={'action':'train_duel','budget_units':5}),
                status=Mock(return_value={'mandatory_rebuild':False}),require_formal_duel=Mock(),
                before_training=Mock(),train_closed_outcomes=Mock(),monitoring_due=Mock(return_value=True))
            with patch('scripts.local_foundation_course.publish_course_status'):
                result=execute_cycle(course,forecast,Mock(),None,Path(temp),Path(temp)/'stop',Mock(),5)
        self.assertEqual(result['executed_units'],1);course.run.assert_called_once_with(1)
        self.assertFalse(result['paused'])

    def test_compute_truncation_creates_no_label_or_monitor_obligation(self):
        controller=object.__new__(CourseForecast);controller.policy=FeedbackPolicy.twenty_fifty()
        pending={'match_id':'attempt','forecast_id':'forecast','task_sha256':'a'*64,'deck_sha256':'b'*64}
        controller.value={'pending_training':deepcopy(pending),'active_forecast':'forecast'}
        controller.course=SimpleNamespace(records=[{'match_id':'attempt','complete':False,'receipts':[{
            'kind':'course-small-game-host-receipt','status':'compute_truncated','termination_kind':'compute_budget',
            'sample_completed':False,'model_update_started':False,'model_update_completed':False}]}])
        controller.save=Mock()
        controller.train_closed_outcomes()
        self.assertIsNone(controller.value['pending_training'])
        self.assertNotIn('monitor_obligations',controller.value)
        self.assertEqual(controller.value['censored_training_observations'][0]['outcome_label'],None)

    def test_terminal_training_sample_registers_exact_frozen_observation_obligation(self):
        controller=object.__new__(CourseForecast);controller.policy=FeedbackPolicy.twenty_fifty()
        pending={'match_id':'terminal','forecast_id':'frozen-forecast','candidate_id':'actual-candidate',
            'task_sha256':'a'*64,'deck_sha256':'b'*64,'duel_model_sha256':'c'*64}
        controller.value={'pending_training':pending,'active_forecast':'newer-forecast',
            'trained_artifacts':['artifact'],'training_sample_origins':[]}
        receipt={'kind':'course-small-game-host-receipt','status':'completed','model_update_completed':True,
            'sample_policy_sha256':'c'*64,'data':{'artifact_id':'artifact'}}
        controller.course=SimpleNamespace(records=[{'match_id':'terminal','complete':True,'purpose':'train',
            'format':'bo1','winner':'actor','receipts':[receipt]}],
            data_index=SimpleNamespace(artifact=Mock(return_value={})))
        controller.save=Mock();controller.train_closed_outcomes()
        obligation=controller.value['monitor_obligations'][0]
        self.assertEqual(obligation['forecast_id'],'frozen-forecast')
        self.assertEqual(obligation['task_sha256'],'a'*64)
        self.assertEqual(obligation['deck_sha256'],'b'*64)
        self.assertIsNone(obligation['outcome_quality_label'])


if __name__=='__main__':unittest.main()
