"""Real pinned C++/Lua and ordinary openings, distinct from wire fixtures."""
from collections import Counter
import copy
import json
from pathlib import Path
import unittest
import random

import torch

from ygo_kito.contracts import ActionSelection, DecisionRequest
from ygo_kito.duel_model import DuelActorCritic, DuelModelConfig, PlayerEncoder
from ygo_kito.native import NativeError, NativeNormalEngine
from ygo_kito.normal_duel import request_digest
from ygo_kito.protocol_cases import run_protocol_case, REQUIRED
from ygo_kito.validation import ContractError

CACHE=Path(__file__).resolve().parents[1]/'.cache'


def visible(trace, player, zone):
    return [c for c in trace['final_observations'][player]['cards'] if c['controller']==player and c['zone']==zone]


class RealProtocolHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.cases={}
        for name in REQUIRED:
            cls.cases[name]=run_protocol_case(CACHE,name)
        cls.last={n:run_protocol_case(CACHE,n,preference='last') for n in ('sum-at-least','counter','sort')}
        cls.complete=run_protocol_case(CACHE,'number-equip',complete=True)

    def test_all_declared_card_scripts_respond_and_replay_actual_observations_and_events(self):
        for name,(summary,trace) in self.cases.items():
            with self.subTest(name=name):
                result,again=run_protocol_case(CACHE,name,replay=json.loads(json.dumps(trace)))
                self.assertEqual(trace,again)
                self.assertEqual(result['trace_sha256'],summary['trace_sha256'])
                self.assertEqual(trace['result']['callback_errors'],0)
                self.assertTrue(set(REQUIRED[name])<=set(trace['result']['actual_prompts']))
                self.assertNotIn(1,summary['messages'])

    def test_real_minimal_at_least_has_two_distinct_accepted_returns_and_no_extra_removal(self):
        returned=[]
        for _,trace in (self.cases['sum-at-least'],self.last['sum-at-least']):
            req=DecisionRequest.from_dict(trace['windows'][0]['request'])
            self.assertEqual(req.sum_selection.mode,'minimal_at_least')
            self.assertEqual(req.sum_selection.target,100)
            self.assertEqual({c.values for c in req.sum_selection.optional},{(2000,),(2100,)})
            self.assertEqual(len(req.actions),2)
            result=[e['public_card'] for e in trace['events'] if e['kind']==50 and e.get('from_zone')==4 and e.get('to_zone')==1]
            self.assertEqual(len(result),1)
            returned.append(result[0])
            self.assertEqual(trace['result']['life_points'][0],4000)
            self.assertEqual(len(visible(trace,1,'monster')),1)
            self.assertLessEqual(sum(c['attack'] for c in visible(trace,1,'monster')),4000)
        self.assertEqual(set(returned),{65367484,43096270})

    def test_real_dual_synchro_level_uses_two_instead_of_one_and_triggers_actual_draw(self):
        _,trace=self.cases['sum-dual']
        req=DecisionRequest.from_dict(trace['windows'][0]['request'])
        self.assertEqual(req.sum_selection.mode,'equal')
        self.assertEqual(req.sum_selection.target,5)
        self.assertEqual([c.values for c in req.sum_selection.mandatory],[(3,)])
        self.assertEqual([c.values for c in req.sum_selection.optional],[(1,2)])
        self.assertEqual({c['card_id'] for c in visible(trace,0,'monster')},{26593852})
        self.assertEqual({c['card_id'] for c in visible(trace,0,'graveyard')},{68505803,92676637})
        kinds=[e['kind'] for e in trace['events']]
        self.assertLess(kinds.index(62),kinds.index(63))
        self.assertTrue(any(e['kind']==90 and e.get('player')==0 and e.get('count')==1 for e in trace['events'][kinds.index(63):]))

    def test_actual_counter_allocations_remove_different_counter_and_replace_destruction(self):
        removed=[]
        for _,trace in (self.cases['counter'],self.last['counter']):
            req=DecisionRequest.from_dict(trace['windows'][0]['request'])
            self.assertEqual({a.details.quantities for a in req.actions},{(0,1),(1,0)})
            self.assertEqual({c['card_id'] for c in visible(trace,0,'monster')},{2525268,71413901})
            events=[e for e in trace['events'] if e['kind']==102]
            self.assertEqual(len(events),1);self.assertEqual(events[0]['count'],1)
            removed.append(events[0]['slot'])
        self.assertEqual(set(removed),{0,1})

    def test_real_sorting_changes_next_actual_draw_without_publishing_top_order(self):
        drawn=[]
        for _,trace in (self.cases['sort'],self.last['sort']):
            window=trace['windows'][0]
            req=DecisionRequest.from_dict(window['request'])
            choices={c.ref:c.card_id for c in req.search_choices}
            expected=choices[window['chosen_refs'][0]]
            before=Counter(c.card_id for c in req.observation.cards if c.controller==0 and c.zone=='hand')
            after=Counter(c['card_id'] for c in visible(trace,0,'hand'))
            self.assertEqual(after-before,Counter({expected:1}));drawn.append(expected)
            history=trace['final_observations'][1]['public_history']
            self.assertFalse(any(e['details']['message']==25 or e['details']['message']==50 and all(p['zone']=='deck' for p in e['details']['locations']) for e in history))
        self.assertNotEqual(*drawn)

    def test_real_multi_zone_disable_agrees_with_core_field_mask(self):
        _,trace=self.cases['disable-two']
        window=trace['windows'][0];req=DecisionRequest.from_dict(window['request'])
        selected=next(a for a in req.actions if a.action_id==window['chosen_action'])
        expected=sum(1<<(p.sequence+(16 if p.controller else 0)) for p in selected.details.destinations)
        masks=[e['details']['value'] for e in trace['final_observations'][0]['public_history'] if e['details']['message']==56]
        self.assertEqual(masks[-1],expected);self.assertEqual(expected.bit_count(),2)

    def test_actual_declarations_pay_cost_then_apply_rule_resolution_and_equipment(self):
        _,trace=self.cases['announcements']
        self.assertEqual(trace['result']['life_points'][0],6500)
        self.assertIn(32864,{c['card_id'] for c in visible(trace,1,'graveyard')})
        history=trace['final_observations'][0]['public_history']
        cost=next(i for i,e in enumerate(history) if e['details']['message']==100)
        resolution=next(i for i,e in enumerate(history) if e['details']['message']==72)
        self.assertLess(cost,resolution)
        _,trace=self.cases['number-equip']
        self.assertEqual(trace['result']['life_points'][0],6000)
        self.assertEqual(visible(trace,0,'monster')[0]['attack'],4000)
        self.assertIn(75539614,{c['card_id'] for c in visible(trace,0,'spell_trap')})
        self.assertTrue(any(e['details']['message']==93 for e in trace['final_observations'][0]['public_history']))

    def test_private_deck_confirmation_is_not_public_but_extra_reveal_is_remembered_after_shuffle(self):
        _,trace=self.cases['private-sort']
        self.assertIn(31,[e['kind'] for e in trace['events']])
        self.assertFalse(any(e['details']['message']==31 for e in trace['final_observations'][1]['public_history']))
        _,trace=self.cases['confirm-extra']
        history=trace['final_observations'][0]['public_history']
        self.assertEqual({c for e in history if e['details']['message']==31 for c in e['card_ids']},{26593852,78156759})
        self.assertEqual(sum(e['details']['message']==39 for e in history),2)
        self.assertTrue(all(c['card_id'] is None for c in trace['final_observations'][0]['cards'] if c['controller']==1 and c['zone']=='extra'))

    def test_real_rps_resolves_both_answers_and_banishes_the_losing_monster_facedown(self):
        _,trace=self.cases['rps']
        self.assertEqual([w['chosen_value'] for w in trace['windows']],[1,2])
        second=trace['windows'][1]['request']
        self.assertFalse(any(e['details']['message']==133 for e in second['observation']['public_history']))
        result=[e for e in trace['final_observations'][0]['public_history'] if e['details']['message']==133]
        self.assertEqual(result[0]['details']['values'],[1,2])
        bans=[c for c in trace['final_observations'][0]['cards'] if c['zone']=='banished']
        self.assertEqual(len(bans),1)
        other=trace['final_observations'][1]['cards']
        hidden=[c for c in other if c['ref']==bans[0]['ref']]
        # Depending on the real RPS result the local/other player's view differs;
        # exactly one observer gets the private face-down identity.
        self.assertNotEqual(bans[0]['card_id'] is None,hidden[0]['card_id'] is None)

    def test_natural_terminal_has_complete_public_lp_battle_chain_and_result_history_and_replay(self):
        summary,trace=self.complete
        self.assertTrue(summary['result']['natural_terminal'])
        history=trace['final_observations'][0]['public_history']
        messages={e['details']['message'] for e in history}
        self.assertTrue({40,41,50,60,61,70,71,72,73,74,90,91,93,100,110,111,113,114,5}<=messages)
        self.assertEqual([e['event_id'] for e in history],[f'public-{i}' for i in range(len(history))])
        self.assertEqual(history,trace['final_observations'][1]['public_history'])
        self.assertEqual(history[-1]['details']['value'],trace['outcome']['winner'])
        _,again=run_protocol_case(CACHE,'number-equip',complete=True,replay=json.loads(json.dumps(trace)))
        self.assertEqual(trace,again)

    def test_existing_generic_effect_duel_and_replay_bind_new_adapter_version(self):
        from ygo_kito.effect_duel import run_effect_duel
        profile=json.loads((CACHE.parent/'configs/effect-history-engineering-v3.json').read_text())
        summary,trace=run_effect_duel(CACHE,profile,seed=3,budget_seconds=30)
        self.assertTrue(summary['ok'])
        self.assertEqual(trace['versions']['adapter_schema'],'native-protocol-history-v3')
        checked,again=run_effect_duel(CACHE,profile,replay=json.loads(json.dumps(trace)),budget_seconds=30)
        self.assertTrue(checked['replay_verified']);self.assertEqual(trace,again)
        bad=copy.deepcopy(trace);bad['versions']['adapter_schema']='native-extra-material-v2'
        with self.assertRaisesRegex(ContractError,'resources differ'):
            run_effect_duel(CACHE,profile,replay=bad,budget_seconds=30)

    def test_native_rejects_corrupt_wire_for_each_supported_advanced_protocol(self):
        cases=[('sum-at-least',23),('sum-dual',23),('counter',22),('disable-two',24),('sort',25),
               ('announcements',140),('announcements',141),('card-name',142),('number-equip',143)]
        for name,kind in cases:
            with self.subTest(name=name,message=kind):
                _,trace=self.cases[name]
                c=trace['case']
                with NativeNormalEngine(CACHE,scenario='effect-duel',deck_profile=c['profile'],seed=c['seed_audit_only']) as engine:
                    req=engine.next_decision();old=None
                    for row in trace['responses']:
                        self.assertEqual(request_digest(req),row['request_sha256'])
                        if req.prompt.message==kind:break
                        old=ActionSelection(req.context.run_id,req.duel_id,req.decision_id,row['action_id'])
                        engine.submit(old);req=engine.next_decision()
                    with self.assertRaises(ContractError):engine.submit(ActionSelection(req.context.run_id,req.duel_id,req.decision_id,'forged'))
                    with self.assertRaises(ContractError):engine.submit(old)
                    chosen=req.actions[0]
                    if kind in (22,23,25): bad=b'\0'*64
                    elif kind==24:
                        native=engine._responses[chosen.action_id];bad=native[:3]*2
                    elif kind==142:bad=next(code for code,row in engine._rows.items() if row['alias'])
                    elif kind==143:bad=255
                    else:bad=0
                    engine._responses[chosen.action_id]=bad
                    engine.submit(ActionSelection(req.context.run_id,req.duel_id,req.decision_id,chosen.action_id))
                    with self.assertRaisesRegex(NativeError,'MSG_RETRY'):engine.next_decision()

    def test_rich_history_reaches_model_and_large_declaration_candidates_fail_closed(self):
        _,trace=self.cases['counter']
        req=DecisionRequest.from_dict(trace['windows'][0]['request'])
        card_ids=sorted({c.card_id for c in req.observation.cards if c.card_id is not None}|{x for e in req.observation.public_history for x in e.card_ids})
        cfg=DuelModelConfig(history_events=8)
        encoder=PlayerEncoder(card_ids,cfg);batch=encoder.batch([req])
        model=DuelActorCritic(cfg,len(card_ids))
        logits,value=model(batch)
        self.assertTrue(torch.isfinite(logits).all());self.assertTrue(torch.isfinite(value).all())
        self.assertFalse(torch.equal(batch['pointers'][0,0],batch['pointers'][0,1]))
        # Full card names are offered, never silently cut to fit the prototype.
        self.assertGreater(self.cases['card-name'][1]['windows'][0]['request']['candidate_count'],2048)
        _,tr=self.cases['card-name'];c=tr['case']
        with NativeNormalEngine(CACHE,scenario='effect-duel',deck_profile=c['profile'],seed=c['seed_audit_only']) as engine:
            r=engine.next_decision()
            for row in tr['responses']:
                if r.prompt.message==142:break
                engine.submit(ActionSelection(r.context.run_id,r.duel_id,r.decision_id,row['action_id']));r=engine.next_decision()
            vocab=sorted({c.card_id for c in r.observation.cards if c.card_id is not None}|{x for ev in r.observation.public_history for x in ev.card_ids})
            with self.assertRaisesRegex(ContractError,'token/action budget'):
                PlayerEncoder(vocab,DuelModelConfig()).encode(r)

    def test_real_private_sort_hidden_worlds_have_identical_opponent_requests_and_features(self):
        c=copy.deepcopy(self.cases['private-sort'][1]['case'])
        changed=copy.deepcopy(c['profile'])
        indices=list(range(40));random.Random(c['seed_audit_only']*2).shuffle(indices)
        i=indices[-6]
        j=next(k for k in indices[:-8] if changed['decks'][0][k]!=changed['decks'][0][i])
        changed['decks'][0][i],changed['decks'][0][j]=changed['decks'][0][j],changed['decks'][0][i]
        from ygo_kito.protocol_cases import EngineeringDriver
        requests=[]
        for profile in (c['profile'],changed):
            with NativeNormalEngine(CACHE,scenario='effect-duel',deck_profile=profile,seed=c['seed_audit_only']) as engine:
                driver=EngineeringDriver(c,engine._rows,'first');r=engine.next_decision();sorted_once=False
                for _ in range(100):
                    if r.prompt.message==25:sorted_once=True
                    if sorted_once and r.observation.observer==1:
                        requests.append(r);break
                    a=driver.choose(r)
                    engine.submit(ActionSelection(r.context.run_id,r.duel_id,r.decision_id,a.action_id));r=engine.next_decision()
                else:self.fail('real private sorting never reached next opponent decision')
                with self.assertRaisesRegex(NativeError,'must not be queried'):
                    engine._query(0,1,0,1)
        self.assertEqual(len(requests),2)
        self.assertEqual(request_digest(requests[0]),request_digest(requests[1]))
        vocab=sorted({c.card_id for r in requests for c in r.observation.cards if c.card_id is not None}|{x for r in requests for e in r.observation.public_history for x in e.card_ids})
        encoder=PlayerEncoder(vocab,DuelModelConfig())
        a,b=map(encoder.encode,requests)
        for key in a:self.assertTrue(torch.equal(a[key],b[key]),key)

    def test_tampered_result_or_resource_cannot_replay_as_verified(self):
        for mutation in ('resources','result'):
            bad=copy.deepcopy(self.cases['sort'][1])
            if mutation=='resources':bad['resources']['resources']['cards']='0'*64
            else:bad['result']['public_events']+=1
            with self.subTest(mutation=mutation),self.assertRaises((NativeError,ContractError)):
                run_protocol_case(CACHE,'sort',replay=bad)

