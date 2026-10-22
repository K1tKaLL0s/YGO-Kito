from contextlib import closing
from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import unittest

from ygo_kito.cpu_training import load_checkpoint
from ygo_kito.local_training import LocalCpuBackend, verified_trainer, _connect, get_row, put_row
from ygo_kito.runner_acceptance import run_runner_acceptance
from ygo_kito.training_runner import read_artifact
from ygo_kito.validation import ContractError, read_json

ROOT = Path(__file__).resolve().parents[1]


class RealMultiroundRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.proof = run_runner_acceptance(ROOT / ".cache", cls.root, "real-multiround",
                                          read_json(ROOT / "configs/cpu-runner-v1.json"))
        cls.state = cls.root / "experiments/real-multiround/host"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_four_actual_updates_periodic_validation_and_checkpoint_scheduling(self):
        p = self.proof
        self.assertTrue(p["ok"])
        self.assertEqual(p["canonical_updates_per_run"], 4)
        self.assertEqual(p["completed_training_games"], 8)
        self.assertEqual(p["completed_validation_games"], 4)
        self.assertEqual(p["scheduled_checkpoint_ids"], ["local-step-2", "local-step-4"])
        for index, item in enumerate(p["actual_updates"], 1):
            self.assertEqual(item["update"]["optimizer_step"], index)
            self.assertEqual(item["duel"]["policy_version"], index - 1)
            self.assertGreater(item["update"]["parameter_delta_l2"], 0)
        self.assertFalse(p["formal_training_ready"])
        self.assertFalse(p["competitive_ability_validated"])

    def test_pause_crash_resume_matches_continuous_including_validation(self):
        self.assertTrue(self.proof["continuous_recovery_equal"])
        self.assertTrue(self.proof["validation_trajectory_recovery_equal"])
        self.assertEqual(self.proof["final_status"]["metrics"]["recovery_count"], 1)
        self.assertGreaterEqual(self.proof["discarded_episode_attempts"], 1)
        self.assertTrue(self.proof["pause_ack"]["local_process_exited"])

    def test_train_validation_seeds_opponent_versions_and_player_data_are_separate(self):
        p = self.proof
        self.assertNotEqual(p["train_opponent_binding_sha256"], p["validation_opponent_binding_sha256"])
        train_seeds = {d["duel"]["seed_audit_only"] for d in p["actual_updates"]}
        self.assertFalse(train_seeds & {d["seed_audit_only"] for d in p["validations"]})
        backend = LocalCpuBackend(self.state, ROOT / ".cache")
        row = backend.details("multiround-duel")
        trainer = verified_trainer(self.state, row)
        run = self.state / "runs/multiround-duel"
        for index in range(1, 5):
            manifest = read_json(run / f"rounds/step-{index}.json")
            for artifact, purpose in [(manifest["train_shard"], "train")] + [(a, "validation") for a in manifest["validation_shards"]]:
                self.assertTrue(artifact["path"].startswith("data/" + purpose + "/"))
                shard = read_artifact(run, artifact)
                self.assertEqual(shard["partition"], purpose)
                self.assertNotIn("seed_audit_only", shard)
                for step in shard["steps"]:
                    dto = step["request"]
                    self.assertIsNone(dto["context"]["seed"])
                    self.assertEqual(dto["observation"]["observer"], trainer.config.actor_seat)
                    for card in dto["observation"]["cards"]:
                        if card["visibility"] == "hidden":
                            self.assertIsNone(card["card_id"])
                            self.assertIsNone(card.get("attack"))
                            self.assertIsNone(card.get("defense"))

    def test_validation_and_old_on_policy_shards_cannot_be_reused_for_update(self):
        backend = LocalCpuBackend(self.state, ROOT / ".cache")
        row = backend.details("multiround-duel")
        trainer = verified_trainer(self.state, row)
        run = self.state / "runs/multiround-duel"
        manifest = read_json(run / "rounds/step-4.json")
        val = read_artifact(run, manifest["validation_shards"][0])
        with self.assertRaisesRegex(ContractError, "stale/off-policy"):
            trainer.update(dict(val, source="live-core-actor-seat", purpose="validation"))
        old = read_artifact(run, manifest["train_shard"])
        with self.assertRaisesRegex(ContractError, "stale/off-policy"):
            trainer.update(dict(old, source="live-core-actor-seat", purpose="train"))

    def test_usage_reconciliation_never_recharges_a_segment_and_retries_are_counted(self):
        p = self.proof
        self.assertTrue(p["usage_reconciliation_idempotent"])
        self.assertEqual(len(p["usage_outbox"]), 4)  # setup + paused + killed + resumed.
        self.assertEqual(len({e["payload"]["event_id"] for e in p["usage_outbox"]}), 4)
        self.assertTrue(all(e["exported"] for e in p["usage_outbox"]))
        self.assertEqual(p["usage_ledger"]["gpu_instance_hours_used"], 0)
        self.assertFalse(p["usage_ledger"]["billing_verified"])
        self.assertIsNone(p["resources"]["interrupted_worker_cpu_seconds"])
        self.assertEqual(p["budget_boundary_status"]["state"], "stopped")
        self.assertEqual(p["budget_boundary_status"]["metrics"]["steps"], 0)

    def fixture_host(self, destination, boundary):
        # File-publication fault fixture made from this suite's actual native run.
        shutil.copytree(self.state, destination)
        with closing(_connect(destination)) as db, db:
            row = get_row(db, "multiround-duel")
            row.update(state="failed", desired="running", phase="publication_fault_fixture", pid=None, pid_stamp=None,
                       checkpoint_ids=row["checkpoint_ids"][:boundary + 1], rounds=row["rounds"][:boundary],
                       updates=row["updates"][:boundary], validations=[], revision=row["revision"] + 1)
            row["metrics"].update(steps=boundary, episodes=boundary)
            put_row(db, row)
        return LocalCpuBackend(destination, ROOT / ".cache"), row

    def test_complete_unregistered_round_is_adopted_with_its_actual_data_and_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "host"
            backend, row = self.fixture_host(state, 1)
            status = backend.recover(row["run_id"], row["revision"])
            self.assertEqual(status["metrics"]["steps"], 2)
            self.assertEqual(status["metrics"]["validation_episodes"], 1)
            restored = verified_trainer(state, backend.details(row["run_id"]))
            self.assertEqual(restored.updates, 2)
            self.assertEqual(len(backend.details(row["run_id"])["updates"]), 2)

    def test_checkpoint_without_complete_round_is_quarantined_and_corrupt_data_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "partial"
            backend, row = self.fixture_host(state, 1)
            (state / "runs/multiround-duel/rounds/step-2.json").unlink()
            status = backend.recover(row["run_id"], row["revision"])
            self.assertEqual(status["metrics"]["steps"], 1)
            self.assertFalse((state / "runs/multiround-duel/checkpoints/local-step-2.weights").exists())
            corrupt_state = Path(temp) / "corrupt"
            backend, row = self.fixture_host(corrupt_state, 4)
            run = corrupt_state / "runs/multiround-duel"
            manifest = read_json(run / "rounds/step-4.json")
            path = run / manifest["train_shard"]["path"]
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(ContractError, "data integrity"):
                verified_trainer(corrupt_state, row)


if __name__ == "__main__":
    unittest.main()
