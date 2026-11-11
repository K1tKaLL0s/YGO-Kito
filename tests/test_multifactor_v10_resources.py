"""V10 sourced recovery facts, finite stock, intervals and named-use limits."""
from dataclasses import replace
import unittest

from ygo_kito.multifactor.conditions import Condition, ConditionGroup, Resource, solve_requirements


class V10ResourceRecoveryTests(unittest.TestCase):
    def initial(self):
        return Resource('card', 'fixture-card', resource_id='entity:one', pool_id='availability:initial',
                        stage='activation', state_zone='hand', source='fixture:initial hand')

    def recovered(self, **changes):
        value = Resource('card', 'fixture-card', resource_id='entity:one', pool_id='availability:returned',
                         stage='post_resolution', state_zone='hand', selectors=('any-monster',),
                         source='fixture:explicit return after resolution')
        return replace(value, **changes)

    def use(self, stage, selector='fixture-card'):
        return Condition('card', selector, stage=stage, state_zone='hand')

    def allocations(self, result):
        return [branch for branch in result['branches'] if branch['satisfied'] is True]

    def test_recovery_is_available_only_at_its_declared_stage(self):
        initial, returned = self.initial(), self.recovered()
        stock = (initial, returned)
        frozen = tuple(value.to_dict() for value in stock)
        tree = ConditionGroup('all', (self.use('activation'), self.use('post_resolution')))
        for wrong in (None, replace(returned, state_zone='grave'), replace(returned, owner='opponent')):
            with self.subTest(stock=wrong):
                supplied = (initial,) if wrong is None else (initial, wrong)
                self.assertIs(solve_requirements(tree, supplied, coverage=True)['satisfied'], False)
        early = ConditionGroup('all', (self.use('activation'), self.use('resolution')))
        self.assertIs(solve_requirements(early, stock, coverage=True)['satisfied'], False)
        result = solve_requirements(tree, stock, coverage=True, state_provided=True)
        self.assertIs(result['satisfied'], True)
        self.assertEqual(result['state_readiness'], 'executable')
        witnesses = self.allocations(result)
        self.assertEqual(len(witnesses), 1)
        consumed = witnesses[0]['consumed']
        self.assertEqual(len(consumed), 2)
        self.assertEqual({row['resource_id'] for row in consumed}, {'entity:one'})
        self.assertEqual({row['source'] for row in consumed}, {initial.source, returned.source})
        self.assertEqual({tuple(row['slot']) for row in consumed},
                         {('availability:initial', 0), ('availability:returned', 0)})
        self.assertEqual(tuple(value.to_dict() for value in stock), frozen)

    def test_recovered_stock_and_aliases_do_not_duplicate_a_copy(self):
        returned = self.recovered()
        alias = replace(returned, selector='any-monster', selectors=('fixture-card',))
        one = solve_requirements(self.use('post_resolution'), (returned, alias), coverage=True)
        self.assertIs(one['satisfied'], True)
        self.assertTrue(all(len(branch['consumed']) == 1 for branch in self.allocations(one)))
        tree = ConditionGroup('all', (self.use('post_resolution'), self.use('post_resolution', 'any-monster')))
        result = solve_requirements(tree, (returned, alias), coverage=True)
        self.assertIs(result['satisfied'], False)
        self.assertTrue(result['conflicts'])
        for mode in ('consume', 'reusable'):
            demands = ConditionGroup('all', tuple(replace(condition, consume_mode=mode,
                                                          distinct_group='same-material-set')
                                                 for condition in tree.children))
            with self.subTest(mode=mode):
                self.assertIs(solve_requirements(demands, (returned, alias), coverage=True)['satisfied'], False)
                other = replace(returned, resource_id='entity:two', pool_id='availability:second-return',
                                source='fixture:explicit second recovered copy')
                complete = solve_requirements(demands, (returned, alias, other), coverage=True)
                self.assertIs(complete['satisfied'], True)
                for witness in self.allocations(complete):
                    self.assertEqual(len({tuple(row['slot']) for row in witness['matched_resources']}), 2)
                    self.assertEqual({row['resource_id'] for row in witness['matched_resources']},
                                     {'entity:one', 'entity:two'})

    def test_unknown_or_unobserved_recovery_keeps_the_result_unknown(self):
        tree = ConditionGroup('all', (self.use('activation'), self.use('post_resolution')))
        initial = self.initial()
        for stock, coverage in (((initial,), False), ((initial, self.recovered(known=False)), True)):
            with self.subTest(coverage=coverage, stock=stock):
                result = solve_requirements(tree, stock, coverage=coverage, state_provided=True)
                self.assertIsNone(result['satisfied'])
                self.assertEqual(result['state_readiness'], 'unknown')
                self.assertFalse(self.allocations(result))
                self.assertTrue(any(branch['residual_conditions'] for branch in result['branches']))
                self.assertTrue(all(row['source'] != self.recovered().source
                                    for branch in result['branches'] for row in branch['consumed']))
        missing = solve_requirements(tree, (initial,), coverage=True, state_provided=True)
        self.assertIs(missing['satisfied'], False)
        self.assertEqual(missing['state_readiness'], 'blocked')
        self.assertIs(solve_requirements(tree, (initial, self.recovered()), coverage=True)['satisfied'], True)

    def test_occupancy_release_and_retention_have_explicit_boundaries(self):
        stock = (replace(self.initial(), available_until='post_resolution'),)
        for mode, field in (('occupy', 'occupied'), ('retain', 'retained')):
            hold = replace(self.use('activation'), consume_mode=mode, until_stage='resolution')
            with self.subTest(mode=mode):
                during = ConditionGroup('all', (hold, self.use('resolution')))
                self.assertIs(solve_requirements(during, stock, coverage=True)['satisfied'], False)
                after = ConditionGroup('all', (hold, self.use('post_resolution')))
                result = solve_requirements(after, stock, coverage=True)
                self.assertIs(result['satisfied'], True)
                for witness in self.allocations(result):
                    self.assertEqual([(row['mode'], row['start'], row['end']) for row in witness[field]],
                                     [(mode, 1, 2)])
                    self.assertEqual(len(witness['consumed']), 1)
                    self.assertEqual(tuple(witness[field][0]['slot']), tuple(witness['consumed'][0]['slot']))
                self.assertIs(solve_requirements(after, (self.initial(),), coverage=True)['satisfied'], False)

    def test_recovery_does_not_reset_a_named_use_limit(self):
        first_limit = Resource('use_limit', 'effect-name', stage='activation',
                               available_until='post_resolution', resource_id='limit:effect-name',
                               pool_id='same-name:current-turn', source='fixture:one use per name')
        later_view = replace(first_limit, stage='post_resolution', source='fixture:same quota observed later')
        tree = ConditionGroup('all', (self.use('activation'),
            Condition('use_limit', 'effect-name', stage='activation'), self.use('post_resolution'),
            Condition('use_limit', 'effect-name', stage='post_resolution')))
        stock = (self.initial(), self.recovered(), first_limit, later_view)
        result = solve_requirements(tree, stock, coverage=True)
        self.assertIs(result['satisfied'], False)
        self.assertTrue(any(row['reason'] == 'RESOURCE_ALREADY_RESERVED'
                            for row in result['rejected_allocations']))
        second_name = replace(later_view, selector='independent-effect', resource_id='limit:other-name',
                              pool_id='other-name:current-turn', source='fixture:independent named quota')
        separate = replace(tree, children=tree.children[:-1] +
                           (replace(tree.children[-1], selector='independent-effect'),))
        complete = solve_requirements(separate, stock + (second_name,), coverage=True)
        self.assertIs(complete['satisfied'], True)
        for witness in self.allocations(complete):
            self.assertEqual(len(witness['consumed']), 4)
            self.assertEqual(len({tuple(row['slot']) for row in witness['consumed']}), 4)
            self.assertEqual({row['source'] for row in witness['consumed'] if row['selector'] == 'fixture-card'},
                             {self.initial().source, self.recovered().source})


if __name__ == '__main__':
    unittest.main()
