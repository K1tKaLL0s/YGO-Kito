"""Joint adapter checks; no native case or formal training is executed."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
import hashlib
import tempfile
import unittest
import torch

from tests.test_coordinator_control import ROOT,TASK,DECK,builder,changed_deck,context
from ygo_kito.coordinator_model import CoordinatorTrainer,public_scope_features
from ygo_kito.build_contracts import digest
from ygo_kito.cpu_training import CpuTrainer,CpuTrainingConfig
from ygo_kito.duel_model import DuelModelConfig,parameter_digest
from ygo_kito.lora import AdapterSession,AdapterConfig,tensor_digest
from ygo_kito.lora_group import coordinator_loss
from ygo_kito.model_build_feedback import compare_model_candidates
from local_foundation_course import CycleBudget,CycleBudgetExhausted,execute_cycle
from local_course_collaboration import cycle


class SharedBudgetTests(unittest.TestCase):
    def test_completed_shared_cycle_receipt_closes_only_warning_without_erasing_history(self):
        from tests.test_coordinator_control import LedgerFixture
        ledger=LedgerFixture('runTest');ledger.setUp();self.addCleanup(ledger.doCleanups)
        ledger.results('forecast',100)
        phases=[{'role':role} for role in ('build_goal','build_optimizer','build_goal','build_optimizer')]
        result={'best':{'deck':DECK.to_dict()},'cb_verified':True,'alternation_completed':True,
                'goal_sha256':digest(TASK.goal),'phases':phases}
        proof={'status':'constraints_and_route_verified','task_sha256':TASK.sha256,
               'native_route':{'core_attempts':[{'seed_audit_only':71}]}}
        def kernel(selection,**options):
            options['verifier'](TASK,DECK,course.assets)
            return deepcopy(result)
        session=SimpleNamespace(check_goal=lambda:None,goal_sha256=digest(TASK.goal),task=TASK)
        models=SimpleNamespace(builder=SimpleNamespace(updates={'build_goal':0,'build_optimizer':0}),
            duel=SimpleNamespace(updates=0),coordinator=SimpleNamespace(updates=0),
            kernel=SimpleNamespace(run_selected=kernel,sessions={'fixture':session}))
        consumed=[]
        course=SimpleNamespace(config={'wall_seconds':1000,'course_id':'fixture'},active_seconds=0.,
            counts=lambda:{'bo1':0,'bo3':0},_task=lambda:TASK,models=models,
            assets=SimpleNamespace(effect_receipts=lambda task:[]),construction=deepcopy(result),deck=DECK,
            selection={'candidate_id':'fixture'},records=[],events=[],save=lambda:None,
            feedback=SimpleNamespace(consumed=consumed),
            apply_feedback=lambda fid,aid,**kw:consumed.append({'feedback_id':fid}),
            data_index=SimpleNamespace(freeze=lambda value:None,ingest_construction=lambda *a,**k:None))
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp,patch('ygo_kito.build_pipeline.verify_goal',return_value=proof):
            summary=cycle(course,None,Path(tmp),Path(tmp)/'stop',lambda *a,**k:None,
                cycle_id='1-0',budget=CycleBudget(course),
                feedback={'status':ledger.host.forecast_status('forecast')})
            receipt=summary['review_receipt']
            self.assertEqual(receipt['trace_sha256'],hashlib.sha256(
                (Path(tmp)/'collaboration-v2-000000-cycle-1-0/actual-four-stage.json').read_bytes()).hexdigest())
            ledger.host.record_construction_review('candidate',receipt)
        status=ledger.host.forecast_status('forecast')
        self.assertFalse(status['pending_review']);self.assertEqual(status['matches'],100)
        self.assertTrue(status['alerts']);self.assertTrue(status['checks'])

    def test_collaboration_passes_actual_remaining_budget_to_basic_cb(self):
        clock=[0.];seen=[]
        class ReachedCB(RuntimeError):pass
        def kernel(selection,**options):
            clock[0]=4.
            options['verifier'](TASK,DECK,object())
        def cb(task,deck,assets,**options):
            seen.append(options['seconds'])
            self.assertEqual(task,TASK);self.assertEqual(deck,DECK)
            raise ReachedCB()
        models=SimpleNamespace(builder=SimpleNamespace(updates={'build_goal':0,'build_optimizer':0}),
            duel=SimpleNamespace(updates=0),coordinator=SimpleNamespace(updates=0),kernel=SimpleNamespace(run_selected=kernel))
        course=SimpleNamespace(config={'wall_seconds':10},active_seconds=0.,counts=lambda:{'bo1':1,'bo3':0},
            _task=lambda:TASK,models=models,assets=object(),construction={'best':{'deck':DECK.to_dict()}},
            deck=DECK,selection={'candidate_id':'fixture'},records=[])
        budget=CycleBudget(course,clock=lambda:clock[0])
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp,patch('ygo_kito.build_pipeline.verify_goal',cb):
            with self.assertRaises(ReachedCB):
                cycle(course,None,Path(tmp),Path(tmp)/'stop',lambda *a,**k:None,cycle_id='1-0',budget=budget)
        self.assertEqual(seen,[6.])

    def test_pair_runner_reserves_sampling_and_replay_before_starting_any_case(self):
        cfg=CpuTrainingConfig(model=DuelModelConfig(width=8,card_width=4,heads=2,feedforward=16),game_seeds=(100,101),episode_seconds=30)
        trainer=CpuTrainer(cfg,list(TASK.pool))
        trainer.updates=1  # Declared synthetic version precondition, no trained-strength claim.
        before=parameter_digest(trainer.model)
        def forbidden(*a,**k):raise AssertionError('no case may start without its sample/replay reserve')
        assets=SimpleNamespace(adapter_revision=5,engine_factory=forbidden)
        registry=SimpleNamespace(training_adapter=forbidden)
        course=SimpleNamespace(config={'wall_seconds':100},active_seconds=0.)
        budget=CycleBudget(course)
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp:
            root=Path(tmp);audit=root/'audit.json';audit.write_text('{}')
            with self.assertRaises(CycleBudgetExhausted):
                compare_model_candidates(TASK,assets,[DECK,changed_deck(DECK)],DECK,trainer=trainer,registry=registry,
                    bot={'bot_id':'fixture','executor_id':'fixture','source_id':'fixture'},audit={'path':str(audit),'assembly_sha256':'a'*64},
                    workspace=root,seeds=(100,101),directory=root/'pairs',data_index=None,experiment_id='fixture',
                    stop=root/'stop',status=lambda *a,**k:None,seconds=5.,budget=budget)
            self.assertFalse(list((root/'pairs').glob('*.in-flight.json')))
        self.assertEqual(parameter_digest(trainer.model),before)
        self.assertFalse(getattr(budget,'in_flight',False))

    def test_unit_supervisor_stops_before_next_allocated_game(self):
        calls=[]
        course=SimpleNamespace(config={'wall_seconds':1000},active_seconds=0.,desired='ready',save=lambda:None,
            models=SimpleNamespace(duel=SimpleNamespace(config=SimpleNamespace(episode_seconds=30))),
            run=lambda n:calls.append(n),stage=lambda:'bots-bo1')
        forecast=SimpleNamespace(decide=lambda n:{'action':'train_duel','budget_units':3},
            status=lambda:{'mandatory_rebuild':False},before_training=lambda:None,train_closed_outcomes=lambda:None)
        checks=[]
        def supervisor(phase,*args):checks.append(phase);return phase=='before'
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp:
            result=execute_cycle(course,forecast,None,None,Path(tmp),Path(tmp)/'stop',lambda *a,**k:None,3,unit_boundary=supervisor)
        self.assertEqual(calls,[1]);self.assertEqual(checks,['before','after'])
        self.assertEqual(result['executed_units'],1);self.assertTrue(result['paused'])


class ScopedLoraTests(unittest.TestCase):
    def test_scoped_forecast_and_budget_loss_preserves_unlabelled_route_adapter(self):
        from tests.test_coordinator_control import scope
        trainer=CoordinatorTrainer()
        session=AdapterSession(trainer.model,AdapterConfig('fixture-scoped','coordinator',
            ('encoder.0','encoder.2','scope_projection','route_head','forecast_head','budget_head'),rank=1,max_updates=2),
            {'base_version':'fixture','feature_version':'coordinator-public-scope-context-v2','context_sha256':'a'*64})
        features=public_scope_features(builder(),TASK,DECK,scope(),{'fixture-opponent':DECK})
        row={'context':context(),'scope_features':features,'route_label':'evaluate_duel','forecast_target':.8,'budget_target':.2,
            'provenance':{'dataset_id':'fixture','record_id':'one','source':'synthetic-unit-not-played-games','evidence_sha256':'a'*64}}
        def examples():return {'source':'host_logged_supervision_v1','records':[row],'sha256':digest([row]),'real_win_rate_supervision':False}
        session.step(coordinator_loss(session,examples()))
        before={k:v.detach().clone() for k,v in session.weights().items() if k.startswith('route_head.')}
        row['route_label']=None;row.pop('budget_target')
        session.step(coordinator_loss(session,examples()))
        self.assertTrue(all(torch.equal(value,session.weights()[name]) for name,value in before.items()))
        self.assertTrue(all(session.weights()[name].grad is None for name in before))


if __name__=='__main__':unittest.main()
