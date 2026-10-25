"""Explicit ordinary native positive check; excluded from the CPU-only suite.

Uses the repository's existing 40-card normal engineering opponent listing.
No C# process, training, fault injection or private response inspection occurs.
"""
from collections import Counter
from datetime import datetime,timezone
import hashlib
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


class WindBotProjectionNormalTests(unittest.TestCase):
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
        receipt['implementation_sha256']={name:hashlib.sha256((ROOT/'src/ygo_kito'/name).read_bytes()).hexdigest()
            for name in ('windbot_projection.py','windbot_room.py','native.py','native_response_guard.py')}
        frames=decisions=0;messages=Counter();prompts=Counter();virtual=False;overlays=False
        try:
            with WindBotProjectionEngine(ROOT/'.cache',observer=0,scenario='effect-duel',deck_profile=profile,seed=1) as engine:
                receipt['resources']=engine.receipt;driver=RouteDriver(raw['goal']['route']);req=engine.next_decision()
                for _ in range(100):
                    self.assertIsNotNone(req);self.assertLess(time.monotonic()-started,30)
                    if req.observation.observer==0:
                        frame=engine.transport_frame(req,state_version=f'existing-xyz-{frames}')
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
                self.assertEqual({c.card_id for c in own.cards if c.zone=='overlay'},{1761063,32269855})
                self.assertEqual(messages[4],1)
                receipt.update(status='passed',existing_route_completed=True,virtual_search_slots=True,
                               public_overlay_projection=True,original_submit_guard_path=True)
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
        receipt['implementation_sha256']={name:hashlib.sha256((ROOT/'src/ygo_kito'/name).read_bytes()).hexdigest()
            for name in ('windbot_projection.py','windbot_room.py','native.py','native_response_guard.py')}
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
