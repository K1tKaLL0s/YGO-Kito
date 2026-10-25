"""Real pinned C++/Lua ordinary-deal cases; raw private audits stay in cloud."""
import copy,json,random,unittest
from pathlib import Path
import torch

from ygo_kito.contracts import ActionSelection,DecisionRequest
from ygo_kito.duel_model import DuelModelConfig,PlayerEncoder
from ygo_kito.knowledge_cases import REQUIRED,read_case,run_knowledge_case
from ygo_kito.native import NativeNormalEngine,NativeError
from ygo_kito.normal_duel import request_digest
from ygo_kito.protocol_cases import EngineeringDriver
from ygo_kito.validation import ContractError

CACHE=Path(__file__).resolve().parents[1]/'.cache'

def opponent_window(trace):
    return next(w for w in trace['windows'] if w['message']==15 and w['request']['observation']['observer']==1)

class RealPrivateKnowledgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.runs={name:run_knowledge_case(CACHE,name) for name in REQUIRED}
        cls.last={name:run_knowledge_case(CACHE,name,preference='last') for name in ('crescent-private','rescue-confirmed')}
        cls.complete=run_knowledge_case(CACHE,'crescent-private',complete=True)

    def test_each_actual_script_case_replays_every_request_response_public_event_and_terminal(self):
        for name,(summary,trace) in self.runs.items():
            with self.subTest(name=name):
                result,again=run_knowledge_case(CACHE,name,replay=json.loads(json.dumps(trace)))
                self.assertEqual(trace,again);self.assertEqual(result['trace_sha256'],summary['trace_sha256'])
                self.assertEqual(trace['result']['callback_errors'],0)
                self.assertNotIn(1,summary['messages'])
        summary,trace=self.complete
        self.assertTrue(summary['result']['natural_terminal'])
        _,again=run_knowledge_case(CACHE,'crescent-private',complete=True,replay=json.loads(json.dumps(trace)))
        self.assertEqual(again,trace)
        self.assertEqual(trace['final_observations'][0]['public_history'],trace['final_observations'][1]['public_history'])
        self.assertEqual(trace['final_observations'][0]['public_history'][-1]['details']['message'],5)

    def test_real_hidden_deck_26_add_remove_readd_without_transferring_cards_early(self):
        _,trace=self.runs['crescent-private']
        windows=[w for w in trace['windows'] if w['message']==26]
        operations=[]
        for window in windows:
            req=DecisionRequest.from_dict(window['request'])
            chosen=next(a for a in req.actions if a.action_id==window['chosen_action'])
            operations.append(chosen.details.operation)
            self.assertTrue(all(c.visibility=='observer' and c.controller==0 and c.zone=='deck' for c in req.selection_choices))
            self.assertFalse(any(c.zone=='deck' for c in req.observation.cards))
            self.assertEqual(req.observation.deck_counts[0],35)
            self.assertFalse(req.private_reveals)
        self.assertEqual(operations[:3],['add','remove','add'])
        self.assertGreater(len(windows),3)
        req=DecisionRequest.from_dict(opponent_window(trace)['request'])
        self.assertEqual(req.observation.deck_counts[0],35)
        self.assertEqual(trace['final_observations'][0]['deck_counts'][0],34)

    def test_real_private_confirmation_survives_as_unlocated_knowledge_but_shuffle_breaks_aliases(self):
        _,trace=self.runs['crescent-private'];w=opponent_window(trace)
        req=DecisionRequest.from_dict(w['request'])
        self.assertEqual({c.card_id for c in req.private_reveals[0].cards},{25123082,89739383,96677818})
        self.assertTrue(all(c.visibility=='hidden' and c.card_id is None and c.knowledge_ref is None for c in req.selection_choices))
        kinds=[e['kind'] for e in trace['events']]
        self.assertLess(kinds.index(31),kinds.index(32));self.assertLess(kinds.index(32),kinds.index(15))
        self.assertFalse(any(e.details.message==31 for e in req.observation.public_history))
        self.assertTrue(all(c.card_id is None for c in req.observation.cards if c.visibility=='hidden'))
        self.assertFalse(any(w['request'].get('private_reveals') for w in trace['windows'] if w['request']['observation']['observer']==0))

    def test_real_unshuffled_opponent_deck_selection_has_evidence_not_inferred_ownership(self):
        outcomes=[]
        for _,trace in (self.runs['rescue-confirmed'],self.last['rescue-confirmed']):
            w=opponent_window(trace);req=DecisionRequest.from_dict(w['request'])
            self.assertEqual({c.card_id for c in req.selection_choices},{14878871,56343672,85138716})
            self.assertTrue(all(c.owner is None and c.knowledge_ref==req.private_reveals[0].ref for c in req.selection_choices))
            self.assertEqual(req.observation.life_points,(4000,8000))
            identities={c.ref:c.card_id for c in req.selection_choices}
            chosen=identities[w['chosen_refs'][0]];outcomes.append(chosen)
            self.assertIn(chosen,{c['card_id'] for c in trace['final_observations'][0]['cards'] if c['zone']=='hand'})
            kinds=[e['kind'] for e in trace['events']]
            self.assertNotIn(32,kinds[kinds.index(31):kinds.index(31)+3])
            bad=copy.deepcopy(req.to_dict());bad['private_reveals'][0]['observer']=0
            with self.assertRaises(ContractError):DecisionRequest.from_dict(bad)
        self.assertNotEqual(*outcomes)

    def test_real_hidden_world_changes_leave_opponent_blind_requests_and_all_tensors_equal(self):
        case=read_case('crescent-private');altered=copy.deepcopy(case['profile'])
        order=list(range(40));random.Random(case['seed_audit_only']*2).shuffle(order)
        candidates=[i for i in order[:-5] if altered['decks'][0][i] not in (25123082,89739383,96677818)]
        left=candidates[0];right=next(i for i in candidates if altered['decks'][0][i]!=altered['decks'][0][left])
        altered['decks'][0][left],altered['decks'][0][right]=altered['decks'][0][right],altered['decks'][0][left]
        requests=[]
        for profile in (case['profile'],altered):
            with NativeNormalEngine(CACHE,scenario='effect-duel',deck_profile=profile,seed=case['seed_audit_only'],selection_key='123456789abcdef0'*2) as engine:
                driver=EngineeringDriver(case,engine._rows,'first');req=engine.next_decision()
                for _ in range(80):
                    if req.prompt.message==15 and req.observation.observer==1:
                        requests.append(req);break
                    action=driver.choose(req)
                    engine.submit(ActionSelection(req.context.run_id,req.duel_id,req.decision_id,action.action_id));req=engine.next_decision()
                else:self.fail('actual opponent deck choice not reached')
                self.assertFalse(engine._private_reveals[0])
                with self.assertRaisesRegex(NativeError,'must not be queried'):engine._query(0,1,0,1)
        self.assertEqual(request_digest(requests[0]),request_digest(requests[1]))
        vocab=sorted({c.card_id for r in requests for c in r.observation.cards if c.card_id}|{c.card_id for r in requests for k in r.private_reveals for c in k.cards}|{c for r in requests for e in r.observation.public_history for c in e.card_ids})
        encoder=PlayerEncoder(vocab,DuelModelConfig(history_events=4))
        left,right=(encoder.encode(r) for r in requests)
        for key in left:self.assertTrue(torch.equal(left[key],right[key]),key)

    def test_facedown_real_host_keeps_public_materials_without_hidden_identity_or_query(self):
        _,trace=self.runs['facedown-xyz'];case=trace['case']
        with NativeNormalEngine(CACHE,scenario='effect-duel',deck_profile=case['profile'],seed=case['seed_audit_only'],selection_key=trace['selection_key_audit_only']) as engine:
            req=engine.next_decision()
            for row in trace['responses']:
                self.assertEqual(request_digest(req),row['request_sha256'])
                engine.submit(ActionSelection(req.context.run_id,req.duel_id,req.decision_id,row['action_id']));req=engine.next_decision()
            native=engine.lib;queries=[]
            class QueryGuard:
                def __getattr__(self,name):return getattr(native,name)
                def query_card(self,handle,controller,zone,sequence,flags,*args):
                    queries.append((controller,zone,sequence,flags))
                    if controller==0 and zone==4 and flags!=2:raise AssertionError('opponent hidden host queried')
                    return native.query_card(handle,controller,zone,sequence,flags,*args)
            engine.lib=QueryGuard()
            other=engine._observation(1)
            host=next(c for c in other.cards if c.controller==0 and c.zone=='monster')
            self.assertEqual((host.card_id,host.owner,host.attack,host.defense),(None,None,None,None))
            self.assertEqual(host.material_count,2)
            materials=[c for c in other.cards if c.zone=='overlay']
            self.assertEqual({c.card_id for c in materials},{1761063,32269855})
            self.assertTrue(all(c.visibility=='public' and c.owner==0 for c in materials))
            self.assertTrue(queries)
            # Projection loss of association is synthetic, NOT a claim of a
            # real MSG36 effect. The guard still forbids filling hidden gaps.
            engine._public_materials.clear()
            self.assertFalse(any(c.zone=='overlay' for c in engine._observation(1).cards))
            self.assertIsNone(next(c for c in engine._observation(1).cards if c.zone=='monster').material_count)

    def test_real_hidden_host_destruction_cleans_material_associations_and_public_grave(self):
        _,trace=self.runs['facedown-destroy']
        for p in (0,1):
            cards=trace['final_observations'][p]['cards']
            self.assertFalse(any(c['zone'] in ('monster','overlay') for c in cards))
            self.assertTrue({78156759,1761063,32269855}<={c['card_id'] for c in cards if c['zone']=='graveyard'})
        self.assertTrue(any(e['kind']==53 and e.get('position')==8 for e in trace['events']))

    def test_native_rejects_bad_26_and_opponent_deck_returns_and_stale_or_forged_action(self):
        for name,kind,player in (('crescent-private',26,0),('rescue-confirmed',15,1)):
            _,trace=self.runs[name];case=trace['case']
            with NativeNormalEngine(CACHE,scenario='effect-duel',deck_profile=case['profile'],seed=case['seed_audit_only'],selection_key=trace['selection_key_audit_only']) as engine:
                req=engine.next_decision();previous=None
                for row in trace['responses']:
                    if req.prompt.message==kind and req.observation.observer==player:break
                    previous=ActionSelection(req.context.run_id,req.duel_id,req.decision_id,row['action_id'])
                    engine.submit(previous);req=engine.next_decision()
                with self.assertRaises(ContractError):engine.submit(ActionSelection(req.context.run_id,req.duel_id,req.decision_id,'forged'))
                with self.assertRaises(ContractError):engine.submit(previous)
                action=req.actions[0];engine._responses[action.action_id]=b'\x01\x7f'
                engine.submit(ActionSelection(req.context.run_id,req.duel_id,req.decision_id,action.action_id))
                with self.assertRaisesRegex(NativeError,'MSG_RETRY'):engine.next_decision()
