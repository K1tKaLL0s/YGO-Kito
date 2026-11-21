"""Read declaration and callback identity from the locked core after initial_effect."""

import json
from pathlib import Path
import sqlite3
import subprocess
from tempfile import TemporaryDirectory

from .build_contracts import digest
from .card_identity import native_card_identity
from .construction_checkpoint import write_json
from .engine import EngineUnavailable
from .native_assets import digest as file_digest, verify_resources


_PROBE = Path(__file__).with_name("resources") / "rules/construction_rule_registrations.cpp"
RULE_DECLARATION_HEADER = _PROBE.with_name("construction_rule_effect.h")
_CALLBACK_ROLES = ("condition", "cost", "target", "operation", "value")


class NativeRegistryError(RuntimeError):
    pass


def _card_data(assets):
    database = assets.root / "engine-src/database/locales/zh-CN/cards.cdb"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        for row in connection.execute("SELECT * FROM datas ORDER BY id"):
            code, alias = row["id"], row["alias"] or row["id"]
            printed, name = assets.native_code_overrides.get(code, (alias, alias))
            level = row["level"]
            link = row["def"] if row["type"] & 0x4000000 else 0
            yield (code, printed if printed != code else 0, row["setcode"] % (1 << 64),
                   row["type"], level & 255, row["attribute"], row["race"], row["atk"], row["def"],
                   (level >> 24) & 255, (level >> 16) & 255, link, name if name != printed else 0)


def _read_row(handle, expected, fields):
    kind, *values = handle.readline().rstrip("\n").split("\t")
    if kind != expected or len(values) != fields:
        raise ValueError(f"invalid {expected} row from the locked core")
    return values


def _read_effect(handle, lua):
    scope, kind, event, area, desc, category, limit, maximum, persistent, *values = _read_row(handle, "registration", 24)
    if scope not in ("card", "field"):
        raise ValueError("invalid registration scope from the locked core")
    callbacks = {}
    for offset, role in enumerate(_CALLBACK_ROLES):
        source, first, last = values[3 * offset:3 * offset + 3]
        if source == "-":
            continue
        name = source.removeprefix("@").removeprefix("./script/").removeprefix("script/")
        callback = dict(file=name, lines=[int(first), int(last)])
        if checksum := lua.script_checksum(name):
            callback["sha256"] = checksum
        callbacks[role] = callback
    return dict(scope=scope, type=int(kind), event=int(event), range=int(area), description=int(desc),
                category=int(category), count_code=int(limit), count_maximum=int(maximum),
                count_persistent=bool(int(persistent)), callbacks=callbacks)


def _read_cards(assets, raw, codes):
    lua = assets.effect_lua_source
    cards = {}
    with raw.open(encoding="utf-8") as handle:
        for code in codes:
            current, printed, name, warnings, registrations = map(int, _read_row(handle, "card", 5))
            if current != code or (printed, name) != native_card_identity(assets.rows, code):
                raise ValueError(f"initialized script identity disagrees with the card catalog for {code}")
            if min(warnings, registrations) < 0:
                raise ValueError("invalid diagnostic or registration count")
            diagnostics = [_read_row(handle, "diagnostic", 1)[0] for _ in range(warnings)]
            native = [_read_effect(handle, lua) for _ in range(registrations)]
            cards[str(code)] = dict(printed_code=printed, rule_name=name, diagnostics=diagnostics, native=native)
        if handle.readline():
            raise ValueError("unexpected cards in the locked core output")
    return cards


def collect_native_registrations(assets, codes, output, *, compiler="g++", raw=None):
    """Initialize the selected cards in isolated core sessions with no duel actions."""
    sources = assets.root / "engine-src"
    library = assets.root / "engine-build/libocgcore.so"
    try:
        if verify_resources(assets.root) != assets.receipt:
            raise NativeRegistryError("locked registration assets changed after binding")
        output.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=output, prefix="registration-build-") as scratch:
            directory = Path(scratch)
            executable = directory / "registrations"
            subprocess.run([compiler, "-std=c++17", "-O2", "-I", sources / "core", "-I", sources / "lua",
                            _PROBE, library, f"-Wl,-rpath,{library.parent}", "-o", executable],
                           capture_output=True, text=True, check=True, timeout=60)
            table = directory / "card-data.tsv"
            with table.open("w", encoding="utf-8") as handle:
                for row in _card_data(assets):
                    handle.write(" ".join(map(str, row)) + "\n")
            path = raw if raw is not None else directory / "registrations.tsv"
            with path.open("w", encoding="utf-8") as handle:
                subprocess.run([executable, sources / "scripts", table],
                               input="\n".join(map(str, codes)), stdout=handle, stderr=subprocess.PIPE,
                               text=True, check=True, timeout=180)
            return _read_cards(assets, path, codes)
    except subprocess.CalledProcessError as error:
        raise NativeRegistryError(f"locked registration probe exited {error.returncode}: {error.stderr.strip()}") from error
    except (OSError, ValueError, EngineUnavailable, sqlite3.Error, subprocess.TimeoutExpired) as error:
        raise NativeRegistryError(f"locked registration probe failed: {error}") from error


class NativeRegistrationSource:
    """Reuse initialized declarations across deck inventories with identical assets."""

    def __init__(self, assets):
        self.assets = assets
        self.directory = assets.workspace / "construction-native-registrations"
        self.binding = dict(schema_version=1, probe_sha256=file_digest(_PROBE),
                            declaration_sha256=file_digest(RULE_DECLARATION_HEADER), resources=assets.receipt,
                            card_identities=digest(assets.native_code_overrides), period=assets.period_context)
        self._cards = {}

    def for_cards(self, codes):
        keys = sorted({str(code) for code in codes}, key=int)
        missing = [key for key in keys if key not in self._cards]
        if missing:
            binding = dict(self.binding, cards=keys)
            path = self.directory / (digest(binding) + ".json")
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                cards = cached["registrations"]
                if (cached["binding"] != binding or sorted(cards, key=int) != keys
                        or cached["registrations_sha256"] != digest(cards)):
                    raise ValueError("registration receipt differs from its binding")
            except (OSError, KeyError, TypeError, ValueError):
                captured = collect_native_registrations(self.assets, tuple(map(int, missing)), self.directory)
                cards = {key: (captured if key in captured else self._cards)[key] for key in keys}
                receipt = dict(binding=binding, registrations=cards, registrations_sha256=digest(cards))
                try:
                    self.directory.mkdir(parents=True, exist_ok=True)
                    with TemporaryDirectory(dir=self.directory, prefix="registration-write-") as scratch:
                        staged = Path(scratch) / path.name
                        write_json(staged, receipt)
                        staged.replace(path)
                except OSError:
                    pass
            self._cards.update(cards)
        return {int(key): self._cards[key] for key in keys}
