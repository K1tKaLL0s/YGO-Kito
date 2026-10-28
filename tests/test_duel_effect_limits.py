"""Exact FAQ semantics with synthetic effect/code bindings, not real card IDs."""
from dataclasses import replace
import json
import unittest

import torch

from ygo_kito.build_contracts import digest
from ygo_kito.contracts import DecisionRequest
from ygo_kito.duel_effect_limits import EffectLimitBinding,EffectLimitTracker,rule_reference,RULES
from ygo_kito.duel_planning import DuelPlanner,ComboPlan,PlanningBudget,_State
from ygo_kito.validation import ContractError
from tests.test_duel_planning import window,card,event,FACTS

TEXT='engineering fixture: exact description already reviewed for test binding only'
ROWS={**FACTS,20:dict(FACTS[20],desc=TEXT),21:dict(FACTS[21],desc=TEXT)}


def binding(rule='qa17200',**changes):
    values=dict(binding_id='bound',rule_id=rule,subject_key='observer:reviewed-name:effect-1',
        effects=((20,321),(21,337)),card_text_digests=((20,digest(TEXT)),(21,digest(TEXT))),scope_complete=True)
    if RULES[rule]['scope']=='explicit_applied_scope':
        values.update(first_turn=1,last_turn=1,application_event_id='applied')
    values.update(changes)
    return EffectLimitBinding(**values)


def view(history=(),turn=1):
    r=window(history=history)
    return replace(r,observation=replace(r.observation,turn=turn))


def activated(ident,code=20,description=321,link=1):
    return event(ident,'activate',70,(code,),player=0,description=description,link=link)


class EffectLimitTests(unittest.TestCase):
    def test_three_uses_count_both_negation_kinds_and_share_copies_then_reset_per_turn(self):
        for negation in (75,76):
            with self.subTest(negation=negation):
                b=binding();t=EffectLimitTracker((b,))
                history=[activated('first'),event('negated','chain',negation,link=1),event('end','chain',74)]
                t.observe(view(history));self.assertEqual(t.remaining(b),2)
                history += [activated('second-copy',21,337),event('end2','chain',74),activated('third')]
                t.observe(view(history));self.assertEqual(t.remaining(b),0)
                history += [event('turn2','turn',40,player=1,turn=2)]
                t.observe(view(history,2));self.assertEqual(t.remaining(b),3)

    def test_named_effect_use_rulings_and_other_effect_slots_are_not_conflated(self):
        for rule,message in (('qa17377',75),('qa17376',76)):
            with self.subTest(rule=rule):
                b=binding(rule);t=EffectLimitTracker((b,))
                t.observe(view((activated('once'),event('negation','chain',message,link=1))))
                self.assertEqual(t.remaining(b),0)
        b=binding();t=EffectLimitTracker((b,))
        t.observe(view((activated('other-effect',20,322),)))
        self.assertEqual(t.remaining(b),3)

    def test_trap_trick_scope_refunds_only_activation_negation(self):
        b=binding('qa22010')
        application=event('applied','chain',73,link=9)
        for message,remaining in ((75,1),(76,0),(73,0)):
            with self.subTest(message=message):
                t=EffectLimitTracker((b,))
                t.observe(view((application,activated('trap'),event('outcome','chain',message,link=1))))
                self.assertEqual(t.remaining(b),remaining)
        # No guessed applicability before the certified effect-application event.
        t=EffectLimitTracker((b,));t.observe(view((activated('before-scope'),)))
        self.assertIsNone(t.remaining(b))
        self.assertTrue(RULES['qa22010']['not_applied'])

    def test_global_activation_wording_exceptions_do_not_refund_activation_negation(self):
        for rule in ('qa7813-caligula','qa23158-soul-crossing','qa23158-unmei-no-draw'):
            with self.subTest(rule=rule):
                b=binding(rule);t=EffectLimitTracker((b,))
                t.observe(view((event('applied','chain',73,link=9),activated('effect'),event('neg','chain',75,link=1))))
                self.assertEqual(t.remaining(b),0)
        b=binding('qa7813-caligula');t=EffectLimitTracker((b,))
        t.observe(view((activated('before-application'),event('applied','chain',73,link=9))))
        self.assertIsNone(t.remaining(b))  # pre-application scope not decided by this evidence

    def test_scope_expiry_unknown_global_events_and_source_changes_remain_unknown(self):
        b=binding('qa23158-soul-crossing',last_turn=2);t=EffectLimitTracker((b,))
        h=[event('applied','chain',73,link=9),activated('first')]
        t.observe(view(h));self.assertEqual(t.remaining(b),0)
        h += [event('next','turn',40,player=1,turn=2)]
        t.observe(view(h,2));self.assertEqual(t.remaining(b),1)
        h += [activated('unclassified-scope-event',20,999)]
        t.observe(view(h,2));self.assertIsNone(t.remaining(b))
        h += [event('expired','turn',40,player=0,turn=3)]
        t.observe(view(h,3));self.assertIsNone(t.remaining(b))
        with self.assertRaises(ContractError):b.assert_catalog({20:dict(desc='changed'),21:dict(desc=TEXT)})
        with self.assertRaises(ContractError):binding('qa22010',last_turn=2)
        missing=replace(binding(),scope_complete=False);m=EffectLimitTracker((missing,));m.observe(view())
        self.assertIsNone(m.remaining(missing))
        p=DuelPlanner(facts=ROWS,effect_limit_bindings=(missing,));p.evaluate(view(),torch.zeros(3))
        state=_State(((20,'monster',0),),())
        self.assertIsNone(p._project(state,'activate',(20,),effect_description=321))
        self.assertIsNotNone(p._project(state,'activate',(20,),effect_description=321,root=True))

    def test_bound_counter_is_consulted_in_future_projection_and_does_not_mask_real_roots(self):
        b=binding();p=DuelPlanner(facts=ROWS,effect_limit_bindings=(b,))
        p.evaluate(view(),torch.zeros(3))
        state=_State(((20,'monster',0),),())
        for remaining in (2,1,0):
            step=p._project(state,'activate',(20,),effect_description=321)
            self.assertIsNotNone(step)
            state=step.resolved
            self.assertEqual(dict(state.limit_spends)[b.subject_key],3-remaining)
        self.assertIsNone(p._project(state,'activate',(20,),effect_description=321))
        self.assertIsNotNone(p._project(state,'activate',(20,),effect_description=321,root=True))
        # Different effect/no reviewed description has unknown counter identity.
        self.assertIsNotNone(p._project(state,'activate',(20,),effect_description=322))

    def test_failure_counter_and_resource_payment_are_independent(self):
        for rule,expected in (('qa17200',1),('qa22010',0)):
            with self.subTest(rule=rule):
                b=binding(rule);p=DuelPlanner(facts=ROWS,effect_limit_bindings=(b,))
                h=(event('applied','chain',73,link=9),) if rule=='qa22010' else ()
                p.evaluate(view(h),torch.zeros(3))
                before=_State(((20,'monster',0),),())
                attempted=p._project(before,'activate',(20,),effect_description=321)
                failed=p._failure(attempted,interruption='activation_negated')
                self.assertEqual(dict(failed.limit_spends)[b.subject_key],expected)
                self.assertEqual(failed.cards,before.cards)

    def test_reference_does_not_generalize_unverified_named_activation_phrase(self):
        reference=rule_reference()
        self.assertEqual(reference['standard_named_card_activation_limit'],'pending_direct_official_evidence')
        self.assertNotEqual(RULES['qa22010']['scope'],RULES['qa17200']['scope'])
        reference['rules']['qa17200']['limit']=999
        self.assertEqual(RULES['qa17200']['limit'],3)


if __name__=='__main__':unittest.main()
