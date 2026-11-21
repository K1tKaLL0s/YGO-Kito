"""Complete printed conditions and selections through the normal Evaluation."""
import unittest
from dataclasses import replace

from ygo_kito.construction_binding import CatalogBindingAdapter
from ygo_kito.construction_inventory import selector, matches, requirement
from tests import test_construction_static_entries


class ConditionSelectionTests(unittest.TestCase):
    setUp = test_construction_static_entries.StaticEntryTests.setUp
    evaluate = test_construction_static_entries.StaticEntryTests.evaluate
    state = test_construction_static_entries.StaticEntryTests.state

    def test_presence_and_activation_event_require_the_printed_support(self):
        self.assets.rows[1].update(type=4, desc='①：自己场上有「匿名2」怪兽或者「匿名3」存在，'
            '怪兽的效果·魔法·陷阱卡发动时才能发动。那个发动无效。')
        facts, quality = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True])
        self.assertTrue(quality['complete'], quality['unknowns'])
        absent = replace(self.deck, main=tuple(c for c in self.deck.main if c not in (2, 3)))
        failed, _ = self.evaluate(absent)
        self.assertEqual(self.state(failed, 1), [False])
        self.assets.rows[1]['desc'] = self.assets.rows[1]['desc'].replace('存在，', '存在且满足未知规则，')
        unknown, quality = self.evaluate()
        self.assertEqual(self.state(unknown, 1), [None])
        self.assertFalse(quality['complete'])

    def test_presence_and_event_bind_the_activated_card_reference(self):
        self.assets.rows[1].update(type=4, desc='①：自己场上有「匿名2」存在，'
            '怪兽的效果·魔法·陷阱卡发动时才能发动。那个发动无效，那张卡回到持有者卡组。'
            '那之后，从自己手卡选1只怪兽送去墓地。')
        facts, quality = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True, True, True])
        self.assertTrue(quality['complete'], quality['unknowns'])
        catalog = CatalogBindingAdapter(self.assets).semantic_catalog
        record = catalog.effect_records(1)[0]
        returned = next(o for o in record['operations'] if o['kind'] == 'return_deck')
        self.assertEqual(returned['subject'], 'activated_card')
        self.assertEqual(returned['quantity'], 1)
        self.assertNotIn('selector_query', returned)

    def test_counted_mixed_choice_keeps_card_name_mentions(self):
        self.assets.rows[1].update(type=33, desc='①：自己主要阶段才能发动。'
            '把1只「不存在」或者1张有那个卡名记述的魔法·陷阱卡从卡组加入手卡。')
        self.assets.rows[2].update(type=2, desc='普通说明，有「不存在」的卡名记述。')
        facts, quality = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True])
        # The mention belongs to the complete selector, not to archetype membership.
        self.assets.rows[2]['desc'] = '普通说明，没有对应的卡名。'
        failed, _ = self.evaluate()
        self.assertEqual(self.state(failed, 1), [False])
        parsed = requirement('把1只「不存在」或者1张有那个卡名记述的魔法·陷阱卡从卡组加入手卡', 'operations')
        self.assertEqual(parsed['minimum'], 1)
        self.assertTrue(matches(dict(name='别名', type=4, desc='「不存在」'), parsed['query']))
        self.assertFalse(matches(dict(name='别名', type=1, desc='「不存在」'), parsed['query']))
        self.assertIsNone(requirement('把1只「不存在」或者2张卡从卡组加入手卡', 'operations'))

    def test_complete_postfix_zone_and_qualifiers_are_not_dropped(self):
        self.assets.rows[1].update(type=33, desc='①：自己主要阶段才能发动。'
            '把1只4星以下的水属性怪兽从卡组加入手卡。')
        self.assets.rows[2].update(attribute=2, level=4)
        facts, quality = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True])
        self.assertTrue(quality['complete'], quality['unknowns'])
        for row in self.assets.rows.values(): row['attribute'] = 4
        failed, _ = self.evaluate()
        self.assertEqual(self.state(failed, 1), [False])
        self.assertIsNone(selector('4星以下的水属性且具有未知标志的怪兽'))

    def test_inline_outcomes_are_alternative_uses_of_one_entity(self):
        self.assets.rows[1].update(type=2, desc='①：自己主要阶段才能发动。'
            '从卡组把1只4星以下的水属性怪兽加入手卡或特殊召唤。')
        for row in self.assets.rows.values(): row['attribute'] = 4
        self.assets.rows[2].update(attribute=2, level=4)
        facts, quality = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True, True])
        self.assertTrue(quality['complete'], quality['unknowns'])
        catalog = CatalogBindingAdapter(self.assets).semantic_catalog
        record = catalog.effect_records(1)[0]
        self.assertEqual(len(record['branch_records']), 2)
        self.assertEqual(len({o['choice'] for o in record['operations']}), 2)
        self.assets.rows[2]['attribute'] = 4
        failed, _ = self.evaluate()
        self.assertEqual(self.state(failed, 1), [False, False])

    def test_inline_outcomes_preserve_common_opponent_return(self):
        self.assets.rows[1].update(type=33, desc='①：以除外的1张对方的卡为对象才能发动。'
            '从卡组把1只4星以下的水属性怪兽加入手卡或特殊召唤，作为对象的卡加入对方手卡。')
        for row in self.assets.rows.values(): row['attribute'] = 4
        self.assets.rows[2].update(attribute=2, level=4)
        facts, quality = self.evaluate()
        self.assertTrue(all(self.state(facts, 1)), self.state(facts, 1))
        self.assertTrue(quality['complete'], quality['unknowns'])
        record = CatalogBindingAdapter(self.assets).semantic_catalog.effect_records(1)[0]
        self.assertEqual(len(record['branch_records']), 2)
        self.assertTrue(all(len(b['operations'])==2 for b in record['branch_records'].values()))

    def test_option_activation_payment_is_not_a_resolution_operation(self):
        self.assets.rows[1].update(type=2, desc='可以从以下效果选择1个发动。'
            '\n●从自己手卡把1只「匿名2」怪兽送去墓地才能发动。自己抽2张。'
            '\n●自己抽1张。')
        facts, quality = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True, True])
        self.assertTrue(quality['complete'], quality['unknowns'])
        record = CatalogBindingAdapter(self.assets).semantic_catalog.effect_records(1)[0]
        self.assertTrue(all(o['kind']=='draw' for o in record['operations']))

    def test_dynamic_damage_retains_formula_without_adjectival_set_operation(self):
        self.assets.rows[1].update(type=33, desc='②：自己·对方的结束阶段发动。'
            '给与对方为场上盖放的卡数量×100伤害。')
        facts, quality = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True])
        self.assertTrue(quality['complete'], quality['unknowns'])
        record = CatalogBindingAdapter(self.assets).semantic_catalog.effect_records(1)[0]
        self.assertEqual([o['kind'] for o in record['operations']], ['damage'])
        damage = record['operations'][0]
        self.assertNotIn('amount', damage)
        self.assertEqual(damage['amount_rule']['multiplier'], 100)

    def test_inline_outcomes_inside_one_option_do_not_replace_other_options(self):
        self.assets.rows[1].update(type=2, desc='从以下效果选择1个发动。'
            '\n●从卡组把1只4星以下的水属性怪兽加入手卡或送去墓地。'
            '\n●自己抽1张。')
        for row in self.assets.rows.values(): row['attribute'] = 4
        self.assets.rows[2].update(attribute=2, level=4)
        facts, quality = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True, True, True])
        self.assertTrue(quality['complete'], quality['unknowns'])
        record = CatalogBindingAdapter(self.assets).semantic_catalog.effect_records(1)[0]
        self.assertEqual(len(record['branch_records']), 3)

    def test_many_automatic_theme_counterparts_preserve_every_condition(self):
        from ygo_kito.construction_layer_flow import _bind_automatic_themes
        from ygo_kito.construction_quality import support_state, support_facts
        from ygo_kito.construction_theme import SECONDARY
        from tests.test_construction_functional_quality import use
        source = use('source', sources=('main:1:1',))
        facts = dict(uses=[source], use_details={
            'source': dict(operation_key=(1, 0, 0), goal_id='preparation')}, scope_status={})
        pairs, variables = [], {}
        for i in range(257):
            code = i + 2
            key = 'counterpart:' + str(i)
            receiver = use(key, sources=(f'main:{code}:1',), family=key, condition=key)
            facts['uses'].append(receiver)
            facts['use_details'][key] = dict(operation_key=(code, 0, 0), goal_id='goal')
            variables[key] = None
            pairs.append(dict(source=(1, 0, 0), receiver=(code, 0, 0), connection=dict(gaps=[])))
        relation = dict(theme_pairs=pairs)
        _bind_automatic_themes(facts, {'resident': (relation, {})},
            dict(theme_profile=dict(gaps=[], goals=[dict(goal_id='goal')])), None, {})
        expression=dict(facts['uses'][0].theme_conditions)[SECONDARY]
        self.assertEqual(support_facts(expression),set(variables))
        self.assertEqual(len(variables),257)
        self.assertIsNone(support_state(expression,variables))
        false={key:False for key in variables}
        self.assertIs(support_state(expression,false),False)
        for key in (next(iter(variables)),next(reversed(variables))):
            self.assertIs(support_state(expression,dict(false,**{key:True})),True)

    def test_large_relation_support_keeps_boolean_meaning_and_fact_ids(self):
        from ygo_kito.construction_layer_flow import _relation_support
        from ygo_kito.construction_quality import support_state, support_facts, validate_support
        for operator in ('all','any'):
            expression=_relation_support(dict(status='unknown',support_expression=(operator,
                tuple(('atom','condition:'+str(i)) for i in range(257)))), 'large','resident',lambda key,*_:key,('printed support',))
            validate_support(expression)
            keys=support_facts(expression)
            self.assertEqual(len(keys),257)
            base={key:operator=='all' for key in keys}
            self.assertIs(support_state(expression,base),operator=='all')
            for key in (min(keys),max(keys)):
                self.assertIs(support_state(expression,dict(base,**{key:operator!='all'})),operator!='all')

    def test_identical_direction_views_reuse_only_completed_relations(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from ygo_kito.build_contracts import BuildTask
        from ygo_kito.construction_layer_flow import normalize_function_uses, _functional_relations
        from ygo_kito.construction_progress import host_construction_quality
        from ygo_kito.construction_quality import evaluate_functional_quality
        from tests.test_construction_theme import theme_fixture
        task,assets,graph,binder,decks,relations=theme_fixture()
        raw=task.to_dict();raw['sizes']['side']=1;task=BuildTask.from_dict(raw)
        side=next(c for c in assets.rows if c not in decks[0].main)
        deck=replace(decks[0],side=(side,))
        policy=host_construction_quality(task,catalog=binder.semantic_catalog)[0]
        with patch('ygo_kito.construction_layer_flow._functional_relations',wraps=_functional_relations) as calculate:
            facts=normalize_function_uses(task,deck,binder.semantic_catalog,policy=policy,
                context=SimpleNamespace(relations=relations))
        self.assertEqual(calculate.call_count,2)
        self.assertEqual({u.scope_id for u in facts['uses']},{'resident','going_first','going_second'})
        quality=evaluate_functional_quality(dict(axis=dict(task=task.to_dict(),inventory=deck.to_dict(),logic=graph.to_dict())),policy=policy,facts=facts)
        self.assertTrue(quality['complete'],quality['unknowns'])

    def test_direction_resource_view_uses_its_original_legal_candidate(self):
        from types import SimpleNamespace
        from ygo_kito.build_contracts import BuildTask, DeckParts
        from ygo_kito.construction_inventory import InventoryDependencies
        from ygo_kito.construction_layer_flow import normalize_function_uses
        from ygo_kito.validation import ContractError
        for code in range(101,131):
            self.assets.rows[code]=dict(self.assets.rows[2],id=code,name='匿名资源'+str(code),
                type=0x51 if code<118 else 17,desc='战士族怪兽＋战士族怪兽' if code<118 else '普通怪兽。')
        self.assets.rows[1].update(type=33,desc='①：自己主要阶段才能发动。'
            '这张卡从手卡特殊召唤，从自己手卡选1只怪兽送去墓地。')
        deck=DeckParts(self.deck.main,tuple(range(101,116)),tuple(range(116,131)))
        raw=self.task.to_dict();raw['sizes'].update(extra=15,side=15);raw['pool']=sorted(self.assets.rows)
        task=BuildTask.from_dict(raw)
        catalog=CatalogBindingAdapter(self.assets).semantic_catalog
        facts=normalize_function_uses(task,deck,catalog,policy=self.policy)
        self.assertEqual(self.state(facts,1),[True]*6)
        dependencies=InventoryDependencies(catalog)
        record=dependencies.specs(1)[0][0]['record']
        view=SimpleNamespace(main=deck.main+tuple(range(118,131)),extra=tuple(range(101,118)))
        check=dependencies.processing_check(view,record,physical_inventory=deck)
        self.assertEqual(check['status'],'inventory_present')
        with self.assertRaisesRegex(ContractError,'cannot invent physical copies'):
            dependencies.processing_check(view,record,physical_inventory=replace(deck,side=tuple(c for c in deck.side if c!=117)))


if __name__ == '__main__':
    unittest.main()
