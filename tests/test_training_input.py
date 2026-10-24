"""Safe profile/index integration with explicitly synthetic period assets.

No native engine, model update, historical qualification or external driver is
fabricated. The synthetic runtime implements only the host input contract.
"""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from ygo_kito.build_contracts import DeckParts, digest
from ygo_kito.contracts import Versions
from ygo_kito.data_isolation import DataIndex, PURPOSES
from ygo_kito.deck_intake import PERIODS, _environment
from ygo_kito.group_runner import profile_deck
from ygo_kito.training_input import compile_training_inputs, load_training_inputs
from ygo_kito.validation import ContractError
from tests import test_deck_intake as intake_fixtures
from tests.test_construction_logic import fixture_assets

ROOT = Path(__file__).resolve().parents[1]


class SyntheticPeriodAssets:
    """Test-only contract implementation, never a production runtime fallback."""
    def __init__(self, period, entry, intake, workspace):
        self.period_context = deepcopy(entry["context"])
        self.environment = {"environment_id": "synthetic-" + period, "authority": "custom",
            "release_cutoff": entry["context"]["release_cutoff"], "versions": deepcopy(entry["versions"])}
        self.receipt = {"source_commits": {"core": entry["versions"]["core"]}, "resources": {
            "cards": entry["context"]["catalog_sha256"], "banlist": entry["context"]["banlist_sha256"],
            "scripts": entry["versions"]["scripts"], "client_protocol": entry["versions"]["protocol"]}}
        _, (self.rows, self.limits, self.allowed) = _environment(workspace, period, intake["environments"][period])
        self.known = {(digest(b), digest(p)) for part in entry["partitions"].values()
                      for b, p in zip(part["opponent_bindings"], part["profiles"])}
        self.checks = 0

    def assert_training_opponent(self, binding, profile):
        self.checks += 1
        if (digest(binding), digest(profile)) not in self.known:
            raise ContractError("synthetic host has no matching frozen opponent")


class TrainingInputTests(unittest.TestCase):
    def setUp(self):
        fixture = intake_fixtures.DeckIntakeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root, self.intake = fixture.root, fixture.config
        self.policy = json.loads((ROOT / "configs/user-training-input-template-v1.json").read_text(encoding="utf-8"))
        self.policy["source"] = "synthetic_contract_test"
        self.policy["training_input_id"] = "synthetic-three-periods"
        for i, slot in enumerate(self.intake["slots"][3:], 1):
            slot["controller"]["driver_version"] = "synthetic-driver-" + str(i)
        for ordinal, period in enumerate(PERIODS):
            spec, env = self.policy["periods"][period], self.intake["environments"][period]
            spec["versions"] = {"core": "a" * 40, "scripts": "b" * 64, "cards": env["catalog"]["sha256"],
                "protocol": "c" * 64, "card_pool": "native-private-knowledge-v5",
                "banlist": env["banlist_section"] + ":" + env["banlist"]["sha256"]}
            for index, purpose in enumerate(PURPOSES):
                ids = list(range(1, 7)) if purpose == "train" else [7] if purpose == "validation" else [8]
                spec["partitions"][purpose] = {"opponents": [self.binding(period, i) for i in ids],
                    "seeds": [1000 * (ordinal + 1) + index * 100 + 1, 1000 * (ordinal + 1) + index * 100 + 2],
                    "policy_seed": 10000 + ordinal * 10 + index}

    def binding(self, period, ordinal):
        slot = self.intake["slots"][2 + ordinal]
        main = self.intake["slots"][PERIODS.index(period)]["deck"]["content"]
        other = slot["deck"]["content"]
        profile = {"schema_version": 2, "name": "registered-v5-match", "decks": [main["main"], other["main"]],
                   "extras": [main["extra"], other["extra"]], "sides": [main["side"], other["side"]], "adapter_revision": 5}
        return {"slot_id": slot["slot_id"], "binding": {"schema_version": 1, "opponent_id": slot["slot_id"],
            "environment_id": "synthetic-" + period, "registered_record_sha256": digest(slot),
            "opponent_deck_sha256": digest(other), "own_deck_sha256": digest(main), "profile_sha256": digest(profile),
            "driver_version": slot["controller"]["driver_version"], "driver_implementation_sha256": digest("synthetic-code-" + str(ordinal)),
            "source": "engineering_fixture", "controller": "external_llm", "strength_qualified": False,
            "external_provider_verified": False, "model_sha256": None,
            "opponent_deck_content_sha256": digest({z: sorted(c) for z, c in other.items()})}}

    def compile(self):
        return compile_training_inputs(self.intake, self.policy, self.root)

    def load(self):
        manifest = self.compile()
        assets = {p: SyntheticPeriodAssets(p, manifest["periods"][p], self.intake, self.root) for p in PERIODS}
        return load_training_inputs(self.intake, self.policy, self.root, runtime_assets=assets)

    def test_empty_templates_do_not_create_a_runtime_or_training_recipe(self):
        empty = json.loads((ROOT / "configs/user-training-input-template-v1.json").read_text(encoding="utf-8"))
        intake = json.loads((ROOT / "configs/user-deck-intake-template-v1.json").read_text(encoding="utf-8"))
        compiled = compile_training_inputs(intake, empty, self.root)
        self.assertEqual(compiled["status"], "pending_input")
        self.assertFalse(compiled["formal_training_ready"])
        with self.assertRaisesRegex(ContractError, "missing"):
            load_training_inputs(intake, empty, self.root, runtime_assets={})

    def test_real_profile_dtos_and_existing_group_extraction_consume_loaded_period_inputs(self):
        loaded = self.load()
        for period in PERIODS:
            for purpose in PURPOSES:
                out = loaded.for_runner(period, purpose, episode_cursor=1)
                self.assertIsInstance(out["main_deck"], DeckParts)
                self.assertIsInstance(out["versions"], Versions)
                self.assertEqual(profile_deck(out["profile"], 0), out["main_deck"])
                self.assertEqual(out["period_context"]["release_cutoff"], self.intake["environments"][period]["release_cutoff"])
                self.assertEqual(out["input_source"], "synthetic_contract_test")
                self.assertEqual(out["purpose"], purpose)
                self.assertIs(out["assets"], loaded.assets[period])
        with self.assertRaises(ContractError):
            loaded.for_runner("2022-07", "train", episode_cursor=2)

    def test_existing_data_index_freezes_nine_period_partitions_without_fake_episodes(self):
        loaded = self.load()
        index = DataIndex(self.root / "index")
        for period in PERIODS:
            for purpose in PURPOSES:
                dataset = loaded.freeze_partition(index, period, purpose)
                self.assertEqual(dataset["purpose"], purpose)
                self.assertEqual(dataset["versions"], self.policy["periods"][period]["versions"])
        self.assertEqual(index.summary()["datasets"], 9)
        self.assertEqual(index.summary()["artifacts"], 0)
        self.assertEqual(loaded.freeze_partition(index, "2022-07", "train")["purpose"], "train")

    def test_current_unscoped_assets_and_missing_historical_runtimes_are_rejected(self):
        with self.assertRaisesRegex(ContractError, "three actual period-aware"):
            load_training_inputs(self.intake, self.policy, self.root, runtime_assets={})
        _, current = fixture_assets()
        with self.assertRaisesRegex(ContractError, "not explicitly bound"):
            load_training_inputs(self.intake, self.policy, self.root, runtime_assets={p: current for p in PERIODS})

    def test_driver_aliases_and_card_order_cannot_create_a_held_out_opponent(self):
        # Same actual deck and driver with renamed registration is still seen.
        slot = self.intake["slots"][9]  # opponent-07, held-out validation.
        slot["controller"]["driver_version"] = "synthetic-driver-1"
        slot["deck"]["content"]["main"].reverse()
        replacement = self.binding("2022-07", 7)
        replacement["binding"].update(driver_implementation_sha256=digest("synthetic-code-1"), opponent_id="renamed-driver")
        self.policy["periods"]["2022-07"]["partitions"]["validation"]["opponents"] = [replacement]
        with self.assertRaisesRegex(ContractError, "actual opponent version crosses"):
            self.compile()

    def test_game_seeds_cannot_cross_train_validation_final_under_same_physical_versions(self):
        phase = self.policy["periods"]["2022-07"]["partitions"]
        phase["validation"]["seeds"][0] = phase["train"]["seeds"][0]
        with self.assertRaisesRegex(ContractError, "physical runtime seed crosses"):
            self.compile()

    def test_fixture_source_and_wrong_deck_or_runtime_versions_cannot_be_promoted(self):
        self.policy["source"] = "user_supplied"
        with self.assertRaisesRegex(ContractError, "fixture and user-supplied"):
            self.compile()
        self.policy["source"] = "synthetic_contract_test"
        self.policy["periods"]["2022-07"]["versions"]["cards"] = "0" * 64
        with self.assertRaisesRegex(ContractError, "historical sources"):
            self.compile()

    def test_period_assignment_and_exact_profile_hashes_remain_required(self):
        self.intake["slots"][3]["periods"] = ["2022-10", "2026-10"]
        with self.assertRaisesRegex(ContractError, "not assigned"):
            self.compile()
        self.intake["slots"][3]["periods"] = list(PERIODS)
        raw = self.policy["periods"]["2022-07"]["partitions"]["train"]["opponents"][0]["binding"]
        raw["profile_sha256"] = "0" * 64
        with self.assertRaisesRegex(ContractError, "actual received decks/profile"):
            self.compile()

    def test_runtime_receipt_card_facts_and_driver_admission_are_rechecked(self):
        manifest = self.compile()
        assets = {p: SyntheticPeriodAssets(p, manifest["periods"][p], self.intake, self.root) for p in PERIODS}
        assets["2022-07"].receipt["resources"]["scripts"] = "0" * 64
        with self.assertRaisesRegex(ContractError, "resource receipt"):
            load_training_inputs(self.intake, self.policy, self.root, runtime_assets=assets)
        assets["2022-07"].receipt["resources"]["scripts"] = "b" * 64
        assets["2022-07"].rows[1]["alias"] = 2
        with self.assertRaisesRegex(ContractError, "card facts or banlist"):
            load_training_inputs(self.intake, self.policy, self.root, runtime_assets=assets)
        assets["2022-07"].rows[1]["alias"] = 0
        assets["2022-07"].known.clear()
        with self.assertRaisesRegex(ContractError, "no matching frozen opponent"):
            load_training_inputs(self.intake, self.policy, self.root, runtime_assets=assets)

    def test_cached_manifest_and_runtime_changes_cannot_reuse_old_evidence(self):
        loaded = self.load()
        selection = loaded.for_runner("2022-07", "train")
        selection["profile"]["decks"][0].clear()
        self.assertEqual(len(loaded.for_runner("2022-07", "train")["profile"]["decks"][0]), 40)
        loaded.assets["2022-07"].known.clear()
        with self.assertRaisesRegex(ContractError, "no matching frozen opponent"):
            loaded.for_runner("2022-07", "train")
        loaded = self.load()
        loaded.manifest["periods"]["2022-07"]["partitions"]["train"]["seeds"][0] = 123
        with self.assertRaisesRegex(ContractError, "manifest was changed"):
            loaded.for_runner("2022-07", "train")

    def test_old_current_task_cannot_drop_the_historical_cutoff_to_pass(self):
        loaded = self.load()
        task, _ = fixture_assets()
        with self.assertRaisesRegex(ContractError, "preserve.*cutoff"):
            loaded.require_task("2022-07", task)


if __name__ == "__main__":
    unittest.main()
