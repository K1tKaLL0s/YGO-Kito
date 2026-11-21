"""Approved granularity and false-positive regressions; no training, CB or native."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ygo_kito.build_contracts import DeckParts, digest
from ygo_kito.build_pipeline import BuildAssets
from ygo_kito.construction_binding import CatalogBindingAdapter
from ygo_kito.construction_effect_blocks import reviewed_effect_blocks
from ygo_kito.construction_inventory import InventoryDependencies, effect_matches
from ygo_kito.construction_logic import LogicTag
from ygo_kito.construction_layer_flow import functional_asset_version, normalize_function_uses, reference_asset_binding
from ygo_kito.construction_relations import _record_facts
from ygo_kito.effect_blocks import BLOCK_VERSION, EffectBlockDictionary, build_dictionary, functional_tags
from ygo_kito.effect_lua import LuaEffectSource
from ygo_kito.effect_mechanisms import MechanismCatalog, MECHANISM_WIDTH, SEMANTIC_VERSION
from ygo_kito.effect_records import effect_records
from ygo_kito.native_assets import LOCK_PATH, digest as file_digest, resource_hashes
from ygo_kito.validation import ContractError


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

    def test_resolution_connector_preserves_deck_mill_before_draw(self):
        first = '①：自己从卡组上面把3张卡送去墓地'
        for continuation in ('。那之后，', '，然后'):
            with self.subTest(continuation=continuation):
                catalog = synthetic(first + continuation + '自己从卡组抽1张。', type=2)
                record, = catalog.effect_records(1)
                self.assertEqual(record['costs'], [])
                self.assertEqual(record['trigger']['event'], 'card_activation')
                mill, draw = record['operations']
                self.assertEqual((mill['kind'], mill['quantity']), ('mill', 3))
                self.assertEqual((draw['kind'], draw['quantity']), ('draw', 1))
                self.assertEqual(draw['depends_on'], [mill['block_id']])
                self.assertTrue(all(op['reason'] == 'effect' for op in (mill, draw)))

    def test_shuffle_reborn_grave_payment_and_delayed_banish_have_distinct_roles(self):
        code, other = 14816688, 28004531
        catalog = synthetic('这个卡名的②的效果1回合只能使用1次。\n'
            '①：自己场上没有怪兽存在的场合，以自己墓地1只怪兽为对象才能发动。那只怪兽特殊召唤。'
            '这个效果特殊召唤的怪兽的效果无效化，结束阶段除外。\n'
            '②：把墓地的这张卡除外，以自己场上1张卡为对象才能发动。那张卡回到持有者卡组洗切，'
            '那之后自己从卡组抽1张。这个回合的结束阶段，自己1张手卡除外。',
            id=code, name='洗牌苏生', type=2)
        catalog.assets.rows[other] = dict(catalog.assets.rows[code], id=other, name='另一张墓地卡',
            desc='①：把墓地的这张卡除外才能发动。抽1张。')
        entry = catalog.effect_blocks(code)
        record = next(row for row in entry['source_records'] if row['effect_index'] == 2)
        effect = next(row for row in entry['effects'] if row['effect_key'] == record['effect_key'])
        self.assertEqual((record['trigger']['event'], record['trigger']['zone']), ('own_main_phase', 'grave'))
        self.assertEqual(record['unknown'], [])
        payment, = effect['cost_blocks']
        self.assertEqual((payment['kind'], payment['phase']), ('banish', 'activation_payment'))
        cost = payment['qualifiers']
        self.assertEqual((cost['from_zones'], cost['to_zone'], cost['quantity'], cost['subject']),
            (['grave'], 'banished', 1, 'this_card'))
        self.assertEqual(cost['selector_query'], {'predicate': {'field': 'card_ids', 'value': [code]}})
        operations = {op['kind']: op for op in record['operations']}
        target, = record['targets']
        self.assertEqual((target['owner'], target['zones'], operations['return_deck']['target_ref']), ('self', ['field'], 0))
        self.assertEqual(operations['draw']['depends_on'], [operations['return_deck']['block_id']])
        delayed = operations['banish']
        self.assertEqual((delayed['phase'], delayed['timing'], delayed['from_zones'], delayed['owner']),
            ('delayed', 'end_phase', ['hand'], 'self'))
        self.assertFalse(delayed['starts_chain'])
        self.assertFalse(delayed.get('depends_on'))

        from ygo_kito.build_contracts import DeckParts
        dependencies = InventoryDependencies(catalog)
        specs = next(row for row in dependencies.specs(code)[0] if row['record']['effect_index'] == 2)
        self.assertEqual(specs['unknown'], [])
        self.assertEqual([r['origin'] for r in specs['requirements']], ['grave', 'field', 'field'])
        own_payment, = [r for r in specs['requirements'] if r['category'] == 'costs']
        self.assertEqual(dependencies._check(DeckParts((other,)), [own_payment])['status'], 'missing')
        self.assertEqual(dependencies._check(DeckParts((code, other)), [own_payment])['status'], 'inventory_present')

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

    def test_dictionary_and_static_inventory_reuse_detached_records(self):
        from ygo_kito.build_contracts import DeckParts

        code = 62034800
        deck = DeckParts((code,))
        uncached = MechanismCatalog(self.assets)

        def generate(code):
            return effect_records(uncached.card(code), semantic_version=SEMANTIC_VERSION, row=self.assets.rows[code])

        with patch.object(uncached, 'effect_records', side_effect=generate) as cold:
            expected_entry = uncached.effect_blocks(code)
            expected_inventory = InventoryDependencies(uncached).evaluate(deck)
            self.assertGreater(cold.call_count, 1)
        expected_records = generate(code)

        with patch('ygo_kito.effect_records.effect_records', wraps=effect_records) as build:
            entry = self.entry(code)
            self.assertEqual(entry, expected_entry)
            records = self.catalog.effect_records(code)
            self.assertEqual(records, expected_records)
            records[0]['trigger']['event'] = 'modified'
            records[0]['block_view']['blocks'].clear()
            entry['effects'][0]['blocks'].clear()
            entry['source_records'][0]['operations'].clear()
            self.assertEqual(InventoryDependencies(self.catalog).evaluate(deck), expected_inventory)
            self.assertEqual(self.catalog.effect_records(code), expected_records)
            self.assertEqual(self.entry(code), expected_entry)
            build.assert_called_once()

    def test_records_follow_row_changes_and_card_database_generation(self):
        catalog = synthetic('「配套怪兽」＋战士族怪兽\n①：自己从卡组抽1张。', type=0x61)
        row = catalog.assets.rows[1]
        with patch('ygo_kito.effect_records.effect_records', wraps=effect_records) as build:
            self.assertTrue(catalog.effect_records(1)[0]['printed_materials'])
            row['type'] = 0x21
            self.assertEqual(catalog.card(1).materials, ())
            self.assertEqual(catalog.effect_records(1)[0]['printed_materials'], [])
            self.assertEqual(build.call_count, 2)

            catalog.assets.rows[1] = dict(row, name='改名卡')
            catalog.effect_records(1)
            self.assertEqual(build.call_count, 3)

            catalog.assets.receipt = {'resources': {'cards': 'b' * 64}}
            current = catalog.effect_records(1)
            self.assertEqual(current[0]['cards_sha256'], 'b' * 64)
            self.assertEqual(catalog.card(1).cards_sha256, 'b' * 64)
            self.assertEqual(build.call_count, 4)
            self.assertEqual(current, MechanismCatalog(catalog.assets).effect_records(1))

    def test_record_cache_evicts_old_entries_and_can_be_cleared(self):
        first, second, third = tuple(self.assets.rows)[:3]
        with (patch('ygo_kito.effect_mechanisms._EFFECT_RECORD_CACHE_SIZE', 2),
              patch('ygo_kito.effect_records.effect_records', wraps=effect_records) as build):
            for code in (first, second, first, third, first, second):
                self.catalog.effect_records(code)
            self.assertEqual([call.args[0].card_id for call in build.call_args_list],
                             [first, second, third, second])
            self.catalog.clear_card_cache()
            self.catalog.effect_records(second)
            self.assertEqual(build.call_count, 5)


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


CONSTANTS = """\
EFFECT_TYPE_SINGLE=1
EFFECT_TYPE_FIELD=2
EFFECT_TYPE_TRIGGER_O=0x80
EFFECT_TYPE_TRIGGER_F=0x200
EFFECT_TYPE_IGNITION=0x10
EFFECT_TYPE_QUICK_O=0x100
EFFECT_TYPE_ACTIVATE=0x20
EFFECT_FLAG_CANNOT_DISABLE=0x400
EFFECT_FLAG_UNCOPYABLE=0x800
EFFECT_FLAG_SINGLE_RANGE=0x20000
EFFECT_SPSUMMON_CONDITION=30
CATEGORY_SPECIAL_SUMMON=0x200
ATTRIBUTE_FIRE=4
RACE_DRAGON=8192
POS_FACEUP=5
HINTMSG_SPSUMMON=509
EVENT_FREE_CHAIN=1002
EFFECT_FLAG_NO_TURN_RESET=0x400000
EFFECT_FLAG_CARD_TARGET=0x10
EFFECT_FLAG_PLAYER_TARGET=0x800
EFFECT_CANNOT_SPECIAL_SUMMON=31
RESET_PHASE=0x40000000
PHASE_END=0x200
ATTRIBUTE_WATER=2
TYPE_SPELL=0x2
TYPE_TRAP=0x4
CATEGORY_TOGRAVE=0x20
CATEGORY_DRAW=0x10000
LOCATION_DECK=0x1
LOCATION_HAND=0x2
LOCATION_MZONE=0x4
LOCATION_SZONE=0x8
LOCATION_FZONE=0x100
REASON_EFFECT=0x40
REASON_COST=0x80
REASON_DISCARD=0x4000
HINT_SELECTMSG=3
HINTMSG_TOGRAVE=504
EVENT_SUMMON_SUCCESS=1100
EVENT_SPSUMMON_SUCCESS=1102
EVENT_TO_GRAVE=1014
HINT_OPSELECTED=6
LOCATION_GRAVE=0x10
LOCATION_EXTRA=0x40
"""

UTILITY = """\
function GetID()
    local offset=self_code<100000000 and 1 or 100
    return self_table,self_code,offset
end
function Auxiliary.Stringid(code,id)
    return code*16+id
end
"""

SCRIPT = """\
local s,id,o=GetID()
local n=1
function s.initial_effect(c)
    -- e:SetCountLimit(99,id)
    local note="e:SetCountLimit(99,id)"
    local e=Effect.CreateEffect(c)
    e:SetDescription(aux.Stringid(id,0))
    e:SetType(EFFECT_TYPE_SINGLE|EFFECT_TYPE_TRIGGER_O)
    e:SetCode(EVENT_SUMMON_SUCCESS)
    e:SetCountLimit(n,id)
    e:SetTarget(s.check)
    e:SetOperation(s.draw)
    c:RegisterEffect(e)
    local e2=e:Clone()
    e2:SetCode(EVENT_SPSUMMON_SUCCESS)
    c:RegisterEffect(e2)
    local n=2
    local e=Effect.CreateEffect(c)
    e:SetDescription(aux.Stringid(id,1))
    e:SetType(EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O)
    e:SetCode(EVENT_TO_GRAVE)
    e:SetCountLimit(n-1,id+o)
    e:SetOperation(s.draw)
    c:RegisterEffect(e)
end
function s.check(e,tp,eg,ep,ev,re,r,rp,chk)
    if chk==0 then return true end
end
function s.draw(e,tp)
    Duel.Draw(tp,1,REASON_EFFECT)
end
"""

INDEPENDENT = "这个卡名的①②的效果1回合各能使用1次。"
SHARED = "这个卡名的①②的效果1回合只能有1次使用其中任意1个。"
DESCRIPTION = "\n①：这张卡召唤·特殊召唤成功的场合才能发动。自己从卡组抽1张。\n" \
              "②：这张卡被效果送去墓地的场合才能发动。自己从卡组抽1张。"
LUA_CARD_ID = 10010002
DECK_SEND_TEXT = "从卡组把1张「幻影骑士团」卡或「幻影」魔法·陷阱卡送去墓地。"
DECK_SEND_SCRIPT = """\
local s,id=GetID()
function s.initial_effect(c)
    local e=Effect.CreateEffect(c)
    e:SetDescription(aux.Stringid(id,0))
    e:SetType(EFFECT_TYPE_SINGLE+EFFECT_TYPE_TRIGGER_O)
    e:SetCode(EVENT_SUMMON_SUCCESS)
    e:SetCountLimit(1,id)
    e:SetCategory(CATEGORY_DRAW)
    e:SetTarget(s.check)
    e:SetOperation(s.send)
    c:RegisterEffect(e)
    local e2=e:Clone()
    e2:SetCode(EVENT_SPSUMMON_SUCCESS)
    c:RegisterEffect(e2)
end
function s.filter(c)
    return (c:IsSetCard(0x10db) or (c:IsSetCard(0xdb) and c:IsType(TYPE_SPELL+TYPE_TRAP))) and c:IsAbleToGrave()
end
function s.check(e,tp,eg,ep,ev,re,r,rp,chk)
    if chk==0 then return Duel.IsExistingMatchingCard(s.filter,tp,LOCATION_DECK,0,1,nil) end
    Duel.SetOperationInfo(0,CATEGORY_TOGRAVE,nil,1,tp,LOCATION_DECK)
end
function s.send(e,tp,eg,ep,ev,re,r,rp)
    Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_TOGRAVE)
    local g=Duel.SelectMatchingCard(tp,s.filter,tp,LOCATION_DECK,0,1,1,nil)
    if #g>0 then
        Duel.SendtoGrave(g,REASON_EFFECT)
    end
end
"""
DECK_SEND_DESCRIPTION = (
    "这个卡名的①的效果1回合只能使用1次。\n"
    "①：这张卡召唤·特殊召唤成功的场合才能发动。" + DECK_SEND_TEXT
)


SELF_SEND_TEXT = "①：把手卡·场上的这张卡送去墓地才能发动。"
SELF_SEND_SCRIPT = """\
local s,id=GetID()
function s.initial_effect(c)
    local e=Effect.CreateEffect(c)
    e:SetDescription(aux.Stringid(id,0))
    e:SetType(EFFECT_TYPE_IGNITION)
    e:SetRange(LOCATION_HAND+LOCATION_MZONE)
    e:SetCost(s.pay)
    c:RegisterEffect(e)
end
function s.pay(e,tp,eg,ep,ev,re,r,rp,chk)
    local c=e:GetHandler()
    if chk==0 then return c:IsAbleToGraveAsCost() end
    Duel.SendtoGrave(c,REASON_COST)
end
"""


GRAVE_SUMMON_TEXT = ("①：以自己墓地1只炎属性怪兽为对象才能发动。"
                     "选自己1张手卡送去墓地，作为对象的怪兽特殊召唤。")
LEGACY_GRAVE_SUMMON_TEXT = ("选择自己墓地的1张怪兽卡。将1张手卡送去墓地，选择的那张怪兽卡特殊召唤。"
                            "这个效果1个回合只能使用1次。这张卡不能从墓地特殊召唤。")
GRAVE_SUMMON_SCRIPT = """\
local s,id=GetID()
function s.initial_effect(c)
    local e=Effect.CreateEffect(c)
    e:SetDescription(aux.Stringid(id,0))
    e:SetType(EFFECT_TYPE_ACTIVATE)
    e:SetCode(EVENT_FREE_CHAIN)
    e:SetProperty(EFFECT_FLAG_CARD_TARGET)
    e:SetTarget(s.target)
    e:SetOperation(s.operation)
    c:RegisterEffect(e)
end
function s.filter(c,e,tp)
    return c:IsAttribute(ATTRIBUTE_FIRE) and c:IsCanBeSpecialSummoned(e,0,tp,false,false)
end
function s.target(e,tp,eg,ep,ev,re,r,rp,chk,chkc)
    if chkc then return chkc:IsLocation(LOCATION_GRAVE) and chkc:IsControler(tp) and s.filter(chkc,e,tp) end
    if chk==0 then return Duel.IsExistingMatchingCard(Card.IsAbleToGrave,tp,LOCATION_HAND,0,1,e:GetHandler())
        and Duel.GetLocationCount(tp,LOCATION_MZONE)>0
        and Duel.IsExistingTarget(s.filter,tp,LOCATION_GRAVE,0,1,nil,e,tp) end
    Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_SPSUMMON)
    local g=Duel.SelectTarget(tp,s.filter,tp,LOCATION_GRAVE,0,1,1,nil,e,tp)
    Duel.SetOperationInfo(0,CATEGORY_SPECIAL_SUMMON,g,1,0,0)
end
function s.operation(e,tp,eg,ep,ev,re,r,rp)
    Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_TOGRAVE)
    if Duel.DiscardHand(tp,Card.IsAbleToGrave,1,1,REASON_EFFECT)<1 then return end
    local gc=Duel.GetOperatedGroup():GetFirst()
    if not gc:IsLocation(LOCATION_GRAVE) then return end
    local tc=Duel.GetFirstTarget()
    if tc:IsRelateToEffect(e) then Duel.SpecialSummon(tc,0,tp,tp,false,false,POS_FACEUP) end
end
"""
LEGACY_GRAVE_SUMMON_SCRIPT = GRAVE_SUMMON_SCRIPT.replace(
    "    e:SetType(EFFECT_TYPE_ACTIVATE)\n    e:SetCode(EVENT_FREE_CHAIN)",
    "    e:SetType(EFFECT_TYPE_IGNITION)\n    e:SetRange(LOCATION_MZONE)\n    e:SetCountLimit(1)",
).replace(
    "    local e=Effect.CreateEffect(c)", """\
    local p=Effect.CreateEffect(c)
    p:SetProperty(EFFECT_FLAG_CANNOT_DISABLE+EFFECT_FLAG_UNCOPYABLE+EFFECT_FLAG_SINGLE_RANGE)
    p:SetType(EFFECT_TYPE_SINGLE)
    p:SetRange(LOCATION_GRAVE)
    p:SetCode(EFFECT_SPSUMMON_CONDITION)
    c:RegisterEffect(p)
    local e=Effect.CreateEffect(c)""",
).replace(
    "c:IsAttribute(ATTRIBUTE_FIRE) and ", "",
).replace(
    "Duel.IsExistingMatchingCard(Card.IsAbleToGrave,tp,LOCATION_HAND,0,1,e:GetHandler())",
    "Duel.GetFieldGroupCount(tp,LOCATION_HAND,0)>0",
).replace(
    """    Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_TOGRAVE)
    if Duel.DiscardHand(tp,Card.IsAbleToGrave,1,1,REASON_EFFECT)<1 then return end
    local gc=Duel.GetOperatedGroup():GetFirst()
    if not gc:IsLocation(LOCATION_GRAVE) then return end""",
    """    if Duel.GetFieldGroupCount(tp,LOCATION_HAND,0)<=0 then return end
    Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_TOGRAVE)
    local sg=Duel.SelectMatchingCard(tp,Card.IsAbleToGrave,tp,LOCATION_HAND,0,1,1,nil)
    if sg:GetCount()==0 then return end
    if Duel.SendtoGrave(sg,REASON_EFFECT)==0 or not sg:GetFirst():IsLocation(LOCATION_GRAVE) then return end""",
)


HANDLER_GRAVE_SUMMON_TEXT = (
    "这个卡名的②的效果1回合只能使用1次。\n"
    "①：只要这张卡在怪兽区域存在，这张卡的等级在对方回合内上升4星。\n"
    "②：把1张手卡送去墓地，以自己墓地1只7·8星的龙族怪兽为对象才能发动。"
    "这张卡送去墓地，作为对象的怪兽特殊召唤。"
)
HANDLER_GRAVE_SUMMON_SCRIPT = """\
local s,id=GetID()
function s.initial_effect(c)
    local e=Effect.CreateEffect(c)
    e:SetDescription(aux.Stringid(id,0))
    e:SetType(EFFECT_TYPE_IGNITION)
    e:SetRange(LOCATION_MZONE)
    e:SetProperty(EFFECT_FLAG_CARD_TARGET)
    e:SetCountLimit(1,id)
    e:SetCost(s.cost)
    e:SetTarget(s.target)
    e:SetOperation(s.operation)
    c:RegisterEffect(e)
end
function s.cost(e,tp,eg,ep,ev,re,r,rp,chk)
    if chk==0 then return Duel.IsExistingMatchingCard(Card.IsAbleToGraveAsCost,tp,LOCATION_HAND,0,1,nil) end
    Duel.DiscardHand(tp,Card.IsAbleToGraveAsCost,1,1,REASON_COST)
end
function s.filter(c,e,tp)
    return c:IsRace(RACE_DRAGON) and c:IsLevel(7,8) and c:IsCanBeSpecialSummoned(e,0,tp,false,false)
end
function s.target(e,tp,eg,ep,ev,re,r,rp,chk,chkc)
    if chkc then return chkc:IsControler(tp) and chkc:IsLocation(LOCATION_GRAVE) and s.filter(chkc,e,tp) end
    if chk==0 then return Duel.GetLocationCount(tp,LOCATION_MZONE)>-1 and e:GetHandler():IsAbleToGrave()
        and Duel.IsExistingTarget(s.filter,tp,LOCATION_GRAVE,0,1,nil,e,tp) end
    Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_SPSUMMON)
    local g=Duel.SelectTarget(tp,s.filter,tp,LOCATION_GRAVE,0,1,1,nil,e,tp)
    Duel.SetOperationInfo(0,CATEGORY_TOGRAVE,e:GetHandler(),1,0,0)
    Duel.SetOperationInfo(0,CATEGORY_SPECIAL_SUMMON,g,1,0,0)
end
function s.operation(e,tp,eg,ep,ev,re,r,rp)
    local c=e:GetHandler()
    if c:IsRelateToEffect(e) and Duel.SendtoGrave(c,REASON_EFFECT)~=0 and c:IsLocation(LOCATION_GRAVE) then
        local tc=Duel.GetFirstTarget()
        if tc:IsRelateToEffect(e) then Duel.SpecialSummon(tc,0,tp,tp,false,false,POS_FACEUP) end
    end
end
"""


class LuaEffectBlockTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        registry = patch("ygo_kito.construction_inventory.archetype_names", return_value=({}, {}))
        registry.start()
        self.addCleanup(registry.stop)
        self.root = Path(temp.name)
        self.directory = self.root / "engine-src/scripts"
        self.directory.mkdir(parents=True)
        self.script = self.directory / f"c{LUA_CARD_ID}.lua"
        self.script.write_bytes(SCRIPT.encode())
        (self.directory / "constant.lua").write_bytes(CONSTANTS.encode())
        self.utility = self.directory / "utility.lua"
        self.utility.write_bytes(UTILITY.encode())

        files = (
            "engine-build/libocgcore.so", "engine-src/client/lflist.conf",
            "engine-src/core/ocgapi.h", "engine-src/core/common.h", "engine-src/core/card_data.h",
            "engine-src/client/gframe/config.h", "engine-src/client/gframe/duelclient.cpp",
        )
        for filename in files:
            path = self.root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"!2026.10\n" if path.name == "lflist.conf" else b"")
        self.cdb = self.root / "engine-src/database/locales/zh-CN/cards.cdb"
        self.cdb.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.cdb)) as db, db:
            db.executescript("""
                create table datas (id integer, alias integer, ot integer, type integer, setcode integer);
                create table texts (id integer, name text, desc text);
            """)
            db.execute("insert into datas values (?,0,1,33,0)", (LUA_CARD_ID,))
            db.execute("insert into texts values (?, ?, ?)", (LUA_CARD_ID, "fixture", INDEPENDENT + DESCRIPTION))

    def assets(self, *, script=None, prelude=None, description=None):
        if script is not None:
            self.script.write_bytes(script.encode())
        if prelude is not None:
            description = prelude + DESCRIPTION
        if description is not None:
            with closing(sqlite3.connect(self.cdb)) as db, db:
                db.execute("update texts set desc=?", (description,))
        receipt = dict(source_lock_sha256=file_digest(LOCK_PATH), resources=resource_hashes(self.root),
                       source_commits=dict(core="fixture-core", scripts="fixture-lua"))
        (self.root / "engine-build/receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        return BuildAssets(self.root)

    def test_resolution_summon_lock_consumes_original_scope_and_physical_recipients(self):
        from ygo_kito.build_semantics import matches
        from ygo_kito.construction_relations import _restriction_contract

        script = f"""
function c{LUA_CARD_ID}.initial_effect(c)
    local e=Effect.CreateEffect(c)
    e:SetDescription(aux.Stringid({LUA_CARD_ID},0))
    e:SetType(EFFECT_TYPE_IGNITION)
    e:SetRange(LOCATION_MZONE)
    e:SetOperation(c{LUA_CARD_ID}.resolve)
    c:RegisterEffect(e)
end
function c{LUA_CARD_ID}.resolve(e,tp)
    Duel.Draw(tp,1,REASON_EFFECT)
    local restriction=Effect.CreateEffect(e:GetHandler())
    restriction:SetCode(EFFECT_CANNOT_SPECIAL_SUMMON)
    restriction:SetType(EFFECT_TYPE_FIELD)
    restriction:SetProperty(EFFECT_FLAG_PLAYER_TARGET)
    restriction:SetTargetRange(1,0)
    restriction:SetTarget(c{LUA_CARD_ID}.blocked)
    restriction:SetReset(RESET_PHASE|PHASE_END)
    Duel.RegisterEffect(restriction,tp)
end
function c{LUA_CARD_ID}.blocked(e,c)
    return not c:IsAttribute(ATTRIBUTE_WATER)
end
"""
        text = '①：自己从卡组抽1张。这个回合，自己若非水属性怪兽则不能特殊召唤。'
        for variant, printing, resolved in (
            (script, text, True),
            (script.replace('    Duel.Draw', '    if Duel.GetTurnPlayer()~=tp then return end\n    Duel.Draw'), text, False),
            (script.replace('ATTRIBUTE_WATER)', 'ATTRIBUTE_FIRE)'), text, False),
            (script, text.replace('这个回合', '发动这个效果的回合'), False),
        ):
            with self.subTest(resolved=resolved, printing=printing, guarded=variant != script):
                assets = self.assets(script=variant, description=printing)
                assets.rows[LUA_CARD_ID].update(attribute=4, level=4)
                for code, attr in ((11, 2), (12, 4)):
                    assets.rows[code] = dict(id=code, alias=0, type=17, name=str(code), desc="",
                                             setcode=0, race=1, attribute=attr, level=4)
                stock = DeckParts((11, 12, LUA_CARD_ID))
                catalog = CatalogBindingAdapter(assets).semantic_catalog
                inventory = InventoryDependencies(catalog)
                (spec,), _ = inventory.specs(LUA_CARD_ID)
                restriction = next(rule for rule in spec["record"]["restrictions"]
                                   if rule["kind"] == "cannot_special_summon")
                if not resolved:
                    self.assertNotIn("lua_summon_lock", restriction)
                    continue
                contract = _restriction_contract(restriction)
                self.assertIs(contract["whole_turn"], False)
                self.assertEqual((contract["condition"], contract["duration"], contract["controller"]),
                                 ("effect_use", "turn", "self"))
                self.assertEqual(contract["lua_summon_lock"]["applies_after"], "resolution")
                self.assertEqual(len(restriction["evidence_refs"]), 2)
                allowed = tuple(code for code in stock.main if matches(assets.rows[code], contract["allowed_summons"]))
                self.assertEqual(allowed, (11,))
                summon = dict(kind="special_summon", from_zones=["deck"], to_zone="field", owner="self",
                              selector_query={"type": 1}, quantity=1,
                              source="从卡组把1只怪兽特殊召唤", phase="resolution")
                record = dict(spec["record"], operations=[summon], costs=[], targets=[])
                self.assertIs(inventory.summon_choice_check(stock, record, summon, allowed, physical_inventory=stock), True)
                without = DeckParts((12, LUA_CARD_ID))
                self.assertIs(inventory.summon_choice_check(without, record, summon, allowed, physical_inventory=without), False)

    def test_locked_resolution_send_allocates_the_original_target_and_a_separate_hand_card(self):
        from tests.test_construction_functional_flow import fixture
        from ygo_kito.build_contracts import BuildTask
        from ygo_kito.construction_layer_flow import ConstructionLayerAdapter

        for card_type, printing, script in ((2, GRAVE_SUMMON_TEXT, GRAVE_SUMMON_SCRIPT),
                                           (33, LEGACY_GRAVE_SUMMON_TEXT, LEGACY_GRAVE_SUMMON_SCRIPT)):
            with self.subTest(card_type=card_type):
                assets = self.assets(script=script, description=printing)
                assets.rows[LUA_CARD_ID]["type"] = card_type
                assets.rows[11] = dict(id=11, alias=0, type=17, name="火属性对象", desc="",
                                       setcode=0, race=1, attribute=4, level=4)
                assets.rows[12] = dict(id=12, alias=0, type=2, name="手卡资源", desc="", setcode=0)
                binder = CatalogBindingAdapter(assets)
                catalog = binder.semantic_catalog
                record, = catalog.effect_records(LUA_CARD_ID)
                target, = record["targets"]
                send, summon = record["operations"]
                observed, = record["lua_source"]["registrations"]
                evidence = observed["preselected_grave_summon"]
                self.assertEqual(record["lua_source"]["alignment"], "matched")
                self.assertEqual((target["timing"], target["zones"], summon["target_ref"]), ("activation", ["grave"], 0))
                self.assertEqual((send["from_zones"], send["reason"], send["processing_role"]), (["hand"], "effect", "auxiliary"))
                self.assertEqual(summon["depends_on"], [send["block_id"]])
                self.assertTrue(evidence["hand_send"]["requires_arrival"])
                self.assertLess(evidence["hand_send"]["movement_span"][0], evidence["summon"]["target_span"][0])
                self.assertEqual(record["costs"], [])
                if card_type == 33:
                    limit, = record["count_limits"]
                    self.assertEqual((limit["scope"], limit["maximum"]), ("this_card_effect", 1))
                    allowed, restriction = InventoryDependencies(catalog).candidate_status(LUA_CARD_ID,
                        dict(category="operations", operation=summon))
                    self.assertFalse(allowed)
                    self.assertEqual(restriction[0]["contract"]["from_zones"], ["grave"])

                deps = InventoryDependencies(catalog)
                adapter = ConstructionLayerAdapter(binder)
                template, _, _, _, _, policy = fixture()
                task = BuildTask.from_dict(dict(template.to_dict(), pool=sorted(assets.rows), requirements=[],
                    environment=assets.environment_for("deck_constraints"), sizes=dict(main=40, extra=0, side=15)))
                for main, side, supported in (
                    ((LUA_CARD_ID, 11), (), False),
                    ((LUA_CARD_ID, 11, 11), (), True),
                    ((LUA_CARD_ID, 11, 12), (), True),
                    ((LUA_CARD_ID, 12), (11,), False),
                    ((LUA_CARD_ID, 11), (12,), False),
                    ((LUA_CARD_ID, LUA_CARD_ID, 11), (), True),
                    ((LUA_CARD_ID, LUA_CARD_ID, LUA_CARD_ID), (), False),
                ):
                    with self.subTest(main=main, side=side):
                        deck = DeckParts(tuple(sorted(main)), (), side)
                        layer = dict(axis=dict(inventory=deck.to_dict(), task=task.to_dict(), logic=None))
                        direct, = deps.evaluate(deck, codes=(LUA_CARD_ID,))["cards"][str(LUA_CARD_ID)]["effects"]
                        evaluated, pending, stop = adapter.evaluate_inventory(task, deck, layer, None, policy=policy)
                        self.assertIsNone(pending)
                        self.assertIsNone(stop)
                        details, = [detail for key, detail in evaluated["use_details"].items()
                            if detail["card_id"] == LUA_CARD_ID and not key.endswith((":going_first", ":going_second"))]
                        self.assertEqual(details["operation"]["kind"], "special_summon")
                        self.assertEqual(details["processing_prerequisites"], [send])
                        self.assertEqual(details["relation"]["status"], "supported" if supported else "missing")
                        self.assertEqual(direct["status"], "inventory_present" if supported else "missing")
                        self.assertEqual(details["inventory_checks"]["processing"]["status"], direct["status"])

    def test_preselected_target_requires_complete_script_and_matching_printing(self):
        def record(script, printing=GRAVE_SUMMON_TEXT):
            assets = self.assets(script=script, description=printing)
            assets.rows[LUA_CARD_ID]["type"] = 2
            return MechanismCatalog(assets).effect_records(LUA_CARD_ID)[0]

        for script, printing in (
            (GRAVE_SUMMON_SCRIPT.replace("    if not gc:IsLocation(LOCATION_GRAVE) then return end\n", ""), GRAVE_SUMMON_TEXT),
            (GRAVE_SUMMON_SCRIPT.replace("local tc=Duel.GetFirstTarget()", "local tc=gc"), GRAVE_SUMMON_TEXT),
            (GRAVE_SUMMON_SCRIPT.replace("IsRelateToEffect(e)", "IsRelateToEffect(re)"), GRAVE_SUMMON_TEXT),
            (GRAVE_SUMMON_SCRIPT.replace("Card.IsAbleToGrave,1,1,REASON_EFFECT", "Card.IsAbleToGrave,1,2,REASON_EFFECT"), GRAVE_SUMMON_TEXT),
            (GRAVE_SUMMON_SCRIPT.replace("c:IsAttribute(ATTRIBUTE_FIRE) and ", ""), GRAVE_SUMMON_TEXT),
            (GRAVE_SUMMON_SCRIPT, GRAVE_SUMMON_TEXT.replace("，作为对象", "，也可以把作为对象")),
        ):
            with self.subTest(script=script, printing=printing):
                observed = record(script, printing)
                self.assertNotIn("preselected_grave_summon_status", observed["lua_source"])
                self.assertFalse(any(op.get("processing_role") == "auxiliary" for op in observed["operations"]))


    def test_handler_grave_summon_keeps_payment_availability_and_target_identity(self):
        from types import SimpleNamespace

        from tests.test_construction_functional_flow import fixture
        from ygo_kito.build_contracts import BuildTask
        from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
        from ygo_kito.effect_records import mechanism_summary

        assets = self.assets(script=HANDLER_GRAVE_SUMMON_SCRIPT, description=HANDLER_GRAVE_SUMMON_TEXT)
        assets.rows[LUA_CARD_ID].update(race=8192, level=4)
        for code, race, level in ((11, 8192, 7), (12, 8192, 8), (13, 8192, 6), (14, 2, 7)):
            assets.rows[code] = dict(id=code, alias=0, type=17, name=str(code), desc="",
                                     setcode=0, race=race, attribute=32, level=level)
        binder = CatalogBindingAdapter(assets)
        catalog = binder.semantic_catalog
        printed = MechanismCatalog(SimpleNamespace(rows=assets.rows, receipt=assets.receipt))
        records = catalog.effect_records(LUA_CARD_ID)
        position, record = next((pos, row) for pos, row in enumerate(records) if row["effect_index"] == 2)
        payment, = record["costs"]
        send, summon = record["operations"]
        registration, = record["lua_source"]["registrations"]
        evidence = registration["preselected_grave_summon"]
        self.assertEqual(registration["description_index"], 0)
        self.assertEqual(record["lua_source"]["preselected_grave_summon_status"], "bound")
        self.assertEqual(record["lua_source"]["count_status"], "bound")
        self.assertEqual((payment["owner"], payment["reason"], payment["phase"]), ("self", "cost", "activation_payment"))
        self.assertEqual((send["subject"], send["from_zones"], send["reason"]), ("this_card", ["field"], "effect"))
        self.assertTrue(send["requires_arrival"])
        self.assertEqual(record["targets"][0]["availability_timing"], "before_activation_payment")
        self.assertEqual(record["targets"][0]["selector_query"], {"type": 1, "race_any": 8192, "level_between": [7, 8]})
        self.assertEqual((summon["target_ref"], summon["depends_on"]), (0, [send["block_id"]]))
        self.assertLess(evidence["handler_send"]["arrival_span"][0], evidence["summon"]["target_span"][0])
        self.assertEqual(mechanism_summary(catalog, (LUA_CARD_ID,)),
                         mechanism_summary(printed, (LUA_CARD_ID,)))

        deps = InventoryDependencies(catalog)
        adapter = ConstructionLayerAdapter(binder)
        template, _, _, _, _, policy = fixture()
        task = BuildTask.from_dict(dict(template.to_dict(), pool=sorted(assets.rows), requirements=[],
            environment=assets.environment_for("deck_constraints"), sizes=dict(main=40, extra=0, side=15)))
        for main, side, supported in (
            ((LUA_CARD_ID, 11), (), False),
            ((LUA_CARD_ID, 11, 11), (), True),
            ((LUA_CARD_ID, 12, 14), (), True),
            ((LUA_CARD_ID, 13, 14), (), False),
            ((LUA_CARD_ID, 14, 14), (), False),
            ((LUA_CARD_ID, 14), (11,), False),
        ):
            with self.subTest(main=main, side=side):
                deck = DeckParts(main, (), side)
                direct = next(row for row in deps.evaluate(deck, codes=(LUA_CARD_ID,))["cards"][str(LUA_CARD_ID)]["effects"]
                              if row["key"].split(":")[2] == "2")
                layer = dict(axis=dict(task=task.to_dict(), inventory=deck.to_dict(), logic=None))
                evaluation, paused, stopped = adapter.evaluate_inventory(task, deck, layer, None, policy=policy)
                self.assertIsNone(paused)
                self.assertIsNone(stopped)
                detail, = [detail for key, detail in evaluation["use_details"].items()
                           if detail["operation_key"][:2] == (LUA_CARD_ID, position)
                           and not key.endswith((":going_first", ":going_second"))]
                self.assertEqual(detail["operation"]["kind"], "special_summon")
                self.assertEqual(detail["relation"]["status"], "supported" if supported else "missing")
                self.assertEqual(direct["status"], "inventory_present" if supported else "missing")
                self.assertEqual(detail["inventory_checks"]["processing"]["status"], direct["status"])
                self.assertEqual(detail["processing_prerequisites"], [send])

        # The same payment entity may be selected after it arrives, if another
        # eligible copy already exists. Compare the two legal allocations.
        deck = DeckParts((LUA_CARD_ID, 11, 12))
        target_only = dict(summon, selector_query=dict(summon["selector_query"],
            predicate={"field": "card_ids", "value": [12]}))
        proof = deps.processing_check(deck, record, target_only)
        self.assertEqual(proof["status"], "inventory_present")
        self.assertTrue(deps.summon_choice_check(deck, record, summon, (12,), physical_inventory=deck))
        no_seed = DeckParts((LUA_CARD_ID, 12))
        self.assertFalse(deps.summon_choice_check(no_seed, record, summon, (12,), physical_inventory=no_seed))
        self.assertFalse(deps.summon_choice_check(deck, record, summon, (LUA_CARD_ID,), physical_inventory=deck))

    def test_handler_grave_summon_accepts_equivalent_scoped_flow(self):
        script = HANDLER_GRAVE_SUMMON_SCRIPT
        script = "\n".join(line for line in script.splitlines() if not any(
            call in line for call in ("Duel.Hint(", "Duel.SetOperationInfo(", "e:SetDescription(")))
        script = script.replace(
            "Duel.DiscardHand(tp,Card.IsAbleToGraveAsCost,1,1,REASON_COST)",
            "local g=Duel.SelectMatchingCard(tp,Card.IsAbleToGraveAsCost,tp,LOCATION_HAND,0,1,1,nil)\n"
            "    Duel.SendtoGrave(g,REASON_COST)")
        script = script[:script.index("    local c=e:GetHandler()")] + """\
    local target=Duel.GetFirstTarget()
    if not e:GetHandler():IsRelateToEffect(e) then return end
    local moved=Duel.SendtoGrave(e:GetHandler(),REASON_EFFECT)
    if moved==0 or not e:GetHandler():IsLocation(LOCATION_GRAVE) then return end
    if not target:IsRelateToEffect(e) then return end
    Duel.SpecialSummon(target,0,tp,tp,false,false,POS_FACEUP)
end
"""
        script = script.replace("Duel.GetLocationCount(tp,LOCATION_MZONE)>-1 and e:GetHandler():IsAbleToGrave()",
                                "e:GetHandler():IsAbleToGrave() and Duel.GetMZoneCount(tp,e:GetHandler())>0")
        printing = HANDLER_GRAVE_SUMMON_TEXT.replace(
            "为对象才能发动。这张卡送去墓地，作为对象的怪兽特殊召唤。",
            "为对象；场上的这张卡送去墓地。那之后，那只怪兽特殊召唤。")
        assets = self.assets(script=script, description=printing)
        record = next(row for row in MechanismCatalog(assets).effect_records(LUA_CARD_ID)
                      if row["effect_index"] == 2)
        self.assertEqual(record["lua_source"]["preselected_grave_summon_status"], "bound")
        window, = record["lua_source"]["registrations"]
        self.assertNotIn("description_index", window)
        self.assertTrue(record["operations"][0]["requires_arrival"])

    def test_handler_grave_summon_requires_the_agreed_complete_callbacks(self):
        for before, after in (
            ("Duel.DiscardHand(tp,Card.IsAbleToGraveAsCost,1,1,REASON_COST)",
             "Duel.DiscardHand(tp,Card.IsAbleToGraveAsCost,1,1,REASON_EFFECT)"),
            ("c:IsRelateToEffect(e) and ", ""),
            (" and c:IsLocation(LOCATION_GRAVE)", ""),
            ("Duel.GetFirstTarget()", "c"),
            ("c:IsLevel(7,8)", "c:IsLevel(7,9)"),
            ("c:IsLevel(7,8)", "c:IsLevel(8)"),
        ):
            with self.subTest(before=before, after=after):
                assets = self.assets(script=HANDLER_GRAVE_SUMMON_SCRIPT.replace(before, after),
                                     description=HANDLER_GRAVE_SUMMON_TEXT)
                record = next(row for row in MechanismCatalog(assets).effect_records(LUA_CARD_ID)
                              if row["effect_index"] == 2)
                self.assertNotIn("preselected_grave_summon_status", record["lua_source"])
                self.assertNotIn("availability_timing", record["targets"][0])
                self.assertFalse(any(op.get("processing_role") == "auxiliary" for op in record["operations"]))

    def test_build_assets_bind_clone_and_count_to_existing_inventory_records(self):
        assets = self.assets()
        catalog = MechanismCatalog(assets)
        first, second = catalog.effect_records(LUA_CARD_ID)
        summon, special = first["lua_source"]["registrations"]
        self.assertEqual([summon["event"], special["event"]], ["normal_summon", "special_summon"])
        self.assertEqual(summon["family"], special["family"])
        self.assertEqual(special["clone_from"], summon["creation_span"][0])
        self.assertEqual(summon["target"]["definition"]["function"], "s.check")
        self.assertEqual(first["targets"], [])
        self.assertEqual(first["costs"], [])
        self.assertEqual([op["kind"] for op in first["operations"]], ["draw"])
        self.assertEqual([r["lua_source"]["count_status"] for r in (first, second)], ["bound", "bound"])
        self.assertEqual(first["count_limits"][0]["lua_counter"], {"code": LUA_CARD_ID, "script_card_id": LUA_CARD_ID})
        self.assertEqual(second["count_limits"][0]["lua_counter"]["code"], LUA_CARD_ID + 1)
        self.assertEqual(first["count_limits"], first["block_view"]["count_limits"])
        summon["count_limit"]["values"][0] = 99
        self.assertEqual(catalog.effect_records(LUA_CARD_ID)[0]["lua_source"]["registrations"][0]["count_limit"]["values"][0], 1)

        inventory = InventoryDependencies(catalog)
        specs, _ = inventory.specs(LUA_CARD_ID)
        observed = tuple(_record_facts(LUA_CARD_ID, (s["record"] for s in specs),
                                      dependencies=inventory, functional=True))
        self.assertEqual([p.pool_id for _, (p,) in observed],
                         [f"catalog-lua-limit:{LUA_CARD_ID}:{n}" for n in (LUA_CARD_ID, LUA_CARD_ID + 1)])
        self.assertTrue(all(f.claims[0].pool_id == p.pool_id and p.capacity == 1 for f, (p,) in observed))

    def test_deck_selection_refines_one_operation_and_reaches_inventory(self):
        assets = self.assets(script=DECK_SEND_SCRIPT, description=DECK_SEND_DESCRIPTION)
        row = assets.rows[LUA_CARD_ID]
        for code, kind, setcode in ((11, 33, 0x10db), (12, 4, 0xdb), (13, 33, 0xdb), (14, 33, 0)):
            assets.rows[code] = dict(row, id=code, type=kind, setcode=setcode,
                                     name=f"fixture {code}", desc="")
        catalog = MechanismCatalog(assets)
        record, = catalog.effect_records(LUA_CARD_ID)
        operation, = record["operations"]
        block, = record["block_view"]["blocks"]
        first, clone = record["lua_source"]["registrations"]
        observed = first["deck_send"]
        self.assertEqual(observed, clone["deck_send"])
        self.assertEqual(record["lua_source"]["deck_send_status"], "selector_bound")
        self.assertEqual(record["targets"], [])
        self.assertEqual(record["costs"], [])
        self.assertEqual(record["lua_source"]["count_status"], "bound")
        self.assertFalse(observed["selection"]["targets"])
        self.assertEqual(observed["activation_check"]["minimum"], 1)
        self.assertEqual(observed["filter"]["runtime_check"], "Card.IsAbleToGrave")
        self.assertEqual(operation["selector_query"], block["qualifiers"]["selector_query"])
        self.assertEqual(operation["selector_query"], record["resource_changes"][0]["selector_query"])
        raw = self.script.read_bytes()
        a, b = observed["transfer"]["byte_span"]
        self.assertEqual(raw[a:b], b"Duel.SendtoGrave(g,REASON_EFFECT)")

        inventory = InventoryDependencies(catalog)
        specs, _ = inventory.specs(LUA_CARD_ID)
        requirement, = specs[0]["requirements"]
        self.assertEqual((requirement["owner"], requirement["origin"], requirement["minimum"]), ("self", "deck", 1))
        for code, status in ((11, "inventory_present"), (12, "inventory_present"), (13, "missing"), (14, "missing")):
            with self.subTest(code=code):
                deck = DeckParts((LUA_CARD_ID, code))
                result = inventory.evaluate(deck, codes=(LUA_CARD_ID,))
                effect, = result["cards"][str(LUA_CARD_ID)]["effects"]
                self.assertEqual(effect["status"], status)
        side_only = DeckParts((LUA_CARD_ID, 14), (), (12,))
        effect, = inventory.evaluate(side_only, codes=(LUA_CARD_ID,))["cards"][str(LUA_CARD_ID)]["effects"]
        self.assertEqual(effect["status"], "missing")

        path = self.root / "deck-send.sqlite3"
        manifest = build_dictionary(catalog, path)
        self.assertEqual(manifest["lua"]["effect_deck_sends"], {"selector_bound": 1})
        with EffectBlockDictionary(path) as dictionary:
            self.assertEqual(dictionary.card(LUA_CARD_ID), catalog.effect_blocks(LUA_CARD_ID))
        operation["selector_query"].clear()
        self.assertTrue(catalog.effect_records(LUA_CARD_ID)[0]["operations"][0]["selector_query"])

    def test_deck_selection_uses_the_same_group_across_callback_styles(self):
        marker = "    Duel.SetOperationInfo(0,CATEGORY_TOGRAVE,nil,1,tp,LOCATION_DECK)"
        target_hint = ("    Duel.Hint(HINT_OPSELECTED,1-tp,e:GetDescription())\n" + marker)
        original = "    if #g>0 then\n        Duel.SendtoGrave(g,REASON_EFFECT)\n    end"
        variations = {
            "advisory calls and unused handler": DECK_SEND_SCRIPT.replace(marker, target_hint).replace(
                "function s.check(e,tp,eg,ep,ev,re,r,rp,chk)\n",
                "function s.check(e,tp,eg,ep,ev,re,r,rp,chk)\n    local c=e:GetHandler()\n"),
            "return on empty group": DECK_SEND_SCRIPT.replace(
                original, "    if g:GetCount()==0 then return end\n    Duel.SendtoGrave(g,REASON_EFFECT)"),
            "first and only member": DECK_SEND_SCRIPT.replace(original,
                "    local selected=g:GetFirst()\n    if selected then Duel.SendtoGrave(selected,REASON_EFFECT) end"),
            "chained first and only member": DECK_SEND_SCRIPT.replace(original, "    if g then Duel.SendtoGrave(g,REASON_EFFECT) end")
                .replace("1,1,nil)\n    if g then", "1,1,nil):GetFirst()\n    if g then"),
        }
        for label, script in variations.items():
            with self.subTest(style=label):
                assets = self.assets(script=script, description=DECK_SEND_DESCRIPTION)
                (record,) = MechanismCatalog(assets).effect_records(LUA_CARD_ID)
                self.assertEqual(record["lua_source"]["deck_send_status"], "selector_bound")
                self.assertEqual(record["operations"][0]["selector_query"], {"any": [
                    {"setcode": 0x10db}, {"setcode": 0xdb, "type": 6}]})

    def test_deck_selection_matches_rule_names_to_aliases_and_second_names(self):
        from ygo_kito.construction_inventory import matches

        header = self.root / "engine-src/core/card_data.h"
        header.write_text(
            "constexpr uint32_t OTHER = 501;\n"
            "const std::unordered_map<uint32_t, uint32_t> second_code = {\n"
            f"    {{OTHER, {LUA_CARD_ID}u}},\n"
            "};\n",
            encoding="utf-8",
        )
        script = DECK_SEND_SCRIPT.replace("    return (c:IsSetCard", "    return not c:IsCode(id) and (c:IsSetCard")
        assets = self.assets(script=script, description=DECK_SEND_DESCRIPTION)
        assets.rows[LUA_CARD_ID]["setcode"] = 0x10db
        assets.rows.update({
            500: dict(id=500, alias=LUA_CARD_ID, setcode=0x10db, type=1),
            501: dict(id=501, alias=0, setcode=0x10db, type=1),
            502: dict(id=502, alias=501, setcode=0x10db, type=1),
            503: dict(id=503, alias=0, setcode=0x10db, type=1),
        })
        catalog = MechanismCatalog(assets)
        record, = catalog.effect_records(LUA_CARD_ID)
        self.assertEqual(record["lua_source"]["deck_send_status"], "selector_bound")
        operation, = record["operations"]
        query = operation["selector_query"]
        self.assertEqual([code for code, row in assets.rows.items() if matches(row, query)], [503])

        # A callback with a mutable captured identity cannot supply this predicate.
        script = script.replace("function s.send(", "function s.change() id=503 end\nfunction s.send(")
        changed = self.assets(script=script)
        changed_record, = MechanismCatalog(changed).effect_records(LUA_CARD_ID)
        self.assertEqual(changed_record["lua_source"]["deck_send_status"], "unresolved_callback")

    def test_deck_selection_keeps_partial_evidence_from_other_scopes(self):
        for statement, status in (("c:EnableReviveLimit()", "selector_bound"),
                                  ("c:CopyEffect(id)", "unresolved_callback")):
            with self.subTest(statement=statement):
                script = DECK_SEND_SCRIPT.replace("    local e=Effect.CreateEffect(c)",
                    f"    {statement}\n    local e=Effect.CreateEffect(c)")
                assets = self.assets(script=script, description=DECK_SEND_DESCRIPTION)
                record, = MechanismCatalog(assets).effect_records(LUA_CARD_ID)
                lua = record["lua_source"]
                self.assertEqual(lua["status"], "partial")
                self.assertEqual(lua["deck_send_status"], status)
                self.assertEqual(lua["count_status"], "unresolved_registration")

    def test_deck_selection_keeps_an_existing_printed_selector(self):
        desc = DECK_SEND_DESCRIPTION.replace(DECK_SEND_TEXT, "从卡组把1只怪兽送去墓地。")
        record, = MechanismCatalog(self.assets(script=DECK_SEND_SCRIPT, description=desc)).effect_records(LUA_CARD_ID)
        operation, = record["operations"]
        self.assertEqual(record["lua_source"]["deck_send_status"], "printed_selector_retained")
        self.assertEqual(operation["selector_query"], {"type": 1, "selector": "怪兽"})

    def test_fixed_lua_quantity_does_not_override_a_printed_range(self):
        desc = DECK_SEND_DESCRIPTION.replace("把1张", "把最多1张")
        record, = MechanismCatalog(self.assets(script=DECK_SEND_SCRIPT, description=desc)).effect_records(LUA_CARD_ID)
        self.assertEqual(record["lua_source"]["deck_send_status"], "unresolved_printed_scope")
        self.assertNotIn("selector_query", record["operations"][0])

    def test_deck_selection_rejects_unsupported_flow_without_projecting_a_group(self):
        variations = (
            ("Duel.SendtoGrave(g,REASON_EFFECT)", "Duel.SendtoGrave(eg,REASON_EFFECT)",
             "not_the_selected_group_sent_by_effect"),
            ("Duel.SendtoGrave(g,REASON_EFFECT)", "Duel.SendtoGrave(g,REASON_COST)",
             "not_the_selected_group_sent_by_effect"),
            ("#g>0 then", "#g>0 and e:GetLabel()>0 then", "unsupported_send_branch"),
            ("0,1,1,nil)", "0,1,1,nil,e)", "unsupported_selection_arguments"),
            ("tp,s.filter,tp,LOCATION_DECK,0", "tp,s.filter,tp,0,LOCATION_DECK",
             "unsupported_selection_arguments"),
            ("0,1,1,nil)", "0,1,2,nil)", "variable_or_unresolved_selection_count"),
            ("0,1,nil) end", "0,2,nil) end", "unsupported_or_different_activation_check"),
            ("chk==0", "chk==false", "unsupported_or_different_activation_check"),
            ("c:IsAbleToGrave()", "c:IsAbleToGrave() and s.dynamic(c)", "unsupported_filter_predicate"),
            ("e:SetTarget(s.check)", "e:SetProperty(EFFECT_FLAG_CARD_TARGET)\n    e:SetTarget(s.check)",
             "card_targeting_or_unresolved_property"),
        )
        for old, new, reason in variations:
            with self.subTest(reason=reason):
                script = DECK_SEND_SCRIPT.replace(old, new)
                record, = MechanismCatalog(self.assets(script=script, description=DECK_SEND_DESCRIPTION)).effect_records(LUA_CARD_ID)
                self.assertEqual(record["lua_source"]["deck_send_status"], "unresolved_callback")
                observed = record["lua_source"]["registrations"][0]["deck_send"]
                self.assertEqual(observed["reason"], reason)
                start, end = observed["byte_span"]
                self.assertLess(start, end)
                self.assertLessEqual(end, len(script.encode()))
                self.assertNotIn("selector_query", record["operations"][0])
                self.assertFalse(record["targets"] or record["costs"])

    def test_self_send_cost_uses_one_handler_and_keeps_the_printed_summary(self):
        desc = SELF_SEND_TEXT + "自己从卡组抽1张。"
        direct = SELF_SEND_SCRIPT.replace("    local c=e:GetHandler()\n", "").replace(
            "c:IsAbleToGraveAsCost()", "e:GetHandler():IsAbleToGraveAsCost()").replace(
            "Duel.SendtoGrave(c,", "Duel.SendtoGrave(e:GetHandler(),")
        for script in (SELF_SEND_SCRIPT, direct):
            with self.subTest(direct=script == direct):
                assets = self.assets(script=script, description=desc)
                catalog = MechanismCatalog(assets)
                record, = catalog.effect_records(LUA_CARD_ID)
                lua = record["lua_source"]
                [registration] = lua["registrations"]
                self.assertEqual(lua["self_send_cost_status"], "bound")
                observed = registration["self_send_cost"]
                self.assertEqual(observed["activation_check"]["runtime_check"], "Card.IsAbleToGraveAsCost")
                start, end = observed["transfer"]["byte_span"]
                self.assertTrue(self.script.read_bytes()[start:end].endswith(b",REASON_COST)"))
                self.assertEqual([op["kind"] for op in record["operations"]], ["draw"])
                self.assertFalse(record["legality_verified"])
                cost, = record["costs"]
                self.assertEqual((cost["subject"], cost["source_card_id"], cost["quantity"], cost["owner"]),
                                 ("this_card", LUA_CARD_ID, 1, "self"))
                self.assertEqual(cost["selector_query"], {"predicate": {"field": "card_ids", "value": [LUA_CARD_ID]}})
                block, = record["block_view"]["cost_blocks"]
                movement = next(change for change in record["resource_changes"] if change["reason"] == "cost")
                for payment in (cost, block["qualifiers"], movement):
                    self.assertEqual((payment["from_zones"], payment["to_zone"], payment["reason"]),
                                     (["hand", "field"], "grave", "cost"))
                    self.assertEqual(payment["selector_query"], cost["selector_query"])
                self.assertEqual(block["phase"], "activation_payment")

                inventory = InventoryDependencies(catalog)
                specs, _ = inventory.specs(LUA_CARD_ID)
                req, = specs[0]["requirements"]
                self.assertEqual((req["origin"], req["origins"], req["minimum"], req["category"]),
                                 ("choice", ["hand", "field"], 1, "costs"))
                for deck, expected in ((DeckParts((LUA_CARD_ID,)), "inventory_present"),
                                       (DeckParts((), (), (LUA_CARD_ID,)), "missing")):
                    [effect] = inventory.evaluate(deck, codes=(LUA_CARD_ID,))["cards"][str(LUA_CARD_ID)]["effects"]
                    self.assertEqual(effect["status"], expected)
                summary = catalog.mechanism_summary((LUA_CARD_ID,))
                with patch.object(BuildAssets, "effect_lua_source", None):
                    self.assertEqual(summary, MechanismCatalog(assets).mechanism_summary((LUA_CARD_ID,)))

        path = self.root / "self-send.sqlite3"
        manifest = build_dictionary(catalog, path)
        self.assertEqual(manifest["lua"]["effect_self_send_costs"], {"bound": 1})
        with EffectBlockDictionary(path) as dictionary:
            self.assertEqual(dictionary.card(LUA_CARD_ID), catalog.effect_blocks(LUA_CARD_ID))
            self.assertEqual(dictionary.find("cost", "送墓"), (LUA_CARD_ID,))
            self.assertEqual(dictionary.find("effect", "送墓"), ())

    def test_self_send_cost_cannot_share_its_copy_with_a_deck_selection(self):
        from tests.test_construction_functional_flow import fixture

        task, _, _, _, _, policy = fixture()
        assets = self.assets(script=SELF_SEND_SCRIPT, description=SELF_SEND_TEXT + "从卡组把1只怪兽送去墓地。")
        catalog = MechanismCatalog(assets)
        dependencies = InventoryDependencies(catalog)
        record, = catalog.effect_records(LUA_CARD_ID)
        operation, = record["operations"]
        for deck, direct, route in (
            (DeckParts((LUA_CARD_ID,)), "missing", "missing"),
            (DeckParts((LUA_CARD_ID,), (), (LUA_CARD_ID,)), "missing", "missing"),
            (DeckParts((LUA_CARD_ID, LUA_CARD_ID)), "inventory_present", "supported"),
        ):
            with self.subTest(deck=deck):
                self.assertEqual(dependencies.processing_check(deck, record, operation)["status"], direct)
                facts = normalize_function_uses(task, deck, catalog, policy=policy)
                resident = {u.use_id for u in facts["uses"] if u.scope_id == "resident" and u.contributes}
                [use] = [d for uid, d in facts["use_details"].items() if uid in resident]
                self.assertEqual(use["relation"]["status"], route)
                self.assertEqual(use["semantics"]["reason"], "effect")

    def test_level_exclusion_search_respects_the_activation_payment_and_deck_zone(self):
        from tests.test_construction_functional_flow import fixture

        task, _, _, _, _, policy = fixture()
        text = SELF_SEND_TEXT + "从卡组把1只8星以外的怪兽加入手卡。"
        assets = self.assets(script=SELF_SEND_SCRIPT, description=text)
        source = assets.rows[LUA_CARD_ID]
        source["level"] = 3
        excluded, xyz = LUA_CARD_ID + 7, LUA_CARD_ID + 8
        assets.rows[excluded] = dict(source, id=excluded, name="八星怪兽", level=8, desc="")
        assets.rows[xyz] = dict(source, id=xyz, name="八阶怪兽", level=8, type=0x800021, desc="")
        catalog = MechanismCatalog(assets)
        dependencies = InventoryDependencies(catalog)
        record, = catalog.effect_records(LUA_CARD_ID)
        operation, = record["operations"]
        self.assertEqual(record["lua_source"]["self_send_cost_status"], "bound")
        self.assertEqual((operation["kind"], operation["from_zones"], operation["to_zone"],
                          operation["quantity"], operation["reason"], operation["random"]),
                         ("search_or_recover", ["deck"], "hand", 1, "effect", False))
        self.assertEqual(operation["selector_query"]["exclude_level"], 8)

        for deck, stock, route in (
            (DeckParts((LUA_CARD_ID, excluded)), "missing", "missing"),
            (DeckParts((LUA_CARD_ID,), (xyz,)), "missing", "missing"),
            (DeckParts((LUA_CARD_ID,), (), (LUA_CARD_ID,)), "missing", "missing"),
            (DeckParts((LUA_CARD_ID, LUA_CARD_ID)), "inventory_present", "supported"),
        ):
            with self.subTest(deck=deck):
                self.assertEqual(dependencies.processing_check(deck, record, operation)["status"], stock)
                facts = normalize_function_uses(task, deck, catalog, policy=policy)
                active = {use.use_id for use in facts["uses"] if use.scope_id == "resident" and use.contributes}
                use, = [detail for key, detail in facts["use_details"].items() if key in active]
                self.assertEqual(use["relation"]["status"], route)
                self.assertEqual(use["inventory_checks"]["costs"]["status"], "inventory_present")

    def test_self_send_cost_uses_each_registered_zone_and_ignores_presentation(self):
        for clause, mask, origins, locations in (
            ("将这张卡从手卡送去墓地", "LOCATION_HAND", ["hand"], ["HAND"]),
            ("把场上的这张卡送去墓地", "LOCATION_MZONE", ["field"], ["MZONE"]),
            ("把场地区域的这张卡送去墓地", "LOCATION_FZONE", ["field"], ["FZONE"]),
            ("把自己场上·手卡的这张卡送去墓地", "LOCATION_MZONE|LOCATION_HAND",
             ["hand", "field"], ["HAND", "MZONE"]),
        ):
            with self.subTest(mask=mask):
                script = SELF_SEND_SCRIPT.replace("LOCATION_HAND+LOCATION_MZONE", mask)
                script = script.replace("if chk==0", "if 0==chk").replace(
                    "    Duel.SendtoGrave(c,REASON_COST)",
                    "    Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_TOGRAVE)\n    Duel.SendtoGrave(e:GetHandler(),REASON_COST)")
                text = f"①：{clause}；自己从卡组抽1张。"
                catalog = MechanismCatalog(self.assets(script=script, description=text))
                record, = catalog.effect_records(LUA_CARD_ID)
                lua = record["lua_source"]
                self.assertEqual(lua["self_send_cost_status"], "bound")
                window, = lua.get("self_send_cost_registrations", lua.get("registrations", ()))
                self.assertEqual(window["self_send_cost"]["locations"], locations)
                cost, = record["costs"]
                self.assertEqual((cost["from_zones"], cost["requires_arrival"]), (origins, True))

    def test_self_send_cost_and_fixed_companion_use_distinct_copies(self):
        body = """\
    local c=e:GetHandler()
    if chk==0 then return Duel.IsExistingMatchingCard(Card.IsAbleToGraveAsCost,tp,LOCATION_HAND,0,1,c)
        and c:IsAbleToGraveAsCost() end
    Duel.Hint(HINT_SELECTMSG,tp,HINTMSG_TOGRAVE)
    local g=Duel.SelectMatchingCard(tp,Card.IsAbleToGraveAsCost,tp,LOCATION_HAND,0,1,1,c)
    g:AddCard(c)
    Duel.SendtoGrave(g,REASON_COST)
"""
        text = "①：从手卡把这张卡和1张卡送去墓地才能发动。自己从卡组抽1张。"
        original = SELF_SEND_SCRIPT.index("    local c=e:GetHandler()")
        for payment in (body, body.replace(",1,1,c)\n    g:AddCard(c)", ",1,1,c)+c")):
            script = SELF_SEND_SCRIPT[:original].replace("LOCATION_HAND+LOCATION_MZONE", "LOCATION_HAND") + payment + "end\n"
            assets = self.assets(script=script, description=text)
            catalog = MechanismCatalog(assets)
            inventory = InventoryDependencies(catalog)
            record, = catalog.effect_records(LUA_CARD_ID)
            self.assertEqual(record["lua_source"]["self_send_cost_status"], "bound")
            self.assertEqual(len(record["costs"]), 2)
            self.assertEqual(len(record["block_view"]["cost_blocks"]), 2)
            self.assertEqual(len([c for c in record["resource_changes"] if c["reason"] == "cost"]), 2)
            operation, = record["operations"]
            for deck, expected in (
                (DeckParts((LUA_CARD_ID,)), "missing"),
                (DeckParts((LUA_CARD_ID,), (), (LUA_CARD_ID,)), "missing"),
                (DeckParts((LUA_CARD_ID, LUA_CARD_ID)), "inventory_present"),
            ):
                with self.subTest(deck=deck):
                    check = inventory.evaluate(deck, codes=(LUA_CARD_ID,))["cards"][str(LUA_CARD_ID)]["effects"][0]
                    self.assertEqual(check["status"], expected)
                    self.assertEqual(inventory.processing_check(deck, record, operation)["status"], expected)
            with patch.object(BuildAssets, "effect_lua_source", None):
                self.assertEqual(catalog.mechanism_summary((LUA_CARD_ID,)),
                                 MechanismCatalog(assets).mechanism_summary((LUA_CARD_ID,)))
            bad_script = script.replace(",1,c)", ",1,nil)").replace(",1,1,c)", ",1,1,nil)")
            bad = MechanismCatalog(self.assets(script=bad_script, description=text)).effect_records(LUA_CARD_ID)[0]
            self.assertNotEqual(bad["lua_source"]["self_send_cost_status"], "bound")

    def test_self_send_cost_preserves_a_different_payment_and_the_target(self):
        script = SELF_SEND_SCRIPT.replace(
            "    e:SetCost(s.pay)",
            "    e:SetCost(s.pay)\n    e:SetProperty(EFFECT_FLAG_CARD_TARGET)\n    e:SetTarget(s.target)"
        ).replace(
            "if chk==0 then return c:IsAbleToGraveAsCost() end",
            "if chk==0 then return Duel.CheckLPCost(tp,500) and c:IsAbleToGraveAsCost() end\n"
            "    Duel.PayLPCost(tp,500)"
        ) + """\
function s.target(e,tp,eg,ep,ev,re,r,rp,chk,chkc)
    if chk==0 then return Duel.IsExistingTarget(Card.IsFaceup,tp,LOCATION_MZONE,0,1,e:GetHandler()) end
    Duel.SelectTarget(tp,Card.IsFaceup,tp,LOCATION_MZONE,0,1,1,nil)
end
"""
        text = ("①：把手卡·场上的这张卡送去墓地，支付500基本分，以自己场上1只怪兽为对象才能发动。"
                "那只怪兽的攻击力上升500。")
        assets = self.assets(script=script, description=text)
        catalog = MechanismCatalog(assets)
        record, = catalog.effect_records(LUA_CARD_ID)
        self.assertEqual(record["lua_source"]["self_send_cost_status"], "bound")
        self.assertEqual({(cost["kind"], cost["quantity"]) for cost in record["costs"]}, {("send_grave", 1), ("pay_lp", 500)})
        target, = record["targets"]
        self.assertEqual((target["timing"], target["selection_timing"]), ("activation", "after_activation_payment"))
        inventory = InventoryDependencies(catalog)
        operations = record["operations"]
        for deck, expected in (
            (DeckParts((LUA_CARD_ID,)), "missing"),
            (DeckParts((LUA_CARD_ID,), (), (LUA_CARD_ID,)), "missing"),
            (DeckParts((LUA_CARD_ID, LUA_CARD_ID)), "inventory_present"),
        ):
            with self.subTest(deck=deck):
                for selected in operations or (None,):
                    self.assertEqual(inventory.processing_check(deck, record, selected)["status"], expected)

    def test_grave_target_requires_availability_before_self_send(self):
        script = SELF_SEND_SCRIPT.replace(
            "    e:SetCost(s.pay)",
            "    e:SetCost(s.pay)\n    e:SetProperty(EFFECT_FLAG_CARD_TARGET)\n    e:SetTarget(s.target)"
        ) + """\
function s.target(e,tp,eg,ep,ev,re,r,rp,chk,chkc)
    if chk==0 then return Duel.IsExistingTarget(s.filter,tp,LOCATION_GRAVE,0,1,nil,e,tp) end
    Duel.SelectTarget(tp,s.filter,tp,LOCATION_GRAVE,0,1,1,nil,e,tp)
end
function s.filter(c,e,tp)
    return c:IsCanBeSpecialSummoned(e,0,tp,false,false)
end
"""
        text = ("①：把手卡·场上的这张卡送去墓地，以自己墓地1只怪兽为对象才能发动。"
                "那只怪兽特殊召唤。")
        assets = self.assets(script=script, description=text)
        existing = LUA_CARD_ID + 1
        assets.rows[existing] = dict(assets.rows[LUA_CARD_ID], id=existing, name="墓地对象", desc="")
        catalog = MechanismCatalog(assets)
        inventory = InventoryDependencies(catalog)
        record, = catalog.effect_records(LUA_CARD_ID)
        self.assertEqual(record["lua_source"]["self_send_cost_status"], "bound")
        target, = record["targets"]
        self.assertTrue(target["payment_may_supply_target"])
        summon, = record["operations"]
        for deck, expected in (
            (DeckParts((LUA_CARD_ID,)), False),
            (DeckParts((LUA_CARD_ID,), (), (existing,)), False),
            (DeckParts((LUA_CARD_ID, existing)), True),
        ):
            with self.subTest(deck=deck):
                choice = inventory.summon_choice_check(deck, record, summon, (LUA_CARD_ID,), physical_inventory=deck)
                self.assertIs(choice, expected)

    def test_self_send_cost_preserves_the_printed_record_when_lua_differs(self):
        desc = SELF_SEND_TEXT + "自己从卡组抽1张。"
        variations = (
            ("SendtoGrave(c,REASON_COST)", "SendtoGrave(eg,REASON_COST)", "handler_not_sent_as_cost"),
            ("SendtoGrave(c,REASON_COST)", "SendtoGrave(c,REASON_EFFECT)", "handler_not_sent_as_cost"),
            ("    Duel.SendtoGrave(c,REASON_COST)\n", "", "unsupported_cost_flow"),
            ("LOCATION_HAND+LOCATION_MZONE", "LOCATION_HAND+LOCATION_GRAVE", "unsupported_cost_activation_range"),
            ("c:IsAbleToGraveAsCost()", "e:GetLabel()==1 and c:IsAbleToGraveAsCost()",
             "unsupported_cost_feasibility_check"),
            ("e:SetCost(s.pay)", "e:SetOperation(s.pay)", "unresolved_cost_callback"),
        )
        for old, new, reason in variations:
            with self.subTest(reason=reason):
                assets = self.assets(script=SELF_SEND_SCRIPT.replace(old, new), description=desc)
                with patch.object(BuildAssets, "effect_lua_source", None):
                    printed, = MechanismCatalog(assets).effect_records(LUA_CARD_ID)
                record, = MechanismCatalog(assets).effect_records(LUA_CARD_ID)
                lua = record["lua_source"]
                self.assertEqual(lua["self_send_cost_status"], "unresolved_callback")
                [registration] = lua["registrations"]
                self.assertEqual(registration["self_send_cost"]["reason"], reason)
                for field in ("costs", "operations", "unknown", "block_view", "resource_changes"):
                    self.assertEqual(record[field], printed[field])

    def test_self_send_cost_never_rewrites_a_printed_hand_only_payment(self):
        desc = "①：把这张卡从手卡送去墓地才能发动。自己从卡组抽1张。"
        assets = self.assets(script=SELF_SEND_SCRIPT, description=desc)
        with patch.object(BuildAssets, "effect_lua_source", None):
            printed, = MechanismCatalog(assets).effect_records(LUA_CARD_ID)
        record, = MechanismCatalog(assets).effect_records(LUA_CARD_ID)
        self.assertEqual(record["costs"], printed["costs"])
        self.assertEqual(record["costs"][0]["from_zones"], ["hand"])
        self.assertEqual(record["costs"][0]["selector_query"], {"predicate": {"field": "card_ids", "value": [LUA_CARD_ID]}})

    def test_explicitly_shared_printed_effects_use_one_pool(self):
        assets = self.assets(script=SCRIPT.replace("n-1,id+o", "n-1,id"), prelude=SHARED)
        catalog = MechanismCatalog(assets)
        records = catalog.effect_records(LUA_CARD_ID)
        self.assertEqual([r["lua_source"]["count_status"] for r in records], ["bound", "bound"])
        facts = list(_record_facts(LUA_CARD_ID, records, static=True))
        self.assertEqual(facts[0][1], facts[1][1])
        self.assertEqual(facts[0][0].claims, facts[1][0].claims)
        self.assertEqual(facts[0][1][0].capacity, 1)

    def test_conflicting_scripts_keep_the_printed_limits(self):
        assets = self.assets(script=SCRIPT.replace("n-1,id+o", "n-1,id"))
        records = MechanismCatalog(assets).effect_records(LUA_CARD_ID)
        self.assertEqual([r["lua_source"]["count_status"] for r in records], ["printed_counter_conflict"] * 2)
        self.assertTrue(all("lua_counter" not in r["count_limits"][0] for r in records))
        self.assertEqual([p.pool_id for _, (p,) in _record_facts(LUA_CARD_ID, records, static=True)],
                         [f"catalog-limit:{LUA_CARD_ID}:{i}" for i in (1, 2)])

    def test_shared_counter_needs_every_member_to_use_the_same_binding(self):
        assets = self.assets(script=SCRIPT.replace("n-1,id+o", "n-1,id"), prelude=SHARED)
        row = assets.rows[LUA_CARD_ID]
        row["desc"] = row["desc"].replace("②：", "②：1回合1次，")
        first, second = MechanismCatalog(assets).effect_records(LUA_CARD_ID)
        self.assertEqual(len(second["count_limits"]), 2)
        self.assertEqual(first["lua_source"]["count_status"], "printed_counter_conflict")
        self.assertEqual(second["lua_source"]["count_status"], "printed_limit_unresolved")
        self.assertTrue(all("lua_counter" not in limit for r in (first, second) for limit in r["count_limits"]))

        no_reset = "e:SetProperty(EFFECT_FLAG_NO_TURN_RESET)\n    e:SetCountLimit(n-1,id)"
        assets = self.assets(script=SCRIPT.replace("e:SetCountLimit(n-1,id+o)", no_reset), prelude=INDEPENDENT)
        first, second = MechanismCatalog(assets).effect_records(LUA_CARD_ID)
        self.assertEqual(first["lua_source"]["count_status"], "printed_counter_conflict")
        self.assertEqual(second["lua_source"]["count_status"], "unsupported_or_inconsistent_counter")
        self.assertTrue(all("lua_counter" not in limit for r in (first, second) for limit in r["count_limits"]))

    def test_dynamic_and_malformed_scripts_keep_location_and_do_not_bind(self):
        conditional = SCRIPT.replace("e:SetCountLimit(n,id)", "if chk then e:SetCountLimit(n,id) end")
        for script, status in ((conditional, "partial"), ("function s.initial_effect(]\n", "syntax_error")):
            with self.subTest(status=status):
                catalog = MechanismCatalog(self.assets(script=script))
                record = catalog.effect_records(LUA_CARD_ID)[0]
                source = record["lua_source"]
                self.assertEqual(source["status"], status)
                self.assertTrue(all("byte_span" in row for row in source["unknown"]))
                self.assertTrue(source["unknown"])
                self.assertNotIn("lua_counter", record["count_limits"][0])

    def test_snapshot_and_reference_identity_follow_the_receipt(self):
        assets = self.assets()
        catalog = MechanismCatalog(assets)
        deck = DeckParts((LUA_CARD_ID,))
        version, reference = functional_asset_version(catalog), reference_asset_binding(catalog, deck)
        prior = catalog.effect_records(LUA_CARD_ID)
        self.utility.write_bytes(UTILITY.replace("1 or 100", "2 or 100").encode())
        self.assertEqual(prior, catalog.effect_records(LUA_CARD_ID))
        self.assertEqual(version, functional_asset_version(catalog))
        with self.assertRaisesRegex(ContractError, "scripts differ from the asset receipt"):
            LuaEffectSource(self.root, assets.receipt)
        changed = self.assets()
        catalog.assets = changed
        self.assertNotEqual(version, functional_asset_version(catalog))
        self.assertNotEqual(reference, reference_asset_binding(catalog, deck))
        record = catalog.effect_records(LUA_CARD_ID)[1]
        self.assertEqual(record["count_limits"][0]["lua_counter"]["code"], LUA_CARD_ID + 2)
        self.assertNotEqual(prior[1]["lua_source"]["scripts_sha256"], record["lua_source"]["scripts_sha256"])

        assets.receipt["resources"]["scripts"] = changed.receipt["resources"]["scripts"]
        with self.assertRaisesRegex(ContractError, "reload BuildAssets"):
            assets.effect_lua_source

    def test_normalization_does_not_reuse_specs_from_another_lua_snapshot(self):
        from tests.test_construction_functional_flow import fixture

        task, _, _, _, _, policy = fixture()
        deck = DeckParts((LUA_CARD_ID,))
        assets = self.assets()
        catalog = MechanismCatalog(assets)
        reuse = dict(specifications={}, projections={}, family_prices={})
        previous = normalize_function_uses(task, deck, catalog, policy=policy, reuse=reuse)
        self.assertEqual(reuse["specifications"][LUA_CARD_ID][1][0][1]["record"]
                         ["count_limits"][0]["lua_counter"]["code"], LUA_CARD_ID + 1)
        catalog.assets = self.assets(script=SCRIPT.replace("n-1,id+o", "n-1,id+2"))
        current = normalize_function_uses(task, deck, catalog, policy=policy, reuse=reuse)
        self.assertNotEqual(current["asset_version"], previous["asset_version"])
        specs, _ = reuse["specifications"][LUA_CARD_ID][1]
        self.assertEqual(specs[1]["record"]["count_limits"][0]["lua_counter"]["code"], LUA_CARD_ID + 2)
        self.assertEqual(current, normalize_function_uses(task, deck, catalog, policy=policy))

    def test_export_uses_the_same_counts_and_source_identity(self):
        assets = self.assets()
        catalog = MechanismCatalog(assets)
        path = self.root / "dictionary.sqlite3"
        manifest = build_dictionary(catalog, path)
        self.assertEqual(manifest["lua"]["effect_counters"], {"bound": 2})
        self.assertEqual(manifest["lua"]["binding"], catalog.lua_binding)
        with closing(sqlite3.connect(path)) as db:
            entry = json.loads(db.execute("select payload from cards where card_id=?", (LUA_CARD_ID,)).fetchone()[0])
        self.assertEqual(entry, catalog.effect_blocks(LUA_CARD_ID))


if __name__=='__main__':unittest.main()
