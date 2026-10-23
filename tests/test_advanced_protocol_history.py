"""Synthetic codec/privacy tests. Actual card scripts are integration tests."""
import copy
from dataclasses import asdict
import json
import struct
from types import SimpleNamespace
import unittest

import torch

from tests.fixtures import request
from ygo_kito.advanced_protocol import declarable
from ygo_kito.contracts import DecisionRequest, PublicEvent, PublicEventDetails, PublicLocation
from ygo_kito.deck_profile import validate_profile
from ygo_kito.duel_model import DuelModelConfig, PlayerEncoder, FEATURE_VERSION
from ygo_kito.native_protocol import NativeError, Reader, decode_prompt
from ygo_kito.native import NativeNormalEngine
from pathlib import Path
from ygo_kito.public_history import consume
from ygo_kito.validation import ContractError


def wire_card(code,controller=0,zone=1,sequence=1):
    return struct.pack('<IBBB',code,controller,zone,sequence)


def fake_engine():
    return SimpleNamespace(_public_history=[],_known_owners={},_overlay_owners={},_revealed_hand=[{},{}],
                           _confirmation_pause=False,turn=0,turn_player=0,phase='draw',life_points=[8000,8000],outcome=None)


class AdvancedCodecTests(unittest.TestCase):
    def decode(self,kind,data,**kwargs):
        return decode_prompt(kind,Reader(data),allow_advanced=True,**kwargs)

    def test_counter_allocations_are_uint16_vectors_not_card_indices(self):
        data=b'\0'+struct.pack('<HHB',1,2,2)+wire_card(100,zone=4,sequence=0)+struct.pack('<H',2)+wire_card(101,zone=4,sequence=1)+struct.pack('<H',2)
        d=self.decode(22,data)
        self.assertEqual([a.details.quantities for a in d.options],[(0,2),(1,1),(2,0)])
        self.assertEqual([a.response for a in d.options],[b'\0\0\2\0',b'\1\0\1\0',b'\2\0\0\0'])
        for bad in (data[:-1],data+b'\0',data[:3]+struct.pack('<H',5)+data[5:]):
            with self.assertRaises(NativeError):self.decode(22,bad)

    def test_disabled_field_responses_are_distinct_triplets_with_explicit_destinations(self):
        available=(1<<0)|(1<<1)|(1<<16)
        d=self.decode(24,b'\1\2'+struct.pack('<I',0xffffffff^available))
        self.assertEqual(len(d.options),3)
        self.assertEqual(d.options[0].response,b'\1\4\0\1\4\1')
        self.assertEqual([(p.controller,p.zone,p.sequence) for p in d.options[-1].details.destinations],[(1,'monster',1),(0,'monster',0)])
        with self.assertRaises(NativeError):self.decode(24,b'\0\x10'+struct.pack('<I',0))

    def test_modern_multi_place_has_same_triplets_and_zero_count_can_cancel(self):
        allowed=(1<<0)|(1<<1)
        data=b'\0\2'+struct.pack('<I',0xffffffff^allowed)
        choice=self.decode(18,data)
        self.assertEqual(choice.options[0].response,b'\0\4\0\0\4\1')
        cancel=self.decode(18,b'\0\0'+struct.pack('<I',0xffffffff))
        self.assertEqual(len(cancel.options),1)
        self.assertEqual(cancel.options[0].response,b'\0\0\0')
        self.assertTrue(cancel.info.cancelable)

    def test_sorting_hides_original_sequence_and_maps_order_to_native_ranks(self):
        one=b'\0\3'+wire_card(300,sequence=31)+wire_card(100,sequence=30)+wire_card(200,sequence=29)
        two=b'\0\3'+wire_card(200,sequence=2)+wire_card(300,sequence=1)+wire_card(100,sequence=0)
        a,b=self.decode(25,one),self.decode(25,two)
        self.assertEqual(a.search_choices,b.search_choices)
        self.assertTrue(all(c.scope=='ordering' for c in a.search_choices))
        self.assertEqual(a.options[0].response,b'\2\0\1')
        self.assertEqual(b.options[0].response,b'\1\2\0')
        self.assertEqual(a.options[-1].response,b'\xff')
        with self.assertRaises(NativeError):self.decode(25,b'\0\7'+wire_card(100)*7)

    def test_announcements_have_their_real_mask_id_or_index_response(self):
        race=self.decode(140,b'\0\2'+struct.pack('<I',7))
        self.assertEqual([a.value for a in race.options],[3,5,6])
        self.assertEqual([a.response for a in race.options],[3,5,6])
        nums=self.decode(143,b'\0\2'+struct.pack('<II',100,2000))
        self.assertEqual([(a.value,a.response) for a in nums.options],[(100,0),(2000,1)])
        self.assertEqual([a.response for a in self.decode(132,b'\1').options],[1,2,3])
        with self.assertRaises(NativeError):self.decode(141,b'\0\1'+struct.pack('<I',128))
        with self.assertRaises(NativeError):decode_prompt(132,Reader(b'\0'))

    def test_declaration_stack_uses_public_callback_facts_and_rejects_unknown_or_overflow(self):
        normal={'alias':0,'type':17,'setcode':0x3012,'race':2,'attribute':16}
        extra={**normal,'type':0x2000}
        ops=[0x2000,0x40000102,0x40000007]
        self.assertTrue(declarable(normal,100,ops))
        self.assertFalse(declarable(extra,200,ops))
        self.assertFalse(declarable({**normal,'alias':100},101,ops))
        self.assertTrue(declarable(normal,100,[0x1012,0x40000101]))
        d=self.decode(142,b'\0'+bytes([len(ops)])+struct.pack('<III',*ops),catalog={100:normal,200:extra})
        self.assertEqual([(a.value,a.response) for a in d.options],[(100,100)])
        for ops in ([0x40000004],[0x40000333],[0x7fffffff,1,0x40000000]):
            with self.assertRaises(NativeError):declarable(normal,100,ops)

    def test_profile_revision_is_explicit_and_version_bound(self):
        value={'schema_version':2,'adapter_revision':3,'name':'example','decks':[[],[]],'extras':[[],[]],'sides':[[],[]]}
        validate_profile(value)
        validate_profile({**value,'adapter_revision':4})
        for rev in (True,2,5):
            with self.assertRaises(ContractError):validate_profile({**value,'adapter_revision':rev})
        for malformed in ('not-a-profile',[],{},True):
            with self.assertRaises(ContractError):
                NativeNormalEngine(Path('/tmp/missing-native-not-created'),scenario='effect-duel',deck_profile=malformed)


class StructuredPublicHistoryTests(unittest.TestCase):
    def test_private_confirmation_sort_updates_missed_timing_and_hints_have_no_public_entry(self):
        engine=fake_engine()
        for kind,data in ((31,b'\0\0\1'+wire_card(777,1,1,31)),
                          (50,struct.pack('<I',0)+bytes((1,1,31,8))*2+struct.pack('<I',64)),
                          (120,bytes((1,2,4,8))+struct.pack('<I',999)),
                          (2,bytes((3,0))+struct.pack('<I',888))):
            consume(engine,kind,Reader(data),{})
        self.assertEqual(engine._public_history,[])

    def test_revealed_past_survives_shuffle_and_no_hidden_draw_or_hand_sequence_is_recorded(self):
        e=fake_engine()
        consume(e,31,Reader(b'\1\0\1'+wire_card(777,0,2,6)),{})
        consume(e,33,Reader(b'\0\1'+struct.pack('<I',999)),{})
        consume(e,90,Reader(b'\1\1'+struct.pack('<I',888)),{})
        self.assertEqual(e._public_history[0].card_ids,(777,))
        self.assertIsNone(e._public_history[0].details.locations[0].sequence)
        self.assertEqual([ev.card_ids for ev in e._public_history[1:]],[(),()])
        self.assertEqual(e._revealed_hand,[{},{}])
        serialized=json.dumps([asdict(x) for x in e._public_history])
        self.assertNotIn('999',serialized);self.assertNotIn('888',serialized)

    def test_public_move_cost_lp_chain_resolution_and_targets_are_typed(self):
        e=fake_engine()
        consume(e,50,Reader(struct.pack('<I',123)+bytes((0,4,2,1,0,16,0,1))+struct.pack('<I',0x80)),{})
        consume(e,100,Reader(b'\0'+struct.pack('<I',1500)),{})
        consume(e,72,Reader(b'\2'),{})
        consume(e,83,Reader(b'\1'+bytes((1,4,3,1))),{})
        history=e._public_history
        self.assertEqual(history[0].details.reason,0x80)
        self.assertEqual(history[1].details.life_points,(6500,8000))
        self.assertEqual(history[2].details.link,2)
        self.assertEqual(history[3].details.locations[0].sequence,3)
        self.assertEqual(history,[PublicEvent.from_dict(json.loads(json.dumps(asdict(x)))) for x in history])
        for bad in ({'controller':1,'zone':'deck','sequence':5},{'controller':1,'zone':'hand','card_id':999}):
            with self.assertRaises(ContractError):PublicLocation.from_dict(bad)
        with self.assertRaises(ContractError):PublicEventDetails.from_dict({'message':50,'audit_seed':7})

    def test_both_rps_hands_are_only_released_together(self):
        e=fake_engine()
        consume(e,133,Reader(b'\x09'),{})
        self.assertEqual(e._public_history[0].details.values,(1,2))
        with self.assertRaises(NativeError):consume(e,133,Reader(b'\0'),{})

    def test_scripted_private_hints_are_not_public_declaration_echoes(self):
        e=fake_engine()
        for hint in (1,2,3,4,5,6,7,8,9):
            consume(e,2,Reader(bytes((hint,0))+struct.pack('<I',777)),{})
        self.assertEqual(e._public_history,[])
        e._public_declarations={(8,0):777}
        consume(e,2,Reader(b'\x08\0'+struct.pack('<I',777)),{})
        self.assertEqual(e._public_history[0].card_ids,(777,))
        consume(e,2,Reader(b'\x08\0'+struct.pack('<I',888)),{})
        self.assertEqual(len(e._public_history),1)

    def test_public_reveal_flag_is_stripped_from_position_without_hiding_public_identity(self):
        e=fake_engine()
        consume(e,50,Reader(struct.pack('<I',777)+bytes((0,2,9,0,0,8,2,0x88))+struct.pack('<I',64)),{})
        event=e._public_history[0]
        self.assertEqual(event.card_ids,(777,))
        self.assertEqual(event.details.locations[-1].position,8)
        consume(e,50,Reader(struct.pack('<I',777)+bytes((0,4,1,1,0,0xc0,12,0))+struct.pack('<I',0x200008)),{})
        self.assertEqual(e._public_history[-1].details.locations[-1].zone,'overlay')
        self.assertIsNone(e._public_history[-1].details.locations[-1].sequence)

    def test_public_details_and_counter_allocations_affect_player_features(self):
        data=request();data['context']['seed']=None
        data['observation']['public_history']=json.loads(json.dumps([asdict(PublicEvent('public-0','lp',(),PublicEventDetails(100,player=0,amount=1500,life_points=(6500,8000))))]))
        r=DecisionRequest.from_dict(data)
        encoder=PlayerEncoder(sorted({c.card_id for c in r.observation.cards if c.card_id is not None}),DuelModelConfig())
        old=encoder.encode(r)
        data['observation']['public_history'][0]['details']['amount']=1000
        new=encoder.encode(DecisionRequest.from_dict(data))
        self.assertFalse(torch.equal(old['numbers'],new['numbers']))
        self.assertIn('v4',FEATURE_VERSION)

    def test_ordering_cards_preserve_controller_and_differ_from_deck_search_tokens(self):
        data=request();data['context']['seed']=None
        data['prompt']={'message':25,'minimum':1,'maximum':1}
        data['search_choices']=[{'ref':'ordering-0','card_id':100,'owner':0,'scope':'ordering'}]
        data['actions']=[{'action_id':'order','kind':'order','card_refs':['ordering-0']}]
        encoder=PlayerEncoder([1,100],DuelModelConfig())
        own=encoder.encode(DecisionRequest.from_dict(data))
        data['search_choices'][0]['owner']=1
        other=encoder.encode(DecisionRequest.from_dict(data))
        self.assertEqual(own['tokens'][3,2:4].tolist(),[0,0])
        self.assertEqual(other['tokens'][3,2:4].tolist(),[1,1])
        data['prompt']['message']=15
        data['search_choices'][0].update(owner=0,scope='search')
        data['actions'][0]['kind']='select'
        searched=encoder.encode(DecisionRequest.from_dict(data))
        self.assertFalse(torch.equal(own['numbers'][3],searched['numbers'][3]))

    def test_unknown_events_and_malformed_public_locations_fail_closed(self):
        for kind in (21,161,162,163,180,255):
            with self.assertRaises(NativeError):consume(fake_engine(),kind,Reader(b''),{})

