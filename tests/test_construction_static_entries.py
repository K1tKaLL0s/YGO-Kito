"""Default configuration purposes through Evaluation; no supplied true facts."""
from dataclasses import replace
from types import SimpleNamespace
import unittest

from ygo_kito.build_contracts import DeckParts
from ygo_kito.construction_binding import CatalogBindingAdapter
from ygo_kito.construction_layer_flow import normalize_function_uses
from ygo_kito.construction_quality import evaluate_functional_quality, support_state
from ygo_kito.construction_relations import InputGroup, Need, RelationContext, Resource, UseRequirement
from tests.test_construction_functional_flow import fixture


class StaticEntryTests(unittest.TestCase):
    def joint_context(self, codes, before=()):
        from ygo_kito.construction_relations import JointConstraint
        initial, _ = self.evaluate()
        ids = {initial['use_details'][u.use_id]['card_id']: u.use_id
               for u in initial['uses'] if u.contributes}
        uses = tuple(UseRequirement('r:' + str(c), InputGroup('all', (Need('r:' + str(c),
            Resource('functional_operation', attributes=(f'catalog:{c}:1:op:0',)), mode='presence'),)),
            'required joint processing', functional_use_ids=(ids[c],)) for c in codes)
        constraints = (JointConstraint('original_order', tuple('r:' + str(c) for c in before),
            'before', 'original required order'),) if before else ()
        return SimpleNamespace(relations=RelationContext(uses, constraints=constraints))

    def test_printed_activation_condition_keeps_no_duel_state_or_resume_work(self):
        self.assets.rows[1].update(type=33, desc='①：自己墓地没有卡存在的场合，'
            '把这张卡从手卡送去墓地才能发动。抽1张。')
        self.assets.rows[2].update(type=33, desc='①：自己主要阶段才能发动。从自己卡组上面把1张卡送去墓地。')
        self.assets.rows[3].update(type=33, desc='①：自己主要阶段才能发动。从自己墓地把1只怪兽除外。')
        self.assets.rows[4]['type'] = 2
        catalog = CatalogBindingAdapter(self.assets).semantic_catalog
        for before in ((), (2, 1), (2, 3, 1)):
            with self.subTest(before=before):
                context = self.joint_context((1, 2, 3), before)
                work = {}
                facts = normalize_function_uses(self.task, self.deck, catalog, policy=self.policy,
                    context=context, work_state=work)
                self.assertEqual(self.state(facts, 1), [True])
                detail, = [detail for detail in facts['use_details'].values() if detail['card_id'] == 1]
                self.assertEqual(detail['activation_state_conditions'][0]['zone'], 'grave')
                self.assertNotIn('state_movements', detail)
                self.assertNotIn('state_orders', work)
                self.assertNotIn('calculation_pending', facts)
                self.assertFalse(any(key.startswith('state_order:') for key in facts['fact_details']))
                self.assertFalse(any(row['condition'] is False for row in facts['hard_requirements']))

    def test_printed_processing_condition_is_recorded_without_a_board(self):
        self.assets.rows[1].update(type=2, desc='①：在自己场上把1只「匿名衍生物」'
            '（天使族·地·4星·攻/守2000）特殊召唤。'
            '自己场上没有「匿名旅程」存在的场合，可以再从卡组把1张「匿名旅程」'
            '在自己的魔法与陷阱区域表侧表示放置。')
        self.assets.rows[2].update(type=0x20002, name='匿名旅程', desc='①：自己主要阶段才能发动。抽1张。')
        facts, quality = self.evaluate()
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertEqual(self.state(facts, 1), [True, True])
        condition, = [state for detail in facts['use_details'].values() if detail['card_id'] == 1
                      for state in (detail['operation'] or {}).get('state_conditions', ())]
        self.assertEqual(condition['timing'], 'before_operation')
        self.assertFalse(any(key.startswith('processing_state:') for key in facts['fact_details']))

    def test_top_deck_payment_choices_use_one_scoring_function(self):
        self.assets.rows[1].update(type=33, desc='①：1回合1次，从自己卡组上面把最多3张卡送去墓地才能发动。'
            '这张卡的攻击力直到回合结束时上升因为这个效果发动而送去墓地的数量×500。'
            '②：自己场上的这张卡被破坏送去墓地的场合发动。自己抽1张。')
        facts, quality = self.evaluate()
        relevant = [(u, facts['use_details'][u.use_id]) for u in facts['uses'] if u.contributes
                    and facts['use_details'][u.use_id]['card_id'] == 1]
        boosts = [(u, detail) for u, detail in relevant if detail['operation']['kind'] == 'stats']
        self.assertEqual(sorted(detail['costs'][0]['quantity'] for _, detail in boosts), [1, 2, 3])
        self.assertEqual(len({u.score_family_id for u, _ in boosts}), 1)
        self.assertTrue(all(support_state(u.self_condition, facts['variables']) is True for u, _ in relevant))
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertEqual(quality['score']['value'], 2.)

    def test_fixed_excavation_choice_and_return_is_one_non_targeted_addition(self):
        self.assets.rows[1].update(type=2,desc='这个卡名的卡在1回合只能发动1张，'
            '这张卡发动的回合，自己不能把怪兽特殊召唤。'
            '①：从自己卡组上面把3张卡翻开，从那之中选1张加入手卡。那之后，剩下的卡回到卡组。')
        facts,quality=self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(facts,1),[True])
        chosen,=[d['operation'] for d in facts['use_details'].values() if d['card_id']==1]
        self.assertTrue(chosen['random'])
        self.assertEqual(chosen['selection_method'],'choose_from_excavated')
        self.assertEqual(chosen['quantity'],1)

    def test_global_destination_replacement_preserves_optional_order_and_required_conflict(self):
        from ygo_kito.construction_relations import JointConstraint
        self.assets.rows[1].update(type=33,desc='①：自己·对方回合，自己墓地没有卡存在的场合，'
            '把这张卡从手卡送去墓地才能发动。'
            '直到下个回合的结束时，被送去墓地的卡不去墓地而除外。')
        self.assets.rows[2].update(type=2,desc='①：从自己卡组把1只怪兽送去墓地。')
        facts, quality=self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(facts,1),[True])
        self.assertEqual(self.state(facts,2),[True])
        ids={facts['use_details'][u.use_id]['card_id']:u.use_id for u in facts['uses'] if u.contributes}
        uses=tuple(UseRequirement('r:'+str(c),InputGroup('all',(Need('r:'+str(c),
            Resource('functional_operation',attributes=(f'catalog:{c}:1:op:0',)),mode='presence'),)),
            'required joint processing',functional_use_ids=(ids[c],)) for c in (1,2))
        ctx=SimpleNamespace(relations=RelationContext(uses,constraints=(
            JointConstraint('after_replacement',('r:1','r:2'),'before','original required order'),)))
        _, conflict=self.evaluate(context=ctx)
        self.assertTrue(conflict['complete'],conflict['unknowns'])
        self.assertTrue(any(r['status']=='failed' and r['requirement_id'].startswith('restriction_order:')
            for r in conflict['hard_requirements']))

    def test_resolution_hand_send_uses_distinct_main_copies_for_deck_summon(self):
        from unittest.mock import patch

        from ygo_kito.construction_inventory import InventoryDependencies
        from ygo_kito.construction_logic import LogicTag
        from tests.test_construction_binding import one_node

        self.assets.rows[1].update(type=33, level=8, name='匿名主题发动者',
            desc='①：把这张卡从手卡送去墓地才能发动。选自己1张手卡送去墓地，'
                 '从卡组把1只8星以外的「匿名主题」怪兽特殊召唤。')
        self.assets.rows[2]['name'] = '匿名主题接收者'
        self.assets.rows[4].update(type=0x800021, name='匿名主题超量',
                                  desc='4星怪兽×2\n①：自己主要阶段才能发动。抽1张。')
        catalog = CatalogBindingAdapter(self.assets).semantic_catalog
        record, = catalog.effect_records(1)
        send, summon = record['operations']
        self.assertEqual(summon['depends_on'], [send['block_id']])
        self.assertEqual(record['targets'], [])
        payment, = record['costs']
        self.assertEqual((payment['reason'], payment['from_zones']), ('cost', ['hand']))
        self.assertEqual((send['reason'], send['from_zones'], send['to_zone'], send['selector_query']),
                         ('effect', ['hand'], 'grave', {'selector': '卡'}))
        self.assertEqual(send['processing_role'], 'auxiliary')
        summary = catalog.mechanism_summary((1,))
        with patch('ygo_kito.effect_records._bind_hand_send_deck_summon'):
            prior_catalog = CatalogBindingAdapter(self.assets).semantic_catalog
            self.assertEqual(summary, prior_catalog.mechanism_summary((1,)))
        dependencies = InventoryDependencies(catalog)
        specs, _ = dependencies.specs(1)
        self.assertEqual([r['origin'] for r in specs[0]['requirements']], ['hand', 'hand', 'deck'])
        graph = one_node(LogicTag('effect_type', 'special_summon'))
        node, = graph.nodes

        for deck, expected in (
            (DeckParts((1,)), False),
            (DeckParts((1, 1, 1)), False),
            (DeckParts((1, 2)), False),
            (DeckParts((1, 2), (4,)), False),
            (DeckParts((1, 2), (), (3,)), False),
            (DeckParts((1, 3), (), (2,)), False),
            (DeckParts((1, 1, 2)), True),
            (DeckParts((1, 2, 2)), True),
            (DeckParts((1, 2, 3)), True),
        ):
            with self.subTest(deck=deck):
                diagnostics = dependencies.evaluate(deck, graph, codes=(1,))
                stock, scoped = diagnostics['cards']['1']['effects']
                expected_stock = 'inventory_present' if expected else 'missing'
                self.assertEqual(stock['status'], expected_stock)
                self.assertEqual(stock['shortfall'], scoped['shortfall'])
                self.assertEqual(scoped['nodes'], [node.node_id])
                self.assertEqual(scoped['status'], expected_stock)
                self.assertEqual(dependencies.function_missing(diagnostics, 1, node.node_id), not expected)
                facts, quality = self.evaluate(deck)
                resident = [u for u in facts['uses'] if u.scope_id == 'resident' and u.contributes
                            and facts['use_details'][u.use_id]['card_id'] == 1]
                use, = resident
                detail = facts['use_details'][use.use_id]
                self.assertEqual(detail['operation']['kind'], 'special_summon')
                self.assertEqual(detail['processing_prerequisites'], [send])
                self.assertEqual(detail['inventory_checks']['processing']['status'], expected_stock)
                self.assertEqual(support_state(use.self_condition, facts['variables']), expected)
                self.assertTrue(quality['complete'], quality['unknowns'])

        self.assets.rows[1]['desc'] = self.assets.rows[1]['desc'].replace(
            '特殊召唤。', '特殊召唤（这只怪兽不能攻击）。')
        record, = CatalogBindingAdapter(self.assets).semantic_catalog.effect_records(1)
        self.assertFalse(any(op.get('processing_role') == 'auxiliary' for op in record['operations']))

    def test_ordered_hand_send_deck_summon_uses_common_movement_and_reserves_the_source(self):
        from ygo_kito.construction_inventory import InventoryDependencies

        self.assets.rows[1].update(type=33, level=8, name='匿名主题发动者')
        self.assets.rows[2]['name'] = '匿名主题接收者'
        for head in ('自己主要阶段才能发动。', '支付500基本分才能发动。'):
            with self.subTest(head=head):
                self.assets.rows[1]['desc'] = (
                    '①：' + head + '从手卡把1张卡送去墓地。那之后，从卡组把1只'
                    '8星以外的「匿名主题」怪兽特殊召唤。')
                catalog = CatalogBindingAdapter(self.assets).semantic_catalog
                record, = catalog.effect_records(1)
                send, summon = record['operations']
                self.assertEqual(send.get('processing_role'), 'auxiliary')
                self.assertEqual(summon.get('depends_on'), [send['block_id']])
                inventory = InventoryDependencies(catalog)
                for hand, side, status in (((1, 2), (), 'missing'),
                                           ((1, 2), (1,), 'missing'),
                                           ((1, 1, 2), (), 'inventory_present')):
                    deck = DeckParts(hand, (), side)
                    detail, = inventory.evaluate(deck, codes=(1,))['cards']['1']['effects']
                    self.assertEqual(detail['status'], status)
                    self.assertEqual(inventory.processing_check(deck, record, summon)['status'], status)

    def test_replacing_resolution_hand_send_affects_deck_summon_in_required_order(self):
        from ygo_kito.construction_relations import JointConstraint

        self.assets.rows[1].update(type=33, desc='①：自己·对方回合，自己墓地没有卡存在的场合，'
            '把这张卡从手卡送去墓地才能发动。'
            '直到下个回合的结束时，被送去墓地的卡不去墓地而除外。')
        self.assets.rows[2].update(type=4, desc='①：自己主要阶段，把墓地的这张卡除外才能发动。'
            '选自己1张手卡送去墓地，从卡组把1只「匿名主题」怪兽特殊召唤。')
        self.assets.rows[3]['name'] = '匿名主题接收者'
        deck = DeckParts((1, 2, 3, 4))
        facts, _ = self.evaluate(deck)
        self.assertEqual(self.state(facts, 2), [True])
        ids = {d['card_id']: uid for uid, d in facts['use_details'].items() if d['card_id'] in (1, 2)}
        summon = facts['use_details'][ids[2]]
        self.assertEqual([cost['kind'] for cost in summon['costs']], ['banish'])
        uses = tuple(UseRequirement(str(code), InputGroup('all', (Need(str(code), Resource(
            'functional_operation', attributes=(facts['use_details'][ids[code]]['relation_fact_id'],)),
            mode='presence'),)), 'required joint processing', functional_use_ids=(ids[code],)) for code in (1, 2))
        for before, failed in ((('1', '2'), True), (('2', '1'), False)):
            with self.subTest(before=before):
                context = SimpleNamespace(relations=RelationContext(uses, constraints=(
                    JointConstraint('required_order', before, 'before', 'original required order'),)))
                _, quality = self.evaluate(deck, context=context)
                self.assertTrue(quality['complete'], quality['unknowns'])
                self.assertEqual(any(r['status'] == 'failed' and r['requirement_id'].startswith('restriction_order:')
                                     for r in quality['hard_requirements']), failed)

    def test_aramesir_whole_turn_lock_distinguishes_normal_field_and_special_entry(self):
        self.assets.rows[1].update(type=2,desc='这个卡名的卡在1回合只能发动1张，'
            '这张卡发动的回合，自己不能把特殊召唤的怪兽以外的场上的怪兽的效果发动。'
            '①：自己场上没有「匿名衍生物」存在的场合才能发动。'
            '在自己场上把1只「匿名衍生物」（天使族·地·4星·攻/守2000）特殊召唤。')
        self.assets.rows[2].update(type=33,desc='①：自己主要阶段才能发动。抽1张。')
        without, quality=self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        checks=[c for d in without['use_details'].values() for c in d.get('restriction_checks',())]
        self.assertTrue(any(c['status']=='mapped' and c['affected_use_ids'] for c in checks))
        score=quality['score']['value']
        self.assets.rows[3].update(type=2,desc='①：从自己手卡把1只怪兽特殊召唤。')
        with_entry, quality=self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        target=[d for d in with_entry['use_details'].values() if d['card_id']==2]
        self.assertTrue(target[0]['special_summon_supported'])
        self.assertGreater(quality['score']['value'],score)

    def test_excavation_default_entry_scores_one_addition_and_one_damage_modifier(self):
        self.assets.rows[1].update(type=2,desc='这个卡名的卡在1回合只能发动1张，'
            '这张卡发动的回合，自己不能用卡的效果抽卡。'
            '①：从额外卡组把3张或6张卡里侧除外才能发动。'
            '把除外数量的卡从自己卡组上面翻开，从那之中选1张加入手卡，'
            '剩下的卡用喜欢的顺序回到卡组下面。'
            '这张卡的发动后，直到回合结束时对方受到的全部伤害变成一半。')
        for code in range(101,107):
            self.assets.rows[code]=dict(self.assets.rows[2],id=code,type=0x41,desc='怪兽2只')
        deck=replace(self.deck,extra=tuple(range(101,107)))
        facts, quality=self.evaluate(deck)
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(facts,1),[True]*4)
        self.assertEqual(len({u.score_family_id for u in facts['uses'] if u.contributes}),2)
        self.assertTrue(all(not d['operation'] or d['operation']['kind'] not in ('banish','return_deck','reveal_deck','damage')
            for d in facts['use_details'].values()))
        missing, quality=self.evaluate(replace(deck,extra=deck.extra[:2]))
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(missing,1),[False]*4)

    def test_counted_attack_checks_potential_tuners_without_asserting_random_hits(self):
        self.assets.rows[1].update(type=33,desc='①：1回合1次，可以发动。'
            '从自己卡组上面翻开5张并回到卡组。'
            '这个回合这张卡可以作出最多有所翻开之中的调整数量的攻击。')
        absent, quality=self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(absent,1),[False])
        self.assets.rows[3]['type']=0x1011
        possible, quality=self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(possible,1),[True])

    def test_other_card_excludes_source_entity_but_allows_another_same_name_copy(self):
        for code in self.assets.rows:self.assets.rows[code]['name']='普通库存'+str(code)
        self.assets.rows[1].update(type=33,name='匿名使者',desc='①：从手卡把1张其他的「匿名」卡送去墓地才能发动。'
            '这张卡从手卡特殊召唤。')
        deck = self.deck
        alone, quality = self.evaluate(deck)
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(alone,1),[False])
        paired, quality = self.evaluate(replace(deck,main=tuple(1 if c==2 else c for c in deck.main)))
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(paired,1),[True])

    def test_payment_name_comparison_rejects_same_names_and_accepts_other_names(self):
        for code in self.assets.rows:self.assets.rows[code]['name']='普通库存'+str(code)
        self.assets.rows[1].update(type=33,name='匿名使者',desc='①：可以从以下效果选择1个发动。'
            '●从手卡把1只「匿名」怪兽送去墓地才能发动。从自己墓地选和那只怪兽卡名不同的1只「匿名」怪兽加入手卡。'
            '●从自己墓地把1只「匿名」怪兽除外才能发动。和那只怪兽卡名不同的1只「匿名」怪兽从卡组送去墓地。')
        deck = self.deck
        same, quality = self.evaluate(deck)
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(same,1),[False,False])
        self.assets.rows[2]['name']='匿名支付'
        insufficient, quality=self.evaluate(deck)
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(insufficient,1),[False,False])
        self.assets.rows[3]['name']='匿名目标'
        different, quality = self.evaluate(deck)
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(different,1),[True,True])

    def test_generated_token_needs_no_deck_copy_but_optional_placement_needs_stock(self):
        self.assets.rows[1].update(type=2,desc='①：自己场上没有「匿名衍生物」存在的场合才能发动。'
            '在自己场上把1只「匿名衍生物」（天使族·地·4星·攻/守2000）特殊召唤。'
            '自己场上没有「匿名旅程」存在的场合，可以再从卡组把1张「匿名旅程」'
            '在自己的魔法与陷阱区域表侧表示放置。')
        missing, quality = self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(missing,1),[True,False])
        self.assets.rows[2]['name']='匿名旅程'
        present, quality = self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(present,1),[True,True])

    def test_effect_local_counters_and_opponent_response_reach_default_evaluation(self):
        self.assets.rows[1].update(type=33,desc='①：1回合1次，要让场上的卡破坏的效果的发动时才能发动。'
            '那个效果无效并破坏。②：1回合1次，对方的攻击宣言时以攻击怪兽为对象才能发动。'
            '场上的这张卡除外，那次攻击无效。③：这个②的效果除外的回合的结束阶段发动。'
            '这张卡特殊召唤。')
        facts, quality = self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertTrue(all(self.state(facts,1)),facts['use_details'])
        self.assets.rows[1]['desc']='③：这个②的效果除外的回合的结束阶段发动。这张卡特殊召唤。'
        missing, quality = self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(missing,1),[False])

    def test_f03_optional_after_activation_uses_need_no_actual_order(self):
        self.assets.rows[1].update(type=2, desc='①：抽1张。这个效果发动后，自己不能特殊召唤。')
        self.assets.rows[2].update(type=2, desc='①：从自己手卡把1只怪兽特殊召唤。')
        facts, quality = self.evaluate()
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertEqual(self.state(facts, 1), [True])
        self.assertEqual(self.state(facts, 2), [True])

    def test_extra_payment_choices_reach_default_evaluation_with_actual_stock(self):
        self.assets.rows[1].update(type=2, desc='①：自己主要阶段1开始时，'
            '把自己的额外卡组3张或6张里侧的卡随机里侧除外才能发动。'
            '除外的卡每有3张，自己抽1张。这张卡的发动后，直到回合结束时自己不能用卡的效果抽卡。')
        for code in range(101,107):
            self.assets.rows[code] = dict(self.assets.rows[2], id=code, type=0x41, desc='怪兽2只')
        deck = replace(self.deck, extra=tuple(range(101,107)))
        facts, quality = self.evaluate(deck)
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertEqual(self.state(facts,1), [True,True])
        self.assertEqual(len({u.score_family_id for u in facts['uses'] if u.contributes}), 1)
        supported, partial = self.evaluate(replace(deck, extra=deck.extra[:3]))
        self.assertEqual(self.state(supported,1), [True,False])
        self.assertEqual(quality['score']['value'], partial['score']['value'])
        failed, missing = self.evaluate(replace(deck, extra=deck.extra[:2]))
        self.assertEqual(self.state(failed,1), [False,False])
        self.assertTrue(missing['complete'])
        self.assertEqual(missing['score']['value'], 0)

    def test_effect_fusion_needs_an_eligible_target_without_invented_materials(self):
        self.assets.rows[1].update(type=2, desc='这个卡名的卡在1回合只能发动1张。'
            '①：支付1000基本分才能发动。把1只5星以下的融合怪兽当作融合召唤从额外卡组特殊召唤。'
            '这个效果特殊召唤的怪兽不能攻击，结束阶段破坏。')
        self.assets.rows[101] = dict(self.assets.rows[2], id=101, type=0x41, level=5,
            desc='「不存在的素材」＋「另一只不存在的素材」')
        facts, quality = self.evaluate(replace(self.deck,extra=(101,)))
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertEqual(self.state(facts,1), [True])
        self.assertEqual(len([u for u in facts['uses'] if u.contributes]), 1)
        self.assets.rows[101]['level'] = 6
        failed, quality = self.evaluate(replace(self.deck,extra=(101,)))
        self.assertEqual(self.state(failed,1), [False])
        self.assertTrue(quality['complete'])

    def test_after_lock_joint_order_and_whole_turn_are_distinct(self):
        from ygo_kito.construction_relations import JointConstraint
        self.assets.rows[1].update(type=2, desc='①：抽1张。这个效果发动后，自己不能特殊召唤。')
        self.assets.rows[2].update(type=2, desc='①：从自己手卡把1只怪兽特殊召唤。')
        initial, _ = self.evaluate()
        ids = {initial['use_details'][u.use_id]['card_id']:u.use_id for u in initial['uses'] if u.contributes}
        requirements = tuple(UseRequirement('required:'+str(c), InputGroup('all', (Need('required:'+str(c),
            Resource('functional_operation', attributes=(f'catalog:{c}:1:op:0',)), mode='presence'),)),
            'original joint requirement', functional_use_ids=(ids[c],)) for c in (1,2))
        context = SimpleNamespace(relations=RelationContext(requirements))
        _, arranged = self.evaluate(context=context)
        self.assertTrue(arranged['complete'], arranged['unknowns'])
        self.assertTrue(all(r['status']=='satisfied' for r in arranged['hard_requirements']))
        context.relations = replace(context.relations, constraints=(JointConstraint('forced',
            ('required:1','required:2'), 'before', 'original required dependency'),))
        _, impossible = self.evaluate(context=context)
        self.assertTrue(impossible['complete'])
        self.assertTrue(any(r['status']=='failed' for r in impossible['hard_requirements']))
        self.assets.rows[1]['desc'] = '①：抽1张。发动这个效果的回合，自己不能特殊召唤。'
        _, whole = self.evaluate()
        self.assertTrue(whole['complete'],whole['unknowns'])
        self.assertLess(whole['score']['value'], arranged['score']['value'])

    def test_whole_turn_lock_filters_the_summon_objects_before_pricing(self):
        self.assets.rows[1].update(type=2, desc='①：抽1张。这个回合，自己若非等级或者阶级是3以上的怪兽则不能特殊召唤。')
        self.assets.rows[2].update(type=2, desc='①：从自己手卡把1只怪兽特殊召唤。')
        for code in range(3,16):
            self.assets.rows[code]['level'] = 2
        self.assets.rows[4]['level'] = 4
        facts, supported = self.evaluate()
        self.assertEqual(self.state(facts, 2), [True])
        self.assertTrue(supported['complete'], supported['unknowns'])
        self.assertEqual(supported['stages']['V2'], supported['stages']['S'])
        self.assets.rows[4]['level'] = 2
        facts, prohibited = self.evaluate()
        self.assertEqual(self.state(facts, 2), [True])
        self.assertTrue(prohibited['complete'], prohibited['unknowns'])
        self.assertLess(prohibited['stages']['S']['lower'], prohibited['stages']['V2']['lower'])

    def test_unparsed_rule_is_shared_and_its_application_binds_each_inventory(self):
        self.assets.rows[1].update(type=33, desc='①：自己主要阶段，自己拥有未知计数的场合才能发动。'
            '抽1张。从自己卡组上面把1张卡送去墓地。')
        first, quality = self.evaluate()
        second, other = self.evaluate(self.decks[2])
        self.assertEqual(self.state(first, 1), [None, None])
        self.assertEqual(self.state(second, 1), [None, None])
        self.assertEqual(len(quality['unknowns']), 2)
        common = set(quality['unknowns']) & set(other['unknowns'])
        self.assertEqual(len(common), 1)
        self.assertIn('activation_condition_unparsed', next(iter(common)))
        for evaluation in (quality, other):
            local, = set(evaluation['unknowns']) - common
            self.assertIn(evaluation['deck_sha256'], local)
            self.assertEqual(evaluation['fact_details'][local]['reason_code'], 'catalog_clause_applicability')

    def test_optional_mutual_locks_fail_only_when_both_uses_are_required(self):
        self.assets.rows[1].update(type=2, desc='①：抽1张。这个效果发动后，自己不能特殊召唤。')
        self.assets.rows[2].update(type=2, desc='①：从自己手卡把1只怪兽特殊召唤。这个效果发动后，自己不能抽卡。')
        initial, optional = self.evaluate()
        self.assertTrue(optional['complete'], optional['unknowns'])
        ids = {initial['use_details'][u.use_id]['card_id']:u.use_id for u in initial['uses'] if u.contributes}
        required = tuple(UseRequirement('required:'+str(c), InputGroup('all', (Need('required:'+str(c),
            Resource('functional_operation', attributes=(f'catalog:{c}:1:op:0',)), mode='presence'),)),
            'original mandatory combination', functional_use_ids=(ids[c],)) for c in (1,2))
        _, joint = self.evaluate(context=SimpleNamespace(relations=RelationContext(required)))
        self.assertTrue(joint['complete'], joint['unknowns'])
        self.assertTrue(any(r['requirement_id'].startswith('restriction_order:') and r['status']=='failed'
            for r in joint['hard_requirements']))

    def test_opponents_lock_does_not_remove_own_configuration_use(self):
        self.assets.rows[1].update(type=2, desc='①：抽1张。发动这个效果的回合，对方不能特殊召唤。')
        self.assets.rows[2].update(type=2, desc='①：从自己手卡把1只怪兽特殊召唤。')
        _, quality = self.evaluate()
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertEqual(quality['losses'][2]['upper'], 0)

    def test_entity_and_effect_timing_limits_do_not_create_global_impacts(self):
        self.assets.rows[1].update(type=33,
            desc='这张卡不能通常召唤。①：自己主要阶段才能发动。抽1张。')
        self.assets.rows[2].update(type=33, desc='①：把墓地的这张卡除外才能发动。'
            '抽1张。这个效果在这张卡送去墓地的回合不能发动。')
        self.assets.rows[3].update(type=2, desc='①：从自己手卡把1只怪兽特殊召唤。')
        facts, quality = self.evaluate()
        checks = [check for detail in facts['use_details'].values() if detail['card_id'] in (1, 2)
                  for check in detail['restriction_checks']]
        self.assertTrue(checks)
        self.assertEqual({check['restriction']['kind'] for check in checks},
            {'cannot_normal_summon_this_card', 'own_effect_activation_timing'})
        self.assertTrue(all(not check['affected_use_ids'] for check in checks))
        self.assertNotIn('impacts', quality['deferred'])
        self.assertFalse(facts['impacts'])

    def test_affected_battle_monster_and_trap_monster_lifecycle_stay_local(self):
        self.assets.rows[1].update(type=4, desc='这个卡名的②的效果1回合只能使用1次。'
            '①：对方怪兽进行战斗的攻击宣言时才能发动。'
            '那只对方怪兽攻击力变成0，不能把表示形式变更，效果无效化。'
            '②：把墓地的这张卡除外才能发动。从卡组把1只5星以上的水属性怪兽送去墓地。'
            '那之后，可以从自己墓地选1只水属性怪兽加入手卡。'
            '这个效果的发动后，直到下次的自己回合的结束时自己不是水属性怪兽不能特殊召唤。')
        self.assets.rows[2].update(type=4, desc='①：从卡组把1张陷阱卡送去墓地。'
            '②：陷阱卡发动时，连锁那个发动才能把这个效果在墓地发动。'
            '这张卡变成通常怪兽（水族·水·2星·攻1200/守0）在怪兽区域特殊召唤（不当作陷阱卡使用）。'
            '这个效果特殊召唤的这张卡不受怪兽的效果影响，从场上离开的场合除外。')
        self.assets.rows[3].update(attribute=2, level=5)
        facts, quality = self.evaluate()
        self.assertNotIn('impacts', quality['deferred'])
        details = [d for d in facts['use_details'].values() if d['card_id'] in (1, 2)]
        checks = [check for detail in details for check in detail['restriction_checks']]
        local = {'cannot_change_position', 'effect_exemption', 'leave_field_banish'}
        self.assertEqual({c['restriction']['kind'] for c in checks if c['status']=='result_entity_restriction'}, local)
        self.assertTrue(all(not c['affected_use_ids'] for c in checks if c['restriction']['kind'] in local))
        ice = [d['operation']['kind'] for d in details if d['card_id'] == 1]
        self.assertIn('search_or_recover', ice)
        trap = next(e['record'] for e in facts['coverage_details']['main:2']['effects'] if e['record']['effect_index']==2)
        self.assertEqual(trap['trigger']['chain_relation'], 'direct_response')
        summons, = [op for op in trap['operations'] if op['kind'] == 'special_summon']
        self.assertEqual(summons['result_entity']['race'], 64)
        self.assertEqual(summons['from_zones'], ['grave'])
        banish, = [op for op in trap['operations'] if op['kind'] == 'banish']
        self.assertEqual((banish['phase'], banish['subject_ref']), ('replacement', summons['block_id']))
        self.assertFalse(any(d['operation']['kind'] == 'banish' for d in details if d['card_id'] == 2))
        from ygo_kito.construction_relations import _restriction_contract
        water = next(c['restriction'] for c in checks if c['restriction']['kind'] == 'cannot_special_summon')
        self.assertEqual(_restriction_contract(water)['duration'], 'next_own_turn_end')

    def test_extra_machine_xyz_exception_and_opponent_grave_lock(self):
        from ygo_kito.construction_layer_flow import _restriction_match
        from ygo_kito.construction_relations import _restriction_contract

        self.assets.rows[1].update(type=2, desc='①：抽1张。这个效果的发动后，直到回合结束时'
            '自己不是机械族超量怪兽不能从额外卡组特殊召唤。')
        self.assets.rows[2].update(type=2, desc='①：抽1张。这个回合，对方不能把墓地的卡的效果发动。')
        catalog = CatalogBindingAdapter(self.assets).semantic_catalog
        extra, = [r for r in catalog.effect_records(1)[0]['restrictions']]
        extra = _restriction_contract(extra)
        self.assertEqual(extra['from_zones'], ['extra'])

        def blocked(zone, monster_type, race):
            detail = dict(card_id=3, semantics=dict(kind='special_summon', from_zones=[zone]),
                operation=dict(source='这张卡特殊召唤'), summoned_card_ids=(3,))
            return _restriction_match(extra, detail, {'3': dict(type=monster_type, race=race)})
        self.assertFalse(blocked('hand', 33, 64))
        self.assertFalse(blocked('extra', 0x800001, 32))
        self.assertTrue(blocked('extra', 0x800001, 64))
        self.assertTrue(blocked('extra', 0x41, 32))
        facts, quality = self.evaluate()
        self.assertNotIn('impacts', quality['deferred'])
        opponent, = {c['status'] for d in facts['use_details'].values() if d['card_id'] == 2
                     for c in d['restriction_checks'] if c['restriction']['kind'] == 'cannot_activate'}
        self.assertEqual(opponent, 'outside_affected_uses')

    def test_legacy_equipment_uses_configured_receiver_without_current_board(self):
        self.assets.rows[1].update(type=0x40002, desc='名字带有「匿名」的4星的怪兽才能装备。'
            '装备怪兽的原本攻击力变成2倍。发动后第2次的自己的准备阶段时这张卡破坏，'
            '自己受到装备怪兽的原本攻击力数值的伤害。')
        facts, quality = self.evaluate()
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertEqual(self.state(facts,1), [True])
        for row in self.assets.rows.values():row['name']='其他怪兽'
        missing, quality = self.evaluate()
        self.assertEqual(self.state(missing,1), [False])
        self.assertTrue(quality['complete'])

    def setUp(self):
        self.task, self.assets, _, _, self.decks, self.policy = fixture()
        for code, row in self.assets.rows.items():
            row.update(type=17, level=4, desc='普通怪兽。', name='匿名'+str(code))
        self.deck = self.decks[1]

    def evaluate(self, deck=None, context=None):
        deck = deck or self.deck
        catalog = CatalogBindingAdapter(self.assets).semantic_catalog
        facts = normalize_function_uses(self.task, deck, catalog, policy=self.policy, context=context)
        quality = evaluate_functional_quality(dict(axis=dict(task=self.task.to_dict(), inventory=deck.to_dict(), logic=None)),
            policy=self.policy, facts=facts)
        return facts, quality

    def state(self, facts, code):
        return [support_state(u.self_condition, facts['variables']) for u in facts['uses']
                if u.contributes and facts['use_details'][u.use_id]['card_id'] == code]

    def test_default_spell_and_normal_summoned_phase_reach_evaluation(self):
        self.assets.rows[1].update(type=2, desc='①：抽1张。')
        self.assets.rows[2].update(type=33, desc='①：自己主要阶段才能发动。抽1张。')
        facts, quality = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True])
        self.assertEqual(self.state(facts, 2), [True])
        self.assertTrue(quality['complete'])
        self.assertGreater(quality['score']['value'], 0)

    def test_default_normal_entries_preserve_joint_summon_capacity(self):
        for code in (1, 2):
            self.assets.rows[code].update(type=33, desc='①：这张卡召唤成功的场合才能发动。抽1张。')
        facts, _ = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True])
        self.assertEqual(self.state(facts, 2), [True])
        requested = tuple(UseRequirement('required:'+str(c), InputGroup('all', (Need('required:'+str(c),
            Resource('functional_operation', attributes=('catalog:'+str(c)+':1:op:0',)), mode='presence'),)),
            'explicit same-turn requirement', functional_use_ids=tuple(u.use_id for u in facts['uses']
                if facts['use_details'][u.use_id]['card_id'] == c)) for c in (1, 2))
        joint, quality = self.evaluate(context=SimpleNamespace(relations=RelationContext(requested)))
        self.assertTrue(any(h['requirement_id'] == 'joint_required' and h['condition'] is False
                            for h in joint['hard_requirements']))
        self.assertTrue(any(h['status'] == 'failed' for h in quality['hard_requirements']))

    def test_default_payment_checks_actual_stock_and_missing_support(self):
        self.assets.rows[1].update(type=2, desc='①：从自己卡组把1张「匿名2」送去墓地才能发动。抽1张。')
        facts, good = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True])
        absent = replace(self.deck, main=tuple(3 if c == 2 else c for c in self.deck.main))
        failed, bad = self.evaluate(absent)
        self.assertEqual(self.state(failed, 1), [False])
        self.assertLess(bad['score']['upper'], good['score']['value'])

    def test_default_external_target_is_scoped_to_its_configuration_purpose(self):
        self.assets.rows[1].update(type=2, desc='①：以对方场上1只怪兽为对象才能发动。那只怪兽破坏。')
        facts, quality = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True])
        self.assertTrue(quality['complete'])
        detail = next(v for v in facts['use_details'].values() if v['card_id'] == 1)
        self.assertTrue(any('configuration purpose' in s for s in detail['relation']['conditions']))

    def test_summon_procedure_supports_later_use_without_a_scoring_use(self):
        self.assets.rows[1].update(type=33, level=7,
            desc='①：对方场上的怪兽数量比自己场上的怪兽多的场合，这张卡可以从手卡特殊召唤。'
                 '②：自己主要阶段才能发动。抽1张。')
        facts, quality = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True])
        self.assertTrue(quality['complete'])
        self.assertEqual(len([u for u in facts['uses'] if u.contributes]), 1)

    def test_hand_and_random_deck_transfers_match_grave_uses_without_a_duel_state(self):
        self.assets.rows[1].update(type=33, desc='①：自己主要阶段才能发动。这张卡从手卡特殊召唤，'
            '从自己手卡选1只怪兽送去墓地。那之后，从自己卡组上面把3张卡送去墓地。')
        self.assets.rows[2].update(type=33, desc='①：这张卡被效果送去墓地的场合才能发动。自己抽1张。')
        facts, quality = self.evaluate()
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertEqual(self.state(facts, 1), [True, True, True])
        self.assertEqual(self.state(facts, 2), [True])
        self.assertTrue(all(not v['costs'] for v in facts['use_details'].values()))
        for detail in facts['use_details'].values():
            self.assertFalse(any('random_recipient' in s for s in detail['relation']['unknown']))
        # Random milling alone is compatible support, never a specific call.
        self.assets.rows[1]['desc']='①：自己主要阶段才能发动。从自己卡组上面把3张卡送去墓地。'
        random_facts, random_quality = self.evaluate()
        self.assertTrue(random_quality['complete'])
        self.assertTrue(all(u.valuation_mode=='main_density' for u in random_facts['uses']))

    def test_selected_hand_discard_reserves_a_different_physical_card(self):
        self.assets.rows[1].update(type=33, race=4, attribute=1, desc=
            '①：从手卡丢弃1只其他的天使族·地属性怪兽才能发动。这张卡从手卡特殊召唤。')
        self.assets.rows[2].update(race=4, attribute=1)
        self.assets.rows[3].update(race=4, attribute=2)
        self.assets.rows[4].update(race=2, attribute=1)
        for main, supported in (((1,), False), ((1, 3, 4), False), ((1, 2), True), ((1, 1), True)):
            with self.subTest(main=main):
                facts, _ = self.evaluate(DeckParts(main))
                self.assertEqual(self.state(facts, 1), [supported])
                detail, = [value for value in facts['use_details'].values() if value['card_id'] == 1]
                requirement, = detail['inventory_checks']['costs']['requirements']
                self.assertEqual(requirement['origin'], 'hand')
                self.assertEqual(requirement['source_card_id'], 1)
                self.assertTrue(requirement['exclude_source_copy'])
                if supported:
                    self.assertEqual(requirement['confirmed_available'], 1)
                    usage = detail['relation']['usage']
                    self.assertTrue(any(token.startswith('activation:') for token in usage['configuration:physical:1']))

    def test_choice_target_and_cost_do_not_leak_to_another_option(self):
        self.assets.rows[1].update(type=2, desc='从以下效果选择1个发动。'
            '\n●以自己墓地1只「不存在」怪兽为对象才能发动。那只怪兽加入手卡。'
            '\n●自己抽1张。')
        facts, quality = self.evaluate()
        values = {facts['use_details'][u.use_id]['operation']['choice']:support_state(u.self_condition, facts['variables'])
                  for u in facts['uses'] if u.contributes}
        self.assertEqual(values, {'option:1':False, 'option:2':True})
        self.assertTrue(quality['complete'], quality['unknowns'])

    def test_multi_zone_payment_counts_distinct_cards_once(self):
        self.assets.rows[1].update(type=2, desc='①：把自己手卡·墓地的2张「匿名2」卡除外才能发动。抽1张。')
        facts, _ = self.evaluate()
        self.assertEqual(self.state(facts, 1), [False])
        enough=replace(self.deck, main=tuple(self.deck.main)+(2,))
        facts, quality=self.evaluate(enough)
        self.assertEqual(self.state(facts, 1), [True])
        self.assertTrue(quality['complete'], quality['unknowns'])

    def test_complex_trigger_checks_configuration_presence_without_a_board(self):
        self.assets.rows[1].update(type=4, desc='①：场上有怪兽召唤·特殊召唤的场合，'
            '若自己场上有「匿名2」存在则能发动。从自己卡组上面把3张卡送去墓地。')
        facts, quality=self.evaluate()
        self.assertEqual(self.state(facts, 1), [True])
        self.assertTrue(quality['complete'], quality['unknowns'])
        absent=replace(self.deck,main=tuple(3 if c==2 else c for c in self.deck.main))
        facts, _=self.evaluate(absent)
        self.assertEqual(self.state(facts, 1), [False])

    def test_fusion_uses_complete_distinct_materials_including_its_source(self):
        for row in self.assets.rows.values():row['race']=2
        self.assets.rows[1].update(type=33,race=1,desc='①：这张卡被效果送去墓地的场合才能发动。'
            '融合怪兽卡决定的包含墓地的这张卡的融合素材怪兽从自己的手卡·场上·墓地用喜欢的顺序回到持有者卡组下面，'
            '把那1只融合怪兽从额外卡组融合召唤。')
        self.assets.rows[2]['race']=1
        self.assets.rows[101]=dict(self.assets.rows[3],id=101,name='匿名融合',type=0x41,desc='「匿名1」＋战士族怪兽')
        deck=replace(self.deck,extra=(101,))
        facts,quality=self.evaluate(deck)
        self.assertEqual(self.state(facts,1),[True,True])
        self.assertTrue(quality['complete'],quality['unknowns'])
        details=[v for v in facts['use_details'].values() if v['card_id']==1]
        self.assertTrue(all(v['inventory_checks']['fusion']['options'][0]['includes_card']==1 for v in details))
        absent=replace(deck,main=tuple(3 if c==2 else c for c in deck.main))
        failed,_=self.evaluate(absent)
        self.assertEqual(self.state(failed,1),[False,False])

    def test_normal_summon_prohibition_is_not_a_missing_board(self):
        self.assets.rows[1].update(type=33,desc='不能通常召唤。①：这张卡召唤成功的场合才能发动。抽1张。')
        facts,quality=self.evaluate()
        self.assertEqual(self.state(facts,1),[False])
        self.assertTrue(quality['complete'])

    def test_choice_payment_is_required_only_by_its_own_option(self):
        self.assets.rows[1].update(type=2,desc='从以下效果选择1个发动。'
            '\n●从自己卡组把1张「不存在」卡送去墓地才能发动。自己抽2张。'
            '\n●自己抽1张。')
        facts,quality=self.evaluate()
        values={facts['use_details'][u.use_id]['operation']['choice']:support_state(u.self_condition,facts['variables'])
            for u in facts['uses'] if u.contributes}
        self.assertEqual(values,{'option:1':False,'option:2':True})
        self.assertTrue(quality['complete'],quality['unknowns'])
        second=next(v for v in facts['use_details'].values() if v['card_id']==1 and v['operation']['choice']=='option:2')
        self.assertFalse(second['costs'])

    def test_unparsed_condition_is_a_program_gap_and_is_not_forced_true(self):
        self.assets.rows[1].update(type=33,desc='①：自己主要阶段，自己拥有未知计数的场合才能发动。抽1张。')
        facts,quality=self.evaluate()
        self.assertEqual(self.state(facts,1),[None])
        self.assertFalse(quality['complete'])
        reasons=[v['reason_code'] for v in facts['fact_details'].values()]
        self.assertTrue(any('activation_condition' in s for s in reasons))

    def test_default_candidate_adapter_consumes_static_applicability(self):
        from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
        from ygo_kito.construction_logic import LogicTag
        from tests.test_construction_binding import one_node
        from tests.test_construction_layer_flow import rows_for
        self.assets.rows[1].update(type=33,desc='①：自己主要阶段才能发动。从自己卡组上面把3张卡送去墓地。')
        graph=one_node(LogicTag('effect','卡组送墓'))
        binder=CatalogBindingAdapter(self.assets)
        _,evaluated,_=ConstructionLayerAdapter(binder).evaluate(self.task,graph,rows_for(self.task,[self.deck]),
            {0:binder(graph,self.task,self.deck)},[0],policy=self.policy)
        candidate=evaluated[0]
        self.assertTrue(candidate['quality_evaluation']['complete'])
        self.assertGreater(candidate['quality_evaluation']['score']['value'],0)
        self.assertFalse('host_condition_unspecified' in str(candidate['layer_evaluation']))

    def test_odd_eyes_seer_position_options_reach_static_coverage(self):
        from ygo_kito.construction_inventory import InventoryDependencies
        from ygo_kito.construction_relations import _record_facts

        self.assets.rows[1].update(type=0x1000021, name='娱乐伙伴 异色眼祭司',
            desc=('←1 【灵摆】 1→\r\n这个卡名的灵摆效果1回合只能使用1次。\r\n'
                  '①：以自己墓地1张「娱乐伙伴」卡或者「异色眼」卡为对象才能发动。那张卡加入手卡。那之后，这张卡破坏。\r\n'
                  '【怪兽效果】\r\n这个卡名的怪兽效果1回合只能使用1次。\r\n'
                  '①：灵摆召唤的这张卡在自己主要阶段可以把表示形式的以下效果发动。\r\n'
                  '●攻击表示：把这张卡除外，以自己墓地1只「娱乐伙伴」怪兽或者「异色眼」怪兽为对象才能发动。那只怪兽特殊召唤。\r\n'
                  '●守备表示：从卡组选1只「娱乐伙伴」灵摆怪兽或者「异色眼」灵摆怪兽表侧表示加入自己的额外卡组或送去墓地。'))
        self.assets.rows[2].update(type=0x1000021, name='娱乐伙伴 匿名怪兽')
        catalog = CatalogBindingAdapter(self.assets).semantic_catalog
        deps = InventoryDependencies(catalog)
        specs, _ = deps.specs(1)
        self.assertEqual([spec['unknown'] for spec in specs], [[], []])
        pendulum, monster = [spec['record'] for spec in specs]
        self.assertEqual([r['unknown'] for r in (pendulum, monster)], [[], []])
        self.assertEqual([r['count_limits'][0]['subject']['section'] for r in (pendulum, monster)],
            ['pendulum', 'monster'])
        self.assertEqual([r['count_limits'][0]['maximum'] for r in (pendulum, monster)], [1, 1])
        recovery, destruction = pendulum['operations']
        self.assertEqual(destruction['subject'], 'this_card')
        self.assertEqual(destruction['quantity'], 1)
        self.assertEqual(destruction['depends_on'], [recovery['block_id']])
        attack, to_extra, to_grave = monster['branch_records'].values()
        for branch in (attack, to_extra, to_grave):
            self.assertEqual(branch['trigger']['summon_kind'], 'pendulum_summon')
            self.assertEqual(branch['conditions']['status'], 'recognized')
            self.assertEqual(len(branch['operations']), 1)
        self.assertEqual(attack['trigger']['battle_position'], 'attack')
        payment, = attack['costs']
        self.assertEqual((payment['kind'], payment['subject'], payment['from_zones'], payment['source_card_id']),
            ('banish', 'this_card', ['field'], 1))
        self.assertEqual(attack['operations'][0]['target_ref'], 0)
        for branch, kind, destination in ((to_extra, 'add_extra', 'extra'), (to_grave, 'send_grave', 'grave')):
            self.assertEqual(branch['trigger']['battle_position'], 'defense')
            self.assertEqual((branch['targets'], branch['costs']), ([], []))
            operation, = branch['operations']
            self.assertEqual((operation['kind'], operation['from_zones'], operation['to_zone'], operation['quantity']),
                (kind, ['deck'], destination, 1))
            requirement = deps.item_requirement(operation, 'operations')
            self.assertEqual([p['type_all'] for p in requirement['query']['any']], [0x1000001, 0x1000001])
        self.assertTrue(to_extra['operations'][0]['face_up'])
        pools = [pool.pool_id for _, ps in _record_facts(1, (pendulum, monster), functional=True) for pool in ps]
        self.assertEqual([pool.rsplit(':', 1)[-1] for pool in pools], ['pendulum'] * 2 + ['monster'] * 3)

        facts, quality = self.evaluate()
        self.assertEqual(facts['coverage']['main:1'], 'evaluated')
        self.assertNotIn('main:1', quality['total']['partial_items'])

        self.assets.rows[1]['desc'] = self.assets.rows[1]['desc'].replace('●攻击表示：', '●攻击表示：符合未识别限制时，')
        _, monster = CatalogBindingAdapter(self.assets).semantic_catalog.effect_records(1)
        self.assertEqual(monster['branch_records']['option:1']['conditions']['status'], 'unknown')

    def test_unrecognized_choice_branch_is_not_lost_from_coverage(self):
        self.assets.rows[1].update(type=2,desc='从以下效果选择1个发动。\n●自己抽1张。\n●调整尚未识别的计数。')
        facts,quality=self.evaluate()
        self.assertFalse(quality['complete'])
        effect=facts['coverage_details']['main:1']['effects'][0]
        self.assertEqual(effect['status'],'unknown')
        self.assertIn('unrecognized_operation',effect['gaps'])
        self.assertIn('调整尚未识别的计数',effect['record']['source_text'])

    def test_shuffle_reborn_checks_one_resident_allocation_and_binds_its_own_payment(self):
        self.assets.rows[1].update(type=2, name='洗牌苏生',
            desc='这个卡名的②的效果1回合只能使用1次。\n'
                 '②：把墓地的这张卡除外，以自己场上1张卡为对象才能发动。'
                 '那张卡回到持有者卡组洗切，那之后自己从卡组抽1张。这个回合的结束阶段，自己1张手卡除外。')
        self.assets.rows[2].update(type=33, desc='①：把墓地的这张卡除外才能发动。自己抽1张。')
        catalog = CatalogBindingAdapter(self.assets).semantic_catalog
        work = {}
        facts = normalize_function_uses(self.task, self.deck, catalog, policy=self.policy, work_state=work)
        relation = work['projections']['resident']['relation']
        checks = [row for key, row in relation['uses'].items() if key.startswith('functional:catalog:1:2:')]
        self.assertTrue(checks)
        for row in checks:
            self.assertEqual(row['status'], 'supported', row['unknown'])
            witness, = row['branches']
            resources = [relation['resource_pools'][pid] for pid, claims in witness['usage'].items()
                if pid in relation['resource_pools'] and any(token.startswith('consume:effect:catalog:1:2:')
                for token in claims)]
            self.assertEqual([p['inventory'] for p in resources], [(('main', 1),)])
        self.assertTrue(all(state is True for state in self.state(facts, 1)))

    def test_complete_processing_cannot_reuse_only_hand_monster(self):
        for code, row in self.assets.rows.items():
            if code != 1:
                row.update(type=2, desc='')
        self.assets.rows[1].update(type=33, desc='①：自己主要阶段才能发动。'
            '这张卡从手卡特殊召唤，从自己手卡选1只怪兽送去墓地。')
        facts, _ = self.evaluate()
        self.assertEqual(self.state(facts, 1), [False, False])
        details = [v for v in facts['use_details'].values() if v['card_id']==1]
        self.assertTrue(all(v['inventory_checks']['processing']['status']=='missing' for v in details))
        second = replace(self.deck, main=(*self.deck.main[:-1], 1))
        supported, _ = self.evaluate(second)
        self.assertEqual(self.state(supported, 1), [True, True])

    def test_complete_processing_can_move_same_monster_to_its_next_origin(self):
        for code, row in self.assets.rows.items():
            if code != 1:
                row.update(type=2, desc='')
        self.assets.rows[1].update(type=33, desc='①：自己主要阶段才能发动。'
            '这张卡从手卡特殊召唤。那之后，从自己场上选1只怪兽送去墓地。')
        facts, _ = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True, True])

    def test_alternative_processing_keeps_independent_entities(self):
        self.assets.rows[1].update(type=2, desc='从以下效果选择1个发动。'
            '\n●从自己手卡选1只「匿名2」特殊召唤。'
            '\n●从自己手卡选1只「匿名2」送去墓地。')
        facts, _ = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True, True])
        self.assertEqual(self.deck.main.count(2), 1)

    def test_common_prefix_operation_cannot_recurse_through_options(self):
        self.assets.rows[1].update(type=2,desc='自己抽1张。从以下效果选择1个发动。'
            '\n●自己回复500基本分。\n●给与对方500伤害。')
        facts,quality=self.evaluate()
        self.assertTrue(any(v['card_id']==1 for v in facts['use_details'].values()))
        self.assertFalse(any('unscoped_choice_operation' in s for v in facts['use_details'].values()
            for s in v['relation']['unknown']))
        self.assertTrue(quality['complete'], quality['unknowns'])
        draws = [u for u in facts['uses'] if facts['use_details'][u.use_id]['card_id']==1
                 and facts['use_details'][u.use_id]['operation']['kind']=='draw']
        self.assertEqual(len(draws), 2)
        self.assertTrue(all(support_state(u.self_condition, facts['variables']) for u in draws))

    def test_unparsed_common_prefix_keeps_its_exact_coverage_gap(self):
        self.assets.rows[1].update(type=2,desc='调整尚未识别的计数。自己抽1张。从以下效果选择1个发动。'
            '\n●自己回复500基本分。\n●给与对方500伤害。')
        facts, quality = self.evaluate()
        self.assertTrue(any('unscoped_choice_operation' in s for v in facts['use_details'].values()
            for s in v['relation']['unknown']))
        self.assertFalse(quality['complete'])


if __name__ == '__main__':
    unittest.main()
