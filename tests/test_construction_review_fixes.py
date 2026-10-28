"""Four targeted review regressions; synthetic fixtures, no engine or training."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

from ygo_kito.build_contracts import BuildTask,DeckParts,digest
from ygo_kito.build_semantics import proof
from ygo_kito.build_training import supervision_projection
from ygo_kito.construction_candidates import axis_edits
from ygo_kito.construction_course_evidence import cycle_identity,task_supervision,supervision_seeds
from ygo_kito.construction_fill import _candidate_basic_cb
from ygo_kito.data_isolation import DataIndex
from ygo_kito.semantic_training import SOURCE,validate
from ygo_kito.validation import ContractError
from tests.test_construction_logic import fixture_session,example_graph
from tests.test_construction_portfolio import catalog

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from local_course_collaboration import cycle


class ConstructionReviewFixes(unittest.TestCase):
    def setUp(self):self.task,self.assets,self.base=catalog()

    def test_completing_group_preserves_existing_anchor_and_its_quantity(self):
        group={'group_id':'anchored','source':'synthetic-reviewed-package',
            'zones':{'main':[1,1,1,20,22],'extra':[21],'side':[]}}
        rows=[r for r in axis_edits(self.task,self.assets,self.base,mechanism_groups=[group])
              if r['strategy']=='axis:mechanism:anchored']
        self.assertTrue(rows)
        for row in rows:
            self.assertGreaterEqual(row['deck'].main.count(1),3)
            for z in ('main','extra','side'):
                self.assertFalse(Counter(group['zones'][z])-Counter(getattr(row['deck'],z)))
            self.assets.validate(self.task,row['deck'])

    def test_full_three_region_package_is_kept_after_joint_replacements(self):
        for code in range(200,206):self.assets.rows[code]=dict(self.assets.rows[1],id=code,alias=0,setcode=0x333)
        raw=self.task.to_dict();raw['pool']=sorted(self.assets.rows);raw['sizes']['side']=15
        task=BuildTask.from_dict(raw);base=DeckParts(self.base.main,self.base.extra,tuple(c for c in range(200,205) for _ in range(3)))
        self.assets.validate(task,base)
        group={'group_id':'three-regions','source':'synthetic-reviewed-package',
            'zones':{'main':[1,1,20],'extra':[21],'side':[200,205]}}
        rows=[r for r in axis_edits(task,self.assets,base,mechanism_groups=[group]) if r['strategy']=='axis:mechanism:three-regions']
        self.assertTrue(rows)
        for row in rows:
            for z in ('main','extra','side'):
                self.assertFalse(Counter(group['zones'][z])-Counter(getattr(row['deck'],z)))
            self.assets.validate(task,row['deck'])

    def test_task_only_positive_has_no_route_requirement_and_is_admitted(self):
        row=task_supervision(self.task,self.base,self.assets)
        self.assertEqual(row['source'],'pinned_catalog_constraint_check')
        self.assertEqual(row['evidence']['status'],'constraints_satisfied')
        data={'source':SOURCE,'purpose':'train','task_sha256':self.task.sha256,'goals':[row],'pairs':[],
            'unknown_routes_used_as_negative':False,'competitive_quality_labels':False,
            'public_effect_receipts':self.assets.effect_receipts(self.task)}
        data['supervision_sha256']=digest(supervision_projection(data))
        validate(self.task,self.assets,data,for_training=False)
        self.assertEqual(supervision_seeds(data),())
        with tempfile.TemporaryDirectory() as folder:
            index=DataIndex(folder)
            index.freeze({'dataset_id':'synthetic-task-only','experiment_id':'review-regression','purpose':'train',
                'family':'construction','versions':self.task.environment['versions'],'opponents':[],'task_sha256':self.task.sha256})
            index.ingest_construction('synthetic-task-only','static-positive',self.task,self.assets,data,seeds=())
            self.assertIsNotNone(index.admit_construction('static-positive',self.task,data))

    def test_seed_collection_follows_all_evidence_types_and_keeps_unknowns_unlabelled(self):
        data={'goals':[task_supervision(self.task,self.base,self.assets),
            {'source':'pinned_constraints_and_actual_native_route','evidence':{'native_route':{'core_attempts':[{'seed_audit_only':5}]}}}],
            'pairs':[{'evidence':{'plan':{'paired_seeds_audit_only':[11,12]}}},
                     {'evidence':{'original_win_comparison':{'plan':{'paired_seeds_audit_only':[21,22]}}}}]}
        self.assertEqual(supervision_seeds(data),(5,11,12,21,22))
        cb=_candidate_basic_cb(self.task,self.base,self.assets,None)
        self.assertEqual(cb['status'],'not_run')
        self.assertNotEqual(cb['status'],proof(self.task,self.base,self.assets)['status'])
        with self.assertRaisesRegex(ContractError,'different task/deck'):
            _candidate_basic_cb(self.task,self.base,self.assets,
                lambda *args:{'status':'bounded_inference_unknown','subject_deck_sha256':'0'*64})

    def test_forced_cycle_requires_persisted_identity(self):
        with self.assertRaisesRegex(ContractError,'persisted host cycle_id'):cycle_identity(0,True,None)
        for bad in ('../x','cycle-one','',True):
            with self.assertRaises(ContractError):cycle_identity(0,True,bad)
        self.assertEqual(cycle_identity(0,True,'2-1'),('0-cycle-2-1','collaboration-v2-000000-forced-cycle-2-1'))

    def test_comparison_case_and_dataset_ids_are_scoped_to_the_same_persisted_cycle(self):
        from ygo_kito.model_build_feedback import comparison_case_id,comparison_dataset_id
        plan={'synthetic':'same-frozen-comparison'};binding={'synthetic':'same-opponent'}
        identities=[]
        for cycle_id in ('1','2'):
            key,_=cycle_identity(0,True,cycle_id)
            pair=(comparison_case_id(plan,0,7,0,key),comparison_dataset_id(binding,key))
            self.assertEqual(pair,(comparison_case_id(plan,0,7,0,key),comparison_dataset_id(binding,key)))
            identities.append(pair)
        self.assertNotEqual(identities[0][0],identities[1][0]);self.assertNotEqual(identities[0][1],identities[1][1])
        self.assertNotEqual(comparison_case_id(plan,0,7,0),identities[0][0])

    def test_actual_course_script_accepts_unknown_cb_and_separates_forced_cycles(self):
        session=fixture_session('堆墓',self.task);session.submit_logic(example_graph(),role='build_goal',reason='synthetic-host-fixture')
        inference={'status':'bounded_inference_unknown','task_sha256':self.task.sha256,
            'subject_deck_sha256':digest(self.base.to_dict()),'routes':[],'inference_completed':True}
        validation={'status':'list_constraints_verified_logic_unproven','best_deck':self.base.to_dict(),
                    'attempts':[{'engine_validation':proof(self.task,self.base,self.assets)}]}
        candidate={'deck':self.base.to_dict(),'logic':session.logic.to_dict(),'logic_sha256':session.logic.sha256,
                   'validation':validation,'basic_cb':inference,'task_verified':True,'cb_verified':False}
        phases=[{'phase_number':i+1,'role':r,'stage_3':{'status':'concrete_candidate_cb_pending'}}
                for i,r in enumerate(('build_goal','build_optimizer','build_goal','build_optimizer'))]
        result={'best':candidate,'phases':phases,'retained_candidates':[],'basic_cb':inference,
            'construction_candidate':candidate,'cb_verified':False,'task_verified':True,'goal_sha256':session.goal_sha256,
            'latest_logic_sha256':session.logic.sha256}
        calls=[]
        def run_selected(selection,**kwargs):
            calls.append(kwargs)
            kwargs['verifier'](self.task,self.base,self.assets)
            kwargs['basic_cb_recorder'](self.task,self.base,inference)
            return deepcopy(result)
        models=SimpleNamespace(builder=SimpleNamespace(updates={'build_goal':0,'build_optimizer':0}),
            duel=SimpleNamespace(updates=0),coordinator=SimpleNamespace(updates=0),
            kernel=SimpleNamespace(run_selected=run_selected,sessions={'selected':session}))
        scratch=Path(__file__).resolve().parents[1]/'.cache'/'construction-review-tests'
        scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            target=Path(folder);index=DataIndex(target/'index')
            course=SimpleNamespace(models=models,assets=self.assets,selection={'candidate_id':'selected'},
                construction=deepcopy(result),deck=self.base,data_index=index,config={'course_id':'review-regression'},
                feedback=SimpleNamespace(consumed=[]),records=[],events=[],counts=lambda:{'bo1':0},
                _task=lambda:self.task,save=lambda:None,status=lambda:{})
            def apply_feedback(feedback_id,artifact_id,**kwargs):
                index.artifact(artifact_id,for_training=True)
                course.feedback.consumed.append({'feedback_id':feedback_id})
            course.apply_feedback=apply_feedback
            with patch('local_design_supervision.require_artifact_clearance',return_value=None):
                first=cycle(course,target,target,target/'stop',lambda *args,**kwargs:None,force_rebuild=True,cycle_id='1')
                second=cycle(course,target,target,target/'stop',lambda *args,**kwargs:None,force_rebuild=True,cycle_id='2')
                before=len(course.feedback.consumed)
                again=cycle(course,target,target,target/'stop',lambda *args,**kwargs:None,force_rebuild=True,cycle_id='2')
            self.assertEqual(first['cycle_id'],'1');self.assertEqual(second,again)
            self.assertEqual(len(calls),2);self.assertTrue(all(c['base'] is None for c in calls))
            self.assertEqual(before,len(course.feedback.consumed))
            ids=[r['feedback_id'] for r in course.feedback.consumed]
            self.assertEqual(len(ids),len(set(ids)))
            self.assertTrue(any('-0-cycle-1-' in i for i in ids));self.assertTrue(any('-0-cycle-2-' in i for i in ids))
            for number in ('1','2'):
                root=target/('collaboration-v2-000000-forced-cycle-'+number)
                data=json.loads((root/'native-goal.json').read_text(encoding='utf-8'))
                self.assertEqual(data['goals'][0]['source'],'pinned_catalog_constraint_check')
                self.assertEqual(supervision_seeds(data),())
                self.assertTrue((root/'basic-cb-inference-001.json').is_file())
