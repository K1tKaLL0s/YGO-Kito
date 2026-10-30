"""Targeted public-DTO/projection fixtures, never live-engine or strength evidence."""
from copy import deepcopy
from types import SimpleNamespace
import json
import struct
import unittest
from unittest.mock import patch
import torch

from tests.fixtures import request as request_payload
from tests.test_duel_runtime_interfaces import construction_fixture
from ygo_kito.basic_cb_inference import infer_basic_cb, proposals
from ygo_kito.build_contracts import BuildTask, DeckParts
from ygo_kito.build_semantics import route_task
from ygo_kito.contracts import DecisionRequest
from ygo_kito.duel_planning import ComboPlan, DuelPlanner, PlanningBudget, _State
from ygo_kito.native_protocol import Reader, decode_prompt
from ygo_kito.route_search import action_intent, discover_goal


def effect(description,quantity=0,restrictions=()):
    return dict(card_id=20,effect_description=description,
        knowledge=dict(activation_boundary='recognized',costs='observed' if quantity else
            'not_observed_in_recognized_activation',restrictions='observed' if restrictions else
            'not_observed_in_recognized_effect'),
        trigger=dict(event='own_main_phase',additional_conditions='none_in_recognized_activation_clause'),
        costs=[dict(kind='send_grave',owner='self',quantity=quantity,from_zones=['hand'],selector='any')]
              if quantity else [],
        operations=[dict(kind='search_or_recover',reason='effect')],restrictions=list(restrictions))


def request(kind='activate',description=321,message=12):
    raw=request_payload();raw['context']['seed']=None;raw['prompt']=dict(message=message)
    raw['observation'].update(cards=[dict(ref='effect',owner=0,controller=0,zone='monster',
        card_id=20,visibility='public')],public_history=[],hand_counts=[0,0])
    raw['actions']=[dict(action_id='effect',kind=kind,card_refs=['effect'],details=dict(description=description))]
    return DecisionRequest.from_dict(raw)


def construction():
    task,deck,_=construction_fixture();raw=task.to_dict()
    raw['pool'].append(44);raw['sizes']['extra']=3
    task=BuildTask.from_dict(raw);deck=DeckParts(deck.main,(42,43,44),())
    text=('\u4ece\u81ea\u5df1\u7684\u624b\u5361\u00b7\u573a\u4e0a\u628a'
          '\u878d\u5408\u602a\u517d\u5361\u51b3\u5b9a\u7684\u878d\u5408\u7d20\u6750'
          '\u602a\u517d\u9001\u53bb\u5893\u5730\uff0c\u5c06\u90a31\u53ea\u878d\u5408'
          '\u602a\u517d\u4ece\u989d\u5916\u5361\u7ec4\u878d\u5408\u53ec\u5524\u3002')
    rows={c:dict(id=c,type=0x1001 if c==1 else 1,level=4,desc='',name=str(c)) for c in task.pool}
    rows[20].update(type=2,level=0,desc=text)
    rows[42].update(type=0x41,level=8)
    rows[43].update(type=0x2001,level=8)
    rows[44].update(type=0x800001,level=4)
    assets=SimpleNamespace(rows=rows,receipt={'resources':{'cards':'a'*64}},validate=lambda *args:None)
    return task,deck,assets


class CbChainRegressionTests(unittest.TestCase):
    def test_specific_effect_confirmation_and_anonymous_yes_are_distinct(self):
        wire=bytes((0,))+struct.pack('<IBBBB',20,0,4,0,0)+struct.pack('<I',321)
        prompt=decode_prompt(12,Reader(wire))
        self.assertEqual((prompt.options[0].kind,prompt.options[0].details.description),('yes',321))
        generic=decode_prompt(13,Reader(bytes((0,))+struct.pack('<I',321)))
        self.assertEqual(generic.options[0].kind,'yes');self.assertEqual(generic.options[0].refs,())
        planner=DuelPlanner()
        old=request('yes')
        self.assertEqual(planner._operation(old,old.actions[0]),'activate')
        anonymous=request('yes',message=13)
        self.assertEqual(planner._operation(anonymous,anonymous.actions[0]),'yes')

    def test_intent_versions_preserve_old_confirmation_and_new_effect_identity(self):
        req=request()
        self.assertEqual(action_intent(req,req.actions[0],schema_version=1),dict(operation='yes',card_ids=[20]))
        self.assertEqual(action_intent(req,req.actions[0]),
                         dict(operation='activate',card_ids=[20],effect_description=321))

    def test_failure_of_one_effect_does_not_block_another_effect_on_same_card(self):
        planner=DuelPlanner(effect_records={20:(effect(321),effect(322))})
        state=_State(((20,'monster',1000),),(),phase='main1')
        failed=planner._failure(planner._project(state,'activate',(20,),effect_description=321))
        self.assertIsNone(planner._project(failed,'activate',(20,),effect_description=321))
        self.assertIsNotNone(planner._project(failed,'activate',(20,),effect_description=322))
        self.assertIsNone(planner._project(failed,'activate',(20,)))

    def test_different_effect_costs_remain_paid_on_failure(self):
        planner=DuelPlanner(effect_records={20:(effect(321,1),effect(322,2))})
        state=_State(((20,'monster',1000),(1,'hand',1000),(2,'hand',1000)),(),phase='main1')
        for description,quantity in ((321,1),(322,2)):
            projection=planner._project(state,'activate',(20,),effect_description=description)
            self.assertEqual(sum(z=='graveyard' for _,z,_ in projection.committed.cards),quantity)
            failed=planner._failure(projection)
            self.assertEqual(failed.cards,projection.committed.cards);self.assertFalse(failed.enabled_search)

    def test_unknown_cost_and_condition_are_not_free_effects_or_root_masks(self):
        record=effect(321);record['knowledge']['costs']='unknown'
        planner=DuelPlanner(effect_records={20:(record,)},budget=PlanningBudget(seconds=1.))
        state=_State(((20,'monster',1000),),(),phase='main1')
        self.assertIsNone(planner._project(state,'activate',(20,),root=True,effect_description=321))
        planner.plans=(ComboPlan('unknown',43,(),(('activate',(20,)),),(321,)),)
        logits,receipt=planner.evaluate(request(),torch.zeros(1))
        self.assertTrue(torch.isfinite(logits).all())
        self.assertEqual(receipt['branches'][0]['effect_projection_status'],'unknown_costs_conditions_or_restrictions')
        record=effect(321);record['trigger']['additional_conditions']='unknown'
        planner=DuelPlanner(effect_records={20:(record,)})
        self.assertIsNone(planner._project(state,'activate',(20,),effect_description=321))
        self.assertIsNotNone(planner._project(state,'activate',(20,),root=True,effect_description=321))

    def test_effect_lock_applies_to_future_projection_while_core_root_stays_authoritative(self):
        lock=dict(kind='cannot_normal_summon',condition='effect_use',duration='turn',whole_turn=False)
        planner=DuelPlanner(effect_records={20:(effect(321,restrictions=(lock,)),)})
        state=_State(((20,'monster',1000),(1,'hand',1000)),(),phase='main1')
        activated=planner._project(state,'activate',(20,),effect_description=321).resolved
        self.assertIsNone(planner._project(activated,'summon',(1,)))
        self.assertIsNotNone(planner._project(activated,'summon',(1,),root=True))

    def test_shared_prefix_expands_once_and_keeps_both_summon_suffixes(self):
        plans=(ComboPlan('synchro',43,(1,2),(('summon',(1,)),('special_summon',(43,)))),
               ComboPlan('xyz',44,(1,2),(('summon',(1,)),('special_summon',(44,)))))
        facts={1:dict(type=0x1001,level=4),2:dict(type=1,level=4),
               43:dict(type=0x2001,level=8),44:dict(type=0x800001,level=4)}
        planner=DuelPlanner(plans=plans,facts=facts)
        state=_State(((1,'hand',1000),(2,'monster',1000),(43,'extra',3000),(44,'extra',2500)),(0,0))
        planner._nodes=0;planner._deadline=float('inf');planner._root_limit=100
        planner._continuation(state,2,0.)
        self.assertEqual(planner._nodes,3)

    def test_distinct_effects_with_distinct_payments_are_not_deduplicated(self):
        plans=tuple(ComboPlan(str(d),43,(),(('activate',(20,)),),(d,)) for d in (321,322))
        planner=DuelPlanner(plans=plans,effect_records={20:(effect(321,1),effect(322,2))})
        state=_State(((20,'monster',1000),(1,'hand',1000),(2,'hand',1000)),(0,0),phase='main1')
        planner._nodes=0;planner._deadline=float('inf');planner._root_limit=100
        planner._continuation(state,1,0.)
        self.assertEqual(planner._nodes,2)

    def test_shared_actual_prefix_rewinds_both_plans_but_counts_one_interruption(self):
        plans=tuple(ComboPlan(str(goal),goal,(),(('activate',(20,)),('special_summon',(goal,))),
                             (321,None)) for goal in (43,44))
        planner=DuelPlanner(plans=plans)
        first=request();planner._observe(first);planner.accepted(first,first.actions[0])
        self.assertEqual(len(planner.memory.pending),2)
        # Cross the JSON boundary: asdict retains internal tuple collections,
        # whereas from_dict deliberately accepts wire arrays only.
        raw=json.loads(json.dumps(first.to_dict()));raw['decision_id']='response'
        raw['observation']['public_history']=[
            dict(event_id='activation',kind='activate',card_ids=[20],details=dict(message=70,player=0,link=1,description=321)),
            dict(event_id='negated',kind='chain',card_ids=[],details=dict(message=75,link=1)),
            dict(event_id='solved',kind='chain',card_ids=[],details=dict(message=73,link=1))]
        planner._observe(DecisionRequest.from_dict(raw))
        self.assertEqual(planner.memory.progress,{'43':0,'44':0})
        self.assertEqual(planner.memory.interruptions,1);self.assertEqual(planner.memory.pending,[])

    def test_explicit_route_and_effect_objectives_are_preserved(self):
        task,deck,assets=construction();raw=task.to_dict()
        raw['goal'].update(route_goal=dict(kind='synchro_summon',card_id=43,
            starting_conditions=dict(player=0,turn=1,requires_opening_hand=[1,2])),
            required_activations=[20],required_chain_resolutions=[20])
        task=BuildTask.from_dict(raw)
        candidates=proposals(task,deck,assets)
        self.assertEqual(len(candidates),1);self.assertEqual(candidates[0].goal,task.goal)

    def test_hand_fusion_and_other_summon_mechanisms_each_get_a_bounded_chance(self):
        task,deck,assets=construction();candidates=proposals(task,deck,assets,limit=3)
        self.assertEqual({c.goal['route_goal']['kind'] for c in candidates},
                         {'fusion_summon','synchro_summon','xyz_summon'})
        fusion=next(c.goal['route_goal'] for c in candidates if c.goal['route_goal']['kind']=='fusion_summon')
        self.assertIn(20,fusion['starting_conditions']['requires_opening_hand'])
        self.assertEqual(fusion['fusion_witness']['required_source_zones'],[2])
        self.assertEqual(fusion['fusion_witness']['allowed_destination_zones'],[16])

    def test_calling_verifier_without_expansion_is_not_completed_inference(self):
        task,deck,assets=construction()
        never=unittest.mock.Mock(side_effect=AssertionError('zero budget must not call verifier'))
        zero=infer_basic_cb(task,deck,assets,verifier=never,seconds=0.,limit=1)
        never.assert_not_called();self.assertEqual(zero['status'],'not_run')
        for count,status in ((0,'not_run'),(1,'bounded_inference_unknown')):
            proof=dict(status='not_found_within_budget',exploration=dict(nodes_expanded=count))
            result=infer_basic_cb(task,deck,assets,verifier=lambda *a,**k:deepcopy(proof),limit=1)
            self.assertTrue(result['attempts']);self.assertEqual(result['status'],status)
            self.assertEqual(result['inference_completed'],bool(count))
        with patch('ygo_kito.basic_cb_inference.proposals',return_value=[]):
            result=infer_basic_cb(task,deck,assets)
        self.assertEqual(result['status'],'bounded_inference_unknown');self.assertTrue(result['inference_completed'])

    def test_initialization_can_exhaust_budget_without_any_action_expansion(self):
        task,deck,assets=construction();task=route_task(proposals(task,deck,assets)[1])
        clock=iter([0.]+[1.]*10)
        with patch('ygo_kito.extra_routes.goal_profile_for',return_value={}), \
             patch('ygo_kito.extra_routes.engine_for_goal') as factory, \
             patch('ygo_kito.route_search.time.monotonic',side_effect=lambda:next(clock)):
            result=discover_goal(task,deck,assets,seconds=.1,attempts=1)
        factory.assert_not_called();self.assertEqual(result['status'],'not_run')
        self.assertEqual(result['exploration']['nodes_expanded'],0)

    def test_an_expanded_synthetic_route_can_truthfully_finish_unknown(self):
        task,deck,assets=construction();task=route_task(proposals(task,deck,assets)[1])
        raw=request_payload();raw['context']['seed']=None;raw['prompt']=dict(message=11)
        raw['observation'].update(cards=[dict(ref=str(c),owner=0,controller=0,zone='hand',
            card_id=c,visibility='observer') for c in (1,2)],public_history=[],hand_counts=[2,0])
        raw['actions']=[dict(action_id='pass',kind='pass',card_refs=[],value=7)]
        req=DecisionRequest.from_dict(raw)
        class SyntheticEngine:
            events=[]
            turn=1
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def next_decision(self):return req if self.turn==1 else None
            def _observation(self,seat):return req.observation
            def submit(self,selection):self.turn=2
        with patch('ygo_kito.extra_routes.goal_profile_for',return_value={}), \
             patch('ygo_kito.extra_routes.engine_for_goal',return_value=SyntheticEngine()):
            result=discover_goal(task,deck,assets,seconds=1.,attempts=1)
        self.assertEqual(result['status'],'not_found_within_budget')
        self.assertEqual(result['exploration']['nodes_expanded'],1)
        self.assertTrue(result['inference_completed'])


if __name__=='__main__':unittest.main()
