import copy
from pathlib import Path
import tempfile
import unittest

import torch
from torch import nn

from ygo_kito.duel_model import parameter_digest
from ygo_kito.lora import AdapterConfig, AdapterSession, tensor_digest
from ygo_kito.validation import ContractError


class LoraTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(19)
        self.model = nn.Sequential(nn.Linear(6, 8), nn.Tanh(), nn.Linear(8, 4))
        self.base = copy.deepcopy(self.model)
        self.x, self.y = torch.randn(7, 6), torch.randn(7, 4)
        self.cfg = AdapterConfig("unit-adapter", "build_goal", ("0", "2"), rank=2)
        self.binding = {"base_version": "unit-v1", "feature_version": "unit-features", "context_sha256": "a" * 64}

    def test_real_update_frozen_base_disable_and_unload(self):
        base_hash = parameter_digest(self.model)
        expected = self.model(self.x).detach()
        s = AdapterSession(self.model, self.cfg, self.binding)
        self.assertTrue(torch.equal(self.model(self.x), expected))
        update = s.step(((self.model(self.x) - self.y) ** 2).mean())
        self.assertGreater(update["changed_adapter_elements"], 0)
        self.assertEqual(update["base_sha256_after"], base_hash)
        self.assertFalse(torch.equal(self.model(self.x), expected))
        s.set_enabled(False)
        self.assertTrue(torch.equal(self.model(self.x), expected))
        with self.assertRaises(ContractError):
            s.step(((self.model(self.x) - self.y) ** 2).mean())
        s.set_enabled(True)
        with s.suspended():
            self.assertEqual(parameter_digest(self.model), base_hash)
            self.assertTrue(torch.equal(self.model(self.x), expected))
        self.assertFalse(torch.equal(self.model(self.x), expected))
        self.assertEqual(s.unload(), base_hash)
        self.assertTrue(torch.equal(self.model(self.x), expected))

    def test_artifact_actual_next_update_and_rng_recovery(self):
        s = AdapterSession(self.model, self.cfg, self.binding)
        s.rng.set_state(torch.Generator().manual_seed(45).get_state())
        s.step(((self.model(self.x) - self.y) ** 2).mean())
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "adapter.weights"
            receipt = s.save(p)
            state = torch.load(p, weights_only=True)
            self.assertNotIn("base", state)
            self.assertFalse(receipt["contains_base_weights"])
            restored = AdapterSession.load(self.base, p, s.compatibility(), receipt)
            self.assertTrue(torch.equal(torch.randperm(7, generator=s.rng), torch.randperm(7, generator=restored.rng)))
            a = s.step(((self.model(self.x) - self.y) ** 2).mean())
            b = restored.step(((self.base(self.x) - self.y) ** 2).mean())
            self.assertEqual(a, b)
            self.assertEqual(tensor_digest(s.weights()), tensor_digest(restored.weights()))
            self.assertEqual(parameter_digest(s.model), parameter_digest(restored.model))
            with self.assertRaises(ContractError):
                s.save(p)
            with self.assertRaises(ContractError):
                AdapterSession.load(copy.deepcopy(nn.Sequential(nn.Linear(6, 8), nn.Tanh(), nn.Linear(8, 4))), p, s.compatibility(), receipt)
            p.write_bytes(p.read_bytes()[:-5])
            with self.assertRaises(ContractError):
                AdapterSession.load(nn.Sequential(), p, s.compatibility(), receipt)

    def test_incompatible_role_context_version_and_target_are_rejected(self):
        s = AdapterSession(self.model, self.cfg, self.binding)
        state, expected = s.state(), s.compatibility()
        for key, value in (("base_sha256", "b" * 64), ("binding", dict(self.binding, base_version="other"))):
            altered = copy.deepcopy(state)
            altered["compatibility"][key] = value
            with self.assertRaises(ContractError):
                AdapterSession.restore(copy.deepcopy(self.base), altered, expected)
        wrong = copy.deepcopy(state)
        wrong["compatibility"]["config"]["role"] = "duel"
        with self.assertRaises(ContractError):
            AdapterSession.restore(copy.deepcopy(self.base), wrong, expected)
        bad = copy.deepcopy(state)
        bad["weights"]["0.a"][0, 0] = float("nan")
        bad["weights_sha256"] = tensor_digest(bad["weights"])
        intact = copy.deepcopy(self.base)
        with self.assertRaises(ContractError):
            AdapterSession.restore(intact, bad, expected)
        self.assertEqual(parameter_digest(intact), parameter_digest(self.base))
        with self.assertRaises(ContractError):
            AdapterSession(self.model, self.cfg, self.binding)
        with self.assertRaises(ContractError):
            AdapterSession(copy.deepcopy(self.base), AdapterConfig("bad-target", "duel", ("missing",)), self.binding)

    def test_frozen_weight_or_gradient_tampering_fails_closed(self):
        s = AdapterSession(self.model, self.cfg, self.binding)
        original = next(iter(s.base_parameters.values()))
        original.grad = torch.zeros_like(original)
        with self.assertRaises(ContractError):
            s.verify_base()
        original.grad = None
        with torch.no_grad():
            original.flatten()[0] += 1
        with self.assertRaises(ContractError):
            s.verify_base()


if __name__ == "__main__":
    unittest.main()
