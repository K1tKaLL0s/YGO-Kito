"""Real clause shapes and anonymous variants; no model, CB or training."""
import unittest

from ygo_kito.effect_mechanisms import analyze_card, SEMANTIC_VERSION
from ygo_kito.effect_records import effect_records
from ygo_kito.construction_inventory import selector, matches


def row(text, *, code=1, **values):
    return dict(id=code,name='匿名怪兽',desc=text,type=33,alias=0,level=4,race=1,
        attribute=32,atk=1500,**values)


def records(text, **values):
    card=row(text,**values)
    return effect_records(analyze_card(card),semantic_version=SEMANTIC_VERSION,row=card)


class PublicTextCompletionTests(unittest.TestCase):
    def test_revealed_summon_reserves_the_source_and_requires_a_different_name(self):
        from types import SimpleNamespace
        from ygo_kito.build_contracts import DeckParts
        from ygo_kito.construction_inventory import InventoryDependencies
        from ygo_kito.effect_mechanisms import MechanismCatalog
        from ygo_kito.multifactor.contracts import AnalysisContext, DeckSpec, Factors, RoleInput
        from ygo_kito.multifactor.semantics import build_analysis_graph

        text = ('①：自己主要阶段才能发动。从手卡把1只1星「匿名系列」怪兽给对方观看，'
                '和给人观看的怪兽卡名不同的1张「匿名系列」卡从卡组除外。那之后，给人观看的怪兽召唤。'
                '②：对方对怪兽的召唤成功的场合才能发动。自己把1只「匿名系列」怪兽召唤。')
        assets = SimpleNamespace(receipt={'resources': {'cards': 'a'*64}}, rows={
            1: dict(row(text), type=0x80002, name='匿名系列地图'),
            2: dict(row('', code=2), level=1, name='匿名系列成员'),
            3: dict(row('', code=3), level=1, name='匿名系列同名处理', alias=2),
            4: dict(row('', code=4), type=4, name='匿名系列陷阱'),
        })
        catalog = MechanismCatalog(assets)
        first, second = catalog.effect_records(1)
        reveal, banish, summon = first['operations']
        self.assertEqual(reveal['processing_role'], 'auxiliary')
        self.assertEqual(first['trigger']['zone'], 'field')
        self.assertEqual(banish['different_name_from_reveal'], reveal['block_id'])
        self.assertEqual(summon['subject_ref'], reveal['block_id'])
        self.assertEqual(summon['depends_on'], [banish['block_id']])
        self.assertEqual((summon['kind'], summon['from_zones'], summon['to_zone']), ('normal_summon', ['hand'], 'field'))
        self.assertEqual(second['trigger']['controller'], 'opponent')
        self.assertEqual(second['operations'][0]['owner'], 'self')
        self.assertEqual(first['unknown'], [])
        inventory = InventoryDependencies(catalog)
        for deck, expected in ((DeckParts((1, 2, 3)), 'missing'), (DeckParts((1, 2, 4)), 'inventory_present'),
                               (DeckParts((1, 1, 2)), 'inventory_present')):
            with self.subTest(deck=deck):
                self.assertEqual(inventory.processing_check(deck, first, summon)['status'], expected)
        for pair, expected in ((((2, 1), (3, 1)), set()),
                               (((2, 1), (4, 1)), {(('card:1', 1), ('card:2', 1), ('card:4', 1))})):
            example = RoleInput('printed configuration', Factors('context'), (), analysis_mode='deck_analysis',
                analysis_context=AnalysisContext(), deck=DeckSpec(((1, 1), *pair), (), ()))
            built = build_analysis_graph(example, card_rows=assets.rows)
            self.assertEqual({axis.members for axis in built.candidates.candidates if axis.functions == ('banish', 'follow_up')}, expected)

    def test_effect_normal_summon_and_banished_recovery_keep_scoped_lock(self):
        from ygo_kito.construction_relations import _restriction_contract
        summon, continuous, recover = records('这个卡名的①③的效果1回合各能使用1次，'
            '这些效果发动的回合，自己不能把怪兽特殊召唤。'
            '①：这张卡召唤成功的场合才能发动。从卡组把1只4星以下的鸟兽族怪兽加入手卡。'
            '那之后，可以把1只鸟兽族怪兽召唤。②：表侧表示的这张卡从场上离开的场合除外。'
            '③：这张卡除外中的状态，自己场上有鸟兽族怪兽召唤的场合才能发动。这张卡加入手卡。')
        _, action = summon['operations']
        self.assertEqual((action['kind'], action['owner'], action['from_zones']), ('normal_summon', 'self', ['hand']))
        self.assertTrue(action['optional'])
        self.assertEqual(action['selector_query']['race'], 512)
        self.assertFalse(any(r['kind'] == 'cannot_special_summon' for r in continuous['restrictions']))
        for record in (summon, recover):
            rule = next(r for r in record['restrictions'] if r['kind'] == 'cannot_special_summon')
            self.assertTrue(_restriction_contract(rule)['whole_turn'])
        self.assertEqual(recover['trigger']['event'], 'own_monster_normal_summon')
        self.assertEqual(recover['trigger']['event_selector']['race'], 512)
        self.assertTrue(recover['activation_requirements'][0]['exclude_source_copy'])
        action, = recover['operations']
        self.assertEqual((action['owner'], action['from_zones'], action['to_zone'], action['quantity']), ('self', ['banished'], 'hand', 1))

    def test_tribute_trigger_payment_and_two_origins_remain_distinct(self):
        first = dict(row('①：这张卡在墓地存在的状态，自己对7星以上的怪兽的上级召唤成功的场合，'
                         '把这张卡除外才能发动。对方场上的怪兽全部变成里侧守备表示。'), type=4)
        record, = effect_records(analyze_card(first), semantic_version=SEMANTIC_VERSION, row=first)
        self.assertEqual((record['trigger']['event'], record['trigger']['zone']), ('own_monster_tribute_summon', 'grave'))
        self.assertEqual(record['trigger']['event_selector']['level_between'], [7, 13])
        cost, = record['costs']
        self.assertEqual((cost['kind'], cost['quantity'], cost['from_zones'], cost['to_zone']), ('banish', 1, ['grave'], 'banished'))
        second = dict(row('①：从手卡以及自己场上的表侧表示怪兽之中把1只鸟兽族怪兽除外才能发动。'
                          '从卡组把1只鸟兽族怪兽加入手卡。'), type=0x10002)
        record, = effect_records(analyze_card(second), semantic_version=SEMANTIC_VERSION, row=second)
        cost, = record['costs']
        self.assertEqual((cost['from_zones'], cost['origin_states'], cost['selector_query']['race']),
                         (['hand', 'field'], {'field': 'face_up'}, 512))

    def test_non_effect_fusion_selector_and_simultaneous_named_outputs(self):
        from types import SimpleNamespace
        from ygo_kito.build_contracts import DeckParts
        from ygo_kito.construction_inventory import InventoryDependencies
        from ygo_kito.effect_mechanisms import MechanismCatalog

        fusion_spell = dict(row('①：支付1000基本分才能发动。除效果怪兽外的1只6星以下的融合怪兽当作融合召唤从额外卡组特殊召唤。'), type=2)
        fusion, = effect_records(analyze_card(fusion_spell), semantic_version=SEMANTIC_VERSION, row=fusion_spell)
        action, = fusion['operations']
        self.assertEqual((action['kind'], action['from_zones'], action['materials_required']), ('fusion_summon', ['extra'], False))
        self.assertTrue(matches(dict(row(''), type=0x41, level=5), action['selector_query']))
        self.assertFalse(matches(dict(row(''), type=0x61, level=5), action['selector_query']))
        self.assertFalse(matches(dict(row(''), type=0x41, level=7), action['selector_query']))

        spell = dict(row('①：从卡组把1张「匿名魔法」和1只「匿名系列」怪兽加入手卡。'), type=2)
        named_spell = dict(row('', code=2), name='匿名魔法', type=2)
        monster = dict(row('', code=3), name='匿名系列成员')
        assets = SimpleNamespace(rows={1: spell, 2: named_spell, 3: monster}, receipt={'resources': {'cards': 'a'*64}})
        catalog = MechanismCatalog(assets)
        record, = catalog.effect_records(1)
        first, second = record['operations']
        self.assertNotEqual(first['block_id'], second['block_id'])
        self.assertEqual(first['simultaneous_group'], second['simultaneous_group'])
        self.assertEqual(first['selector_query']['exact_name'], '匿名魔法')
        self.assertEqual(second['selector_query']['name_contains'], '匿名系列')
        inventory = InventoryDependencies(catalog)
        self.assertEqual(inventory.processing_check(DeckParts((1, 2, 3)), record, first)['status'], 'inventory_present')
        self.assertEqual(inventory.processing_check(DeckParts((1, 3, 3)), record, first)['status'], 'missing')

    def test_top_deck_payment_range_and_amount_bind_the_same_effect(self):
        from ygo_kito.construction_layer_flow import _function_semantics
        for cap, multiplier in ((3, 500), (2, 300), (1, 100)):
            with self.subTest(cap=cap):
                payment, trigger = records(f'①：1回合1次，从自己卡组上面把最多{cap}张卡送去墓地才能发动。'
                    f'这张卡的攻击力直到回合结束时上升因为这个效果发动而送去墓地的数量×{multiplier}。'
                    '②：自己场上的这张卡被破坏送去墓地的场合发动。自己抽1张。')
                amounts, functions = [], []
                self.assertFalse(payment['restrictions'])
                for branch in (payment.get('branch_records') or {'payment': payment}).values():
                    cost, = branch['costs']
                    operation, = branch['operations']
                    self.assertTrue(cost['random'])
                    self.assertEqual((cost['from_zones'], cost['to_zone']), (['deck'], 'grave'))
                    self.assertEqual(operation['amount_rule'], dict(kind='per_payment_card', cost_index=0,
                                                                   multiplier=multiplier))
                    amounts.append(cost['quantity'])
                    functions.append(_function_semantics(payment, operation))
                self.assertEqual(amounts, list(range(1, cap + 1)))
                self.assertTrue(all(function == functions[0] for function in functions))
                self.assertEqual(trigger['trigger']['event'], 'destroyed_and_sent_to_grave')
                self.assertEqual((trigger['trigger']['origin'], trigger['trigger']['zone']), ('field', 'grave'))
                self.assertFalse(trigger['unknown'])

    def test_deck_copy_limit_requires_deck_construction_wording(self):
        selected, = records('①：自己主要阶段才能发动。从自己卡组把2只战士族怪兽特殊召唤（同名卡最多1张）。')
        restriction, = selected['restrictions']
        self.assertEqual((restriction['kind'], restriction['scope']), ('selection_limit', 'this_effect'))
        self.assertIn('同名卡最多1张', restriction['source'])
        printed, = records('这张卡在卡组中最多只能投入1张。')
        self.assertEqual([r['kind'] for r in printed['restrictions']], ['deck_copy_limit'])

    def test_empty_grave_is_checked_before_self_payment_and_global_replacement_is_one_rule(self):
        from ygo_kito.construction_relations import _operation_transfer,_restriction_contract,_record_outputs
        record, = records('①：自己·对方回合，自己墓地没有卡存在的场合，'
            '把这张卡从手卡送去墓地才能发动。'
            '直到下个回合的结束时，被送去墓地的卡不去墓地而除外。')
        self.assertEqual(record['activation_state_conditions'][0]['timing'],'before_payment')
        self.assertEqual(record['activation_state_conditions'][0]['zone'],'grave')
        self.assertEqual(record['costs'][0]['from_zones'],['hand'])
        self.assertEqual(record['costs'][0]['to_zone'],'grave')
        operation, = [o for _,o in _record_outputs(record)]
        self.assertEqual(operation['kind'],'grave_destination_replace')
        self.assertEqual(operation['replacement_rule']['duration'],'next_turn_end')
        self.assertIsNone(_operation_transfer(operation,'anonymous replacement'))
        rule, = [r for r in record['restrictions'] if r['kind']=='grave_destination_replace']
        self.assertFalse(_restriction_contract(rule)['whole_turn'])
        self.assertEqual(record['trigger']['zone'],'hand')
        self.assertFalse(record['unknown'])

    def test_excavated_set_selection_and_remaining_count_follow_payment_choice(self):
        from ygo_kito.construction_relations import _record_outputs
        record, = records('①：从额外卡组把3张或6张卡里侧除外才能发动。'
            '把除外数量的卡从自己卡组上面翻开，从那之中选1张加入手卡，'
            '剩下的卡用喜欢的顺序回到卡组下面。'
            '这张卡的发动后，直到回合结束时对方受到的全部伤害变成一半。')
        observed=set()
        for branch in record['branch_records'].values():
            reveal=next(o for o in branch['operations'] if o['kind']=='reveal_deck')
            selected=next(o for o in branch['operations'] if o['kind']=='search_or_recover')
            returned=next(o for o in branch['operations'] if o['kind']=='return_deck')
            observed.add((branch['costs'][0]['quantity'],reveal['quantity'],selected['quantity'],returned['quantity']))
            self.assertTrue(selected['random'])
            self.assertEqual(selected['selection_method'],'choose_from_excavated')
            self.assertNotIn('selector',selected)
            self.assertEqual(returned['deck_position'],'bottom')
            self.assertFalse(branch['unknown'])
        self.assertEqual(observed,{(3,3,1,2),(6,6,1,5)})
        self.assertEqual({o['kind'] for _,o in _record_outputs(record)},{'search_or_recover','damage_change'})

    def test_reveal_and_return_are_processing_of_the_counted_attack_permission(self):
        from ygo_kito.construction_relations import _record_outputs
        record, = records('①：1回合1次，可以发动。从自己卡组上面翻开5张并回到卡组。'
            '这个回合这张卡可以作出最多有所翻开之中的调整数量的攻击。')
        attack, = [o for _,o in _record_outputs(record)]
        self.assertEqual(attack['kind'],'extra_attack')
        self.assertEqual(attack['amount_rule'],dict(kind='revealed_tuner_count',maximum=5))
        self.assertEqual(attack['outcome_requirement']['minimum'],2)
        self.assertFalse(set(record['unknown'])-{'count_negation_policy'},record['unknown'])

    def test_other_payment_copy_and_option_name_references_are_explicit(self):
        first, second = records('这个卡名的①②的效果1回合各能使用1次。'
            '①：从手卡把1张其他的「匿名」卡送去墓地才能发动。这张卡从手卡特殊召唤。'
            '②：可以从以下效果选择1个发动。'
            '●从手卡把1只「匿名」怪兽送去墓地才能发动。从自己墓地选和那只怪兽卡名不同的1只「匿名」怪兽加入手卡。'
            '●从自己墓地把1只「匿名」怪兽除外才能发动。和那只怪兽卡名不同的1只「匿名」怪兽从卡组送去墓地。')
        self.assertTrue(first['costs'][0]['exclude_source_copy'])
        self.assertEqual(first['costs'][0]['source_card_id'],1)
        self.assertEqual(first['costs'][0]['owner'],'self')
        for choice, branch in second['branch_records'].items():
            self.assertEqual(branch['operations'][0]['different_name_from_cost'],0,choice)
            self.assertEqual(branch['conditions']['status'],'recognized')
            self.assertFalse(set(branch['unknown'])-{'count_negation_policy'},branch['unknown'])
        self.assertEqual(second['branch_records']['option:1']['operations'][0]['from_zones'],['grave'])
        self.assertEqual(second['branch_records']['option:2']['operations'][0]['from_zones'],['deck'])
        self.assertFalse(second['unknown'])

    def test_absence_token_generation_and_optional_named_placement_are_separate(self):
        record, = records(
            '①：自己场上没有「匿名衍生物」存在的场合才能发动。'
            '在自己场上把1只「匿名衍生物」（天使族·地·4星·攻/守2000）特殊召唤。'
            '自己场上没有「匿名旅程」存在的场合，可以再从卡组把1张「匿名旅程」'
            '在自己的魔法与陷阱区域表侧表示放置。')
        self.assertEqual(record['conditions']['status'],'recognized')
        self.assertEqual(record['activation_state_conditions'][0]['maximum'],0)
        token, placed = record['operations']
        self.assertEqual(token['generation']['atk'],2000)
        self.assertEqual(token['generation']['name'],'匿名衍生物')
        self.assertEqual(token['from_zones'],[])
        self.assertEqual(placed['selector_query'],{'exact_name':'匿名旅程'})
        self.assertTrue(placed['optional'])
        self.assertEqual(placed['state_conditions'][0]['timing'],'before_operation')
        self.assertFalse(record['unknown'])

    def test_effect_local_counter_response_and_return_trigger_keep_their_scope(self):
        first, second, third = records('①：1回合1次，要让场上的卡破坏的效果的发动时才能发动。'
            '那个效果无效并破坏。②：1回合1次，对方的攻击宣言时以攻击怪兽为对象才能发动。'
            '场上的这张卡除外，那次攻击无效。③：这个②的效果除外的回合的结束阶段发动。'
            '这张卡特殊召唤。')
        self.assertEqual(first['trigger']['event'],'card_destruction_effect_activation')
        self.assertEqual(first['count_limits'][0]['scope'],'this_card_effect')
        self.assertEqual(first['operations'][1]['subject'],'activated_card')
        self.assertEqual(second['trigger']['event'],'opponent_attack_declaration')
        self.assertEqual(second['targets'][0]['owner'],'opponent')
        self.assertEqual(second['targets'][0]['quantity'],1)
        self.assertEqual(second['operations'][0]['from_zones'],['field'])
        self.assertEqual(third['trigger']['event'],'effect_banished_end_phase')
        self.assertEqual(third['trigger']['related_effect_index'],2)
        self.assertEqual(third['operations'][0]['from_zones'],['banished'])
        for record in (first,second,third):
            self.assertEqual(record['conditions']['status'],'recognized')
            self.assertFalse(set(record['unknown'])-{'count_negation_policy'},record['unknown'])

    def test_f01_extra_random_banish_payment_preserves_choices_and_destination(self):
        record, = records('①：自己主要阶段1开始时，把自己的额外卡组的卡3张或6张随机里侧除外才能发动。'
            '除外的卡每有3张，自己从卡组抽1张。这个卡的发动后，直到回合结束时自己不能用卡的效果抽卡。')
        branches = list(record.get('branch_records', {}).values())
        self.assertEqual(len(branches), 2)
        pairs = set()
        for branch in branches:
            cost, = branch['costs']
            self.assertEqual((cost['kind'], cost['from_zones'], cost['to_zone']),
                ('banish', ['extra'], 'banished'))
            self.assertEqual(cost['quantity_options'], [3, 6])
            self.assertTrue(cost['random'])
            self.assertTrue(cost['face_down'])
            draw = next(op for op in branch['operations'] if op['kind'] == 'draw')
            self.assertEqual(draw['quantity_binding'], dict(cost_index=0, divisor=3))
            pairs.add((cost['quantity'], draw['quantity']))
        self.assertEqual(pairs, {(3, 1), (6, 2)})

    def test_extra_payment_word_order_does_not_mix_source_and_destination_positions(self):
        from ygo_kito.construction_binding import CatalogBindingAdapter
        from ygo_kito.construction_inventory import InventoryDependencies
        from tests.test_construction_binding import catalog
        _, assets = catalog()
        for payment, source_face_down in (
                ('把自己的额外卡组3张或6张里侧的卡随机里侧除外',True),
                ('从自己的额外卡组将3张或者6张卡随机里侧表示除外',False),
                ('把自己融合卡组的卡3张或6张随机里侧除外',False)):
            with self.subTest(payment=payment):
                assets.rows[1].update(type=2,desc='①：自己主要阶段1开始时，'+payment+
                    '才能发动。除外的卡每有3张，自己抽1张。')
                observer = CatalogBindingAdapter(assets).semantic_catalog
                record, = observer.effect_records(1)
                self.assertEqual(len(record['branch_records']),2)
                for branch in record['branch_records'].values():
                    cost, = branch['costs']
                    self.assertEqual((cost['from_zones'],cost['to_zone']),(['extra'],'banished'))
                    self.assertTrue(cost['face_down'])
                    self.assertEqual(cost['selector_query'].get('face_up'),False if source_face_down else None)
                    self.assertIsNotNone(InventoryDependencies(observer).item_requirement(cost,'costs'))

    def test_f02_as_fusion_is_one_summon_processing(self):
        from ygo_kito.construction_relations import _record_outputs
        from ygo_kito.construction_layer_flow import _function_semantics
        record, = records('这个卡名的卡在1回合只能发动1张。①：支付1000基本分才能发动。'
            '把1只5星以下的融合怪兽当作融合召唤从额外卡组特殊召唤。'
            '这个效果特殊召唤的怪兽不能攻击，结束阶段破坏。')
        summons = [op for _, op in _record_outputs(record) if op is not None
            and op['kind'] in ('fusion_summon', 'special_summon')]
        self.assertEqual(len(summons), 1)
        semantics = _function_semantics(record, summons[0])
        self.assertEqual(semantics['kind'], 'fusion_summon')
        self.assertNotEqual(semantics['result'].get('materials'), 'unknown')

    def test_as_summon_variants_keep_independent_second_summon(self):
        from ygo_kito.construction_relations import _record_outputs
        for wording in ('当作融合召唤', '作为融合召唤处理'):
            with self.subTest(wording=wording):
                record, = records('①：支付1000基本分才能发动。'
                    '把1只5星以下的融合怪兽'+wording+'从额外卡组特殊召唤。'
                    '从自己手卡把1只怪兽特殊召唤。')
                operations = [o for _,o in _record_outputs(record)]
                self.assertEqual([o['kind'] for o in operations], ['fusion_summon','special_summon'])
                self.assertEqual(operations[0]['selector_query']['level_between'], [1,5])

    def test_delayed_removal_has_result_identity_and_no_immediate_output(self):
        from ygo_kito.construction_relations import _record_outputs
        card = row('①：从手卡·卡组把1只3星以下的念动力族怪兽特殊召唤。'
            '这个效果特殊召唤的怪兽在这个回合的结束阶段除外。')
        card['type'] = 0x10002
        record, = effect_records(analyze_card(card), semantic_version=SEMANTIC_VERSION, row=card)
        summon, = [o for _,o in _record_outputs(record)]
        delayed, = [o for o in record['operations'] if o.get('phase')=='delayed']
        self.assertEqual(summon['from_zones'], ['hand','deck'])
        self.assertEqual((delayed['timing'], delayed['subject_ref'], delayed['quantity']),
            ('end_phase', summon['block_id'], 1))
        self.assertEqual(record['conditions']['status'], 'recognized')
        self.assertFalse(record['unknown'])

    def test_extra_source_is_not_deck_or_banished_destination(self):
        from ygo_kito.effect_mechanisms import _zones
        for source in ('把自己的额外卡组3张卡除外','从自己融合卡组把1只怪兽特殊召唤'):
            self.assertEqual(_zones(source), ('extra',))

    def test_legacy_equipment_selector_and_delayed_self_processing_are_scoped(self):
        from ygo_kito.construction_relations import _record_outputs
        card = row('名字带有「匿名」的4星的怪兽才能装备。装备怪兽的原本攻击力变成2倍。'
            '发动后第2次的自己的准备阶段时这张卡破坏，自己受到装备怪兽的原本攻击力数值的伤害。')
        card['type'] = 0x40002
        record, = effect_records(analyze_card(card), semantic_version=SEMANTIC_VERSION, row=card)
        self.assertEqual(record['equipment_condition']['query']['level'], 4)
        self.assertEqual(record['equipment_condition']['query']['name_contains'], '匿名')
        current, = [o for _,o in _record_outputs(record)]
        self.assertEqual((current['kind'], current['subject']), ('stats','equipped_monster'))
        delayed = [o for o in record['operations'] if o['phase']=='delayed']
        self.assertEqual(len(delayed), 2)
        self.assertTrue(all(o['timing']['occurrence']==2 for o in delayed))
        self.assertFalse(record['unknown'])

    def test_one_effects_limit_does_not_make_another_effects_count_unknown(self):
        _,other=records('这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。抽1张。'
            '②：对方回合才能发动。抽1张。')
        self.assertEqual(other['count_limits'],[])
        self.assertNotIn('count_limit',other['unknown'])

    def test_response_card_is_not_an_ambiguous_target(self):
        record,=records('①：魔法·陷阱卡发动时才能发动。那个发动无效，那张卡回到持有者卡组。')
        self.assertFalse(record['targets'])
        self.assertNotIn('ambiguous_target_reference',record['unknown'])

    def test_legacy_choice_target_keeps_its_owner_without_missing_fields(self):
        record,=records('可以从以下效果选择1个发动。\n●以自己墓地1只战士族怪兽为对象才能发动。那只怪兽回到卡组。\n●自己回复500基本分。')
        self.assertEqual(record['targets'][0]['owner'],'self')
        returned=next(op for op in record['operations'] if op['kind']=='return_deck')
        self.assertEqual((returned['owner'],returned['quantity']),('self',1))

    def test_face_up_selector_keeps_the_required_position(self):
        query=selector('表侧表示的暗属性怪兽')
        self.assertTrue(query['face_up'])
        self.assertEqual(query['attribute_any'],32)
        self.assertFalse(selector('里侧表示怪兽')['face_up'])
        self.assertIsNone(selector('持有超量素材的怪兽'))

    def test_explicit_end_phase_is_a_known_activation_condition(self):
        record,=records('①：自己·对方的结束阶段发动。给与对方500伤害。')
        self.assertEqual(record['conditions']['status'],'recognized')
        self.assertEqual(record['trigger']['event'],'either_end_phase')
        self.assertNotIn('activation_boundary',record['unknown'])

    def test_ordinary_spell_card_activation_needs_no_extra_wording(self):
        card=row('①：从自己卡组抽1张。');card['type']=2
        record,=effect_records(analyze_card(card),semantic_version=SEMANTIC_VERSION,row=card)
        self.assertEqual(record['trigger']['event'],'card_activation')
        self.assertEqual(record['conditions']['status'],'recognized')
        monster,=records('①：从自己卡组抽1张。')
        self.assertIn('activation_boundary',monster['unknown'])

    def test_payment_target_and_pronoun_preserve_different_origins(self):
        record,=records('①：把1张手卡除外，以除外的1只自己的暗属性怪兽为对象才能发动。那只怪兽表侧守备表示或者里侧守备表示特殊召唤。')
        cost,=record['costs'];target,=record['targets'];operation,=record['operations']
        self.assertEqual((cost['kind'],cost['from_zones'],cost['to_zone'],cost['owner'],cost['quantity']),
            ('banish',['hand'],'banished','self',1))
        self.assertEqual(cost['source'],'把1张手卡除外')
        self.assertEqual((target['zones'],target['owner'],target['selector'],target['quantity']),
            (['banished'],'self','暗属性怪兽',1))
        self.assertEqual((operation['from_zones'],operation['owner'],operation['quantity'],operation['selector']),
            (['banished'],'self',1,'暗属性怪兽'))
        self.assertEqual(record['conditions']['status'],'recognized')

    def test_pronoun_keeps_opponents_target_ownership(self):
        record,=records('①：以对方墓地1只战士族怪兽为对象才能发动。那只怪兽特殊召唤。')
        self.assertEqual(record['operations'][0]['owner'],'opponent')
        self.assertEqual(record['operations'][0]['quantity'],1)
        self.assertEqual(record['operations'][0]['selector'],'战士族怪兽')

    def test_multiple_targets_do_not_guess_one_pronoun(self):
        record,=records('①：以自己墓地1只战士族怪兽和以对方墓地1只魔法师族怪兽为对象才能发动。那只怪兽特殊召唤。')
        self.assertIn('ambiguous_target_reference',record['unknown'])
        self.assertIsNone(record['operations'][0]['quantity'])

    def test_gy_trigger_with_target_does_not_gain_an_unknown_condition(self):
        record,=records('①：这张卡被效果送去墓地的场合，以自己墓地1张「匿名系列」陷阱卡为对象才能发动。那张卡加入手卡。')
        self.assertEqual(record['trigger']['event'],'sent_to_grave')
        self.assertEqual(record['conditions']['status'],'recognized')
        self.assertFalse(record['costs'])
        self.assertEqual(record['operations'][0]['quantity'],1)
        self.assertEqual(record['operations'][0]['from_zones'],['grave'])
        self.assertNotIn('additional_activation_conditions',record['unknown'])

    def test_combined_count_clause_and_summon_procedure_are_not_activation(self):
        text=('这个卡名的①的方法的特殊召唤1回合只能有1次，②的效果1回合只能使用1次。'
            '①：对方场上的怪兽数量比自己场上的怪兽多的场合，这张卡可以从手卡特殊召唤。'
            '②：自己·对方回合，把自己场上1只「匿名系列」怪兽解放，以对方场上1张卡为对象才能发动。那张卡破坏。')
        procedure,effect=records(text)
        self.assertEqual(procedure['block_view']['status'],'summon_procedure')
        self.assertFalse(procedure['summon_procedure']['starts_chain'])
        self.assertEqual(procedure['count_limits'][0]['count_event'],'special_summon_method')
        self.assertNotIn('activation_boundary',procedure['unknown'])
        self.assertNotIn('count_limit',procedure['unknown'])
        self.assertEqual(effect['count_limits'][0]['scope'],'same_name_this_effect')
        self.assertEqual(effect['count_limits'][0]['maximum'],1)
        self.assertEqual(effect['trigger']['event'],'either_turn')

    def test_no_printed_count_is_distinct_from_unrecognized_count(self):
        ordinary,=records('①：自己主要阶段才能发动。抽1张。')
        self.assertNotIn('count_limit',ordinary['unknown'])
        uncertain,=records('①：自己主要阶段才能发动。抽1张。下次回合才能再使用这个效果。')
        self.assertIn('unparsed_resolution_or_restriction',uncertain['unknown'])

    def test_selector_preserves_attributes_types_and_order(self):
        for text in ('7星暗属性战士族怪兽','暗属性7星战士族怪兽'):
            query=selector(text)
            self.assertIsNotNone(query)
            candidate=row('',code=3);candidate.update(level=7)
            self.assertTrue(matches(candidate,query))
            candidate['attribute']=16
            self.assertFalse(matches(candidate,query))
        query=selector('攻击力2000以下的魔法师族怪兽')
        candidate=row('');candidate.update(race=2)
        self.assertTrue(matches(candidate,query))
        candidate['atk']=2100
        self.assertFalse(matches(candidate,query))
        self.assertIsNone(selector('7星且不受其他卡的效果影响的怪兽'))

    def test_xyz_rank_and_link_rating_are_not_printed_level(self):
        query=selector('4星怪兽')
        card=row('')
        self.assertTrue(matches(card,query))
        for kind in (0x800001,0x4000001):
            card['type']=kind
            self.assertFalse(matches(card,query))


class SummonRestrictionCompletionTests(unittest.TestCase):
    LEVEL='这个回合，自己若非等级或者阶级是3以上的怪兽则不能特殊召唤'
    RACE='这个效果的发动后，直到回合结束时自己不是鸟兽族怪兽不能特殊召唤'

    def contract(self,text):
        from ygo_kito.construction_relations import _restriction_contract
        return _restriction_contract(dict(kind='cannot_summon',source=text,scope='player',
            duration='while_applicable',tag={'dimension':'restriction','value':'召唤限制'}))

    def affected(self,rule,cards,*,actor='self'):
        from ygo_kito.construction_layer_flow import _restriction_match
        raw=dict(kind='special_summon',from_zones=['hand'],to_zone='field',reason='effect',
            owner=actor,controller=actor,phase='resolution',source='选1只怪兽特殊召唤',
            selector_query={'predicate':{'field':'card_ids','value':[c['id'] for c in cards]}})
        detail=dict(card_id=99,operation=raw,semantics=raw,costs=[])
        return _restriction_match(rule,detail,{str(c['id']):c for c in cards},dict(main=[c['id'] for c in cards],extra=[]))

    def test_complete_sources_produce_timing_player_and_allowed_predicate(self):
        whole=self.contract(self.LEVEL);after=self.contract(self.RACE)
        self.assertIsNotNone(whole);self.assertIsNotNone(after)
        self.assertEqual(whole['controller'],'self')
        self.assertIs(whole['whole_turn'],True)
        self.assertIs(after['whole_turn'],False)
        self.assertEqual(after['allowed_summons'],{'field':'race_any','value':512})

    def test_level_rank_and_link_are_distinct(self):
        rule=self.contract(self.LEVEL)
        for code,kind,level,expected in ((1,33,3,False),(2,33,2,True),
            (3,0x800001,3,False),(4,0x800001,2,True),(5,0x4000001,3,True)):
            card=row('',code=code);card.update(type=kind,level=level)
            self.assertIs(self.affected(rule,[card]),expected)

    def test_race_actor_and_mixed_recipients_are_kept_separate(self):
        rule=self.contract(self.RACE)
        bird=row('',code=1);bird['race']=512
        other=row('',code=2)
        self.assertIs(self.affected(rule,[bird]),False)
        self.assertIs(self.affected(rule,[other]),True)
        self.assertIs(self.affected(rule,[other],actor='opponent'),False)
        self.assertIsNone(self.affected(rule,[bird,other]))

    def test_unrecognized_exception_is_not_dropped(self):
        self.assertIsNone(self.contract(self.LEVEL.replace('3以上','3以上且本回合没有召唤')))


if __name__=='__main__':
    unittest.main()
