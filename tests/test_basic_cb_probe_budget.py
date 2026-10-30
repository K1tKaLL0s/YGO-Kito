"""Probe scheduling fixtures only; no native execution or model inference."""
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ygo_kito.basic_cb_inference import infer_basic_cb
from ygo_kito.route_search import discover_goal, shared_probe_seeds


class BasicCbProbeBudgetTests(unittest.TestCase):
    def test_shared_cursor_is_lazy_and_scope_restores_after_exit_or_failure(self):
        clock = [0.]
        task = SimpleNamespace(schema_version=3, pool=(1, 9), goal={
            'kind': 'xyz_summon', 'card_id': 9,
            'starting_conditions': {'requires_opening_hand': [1]}})
        assets = SimpleNamespace(rows={9: {'type': 0x800000}}, validate=lambda *args: None)
        deck = object()

        @contextmanager
        def fake_engine(assets, deck, seed, **kwargs):
            # One missing-hand probe outlasts this candidate's wall allowance.
            clock[0] += 2.
            yield SimpleNamespace(next_decision=lambda: None,
                                  _observation=lambda player: SimpleNamespace(cards=()))

        def probe(*, seconds=1., attempts=16):
            result = discover_goal(task, deck, assets, seconds=seconds, attempts=attempts)
            self.assertEqual(result['status'], 'not_run')
            self.assertEqual(result['exploration']['nodes_expanded'], 0)
            return [trial['seed_audit_only'] for trial in result['core_attempts']]

        with patch('ygo_kito.route_search.time.monotonic', side_effect=lambda: clock[0]), \
                patch('ygo_kito.extra_routes.goal_profile_for', return_value={}), \
                patch('ygo_kito.extra_routes.engine_for_goal', side_effect=fake_engine):
            with shared_probe_seeds():
                self.assertEqual(probe(), [7])
                self.assertEqual(probe(), [24])
            self.assertEqual(probe(seconds=10., attempts=3), [7, 24, 1724])
            with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
                with shared_probe_seeds():
                    self.assertEqual(probe(), [7])
                    raise RuntimeError('fixture failure')
            self.assertEqual(probe(), [7])

    def test_infer_keeps_ten_second_slice_deadline_family_order_and_not_run(self):
        task = SimpleNamespace(sha256='construction')
        deck = SimpleNamespace(main=(1,)*40,extra=(),side=(),
                               to_dict=lambda: {'main': [1] * 40, 'extra': [], 'side': []})
        assets = SimpleNamespace(rows={},validate=lambda *args: None)
        candidates = []
        for i in range(8):
            goal = {'route_goal': {'kind': 'fusion_summon' if i < 4 else 'xyz_summon'}}
            candidates.append(SimpleNamespace(sha256=str(i), goal=goal,
                                             to_dict=lambda i=i, goal=goal: {'id': i, 'goal': goal}))

        # Exercise the inference's own 20-second cap and a shorter shared budget.
        for deadline in (100., 13.):
            with self.subTest(cycle_deadline=deadline):
                clock, calls, checks = [0.], [], []

                def check(stage):
                    checks.append(stage)
                    return max(0., deadline - clock[0])

                budget = SimpleNamespace(check=check)

                def verifier(candidate, deck, assets, **limits):
                    remaining = min(20. - clock[0], deadline - clock[0])
                    self.assertEqual(limits['seconds'], min(10., remaining))
                    self.assertEqual((limits['attempts'], limits['decision_budget']), (16, 100))
                    calls.append((candidate.sha256, limits['seconds']))
                    clock[0] += 6. if limits['seconds'] >= 6. else limits['seconds'] / 2.
                    return {'status': 'not_run', 'native_route': {
                        'status': 'not_run', 'search_started': False,
                        'exploration': {'nodes_expanded': 0}}}

                with patch('ygo_kito.basic_cb_inference.proposals', return_value=candidates), \
                        patch('ygo_kito.basic_cb_inference.time.monotonic', side_effect=lambda: clock[0]):
                    result = infer_basic_cb(task, deck, assets, seconds=20., verifier=verifier, budget=budget)

                self.assertEqual(calls[0][1], 10.)
                self.assertEqual([ident for ident, _ in calls], ['0', '4', '1', '5', '2', '6', '3', '7'])
                self.assertLess(clock[0], min(20., deadline))
                self.assertEqual(checks.count('basic_cb_inference_start'), 1)
                self.assertEqual(checks.count('before_basic_cb_route'), len(calls))
                self.assertEqual(checks.count('after_basic_cb_route'), len(calls))
                self.assertEqual((result['status'], result['stop_reason']), ('not_run', 'no_action_expansion'))
                self.assertFalse(result['inference_completed'])
                self.assertEqual(result['routes'], [])


if __name__ == '__main__':
    unittest.main()
