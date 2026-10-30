"""Pure saved-receipt/admission contracts; no native, model or ledger execution."""
from copy import deepcopy
from pathlib import Path
from types import ModuleType,SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from ygo_kito.build_contracts import BuildTask,DeckParts,digest
from ygo_kito.build_semantics import route_task,validate_counts
from ygo_kito.basic_cb_inference import inference_requirements
from ygo_kito.coord_contracts import FeedbackPolicy
from ygo_kito.training_admission import (TrainingAdmissionDeferred,require_training_admission,
                                        verified_conditional_basic_cb)


def receipt_fixture():
    versions={key:'fixture-'+key for key in ('core','scripts','cards','protocol','card_pool','banlist')}
    raw={'schema_version':4,'task_id':'construction-fixture','source':'engineering_fixture','candidate_budget':16,
        'environment':{'environment_id':'fixture','authority':'custom','release_cutoff':None,'versions':versions},
        'goal':{'kind':'deck_constraints','constraints':[{'id':'main-members','zones':['main'],
            'predicate':{'field':'card_ids','value':list(range(1,15))},'minimum':40,'maximum':40}],'preferences':[]},
        'sizes':{'main':40,'extra':1,'side':0},'pool':list(range(1,15))+[100],'requirements':[],
        'annotations':[{'tag':'fixture\u00b7controlled','layer':'engineering_goal','source':'unit-fixture','subject':'self','condition':'pure data'}]}
    task=BuildTask.from_dict(raw);deck=DeckParts(tuple(c for c in range(1,14) for _ in range(3))+(14,),(100,))
    rows={c:{'id':c,'type':17,'level':4} for c in range(1,15)};rows[100]={'id':100,'type':0x800000,'level':4}
    assets=SimpleNamespace(rows=rows,validate=Mock())
    derived=deepcopy(raw);derived['task_id']='basic-cb-fixture'
    derived['goal']['route_goal']={'kind':'xyz_summon','card_id':100,
        'starting_conditions':{'player':0,'turn':1,'requires_opening_hand':[1,2]}}
    derived['requirements']=inference_requirements(task,deck,derived['goal'])
    derived=BuildTask.from_dict(derived);native_task=route_task(derived);subject=digest(deck.to_dict())
    assumption={'mode':'hypothetical_exact_hand_v1','player':0,'hand':[1,2],
                'unspecified_hand_resources':0,'opening_probability_evaluated':False}
    responses=[{'player':0,'request_sha256':'a'*64,'action_id':'offered-action-fixture'}]
    events=[{'kind':62,'public_summoning_card':100,'player':0},{'kind':63}]
    observation={'observer':0,'turn_player':0,'turn':1,'phase':'main1','life_points':[8000,8000],
        'hand_counts':[0,5],'deck_counts':[38,35],'cards':[
            {'ref':'target','owner':0,'controller':0,'zone':'monster','visibility':'public','card_id':100,'material_count':2},
            {'ref':'material-a','owner':0,'controller':0,'zone':'overlay','visibility':'public','card_id':1,'attached_to':'target'},
            {'ref':'material-b','owner':0,'controller':0,'zone':'overlay','visibility':'public','card_id':2,'attached_to':'target'}]}
    native={'status':'verified_success','card_list_legal':True,'task_sha256':native_task.sha256,'deck_sha256':subject,
        'starting_condition':native_task.goal['starting_conditions'],'random_dependency':'controlled own hand',
        'core_attempts':[{'seed_audit_only':7,'declared_opening_condition_met':True,'opening_assumption':deepcopy(assumption)}],
        'responses':responses,'core_event_kinds':[62,63],'trajectory_sha256':digest(responses),'elapsed_seconds':.1,'unmet':[],
        'route_evidence':{'driver':'bounded-public-dto-route-search-v1','opponent':'neutral-pass-engineering-only',
            'conditional_only':True,'opening_assumption':assumption,'material_preference':'public-fact-ranked','sum_choices':[],
            'final_observation':observation,'core_event_audit_not_policy_input':events,'versions':native_task.environment['versions'],
            'exploration':{'branches_executed':1,'branch_budget':24,'nodes_expanded':1,'intent_schema_version':2,
                'prewritten_route_supplied':False,'failed_branches':[],'discovered_intents':[
                    {'operation':'select','card_ids':[1,2]},{'operation':'special_summon','card_ids':[100]}]}}}
    proof={'status':'constraints_and_route_verified','task_sha256':derived.sha256,'deck_sha256':subject,
        'effect_execution_verified':True,'competitive_strength_verified':False,
        'constraints':{'status':'constraints_satisfied','task_sha256':derived.sha256,'deck_sha256':subject,
            'versions':derived.environment['versions'],'counts':validate_counts(derived,deck,assets)},'native_route':native}
    cb={'status':'routes_inferred','task_sha256':task.sha256,'subject_deck_sha256':subject,'inference_completed':True,
        'initial_state_mode':'hypothetical_exact_hand_v1','opening_probability_evaluated':False,
        'routes':[{'task':derived.to_dict(),'proof':proof}]}
    return task,deck,assets,cb


def policy_verdict(task,deck,**kwargs):
    return {'status':'admitted','task_sha256':task.sha256,'deck_sha256':digest(deck.to_dict()),
            'policy_epoch':'explicit-unit-definition','reasons':[],'evidence_refs':[{'kind':'unit-policy-evidence'}]}


class MemoryRoot:
    def __init__(self,in_flight=False):self.in_flight=in_flight
    def __truediv__(self,name):return SimpleNamespace(exists=lambda:self.in_flight)


class TrainingAdmissionTests(unittest.TestCase):
    def test_saved_native_success_requires_actual_target_material_action_and_resource_evidence(self):
        task,deck,assets,cb=receipt_fixture()
        with patch('ygo_kito.extra_routes.engine_for_goal') as native:
            self.assertTrue(verified_conditional_basic_cb(task,deck,cb,assets=assets))
            for field in ('intents','materials','target','trajectory','opening','resource','attempts'):
                broken=deepcopy(cb);proof=broken['routes'][0]['proof']['native_route'];evidence=proof['route_evidence']
                if field=='intents':evidence['exploration']['discovered_intents']=[]
                elif field=='materials':evidence['final_observation']['cards']=[]
                elif field=='target':evidence['core_event_audit_not_policy_input'][0]['public_summoning_card']=99
                elif field=='trajectory':proof['trajectory_sha256']='b'*64
                elif field=='opening':evidence['opening_assumption']['hand']=[3,4]
                elif field=='resource':evidence['versions']['core']='different-core'
                else:proof['core_attempts']=[]
                with self.subTest(field=field):self.assertFalse(verified_conditional_basic_cb(task,deck,broken,assets=assets))
            self.assertFalse(verified_conditional_basic_cb(task,deck,cb))
            self.assertFalse(verified_conditional_basic_cb(task,DeckParts((9,)*40),cb,assets=assets))
            native.assert_not_called()

    def test_reasons_are_blockers_and_independent_signals_cannot_claim_admission(self):
        task,deck,assets,cb=receipt_fixture()
        def query(policy):return require_training_admission(task=task,deck=deck,basic_cb=cb,assets=assets,purpose='train',comparison_policy=policy)
        self.assertEqual(query(None)['status'],'deferred')
        good=query(policy_verdict);self.assertEqual(good['status'],'admitted')
        self.assertIsNone(good['signals']['hint_permission'])
        for change in ({'reasons':['score_below_56']},{'evidence_refs':[]},{'deck_sha256':'wrong'},
                       {'signals':{'hint_permission':'all'}},{'signals':{'mandatory_rebuild':True}},
                       {'status':'deferred','reasons':[]}):
            with self.subTest(change=change):
                result=query(lambda **kwargs:dict(policy_verdict(**kwargs),**change))
                self.assertEqual(result['status'],'deferred')
        signals={'optimization_requested':True,'mandatory_rebuild':False,'hint_permission':False}
        result=query(lambda **kwargs:dict(policy_verdict(**kwargs),signals=signals))
        self.assertEqual(result['signals'],signals);self.assertEqual(result['status'],'admitted')

    def test_repeated_admission_queries_are_pure_and_do_not_record_inference_failures_or_hint_tiers(self):
        task,deck,assets,cb=receipt_fixture();before=deepcopy(cb);ledger={'cb_failures':1,'below_56_count':1,'hint_tier':0}
        original=deepcopy(ledger)
        def policy(**kwargs):
            self.assertEqual(ledger,original)
            return policy_verdict(**kwargs)
        for _ in range(3):
            result=require_training_admission(task=task,deck=deck,basic_cb=cb,assets=assets,
                purpose='construction_comparison',comparison_policy=policy)
            self.assertEqual(result['status'],'admitted')
        self.assertEqual(ledger,original);self.assertEqual(cb,before)
        error=TrainingAdmissionDeferred({'reasons':['missing-definition']})
        self.assertFalse(error.safe_boundary_saved);self.assertFalse(error.pause_requested)

    def test_scenario_marks_saved_boundary_only_after_its_actual_save_without_inflight(self):
        from ygo_kito.scenario_course import ScenarioCourse
        task,deck,assets,cb=receipt_fixture();deferred={'status':'deferred','reasons':['definition-missing']}
        for in_flight in (False,True):
            course=object.__new__(ScenarioCourse);course.root=MemoryRoot(in_flight);course.assets=assets
            course.construction={'best':{'deck':deck.to_dict(),'basic_cb':cb}};course.comparison_policy=None
            course.selection=None;course.models=SimpleNamespace(builder=SimpleNamespace(task=task));course.save=Mock()
            with patch('ygo_kito.training_admission.require_training_admission',return_value=deferred):
                with self.assertRaises(TrainingAdmissionDeferred) as caught:course._require_training_admission(deck,'train')
            self.assertEqual(caught.exception.safe_boundary_saved,not in_flight)
            self.assertEqual(caught.exception.pause_requested,not in_flight)
            self.assertEqual(course.save.call_count,0 if in_flight else 1)

    def test_adapter_rechecks_actual_actor_deck_before_attempt_or_model_state(self):
        from ygo_kito.course_game_adapter import CourseGameAdapter
        task,deck,assets,cb=receipt_fixture()
        class Spec(SimpleNamespace):pass
        spec=Spec(participants=[SimpleNamespace(participant_id='actor',deck=DeckParts((9,)*40))])
        adapter=object.__new__(CourseGameAdapter);adapter.actor_id='actor';adapter.assets=assets;adapter.purpose='train'
        adapter.match_state=SimpleNamespace(assert_game_spec=Mock());adapter._used_specs=set();adapter.state_metadata=Mock()
        adapter._admission_task=task;adapter._admission_basic_cb=cb;adapter._comparison_policy=policy_verdict
        with patch('ygo_kito.match_runner.GameSpec',Spec):
            with self.assertRaises(TrainingAdmissionDeferred) as caught:adapter(spec)
        self.assertFalse(caught.exception.safe_boundary_saved);self.assertEqual(adapter._used_specs,set())
        adapter.state_metadata.assert_not_called()

    def test_cycle_defers_before_forecast_pending_or_course_attempt_and_saves_real_boundary(self):
        script=Path(__file__).resolve().parents[1]/'scripts/local_foundation_course.py'
        module=ModuleType('admission_cycle_fixture');module.__file__=str(script)
        exec(compile(script.read_text(encoding='utf-8'),str(script),'exec'),module.__dict__)
        course=SimpleNamespace(active_seconds=0.,config={'wall_seconds':100.},root=MemoryRoot(),save=Mock(),run=Mock(),
            models=SimpleNamespace(duel=SimpleNamespace(config=SimpleNamespace(episode_seconds=1.))))
        forecasts=SimpleNamespace(decide=Mock(return_value={'action':'train_duel','budget_units':1}),
            status=Mock(return_value={'mandatory_rebuild':False}),before_training=Mock(),
            require_formal_duel=Mock(side_effect=TrainingAdmissionDeferred({'reasons':['definition-missing']})))
        with patch.object(module,'publish_course_status'):
            with self.assertRaises(TrainingAdmissionDeferred) as caught:
                module.execute_cycle(course,forecasts,Mock(),None,None,MemoryRoot()/ 'stop',Mock(),1)
        forecasts.before_training.assert_not_called();course.run.assert_not_called();course.save.assert_called_once()
        self.assertEqual(course.desired,'paused');self.assertTrue(caught.exception.safe_boundary_saved)

    def test_new_twenty_fifty_policy_requires_explicit_looks_and_keeps_old_policy_exact(self):
        from scripts.local_course_forecast import CourseForecast
        old=FeedbackPolicy();serialized=old.to_dict()
        self.assertNotIn('review_horizon',serialized)
        self.assertEqual(FeedbackPolicy.from_dict(serialized).to_dict(),serialized)
        controller=object.__new__(CourseForecast);controller.policy=old
        self.assertIn('explicit_twenty_fifty_forecast_policy_boundary_required',controller._forecast_definition_reasons())
        missing=FeedbackPolicy(review_horizon=20,rebuild_horizon=50,checkpoints=(),minimum_matches=None)
        self.assertFalse(missing.definitions_ready)
        self.assertIn('predeclared_look_schedule',missing.missing_definitions)
        controller.policy=missing
        self.assertIn('forecast_definition_missing:predeclared_look_schedule',controller._forecast_definition_reasons())
        with self.assertRaisesRegex(ValueError,'definitions missing'):missing.assess(20,0.,.9,1)
        # Synthetic declared looks, not a proposed production look schedule.
        policy=FeedbackPolicy(review_horizon=20,rebuild_horizon=50,checkpoints=(5,20,30,50),minimum_matches=5,
            policy_epoch='unit-only',count_definition_id='unit-only',significance_definition_id='unit-only')
        self.assertTrue(policy.assess(5,0.,.9,1)['low'])
        self.assertFalse(policy.assess(20,20.,.9,1)['low'])
        self.assertIsNone(policy.assess(19,0.,.9,1))


if __name__=='__main__':unittest.main()
