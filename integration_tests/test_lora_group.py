from pathlib import Path
import tempfile
import unittest

from ygo_kito.build_contracts import BuildTask
from ygo_kito.build_pipeline import BuildAssets
from ygo_kito.coord_contracts import FeedbackPolicy
from ygo_kito.duel_model import parameter_digest
from ygo_kito.lora import AdapterSession, ROLES
from ygo_kito.lora_group import run_lora_group_smoke
from ygo_kito.model_group import execute_duel_job, restore_group
from ygo_kito.validation import ContractError, read_json

ROOT = Path(__file__).resolve().parents[1]


class LoraGroupIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.state_root = Path(cls.temp.name)
        cls.assets = BuildAssets(ROOT / ".cache")
        cls.profile = read_json(ROOT / "configs/effect-duel-v1.json")
        cls.proof = run_lora_group_smoke(ROOT / ".cache", cls.state_root, "lora-test",
                                        BuildTask.from_dict(read_json(ROOT / "configs/build-engineering-v1.json")),
                                        read_json(ROOT / "configs/lora-engineering-v1.json"), FeedbackPolicy())
        cls.run_dir = cls.state_root / "runs/lora-test"
        cls.checkpoint = cls.run_dir / "checkpoints/group-adapted-before-duel.weights"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_actual_adapter_updates_and_base_freezing_in_all_roles(self):
        p = self.proof
        self.assertTrue(p["ok"])
        self.assertEqual(len(p["updates"]), 8)
        self.assertEqual(set(p["rollback"]), set(ROLES))
        for u in p["updates"]:
            self.assertGreater(u["gradient_norm_before_clip"], 0)
            self.assertGreater(u["changed_adapter_elements"], 0)
            self.assertEqual(u["base_sha256_before"], u["base_sha256_after"])
            self.assertEqual(u["base_parameter_elements_changed"], 0)
            self.assertFalse(u["base_gradients_present"])
        self.assertFalse(p["transfer_ability_validated"])
        self.assertFalse(p["competitive_ability_validated"])

    def test_adapter_versions_reach_real_construction_and_native_job(self):
        p = self.proof
        self.assertEqual(len(p["construction"]["stages"]), 4)
        for s in p["construction"]["stages"]:
            self.assertEqual(s["lora_version"], p["adapter_versions"][s["role"]])
            self.assertEqual(s["validation"]["status"], "verified_success")
        self.assertEqual(p["job"]["scope"]["duel_lora"], p["adapter_versions"]["duel"])
        self.assertEqual(p["evaluation"]["result"]["source"], "real_engine")
        self.assertGreater(p["evaluation"]["duel"]["native_decisions"], 0)
        self.assertEqual(p["evaluation"]["status"]["matches"], 1)
        self.assertEqual(p["prior_base_forecast_matches_preserved"], 1)
        self.assertTrue(p["restore_verified"])

    def test_disable_and_unload_recover_exact_base_outputs_and_weights(self):
        p = self.proof
        for r in ROLES:
            evidence = p["rollback"][r]
            self.assertTrue(evidence["active_output_changed"])
            self.assertTrue(evidence["exact_base_output_restore"])
            self.assertEqual(evidence["base_output_sha256"], evidence["disabled_output_sha256"])
            self.assertEqual(p["unloaded_base_hashes"][r], p["base_proof"]["model_hashes"][r])

    def test_exported_adapters_actually_load_onto_restored_base_models(self):
        p = self.proof
        base = self.state_root / "runs/lora-test-base/checkpoints/group-before-duel.weights"
        restored = restore_group(base, self.run_dir / "standalone-adapter-load", self.assets, p["binding"])
        models = dict(restored["builder"].models, duel=restored["duel"].model, coordinator=restored["coordinator"].model)
        for r in ROLES:
            s = AdapterSession.load(models[r], self.run_dir / "adapters" / (r + ".weights"),
                                    p["adapter_compatibility"][r], p["adapter_artifacts"][r])
            self.assertEqual(s.version_id(), p["adapter_versions"][r])
            self.assertEqual(s.unload(), p["base_proof"]["model_hashes"][r])
            self.assertEqual(parameter_digest(models[r]), p["base_proof"]["model_hashes"][r])

    def test_adapter_snapshot_cannot_silently_run_as_base_or_other_context(self):
        p = self.proof
        with self.assertRaises(ContractError):
            restore_group(self.checkpoint, self.run_dir / "missing-adapters", self.assets, p["binding"])
        bad = {r: dict(v, binding=dict(v["binding"], base_version="foreign-version")) for r, v in p["adapter_compatibility"].items()}
        with self.assertRaises(ContractError):
            restore_group(self.checkpoint, self.run_dir / "wrong-context", self.assets, p["binding"], expected_adapters=bad)
        restored = restore_group(self.checkpoint, self.run_dir / "explicit-adapter-required", self.assets, p["binding"],
                                 expected_adapters=p["adapter_compatibility"])
        with self.assertRaises(ContractError):
            execute_duel_job(restored["host"], restored["duel"], restored["coordinator"], self.assets, self.profile,
                             dict(restored["cursor"], task=restored["task"]))
        self.assertEqual(restored["host"].forecast_status("lora-forecast")["matches"], 0)


if __name__ == "__main__":
    unittest.main()
