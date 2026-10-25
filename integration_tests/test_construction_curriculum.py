"""Two real four-role cycles, private audit source, and crash/recovery control."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from ygo_kito.build_contracts import digest
from ygo_kito.construction_curriculum import validate_state, validate_trace
from ygo_kito.discovery_acceptance import run_curriculum_cycles
from ygo_kito.local_training import LocalCpuBackend, verified_trainer
from ygo_kito.training_runner import read_artifact
from ygo_kito.validation import ContractError, read_json

ROOT = Path(__file__).resolve().parents[1]


class RealConstructionCurriculumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(dir=ROOT / ".cache")
        cls.directory = Path(cls.temporary.name)
        cls.proof = run_curriculum_cycles(ROOT / ".cache", cls.directory)
        cls.backend = LocalCpuBackend(cls.directory / "host", ROOT / ".cache",
            recipe=read_json(ROOT / "configs/group-real-curriculum-v1.json"))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def trainer(self):
        return verified_trainer(self.backend.state_root, self.backend.details("curriculum-recovered"))

    def test_real_source_has_actual_role_updates_extra_decks_and_four_step_construction(self):
        p = self.proof
        self.assertEqual(p["source"], "engineering_real_game_pair_v1")
        self.assertEqual(p["final_snapshot"]["cursor"], {"cycle": 2, "phase": "done", "committed_stages": 13})
        self.assertEqual(set(p["final_snapshot"]["role_adapter_updates"].values()), {2})
        for update in p["actual_updates"]:
            if "adapter_delta_l2" in update:
                self.assertEqual(update["base_parameter_elements_changed"], 0)
                self.assertEqual(update["base_sha256_before"], update["base_sha256_after"])
                self.assertGreater(update["changed_adapter_elements"], 0)
            else:
                self.assertNotEqual(update["before_sha256"], update["after_sha256"])
            self.assertGreater(update.get("parameter_delta_l2", update.get("adapter_delta_l2", 0)), 0)
        constructions = [e["payload"]["construction"] for e in p["events"] if e["event_id"].endswith("-build_optimizer")]
        self.assertEqual(len(constructions), 2)
        for construction in constructions:
            self.assertEqual([s["role"] for s in construction["stages"]], ["build_goal", "build_optimizer"] * 2)
            self.assertNotIn("engineering_proxy", construction)
            self.assertIn("real-rule-driver", construction["best_criterion"])
            self.assertTrue(all(s["deck"]["extra"] == [26593852] and s["validation"]["status"] == "verified_success" for s in construction["stages"]))

    def test_actual_worker_loss_restores_all_roles_and_committed_source_without_repeating_updates(self):
        p = self.proof
        self.assertTrue(p["recovered_equals_continuous"])
        self.assertTrue(p["committed_source_not_regenerated"])
        self.assertTrue(p["usage_reconciliation_idempotent"])
        self.assertEqual(p["canonical_optimizer_calls"], len(p["actual_updates"]))
        self.assertEqual(p["confirmed_physical_optimizer_calls"], 2 * p["canonical_optimizer_calls"])
        self.assertFalse(p["formal_training_ready"])
        self.assertFalse(p["competitive_ability_validated"])
        self.assertFalse(p["cloud_billing_stopped"])

    def test_validation_sources_and_training_consumption_are_separate_and_tampering_fails(self):
        state = self.trainer()
        validate_state(state, artifacts=True)
        saved = deepcopy(state.construction_state)
        self.assertEqual(len(saved["consumed"]), 6)
        self.assertEqual(len(saved["validation"]), 2)
        self.assertTrue(all(e["payload"]["training_state_unchanged"] for e in self.proof["events"] if e["event_id"].endswith("-evaluate")))
        for mutation in ("duplicate", "validation_as_training", "wrong_digest", "wrong_validation", "marker_partition", "marker_sha"):
            state.construction_state = deepcopy(saved)
            if mutation == "duplicate": state.construction_state["consumed"].append(state.construction_state["consumed"][0])
            elif mutation == "validation_as_training": state.construction_state["consumed"][0]["partition"] = "construction_validation"
            elif mutation == "wrong_digest": state.construction_state["consumed"][0]["supervision_sha256"] = "0" * 64
            elif mutation == "wrong_validation": state.construction_state["validation"][0]["artifact"] = saved["train_artifact"]
            elif mutation == "marker_partition": state.construction_state["validation"][0]["partition"] = "construction_train"
            elif mutation == "marker_sha": state.construction_state["validation"][0]["comparison_sha256"] = "0" * 64
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                validate_state(state, artifacts=True)

    def test_true_trace_and_rehashed_game_receipts_cannot_disagree_about_real_result(self):
        state = self.trainer()
        run = self.backend.state_root / "runs/curriculum-recovered"
        artifact = read_artifact(run, state.construction_state["train_artifact"])
        original, original_trace = artifact["comparison"]["games"][0], artifact["traces"][0]
        validate_trace(original, original_trace, state.assets)
        for mutation in ("outcome", "seed", "profile", "turns", "decisions", "terminal", "version"):
            game, trace = deepcopy(original), deepcopy(original_trace)
            if mutation == "outcome": game["outcome"]["winner"] = 1 - game["outcome"]["winner"]
            elif mutation == "seed": game["seed_audit_only"] += 1
            elif mutation == "profile": game["profile_sha256"] = "0" * 64
            elif mutation == "turns": game["turns"] += 1
            elif mutation == "decisions": game["decisions"] += 1
            elif mutation == "terminal": trace["events"][-1]["winner"] = 1 - trace["events"][-1]["winner"]
            elif mutation == "version": trace["versions"]["policy"] = "unfrozen"
            game["trace_sha256"] = digest(trace)
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                validate_trace(game, trace, state.assets)


if __name__ == "__main__":
    unittest.main()
