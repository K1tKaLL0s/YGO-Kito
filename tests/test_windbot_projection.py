"""Pure CPU fixtures for recipient projection; no native library/process loaded."""
from contextlib import contextmanager
from dataclasses import replace
from copy import deepcopy
import ctypes
import json
import struct
import unittest
from unittest.mock import patch

from tests.fixtures import request
from ygo_kito.build_contracts import digest
from ygo_kito.contracts import DecisionRequest
from ygo_kito.native_protocol import Reader
from ygo_kito.validation import ContractError
from ygo_kito.windbot_projection import (ProjectionJournal,WindBotProjectionEngine,WindBotOpponent,
    _ProjectionLibrary,_SCALARS,_FLAGS,_Aliases,transport_frame)
from ygo_kito.windbot_room import WindBotWindow,WindBotUnsupported,game_message


def u32(n):return struct.pack('<I',n)
def card(code=1,p=0,z=4,s=0,extra=None):
    return struct.pack('<IBBB',code,p,z,s)+(b'' if extra is None else bytes((extra,)))
def idle():return bytes((11,0,0,0,0,0,0,0,1,1,0))
def draw(p,codes):return bytes((90,p,len(codes)))+b''.join(u32(c) for c in codes)
def move(code,a,b):return bytes((50,))+u32(code)+bytes(a)+bytes(b)+u32(0)


class ScalarLibrary:
    """Returns the documented fixed scalar layout; records queried addresses."""
    def __init__(self):self.queries=[];self.positions={}
    def query_card(self,handle,p,z,s,flags,buffer,cache):
        self.queries.append((p,z,s,flags,cache))
        position=self.positions.get((p,z,s),1 if z in (4,8) else 8)
        values=dict(code=1,position=p|(z<<8)|(s<<16)|(position<<24),alias=123,type=17,
                    level=9,rank=3,attribute=4,race=8,attack=2700,defense=1800,
                    base_attack=1000,base_defense=900,owner=p,status=1,lscale=2,rscale=7,link=2)
        parts=[]
        for _,name in _SCALARS:
            parts.append(u32(values[name]))
            if name=='link':parts.append(u32(0x81))
        body=u32(8+sum(map(len,parts)))+u32(flags)+b''.join(parts)
        buffer[:len(body)]=body
        return len(body)


def fixture_engine():
    payload=request();payload['context']['seed']=None
    payload['observation']['cards'][0]['ref']='p0.hand.0'
    payload['observation']['cards'][1]['ref']='p1.spell_trap.0'
    payload['prompt']={'message':11}
    payload['actions']=[{'action_id':'choice-0','kind':'pass','card_refs':[],'value':6},
                        {'action_id':'choice-1','kind':'pass','card_refs':[],'value':7}]
    req=DecisionRequest.from_dict(payload)
    engine=object.__new__(WindBotProjectionEngine)
    engine._transport=ProjectionJournal(0,deck_counts=(40,40))
    engine._transport.consume(draw(0,(1,))+draw(1,(987654321,))+idle())
    engine._transport_sent=set();engine.pending=req;engine.handle=None;engine.lib=ScalarLibrary()
    engine._count=lambda p,z:0
    return engine,req


class WindBotProjectionTests(unittest.TestCase):
    def test_enemy_draw_and_hidden_sequence_are_anonymous_local_facts(self):
        journal=ProjectionJournal(0,deck_counts=(40,40))
        journal.consume(draw(1,(111111111,222222222,333333333)))
        journal.consume(move(222222222,(1,2,1,8),(1,8,3,8)))
        values=[m.fields for m in journal.messages]
        self.assertEqual(values[1]['card_ids'],(0,0,0))
        self.assertEqual(values[2]['previous'],(1,2,2,8))
        self.assertEqual(values[2]['card_id'],0)
        self.assertNotIn('222222222',repr(journal.__dict__))
        self.assertEqual(journal.hand_counts,[0,2])

    def test_deck_move_does_not_export_native_deck_index(self):
        j=ProjectionJournal(0,deck_counts=(40,40))
        j.consume(move(999999999,(1,1,33,8),(1,4,2,8)))
        event=j.messages[-1].fields
        self.assertEqual(event['previous'],(1,1,0,8));self.assertEqual(event['card_id'],0)
        self.assertNotIn('999999999',repr(j.__dict__))

    def test_prompt_flags_are_exact_offered_values_not_card_heuristics(self):
        j=ProjectionJournal(0,deck_counts=(40,40))
        wire=bytes((10,0,1))+card()+u32(456)+bytes((1,))+card(2,s=1,extra=1)+b'\x01\x01'
        j.consume(wire)
        self.assertEqual(j.capture,(10,0,{'direct_attack':{'choice-1':True}}))
        chain=bytes((16,0,1,2))+u32(31)+u32(47)+bytes((5,1))+card(extra=1)+u32(999)
        j.consume(chain)
        self.assertEqual(j.capture[2],{'chain_special_count':2,'chain_hints':(31,47),
                                    'chain':{'choice-0':{'flag':5,'forced':True}}})
        j.consume(bytes((11,0,0,0,0,1))+card(z=2)+bytes((1,))+card(z=2)+bytes((0,1,1,0)))
        self.assertEqual(j.capture[2],{'idle_set_modes':{'choice-0':3,'choice-1':4}})

    def test_position_tribute_and_card_declaration_capture(self):
        j=ProjectionJournal(0,deck_counts=(40,40))
        j.consume(bytes((19,0))+u32(321)+b'\x05')
        self.assertEqual(j.capture[2]['position_card_id'],321)
        j.consume(bytes((20,0,0,1,1,1))+card(2,extra=2))
        self.assertEqual(j.capture[2]['tribute_weights'],{'p0.monster.0':2})
        j.consume(bytes((22,0))+struct.pack('<HHB',17,3,1)+card(2)+struct.pack('<H',4))
        self.assertEqual(j.capture[2]['counter_caps'],{'p0.monster.0':4})
        j.consume(bytes((142,0,2))+u32(99)+u32(100))
        self.assertEqual(j.capture[2]['declaration_opcodes'],(99,100))

    def test_unknown_or_truncated_history_fails_permanently(self):
        for wire in (b'\xff',bytes((90,0,2))+u32(1),bytes((31,0,1))+card()):
            j=ProjectionJournal(0,deck_counts=(40,40))
            with self.assertRaises((ContractError,RuntimeError)):j.consume(wire)
            self.assertTrue(j.failed)
            with self.assertRaises(WindBotUnsupported):j.consume(b'')

    def test_unregistered_locations_and_hidden_identified_hand_removal_rejected(self):
        for wire in (move(3,(1,64,2,8),(1,4,0,1)),
                     move(3,(0,4,0,1),(0,130,0,0))):
            j=ProjectionJournal(0,deck_counts=(40,40))
            with self.assertRaises(WindBotUnsupported):j.consume(wire)
        j=ProjectionJournal(0,deck_counts=(40,40))
        j.consume(move(3,(1,16,0,0),(1,2,0,8)))
        with self.assertRaises(WindBotUnsupported):j.consume(move(0,(1,2,0,8),(1,8,0,8)))

    def test_frame_queries_visible_only_and_carries_all_dynamic_scalars(self):
        engine,req=fixture_engine()
        frame=transport_frame(engine,req,state_version='fixture-window')
        self.assertEqual([(p,z,s) for p,z,s,_,_ in engine.lib.queries],[(0,2,0)])
        self.assertEqual(frame.request_sha256,digest(req.to_dict()))
        records=[m.fields for m in frame.messages if m.kind==6 and m.fields['location']==2 and m.fields['player']==0][0]['cards']
        self.assertEqual({k:records[0][k] for k in ('level','rank','type','attribute','race','status','link','link_marker')},
                         dict(level=9,rank=3,type=17,attribute=4,race=8,status=1,link=2,link_marker=0x81))
        self.assertNotIn('987654321',repr(frame))
        self.assertNotIn('_responses',repr(frame));self.assertNotIn('seed',repr(frame.prompt_facts))
        with self.assertRaises(WindBotUnsupported):transport_frame(engine,req,state_version='again')

    def test_actual_journal_frame_to_room_codec_composes(self):
        engine,req=fixture_engine()
        frame=transport_frame(engine,req,state_version='fixture-window')
        window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
        self.assertTrue(all(game_message(message,window) for message in frame.messages))
        self.assertEqual(window.translate(struct.pack('<I',7),request=req,state_version='fixture-window'),req.actions[1])

    def test_event_codecs_composed_with_exact_journal_fields(self):
        engine,req=fixture_engine();j=engine._transport
        events=(bytes((53,))+u32(1)+bytes((0,4,0,1,4))+
                bytes((93,))+bytes((0,8,0,1,0,4,0,1))+
                bytes((96,))+bytes((0,4,0,1,1,4,0,1))+
                bytes((97,))+bytes((0,4,0,1,1,4,0,1))+
                bytes((101,))+struct.pack('<HBBBH',12,0,4,0,3)+
                bytes((102,))+struct.pack('<HBBBH',12,0,4,0,1)+
                bytes((110,))+bytes((0,4,0,1,1,4,0,1)))
        j.consume(events)
        frame=transport_frame(engine,req,state_version='composed')
        window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
        self.assertTrue(all(game_message(message,window) for message in frame.messages))
        self.assertEqual(j.counters[(0,4,0)],{12:2})
        self.assertEqual(j.targets[(0,4,0)],set())

    def test_wrong_request_seed_or_incomplete_journal_never_queries(self):
        for change in ('pending','seed','count'):
            engine,req=fixture_engine()
            if change=='pending':engine.pending=DecisionRequest.from_dict(json.loads(json.dumps(req.to_dict())))
            if change=='seed':
                value=json.loads(json.dumps(req.to_dict()));value['context']['seed']=5
                req=DecisionRequest.from_dict(value);engine.pending=req
            if change=='count':engine._transport.hand_counts[0]=0
            with self.assertRaises(WindBotUnsupported):transport_frame(engine,req,state_version='bad')
            self.assertEqual(engine.lib.queries,[])

    def test_library_proxy_preserves_bound_function_identity_and_buffer(self):
        class Library:
            marker=object()
            def get_message(self,handle,buffer):
                payload=draw(1,(987654321,))
                buffer[:len(payload)]=payload
                return len(payload)
        original=Library();j=ProjectionJournal(0,deck_counts=(40,40));proxy=_ProjectionLibrary(original,j)
        old=original.get_message;buffer=(ctypes.c_uint8*64)()
        length=proxy.get_message(None,buffer)
        self.assertEqual(bytes(buffer[:length]),draw(1,(987654321,)))
        self.assertEqual(original.get_message,old);self.assertIs(proxy.marker,original.marker)
        self.assertNotIn('987654321',repr(j.__dict__))

    def test_opponent_requires_real_runtime_validator_and_frozen_profile(self):
        engine,req=fixture_engine();calls=[]
        profile={'fixture':'not-a-deck'};binding={'profile_sha256':digest(profile)}
        @contextmanager
        def room_factory(opponent):yield None
        opponent=WindBotOpponent(root='.',profile=profile,seat=0,versions=req.context.versions,binding=binding,
                                 runtime_validator=lambda:calls.append(1),room_factory=room_factory)
        self.assertEqual(calls,[1])
        with self.assertRaises(ContractError):opponent.choose(req)
        with self.assertRaises(ContractError):opponent.assert_runtime('.',profile,0)
        opponent.binding['new']='tamper'
        with self.assertRaises(ContractError):opponent.assert_runtime('.',profile,1)
        with self.assertRaises(ContractError):WindBotOpponent(root='.',profile=profile,seat=0,
            versions=req.context.versions,binding=binding,runtime_validator=None,room_factory=room_factory)

    def test_managed_host_factory_real_adapter_path_and_cleanup_fixture_only(self):
        template,req=fixture_engine();calls=[];closed=[];frames=[]
        profile={'fixture':'not-a-deck'}
        class FixtureRoom:
            observer=0;duel_rule=5
            def choose(self,current,frame):
                frames.append(frame)
                return current.actions[0]
        @contextmanager
        def rooms(opponent):
            try:yield FixtureRoom()
            finally:closed.append('room')
        @contextmanager
        def hosts(root,**options):
            engine,request_value=fixture_engine()
            del engine._transport;del engine._transport_sent
            engine.pending=None;engine.window=0;engine.closed=False;engine.modern_actions=True
            engine.player_decks=((1,)*40,(1,)*40);engine.player_extras=((),());engine.context=req.context
            try:yield engine
            finally:closed.append('engine')
        opponent=WindBotOpponent(root='.',profile=profile,seat=0,versions=req.context.versions,
            binding={'profile_sha256':digest(profile)},runtime_validator=lambda:calls.append(1),room_factory=rooms)
        with opponent.managed_engine_factory(hosts,'.',deck_profile=profile) as engine:
            engine._transport.consume(draw(0,(1,))+draw(1,(222222222,))+idle())
            engine.pending=req
            self.assertEqual(opponent.policy.choose(req),req.actions[0])
            self.assertEqual(frames[0].request_sha256,digest(req.to_dict()))
            self.assertNotIn('222222222',repr(frames))
        self.assertEqual(closed,['room','engine'])
        self.assertIsNone(opponent._engine);self.assertIsNone(opponent._room)
        self.assertGreaterEqual(len(calls),3)
        with self.assertRaises(ContractError):opponent.select(req)

    def test_battle_event_journal_to_room_codec_and_dynamic_counters(self):
        engine,req=fixture_engine();j=engine._transport
        a,b=bytes((0,4,0,1)),bytes((1,4,0,1))
        j.consume(bytes((111,))+a+struct.pack('<iiB',2700,1800,0)+b+struct.pack('<iiB',1000,900,1))
        frame=transport_frame(engine,req,state_version='battle')
        window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
        encoded=[game_message(m,window) for m in frame.messages if m.kind==111]
        self.assertEqual(len(encoded),1)

    def test_cpu_sampler_invokes_managed_adapter_fixture_without_update(self):
        # This substitutes a two-window host and room. It checks real sampler
        # wiring, not a real native episode, C# bot, reward or trained ability.
        from ygo_kito.cpu_training import CpuTrainer,CpuTrainingConfig
        from ygo_kito.duel_model import DuelModelConfig
        _,bot_request=fixture_engine();payload=json.loads(json.dumps(bot_request.to_dict()))
        payload['decision_id']='fixture-actor-window';payload['observation']['observer']=1
        payload['observation']['cards']=[]
        actor_request=DecisionRequest.from_dict(payload)
        profile={'fixture':'not-a-deck'};seen=[];closed=[]
        class FixtureRoom:
            observer=0;duel_rule=5
            def choose(self,req,frame):seen.append(frame);return req.actions[0]
        @contextmanager
        def rooms(opponent):
            try:yield FixtureRoom()
            finally:closed.append('room')
        @contextmanager
        def host(root,**options):
            e,_=fixture_engine();del e._transport;del e._transport_sent
            e.pending=None;e.window=0;e.closed=False;e.modern_actions=True
            e.player_decks=((1,)*40,(1,)*40);e.player_extras=((),());e.context=bot_request.context
            e.receipt={'fixture':True};e._selection_seed=None;e.outcome=None;e.events=[]
            e.turn=1;e.life_points=[0,8000];windows=iter((bot_request,actor_request))
            def next_decision():
                value=next(windows,None)
                if e.window==0:e._transport.consume(draw(0,(1,))+draw(1,(444444444,))+idle())
                e.window+=1;e.pending=value
                if value is None:e.outcome={'winner':1,'reason_code':1};e.events=[{'kind':5}]
                return value
            e.next_decision=next_decision;e.submit=lambda selection:None
            e._observation=lambda p:bot_request.observation if p==0 else actor_request.observation
            try:yield e
            finally:closed.append('engine')
        opponent=WindBotOpponent(root='.',profile=profile,seat=0,versions=bot_request.context.versions,
            binding={'profile_sha256':digest(profile),'driver_version':'explicit-room-fixture'},
            runtime_validator=lambda:None,room_factory=rooms)
        trainer=CpuTrainer(CpuTrainingConfig(actor_seat=1,game_seeds=(1,),
            model=DuelModelConfig(width=8,card_width=4,heads=2,feedforward=16)),(1,))
        with patch('ygo_kito.cpu_training.public_card_facts',return_value={}):
            episode=trainer.sample_episode('.',profile,purpose='validation',seed=2,policy_seed=3,
                                           opponent_adapter=opponent,engine_factory=host)
        self.assertEqual(len(seen),1);self.assertEqual(len(episode['steps']),1)
        self.assertEqual(trainer.updates,0);self.assertEqual(trainer.episode_cursor,0)
        self.assertEqual(closed,['room','engine']);self.assertIsNone(opponent._engine)

    def test_frozen_seat_versions_root_and_policy_cannot_drift(self):
        _,req=fixture_engine();profile={'fixture':'not-a-deck'}
        @contextmanager
        def rooms(opponent):yield None
        for mutation in ('seat','versions','root','policy','validator','room_factory','_profile'):
            o=WindBotOpponent(root='.',profile=profile,seat=0,versions=req.context.versions,
                binding={'profile_sha256':digest(profile)},runtime_validator=lambda:None,room_factory=rooms)
            if mutation=='seat':o.seat=1
            elif mutation=='versions':o.versions=replace(o.versions,core='different-core')
            elif mutation=='root':o.root=o.root/'different'
            elif mutation=='policy':o.policy=object()
            elif mutation=='validator':o._runtime_validator=lambda:None
            elif mutation=='room_factory':o._room_factory=lambda:None
            else:o._profile={'changed':True}
            with self.subTest(mutation=mutation),self.assertRaises(ContractError):
                o.assert_runtime(o.root,o.profile,1-o.seat)

    def test_window_local_search_and_opaque_choices_never_reuse_deck_positions(self):
        for opaque in (False,True):
            engine,req=fixture_engine();data=json.loads(json.dumps(req.to_dict()))
            data['prompt']={'message':15,'minimum':1,'maximum':1,'cancelable':True}
            if opaque:data['selection_choices']=[dict(ref='opaque-choice',controller=1,zone='deck',visibility='hidden')]
            else:data['search_choices']=[dict(ref='search-choice',owner=0,card_id=1)]
            ref='opaque-choice' if opaque else 'search-choice'
            data['actions']=[dict(action_id='choose',kind='select',card_refs=[ref],value=1),
                             dict(action_id='cancel',kind='pass',card_refs=[])]
            req=DecisionRequest.from_dict(data);engine.pending=req;engine._transport.capture=(15,0,{})
            frame=transport_frame(engine,req,state_version='temporary')
            slot=next(s for s in frame.slots if s.ref==ref)
            self.assertEqual(slot.sequence,39);self.assertEqual(slot.location,1)
            window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
            self.assertEqual(window.translate(b'\x01\x00',request=req,state_version='temporary'),req.actions[0])
            self.assertEqual(len(engine.lib.queries),1)  # only the real own hand

    def test_public_material_registry_and_query_without_material_native_query(self):
        engine,req=fixture_engine();data=json.loads(json.dumps(req.to_dict()))
        data['observation']['cards'] += [dict(ref='p0.monster.0',owner=0,controller=0,zone='monster',
            visibility='public',card_id=1,position=1,material_count=2),
            dict(ref='p0.monster.0.material.0',owner=None,controller=0,zone='overlay',visibility='public',
                 card_id=2,attached_to='p0.monster.0'),
            dict(ref='p0.monster.0.material.1',owner=None,controller=0,zone='overlay',visibility='public',
                 card_id=1,attached_to='p0.monster.0')]
        req=DecisionRequest.from_dict(data);engine.pending=req
        engine._material_refs={(0,4,0,0):'p0.monster.0.material.0',(0,4,0,1):'p0.monster.0.material.1'}
        frame=transport_frame(engine,req,state_version='materials')
        material=next(s for s in frame.slots if s.ref.endswith('material.0'))
        self.assertEqual((material.location,material.sequence,material.subsequence),(132,0,0))
        record=next(m.fields['cards'][0] for m in frame.messages if m.kind==6 and
                    m.fields['player']==0 and m.fields['location']==4)
        self.assertEqual(record['overlay'],[2,1])
        self.assertTrue(all(z in (2,4) for _,z,_,_,_ in engine.lib.queries))
        window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
        self.assertTrue(all(game_message(m,window) for m in frame.messages))

    def test_extra_overlay_move_alias_and_counter_target_relocation(self):
        targeted=ProjectionJournal(0,deck_counts=(40,40),extra_counts=(0,3))
        targeted.consume(bytes((96,0,4,0,1,1,64,0,8)))
        self.assertEqual(targeted.messages[-1].fields['second'],(1,64,2,8))
        j=ProjectionJournal(0,deck_counts=(40,40),extra_counts=(0,3))
        # The anonymous extra host gets local last-slot 2, independent of native 0.
        j.consume(move(7,(1,4,1,1),(1,192,0,0)))
        self.assertEqual(j.messages[-1].fields['current'],(1,192,2,0))
        j.consume(move(8,(1,64,0,8),(1,4,0,1)))
        self.assertEqual(j.messages[-1].fields['previous'],(1,64,2,8))
        self.assertEqual(j.extra_counts,[0,2])
        j.counters[(0,4,1)]={17:2};j.targets[(1,4,0)]={(0,4,1,1)};j.equips[(0,8,0)]=(0,4,1,1)
        j.consume(move(5,(0,4,1,1),(1,4,3,1)))
        self.assertEqual(j.counters[(1,4,3)],{17:2})
        self.assertEqual(j.targets[(1,4,0)],{(1,4,3,1)})
        self.assertEqual(j.equips[(0,8,0)],(1,4,3,1))

    def test_shuffle_only_retains_published_enemy_identities(self):
        j=ProjectionJournal(0,deck_counts=(40,40),extra_counts=(0,2))
        j.consume(draw(1,(111111111,222222222)))
        j.consume(bytes((33,1,2))+u32(333333333)+u32(444444444))
        self.assertEqual(j.messages[-1].fields['card_ids'],(0,0))
        j.consume(bytes((39,1,2))+u32(555555555)+u32(666666666))
        self.assertEqual(j.messages[-1].fields['card_ids'],(0,0))
        self.assertFalse(any(str(n) in repr(j.__dict__) for n in (111111111,333333333,555555555)))
        j.consume(bytes((32,1)))
        self.assertEqual(j.messages[-1].fields,{'player':1})

    def test_known_enemy_hand_and_extra_use_independent_local_aliases(self):
        engine,req=fixture_engine();data=json.loads(json.dumps(req.to_dict()))
        data['observation']['cards'] += [dict(ref='p1.extra.visible-0',owner=1,controller=1,
            zone='extra',visibility='public',card_id=1,position=1)]
        engine._transport.extra_counts[1]=3;engine._transport.aliases[(1,64)]=_Aliases(3)
        engine._extra_refs={(1,0):'p1.extra.visible-0'};engine.lib.positions[(1,64,0)]=1
        req=DecisionRequest.from_dict(data);engine.pending=req
        frame=transport_frame(engine,req,state_version='known-extra')
        slot=next(s for s in frame.slots if s.ref=='p1.extra.visible-0')
        self.assertEqual(slot.sequence,2)
        self.assertFalse(engine._transport.aliases[(1,64)].locked)
        self.assertIn((1,64,0,_FLAGS,0),engine.lib.queries)
        window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
        self.assertTrue(all(game_message(m,window) for m in frame.messages))
        # A public hand confirmation gets an independent local placeholder too.
        j=ProjectionJournal(0,deck_counts=(40,40));j.consume(draw(1,(11,22,33)))
        j.consume(bytes((31,0,0,1))+card(7,1,2,0))
        self.assertEqual(j.messages[-1].fields['cards'][0]['sequence'],2)
        self.assertEqual(j.messages[-1].fields['cards'][0]['card_id'],7)

    def test_public_hand_confirmation_alias_composes_with_current_legal_slot(self):
        engine,req=fixture_engine();data=json.loads(json.dumps(req.to_dict()))
        data['observation']['hand_counts'][1]=3;data['observation']['deck_counts'][1]=37
        data['observation']['cards'].append(dict(ref='p1.hand.0',owner=1,controller=1,
            zone='hand',visibility='public',card_id=1))
        j=ProjectionJournal(0,deck_counts=(40,40))
        j.consume(draw(0,(1,))+draw(1,(888888888,777777777,666666666)))
        j.consume(bytes((31,0,0,1))+card(1,1,2,0)+idle())
        engine._transport=j;req=DecisionRequest.from_dict(data);engine.pending=req
        frame=transport_frame(engine,req,state_version='public-hand')
        slot=next(s for s in frame.slots if s.ref=='p1.hand.0')
        self.assertEqual(slot.sequence,2)
        window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
        self.assertTrue(all(game_message(m,window) for m in frame.messages))
        self.assertFalse(any(str(n) in repr(frame) for n in (888888888,777777777,666666666)))

    def test_hidden_host_only_retains_complete_previously_public_materials(self):
        engine,req=fixture_engine();data=json.loads(json.dumps(req.to_dict()))
        data['observation']['cards'] += [dict(ref='p1.monster.0',owner=None,controller=1,
            zone='monster',visibility='hidden',card_id=None,position=8,material_count=1),
            dict(ref='p1.monster.0.material.0',owner=None,controller=1,zone='overlay',visibility='public',
                 card_id=2,attached_to='p1.monster.0')]
        req=DecisionRequest.from_dict(data);engine.pending=req
        engine._material_refs={(1,4,0,0):'p1.monster.0.material.0'}
        frame=transport_frame(engine,req,state_version='hidden-host-public-material')
        record=next(m.fields['cards'][0] for m in frame.messages if m.kind==6 and
                    m.fields['player']==1 and m.fields['location']==4)
        self.assertEqual(record,{'sequence':0,'overlay':[2]})
        self.assertEqual(len(engine.lib.queries),1)  # no query to the hidden host/material
        window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
        self.assertTrue(all(game_message(m,window) for m in frame.messages))

    def test_enemy_hand_position_bit_never_unmasks_raw_move_identity(self):
        j=ProjectionJournal(0,deck_counts=(40,40))
        j.consume(move(999999999,(1,1,33,8),(1,2,0,1)))
        self.assertEqual(j.messages[-1].fields['card_id'],0)
        self.assertNotIn('999999999',repr(j.__dict__))

    def test_opponent_deck_to_overlay_identity_is_public_and_codec_accepts(self):
        engine,req=fixture_engine()
        engine._transport.consume(move(2,(1,1,33,8),(1,132,0,0)))
        data=json.loads(json.dumps(req.to_dict()));data['observation']['deck_counts'][1]-=1
        req=DecisionRequest.from_dict(data);engine.pending=req
        frame=transport_frame(engine,req,state_version='public-overlay-move')
        event=next(m for m in frame.messages if m.kind==50)
        self.assertEqual(event.fields['card_id'],2);self.assertEqual(event.fields['previous'][2],0)
        window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
        self.assertTrue(game_message(event,window))

    def test_revealed_alias_assignment_does_not_encode_hidden_hand_order(self):
        outputs=[]
        for rows in (((2,0),(1,2)),((1,0),(2,2))):
            j=ProjectionJournal(0,deck_counts=(40,40));j.consume(draw(1,(9,8,7)))
            j.consume(bytes((31,0,0,2))+b''.join(card(code,1,2,s) for code,s in rows))
            outputs.append(j.messages[-1].fields)
        self.assertEqual(*outputs)


if __name__=='__main__':unittest.main()
