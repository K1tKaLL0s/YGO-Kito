"""Joint-unit invariants and user definition cases; no independent quality score."""

from dataclasses import replace
import json
from pathlib import Path
import unittest

import torch

from ygo_kito.multifactor import FactorContractError, Factors, Group, RoleInput
from ygo_kito.multifactor.annotations import AnnotationRecord
from ygo_kito.multifactor.functional_units import Dependency, FunctionalContract, KnownCondition, MemberAmount, assess_unit, minimum_members
from ygo_kito.multifactor.network import NetworkConfig, encode_batch
from ygo_kito.multifactor.scoring import Candidate, CandidateScorer, prepare_function_candidate
from ygo_kito.multifactor.training import RoleTrainer, Supervision, Targets
from tests.multifactor_helpers import synthetic_contract, synthetic_example

FIXTURE = Path(__file__).parent / "fixtures" / "multifactor-functional-definition-cases-v2.json"


class MultifactorFunctionalUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.records = tuple(AnnotationRecord.from_dict(row) for row in json.loads(FIXTURE.read_text())["records"])

    def setUp(self):
        self.example = synthetic_example()
        self.contract = synthetic_contract(self.example.context_ref, ("opaque-A", "opaque-B"))

    def test_function_contract_roundtrip_and_exact_joint_membership(self):
        self.assertEqual(FunctionalContract.from_dict(json.loads(json.dumps(self.contract.to_dict()))), self.contract)
        self.assertEqual(minimum_members(self.contract), {"opaque-A": 1, "opaque-B": 1})
        result = assess_unit(self.contract, ("opaque-B", "opaque-A"))
        self.assertTrue(result["exact_minimum"])
        self.assertEqual(result["genericity_scope"], "strict_joint")
        self.assertFalse(result["rule_authority"])

    def test_transitive_and_cyclic_joint_requirements_preserve_shared_quantities(self):
        rules = (Dependency("opaque-A", (MemberAmount("opaque-B"), MemberAmount("opaque-C", 2)), "synthetic AND"),
                 Dependency("opaque-B", (MemberAmount("opaque-A"), MemberAmount("opaque-D")), "synthetic cycle"))
        contract = replace(self.contract, dependencies=rules, reviewed_members=("opaque-A", "opaque-B", "opaque-C", "opaque-D"))
        self.assertEqual(minimum_members(contract), {"opaque-A": 1, "opaque-B": 1, "opaque-C": 2, "opaque-D": 1})
        self.assertFalse(assess_unit(contract, ("opaque-A", "opaque-B", "opaque-C", "opaque-D"))["membership_ready"])

    def test_any_missing_necessary_member_prevents_positive_genericity(self):
        trainer = RoleTrainer(NetworkConfig(hidden_dim=16))
        for members in (("opaque-A",), ("opaque-B",)):
            group = Group("partial", Factors("group"), members, unit=self.contract)
            example = replace(self.example, groups=(group,), relations=())
            self.assertFalse(assess_unit(self.contract, members)["membership_ready"])
            with self.assertRaisesRegex(FactorContractError, "never broadcast"):
                trainer.train_supervised((example,), (Targets(roles=(("partial", (None, None, None, None, 1)),)),),
                                          (Supervision("engineering_fixture", "synthetic invalid projection"),))
        self.assertEqual(trainer.steps, 0)

    def test_excess_members_are_not_silently_called_the_minimum_generic_unit(self):
        result = assess_unit(self.contract, ("opaque-A", "opaque-B", "unnecessary-X"))
        self.assertTrue(result["membership_ready"])
        self.assertFalse(result["exact_minimum"])
        self.assertEqual(result["excess_members"], {"unnecessary-X": 1})

    def test_unknown_dependency_review_or_conditions_remain_unverified(self):
        contracts = (replace(self.contract, reviewed_members=("opaque-A",)),
                     replace(self.contract, conditions=(KnownCondition("window", "unknown", "not checked"),)),
                     replace(self.contract, conditions=(KnownCondition("window", "unsatisfied", "synthetic failure"),)))
        for contract in contracts:
            self.assertFalse(assess_unit(contract, ("opaque-A", "opaque-B"))["membership_ready"])

    def test_a_member_other_function_is_a_separate_query_not_a_global_card_label(self):
        other = synthetic_contract(self.example.context_ref, ("opaque-B",), key="independent-other-function")
        other = replace(other, function_ref="a different explicitly reviewed function")
        self.assertFalse(assess_unit(self.contract, ("opaque-B",))["membership_ready"])
        self.assertTrue(assess_unit(other, ("opaque-B",))["exact_minimum"])
        self.assertEqual(assess_unit(other, ("opaque-B",))["genericity_scope"], "single_card")

    def test_resolve_joint_unit_before_calling_whole_unit_cost_provider(self):
        calls = []
        def provider(members):
            calls.append(members)
            return Factors.observed("group", {"resource_cost": len(members) / 10}, source="synthetic whole-package accounting")
        arguments = dict(candidate_ref="new-unit", target_key="new-unit", recall_source="functional gap", factor_provider=provider)
        missing = prepare_function_candidate(self.example, self.contract, ("opaque-A",), **arguments)
        self.assertIsNone(missing["candidate"])
        self.assertFalse(calls)
        complete = prepare_function_candidate(self.example, self.contract, ("opaque-A", "unneeded", "opaque-B"), **arguments)
        self.assertEqual(calls, [("opaque-A", "opaque-B")])
        self.assertEqual(complete["candidate"].example.groups[-1].factors.get("resource_cost").value, 0.2)
        self.assertTrue(complete["assessment"]["exact_minimum"])

    def test_package_and_member_roles_are_never_broadcast(self):
        package = self.records[0]
        example, target, source = package.training_view()
        self.assertEqual(target.roles, ((package.target_key, (None, None, None, None, 1)),))
        trainer = RoleTrainer(NetworkConfig(hidden_dim=16))
        trainer.train_supervised((example,), (target,), (source,))
        self.assertEqual(trainer.head_status("role:generic_utility"), "engineering_only")
        result = assess_unit(example.groups[0].unit, example.groups[0].member_refs)
        self.assertTrue(all(member["generic_utility"] is None and not member["inherited_from_package"] for member in result["member_roles"]))

    def test_optional_copies_are_costed_as_the_full_package_not_dropped_at_unit_resolution(self):
        calls = []
        def provider(members):
            calls.append(members)
            return Factors.observed("group", {"resource_cost": len(members) / 10}, source="synthetic complete package cost")
        members = ("opaque-A", "opaque-A", "opaque-A", "opaque-B")
        result = prepare_function_candidate(self.example, self.contract, members, candidate_ref="copies", target_key="copies",
                                            recall_source="synthetic functional gap", factor_provider=provider, proposed_refs=members)
        self.assertEqual(calls, [members])
        self.assertEqual(result["candidate"].example.groups[-1].factors.get("resource_cost").value, 0.4)
        self.assertEqual(result["assessment"]["minimum_members"], {"opaque-A": 1, "opaque-B": 1})
        self.assertEqual(result["assessment"]["excess_members"], {"opaque-A": 2})
        self.assertFalse(result["assessment"]["exact_minimum"])

    def test_gamma_driver_cases_are_explicit_development_labels_not_neural_success(self):
        self.assertEqual([record.role_labels[-1] for record in self.records], [1, 0, 0])
        for i, record in enumerate(self.records):
            self.assertIsNone(record.period_ref)
            self.assertEqual(record.partition, "development")
            self.assertEqual(AnnotationRecord.from_dict(record.to_dict()), record)
            with self.assertRaisesRegex(FactorContractError, "independent evaluation"):
                replace(record, partition="final_eval")
            if i:
                self.assertFalse(assess_unit(record.example.groups[0].unit, record.example.groups[0].member_refs)["membership_ready"])

    def test_untrained_public_outputs_null_even_for_positive_definition_case(self):
        record = self.records[0]
        result = CandidateScorer(RoleTrainer(NetworkConfig(hidden_dim=16))).score_candidates(
            (Candidate("definition", record.example, record.target_key, "user definition case"),), explain=False)[0]
        self.assertTrue(all(value is None for value in result["role_probabilities"].values()))
        self.assertIsNone(result["compatibility_probability"])
        self.assertIsNone(result["advisory_score"])

    def test_opaque_member_renaming_preserves_derived_features(self):
        group = Group("unit", Factors("group"), ("opaque-A", "opaque-B"), unit=self.contract)
        renamed = replace(self.contract, roots=(MemberAmount("new-X"),), reviewed_members=("new-X", "new-Y"),
                          dependencies=(Dependency("new-X", (MemberAmount("new-Y"),), "different audit source"),))
        other = replace(group, member_refs=("new-Y", "new-X"), unit=renamed)
        first = replace(self.example, groups=(group,), relations=())
        second = replace(self.example, groups=(other,), relations=())
        self.assertTrue(torch.equal(encode_batch((first,))["groups"], encode_batch((second,))["groups"]))

    def test_unit_context_and_derived_feature_spoofing_are_rejected(self):
        group = Group("unit", Factors("group"), ("opaque-A", "opaque-B"), unit=self.contract)
        with self.assertRaises(FactorContractError):
            replace(self.example, context_ref="another-context", groups=(group,), relations=())
        with self.assertRaises(FactorContractError):
            Group("spoof", Factors.observed("group", {"unit_joint_dependency": 0}, source="unsupported override"))

    def test_requested_function_enters_features_and_unencoded_function_stays_unknown(self):
        group = Group("unit", Factors("group"), ("opaque-A", "opaque-B"), unit=self.contract)
        other = replace(group, unit=replace(self.contract, function_ref="different explicit function", function_tags=("draw",)))
        first = replace(self.example, groups=(group,), relations=())
        second = replace(self.example, groups=(other,), relations=())
        self.assertFalse(torch.equal(encode_batch((first,))["groups"], encode_batch((second,))["groups"]))
        unknown = replace(group, unit=replace(self.contract, function_tags=()))
        result = CandidateScorer(RoleTrainer(NetworkConfig(hidden_dim=16))).score_candidates(
            (Candidate("unknown-function", replace(first, groups=(unknown,)), "unit", "synthetic"),), explain=False)[0]
        self.assertIn("function_features_unknown", result["abstention_reasons"])
        self.assertIsNone(result["role_probabilities"]["generic_utility"])


if __name__ == "__main__":
    unittest.main()
