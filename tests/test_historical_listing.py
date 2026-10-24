"""Static synthetic listing evidence and pinned third-party text; no engine."""
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ygo_kito.build_contracts import digest
from ygo_kito.deck_intake import PERIODS
from ygo_kito.historical_listing import KINDS, audit_listings, validate_source_index
from ygo_kito.validation import ContractError, canonical_json, read_json

ROOT = Path(__file__).resolve().parents[1]


class HistoricalListingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.catalog = self.root / "cards.cdb"
        with sqlite3.connect(self.catalog) as db:
            db.execute("CREATE TABLE datas(id INTEGER PRIMARY KEY,alias INTEGER,ot INTEGER,type INTEGER)")
            db.executemany("INSERT INTO datas VALUES(?,?,?,?)", [(code, 0, 1, 17) for code in range(1, 21)] +
                           [(21, 1, 1, 17), (22, 0, 1, 0x41), (23, 0, 1, 0x4011)])
        self.banlist = self.root / "lflist.conf"
        self.banlist.write_text("!2022.7\n1 2\n!2022.10\n1 1\n!2026.10\n1 0\n", encoding="utf-8")
        self.deck = {"main": [code for code in range(1, 21) for _ in range(2)], "extra": [], "side": []}
        self.ydk = self.root / "sample.ydk.txt"
        self.write_deck(self.deck)
        self.index = {"schema_version": 1, "kind": "historical-listing-source-index-v1", "sources": {
            "catalog": self.source("catalog", self.catalog), "banlist": self.source("banlist", self.banlist),
            "sample": self.source("ydk", self.ydk)}, "periods": {},
            "samples": [{"sample_id": "synthetic-static-sample", "source_id": "sample", "profile_seat": None}]}
        for period, cutoff, section in (("2022-07", "2022-09-30", "2022.7"),
                                        ("2022-10", "2022-12-31", "2022.10"), ("2026-10", None, "2026.10")):
            self.index["periods"][period] = {"release_cutoff": cutoff, "banlist_effective": period + "-01",
                "banlist_section": section, "catalog_source": "catalog", "banlist_source": "banlist", "release_source": None}

    def source(self, kind, path):
        return {"kind": kind, "dataset_kind": KINDS[kind],
            "artifact": {"path": path.relative_to(self.root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "source": "explicit-synthetic-unit-source-not-real-historical-data"},
            "origin": {"repository": "synthetic-unit-fixture", "commit": None, "path": path.name,
                       "url": "fixture://synthetic-listing/" + path.name, "git_blob_sha1": None}}

    def write_deck(self, deck):
        self.ydk.write_text("\n".join(["#main", *map(str, deck["main"]), "#extra", *map(str, deck["extra"]),
                                      "!side", *map(str, deck["side"])]) + "\n", encoding="utf-8")

    def refresh(self, key, path):
        self.index["sources"][key] = self.source(self.index["sources"][key]["kind"], path)

    def releases(self, period="2022-07", *, dates=None):
        env = self.index["periods"][period]
        dates = dates if dates is not None else {code: "2020-01-01" for code in range(1, 24)}
        value = {"schema_version": 1, "period_id": period, "release_cutoff": env["release_cutoff"],
                 "cards": [{"card_id": code, "ocg_release_date": day} for code, day in dates.items()]}
        path = self.root / (period + "-release.json")
        path.write_text(canonical_json(value), encoding="utf-8")
        key = "release-" + period
        self.index["sources"][key] = self.source("releases", path)
        env["release_source"] = key
        return path

    def report(self):
        return audit_listings(self.index, self.root)

    def checks(self):
        return {row["period_id"]: row for row in self.report()["samples"][0]["checks"]}

    def test_missing_release_and_null_cutoff_never_promote_structural_or_banlist_checks(self):
        report = self.report(); checks = self.checks()
        self.assertEqual(checks["2022-07"]["structure"]["status"], "valid_under_pinned_catalog_and_standard_copy_limit")
        self.assertEqual(checks["2022-07"]["historical_listing_status"], "unverified")
        self.assertEqual(checks["2022-07"]["release"]["unknown_card_ids"], list(range(1, 21)))
        self.assertEqual(checks["2026-10"]["historical_listing_status"], "blocked_cutoff_unspecified")
        self.assertEqual(checks["2026-10"]["banlist"]["status"], "rejected")
        for key in ("native_executed", "third_party_code_executed", "user_decks_received", "official_sources_verified",
                    "historical_rules_verified", "formal_training_ready", "driver_strength_qualified"):
            self.assertIs(report[key], False)

    def test_unknown_catalog_and_unknown_release_are_separate_and_names_are_not_evidence(self):
        deck = deepcopy(self.deck); deck["main"][-1] = 999
        self.write_deck(deck); self.refresh("sample", self.ydk)
        self.releases(dates={1: "2020-01-01", 999: "2020-01-01"})
        check = self.checks()["2022-07"]
        self.assertEqual(check["catalog_unknown_card_ids"], [999])
        self.assertNotIn(999, check["release"]["unknown_card_ids"])
        self.assertEqual(check["structure"]["status"], "unverified_unknown_catalog_cards")
        self.assertEqual(check["historical_listing_status"], "unverified")

    def test_explicit_future_release_is_rejected_and_missing_date_is_unknown(self):
        dates = {code: "2020-01-01" for code in range(1, 21)}; dates[20] = "2022-10-01"
        self.releases(dates=dates)
        check = self.checks()["2022-07"]
        self.assertEqual(check["release"]["after_cutoff_card_ids"], [20])
        self.assertEqual(check["historical_listing_status"], "rejected")
        dates.pop(20); self.releases(dates=dates)
        check = self.checks()["2022-07"]
        self.assertEqual(check["release"]["unknown_card_ids"], [20])
        self.assertEqual(check["historical_listing_status"], "unverified")

    def test_complete_supplied_evidence_is_only_listing_check_not_official_or_rules(self):
        self.releases()
        check = self.checks()["2022-07"]
        self.assertEqual(check["historical_listing_status"], "checked_under_supplied_evidence")
        self.assertFalse(check["historical_rules_verified"])
        self.assertFalse(check["official_sources_verified"])
        self.index["periods"]["2022-07"]["release_cutoff"] = "2022-07-01"
        self.assertEqual(self.report()["periods"]["2022-07"]["sources"]["release_source"]["status"], "invalid")
        self.assertEqual(self.checks()["2022-07"]["historical_listing_status"], "unverified")

    def test_three_selected_sections_and_combined_alias_limits_are_independent(self):
        checks = self.checks()
        self.assertEqual(checks["2022-07"]["banlist"]["violations"], [])
        self.assertEqual(checks["2022-10"]["banlist"]["violations"][0]["limit"], 1)
        self.assertEqual(checks["2026-10"]["banlist"]["violations"][0]["limit"], 0)
        deck = deepcopy(self.deck); deck["side"] = [21]
        self.write_deck(deck); self.refresh("sample", self.ydk)
        violation = self.checks()["2022-07"]["banlist"]["violations"][0]
        self.assertEqual((violation["alias_card_id"], violation["count"], violation["limit"]), (1, 3, 2))

    def test_shared_strict_banlist_reader_remains_closed_for_malformed_duplicate_and_missing_section(self):
        for bad in (" 1 0", "garbage", "1", "1 4", "1 2 extra", "1 2\n1 0", "1 2\n!2022.7\n1 3"):
            self.banlist.write_text("!2022.7\n" + bad + "\n", encoding="utf-8"); self.refresh("banlist", self.banlist)
            with self.subTest(bad=bad):
                report = self.report()
                self.assertEqual(report["periods"]["2022-07"]["sources"]["banlist_source"]["status"], "invalid")
                self.assertEqual(report["samples"][0]["checks"][0]["banlist"]["status"], "unverified_source_unavailable")

    def test_source_hash_path_and_git_blob_mismatch_cannot_upgrade_listing(self):
        for mutate in (lambda source: source["artifact"].update(sha256="0" * 64),
                       lambda source: source["artifact"].update(path="../outside.cdb"),
                       lambda source: source["origin"].update(git_blob_sha1="0" * 40)):
            source = self.source("catalog", self.catalog); mutate(source)
            self.index["sources"]["catalog"] = source
            with self.subTest(source=source):
                self.assertEqual(self.report()["periods"]["2022-07"]["sources"]["catalog_source"]["status"], "invalid")
        self.index["sources"]["sample"]["artifact"]["sha256"] = "0" * 64
        sample = self.report()["samples"][0]
        self.assertEqual(sample["status"], "sample_unavailable_or_invalid")
        self.assertEqual(sample["checks"], [])

    def test_row_provenance_has_artifact_and_independent_line_catalog_release_hashes(self):
        self.releases()
        row = self.checks()["2022-07"]["rows"][0]
        self.assertEqual(row["deck_evidence"]["occurrences"][0]["line"], 2)
        self.assertEqual(row["deck_evidence"]["occurrences"][0]["row_sha256"], hashlib.sha256(b"1").hexdigest())
        self.assertEqual(row["catalog_evidence"]["row_sha256"], digest({"id": 1, "alias": 0, "ot": 1, "type": 17}))
        self.assertEqual(row["release_evidence"]["row_sha256"], digest({"card_id": 1, "ocg_release_date": "2020-01-01"}))
        self.assertFalse(row["release_evidence"]["card_effects_inferred"])
        self.assertFalse(row["catalog_evidence"]["source_authenticity_verified"])

    def test_profile_and_ydk_reuse_parsers_and_short_deck_rejected_even_with_unknown_card(self):
        profile = self.root / "profile.json"
        profile.write_text(canonical_json({"schema_version": 1, "name": "synthetic", "decks": [self.deck["main"]] * 2}), encoding="utf-8")
        self.index["sources"]["profile"] = self.source("profile", profile)
        self.index["samples"].append({"sample_id": "profile-seat-1", "source_id": "profile", "profile_seat": 1})
        samples = self.report()["samples"]
        self.assertEqual(samples[0]["deck_sha256"], samples[1]["deck_sha256"])
        self.assertEqual(samples[1]["checks"][0]["rows"][0]["deck_evidence"]["occurrences"][0]["json_pointer"], "/decks/1/0")
        deck = deepcopy(self.deck); deck["main"] = deck["main"][:-2] + [999]
        self.write_deck(deck); self.refresh("sample", self.ydk)
        self.assertEqual(self.checks()["2022-07"]["structure"]["status"], "rejected")

    def test_index_rejects_hidden_switches_false_source_claims_and_duplicate_samples(self):
        for mutate in (lambda index: index.update(native=True),
                       lambda index: index["sources"]["sample"].update(dataset_kind="real-user-mainstream-deck"),
                       lambda index: index["samples"].append(deepcopy(index["samples"][0])),
                       lambda index: index["periods"]["2022-07"].update(release_cutoff="2022-7-1")):
            candidate = deepcopy(self.index); mutate(candidate)
            with self.assertRaises(ContractError): validate_source_index(candidate)

    def test_checked_in_six_third_party_texts_match_git_blobs_and_have_no_user_or_historical_claim(self):
        index = validate_source_index(read_json(ROOT / "configs/historical-listing-sources-v1.json"))
        samples = [sample for sample in index["samples"] if sample["sample_id"].startswith("windbot-")]
        self.assertEqual(len(samples), 6)
        for sample in samples:
            source = index["sources"][sample["source_id"]]; raw = (ROOT / source["artifact"]["path"]).read_bytes()
            self.assertEqual(source["dataset_kind"], "third_party_sample_not_user_deck")
            self.assertEqual(source["origin"]["commit"], "ab963c1cb9776bea4262ae1bba38f541ec70e357")
            self.assertEqual(hashlib.sha256(raw).hexdigest(), source["artifact"]["sha256"])
            self.assertEqual(hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(), source["origin"]["git_blob_sha1"])
        self.assertIsNone(index["periods"]["2026-10"]["release_cutoff"])
        self.assertTrue(all(env["release_source"] is None for env in index["periods"].values()))

    def test_script_writes_only_report_and_explains_static_completion_not_qualification(self):
        from scripts.historical_listing_audit import main
        index_file, output = self.root / "index.json", self.root / "out/report.json"
        index_file.write_text(canonical_json(self.index), encoding="utf-8")
        before = {path.name: path.read_bytes() for path in (self.catalog, self.banlist, self.ydk, index_file)}
        with redirect_stdout(io.StringIO()) as console:
            self.assertEqual(main(["--workspace", str(self.root), "--index", str(index_file), "--output", str(output)]), 0)
        self.assertFalse(json.loads(console.getvalue())["historical_rules_verified"])
        self.assertFalse(read_json(output)["native_executed"])
        self.assertEqual(before, {path.name: path.read_bytes() for path in (self.catalog, self.banlist, self.ydk, index_file)})


if __name__ == "__main__":
    unittest.main()
