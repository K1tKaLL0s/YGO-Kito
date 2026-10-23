"""Actual extra games and paired-rule-driver CPU learning; not competitive acceptance."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import torch

from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.build_feedback import comparison_projection, descriptive_uncertainty, real_game_dataset, validate_comparison
from ygo_kito.build_pipeline import BuildAssets, apply_changes
from ygo_kito.build_training import load_checkpoint, validate_supervision
from ygo_kito.effect_duel import run_effect_duel
from ygo_kito.extra_acceptance import run_extra_feedback_acceptance
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"


def reseal(comparison):
    comparison["plan_sha256"] = digest(comparison["plan"])
    comparison["comparison_sha256"] = digest(comparison_projection(comparison))


class RealBuildFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.proof = run_extra_feedback_acceptance(CACHE, cls.temp.name, "real-feedback-integration")
        cls.directory = Path(cls.temp.name) / "real-feedback-integration"
        cls.assets = BuildAssets(CACHE)
        cls.task = BuildTask.from_dict(json.loads((ROOT / "configs/build-real-feedback-task-v2.json").read_text()))
        cls.data = json.loads((cls.directory / "construction-train-data.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_three_routed_extra_games_reach_native_terminal_and_exact_private_replays(self):
        games = self.proof["full_extra_games"]
        self.assertEqual(len(games), 3)
        for game in games:
            self.assertTrue(game["exact_replay"])
            self.assertIn(game["outcome"]["winner"], (0, 1, 2))
            self.assertGreater(game["decisions"], 0)
            self.assertTrue(game["player_view_audit"]["no_hidden_identity_owner_stats"])
            self.assertGreater(game["player_view_audit"]["both_player_windows"], 0)
        self.assertEqual(games[-1]["player_view_audit"]["xyz_material_counts_observed"], [0, 1, 2])
        trace = json.loads((self.directory / "game-xyz-first.json").read_text())
        self.assertEqual(trace["events"][-1]["kind"], 5)
        self.assertTrue(any(e["kind"] == 50 and e.get("from_zone", 0) & 128 for e in trace["events"]))

    def test_real_comparison_is_complete_frozen_paired_and_explicitly_unqualified(self):
        comparison = self.proof["comparison"]
        validate_comparison(self.task, self.assets, comparison)
        self.assertEqual(len(comparison["games"]), 8)
        self.assertEqual(len({(g["candidate_index"], g["seed_audit_only"], g["actor_seat"]) for g in comparison["games"]}), 8)
        self.assertTrue(all(g["core_terminal_received"] and g["replay_verified"] for g in comparison["games"]))
        self.assertIsNotNone(comparison["preferred_index"])
        self.assertFalse(comparison["competitive_ability_validated"])
        self.assertFalse(comparison["plan"]["driver"]["trained_policy"])
        self.assertFalse(comparison["opponent_qualification"]["competitive_strength_verified"])
        self.assertFalse(comparison["uncertainty"]["confidence_gate_passed"])
        self.assertIn("no_single_loss", comparison["uncertainty"]["failure_attribution"])

    def test_real_pair_updates_independent_goal_and_optimizer_weights_and_retains_goal(self):
        train = self.proof["training"]
        self.assertEqual(train["canonical_optimizer_calls"], 4)
        self.assertEqual(train["total_executed_optimizer_calls"], 6)
        self.assertEqual({u["role"] for batch in train["updates"] for u in batch}, {"build_goal", "build_optimizer"})
        for update in [u for batch in train["updates"] for u in batch] + train["recovery_updates"]:
            self.assertGreater(update["changed_parameter_elements"], 0)
            self.assertGreater(update["parameter_delta_l2"], 0)
            self.assertNotEqual(update["before_sha256"], update["after_sha256"])
        self.assertTrue(train["training_pair_margin_improved"])
        self.assertFalse(train["on_policy_ppo_data_used"])
        chosen = DeckParts.from_dict(train["selected_deck"])
        self.assets.validate(self.task, chosen)
        before = DeckParts.from_dict(self.proof["comparison"]["plan"]["candidates"][0])
        self.assertEqual(apply_changes(before, train["changes_from_candidate_0"]), chosen)
        self.assertTrue(train["goal_sha256_unchanged"])
        self.assertEqual(train["selected_goal_status"], "verified_success")
        self.assertFalse(train["general_quality_learned"])
        validate_supervision(self.task, self.assets, self.data)

    def test_checkpoint_restore_exact_state_and_real_artifact_integrity_and_version_rejection(self):
        train = self.proof["training"]
        self.assertTrue(train["checkpoint_state_exact_match"])
        for artifact in self.proof["artifacts"]:
            path = self.directory / artifact["path"]
            self.assertEqual(path.stat().st_size, artifact["bytes"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), artifact["sha256"])
        state = torch.load(self.directory / "paired-feedback-step-2.weights", weights_only=True)
        self.assertNotEqual(state["model_hashes"]["build_goal"], state["model_hashes"]["build_optimizer"])
        wrong = copy.deepcopy(train["binding"])
        wrong["feature_version"] = "build-task-catalog-candidate-v1"
        with self.assertRaises(ContractError):
            load_checkpoint(self.directory / "paired-feedback-step-1.weights", self.assets, wrong)
        self.assertTrue(all(value is False for value in self.proof["gates"].values()))

    def test_synthetic_mutations_of_real_comparison_reject_missing_duplicate_score_driver_and_version(self):
        # These deliberate mutations are contract negatives, never additional engine games.
        for mutation in ("missing", "duplicate", "score", "driver", "version", "opponent"):
            bad = copy.deepcopy(self.proof["comparison"])
            if mutation == "missing": bad["games"].pop()
            elif mutation == "duplicate": bad["games"].append(bad["games"][0])
            elif mutation == "score": bad["games"][0]["score"] = 1 - bad["games"][0]["score"]
            elif mutation == "driver": bad["plan"]["driver"]["trained_policy"] = True
            elif mutation == "version": bad["plan"]["versions"]["card_pool"] = "old"
            else: bad["plan"]["opponent"]["main"].pop()
            reseal(bad)
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                validate_comparison(self.task, self.assets, bad)

    def test_synthetic_tie_and_validation_partition_do_not_become_training_labels(self):
        validation = copy.deepcopy(self.proof["comparison"])
        validation["plan"]["purpose"] = "construction_validation"
        reseal(validation)
        validate_comparison(self.task, self.assets, validation)
        with self.assertRaisesRegex(ContractError, "validation"):
            real_game_dataset(self.task, self.assets, validation)
        tied = copy.deepcopy(self.proof["comparison"])
        for row in tied["games"]:
            row["outcome"]["winner"], row["score"] = 2, .5
        tied.update(mean_scores=[.5, .5], paired_differences=[0., 0., 0., 0.], preferred_index=None, status="no_strict_label",
                    uncertainty=descriptive_uncertainty([0., 0., 0., 0.]))
        reseal(tied)
        validate_comparison(self.task, self.assets, tied)
        with self.assertRaisesRegex(ContractError, "tied"):
            real_game_dataset(self.task, self.assets, tied)
        mislabeled = copy.deepcopy(self.data)
        mislabeled["pairs"][0]["source"] = "engineering_mean_printed_attack_proxy_only"
        with self.assertRaises(ContractError):
            validate_supervision(self.task, self.assets, mislabeled)

    def test_real_routed_replay_rejects_response_mutation_and_wrong_actual_opening(self):
        trace = json.loads((self.directory / "game-extra-first.json").read_text())
        trace["responses"][0]["response"] = {"integer": -1}
        from ygo_kito.native import NativeError
        with self.assertRaises(NativeError):
            run_effect_duel(CACHE, {}, replay=trace)
        trace = json.loads((self.directory / "game-extra-first.json").read_text())
        with self.assertRaisesRegex(ContractError, "opening"):
            run_effect_duel(CACHE, trace["profile"], seed=7, route_task=trace["route_task"])
