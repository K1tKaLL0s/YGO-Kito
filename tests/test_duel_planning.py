"""Isolated conditional planning examples, not core/effect/strength claims."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch
from torch.distributions import Categorical

from tests.fixtures import request as fixture_request
from ygo_kito.contracts import DecisionRequest
from ygo_kito.cpu_training import CpuTrainer, CpuTrainingConfig
from ygo_kito.duel_model import DuelModelConfig
from ygo_kito.duel_planning import (ComboPlan, DuelPlanner, PlanningBudget, VERSION,
    plans_from_construction, replay_planning_bias, response_catalog, _State)
from ygo_kito.hierarchical_policy import score_requests
from ygo_kito.validation import ContractError


FACTS = {1:{'type':0x1001,'level':4,'attack':1000},2:{'type':1,'level':4,'attack':1000},
         3:{'type':1,'level':4,'attack':1800},9:{'type':0x2001,'level':8,'attack':5000},
         20:{'type':2,'level':0,'attack':0},21:{'type':2,'level':0,'attack':0}}
PLANS = (ComboPlan('long',9,(1,2),(('summon',(1,)),('special_summon',(9,)))),
         ComboPlan('short',3,(3,),(('summon',(3,)),)))

# These tests model explicit, synthetic cost-free search effects. Missing
# catalog semantics in production must stay unknown rather than inherit them.
PROJECTION_EFFECTS={c:(dict(card_id=c,
    knowledge=dict(activation_boundary='recognized',costs='not_observed_in_recognized_activation',
                   restrictions='not_observed_in_recognized_effect'),
    trigger=dict(event='unconditional',additional_conditions='none_in_recognized_activation_clause'),
    costs=[],restrictions=[],operations=[dict(kind='search_or_recover',reason='effect')]),) for c in (1,20,21)}


def card(code, zone, ref=None, controller=0, visibility=None):
    return dict(ref=ref or 'own-'+str(code), owner=controller, controller=controller, zone=zone,
                card_id=code, visibility=visibility or ('observer' if controller==0 else 'public'))


def window(*, fuel=True, history=(), extra_cards=(), actions=None, message=11, decision='window-1'):
    d = fixture_request(); d['context']['seed'] = None
    d['decision_id'] = decision
    d['observation'].update(cards=[card(1,'hand'),card(3,'hand'),card(9,'extra')]+
        ([card(2,'monster')] if fuel else [])+list(extra_cards), public_history=list(history),hand_counts=[2,0])
    d['prompt'] = dict(message=message)
    d['actions'] = actions or [dict(action_id='long',kind='summon',card_refs=['own-1']),
                               dict(action_id='short',kind='summon',card_refs=['own-3']),
                               dict(action_id='pass',kind='pass',card_refs=[],value=7)]
    return DecisionRequest.from_dict(d)


def planner(plans=PLANS, **options):
    return DuelPlanner(plans=plans,facts=FACTS,effect_records=PROJECTION_EFFECTS,
                       budget=PlanningBudget(seconds=1,nodes=180,depth=4,roots=8),**options)


def event(ident, kind, message, codes=(), **details):
    if kind=='activate' and message==70:details.setdefault('description',321)
    return dict(event_id=ident,kind=kind,card_ids=list(codes),details=dict(message=message,**details))


class DuelPlanningTests(unittest.TestCase):
    def test_negated_summon_keeps_both_paid_materials_and_cannot_pay_them_again(self):
        facts=dict(FACTS); facts[10]=dict(FACTS[9],attack=6000)
        plans=(ComboPlan('first',9,(1,2),(('special_summon',(9,)),)),
               ComboPlan('alternative',10,(1,2),(('special_summon',(10,)),)))
        p=DuelPlanner(plans=plans,facts=facts,effect_records=PROJECTION_EFFECTS,responses={20:('negate',)},
                      budget=PlanningBudget(nodes=180,seconds=1,depth=4,roots=8))
        before=_State(((1,'monster',1000),(2,'monster',1000),(9,'extra',5000),(10,'extra',6000)),(0,0))
        attempted=p._project(before,'special_summon',(9,))
        self.assertEqual(attempted.stage,'summon_attempt_after_material_commitment')
        failed=p._failure(attempted)
        self.assertEqual(failed.cards,((1,'graveyard',1000),(2,'graveyard',1000),(9,'graveyard',5000),(10,'extra',6000)))
        self.assertIsNone(p._project(failed,'special_summon',(10,)))
        self.assertFalse(any(e[2]=='successful_summon_material_use' for e in failed.material_events))
        self.assertIsNone(p._project(failed,'activate',(1,)))  # no inferred successful-S material trigger
        self.assertIsNotNone(p._project(failed,'activate',(1,),root=True))  # actual legal effect is preserved
        # Exercise the actual root -> response -> recovery recursion as well:
        # the previous bug restored 1/2 and found a free second summon of 10.
        d=json.loads(json.dumps(window().to_dict()))
        d['observation'].update(cards=[card(1,'monster'),card(2,'monster'),card(9,'extra'),
            card(10,'extra'),card(20,'hand','response',1)],hand_counts=[0,1])
        d['actions']=[dict(action_id='try-first',kind='special_summon',card_refs=['own-9']),
                      dict(action_id='pass',kind='pass',card_refs=[],value=7)]
        _,r=p.evaluate(DecisionRequest.from_dict(d),torch.zeros(2))
        branch=next(b for b in r['branches'] if b['action_index']==0)
        self.assertEqual(branch['committed_materials'],[1,2])
        self.assertAlmostEqual(branch['response_value'],.21)
        self.assertEqual(branch['recovery'],[])

    def test_failed_xyz_materials_go_to_gy_from_material_state_without_success_event(self):
        facts={**FACTS,9:dict(type=0x800001,level=4,attack=5000)}
        p=DuelPlanner(facts=facts)
        state=_State(((1,'monster',1000),(2,'monster',1000),(9,'extra',5000)),())
        attempt=p._project(state,'special_summon',(9,))
        self.assertEqual([c[1] for c in attempt.committed.cards],['overlay','overlay','extra'])
        self.assertTrue(all(e[2]=='successful_summon_material_use' for e in attempt.resolved.material_events))
        failed=p._failure(attempt)
        self.assertEqual([c[1] for c in failed.cards],['graveyard','graveyard','graveyard'])
        self.assertTrue(any(e[2]=='sent_to_gy_from_material_after_failed_summon' for e in failed.material_events))
        self.assertFalse(any(e[2]=='successful_summon_material_use' for e in failed.material_events))

    def test_pre_resolution_failure_does_not_invent_payment_or_resolution_benefits(self):
        p=planner()
        before=_State(((20,'hand',0),(1,'monster',1000),(2,'deck',1000),(9,'extra',5000)),(0,0))
        effect=p._project(before,'activate',(20,))
        self.assertEqual(effect.stage,'effect_before_resolution')
        self.assertEqual(effect.committed.cards,before.cards)
        self.assertEqual(p._failure(effect).cards,before.cards)
        searching=p._project(replace(before,enabled_search=True),'search',(2,))
        self.assertIn((2,'hand',1000),searching.resolved.cards)
        self.assertIn((2,'deck',1000),p._failure(searching).cards)
        # Unknown material timing is not modeled as either a refund or a paid
        # cost. There is no invented recovery state to spend those cards in.
        fusion=DuelPlanner(facts={**FACTS,11:dict(type=0x41,level=8,attack=3000)})
        fusion_state=_State(((1,'monster',1000),(2,'monster',1000),(11,'extra',3000)),())
        projected=fusion._project(fusion_state,'special_summon',(11,))
        self.assertEqual(projected.stage,'material_timing_unknown')
        self.assertIsNone(fusion._failure(projected))

    def test_unknown_retry_counts_defer_to_engine_and_keep_distinct_interruption_messages(self):
        for message in (75,76):
            with self.subTest(message=message):
                plan=ComboPlan('effect',9,(20,),(('activate',(20,)),('search',(1,)),('special_summon',(9,))))
                p=planner((plan,))
                start=window(extra_cards=(card(20,'hand'),),actions=[dict(action_id='effect',kind='activate',
                    card_refs=['own-20'],details=dict(description=321))])
                p.evaluate(start,torch.zeros(1)); p.accepted(start,start.actions[0])
                history=(event('link','activate',70,(20,),player=0,link=1),
                         event('interruption','chain',message,link=1),event('resolved','chain',73,link=1))
                later=window(extra_cards=(card(20,'graveyard'),),history=history,decision='retry',
                    actions=[dict(action_id='engine-offered-again',kind='activate',card_refs=['own-20']),
                             dict(action_id='pass',kind='pass',card_refs=[],value=7)])
                logits,r=p.evaluate(later,torch.zeros(2))
                self.assertEqual(r['interruption_context'][-1]['native_message'],message)
                self.assertEqual(r['interruption_context'][-1]['effect_description'],321)
                self.assertEqual(r['interruption_context'][-1]['retry_legality'],'engine_legal_options')
                self.assertFalse(r['interruption_rules']['use_vs_activation_counts_inferred'])
                self.assertTrue(torch.isfinite(logits).all()); self.assertTrue((logits.softmax(0)>0).all())
                state=_State(((20,'graveyard',0),),(0,))
                failed=p._failure(p._project(state,'activate',(20,),root=True))
                self.assertIsNone(p._project(failed,'activate',(20,)))  # unknown future, not illegal
                self.assertIsNotNone(p._project(failed,'activate',(20,),root=True))  # actual legal root stays available

    def test_visible_fuel_changes_actual_future_branch_and_preferred_root(self):
        full, receipt = planner().evaluate(window(),torch.zeros(3))
        empty, missing = planner().evaluate(window(fuel=False),torch.zeros(3))
        self.assertGreater(full[0],full[1])
        self.assertGreater(empty[1],empty[0])
        self.assertTrue(any(s['operation']=='special_summon' for s in receipt['branches'][0]['continuation']))
        self.assertFalse(any(s['operation']=='special_summon' for b in missing['branches'] for s in b['continuation']))
        self.assertFalse(receipt['starting_conditions']['long']['currently_in_hand'])
        self.assertEqual(receipt['projection_status'],'conditional-approximate-not-core-verified')

    def test_revealed_response_changes_expected_consequences_and_root(self):
        no_response, _ = planner(responses={20:('negate',)}).evaluate(window(),torch.zeros(3))
        public = window(extra_cards=(card(20,'hand','public-response',1),))
        public = replace(public,observation=replace(public.observation,hand_counts=(2,1)))
        response, r = planner(responses={20:('negate',)}).evaluate(public,torch.zeros(3))
        self.assertGreater(no_response[0],no_response[1])
        self.assertGreater(response[1],response[0])
        self.assertEqual(r['belief']['known_revealed_in_hand'],[20])
        self.assertGreater(r['belief']['response_probability'],.6)
        self.assertTrue(any(b['success_value'] != b['response_value'] for b in r['branches']))

    def test_probability_unknown_stays_unknown_and_anonymous_exit_weakens_memory(self):
        p = planner(responses={20:('negate',)})
        seen = event('seen','move',50,(20,),player=1,locations=[dict(controller=1,zone='graveyard'),dict(controller=1,zone='hand')])
        first = window(history=(seen,)); first = replace(first,observation=replace(first.observation,hand_counts=(2,2)))
        _, a = p.evaluate(first,torch.zeros(3))
        departed = event('left','move',50,player=1,locations=[dict(controller=1,zone='hand'),dict(controller=1,zone='spell_trap',position=8)])
        nxt = window(history=(seen,departed),decision='window-2')
        nxt = replace(nxt,observation=replace(nxt.observation,hand_counts=(2,1)))
        _, b = p.evaluate(nxt,torch.zeros(3))
        self.assertEqual(a['belief']['known_revealed_in_hand'],[20])
        self.assertEqual(b['belief']['known_revealed_in_hand'],[])
        self.assertEqual(b['belief']['possibly_still_in_hand'],[20])
        self.assertLess(b['belief']['response_probability'],a['belief']['response_probability'])

    def test_negated_step_replans_from_actual_graveyard_and_keeps_other_branch(self):
        plans = (ComboPlan('spell',9,(20,),(('activate',(20,)),('search',(1,)),('summon',(1,)),('special_summon',(9,)))),PLANS[1])
        p = planner(plans)
        start = window(extra_cards=(card(20,'hand'),),actions=[dict(action_id='spell',kind='activate',card_refs=['own-20'])])
        p.evaluate(start,torch.zeros(1)); p.accepted(start,start.actions[0])
        self.assertEqual(p.memory.goal,9)
        hist = (event('chain-start','activate',70,(20,),player=0,link=1),
                event('negated','chain',75,link=1),event('solved','chain',73,link=1))
        later = window(history=hist,extra_cards=(card(20,'graveyard'),),decision='window-2')
        logits, receipt = p.evaluate(later,torch.zeros(3))
        self.assertEqual(receipt['interruptions'],1)
        self.assertEqual(p.memory.pending,[])
        self.assertIsNone(receipt['goal'])
        self.assertGreater(logits[1],logits[0])
        self.assertFalse(any(s['operation']=='search' for b in receipt['branches'] for s in b['continuation']))

    def test_staged_search_does_not_lose_unresolved_activation_or_incremental_materials(self):
        plans = (ComboPlan('spell',9,(20,),(('activate',(20,)),('search',(1,)),('special_summon',(9,)))),)
        p = planner(plans,own_deck=(1,2,9,20))
        start = window(extra_cards=(card(20,'hand'),),actions=[dict(action_id='spell',kind='activate',card_refs=['own-20'])])
        p.evaluate(start,torch.zeros(1)); p.accepted(start,start.actions[0])
        d = json.loads(json.dumps(start.to_dict())); d['decision_id']='search'; d['prompt']=dict(message=15)
        d['search_choices']=[dict(ref='legal-search',card_id=1,owner=0)]
        d['actions']=[dict(action_id='get',kind='select',card_refs=['legal-search'])]
        search=DecisionRequest.from_dict(d); p.evaluate(search,torch.zeros(1)); p.accepted(search,search.actions[0])
        self.assertEqual([x['cursor'] for x in p.memory.pending],[0,1])
        pick = window(message=26,actions=[dict(action_id='add',kind='select',card_refs=['own-2'],details=dict(operation='add'))],decision='pick')
        p.evaluate(pick,torch.zeros(1)); p.accepted(pick,pick.actions[0])
        again = replace(pick,decision_id='pick-again')
        _, r = p.evaluate(again,torch.zeros(1))
        self.assertEqual(r['goal'],9); self.assertEqual(r['selected_materials'],[2])
        remove = replace(again,actions=(replace(again.actions[0],details=replace(again.actions[0].details,operation='remove')),))
        p.accepted(remove,remove.actions[0]); self.assertEqual(p.memory.selected,[])

    def test_all_roots_keep_mass_under_node_budget_and_receipt_is_replayable(self):
        req = window(); p = DuelPlanner(plans=PLANS,facts=FACTS,budget=PlanningBudget(nodes=4,roots=3,seconds=1))
        logits, receipt = p.evaluate(req,torch.zeros(3))
        self.assertLessEqual(receipt['nodes'],4); self.assertGreaterEqual(receipt['root_count'],2)
        self.assertTrue(torch.isfinite(logits).all()); self.assertTrue((logits.softmax(0)>0).all())
        replay = replay_planning_bias(torch.zeros(1,3),[dict(request=req,planning=receipt)])
        self.assertTrue(torch.equal(replay[0],logits))
        bad = deepcopy(receipt); bad['request_sha256']='wrong'
        with self.assertRaises(ContractError): replay_planning_bias(torch.zeros(1,3),[dict(request=req,planning=bad)])

    def test_compiler_uses_cb_from_combined_construction_and_strips_private_audit(self):
        goal = dict(kind='synchro_summon',card_id=9,starting_conditions=dict(requires_opening_hand=[1,2]))
        evidence = dict(exploration=dict(discovered_intents=[dict(operation='summon',card_ids=[1]),
            dict(operation='special_summon',card_ids=[9])]),private_selection_key_audit_only='secret',
            final_observation=dict(opponent_hand=[999999]),seed=777)
        validation = dict(native_route=dict(route_evidence=evidence))
        proof = dict(best=dict(validation=dict(attempts=[dict(engine_validation=validation)])))
        plans = plans_from_construction(SimpleNamespace(goal=dict(route_goal=goal),pool=(1,2,9)),proof)
        self.assertEqual(len(plans),1); self.assertEqual(plans[0].steps,PLANS[0].steps)
        self.assertNotIn('999999',repr(plans)); self.assertNotIn('secret',repr(plans)); self.assertNotIn('777',repr(plans))

    def test_catalog_proposes_possible_classes_without_archetype_dispatch(self):
        self.assertEqual(response_catalog({20:dict(desc='可以使发动无效'),21:dict(desc='destroy a card')}),
                         {20:('negate',),21:('remove',)})

    def test_legal_graveyard_activation_can_enter_a_cb_without_the_original_hand(self):
        route=ComboPlan('grave',9,(20,),(('activate',(20,)),('search',(2,)),('summon',(2,)),('special_summon',(9,))))
        d=json.loads(json.dumps(window().to_dict()))
        d['observation']['cards']=[card(1,'monster'),card(9,'extra'),card(20,'graveyard')]
        d['actions']=[dict(action_id='grave-effect',kind='activate',card_refs=['own-20']),
                      dict(action_id='pass',kind='pass',card_refs=[],value=7)]
        req=DecisionRequest.from_dict(d)
        scores,r=planner((route,),own_deck=(1,2,9,20)).evaluate(req,torch.zeros(2))
        self.assertFalse(r['starting_conditions']['grave']['currently_in_hand'])
        self.assertGreater(scores[0],scores[1])
        self.assertEqual([s['operation'] for s in r['branches'][0]['continuation']],['search','summon','special_summon'])

    def test_retained_materials_affect_the_next_incremental_choice(self):
        p=planner(); p.evaluate(window(),torch.zeros(3)); p.memory.goal=9
        p.memory.selected=[2]  # one non-tuner was already committed
        d=json.loads(json.dumps(window().to_dict()));d['decision_id']='materials';d['prompt']=dict(message=26)
        d['actions']=[dict(action_id='tuner',kind='select',card_refs=['own-1'],details=dict(operation='add')),
                      dict(action_id='other-nontuner',kind='select',card_refs=['own-3'],details=dict(operation='add'))]
        logits,r=p.evaluate(DecisionRequest.from_dict(d),torch.zeros(2))
        self.assertEqual(r['selected_materials'],[2])
        self.assertGreater(logits[0],logits[1])

    def test_public_battle_stats_change_attack_and_hidden_stats_stay_hypotheses(self):
        def battle(attack,hidden=False):
            d=json.loads(json.dumps(window().to_dict()));d['prompt']=dict(message=10)
            d['observation']['cards']=[dict(card(1,'monster'),attack=3000),
                dict(card(None if hidden else 30,'monster','target',1,'hidden' if hidden else 'public'),
                     attack=None if hidden else attack,position=8 if hidden else 1)]
            d['actions']=[dict(action_id='attack',kind='attack',card_refs=['own-1','target']),
                          dict(action_id='pass',kind='pass',card_refs=[],value=3)]
            return planner(()).evaluate(DecisionRequest.from_dict(d),torch.zeros(2))
        weak,_=battle(500);strong,_=battle(4000);_,hidden=battle(None,True)
        self.assertGreater(weak[0],weak[1]);self.assertLess(strong[0],strong[1])
        self.assertEqual(len(hidden['branches'][0]['combat']),3)
        self.assertTrue(all(c['status']=='unknown-stat-prior' for c in hidden['branches'][0]['combat']))

    def test_seed_and_cross_player_planner_reuse_are_rejected(self):
        p=planner();req=window()
        with self.assertRaisesRegex(ContractError,'seeds'):
            p.evaluate(replace(req,context=replace(req.context,seed=7)),torch.zeros(3))
        p.evaluate(req,torch.zeros(3))
        with self.assertRaisesRegex(ContractError,'perspectives'):
            other=replace(req,observation=replace(req.observation,observer=1,cards=()),actions=(req.actions[-1],))
            p.evaluate(other,torch.zeros(1))

    def test_sampler_uses_planning_before_sample_and_replays_nonzero_probability(self):
        cfg=CpuTrainingConfig(model=DuelModelConfig(width=8,card_width=4,heads=2,feedforward=16),game_seeds=(100,),batch_size=1)
        trainer=CpuTrainer(cfg,list(FACTS))
        req=window(); submitted=[]
        class Engine:
            def __enter__(self): self.turn=1; self.outcome=None; self.events=[]; self.count=0; return self
            def __exit__(self,*args): return False
            def next_decision(self):
                self.count+=1
                if self.count==1:return req
                self.outcome=dict(winner=0);self.events=[dict(kind=5)];return None
            def submit(self, selection): submitted.append(selection.action_id)
        profile=dict(decks=[[1,2,3],[999999999]],extras=[[9],[]])
        with patch('ygo_kito.cpu_training.public_card_facts',return_value=FACTS):
            ep=trainer.sample_episode(Path('.'),profile,engine_factory=lambda *a,**kw:Engine(),combo_plans=PLANS,
                planning_budget=PlanningBudget(nodes=180,seconds=1))
        step=ep['steps'][0]
        self.assertEqual(ep['summary']['decision_policy'],VERSION)
        self.assertEqual(ep['summary']['combo_plan_count'],2)
        self.assertEqual(len(submitted),1); self.assertTrue(any(x!=0 for x in step['planning']['bias']))
        self.assertEqual(step['planning']['belief']['known_revealed_in_hand'],[])
        self.assertFalse(any(999999999 in s['card_ids'] for b in step['planning']['branches'] for s in b['continuation']))
        second=CpuTrainer(cfg,list(FACTS))
        other_profile=dict(decks=[[1,2,3],[888888888]],extras=[[9],[]])
        with patch('ygo_kito.cpu_training.public_card_facts',return_value=FACTS):
            other=second.sample_episode(Path('.'),other_profile,engine_factory=lambda *a,**kw:Engine(),combo_plans=PLANS,
                planning_budget=PlanningBudget(nodes=180,seconds=1))
        self.assertEqual(step['planning'],other['steps'][0]['planning'])
        self.assertEqual(step['action_index'],other['steps'][0]['action_index'])
        with torch.no_grad(): raw,_=score_requests(trainer.model,trainer.encoder,[req])
        planned=replay_planning_bias(raw,[step])
        index=torch.tensor([step['action_index']])
        self.assertAlmostEqual(step['old_log_prob'],float(Categorical(logits=planned).log_prob(index)[0]),places=6)
        self.assertNotAlmostEqual(step['old_log_prob'],float(Categorical(logits=raw).log_prob(index)[0]),places=4)
        trainer.update(ep)  # bounded fake-engine gradient check, no formal course
        self.assertEqual(trainer.updates,1)


if __name__=='__main__': unittest.main()
