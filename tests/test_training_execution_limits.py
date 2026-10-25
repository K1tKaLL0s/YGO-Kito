"""CPU update budgets and explicit logged targets; no core trajectory is forged."""
from copy import deepcopy
import unittest

import torch

from ygo_kito.build_contracts import digest
from ygo_kito.build_training import BuildTrainingConfig
from ygo_kito.coordinator_model import CoordinatorModelConfig, CoordinatorTrainer, engineering_examples
from ygo_kito.lora_group import normalize_advantages
from ygo_kito.validation import ContractError


def logged_examples(*, forecast=True):
    record = engineering_examples()["records"][0]
    rows = [{"context": deepcopy(record["context"]), "route_label": record["route_label"],
             "forecast_target": .25 if forecast else None,
             "provenance": {"dataset_id": "logged-fixture", "record_id": "aggregate-1",
                            "source": "explicit-synthetic-log-fixture", "evidence_sha256": "a" * 64}}]
    return {"source": "host_logged_supervision_v1", "records": rows,
            "real_win_rate_supervision": False, "sha256": digest(rows)}


class TrainingExecutionLimitTests(unittest.TestCase):
    def test_bounded_update_counts_are_configurable_and_defaults_remain_two(self):
        self.assertEqual(BuildTrainingConfig().batches, 2)
        self.assertEqual(CoordinatorModelConfig().steps, 2)
        for count in (1, 3, 100000):
            self.assertEqual(BuildTrainingConfig(batches=count).batches, count)
            self.assertEqual(CoordinatorModelConfig(steps=count).steps, count)
        for count in (True, 0, 100001):
            with self.assertRaises(ContractError): BuildTrainingConfig(batches=count)
            with self.assertRaises(ContractError): CoordinatorModelConfig(steps=count)

    def test_explicit_logged_targets_train_restore_and_continue_past_two_steps(self):
        trainer = CoordinatorTrainer(CoordinatorModelConfig(steps=4))
        data = logged_examples()
        first = trainer.step(data)
        self.assertNotEqual(first["before_sha256"], first["after_sha256"])
        self.assertEqual(first["supervision_sha256"], data["sha256"])
        self.assertEqual(first["supervision_source"], "host_logged_supervision_v1")
        self.assertFalse(first["supervision_evidence_verified"])
        self.assertFalse(first["real_win_rate_supervision"])
        self.assertIsNone(first["synthetic_forecast_loss"])
        trainer.step(data)
        state = deepcopy(trainer.state())
        restored = CoordinatorTrainer.restore(state)
        self.assertEqual(trainer.step(data), restored.step(data))
        trainer.step(data)
        with self.assertRaisesRegex(ContractError, "budget"):
            trainer.step(data)

    def test_missing_forecast_target_does_not_train_forecast_head_or_invent_anchor(self):
        trainer = CoordinatorTrainer(CoordinatorModelConfig(steps=3))
        trainer.step(logged_examples())  # Populate optimizer momentum for the forecast head.
        before = {name: value.detach().clone() for name, value in trainer.model.forecast_head.named_parameters()}
        result = trainer.step(logged_examples(forecast=False))
        self.assertEqual(result["forecast_supervised_rows"], 0)
        self.assertIsNone(result["forecast_loss"])
        self.assertTrue(all(torch.equal(value, before[name]) for name, value in trainer.model.forecast_head.named_parameters()))

    def test_bad_logged_data_cannot_relabel_itself_as_verified_real_supervision(self):
        for mutate in (lambda data: data.update(real_win_rate_supervision=True),
                       lambda data: data["records"][0]["context"].update(opponent_private_hand=[123]),
                       lambda data: data["records"][0]["provenance"].update(evidence_sha256="bad"),
                       lambda data: data["records"].append(deepcopy(data["records"][0]))):
            data = logged_examples()
            mutate(data)
            data["sha256"] = digest(data["records"])
            with self.assertRaises(ContractError): CoordinatorTrainer().step(data)
        data = logged_examples(); data["records"][0]["forecast_target"] = .9
        with self.assertRaises(ContractError): CoordinatorTrainer().step(data)

    def test_single_advantage_preserves_its_signal_and_derivative_without_an_episode(self):
        single = torch.tensor([2.5], requires_grad=True)
        normalized = normalize_advantages(single)
        self.assertEqual(normalized.tolist(), [2.5])
        normalized.sum().backward()
        self.assertEqual(single.grad.tolist(), [1.0])
        multi = normalize_advantages(torch.tensor([1., 2., 3.]))
        self.assertAlmostEqual(float(multi.mean()), 0., places=6)
        self.assertAlmostEqual(float(multi.std(unbiased=False)), 1., places=6)
        for invalid in (torch.tensor([]), torch.tensor([[1.]]), torch.tensor([float("nan")])):
            with self.assertRaises(ContractError): normalize_advantages(invalid)


if __name__ == "__main__":
    unittest.main()
