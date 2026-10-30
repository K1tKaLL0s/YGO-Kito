"""Prospective host seams only: no model, native game, or training execution."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ygo_kito.build_contracts import DeckParts, digest
from ygo_kito.course_admission_policy import (ActualCandidateContext, CourseAdmissionPolicy,
                                             candidate_functional_units, load_course_admission_policy)
from ygo_kito.effect_mechanisms import MechanismCatalog
from ygo_kito.reference_scoring import Block, PEARL_PRIORS
from ygo_kito.validation import ContractError


def fixture():
    task = SimpleNamespace(sha256='a'*64, environment={'environment_id':'unit'})
    deck = DeckParts(tuple(c for c in range(1,14) for _ in range(3))+(14,))
    assets = SimpleNamespace(rows={c:{'id':c,'type':17,'desc':'unit effect','name':str(c)}
        for c in range(1,15)}, validate=Mock())
    return task, deck, assets


def write_private(root):
    profiles = {sha256(b'unit effect').hexdigest(): {'blocks': [dict(
        kind='mill',fact_id='unit-mill',quote='unit effect')], 'unknowns': []}}
    (root/'reviewed_semantics.json').write_text(json.dumps({'profiles':profiles}),encoding='utf-8')
    (root/'calibration-manifests.json').write_text(json.dumps({'2022-07':{
        'reference_period_id':'2022-07','theme':'pearl_grave_fusion','reference_score':70,
        'reference_raw':52.07806234375,'scope':'2022-07/pearl-reference-v1'}}),encoding='utf-8')


def policy(root, *, historical=False, contextualize_factory=None):
    if historical: write_private(root)
    return CourseAdmissionPolicy(root/'host'/'state.json', private_root=root,
        period_id='2022-07' if historical else '2026-10',
        theme='pearl_grave_fusion' if historical else None,
        priors=PEARL_PRIORS if historical else None,
        contextualize_factory=contextualize_factory)


def event(task, deck, attempt, *, success=False, eligible=True):
    return {'attempt_id':attempt,'task_sha256':task.sha256,'deck_sha256':digest(deck.to_dict()),
        'success':success,'failure_count_eligible':eligible,'reason':'synthetic completed controlled inference'}


class CourseAdmissionPolicyTests(unittest.TestCase):
    def test_autonomous_goal_has_no_reference_hold_or_hint_state(self):
        task,deck,assets=fixture()
        with TemporaryDirectory() as temporary:
            host=policy(Path(temporary))
            result=host(task=task,deck=deck,basic_cb=None,assets=assets,purpose='train')
            self.assertEqual(result['status'],'admitted')
            feedback=host.record_completed_construction(task=task,deck=deck,assets=assets,
                basic_cb=None,cycle_id='autonomous-1')
            self.assertFalse(feedback['reference_comparison_applicable'])
            self.assertIsNone(feedback['score']);self.assertIsNone(host.tracker)
            self.assertFalse(feedback['force_optimization'])

    def test_queries_do_not_count_real_failure_events_or_write_state(self):
        task,deck,assets=fixture()
        with TemporaryDirectory() as temporary:
            host=policy(Path(temporary))
            for attempt in ('guard','random-hand','not-run'):
                host.consume_cb_signal(event(task,deck,attempt,eligible=False))
            self.assertEqual(host.value['cb_events'],[])
            host.consume_cb_signal(event(task,deck,'real-1'))
            before=host.path.read_bytes()
            for _ in range(3):
                verdict=host(task=task,deck=deck,basic_cb=None,assets=assets,purpose='train')
                self.assertFalse(verdict['signals']['optimization_requested'])
            self.assertEqual(host.path.read_bytes(),before)
            host.consume_cb_signal(event(task,deck,'real-2'))
            verdict=host(task=task,deck=deck,basic_cb=None,assets=assets,purpose='train')
            self.assertTrue(verdict['signals']['optimization_requested'])
            self.assertIn({'kind':'conditional_cb_optimization_signal','attempt_id':'real-2'},verdict['evidence_refs'])
            host.consume_cb_signal(event(task,deck,'real-2'))
            self.assertEqual(len(host.value['cb_events']),2)

    def test_success_resets_consecutive_failures_and_restored_state_keeps_events(self):
        task,deck,assets=fixture()
        with TemporaryDirectory() as temporary:
            root=Path(temporary);host=policy(root)
            host.consume_cb_signal(event(task,deck,'failure-1'))
            host.consume_cb_signal(event(task,deck,'success',success=True,eligible=False))
            host.consume_cb_signal(event(task,deck,'failure-2'))
            host=policy(root)
            self.assertFalse(host(task=task,deck=deck,basic_cb=None,assets=assets,purpose='train')['signals']['optimization_requested'])
            host.consume_cb_signal(event(task,deck,'failure-3'))
            self.assertTrue(host(task=task,deck=deck,basic_cb=None,assets=assets,purpose='train')['signals']['optimization_requested'])

    def test_completed_review_does_not_consume_new_inference_failures_in_that_cycle(self):
        task,deck,assets=fixture()
        with TemporaryDirectory() as temporary:
            host=policy(Path(temporary))
            for attempt in ('old-1','old-2','new-1','new-2'):
                host.consume_cb_signal(event(task,deck,attempt))
            host.record_completed_construction(task=task,deck=deck,assets=assets,basic_cb=None,cycle_id='review-1')
            host.review_completed(task=task,deck=deck,cycle_id='review-1',through_attempt_id='old-2')
            verdict=host(task=task,deck=deck,basic_cb=None,assets=assets,purpose='train')
            self.assertTrue(verdict['signals']['optimization_requested'])
            self.assertIn({'kind':'conditional_cb_optimization_signal','attempt_id':'new-2'},verdict['evidence_refs'])

    def test_unknown_actual_candidate_score_does_not_count_as_low_score_or_release_hints(self):
        task,deck,assets=fixture()
        with TemporaryDirectory() as temporary:
            host=policy(Path(temporary),historical=True)
            for cycle in ('one','two','three'):
                feedback=host.record_completed_construction(task=task,deck=deck,assets=assets,
                    basic_cb=None,cycle_id=cycle)
                self.assertIsNone(feedback['score']['score']);self.assertIsNone(feedback['hint'])
            self.assertEqual(host.tracker.to_dict()['scopes'],[])
            self.assertEqual(host(task=task,deck=deck,basic_cb=None,assets=assets,purpose='train')['status'],'deferred')

    def test_known_side_only_does_not_grade_unknown_active_functions_but_known_zero_and_partial_scores_remain(self):
        task,main,assets=fixture();deck=DeckParts(main.main,(),(15,))
        assets.rows[15]={'id':15,'type':17,'level':4,'desc':'unit effect','name':'15'}
        mode={'value':'side_only'}
        def context_factory(catalog):
            def contextualize(row,block,actual,rows):
                is_side=row['id'] in actual['side']
                known=(is_side or mode['value']=='known_zero' or
                       mode['value']=='partial' and row['id']==actual['main'][0])
                return replace(block,status='reviewed' if known else 'unknown',
                    feasibility=0. if mode['value']=='known_zero' and not is_side else .9,
                    knowledge={k:'known' if known else 'unknown' for k in
                        ('conditions','costs','limits','resources','conflicts')})
            return contextualize
        with TemporaryDirectory() as temporary:
            root=Path(temporary);host=policy(root,historical=True,contextualize_factory=context_factory)
            for cycle in ('unknown-active-1','unknown-active-2'):
                result=host.record_completed_construction(task=task,deck=deck,assets=assets,
                    basic_cb=None,cycle_id=cycle)
                self.assertIsNone(result['score']['score']);self.assertIsNone(result['hint'])
            self.assertEqual(host.tracker.to_dict()['scopes'],[])
            first=next(iter(host.value['construction_evaluations'].values()))[0]
            audit=json.loads((host.path.parent/(first['evaluation_id']+'.private-audit.json')).read_text(
                encoding='utf-8'))['audit']
            self.assertEqual(audit['raw_score'],0.)
            self.assertEqual(audit['active_priced_context_reviewed_functions'],0)
            side=next(c for c in audit['cards'] if c['zone']=='side')
            self.assertGreater(side['blocks'][0]['context_factor'],0.)
            self.assertEqual(side['blocks'][0]['offered'],0.)
            self.assertTrue(all(c['block_contribution']==0. for c in audit['cards']))
            mode['value']='known_zero'
            zero=host.record_completed_construction(task=task,deck=deck,assets=assets,
                basic_cb=None,cycle_id='known-zero')
            self.assertEqual(zero['score']['score'],0.)
            self.assertEqual(host.tracker.to_dict()['scopes'][0]['evaluations_counted'],1)
            mode['value']='partial'
            partial=host.record_completed_construction(task=task,deck=deck,assets=assets,
                basic_cb=None,cycle_id='partial-known')
            self.assertGreater(partial['score']['score'],0.)
            self.assertEqual(host.tracker.to_dict()['scopes'][0]['evaluations_counted'],2)

    def test_new_independent_low_scores_release_hint_once_and_guards_stay_pure(self):
        task,deck,assets=fixture()
        def context_factory(catalog):
            return lambda row,block,actual,rows: replace(block,feasibility=.5)
        with TemporaryDirectory() as temporary:
            root=Path(temporary);host=policy(root,historical=True,contextualize_factory=context_factory)
            one=host.record_completed_construction(task=task,deck=deck,assets=assets,basic_cb=None,cycle_id='one')
            self.assertIsNone(one['hint'])
            two=host.record_completed_construction(task=task,deck=deck,assets=assets,basic_cb=None,cycle_id='two')
            self.assertIsNotNone(two['hint'])
            state=deepcopy(host.tracker.to_dict())
            duplicate=host.record_completed_construction(task=task,deck=deck,assets=assets,basic_cb=None,cycle_id='two')
            self.assertEqual(duplicate,two)
            for _ in range(3):host(task=task,deck=deck,basic_cb=None,assets=assets,purpose='train')
            self.assertEqual(host.tracker.to_dict(),state)
            restored=policy(root,historical=True,contextualize_factory=context_factory)
            self.assertEqual(restored.tracker.to_dict(),state)
            public=json.dumps(host.public_feedback(task=task,deck=deck))
            for private_field in ('reference_raw','raw_score','profiles','inventory_digest','hint_state'):
                self.assertNotIn(private_field,public)

    def test_context_reviewer_discards_reference_feasibility_and_marks_missing_current_requirements_unknown(self):
        row={'id':1};block=Block('mill','effect-1','unmatched text',feasibility=1.,resource_factor=1.)
        catalog=SimpleNamespace(card=lambda code:SimpleNamespace(effects=()))
        reviewed=ActualCandidateContext(catalog)(row,block,{'main':[1]}, {1:row})
        self.assertEqual(reviewed.status,'unknown');self.assertEqual(reviewed.factor(),0.)
        self.assertEqual(reviewed.knowledge['resources'],'unknown')
        actual_row={'id':1,'type':33,'desc':'①：未知条件才能发动。从自己卡组上面把3张卡送去墓地。'}
        actual=MechanismCatalog(SimpleNamespace(rows={1:actual_row}))
        unresolved=ActualCandidateContext(actual)(actual_row,
            Block('mill','unresolved-mill',actual_row['desc']),{'main':[1]*40},{1:actual_row})
        self.assertEqual(unresolved.knowledge['costs'],'unknown')
        self.assertEqual(unresolved.knowledge['resources'],'unknown')
        self.assertEqual(unresolved.knowledge['conditions'],'unknown')
        self.assertEqual(unresolved.factor(),0.)

    def test_factory_uses_explicit_historical_theme_and_rejects_scope_changes(self):
        with TemporaryDirectory() as temporary:
            root=Path(temporary);write_private(root)
            course=SimpleNamespace(config={'period_id':'2022-07','course_id':'unit',
                'construction_theme_ids':['setcode-181']})
            host=load_course_admission_policy(course,root/'course',private_root=root)
            self.assertEqual(host.manifest['reference_period_id'],'2022-07')
            task,deck,assets=fixture();host.record_completed_construction(task=task,deck=deck,
                assets=assets,basic_cb=None,cycle_id='one')
            with self.assertRaisesRegex(ContractError,'policy changed'):
                CourseAdmissionPolicy(host.path,private_root=root,period_id='2026-10')

    def test_actual_inventory_material_witness_binds_relation_entities_and_unknown_targets_get_no_relation(self):
        starter=('这个卡名的①的效果1回合各能使用1次。\n'
            '①：这张卡召唤·特殊召唤成功的场合才能发动。从卡组把「星河·100」以外的1只「星河」怪兽送去墓地。')
        fuser=('这个卡名的①②的效果1回合各能使用1次。\n'
            '①：这张卡召唤·特殊召唤成功的场合才能发动。从自己卡组上面把3张卡送去墓地。\n'
            '②：这张卡被效果送去墓地的场合才能发动。融合怪兽卡决定的包含墓地的这张卡的融合素材怪兽'
            '从自己的手卡·场上·墓地用喜欢的顺序回到持有者卡组下面，把那1只融合怪兽从额外卡组融合召唤。')
        rows={100:{'id':100,'name':'星河·100','type':33,'race':1,'level':4,'desc':starter},
            101:{'id':101,'name':'星河·101','type':33,'race':64,'level':4,'desc':fuser},
            114:{'id':114,'name':'compatible fusion','type':97,'race':64,'level':4,
                 'desc':'「星河」怪兽＋水族怪兽\n①：未知条件。'},
            115:{'id':115,'name':'incompatible fusion','type':97,'race':8192,'level':4,
                 'desc':'龙族怪兽＋龙族怪兽\n①：未知条件。'}}
        catalog=MechanismCatalog(SimpleNamespace(rows=rows))
        kwargs={'theme':'pearl_grave_fusion','period_id':'2022-07'}
        units=candidate_functional_units(DeckParts((100,101),(114,)),catalog,**kwargs)
        main=[u for u in units if u.category=='main_axis']
        self.assertEqual(len(main),1);self.assertEqual(main[0].relation_status,'proposed')
        self.assertEqual([r.entities for r in main[0].requirements],
            [('main:100',),('main:101',),('extra:114',)])
        self.assertTrue(all(u.relation_status=='unknown' for u in units if u.category!='main_axis'))
        for deck in (DeckParts((100,101),(115,)),DeckParts((100,),(114,),(101,))):
            unknown=candidate_functional_units(deck,catalog,**kwargs)
            self.assertTrue(all(u.relation_status=='unknown' for u in unknown))
        self.assertEqual(candidate_functional_units(DeckParts((100,101),(114,)),catalog,
            theme='pearl_grave_fusion',period_id='2026-10'),())

    def test_factory_restores_same_logical_course_across_targets_and_rejects_changed_private_binding(self):
        task,deck,assets=fixture()
        with TemporaryDirectory() as temporary:
            root=Path(temporary);write_private(root)
            course=SimpleNamespace(config={'period_id':'2022-07','course_id':'stable-course',
                'construction_theme_ids':['setcode-181']})
            original=load_course_admission_policy(course,root/'old-generation',private_root=root)
            original.consume_cb_signal(event(task,deck,'real-1'))
            original.consume_cb_signal(event(task,deck,'real-2'))
            descriptor=original.checkpoint_descriptor()
            restored=load_course_admission_policy(course,root/'new-generation',private_root=root)
            self.assertEqual(restored.path,original.path)
            self.assertEqual(restored.value['cb_events'],original.value['cb_events'])
            restored.validate_checkpoint_descriptor(descriptor)
            self.assertTrue(restored(task=task,deck=deck,basic_cb=None,assets=assets,
                purpose='train')['signals']['optimization_requested'])
            self.assertEqual(set(descriptor),{'kind','logical_course_id','policy_epoch',
                'binding_sha256','state_sha256'})
            from ygo_kito.scenario_course import ScenarioCourse
            def saved_course():
                seam=object.__new__(ScenarioCourse);seam.events=[]
                seam._admission_state_reference=deepcopy(descriptor)
                seam._admission_reference_validated=False;seam.comparison_policy=None
                return seam
            seam=saved_course();seam.bind_admission_policy(restored)
            self.assertEqual(seam._admission_checkpoint_reference(),descriptor)
            saved=restored.path.read_bytes()
            tampered=json.loads(saved);tampered['cb_events']=[]
            restored.path.write_text(json.dumps(tampered),encoding='utf-8')
            with self.assertRaisesRegex(ContractError,'bound in-memory ledger'):
                restored(task=task,deck=deck,basic_cb=None,assets=assets,purpose='train')
            with self.assertRaisesRegex(ContractError,'bound in-memory ledger'):
                saved_course().bind_admission_policy(restored)
            restored.path.write_bytes(saved)
            restored.path.unlink()
            with self.assertRaisesRegex(ContractError,'must be saved'):
                saved_course().bind_admission_policy(restored)
            course._admission_state_reference=descriptor
            with self.assertRaisesRegex(ContractError,'checkpoint private admission state is missing'):
                load_course_admission_policy(course,root/'missing-generation',private_root=root)
            self.assertFalse(restored.path.exists())
            del course._admission_state_reference
            restored.path.write_bytes(saved)
            manifest=json.loads((root/'calibration-manifests.json').read_text(encoding='utf-8'))
            manifest['2022-07']['reference_raw']+=1
            (root/'calibration-manifests.json').write_text(json.dumps(manifest),encoding='utf-8')
            with self.assertRaisesRegex(ContractError,'policy changed'):
                load_course_admission_policy(course,root/'third-generation',private_root=root)
        with TemporaryDirectory() as temporary:
            root=Path(temporary);write_private(root)
            legacy=root/'courses'/'unrecoverable-target-hash'/'admission-state.json'
            legacy.parent.mkdir(parents=True)
            legacy.write_text(json.dumps({'binding':{'period_id':'2022-07',
                'policy_epoch':descriptor['policy_epoch']}}),encoding='utf-8')
            with self.assertRaisesRegex(ContractError,'legacy private admission state'):
                load_course_admission_policy(course,root/'relocated',private_root=root)


if __name__=='__main__':unittest.main()
