"""Static objectives and public DTO scope checks. No CB search or replay."""
from copy import deepcopy
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from ygo_kito.basic_cb_scope import LinearMainline, random_outputs, VERSION
from ygo_kito.effect_mechanisms import analyze_card, SEMANTIC_VERSION
from ygo_kito.effect_records import effect_records


def card(code, zone='hand'):
    return NS(ref=f'{zone}:{code}',card_id=code,zone=zone,controller=0)


def request(cards):
    return NS(observation=NS(observer=0,cards=cards),search_choices=(),selection_choices=(),prompt=NS(message=11),sum_selection=None)


def action(code,kind='activate',zone='hand'):
    return NS(kind=kind,card_refs=(f'{zone}:{code}',),details=None)


def record(reason='effect'):
    movement=dict(kind='mill',random=True,quantity=3,from_zones=['deck'],to_zone='grave',reason=reason)
    return dict(effect_index=1,costs=[movement] if reason=='cost' else [],
        operations=[] if reason=='cost' else [movement],conditions={'status':'recognized'},
        trigger={'event':'free'},unknown=[],targets=[],count_limits=[])


class BasicCBScopeTests(unittest.TestCase):
    def guard(self,reason='effect'):
        return LinearMainline(NS(effect_records=lambda c:[record(reason)]),(1,2),())

    def test_fixed_mill_allowed_and_hit_cannot_supply_trigger_or_material(self):
        guard=self.guard();req=request((card(1),card(2)))
        self.assertTrue(guard.allows(req,action(1)))
        guard.select(req,action(1))
        req=request((card(1),card(2),card(10,'graveyard')))
        guard.observe(req.observation,[dict(kind=50,player=0,from_zone=1,to_zone=16,public_card=10)])
        self.assertFalse(guard.allows(req,action(10,zone='graveyard')))
        self.assertFalse(guard.allows(req,action(10,'select','graveyard')))
        self.assertNotIn(10,[c.card_id for c in guard.known_cards(req.observation)])
        self.assertTrue(guard.allows(req,action(2,'summon')))
        guard.select(req,action(2,'summon'))
        self.assertEqual([s['operation'] for s in guard.receipt()['steps']],['activate','summon'])

    def test_cost_and_effect_randomness_remain_independent(self):
        for reason in ('cost','effect'):
            guard=self.guard(reason);req=request((card(1),card(2)))
            guard.select(req,action(1))
            step=guard.receipt()['steps'][0]
            self.assertEqual(step['random_outputs'][0]['reason'],reason)
            self.assertEqual(bool(step['costs']),reason=='cost')
            self.assertFalse(guard.receipt()['future_deck_order_fixed'])

    def test_random_scope_does_not_depend_on_kind_quantity_or_card_identity(self):
        destinations = {'mill': ('graveyard', 16), 'send_grave': ('graveyard', 16),
                        'draw': ('hand', 2), 'banish': ('banished', 32)}
        for source, independent, outcome in ((101, 202, 303), (1701, 2849, 4013)):
            for kind, (destination, zone_id) in destinations.items():
                for quantity in (1, 2, 3, 5, 8):
                    for reason in ('cost', 'effect'):
                        with self.subTest(source=source, kind=kind, quantity=quantity, reason=reason):
                            effect = record(reason)
                            movement = (effect['costs'] or effect['operations'])[0]
                            movement.update(kind=kind, quantity=quantity, to_zone=destination)
                            guard = LinearMainline(NS(effect_records=lambda c: [deepcopy(effect)]),
                                                   (source, independent), ())
                            req = request((card(source), card(independent)))
                            self.assertTrue(guard.allows(req, action(source)))
                            guard.select(req, action(source))
                            req = request((card(source), card(independent), card(outcome, destination)))
                            guard.observe(req.observation, [
                                dict(kind=70, player=0, zone=2, public_card=source),
                                dict(kind=50, player=0, from_zone=1, to_zone=zone_id, public_card=outcome),
                            ])
                            self.assertFalse(guard.allows(req, action(outcome, zone=destination)))
                            self.assertFalse(guard.allows(req, action(outcome, 'select', destination)))
                            self.assertTrue(guard.allows(req, action(independent, 'summon')))
                            self.assertNotIn(outcome, [c.card_id for c in guard.known_cards(req.observation)])
                            receipt = guard.receipt()
                            self.assertEqual(receipt['unknown'], [])
                            output = receipt['steps'][0]['random_outputs'][0]
                            self.assertEqual((output['kind'], output['quantity'], output['reason']),
                                             (kind, quantity, reason))
                            self.assertFalse(receipt['random_result_branches_expanded'])

    def test_known_trigger_and_fusion_can_follow_an_independent_random_operation(self):
        first = record()
        first['operations'].append(dict(kind='send_grave', random=False, quantity=1,
                                       from_zones=['hand'], to_zone='grave', reason='effect'))
        trigger = record()
        trigger['trigger'] = {'event': 'sent_to_grave', 'reason': 'effect'}
        trigger['operations'] = [dict(kind='fusion_summon', from_zones=['extra'],
                                      to_zone='monster', reason='effect')]
        effects = {101: first, 202: trigger}
        guard = LinearMainline(NS(effect_records=lambda c: [deepcopy(effects[c])]), (101, 202), (909,))
        req = request((card(101), card(202), card(909, 'extra')))
        guard.select(req, action(101))
        req = request((card(101), card(202, 'graveyard'), card(303, 'graveyard'), card(909, 'extra')))
        guard.observe(req.observation, [
            dict(kind=70, player=0, zone=2, public_card=101),
            dict(kind=50, player=0, from_zone=1, to_zone=16, public_card=303),
            dict(kind=50, player=0, from_zone=2, to_zone=16, public_card=202),
        ])
        self.assertTrue(guard.allows(req, action(202, zone='graveyard')))
        guard.select(req, action(202, zone='graveyard'))
        self.assertEqual(guard.receipt()['steps'][1]['operations'], trigger['operations'])
        self.assertTrue(guard.allows(req, action(202, 'select', 'graveyard')))
        self.assertTrue(guard.allows(req, action(909, 'special_summon', 'extra')))
        self.assertFalse(guard.allows(req, action(303, 'select', 'graveyard')))
        self.assertEqual(guard.receipt()['unknown'], [])

    def test_real_dictionary_projection_separates_mill_cost_and_mill_effect(self):
        texts=('从自己卡组上面把3张卡送去墓地才能发动。从卡组把1只「光道」怪兽加入手卡。',
               '①：自己主要阶段才能发动。双方从卡组上面把2张卡送去墓地。')
        rows=[]
        for i,text in enumerate(texts,1):
            row=dict(id=i,name='anonymous wording fixture',desc=text,type=2,level=0,race=0,attribute=0,setcode=0)
            rows.append(effect_records(analyze_card(row,'synthetic-source'),semantic_version=SEMANTIC_VERSION,row=row))
        costs=[o for r in rows[0] for o in random_outputs(r)]
        effects=[o for r in rows[1] for o in random_outputs(r)]
        self.assertTrue(any(o['reason']=='cost' and o['quantity']==3 for o in costs))
        self.assertFalse(any(o['reason']=='effect' for o in costs))
        self.assertTrue(any(o['reason']=='effect' and o['quantity']==2 for o in effects))

    def test_random_draw_does_not_unlock_a_card_identity(self):
        guard=self.guard();req=request((card(1),card(2),card(9)))
        guard.observe(req.observation,[])
        self.assertFalse(guard.allows(req,action(9,'summon')))
        self.assertTrue(guard.allows(req,action(2,'summon')))

    def test_automatic_random_trigger_is_unknown_not_a_seed_proof(self):
        guard=self.guard();req=request((card(1),card(2),card(10,'graveyard')))
        guard.observe(req.observation,[dict(kind=50,player=0,from_zone=1,to_zone=16,public_card=10),
            dict(kind=70,player=0,zone=16,public_card=10)])
        self.assertTrue(guard.receipt()['unknown'])
        self.assertEqual(guard.receipt()['version'],VERSION)

    def test_targeted_selection_has_distinct_provenance_from_random_hit(self):
        guard=self.guard();req=request((card(1),card(2)))
        req.search_choices=(card(7,'deck'),)
        choice=action(7,'select','deck');self.assertTrue(guard.allows(req,choice));guard.select(req,choice)
        req=request((card(1),card(2),card(7,'graveyard'),card(8,'graveyard')))
        guard.observe(req.observation,[dict(kind=50,player=0,from_zone=1,to_zone=16,public_card=c) for c in (7,8)])
        self.assertTrue(guard.allows(req,action(7,'select','graveyard')))
        self.assertFalse(guard.allows(req,action(8,'select','graveyard')))

    def test_random_removal_cannot_reuse_previously_known_card_but_other_zone_continues(self):
        effect=record();effect['operations']=[dict(kind='banish',random=True,quantity=1,
            from_zones=['hand'],to_zone='banished',reason='effect')]
        guard=LinearMainline(NS(effect_records=lambda c:[effect]),(1,2),(9,))
        req=request((card(1),card(2),card(9,'extra')));guard.select(req,action(1))
        req=request((card(1),card(2,'banished'),card(9,'extra')))
        guard.observe(req.observation,[dict(kind=70,player=0,zone=2,public_card=1),
            dict(kind=50,player=0,from_zone=2,to_zone=32,public_card=2)])
        self.assertFalse(guard.allows(req,action(2,zone='banished')))
        self.assertFalse(guard.allows(req,action(1)))
        self.assertTrue(guard.allows(req,action(9,'special_summon','extra')))
        self.assertEqual(guard.receipt()['unknown'],[])


class SymbolicObjectiveTests(unittest.TestCase):
    def fixture(self):
        from ygo_kito.build_contracts import BuildTask, DeckParts
        from tests.test_construction_binding import catalog

        original, assets = catalog()
        assets.rows[1].update(type=2, name='ritual access', desc='①：从自己的手卡·场上把等级合计直到8以上的怪兽解放，从手卡把「匿名仪式」仪式召唤。')
        assets.rows[2].update(type=129, level=8, name='匿名仪式', desc='「匿名仪式魔法」降临。')
        assets.rows[3].update(type=17, level=8, desc='通常怪兽。')
        assets.rows[4].update(type=2, desc='①：抽2张。')
        assets.rows[5].update(type=17, level=1, desc='通常怪兽。')
        assets.rows[101] = dict(assets.rows[5], id=101, type=0x4000021, level=1, desc='1星怪兽1只')
        raw = original.to_dict()
        raw['pool'].append(101)
        raw['sizes']['extra'] = 1
        raw['goal']['constraints'][0].update(minimum=1, maximum=40, predicate={'field':'type_all','value':1})
        raw['requirements'] = []
        task = BuildTask.from_dict(raw)
        deck = DeckParts(tuple(sorted([1,2,3,4,5,6,18]+[c for c in range(7,18) for _ in range(3)])), (101,))
        assets.validate(task, deck)
        return task, deck, assets

    def test_link_ritual_and_random_identity_free_effect_goals_are_bound(self):
        from ygo_kito.basic_cb_inference import proposals, static_route_support, route_blocks
        from ygo_kito.build_semantics import route_task
        from ygo_kito.effect_mechanisms import MechanismCatalog

        task, deck, assets = self.fixture()
        before = task.sha256, deck.to_dict()
        with patch('ygo_kito.route_search.discover_goal', side_effect=AssertionError('search forbidden')):
            derived = proposals(task, deck, assets)
        kinds = {value.goal['route_goal']['kind'] for value in derived}
        self.assertEqual(kinds, {'link_summon', 'ritual_summon', 'effect_resolution'})
        for value in derived:
            route = value.goal['route_goal']
            self.assertTrue(route_blocks(route))
            self.assertTrue(static_route_support(route, deck, MechanismCatalog(assets)))
            native = route_task(value)
            self.assertEqual(native.goal, route)
            self.assertEqual(value.goal['constraints'], task.goal['constraints'])
            assets.validate(value, deck)
        self.assertEqual((task.sha256, deck.to_dict()), before)
        # A printed material prohibition removes this concrete binding.
        assets.rows[5]['desc'] = '这张卡不能作为连接素材。'
        self.assertFalse(any(v.goal['route_goal']['kind']=='link_summon' for v in proposals(task,deck,assets)))

    def test_effect_quantity_binds_the_exact_solved_link_without_draw_identity(self):
        from ygo_kito.route_search import effect_goal_witness
        goal = dict(kind='effect_resolution', card_id=4,
                    effect_objective=dict(kind='draw', effect_index=1, minimum=2))
        events = [dict(kind=70, player=0, public_card=4, description=0, link=1),
                  dict(kind=72, link=1), dict(kind=90, player=0, count=2), dict(kind=73, link=1)]
        self.assertEqual(effect_goal_witness(goal, events)['quantity'], 2)
        self.assertIsNone(effect_goal_witness(goal, events, exact_description=True))
        for change in ('other-link', 'negated', 'insufficient', 'other-player'):
            altered = deepcopy(events)
            if change == 'other-link':
                altered[1]['link'] = 2
            elif change == 'negated':
                altered.insert(1, dict(kind=75, link=1))
            elif change == 'insufficient':
                altered[2]['count'] = 1
            else:
                altered[2]['player'] = 1
            self.assertIsNone(effect_goal_witness(goal, altered), change)
        guard = LinearMainline(NS(effect_records=lambda _code: [record()]), (1,), ())
        self.assertTrue(guard.supports_goal(goal))
        guard.unknown.append('random_identity_required')
        self.assertFalse(guard.supports_goal(goal))

    def test_summon_method_and_plan_goal_survive_public_binding(self):
        from ygo_kito.route_search import route_witness
        from ygo_kito.duel_planning import plans_from_construction
        from ygo_kito.build_semantics import route_task
        from ygo_kito.basic_cb_inference import proposals

        task, deck, assets = self.fixture()
        observation = NS(cards=(NS(card_id=101, zone='monster', controller=0, visibility='public'),))
        goal = dict(kind='link_summon', card_id=101)
        events = [dict(kind=50, player=0, from_zone=4, to_zone=16, reason=0x10000008),
                  dict(kind=62, player=0, public_summoning_card=101), dict(kind=63)]
        self.assertEqual(route_witness(goal, events, observation)['kind'], 'link_summon')
        events[0]['reason'] = 0x80008
        self.assertIsNone(route_witness(goal, events, observation))
        effect = next(value for value in proposals(task, deck, assets) if value.goal['route_goal']['kind']=='effect_resolution')
        native = route_task(effect)
        plans = plans_from_construction(native, dict(route_evidence=dict(exploration=dict(discovered_intents=[
            dict(operation='activate', card_ids=[4])]), private_selection_key_audit_only='excluded')))
        self.assertEqual(plans[0].goal_kind, 'effect_resolution')
        self.assertEqual(plans[0].effect_objective, ('draw', 1, 2))
        self.assertFalse(hasattr(plans[0], 'private_selection_key_audit_only'))


if __name__=='__main__':unittest.main()
