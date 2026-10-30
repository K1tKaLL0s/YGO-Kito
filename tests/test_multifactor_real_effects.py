"""Official-text partial observations: contract tests, not engine/role validation."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from ygo_kito.multifactor import FactorContractError, Factors
from ygo_kito.multifactor.semantics import group_from_semantics

FIXTURE = Path(__file__).parent / "fixtures" / "multifactor-real-effect-observations-v1.json"


class MultifactorRealEffectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.samples = {row["key"]: row for row in payload["samples"]}

    def group(self, key):
        row = self.samples[key]
        return group_from_semantics(row["snapshot"], key=key, source_ref=row["official_source"], confidence=1, uncertainty=0)

    def test_ash_response_conditions_are_not_its_search_or_summon_effects(self):
        group = self.group("ash-blossom")
        self.assertEqual(group.factors.get("effect_negate").value, 1)
        self.assertEqual(group.factors.get("effect_once_per_turn").value, 1)
        for name in ("effect_search", "effect_special_summon", "effect_send_grave", "activation_access", "one_card_independence"):
            self.assertIsNone(group.factors.get(name).value, name)
        self.assertTrue(any("costs=" in note and "cost" in note for note in group.notes))

    def test_desires_payment_is_not_resolution_and_piece_risk_stays_unknown(self):
        group = self.group("pot-of-desires")
        self.assertEqual(group.factors.get("effect_draw").value, 1)
        for name in ("effect_send_grave", "resource_cost", "resource_return", "required_brick_fraction", "cross_context_utility"):
            self.assertIsNone(group.factors.get(name).value, name)
        self.assertTrue(any("face_down" in note and "10" in note for note in group.notes))

    def test_branded_scoped_player_lock_is_not_global_compatibility_verdict(self):
        group = self.group("branded-fusion")
        self.assertEqual(group.factors.get("effect_fusion").value, 1)
        self.assertEqual(group.factors.get("effect_player_lock").value, 1)
        for name in ("summon_lock_risk", "goal_contribution", "activation_access", "external_dependency"):
            self.assertIsNone(group.factors.get(name).value, name)
        self.assertTrue(any("whole_turn" in note and "extra_fusion_only" in note for note in group.notes))

    def test_official_examples_have_no_role_labels_full_digest_or_period_approval(self):
        for key, sample in self.samples.items():
            self.assertTrue(sample["official_source"].startswith("https://www.db.yugioh-card.com/yugiohdb/card_search.action?"))
            self.assertNotIn("roles", sample)
            self.assertIsNone(sample["snapshot"]["text_sha256"])
            group = self.group(key)
            self.assertTrue(all("text_digest_unknown" in obs.source for _, obs in group.factors.items))
            self.assertTrue(any("no OCG-period or engine certification" in note for note in group.notes))

    def test_version_unknown_operations_and_costs_do_not_become_effects(self):
        original = self.samples["ash-blossom"]
        snapshot = deepcopy(original["snapshot"])
        snapshot["semantic_version"] = "unseen-schema"
        with self.assertRaises(FactorContractError):
            group_from_semantics(snapshot, key="anything", source_ref=original["official_source"])
        snapshot = deepcopy(original["snapshot"])
        snapshot["effects"][0]["operations"].extend([
            dict(kind="search_or_recover", reason="effect", from_zones=["deck", "grave"], source="ambiguous origins"),
            dict(kind="send_grave", reason="cost", source="payment is not resolution"),
            dict(kind="unrecognized_operation", reason="effect", source="unknown operation"),
        ])
        group = group_from_semantics(snapshot, key="anything", source_ref=original["official_source"])
        self.assertIsNone(group.factors.get("effect_search").value)
        self.assertIsNone(group.factors.get("effect_recover").value)
        self.assertIsNone(group.factors.get("effect_send_grave").value)
        self.assertTrue(any("unsupported_operation" in note for note in group.notes))

    def test_host_measurements_are_explicit_and_semantic_reliability_defaults_are_unclaimed(self):
        row = self.samples["branded-fusion"]
        measured = Factors.observed("group", {"activation_access": 0.6}, source="artificial host measurement; no engine run")
        group = group_from_semantics(row["snapshot"], key="package", source_ref=row["official_source"], measured=measured)
        self.assertEqual(group.factors.get("activation_access").value, 0.6)
        self.assertEqual(group.factors.get("effect_fusion").confidence, 0)
        self.assertEqual(group.factors.get("effect_fusion").uncertainty, 1)
        with self.assertRaisesRegex(FactorContractError, "overwrite"):
            group_from_semantics(row["snapshot"], key="package", source_ref=row["official_source"],
                                 measured=Factors.observed("group", {"effect_fusion": 0}, source="conflicting host assertion"))


if __name__ == "__main__":
    unittest.main()
