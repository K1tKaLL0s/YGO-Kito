"""Host recipe/provenance contracts; real saved GroupState smoke is separate."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from ygo_kito.build_contracts import digest
from ygo_kito.group_runner import initialization_spec, check_initialization_provenance, validate_recipe
from ygo_kito.validation import ContractError, read_json

ROOT = Path(__file__).resolve().parents[1]


class InitializationHostContracts(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="init-contract-", dir=ROOT / "configs")
        self.addCleanup(self.folder.cleanup)
        self.source_binding = {"scope": "explicit-contract-fixture-not-a-training-checkpoint"}
        self.spec = {"path": ".cache/source-need-not-exist-for-target-restore.weights", "sha256": "a" * 64,
                     "source_binding_sha256": digest(self.source_binding), "weights": "effective"}
        self.path = Path(self.folder.name) / "init.json"
        self.path.write_text(json.dumps(self.spec), encoding="utf-8")
        self.recipe = dict(read_json(ROOT / "configs/group-runner-v1.json"), initialize_from=str(self.path.relative_to(ROOT)))
        self.binding = {"task_sha256": "b" * 64, "period_context": {"period_id": "synthetic-target"}}
        self.provenance = {"schema_version": 1, "kind": "explicit-group-weight-initialization-not-resume",
            "weights": "effective", "source_artifact_sha256": self.spec["sha256"],
            "source_binding_sha256": self.spec["source_binding_sha256"], "source_binding": self.source_binding,
            "target_binding_sha256": digest(self.binding), "target_task_sha256": self.binding["task_sha256"],
            "target_period_context": self.binding["period_context"], "optimizer_state_inherited": False,
            "rng_state_inherited": False, "data_or_ledger_inherited": False,
            "historical_training_verified": False, "ability_verified": False}

    def test_host_recipe_selects_only_explicit_valid_initialization(self):
        self.assertEqual(validate_recipe(self.recipe), self.recipe)
        self.assertEqual(initialization_spec(self.recipe), self.spec)
        self.assertIsNone(initialization_spec({}))
        with self.assertRaises(ContractError):
            validate_recipe(dict(self.recipe, initialize_from=".cache/unsafe-host-selection.json"))
        self.path.write_text(json.dumps(dict(self.spec, weights="implicit-drop-lora")), encoding="utf-8")
        with self.assertRaises(ContractError): validate_recipe(self.recipe)

    def test_target_resume_needs_immutable_provenance_not_the_old_source_file(self):
        self.assertFalse((ROOT / self.spec["path"]).exists())
        check_initialization_provenance(self.recipe, self.provenance, self.binding)
        check_initialization_provenance({}, None, self.binding)
        with self.assertRaises(ContractError): check_initialization_provenance(self.recipe, None, self.binding)
        with self.assertRaises(ContractError): check_initialization_provenance({}, self.provenance, self.binding)

    def test_changed_source_target_or_inherited_state_is_not_accepted_as_the_saved_transfer(self):
        for key, value in (("source_artifact_sha256", "0" * 64), ("source_binding", {"changed": True}),
                           ("target_binding_sha256", "0" * 64), ("target_task_sha256", "0" * 64),
                           ("target_period_context", None), ("weights", "base"),
                           ("optimizer_state_inherited", True), ("rng_state_inherited", True),
                           ("data_or_ledger_inherited", True), ("historical_training_verified", True)):
            bad = deepcopy(self.provenance); bad[key] = value
            with self.subTest(key=key), self.assertRaises(ContractError):
                check_initialization_provenance(self.recipe, bad, self.binding)


if __name__ == "__main__": unittest.main()
