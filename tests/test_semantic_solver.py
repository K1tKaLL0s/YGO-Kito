"""Actual pinned SciPy solver, using explicitly synthetic public card facts."""
from copy import deepcopy
import unittest

from ygo_kito.build_contracts import BuildTask
from ygo_kito.build_semantics import solve_candidates,validate_counts
from tests.test_construction_binding import catalog


class SemanticSolverTests(unittest.TestCase):
    def test_from_scratch_solver_returns_independently_legal_lists(self):
        task,assets=catalog()
        result=solve_candidates(task,assets,seconds=2.,candidate_count=2)
        self.assertEqual(result['status'],'verified_list_candidates')
        self.assertGreater(result['solver_calls'],0)
        for deck in result['candidates']:
            assets.validate(task,deck)
            self.assertEqual(len(deck.main),40)
            self.assertEqual(validate_counts(task,deck,assets)[0]['actual'],40)

    def test_explicit_infeasibility_and_no_search_budget_are_different(self):
        task,assets=catalog()
        raw=task.to_dict();raw['goal']=deepcopy(raw['goal'])
        raw['goal']['constraints'].append({'id':'absent-race','zones':['main'],
            'predicate':{'field':'race_any','value':2},'minimum':1,'maximum':40})
        impossible=BuildTask.from_dict(raw)
        result=solve_candidates(impossible,assets,seconds=2.,candidate_count=1)
        self.assertEqual(result['status'],'infeasible_declared_list_constraints')
        self.assertEqual(result['candidates'],[])
        unknown=solve_candidates(impossible,assets,seconds=0.)
        self.assertEqual(unknown['status'],'not_found_within_budget')
        self.assertEqual(unknown['solver_calls'],0)
