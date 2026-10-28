"""Production recorder and observer scan; synthetic evidence, no native games.

The scan subprocess is portable. It does not certify the Linux daemon's lease,
heartbeat or formal-training guard.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import gc,json,os,subprocess,sys,unittest

from tests import test_design_supervisor as supervisor_fixture
from tests.test_autonomous_construction import kernel_fixture,deck_for
from ygo_kito.autonomous_construction import AutonomousConstructionKernel
from ygo_kito.construction_fill import construction_cycle
from ygo_kito.validation import ContractError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from local_course_collaboration import record_basic_cb_inference


class ConstructionSupervisorIntegrationTests(unittest.TestCase):
    def test_duplicate_receipts_keep_namespace_priority_and_task_deck_checks_with_reversed_glob(self):
        from design_supervisor import Catalog, inspect_artifact
        fixture=supervisor_fixture.IndependentDesignSupervisorTests()
        fixture.setUp();self.addCleanup(fixture.doCleanups)
        original=fixture.course/'basic-cb-inference-001.json'
        raw=json.loads(original.read_text(encoding='utf-8'))
        for name in ('basic-cb-inference-002.json','basic-cb-inference-004.json','construction-route-000.json'):
            supervisor_fixture.write(fixture.course/name,raw)
        nested=fixture.course/'collaboration-v2-000000';nested.mkdir()
        supervisor_fixture.write(nested/'basic-cb-inference-000.json',raw)
        wrong_task=deepcopy(raw);wrong_task['task']['task_id']='different-synthetic-task'
        supervisor_fixture.write(fixture.course/'basic-cb-inference-000-wrong-task.json',wrong_task)
        wrong_deck=deepcopy(raw);wrong_deck['deck']['main'][-1]=24
        supervisor_fixture.write(fixture.course/'basic-cb-inference-000-wrong-deck.json',wrong_deck)
        glob=Path.glob
        catalog=Catalog(fixture.base,fixture.policy)
        try:
            with patch.object(Path,'glob',lambda path,pattern:iter(reversed(list(glob(path,pattern))))):
                receipt=inspect_artifact(fixture.path,fixture.course,catalog)
        finally:catalog.db.close()
        self.assertEqual(receipt['cb_source'],original.name)

    def test_real_kernel_runs_basic_inference_only_after_four_concrete_outputs_and_keeps_unknown(self):
        from ygo_kito.basic_cb_inference import infer_basic_cb
        _,assets,builder,original_kernel=kernel_fixture()
        binding=deepcopy(original_kernel.source_binding);binding['basic_cb_stage']='after_construction'
        kernel=AutonomousConstructionKernel(builder,original_kernel.coordinator,assets=assets,
            host_available_ids=assets.rows,source_binding=binding,pool_limit=32,candidate_limit=8)
        selection=kernel.select_task();task=kernel._selection(selection)
        session,_=kernel._session(selection);calls=[]
        def infer(current,deck,current_assets,**kwargs):
            roles=[h['role'] for h in session.history if h.get('stage')==3 and
                   h.get('result',{}).get('status')=='concrete_candidate_cb_pending']
            self.assertEqual(roles,['build_goal','build_optimizer']*2)
            self.assertNotIn('route_goal',current.goal);self.assertEqual(current.requirements,())
            calls.append(supervisor_fixture.digest(deck.to_dict()))
            return infer_basic_cb(current,deck,current_assets,**kwargs)
        with patch('ygo_kito.basic_cb_inference.infer_basic_cb',side_effect=infer):
            result=kernel.run_selected(selection,base=deck_for(task,assets))
        self.assertTrue(calls);self.assertTrue(result['alternation_completed'])
        self.assertTrue(result['task_verified']);self.assertTrue(result['basic_cb_inference_performed'])
        self.assertEqual(result['basic_cb']['status'],'bounded_inference_unknown')
        self.assertTrue(result['basic_cb']['inference_completed'])
        self.assertEqual(result['basic_cb']['routes'],[]);self.assertFalse(result['cb_verified'])
        self.assertEqual(calls[0],supervisor_fixture.digest(result['phases'][-1]['proposal_deck']))
        for before,after in zip(result['phases'],result['phases'][1:]):
            self.assertEqual(before['proposal_deck'],after['input_deck'])
        self.assertEqual(result['best']['deck'],result['phases'][-1]['proposal_deck'])
        for phase in result['phases']:
            for attempt in phase['stage_3']['attempts']:
                self.assertEqual(attempt['engine_validation']['status'],'not_run')

    def test_production_records_are_seen_by_the_real_observer_in_a_separate_process(self):
        fixture=supervisor_fixture.IndependentDesignSupervisorTests()
        fixture.setUp()
        def cleanup():
            gc.collect();fixture.doCleanups()
        self.addCleanup(cleanup)
        root=fixture.course/'collaboration-v2-000000-forced-cycle-1';root.mkdir()
        result=deepcopy(fixture.result)
        deck=deepcopy(result['construction_candidate']['deck']);deck['main'][-1]=24
        result['phases'][-1]['proposal_deck']=deepcopy(deck)
        result['phases'][-1]['stage_3']['attempts'][0]['concrete_proposal']['deck']=deepcopy(deck)
        result['construction_candidate']['deck']=deepcopy(deck)
        result['basic_cb'].update(subject_deck_sha256=supervisor_fixture.digest(deck),
                                 status='bounded_inference_unknown',inference_completed=True)
        result['basic_cb']['engine_validation']['deck_sha256']=supervisor_fixture.digest(deck)
        supervisor_fixture.write(root/'actual-four-stage.json',result)
        # A legacy filename is neither a new record nor part of the new count.
        supervisor_fixture.write(root/'basic-cb-999.json',{'legacy':'unconsumed'})
        task_dto=SimpleNamespace(to_dict=lambda:deepcopy(fixture.task))
        deck_dto=SimpleNamespace(to_dict=lambda:deepcopy(deck))
        first=record_basic_cb_inference(root,task_dto,deck_dto,result['basic_cb'])
        second=record_basic_cb_inference(root,task_dto,deck_dto,result['basic_cb'])
        self.assertEqual(first.name,'basic-cb-inference-001.json')
        self.assertEqual(second.name,'basic-cb-inference-002.json')
        preserved=second.with_name('basic-cb-inference-004.json');second.rename(preserved)
        old_bytes=preserved.read_bytes()
        self.assertEqual(record_basic_cb_inference(root,task_dto,deck_dto,result['basic_cb']).name,
                         'basic-cb-inference-005.json')
        self.assertEqual(preserved.read_bytes(),old_bytes)
        code='''from pathlib import Path
import json,os,sys
sys.path.insert(0,str(Path(sys.argv[1])/'scripts'))
from design_supervisor import Catalog,audit
base=Path(sys.argv[2]);policy=json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))
catalog=Catalog(base,policy)
try: print(json.dumps({'pid':os.getpid(),'receipts':audit(base,policy,catalog)}))
finally: catalog.db.close()
'''
        process=subprocess.run([sys.executable,'-X','utf8','-c',code,str(ROOT),str(fixture.base),str(fixture.policy_path)],
                               capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(process.returncode,0,process.stdout+process.stderr)
        observed=json.loads(process.stdout)
        self.assertNotEqual(observed['pid'],os.getpid())
        receipt=next(r for r in observed['receipts'] if r['artifact'].endswith('actual-four-stage.json'))
        self.assertEqual(Path(receipt['cb_source']).name,first.name)
        self.assertFalse(receipt['whole_graph_execution_or_competitive_strength_certified'])

    def test_actual_incomplete_kernel_result_keeps_none_and_false(self):
        _,assets,_,kernel=kernel_fixture()
        selection=kernel.select_task();task=kernel._selection(selection)
        deck=deck_for(task,assets);session,_=kernel._session(selection)
        incomplete=construction_cycle(session,assets,{},base=deck,verifier=None)
        self.assertIsNone(incomplete['basic_cb'])
        # Supply a real unresolved cycle at the controller boundary; all
        # inference/performed flags are still produced by the actual kernel.
        with patch('ygo_kito.autonomous_construction.ConstructionController.run',return_value=incomplete):
            result=kernel.run_selected(selection,base=deck,verifier=None)
        self.assertIsNone(result['basic_cb'])
        self.assertFalse(result['alternation_completed'])
        self.assertFalse(result['basic_cb_inference_performed'])
        self.assertFalse(result['cb_verified'])
        self.assertEqual(result['status'],'construction_unresolved')

    def test_integrated_kernel_keeps_the_supervisor_wip_preassigned_route_rejection(self):
        _,assets,builder,kernel=kernel_fixture()
        binding=deepcopy(kernel.source_binding)
        binding.update(basic_cb_stage='after_construction',construction_goal=deepcopy(builder.task.goal))
        binding['construction_goal']['route_goal']={'kind':'synchro_summon','card_id':1}
        with self.assertRaisesRegex(ContractError,'preassigned construction goal'):
            AutonomousConstructionKernel(builder,kernel.coordinator,assets=assets,
                host_available_ids=assets.rows,source_binding=binding,pool_limit=32,candidate_limit=8)
