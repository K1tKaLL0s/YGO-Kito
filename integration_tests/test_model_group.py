"""Actual native match after construction handoff, frozen prediction and recovery."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

from ygo_kito.agent_monitor import RunMonitor
from ygo_kito.build_contracts import BuildTask, digest
from ygo_kito.build_pipeline import BuildAssets
from ygo_kito.validation import ContractError, read_json

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"
HAS_TORCH = importlib.util.find_spec("torch") is not None
if HAS_TORCH:
    import torch
    from ygo_kito.duel_model import parameter_digest
    from ygo_kito.model_group import call, execute_duel_job, restore_group, run_model_group_smoke, save_group


@unittest.skipUnless(HAS_TORCH, "CPU Torch unavailable; group integration not passed")
class RealModelGroupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.state = Path(cls.temp.name)
        cls.task = BuildTask.from_dict(read_json(ROOT / "configs/build-engineering-v1.json"))
        cls.result = run_model_group_smoke(CACHE, cls.state, "real-model-group", cls.task)
        cls.run_directory = cls.state / "runs/real-model-group"
        cls.checkpoint = cls.run_directory / "checkpoints/group-before-duel.weights"
        cls.assets = BuildAssets(CACHE)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def restored(self, name):
        return restore_group(self.checkpoint, self.state / name, self.assets, self.result["binding"])

    def test_three_transformers_and_advisory_coordinator_complete_an_actual_native_workflow(self):
        r = self.result
        self.assertEqual(set(r["parameter_counts"]), {"duel", "build_goal", "build_optimizer", "coordinator"})
        self.assertEqual(r["canonical_optimizer_calls"], 7)
        self.assertEqual(r["canonical_evaluation_matches"], 1)
        self.assertEqual(r["physical_evaluation_matches_including_recovery"], 2)
        self.assertEqual(r["evaluation"]["result"]["source"], "real_engine")
        self.assertEqual(r["evaluation"]["status"]["matches"], 1)
        self.assertIn(r["evaluation"]["result"]["outcome"], ("win", "loss", "draw"))
        self.assertFalse(r["competitive_ability_validated"])
        self.assertEqual(r["statistical_calibration"], "pending")
        self.assertEqual(r["coordinator_supervision"]["source"], "synthetic_rule_imitation_and_probability_anchors")
        self.assertEqual(r["evaluation"]["stop_route"]["action"], "stop")

    def test_forecast_is_registered_before_allocating_and_reporting_versioned_duel(self):
        r = self.result
        events = [e["event"] for e in r["history"]]
        self.assertLess(events.index("prediction_registered_before_games"), events.index("duel_job_allocated"))
        self.assertEqual(r["forecast"]["scope"]["actor_policy_sha256"], r["model_hashes"]["duel"])
        self.assertEqual(r["forecast"]["model_sha256"], r["model_hashes"]["coordinator"])
        self.assertEqual(r["forecast"]["scope"]["unit"], "BO1")
        self.assertEqual(r["job"]["task_sha256"], self.task.sha256)
        self.assertEqual(r["job"]["deck"], r["construction"]["best_deck"])
        self.assertEqual(r["evaluation"]["status"]["checks"], [])  # One actual match cannot trigger 25+ checks.
        self.assertEqual(r["evaluation"]["status"]["alerts"], [])
        if r["evaluation"]["result"]["outcome"] == "loss":
            self.assertEqual(r["evaluation"]["result"]["diagnosis"], "unknown")

    def test_full_group_checkpoint_restores_four_models_optimizers_rng_job_and_sqlite(self):
        self.assertTrue(self.result["restore_verified"])
        group = self.restored("inspect-checkpoint")
        self.assertEqual(group["duel"].updates, 1)
        self.assertEqual(group["builder"].updates, {"build_goal": 2, "build_optimizer": 2})
        self.assertEqual(group["coordinator"].updates, 2)
        models = dict(group["builder"].models, duel=group["duel"].model, coordinator=group["coordinator"].model)
        for role, model in models.items():
            self.assertEqual(parameter_digest(model), self.result["model_hashes"][role])
        pointers = [{p.data_ptr() for p in m.parameters()} for m in models.values()]
        self.assertTrue(all(not (a & b) for i, a in enumerate(pointers) for b in pointers[i + 1:]))
        before = group["host"].forecast_status("group-forecast")
        self.assertEqual(before["matches"], 0)
        self.assertEqual(group["host"].state_digest(), self.result["checkpoint"]["ledger_state_sha256"])
        monitor = RunMonitor(self.state)
        self.assertTrue(monitor.checkpoint("real-model-group", "group-before-duel")["integrity_verified"])
        self.assertEqual(set(monitor.snapshot("real-model-group")["model_versions"]), set(models))

    def test_restore_rejects_wrong_binding_and_existing_destination_without_overwrite(self):
        with self.assertRaisesRegex(ContractError, "resources/implementation differs"):
            restore_group(self.checkpoint, self.state / "wrong-binding", self.assets,
                          dict(self.result["binding"], implementation_sha256="0" * 64))
        group = self.restored("one-time-recovery")
        with self.assertRaisesRegex(ContractError, "destination exists"):
            restore_group(self.checkpoint, self.state / "one-time-recovery", self.assets, self.result["binding"])
        self.assertEqual(group["host"].forecast_status("group-forecast")["matches"], 0)

    def test_wrong_driving_weights_fail_before_core_and_inflight_job_cannot_be_snapshotted(self):
        group = self.restored("wrong-driving-weights")
        with torch.no_grad():
            next(group["duel"].model.parameters()).add_(.01)
        cursor = dict(group["cursor"], task=group["task"])
        with self.assertRaisesRegex(ContractError, "binding differs"):
            execute_duel_job(group["host"], group["duel"], group["coordinator"], self.assets,
                             read_json(ROOT / "configs/effect-duel-v1.json"), cursor)
        self.assertEqual(group["host"].forecast_status("group-forecast")["matches"], 0)
        with self.assertRaisesRegex(ContractError, "in-flight"):
            save_group(self.state / "unsafe.weights", group["builder"], group["duel"], group["coordinator"], {}, group["host"],
                       self.task, self.assets, group["host"].policy, {}, group["cursor"])
