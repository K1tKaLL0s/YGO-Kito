from contextlib import closing
from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import unittest

import torch

from ygo_kito.build_pipeline import BuildAssets
from ygo_kito.build_training import load_checkpoint as load_build
from ygo_kito.group_runner_acceptance import run_group_acceptance
from ygo_kito.local_training import LocalCpuBackend, verified_trainer, _connect, get_row, put_row, checkpoint_receipt
from ygo_kito.training_runner import read_artifact
from ygo_kito.validation import ContractError, canonical_json, read_json

ROOT = Path(__file__).resolve().parents[1]


class RealFourModelAlternatingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.proof = run_group_acceptance(ROOT / ".cache", cls.root, "real-group-cycles",
                                         read_json(ROOT / "configs/group-runner-v1.json"))
        cls.state = cls.root / "experiments/real-group-cycles/host"
        cls.run_dir = cls.state / "runs/group-interrupted"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_two_real_cycles_update_all_four_roles_and_keep_bases_frozen(self):
        p = self.proof
        self.assertTrue(p["ok"])
        self.assertEqual(p["final_snapshot"]["cursor"], {"cycle": 2, "phase": "done", "committed_stages": 13})
        self.assertEqual(p["final_snapshot"]["metrics"]["optimizer_updates"], 12)
        self.assertEqual(p["confirmed_physical_optimizer_calls"], 36)
        self.assertEqual(p["committed_training_games"], 9)
        self.assertEqual(p["committed_frozen_evaluation_games"], 6)
        self.assertEqual(set(p["role_adapters"]), {"duel", "build_goal", "build_optimizer", "coordinator"})
        for role, meta in p["role_adapters"].items():
            self.assertEqual(meta["updates"], 2)
            self.assertEqual(meta["compatibility"]["base_sha256"], p["role_base_sha256"][role])
        for update in p["updates_after_final"]:
            self.assertGreater(update.get("parameter_delta_l2", update.get("adapter_delta_l2")), 0)
            self.assertGreater(update["gradient_norm_before_clip"], 0)
            if "base_parameter_elements_changed" in update:
                self.assertEqual(update["base_parameter_elements_changed"], 0)
        self.assertFalse(p["formal_training_ready"])
        self.assertFalse(p["competitive_ability_validated"])

    def test_mixed_role_pause_and_manual_checkpoint_are_real(self):
        p = self.proof
        self.assertTrue(p["pause_ack"]["local_process_exited"])
        self.assertEqual(p["paused_stage_snapshot"]["cursor"]["phase"], "coordinator_train")
        self.assertEqual(p["paused_stage_snapshot"]["role_adapter_updates"],
                         {"build_goal": 1, "build_optimizer": 1, "duel": 1, "coordinator": 0})
        self.assertTrue(p["manual_checkpoint_ack"]["applied"])

    def test_real_evaluation_crash_restores_all_training_state_without_duplicate_updates(self):
        p = self.proof
        self.assertEqual(p["fault_phase"], "evaluate")
        self.assertEqual(p["fault_committed_stages"], 5)
        self.assertEqual(len(p["updates_before_fault"]), 8)
        self.assertEqual(p["updates_after_final"][:8], p["updates_before_fault"])
        self.assertTrue(p["continuous_recovery_equal"])
        self.assertEqual(p["discarded_optimizer_calls"], 0)
        self.assertEqual(len(set(p["consumed_stage_markers"])), 13)
        self.assertEqual(p["final_status"]["metrics"]["recovery_count"], 1)

    def test_freeze_evaluation_and_feedback_use_rule_authority_and_feed_next_cycle(self):
        events = {e["event_id"]: e["payload"] for e in self.proof["events"]}
        for cycle in (1, 2):
            evaluation = events[f"cycle-{cycle}-evaluate"]
            self.assertTrue(evaluation["training_state_unchanged"])
            self.assertEqual(evaluation["forecast"]["calibration"], "pending")
            feedback = events[f"cycle-{cycle}-feedback"]
            self.assertEqual(feedback["evaluation_budget_route"]["mode"], "rule_authoritative")
            self.assertEqual(feedback["evaluation_budget_route"]["action"], "stop")
        self.assertEqual(events["cycle-2-build_goal"]["previous_feedback"], events["cycle-1-feedback"])
        self.assertEqual(events["cycle-2-feedback"]["next_phase"], "done")
        self.assertEqual(len(events["cycle-1-build_optimizer"]["construction"]["stages"]), 4)

    def test_train_eval_are_held_out_and_persist_only_legal_player_views(self):
        p = self.proof
        self.assertEqual(len(p["data_marks"]), 5)
        train = [e["payload"]["duel"] for e in p["events"] if e["event_id"].endswith("duel_train")]
        self.assertEqual([d["seed_audit_only"] for d in train], [1725, 1726])
        self.assertTrue(all(v["duel"]["purpose"] == "validation" and v["duel"]["seed_audit_only"] == 1001724 for v in p["evaluations"]))
        for mark in p["data_marks"]:
            artifact = read_artifact(self.run_dir, mark["artifact"])
            self.assertEqual(artifact["partition"], mark["partition"])
            self.assertTrue(mark["artifact"]["path"].startswith("data/" + mark["partition"] + "/"))
            for step in artifact["steps"]:
                dto = step["request"]
                self.assertIsNone(dto["context"]["seed"])
                self.assertEqual(dto["observation"]["observer"], 0)
                for card in dto["observation"]["cards"]:
                    if card["visibility"] == "hidden":
                        self.assertIsNone(card["card_id"])
                        self.assertIsNone(card.get("attack"))
                        self.assertIsNone(card.get("defense"))

    def test_stage_budget_resume_preserves_total_budget_and_does_not_train_again(self):
        p = self.proof
        self.assertEqual(p["stage_budget_pause"]["cursor_step"], 12)
        self.assertEqual(p["stage_budget_pause"]["state"], "paused")
        self.assertTrue(p["stage_budget_resume_equal"])
        self.assertTrue(p["total_budget_unchanged"])
        self.assertEqual(p["stage_budget_final_status"]["state"], "completed")
        self.assertTrue(p["usage_reconciliation_idempotent"])
        self.assertEqual(p["usage_ledger"]["events"], 9)
        self.assertEqual(p["usage_ledger"]["gpu_instance_hours_used"], 0)
        self.assertFalse(p["cloud_billing_stopped"])

    def test_checkpoint_contains_all_models_optimizers_adapters_stage_rng_and_data_markers(self):
        state = torch.load(self.run_dir / "checkpoints/local-step-13.weights", weights_only=True)
        self.assertEqual(set(state["adapters"]), set(self.proof["role_adapters"]))
        self.assertEqual(state["cursor"]["committed_stages"], 13)
        self.assertEqual(len(state["consumed"]), 13)
        self.assertEqual(len(state["data_marks"]), 5)
        self.assertIn("torch", state["global_rng"])
        self.assertIn("python", state["global_rng"])
        self.assertIn("usage_outbox", state["budget_snapshot"])
        self.assertEqual(state["budget_snapshot"]["wall_limit_seconds"], 180.)
        for adapter in state["adapters"].values():
            self.assertEqual(adapter["updates"], 2)
            self.assertTrue(adapter["optimizer"]["state"])
            self.assertIn("scheduler", adapter)
            self.assertIn("rng", adapter)
        self.assertTrue(state["components"]["duel"]["optimizer"]["state"])
        self.assertTrue(state["components"]["coordinator"]["optimizer"]["state"])
        self.assertEqual(state["components"]["build"]["updates"], {"build_goal": 1, "build_optimizer": 1})

    def fixture_host(self, destination, boundary):
        # Explicit publication fault fixture, copied from this suite's real run.
        shutil.copytree(self.state, destination)
        run = destination / "runs/group-interrupted"
        manifest = read_json(run / f"stages/step-{boundary}.json")
        progress = manifest["snapshot"]
        with closing(_connect(destination)) as db, db:
            row = get_row(db, "group-interrupted")
            row.update(state="failed", desired="running", phase="publication_fault_fixture", pid=None, pid_stamp=None,
                       rounds=row["rounds"][:boundary], group_events=row["group_events"][:boundary],
                       checkpoint_ids=[c for c in row["checkpoint_ids"] if read_json(run / "checkpoints" / (c + ".json"))["step"] <= boundary],
                       updates=row["updates"][:progress["metrics"]["optimizer_updates"]], validations=[],
                       model_versions=progress["model_versions"], revision=row["revision"] + 1)
            row["metrics"].update(progress["metrics"])
            put_row(db, row)
        return LocalCpuBackend(destination, ROOT / ".cache"), row

    def test_complete_unregistered_stage_is_adopted_with_no_repeated_update(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "host"
            backend, row = self.fixture_host(state, 5)
            recovered = backend.recover(row["run_id"], row["revision"])
            self.assertEqual(recovered["metrics"]["steps"], 6)
            self.assertEqual(recovered["metrics"]["optimizer_updates"], 8)
            self.assertEqual(recovered["metrics"]["validation_episodes"], 1)
            current = verified_trainer(state, backend.details(row["run_id"]))
            self.assertEqual(current.phase, "feedback")

    def test_partial_publication_is_quarantined_and_bad_phase_cursor_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "partial"
            backend, row = self.fixture_host(state, 5)
            (state / "runs/group-interrupted/stages/step-6.json").unlink()
            recovered = backend.recover(row["run_id"], row["revision"])
            self.assertEqual(recovered["metrics"]["steps"], 5)
            self.assertFalse((state / "runs/group-interrupted/checkpoints/local-step-6.weights").exists())
            state = Path(temp) / "cursor"
            shutil.copytree(self.state, state)
            backend = LocalCpuBackend(state, ROOT / ".cache")
            row = backend.details("group-interrupted")
            path = state / "runs/group-interrupted/checkpoints/local-step-13.weights"
            payload = torch.load(path, weights_only=True)
            payload["cursor"]["cycle"] = 0
            with path.open("wb") as output:
                torch.save(payload, output)
            path.with_suffix(".json").write_text(canonical_json(checkpoint_receipt(row["run_id"], path, 13)) + "\n")
            with self.assertRaisesRegex(ContractError, "cursor"):
                verified_trainer(state, row)

    def test_untrained_build_component_requires_explicit_initial_load_opt_in(self):
        state = torch.load(self.run_dir / "checkpoints/local-step-0.weights", weights_only=True)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "initial-build.weights"
            with path.open("wb") as output:
                torch.save(state["components"]["build"], output)
            assets = BuildAssets(ROOT / ".cache")
            with self.assertRaises(ContractError):
                load_build(path, assets, state["components"]["build"]["binding"])
            initial = load_build(path, assets, state["components"]["build"]["binding"], allow_initial=True)
            self.assertEqual(initial.batch_cursor, 0)
            self.assertEqual(initial.updates, {"build_goal": 0, "build_optimizer": 0})

    def test_model_checkpoint_cannot_roll_back_spent_budget_or_drop_usage_events(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "budget-rollback"
            shutil.copytree(self.state, state)
            backend = LocalCpuBackend(state, ROOT / ".cache")
            row = backend.details("group-interrupted")
            row["active_seconds"] = 0.
            row["segment_started"] = None
            row["usage_outbox"] = []
            with self.assertRaisesRegex(ContractError, "budget|accounting"):
                verified_trainer(state, row)


if __name__ == "__main__":
    unittest.main()
