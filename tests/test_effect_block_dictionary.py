"""Approved granularity and false-positive regressions; no training, CB or native."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ygo_kito.build_contracts import digest
from ygo_kito.construction_binding import CatalogBindingAdapter
from ygo_kito.construction_effect_blocks import reviewed_effect_blocks
from ygo_kito.construction_inventory import InventoryDependencies, effect_matches
from ygo_kito.construction_logic import LogicTag
from ygo_kito.effect_blocks import BLOCK_VERSION, EffectBlockDictionary, build_dictionary, functional_tags
from ygo_kito.effect_mechanisms import MechanismCatalog, MECHANISM_WIDTH


def synthetic(text, **changes):
    row=dict(id=1,alias=0,type=33,name='匿名卡',desc=text,setcode=0,race=1,attribute=1,level=4)
    row.update(changes)
    return MechanismCatalog(SimpleNamespace(rows={row['id']:row},receipt={'resources':{'cards':'a'*64}}))


class EffectBlockDictionaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=json.loads((Path(__file__).parent/'fixtures/effect-blocks-accepted-cards.json').read_text(encoding='utf-8'))

    def setUp(self):
        self.assets=SimpleNamespace(rows={r['id']:deepcopy(r) for r in self.fixture['cards']},receipt=self.fixture['receipt'])
        self.catalog=MechanismCatalog(self.assets)

    def entry(self,code):return self.catalog.effect_blocks(code)
    def labels(self,code):return {t['tag']['value'] for t in functional_tags(self.entry(code))}

    def test_all_ten_approved_function_sets(self):
        expected={
            32003338:{'控制权取得'},62034800:{'特召','等级变更'},95735217:{'贯穿战斗伤害','追加攻击','检索','回收'},
            83982270:{'破坏','效果伤害'},72502414:{'补充超量素材'},32134638:{'效果无效','破坏','除外'},
            34314989:{'表侧放置','回收','特召','战斗破坏保护'},60950180:{'表示形式变更','特召'},
            41613948:{'除外'},93506862:{'响应限制'},
        }
        for code,labels in expected.items():
            with self.subTest(card=code):self.assertEqual(self.labels(code),labels)

    def test_charge_cost_and_vector_resolution_have_distinct_reasons_and_phases(self):
        charge=self.entry(94886282)['effects'][0]
        vector=self.entry(21623008)['effects'][0]
        self.assertEqual(self.labels(94886282),{'检索'})
        cost=charge['cost_blocks'][0]
        self.assertEqual((cost['tag']['value'],cost['phase'],cost['qualifiers']['quantity']),('送墓','activation_payment',3))
        self.assertTrue(cost['qualifiers']['random'])
        self.assertEqual(vector['cost_blocks'],[])
        mill=next(b for b in vector['blocks'] if b['kind']=='send_grave')
        self.assertEqual((mill['phase'],mill['qualifiers']['owner'],mill['qualifiers']['quantity']),('resolution','both',2))
        self.assertTrue(mill['qualifiers']['random'])
        self.assertIn('卡组送墓',self.labels(21623008))
        self.assertNotIn('卡组送墓',self.labels(94886282))

    def test_cost_materials_targets_and_identity_are_separate(self):
        entry=self.entry(32003338);effect=entry['effects'][0]
        self.assertIn({'dimension':'rank','value':'3'},entry['identity_tags'])
        self.assertFalse(any(t['dimension']=='level' for t in entry['identity_tags']))
        self.assertEqual(entry['summon_material_source'],'3星怪兽×3')
        self.assertEqual(effect['cost_blocks'][0]['tag']['value'],'取除素材')
        self.assertEqual(effect['cost_blocks'][0]['qualifiers']['quantity'],1)
        self.assertEqual(effect['target_refs'],[0])
        self.assertIn('4星以下',entry['source_records'][0]['targets'][0]['selector'])
        self.assertIn('自己主要阶段',[c['kind'] for c in effect['connectors']])

    def test_pendulum_duplicate_numbers_are_different_effects_and_not_costs(self):
        p,m=self.entry(32134638)['effects']
        self.assertNotEqual(p['effect_key'],m['effect_key'])
        self.assertEqual((p['scope'],m['scope']),('pendulum','monster'))
        self.assertEqual(p['cost_blocks'],[])
        self.assertTrue(all(c['starts_chain'] is False for c in p['connectors']))
        self.assertTrue(all(b['phase']=='continuous' for b in p['blocks']))
        self.assertTrue(any(c.get('period')=='presence' for c in p['count_limits']))
        from ygo_kito.construction_relations import _record_facts
        facts=[f for f,_ in _record_facts(32134638,self.catalog.effect_records(32134638))]
        self.assertEqual(len({f.effect_ref for f in facts}),2)
        self.assertFalse(any('repeated_effect_number_scope_unresolved' in f.unknown for f in facts))

    def test_choices_share_payment_but_do_not_merge_their_operations(self):
        first=self.entry(34314989)['effects'][0]
        self.assertEqual(len(first['cost_blocks']),1)
        self.assertEqual(first['alternatives'],{'mode':'one_of','branches':[1,2]})
        self.assertEqual([b['kind'] for b in first['blocks'] if b['branch']==1],['place'])
        self.assertEqual([b['kind'] for b in first['blocks'] if b['branch']==2],['recover','special_summon'])
        self.assertTrue(first['blocks'][-1]['qualifiers']['optional'])
        self.assertTrue(any(c.get('scope')=='same_name_each_option' for c in first['count_limits']))
        self.assertFalse(any(t['dimension']=='field' for t in self.entry(34314989)['identity_tags']))

    def test_summoned_this_turn_is_not_a_summon_trigger(self):
        first,second=self.entry(60950180)['effects']
        self.assertEqual([c['kind'] for c in first['connectors']],['自己主要阶段'])
        self.assertEqual([c['kind'] for c in second['connectors']],['自己主要阶段2'])
        summoned=self.entry(62034800)['effects'][0]
        self.assertEqual([c['kind'] for c in summoned['connectors']],['ns','ss'])

    def test_battle_send_and_material_attach_are_not_effect_mill_or_summon(self):
        self.assertNotIn('送墓',self.labels(83982270))
        self.assertEqual(self.entry(83982270)['effects'][0]['cost_blocks'],[])
        damage=next(b for b in self.entry(83982270)['effects'][0]['blocks'] if b['kind']=='damage')
        self.assertEqual(damage['qualifiers']['amount'],800)
        attached=self.entry(72502414)['effects'][0]
        self.assertEqual(attached['blocks'][0]['qualifiers']['to_zone'],'xyz_material')
        self.assertTrue(any(c.get('period')=='duel' for c in attached['count_limits']))

    def test_card_restrictions_remain_scoped_and_never_become_functions(self):
        self.assertTrue(any(r['kind']=='cannot_special_summon_this_card' for r in self.entry(95735217)['card_restrictions']))
        lock=next(r for r in self.entry(41613948)['card_restrictions'] if r['kind']=='cannot_declare_attack')
        self.assertEqual((lock['scope'],lock['duration']),('player','whole_turn'))
        self.assertEqual(self.entry(41613948)['effects'][0]['blocks'][0]['qualifiers']['duration'],'second_own_standby_phase')

    def test_reference_bullets_negatives_adjectives_and_reactive_ss_are_not_capabilities(self):
        texts=[
            ('①：包含以下效果的效果发动时，把这张卡从手卡丢弃才能发动。那个效果无效。\n●从卡组把卡加入手卡的效果\n●从卡组把怪兽特殊召唤的效果\n●从卡组把卡送去墓地的效果',{'效果无效'}),
            ('①：自己主要阶段才能发动。融合召唤的怪兽不会被效果破坏。',{'效果破坏保护'}),
            ('①：自己主要阶段才能发动。不能从卡组把怪兽特殊召唤。',set()),
            ('①：这个回合中，以下效果适用。\n●每次对方把怪兽特殊召唤，自己抽1张。',{'抽卡'}),
            ('①：自己主要阶段才能发动。从卡组把1张「融合」加入手卡。',{'检索'}),
            ('①：从卡组把装备魔法卡任意数量送去墓地才能发动（同名卡最多1张）。和送去墓地的卡数量相同等级的1只战士族怪兽从卡组特殊召唤。',{'特召'}),
        ]
        for text,expected in texts:
            with self.subTest(text=text):
                self.assertEqual({t['tag']['value'] for t in functional_tags(synthetic(text).effect_blocks(1))},expected)

    def test_same_wording_different_ids_is_not_a_card_answer_table(self):
        original=deepcopy(self.assets.rows[94886282]);original.update(id=12345,name='匿名样本')
        self.assets.rows[12345]=original
        a,b=self.entry(94886282),self.entry(12345)
        self.assertEqual(a['effects'],b['effects'])
        self.assertEqual(a['identity_tags'],b['identity_tags'])

    def test_new_view_also_refines_shared_operation_records(self):
        cat=synthetic('①：包含以下效果的效果发动时，把这张卡从手卡丢弃才能发动。那个效果无效。\n●从卡组把卡加入手卡的效果\n●从卡组把怪兽特殊召唤的效果')
        record=cat.effect_records(1)[0]
        self.assertEqual([o['kind'] for o in record['operations']],['negate'])
        self.assertEqual(record['costs'][0]['reason'],'cost')
        self.assertFalse(any(c['phase']=='resolution' and c.get('to_zone')=='hand' for c in record['resource_changes']))

    def test_unresolved_payment_boundary_cannot_become_effect_send(self):
        for suffix in ('','自己主要阶段可以发动。从卡组上面把3张卡送去墓地。'):
            cat=synthetic('①：从卡组把1张卡送去墓地才能发动（条件（复杂））。抽1张。'+suffix)
            self.assertEqual(cat.effect_records(1)[0]['operations'],[])
            self.assertEqual(functional_tags(cat.effect_blocks(1)),())

    def test_existing_relation_adapter_preserves_choices_and_processing_order(self):
        from ygo_kito.construction_relations import _record_facts
        record=self.catalog.effect_records(34314989)[0]
        self.assertEqual([o.get('choice') for o in record['operations']],['option:1','option:2','option:2'])
        self.assertEqual(record['operations'][2]['depends_on'],[record['operations'][1]['block_id']])
        facts=[fact for fact,_ in _record_facts(34314989,[record])]
        self.assertEqual([f.choice for f in facts],['option:1','option:2','option:2'])
        self.assertTrue(any(c.startswith('preceding_operation:') for c in facts[-1].conditions))
        claims = [{claim.pool_id for claim in fact.claims if 'same_name_each_option' in claim.pool_id} for fact in facts]
        self.assertTrue(all(claims))
        self.assertFalse(claims[0] & claims[1])
        self.assertEqual(claims[1],claims[2])  # One option's processing shares its limit.
        self.assertFalse(any('same_name_each_option' in item for fact in facts for item in fact.unknown))

    def test_summoning_procedure_is_not_activation_payment_or_resolution(self):
        cat=synthetic('①：这张卡可以从手卡特殊召唤。')
        effect=cat.effect_blocks(1)['effects'][0]
        self.assertEqual(effect['blocks'],[])
        self.assertEqual(effect['cost_blocks'],[])
        self.assertEqual(effect['procedure_blocks'][0]['phase'],'summon_procedure')
        self.assertEqual(cat.effect_records(1)[0]['operations'],[])
        self.assertEqual([c['kind'] for c in effect['connectors']],['召唤手续'])

    def test_counter_references_and_destination_position_are_scoped(self):
        cat=synthetic('①：这张卡放置的魔力指示物每有1个，这张卡的攻击力上升300。')
        self.assertEqual({t['tag']['value'] for t in functional_tags(cat.effect_blocks(1))},{'攻守变更'})
        cat=synthetic('①：以对方场上1只守备表示怪兽为对象才能发动。那只守备表示怪兽变成表侧攻击表示。')
        self.assertEqual(cat.effect_blocks(1)['effects'][0]['blocks'][0]['qualifiers']['position'],'attack')

    def test_synchro_instruction_and_targeted_recovery_keep_function(self):
        cat=synthetic('①：自己主要阶段才能发动。用包含这张卡的自己场上的怪兽为同调素材作同调召唤。')
        self.assertEqual({t['tag']['value'] for t in functional_tags(cat.effect_blocks(1))},{'同调召唤'})
        cat=synthetic('①：以自己墓地1只怪兽为对象才能发动。作为对象的怪兽加入手卡。')
        self.assertEqual({t['tag']['value'] for t in functional_tags(cat.effect_blocks(1))},{'回收'})

    def test_multiple_cost_origins_and_opponent_payment_do_not_leak(self):
        cat=synthetic('①：把自己墓地1只怪兽除外，把自己手卡1张卡除外才能发动。抽1张。')
        costs=cat.effect_records(1)[0]['costs']
        self.assertEqual([c['from_zones'] for c in costs],[['grave'],['hand']])
        cat=synthetic('①：从自己的手卡·场上把1只怪兽除外才能发动。抽1张。')
        self.assertEqual(cat.effect_records(1)[0]['costs'][0]['from_zones'],['hand','field'])
        cat=synthetic('①：把对方场上1只怪兽解放才能发动。抽1张。')
        self.assertEqual(cat.effect_records(1)[0]['costs'][0]['owner'],'opponent')

    def test_live_binding_and_inventory_read_the_same_dictionary(self):
        tags,assessments=reviewed_effect_blocks(self.assets,tuple(self.assets.rows),catalog=self.catalog)
        self.assertIn(LogicTag('effect','控制权取得'),tags)
        self.assertTrue(all(a.source==BLOCK_VERSION and a.quote in self.assets.rows[a.card_id]['desc'] for a in assessments))
        adapter=CatalogBindingAdapter(self.assets)
        self.assertEqual(adapter._tag_status(self.assets.rows[94886282],LogicTag('effect','送墓'))[0],'unknown')
        self.assertEqual(adapter._tag_status(self.assets.rows[32003338],LogicTag('effect','控制权取得'))[0],'satisfied')
        records=self.catalog.effect_records(62034800)
        self.assertTrue(effect_matches(records[1],(LogicTag('effect','等级变更'),)))
        self.assertFalse(effect_matches(records[0],(LogicTag('effect','等级变更'),)))
        unknown=InventoryDependencies(self.catalog).specs(34314989)[0][0]['unknown']
        self.assertTrue(unknown)
        summon=InventoryDependencies(self.catalog).specs(62034800)[0][0]
        self.assertFalse(any(u['category']=='block_selector' for u in summon['unknown']))
        self.assertTrue(any(u['category']=='operations'
            and u['source']==summon['record']['operations'][0]['source'] for u in summon['unknown']))

    def test_labels_are_short_source_spans_roundtrip_and_legacy_features_unchanged(self):
        before={c:self.catalog.vector(c) for c in self.assets.rows}
        for c in self.assets.rows:
            entry=self.entry(c)
            self.assertEqual(entry['text_sha256'],digest(self.assets.rows[c]['desc']))
            for effect,source in zip(entry['effects'],entry['source_records']):
                for b in effect['blocks']:
                    self.assertLessEqual(len(b['tag']['value']),8)
                    start,end=b['source_span'];self.assertEqual(source['source_text'][start:end],b['source'])
                    self.assertNotIn('connector',b['tag'])
                self.assertTrue(all(len(c['kind'])<=16 for c in effect['connectors']))
        self.assertEqual(MECHANISM_WIDTH,18)
        self.assertEqual(before,{c:self.catalog.vector(c) for c in self.assets.rows})

    def test_offline_index_matches_live_view_and_excludes_aliases_and_tokens(self):
        self.assets.rows[90]=dict(self.assets.rows[94886282],id=90,alias=94886282)
        self.assets.rows[91]=dict(self.assets.rows[94886282],id=91,type=0x4001)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'blocks.sqlite3'
            with patch.object(self.catalog,'fusion_goals',side_effect=AssertionError('CB is paused')):
                manifest=build_dictionary(self.catalog,path)
            self.assertEqual(manifest['canonical_cards'],12)
            with EffectBlockDictionary(path) as db:
                self.assertEqual(db.card(34314989),json.loads(json.dumps(self.entry(34314989))))
                self.assertIn(94886282,db.find('cost','送墓'))
                self.assertNotIn(94886282,db.find('effect','送墓'))
                self.assertIn(21623008,db.find('effect','送墓'))
                self.assertIn(62034800,db.find_connector('ss'))
                self.assertIsNone(db.card(90))
                self.assertIsNone(db.card(91))

    def test_text_change_invalidates_live_source_and_unknown_is_not_empty_success(self):
        self.assertIn('检索',self.labels(94886282))
        self.assets.rows[94886282]['desc']='①：将未定义的因果改写为另一条规则。'
        entry=self.entry(94886282)
        self.assertEqual(functional_tags(entry),())
        self.assertEqual(entry['effects'][0]['status'],'unresolved')
        self.assertTrue(entry['effects'][0]['unknown'])


class UnresolvedDictionaryRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture=json.loads((Path(__file__).parent/'fixtures/effect-blocks-unresolved-cards.json').read_text(encoding='utf-8'))
        cls.catalog=MechanismCatalog(SimpleNamespace(rows={r['id']:r for r in fixture['cards']},receipt=fixture['receipt']))

    def effect(self,code,key):
        return next(e for e in self.catalog.effect_blocks(code)['effects'] if e['effect_key']==key)

    def test_original_ten_have_the_correct_functions_or_structural_classification(self):
        expected=[(58392024,'spell_trap:0:0',{'回额外卡组'}),(44910027,'monster:0:0',{'特殊胜利'}),
                  (88093706,'monster:1:0',{'效果无效','战斗计算变更','效果伤害'}),(64342551,'monster:0:0',{'直接攻击'}),
                  (39910367,'spell_trap:3:2',{'费用代替'}),(82085295,'monster:3:2',set()),
                  (80896940,'monster:2:1',{'LP变更'}),(50366775,'monster:1:0',{'展示','素材身份代用'}),
                  (49064413,'monster:0:0',set()),(86527709,'spell_trap:1:0',{'种族变更'})]
        for code,key,labels in expected:
            with self.subTest(card=code):
                effect=self.effect(code,key)
                self.assertNotEqual(effect['status'],'unresolved')
                self.assertEqual({b['tag']['value'] for b in effect['blocks']},labels)
                self.assertEqual(effect['cost_blocks'],[])

    def test_old_fusion_deck_and_match_victory_keep_their_meanings(self):
        returned=self.effect(58392024,'spell_trap:0:0')['blocks'][0]
        self.assertEqual((returned['qualifiers']['to_zone'],returned['qualifiers']['owner']),('extra','both'))
        victory=self.effect(44910027,'monster:0:0')
        self.assertEqual((victory['blocks'][0]['qualifiers']['scope'],victory['blocks'][0]['qualifiers']['winner']),('match','controller'))
        tribute=victory['procedure_blocks'][0]
        self.assertEqual((tribute['phase'],tribute['qualifiers']['quantity'],tribute['qualifiers']['race_name']),('summon_procedure',3,'龙族'))

    def test_damage_calculation_limit_duration_and_conditional_burn(self):
        effect=self.effect(88093706,'monster:1:0')
        self.assertTrue(any(c['period']=='damage_calculation' and c['maximum']==1 for c in effect['count_limits']))
        self.assertFalse(any(c['period']=='turn' for c in effect['count_limits']))
        self.assertEqual(effect['blocks'][0]['qualifiers']['duration'],'damage_step_end')
        burn=effect['blocks'][-1]
        self.assertEqual(burn['qualifiers']['amount'],1000)
        self.assertTrue(any(c['target']==burn['block_id'] and '被破坏送去墓地时' in c['condition_source'] for c in effect['connectors']))
        from ygo_kito.construction_relations import _record_facts
        facts=[fact for fact,_ in _record_facts(88093706,self.catalog.effect_records(88093706)) if fact.output.kind=='damage']
        self.assertTrue(any('被破坏送去墓地时' in c for fact in facts for c in fact.conditions))
        self.assertTrue(all('operation_condition_unresolved' in fact.unknown for fact in facts))

    def test_cost_substitution_does_not_execute_its_own_payment(self):
        effect=self.effect(39910367,'spell_trap:3:2')
        block=effect['blocks'][0]
        self.assertEqual(block['phase'],'continuous')
        self.assertEqual(block['qualifiers']['counter_name'],'魔力指示物')
        self.assertEqual(block['qualifiers']['replaces'],'activation_payment')
        self.assertEqual(block['qualifiers']['quantity_rule'],'entire_payment')
        self.assertTrue(all(c.get('starts_chain') is False for c in effect['connectors']))
        self.assertTrue(any(c['period']=='turn' and c['count_event']=='apply' for c in effect['count_limits']))

    def test_restriction_and_noneffect_ritual_are_not_positive_summons(self):
        lock=self.effect(82085295,'monster:3:2')
        self.assertEqual(lock['status'],'restriction')
        self.assertEqual(lock['restrictions'][0]['kind'],'cannot_special_summon_from_extra')
        self.assertEqual(lock['restrictions'][0]['condition'],'this_card_in_monster_zone')
        ritual=self.effect(49064413,'monster:0:0')
        self.assertEqual(ritual['status'],'summon_description')
        self.assertEqual(ritual['description_blocks'][0]['ritual_card_names'],['假面魔兽的仪式'])

    def test_lp_and_continuous_race_change_do_not_become_damage_or_summons(self):
        lp=self.effect(80896940,'monster:2:1')['blocks'][0]
        self.assertEqual(lp['qualifiers']['fraction'],[1,2])
        self.assertEqual(lp['qualifiers']['owner'],'opponent')
        insect=self.effect(86527709,'spell_trap:1:0')['blocks'][0]
        self.assertEqual(insect['phase'],'continuous')
        self.assertNotIn('duration',insect['qualifiers'])
        self.assertEqual(insect['qualifiers']['race'],0x800)
        self.assertEqual(insect['qualifiers']['selector_condition'],'not_summoned_this_turn')

    def test_material_identity_references_revealed_monster_only_for_link_material(self):
        effect=self.effect(50366775,'monster:1:0')
        reveal,identity=effect['blocks']
        self.assertEqual(reveal['qualifiers']['from_zones'],['extra'])
        self.assertEqual(identity['qualifiers']['reference_block'],reveal['block_id'])
        self.assertEqual(identity['qualifiers']['fields'],['name','race','attribute'])
        self.assertEqual(identity['qualifiers']['summon_type'],'link')
        self.assertEqual(identity['qualifiers']['duration'],'turn')
        self.assertEqual(identity['qualifiers']['application'],'summon_material_only')
        unresolved=InventoryDependencies(self.catalog).specs(50366775)[0][0]['unknown']
        self.assertTrue(any(u['category']=='block_selector' for u in unresolved))

    def test_legacy_families_generalize_and_keep_unrecognized_remainders(self):
        cases=[('这张卡可以向对方直接攻击。',{'直接攻击'}),
               ('这张卡的卡名只要在场上存在当作「匿名名称」使用。',{'卡名变更'}),
               ('自己准备阶段发动。自己受到500伤害。',{'效果伤害'}),
               ('自己抽出自己场上的怪兽数量。',{'抽卡'}),
               ('这张卡可以用表侧守备表示的状态作出攻击。',{'守备攻击'}),
               ('直到结束阶段，这张卡的攻击力上升300。',{'攻守变更'})]
        for text,labels in cases:
            with self.subTest(text=text):
                self.assertEqual({t['tag']['value'] for t in functional_tags(synthetic(text).effect_blocks(1))},labels)
        unknown=synthetic('这张卡不能攻击。未定义的因果改写为另一条规则。').effect_blocks(1)['effects'][0]
        self.assertEqual(unknown['status'],'unresolved')
        self.assertTrue(unknown['restrictions'])

    def test_attack_payment_and_inherent_tribute_procedure_are_not_resolution(self):
        cat=synthetic('这张卡的攻击宣言之际，自己必须支付500基本分。')
        effect=cat.effect_blocks(1)['effects'][0]
        self.assertEqual(effect['blocks'],[])
        self.assertEqual(effect['cost_blocks'][0]['phase'],'attack_payment')
        record=cat.effect_records(1)[0]
        self.assertEqual(record['costs'],[])
        self.assertEqual(record['non_activation_costs'][0]['quantity'],500)
        effect=synthetic('这张卡可以不用解放作召唤。').effect_blocks(1)['effects'][0]
        self.assertEqual(effect['blocks'],[])
        self.assertEqual(effect['procedure_blocks'][0]['tag']['value'],'解放数量减少')

    def test_all_new_sample_records_reach_the_existing_relation_adapter(self):
        from ygo_kito.construction_relations import _record_facts
        for code in self.catalog.assets.rows:
            with self.subTest(card=code):
                list(_record_facts(code,self.catalog.effect_records(code)))

    def test_set_card_inspection_is_not_setting_a_new_card(self):
        cat=synthetic('①：自己·对方的结束阶段以对方场上盖放的1张魔法·陷阱卡为对象才能把这个效果发动。把那张卡确认，回到原状。',type=0x20002)
        self.assertEqual({t['tag']['value'] for t in functional_tags(cat.effect_blocks(1))},{'检视'})

    def test_index_exposes_new_functions_restrictions_and_descriptions_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'blocks.sqlite3';build_dictionary(self.catalog,path)
            with EffectBlockDictionary(path) as db:
                self.assertIn(64342551,db.find('effect','直接攻击'))
                self.assertIn(82085295,db.find('restriction','召唤限制'))
                # Its other effects genuinely summon; the third is only a lock.
                self.assertIn(82085295,db.find('effect','特召'))
                self.assertEqual(db.db.execute("select count(*) from tags where card_id=? and effect_key=? and dimension='effect'",
                                               (82085295,'monster:3:2')).fetchone()[0],0)
                self.assertIn(49064413,db.find('summon_description','仪式召唤说明'))
                self.assertNotIn(49064413,db.find('effect','仪式召唤'))


if __name__=='__main__':unittest.main()
