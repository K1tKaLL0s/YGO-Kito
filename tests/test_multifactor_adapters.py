"""Bounded engineering-only LoRA checks; random bases do not prove concepts."""

from pathlib import Path
import unittest

import torch

from ygo_kito.multifactor import FactorContractError
from ygo_kito.multifactor.adapters import AdapterConfig, base_binding
from ygo_kito.multifactor.network import NetworkConfig, encode_batch
from ygo_kito.multifactor.scoring import Candidate, CandidateScorer
from ygo_kito.multifactor.training import RoleTrainer, Supervision, Targets
from tests.multifactor_helpers import synthetic_example, task_temporary_directory


class MultifactorAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        self.example = synthetic_example()
        self.trainer = RoleTrainer(NetworkConfig(hidden_dim=16))
        self.targets = Targets(roles=(("package", (None, None, None, None, 1)),))
        self.source = Supervision("engineering_fixture", "LoRA code path only; no concept-learning claim")

    def logits(self, trainer=None):
        with torch.inference_mode():
            return (trainer or self.trainer).model(encode_batch((self.example,)))["role_logits"].clone()

    def update(self, trainer=None):
        return (trainer or self.trainer).train_supervised((self.example,), (self.targets,), (self.source,))

    def enable(self):
        self.trainer.enable_lora(engineering_mode=True)
        self.trainer.create_adapter("context-A", AdapterConfig(rank=2, alpha=2))

    def test_random_and_engineering_base_cannot_enter_normal_lora_adaptation(self):
        with self.assertRaisesRegex(FactorContractError, "supervised base"):
            self.trainer.enable_lora()
        self.assertIsNone(self.trainer.lora)
        self.update()
        with self.assertRaisesRegex(FactorContractError, "supervised base"):
            self.trainer.enable_lora()
        self.assertTrue(all(parameter.requires_grad for parameter in self.trainer.model.parameters()))

    def test_zero_delta_preserves_base_output_and_host_rng(self):
        logits, rng = self.logits(), torch.get_rng_state().clone()
        self.enable()
        self.assertTrue(torch.equal(rng, torch.get_rng_state()))
        self.assertTrue(torch.equal(logits, self.logits()))
        self.assertFalse(any(parameter.requires_grad for parameter in self.trainer.model.parameters()))

    def test_only_low_rank_parameters_change_and_random_base_stays_unverified(self):
        before = base_binding(self.trainer)
        self.enable()
        entry = self.trainer.lora.entries["context-A"]
        weights = {key: value.clone() for key, value in entry.deltas.state_dict().items()}
        self.update()
        self.update()
        self.assertEqual(base_binding(self.trainer), before)
        self.assertEqual(self.trainer.steps, 0)
        self.assertEqual(entry.steps, 2)
        self.assertTrue(any(not torch.equal(value, weights[key]) for key, value in entry.deltas.state_dict().items()))
        self.assertLess(sum(p.numel() for p in entry.deltas.parameters()), sum(p.numel() for p in self.trainer.model.parameters()))
        result = CandidateScorer(self.trainer).score_candidates((Candidate("case", self.example, "package", "synthetic gap"),), explain=False)[0]
        self.assertIsNone(result["advisory_score"])
        self.assertTrue(all(value is None for value in result["role_probabilities"].values()))

    def test_adapter_switches_and_disable_restore_exact_outputs(self):
        base = self.logits()
        self.enable()
        self.update()
        first = self.logits()
        self.assertFalse(torch.equal(first, base))
        self.trainer.create_adapter("context-B", AdapterConfig(rank=2, seed=141))
        self.assertTrue(torch.equal(self.logits(), base))
        self.trainer.activate_adapter("context-A")
        self.assertTrue(torch.equal(self.logits(), first))
        self.trainer.activate_adapter(None)
        self.assertTrue(torch.equal(self.logits(), base))
        with self.assertRaises(FactorContractError):
            self.update()

    def test_independent_adapter_weights_adam_cursor_and_next_update_resume(self):
        with task_temporary_directory() as directory:
            base, adapter = Path(directory) / "base.pt", Path(directory) / "adapter.pt"
            self.trainer.save(base)
            self.enable()
            self.update()
            self.trainer.save_adapter(adapter, "context-A", data_cursor="synthetic-context-A:1")
            payload = torch.load(adapter, weights_only=True)
            self.assertNotIn("model", payload)
            self.assertNotIn("base_weights", payload)
            restored = RoleTrainer.load(base)
            restored.load_adapter(adapter)
            self.assertEqual(restored.lora.entries["context-A"].data_cursor, "synthetic-context-A:1")
            self.assertTrue(torch.equal(self.logits(), self.logits(restored)))
            self.assertEqual(self.update(), self.update(restored))
            self.assertTrue(torch.equal(self.logits(), self.logits(restored)))
            self.assertEqual(restored.lora.entries["context-A"].data_digest, self.trainer.lora.entries["context-A"].data_digest)
            self.assertEqual(base_binding(restored), base_binding(self.trainer))

    def test_wrong_base_and_protocol_rejected_before_adapters_attached(self):
        self.enable()
        with task_temporary_directory() as directory:
            path = Path(directory) / "adapter.pt"
            self.trainer.save_adapter(path, "context-A")
            for other in (RoleTrainer(NetworkConfig(hidden_dim=16, seed=99)),
                          RoleTrainer(NetworkConfig(hidden_dim=16), label_protocol_sha256="0" * 64)):
                with self.assertRaisesRegex(FactorContractError, "binding differs"):
                    other.load_adapter(path)
                self.assertIsNone(other.lora)

    def test_engineering_adapter_cannot_acquire_real_provenance_or_be_saved_as_base(self):
        self.enable()
        with self.assertRaisesRegex(FactorContractError, "engineering adapter"):
            self.trainer.train_supervised((self.example,), (self.targets,), (Supervision("human_feedback", "contract rejection test only"),))
        self.assertEqual(self.trainer.lora.entries["context-A"].steps, 0)
        with task_temporary_directory() as directory:
            with self.assertRaisesRegex(FactorContractError, "independently"):
                self.trainer.save(Path(directory) / "ambiguous-base.pt")

    def test_changed_frozen_base_invalidates_adapter_switch(self):
        self.enable()
        with torch.no_grad():
            next(self.trainer.model.parameters()).add_(0.01)
        with self.assertRaisesRegex(FactorContractError, "base changed"):
            self.trainer.activate_adapter(None)
        with self.assertRaisesRegex(FactorContractError, "base changed"):
            CandidateScorer(self.trainer).score_candidates((Candidate("case", self.example, "package", "synthetic"),), explain=False)


if __name__ == "__main__":
    unittest.main()
