"""Historical intake uses synthetic files and listing checks, no native calls."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from ygo_kito.agent_registry import OpponentRegistry
from ygo_kito.deck_intake import PERIODS, SLOTS, _environment, cutoff_timing, prepare_intake, store_intake, validate_intake
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]


class DeckIntakeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.template = json.loads((ROOT / "configs/user-deck-intake-template-v1.json").read_text(encoding="utf-8"))
        self.config = deepcopy(self.template)
        catalog = self.root / "cards.cdb"
        with sqlite3.connect(catalog) as db:
            db.execute("CREATE TABLE datas(id INTEGER PRIMARY KEY,alias INTEGER,ot INTEGER,type INTEGER)")
            db.executemany("INSERT INTO datas VALUES(?,?,?,?)", [(i, 0, 1, 17) for i in range(1, 21)] +
                           [(21, 1, 1, 17), (22, 0, 1, 0x41), (23, 0, 1, 0x4011)])
        self.banlist = self.root / "lflist.conf"
        self.banlist.write_text("\n".join("!" + self.config["environments"][p]["banlist_section"] + "\n1 2" for p in PERIODS), encoding="utf-8")
        for period, env in self.config["environments"].items():
            # Explicit synthetic fixture choices, never production defaults.
            env["release_cutoff"] = {"2022-07": "2022-09-30", "2022-10": "2022-12-31", "2026-10": "2026-10-24"}[period]
            release = self.root / (period + "-releases.json")
            release.write_text(json.dumps({"schema_version": 1, "period_id": period, "release_cutoff": env["release_cutoff"],
                "cards": [{"card_id": code, "ocg_release_date": "2020-01-01"} for code in range(1, 24)]}), encoding="utf-8")
            env.update(catalog=self.artifact(catalog), releases=self.artifact(release), banlist=self.artifact(self.banlist))
        self.deck = {"main": [i for i in range(1, 21) for _ in range(2)], "extra": [], "side": []}
        for slot in self.config["slots"]:
            slot["deck"] = {"format": "json", "content": deepcopy(self.deck), "source": "synthetic-listing-fixture-not-user-deck"}
            if slot["slot_id"].startswith("opponent-"):
                slot["periods"] = list(PERIODS)
                slot["controller"] = {"controller": "external_llm", "provider": "DeepSeek",
                    "model": "explicit-test-model", "driver_version": "explicit-test-driver"}

    def artifact(self, path):
        return {"path": str(path.relative_to(self.root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source": "synthetic-unit-evidence"}

    def prepare(self):
        return prepare_intake(self.config, self.root)

    def alter_release(self, period, mutation):
        path = self.root / self.config["environments"][period]["releases"]["path"]
        data = json.loads(path.read_text(encoding="utf-8"))
        mutation(data)
        path.write_text(json.dumps(data), encoding="utf-8")
        self.config["environments"][period]["releases"] = self.artifact(path)

    def test_blank_template_preserves_eleven_numbers_and_does_not_invent_cards_or_models(self):
        out = prepare_intake(self.template, self.root)
        self.assertEqual([s["slot_id"] for s in out["slots"]], list(SLOTS))
        self.assertEqual(len(out["training_configuration"]["main_decks"]), 3)
        self.assertEqual(len(out["training_configuration"]["opponents"]), 8)
        self.assertFalse(out["complete_user_input"])
        self.assertTrue(all("deck" not in s for s in out["slots"]))
        self.assertTrue(all(s["preferred_provider"] == "DeepSeek" and s["controller"] is None for s in out["slots"][3:]))
        self.assertFalse(out["native_executed"])
        self.assertEqual(self.template["environments"]["2022-07"]["release_cutoff"], "2022-09-30")
        self.assertEqual(self.template["environments"]["2022-10"]["release_cutoff"], "2022-12-31")
        self.assertEqual(self.template["environments"]["2026-10"]["release_cutoff"], "2026-11-01")
        self.assertEqual(self.template["environments"]["2026-10"]["banlist_effective"], "2026-10-01")
        self.assertEqual(self.template["environments"]["2026-10"]["banlist_section"], "2026.10")

    def test_cutoff_is_inclusive_in_japan_and_does_not_claim_a_final_verified_pool(self):
        for moment, reached, day in ((datetime(2026, 10, 31, 14, 59, 59, tzinfo=timezone.utc), False, "2026-10-31"),
                                    (datetime(2026, 10, 31, 15, tzinfo=timezone.utc), True, "2026-11-01")):
            with self.subTest(moment=moment), patch("ygo_kito.deck_intake.datetime") as clock:
                clock.now.side_effect = lambda zone: moment.astimezone(zone)
                state = cutoff_timing("2026-11-01")
                self.assertEqual(state["as_of_date"], day)
                self.assertEqual(state["cutoff_reached"], reached)
                self.assertEqual(state["timezone"], "Asia/Tokyo")
                self.assertTrue(state["inclusive"])
                self.assertFalse(state["final_card_pool_verified"])

    def test_future_cutoff_with_complete_files_stays_pending_and_cannot_be_registered(self):
        env = self.config["environments"]["2026-10"]
        env["release_cutoff"] = "2026-11-01"
        self.alter_release("2026-10", lambda data: data.update(release_cutoff="2026-11-01"))
        with patch("ygo_kito.deck_intake.datetime") as clock:
            clock.now.side_effect = lambda zone: datetime(2026, 10, 25, tzinfo=timezone.utc).astimezone(zone)
            receipt, parsed = _environment(self.root, "2026-10", env)
            self.assertIsNone(parsed)
            self.assertEqual(receipt["status"], "pending")
            self.assertEqual(receipt["cutoff_timing"]["status"], "awaiting_cutoff_date")
            self.assertFalse(self.prepare()["complete_user_input"])
            registry = OpponentRegistry(self.root / "future-state", self.root / "no-runtime")
            with self.assertRaises(ContractError): store_intake(registry, self.config, self.root)
            self.assertEqual(registry.records("deck_intake"), [])

    def test_cutoff_day_still_checks_release_records_sources_and_october_banlist(self):
        env = self.config["environments"]["2026-10"]
        env["release_cutoff"] = "2026-11-01"
        def update(data):
            data["release_cutoff"] = "2026-11-01"
            data["cards"][19]["ocg_release_date"] = "2026-11-01"
            data["cards"][18]["ocg_release_date"] = "2026-11-02"
        self.alter_release("2026-10", update)
        with patch("ygo_kito.deck_intake.datetime") as clock:
            clock.now.side_effect = lambda zone: datetime(2026, 10, 31, 15, tzinfo=timezone.utc).astimezone(zone)
            receipt, (_, limits, allowed) = _environment(self.root, "2026-10", env)
            self.assertIn(20, allowed)
            self.assertNotIn(19, allowed)
            self.assertEqual(limits[1], 2)
            self.assertEqual(receipt["banlist_section"], "2026.10")
            self.assertFalse(receipt["cutoff_timing"]["final_card_pool_verified"])
            env["releases"]["sha256"] = "0" * 64
            self.assertEqual(_environment(self.root, "2026-10", env)[0]["status"], "invalid")
            env["releases"] = None
            self.assertEqual(_environment(self.root, "2026-10", env)[0]["status"], "pending")

    def test_preflight_reports_selected_future_cutoff_without_a_gpu_development_gate(self):
        from ygo_kito.training_preflight import cpu_preflight
        with patch("ygo_kito.deck_intake.datetime") as clock:
            clock.now.side_effect = lambda zone: datetime(2026, 10, 25, tzinfo=timezone.utc).astimezone(zone)
            report = cpu_preflight(self.root / "no-native-resources", json.loads((ROOT / "configs/training-plan-v1.json").read_text()))
        formal = report["formal_training"]
        current = formal["declared_period_cutoffs"]["2026-10"]
        self.assertEqual(current["release_cutoff"], "2026-11-01")
        self.assertEqual(current["banlist_effective"], "2026-10-01")
        self.assertEqual(current["banlist_section"], "2026.10")
        self.assertTrue(current["cutoff_selected"])
        self.assertFalse(current["cutoff_reached"])
        self.assertFalse(current["final_card_pool_verified"])
        self.assertEqual(formal["gpu_validation_phase"], "stage2_training")
        self.assertFalse(formal["gpu_checks_block_software_completion"])
        self.assertFalse(formal["paid_execution_authorized"])
        self.assertFalse(formal["ready"])

    def test_same_intake_keeps_legacy_immutable_identity_across_japan_dates(self):
        registry = OpponentRegistry(self.root / "cross-day-state", self.root / "no-runtime")
        with patch("ygo_kito.deck_intake.datetime") as clock:
            clock.now.side_effect = lambda zone: datetime(2026, 10, 25, tzinfo=timezone.utc).astimezone(zone)
            legacy = self.prepare()
            for environment in legacy["environments"].values(): environment.pop("cutoff_timing")
            registry.put("deck_intake", self.config["intake_id"], legacy)
            self.assertEqual(store_intake(registry, self.config, self.root), legacy)
            clock.now.side_effect = lambda zone: datetime(2026, 10, 26, tzinfo=timezone.utc).astimezone(zone)
            self.assertEqual(store_intake(registry, self.config, self.root), legacy)
            self.assertEqual(len(registry.records("deck_intake")), 1)
            self.assertEqual(self.prepare()["environments"]["2026-10"]["cutoff_timing"]["as_of_date"], "2026-10-26")

    def test_three_supplied_environments_and_all_assignments_check_lists_without_runtime_promotion(self):
        self.config["slots"].reverse()
        out = self.prepare()
        self.assertTrue(out["complete_user_input"])
        self.assertTrue(all(e["status"] == "supplied_listing_evidence_checked" for e in out["environments"].values()))
        self.assertTrue(all(s["status"] == "prepared_runtime_pending" for s in out["slots"]))
        self.assertEqual([s["slot_id"] for s in out["slots"]], list(SLOTS))
        self.assertFalse(out["runtime_compatible"])
        self.assertFalse(out["formal_training_ready"])
        self.assertFalse(out["external_provider_verified"])

    def test_ydk_reuses_existing_parser_and_has_same_deck_digest(self):
        slot = self.config["slots"][0]
        first = self.prepare()["slots"][0]["deck_sha256"]
        slot["deck"].update(format="ydk", content="#main\n" + "\n".join(map(str, self.deck["main"])) + "\n#extra\n!side\n")
        second = self.prepare()
        self.assertEqual(second["slots"][0]["deck_sha256"], first)
        self.assertTrue(second["complete_user_input"])

    def test_release_cutoff_is_distinct_from_banlist_date_and_future_or_unknown_cards_fail_closed(self):
        self.alter_release("2022-07", lambda d: d["cards"][-4].update(ocg_release_date="2022-10-01"))  # Card 20.
        out = self.prepare()
        self.assertEqual(out["slots"][0]["checks"][0]["status"], "listing_rejected")
        self.assertEqual(out["slots"][1]["checks"][0]["status"], "listing_checked_under_supplied_evidence")
        self.assertFalse(out["complete_user_input"])
        self.alter_release("2022-10", lambda d: d["cards"].pop(0))
        self.assertEqual(self.prepare()["slots"][1]["checks"][0]["status"], "listing_rejected")

    def test_period_cutoff_and_release_manifest_cannot_be_silently_relabelled(self):
        self.config["environments"]["2022-07"]["release_cutoff"] = "2022-07-01"
        self.assertEqual(self.prepare()["environments"]["2022-07"]["status"], "invalid")
        self.alter_release("2022-07", lambda d: d.update(release_cutoff="2022-07-01"))
        self.assertEqual(self.prepare()["environments"]["2022-07"]["status"], "supplied_listing_evidence_checked")
        self.alter_release("2022-07", lambda d: d.update(period_id="2022-10"))
        self.assertEqual(self.prepare()["environments"]["2022-07"]["status"], "invalid")

    def test_local_controller_types_require_no_external_provider_or_model(self):
        slot = self.config["slots"][3]
        for kind in ("rule_baseline", "bot"):
            slot["controller"] = {"controller": kind, "provider": None, "model": None, "driver_version": "explicit-local-version"}
            with self.subTest(kind=kind):
                self.assertEqual(self.prepare()["slots"][3]["status"], "prepared_runtime_pending")
        slot["controller"].update(controller="local_snapshot")
        self.assertEqual(self.prepare()["slots"][3]["status"], "pending_or_rejected")
        slot["controller"]["model"] = "explicit-snapshot-identity"
        self.assertEqual(self.prepare()["slots"][3]["status"], "prepared_runtime_pending")
        slot["controller"].update(controller="external_llm")
        self.assertEqual(self.prepare()["slots"][3]["status"], "pending_or_rejected")

    def test_banlist_sections_limits_and_combined_aliases_use_existing_legality(self):
        # Two aliases of card 1 plus its two existing copies violate its limit 2.
        self.config["slots"][0]["deck"]["content"]["side"] = [21, 21]
        self.assertEqual(self.prepare()["slots"][0]["checks"][0]["status"], "listing_rejected")
        self.config["environments"]["2022-10"]["banlist_section"] = "absent-historical-section"
        out = self.prepare()
        self.assertEqual(out["environments"]["2022-10"]["status"], "invalid")
        self.assertFalse(out["complete_user_input"])

    def test_missing_any_historical_resource_or_cutoff_does_not_fall_back_to_current_assets(self):
        for key in ("catalog", "releases", "banlist", "release_cutoff"):
            config = deepcopy(self.config)
            config["environments"]["2026-10"][key] = None
            with self.subTest(key=key):
                out = prepare_intake(config, self.root)
                self.assertEqual(out["environments"]["2026-10"]["status"], "pending")
                self.assertFalse(out["complete_user_input"])

    def test_bad_hashes_missing_files_duplicate_banlist_sections_and_path_escape_are_closed(self):
        config = deepcopy(self.config)
        config["environments"]["2022-07"]["catalog"]["sha256"] = "0" * 64
        self.assertEqual(prepare_intake(config, self.root)["environments"]["2022-07"]["status"], "invalid")
        config["environments"]["2022-07"]["catalog"]["path"] = "missing.cdb"
        self.assertEqual(prepare_intake(config, self.root)["environments"]["2022-07"]["status"], "pending")
        config["environments"]["2022-07"]["catalog"]["path"] = "../outside.cdb"
        self.assertEqual(prepare_intake(config, self.root)["environments"]["2022-07"]["status"], "invalid")
        self.banlist.write_text("!2022.7\n1 2\n!2022.7\n1 3\n", encoding="utf-8")
        self.config["environments"]["2022-07"]["banlist"] = self.artifact(self.banlist)
        self.assertEqual(self.prepare()["environments"]["2022-07"]["status"], "invalid")

    def test_selected_banlist_entries_are_strict_and_never_silently_ignored(self):
        for malformed in (" 1 0", "garbage", "1", "1 nope", "1 -1", "1 4", "1 2 extra", "1 2\n1 0"):
            self.banlist.write_text("!outside\nignore this outside the chosen section\n!2022.7\n" + malformed + "\n", encoding="utf-8")
            self.config["environments"]["2022-07"]["banlist"] = self.artifact(self.banlist)
            with self.subTest(malformed=malformed):
                self.assertEqual(self.prepare()["environments"]["2022-07"]["status"], "invalid")

    def test_incomplete_or_conflicting_slots_fail_and_preparation_never_partially_registers(self):
        registry = OpponentRegistry(self.root / "state", self.root / "not-a-native-runtime")
        with self.assertRaises(ContractError):
            store_intake(registry, self.template, self.root)
        self.assertEqual(registry.records("deck_intake"), [])
        stored = store_intake(registry, self.config, self.root)
        self.assertEqual(registry.get("deck_intake", self.config["intake_id"]), stored)
        for kind in ("deck", "environment", "opponent"):
            self.assertEqual(registry.records(kind), [])
        self.assertEqual(store_intake(registry, self.config, self.root), stored)
        self.config["slots"][0]["deck"]["source"] = "different-source-version"
        with self.assertRaisesRegex(ContractError, "new version ID"):
            store_intake(registry, self.config, self.root)

    def test_strict_input_rejects_unknown_fields_booleans_bad_roles_and_invalid_periods(self):
        for mutation in (lambda c: c.update(native=True), lambda c: c["slots"].pop(),
                         lambda c: c["slots"][0].update(periods=[[]]),
                         lambda c: c["slots"][0].update(slot_id={}),
                         lambda c: c["slots"][0]["deck"]["content"]["main"].__setitem__(0, True),
                         lambda c: c["slots"][0].update(controller={}),
                         lambda c: c["environments"]["2022-07"].update(banlist_effective="2022-10-01")):
            config = deepcopy(self.config)
            mutation(config)
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                validate_intake(config)


if __name__ == "__main__":
    unittest.main()
