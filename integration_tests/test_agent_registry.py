"""Registry validation uses locked card/banlist assets; examples are engineering fixtures."""

import copy
import json
from pathlib import Path
import tempfile
import sqlite3
import unittest

from ygo_kito.agent_registry import OpponentRegistry, parse_ydk
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]
PROFILE = json.loads((ROOT / "configs/effect-duel-v1.json").read_text())


class RegisteredOpponentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = OpponentRegistry(Path(self.temp.name), ROOT / ".cache")
        self.env = self.registry.runtime_environment()
        self.registry.environment(self.env)

    def tearDown(self):
        self.temp.cleanup()

    def deck(self, ident="fixture-deck", environment=None):
        return {"deck_id": ident, "environment_id": environment or self.env["environment_id"], "source": "engineering_fixture",
                "format": "json", "content": {"main": PROFILE["decks"][0], "extra": [], "side": []}}

    def test_ydk_and_json_import_are_equivalent_and_never_become_user_decks(self):
        d = self.deck()
        first = self.registry.import_deck(d)
        ydk = "#created by engineering test\n#main\n" + "\n".join(map(str, d["content"]["main"])) + "\n#extra\n!side\n"
        other = self.registry.import_deck(dict(d, deck_id="fixture-ydk", format="ydk", content=ydk))
        self.assertEqual(first["sha256"], other["sha256"])
        self.assertEqual(first["source"], "engineering_fixture")
        self.assertFalse(first["user_acceptance_verified"])
        self.assertFalse(first["historical_rules_verified"])
        self.assertTrue(first["runtime_compatible"])
        self.assertEqual(len(parse_ydk(ydk)["main"]), 40)

    def test_invalid_size_unknown_card_and_main_side_copy_limits_are_rejected(self):
        for kind in ("size", "unknown", "side-limit"):
            d = self.deck(kind)
            d = copy.deepcopy(d)
            if kind == "size":
                d["content"]["main"].pop()
            elif kind == "unknown":
                d["content"]["main"][0] = 999999999
            else:
                d["content"]["side"] = [26202165]
            with self.subTest(kind=kind), self.assertRaises(ContractError):
                self.registry.import_deck(d)

    def test_aliases_share_combined_limit_from_real_database(self):
        self.registry._assets()
        rows = self.registry._rows
        alias = next(r for r in rows.values() if r["alias"] in rows and r["ot"] & 1 and rows[r["alias"]]["ot"] & 1 and
            not r["type"] & (0x40 | 0x2000 | 0x800000 | 0x4000000) and self.registry._limits.get(r["alias"], 3) == 3)
        d = copy.deepcopy(self.deck("aliases"))
        d["content"]["main"][:4] = [alias["id"], alias["id"], alias["alias"], alias["alias"]]
        with self.assertRaisesRegex(ContractError, "combined copy limit"):
            self.registry.import_deck(d)

    def test_historical_declaration_remains_pending_instead_of_using_today_banlist(self):
        historic = copy.deepcopy(self.env)
        historic.update(environment_id="historic-pending", authority="official", release_cutoff="2022-09-30")
        historic["versions"]["banlist"] = "not-yet-verified-historical"
        self.assertFalse(self.registry.environment(historic)["runtime_compatible"])
        d = copy.deepcopy(self.deck(environment="historic-pending"))
        d["content"]["main"][0] = next(code for code, limit in self.registry._limits.items() if limit == 0 and code in self.registry._rows and
            self.registry._rows[code]["ot"] & 1 and not self.registry._rows[code]["type"] & (0x40 | 0x2000 | 0x800000 | 0x4000000))
        saved = self.registry.import_deck(d)
        self.assertEqual(saved["validation"], "pending-environment-validation")
        self.assertFalse(saved["runtime_compatible"])

    def test_opponent_assignment_preserves_environment_and_is_not_training_verified(self):
        self.registry.import_deck(self.deck())
        op = self.registry.register_opponent({"opponent_id": "fixture-opponent", "deck_id": "fixture-deck", "controller": "external_llm",
            "provider": "local-contract-fixture", "model": "no-external-model", "driver_version": "fixture-v1"})
        self.assertFalse(op["provider_verified"])
        self.assertFalse(op["training_ready"])
        config = self.registry.match_configuration("fixture-opponent", "fixture-deck", 1)
        self.assertEqual(config["profile"]["decks"][1], PROFILE["decks"][0])
        self.assertEqual(config["opponent"]["environment_id"], self.env["environment_id"])
        # Simulate a stale/corrupt ready flag: the actual version binding must still reject it.
        env = self.registry.get("environment", self.env["environment_id"])
        env["versions"]["banlist"] = "stale-runtime-version"
        with sqlite3.connect(self.registry.path) as db:
            db.execute("UPDATE records SET payload=? WHERE kind='environment' AND id=?", (json.dumps(env), self.env["environment_id"]))
        with self.assertRaisesRegex(ContractError, "versions"):
            self.registry.match_configuration("fixture-opponent", "fixture-deck", 1)

    def test_registry_ids_do_not_overwrite_previous_versions(self):
        self.registry.import_deck(self.deck())
        bad = self.deck()
        bad["source"] = "external_submission"
        with self.assertRaises(ContractError):
            self.registry.import_deck(bad)
