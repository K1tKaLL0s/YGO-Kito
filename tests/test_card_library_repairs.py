"""Printed-text regressions from the full local card-library audit; CPU only."""
from types import SimpleNamespace
import tempfile
from pathlib import Path
import unittest

from ygo_kito.effect_blocks import build_dictionary, EffectBlockDictionary
from ygo_kito.effect_mechanisms import MechanismCatalog


def catalog(text, **changes):
    row=dict(id=900001,alias=0,type=33,name='匿名测试卡',desc=text,setcode=0,
             atk=1000,level=4,race=1,attribute=1,**{'def':1000})
    row.update(changes)
    return MechanismCatalog(SimpleNamespace(rows={row['id']:row},receipt={'resources':{'cards':'a'*64}}))


def all_blocks(cat, section='blocks'):
    return [b for r in cat.effect_records(900001) for b in r['block_view'][section]]


class CardLibraryRepairTests(unittest.TestCase):
    LABYRINTH_TEXT='给「迷宫壁」装备。把「迷宫壁」和装备的这张卡作为祭品，从卡组把「墙壁之影」特殊召唤。'

    def test_official_equipped_monster_payment_is_one_card_in_every_projection(self):
        cat=catalog(self.LABYRINTH_TEXT,id=64389297,type=0x40002,name='迷宫变化')
        equip,activated=cat.effect_records(64389297)
        self.assertFalse(equip['costs'])
        paid,=activated['costs']
        self.assertEqual((paid['kind'],paid['quantity'],paid['subject']),('release',1,'equipped_monster'))
        self.assertTrue(paid['requires_equipped_to_source'])
        self.assertEqual(paid['selector_query']['exact_name'],'迷宫壁')
        self.assertEqual(activated['block_view']['cost_blocks'][0]['qualifiers']['quantity'],1)
        self.assertEqual(next(c for c in activated['resource_changes'] if c['reason']=='cost')['quantity'],1)
        self.assertFalse(activated['targets'])
        self.assertFalse(activated['legality_verified'])

    def test_equipping_and_equipped_spell_effect_have_distinct_activation_events(self):
        cat=catalog(self.LABYRINTH_TEXT,id=64389297,type=0x40002)
        equip,activated=cat.effect_records(64389297)
        self.assertEqual(equip['trigger']['event'],'card_activation')
        self.assertEqual(equip['trigger']['activation_kind'],'card_activation')
        self.assertEqual(activated['trigger']['event'],'own_main_phase')
        self.assertEqual(activated['trigger']['activation_kind'],'effect_activation')
        self.assertEqual(activated['trigger']['zone'],'field')
        self.assertTrue(activated['trigger']['optional'])
        self.assertNotIn('卡片发动',{c['kind'] for c in activated['block_view']['connectors']})
        self.assertIn('自己主要阶段',{c['kind'] for c in activated['block_view']['connectors']})

    def test_official_ruling_requires_exact_identity_type_and_text(self):
        for code,kind,text in ((900001,0x40002,self.LABYRINTH_TEXT),(64389297,0x20002,self.LABYRINTH_TEXT),
                               (64389297,0x40002,self.LABYRINTH_TEXT+' ')):
            cat=catalog(text,id=code,type=kind)
            self.assertTrue(all(not r.get('official_rulings') for r in cat.effect_records(code)))

    def test_official_payment_reaches_inventory_and_saved_dictionary(self):
        from ygo_kito.construction_inventory import InventoryDependencies
        cat=catalog(self.LABYRINTH_TEXT,id=64389297,type=0x40002,name='迷宫变化')
        wall=dict(cat.assets.rows[64389297],id=100,name='迷宫壁',type=17,desc='普通怪兽。')
        cat.assets.rows[100]=wall
        cat=MechanismCatalog(cat.assets)
        activated=cat.effect_records(64389297)[1]
        need=InventoryDependencies(cat).item_requirement(activated['costs'][0],'costs')
        self.assertIsNotNone(need)
        self.assertEqual((need['minimum'],need['origin']),(1,'field'))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'ruling.sqlite3'
            build_dictionary(cat,path)
            with EffectBlockDictionary(path) as saved:
                self.assertEqual(saved.card(64389297),cat.effect_blocks(64389297))
                self.assertIn(64389297,saved.find_connector('自己主要阶段'))

    def test_old_lp_payment_before_field_shuffle_is_a_cost(self):
        cat=catalog('支付300基本分，自己的主要怪兽区域的里侧守备表示怪兽洗切，再以里侧守备表示重新排列。这个效果1个回合只能使用1次。',type=0x20002)
        paid,=all_blocks(cat,'cost_blocks')
        self.assertEqual((paid['kind'],paid['qualifiers']['quantity']),('pay_lp',300))
        self.assertIn('field_shuffle',{b['kind'] for b in all_blocks(cat)})

    def test_printed_materials_do_not_hide_effects_or_unnumbered_options(self):
        cat=catalog('4星怪兽×3\n1回合1次，可以把这张卡1个超量素材取除，从以下效果选择1个发动。\n●选择对方场上1张卡回到持有者手卡。\n●对方随机丢弃1张手卡。',type=0x800021)
        r,=cat.effect_records(900001)
        self.assertEqual({b['kind'] for b in all_blocks(cat)},{'return_hand','discard'})
        self.assertIn('printed_materials',{d['kind'] for d in r['block_view']['description_blocks']})
        self.assertEqual(r['block_view']['alternatives']['mode'],'one_of')
        self.assertTrue(r['branch_records'])

    def test_old_resolution_before_parenthetical_limits_or_followup_is_not_a_cost(self):
        for text,kinds in (
            ('装备怪兽每次战斗破坏对方怪兽时，对方随机丢弃1张手卡。（1只怪兽可以装备的同盟最多1张。）',{'discard'}),
            ('自己受到战斗伤害时，墓地存在的这张卡从游戏中除外。那个时候，自己墓地有炎属性怪兽存在的场合，给与对方基本分和自己受到的战斗伤害相同的伤害。',{'banish','damage'}),
        ):
            cat=catalog(text)
            self.assertFalse(all_blocks(cat,'cost_blocks'))
            self.assertTrue(kinds <= {b['kind'] for b in all_blocks(cat)})

    def test_parallel_deck_top_and_grave_payment_keeps_both_sources(self):
        cat=catalog('从自己的卡组上面·墓地把合计5张卡里侧除外才能把这张卡发动。这个卡名的①的效果1回合只能使用1次。①：自己主要阶段才能发动。抽1张。',type=2)
        paid=next(c for r in cat.effect_records(900001) for c in r['costs'] if c['kind']=='banish')
        self.assertEqual(paid['from_zones'],['deck','grave'])
        self.assertEqual(paid['quantity'],5)
        self.assertEqual(paid['selection_by_zone'],{'deck':'top','grave':'choose'})
        self.assertIsNone(paid['random'])

    def test_old_target_activation_preserves_the_following_lock(self):
        cat=catalog('这张卡被战斗破坏送去墓地时，选择场上盖放的2张魔法·陷阱卡发动。只要这张卡在墓地存在，选择的卡不能发动。')
        r,=cat.effect_records(900001)
        self.assertEqual(r['block_view']['status'],'restriction')
        self.assertTrue(any(x['kind']=='cannot_activate' for x in r['restrictions']))

    def test_unnumbered_options_keep_their_shared_condition(self):
        cat=catalog('自己场上有水属性怪兽存在的场合，从以下效果选择1个发动。自己场上有仪式怪兽存在的场合，可以选择两方发动。\n●抽1张。\n●自己回复1000基本分。',type=2)
        r,=cat.effect_records(900001)
        a=r['block_view']['alternatives']
        self.assertEqual(a['mode'],'subset')
        self.assertEqual(a['default_count'],1)
        self.assertEqual(a['count_variants'][0]['count'],2)
        self.assertEqual({b['kind'] for b in r['block_view']['blocks']},{'draw','recover_lp'})

    def test_counter_transfer_and_variable_tribute_are_retained(self):
        cat=catalog('①：有魔力指示物放置的卡被破坏的场合把那些卡放置的魔力指示物数量的魔力指示物给这张卡放置。',type=2)
        self.assertIn('counter',{b['kind'] for b in all_blocks(cat)})
        cat=catalog('这张卡祭品召唤的场合，可以只用自己场上任意数量的水属性怪兽作为祭品。')
        self.assertTrue(all_blocks(cat,'procedure_blocks'))
        self.assertFalse(all_blocks(cat,'cost_blocks'))

    def test_monster_subtypes_are_preserved_in_identity_tags(self):
        for flag,label in ((0x200,'灵魂'),(0x400,'同盟'),(0x800,'二重'),(0x400000,'卡通'),(0x2000000,'特殊召唤')):
            entry=catalog('①：自己主要阶段才能发动。抽1张。',type=33|flag).effect_blocks(900001)
            self.assertIn({'dimension':'card_type','value':label},entry['identity_tags'])

    def test_token_material_limits_do_not_create_another_token(self):
        cat=catalog('在自己场上把1只「匿名衍生物」（战士族·地·1星·攻/守0）特殊召唤。这衍生物不能为上级召唤而解放。',type=2)
        tokens=[b for b in all_blocks(cat) if b['qualifiers'].get('creates_token')]
        self.assertEqual(len(tokens),1)
        self.assertIn('特殊召唤',tokens[0]['source'])
        self.assertTrue(any(r['kind']=='cannot_release' for record in cat.effect_records(900001) for r in record['restrictions']))
        self.assertFalse(any(r['kind']=='cannot_summon' for record in cat.effect_records(900001) for r in record['restrictions']))

    def test_legacy_lp_fee_is_not_a_resolution_and_newline_effects_stay_separate(self):
        cat=catalog('反转：可以支付2000分，对方受到1000分的伤害。\n1回合1次，可以把这张卡解放，自己抽1张。')
        costs=all_blocks(cat,'cost_blocks')
        self.assertEqual({b['kind'] for b in costs},{'pay_lp','release'})
        self.assertEqual(next(b for b in costs if b['kind']=='pay_lp')['qualifiers']['quantity'],2000)
        self.assertNotIn('release',{b['kind'] for b in all_blocks(cat)})

    def test_modern_semicolon_keeps_the_payment_target_and_processing(self):
        cat=catalog('这张卡在墓地存在的场合：可以丢弃1张手卡，以自己除外状态的1只怪兽为对象；那只怪兽特殊召唤。')
        record,=cat.effect_records(900001)
        self.assertEqual(record['costs'][0]['from_zones'],['hand'])
        self.assertEqual(record['operations'][0]['kind'],'special_summon')
        self.assertEqual(record['operations'][0]['from_zones'],['banished'])

    def test_shared_counter_payment_does_not_become_search_quantity(self):
        cat=catalog('①：可以把自己场上的武士道指示物的以下数量取除，那个效果发动。\n●2个：自己场上1只怪兽的攻击力上升500。\n●4个：从自己的卡组·墓地选1只怪兽加入手卡。',type=0x20002)
        record,=cat.effect_records(900001)
        branches=record['branch_records']
        self.assertEqual(branches['option:2']['costs'][0]['quantity'],4)
        self.assertEqual(branches['option:2']['costs'][0]['kind'],'remove_counter')
        self.assertEqual(branches['option:2']['operations'][0]['quantity'],1)
        self.assertEqual({b['qualifiers']['quantity'] for b in record['block_view']['cost_blocks']},{2,4})

    def test_summon_negation_does_not_advertise_special_summoning(self):
        cat=catalog('①：怪兽特殊召唤之际，支付1000基本分才能发动。那次特殊召唤无效并破坏。',type=4)
        kinds={b['kind'] for b in all_blocks(cat)}
        self.assertIn('negate_summon',kinds)
        self.assertNotIn('special_summon',kinds)
        event=catalog('怪兽的特殊召唤被无效的场合才能发动。抽1张。',type=4)
        self.assertNotIn('negate_summon',{b['kind'] for b in all_blocks(event)})

    def test_tokens_are_created_and_parallel_extra_source_is_preserved(self):
        cat=catalog('①：自己主要阶段才能发动。在自己场上把1只「匿名衍生物」（战士族·地·1星·攻/守0）特殊召唤。')
        summon=next(o for r in cat.effect_records(900001) for o in r['operations'] if o['kind']=='special_summon')
        self.assertTrue(summon['creates_token'])
        self.assertEqual(summon['from_zones'],[])
        other=catalog('①：自己主要阶段才能发动。从卡组·额外卡组把1只怪兽特殊召唤。')
        self.assertEqual(all_blocks(other)[0]['qualifiers']['from_zones'],['deck','extra'])

    def test_normal_pendulum_description_is_not_a_second_pendulum_effect(self):
        cat=catalog('←3 【灵摆】 3→\n①：自己主要阶段才能发动。抽1张。\n【怪兽描述】\n栖息在森林中的普通战士。',type=0x1000011)
        records=cat.effect_records(900001)
        self.assertEqual({r['scope'] for r in records},{'pendulum','monster'})
        self.assertTrue(all(not r['operations'] for r in records if r['scope']=='monster'))

    def test_trigger_and_noun_references_are_not_repeated_movements(self):
        cat=catalog('①：这张卡从场上送去墓地时，自己抽1张。②：自己主要阶段才能发动。得到对方场上1只怪兽的控制权。这个效果得到控制权的怪兽的效果无效化。')
        kinds=[b['kind'] for b in all_blocks(cat)]
        self.assertNotIn('send_grave',kinds)
        self.assertEqual(kinds.count('control'),1)
        self.assertIn('negate_effect',kinds)

    def test_damage_timing_and_level_formulas_keep_their_stat_meaning(self):
        cat=catalog('①：这张卡的攻击力只在那次伤害计算时变成一半。②：这张卡的攻击力·守备力变成这张卡的等级×200。')
        kinds={b['kind'] for b in all_blocks(cat)}
        self.assertEqual(kinds,{'stats'})

    def test_negated_selector_does_not_suppress_search(self):
        cat=catalog('①：自己主要阶段才能发动。从卡组把1只不能通常召唤的怪兽加入手卡。')
        self.assertIn('search',{b['kind'] for b in all_blocks(cat)})

    def test_conditional_search_changes_the_selection_without_adding_a_second_search(self):
        cat=catalog('①：自己主要阶段才能发动。从卡组把1只怪兽加入手卡。自己场上有5星以上的怪兽存在的场合，这个效果加入手卡的数量可以变成2张（同名卡最多1张）。')
        record,=cat.effect_records(900001)
        operations=[o for o in record['operations'] if o['kind']=='search_or_recover']
        self.assertEqual(len(operations),1)
        self.assertEqual(operations[0]['quantity'],1)
        self.assertEqual(operations[0]['variants'][0]['quantity'],2)
        self.assertEqual(operations[0]['variants'][0]['maximum_per_name'],1)

    def test_state_payment_is_preserved_without_consuming_the_card(self):
        cat=catalog('①：把这张卡变更为表侧守备表示，以自己墓地1只怪兽为对象才能发动。那只怪兽加入手卡。')
        record,=cat.effect_records(900001)
        self.assertEqual(record['costs'][0]['kind'],'position')
        self.assertFalse(record['costs'][0]['consumes_card'])

    def test_procedure_and_activated_summon_remain_distinct(self):
        cat=catalog('这张卡不能通常召唤。\n从自己墓地把2只怪兽除外的场合可以特殊召唤。\n1回合1次，可以丢弃1张手卡，以自己墓地1只怪兽为对象才能发动。那只怪兽特殊召唤。')
        procedures=all_blocks(cat,'procedure_blocks')
        self.assertTrue(any(b['kind']=='special_summon' and b['qualifiers']['from_zones']==['hand'] for b in procedures))
        self.assertTrue(any(b['kind']=='banish' and b['phase']=='summon_payment' for b in procedures))
        self.assertEqual(sum(b['kind']=='special_summon' for b in all_blocks(cat)),1)

    def test_export_includes_distinct_rule_alias_and_excludes_only_actual_duplicate(self):
        cat=catalog('①：自己主要阶段才能发动。抽1张。')
        base=cat.assets.rows[900001]
        cat.assets.rows[900002]=dict(base,id=900002,alias=900001)
        cat.assets.rows[900003]=dict(base,id=900003,alias=900001,name='另一张规则同名卡',desc='①：自己主要阶段才能发动。场上1只怪兽破坏。')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'effects.sqlite3'
            manifest=build_dictionary(cat,path)
            self.assertEqual(manifest['canonical_cards'],2)
            with EffectBlockDictionary(path) as saved:
                self.assertIsNone(saved.card(900002))
                self.assertIsNotNone(saved.card(900003))
                self.assertEqual(saved.card(900001),cat.effect_blocks(900001))

    def test_export_keeps_prelude_self_lock_metadata(self):
        cat=catalog('这个卡名的①②的效果1回合各能使用1次，这些效果发动的回合，自己不能把怪兽特殊召唤。①：自己主要阶段才能发动。抽1张。②：自己主要阶段才能发动。场上1只怪兽破坏。')
        with tempfile.TemporaryDirectory() as directory:
            manifest=build_dictionary(cat,Path(directory)/'effects.sqlite3')
            self.assertEqual(manifest['canonical_cards'],1)

    def test_above_below_and_can_are_not_the_target_preposition(self):
        cat=catalog('①：自己手卡比对方少2张以上的场合，可以把手卡1只怪兽给对方观看，把这张卡解放，以对方场上2张卡为对象才能发动。那些卡破坏。')
        record,=cat.effect_records(900001)
        self.assertEqual({c['kind'] for c in record['costs']},{'reveal','release'})
        self.assertEqual(record['targets'][0]['owner'],'opponent')
        self.assertEqual(record['targets'][0]['quantity'],2)

    def test_counter_trap_choices_share_a_half_lp_fee_and_resolve_pronouns(self):
        cat=catalog('①：可以把基本分支付一半把以下效果发动。\n●魔法·陷阱卡发动时才能发动。那个发动无效并破坏。\n●自己或对方把怪兽召唤·反转召唤·特殊召唤之际才能发动。那个无效，那些怪兽破坏。',type=4)
        record,=cat.effect_records(900001)
        self.assertEqual(set(record['branch_records']),{'option:1','option:2'})
        self.assertEqual(record['branch_records']['option:2']['costs'][0]['fraction'],[1,2])
        kinds={o['kind'] for o in record['branch_records']['option:2']['operations']}
        self.assertIn('negate_summon',kinds)
        self.assertNotIn('special_summon',kinds)

    def test_contact_procedure_before_numbered_effect_does_not_become_a_function(self):
        cat=catalog('「匿名甲」＋「匿名乙」\n把自己场上的上记卡除外的场合才能从额外卡组特殊召唤。\n①：自己主要阶段才能发动。抽1张。',type=0x61)
        kinds={b['kind'] for b in all_blocks(cat)}
        self.assertEqual(kinds,{'draw'})
        self.assertTrue(any(b['kind']=='special_summon' for b in all_blocks(cat,'procedure_blocks')))

    def test_optional_additional_payment_is_not_a_mandatory_fee(self):
        cat=catalog('这张卡也能把自己场上1只植物族怪兽解放来发动。①：从卡组把1只怪兽加入手卡。',type=2)
        self.assertTrue(any(c['kind']=='release' and c['phase']=='alternative_activation_payment' for c in all_blocks(cat,'cost_blocks')))
        self.assertTrue(all(not r['costs'] for r in cat.effect_records(900001)))

    def test_dice_stat_results_have_conditions_and_extra_attack_uses_old_word_order(self):
        cat=catalog('①：自己主要阶段才能发动。双方各自掷1次骰子，自身场上的全部怪兽的攻击力直到回合结束时受出现的数目的效果适用。\n●1：下降1000。\n●2：上升1000。②：这张卡1回合可以攻击2次。')
        stats=[b for b in all_blocks(cat) if b['kind']=='stats']
        self.assertEqual({b['qualifiers']['result_condition']['value'] for b in stats},{1,2})
        self.assertIn('extra_attack',{b['kind'] for b in all_blocks(cat)})

    def test_comparison_with_target_does_not_replace_the_new_monsters_source(self):
        cat=catalog('①：以自己场上1只怪兽为对象才能发动。原本的种族·等级和那只怪兽相同的1只怪兽从卡组·额外卡组特殊召唤。')
        record,=cat.effect_records(900001)
        summon=record['operations'][0]
        self.assertEqual(summon['from_zones'],['deck','extra'])
        self.assertNotIn('target_ref',summon)

    def test_discard_and_lp_are_two_fees_in_a_single_clause(self):
        cat=catalog('①：丢弃1张手卡并支付1000基本分，以场上1张卡为对象才能发动。那张卡破坏。')
        record,=cat.effect_records(900001)
        self.assertEqual({c['kind'] for c in record['costs']},{'send_grave','pay_lp'})

    def test_card_sent_by_another_activation_is_a_trigger_not_a_fee(self):
        cat=catalog('①：这张卡在墓地存在的状态，为让自己把其他卡的效果发动而让手卡的卡被送去墓地的场合才能发动。这张卡加入手卡。')
        record,=cat.effect_records(900001)
        self.assertEqual(record['costs'],[])
        self.assertNotIn('send_grave',{o['kind'] for o in record['operations']})

    def test_discard_procedure_keeps_both_hand_and_grave_access(self):
        cat=catalog('①：这张卡可以把等级合计直到8以上的手卡的机械族怪兽丢弃，从手卡·墓地特殊召唤（把自身丢弃的场合，从墓地特殊召唤）。')
        record,=cat.effect_records(900001)
        self.assertFalse(record['costs'])
        self.assertFalse(record['operations'])
        summon=next(b for b in record['block_view']['procedure_blocks'] if b['kind']=='special_summon')
        self.assertEqual(summon['qualifiers']['from_zones'],['hand','grave'])

    def test_cost_replacement_is_not_an_independent_banish(self):
        cat=catalog('①：自己场上的怪兽为让效果发动而把自身解放的场合，可以作为代替把墓地的这张卡除外。')
        record,=cat.effect_records(900001)
        self.assertIn('cost_replacement',{o['kind'] for o in record['operations']})
        self.assertNotIn('banish',{o['kind'] for o in record['operations']})
        self.assertFalse(record['costs'])

    def test_one_card_ritual_value_is_material_permission_not_a_ritual_effect(self):
        cat=catalog('①：水属性仪式怪兽1只仪式召唤的场合，可以用这1张卡作为仪式召唤需要的数值的解放使用。')
        blocks=all_blocks(cat)
        self.assertEqual({b['kind'] for b in blocks},{'material_count'})
        self.assertEqual(blocks[0]['qualifiers']['value_rule'],'full_ritual_requirement')

    def test_granted_effect_payment_keeps_its_conditional_scope(self):
        cat=catalog('①：这张卡战斗破坏怪兽时才能发动。这张卡得到以下效果。\n●双方的主要阶段，把这张卡解放才能发动。从额外卡组把1只融合怪兽特殊召唤。')
        record,=cat.effect_records(900001)
        self.assertEqual(record['costs'],[])
        self.assertNotIn('release',{o['kind'] for o in record['operations']})
        self.assertTrue(any(b['kind']=='release' and b['phase']=='conditional_activation_payment' for b in record['block_view']['cost_blocks']))

    def test_old_target_wording_roundtrips_live_and_saved_zone_arrays(self):
        cat=catalog('从自己墓地选择1只攻击力1000以下的怪兽，攻击表示特殊召唤。这张卡从场上离开时那只怪兽破坏。',type=0x20004)
        record,=cat.effect_records(900001)
        self.assertEqual(next(o for o in record['operations'] if o['kind']=='special_summon')['from_zones'],['grave'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'effects.sqlite3'
            build_dictionary(cat,path)
            with EffectBlockDictionary(path) as saved:self.assertEqual(saved.card(900001),cat.effect_blocks(900001))

    def test_victory_rule_in_prelude_has_its_own_record(self):
        cat=catalog('这张卡有3个指示物放置的场合，自己决斗胜利。①：自己主要阶段才能发动。给这张卡放置1个指示物。')
        records=cat.effect_records(900001)
        rule=next(r for r in records if any(o['kind']=='win' for o in r['operations']))
        self.assertEqual(rule['effect_index'],0)
        self.assertEqual(rule['operations'][0]['phase'],'rule_condition')
        self.assertNotIn('counter',{o['kind'] for o in rule['operations']})

    def test_maintenance_before_numbered_effect_is_not_its_activation_fee(self):
        cat=catalog('这张卡的控制者在每次双方的准备阶段支付700基本分。不能支付700基本分的场合这张卡破坏。①：自己主要阶段才能发动。抽1张。',type=0x20002)
        self.assertTrue(any(b['kind']=='pay_lp' and b['phase']=='upkeep_payment' for b in all_blocks(cat,'cost_blocks')))
        self.assertTrue(any(b['kind']=='destroy' and b['phase']=='upkeep' for b in all_blocks(cat)))
        self.assertTrue(all(not r['costs'] for r in cat.effect_records(900001)))

    def test_named_effect_summon_condition_is_not_the_monsters_own_procedure(self):
        cat=catalog('这张卡在用「匿名魔法」的效果把自己的手卡·场上的「匿名陷阱」送去墓地的场合才能特殊召唤。①：自己主要阶段才能发动。抽1张。',type=0x61)
        self.assertNotIn('special_summon',{b['kind'] for b in all_blocks(cat)})
        self.assertFalse(all_blocks(cat,'procedure_blocks'))
        self.assertTrue(any(d['kind']=='summon_condition' for d in all_blocks(cat,'description_blocks')))

    def test_counter_eligibility_is_a_selector_and_not_a_placement(self):
        cat=catalog('①：自己主要阶段才能发动。可以放置魔力指示物的1只怪兽从卡组特殊召唤。')
        blocks=all_blocks(cat)
        self.assertEqual({b['kind'] for b in blocks},{'special_summon'})
        self.assertFalse(blocks[0]['qualifiers'].get('optional',False))

    def test_ritual_material_instruction_is_not_an_activation_fee(self):
        cat=catalog('需要把合计等级直到6以上的自己的手卡·场上的怪兽作为祭品，从手卡把1只仪式怪兽仪式召唤。',type=0x82)
        self.assertTrue(all(not r['costs'] for r in cat.effect_records(900001)))
        self.assertIn('ritual_summon',{b['kind'] for b in all_blocks(cat)})


class RemainingLibraryRepairTests(unittest.TestCase):
    def test_parenthetical_timing_and_restrictions_keep_the_actual_summon(self):
        for text in (
            '怪兽的效果发动的场合（伤害步骤除外）：可以把这张卡从手卡特殊召唤。',
            '自己的卡组·墓地·除外状态的1只怪兽守备表示特殊召唤（自己场上没有怪兽存在的场合，不是通常怪兽不能特殊召唤）。',
        ):
            cat=catalog(text)
            self.assertEqual([b['kind'] for b in all_blocks(cat)],['special_summon'])

    def test_cannot_direct_attack_is_only_a_restriction(self):
        cat=catalog('这张卡不能直接攻击。')
        self.assertNotIn('direct_attack',{b['kind'] for b in all_blocks(cat)})
        self.assertIn('cannot_attack',{b['kind'] for b in all_blocks(cat,'restrictions')})

    def test_optional_set_turn_payment_does_not_become_removal(self):
        cat=catalog('这张卡也能把自己场上1只表侧表示怪兽除外，在盖放的回合发动。①：自己主要阶段才能发动。抽1张。',type=4)
        self.assertIn('activation_permission',{b['kind'] for b in all_blocks(cat)})
        self.assertNotIn('banish',{b['kind'] for b in all_blocks(cat)})
        self.assertTrue(any(b['kind']=='banish' and b['phase']=='alternative_activation_payment' for b in all_blocks(cat,'cost_blocks')))

    def test_targeted_card_reference_does_not_erase_a_send_cost(self):
        cat=catalog('对方怪兽的效果发动时，把成为对象的自己的卡全部送去墓地才能发动。这张卡从手卡特殊召唤。')
        self.assertTrue(any(c['kind']=='send_grave' for r in cat.effect_records(900001) for c in r['costs']))

    def test_legacy_lp_summon_is_a_procedure(self):
        for text in ('场上有表侧表示卡存在的场合，可以支付500基本分把这张卡从手卡特殊召唤。',
                     '这张卡可以支付2000基本分，从手卡特殊召唤。'):
            cat=catalog(text)
            self.assertNotIn('special_summon',{b['kind'] for b in all_blocks(cat)})
            self.assertTrue(any(b['kind']=='pay_lp' and b['phase']=='summon_payment' for b in all_blocks(cat,'procedure_blocks')))

    def test_material_destination_and_tribute_substitution_are_not_removal_effects(self):
        cat=catalog('被同调召唤使用的这张卡除外。')
        self.assertEqual({b['kind'] for b in all_blocks(cat)},{'grave_destination_replace'})
        cat=catalog('可以不把怪兽2只解放而从自己墓地把2只怪兽除外来上级召唤。')
        blocks=all_blocks(cat)
        self.assertEqual({b['kind'] for b in blocks},{'tribute_replace'})
        self.assertEqual(blocks[0]['qualifiers']['replacement_payments'][0]['quantity'],2)

    def test_lp_payment_inside_resolution_is_not_an_activation_cost(self):
        cat=catalog('伤害计算时才能发动。攻击力低的怪兽的控制者可以支付500基本分让那只怪兽的攻击力上升500。那之后，直到变成双方不支付基本分为止让这个效果重复。',type=2)
        self.assertTrue(all(not r['costs'] for r in cat.effect_records(900001)))
        self.assertEqual({b['kind'] for b in all_blocks(cat)},{'stats','lp_payment','repeat_effect'})

    def test_order_of_operations_is_not_reordering_a_deck(self):
        cat=catalog('①：自己主要阶段才能发动。以自己卡组·对方卡组最上面·对方的额外卡组的顺序来确认并各让1张除外。')
        self.assertNotIn('reorder_deck',{b['kind'] for b in all_blocks(cat)})

    def test_inspect_then_discard_is_processing_not_payment(self):
        cat=catalog('①：双方各自把对方手卡确认，从那之中选1张卡丢弃。那之后，双方各自从卡组抽1张。',type=2)
        self.assertTrue(all(not r['costs'] for r in cat.effect_records(900001)))
        self.assertIn('discard',{b['kind'] for b in all_blocks(cat)})

    def test_legacy_processing_followed_by_usage_limit_is_not_payment(self):
        for text,kind in (
            ('这张卡特殊召唤成功时，对方随机丢弃3张手卡。此效果仅当自己场上存在场地魔法时才适用。','discard'),
            ('这张卡的表示形式变更时，从卡组把1只水属性怪兽送去墓地。这个效果1回合只能使用1次。','send_grave'),
            ('选择对方墓地存在的1张卡从游戏中除外。这个效果1回合只能使用1次。','banish'),
            ('从卡组把1只龙族怪兽送去墓地。这个效果送去墓地的怪兽是通常怪兽的场合，可以再从卡组把1只龙族怪兽送去墓地。','send_grave'),
        ):
            cat=catalog(text)
            self.assertTrue(all(not r['costs'] for r in cat.effect_records(900001)))
            self.assertIn(kind,{b['kind'] for b in all_blocks(cat)})

    def test_permission_to_activate_another_card_is_not_an_activation_head(self):
        cat=catalog('①：自己可以把1张通常陷阱卡在盖放的回合的自己主要阶段发动。',type=2)
        self.assertIn('activation_permission',{b['kind'] for b in all_blocks(cat)})

    def test_scheduled_self_send_is_not_a_cost(self):
        cat=catalog('这张卡发动后，第2次的自己准备阶段送去墓地。①：自己主要阶段才能发动。抽1张。',type=2)
        self.assertFalse(all_blocks(cat,'cost_blocks'))
        sent=next(b for b in all_blocks(cat) if b['kind']=='send_grave')
        self.assertEqual(sent['phase'],'delayed')
        self.assertEqual(sent['qualifiers']['subject'],'this_card')

    def test_bounded_detach_selects_its_corresponding_result(self):
        cat=catalog('①：把这张卡最多2个超量素材取除才能发动。为这个效果发动而取除的超量素材数量的以下效果适用。●1个：从手卡把1只怪兽特殊召唤。●2个：从卡组把1只怪兽特殊召唤。')
        r,=cat.effect_records(900001)
        self.assertEqual(r['branch_records']['option:1']['costs'][0]['quantity'],1)
        self.assertEqual(r['branch_records']['option:2']['costs'][0]['quantity'],2)
        self.assertTrue(all(o['quantity']==1 for o in r['operations']))
        self.assertEqual(r['branch_records']['option:2']['operations'][0]['from_zones'],['deck'])

    def test_resolution_detach_does_not_become_activation_payment(self):
        cat=catalog('①：1回合1次，可以发动。这张卡的超量素材任意数量取除。这张卡的攻击力上升取除的超量素材种类×1000。')
        r,=cat.effect_records(900001)
        self.assertFalse(r['costs'])
        self.assertIn('detach',{o['kind'] for o in r['operations']})

    def test_lp_multiple_controls_subset_size(self):
        cat=catalog('①：可以支付2000的倍数的基本分，从以下效果选择支付的基本分每2000为1个的数量发动。●自己抽1张。●场上1只怪兽破坏。')
        r,=cat.effect_records(900001)
        self.assertEqual(r['block_view']['alternatives']['mode'],'subset')
        self.assertEqual(r['block_view']['alternatives']['count_binding']['divisor'],2000)
        self.assertIn('paid_subset_selection_requires_binding',r['unknown'])

    def test_named_summon_condition_does_not_lock_effect_activation(self):
        cat=catalog('这张卡不能通常召唤，用把5星以上的战士族怪兽解放发动的「匿名陷阱」的效果可以特殊召唤。①：自己主要阶段才能发动。抽1张。')
        for r in cat.effect_records(900001):
            self.assertNotIn('cannot_activate',{v['kind'] for key in ('restrictions','card_restrictions') for v in r[key]})
        self.assertIn('summon_condition',{d['kind'] for d in all_blocks(cat,'description_blocks')})

    def test_counter_condition_applies_to_the_whole_bullet(self):
        cat=catalog('①：这张卡战斗破坏怪兽的场合发动。给这张卡放置1个指示物。那之后，这张卡的指示物数量的以下效果适用。●1个：这张卡的攻击力上升400。●3个：这张卡回到额外卡组，自己抽3张。')
        drawn=next(b for b in all_blocks(cat) if b['kind']=='draw')
        self.assertEqual(drawn['qualifiers']['branch_condition']['value'],3)
        self.assertEqual(drawn['qualifiers']['quantity'],3)

    def test_target_count_variant_is_retained_on_stats_and_copy_summon(self):
        for text in (
            '①：以对方场上1只怪兽为对象才能发动。那只怪兽攻击力变成0，效果无效化。场上的这张卡为素材的场合这个效果的对象可以变成2只。',
            '①：以自己墓地1只通常怪兽为对象才能发动。那1只同名怪兽从卡组特殊召唤。自己场上有怪兽存在的场合，这个效果的对象可以变成2只。',
        ):
            r,=catalog(text).effect_records(900001)
            self.assertTrue(any(o.get('quantity_variants') for o in r['operations']))
            self.assertEqual(r['targets'][0]['quantity_variants'][0]['quantity'],2)


if __name__=='__main__':
    unittest.main()
