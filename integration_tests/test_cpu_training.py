"""Real native games and actual CPU learning/recovery. No engine/policy mocks."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from ygo_kito.agent_bridge import AgentBridge
from ygo_kito.agent_monitor import RunMonitor
from ygo_kito.native import NativeError
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"
PROFILE = json.loads((ROOT / "configs/effect-duel-v1.json").read_text())
HAS_TORCH = importlib.util.find_spec("torch") is not None
if HAS_TORCH:
    import torch
    from ygo_kito.cpu_training import (CpuTrainingConfig, load_checkpoint,
                                       run_cpu_training_smoke, save_checkpoint)
    from ygo_kito.duel_model import parameter_digest


@unittest.skipUnless(HAS_TORCH, "optional CPU PyTorch unavailable; training integration not passed")
class RealCpuTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.state = Path(cls.temp.name)
        cls.result = run_cpu_training_smoke(CACHE, cls.state, "actual-cpu-proof", PROFILE)
        cls.run_directory = cls.state / "runs/actual-cpu-proof"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_real_terminal_games_produce_nonzero_policy_and_parameter_updates(self):
        result = self.result
        self.assertEqual(result["source"], "real-core-on-policy-parameter-updates")
        self.assertFalse(result["competitive_ability_validated"])
        self.assertEqual(result["canonical_updates"], 2)
        self.assertEqual(result["physical_optimizer_calls"], 3)
        self.assertEqual(result["models_in_this_run"], ["duel"])
        for episode, update in zip(result["episodes"], result["updates"]):
            self.assertEqual(episode["source"], "live-core-actor-seat")
            self.assertIn(episode["outcome"]["winner"], (0, 1, 2))
            self.assertGreater(episode["native_decisions"], episode["actor_samples"])
            self.assertGreater(update["changed_parameter_elements"], 0)
            self.assertGreater(update["gradient_norm_before_clip"], 0)
            self.assertGreater(update["policy_head_delta_l2"], 0)
            self.assertNotEqual(update["before_sha256"], update["after_sha256"])
            self.assertTrue(torch.isfinite(torch.tensor(update["loss"])))
        self.assertEqual(result["updates"][0]["after_sha256"], result["updates"][1]["before_sha256"])

    def test_actual_recovery_restores_optimizer_scheduler_rng_cursor_and_next_trajectory(self):
        self.assertTrue(self.result["restore_verified"])
        self.assertEqual(self.result["restored_second_trajectory_sha256"], self.result["episodes"][1]["trajectory_sha256"])
        trainers = [load_checkpoint(self.run_directory / f"checkpoints/step-{i}.weights", self.result["binding"]) for i in (1, 2)]
        for step, trainer in enumerate(trainers, 1):
            self.assertEqual(trainer.updates, step)
            self.assertEqual(trainer.episode_cursor, step)
            self.assertEqual(trainer.scheduler.last_epoch, step)
            self.assertTrue(trainer.optimizer.state)
            self.assertTrue(all(int(s["step"].item()) == step for s in trainer.optimizer.state.values()))
            self.assertEqual(parameter_digest(trainer.model), self.result["updates"][step - 1]["after_sha256"])
        self.assertFalse(torch.equal(trainers[0].policy_rng.get_state(), trainers[1].policy_rng.get_state()))
        self.assertFalse(torch.equal(trainers[0].batch_rng.get_state(), trainers[1].batch_rng.get_state()))
        wrong_binding = dict(self.result["binding"], profile_sha256="0" * 64)
        with self.assertRaisesRegex(ContractError, "resources differ"):
            load_checkpoint(self.run_directory / "checkpoints/step-1.weights", wrong_binding)

    def test_real_metrics_and_checkpoint_are_readable_through_existing_monitor_tools(self):
        bridge = AgentBridge(ROOT, self.state, CACHE, role="monitor")
        def call(method, params):
            response = bridge.dispatch({"schema_version": 1, "id": "read-proof", "method": method, "params": params})
            self.assertTrue(response["ok"], response)
            return response["result"]
        status = call("runs.read", {"run_id": "actual-cpu-proof"})
        self.assertEqual(status["source"], "trainer")
        self.assertEqual(status["state"], "completed")
        self.assertEqual(status["metrics"]["steps"], 2)
        self.assertGreater(status["metrics"]["process_peak_rss_bytes"], 0)
        checkpoint = call("checkpoints.read", {"run_id": "actual-cpu-proof", "checkpoint_id": "step-1"})
        self.assertTrue(checkpoint["integrity_verified"])
        self.assertFalse(checkpoint["deserialized"])
        self.assertFalse(call("capabilities", {})["training_backend_configured"])

    def test_same_run_or_checkpoint_cannot_overwrite_saved_evidence(self):
        before = (self.run_directory / "proof.json").read_bytes()
        with self.assertRaisesRegex(ContractError, "already exists"):
            run_cpu_training_smoke(CACHE, self.state, "actual-cpu-proof", PROFILE)
        path = self.run_directory / "checkpoints/step-2.weights"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        trainer = load_checkpoint(path, self.result["binding"])
        with self.assertRaises(FileExistsError):
            save_checkpoint(trainer, path.parent, "step-2", self.result["binding"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertEqual((self.run_directory / "proof.json").read_bytes(), before)

    def test_only_fresh_actor_seat_samples_can_update_and_old_rollout_is_rejected(self):
        trainer = load_checkpoint(self.run_directory / "checkpoints/step-1.weights", self.result["binding"])
        episode = trainer.sample_episode(CACHE, PROFILE)
        for step in episode["steps"]:
            request = step["request"]
            self.assertEqual(request.observation.observer, trainer.config.actor_seat)
            self.assertIsNone(request.context.seed)
            for card in request.observation.cards:
                self.assertNotEqual(card.zone, "deck")
                if card.visibility == "hidden":
                    self.assertIsNone(card.card_id)
                    self.assertIsNone(card.attack)
                    self.assertIsNone(card.defense)
                if card.visibility == "observer":
                    self.assertEqual(card.controller, trainer.config.actor_seat)
        initial = parameter_digest(trainer.model)
        for mutation in ({"source": "historical-replay"}, {"policy_version": 0}, {"policy_sha256": "0" * 64}):
            with self.assertRaisesRegex(ContractError, "stale/off-policy"):
                trainer.update(dict(episode, **mutation))
            self.assertEqual(parameter_digest(trainer.model), initial)
        trainer.update(episode)
        self.assertNotEqual(parameter_digest(trainer.model), initial)
        with self.assertRaisesRegex(ContractError, "stale/off-policy"):
            trainer.update(episode)

    def test_native_budget_failure_does_not_fabricate_terminal_reward_or_training_success(self):
        with self.assertRaisesRegex(NativeError, "budget exhausted"):
            run_cpu_training_smoke(CACHE, self.state, "budget-failure", PROFILE,
                                   CpuTrainingConfig(native_decision_limit=1))
        status = RunMonitor(self.state).snapshot("budget-failure")
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["metrics"]["steps"], 0)
        self.assertFalse(status["checkpoint_ids"])
        self.assertFalse((self.state / "runs/budget-failure/proof.json").exists())
