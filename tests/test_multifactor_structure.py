"""Structural properties, independent of semantic labels or model skill."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import torch

from ygo_kito.multifactor import FactorContractError, Factors, Group, Observation, Relation, RoleInput
from ygo_kito.multifactor.network import NetworkConfig, RoleNetwork, encode_batch
from ygo_kito.multifactor.training import RoleTrainer, Supervision, Targets
from tests.multifactor_helpers import synthetic_example, task_temporary_directory


class MultifactorStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        self.example = synthetic_example()
        self.network = RoleNetwork(NetworkConfig(hidden_dim=16))

    def test_contract_roundtrip_detaches_mutable_json(self):
        payload = self.example.to_dict()
        restored = RoleInput.from_dict(json.loads(json.dumps(payload)))
        payload["groups"][0]["factors"]["observations"]["activation_access"]["value"] = 0
        self.assertEqual(restored, self.example)
        self.assertEqual(restored.groups[0].factors.get("activation_access").value, 0.7)

    def test_unknown_is_distinct_from_known_zero_and_uncertain_measurement(self):
        unknown = Factors("group")
        zero = Factors.observed("group", {"activation_access": 0}, source="measured zero / synthetic")
        uncertain = Factors.from_mapping("group", {"activation_access": Observation(0, 0.2, 0.8, "uncertain / synthetic")})
        self.assertNotEqual(unknown.channels(), zero.channels())
        self.assertNotEqual(uncertain.channels(), zero.channels())
        self.assertIsNone(unknown.get("activation_access").value)

    def test_invalid_observations_and_unknown_schema_rejected(self):
        for value in (float("nan"), float("inf"), -0.01, 1.01, True):
            with self.subTest(value=value), self.assertRaises(FactorContractError):
                Observation(value, 1, 0, "invalid / synthetic")
        for args in ((None, 1, 1, "bad"), (1, 1, 0, "")):
            with self.assertRaises(FactorContractError):
                Observation(*args)
        payload = self.example.to_dict()
        payload["schema_version"] = "unknown-future-version"
        with self.assertRaises(FactorContractError):
            RoleInput.from_dict(payload)
        with self.assertRaises(FactorContractError):
            Factors.observed("group", {"card_id": 0.5}, source="forbidden feature")

    def test_bad_graph_endpoints_duplicates_and_malformed_arrays_rejected(self):
        with self.assertRaises(FactorContractError):
            replace(self.example, groups=(self.example.groups[0], self.example.groups[0]))
        with self.assertRaises(FactorContractError):
            replace(self.example, relations=(Relation("missing", "core", Factors("relation")),))
        with self.assertRaises(FactorContractError):
            replace(self.example, relations=self.example.relations + self.example.relations)
        payload = self.example.to_dict()
        payload["groups"][0]["member_refs"] = "not-an-array"
        with self.assertRaises(FactorContractError):
            RoleInput.from_dict(payload)

    def test_group_and_relation_permutation_equivariance_and_set_invariance(self):
        order = (2, 0, 1)
        changed = replace(self.example, groups=tuple(self.example.groups[i] for i in order),
                          relations=tuple(reversed(self.example.relations)))
        original = self.network(encode_batch((self.example,)))
        permuted = self.network(encode_batch((changed,)))
        for name in ("role_logits", "compatibility_logits", "utility"):
            torch.testing.assert_close(permuted[name], original[name][:, order], atol=2e-6, rtol=2e-6)
        torch.testing.assert_close(permuted["pair_logits"], original["pair_logits"][:, order][:, :, order], atol=2e-6, rtol=2e-6)
        torch.testing.assert_close(permuted["set_representation"], original["set_representation"], atol=2e-6, rtol=2e-6)

    def test_batch_padding_cannot_change_valid_node_scores(self):
        small = replace(self.example, groups=self.example.groups[:1], relations=())
        solo = self.network(encode_batch((small,)))
        mixed = self.network(encode_batch((small, self.example)))
        for name in ("role_logits", "compatibility_logits", "utility"):
            torch.testing.assert_close(solo[name][0, 0], mixed[name][0, 0], atol=2e-6, rtol=2e-6)
            self.assertEqual(float(mixed[name][0, 1:].detach().abs().sum()), 0)

    def test_symmetric_sum_pool_retains_multiplicity_without_position_features(self):
        one = replace(self.example, groups=self.example.groups[:1], relations=())
        two = replace(one, groups=one.groups + (replace(one.groups[0], key="opaque-second-component"),))
        output = self.network(encode_batch((one, two)))
        self.assertFalse(torch.allclose(output["utility"][0, 0], output["utility"][1, 0], atol=1e-7, rtol=1e-7))

    def test_opaque_ids_names_sources_and_member_order_never_enter_tensors(self):
        names = {group.key: "opaque-renamed-" + str(i) for i, group in enumerate(self.example.groups)}
        groups = tuple(replace(group, key=names[group.key], member_refs=tuple(reversed(group.member_refs)),
                               notes=("totally different archetype display name",),
                               unit=None if group.unit is None else replace(group.unit, context_ref="opaque context rename"),
                               factors=Factors.from_mapping("group", {name: replace(value, source="unrelated-audit-source")
                                                                      for name, value in group.factors.items}))
                       for group in self.example.groups)
        changed = replace(self.example, context_ref="opaque context rename", groups=groups,
                          relations=tuple(replace(edge, source=names[edge.source], target=names[edge.target]) for edge in self.example.relations))
        left, right = encode_batch((self.example,)), encode_batch((changed,))
        for name in left:
            self.assertTrue(torch.equal(left[name], right[name]), name)

    def test_directed_dependency_is_encoded_and_pair_compatibility_is_symmetric(self):
        flipped = replace(self.example, relations=tuple(replace(edge, source=edge.target, target=edge.source) for edge in self.example.relations))
        before, after = encode_batch((self.example,)), encode_batch((flipped,))
        self.assertFalse(torch.equal(before["relations"], after["relations"]))
        first, second = self.network(before), self.network(after)
        self.assertFalse(torch.allclose(first["role_logits"], second["role_logits"], atol=1e-7, rtol=1e-7))
        torch.testing.assert_close(first["pair_logits"], first["pair_logits"].transpose(1, 2), atol=1e-7, rtol=1e-7)

    def test_initialization_preserves_host_rng(self):
        state = torch.get_rng_state().clone()
        RoleNetwork(NetworkConfig(seed=19))
        self.assertTrue(torch.equal(state, torch.get_rng_state()))

    def test_partial_multilabel_loss_masks_unknown_role(self):
        trainer = RoleTrainer(NetworkConfig(hidden_dim=16))
        before = trainer.model.role_head.weight.detach().clone()
        trainer.train_supervised((self.example,), (Targets(roles=(("package", (1, None, 1, None, 1)),)),),
                                 (Supervision("engineering_fixture", "partial labels / code path only"),))
        self.assertTrue(torch.equal(before[1], trainer.model.role_head.weight.detach()[1]))
        self.assertFalse(torch.equal(before[0], trainer.model.role_head.weight.detach()[0]))
        self.assertEqual(trainer.head_status("role:small_axis"), "untrained")
        self.assertEqual(trainer.head_status("role:generic_utility"), "engineering_only")

    def test_weights_optimizer_metadata_and_next_update_resume_exactly(self):
        trainer = RoleTrainer(NetworkConfig(hidden_dim=16))
        targets = Targets(roles=(("package", (1, None, 1, 1, None)),), compatibility=(("package", 0),), pairs=(("core", "package", 0),))
        source = Supervision("engineering_fixture", "checkpoint test only")
        trainer.train_supervised((self.example,), (targets,), (source,))
        with task_temporary_directory() as directory:
            path = Path(directory) / "roles.pt"
            trainer.save(path, data_cursor="synthetic-shard-0:row-1")
            rng = torch.get_rng_state().clone()
            restored = RoleTrainer.load(path)
            self.assertTrue(torch.equal(rng, torch.get_rng_state()))
            self.assertEqual(restored.data_cursor, "synthetic-shard-0:row-1")
            self.assertEqual(restored.data_digest, trainer.data_digest)
            self.assertEqual(restored.updates, trainer.updates)
            restored.save(path)
            self.assertEqual(RoleTrainer.load(path).data_cursor, "synthetic-shard-0:row-1")
            left = trainer.train_supervised((self.example,), (targets,), (source,))
            right = restored.train_supervised((self.example,), (targets,), (source,))
            self.assertEqual(left, right)
            for key, value in trainer.model.state_dict().items():
                self.assertTrue(torch.equal(value, restored.model.state_dict()[key]), key)
            self.assertEqual(restored.data_digest, trainer.data_digest)

    def test_checkpoint_source_and_feature_binding_refuse_silent_migration(self):
        trainer = RoleTrainer(NetworkConfig(hidden_dim=16))
        with task_temporary_directory() as directory:
            path = Path(directory) / "roles.pt"
            trainer.save(path)
            payload = torch.load(path, weights_only=True)
            for key in ("schema_sha256", "source_sha256"):
                changed = dict(payload, **{key: "0" * 64})
                torch.save(changed, path)
                with self.assertRaisesRegex(FactorContractError, "differs"):
                    RoleTrainer.load(path)

    def test_changed_annotation_protocol_cannot_mix_or_silently_restore(self):
        trainer = RoleTrainer(NetworkConfig(hidden_dim=16))
        source = Supervision("engineering_fixture", "mismatched rubric / code path only", label_protocol_sha256="0" * 64)
        with self.assertRaisesRegex(FactorContractError, "protocol differs"):
            trainer.train_supervised((self.example,), (Targets(roles=(("package", (1, None, 1, 1, 0)),)),), (source,))
        self.assertEqual(trainer.steps, 0)
        custom = RoleTrainer(NetworkConfig(hidden_dim=16), label_protocol_sha256="0" * 64)
        with task_temporary_directory() as directory:
            path = Path(directory) / "custom-rubric.pt"
            custom.save(path)
            with self.assertRaisesRegex(FactorContractError, "label protocol differs"):
                RoleTrainer.load(path)
            restored = RoleTrainer.load(path, expected_label_protocol_sha256="0" * 64)
            self.assertEqual(restored.label_protocol_sha256, "0" * 64)

    def test_standalone_cli_roundtrips_candidates_without_training_or_active_imports(self):
        from ygo_kito.multifactor.scoring import Candidate
        candidate = Candidate("synthetic-json", self.example, "package", "synthetic gap recall")
        self.assertEqual(Candidate.from_dict(candidate.to_dict()), candidate)
        with task_temporary_directory() as directory:
            input_path, output_path = Path(directory) / "input.json", Path(directory) / "output.json"
            input_path.write_text(json.dumps(dict(schema_version="multifactor-candidates-v2", candidates=[candidate.to_dict()])), encoding="utf-8")
            subprocess.run((sys.executable, "-m", "ygo_kito.multifactor", "--input", str(input_path),
                            "--output", str(output_path), "--without-explanations"), env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/"src")),
                           capture_output=True, text=True, check=True, timeout=60)
            output = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertFalse(output["training_started"])
            self.assertIsNone(output["results"][0]["advisory_score"])
            self.assertEqual(set(output["results"][0]["role_probabilities"]),
                             {"large_axis", "small_axis", "strategic_core", "support_role", "generic_utility"})

    def test_lightweight_contract_import_does_not_load_torch_or_active_modules(self):
        code = "import sys,json; import ygo_kito.multifactor; print(json.dumps(sorted(n for n in sys.modules if n=='torch' or n.startswith(('ygo_kito.build_', 'ygo_kito.construction_', 'ygo_kito.effect_', 'ygo_kito.autonomous_construction', 'ygo_kito.native')))))"
        result = subprocess.run((sys.executable, "-c", code), env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]/"src")),
                                capture_output=True, text=True, check=True, timeout=30)
        self.assertEqual(json.loads(result.stdout), [])


if __name__ == "__main__":
    unittest.main()
