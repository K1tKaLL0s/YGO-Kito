"""Append-only source records and run index in a versioned SQLite database."""

import json
from contextlib import closing
from pathlib import Path
import sqlite3

from .contracts import RunContext
from .data import Annotation, CardRecord
from .validation import ContractError, array, canonical_json, fields

SCHEMA_VERSION = 1
APPLICATION_ID = 0x59474F4B  # YGOK; user_version alone can match unrelated databases.


def _check_schema(connection):
    if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise ContractError("database schema mismatch; explicit migration required")
    if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
        raise ContractError("database does not belong to YGO-Kito")
    expected = {
        "cards": ("card_id", "payload"), "card_names": ("card_id", "normalized"),
        "annotations": ("annotation_id", "card_id", "payload"), "runs": ("run_id", "payload"),
    }
    for table, columns in expected.items():
        actual = tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))
        if actual != columns:
            raise ContractError("database schema is incomplete or incompatible")


class Store:
    def __init__(self, path: Path):
        # mode=rw avoids creating a DB when a read/import command used the wrong path.
        self.connection = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True)
        self.connection.execute("PRAGMA foreign_keys = ON")
        try:
            _check_schema(self.connection)
        except (ContractError, sqlite3.Error):
            self.connection.close()
            raise

    @classmethod
    def initialize(cls, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as connection, connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if version == SCHEMA_VERSION:
                _check_schema(connection)
                return
            if version != 0 or tables:
                raise ContractError("refusing to modify an existing incompatible database")
            # DDL and the version marker commit together.
            connection.execute("BEGIN")
            connection.execute("CREATE TABLE cards (card_id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
            connection.execute("CREATE TABLE card_names (card_id INTEGER NOT NULL REFERENCES cards(card_id), normalized TEXT NOT NULL, PRIMARY KEY(card_id, normalized))")
            connection.execute("CREATE INDEX card_names_lookup ON card_names(normalized)")
            connection.execute("CREATE TABLE annotations (annotation_id TEXT PRIMARY KEY, card_id INTEGER NOT NULL REFERENCES cards(card_id), payload TEXT NOT NULL)")
            connection.execute("CREATE INDEX annotations_card ON annotations(card_id)")
            connection.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.connection.close()

    def _insert(self, table: str, key_column: str, key, payload: dict, *, card_id=None):
        # SQL identifiers come only from internal constants; all input values bind.
        encoded = canonical_json(payload)
        found = self.connection.execute(f"SELECT payload FROM {table} WHERE {key_column} = ?", (key,)).fetchone()
        if found:
            if found[0] != encoded:
                raise ContractError("record ID already exists with different content; preserve source history")
            return
        if card_id is None:
            self.connection.execute(f"INSERT INTO {table} ({key_column}, payload) VALUES (?, ?)", (key, encoded))
        else:
            self.connection.execute(f"INSERT INTO {table} ({key_column}, card_id, payload) VALUES (?, ?, ?)", (key, card_id, encoded))

    def import_dataset(self, dataset: dict) -> tuple[int, int]:
        d = fields(dataset, {"schema_version", "cards", "annotations"})
        if type(d["schema_version"]) is not int or d["schema_version"] != SCHEMA_VERSION:
            raise ContractError("unsupported dataset schema_version")
        cards = tuple(CardRecord.from_dict(c) for c in array(d["cards"], "cards"))
        annotations = tuple(Annotation.from_dict(a) for a in array(d["annotations"], "annotations"))
        with self.connection:
            for card in cards:
                self._insert("cards", "card_id", card.card_id, card.to_dict())
                for name in (*card.names.values(), *card.aliases):
                    self.connection.execute("INSERT OR IGNORE INTO card_names VALUES (?, ?)", (card.card_id, name.strip().casefold()))
            for annotation in annotations:
                if self.get_card(annotation.card_id) is None:
                    raise ContractError("annotation references an unknown card")
                self._insert("annotations", "annotation_id", annotation.annotation_id,
                             annotation.to_dict(), card_id=annotation.card_id)
        return len(cards), len(annotations)

    def get_card(self, card_id: int) -> CardRecord | None:
        row = self.connection.execute("SELECT payload FROM cards WHERE card_id = ?", (card_id,)).fetchone()
        return CardRecord.from_dict(json.loads(row[0])) if row else None

    def find_name(self, name: str) -> tuple[int, ...]:
        # Return every identity, so ambiguous aliases cannot silently choose a card.
        return tuple(row[0] for row in self.connection.execute(
            "SELECT card_id FROM card_names WHERE normalized = ? ORDER BY card_id", (name.strip().casefold(),)
        ))

    def annotations(self, card_id: int) -> tuple[Annotation, ...]:
        return tuple(Annotation.from_dict(json.loads(row[0])) for row in self.connection.execute(
            "SELECT payload FROM annotations WHERE card_id = ? ORDER BY annotation_id", (card_id,)
        ))

    def record_run(self, context: RunContext):
        with self.connection:
            self._insert("runs", "run_id", context.run_id, context.to_dict())

    def get_run(self, run_id: str) -> RunContext | None:
        row = self.connection.execute("SELECT payload FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return RunContext.from_dict(json.loads(row[0])) if row else None
