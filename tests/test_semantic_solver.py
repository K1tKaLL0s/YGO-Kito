"""Actual pinned SciPy solver, using explicitly synthetic public card facts."""
from copy import deepcopy
import unittest

from ygo_kito.build_contracts import BuildTask, DeckParts
from ygo_kito.build_semantics import solve_candidates,validate_counts
from ygo_kito.construction_logic import LogicTag
from tests.test_construction_binding import catalog, one_node


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

    def test_draft_completion_supplies_a_printed_search_target(self):
        task, assets = catalog()
        assets.rows[1]['desc'] = '①：自己主要阶段才能发动。从卡组把1只植物族怪兽加入手卡。'
        assets.rows[18]['race'] = 1024
        seed = DeckParts((1,))
        graph = one_node(LogicTag('effect', '检索'))

        unguided = solve_candidates(task, assets, candidate_count=1, skeleton=seed)
        self.assertNotIn(18, unguided['candidates'][0].main)
        result = solve_candidates(task, assets, candidate_count=5, skeleton=seed, draft_graph=graph)
        self.assertTrue(result['candidates'])
        self.assertLessEqual(result['solver_calls'], 5)
        self.assertTrue(all(18 in deck.main for deck in result['candidates']))
        for deck in result['candidates']:
            assets.validate(task, deck)

    def test_draft_prefers_supported_theme_cards_without_a_count_floor(self):
        task, assets = catalog()
        raw = task.to_dict()
        raw['goal']['constraints'].append({'id': 'requested-theme', 'zones': ['main'],
            'predicate': {'field': 'setcode', 'value': 385}, 'minimum': 1, 'maximum': 40})
        task = BuildTask.from_dict(raw)
        for row in assets.rows.values():
            row['desc'] = '①：这张卡召唤成功的场合才能发动。自己抽1张卡。'
        assets.rows[18]['setcode'] = 385
        graph = one_node(LogicTag('effect', '抽卡'))

        result = solve_candidates(task, assets, candidate_count=1, draft_graph=graph)
        deck = result['candidates'][0]
        assets.validate(task, deck)
        self.assertGreater(deck.main.count(18), 1)

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
