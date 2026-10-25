"""Portable checks of authorized numeric editions; no CDB, engine or training."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import unittest

from ygo_kito.build_contracts import digest
from ygo_kito.deck_intake import SLOTS, validate_intake


ROOT = Path(__file__).resolve().parents[1]
ZONES = ("main", "extra", "side")
EXPECTED_DECK_SHA256 = {
    "main-01-source-v1": "2520a0b227ec0b909c580fdb50da9d83a98fecf6bfeb0f0e28d1319951affc66",
    "main-02-source-v1": "b97fcaddcfae9665ef134356191558f7b6a68eda7e609f0b7f676328f6412bc4",
    "main-03-reference-v1": "340dc6cc39e1e59605e4b8502a878f6f977a9df6fbd5a9f9303d6dac4de325d5",
    "main-03-reference-v2": "83a2d51e28ec0a4f1c669d4137465ec5f252486553024042d8803cce78c89374",
    "opponent-01-runick-source-v1": "f04c604d47417c8ab4e32a9e9a3a410ea6f1518aaadd1c9b7b6485be32f1afb2",
    "opponent-02-floowandereeze-side0-v1": "77fbdc8e737b9b344fd9f87f37effec9609c191fe3e81b71e1067d53f71c346d",
    "opponent-02-floowandereeze-supplement-v2": "6b90b40ee900d6bf7c5e1123a40bc4df2a483c3fec76fe104309559e4409f57f",
    "opponent-03-spright-source-v1": "0612b84f7405ca496726107f93a5e9b3737f6efb7bef5e12e75f6f132ae32592",
    "opponent-04-moonglade-source-v1": "1678960573b72f552a082f747f3f2771a78b2a03199b35549075929d4d15bbe6",
    "opponent-05-mitsurugi-quarantined-v1": "d0f4e5a19e9c5a26d43c1ca1b382c5a6697d18f9bc29fc2cae357e7797a66ee4",
    "opponent-05-mitsurugi-revision-v2": "5e2531a0343a285261a29f484db864c419c070cc63e5974eed32d87eae384d33",
    "opponent-06-doom-z-art-source-v1": "685db3e5f8f254d3319f325e4fa0c8ad39c82469e0f47180f4dab97c76d4be2f",
}
EXPECTED_MITSURUGI_CHANGES = [
    ("main", 15, 14558127, 10045474), ("main", 20, 23434538, 84192580),
    ("main", 23, 13048472, 18176525), ("main", 24, 13048472, 18176525),
    ("main", 29, 45171524, 40543231), ("main", 30, 45171524, 49721684),
    ("main", 35, 24224830, 65681983), ("main", 36, 24224830, 10045474),
    ("main", 39, 40366667, 10045474), ("extra", 12, 90590303, 11398059),
    ("side", 5, 94145021, 84192580), ("side", 6, 94145021, 84192580),
    ("side", 10, 91800273, 24508238), ("side", 12, 41420027, 40605147),
    ("side", 13, 41420027, 40605147),
]


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


class UserDeckDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.intake = load("configs/user-deck-intake-received-v1.json")
        cls.provenance = load("configs/user-deck-received-provenance-v1.json")
        cls.report = load("docs/reports/2026-10-26-user-deck-static-check.json")
        cls.references = {row["reference_id"]: load(row["path"]) for row in cls.provenance["editions"]}
        cls.slots = {row["slot_id"]: row for row in cls.intake["slots"]}
        cls.checks = {row["reference_id"]: row for row in cls.report["listings"]}

    def test_existing_schema_has_three_main_six_received_and_two_unfilled_opponents(self):
        self.assertEqual(validate_intake(self.intake), self.intake)
        self.assertEqual([row["slot_id"] for row in self.intake["slots"]], list(SLOTS))
        periods = {"main-01": "2022-07", "main-02": "2022-10", "main-03": "2026-10",
            "opponent-01": "2022-10", "opponent-02": "2022-10", "opponent-03": "2022-07",
            "opponent-04": "2026-10", "opponent-05": "2026-10", "opponent-06": "2026-10"}
        for slot_id, period in periods.items():
            self.assertEqual(self.slots[slot_id]["periods"], [period])
            self.assertEqual(self.slots[slot_id]["deck"]["format"], "json")
        for slot_id in ("opponent-07", "opponent-08"):
            self.assertIsNone(self.slots[slot_id]["deck"])
            self.assertIsNone(self.slots[slot_id]["periods"])

    def test_numeric_editions_are_pinned_and_selected_lists_preserve_counts_and_order(self):
        self.assertEqual(set(self.references), set(EXPECTED_DECK_SHA256))
        for ref, expected in EXPECTED_DECK_SHA256.items():
            deck = self.references[ref]["deck"]
            self.assertEqual(set(deck), set(ZONES))
            self.assertEqual(digest(deck), expected)
            self.assertEqual(self.references[ref]["normalized_deck_sha256"], expected)
            self.assertTrue(all(type(c) is int and 0 < c < 2**32 for z in ZONES for c in deck[z]))
        for row in self.provenance["slots"]:
            selected = self.slots[row["slot_id"]]["deck"]
            self.assertEqual(selected["content"], self.references[row["reference_id"]]["deck"])
            self.assertEqual(selected["source"], row["reference_path"])
            main_count = 41 if row["slot_id"] in ("opponent-02", "opponent-03") else 40
            self.assertEqual([len(selected["content"][z]) for z in ZONES], [main_count, 15, 15])

    def test_floowandereeze_original_empty_side_is_not_overwritten(self):
        old = self.references["opponent-02-floowandereeze-side0-v1"]
        new = self.references["opponent-02-floowandereeze-supplement-v2"]
        self.assertEqual(old["deck"]["side"], [])
        self.assertEqual(old["deck"]["main"], new["deck"]["main"])
        self.assertEqual(old["deck"]["extra"], new["deck"]["extra"])
        change = next(x for x in self.provenance["authorized_revisions"] if x["revision_id"] == "floowandereeze-side-supplement-v2")
        self.assertEqual(new["deck"]["side"], change["supplemented_side"])
        self.assertEqual(old["edition_status"], "superseded_reference_only")

    def test_mitsurugi_revision_has_only_the_fifteen_exact_authorized_changes(self):
        old = self.references["opponent-05-mitsurugi-quarantined-v1"]
        new = self.references["opponent-05-mitsurugi-revision-v2"]
        self.assertEqual(old["edition_status"], "quarantined_reference_only")
        self.assertFalse(old["training_enabled"])
        self.assertEqual(self.slots["opponent-05"]["deck"]["content"], new["deck"])
        expected = [dict(zone=z, index_1based=i, removed=a, added=b) for z, i, a, b in EXPECTED_MITSURUGI_CHANGES]
        actual = [dict(zone=z, index_1based=i+1, removed=a, added=b) for z in ZONES
            for i, (a, b) in enumerate(zip(old["deck"][z], new["deck"][z])) if a != b]
        self.assertEqual(actual, expected)
        self.assertEqual(Counter(row["zone"] for row in actual), Counter(main=9, extra=1, side=5))
        applied = deepcopy(old["deck"])
        for z, i, old_id, new_id in EXPECTED_MITSURUGI_CHANGES:
            self.assertEqual(applied[z][i-1], old_id)
            applied[z][i-1] = new_id
        self.assertEqual(applied, new["deck"])
        self.assertEqual(len(self.checks[old["reference_id"]]["combined_limit_violations"]), 10)
        self.assertEqual(self.checks[new["reference_id"]]["combined_limit_violations"], [])

    def test_modern_main_is_an_optional_reference_with_only_its_authorized_id_change(self):
        old = self.references["main-03-reference-v1"]["deck"]
        new = self.references["main-03-reference-v2"]["deck"]
        actual = [(z, i+1, a, b) for z in ZONES for i, (a, b) in enumerate(zip(old[z], new[z])) if a != b]
        self.assertEqual(actual, [("extra", 6, 80843006, 11765832)])
        policy = self.provenance["modern_main_policy"]
        self.assertEqual(policy["theme_selection"], "autonomous")
        self.assertFalse(policy["reference_is_exclusive_entry"])
        self.assertFalse(policy["missing_reference_ids_gate_other_themes"])
        self.assertEqual(self.checks["main-03-reference-v2"]["missing_catalog_ids"], [100268022, 101307067])
        self.assertFalse(self.checks["main-03-reference-v2"]["combined_main_extra_side_alias_limits_checked"])
        self.assertTrue(self.checks["main-03-reference-v2"]["known_catalog_id_alias_limits_checked"])
        self.assertTrue(all(c in sum(new.values(), []) for c in (100268022, 101307067)))

    def test_aliases_stay_in_lists_and_resolve_scripts_only_through_recorded_cdb_alias(self):
        scripts = {row["script_id"]: row for row in self.report["primary_script_references"]}
        alias_count = 0
        for ref, row in self.checks.items():
            deck = self.references[ref]["deck"]
            self.assertEqual(digest(deck), EXPECTED_DECK_SHA256[ref])
            for alias in row["alias_mappings"]:
                alias_count += 1
                raw, canonical = alias["submitted_id"], alias["canonical_id"]
                self.assertIn(raw, sum(deck.values(), []))
                self.assertIn(raw, scripts[canonical]["submitted_ids"])
                self.assertTrue(scripts[canonical]["present"])
                self.assertTrue(scripts[canonical]["raw_submitted_id_script_not_required_when_alias"])
        self.assertGreater(alias_count, 0)
        self.assertFalse(self.report["scope"]["numeric_neighbor_mapping_used"])
        self.assertTrue(all(not c["required_primary_scripts_missing"] for c in self.checks.values()))
        self.assertNotIn(100268022, scripts)
        self.assertNotIn(101307067, scripts)

    def test_static_summary_cannot_enable_training_or_replace_release_and_runtime_evidence(self):
        for env in self.intake["environments"].values():
            for key in ("catalog", "releases", "banlist"):
                self.assertIsNone(env[key])
        self.assertTrue(all(row["controller"] is None for row in self.intake["slots"]))
        self.assertTrue(all(self.slots[f"opponent-{i:02}"]["preferred_provider"] == "DeepSeek" for i in range(1, 9)))
        for key in ("training_enabled", "formal_training_ready", "controllers_configured", "external_provider_verified",
                    "source_only_bots_are_runnable", "full_per_card_release_manifest_verified", "card_effects_verified", "native_executed"):
            self.assertFalse(self.provenance["activation"][key])
        self.assertEqual(self.report["summary"]["selected_incomplete_slots"], ["main-03"])
        self.assertEqual(len(self.report["summary"]["selected_static_pass_slots"]), 8)
        for row in self.report["listings"]:
            self.assertFalse(row["full_release_manifest_verified"])
            self.assertFalse(row["card_effects_verified"])
            self.assertFalse(row["runtime_verified"])
            self.assertFalse(row["training_ready"])

    def test_published_sources_are_numeric_derivatives_without_private_identifiers_or_fake_bytes(self):
        paths = ["configs/user-deck-intake-received-v1.json", "configs/user-deck-received-provenance-v1.json",
                 "docs/reports/2026-10-26-user-deck-static-check.json"] + [x["path"] for x in self.provenance["editions"]]
        for relative in paths:
            path = (ROOT / relative).resolve()
            self.assertTrue(path.is_relative_to(ROOT))
            text = path.read_text(encoding="utf-8")
            for forbidden in (".cache/", "library_file_id", "source_library_file_id", "Sentinel_", "##"):
                self.assertNotIn(forbidden, text)
        for ref in self.references.values():
            self.assertFalse(ref["original_attachment_bytes_materialized"])
            self.assertIsNone(ref["original_attachment_bytes_sha256"])
            self.assertFalse(ref["training_enabled"])


if __name__ == "__main__":
    unittest.main()
