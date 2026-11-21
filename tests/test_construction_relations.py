"""Anonymous static relation behavior; no rules engine, training or card recipes."""

from dataclasses import replace
import json
import time
import unittest
from unittest.mock import Mock, patch

from ygo_kito.construction_relations import (
    Claim, InputGroup, JointConstraint, Need, PoolRecovery, ProbabilityRequest, RelationBudget,
    RelationContext, RelationFact, Resource, ResourcePool, ResourceTransfer, UseRequirement,
    compare_configurations, evaluate_relations, relation_index,
    single_event_probabilities, update_relations,
)
from ygo_kito.validation import ContractError
from tests.test_construction_layers import context as axis_context, skeleton, AxisModule, refs


def all_of(*items):
    return InputGroup("all", tuple(items))


def any_of(*items):
    return InputGroup("any", tuple(items))


def need(key, quantity=1, **kwargs):
    return Need(key, Resource(key), quantity, **kwargs)


def fact(key, card=1, *, output=None, **kwargs):
    return RelationFact(key, "effect:" + key, output or Resource(key), "anonymous reviewed fact", card, **kwargs)


def use(key, *items, **kwargs):
    return UseRequirement(key, all_of(*(items or (need(key),))), "explicit original task", **kwargs)


def evaluate(ctx, main=(1,), extra=(), **kwargs):
    index = relation_index(None, ctx)
    return evaluate_relations(skeleton(main, extra), ctx, index, **kwargs)


def semantic(result):
    value = result.to_dict()
    value.pop("work")
    return value


class SupportAssessmentTests(unittest.TestCase):
    def test_effect_counter_scales_with_copies_without_spending_physical_stock(self):
        ctx=RelationContext((use('both',need('left'),need('right')),),
            (fact('left',None,claims=(Claim('per-copy'),)),fact('right',None,claims=(Claim('per-copy'),))),
            (ResourcePool('per-copy','one activation for each copy',capacity=1,count_inventory=(('main',1),)),))
        index=relation_index(None,ctx)
        single=evaluate_relations(skeleton((1,)),ctx,index)
        self.assertEqual(single.data['uses']['both']['status'],'missing')
        doubled=evaluate_relations(skeleton((1,1)),ctx,index,previous=single)
        self.assertEqual(doubled.data['uses']['both']['status'],'supported')
        self.assertTrue(doubled.data['work']['incremental'])
        self.assertEqual(doubled.data['resource_pools']['per-copy']['inventory'],())

    def test_normal_summon_capacity_only_combines_explicit_joint_uses(self):
        normal = lambda c: Resource('activation',event='normal_summon',attributes=('card:'+str(c),))
        facts = (fact('a',1,output=normal(1)),fact('b',2,output=normal(2)))
        alternatives = RelationContext((use('one',Need('one',normal(1)),required=False),
            use('two',Need('two',normal(2)),required=False)),facts)
        result = evaluate(alternatives,(1,2)).data
        self.assertEqual([r['status'] for r in result['uses'].values()],['supported','supported'])
        together = replace(alternatives,uses=tuple(replace(u,required=True) for u in alternatives.uses))
        self.assertEqual(evaluate(together,(1,2)).data['joint_required']['status'],'missing')
        allowance = Resource('normal_summon_allowance',attributes=('controller:self',))
        bonus = fact('bonus',3,output=allowance,inputs=all_of(need('permission')))
        for state,expected in (('present','supported'),('unknown','unknown'),('absent','missing')):
            evidence = (fact('permission',None,unknown=('permission_state',) if state=='unknown' else ()),) if state!='absent' else ()
            ctx = replace(together,facts=(*facts,bonus,*evidence))
            self.assertEqual(evaluate(ctx,(1,2,3)).data['joint_required']['status'],expected)
        special = replace(facts[1],output=replace(normal(2),event='special_summon'))
        ctx = replace(together,facts=(facts[0],special),uses=(together.uses[0],use('two',Need('two',special.output))))
        self.assertEqual(evaluate(ctx,(1,2)).data['joint_required']['status'],'supported')
        effect_summon = fact('effect-summon',3,output=Resource('normal_summon',reason='effect'))
        ctx = replace(together,facts=(facts[0],effect_summon),uses=(together.uses[0],use('two',Need('two',effect_summon.output))))
        self.assertEqual(evaluate(ctx,(1,2,3)).data['joint_required']['status'],'supported')

    def test_complete_legacy_and_entity_returns_share_one_physical_schedule(self):
        deck,hand,field = (Resource('x',zone=z) for z in ('deck','hand','field'))
        moves = (ResourceTransfer('first return','grave','hand','self','self','targeted',(('main',1),),'effect'),
                 ResourceTransfer('second return','grave','field','self','self','targeted',(('main',1),),'effect'))
        ctx = RelationContext((use('all',Need('first',deck,destination='grave'),
            Need('second',hand,destination='grave'),Need('third',field)),),(
            fact('deck',None,output=deck,output_pool='stock'),fact('hand',None,output=hand,output_pool='stock'),
            fact('field',None,output=field,output_pool='stock'),fact('r1',3,transfer=moves[0]),fact('r2',4,transfer=moves[1])),(
            ResourcePool('stock','one actual card',inventory=(('main',1),),recoveries=(
                PoolRecovery('r1','first','second'),PoolRecovery('r2','second','third'))),))
        explicit = evaluate(ctx,(1,3,4)).data['joint_required']
        self.assertEqual(explicit['status'],'supported')
        mixed = replace(ctx,facts=tuple(replace(f,transfer=None) if f.fact_id=='r1' else f for f in ctx.facts))
        self.assertEqual(evaluate(mixed,(1,3,4)).data['joint_required']['status'],explicit['status'])
        for party in ('owner','controller'):
            wrong = replace(mixed,facts=tuple(replace(f,transfer=replace(f.transfer,**{party:'opponent'}))
                if f.fact_id=='r2' else f for f in mixed.facts))
            self.assertEqual(evaluate(wrong,(1,3,4)).data['joint_required']['status'],'missing')
        wrong_zone = replace(mixed,facts=tuple(replace(f,transfer=replace(f.transfer,origin='banished'))
            if f.fact_id=='r2' else f for f in mixed.facts))
        self.assertEqual(evaluate(wrong_zone,(1,3,4)).data['joint_required']['status'],'missing')
        fee = replace(mixed,facts=tuple(replace(f,claims=(Claim('fee',2),)) if f.fact_id=='r2' else f for f in mixed.facts),
            pools=(*mixed.pools,ResourcePool('fee','whole fee',capacity=1)))
        self.assertEqual(evaluate(fee,(1,3,4)).data['joint_required']['status'],'missing')

    def test_complete_processing_locks_keep_player_cost_origin_and_destination(self):
        from ygo_kito.construction_relations import _record_applicability, _restriction_contract
        from ygo_kito.construction_binding import CatalogBindingAdapter
        from tests.test_construction_binding import catalog
        _, assets = catalog()
        cases = (
            ('自己不能作为代价从手卡把卡送去墓地', 'cannot_send_grave', 'self', ['hand'], None, 'cost'),
            ('对方不能从墓地把卡除外', 'cannot_banish', 'opponent', ['grave'], None, None),
            ('双方不能把卡返回卡组', 'cannot_return', 'both', None, 'deck', None),
            ('自己不能把怪兽解放', 'cannot_release', 'self', None, None, None),
            ('双方不能发动效果', 'cannot_activate', 'both', None, None, None),
            ('自己不能从墓地把怪兽特殊召唤', 'cannot_special_summon', 'self', ['grave'], None, None),
            ('对方不能盖放卡', 'cannot_set', 'opponent', None, None, None))
        for body, kind, player, origins, destination, reason in cases:
            for prefix, whole in (('这张卡在怪兽区域存在', None), ('这个效果发动后', False), ('发动这个效果的回合', True)):
                with self.subTest(body=body, prefix=prefix):
                    assets.rows[2].update(type=33, desc='①：' + prefix + '，' + body + '。')
                    record, = CatalogBindingAdapter(assets).semantic_catalog.effect_records(2)
                    self.assertTrue(record['restrictions'])
                    for observed in record['restrictions']:
                        rule = _restriction_contract(observed)
                        self.assertIsNotNone(rule, observed)
                        self.assertEqual((rule['kind'], rule['controller'], rule.get('from_zones'), rule.get('to_zone'), rule.get('reason')),
                            (kind, player, origins, destination, reason))
                        self.assertIs(rule.get('whole_turn'), whole)
                    self.assertEqual(bool(_record_applicability(record)), whole is None)
        complete = dict(kind='cannot_send_grave', source='reviewed complete structured lock', scope='player',
            controller='self', condition='effect_activation', duration='turn', whole_turn=True,
            from_zones=['hand'], to_zone='grave', reason='cost')
        self.assertIsNotNone(_restriction_contract(complete))
        self.assertIsNotNone(_restriction_contract(dict(complete, kind='cannot_release', from_zones=['field'], reason='effect')))
        self.assertIsNone(_restriction_contract(dict(complete, only_if='unhandled extra condition')))
        self.assertIsNone(_restriction_contract(dict(complete, reason='unknown')))
        intrinsic = dict(kind='cannot_be_fusion_material', scope='this_card', condition='this_card',
            duration='while_applicable', source='这张卡不能作为融合素材')
        self.assertIsNotNone(_restriction_contract(intrinsic))
        self.assertIsNone(_restriction_contract(dict(intrinsic, only_if='unhandled state')))
        self.assertIsNone(_restriction_contract(dict(intrinsic, reason='effect')))

    def test_raw_summon_and_attack_locks_require_complete_player_and_timing(self):
        from ygo_kito.construction_relations import _record_applicability, _restriction_contract
        from ygo_kito.construction_layer_flow import _mapped_restriction
        from ygo_kito.construction_binding import CatalogBindingAdapter
        from tests.test_construction_binding import catalog
        _, assets = catalog()
        for body, kind, actor in (('自己不能通常召唤', 'cannot_normal_summon', 'self'),
                ('双方不能通常召唤（盖放）', 'cannot_normal_summon', 'both'),
                ('对方不能攻击宣言', 'cannot_declare_attack', 'opponent')):
            for prefix, duration, whole in (('这张卡在怪兽区域存在', 'while_applicable', None),
                    ('这个效果发动后', 'turn', False), ('发动这个效果的回合', 'turn', True)):
                with self.subTest(body=body, prefix=prefix):
                    assets.rows[2].update(type=33, desc='①：' + prefix + '，' + body + '。')
                    record, = CatalogBindingAdapter(assets).semantic_catalog.effect_records(2)
                    self.assertTrue(record['restrictions'])
                    for observed in record['restrictions']:
                        rule = _restriction_contract(observed)
                        self.assertIsNotNone(rule)
                        self.assertEqual((rule['kind'], rule['controller'], rule['duration'], rule.get('whole_turn')),
                            (kind, actor, duration, whole))
                        self.assertTrue(_mapped_restriction(record, observed))
                    self.assertEqual(bool(_record_applicability(record)), prefix == '这张卡在怪兽区域存在')
        for body in ('这张卡在怪兽区域存在，自己不能通常召唤，但指定怪兽除外',
                     '这张卡有指示物且在怪兽区域存在，对方不能攻击宣言'):
            assets.rows[2]['desc'] = '①：' + body + '。'
            record, = CatalogBindingAdapter(assets).semantic_catalog.effect_records(2)
            self.assertTrue(record['restrictions'])
            self.assertFalse(_record_applicability(record))
            self.assertTrue(all(not _mapped_restriction(record, r) for r in record['restrictions']))
        from ygo_kito.construction_inventory import InventoryDependencies
        assets.rows[2]['desc'] = '这个卡名的①效果发动的回合，自己不能攻击宣言。①：自己主要阶段才能发动。抽1张。'
        specs, _ = InventoryDependencies(CatalogBindingAdapter(assets).semantic_catalog).specs(2)
        record = specs[0]['record']
        self.assertTrue(record['card_restrictions'])
        self.assertTrue(all(not _mapped_restriction(record, r) for r in record['card_restrictions']))

    def test_raw_hand_locks_require_complete_sourced_applicability(self):
        from ygo_kito.construction_relations import _record_facts, _needs, _restriction_contract
        from ygo_kito.construction_layer_flow import _mapped_restriction
        from ygo_kito.construction_binding import CatalogBindingAdapter
        from tests.test_construction_binding import catalog
        _, assets = catalog()
        for body, kind, controller, origins in (
                ('自己不能抽卡', 'cannot_draw', 'self', None),
                ('双方不能抽卡', 'cannot_draw', 'both', None),
                ('对方不能从卡组把卡加入手卡', 'cannot_add_hand', 'opponent', ['deck']),
                ('自己不能把卡加入手卡', 'cannot_add_hand', 'self', None)):
            with self.subTest(body=body):
                assets.rows[2].update(type=33, desc='①：这张卡在怪兽区域存在，' + body + '。')
                record, = CatalogBindingAdapter(assets).semantic_catalog.effect_records(2)
                rule, = record['restrictions']
                contract = _restriction_contract(rule)
                self.assertEqual((contract['kind'], contract['controller'], contract.get('from_zones')),
                                 (kind, controller, origins))
                self.assertEqual(contract['source'], rule['source'])
                self.assertTrue(_mapped_restriction(record, rule))
                observed, _ = next(_record_facts(2, (record,)))
                state, = _needs(observed.inputs)
                self.assertEqual((state.mode, state.resource.kind), ('presence', 'effect_applicability'))
                self.assertIn('controller:self', state.resource.attributes)
                self.assertNotIn('activation_condition_unknown', observed.unknown)
        for prefix, whole in (('这个效果发动后', False), ('发动这个效果的回合', True)):
            assets.rows[2]['desc'] = '①：' + prefix + '，自己不能抽卡。'
            record, = CatalogBindingAdapter(assets).semantic_catalog.effect_records(2)
            rule, = record['restrictions']
            self.assertIs(_restriction_contract(rule)['whole_turn'], whole)
            self.assertTrue(_mapped_restriction(record, rule))
        for body in ('这张卡在怪兽区域存在，自己不能在抽卡阶段以外抽卡',
                     '这张卡有指示物且在怪兽区域存在，自己不能从额外卡组特殊召唤',
                     '这张卡在怪兽区域存在，自己不能从卡组把怪兽卡加入手卡'):
            with self.subTest(unresolved=body):
                assets.rows[2]['desc'] = '①：' + body + '。'
                record, = CatalogBindingAdapter(assets).semantic_catalog.effect_records(2)
                self.assertTrue(record['restrictions'])
                self.assertTrue(all(not _mapped_restriction(record, r) for r in record['restrictions']))
                observed, _ = next(_record_facts(2, (record,)))
                self.assertIn('activation_condition_unknown', observed.unknown)
                self.assertFalse(any(n.resource.kind == 'effect_applicability' for n in _needs(observed.inputs)))
        assets.rows[2]['desc'] = '这张卡不能通常召唤。①：自己主要阶段才能发动。抽1张。'
        record, = CatalogBindingAdapter(assets).semantic_catalog.effect_records(2)
        self.assertTrue(record['card_restrictions'])
        self.assertTrue(all(_mapped_restriction(record, r) for r in record['card_restrictions']))
        observed, _ = next(_record_facts(2, (record,)))
        self.assertIn('restriction_joint_scope_unresolved', observed.unknown)

    def test_cross_zone_transfer_tracks_same_slots_and_final_state(self):
        deck, hand = Resource("x", zone="deck"), Resource("x", zone="hand")
        transfer = ResourceTransfer("return the consumed A to hand", "grave", "hand", "self", "self",
            "targeted", (("main", 1),), "effect")
        ctx = RelationContext((use("both", Need("first", deck, destination="grave"), Need("last", hand)),), (
            fact("deck", None, output=deck, output_pool="stock"),
            fact("hand", None, output=hand, output_pool="stock"), fact("return", 3, transfer=transfer)), (
            ResourcePool("stock", "one actual A", inventory=(("main", 1),), recoveries=(
                PoolRecovery("return", "first", "last"),)),))
        result = evaluate(ctx, (1, 3)).data["joint_required"]
        self.assertEqual(result["status"], "supported")
        witness = next(b for b in result["branches"] if b["status"] == "supported")
        self.assertEqual({tuple(r["slot"]) for r in witness["recovery_allocation"]}, {("physical:main:1", 0)})
        self.assertEqual([(r["consumed_zone"], r["consumed_destination"], r["destination"])
                          for r in witness["transfer_states"]], [("deck", "grave", "hand")])
        stale = replace(ctx, uses=(use("both", Need("first", deck, destination="grave"), Need("last", hand),
            Need("old-zone", deck)),))
        self.assertEqual(evaluate(stale, (1, 3)).data["joint_required"]["status"], "missing")
        wrong = replace(ctx, facts=ctx.facts[:-1] + (replace(ctx.facts[-1],
            transfer=replace(transfer, inventory=(("main", 2),))),))
        self.assertEqual(evaluate(wrong, (1, 2, 3)).data["joint_required"]["status"], "missing")
        reversed_inputs = replace(ctx, uses=(replace(ctx.uses[0], inputs=all_of(*reversed(ctx.uses[0].inputs.items))),))
        self.assertEqual(evaluate(reversed_inputs, (1, 3)).data["joint_required"]["status"], "supported")

    def test_cross_zone_transfer_preserves_quantity_fee_and_incremental_updates(self):
        deck, hand = Resource("x", zone="deck"), Resource("x", zone="hand")
        transfer = ResourceTransfer("return two consumed copies", "grave", "hand", "self", "self",
            "targeted", (("main", 1),), "effect")
        ctx = RelationContext((use("both", Need("first", deck, 2, destination="grave"), Need("last", hand, 2)),), (
            fact("deck", None, output=deck, quantity=2, output_pool="stock"),
            fact("hand", None, output=hand, quantity=2, output_pool="stock"),
            fact("return", 3, quantity=2, transfer=transfer, claims=(Claim("fee", 2),))), (
            ResourcePool("stock", "two physical copies", inventory=(("main", 1),), recoveries=(
                PoolRecovery("return", "first", "last"),)), ResourcePool("fee", "whole fee", capacity=2)))
        index = relation_index(None, ctx)
        previous = evaluate_relations(skeleton((1, 1, 3)), ctx, index)
        self.assertEqual(previous.data["joint_required"]["status"], "supported")
        witness = next(b for b in previous.data["joint_required"]["branches"] if b["status"] == "supported")
        self.assertEqual(sum(witness["usage"]["fee"].values()), 2)
        self.assertEqual({tuple(r["slot"]) for r in witness["transfer_states"]},
                         {("physical:main:1", 0), ("physical:main:1", 1)})
        for main, expected in (((1, 3), "missing"), ((1, 1), "missing"), ((1, 1, 3), "supported")):
            current = update_relations(previous, skeleton(main), ctx)
            self.assertEqual(current.data["joint_required"]["status"], expected)
            self.assertEqual(semantic(current), semantic(evaluate_relations(skeleton(main), ctx, index)))
            previous = current
        scarce = replace(ctx, facts=ctx.facts[:-1] + (replace(ctx.facts[-1], quantity=1),))
        self.assertEqual(evaluate(scarce, (1, 1, 3)).data["joint_required"]["status"], "missing")
        fee = replace(ctx, pools=(ctx.pools[0], replace(ctx.pools[1], capacity=1)))
        self.assertEqual(evaluate(fee, (1, 1, 3)).data["joint_required"]["status"], "missing")

    def test_deck_position_transfer_keeps_membership_and_unknown_order(self):
        deck, top, bottom = (Resource("x", zone=z) for z in ("deck", "deck_top", "deck_bottom"))
        transfer = ResourceTransfer("known bottom return", "grave", "deck_bottom", "self", "self",
            "targeted", (("main", 1),), "effect")
        ctx = RelationContext((use("both", Need("first", deck, destination="grave"), Need("last", deck)),), (
            fact("deck", None, output=deck, output_pool="stock"), fact("top", None, output=top, output_pool="stock"),
            fact("bottom", None, output=bottom, output_pool="stock"), fact("return", 3, transfer=transfer)), (
            ResourcePool("stock", "A in the deck", inventory=(("main", 1),), recoveries=(
                PoolRecovery("return", "first", "last"),)),))
        self.assertEqual(evaluate(ctx, (1, 3)).data["joint_required"]["status"], "supported")
        for zone, expected in ((bottom, "supported"), (top, "missing")):
            current = replace(ctx, uses=(use("both", Need("first", deck, destination="grave"), Need("last", zone)),))
            self.assertEqual(evaluate(current, (1, 3)).data["joint_required"]["status"], expected)
        unknown = replace(ctx, uses=(use("both", Need("first", deck, destination="grave"), Need("last", top)),),
            facts=ctx.facts[:-1] + (replace(ctx.facts[-1], transfer=replace(transfer, destination="deck")),))
        self.assertEqual(evaluate(unknown, (1, 3)).data["joint_required"]["status"], "unknown")
        grouped = replace(ctx, uses=(use("both", Need("first", deck, 2, destination="grave"), Need("last", bottom, 2)),),
            facts=tuple(replace(f, quantity=2) for f in ctx.facts))
        self.assertEqual(evaluate(grouped, (1, 1, 3)).data["joint_required"]["status"], "unknown")
        membership = replace(grouped, uses=(use("both", Need("first", deck, 2, destination="grave"), Need("last", deck, 2)),))
        self.assertEqual(evaluate(membership, (1, 1, 3)).data["joint_required"]["status"], "supported")
        multiple = replace(ctx, uses=(use("both", Need("first", deck, destination="grave"),
            Need("middle", bottom, destination="grave"), Need("last", top)),),
            facts=ctx.facts + (fact("return-top", 4, transfer=replace(transfer, destination="deck_top")),),
            pools=(replace(ctx.pools[0], recoveries=(PoolRecovery("return", "first", "middle"),
                PoolRecovery("return-top", "middle", "last"))),))
        self.assertEqual(evaluate(multiple, (1, 3, 4)).data["joint_required"]["status"], "unknown")
        ordinary = replace(multiple, uses=(use("both", Need("first", deck, destination="grave"),
            Need("middle", deck, destination="grave"), Need("last", deck)),))
        self.assertEqual(evaluate(ordinary, (1, 3, 4)).data["joint_required"]["status"], "supported")

    def test_summoned_leave_rule_changes_only_selected_entity(self):
        deck, field = Resource("x", zone="deck"), Resource("x", zone="field")
        summon = ResourceTransfer("summon A with a leave rule", "grave", "field", "self", "self",
            "targeted", (("main", 1),), "effect", "banished", "this summoned card is banished when leaving")
        recover = ResourceTransfer("return the actual banished A", "banished", "deck", "self", "self",
            "targeted", (("main", 1),), "effect")
        ctx = RelationContext((use("chain", Need("first", deck, destination="grave"),
            Need("field", field, destination="grave"), Need("last", deck)),), (
            fact("deck", None, output=deck, output_pool="stock"), fact("field", None, output=field, output_pool="stock"),
            fact("summon", 3, transfer=summon), fact("recover", 4, transfer=recover)), (
            ResourcePool("stock", "one selected entity", inventory=(("main", 1),), recoveries=(
                PoolRecovery("summon", "first", "field"), PoolRecovery("recover", "field", "last"))),))
        result = evaluate(ctx, (1, 3, 4)).data["joint_required"]
        self.assertEqual(result["status"], "supported")
        witness = next(b for b in result["branches"] if b["status"] == "supported")
        departed = next(r for r in witness["transfer_states"] if r["fact_id"] == "recover")
        self.assertEqual((departed["declared_destination"], departed["consumed_destination"]), ("grave", "banished"))
        wrong = replace(ctx, facts=ctx.facts[:-1] + (replace(ctx.facts[-1], transfer=replace(recover, origin="grave")),))
        failed = evaluate(wrong, (1, 3, 4)).data["joint_required"]
        self.assertEqual(failed["status"], "missing")
        self.assertIn("leave_fact_id", repr(failed))
        self.assertIn("this summoned card is banished when leaving", repr(failed))
        ordinary = replace(wrong, facts=wrong.facts[:2] + (replace(wrong.facts[2],
            transfer=replace(summon, leave_destination=None, leave_source=None)), wrong.facts[3]))
        self.assertEqual(evaluate(ordinary, (1, 3, 4)).data["joint_required"]["status"], "supported")
        # An independently accessed B was not summoned by this event and keeps
        # its actual grave destination while A retains its own leave rule.
        own_b = Resource("B", zone="field")
        b_deck = Resource("B", zone="deck")
        separate = replace(ctx, uses=(use("all", Need("first", deck, destination="grave"), Need("field", field),
            Need("b-field", own_b, destination="grave"), Need("b-last", b_deck)),), facts=ctx.facts[:3] + (
                fact("b-field", None, output=own_b, output_pool="B"), fact("b-deck", None, output=b_deck, output_pool="B"),
                fact("recover", 4, transfer=replace(recover, origin="grave", inventory=(("main", 2),)))), pools=(
            replace(ctx.pools[0], recoveries=(PoolRecovery("summon", "first", "field"),)),
            ResourcePool("B", "independent B", inventory=(("main", 2),), recoveries=(
                PoolRecovery("recover", "b-field", "b-last"),))))
        self.assertEqual(evaluate(separate, (1, 2, 3, 4)).data["joint_required"]["status"], "supported")

    def test_raw_summon_transfer_keeps_leave_rule_scoped_to_effect(self):
        from copy import deepcopy
        from ygo_kito.construction_relations import _record_facts, _record_outputs, _operation_transfer
        from ygo_kito.construction_inventory import InventoryDependencies
        from ygo_kito.construction_binding import CatalogBindingAdapter
        from tests.test_construction_binding import catalog
        _, assets = catalog()
        assets.rows[1]['name'] = '静态对象'
        assets.rows[2]['desc'] = ('这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。'
            '从自己墓地把1只「静态对象」特殊召唤。这个效果特殊召唤的怪兽从场上离开的场合除外。'
            '②：自己主要阶段才能发动。从自己墓地把1只「静态对象」特殊召唤。')
        catalog = CatalogBindingAdapter(assets).semantic_catalog
        records = catalog.effect_records(2)
        dependencies = InventoryDependencies(catalog)
        rows = [f for f, _ in _record_facts(2, records, inventory=(("main", 1),),
            dependencies=dependencies, controller="self")]
        self.assertEqual(len(rows), 2)
        self.assertEqual([len(_record_outputs(r)) for r in records], [1, 1])
        self.assertEqual(rows[0].transfer.leave_destination, "banished")
        self.assertEqual(rows[0].transfer.inventory, (("main", 1),))
        self.assertIn("从场上离开", rows[0].transfer.leave_source)
        self.assertIsNone(rows[1].transfer.leave_destination)
        self.assertFalse(dependencies.specs(2)[0][0]['unknown'])
        self.assertEqual(dependencies.specs(2)[0][0]['requirements'][0]['query']['exact_name'], '静态对象')
        qualified = dict(records[1]['operations'][0], source='从自己墓地把1只「静态对象」以外的怪兽特殊召唤')
        unresolved = _operation_transfer(qualified, 'unparsed exclusion', (("main", 1),), dependencies, 'self')
        self.assertIsNone(unresolved.inventory)
        opaque = deepcopy(records)
        opaque[0]['restrictions'][0]['condition'] = 'unresolved_condition'
        unknown = [f for f, _ in _record_facts(2, opaque)]
        self.assertIsNone(unknown[0].transfer.leave_destination)
        self.assertIn('restriction_joint_scope_unresolved', unknown[0].unknown)
        positioned = _operation_transfer(dict(kind='return_deck', from_zones=['grave'], to_zone='deck',
            deck_position='bottom'), 'recognized bottom placement')
        self.assertEqual(positioned.destination, 'deck_bottom')
        for action in (lambda: replace(rows[0].transfer, leave_source=None),
                       lambda: replace(rows[0].transfer, destination='hand')):
            with self.assertRaises(ContractError):
                action()

    def test_raw_no_operation_source_preserves_scope_and_field_applicability(self):
        from copy import deepcopy
        from ygo_kito.construction_relations import _record_facts, _needs
        from ygo_kito.construction_binding import CatalogBindingAdapter
        from tests.test_construction_binding import catalog
        _, assets = catalog()
        assets.rows[2].update(type=33, desc='①：这张卡在怪兽区域存在，自己不能从额外卡组特殊召唤。')
        records = CatalogBindingAdapter(assets).semantic_catalog.effect_records(2)
        self.assertEqual(records[0]['operations'], [])
        observed, pools = next(_record_facts(2, records))
        self.assertEqual((observed.fact_id, observed.output.kind, observed.quantity),
                         ('catalog:2:1:adoption', 'effect_adoption', 1))
        self.assertEqual(pools, [])
        state, = _needs(observed.inputs)
        self.assertEqual((state.mode, state.resource.kind, state.resource.zone),
                         ('presence', 'effect_applicability', 'field'))
        self.assertEqual(set(state.resource.attributes), {'card:2', 'controller:self', 'state:monster_zone'})
        self.assertIn('restriction_joint_scope_unresolved', observed.unknown)
        self.assertNotIn('activation_condition_unknown', observed.unknown)
        self.assertNotIn('count_limit', observed.unknown)
        repeated = [deepcopy(records[0]), deepcopy(records[0])]
        repeated[0]['scope'] = 'pendulum'
        repeated[1]['scope'] = 'monster'
        facts = [f for f, _ in _record_facts(2, repeated)]
        self.assertEqual(len({f.fact_id for f in facts}), 2)
        self.assertEqual(len({f.effect_ref for f in facts}), 2)
        self.assertTrue(all(f.source.endswith(':record:' + str(i)) for i, f in enumerate(facts)))
        opaque = deepcopy(records)
        opaque[0]['restrictions'][0]['condition'] = 'source_clause'
        unknown, _ = next(_record_facts(2, opaque))
        self.assertIn('activation_condition_unknown', unknown.unknown)
        self.assertFalse(any(n.resource.kind == 'effect_applicability' for n in _needs(unknown.inputs)))
        flavor = deepcopy(records)
        flavor[0]['block_view']['status'] = 'flavor'
        self.assertEqual(list(_record_facts(2, flavor)), [])

    def test_raw_no_operation_source_keeps_complete_cost_and_limit_claim(self):
        from ygo_kito.construction_relations import _record_facts, _needs
        from ygo_kito.construction_binding import CatalogBindingAdapter
        from tests.test_construction_binding import catalog
        _, assets = catalog()
        assets.rows[2].update(type=33, desc='这个卡名的①效果1回合只能使用1次。①：丢弃2张手卡才能发动。')
        records = CatalogBindingAdapter(assets).semantic_catalog.effect_records(2)
        self.assertFalse(records[0]['operations'])
        observed, pools = next(_record_facts(2, records, same_name=20))
        payment, = (n for n in _needs(observed.inputs) if n.resource.kind == 'payment')
        self.assertEqual((payment.mode, payment.quantity, payment.resource.reason), ('consume', 2, 'cost'))
        self.assertEqual([c.pool_id for c in observed.claims], ['catalog-limit:20:1'])
        self.assertEqual(pools[0].capacity, 1)
        self.assertNotIn('activation_condition_unknown', observed.unknown)
        self.assertNotIn('additional_activation_conditions', observed.unknown)
        self.assertIn('resolution', observed.unknown)  # No processing instruction was printed.
        self.assertIsNone(observed.transfer)

    def test_typed_return_reuses_only_selected_physical_entities(self):
        broad, only_a, only_b = (Resource(k, zone="deck") for k in ("broad", "a", "b"))
        transfer = ResourceTransfer("return B from grave to deck", "grave", "deck", "self", "self",
            "targeted", (("main", 2),), "effect")
        ctx = RelationContext((use("reserve", Need("reserve-a", only_a, destination="grave")),
            use("first", Need("first", broad, destination="grave")), use("last", Need("last", only_b))), (
            fact("broad", None, output=broad, quantity=2, output_pool="broad"),
            fact("a", None, output=only_a, output_pool="a"), fact("b", None, output=only_b, output_pool="b"),
            fact("return", 3, transfer=transfer)), (
            ResourcePool("broad", "all physical cards", inventory=(("main", 1), ("main", 2)),
                recoveries=(PoolRecovery("return", "first", "last"),)),
            ResourcePool("a", "only A", inventory=(("main", 1),)),
            ResourcePool("b", "only B", inventory=(("main", 2),))), constraints=(
            JointConstraint("reserve-first", ("reserve", "first"), "before", "A is already consumed"),))
        result = evaluate(ctx, (1, 2, 3)).data["joint_required"]
        self.assertEqual(result["status"], "supported")
        witness = next(b for b in result["branches"] if b["status"] == "supported")
        released = [r for r in witness["recovery_allocation"] if r["selector"] in witness["return_selections"]]
        self.assertEqual([tuple(r["slot"]) for r in released], [("physical:main:2", 0)])
        self.assertEqual(witness["recovery_returns"][0]["transfer"]["source"], transfer.source)
        wrong = replace(ctx, facts=ctx.facts[:-1] + (replace(ctx.facts[-1],
            transfer=replace(transfer, inventory=(("main", 1),))),))
        self.assertEqual(evaluate(wrong, (1, 2, 3)).data["joint_required"]["status"], "missing")

    def test_typed_return_checks_zones_control_and_incomplete_evidence(self):
        resource = Resource("x", zone="hand")
        transfer = ResourceTransfer("explicit own return", "grave", "hand", "self", "self",
            "targeted", (("main", 1),), "effect")
        ctx = RelationContext((use("both", Need("first", resource, destination="grave"), Need("last", resource)),),
            (fact("x", output=resource, output_pool="stock"), fact("return", 2, transfer=transfer)),
            (ResourcePool("stock", "one physical card", inventory=(("main", 1),),
                recoveries=(PoolRecovery("return", "first", "last"),)),))
        self.assertEqual(evaluate(ctx, (1, 2)).data["joint_required"]["status"], "supported")
        for field, value in (("owner", "opponent"), ("controller", "opponent"), ("origin", "field"),
                             ("destination", "deck"), ("inventory", ())):
            with self.subTest(field=field):
                current = replace(ctx, facts=(ctx.facts[0], replace(ctx.facts[1], transfer=replace(transfer, **{field:value}))))
                self.assertEqual(evaluate(current, (1, 2)).data["joint_required"]["status"], "missing")
        for field, value in (("owner", None), ("owner", "both"), ("controller", None), ("origin", None),
                             ("destination", None), ("selection", "random"), ("inventory", None)):
            with self.subTest(field=field):
                current = replace(ctx, facts=(ctx.facts[0], replace(ctx.facts[1], transfer=replace(transfer, **{field:value}))))
                result = evaluate(current, (1, 2)).data["joint_required"]
                self.assertEqual(result["status"], "unknown")
                self.assertIn("recovery_transfer_", repr(result["support_expression"]))
        incomplete = replace(ctx, uses=(use("both", Need("first", resource), Need("last", resource)),))
        self.assertEqual(evaluate(incomplete, (1, 2)).data["joint_required"]["status"], "unknown")
        logical = replace(ctx, pools=(replace(ctx.pools[0], inventory=(), capacity=1),))
        self.assertEqual(evaluate(logical, (1, 2)).data["joint_required"]["status"], "unknown")
        cross_zone = replace(ctx, uses=(use("both", Need("first", replace(resource, zone="deck"), destination="grave"),
            Need("last", resource)),), facts=ctx.facts + (
            fact("deck", output=replace(resource, zone="deck"), output_pool="stock"),))
        self.assertEqual(evaluate(cross_zone, (1, 2)).data["joint_required"]["status"], "supported")
        deck_resource = replace(resource, zone="deck")
        deck_position = replace(ctx, uses=(use("both", Need("first", deck_resource, destination="grave"),
            Need("last", deck_resource)),), facts=(replace(ctx.facts[0], output=deck_resource),
                replace(ctx.facts[1], transfer=replace(transfer, destination="deck_bottom"))))
        self.assertEqual(evaluate(deck_position, (1, 2)).data["joint_required"]["status"], "supported")
        wrong_next_zone = replace(ctx, uses=(use("both", Need("first", resource, destination="grave"),
            Need("last", replace(resource, zone="field"))),), facts=ctx.facts + (
            fact("field", output=replace(resource, zone="field"), output_pool="stock"),))
        self.assertEqual(evaluate(wrong_next_zone, (1, 2)).data["joint_required"]["status"], "missing")
        for action in (lambda: Need("presence", resource, mode="presence", destination="grave"),
                       lambda: replace(transfer, inventory=(("side", 1),)),
                       lambda: replace(transfer, inventory=(("main", 1), ("main", 1)))):
            with self.assertRaises(ContractError):
                action()

    def test_typed_return_keeps_shared_event_quantity_and_whole_fee(self):
        resource = Resource("x", zone="deck")
        transfer = ResourceTransfer("two selected returns", "grave", "deck", "self", "self",
            "targeted", (("main", 1),), "effect")
        ctx = RelationContext((use("all", Need("first", resource, 2, destination="grave"),
            Need("second", resource), Need("third", resource)),), (
            fact("x", output=resource, quantity=2, output_pool="stock"),
            fact("return", 2, quantity=2, transfer=transfer, claims=(Claim("fee"),))), (
            ResourcePool("stock", "two actual copies", inventory=(("main", 1),), recoveries=(
                PoolRecovery("return", "first", "second"), PoolRecovery("return", "first", "third"))),
            ResourcePool("fee", "one whole activation fee", capacity=1)))
        result = evaluate(ctx, (1, 1, 2)).data["joint_required"]
        self.assertEqual(result["status"], "supported")
        witness = next(b for b in result["branches"] if b["status"] == "supported")
        self.assertEqual(sum(r["quantity"] for r in witness["recovery_returns"]), 2)
        self.assertEqual(sum(witness["usage"]["fee"].values()), 1)
        scarce = replace(ctx, facts=(ctx.facts[0], replace(ctx.facts[1], quantity=1)))
        self.assertEqual(evaluate(scarce, (1, 1, 2)).data["joint_required"]["status"], "missing")
        no_fee = replace(ctx, pools=(ctx.pools[0], replace(ctx.pools[1], capacity=0)))
        self.assertEqual(evaluate(no_fee, (1, 1, 2)).data["joint_required"]["status"], "missing")

    def test_typed_return_incremental_entity_and_source_removal_equals_full(self):
        resource = Resource("x", zone="deck")
        transfer = ResourceTransfer("return only A", "grave", "deck", "self", "self",
            "targeted", (("main", 1),), "effect")
        ctx = RelationContext((use("both", Need("first", resource, destination="grave"), Need("last", resource)),),
            (fact("x", None, output=resource, output_pool="stock"), fact("return", 3, transfer=transfer)),
            (ResourcePool("stock", "A or B", inventory=(("main", 1), ("main", 2)),
                recoveries=(PoolRecovery("return", "first", "last"),)),))
        index = relation_index(None, ctx)
        previous = evaluate_relations(skeleton((1, 3)), ctx, index)
        self.assertEqual(previous.data["joint_required"]["status"], "supported")
        for main, expected in (((2, 3), "missing"), ((1,), "missing"), ((1, 3), "supported")):
            current = update_relations(previous, skeleton(main), ctx)
            self.assertEqual(current.data["joint_required"]["status"], expected)
            self.assertEqual(semantic(current), semantic(evaluate_relations(skeleton(main), ctx, index)))
            previous = current

    def test_raw_transfer_keeps_selector_identity_and_separate_parties(self):
        from ygo_kito.construction_inventory import InventoryDependencies
        from ygo_kito.construction_relations import _record_facts
        from ygo_kito.construction_binding import CatalogBindingAdapter
        from tests.test_construction_binding import catalog
        _, assets = catalog()
        assets.rows[1]['name'] = '指定实体'
        assets.rows[2]['desc'] = '这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。从自己墓地把2张「指定实体」加入手卡。'
        catalog = CatalogBindingAdapter(assets).semantic_catalog
        records = catalog.effect_records(2)
        dependencies = InventoryDependencies(catalog)
        observed, _ = next(_record_facts(2, records, inventory=(("main", 1), ("main", 3)), dependencies=dependencies))
        self.assertEqual(observed.quantity, 2)
        self.assertEqual(observed.transfer.inventory, (("main", 1),))
        self.assertEqual((observed.transfer.origin, observed.transfer.destination, observed.transfer.owner,
            observed.transfer.controller, observed.transfer.selection), ("grave", "hand", "self", None, "targeted"))
        self.assertEqual(observed.transfer.source, observed.source)
        changed = json.loads(json.dumps(records))
        changed[0]['operations'][0].update(controller='opponent', owner='self', selector_query={'unsupported_predicate':True})
        unsupported, _ = next(_record_facts(2, changed, inventory=(("main", 1),), dependencies=dependencies, controller='self'))
        self.assertEqual(unsupported.transfer.controller, 'opponent')
        self.assertIsNone(unsupported.transfer.inventory)
        changed[0]['operations'][0].update(owner='both', selector_query={'type':'fusion'})
        shared, _ = next(_record_facts(2, changed, inventory=(("main", 1),), dependencies=dependencies))
        self.assertEqual(shared.transfer.owner, 'both')
        self.assertIsNone(shared.transfer.inventory)
        omitted, _ = next(_record_facts(2, records, inventory=(("main", 3),), dependencies=dependencies))
        self.assertEqual(omitted.transfer.inventory, ())

    def test_joint_all_rechecks_whole_alternatives_without_mixing_branches(self):
        choose = UseRequirement("choice", any_of(need("a"), need("b")), "task")
        ctx = RelationContext((choose, use("c")), (
            fact("a", claims=(Claim("once"),)), fact("b", 2), fact("c", claims=(Claim("once"),))),
            (ResourcePool("once", "shared once", capacity=1),))
        for current in (ctx, replace(ctx, uses=tuple(reversed(ctx.uses)), facts=tuple(reversed(ctx.facts)))):
            result = evaluate(current, (1, 2)).data["joint_required"]
            self.assertEqual(result["status"], "supported")
            self.assertTrue(any("b" in b["suppliers"] for b in result["branches"] if b["status"] == "supported"))
        self.assertEqual(evaluate(ctx, (1,)).data["joint_required"]["status"], "missing")

    def test_sourced_recovery_between_two_consumptions_and_explicit_order(self):
        ctx = RelationContext((use("both", Need("first", Resource("x")), Need("second", Resource("x"))),),
            (fact("x", output_pool="stock"), fact("recover", 2)),
            (ResourcePool("stock", "reviewed return between needs", capacity=1,
                          reusable_if="recover", recovery_between=("first", "second")),))
        self.assertEqual(evaluate(ctx, (1, 2)).data["joint_required"]["status"], "supported")
        self.assertEqual(evaluate(ctx, (1,)).data["joint_required"]["status"], "missing")
        uncertain = replace(ctx, facts=(ctx.facts[0], replace(ctx.facts[1], unknown=("return_access",))))
        self.assertEqual(evaluate(uncertain, (1, 2)).data["joint_required"]["status"], "unknown")
        ordered = RelationContext((use("a"), use("b")), (fact("a"), fact("b")),
            constraints=(JointConstraint("ab", ("a", "b"), "before", "reviewed order"),))
        self.assertEqual(evaluate(ordered).data["joint_required"]["status"], "supported")
        reversed_order = replace(ordered, constraints=ordered.constraints + (
            JointConstraint("ba", ("b", "a"), "before", "conflicting order"),))
        self.assertEqual(evaluate(reversed_order).data["joint_required"]["status"], "missing")
    def test_all_keeps_missing_input_and_any_keeps_alternatives(self):
        ctx = RelationContext((use("both", need("a"), need("b")),
            UseRequirement("either", any_of(need("a"), need("b")), "task")), (fact("a"),))
        result = evaluate(ctx).data
        self.assertEqual(result["uses"]["both"]["status"], "missing")
        self.assertEqual(result["uses"]["both"]["gaps"], ["b"])
        self.assertEqual(result["uses"]["either"]["status"], "supported")

    def test_zone_origin_reason_state_event_and_random_are_not_conflated(self):
        supply = Resource("move", "grave", "deck", "effect", "sent", "random")
        for field, other in (("zone", "hand"), ("origin", "hand"), ("reason", "cost"),
                             ("event", "exists"), ("selection", "targeted")):
            with self.subTest(field=field):
                ctx = RelationContext((use("x", Need("wanted", replace(supply, **{field: other}))),),
                                      (fact("move", output=supply),))
                self.assertEqual(evaluate(ctx).data["uses"]["x"]["status"], "missing")

    def test_no_source_cycle_is_a_gap_and_seed_propagates(self):
        ctx = RelationContext((use("finish", need("b")),), (
            fact("a", inputs=all_of(need("b"))), fact("b", inputs=all_of(need("a")))))
        self.assertEqual(evaluate(ctx).data["uses"]["finish"]["status"], "missing")
        ctx = replace(ctx, facts=ctx.facts + (fact("seed", output=Resource("a")),))
        self.assertEqual(evaluate(ctx).data["uses"]["finish"]["status"], "supported")
        normal=Resource('activation',event='normal_summon',attributes=('card:1',))
        seeded=replace(ctx,facts=ctx.facts[:-1]+(fact('normal',output=normal),
            fact('seed',output=Resource('a'),inputs=all_of(Need('entry',normal,mode='presence'))),
            fact('other',output=Resource('independent'))),uses=(*ctx.uses,use('other',Need('other',Resource('independent')))))
        self.assertEqual(evaluate(seeded).data['joint_required']['status'],'supported')
        without=replace(seeded,facts=tuple(f for f in seeded.facts if f.fact_id!='normal'))
        self.assertEqual(evaluate(without).data['uses']['finish']['status'],'missing')
        self.assertEqual(evaluate(without).data['uses']['other']['status'],'supported')

    def test_unknown_is_local_and_known_alternative_can_support(self):
        ctx = RelationContext((use("a"), use("b")), (fact("a", unknown=("selector",)), fact("b")))
        result = evaluate(ctx).data
        self.assertEqual(result["uses"]["a"]["status"], "unknown")
        self.assertEqual(result["uses"]["b"]["status"], "supported")
        ctx = replace(ctx, facts=ctx.facts + (fact("known", output=Resource("a")),))
        self.assertEqual(evaluate(ctx).data["uses"]["a"]["status"], "supported")

    def test_actual_inventory_quantity_not_effective_axis_count(self):
        ctx = RelationContext((use("material", need("material", 3)),),
            (fact("material", inventory_scaled=True, output_pool="physical"),),
            (ResourcePool("physical", "inventory", inventory=(("main", 1),)),))
        self.assertEqual(evaluate(ctx, (1, 1)).data["uses"]["material"]["status"], "missing")
        self.assertEqual(evaluate(ctx, (1, 1, 1)).data["uses"]["material"]["status"], "supported")

    def test_disjoint_suppliers_can_meet_one_integer_quantity(self):
        ctx = RelationContext((use("material", need("material", 2)),), (
            fact("a", output=Resource("material")), fact("b", 2, output=Resource("material"))))
        self.assertEqual(evaluate(ctx, (1, 2)).data["uses"]["material"]["status"], "supported")

    def test_surplus_supplier_conflict_cannot_disprove_feasible_subsets(self):
        ctx = RelationContext((use("material", need("material", 2)),), (
            fact("a", output=Resource("material"), claims=(Claim("once"),)),
            fact("b", 2, output=Resource("material"), claims=(Claim("once"),)),
            fact("c", 3, output=Resource("material"))), (ResourcePool("once", "shared", capacity=1),))
        result = evaluate(ctx, (1, 2, 3)).data["uses"]["material"]
        self.assertEqual(result["status"], "supported")
        self.assertTrue(all(len(b["suppliers"]) == 2 for b in result["branches"] if b["status"] == "supported"))
        # The supplier not selected to meet this demand does not spend its cost.
        joint = replace(ctx, uses=ctx.uses + (use("a-later", Need("later", Resource("later"))),),
            facts=ctx.facts + (fact("later", output=Resource("later"), claims=(Claim("once"),)),))
        self.assertEqual(evaluate(joint, (1, 2, 3)).data["joint_required"]["status"], "missing")
        all_conflict = replace(ctx, facts=tuple(replace(f, claims=(Claim("once"),)) for f in ctx.facts))
        self.assertEqual(evaluate(all_conflict, (1, 2, 3)).data["uses"]["material"]["status"], "missing")
        limited = replace(ctx, budget=RelationBudget(matches=4))
        bounded = evaluate(limited, (1, 2, 3)).data['uses']['material']
        self.assertEqual(bounded['status'], 'supported')
        self.assertTrue(any(b['status']=='supported' and len(b['suppliers'])==2 for b in bounded['branches']))
        self.assertEqual(evaluate(replace(ctx,budget=RelationBudget(matches=0)),(1,2,3)).data['uses']['material']['status'],'unknown')

    def test_partial_supply_retains_pool_alternatives_and_exact_quantity_branches(self):
        ctx = RelationContext((use("material", need("material", 3)), use("later")), (
            fact("a-costly", output=Resource("material"), quantity=2, output_pool="shared", claims=(Claim("once"),)),
            fact("a-free", output=Resource("material"), output_pool="shared"),
            fact("b", 2, output=Resource("material"), quantity=2),
            fact("later", claims=(Claim("once"),))),
            (ResourcePool("shared", "one output pool", capacity=2), ResourcePool("once", "cost", capacity=1)))
        for current in (ctx, replace(ctx, facts=ctx.facts[::-1], uses=ctx.uses[::-1])):
            result = evaluate(current, (1, 2)).data["joint_required"]
            self.assertEqual(result["status"], "supported")
            witnesses = [b for b in result["branches"] if b["status"] == "supported"]
            self.assertTrue(any("a-free" in b["suppliers"] and "a-costly" not in b["suppliers"] for b in witnesses))
        uncertain = replace(ctx, facts=tuple(replace(f, unknown=("access",)) if f.fact_id == "a-free" else f for f in ctx.facts))
        self.assertEqual(evaluate(uncertain, (1, 2)).data["joint_required"]["status"], "unknown")

    def test_multiple_returns_share_physical_stock_and_check_return_costs(self):
        uses = (use("sequence", Need("first", Resource("x")), Need("second", Resource("y")),
                    Need("third", Resource("x"))),)
        ctx = RelationContext(uses,
            (fact("x", output_pool="race"), fact("y", output_pool="attribute"),
             fact("return1", 2, claims=(Claim("once"),)), fact("return2", 3, claims=(Claim("once"),))),
            (ResourcePool("race", "race selector", inventory=(("main", 1),),
                recoveries=(PoolRecovery("return1", "first", "second"),)),
             ResourcePool("attribute", "attribute selector", inventory=(("main", 1),),
                recoveries=(PoolRecovery("return2", "second", "third"),)),
             ResourcePool("once", "two returns need separate capacity", capacity=2)))
        result = evaluate(ctx, (1, 2, 3)).data["joint_required"]
        self.assertEqual(result["status"], "supported")
        witness = next(b for b in result["branches"] if b["status"] == "supported")
        self.assertTrue({"return1", "return2"} <= set(witness["suppliers"]))
        scarce = replace(ctx, pools=ctx.pools[:-1] + (replace(ctx.pools[-1], capacity=1),))
        self.assertEqual(evaluate(scarce, (1, 2, 3)).data["joint_required"]["status"], "missing")
        self.assertEqual(evaluate(ctx, (1, 2)).data["joint_required"]["status"], "missing")
        unknown = replace(ctx, facts=ctx.facts[:-1] + (replace(ctx.facts[-1], unknown=("return_access",)),))
        self.assertEqual(evaluate(unknown, (1, 2, 3)).data["joint_required"]["status"], "unknown")

    def test_return_quantity_is_not_unlimited_and_optional_return_cost_is_not_forced(self):
        ctx = RelationContext((use("both", Need("first", Resource("x"), 2), Need("second", Resource("x"), 2)),),
            (fact("x", quantity=2, output_pool="stock"), fact("return", 2)),
            (ResourcePool("stock", "inventory", inventory=(("main", 1),),
                recoveries=(PoolRecovery("return", "first", "second"),)),))
        self.assertEqual(evaluate(ctx, (1, 1, 2)).data["joint_required"]["status"], "missing")
        enough = replace(ctx, facts=(ctx.facts[0], replace(ctx.facts[1], quantity=2)))
        self.assertEqual(evaluate(enough, (1, 1, 2)).data["joint_required"]["status"], "supported")
        no_return_needed = replace(ctx, facts=(ctx.facts[0], replace(ctx.facts[1], claims=(Claim("none"),))),
            pools=(replace(ctx.pools[0], inventory=(("main", 1), ("main", 4))),
                   ResourcePool("none", "unavailable return cost", capacity=0)))
        self.assertEqual(evaluate(no_return_needed, (1, 1, 4, 4, 2)).data["joint_required"]["status"], "supported")

    def test_return_events_preserve_order_bounds_and_incremental_invalidation(self):
        needs = tuple(Need(k, Resource("x")) for k in ("first", "second", "third", "fourth"))
        returns = tuple(PoolRecovery("r"+str(i), a.need_id, b.need_id)
                        for i, (a,b) in enumerate(zip(needs,needs[1:]), 1))
        ctx = RelationContext((use("sequence", *needs[:3]),),
            (fact("x", output_pool="stock"), fact("r1",2), fact("r2",3), fact("r3",4)),
            (ResourcePool("stock", "one physical card", inventory=(("main",1),), recoveries=returns),))
        before = evaluate(ctx,(1,2,3,4))
        self.assertEqual(before.data["joint_required"]["status"],"supported")
        updated = update_relations(before,skeleton((1,2,4)),ctx)
        self.assertEqual(updated.data["joint_required"]["status"],"missing")
        self.assertEqual(semantic(updated),semantic(evaluate_relations(skeleton((1,2,4)),ctx,before.index)))
        too_many = replace(ctx,uses=(use("sequence",*needs),))
        self.assertEqual(evaluate(too_many,(1,2,3,4)).data["joint_required"]["status"],"unknown")
        repeated = replace(ctx, facts=(ctx.facts[0],replace(ctx.facts[1],quantity=2),*ctx.facts[2:]),
            pools=(replace(ctx.pools[0],recoveries=tuple(replace(r,fact_id="r1") for r in returns[:2])),))
        self.assertEqual(evaluate(repeated,(1,2,3,4)).data["joint_required"]["status"],"missing")
        reversed_order = replace(ctx, uses=(use("one",needs[0]),use("two",needs[1])),
            constraints=(JointConstraint("reverse",("two","one"),"before","sourced opposing order"),))
        self.assertEqual(evaluate(reversed_order,(1,2,3,4)).data["joint_required"]["status"],"missing")
        nested = replace(ctx,uses=(UseRequirement("nested",all_of(all_of(needs[0],needs[2]),needs[1]),"task"),))
        self.assertEqual(evaluate(nested,(1,2,3,4)).data["joint_required"]["status"],"supported")

    def test_cross_scope_recovery_rechecks_only_resource_unknowns(self):
        first, middle, last = (Need(k, Resource("x")) for k in ("first", "middle", "last"))
        ctx = RelationContext((use("outer", first, last), use("middle", middle)),
            (fact("x", output_pool="stock"), fact("r1", 2), fact("r2", 3)),
            (ResourcePool("stock", "one physical card", inventory=(("main", 1),), recoveries=(
                PoolRecovery("r1", "first", "middle"), PoolRecovery("r2", "middle", "last"))),))
        for current in (ctx, replace(ctx, uses=ctx.uses[::-1], facts=ctx.facts[::-1])):
            result = evaluate(current, (1, 2, 3))
            self.assertEqual(result.data["uses"]["outer"]["status"], "unknown")
            self.assertEqual(result.data["joint_required"]["status"], "supported")
            self.assertFalse(result.data["joint_required"]["unknown"])
            self.assertEqual(result.data["joint_required"]["support_expression"], ("all", ()))
        uncertain = replace(ctx, facts=(ctx.facts[0], replace(ctx.facts[1], unknown=("actual_return_access",)), ctx.facts[2]))
        result = evaluate(uncertain, (1, 2, 3)).data["joint_required"]
        self.assertEqual(result["status"], "unknown")
        self.assertIn("actual_return_access", result["unknown"])
        self.assertIn("fact:r1:actual_return_access", repr(result["support_expression"]))

    def test_one_return_event_releases_once_for_multiple_later_edges(self):
        ctx = RelationContext((use("prior", Need("first", Resource("x"), 2)),
                use("next", Need("second", Resource("x"))), use("last", Need("third", Resource("x")))),
            (fact("x", quantity=2, output_pool="stock"), fact("return", 2, quantity=2, claims=(Claim("once"),))),
            (ResourcePool("stock", "two physical copies", inventory=(("main", 1),), recoveries=(
                PoolRecovery("return", "first", "second"), PoolRecovery("return", "first", "third"))),
             ResourcePool("once", "one return activation", capacity=1)),
            constraints=(JointConstraint("later", ("next", "last"), "before", "sourced later order"),))
        for current in (ctx, replace(ctx, uses=ctx.uses[::-1], pools=tuple(reversed(ctx.pools)))):
            result = evaluate(current, (1, 1, 2)).data["joint_required"]
            self.assertEqual(result["status"], "supported")
            witness = next(b for b in result["branches"] if b["status"] == "supported")
            self.assertEqual(sum(r["quantity"] for r in witness["recovery_returns"]), 2)
            self.assertEqual(sum(witness["usage"]["once"].values()), 1)
        scarce = replace(ctx, facts=(ctx.facts[0], replace(ctx.facts[1], quantity=1)))
        self.assertEqual(evaluate(scarce, (1, 1, 2)).data["joint_required"]["status"], "missing")

    def test_shared_return_quantity_is_split_between_prior_consumers(self):
        ctx = RelationContext((use("prior", Need("a0", Resource("a"), 2), Need("b0", Resource("b"), 2)),
                use("next", Need("a1", Resource("a")), Need("b1", Resource("b")))),
            (fact("a", quantity=2, output_pool="race"), fact("b", 2, quantity=2, output_pool="attribute"),
             fact("return", 3, quantity=2, claims=(Claim("once"),))),
            (ResourcePool("race", "race stock", inventory=(("main", 1),), recoveries=(PoolRecovery("return", "a0", "a1"),)),
             ResourcePool("attribute", "attribute stock", inventory=(("main", 2),), recoveries=(PoolRecovery("return", "b0", "b1"),)),
             ResourcePool("once", "one event", capacity=1)),
            constraints=(JointConstraint("sequence", ("prior", "next"), "before", "original order"),))
        result = evaluate(ctx, (1, 1, 2, 2, 3)).data["joint_required"]
        self.assertEqual(result["status"], "supported")
        witness = next(b for b in result["branches"] if b["status"] == "supported")
        self.assertEqual(sorted(r["quantity"] for r in witness["recovery_returns"]), [1, 1])
        scarce = replace(ctx, facts=ctx.facts[:-1] + (replace(ctx.facts[-1], quantity=1),))
        self.assertEqual(evaluate(scarce, (1, 1, 2, 2, 3)).data["joint_required"]["status"], "missing")
        overlapping = replace(ctx, pools=(replace(ctx.pools[0], inventory=(("main", 1), ("main", 4))),
            replace(ctx.pools[1], inventory=(("main", 1), ("main", 2))), ctx.pools[2]))
        self.assertEqual(evaluate(overlapping, (1, 1, 2, 4, 3)).data["joint_required"]["status"], "supported")
        scarce_overlap = replace(overlapping, facts=scarce.facts)
        self.assertEqual(evaluate(scarce_overlap, (1, 1, 2, 4, 3)).data["joint_required"]["status"], "missing")
        uncertain = replace(ctx, facts=ctx.facts[:-1] + (replace(ctx.facts[-1], quantity=None),))
        self.assertEqual(evaluate(uncertain, (1, 1, 2, 2, 3)).data["joint_required"]["status"], "unknown")
        limited = replace(ctx, budget=RelationBudget(matches=8))
        bounded = evaluate(limited, (1,1,2,2,3)).data['joint_required']
        self.assertEqual(bounded['status'], 'supported')
        witness = next(b for b in bounded['branches'] if b['status']=='supported')
        self.assertEqual(sorted(r['quantity'] for r in witness['recovery_returns']),[1,1])
        self.assertEqual(evaluate(replace(ctx,budget=RelationBudget(matches=0)),(1,1,2,2,3)).data['joint_required']['status'],'unknown')

    def test_return_cost_order_pays_complete_cost_before_release(self):
        with self.assertRaises(ContractError):
            PoolRecovery("return", "first", "second", "after")
        ctx = RelationContext((use("both", Need("first", Resource("x"), 2), Need("second", Resource("x"), 2)),),
            (fact("x", quantity=2, output_pool="stock"), fact("return", 2, quantity=2, claims=(Claim("stock"),))),
            (ResourcePool("stock", "return also consumes one whole copy", inventory=(("main", 1),),
                recoveries=(PoolRecovery("return", "first", "second"),)),))
        self.assertEqual(evaluate(ctx, (1, 1, 1, 2)).data["joint_required"]["status"], "unknown")
        for timing in ("before", "between"):
            ordered = replace(ctx, pools=(replace(ctx.pools[0], recoveries=(PoolRecovery("return", "first", "second", timing),)),))
            result = evaluate(ordered, (1, 1, 1, 2)).data["joint_required"]
            self.assertEqual(result["status"], "supported")
            self.assertEqual(evaluate(ordered, (1, 1, 2)).data["joint_required"]["status"], "missing")
            scarce = replace(ordered, facts=(ordered.facts[0], replace(ordered.facts[1], quantity=1)))
            self.assertEqual(evaluate(scarce, (1, 1, 1, 2)).data["joint_required"]["status"], "missing")
        enough_stock = replace(ctx, pools=(replace(ctx.pools[0], inventory=(("main", 1), ("main", 4))),))
        no_return = evaluate(enough_stock, (1, 1, 4, 4, 2)).data["joint_required"]
        self.assertEqual(no_return["status"], "supported")
        self.assertNotIn("return", no_return["suppliers"])

    def test_return_prerequisite_recovery_rechecks_costs_and_invalidates_consumers(self):
        ctx = RelationContext((use("both", Need("first", Resource("a")), Need("second", Resource("a"))),),
            (fact("a", output_pool="a"), fact("b", 2, output_pool="b"), fact("return-b", 3),
             fact("return-a", 4, inputs=all_of(Need("fee1", Resource("b")), Need("fee2", Resource("b"))))),
            (ResourcePool("a", "first stock", inventory=(("main", 1),), recoveries=(PoolRecovery("return-a", "first", "second"),)),
             ResourcePool("b", "return cost stock", inventory=(("main", 2),), recoveries=(PoolRecovery("return-b", "fee1", "fee2"),))))
        result = evaluate(ctx, (1, 2, 3, 4))
        self.assertEqual(result.fact_states["return-a"]["status"], "supported")
        joint = result.data["joint_required"]
        self.assertEqual(joint["status"], "supported")
        witness = next(b for b in joint["branches"] if b["status"] == "supported")
        self.assertEqual({r["fact_id"] for r in witness["recovery_returns"]}, {"return-a", "return-b"})
        self.assertEqual(sum(witness["usage"]["b"].values()), 2)
        removed = skeleton((1, 2, 4))
        updated = update_relations(result, removed, ctx)
        self.assertEqual(updated.fact_states["return-a"]["status"], "missing")
        self.assertEqual(updated.data["joint_required"]["status"], "missing")
        self.assertEqual(semantic(updated), semantic(evaluate_relations(removed, ctx, result.index)))


    def test_multiple_uncertain_supplies_keep_joint_quantity_unknown(self):
        ctx = RelationContext((use("material", need("material", 2)),), (
            fact("a", output=Resource("material"), unknown=("access",)),
            fact("b", 2, output=Resource("material"), unknown=("timing",))))
        self.assertEqual(evaluate(ctx, (1, 2)).data["uses"]["material"]["status"], "unknown")

    def test_same_name_copies_do_not_reset_shared_limit(self):
        ctx = RelationContext((use("a"), use("b")), (
            fact("a", claims=(Claim("once"),)), fact("b", claims=(Claim("once"),))),
            (ResourcePool("once", "same name once", capacity=1),))
        result = evaluate(ctx, (1, 1, 1)).data
        self.assertTrue(all(v["status"] == "supported" for v in result["uses"].values()))
        self.assertEqual(result["joint_required"]["status"], "missing")
        self.assertEqual(result["joint_required"]["conflicts"][0]["required"], 2)

    def test_multi_output_effect_shares_one_activation(self):
        a, b = fact("a", claims=(Claim("once"),)), fact("b", claims=(Claim("once"),))
        ctx = RelationContext((use("both", need("a"), need("b")),),
            (replace(a, effect_ref="one-effect"), replace(b, effect_ref="one-effect")),
            (ResourcePool("once", "one use", capacity=1),))
        self.assertEqual(evaluate(ctx).data["uses"]["both"]["status"], "supported")
        alternative = replace(ctx, facts=(ctx.facts[0], replace(ctx.facts[1], choice="other")))
        self.assertEqual(evaluate(alternative).data["uses"]["both"]["status"], "missing")

    def test_optional_choices_do_not_consume_two_required_resources(self):
        ctx = RelationContext((UseRequirement("choice", any_of(need("a"), need("b")), "task"),),
            (fact("a", claims=(Claim("once"),)), fact("b", claims=(Claim("once"),))),
            (ResourcePool("once", "one", capacity=1),))
        self.assertEqual(evaluate(ctx).data["joint_required"]["status"], "supported")

    def test_a_plus_b_and_b_plus_c_compete_for_b(self):
        b1 = Need("b1", Resource("b"))
        b2 = Need("b2", Resource("b"))
        ctx = RelationContext((use("ab", need("a"), b1), use("bc", b2, need("c"))),
            (fact("a"), fact("b", 2, output_pool="b-stock", inventory_scaled=True), fact("c", 3)),
            (ResourcePool("b-stock", "physical", inventory=(("main", 2),)),))
        self.assertEqual(evaluate(ctx, (1, 2, 3)).data["joint_required"]["status"], "missing")
        self.assertEqual(evaluate(ctx, (1, 2, 2, 3)).data["joint_required"]["status"], "supported")

    def test_presence_can_share_but_consuming_distinct_inputs_cannot(self):
        inputs = tuple(Need("p" + str(i), Resource("x"), mode="presence") for i in range(2))
        ctx = RelationContext((use("exists", *inputs),), (fact("x"),))
        self.assertEqual(evaluate(ctx).data["joint_required"]["status"], "supported")
        ctx = replace(ctx, uses=(use("exists", *(replace(n, mode="consume") for n in inputs)),))
        self.assertEqual(evaluate(ctx).data["joint_required"]["status"], "missing")

    def test_same_named_need_in_two_uses_is_two_consumptions(self):
        ctx = RelationContext((use("one", need("x")), use("two", need("x"))), (fact("x"),))
        self.assertEqual(evaluate(ctx).data["joint_required"]["status"], "missing")

    def test_recovery_requires_supported_fact_and_still_preserves_order(self):
        ctx = RelationContext((use("both", Need("x1", Resource("x")), Need("x2", Resource("x"))),),
            (fact("x", output_pool="stock"), fact("recover", 2)),
            (ResourcePool("stock", "one", capacity=1, reusable_if="recover"),))
        self.assertEqual(evaluate(ctx).data["joint_required"]["status"], "missing")
        result = evaluate(ctx, (1, 2)).data["joint_required"]
        self.assertEqual(result["status"], "unknown")
        self.assertIn("recovery_order:stock", result["unknown"])

    def test_order_and_known_incompatibility_are_distinct(self):
        ctx = RelationContext((use("a"), use("b")), (fact("a"), fact("b")),
            constraints=(JointConstraint("sequence", ("a", "b"), "order_unknown", "restriction fact"),))
        self.assertEqual(evaluate(ctx).data["joint_required"]["status"], "unknown")
        ctx = replace(ctx, constraints=(replace(ctx.constraints[0], kind="incompatible"),))
        self.assertEqual(evaluate(ctx).data["joint_required"]["status"], "missing")

    def test_overlapping_material_pools_use_distinct_integer_entities(self):
        ctx = RelationContext((use("a"), use("b")),
            (fact("a", output_pool="race"), fact("b", output_pool="attribute")),
            (ResourcePool("race", "type", inventory=(("main", 1), ("main", 2))),
             ResourcePool("attribute", "type", inventory=(("main", 1), ("main", 3)))))
        result = evaluate(ctx, (1, 2, 3)).data["joint_required"]
        self.assertEqual(result["status"], "supported")
        self.assertEqual(evaluate(ctx, (1,)).data["joint_required"]["status"], "missing")

    def test_bad_sources_references_and_quantities_rejected(self):
        for action in (lambda: fact("x", source=""), lambda: Need("x", Resource("x"), 1.9),
                       lambda: InputGroup("implicit", (need("x"),)),
                       lambda: relation_index(None, RelationContext((use("x"),), (fact("x", output_pool="absent"),)))):
            with self.assertRaises((ContractError, TypeError)):
                action()


class EditComparisonTests(unittest.TestCase):
    def test_required_gap_repair_precedes_slot_cost_and_optional_loss(self):
        ctx = RelationContext((use("a"), use("b", required=False)), (fact("a", 2), fact("b")))
        before, after = evaluate(ctx, (1,)), evaluate(ctx, (2, 2))
        result = compare_configurations(before, after, ctx)
        self.assertEqual((result.status, result.preferred), ("preferred", "after"))
        self.assertIn("support:b", result.advantages_before)

    def test_two_different_required_losses_are_not_offset_by_count(self):
        ctx = RelationContext((use("a"), use("b")), (fact("a"), fact("b", 2)))
        result = compare_configurations(evaluate(ctx, (1,)), evaluate(ctx, (2,)), ctx)
        self.assertEqual(result.status, "tradeoff")
        self.assertEqual(result.changes["slots"]["main"], 0)
        self.assertEqual(result.changes["cards"]["main"]["removed"], [1])

    def test_higher_original_priority_can_decide_real_tradeoff(self):
        ctx = RelationContext((use("a", priority=0), use("b", priority=2)), (fact("a"), fact("b", 2)))
        result = compare_configurations(evaluate(ctx, (1,)), evaluate(ctx, (2,)), ctx)
        self.assertEqual((result.status, result.preferred), ("preferred", "after"))

    def test_partial_and_gap_repair_has_value_without_claiming_completion(self):
        ctx = RelationContext((use("abc", need("a"), need("b"), need("c")),),
                              (fact("a"), fact("b", 2)))
        result = compare_configurations(evaluate(ctx), evaluate(ctx, (1, 2)), ctx)
        self.assertEqual(result.preferred, "after")
        self.assertEqual(result.changes["uses"]["abc"]["after"], "missing")

    def test_partial_integer_shortfall_repair_is_explicit(self):
        ctx = RelationContext((use("material", need("material", 3)),),
            (fact("material", inventory_scaled=True, output_pool="stock"),),
            (ResourcePool("stock", "physical", inventory=(("main", 1),)),))
        before, after = evaluate(ctx), evaluate(ctx, (1, 1))
        self.assertEqual(before.data["uses"]["material"]["quantities"]["material"]["shortfall_lower"], 2)
        self.assertEqual(after.data["uses"]["material"]["quantities"]["material"]["shortfall_lower"], 1)
        self.assertEqual(compare_configurations(before, after, ctx).preferred, "after")

    def test_extra_copy_probability_improvement_is_a_slot_tradeoff(self):
        ctx = RelationContext((use("a"),), (fact("a"),),
            probabilities=(ProbabilityRequest("draw", (1,), 5, "initial sample"),))
        layer = axis_context(requirements=(), relations=ctx)
        index = relation_index(None, layer)
        before = evaluate_relations(skeleton((1,)), layer, index)
        after = evaluate_relations(skeleton((1, 1)), layer, index)
        result = compare_configurations(before, after, layer)
        self.assertEqual(result.status, "tradeoff")
        self.assertEqual(after.data["probabilities"]["draw"]["copies"], 2)

    def test_probability_values_and_zero_all_boundary(self):
        self.assertEqual(single_event_probabilities(40, 1, 5)["acquired"], .125)
        self.assertEqual(single_event_probabilities(40, 1, 5)["retained"], .875)
        self.assertAlmostEqual(single_event_probabilities(40, 2, 5)["acquired"], .23717948717948723)
        for size, m, h in ((40, 0, 5), (0, 0, 0), (40, 40, 40)):
            result = single_event_probabilities(size, m, h)
            self.assertEqual(result["retained"], 0)
        with self.assertRaises(ContractError):
            single_event_probabilities(40, 1.9, 5)
        single_event_probabilities(40, 1, 5)["acquired"] = 100
        self.assertEqual(single_event_probabilities(40, 1, 5)["acquired"], .125)

    def test_common_unknown_does_not_freeze_known_slot_difference(self):
        ctx = RelationContext((use("a"),), (fact("a", unknown=("same condition",)),))
        result = compare_configurations(evaluate(ctx, (1, 1)), evaluate(ctx), ctx)
        self.assertEqual((result.status, result.preferred), ("preferred", "after"))

    def test_new_unknown_benefit_is_undetermined(self):
        ctx = RelationContext((use("a"),), (fact("a", 2, unknown=("condition",)),))
        result = compare_configurations(evaluate(ctx), evaluate(ctx, (2,)), ctx)
        self.assertEqual(result.status, "undetermined")

    def test_shared_material_small_package_counts_unique_physical_slots(self):
        ctx = RelationContext((use("a"),), (fact("a"),))
        base = skeleton((1,))
        after = skeleton((1,), (2,), modules=(
            AxisModule("a", "first", refs(1)), AxisModule("b", "package", refs(1) + refs(2, zone="extra"))))
        index = relation_index(None, ctx)
        result = compare_configurations(evaluate_relations(base, ctx, index), evaluate_relations(after, ctx, index), ctx)
        self.assertEqual(result.changes["slots"], {"main": 0, "extra": 1})

    def test_different_limit_and_independent_entry_relieve_recorded_bottleneck(self):
        ctx = RelationContext((use("a"),), (
            fact("one", output=Resource("a"), claims=(Claim("first"),)),
            fact("two", 2, output=Resource("a"), claims=(Claim("second"),))),
            (ResourcePool("first", "source1", capacity=1), ResourcePool("second", "source2", capacity=1)))
        old = evaluate(ctx).data["uses"]["a"]["bottlenecks"]
        new = evaluate(ctx, (1, 2)).data["uses"]["a"]["bottlenecks"]
        self.assertIn("first", old)
        self.assertNotIn("first", new)

    def test_disjoint_conditional_alternatives_are_not_unconditional(self):
        ctx = RelationContext((use("x"),), (
            fact("a", output=Resource("x"), conditions=("requires-A",)),
            fact("b", 2, output=Resource("x"), conditions=("requires-B",)),
            fact("c", 3, output=Resource("x"))))
        before, after = evaluate(ctx, (1, 2)), evaluate(ctx, (1, 2, 3))
        self.assertNotEqual(before.data["uses"]["x"]["condition_expression"], ("all", ()))
        result = compare_configurations(before, after, ctx)
        self.assertIn("conditions:x", result.advantages_after)

    def test_incremental_recovery_invalidation_equals_full(self):
        ctx = RelationContext((use("both", Need("x1", Resource("x")), Need("x2", Resource("x"))),),
            (fact("x", output_pool="stock"), fact("recover", 2)),
            (ResourcePool("stock", "one", capacity=1, reusable_if="recover"),))
        before = evaluate(ctx)
        updated = update_relations(before, skeleton((1, 2)), ctx)
        full = evaluate_relations(skeleton((1, 2)), ctx, before.index)
        self.assertEqual(semantic(updated), semantic(full))

    def test_incremental_equals_full_after_removal_addition_and_module_change(self):
        ctx = RelationContext((use("b"), use("other")), (
            fact("a"), fact("b", 2, inputs=all_of(need("a"))), fact("other", 3)))
        index = relation_index(None, ctx)
        value = evaluate_relations(skeleton((1, 2, 3)), ctx, index)
        for spec in (skeleton((2, 3)), skeleton((1, 2, 3)), skeleton((1, 1, 2, 3)),
                     skeleton((1, 2, 3), modules=(AxisModule("only", "subset", refs(3)),))):
            updated = update_relations(value, spec, ctx)
            full = evaluate_relations(spec, ctx, index)
            self.assertEqual(semantic(updated), semantic(full))
            self.assertTrue(updated.data["work"]["incremental"])
            value = updated

    def test_same_index_reuses_unaffected_uses_and_context_change_rejects(self):
        ctx = RelationContext((use("a"), use("b")), (fact("a"), fact("b", 2)))
        result = evaluate(ctx, (1, 2))
        updated = update_relations(result, skeleton((1, 1, 2)), ctx)
        self.assertEqual(updated.data["work"]["affected_uses"], 1)
        with self.assertRaises(ContractError):
            update_relations(result, skeleton((1,)), replace(ctx, facts=ctx.facts + (fact("c"),)))


class BudgetAndGeneralityTests(unittest.TestCase):
    def test_saved_operation_proof_keeps_its_capacity_after_resume(self):
        operation = Resource("functional_operation", attributes=("a",))
        ctx = RelationContext((use("b"),), (
            fact("a", output=operation, conditions=("prepared",)),
            fact("b", inputs=all_of(Need("prior", operation, mode="presence"))),
            fact("c"),
        ))
        full = evaluate(ctx)
        sliced = replace(ctx, budget=RelationBudget(updates=2))
        pending = evaluate(sliced, resumable=True).data["continuation"]
        self.assertIn("operation-proof:a", pending["states"]["b"]["usage"])
        self.assertEqual(pending["queue"], ["c"])
        resumed = evaluate(sliced, continuation=json.loads(json.dumps(pending)), resumable=True)
        self.assertEqual(semantic(resumed), semantic(full))

    def test_matching_budget_before_checks_and_truncation_is_not_missing(self):
        ctx = RelationContext((use("a"), use("b")), (fact("a"), fact("b")),
                              budget=RelationBudget(matches=1))
        result = evaluate(ctx).data
        self.assertEqual(result["work"]["M"], 1)
        self.assertEqual(result["uses"]["a"]["status"], "supported")
        self.assertEqual(result["uses"]["b"]["status"], "unknown")

    def test_fact_and_update_budgets_report_uncovered(self):
        ctx = RelationContext((use("a"), use("b")), (fact("a"), fact("b")), budget=RelationBudget(facts=1))
        result = evaluate(ctx).data
        self.assertEqual(result["work"]["F"], 1)
        self.assertEqual(result["uses"]["b"]["status"], "unknown")
        ctx = replace(ctx, budget=RelationBudget(updates=0))
        result = evaluate(ctx).data
        self.assertTrue(result["budget"]["update_exhausted"])
        self.assertEqual(result["uses"]["a"]["status"], "unknown")

    def test_zero_recall_budget_does_not_touch_catalog(self):
        catalog = Mock()
        ctx = RelationContext((use("a"),), catalog_cards=(1, 2), budget=RelationBudget(cards=0))
        index = relation_index(catalog, ctx)
        catalog.effect_records.assert_not_called()
        self.assertTrue(index.truncated_facts)

    def test_alternating_diamonds_bound_condition_explanation(self):
        facts = [fact("seed", output=Resource("r0"))]
        for level in range(1, 15):
            for branch in ("a", "b"):
                facts.append(fact(f"f{level}-{branch}", output=Resource(f"r{level}"),
                    inputs=all_of(Need(f"input-{level}-{branch}", Resource(f"r{level-1}"))),
                    conditions=(f"condition-{level}-{branch}",)))
        ctx = RelationContext((use("last", Need("last", Resource("r14"))),), tuple(facts))
        result = evaluate(ctx).data
        self.assertEqual(result["uses"]["last"]["status"], "supported")
        self.assertEqual(result["budget"]["condition_uncovered_uses"], [])
        self.assertLess(result["work"]["updates"], 200)
        self.assertEqual(len(result["fact_records"]), 29)

    def test_fact_order_module_split_and_card_rename_preserve_meaning(self):
        ctx = RelationContext((use("x"),), (fact("a", output=Resource("x")), fact("b", 2, output=Resource("x"))))
        a = evaluate(ctx, (1, 2))
        b = evaluate(replace(ctx, facts=ctx.facts[::-1]), (2, 1))
        self.assertEqual(a.data["uses"], b.data["uses"])
        renamed = replace(ctx, facts=tuple(replace(f, card_id=f.card_id + 40) for f in ctx.facts))
        c = evaluate(renamed, (41, 42))
        self.assertEqual(a.data["uses"], c.data["uses"])

    def test_anonymous_mechanisms_use_same_kernel(self):
        for kind, zone in (("tool", "hand"), ("recovery", "deck"), ("banished", "banished"),
                           ("spell", "field"), ("response", "field"), ("main_terminal", "field")):
            with self.subTest(kind=kind):
                resource = Resource(kind, zone, reason="effect")
                ctx = RelationContext((use("purpose", Need("wanted", resource)),),
                                      (fact("supply", output=resource, conditions=("explicit access",)),))
                self.assertEqual(evaluate(ctx).data["joint_required"]["status"], "supported")

    def test_wide_matching_growth_is_product_of_ports_and_needs_not_suppliers(self):
        measured = []
        for size in (20, 40):
            ctx = RelationContext(tuple(use(f"u{i}", Need(f"n{i}", Resource("wide"), mode="presence")) for i in range(size)),
                tuple(fact(f"f{i}", output=Resource("wide")) for i in range(size)))
            start = time.perf_counter()
            result = evaluate(ctx)
            measured.append({**result.data["work"], "total_seconds": time.perf_counter()-start})
            self.assertEqual(result.data["work"]["M"], size * size)
            self.assertEqual(result.data["work"]["L"], size * size)
        self.assertEqual(measured[1]["M"], 4 * measured[0]["M"])
        print("RELATION_SCALE " + json.dumps(measured, sort_keys=True))

    def test_sparse_shared_resources_and_hot_updates_have_visible_work(self):
        import tracemalloc
        measured = []
        for shape in ("sparse", "shared"):
            ctx = RelationContext(tuple(use(f"u{i}", need(f"r{i}")) for i in range(24)),
                tuple(fact(f"f{i}", i % 8 + 1, output=Resource(f"r{i}"),
                           claims=(Claim("once"),) if shape == "shared" else ()) for i in range(24)),
                (ResourcePool("once", "global opportunity", capacity=1),) if shape == "shared" else ())
            tracemalloc.start()
            index = relation_index(None, ctx)
            cold = evaluate_relations(skeleton(tuple(range(1, 9))), ctx, index)
            hot = update_relations(cold, skeleton(tuple(range(1, 9)) + (1,)), ctx)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            self.assertEqual(semantic(hot), semantic(evaluate_relations(skeleton(tuple(range(1, 9)) + (1,)), ctx, index)))
            self.assertEqual(index.counters["M"], 24)
            self.assertEqual(hot.data["work"]["affected_uses"], 3)
            self.assertEqual(hot.data["work"]["updates"], 3)
            measured.append({"shape": shape, "peak_traced_bytes": peak, "cold": cold.data["work"], "hot": hot.data["work"]})
        print("RELATION_HOT_SCALE " + json.dumps(measured, sort_keys=True))

    def test_no_torch_cb_or_engine_dependency_in_kernel(self):
        import ast
        from pathlib import Path
        path = Path(__file__).parents[1] / "src/ygo_kito/construction_relations.py"
        imports = [n.module for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(n, ast.ImportFrom)]
        self.assertFalse(any(v and any(k in v for k in ("native", "cb_", "build_model", "torch")) for v in imports))
        with patch("ygo_kito.construction_relations._record_facts", side_effect=AssertionError("no recall requested")):
            self.assertEqual(evaluate(RelationContext((use("a"),), (fact("a"),))).data["joint_required"]["status"], "supported")


if __name__ == "__main__":
    unittest.main()
