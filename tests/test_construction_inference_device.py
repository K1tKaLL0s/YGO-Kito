"""Explicit invocation device and observed inference, independent of training restore."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch

from scripts.run_construction import prepare_inference_device
from ygo_kito.validation import ContractError


class InferenceDeviceTests(unittest.TestCase):
    def test_host_candidate_budget_preserves_pool_and_binds_resume(self):
        from tests.test_autonomous_construction import fixture
        from ygo_kito.autonomous_construction import AutonomousConstructionKernel
        task, assets, builder, coordinator = fixture()
        options = dict(assets=assets, host_available_ids=assets.rows, allowed_theme_ids=('setcode-2c3',))
        small = AutonomousConstructionKernel(builder, coordinator, source_binding={'construction_candidate_budget': 2}, **options)
        larger = AutonomousConstructionKernel(builder, coordinator, source_binding={'construction_candidate_budget': 3}, **options)
        theme = small.enumerate_themes()[0]
        a = small._task(theme, small.task_ids, None)
        b = larger._task(theme, larger.task_ids, None)
        self.assertEqual(a.candidate_budget, 2)
        self.assertEqual(b.candidate_budget, 3)
        self.assertEqual(a.pool, b.pool)
        self.assertEqual(len(a.pool), len(assets.rows))
        self.assertEqual(a.goal, b.goal)
        with self.assertRaises(ContractError):
            larger.load_state_dict(small.state_dict())
        with self.assertRaises(ContractError):
            AutonomousConstructionKernel(builder, coordinator, source_binding={'construction_candidate_budget': 1}, **options)

    def bundle(self):
        model = torch.nn.Linear(2, 1)
        trainers = [SimpleNamespace(device=torch.device('cpu')) for _ in range(3)]
        bundle = SimpleNamespace(device=torch.device('cpu'), builder=trainers[0],
            duel=trainers[1], coordinator=trainers[2],
            kernel=SimpleNamespace(adapters={'saved': SimpleNamespace(device=torch.device('cpu'))}),
            models=lambda: {'build_goal': model})
        return bundle, model

    def test_cpu_observation_preserves_weights_and_counts_real_forward(self):
        bundle, model = self.bundle()
        before = {key: value.clone() for key, value in model.state_dict().items()}
        receipt = prepare_inference_device(bundle, 'cpu')
        with torch.no_grad():
            model(torch.ones(1, 2))
        self.assertEqual(receipt['roles']['build_goal']['forward_calls'], 1)
        self.assertEqual(receipt['roles']['build_goal']['output_devices'], ['cpu'])
        self.assertFalse(receipt['training_checkpoint_migrated'])
        for key, value in model.state_dict().items():
            torch.testing.assert_close(before[key], value, rtol=0, atol=0)

    def test_unavailable_cuda_does_not_fall_back_or_change_bundle(self):
        bundle, model = self.bundle()
        with patch('torch.cuda.is_available', return_value=False):
            with self.assertRaises(ContractError):
                prepare_inference_device(bundle, 'cuda:0')
        self.assertEqual(str(bundle.device), 'cpu')
        self.assertEqual(str(next(model.parameters()).device), 'cpu')

    def test_nested_outputs_are_checked_and_nonfinite_values_rejected(self):
        bundle, linear = self.bundle()
        class MultipleHeads(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.head = linear
            def forward(self, inputs):
                value = self.head(inputs)
                return value, {'forecast': value.sigmoid()}
        model = MultipleHeads()
        bundle.models = lambda: {'coordinator': model}
        receipt = prepare_inference_device(bundle, 'cpu')
        model(torch.ones(1, 2))
        self.assertEqual(receipt['roles']['coordinator']['forward_calls'], 1)
        with self.assertRaisesRegex(RuntimeError, 'nonfinite'):
            model(torch.full((1, 2), float('nan')))


if __name__ == '__main__':
    unittest.main()
