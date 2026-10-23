"""Synthetic contract/provenance tests; real Lua evidence lives in integration_tests."""
from dataclasses import replace
import json,struct,unittest
from types import SimpleNamespace
import torch

from ygo_kito.contracts import (ActionSelection,PrivateReveal,RevealedCard,SelectionChoice,
                              CardView,DecisionRequest,LegalAction,Observation,PromptInfo,RunContext,Versions)
from ygo_kito.duel_model import PlayerEncoder,DuelModelConfig
from ygo_kito.native_protocol import Reader,decode_prompt,NativeError
from ygo_kito.private_knowledge import remember_confirmation,forget_slots,public_move,forget_material_associations
from ygo_kito.public_history import consume
from ygo_kito.knowledge_acceptance import public_projection
from ygo_kito.validation import ContractError

def state():
    return SimpleNamespace(knowledge_actions=True,_private_reveals=[[],[]],_private_reveal_counters=[0,0],
                           _private_revealed_slots=[{},{}],_public_materials={},_known_owners={})

def observation():return Observation(1,0,1,'main1',(8000,8000),(5,5),(35,35),())

def request(choices=(),reveals=()):
    return DecisionRequest(RunContext('unit',Versions(*(['synthetic']*6)),None),'duel','window',observation(),
                           (LegalAction('a','select',(choices[0].ref,) if choices else ()),),
                           prompt=PromptInfo(15,1,1),selection_choices=choices,private_reveals=reveals)

class PrivateKnowledgeContracts(unittest.TestCase):
    def test_public_export_whitelists_only_common_typed_history_and_public_result(self):
        trace={'name':'synthetic','responses':['PRIVATE'],'private_reveals':['PRIVATE'],
               'final_observations':[{'public_history':[]},{'public_history':[]}],
               'outcome':None,'result':{'turns':1,'life_points':[8000,8000],'scripts':['PRIVATE']}}
        value=public_projection(trace,{'sha256':'a'*64,'bytes':100})
        self.assertNotIn('PRIVATE',json.dumps(value))
        trace['final_observations'][1]['public_history']=[{'private':'forged'}]
        with self.assertRaises(ContractError):public_projection(trace,{'sha256':'a'*64,'bytes':100})

    def test_confirmations_are_observer_bound_past_multisets_without_positions(self):
        e=state();remember_confirmation(e,1,[(222,0,1,17),(111,0,1,29)])
        self.assertFalse(e._private_reveals[0])
        reveal=e._private_reveals[1][0]
        self.assertEqual([c.card_id for c in reveal.cards],[111,222])
        r=request((SelectionChoice('x',0,'deck','observer',222,knowledge_ref=reveal.ref),),(reveal,))
        self.assertEqual(DecisionRequest.from_dict(json.loads(json.dumps(r.to_dict()))),r)
        serialized=json.dumps(r.to_dict()['private_reveals'])
        for key in ('sequence','native_index','seed','view_key'):
            self.assertNotIn('"'+key+'"',serialized)
        for mutation in (replace(reveal,observer=0),replace(reveal,cards=(RevealedCard(333,0,'deck'),))):
            with self.assertRaises(ContractError):replace(r,private_reveals=(mutation,))
        with self.assertRaises(ContractError):replace(r,private_reveals=())
        with self.assertRaises(ContractError):replace(r,selection_choices=(r.selection_choices[0],replace(r.selection_choices[0],ref='y')))
        with self.assertRaises(ContractError):SelectionChoice('x',0,'deck','hidden',knowledge_ref='forged')
        with self.assertRaises(ContractError):SelectionChoice('x',0,'deck','observer',111,owner=0,knowledge_ref='forged')
        with self.assertRaises(ContractError):RevealedCard.from_dict({'card_id':111,'controller':0,'zone':'deck','sequence':29})

    def test_private_knowledge_reaches_model_but_empty_history_does_not_change_legacy_shape(self):
        reveal=PrivateReveal('k',1,(RevealedCard(111,0,'deck'),))
        r=request(reveals=(reveal,));encoder=PlayerEncoder([111],DuelModelConfig())
        self.assertEqual(len(encoder.encode(r)['tokens']),len(encoder.encode(request())['tokens'])+1)
        self.assertNotIn('private_reveals',request().to_dict())

    def test_shuffle_and_array_moves_invalidate_aliases_but_keep_past_knowledge(self):
        e=state();remember_confirmation(e,1,[(111,0,1,7)])
        before=tuple(e._private_reveals[1]);forget_slots(e,0,1)
        self.assertFalse(e._private_revealed_slots[1]);self.assertEqual(tuple(e._private_reveals[1]),before)
        remember_confirmation(e,1,[(222,0,1,8)])
        public_move(e,333,(0,1,22,8),(0,2,0,8),False)
        self.assertFalse(e._private_revealed_slots[1]);self.assertEqual(len(e._private_reveals[1]),2)
        self.assertEqual(e._private_reveal_counters,[0,2])

    def test_draw_grave_deck_swap_and_reverse_deck_clear_deck_aliases(self):
        for kind,payload in ((90,b'\0\1'+struct.pack('<I',111)),(35,b'\0'),(37,b'')):
            with self.subTest(message=kind):
                e=state();e._public_history=[];e._revealed_hand=[{},{}]
                remember_confirmation(e,1,[(111,0,1,7)])
                consume(e,kind,Reader(payload),{})
                self.assertFalse(e._private_revealed_slots[1])
                self.assertEqual(len(e._private_reveals[1]),1)

    def test_alias_must_match_slot_and_identity_and_is_not_reconstructed_after_shuffle(self):
        e=state();remember_confirmation(e,1,[(111,0,1,7)])
        def decode(code,seq):
            payload=bytes((1,0,1,1,1))+struct.pack('<IBBBB',code,0,1,seq,8)
            return decode_prompt(15,Reader(payload),selection_observation=observation(),selection_seed=(1,1,0),known_slots=e._private_revealed_slots[1])
        self.assertEqual(decode(111,7).selection_choices[0].card_id,111)
        self.assertIsNone(decode(111,8).selection_choices[0].card_id)
        self.assertIsNone(decode(222,7).selection_choices[0].card_id)
        forget_slots(e,0,1)
        self.assertIsNone(decode(111,7).selection_choices[0].card_id)

    def test_bounded_history_evicts_aliases_and_never_uses_other_viewer_counter(self):
        e=state()
        for i in range(33):remember_confirmation(e,1,[(100+i,0,1,i)])
        self.assertEqual(len(e._private_reveals[1]),32)
        self.assertNotIn((0,1,0),e._private_revealed_slots[1])
        remember_confirmation(e,0,[(999,1,1,7)])
        self.assertEqual(e._private_reveals[0][0].ref,'private-reveal-0')
        with self.assertRaises(ContractError):request(reveals=tuple(e._private_reveals[1])+tuple(e._private_reveals[1][:1]))
        with self.assertRaises(NativeError):remember_confirmation(e,0,[(111,1,1,0),(222,1,2,0)])

    def test_public_overlay_identity_provenance_relocation_detach_and_hidden_shuffle(self):
        e=state();e._known_owners={(0,4,0):1,(0,2,0):0}
        public_move(e,111,(0,4,0,1),(0,192,0,0),True)
        # Raw own-hand owner cache is NOT a shared ownership fact.
        public_move(e,222,(0,2,0,8),(0,192,0,1),False)
        public_move(e,333,(0,64,0,8),(0,4,2,1),False)
        self.assertEqual(e._public_materials,{(0,4,2,0):(111,1),(0,4,2,1):(222,None)})
        public_move(e,111,(0,132,2,0),(1,16,0,1),True)
        self.assertEqual(e._public_materials,{(0,4,2,0):(222,None)})
        forget_material_associations(e);self.assertFalse(e._public_materials)

    def test_public_material_under_hidden_host_requires_typed_host_and_count(self):
        host=CardView('h',None,0,'monster','hidden',None,8,material_count=1)
        material=CardView('m',None,0,'overlay','public',111,attached_to='h')
        valid=replace(observation(),cards=(host,material))
        self.assertEqual(valid.cards[0].card_id,None)
        for cards in ((material,),(replace(host,material_count=None),material),(replace(host,material_count=2),material)):
            with self.assertRaises(ContractError):replace(valid,cards=cards)
