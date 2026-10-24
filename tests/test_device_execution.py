"""Real CPU execution/restore and unavailable-device rejection; not GPU proof."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import torch
from torch import nn

from ygo_kito.build_training import BuildTrainer, BuildTrainingConfig, binding_for, load_checkpoint as load_build, save_checkpoint as save_build
from ygo_kito.coordinator_model import CoordinatorTrainer, engineering_examples
from ygo_kito.cpu_training import CpuTrainer, CpuTrainingConfig, load_checkpoint as load_duel, save_checkpoint as save_duel
from ygo_kito.device import (capture_device_rng, checkpoint_device, checkpoint_execution, execution_metadata,
                            model_device, move_batch, optimizer_to, resolve_device, restore_device_rng)
from ygo_kito.duel_model import parameter_digest
from ygo_kito.lora import AdapterConfig, AdapterSession
from ygo_kito.validation import ContractError
from tests.test_construction_logic import fixture_assets


class DeviceExecutionTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_explicit_cpu_and_unavailable_cuda_never_silently_fall_back(self):
        self.assertEqual(str(resolve_device("cpu")), "cpu")
        self.assertEqual(execution_metadata("cpu"), {"schema_version": 1, "device": "cpu", "dtype": "float32"})
        for invalid in ("meta", "mps", "cpu:0", "not-a-device"):
            with self.subTest(device=invalid), self.assertRaises(ContractError):
                resolve_device(invalid)
        if not torch.cuda.is_available():
            state = torch.get_rng_state().clone()
            for constructor in (lambda: CpuTrainer(CpuTrainingConfig(), [1], device="cuda"),
                                lambda: CoordinatorTrainer(device="cuda")):
                with self.assertRaisesRegex(ContractError, "unavailable"):
                    constructor()
                self.assertTrue(torch.equal(state, torch.get_rng_state()))
        else:
            self.assertEqual(resolve_device("cuda").type, "cuda")  # Availability only; no CUDA numerical claim.

    def test_tensor_batch_migration_preserves_integer_masks_values_and_structure(self):
        batch = {"tokens": torch.tensor([[1, 2]], dtype=torch.long), "mask": torch.tensor([[True, False]]),
                 "nested": (torch.tensor([1.5]), {"identity": "DTO"})}
        moved = move_batch(batch, "cpu")
        self.assertIsNot(moved, batch)
        self.assertEqual(moved["tokens"].dtype, torch.long)
        self.assertEqual(moved["mask"].dtype, torch.bool)
        self.assertTrue(torch.equal(moved["nested"][0], batch["nested"][0]))
        self.assertEqual(moved["nested"][1]["identity"], "DTO")

    def test_checkpoint_execution_is_bound_and_metadata_cannot_lose_rng(self):
        self.assertEqual(str(checkpoint_device()), "cpu")
        for metadata in ({}, {"schema_version": True, "device": "cpu", "dtype": "float32"},
                         {"schema_version": 1, "device": "cpu", "dtype": "float16"}):
            with self.subTest(metadata=metadata), self.assertRaises(ContractError):
                checkpoint_device(metadata)
        for incomplete in ({"execution": execution_metadata("cpu")}, {"device_rng": capture_device_rng("cpu")}):
            with self.assertRaises(ContractError):
                checkpoint_execution(incomplete)
        with self.assertRaises(ContractError):
            checkpoint_device(execution_metadata("cpu"), "meta")
        rng = capture_device_rng("cpu")
        expected = torch.rand(4)
        restore_device_rng(rng, "cpu")
        self.assertTrue(torch.equal(expected, torch.rand(4)))
        with self.assertRaises(ContractError):
            restore_device_rng({"cpu": rng["cpu"], "cuda": torch.zeros(1, dtype=torch.uint8)}, "cpu")
        before = torch.get_rng_state().clone()
        with self.assertRaisesRegex(ContractError, "length"):
            restore_device_rng({"cpu": torch.zeros(3, dtype=torch.uint8), "cuda": None}, "cpu")
        self.assertTrue(torch.equal(before, torch.get_rng_state()))

    def test_duel_checkpoint_roundtrip_has_execution_rng_and_keeps_old_cpu_gate(self):
        trainer = CpuTrainer(CpuTrainingConfig(), [1, 2], device="cpu")
        with tempfile.TemporaryDirectory() as folder:
            path = save_duel(trainer, Path(folder), "initial", {"explicit": "CPU fixture"}, allow_initial=True)
            state = torch.load(path, weights_only=True)
            self.assertEqual(state["execution"]["device"], "cpu")
            self.assertIsNone(state["device_rng"]["cuda"])
            restored = load_duel(path, {"explicit": "CPU fixture"}, allow_initial=True, device="cpu")
            self.assertEqual(parameter_digest(restored.model), parameter_digest(trainer.model))
            state.pop("execution"); state.pop("device_rng")
            torch.save(state, path)
            old = load_duel(path, {"explicit": "CPU fixture"}, allow_initial=True)
            self.assertEqual(model_device(old.model), torch.device("cpu"))
            state["execution"] = execution_metadata("cpu")
            torch.save(state, path)
            with self.assertRaisesRegex(ContractError, "together"):
                load_duel(path, {"explicit": "CPU fixture"}, allow_initial=True)

    def test_build_initial_checkpoint_restores_both_roles_on_declared_device(self):
        task, assets = fixture_assets()
        assets.receipt = {"source_commits": {}, "resources": {}}
        trainer = BuildTrainer(task, assets, BuildTrainingConfig(), device="cpu")
        binding = binding_for(task, assets, {"supervision_sha256": "a" * 64})
        with tempfile.TemporaryDirectory() as folder:
            path = save_build(trainer, Path(folder), "initial", binding, allow_initial=True)
            restored = load_build(path, assets, binding, allow_initial=True, device="cpu")
            for role in trainer.models:
                self.assertEqual(model_device(restored.models[role]), torch.device("cpu"))
                self.assertEqual(parameter_digest(trainer.models[role]), parameter_digest(restored.models[role]))
            self.assertFalse({p.data_ptr() for p in restored.models["build_goal"].parameters()} &
                             {p.data_ptr() for p in restored.models["build_optimizer"].parameters()})

    def test_coordinator_and_lora_actual_cpu_next_update_restore(self):
        trainer = CoordinatorTrainer(device="cpu")
        trainer.step(engineering_examples())
        state = deepcopy(trainer.state())
        restored = CoordinatorTrainer.restore(state, device="cpu")
        first, second = trainer.step(engineering_examples()), restored.step(engineering_examples())
        self.assertEqual(first["after_sha256"], second["after_sha256"])
        model = nn.Sequential(nn.Linear(4, 4))
        original = deepcopy(model)
        adapter = AdapterSession(model, AdapterConfig("device-fixture", "duel", ("0",), rank=2),
                                 {"base_version": "device-fixture", "feature_version": "fixture", "context_sha256": "a" * 64})
        values = torch.ones(2, 4)
        adapter.step(model(values).square().mean())
        saved = deepcopy(adapter.state())
        copy = AdapterSession.restore(original, saved, adapter.compatibility())
        self.assertTrue(all(p.device == model_device(model) for p in adapter.parameters()))
        a, b = adapter.step(model(values).square().mean()), copy.step(original(values).square().mean())
        self.assertEqual(a["adapter_version"], b["adapter_version"])
        optimizer_to(copy.optimizer, torch.device("cpu"))
        self.assertTrue(all(value.device.type == "cpu" for state in copy.optimizer.state.values()
                            for value in state.values() if isinstance(value, torch.Tensor)))


if __name__ == "__main__":
    unittest.main()
