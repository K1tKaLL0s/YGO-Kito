"""Q4 inference mechanics on engineering fixtures; never train or update."""
from copy import deepcopy
from dataclasses import replace
import math
import unittest
from unittest.mock import patch

import torch

from ygo_kito.multifactor import DeckSpec, FunctionSeed, build_analysis_graph
from ygo_kito.multifactor.contracts import TASK_DOMAINS
from ygo_kito.multifactor.graph_training import compile_records
from ygo_kito.multifactor.network import encode_batch
from ygo_kito.multifactor.scoring import CandidateScorer
from ygo_kito.multifactor.task_queries import iter_queries, observation_view, query_domain
from tests.test_multifactor_learning_v3 import build, config, record, trainer


class InferenceWithoutUpdatesTests(unittest.TestCase):
    def snapshot(self, current):
        self.assertTrue(all(value.device.type == 'cpu' for value in current.model.parameters()))
        return dict(parameters={key: value.detach().clone() for key, value in current.model.state_dict().items()},
                    optimizer=deepcopy(current.optimizer.state_dict()), updates=deepcopy(current.updates),
                    steps=current.steps, training=current.model.training)

    def assert_unchanged(self, current, before):
        self.assertEqual(current.steps, before['steps'])
        self.assertEqual(current.updates, before['updates'])
        self.assertEqual(current.optimizer.state_dict(), before['optimizer'])
        self.assertEqual(current.model.training, before['training'])
        for key, value in current.model.state_dict().items():
            torch.testing.assert_close(value, before['parameters'][key], rtol=0, atol=0)

    def test_training_queries_do_not_change_inference_tensors_or_natural_domain(self):
        observed = build()
        source = observed.candidates.candidates[0]
        injected = replace(source, members=(('card:1', 1), ('card:3', 1)))
        row = record([('axis_membership', (injected.candidate_id, 'card:3'), 'member', 1)])
        row['supervision']['training_queries'] = [dict(source_candidate_ref=source.candidate_id,
                                                      members=[['card:1', 1], ['card:3', 1]])]
        original = deepcopy(row)
        normal = encode_batch((row,), config=config())
        training_view = encode_batch((row,), config=config(), training=True)
        for key, value in normal.items():
            if isinstance(value, torch.Tensor):
                torch.testing.assert_close(value, training_view[key], rtol=0, atol=0)
        self.assertNotIn(injected.candidate_id, normal['domains'][0]['axes'])
        self.assertIn(injected.candidate_id, training_view['domains'][0]['axes'])
        self.assertEqual(row, original)

    def test_missing_natural_axis_remains_known_without_an_inference_query(self):
        row = record([('axis_membership', ('gold-axis-not-recalled', 'card:3'), 'member', 1)])
        current = trainer()
        before = self.snapshot(current)
        compiled, diagnostics = compile_records(current, [row])
        self.assertEqual(compiled, [])
        self.assertEqual(diagnostics['unrepresented_candidate_cells'], 1)
        encoded = encode_batch((row,), config=config())
        self.assertNotIn('gold-axis-not-recalled', encoded['domains'][0]['axes'])
        self.assertEqual(row['targets']['task_labels'][0]['cells']['member']['status'], 'known')
        self.assertEqual(current.steps, 0)
        self.assertFalse(current.optimizer.state)
        self.assertTrue(all(count == 0 for counts in current.updates.values() for count in counts.values()))
        self.assert_unchanged(current, before)

    def test_real_graph_scoring_streams_full_domains_without_updates(self):
        observed = build()
        seeds = tuple(FunctionSeed('scope:' + str(index), (('card:1', 1), ('card:2', 1)), ('search',))
                      for index in range(40))
        observed = build_analysis_graph(observed.input, function_seeds=seeds)
        domain = query_domain(*observation_view(observed))
        current = trainer()
        before = self.snapshot(current)
        scorer = CandidateScorer(current)
        # Engineering eligibility only: no training counts or capability publication.
        with patch.object(current, 'head_status', return_value='trained_uncalibrated'):
            for task in ('axis_function', 'axis_membership'):
                expected = list(iter_queries(domain, task))
                self.assertGreater(len(expected), 32)
                real_scores = current.model.score_queries
                with patch.object(current.model, 'score_queries', wraps=real_scores) as query_calls:
                    result = scorer.score_graph(observed, task=task)
                actual = [(row['task'], tuple(row['subject']), row['coordinate']) for row in result['raw_prediction']]
                self.assertEqual(set(actual), set(expected))
                self.assertEqual(len(actual), len(expected))
                sizes = [len(call.args[2]) for call in query_calls.call_args_list]
                self.assertGreater(len(sizes), 1)
                self.assertEqual(sum(sizes), len(expected))
                self.assertTrue(all(0 < size <= 32 for size in sizes))
                self.assertTrue(all(math.isfinite(row['value']) and 0 <= row['value'] <= 1
                                    for row in result['raw_prediction']))
                self.assertEqual(result['calibrated_scores'], ())
                self.assertEqual(result['applied_prediction'], ())
                if task == 'axis_membership':
                    candidate = observed.candidates.candidates[0]
                    self.assertNotIn('card:3', dict(candidate.members))
                    self.assertIn((task, (candidate.candidate_id, 'card:3'), 'member'), actual)
                self.assert_unchanged(current, before)

    def test_real_copy_scoring_observes_both_configurations_without_updates(self):
        left = build()
        right_input = replace(left.input, deck=DeckSpec(((1, 2), (2, 1), (4, 1)), (), ()))
        right = build_analysis_graph(right_input,
            function_seeds=(FunctionSeed('observed-search', (('card:1', 1), ('card:2', 1)), ('search',)),))
        self.assertIn(3, dict(left.input.deck.main))
        self.assertNotIn(3, dict(right.input.deck.main))
        self.assertNotIn(4, dict(left.input.deck.main))
        self.assertIn(4, dict(right.input.deck.main))
        operation = dict(kind='replacement', add=dict(card_id=4, section='main', quantity=1),
                         remove=dict(card_id=3, section='main', quantity=1))
        calls = []

        def engineering_calibrator(task, raw):
            calls.append((task, deepcopy(raw)))
            return dict(calibrated_scores=(), applied_prediction=())

        current = trainer()
        scorer = CandidateScorer(current, calibrator=engineering_calibrator)
        with patch.object(current, 'head_status', return_value='trained_uncalibrated'):
            for prior_mode in (True, False):
                current.model.train(prior_mode)
                before = self.snapshot(current)
                result = scorer.score_copy_graphs(left, right, operation=operation)
                self.assertEqual(len(result['raw_prediction']), 1)
                raw = result['raw_prediction'][0]
                self.assertEqual(raw['task'], 'copy_preference')
                self.assertEqual(raw['subject'], ['query:unit', 'query:unit'])
                self.assertEqual(set(raw['value']), set(TASK_DOMAINS['copy_preference']))
                self.assertTrue(all(math.isfinite(value) and 0 <= value <= 1 for value in raw['value'].values()))
                self.assertAlmostEqual(sum(raw['value'].values()), 1, places=6)
                self.assertEqual(result['calibrated_scores'], ())
                self.assertEqual(result['applied_prediction'], ())
                self.assert_unchanged(current, before)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(task == 'copy_preference' and len(raw) == 1 for task, raw in calls))


if __name__ == '__main__':
    unittest.main()
