"""Local deck/opponent registration. No user decks, paid providers or jobs are preloaded."""

from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .contracts import Versions
from .deck_profile import validate_deck_parts
from .native import banlist_limits
from .native_assets import verify_resources
from .validation import ContractError, array, canonical_json, fields, integer, member, text

APPLICATION_ID = 0x59474F41


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ContractError("invalid resource identifier")
    return value


def parse_ydk(source):
    text(source, "YDK content")
    sections = {"main": [], "extra": [], "side": []}
    section = None
    for line in source.splitlines():
        line = line.strip()
        if line in ("#main", "#extra", "!side"):
            section = {"#main": "main", "#extra": "extra", "!side": "side"}[line]
        elif not line or line.startswith("#"):
            continue
        elif section is None or not line.isascii() or not line.isdigit():
            raise ContractError("invalid YDK section or card ID")
        else:
            sections[section].append(int(line))
    return sections


class OpponentRegistry:
    def __init__(self, state_root, native_root):
        self.root, self.native_root = Path(state_root).resolve(), Path(native_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / "registry.sqlite3"
        if path.is_symlink():
            raise ContractError("registry symlinks are unsupported")
        self.path = path
        with sqlite3.connect(path) as db:
            app = db.execute("PRAGMA application_id").fetchone()[0]
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if tables and app != APPLICATION_ID:
                raise ContractError("file is not an agent registry")
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute("CREATE TABLE IF NOT EXISTS records(kind TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(kind,id))")
            db.execute("CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, kind TEXT, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS controls(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, run_id TEXT, revision INTEGER, result TEXT, UNIQUE(run_id,revision))")
        self._rows = self._limits = self._runtime_versions = None

    def _assets(self, *, refresh=False):
        if refresh:
            self._rows = None
        if self._rows is None:
            receipt = verify_resources(self.native_root)
            source = self.native_root / "engine-src"
            with sqlite3.connect((source / "database/locales/zh-CN/cards.cdb").as_uri() + "?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                self._rows = {r["id"]: dict(r) for r in db.execute("SELECT * FROM datas")}
            self._limits = banlist_limits(source / "client/lflist.conf")
            h = receipt["resources"]
            self._runtime_versions = Versions(receipt["source_commits"]["core"], h["scripts"], h["cards"],
                h["client_protocol"], "native-effect-duel-v1", "2026.10:" + h["banlist"])

    def get(self, kind, record_id):
        identifier(record_id)
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
        if row is None:
            raise ContractError("registered resource not found")
        return json.loads(row[0])

    def put(self, kind, record_id, payload):
        identifier(record_id)
        raw = canonical_json(payload)
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
            if row and row[0] != raw:
                raise ContractError("registered resource conflict; use a new version ID")
            db.execute("INSERT OR IGNORE INTO records VALUES(?,?,?)", (kind, record_id, raw))
        return payload

    def records(self, kind):
        with sqlite3.connect(self.path) as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload FROM records WHERE kind=? ORDER BY id", (kind,))]

    def environment(self, value):
        d = fields(value, {"environment_id", "versions", "authority", "release_cutoff"})
        identifier(d["environment_id"])
        versions = Versions.from_dict(d["versions"])
        member(d["authority"], "environment authority", ("custom", "community", "official"))
        if d["release_cutoff"] is not None:
            try:
                date.fromisoformat(text(d["release_cutoff"], "release cutoff"))
            except ValueError:
                raise ContractError("release cutoff must be an ISO date") from None
        self._assets()
        verified = d["authority"] == "custom" and d["release_cutoff"] is None and versions == self._runtime_versions
        payload = dict(d, validation="custom-runtime-verified" if verified else "pending-environment-validation",
                       historical_rules_verified=False, runtime_compatible=verified)
        return self.put("environment", d["environment_id"], payload)

    def runtime_environment(self):
        self._assets()
        from dataclasses import asdict
        return {"environment_id": "custom-native-current", "versions": asdict(self._runtime_versions),
                "authority": "custom", "release_cutoff": None}

    def import_deck(self, value):
        d = fields(value, {"deck_id", "environment_id", "source", "format", "content"})
        identifier(d["deck_id"])
        member(d["source"], "deck source", ("engineering_fixture", "user_provided", "external_submission"))
        member(d["format"], "deck format", ("ydk", "json"))
        deck = parse_ydk(d["content"]) if d["format"] == "ydk" else fields(d["content"], {"main", "extra", "side"})
        env = self.get("environment", d["environment_id"])
        self._assets()
        limits = self._limits if env["runtime_compatible"] else {}
        validate_deck_parts(deck, self._rows, limits)
        payload = {"deck_id": d["deck_id"], "environment_id": d["environment_id"], "source": d["source"],
                   "cards": deck, "sha256": hashlib.sha256(canonical_json(deck).encode()).hexdigest(),
                   "validation": env["validation"], "runtime_compatible": env["runtime_compatible"] and not deck["extra"],
                   "historical_rules_verified": False, "user_acceptance_verified": False}
        return self.put("deck", d["deck_id"], payload)

    def register_opponent(self, value):
        d = fields(value, {"opponent_id", "deck_id", "controller", "provider", "model", "driver_version"})
        identifier(d["opponent_id"])
        deck = self.get("deck", d["deck_id"])
        member(d["controller"], "controller", ("rule_baseline", "bot", "external_llm"))
        for key in ("provider", "model", "driver_version"):
            text(d[key], key)
        return self.put("opponent", d["opponent_id"], dict(d, environment_id=deck["environment_id"],
            source=deck["source"], provider_verified=False, operation_strength_verified=False,
            training_ready=False, validation="registered-not-end-to-end-verified"))

    def match_configuration(self, opponent_id, own_deck_id, seat):
        integer(seat, "opponent seat", 0, 1)
        opponent = self.get("opponent", opponent_id)
        other = self.get("deck", own_deck_id)
        deck = self.get("deck", opponent["deck_id"])
        if deck["environment_id"] != other["environment_id"]:
            raise ContractError("duel decks bind different environments")
        if not deck["runtime_compatible"] or not other["runtime_compatible"]:
            raise ContractError("environment or extra-deck protocol is not ready for this runtime")
        self._assets(refresh=True)
        environment = self.get("environment", deck["environment_id"])
        if (Versions.from_dict(environment["versions"]) != self._runtime_versions or
                environment["authority"] != "custom" or environment["release_cutoff"] is not None):
            raise ContractError("registered environment versions do not match current runtime")
        decks = [other["cards"]["main"], other["cards"]["main"]]
        decks[seat] = deck["cards"]["main"]
        return {"profile": {"schema_version": 1, "name": "registered-main-deck-match", "decks": decks},
                "opponent": opponent, "versions": environment["versions"], "actor_seat": seat, "training_ready": False}

    def audit(self, kind, value):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO audit(kind,payload) VALUES(?,?)", (kind, canonical_json(value)))

    def control_once(self, request_id, value, execute):
        fingerprint = hashlib.sha256(canonical_json(value).encode()).hexdigest()
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT fingerprint,result FROM controls WHERE id=?", (request_id,)).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise ContractError("control request ID conflict")
                return json.loads(row[1]) if row[1] is not None else {"execution": "uncertain", "retry_allowed": False}
            try:
                db.execute("INSERT INTO controls VALUES(?,?,?,?,NULL)", (request_id, fingerprint, value["run_id"], value["expected_revision"]))
            except sqlite3.IntegrityError:
                raise ContractError("run revision already has a reserved control operation") from None
        try:
            result = execute()
        except Exception:
            self.audit("control-outcome-uncertain", {"request_id": request_id})
            return {"execution": "uncertain", "retry_allowed": False}
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE controls SET result=? WHERE id=?", (canonical_json(result), request_id))
        return result

    def cached_control(self, request_id, value):
        fingerprint = hashlib.sha256(canonical_json(value).encode()).hexdigest()
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT fingerprint,result FROM controls WHERE id=?", (request_id,)).fetchone()
        if row is None:
            return None
        if row[0] != fingerprint:
            raise ContractError("control request ID conflict")
        return json.loads(row[1]) if row[1] is not None else {"execution": "uncertain", "retry_allowed": False}
