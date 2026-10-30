"""Real post-construction provider/forecast paths with isolated synthetic data.

Native goal search is replaced at its explicit verifier boundary. No formal
learner update, original checkpoint, or Linux supervisor process is exercised.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,tempfile,unittest

from tests import test_coordinator_control  # explicit fail-loud Windows import guard
from tests.test_effect_mechanisms import assets_fixture
from tests.test_effect_construction_integration import legal_base
from ygo_kito.autonomous_construction import AutonomousConstructionKernel
from ygo_kito.build_contracts import BuildTask,DeckParts,digest
from ygo_kito.build_semantics import proof
from ygo_kito.data_isolation import DataIndex
from ygo_kito.validation import ContractError
from local_foundation_course import CycleBudget,execute_cycle
from local_course_collaboration import cycle
from local_course_forecast import CourseForecast,canonical_deck
from local_design_supervision import make_unit_boundary


class CrossWindowAdapterTests(unittest.TestCase):
    def test_real_new_provider_shares_six_second_budget_and_unknown_cb_admits_task_and_retained(self):
        _,assets,builder,old_kernel=assets_fixture()
        kernel=AutonomousConstructionKernel(builder,old_kernel.coordinator,assets=assets,
            host_available_ids=assets.rows,allowed_theme_ids=['setcode-2d1'],
            source_binding={'kind':'synthetic-post-construction-budget','basic_cb_stage':'after_construction'})
        selection=kernel.select_task();task=BuildTask.from_dict(selection['task']);base=legal_base(task,assets)
        # The incumbent only seeds the actual four new phases. It contributes
        # no route proof and receives no competitive quality label.
        incumbent={'best':{'deck':base.to_dict()},'retained_candidates':[]}
        models=SimpleNamespace(builder=builder,duel=SimpleNamespace(updates=0),
            coordinator=old_kernel.coordinator,kernel=kernel)
        clock=[0.];stages=[];seen=[];consumed=[]
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp);index=DataIndex(target/'index')
            course=SimpleNamespace(config={'wall_seconds':10.,'course_id':'synthetic-budget'},active_seconds=0.,
                counts=lambda:{'bo1':0,'bo3':0},_task=lambda:task,models=models,assets=assets,
                construction=incumbent,deck=base,selection=selection,records=[],events=[],save=lambda:None,
                status=lambda:{},data_index=index,feedback=SimpleNamespace(consumed=consumed))
            def apply_feedback(fid,artifact_id,**kwargs):
                index.artifact(artifact_id,for_training=True)
                consumed.append({'feedback_id':fid})
            course.apply_feedback=apply_feedback
            class ObservedBudget(CycleBudget):
                def check(self,stage,**kwargs):
                    stages.append(stage);return super().check(stage,**kwargs)
            budget=ObservedBudget(course,clock=lambda:clock[0]);clock[0]=4.
            def native_boundary(current,deck,current_assets,**options):
                if 'route_goal' in current.goal:
                    seen.append(options['seconds'])
                    return {'status':'bounded_inference_unknown','task_sha256':current.sha256,
                            'deck_sha256':digest(deck.to_dict()),
                            'exploration':{'nodes_expanded':1},'search_started':True}
                return proof(current,deck,current_assets)
            # Only the unavailable live guard is replaced here; a separate
            # integration test runs the actual observer audit subprocess.
            with (patch('ygo_kito.build_pipeline.verify_goal',side_effect=native_boundary),
                  patch('local_design_supervision.require_artifact_clearance',return_value=None),
                  patch('ygo_kito.construction_candidates.comparable_candidates',
                        side_effect=lambda result,incumbent:[result['best']])):
                summary=cycle(course,target,target,target/'stop',lambda *a,**k:None,
                              cycle_id='1-0',budget=budget)
            self.assertTrue(seen)
            self.assertTrue(all(0.<seconds<=6. for seconds in seen),seen)
            for stage in ('before_basic_cb_provider','before_basic_cb_route','before_basic_cb_verifier','after_basic_cb_provider'):
                self.assertIn(stage,stages)
            result=json.loads((target/'collaboration-v2-000000-cycle-1-0/actual-four-stage.json').read_text(encoding='utf-8'))
            self.assertFalse(result['cb_verified']);self.assertTrue(result['task_verified'])
            self.assertNotIn('engine_validation',result['basic_cb'])
            self.assertEqual(result['basic_cb']['status'],'bounded_inference_unknown')
            self.assertTrue(summary['review_receipt']['task_verified'])
            self.assertTrue(summary['review_receipt']['basic_cb_inference_performed'])
            observer=CourseForecast.__new__(CourseForecast)
            subject=SimpleNamespace(construction=result);observer.course=subject
            chosen=canonical_deck(DeckParts.from_dict(result['best']['deck']))
            checked=observer._existing_candidate_proof(task,chosen,assets)
            self.assertEqual(checked['status'],'constraints_satisfied')
            retained=result['retained_candidates'];self.assertGreaterEqual(len(retained),2)
            for candidate in retained:
                deck=canonical_deck(DeckParts.from_dict(candidate['deck']))
                self.assertEqual(observer._existing_candidate_proof(task,deck,assets)['task_sha256'],task.sha256)
            bad=deepcopy(result);bad['basic_cb']['subject_deck_sha256']='0'*64
            bad['best']['basic_cb']['subject_deck_sha256']='0'*64;subject.construction=bad
            with self.assertRaises(ContractError):observer._existing_candidate_proof(task,chosen,assets)
            subject.construction=deepcopy(result)
            for attempt in subject.construction['best']['validation']['attempts']:
                attempt.get('engine_validation',attempt)['task_sha256']='0'*64
            with self.assertRaises(ContractError):observer._existing_candidate_proof(task,chosen,assets)
            self.assertEqual(builder.updates,{'build_goal':0,'build_optimizer':0})

    def test_real_unit_callback_stops_before_any_learning_when_observer_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stop=root/'stop';saved=[]
            course=SimpleNamespace(root=root/'course',deck=object(),active_seconds=0.,desired='ready',
                config={'wall_seconds':100.},save=lambda:saved.append(True),status=lambda:{},
                models=SimpleNamespace(builder=SimpleNamespace(updates={'build_goal':0,'build_optimizer':0}),
                    duel=SimpleNamespace(updates=0),coordinator=SimpleNamespace(updates=0)),
                run=lambda *a:(_ for _ in ()).throw(AssertionError('learning must not start')))
            forecast=SimpleNamespace(decide=lambda n:{'action':'train_duel','budget_units':1},
                                     status=lambda:{'mandatory_rebuild':False})
            result=execute_cycle(course,forecast,None,root,root,stop,lambda *a,**k:None,1,
                                 unit_boundary=make_unit_boundary(root,stop))
            self.assertEqual(result['executed_units'],0);self.assertTrue(result['paused'])
            self.assertEqual(course.desired,'paused');self.assertTrue(stop.exists());self.assertTrue(saved)
