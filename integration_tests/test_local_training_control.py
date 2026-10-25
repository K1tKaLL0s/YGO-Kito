from pathlib import Path
import shutil
import tempfile
import unittest

from ygo_kito.engineering_acceptance import control_acceptance, paired_hidden_information_check
from ygo_kito.local_training import LocalCpuBackend, verified_trainer, _connect, get_row, put_row, checkpoint_receipt
from ygo_kito.duel_model import parameter_digest
from ygo_kito.validation import canonical_json
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]


class RealLocalTrainingControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.state_root = Path(cls.temp.name)
        cls.proof = control_acceptance(ROOT / ".cache", cls.state_root)
        backend = LocalCpuBackend(cls.state_root, ROOT / ".cache")
        trainer = verified_trainer(cls.state_root, backend.details("controlled-duel"))
        cls.privacy = paired_hidden_information_check(ROOT / ".cache", trainer)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_json_actions_really_update_pause_exit_save_and_restart(self):
        p = self.proof
        self.assertTrue(p["ok"])
        self.assertEqual(p["paused_checkpoint"]["step"], 1)
        self.assertTrue(p["paused_checkpoint"]["integrity_verified"])
        self.assertEqual(p["pause_ack"]["state"], "paused")
        self.assertTrue(p["pause_ack"]["local_process_exited"])
        self.assertEqual(p["final_status"]["metrics"]["steps"], 2)
        self.assertEqual(len(p["actual_updates"]), 2)
        for row in p["actual_updates"]:
            self.assertEqual(row["duel"]["source"], "live-core-actor-seat")
            self.assertGreater(row["update"]["parameter_delta_l2"], 0)

    def test_real_process_loss_requires_explicit_recovery_and_matches_continuous(self):
        p = self.proof
        self.assertTrue(p["resume_without_recovery_rejected"])
        self.assertTrue(p["continuous_recovery_equal"])
        self.assertEqual(p["final_model_sha256"], p["continuous_final_model_sha256"])
        self.assertEqual(p["final_status"]["metrics"]["recovery_count"], 1)
        self.assertGreaterEqual(p["final_status"]["metrics"]["discarded_episodes"], 1)

    def test_kernel_time_cap_and_local_stop_do_not_claim_cloud_billing_control(self):
        p = self.proof
        self.assertEqual(p["kernel_budget_reason"], "kernel_wall_budget_exhausted")
        self.assertEqual(p["kernel_budget_status"]["state"], "stopped")
        self.assertLess(p["kernel_budget_status"]["metrics"]["steps"], 2)
        self.assertTrue(p["stop_ack"]["local_process_exited"])
        self.assertFalse(p["stop_ack"]["cloud_billing_stopped"])
        self.assertFalse(p["cloud_resource_control_implemented"])

    def test_role_boundaries_idempotency_and_wrong_version_fail_before_launch(self):
        p = self.proof
        self.assertTrue(p["opponent_control_denied"])
        self.assertTrue(p["wrong_version_rejected_before_launch"])
        starts = [row for row in p["transcript"] if row["request"]["id"] == "start-once"]
        self.assertEqual(len(starts), 2)
        self.assertEqual(starts[0]["response"], starts[1]["response"])
        for row in p["transcript"]:
            if row["role"] == "opponent":
                self.assertFalse(row["response"]["ok"])

    def test_two_actual_hidden_worlds_have_identical_legal_features_and_outputs(self):
        self.assertTrue(self.privacy["hidden_hands_actually_differ"])
        self.assertTrue(self.privacy["legal_player_encodings_equal"])
        self.assertTrue(self.privacy["policy_and_value_equal"])
        self.assertFalse(self.privacy["private_identities_returned_to_policy"])
        self.assertEqual(self.privacy["games_completed"], 0)

    def test_publication_crash_reconciles_a_real_unregistered_complete_checkpoint(self):
        backend = LocalCpuBackend(self.state_root, ROOT / ".cache")
        name = "publication-crash-fixture"
        backend.prepare(name)
        checkpoint = self.state_root / "runs" / name / "checkpoints/local-step-1.weights"
        actual = self.state_root / "runs/controlled-duel/checkpoints/local-step-1.weights"
        shutil.copyfile(actual, checkpoint)
        checkpoint.with_suffix(".json").write_text(canonical_json(checkpoint_receipt(name, checkpoint, 1)) + "\n")
        with closing(_connect(self.state_root)) as db, db:
            row = get_row(db, name)
            row.update(state="failed", phase="synthetic_publication_fault", revision=1)
            put_row(db, row)
        restored = backend.recover(name, 1)
        self.assertEqual(restored["metrics"]["steps"], 1)
        self.assertEqual(restored["checkpoint_ids"][-1], "local-step-1")
        recovered = verified_trainer(self.state_root, backend.details(name))
        source = verified_trainer(self.state_root, dict(backend.details("controlled-duel"), checkpoint_ids=["local-step-1"]))
        self.assertEqual(parameter_digest(recovered.model), parameter_digest(source.model))

    def test_incomplete_unregistered_file_is_quarantined_without_inventing_an_update(self):
        backend = LocalCpuBackend(self.state_root, ROOT / ".cache")
        name = "incomplete-file-fixture"
        backend.prepare(name)
        checkpoint = self.state_root / "runs" / name / "checkpoints/local-step-1.weights"
        checkpoint.write_bytes(b"synthetic interrupted file publication")
        with closing(_connect(self.state_root)) as db, db:
            row = get_row(db, name)
            row.update(state="failed", phase="synthetic_partial_file_fault", revision=1)
            put_row(db, row)
        restored = backend.recover(name, 1)
        self.assertEqual(restored["metrics"]["steps"], 0)
        self.assertEqual(restored["checkpoint_ids"][-1], "local-step-0")
        self.assertFalse(checkpoint.exists())
        self.assertEqual(len(list((checkpoint.parent / "quarantine").iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
