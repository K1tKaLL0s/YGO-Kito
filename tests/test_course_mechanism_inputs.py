"""Direct course wiring contracts; authored here, runtime status is not_run."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import torch
from tests.test_coordinator_control import TASK,DECK,builder,scope,context
from tests.test_effect_mechanisms import assets_fixture
from ygo_kito.coordinator_model import CoordinatorTrainer,CoordinatorModelConfig,FEATURE_VERSION,MECHANISM_FEATURE_VERSION
from ygo_kito.course_models import CourseModels
from ygo_kito.course_game_adapter import CourseTrainingConfig
from ygo_kito.duel_model import DuelModelConfig
from ygo_kito.lora import AdapterConfig
from ygo_kito.build_contracts import digest
from ygo_kito.coord_contracts import FeedbackPolicy
from ygo_kito.group_runner import tree_digest
from ygo_kito.validation import ContractError
from local_course_forecast import CourseForecast
from local_course_collaboration import basic_cb_completed


def fresh_models(mechanisms):
    task,assets,_,_=assets_fixture()
    configs={r:AdapterConfig('test-'+r,r,('head.0',) if r.startswith('build_') else
        ('value_head.2',) if r=='duel' else ('route_head',),rank=1,max_updates=2)
        for r in ('build_goal','build_optimizer','duel','coordinator')}
    cfg=CourseTrainingConfig(model=DuelModelConfig(width=8,card_width=4,heads=2,feedforward=16),game_seeds=(100,))
    binding={'kind':'explicit-synthetic-mechanism-course','learning_stage':'base'}
    if mechanisms:binding['coordinator_mechanism_inputs']=True
    return CourseModels.initialize(task,assets,cfg,configs,'.',None,assets.rows,binding),assets


class CourseMechanismInputTests(unittest.TestCase):
    def test_foundation_and_collaboration_completion_accept_unknown_but_reject_not_run(self):
        for status,completed,expected in (('routes_inferred',True,True),('bounded_inference_unknown',True,True),
                                           ('not_run',False,False),('bounded_inference_unknown',False,False)):
            result={'basic_cb':{'status':status,'inference_completed':completed},'cb_verified':True}
            with self.subTest(status=status,completed=completed):
                self.assertEqual(basic_cb_completed(result),expected)

    def test_real_forecast_and_prospective_training_caller_use_the_selected_generation(self):
        for mechanisms in (False,True):
            trainer=CoordinatorTrainer(CoordinatorModelConfig(mechanism_inputs=mechanisms))
            course=SimpleNamespace(models=SimpleNamespace(builder=builder(),coordinator=trainer,
                versions=lambda:{'duel':'3'*64,'build_goal':'1'*64,'build_optimizer':'2'*64}),
                _task=lambda:TASK,deck=DECK,stage=lambda:'bots-bo1',pending=None,records=[],config={'course_id':'test-course'})
            f=object.__new__(CourseForecast);f.course=course;f.policy=FeedbackPolicy()
            # This test isolates feature generation; actual policy guards are tested separately.
            f.require_formal_duel=lambda purpose: {'status':'admitted','fixture':'features-only'}
            f.feature_version=MECHANISM_FEATURE_VERSION if mechanisms else FEATURE_VERSION
            f.host=SimpleNamespace(forecast_status=lambda fid:{'matches':0,'pending_review':False,'mandatory_rebuild':False})
            f.value={'candidates':{},'forecasts':{},'active_candidate':None,'active_forecast':None,'pending_training':None}
            f._scope=lambda:(scope(),{'fixture-opponent':DECK})
            f.save=lambda:None;f._capture_window=lambda fid:{'synthetic':'no filesystem'}
            def host_call(host,method,payload):
                if method=='handoff.submit':return {'candidate_id':payload['candidate_id']}
                if method=='route':return {'context':context()}
                if method=='forecast.register':return {'forecast_id':payload['forecast_id']}
                raise AssertionError(method)
            with patch('local_course_forecast.call',side_effect=host_call):
                features=f.before();f.before_training()
            self.assertEqual(f.value['pending_training']['features'],features)
            if mechanisms:
                self.assertEqual(features['feature_version'],MECHANISM_FEATURE_VERSION)
                self.assertEqual(len(features['mechanism_features']),64)
            else:self.assertEqual(len(features),64);self.assertIsInstance(features,list)
            self.assertEqual(trainer.updates,0)

    def test_new_base_v3_roundtrip_is_explicit_and_projection_is_untrained_zero(self):
        models,assets=fresh_models(True);state=models.save_state()
        restored=CourseModels.from_state(state,assets=assets,expected_binding=state['binding'])
        self.assertTrue(restored.coordinator.config.mechanism_inputs)
        self.assertEqual(int(restored.coordinator.model.mechanism_projection.weight.count_nonzero()),0)
        self.assertEqual(restored.coordinator.updates,0)
        self.assertEqual(restored.initialization_provenance['coordinator_mechanisms']['ability_verified'],False)
        self.assertTrue(torch.equal(models.policy_rng.get_state(),restored.policy_rng.get_state()))

    def test_legacy_checkpoint_stays_v2_and_relabelling_does_not_migrate_tensors(self):
        models,assets=fresh_models(False);state=models.save_state()
        state['configs']['coordinator'].pop('mechanism_inputs')
        state['state_sha256']=tree_digest({k:v for k,v in state.items() if k!='state_sha256'})
        restored=CourseModels.from_state(state,assets=assets,expected_binding=state['binding'])
        self.assertFalse(restored.coordinator.config.mechanism_inputs)
        changed=deepcopy(state);changed['configs']['coordinator']['mechanism_inputs']=True
        changed['binding']['coordinator_mechanism_inputs']=True;changed['binding_sha256']=digest(changed['binding'])
        changed['state_sha256']=tree_digest({k:v for k,v in changed.items() if k!='state_sha256'})
        with self.assertRaisesRegex(ContractError,'base tensor shape'):
            CourseModels.from_state(changed,assets=assets,expected_binding=changed['binding'])
