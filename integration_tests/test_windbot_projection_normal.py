"""Explicit ordinary native positive check; excluded from the CPU-only suite.

Uses the repository's existing 40-card normal engineering opponent listing.
No C# process, training, fault injection or private response inspection occurs.
"""
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import time
import unittest

from ygo_kito.build_contracts import digest
from ygo_kito.contracts import ActionSelection
from ygo_kito.normal_duel import choose_normal_action
from ygo_kito.windbot_projection import WindBotProjectionEngine
from ygo_kito.windbot_room import WindBotWindow,game_message

ROOT=Path(__file__).resolve().parents[1]


def implementation_receipt():
    from ygo_kito.implementation_identity import source_tree_snapshot
    tree=source_tree_snapshot(ROOT/'src/ygo_kito')
    return {'implementation_sha256':{name:tree[name] for name in
        ('windbot_projection.py','windbot_room.py','native.py','native_response_guard.py')},
        'python_source_tree_sha256':digest(tree),'python_source_tree':tree}


class WindBotProjectionNormalTests(unittest.TestCase):
    def test_existing_public_extra_confirmation_survives_immediate_shuffle(self):
        from ygo_kito.protocol_cases import EngineeringDriver
        case=json.loads((ROOT/'configs/protocol-history-engineering-v3.json').read_text())['cases']['confirm-extra']
        attempted_at=datetime.now(timezone.utc);started=time.monotonic()
        receipt={'schema_version':1,'kind':'existing-public-confirmation-history-host-positive-check',
                 'case':'confirm-extra','attempted_at_utc':attempted_at.isoformat(),'profile_sha256':digest(case['profile']),
                 'csharp_windbot_executed':False,'trained':False,'natural_terminal':False,
                 'historical_qualified':False,'strength_qualified':False}
        receipt.update(implementation_receipt())
        frames=decisions=0;messages=Counter();proofs=0;shuffled=False
        try:
            with WindBotProjectionEngine(ROOT/'.cache',observer=0,scenario='effect-duel',
                deck_profile=case['profile'],seed=case['seed_audit_only']) as engine:
                receipt['resources']=engine.receipt;driver=EngineeringDriver(case,engine._rows,'first');req=engine.next_decision()
                for _ in range(300):
                    self.assertIsNotNone(req);self.assertLess(time.monotonic()-started,30)
                    if req.observation.observer==0:
                        frame=engine.transport_frame(req,state_version=f'public-confirm-extra-{frames}')
                        window=WindBotWindow(req,frame,observer=0,deadline=time.monotonic()+10)
                        for message in frame.messages:
                            game_message(message,window);messages[message.kind]+=1
                            proofs+=int(message.kind==31 and message.fields.get('public_ref') is not None)
                        frames+=1
                        if proofs>=2 and messages[39]>=2:
                            self.assertFalse(any(c.card_id is not None for c in req.observation.cards
                                                 if c.controller==1 and c.zone=='extra'))
                            self.assertEqual(len(frame.prompt_facts.get('public_confirmations',{})),2)
                            shuffled=True;break
                    action=driver.choose(req)
                    engine.submit(ActionSelection(req.context.run_id,req.duel_id,req.decision_id,action.action_id))
                    decisions+=1;req=engine.next_decision()
                else:self.fail('bounded existing public confirmation mechanism did not finish')
                self.assertTrue(shuffled)
                receipt.update(status='passed',public_confirmation_history_refs=proofs,
                               current_opponent_extra_identity_hidden=True,immediate_shuffles_encoded=True,
                               original_submit_guard_path=True)
        except Exception as error:
            receipt.update(status='failed_or_unsupported',error_type=type(error).__name__,error=str(error));raise
        finally:
            receipt.update(decisions=decisions,projected_frames=frames,projected_message_counts=dict(messages),
                           elapsed_seconds=round(time.monotonic()-started,3))
            directory=ROOT/'.cache/windbot-projection-normal';directory.mkdir(exist_ok=True)
            filename='public-confirm-extra-attempt-'+attempted_at.strftime('%Y%m%dT%H%M%S%fZ')+'.json'
            (directory/filename).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')

    def test_existing_private_deck_confirmation_and_selection_mechanisms(self):
        from ygo_kito.knowledge_cases import read_case
        from ygo_kito.protocol_cases import EngineeringDriver
        for name in ('crescent-private','rescue-confirmed'):
            with self.subTest(case=name):self._private_case(name,read_case(name),EngineeringDriver)

    def _private_case(self,name,case,driver_type):
        attempted_at=datetime.now(timezone.utc);started=time.monotonic()
        receipt={'schema_version':1,'kind':'existing-private-knowledge-host-projection-positive-check',
                 'case':name,'attempted_at_utc':attempted_at.isoformat(),'profile_sha256':digest(case['profile']),
                 'csharp_windbot_executed':False,'trained':False,'natural_terminal':False,
                 'historical_qualified':False,'strength_qualified':False}
        receipt.update(implementation_receipt())
        frames=decisions=0;messages=Counter();prompts=Counter();confirmed=False;chosen=False;post=False
        try:
            with WindBotProjectionEngine(ROOT/'.cache',observer=1,scenario='effect-duel',
                deck_profile=case['profile'],seed=case['seed_audit_only']) as engine:
                receipt['resources']=engine.receipt;driver=driver_type(case,engine._rows,'first');req=engine.next_decision()
                for _ in range(300):
                    self.assertIsNotNone(req);self.assertLess(time.monotonic()-started,30)
                    if req.observation.observer==1:
                        frame=engine.transport_frame(req,state_version=f'{name}-{frames}')
                        window=WindBotWindow(req,frame,observer=1,deadline=time.monotonic()+10)
                        for message in frame.messages:
                            game_message(message,window);messages[message.kind]+=1
                            confirmed|=message.kind==31 and message.fields.get('knowledge_ref') is not None
                        prompts[req.prompt.message]+=1;frames+=1
                        if chosen:post=True;break
                    action=driver.choose(req)
                    if req.observation.observer==1 and req.prompt.message==15 and req.private_reveals:
                        self.assertTrue(confirmed)
                        if name=='crescent-private':self.assertTrue(all(c.card_id is None for c in req.selection_choices))
                        else:self.assertTrue(all(c.card_id is not None and c.knowledge_ref for c in req.selection_choices))
                        chosen=True
                    engine.submit(ActionSelection(req.context.run_id,req.duel_id,req.decision_id,action.action_id))
                    decisions+=1;req=engine.next_decision()
                else:self.fail('bounded existing private mechanism did not complete')
                self.assertTrue(confirmed and chosen and post)
                receipt.update(status='passed',private_confirmation_projected=True,legal_selection_submitted=True,
                               later_seat_request_encoded=True,original_submit_guard_path=True,
                               complete_redactions=messages[7])
        except Exception as error:
            receipt.update(status='failed_or_unsupported',error_type=type(error).__name__,error=str(error));raise
        finally:
            receipt.update(decisions=decisions,projected_frames=frames,prompt_counts=dict(prompts),
                           projected_message_counts=dict(messages),elapsed_seconds=round(time.monotonic()-started,3))
            directory=ROOT/'.cache/windbot-projection-normal';directory.mkdir(exist_ok=True)
            filename='private-'+name+'-attempt-'+attempted_at.strftime('%Y%m%dT%H%M%S%fZ')+'.json'
            (directory/filename).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')

    def test_existing_rescue_cat_search_and_xyz_material_projection(self):
        from ygo_kito.extra_routes import RouteDriver,completed_special_summon
        raw=json.loads((ROOT/'configs/build-xyz-engineering-v2.json').read_text())
        profile=json.loads((ROOT/'configs/extra-material-engineering-v2.json').read_text())
        profile['adapter_revision']=3;profile['extras'][0]=[78156759]
        attempted_at=datetime.now(timezone.utc);started=time.monotonic()
        receipt={'schema_version':1,'kind':'existing-search-xyz-host-projection-positive-check',
                 'attempted_at_utc':attempted_at.isoformat(),'profile_sha256':digest(profile),
                 'csharp_windbot_executed':False,'trained':False,'natural_terminal':False,
                 'historical_qualified':False,'strength_qualified':False}
        receipt.update(implementation_receipt())
        frames=decisions=0;messages=Counter();prompts=Counter();virtual=False;overlays=False;last_visible_types=0
        try:
            with WindBotProjectionEngine(ROOT/'.cache',observer=0,scenario='effect-duel',deck_profile=profile,seed=1) as engine:
                receipt['resources']=engine.receipt;driver=RouteDriver(raw['goal']['route']);req=engine.next_decision()
                for _ in range(100):
                    self.assertIsNotNone(req);self.assertLess(time.monotonic()-started,30)
                    if req.observation.observer==0:
                        frame=engine.transport_frame(req,state_version=f'existing-xyz-{frames}')
                        last_visible_types+=len(frame.prompt_facts.get('last_visible_type',()))
                        window=WindBotWindow(req,frame,observer=0,deadline=time.monotonic()+10)
                        for message in frame.messages:
                            game_message(message,window);messages[message.kind]+=1
                            if message.kind==6:
                                overlays |= any(bool(c.get('overlay')) for c in message.fields['cards'])
                        if req.search_choices:
                            refs={c.ref for c in req.search_choices}
                            self.assertTrue(all(s.sequence>=req.observation.deck_counts[s.controller] for s in frame.slots if s.ref in refs))
                            virtual=True
                        prompts[req.prompt.message]+=1;frames+=1
                    own=engine._observation(0)
                    if completed_special_summon(engine.events,own,0,78156759):break
                    action=driver.choose(req)
                    engine.submit(ActionSelection(req.context.run_id,req.duel_id,req.decision_id,action.action_id))
                    decisions+=1;req=engine.next_decision()
                else:self.fail('bounded existing XYZ route did not complete')
                self.assertTrue(virtual);self.assertTrue(overlays)
                self.assertGreater(last_visible_types,0)
                self.assertEqual({c.card_id for c in own.cards if c.zone=='overlay'},{1761063,32269855})
                self.assertEqual(messages[4],1)
                receipt.update(status='passed',existing_route_completed=True,virtual_search_slots=True,
                               public_overlay_projection=True,original_submit_guard_path=True,
                               uninterrupted_last_visible_type_used=last_visible_types)
        except Exception as error:
            receipt.update(status='failed_or_unsupported',error_type=type(error).__name__,error=str(error))
            raise
        finally:
            receipt.update(decisions=decisions,projected_frames=frames,prompt_counts=dict(prompts),
                           projected_message_counts=dict(messages),elapsed_seconds=round(time.monotonic()-started,3))
            directory=ROOT/'.cache/windbot-projection-normal';directory.mkdir(exist_ok=True)
            filename='search-xyz-attempt-'+attempted_at.strftime('%Y%m%dT%H%M%S%fZ')+'.json'
            (directory/filename).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')

    def test_normal_projection_continuous_guarded_game(self):
        existing=json.loads((ROOT/'configs/private-selection-engineering-v4.json').read_text())
        normal=existing['cases']['chosen-blind']['profile']['decks'][1]
        profile={'schema_version':2,'adapter_revision':5,'name':'normal-engineering-projection-check',
                 'decks':[normal,normal],'extras':[[],[]],'sides':[[],[]]}
        receipt={'schema_version':1,'kind':'normal-host-projection-positive-check',
                 'dataset_kind':'existing-normal-engineering-listing-not-user-deck',
                 'profile_sha256':digest(profile),'csharp_windbot_executed':False,
                 'historical_qualified':False,'strength_qualified':False,'trained':False}
        attempted_at=datetime.now(timezone.utc)
        receipt['attempted_at_utc']=attempted_at.isoformat()
        receipt.update(implementation_receipt())
        frames=decisions=0;prompts=Counter();messages=Counter();started=time.monotonic()
        try:
            with WindBotProjectionEngine(ROOT/'.cache',observer=0,scenario='effect-duel',
                                         deck_profile=profile,seed=7) as engine:
                receipt['resources']=engine.receipt
                req=engine.next_decision()
                while req is not None:
                    self.assertLess(decisions,600);self.assertLess(time.monotonic()-started,30)
                    if req.observation.observer==0:
                        frame=engine.transport_frame(req,state_version=f'normal-positive-{frames}')
                        window=WindBotWindow(req,frame,observer=0,deadline=time.monotonic()+10)
                        for message in frame.messages:
                            game_message(message,window)
                            messages[message.kind]+=1
                        prompts[req.prompt.message]+=1;frames+=1
                    action=choose_normal_action(req)
                    engine.submit(ActionSelection(req.context.run_id,req.duel_id,req.decision_id,action.action_id))
                    decisions+=1;req=engine.next_decision()
                self.assertIsNotNone(engine.outcome);self.assertFalse(engine.callback_errors)
                self.assertIsNone(engine.next_decision())
                self.assertEqual(messages[4],1)
                receipt.update(status='passed',natural_terminal=True,outcome=engine.outcome,
                               original_submit_guard_path=True,turns=engine.turn)
        except Exception as error:
            receipt.update(status='failed_or_unsupported',error_type=type(error).__name__,error=str(error),natural_terminal=False)
            raise
        finally:
            receipt.update(decisions=decisions,projected_frames=frames,prompt_counts=dict(prompts),
                           projected_message_counts=dict(messages),elapsed_seconds=round(time.monotonic()-started,3))
            directory=ROOT/'.cache/windbot-projection-normal';directory.mkdir(exist_ok=True)
            filename='attempt-'+attempted_at.strftime('%Y%m%dT%H%M%S%fZ')+'.json'
            (directory/filename).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':unittest.main()
