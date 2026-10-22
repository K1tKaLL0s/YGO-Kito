import copy
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ygo_kito.contracts import DecisionRequest
from ygo_kito.storage import Store
from ygo_kito.validation import ContractError

from tests.fixtures import annotation, card, dataset, request


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "index.sqlite3"
        Store.initialize(self.path)

    def test_import_persists_across_connections_and_is_idempotent(self):
        with Store(self.path) as store:
            self.assertEqual(store.import_dataset(dataset()), (1, 1))
            store.import_dataset(dataset())
        with Store(self.path) as store:
            self.assertEqual(store.get_card(1).names["ja"], "テスト1")
            self.assertEqual(store.annotations(1)[0].display_label, "送墓·特召")
            self.assertEqual(store.connection.execute("SELECT count(*) FROM cards").fetchone()[0], 1)

    def test_ambiguous_multilingual_and_quoted_alias_lookup_is_explicit(self):
        payload = dataset()
        payload["cards"].append(card(2))
        with Store(self.path) as store:
            store.import_dataset(payload)
            self.assertEqual(store.find_name("  TEST card 1  "), (1,))
            self.assertEqual(store.find_name("テスト1"), (1,))
            self.assertEqual(store.find_name("O'Brien fixture"), (1, 2))
            self.assertEqual(store.find_name("' OR 1=1 --"), ())

    def test_conflicting_source_cannot_overwrite_existing_fact(self):
        with Store(self.path) as store:
            store.import_dataset(dataset())
            changed = dataset()
            changed["cards"][0]["effect_texts"]["zh"] = "different content"
            with self.assertRaisesRegex(ContractError, "different content"):
                store.import_dataset(changed)
            self.assertEqual(store.get_card(1).effect_texts, card()["effect_texts"])

    def test_annotation_layers_coexist_without_mutating_facts(self):
        payload = dataset()
        payload["annotations"] = [annotation(layer, layer) for layer in ("fact", "model_inference", "llm_review", "human_correction")]
        with Store(self.path) as store:
            store.import_dataset(payload)
            self.assertEqual({a.layer for a in store.annotations(1)}, {"fact", "model_inference", "llm_review", "human_correction"})
            self.assertEqual(store.get_card(1).effect_texts, card()["effect_texts"])

    def test_import_is_atomic_on_conflict_and_bad_foreign_key(self):
        for failure in ("conflict", "unknown_card"):
            with self.subTest(failure=failure), Store(self.path) as store:
                store.import_dataset(dataset())
                payload = dataset()
                payload["cards"] = [card(2)]
                if failure == "conflict":
                    changed = copy.deepcopy(card())
                    changed["card_type"] = "changed"
                    payload["cards"].append(changed)
                else:
                    payload["annotations"][0]["card_id"] = 999
                with self.assertRaises(ContractError):
                    store.import_dataset(payload)
                self.assertIsNone(store.get_card(2))
                self.assertEqual(store.find_name("Test Card 2"), ())

    def test_run_index_binds_seed_and_all_environment_versions(self):
        context = DecisionRequest.from_dict(request()).context
        with Store(self.path) as store:
            store.record_run(context)
            store.record_run(context)
        with Store(self.path) as store:
            self.assertEqual(store.get_run(context.run_id), context)
            changed = context.to_dict()
            changed["seed"] = 99
            from ygo_kito.contracts import RunContext
            with self.assertRaises(ContractError):
                store.record_run(RunContext.from_dict(changed))

    def test_unknown_schema_or_nonproject_database_is_not_overwritten(self):
        incompatible = Path(self.temp.name) / "other.sqlite3"
        with sqlite3.connect(incompatible) as connection:
            connection.execute("CREATE TABLE valuable (value TEXT)")
            connection.execute("INSERT INTO valuable VALUES ('preserve')")
        with self.assertRaises(ContractError):
            Store.initialize(incompatible)
        with sqlite3.connect(incompatible) as connection:
            self.assertEqual(connection.execute("SELECT * FROM valuable").fetchall(), [("preserve",)])
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA user_version = 99")
        with self.assertRaises(ContractError):
            Store(self.path)

    def test_open_missing_database_does_not_create_it(self):
        missing = Path(self.temp.name) / "missing.sqlite3"
        with self.assertRaises(sqlite3.OperationalError):
            Store(missing)
        self.assertFalse(missing.exists())

    def test_matching_version_in_foreign_database_is_not_mistaken_for_ours(self):
        foreign = Path(self.temp.name) / "foreign.sqlite3"
        with sqlite3.connect(foreign) as connection:
            connection.execute("PRAGMA user_version = 1")
            connection.execute("CREATE TABLE other_application (value TEXT)")
            connection.execute("INSERT INTO other_application VALUES ('keep')")
        for action in (Store.initialize, Store):
            with self.subTest(action=action), self.assertRaisesRegex(ContractError, "does not belong"):
                action(foreign)
        with sqlite3.connect(foreign) as connection:
            self.assertEqual(connection.execute("SELECT * FROM other_application").fetchall(), [("keep",)])

    def test_damaged_database_does_not_report_successful_initialization(self):
        with sqlite3.connect(self.path) as connection:
            connection.execute("DROP TABLE runs")
        with self.assertRaisesRegex(ContractError, "incomplete"):
            Store.initialize(self.path)

    def test_malformed_dataset_versions_sources_and_labels_are_rejected(self):
        for mutation in ("version", "bool_id", "oversized_id", "missing_source", "unknown_layer", "joined_tags", "unknown_field"):
            with self.subTest(mutation=mutation), Store(self.path) as store:
                payload = dataset()
                match mutation:
                    case "version":
                        payload["schema_version"] = 2
                    case "bool_id":
                        payload["cards"][0]["card_id"] = True
                    case "oversized_id":
                        payload["cards"][0]["card_id"] = 2**63
                    case "missing_source":
                        del payload["cards"][0]["source"]
                    case "unknown_layer":
                        payload["annotations"][0]["layer"] = "guessed_fact"
                    case "joined_tags":
                        payload["annotations"][0]["tags"] = ["送墓·特召"]
                    case "unknown_field":
                        payload["cards"][0]["model_guess"] = "must not become a fact"
                with self.assertRaises(ContractError):
                    store.import_dataset(payload)
                self.assertIsNone(store.get_card(1))

