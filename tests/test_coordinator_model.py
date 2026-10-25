"""Learnable MLP engineering fixtures; synthetic targets are not real win rates."""

import copy
import importlib.util
import unittest

from ygo_kito.coord_contracts import ROUTES
from ygo_kito.validation import ContractError

HAS_TORCH = importlib.util.find_spec("torch") is not None
if HAS_TORCH:
    import torch
    from ygo_kito.coordinator_model import CoordinatorTrainer, context_tensor, engineering_examples
    from ygo_kito.duel_model import parameter_digest


@unittest.skipUnless(HAS_TORCH, "CPU Torch unavailable; coordinator model not passed")
class CoordinatorModelContractTests(unittest.TestCase):
    def test_actual_heads_update_and_restored_next_synthetic_update_is_identical(self):
        trainer = CoordinatorTrainer()
        data = engineering_examples()
        first = trainer.step(data)
        self.assertGreater(first["changed_parameter_elements"], 0)
        frozen = copy.deepcopy(trainer.state())
        expected = trainer.step(data)
        restored = CoordinatorTrainer.restore(frozen)
        actual = restored.step(data)
        self.assertEqual(actual, expected)
        self.assertEqual(parameter_digest(restored.model), parameter_digest(trainer.model))
        self.assertFalse(data["real_win_rate_supervision"])
        self.assertEqual(expected["calibration"], "pending")

    def test_advice_is_explicitly_uncalibrated_and_hidden_fields_fail_closed(self):
        trainer = CoordinatorTrainer()
        context = engineering_examples()["records"][3]["context"]
        advice = trainer.advice(context)
        self.assertIn(advice["route"], ROUTES)
        self.assertTrue(0 <= advice["probability"] <= 1)
        self.assertEqual(advice["mode"], "advisory_only")
        with self.assertRaises(ContractError):
            context_tensor(dict(context, opponent_private_hand=[123]))
        with self.assertRaises(ContractError):
            trainer.model(torch.tensor([[float("nan")] * 14]))

    def test_real_win_rate_claim_or_modified_synthetic_targets_are_not_accepted(self):
        trainer = CoordinatorTrainer()
        data = engineering_examples()
        data["source"] = "real-calibrated-win-rate-data"
        with self.assertRaises(ContractError):
            trainer.step(data)
