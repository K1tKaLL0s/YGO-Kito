"""Simulated-factor code paths. These checks do not measure learned role quality."""

from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

import torch

from ygo_kito.multifactor import FactorContractError, Factors, Observation
from ygo_kito.multifactor.network import NetworkConfig, encode_batch
from ygo_kito.multifactor.scoring import Candidate, CandidateScorer
from ygo_kito.multifactor.training import RoleTrainer, Supervision, Targets
from tests.multifactor_helpers import synthetic_example, task_temporary_directory


class MultifactorSyntheticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def setUp(self):
        self.example = synthetic_example()
        self.trainer = RoleTrainer(NetworkConfig(hidden_dim=16))
        self.scorer = CandidateScorer(self.trainer)

    def candidate(self, example=None, **kwargs):
        return Candidate("synthetic-recall-1", example or self.example, "package", "synthetic interaction-gap recall", **kwargs)

    def test_supervised_gradients_reach_factors_relations_and_three_independent_heads(self):
        target = Targets(roles=(("core", (1, None, 1, None, 0)), ("package", (1, None, 1, 1, 1))),
                         compatibility=(("package", 0),), pairs=(("core", "package", 0),))
        before = {name: value.detach().clone() for name, value in self.trainer.model.named_parameters()}
        result = self.trainer.train_supervised((self.example,), (target,),
                                              (Supervision("engineering_fixture", "artificial factors; no real quality labels"),))
        self.assertTrue(torch.isfinite(torch.tensor(result["loss"])))
        self.assertGreater(result["gradient_norm"], 0)
        for prefix in ("group_encoder", "relation_encoder", "role_head", "compatibility_head", "pair_head"):
            self.assertTrue(any(not torch.equal(value, before[name]) for name, value in self.trainer.model.named_parameters()
                                if name.startswith(prefix)), prefix)
        self.assertEqual(result["head_status"]["role"], "engineering_only")
        self.assertEqual(result["head_status"]["utility"], "untrained")

    def test_candidate_preference_updates_utility_without_assigning_role_labels(self):
        other = synthetic_example(conflict=0.9)
        before = self.trainer.model.utility_head.weight.detach().clone()
        result = self.trainer.train_preference(self.example, other, left_key="package", right_key="package", preferred_left=1,
                                              source=Supervision("engineering_fixture", "synthetic pair; not measured performance", scope="candidate"))
        self.assertNotEqual(float((before - self.trainer.model.utility_head.weight.detach()).abs().sum()), 0)
        self.assertEqual(result["head_status"]["utility"], "engineering_only")
        self.assertEqual(result["head_status"]["role"], "untrained")
        self.assertEqual(result["head_status"]["compatibility"], "untrained")
        with task_temporary_directory() as directory:
            path = Path(directory) / "preference.pt"
            self.trainer.save(path)
            restored = RoleTrainer.load(path)
            source = Supervision("engineering_fixture", "synthetic resume only", scope="candidate")
            left = self.trainer.train_preference(self.example, other, left_key="package", right_key="package", preferred_left=1, source=source)
            right = restored.train_preference(self.example, other, left_key="package", right_key="package", preferred_left=1, source=source)
            self.assertEqual(left, right)
            for name, value in self.trainer.model.state_dict().items():
                self.assertTrue(torch.equal(value, restored.model.state_dict()[name]), name)

    def test_same_bundle_different_context_has_conditional_capacity_not_asserted_correct_labels(self):
        other = synthetic_example(interaction_gap=0.1)
        self.assertEqual(self.example.groups, other.groups)
        first, second = encode_batch((self.example,)), encode_batch((other,))
        self.assertTrue(torch.equal(first["groups"], second["groups"]))
        self.assertFalse(torch.equal(first["context"], second["context"]))
        logits = self.trainer.model(encode_batch((self.example, other)))["role_logits"]
        self.assertFalse(torch.allclose(logits[0, 1], logits[1, 1], atol=1e-7, rtol=1e-7))
        # No assertion that the random network picks the right contextual role.

    def test_equal_space_different_dependency_or_lock_produces_distinct_inputs(self):
        other = synthetic_example(conflict=0.95)
        for name in ("main_space", "extra_space"):
            self.assertEqual(self.example.groups[1].factors.get(name), other.groups[1].factors.get(name))
        self.assertFalse(torch.equal(encode_batch((self.example,))["groups"], encode_batch((other,))["groups"]))

    def test_untrained_and_engineering_only_outputs_abstain_with_explicit_head_status(self):
        before = self.scorer.score_candidates((self.candidate(legality="pass", legality_ref="synthetic external pass"),), explain=False)[0]
        self.assertIsNone(before["advisory_score"])
        self.assertFalse(before["calibrated"])
        self.assertEqual(before["head_status"]["utility"], "untrained")
        self.trainer.train_preference(self.example, synthetic_example(conflict=0.8), left_key="package", right_key="package", preferred_left=1,
                                      source=Supervision("engineering_fixture", "synthetic update only", scope="candidate"))
        after = self.scorer.score_candidates((self.candidate(legality="pass", legality_ref="synthetic external pass"),), explain=False)[0]
        self.assertIsNone(after["advisory_score"])
        self.assertIn("utility_engineering_only", after["abstention_reasons"])

    def test_external_rules_and_missing_factors_remain_authoritative_even_with_mocked_training_status(self):
        # Mocking only tests the control seam, not trained weights or real feedback.
        with patch.object(self.trainer, "head_status", return_value="trained_uncalibrated"):
            passed = self.scorer.score_candidates((self.candidate(legality="pass", legality_ref="synthetic external pass"),), explain=False)[0]
            self.assertIsInstance(passed["advisory_score"], float)
            for legality in ("fail", "unknown"):
                result = self.scorer.score_candidates((self.candidate(legality=legality, legality_ref="synthetic external result"),), explain=False)[0]
                self.assertIsNone(result["advisory_score"])
                self.assertIn("external_legality_" + legality, result["abstention_reasons"])
            groups = list(self.example.groups)
            groups[1] = replace(groups[1], factors=groups[1].factors.without("summon_lock_risk"))
            result = self.scorer.score_candidates((self.candidate(replace(self.example, groups=tuple(groups)),
                                                   legality="pass", legality_ref="synthetic external pass"),), explain=False)[0]
            self.assertIsNone(result["advisory_score"])
            self.assertIn("summon_lock_risk", result["unresolved_required_factors"])
        self.assertFalse(passed["rule_authority"])

    def test_explanation_reports_actual_ablation_and_unknowns_without_mutating_input(self):
        before = self.example.to_dict()
        result = self.scorer.score_candidates((self.candidate(),))[0]
        explanation = result["explanation"]
        self.assertFalse(explanation["causal"])
        self.assertIn("recycle_closure", explanation["unknown_factors"])
        item = next(item for item in explanation["factors"] if item["factor"] == "goal_contribution")
        groups = list(self.example.groups)
        groups[1] = replace(groups[1], factors=groups[1].factors.without("goal_contribution"))
        raw = self.scorer.score_candidates((self.candidate(replace(self.example, groups=tuple(groups))),), explain=False)[0]["raw_utility"]
        self.assertAlmostEqual(item["utility_delta"], result["raw_utility"] - raw, places=6)
        self.assertEqual(before, self.example.to_dict())

    def test_candidate_order_and_explicit_recall_boundaries(self):
        a = self.candidate()
        b = replace(a, candidate_ref="synthetic-recall-0", example=synthetic_example(conflict=0.8))
        result = self.scorer.score_candidates((a, b), explain=False)
        self.assertEqual([row["candidate_ref"] for row in result], [a.candidate_ref, b.candidate_ref])
        with self.assertRaises(FactorContractError):
            self.scorer.score_candidates(())
        with self.assertRaises(FactorContractError):
            self.scorer.score_candidates((a, a))
        with self.assertRaises(FactorContractError):
            self.scorer.score_candidates((a, replace(b, example=synthetic_example(context_ref="different goal"))))
        with self.assertRaises(FactorContractError):
            replace(a, recall_source="")

    def test_validation_or_final_eval_data_and_deck_sources_cannot_update(self):
        state = {name: value.clone() for name, value in self.trainer.model.state_dict().items()}
        for partition in ("validation", "final_eval"):
            source = Supervision("engineering_fixture", "held-out synthetic", partition=partition)
            with self.assertRaisesRegex(FactorContractError, "only train"):
                self.trainer.train_supervised((self.example,), (Targets(roles=(("package", (1, None, 0, 1, 1)),)),), (source,))
        for source_kind in ("external_hot_deck", "reference", "opponent"):
            with self.assertRaises(FactorContractError):
                Supervision(source_kind, "not learner data")
        self.assertEqual(self.trainer.steps, 0)
        for name, value in self.trainer.model.state_dict().items():
            self.assertTrue(torch.equal(value, state[name]))

    def test_unknown_labels_do_not_become_negatives_and_bad_scope_cannot_assign_roles(self):
        with self.assertRaisesRegex(FactorContractError, "no observed"):
            self.trainer.train_supervised((self.example,), (Targets(roles=(("package", (None, None, None, None, None)),)),),
                                          (Supervision("engineering_fixture", "unknown labels"),))
        for source in (Supervision("engine_probe", "scope check only"),
                       Supervision("self_generated_candidate", "whole-candidate attribution", scope="candidate")):
            with self.assertRaises(FactorContractError):
                self.trainer.train_supervised((self.example,), (Targets(roles=(("package", (1, None, 1, 1, 0)),)),), (source,))
        self.assertEqual(self.trainer.steps, 0)

    def test_pairing_must_preserve_context_and_candidate_target(self):
        source = Supervision("engineering_fixture", "invalid pair test", scope="candidate")
        for other, key in ((synthetic_example(interaction_gap=0.2), "package"), (self.example, "missing")):
            with self.assertRaises(FactorContractError):
                self.trainer.train_preference(self.example, other, left_key="package", right_key=key, preferred_left=1, source=source)
        self.assertEqual(self.trainer.steps, 0)


if __name__ == "__main__":
    unittest.main()
