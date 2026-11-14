"""Static source/inventory regressions. No CB, engines, training or card recipes."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from ygo_kito.build_contracts import BuildTask, DeckParts
from ygo_kito.build_pipeline import DeckEdits
from ygo_kito.construction_binding import CatalogBindingAdapter
from ygo_kito.construction_candidates import portfolio
from ygo_kito.construction_inventory import (InventoryDependencies, matches, query_supported,
                                             repair_ideas, requirement, selector)
from ygo_kito.construction_logic import LogicTag
from ygo_kito.effect_mechanisms import MechanismCatalog
from tests.test_construction_layer_flow import flow_fixture
from tests.test_construction_binding import one_node


def fixture():
    value = list(flow_fixture())
    task, assets = value[:2]
    raw=task.to_dict();raw['sizes']['side']=1;raw['sizes']['extra']=1;raw['pool'].append(101)
    raw['goal']['constraints'][0].update(minimum=1, predicate={'field':'type_all','value':1})
    task=BuildTask.from_dict(raw)
    assets.rows[101]=dict(assets.rows[1],id=101,type=0x41,name='匿名融合目标',desc='Normal text')
    assets.rows[2].update(name='绯色素材', level=7, race=1)
    assets.rows[1]['desc']='①：从手卡把1只7星「绯色」怪兽送去墓地才能发动。从自己卡组上面把3张卡送去墓地。'
    deck=DeckParts((1,)+tuple(c for c in range(3,16) for _ in range(3)),(101,),(2,))
    fixed=replace(deck,main=tuple(sorted((2,)+tuple(c for c in deck.main if c!=1))),side=(1,))
    # For function coverage retain the consumer, moving a support from Side.
    supported=replace(deck,main=tuple(sorted([*deck.main[:-1],2])),side=(15,))
    value[:5]=[task,assets,one_node(LogicTag('effect','卡组送墓')),CatalogBindingAdapter(assets),[deck,supported]]
    for item in (deck,supported):assets.validate(task,item)
    return value, InventoryDependencies(MechanismCatalog(assets)), fixed


class InventoryDependencyTests(unittest.TestCase):
    def test_xyz_overlay_is_an_alternative_and_keeps_its_battle_condition(self):
        value, dependencies, _ = fixture()
        assets, deck = value[1], value[4][0]
        assets.rows[101].update(type=0x800021, level=12, desc=
            '12星怪兽×2\n这张卡在超量怪兽进行过战斗的回合有1次也能在自己场上的超量怪兽上面重叠来超量召唤。'
            '\n①：自己主要阶段才能发动。抽1张。')
        assets.rows[102] = dict(assets.rows[101], id=102, name='匿名超量怪兽', desc='4星怪兽×2', level=4)
        assets.rows[2]['level'] = 12
        procedures = [r for r in dependencies.catalog.effect_records(101) if 'summon_procedure' in r]
        record, = procedures
        self.assertEqual(record['unknown'], [])
        procedure = record['summon_procedure']
        self.assertEqual(procedure['condition'], {'kind': 'xyz_monster_battled_this_turn'})
        self.assertTrue(procedure['transfers_xyz_materials'])
        self.assertFalse(procedure['starts_chain'])
        self.assertEqual(procedure['per_turn_maximum'], 1)
        self.assertEqual(dependencies.summon_material_check(deck, 101)['status'], 'missing')
        overlay = dependencies.summon_material_check(replace(deck, extra=(101,102)), 101)
        self.assertEqual(overlay['status'], 'inventory_present')
        self.assertEqual(overlay['requirements'][0]['matching_card_ids'], [102])
        same_name = dependencies.summon_material_check(replace(deck, extra=(101,101)), 101)
        self.assertEqual(same_name['status'], 'unknown')
        normal = dependencies.summon_material_check(replace(deck, main=(*deck.main,2,2)), 101)
        self.assertEqual(normal['status'], 'inventory_present')
        self.assertNotIn('summon_procedure', normal)

    def test_inclusion_link_materials_and_same_turn_restrictions(self):
        value, dependencies, _ = fixture()
        assets, deck = value[1], value[4][0]
        assets.rows[101].update(type=0x4000021, level=2, desc=
            '包含2星·2阶·连接2的怪兽在内的怪兽2只\n这张卡在连接召唤的回合不能作为连接素材。'
            '这个卡名的①的效果1回合只能使用1次。\n①：自己主要阶段才能发动。抽1张。')
        assets.rows[102] = dict(assets.rows[101], id=102, name='匿名2阶怪兽', desc='2星怪兽×2',
                               level=2, type=0x800021)
        assets.rows[103] = dict(assets.rows[101], id=103, name='匿名连接2怪兽', desc='效果怪兽2只')
        assets.rows[104] = dict(assets.rows[101], id=104, name='匿名4阶怪兽', desc='4星怪兽×2',
                               level=4, type=0x800021)
        assets.rows[2]['level'] = 2
        for base in (102,103):
            with self.subTest(base=base):
                self.assertEqual(dependencies.summon_material_check(replace(deck, extra=(101,base)), 101)['status'],
                                 'inventory_present')
        self.assertEqual(dependencies.summon_material_check(replace(deck, extra=(101,104)), 101)['status'], 'missing')
        self.assertEqual(dependencies.summon_material_check(replace(deck, main=(*deck.main,2)), 101)['status'],
                         'inventory_present')
        only_one = replace(deck, main=(2,), extra=(101,))
        self.assertEqual(dependencies.summon_material_check(only_one, 101)['status'], 'missing')
        req = dict(category='material', origin='field', summon_type='link')
        self.assertTrue(dependencies.candidate_status(101, req, target=103)[0])
        same_turn = dict(req, summon_history={'kind': 'link_summon', 'this_turn': True})
        self.assertFalse(dependencies.candidate_status(101, same_turn, target=103)[0])
        later = dict(req, summon_history={'kind': 'link_summon', 'this_turn': False})
        self.assertTrue(dependencies.candidate_status(101, later, target=103)[0])
        different = dict(req, summon_history={'kind': 'pendulum_summon', 'this_turn': True})
        self.assertTrue(dependencies.candidate_status(101, different, target=103)[0])

    def test_extra_cost_uses_actual_section_and_complete_integer_payment(self):
        value, dependencies, _ = fixture()
        assets, deck = value[1], value[4][0]
        assets.rows[1]['desc'] = '①：自己主要阶段，把自己额外卡组的1张卡除外才能发动。抽1张。'
        effects, _ = dependencies.specs(1)
        cost, = effects[0]['record']['costs']
        self.assertEqual((cost['kind'],cost['from_zones'],cost['to_zone']),('banish',['extra'],'banished'))
        self.assertEqual(effects[0]['record']['conditions']['status'],'recognized')
        requirements = effects[0]['requirements']
        self.assertEqual(dependencies._check(deck,requirements,distinct=True)['status'],'inventory_present')
        absent = replace(deck,extra=())
        self.assertEqual(dependencies._check(absent,requirements,distinct=True)['status'],'missing')
        doubled = [dict(requirements[0],minimum=2)]
        self.assertEqual(dependencies._check(deck,doubled,distinct=True)['shortfall'],1)

    def test_structured_selectors_external_targets_and_unknown_positions(self):
        value, dependencies, _ = fixture()
        deck = value[4][1]
        item = dict(source='complete supplied selection',quantity=1,from_zones=['grave'],owner='self',
            selector_query={'predicate':{'all':[{'field':'card_ids','value':[2]},
                {'field':'level_between','value':[7,7]}]}})
        req = dependencies.item_requirement(item,'costs')
        self.assertEqual(dependencies._check(deck,[req])['status'],'inventory_present')
        self.assertEqual(dependencies._check(replace(deck,main=tuple(c for c in deck.main if c!=2)),[req])['status'],'missing')
        unknown = dict(req,query={**req['query'],'unobserved_exception':True})
        self.assertEqual(dependencies._check(deck,[unknown])['status'],'unknown')
        opponent = dependencies.item_requirement(dict(source='以对方场上的1张卡为对象',quantity=1),'targets')
        external = dependencies._check(deck,[opponent])
        self.assertEqual((external['status'],external['shortfall']),('unknown',0))
        self.assertEqual(external['requirements'][0]['matching_card_ids'],[])
        faceup = dict(req,query={**req['query'],'face_up':True})
        self.assertEqual(dependencies._check(deck,[faceup])['status'],'unknown')
        extra = dependencies.item_requirement(dict(item,from_zones=['extra'],selector_query={'type':'fusion'}),'costs')
        self.assertEqual(dependencies._check(deck,[extra])['status'],'inventory_present')
        self.assertEqual(dependencies._check(replace(deck,extra=()),[extra])['status'],'missing')

    def test_material_prohibitions_use_each_actual_summon_type(self):
        from ygo_kito.construction_inventory import matches
        for name,kind,mask in (('融合','fusion',0x41),('同调','synchro',0x2001),('超量','xyz',0x800001),
                               ('连接','link',0x4000001),('仪式','ritual',0x81)):
            with self.subTest(kind=kind):
                value,dependencies,_ = fixture()
                value[1].rows[2]['desc'] = '这张卡不能作为'+name+'素材。①：自己主要阶段才能发动。抽1张。'
                value[1].rows[101]['type'] = mask
                req = dict(query=selector('「绯色素材」'),minimum=1,source='complete material',origin='field',category='material')
                blocked = dependencies._check(value[4][1],[req],joint=True,target=101)
                self.assertEqual(blocked['status'],'missing')
                permitted = dict(req,summon_type='link' if kind!='link' else 'fusion')
                self.assertEqual(dependencies._check(value[4][1],[permitted],joint=True,target=101)['status'],'inventory_present')
                q = dependencies.resolve_query({'type':kind})
                self.assertTrue(matches(value[1].rows[101],q))
                self.assertFalse(matches(value[1].rows[2],q))

    def test_summon_only_by_a_named_effect_is_not_a_summon_function(self):
        value, dependencies, _ = fixture()
        value[1].rows[2]['desc'] = '「指定之门」的效果才能特殊召唤。①：自己主要阶段才能发动。抽1张。'
        records = dependencies.catalog.effect_records(2)
        self.assertEqual([op['kind'] for record in records for op in record['operations']], ['draw'])
        descriptions = [d for record in records for d in record['block_view']['description_blocks']]
        self.assertTrue(any(d['kind'] == 'summon_condition' for d in descriptions))

    def test_intrinsic_summon_prohibitions_check_the_recipient_and_keep_other_uses(self):
        value, dependencies, _ = fixture()
        assets, deck = value[1], value[4][1]
        assets.rows[2]['desc'] = '这张卡不能通常召唤。这张卡不能特殊召唤。①：自己主要阶段才能发动。抽1张。'
        req = dict(query=selector('「绯色素材」'), minimum=1, source='complete recipient', origin='hand',
            category='operations', operation=dict(kind='special_summon', from_zones=['hand'], to_zone='field',
                owner='self', controller='opponent'))
        for action in ('normal_summon', 'tribute_summon', 'special_summon'):
            with self.subTest(action=action):
                req['operation']['kind'] = action
                result = dependencies._check(deck, [req])
                self.assertEqual((result['status'], result['shortfall']), ('missing', 1))
                checks = result['requirements'][0]['restriction_checks']
                self.assertTrue(checks)
                self.assertTrue(all((check['card_id'],check['controller'],check['allowed'])==(2,'opponent',False)
                    for check in checks))
        for action in ('send_grave', 'search_or_recover'):
            req['operation']['kind'] = action
            self.assertEqual(dependencies._check(deck, [req])['status'], 'inventory_present')
        own = dependencies.evaluate(deck, codes=(2,))['cards']['2']['effects'][0]
        self.assertEqual(own['status'], 'inventory_present')
        for event, status in (('normal_summon', 'missing'), ('special_summon', 'missing'),
                              ('normal_or_special_summon', 'missing'), ('own_main_phase', 'inventory_present')):
            self.assertEqual(dependencies.summon_trigger_check(2, {'trigger':{'event':event}})['status'], status)
        assets.rows[2]['desc'] = '这张卡不能特殊召唤，但可以用指定效果召唤。①：自己主要阶段才能发动。抽1张。'
        dependencies = InventoryDependencies(dependencies.catalog)
        req['operation']['kind'] = 'special_summon'
        unknown = dependencies._check(deck, [req])
        self.assertEqual((unknown['status'], unknown['shortfall']), ('unknown', 0))
        rule = unknown['requirements'][0]['restriction_checks'][0]['restriction']
        self.assertIn('但可以用指定效果召唤', rule['source'])
        self.assertEqual(rule['observed_source'], '这张卡不能特殊召唤')
        # Adaptation is detached: the raw effect records remain unchanged.
        self.assertFalse(dependencies.catalog.effect_records(2)[0]['card_restrictions'])
        self.assertEqual(dependencies._check(value[4][0], [req])['status'], 'missing')
        assets.rows[2]['desc'] = '这张卡不能特殊召唤。指定效果召唤的场合不受这个限制。①：自己主要阶段才能发动。抽1张。'
        dependencies = InventoryDependencies(dependencies.catalog)
        separate = dependencies._check(deck, [req])
        self.assertEqual(separate['status'], 'unknown')
        self.assertIn('指定效果召唤', separate['unknown_restrictions'][0]['restriction']['context_source'])
        assets.rows[2]['desc'] = '这张卡不能通常召唤。①：自己主要阶段才能发动。抽1张。'
        dependencies = InventoryDependencies(dependencies.catalog)
        self.assertEqual(dependencies.summon_trigger_check(2, {'trigger':{'event':'normal_or_special_summon'}})['status'], 'inventory_present')

    def test_material_prohibition_preserves_summon_kind_zone_and_uncertain_alternatives(self):
        value, original, _ = fixture()
        assets, deck = value[1], value[4][1]
        req = dict(query=selector('「绯色素材」'), minimum=1, source='printed named material',
            origin='material', category='material')
        def check(text, *, origin='material', target=101, specs=None):
            assets.rows[2]['desc'] = text + '。①：自己主要阶段才能发动。抽1张。'
            dependencies = InventoryDependencies(original.catalog)
            return dependencies._check(deck, specs or [dict(req, origin=origin)], joint=True, target=target)
        self.assertEqual(check('这张卡不能作为融合素材')['status'], 'missing')
        assets.rows[101]['type'] = 0x2001
        self.assertEqual(check('这张卡不能作为融合素材')['status'], 'inventory_present')
        assets.rows[101]['type'] = 0x41
        self.assertEqual(check('这张卡不能作为融合素材', target=None)['status'], 'unknown')
        text = '这张卡在墓地存在，不能作为融合素材'
        for origin, status in (('material', 'unknown'), ('grave', 'missing'), ('hand', 'inventory_present'),
                               ('field', 'inventory_present')):
            with self.subTest(origin=origin):
                result = check(text, origin=origin)
                self.assertEqual(result['status'], status)
                rule, = result['requirements'][0]['restriction_checks']
                self.assertEqual(rule['restriction']['source'], text)
                self.assertEqual(bool(result['unknown_restrictions']), status == 'unknown')
        self.assertEqual(check('这张卡在怪兽区域存在，不能作为融合素材', origin='field')['status'], 'unknown')
        unresolved = '这张卡有指示物的场合，不能作为融合素材'
        self.assertEqual(check(unresolved)['status'], 'unknown')
        self.assertEqual(check(unresolved, specs=[req, req])['shortfall'], 1)
        # A complete known alternative closes inventory without assuming the
        # uncertain candidate is legal; integer slots still cannot reuse it.
        assets.rows[3].update(name='绯色素材', desc='①：自己主要阶段才能发动。抽1张。')
        resolved = check(unresolved)
        self.assertEqual((resolved['status'], resolved['requirements'][0]['confirmed_available']), ('inventory_present', 3))
        self.assertFalse(resolved['unknown_restrictions'])
        cost = dict(req, origin='hand', category='costs')
        dependencies = InventoryDependencies(original.catalog)
        self.assertEqual(dependencies._check(deck, [cost], distinct=True, target=101)['status'], 'inventory_present')

    def test_selector_preserves_level_name_and_type_and_unknown_qualifiers(self):
        self.assertEqual(selector('7星「绯色」怪兽')['level'],7)
        self.assertEqual(selector('7星以上的「绯色」怪兽')['level_between'],[7,13])
        self.assertIsNone(selector('7星以上且满足未知标志的「绯色」怪兽'))
        self.assertIsNone(selector('「绯色」怪兽以外的怪兽'))

    def test_level_exclusion_keeps_the_other_selector_conditions(self):
        query = selector('8星以外的「绯色」怪兽')
        self.assertTrue(query_supported(query))
        monster = dict(name='绯色素材', type=0x21, level=3)
        for changes, expected in (
            ({}, True),
            ({'level': (7 << 24) | (2 << 16) | 8}, False),
            ({'level': 8, 'type': 0x2021}, False),
            ({'level': 8, 'type': 0x800021}, True),
            ({'level': 8, 'type': 0x4000021}, True),
            ({'name': '另一主题的怪兽'}, False),
            ({'type': 2}, False),
        ):
            with self.subTest(changes=changes):
                self.assertEqual(matches(dict(monster, **changes), query), expected)
        self.assertFalse(matches(dict(monster, level=0), selector('1星以外的怪兽')))
        self.assertTrue(matches(dict(monster, level=None), selector('「绯色」怪兽')))
        req = requirement('从自己的卡组选2只5星以外的龙族·暗属性怪兽加入手卡', 'operations')
        self.assertEqual((req['minimum'], req['owner'], req['origins'], req['action']),
                         (2, 'self', ['deck'], '加入手卡'))
        dragon = dict(type=0x21, level=4, race=0x2000, attribute=0x20)
        self.assertTrue(matches(dragon, req['query']))
        for changes in ({'level': 5}, {'attribute': 0x10}, {'race': 1}):
            self.assertFalse(matches(dict(dragon, **changes), req['query']))
        for qualifier in ('0星以外', '256星以外', '8星以外且满足未知标志', '8星以外的4星'):
            self.assertIsNone(selector(qualifier + '的怪兽'))
        for malformed in (0, -1, 256, True, '8'):
            self.assertFalse(query_supported({'exclude_level': malformed}))

    def test_named_cost_is_missing_despite_other_unknown_effect_fields_and_side(self):
        value, catalog, _ = fixture();deck,supported=value[4]
        before=catalog.evaluate(deck,value[2]);after=catalog.evaluate(supported,value[2])
        self.assertTrue(before['known_deficits'])
        self.assertFalse(after['known_deficits'])
        req=before['cards']['1']['effects'][0]['requirements'][0]
        self.assertEqual((req['available'],req['shortfall']),(0,1))
        self.assertEqual(after['cards']['1']['effects'][0]['execution_status'],'unknown')

    def test_actual_layer_selection_and_effective_investment_use_dependency(self):
        value, _, _ = fixture()
        from unittest.mock import patch
        from ygo_kito.construction_fill import fill_with_existing
        from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
        from ygo_kito.construction_layers import LayerContext
        from ygo_kito.construction_progress import host_construction_quality
        from ygo_kito.construction_relations import RelationContext, RelationFact, Resource, ResourcePool
        from tests.test_construction_layer_flow import rows_for, session_for
        task,assets,graph,binder,decks,_=value
        assets.rows[1]['desc']=('这个卡名的①效果1回合只能使用1次。①：自己主要阶段，'
            '从手卡把1只7星「绯色」怪兽送去墓地才能发动。从自己卡组上面把3张卡送去墓地。')
        assets.rows[101]['desc']='「绯色素材」＋水族怪兽'
        payment=binder.semantic_catalog.effect_records(1)[0]['costs'][0]['source']
        relations=RelationContext((),(
            RelationFact('phase','phase',Resource('activation',event='own_main_phase',reason='not_applicable',
                attributes=('card:1',)),'host own Main Phase'),
            RelationFact('pay','pay',Resource('payment',reason='cost',attributes=(payment,)),
                'host complete hand payment',output_pool='hand-material')),
            (ResourcePool('hand-material','actual resident hand stock',inventory=(('main',2),)),))
        adapter=ConstructionLayerAdapter(binder,context_provider=lambda t,g:LayerContext(t,g,(),relations=relations))
        policy=host_construction_quality(task,catalog=binder.semantic_catalog)[0]
        # This comparison tests resident payment, before considering a side exchange.
        policy['quality']['required_scope'].remove('side')
        with patch('ygo_kito.build_pipeline.edit_candidates',return_value=rows_for(task,decks)):
            result=fill_with_existing(session_for(task,graph),assets,role='build_optimizer',base=decks[0],
                binding_provider=binder,text_reviewer=binder.reviewer,layer_adapter=adapter,
                quality_policy=policy,defer_engine=True)
        self.assertEqual(result['best_deck'],value[4][1].to_dict())
        rows=result['candidate_trace']['candidates']
        self.assertEqual(rows[0]['quality_summary']['value'],0)
        self.assertEqual(rows[1]['quality_summary']['value'],1)
        self.assertTrue(result['layer_selection']['preferred_pairs'])

    def test_targeted_deck_recipient_without_cost_is_a_known_gap(self):
        value,catalog,_=fixture()
        value[1].rows[1]['desc']='①：自己主要阶段才能发动。从卡组把1张「熔岩」卡送去墓地。'
        evaluation=catalog.evaluate(value[4][0],value[2])
        self.assertTrue(evaluation['known_deficits'])
        self.assertEqual(evaluation['cards']['1']['effects'][0]['requirements'][0]['category'],'operations')

    def test_all_selected_extra_materials_checked_without_fixed_task_card(self):
        value,catalog,_=fixture();assets=value[1]
        assets.rows[101]['desc']='「绯色素材」＋水族怪兽×2\n①：自己主要阶段才能发动。从自己卡组上面把3张卡送去墓地。'
        assets.rows[3]['race']=64
        absent=catalog.evaluate(value[4][0]);present=catalog.evaluate(value[4][1])
        self.assertEqual(absent['cards']['101']['materials']['shortfall'],1)
        self.assertEqual(present['cards']['101']['materials']['shortfall'],0)

    def test_overlapping_material_slots_cannot_reuse_one_physical_copy(self):
        value,catalog,_=fixture();assets=value[1]
        assets.rows[101]['desc']='「绯色素材」＋水族怪兽×2\n①：自己主要阶段才能发动。抽1张。'
        for code in value[0].pool:assets.rows[code]['race']=1
        assets.rows[2]['race']=64
        deck=value[4][1]
        result=catalog.evaluate(deck)['cards']['101']['materials']
        self.assertEqual(result['shortfall'],2)

    def test_unrelated_optional_operation_does_not_block_a_draw_function(self):
        value,catalog,_=fixture()
        value[1].rows[1]['desc']='①：自己主要阶段才能发动。抽1张。那之后，可以从卡组把1张「熔岩」卡送去墓地。'
        graph=one_node(LogicTag('effect_type','draw'))
        scoped=catalog.evaluate(value[4][0],graph)
        self.assertTrue(scoped['known_deficits'])
        self.assertFalse(scoped['scoped_deficits'])
        self.assertFalse(catalog.function_missing(scoped,1,'goal'))
        self.assertTrue(catalog.evaluate(value[4][0],value[2])['known_deficits'])

    def test_generated_repairs_use_original_pool_and_atomic_side_exchange(self):
        value,catalog,_=fixture()
        value[1].limits[2]=1
        task, assets, base = value[0], value[1], value[4][0]
        edits = DeckEdits(task, assets, base)
        with patch.object(DeckParts, '__init__', side_effect=AssertionError('generated a complete deck')):
            repairs = list(repair_ideas(task, assets, base, limit=2, edits=edits))
        self.assertTrue(repairs)
        self.assertEqual(repairs[0]['changes']['side']['removed'], [2])
        decks = [edits.materialize(row['changes']) for row in repairs]
        self.assertIn(2, decks[0].main)
        self.assertNotIn(2, decks[0].side)
        self.assertFalse(catalog.evaluate(decks[0])['known_deficits'])
        for deck in decks:
            assets.validate(task, deck)
            self.assertTrue(set(deck.main + deck.extra + deck.side) <= set(task.pool))

    def test_repair_is_bounded_and_never_uses_an_unavailable_external_card(self):
        value,_,_=fixture()
        value[1].rows[2]['level']=6
        self.assertEqual(list(repair_ideas(value[0],value[1],value[4][0],checks=0)),[])

    def test_extra_only_gap_does_not_spend_its_budget_on_unrelated_main_edits(self):
        value,_,_=fixture();task,assets=value[:2]
        assets.rows[1]['desc']='A source without a specified card dependency.'
        assets.rows[101]['desc']='「不存在的素材」＋植物族怪兽\n①：自己主要阶段才能发动。抽1张。'
        assets.rows[3]['name']='已有素材'
        assets.rows[4]['race']=1024
        assets.rows[102]=dict(assets.rows[101],id=102,name='替代目标',
            desc='「已有素材」＋植物族怪兽\n①：自己主要阶段才能发动。抽1张。')
        raw=task.to_dict();raw['pool'].append(102);task=BuildTask.from_dict(raw)
        rows=list(repair_ideas(task,assets,value[4][0],checks=2))
        self.assertTrue(rows)
        self.assertEqual(rows[0]['changes']['extra'], dict(added=[102], removed=[101]))

    def test_generator_uses_the_same_function_scope_as_the_evaluator(self):
        value,_,_=fixture();task,assets=value[:2]
        assets.rows[1]['desc']='①：自己主要阶段才能发动。抽1张。那之后，可以从卡组把1张「熔岩」卡送去墓地。'
        draw=one_node(LogicTag('effect_type','draw'))
        # The draw stays usable, while the separate printed recipient remains
        # visible to whole-inventory repair instead of disappearing from it.
        original = InventoryDependencies(MechanismCatalog(assets)).evaluate(value[4][0], draw)
        self.assertTrue(original['known_deficits'])
        with patch.object(InventoryDependencies, 'evaluate_counts',
                          autospec=True, side_effect=InventoryDependencies.evaluate_counts) as evaluate:
            list(repair_ideas(task, assets, value[4][0], graph=draw))
        self.assertTrue(evaluate.called)
        self.assertTrue(all(call.args[3] is draw for call in evaluate.call_args_list))

    def test_small_portfolio_keeps_chain_endpoint_not_only_first_copy_edit(self):
        value,catalog,_=fixture();task,assets=value[:2]
        raw=task.to_dict();raw['candidate_budget']=2;task=BuildTask.from_dict(raw)
        assets.rows[3]['desc']='①：自己主要阶段才能发动。从卡组把1张「不存在」卡送去墓地。'
        # The original mandatory consumer has its support. Only the three
        # anonymous copies of 3 need repair, without any external card.
        base=value[4][1]
        rows=portfolio(task,assets,base=base,graph=value[2])
        self.assertEqual(len(rows),2)
        repaired=next(r for r in rows if r['strategy']=='dependency:inventory')
        self.assertFalse(catalog.evaluate(repaired['deck'],value[2])['known_deficits'])
        self.assertGreaterEqual(repaired['dependency_repair']['step'],3)


if __name__=='__main__':unittest.main()
