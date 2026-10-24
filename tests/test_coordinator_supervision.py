"""Explicit synthetic aggregate labels exercise actual CPU loss and restore.

Stage wiring isolates unrelated engine work with labelled fixtures. No live
engine, provider, process signal, or competitive-supervision claim is involved.
"""
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch
from torch.nn import functional as F

from ygo_kito import group_runner
from ygo_kito.build_contracts import digest
from ygo_kito.coordinator_model import CoordinatorTrainer, context_tensor, engineering_examples
from ygo_kito.coord_contracts import ROUTES
from ygo_kito.lora import AdapterConfig, AdapterSession, tensor_digest
from ygo_kito.lora_group import coordinator_loss
from ygo_kito.validation import ContractError, canonical_json, read_json

ROOT = Path(__file__).resolve().parents[1]


def synthetic_logged_examples(targets=(.25, None)):
    originals = engineering_examples()["records"]
    records = [{"context": deepcopy(originals[i]["context"]), "route_label": originals[i]["route_label"],
                "forecast_target": target,
                "provenance": {"dataset_id": "unit-synthetic-aggregate", "record_id": "record-" + str(i),
                               "source": "explicit-synthetic-fixture-not-real-matches", "evidence_sha256": "a" * 64}}
               for i, target in enumerate(targets)]
    return {"source": "host_logged_supervision_v1", "records": records,
            "real_win_rate_supervision": False, "sha256": digest(records)}


def adapter(model, max_updates=4):
    return AdapterSession(model, AdapterConfig("unit-coordinator", "coordinator",
        ("encoder.0", "encoder.2", "route_head", "forecast_head"), rank=1, max_updates=max_updates),
        {"base_version": "unit-synthetic", "feature_version": "unit-context", "context_sha256": "a" * 64})


class CoordinatorSupervisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="unit-coordinator-", dir=ROOT / "configs")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "supervision.json"
        self.examples = synthetic_logged_examples()
        self.write(self.examples)
        self.recipe = read_json(ROOT / "configs/group-runner-v1.json")
        self.recipe["coordinator_supervision"] = self.path.relative_to(ROOT).as_posix()

    def write(self, examples):
        self.path.write_text(canonical_json(examples) + "\n", encoding="utf-8")

    def test_recipe_inputs_load_and_validate_explicit_labels_and_preserve_default(self):
        base = read_json(ROOT / "configs/group-runner-v1.json")
        self.assertEqual(group_runner.coordinator_supervision(base), engineering_examples())
        validated = group_runner.validate_recipe(self.recipe)
        group_runner.inputs(validated)
        self.assertEqual(group_runner.coordinator_supervision(validated), self.examples)
        report = group_runner.coordinator_supervision_report(self.examples)
        self.assertEqual(report["forecast_supervised_rows"], 1)
        self.assertFalse(report["real_win_rate_supervision"])
        self.assertFalse(report["supervision_evidence_verified"])
        for path in ("outside.json", "configs/../outside.json", "/tmp/labels.json", None):
            with self.subTest(path=path), self.assertRaises(ContractError):
                group_runner.validate_recipe(dict(self.recipe, coordinator_supervision=path))
        malformed = deepcopy(self.examples)
        malformed["real_win_rate_supervision"] = True
        self.write(malformed)
        for load in (group_runner.validate_recipe, group_runner.inputs):
            with self.assertRaises(ContractError): load(self.recipe)

    def test_content_binding_changes_when_same_named_supervision_file_changes(self):
        profiles, cfg, task, _, _ = group_runner.inputs(self.recipe)
        from dataclasses import asdict
        row = {"recipe": self.recipe, "profile": profiles["train"], "validation_profile": profiles["validation"],
               "config": asdict(cfg), "task": task.to_dict(), "feedback_policy": {"fixture": True}}
        with patch("ygo_kito.cpu_training.resource_binding", return_value={"resource": "static-test-fixture"}):
            before = group_runner.binding_for(ROOT / ".cache", row)
            self.assertEqual(before["coordinator_supervision_sha256"], digest(self.examples))
            self.assertEqual(before["coordinator_supervision_source"], self.examples["source"])
            changed = synthetic_logged_examples((.9, None)); self.write(changed)
            after = group_runner.binding_for(ROOT / ".cache", row)
        self.assertNotEqual(before, after)
        self.assertEqual(before["runner_recipe_sha256"], after["runner_recipe_sha256"])

    def test_loss_uses_only_explicit_labelled_rows_and_keeps_default_loss(self):
        session = adapter(CoordinatorTrainer().model)
        rows = self.examples["records"]
        logits, forecasts = session.model(torch.tensor([context_tensor(r["context"]) for r in rows]))
        expected = F.cross_entropy(logits, torch.tensor([ROUTES.index(r["route_label"]) for r in rows]))
        expected = expected + F.mse_loss(forecasts[:1], torch.tensor([.25]))
        self.assertAlmostEqual(float(coordinator_loss(session, self.examples).detach()), float(expected.detach()), places=6)
        self.assertTrue(torch.isfinite(coordinator_loss(session)))

    def test_actual_cpu_adapter_restore_and_nullable_forecast_preserve_head_momentum(self):
        trainer = CoordinatorTrainer()
        trainer.step(self.examples)
        base = deepcopy(trainer.model)
        session = adapter(trainer.model)
        session.step(coordinator_loss(session, self.examples))
        forecast_names = [name for name in session.weights() if name.startswith("forecast_head.")]
        self.assertTrue(forecast_names)
        self.assertTrue(all(session.weights()[name] in session.optimizer.state for name in forecast_names))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "adapter.weights"
            receipt = session.save(path)
            restored = AdapterSession.load(base, path, session.compatibility(), receipt)
        unlabelled = synthetic_logged_examples((None, None))
        before = {name: session.weights()[name].detach().clone() for name in forecast_names}
        first = session.step(coordinator_loss(session, unlabelled))
        second = restored.step(coordinator_loss(restored, unlabelled))
        self.assertEqual(first, second)
        self.assertEqual(tensor_digest(session.weights()), tensor_digest(restored.weights()))
        self.assertTrue(all(torch.equal(before[name], session.weights()[name]) for name in forecast_names))
        self.assertTrue(all(session.weights()[name].grad is None for name in forecast_names))
        self.assertTrue(all(torch.equal(before[name], restored.weights()[name]) for name in forecast_names))

    def test_group_coordinator_stage_consumes_selected_targets_and_reports_source(self):
        session = adapter(CoordinatorTrainer().model)
        state = SimpleNamespace(row={"recipe": self.recipe}, phase="coordinator_train", consumed=[],
                                event_id=lambda: "cycle-1-coordinator_train", sessions={"coordinator": session},
                                coordinator_examples=self.examples)
        result = group_runner.execute_stage(state, "unit-stage")
        self.assertEqual(result["supervision_sha256"], self.examples["sha256"])
        self.assertEqual(result["supervision_source"], "host_logged_supervision_v1")
        self.assertEqual(result["forecast_supervised_rows"], 1)
        self.assertEqual(session.updates, 1)
        self.assertTrue(result["rule_authority"])
        self.assertFalse(result["real_win_rate_supervision"])

    def test_bootstrap_wiring_uses_same_explicit_supervision_with_engine_work_isolated(self):
        # Only the coordinator below is trained; other stage work is a fixture.
        trainer = CoordinatorTrainer()
        data = {"source": "unit-construction-fixture"}
        duel = SimpleNamespace(sample_episode=lambda *a, **k: {"summary": {"fixture": True}},
                               update=lambda episode: {"fixture": True})
        state = SimpleNamespace(row={"recipe": self.recipe, "profile": {}}, phase="bootstrap", consumed=[],
            event_id=lambda: "bootstrap", builder=SimpleNamespace(step=lambda *a, **k: []), duel=duel,
            coordinator=trainer, coordinator_examples=self.examples, assets=SimpleNamespace(root=ROOT),
            construction_state=None, attach=lambda: None)
        with patch("ygo_kito.construction_curriculum.initialize", return_value=data), \
             patch("ygo_kito.construction_curriculum.consume"), patch("ygo_kito.group_runner.record_episode"):
            result = group_runner.execute_stage(state, "unit-bootstrap")
        update = result["updates"][-1]
        self.assertEqual(update["supervision_sha256"], self.examples["sha256"])
        self.assertEqual(update["supervision_source"], result["supervision_source"]["coordinator"])
        self.assertEqual(result["coordinator_supervision"]["forecast_supervised_rows"], 1)
        self.assertEqual(trainer.updates, 1)


if __name__ == "__main__":
    unittest.main()
