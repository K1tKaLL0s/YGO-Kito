"""Requirement-tree tests: all/any/at_least_k/not, stock consumption and zones."""
import unittest
import json

from ygo_kito.multifactor import (
    Condition, ConditionGroup, FactorContractError, Resource, SolverBudget, solve_requirements as _solve,
)


def solve_requirements(tree, stock):
    # These fixtures explicitly enumerate the entire stock being evaluated.
    return _solve(tree, stock, coverage=True)


def card(selector, quantity=1, **kwargs):
    return Resource("card", selector, quantity, **kwargs)


class RequirementTreeTests(unittest.TestCase):
    def test_static_state_conserves_entities_through_split_clearance_and_return(self):
        def move(origin, destination):
            return Condition('card', 'A', consume_mode='reusable', state_origins=(origin,),
                             state_destination=destination)
        absent = Condition('card', 'A', consume_mode='reusable', state_origins=('grave',), state_absent=True)
        stock = (card('A', 2, initial_zones=('deck',)),)
        produced = (move('deck', 'grave'), move('deck', 'grave'))
        self.assertFalse(solve_requirements(ConditionGroup('all', (*produced, move('grave', 'banished'), absent)), stock)['satisfied'])
        self.assertTrue(solve_requirements(ConditionGroup('all', (*produced, move('grave', 'banished'),
            move('grave', 'banished'), absent)), stock)['satisfied'])
        sequence = (move('deck', 'grave'), move('grave', 'deck'), move('deck', 'grave'), move('grave', 'banished'), absent)
        self.assertTrue(solve_requirements(ConditionGroup('all', sequence),
            (card('A', initial_zones=('deck',)),))['satisfied'])

    def test_static_absence_constrains_unmoved_slots_and_is_branch_local(self):
        absent = Condition('card', 'A', consume_mode='reusable', state_origins=('grave',), state_absent=True)
        from_grave = Condition('card', 'A', consume_mode='reusable', state_origins=('grave',), state_destination='hand')
        stock = (card('A', initial_zones=('deck', 'grave')),)
        impossible = ConditionGroup('all', (absent, from_grave))
        self.assertFalse(solve_requirements(impossible, stock)['satisfied'])
        self.assertTrue(solve_requirements(ConditionGroup('any', (impossible, from_grave)), stock)['satisfied'])
        self.assertIsNone(solve_requirements(absent, (card('A'),))['satisfied'])

    def test_static_actor_binding_cannot_switch_to_another_copy_after_payment(self):
        source = Condition('card', 'A', consume_mode='reusable', state_origins=('field',), state_binding='actor')
        payment = Condition('card', 'A', consume_mode='reusable', state_origins=('field',),
            state_destination='grave', state_binding='actor')
        still_on_field = Condition('card', 'A', consume_mode='reusable', state_origins=('field',), state_binding='actor')
        self.assertFalse(solve_requirements(ConditionGroup('all', (source, payment, still_on_field)),
            (card('A', 2, initial_zones=('field',)),))['satisfied'])

    def test_generated_token_leaves_without_becoming_recoverable_stock(self):
        def move(origin, destination):
            return Condition('card', 'token', consume_mode='reusable', state_origins=(origin,), state_destination=destination)
        stock = (card('token', initial_zones=('uncreated',)),)
        tree = ConditionGroup('all', (move('uncreated', 'field'), move('field', 'grave'), move('grave', 'field')))
        self.assertFalse(solve_requirements(tree, stock)['satisfied'])

    def test_state_replacement_changes_future_destinations_and_preserves_existing_cards(self):
        move = Condition('card', 'A', consume_mode='reusable', state_origins=('deck',), state_destination='grave')
        rule = Condition('card', 'rule', consume_mode='reusable', state_destination_replace=('grave', 'banished'))
        absent = Condition('card', 'A', consume_mode='reusable', state_origins=('grave',), state_absent=True)
        stock = (card('A', initial_zones=('deck',)),)
        self.assertTrue(solve_requirements(ConditionGroup('all', (rule, move, absent)), stock)['satisfied'])
        self.assertFalse(solve_requirements(ConditionGroup('all', (move, rule, absent)), stock)['satisfied'])

    def test_static_state_contract_roundtrips_json_without_changing_allocation(self):
        import json
        from ygo_kito.multifactor.conditions import condition_from_dict, condition_to_dict
        tree = Condition('card', 'A', consume_mode='reusable', state_origins=('deck', 'hand'),
            state_destination='grave', state_binding='actor')
        stock = card('A', initial_zones=('deck', 'hand'))
        restored = condition_from_dict(json.loads(json.dumps(condition_to_dict(tree))))
        resource = Resource.from_dict(json.loads(json.dumps(stock.to_dict())))
        self.assertEqual(restored, tree)
        self.assertEqual(resource, stock)
        self.assertEqual(solve_requirements(restored, (resource,))['satisfied'], True)

    def test_all_and_missing(self):
        tree = ConditionGroup("all", (Condition("card", "A"), Condition("card", "B")))
        complete = solve_requirements(tree, (card("A"), card("B")))
        self.assertTrue(complete["satisfied"])
        self.assertEqual(complete["structural_status"], "complete")
        self.assertEqual(complete["state_readiness"], "unknown")
        partial = solve_requirements(tree, (card("A"),))
        self.assertFalse(partial["satisfied"])
        self.assertEqual(partial["structural_status"], "partial")
        self.assertTrue(partial["missing"])

    def test_terminal_fixed_matching_proves_shared_shortage_without_searching_alternatives(self):
        tree = ConditionGroup('all', (Condition('card', 'wide', 5),
            Condition('card', 'medium', 3), Condition('card', 'tight', 2)))
        stock = tuple(Resource('card', 'wide', selectors=('medium', 'tight') if i < 2 else
                               ('medium',) if i < 4 else (), pool_id=str(i)) for i in range(13))
        full = _solve(tree, stock, coverage=True, budget=SolverBudget(max_states=10000))
        bounded = SolverBudget(max_states=1, max_solutions=1)
        matched = _solve(tree, stock, coverage=True, budget=bounded, existential=True)
        self.assertIs(full['satisfied'], False)
        self.assertIs(matched['satisfied'], False)
        self.assertTrue(matched['conflicts'])
        self.assertEqual(matched['explored_states'], 1)
        self.assertIsNone(matched['continuation'])
        self.assertIsNone(_solve(tree, stock, budget=bounded, existential=True)['satisfied'])
        self.assertIsNone(_solve(tree, stock, coverage=True, budget=bounded,
                                 existential=True, should_stop=lambda: True)['satisfied'])

    def test_any_and_at_least_k_use_independent_branches(self):
        either = ConditionGroup("any", (Condition("card", "B"), Condition("card", "C")))
        self.assertTrue(solve_requirements(either, (card("C"),))["satisfied"])
        self.assertFalse(solve_requirements(either, (card("A"),))["satisfied"])
        two_of_three = ConditionGroup("at_least_k", (Condition("card", "B"), Condition("card", "C"),
                                                     Condition("card", "D")), min_count=2)
        self.assertTrue(solve_requirements(two_of_three, (card("B"), card("D")))["satisfied"])
        self.assertFalse(solve_requirements(two_of_three, (card("B"),))["satisfied"])

    def test_not_and_shared_consumption(self):
        absent = ConditionGroup("not", (Condition("card", "A", consume_mode="reusable"),))
        self.assertTrue(solve_requirements(absent, ())["satisfied"])
        self.assertFalse(solve_requirements(absent, (card("A"),))["satisfied"])
        two_copies = ConditionGroup("all", (Condition("card", "A"), Condition("card", "A")))
        self.assertFalse(solve_requirements(two_copies, (card("A", 1),))["satisfied"])
        self.assertTrue(solve_requirements(two_copies, (card("A", 2),))["satisfied"])

    def test_reusable_and_zone_matching(self):
        reusable = Resource("card", "A", 1, reusable=True)
        two_copies = ConditionGroup("all", (Condition("card", "A"), Condition("card", "A")))
        self.assertFalse(solve_requirements(two_copies, (reusable,))["satisfied"])
        two_observations = ConditionGroup("all", (Condition("card", "A", consume_mode="reusable"),
                                                  Condition("card", "A", consume_mode="reusable")))
        self.assertTrue(solve_requirements(two_observations, (reusable,))["satisfied"])
        in_extra = Condition("card", "A", deck_section="extra")
        self.assertFalse(solve_requirements(in_extra, (card("A", zone="main"),))["satisfied"])
        self.assertTrue(solve_requirements(in_extra, (card("A", zone="extra"),))["satisfied"])

    def test_invalid_tree_is_rejected(self):
        with self.assertRaises(FactorContractError):
            ConditionGroup("all", ())
        with self.assertRaises(FactorContractError):
            ConditionGroup("at_least_k", (Condition("card", "A"),), min_count=2)
        with self.assertRaises(FactorContractError):
            Condition("card", "A", stage="not_a_stage")
        with self.assertRaises(FactorContractError):
            solve_requirements("not-a-tree", ())


class ResumableAllocationTests(unittest.TestCase):
    def finish(self, tree, stock, *, coverage=True, states=1, solutions=1):
        expected = _solve(tree, stock, coverage=coverage,
            budget=SolverBudget(max_states=1000000, max_solutions=4096))
        self.assertTrue(expected['enumeration_complete'])
        progress, work, previous = None, 0, 0
        snapshots = []
        for _ in range(10000):
            value = _solve(tree, stock, coverage=coverage, continuation=progress,
                budget=SolverBudget(max_states=states, max_solutions=solutions))
            work += value['explored_states']
            self.assertEqual(value['total_explored_states'], work)
            self.assertGreaterEqual(len(value['branches']), previous)
            previous = len(value['branches'])
            if value['enumeration_complete']:
                break
            progress = json.loads(json.dumps(value['continuation']))
            snapshots.append(progress)
        else:
            self.fail('finite allocation did not finish')
        for key in ('branches', 'satisfied', 'missing', 'rejected_allocations', 'conflicts'):
            self.assertEqual(value[key], expected[key], key)
        self.assertEqual(work, expected['explored_states'])
        return value, snapshots

    def test_129_physical_alternatives_resume_after_solution_and_work_budgets(self):
        stock = tuple(card('A', pool_id=f'pool:{i}') for i in range(129))
        value, snapshots = self.finish(Condition('card', 'A'), stock, states=7, solutions=3)
        self.assertEqual(len(value['branches']), 129)
        self.assertGreater(len(snapshots), 1)
        self.assertEqual(len({tuple(b['consumed'][0]['slot']) for b in value['branches']}), 129)

    def test_all_any_at_least_k_keep_shared_reservations(self):
        either = ConditionGroup('any', (Condition('card', 'A'), Condition('card', 'B')))
        two = ConditionGroup('at_least_k', (Condition('card', 'A'), Condition('card', 'B'),
            Condition('card', 'C')), min_count=2)
        value, _ = self.finish(ConditionGroup('all', (either, two)),
            (card('A'), card('B'), card('C')))
        self.assertTrue(value['satisfied'])
        for branch in value['branches']:
            slots = [tuple(row['slot']) for row in branch['consumed']]
            self.assertEqual(len(slots), len(set(slots)))

    def test_negation_substack_resumes_unknown_then_refuting_witness(self):
        predicate = ConditionGroup('any', (
            Condition('card', 'unknown', consume_mode='reusable'),
            Condition('card', 'A', consume_mode='reusable')))
        value, snapshots = self.finish(ConditionGroup('not', (predicate,)),
            (card('unknown', known=False), card('A')))
        self.assertFalse(value['satisfied'])
        self.assertTrue(any(frame['kind'] == 'not' for saved in snapshots for frame in saved['stack']))

    def test_negation_preserves_unknown_incomplete_observation(self):
        tree = ConditionGroup('not', (Condition('card', 'A', consume_mode='reusable'),))
        value, _ = self.finish(tree, (), coverage=False)
        self.assertIsNone(value['satisfied'])
        self.assertEqual(value['branches'][0]['residual_conditions'][0]['reason'], 'NEGATION_UNKNOWN')

    def test_dynamic_zones_binding_replacement_and_return_survive_json(self):
        def move(origin, destination, binding=None):
            return Condition('card', 'A', consume_mode='reusable', state_origins=(origin,),
                state_destination=destination, state_binding=binding)
        absent = Condition('card', 'A', consume_mode='reusable', state_origins=('grave',), state_absent=True)
        rule = Condition('card', 'rule', consume_mode='reusable', state_destination_replace=('grave', 'banished'))
        sequence = (move('deck', 'grave', 'actor'), move('grave', 'deck', 'actor'),
            rule, move('deck', 'grave', 'actor'), absent)
        value, _ = self.finish(ConditionGroup('all', sequence),
            (card('A', 2, initial_zones=('deck',)),))
        self.assertTrue(value['satisfied'])
        self.assertEqual(len(value['branches']), 2)

    def test_random_identity_verdict_and_child_stack_survive_single_step_json(self):
        stock = (card('A', selectors=('all',), initial_zones=('deck',)),
                 card('B', selectors=('all',), initial_zones=('deck',)))
        mill = Condition('card', 'all', consume_mode='reusable', state_origins=('deck',),
            state_destination='grave', state_random=True)
        empty = Condition('card', 'all', consume_mode='reusable', state_origins=('grave',), state_absent=True)
        clear = Condition('card', 'A', consume_mode='reusable', state_origins=('grave',), state_destination='banished')
        from dataclasses import replace
        for children, expected in (((mill, empty), False), ((mill, clear, empty), None),
                                   ((mill, replace(clear, selector='all'), empty), True)):
            with self.subTest(expected=expected):
                value, snapshots = self.finish(ConditionGroup('all', children), stock)
                self.assertIs(value['satisfied'], expected)
                self.assertTrue(any(frame['kind'] == 'random' and frame['child']
                    for saved in snapshots for frame in saved['stack']))
                if expected is None:
                    self.assertEqual(value['branches'][0]['residual_conditions'][0]['reason'], 'RANDOM_IDENTITY_CONDITIONAL')
                if expected is True:
                    self.assertTrue(value['branches'][0]['matched_resources'][0]['random'])

    def test_excavated_set_allows_choice_and_leaves_unpicked_slots_in_deck(self):
        stock = (card('A', selectors=('all',), initial_zones=('deck',)),
                 card('B', 2, selectors=('all',), initial_zones=('deck',)))
        reveal = Condition('card', 'all', 2, consume_mode='reusable', state_origins=('deck',),
            state_binding='exposed', state_random=True)
        choose = Condition('card', 'B', consume_mode='reusable', state_origins=('deck',),
            state_destination='hand', state_binding='exposed')
        later = Condition('card', 'B', consume_mode='reusable', state_origins=('deck',),
            state_destination='grave', state_random=True)
        value, _ = self.finish(ConditionGroup('all', (reveal, choose, later)), stock)
        self.assertTrue(value['satisfied'])
        slots = value['branches'][0]['matched_resources']
        self.assertIn(slots[2]['slot'], [r['slot'] for r in slots[:2]])
        self.assertNotEqual(slots[2]['slot'], slots[3]['slot'])

    def test_explicit_destination_fails_under_replacement(self):
        from dataclasses import replace
        stock = (card('A', initial_zones=('deck',)),)
        redirect = Condition('card', 'rule', consume_mode='reusable', state_destination_replace=('grave', 'banished'))
        move = Condition('card', 'A', consume_mode='reusable', state_origins=('deck',), state_destination='grave',
            state_destination_required=True)
        self.assertFalse(solve_requirements(ConditionGroup('all', (redirect, move)), stock)['satisfied'])
        self.assertTrue(solve_requirements(ConditionGroup('all', (redirect, replace(move, state_destination_required=False))),
            stock)['satisfied'])

    def test_resume_rejects_changed_tree_stock_and_coverage(self):
        tree, stock = Condition('card', 'A'), (card('A', 2),)
        first = _solve(tree, stock, coverage=True, budget=SolverBudget(max_states=1))
        progress = json.loads(json.dumps(first['continuation']))
        for other_tree, other_stock, coverage in ((Condition('card', 'B'), stock, True),
                (tree, (card('A'),), True), (tree, stock, False)):
            with self.subTest(coverage=coverage, tree=other_tree, stock=other_stock):
                with self.assertRaisesRegex(FactorContractError, 'different inputs'):
                    _solve(other_tree, other_stock, coverage=coverage, continuation=progress)

    def test_stop_before_work_keeps_exact_next_frame(self):
        tree, stock = Condition('card', 'A'), (card('A'),)
        first = _solve(tree, stock, coverage=True, should_stop=lambda: True)
        self.assertEqual(first['explored_states'], 0)
        self.assertIsNone(first['satisfied'])
        resumed = _solve(tree, stock, coverage=True, continuation=json.loads(json.dumps(first['continuation'])))
        full = _solve(tree, stock, coverage=True)
        self.assertEqual(resumed, full)


if __name__ == "__main__":
    unittest.main()
