"""Stateless inventory admission and checkpoint-owned CB signals; no engine."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from ygo_kito.course_admission_policy import load_course_admission_policy
from ygo_kito.build_contracts import digest
from ygo_kito.validation import ContractError
from tests.test_construction_inventory import fixture


class CourseAdmissionPolicyTests(unittest.TestCase):
    def test_admission_recomputes_current_inventory_without_private_scores_or_files(self):
        value,_,_=fixture();task,assets=value[:2];missing,present=value[4]
        course=SimpleNamespace(events=[],_admission_state_reference={'missing':'retired-ledger'})
        host=load_course_admission_policy(course)
        def verdict(deck):return host(task=task,deck=deck,basic_cb=None,assets=assets,purpose='comparison')
        self.assertEqual(verdict(missing)['status'],'deferred')
        self.assertEqual(verdict(present)['status'],'deferred')
        self.assertIn('quality_policy_unconfigured',verdict(present)['reasons'])
        assets.rows[2]['level']=6
        self.assertEqual(verdict(present)['status'],'deferred')
        self.assertEqual(course.events,[])
        self.assertFalse(hasattr(host,'path'));self.assertFalse(hasattr(host,'checkpoint_descriptor'))

    def test_unknown_selectors_remain_unknown_without_a_numeric_failure_or_review_loop(self):
        value,_,_=fixture();task,assets=value[:2]
        assets.rows[1]['desc']='①：从手卡把1只7星以上的「绯色」怪兽送去墓地才能发动。从自己卡组上面把3张卡送去墓地。'
        host=load_course_admission_policy(SimpleNamespace(events=[]))
        feedback=host.record_completed_construction(task=task,deck=value[4][0],assets=assets,basic_cb=None,cycle_id='cycle')
        self.assertTrue(feedback['inventory_dependencies']['unknown_requirements'])
        self.assertTrue(feedback['force_optimization']);self.assertFalse(feedback['context_review_required'])
        self.assertNotIn('score',feedback)

    def test_only_completed_eligible_cb_events_count_and_restore_with_course(self):
        value,_,_=fixture();task,assets=value[:2];deck=value[4][1]
        course=SimpleNamespace(events=[]);host=load_course_admission_policy(course)
        row=dict(attempt_id='not-run',task_sha256=task.sha256,deck_sha256=digest(deck.to_dict()),
                 success=False,failure_count_eligible=False,reason='budget')
        host.consume_cb_signal(row);self.assertEqual(course.events,[])
        for i in range(2):host.consume_cb_signal(dict(row,attempt_id=str(i),failure_count_eligible=True))
        host.consume_cb_signal(dict(row,attempt_id='1',failure_count_eligible=True))
        self.assertEqual(len(course.events),2)
        restored=load_course_admission_policy(SimpleNamespace(events=deepcopy(course.events)))
        result=restored(task=task,deck=deck,basic_cb=None,assets=assets,purpose='comparison')
        self.assertTrue(result['signals']['optimization_requested'])
        restored.review_completed(task=task,deck=deck,cycle_id='cycle',through_attempt_id='1')
        self.assertIsNone(restored._cb_trigger(task,deck))
        with self.assertRaises(ContractError):host.consume_cb_signal(dict(row,attempt_id='1',success=True))

    def test_review_does_not_consume_failures_produced_during_this_construction(self):
        value,_,_=fixture();task=value[0];deck=value[4][1]
        host=load_course_admission_policy(SimpleNamespace(events=[]))
        for i in range(4):
            host.consume_cb_signal(dict(attempt_id=str(i),task_sha256=task.sha256,deck_sha256=digest(deck.to_dict()),
                success=False,failure_count_eligible=True,reason='completed conditional exploration'))
        host.review_completed(task=task,deck=deck,cycle_id='cycle',through_attempt_id='1')
        self.assertEqual(host._cb_trigger(task,deck),'3')

    def test_cb_failures_from_different_candidates_are_not_combined(self):
        value,_,_=fixture();task=value[0];first,second=value[4]
        host=load_course_admission_policy(SimpleNamespace(events=[]))
        for ident,deck in (('first',first),('second',second)):
            host.consume_cb_signal(dict(attempt_id=ident,task_sha256=task.sha256,
                deck_sha256=digest(deck.to_dict()),success=False,failure_count_eligible=True,reason='completed'))
        self.assertIsNone(host._cb_trigger(task,first))
        self.assertIsNone(host._cb_trigger(task,second))
        host.consume_cb_signal(dict(attempt_id='second-again',task_sha256=task.sha256,
            deck_sha256=digest(second.to_dict()),success=False,failure_count_eligible=True,reason='completed'))
        self.assertEqual(host._cb_trigger(task,second),'second-again')
