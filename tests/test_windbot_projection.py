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
def public_confirmation(ref,cards,player=0):
    return dict(event_id=ref,kind='reveal',card_ids=[c[0] for c in cards],details=dict(message=31,player=player,
        locations=[dict(controller=p,zone=z,**({'sequence':s} if s is not None else {})) for _,p,z,s in cards]))


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

    def test_unregistered_locations_fail_and_hidden_hand_removal_redacts_first(self):
        for wire in (move(3,(1,64,2,8),(1,4,0,1)),
                     move(3,(0,4,0,1),(0,130,0,0))):
            j=ProjectionJournal(0,deck_counts=(40,40))
            with self.assertRaises(WindBotUnsupported):j.consume(wire)
        j=ProjectionJournal(0,deck_counts=(40,40))
        j.consume(move(3,(1,1,0,8),(1,16,0,0)))
        j.consume(move(3,(1,16,0,0),(1,2,0,8)))
        j.consume(move(0,(1,2,0,8),(1,8,0,8)))
        self.assertEqual([m.kind for m in j.messages][-2:],[7,50])
        self.assertTrue(j.messages[-2].fields['redact'])

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
        data['observation']['public_history'].append(public_confirmation('public-hand-current',[(1,1,'hand',None)]))
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

    def test_private_deck_confirm_uses_dto_multiset_and_existing_local_pool(self):
        engine,req=fixture_engine();data=json.loads(json.dumps(req.to_dict()))
        data['private_reveals']=[dict(ref='private-reveal-0',observer=0,message=31,cards=[
            dict(card_id=2,controller=1,zone='deck'),dict(card_id=1,controller=1,zone='deck')])]
        req=DecisionRequest.from_dict(data);engine.pending=req
        engine._transport.consume(bytes((31,0,0,2))+card(2,1,1,35)+card(1,1,1,12))
        frame=transport_frame(engine,req,state_version='private-multiset')
        event=next(m for m in frame.messages if m.kind==31)
        self.assertEqual([(c['card_id'],c['sequence']) for c in event.fields['cards']],[(1,0),(2,1)])
        self.assertEqual(event.fields['knowledge_ref'],'private-reveal-0')
        window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
        self.assertTrue(all(game_message(m,window) for m in frame.messages))
        self.assertEqual(len(engine.lib.queries),1)

    def test_private_confirmation_for_other_seat_retains_no_identity_or_alias(self):
        j=ProjectionJournal(0,deck_counts=(40,40))
        j.consume(bytes((31,1,0,1))+card(987654321,0,1,33))
        self.assertEqual(len(j.messages),1);self.assertNotIn('987654321',repr(j.__dict__))
        self.assertEqual(j.private_counter,0)

    def test_private_confirmation_alias_is_erased_before_blind_draw(self):
        engine,req=fixture_engine();data=json.loads(json.dumps(req.to_dict()))
        data['private_reveals']=[dict(ref='private-reveal-0',observer=0,message=31,cards=[dict(card_id=1,controller=1,zone='deck')])]
        data['observation']['hand_counts'][1]=2;data['observation']['deck_counts'][1]=38
        req=DecisionRequest.from_dict(data);engine.pending=req
        j=engine._transport
        j.consume(bytes((31,0,0,1))+card(1,1,1,12)+draw(1,(888888888,)))
        frame=transport_frame(engine,req,state_version='private-blind-draw')
        confirm=next(i for i,m in enumerate(frame.messages) if m.kind==31)
        draw_index=max(i for i,m in enumerate(frame.messages) if m.kind==90)
        redactions=[m for m in frame.messages[confirm+1:draw_index] if m.kind==7 and m.fields.get('redact')]
        self.assertEqual(len(redactions),39)
        self.assertTrue(all(m.fields['cards'][0]['code']==0 and m.fields['cards'][0]['type']==0 for m in redactions))
        window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
        self.assertTrue(all(game_message(m,window) for m in frame.messages))
        self.assertNotIn('888888888',repr(frame))

    def test_identified_hidden_hand_and_extra_removal_clear_complete_old_state(self):
        for zone in (2,64):
            j=ProjectionJournal(0,deck_counts=(40,40),extra_counts=(0,2 if zone==64 else 0))
            if zone==2:j.consume(draw(1,(111111111,222222222)))
            aliases=j.aliases[(1,zone)];aliases.index(0,known=1)
            if zone==64:
                aliases.index(0,position=1)
                j.consume(bytes((53,))+u32(1)+bytes((1,64,0,1,8)))
            j.consume(move(999999999,(1,zone,0,8),(1,8,0,8)))
            resets=[m for m in j.messages if m.kind==7 and m.fields.get('redact')]
            self.assertEqual(len(resets),2)
            self.assertEqual(j.messages[-1].fields['previous'][2],1)
            self.assertEqual(j.messages[-1].fields['card_id'],0)
            for message in resets:
                record=message.fields['cards'][0]
                self.assertEqual(record['targets'],[]);self.assertEqual(record['overlay'],[])
                self.assertEqual(record['equip'],(0,0,0,0));self.assertEqual(record['attack'],0)
            self.assertNotIn('999999999',repr(j.__dict__))

    def test_extra_shuffle_forgets_bound_anonymous_objects_before_codec(self):
        engine,req=fixture_engine();j=engine._transport
        j.extra_counts[1]=2;j.aliases[(1,64)]=_Aliases(2)
        j.aliases[(1,64)].index(0,lock=True)
        j.consume(bytes((39,1,2))+u32(111111111)+u32(222222222))
        frame=transport_frame(engine,req,state_version='bound-extra-shuffle')
        self.assertFalse(j.aliases[(1,64)].locked)
        reset_indices=[i for i,m in enumerate(frame.messages) if m.kind==7 and m.fields.get('redact')]
        shuffle=next(i for i,m in enumerate(frame.messages) if m.kind==39)
        self.assertTrue(reset_indices and max(reset_indices)<shuffle)
        # Add legal opaque extra placeholders to establish its public count.
        data=json.loads(json.dumps(req.to_dict()))
        data['observation']['cards'] += [dict(ref=f'p1.extra.hidden-{i}',owner=None,controller=1,zone='extra',visibility='hidden',card_id=None,position=8) for i in range(2)]
        current=DecisionRequest.from_dict(data)
        from dataclasses import replace as replacement
        frame=replacement(frame,request_sha256=digest(current.to_dict()))
        window=WindBotWindow(current,frame,observer=0,deadline=20,clock=lambda:1)
        self.assertTrue(all(game_message(m,window) for m in frame.messages))

    def test_private_chain_trigger_rank_is_zero_and_public_type_precedes_callback(self):
        engine,req=fixture_engine();j=engine._transport;j.card_types[1]=17
        wire=bytes((70,))+u32(1)+bytes((1,2,0,8))+bytes((1,2,37))+u32(1234)+bytes((1,))
        j.consume(wire)
        frame=transport_frame(engine,req,state_version='private-chain')
        event=next(m for m in frame.messages if m.kind==70)
        self.assertEqual(event.fields['chain_location'],(1,2,0));self.assertEqual(event.fields['card_type'],17)
        data=json.loads(json.dumps(req.to_dict()))
        data['observation']['public_history'].append(dict(event_id='chain-public',kind='activate',card_ids=[1],
            details={'message':70,'player':1,'link':1,'description':1234}))
        current=DecisionRequest.from_dict(data)
        from dataclasses import replace as replacement
        frame=replacement(frame,request_sha256=digest(current.to_dict()))
        window=WindBotWindow(current,frame,observer=0,deadline=20,clock=lambda:1)
        encoded=game_message(event,window)
        self.assertEqual(encoded[3],7)  # a CODE|TYPE query packet precedes MSG70

    def test_new_grave_handler_uses_real_visible_type_before_chain_callback(self):
        engine,req=fixture_engine();j=engine._transport;j.card_types[1]=2  # printed != current fixture type17
        j.consume(move(1,(1,1,10,8),(1,16,0,1)))
        j.consume(bytes((70,))+u32(1)+bytes((1,16,0,1,1,2,33))+u32(1234)+bytes((1,)))
        data=json.loads(json.dumps(req.to_dict()));data['observation']['deck_counts'][1]-=1
        data['observation']['cards'].append(dict(ref='p1.graveyard.0',owner=1,controller=1,zone='graveyard',visibility='public',card_id=1))
        data['observation']['public_history'].append(dict(event_id='grave-chain',kind='activate',card_ids=[1],details={'message':70,'player':1}))
        req=DecisionRequest.from_dict(data);engine.pending=req;engine._count=lambda p,z:int((p,z)==(1,16))
        frame=transport_frame(engine,req,state_version='dynamic-grave-handler')
        index=next(i for i,m in enumerate(frame.messages) if m.kind==70)
        self.assertEqual(frame.messages[index-1].kind,7)
        self.assertEqual(frame.messages[index-1].fields['cards'][0]['type'],17)
        window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
        self.assertTrue(all(game_message(m,window) for m in frame.messages))
        # A past origin whose current public slot no longer identifies that card
        # cannot borrow printed type to fill the missing dynamic observation.
        engine,req=fixture_engine();engine._transport.card_types[1]=17
        engine._transport.consume(bytes((70,))+u32(1)+bytes((1,16,0,1,1,2,33))+u32(1234)+bytes((1,)))
        with self.assertRaises(WindBotUnsupported):transport_frame(engine,req,state_version='missing-handler')

    def test_hand_shuffle_clears_complete_old_metadata_before_new_ids(self):
        engine,req=fixture_engine();j=engine._transport
        j.aliases[(1,2)].index(0,known=1)
        j.consume(bytes((33,1,1))+u32(987654321))
        frame=transport_frame(engine,req,state_version='known-hand-shuffle')
        index=next(i for i,m in enumerate(frame.messages) if m.kind==33)
        self.assertTrue(frame.messages[index-1].fields['redact'])
        window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
        self.assertTrue(all(game_message(m,window) for m in frame.messages))
        self.assertNotIn('987654321',repr(frame))

    def test_set_shuffle_redacts_whole_objects_without_hidden_destination_mapping(self):
        engine,req=fixture_engine();j=engine._transport
        j.consume(bytes((36,8,2))+bytes((1,8,1,8,1,8,0,8))+bytes((1,8,4,8,1,8,3,8)))
        frame=transport_frame(engine,req,state_version='set-shuffle')
        event=next(m for m in frame.messages if m.kind==36)
        self.assertEqual(event.fields['slots'],[(1,8,0,8),(1,8,1,8)])
        resets=[m for m in frame.messages if m.kind==7 and m.fields.get('redact')]
        self.assertEqual(len(resets),2)
        self.assertTrue(all(m.fields['cards'][0]['type']==0 for m in resets))
        window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
        self.assertTrue(all(game_message(m,window) for m in frame.messages))

    def test_swap_uses_pinned_base_types_and_redacts_old_deck_before_shrinking(self):
        engine,req=fixture_engine();j=engine._transport;j.card_types.update({1:17,2:0x800021})
        j.consume(move(2,(1,1,10,8),(1,16,0,1))+move(1,(1,1,12,8),(1,16,1,1)))
        old_deck=j.deck_counts[1]
        j.consume(bytes((35,1,32,1)))
        data=json.loads(json.dumps(req.to_dict()));data['observation']['deck_counts'][1]=1
        data['observation']['cards'] += [dict(ref=f'p1.graveyard.{i}',owner=1,controller=1,
            zone='graveyard',visibility='public',card_id=1) for i in range(old_deck)]
        data['observation']['cards'].append(dict(ref='p1.extra.hidden-0',owner=None,controller=1,
            zone='extra',visibility='hidden',card_id=None,position=8))
        data['observation']['public_history'].append(dict(event_id='public-old-grave',kind='move',card_ids=[2,1],
            details={'message':50,'locations':[dict(controller=1,zone='graveyard',sequence=0),dict(controller=1,zone='graveyard',sequence=1)]}))
        req=DecisionRequest.from_dict(data);engine.pending=req;engine._count=lambda p,z:old_deck if (p,z)==(1,16) else 0
        frame=transport_frame(engine,req,state_version='public-deck-grave-swap')
        event=next(m for m in frame.messages if m.kind==35)
        self.assertEqual(event.fields['old_grave_types'],[dict(sequence=0,card_id=2,type=0x800021),dict(sequence=1,card_id=1,type=17)])
        self.assertEqual(j.extra_counts[1],1);self.assertEqual(j.deck_counts[1],1)
        window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
        encoded=game_message(event,window)
        self.assertEqual(encoded[3],7)  # base CODE|TYPE refresh precedes swap
        self.assertTrue(all(game_message(m,window) for m in frame.messages))

    def test_all_hint_types_obey_pinned_server_recipient_not_player_field(self):
        for hint in range(1,13):
            for player in (0,1):
                for observer in (0,1):
                    j=ProjectionJournal(observer,deck_counts=(40,40))
                    j.consume(bytes((2,hint,player))+u32(987654321))
                    expected=hint in (10,11) or hint in (1,2,3,5) and observer==player or hint in (4,6,7,8,9) and observer==1-player
                    with self.subTest(hint=hint,player=player,observer=observer):
                        self.assertEqual(len(j.messages),1+int(expected))
                        if expected:self.assertEqual(j.messages[-1].fields['player'],player)
                        else:self.assertNotIn('987654321',repr(j.__dict__))

    def test_chain_before_cost_move_keeps_uninterrupted_last_visible_dynamic_type(self):
        for invalidate in (False,True):
            engine,req=fixture_engine();data=json.loads(json.dumps(req.to_dict()))
            data['observation']['cards'].append(dict(ref='p0.monster.0',owner=0,controller=0,
                zone='monster',visibility='public',card_id=1,position=1))
            first=DecisionRequest.from_dict(data);engine.pending=first
            before=transport_frame(engine,first,state_version='before-cost')
            engine._transport.card_types[1]=2  # never substitute printed type for query's actual17
            if invalidate:engine._transport.consume(bytes((41,))+struct.pack('<H',4))
            engine._transport.consume(bytes((70,))+u32(1)+bytes((0,4,0,1,0,4,0))+u32(1234)+bytes((1,)))
            engine._transport.consume(move(1,(0,4,0,1),(0,16,0,5)))
            data['decision_id']='after-cost';data['observation']['cards']=[c for c in data['observation']['cards'] if c['ref']!='p0.monster.0']
            data['observation']['cards'].append(dict(ref='p0.graveyard.0',owner=0,controller=0,
                zone='graveyard',visibility='public',card_id=1))
            data['observation']['public_history'].append(dict(event_id='public-chain-before-cost',kind='activate',
                card_ids=[1],details={'message':70,'player':0}))
            current=DecisionRequest.from_dict(data);engine.pending=current;engine._count=lambda p,z:int((p,z)==(0,16))
            if invalidate:
                with self.assertRaises(WindBotUnsupported):transport_frame(engine,current,state_version='invalid-history')
                continue
            after=transport_frame(engine,current,state_version='after-cost')
            evidence=after.prompt_facts['last_visible_type'][0]
            self.assertEqual(evidence['type'],17);self.assertEqual(evidence['source_request_sha256'],before.request_sha256)
            self.assertEqual(evidence['source'],'last_legal_visible_query')
            self.assertEqual(next(m.fields['card_type'] for m in after.messages if m.kind==70),17)
            window=WindBotWindow(current,after,observer=0,deadline=20,clock=lambda:1)
            self.assertTrue(all(game_message(m,window) for m in after.messages))

    def test_public_confirmation_history_binds_old_alias_after_hidden_move(self):
        engine,req=fixture_engine();data=json.loads(json.dumps(req.to_dict()))
        data['observation']['hand_counts'][1]=0
        data['observation']['public_history'].append(public_confirmation('old-hand-confirm',[(1,1,'hand',None)]))
        engine._transport.consume(bytes((31,0,0,1))+card(1,1,2,0)+move(987654321,(1,2,0,8),(1,8,0,8)))
        req=DecisionRequest.from_dict(data);engine.pending=req
        frame=transport_frame(engine,req,state_version='old-confirmed-object')
        index=next(i for i,m in enumerate(frame.messages) if m.kind==31)
        event=frame.messages[index]
        self.assertEqual(event.fields['public_ref'],'old-hand-confirm')
        self.assertEqual(frame.prompt_facts['public_confirmations'],{'old-hand-confirm':{'message_index':index}})
        self.assertFalse(any(s.controller==1 and s.location==2 for s in frame.slots))
        window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
        self.assertTrue(all(game_message(m,window) for m in frame.messages))
        self.assertNotIn('987654321',repr(frame))
        with self.assertRaises(ContractError):game_message(event,window)

    def test_public_confirmation_requires_fresh_history_and_unchanged_prefix(self):
        engine,req=fixture_engine()
        engine._transport.consume(bytes((31,0,0,1))+card(1,1,2,0))
        with self.assertRaises(WindBotUnsupported):transport_frame(engine,req,state_version='missing-public-proof')
        for altered in (False,True):
            engine,req=fixture_engine();data=json.loads(json.dumps(req.to_dict()))
            data['observation']['public_history'].append(public_confirmation('one-time-ref',[(1,1,'hand',None)]))
            req=DecisionRequest.from_dict(data);engine.pending=req
            engine._transport.consume(bytes((31,0,0,1))+card(1,1,2,0))
            transport_frame(engine,req,state_version='first-public-proof')
            data['decision_id']='next-public-window'
            if altered:data['observation']['public_history'][0]['event_id']='rewritten-prefix'
            current=DecisionRequest.from_dict(data);engine.pending=current
            engine._transport.consume(bytes((31,0,0,1))+card(1,1,2,0))
            with self.assertRaises(WindBotUnsupported):transport_frame(engine,current,state_version='stale-public-proof')

    def test_equal_public_confirmations_consume_distinct_broadcast_refs(self):
        engine,req=fixture_engine();data=json.loads(json.dumps(req.to_dict()))
        data['observation']['public_history'] += [public_confirmation(name,[(1,1,'hand',None)]) for name in ('same-a','same-b')]
        req=DecisionRequest.from_dict(data);engine.pending=req
        engine._transport.consume((bytes((31,0,0,1))+card(1,1,2,0))*2)
        frame=transport_frame(engine,req,state_version='two-equal-broadcasts')
        refs=[m.fields['public_ref'] for m in frame.messages if m.kind==31]
        self.assertEqual(refs,['same-a','same-b'])
        window=WindBotWindow(req,frame,observer=0,deadline=20,clock=lambda:1)
        self.assertTrue(all(game_message(m,window) for m in frame.messages))


if __name__=='__main__':unittest.main()
