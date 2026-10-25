"""Explicit 3+8 deck intake over supplied historical listing evidence.

Reuses the existing YDK parser, banlist-section reader and shared deck checks.
This is preparation, not a historical rule engine or provider registration:
all reports remain runtime/training-unready and no current assets fill gaps.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from contextlib import closing
import hashlib
import sqlite3

from .agent_registry import OpponentRegistry, identifier, parse_ydk
from .build_contracts import digest
from .deck_profile import validate_deck_parts
from .native import banlist_limits
from .native_protocol import NativeError
from .validation import ContractError, array, canonical_json, fields, integer, member, parse_json, text

PERIODS = ("2022-07", "2022-10", "2026-10")
SLOTS = tuple(f"main-{i:02}" for i in range(1, 4)) + tuple(f"opponent-{i:02}" for i in range(1, 9))


def _date(value, label):
    text(value, label)
    try:
        result = date.fromisoformat(value)
    except ValueError as error:
        raise ContractError(label + " requires an explicit ISO date") from error
    if result.isoformat() != value:
        raise ContractError(label + " requires YYYY-MM-DD")
    return result


def cutoff_timing(value):
    """A selected inclusive OCG date is not a verified, released card pool.

    Read the host clock in Japan, independently of the host's local timezone.
    There is deliberately no caller-provided date override in intake/runtime.
    Announcements and public card text are staging data, not release evidence.
    """
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    cutoff = _date(value, "release cutoff") if value is not None else None
    reached = cutoff is not None and cutoff <= today
    return {"release_cutoff": value, "timezone": "Asia/Tokyo", "inclusive": True,
            "as_of_date": today.isoformat(), "cutoff_selected": cutoff is not None,
            "cutoff_reached": reached, "final_card_pool_verified": False,
            "status": "cutoff_not_selected" if cutoff is None else
                      "cutoff_reached_requires_resource_verification" if reached else "awaiting_cutoff_date"}


def _sha(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ContractError("artifact requires a lowercase SHA-256")


def _artifact(workspace, value):
    row = fields(value, {"path", "sha256", "source"})
    text(row["path"], "artifact path")
    text(row["source"], "artifact source")
    _sha(row["sha256"])
    path = (workspace / row["path"]).resolve()
    if not path.is_relative_to(workspace):
        raise ContractError("intake artifacts must stay inside the supplied workspace")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise ContractError("intake artifact checksum differs")
    return path, raw


def validate_intake(value):
    """Accept explicit blanks; never fill user deck, period or model choices."""
    d = fields(value, {"schema_version", "intake_id", "environments", "slots"})
    integer(d["schema_version"], "deck intake schema", 1, 1)
    identifier(d["intake_id"])
    environments = fields(d["environments"], set(PERIODS))
    for period, environment in environments.items():
        env = fields(environment, {"release_cutoff", "banlist_effective", "banlist_section", "catalog", "releases", "banlist"})
        if env["release_cutoff"] is not None:
            _date(env["release_cutoff"], "release cutoff")
        if env["banlist_effective"] != period + "-01":
            raise ContractError("banlist effective date differs from its assigned period")
        text(env["banlist_section"], "explicit banlist section")
        for key in ("catalog", "releases", "banlist"):
            if env[key] is not None:
                artifact = fields(env[key], {"path", "sha256", "source"})
                for name in ("path", "source"):
                    text(artifact[name], "artifact " + name)
                _sha(artifact["sha256"])
    slots = array(d["slots"], "intake slots")
    if len(slots) != 11:
        raise ContractError("exactly main-01..03 and opponent-01..08 are required")
    seen_slots = set()
    for slot in slots:
        fields(slot, {"slot_id", "periods", "deck", "controller", "preferred_provider"})
        identifier(slot["slot_id"])
        if slot["slot_id"] not in SLOTS or slot["slot_id"] in seen_slots:
            raise ContractError("unknown or duplicate intake slot")
        seen_slots.add(slot["slot_id"])
        periods = array(slot["periods"], "explicit slot periods") if slot["periods"] is not None else []
        if any(not isinstance(p, str) or p not in PERIODS for p in periods) or len(set(periods)) != len(periods):
            raise ContractError("unknown or duplicate slot period assignment")
        if slot["preferred_provider"] is not None:
            text(slot["preferred_provider"], "preferred provider")
        if slot["deck"] is not None:
            deck = fields(slot["deck"], {"format", "content", "source"})
            member(deck["format"], "deck format", ("json", "ydk"))
            text(deck["source"], "user deck source reference")
            if deck["format"] == "json":
                parts = fields(deck["content"], {"main", "extra", "side"})
                for zone in parts:
                    for code in array(parts[zone], zone):
                        integer(code, "deck card ID", 1, 2**32 - 1)
            else:
                parse_ydk(deck["content"])
        controller = slot["controller"]
        if slot["slot_id"].startswith("main-"):
            if controller is not None or slot["preferred_provider"] is not None:
                raise ContractError("main-deck slots do not assign an opponent controller")
        elif controller is not None:
            fields(controller, {"controller", "provider", "model", "driver_version"})
            member(controller["controller"], "opponent controller", ("external_llm", "bot", "rule_baseline", "local_snapshot"))
            for key in ("provider", "model", "driver_version"):
                if controller[key] is not None:
                    text(controller[key], key)
    return parse_json(canonical_json(d))


def read_listing_catalog(workspace, artifact):
    """Read the pinned public listing fields without loading a rule engine."""
    catalog, _ = _artifact(Path(workspace).resolve(), artifact)
    with closing(sqlite3.connect(catalog.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = {r["id"]: dict(r) for r in db.execute("SELECT id,alias,ot,type FROM datas")}
    for row in rows.values():
        integer(row["id"], "catalog card ID", 1, 2**32 - 1)
        for key in ("alias", "ot", "type"):
            integer(row[key], "catalog " + key, 0, 2**32 - 1)
    return rows


def read_selected_banlist(workspace, artifact, section):
    """Keep the intake's strict selected-section gate around the legacy reader."""
    text(section, "explicit banlist section")
    banlist, raw = _artifact(Path(workspace).resolve(), artifact)
    active, occurrences, seen_limits = False, 0, set()
    for line in raw.decode("utf-8-sig").splitlines():
        if line.startswith("!"):
            active = line[1:].strip() == section
            occurrences += int(active)
        elif active and line.strip() and not line.lstrip().startswith("#"):
            parts = line.split()
            if (line != line.lstrip() or len(parts) < 2 or
                    any(not part.isascii() or not part.isdecimal() for part in parts[:2]) or
                    (len(parts) > 2 and not parts[2].startswith(("#", "--")))):
                raise ContractError("malformed entry in selected historical banlist section")
            code, limit = map(int, parts[:2])
            integer(code, "banlist card ID", 1, 2**32 - 1)
            integer(limit, "banlist card limit", 0, 3)
            if code in seen_limits:
                raise ContractError("duplicate card entry in selected banlist section")
            seen_limits.add(code)
    if occurrences != 1:
        raise ContractError("exactly one explicit historical banlist section required")
    limits = banlist_limits(banlist, section=section)
    for code, limit in limits.items():
        integer(code, "banlist card ID", 1, 2**32 - 1)
        integer(limit, "banlist card limit", 0, 3)
    return limits


def _environment(workspace, period, env):
    timing = cutoff_timing(env["release_cutoff"])
    missing = [key for key in ("release_cutoff", "catalog", "releases", "banlist") if env[key] is None]
    unmet = ["missing " + key for key in missing]
    if timing["cutoff_selected"] and not timing["cutoff_reached"]:
        unmet.append("selected OCG cutoff has not arrived in Asia/Tokyo; final pool remains pending")
    if unmet:
        return {"status": "pending", "period_id": period, "cutoff_timing": timing, "unmet": unmet}, None
    try:
        _, raw_releases = _artifact(workspace, env["releases"])
        release = fields(parse_json(raw_releases.decode("utf-8")), {"schema_version", "period_id", "release_cutoff", "cards"})
        integer(release["schema_version"], "release manifest schema", 1, 1)
        if release["period_id"] != period or release["release_cutoff"] != env["release_cutoff"]:
            raise ContractError("release manifest period/cutoff differs from the explicit environment")
        cutoff = _date(env["release_cutoff"], "release cutoff")
        allowed, seen = set(), set()
        for card in array(release["cards"], "release records"):
            fields(card, {"card_id", "ocg_release_date"})
            integer(card["card_id"], "released card ID", 1, 2**32 - 1)
            if card["card_id"] in seen:
                raise ContractError("duplicate card release record")
            seen.add(card["card_id"])
            if _date(card["ocg_release_date"], "OCG release date") <= cutoff:
                allowed.add(card["card_id"])
        rows = read_listing_catalog(workspace, env["catalog"])
        limits = read_selected_banlist(workspace, env["banlist"], env["banlist_section"])
        if not allowed or not allowed <= rows.keys():
            raise ContractError("release manifest is empty or contains cards absent from its catalog")
    except OSError:
        return {"status": "pending", "unmet": ["a declared historical artifact is unavailable"]}, None
    except (ContractError, NativeError, sqlite3.Error, UnicodeError, ValueError) as error:
        # Parser messages can contain source fragments; expose a bounded class.
        return {"status": "invalid", "unmet": [str(error) if isinstance(error, ContractError) else "historical artifact format is invalid"]}, None
    receipt = {"status": "supplied_listing_evidence_checked", "period_id": period,
        "release_cutoff": env["release_cutoff"], "banlist_effective": env["banlist_effective"],
        "cutoff_timing": timing,
        "banlist_section": env["banlist_section"], "artifacts": {k: env[k] for k in ("catalog", "releases", "banlist")},
        "official_sources_verified": False, "historical_rules_verified": False, "runtime_compatible": False}
    return receipt, (rows, limits, allowed)


def prepare_intake(value, workspace):
    """Check every explicit assignment; missing data fails closed, without writes."""
    config, workspace = validate_intake(value), Path(workspace).resolve()
    environments, assets = {}, {}
    for period in PERIODS:
        environments[period], assets[period] = _environment(workspace, period, config["environments"][period])
    slots = []
    for slot in sorted(config["slots"], key=lambda s: SLOTS.index(s["slot_id"])):
        result = {"slot_id": slot["slot_id"], "periods": slot["periods"] or [], "checks": [], "unmet": [],
                  "controller": slot["controller"], "runtime_compatible": False, "training_ready": False}
        result["preferred_provider"] = slot["preferred_provider"]
        if slot["deck"] is None:
            result["unmet"].append("user deck not supplied")
        if not slot["periods"]:
            result["unmet"].append("explicit environment assignment not supplied")
        if slot["slot_id"].startswith("opponent-"):
            controller = slot["controller"]
            needed = (("provider", "model", "driver_version") if controller is not None and controller["controller"] == "external_llm"
                      else ("model", "driver_version") if controller is not None and controller["controller"] == "local_snapshot"
                      else ("driver_version",))
            if controller is None or any(controller[key] is None for key in needed):
                result["unmet"].append("opponent controller assignment lacks required fields for its type")
        if slot["deck"] is not None:
            deck = parse_ydk(slot["deck"]["content"]) if slot["deck"]["format"] == "ydk" else slot["deck"]["content"]
            result.update(deck=deck, deck_sha256=digest(deck), source=slot["deck"]["source"])
            for period in result["periods"]:
                if assets[period] is None:
                    result["checks"].append({"period_id": period, "status": "environment_unavailable"})
                    result["unmet"].append("historical evidence unavailable for " + period)
                    continue
                rows, limits, allowed = assets[period]
                try:
                    validate_deck_parts(deck, rows, limits, allowed=allowed)
                    result["checks"].append({"period_id": period, "status": "listing_checked_under_supplied_evidence"})
                except ContractError as error:
                    result["checks"].append({"period_id": period, "status": "listing_rejected", "reason": str(error)})
                    result["unmet"].append("listing rejected for " + period)
        result["status"] = "prepared_runtime_pending" if not result["unmet"] else "pending_or_rejected"
        slots.append(result)
    complete = (all(s["status"] == "prepared_runtime_pending" for s in slots)
                and all(e["status"] == "supplied_listing_evidence_checked" for e in environments.values()))
    training = {"kind": "intake_mapping_not_a_training_recipe", "main_decks": slots[:3], "opponents": slots[3:],
                "environment_ids": list(PERIODS), "formal_training_ready": False,
                "external_provider_verified": False, "driver_strength_verified": False}
    return {"schema_version": 1, "kind": "user-three-main-eight-opponent-intake", "intake_id": config["intake_id"],
        "config_sha256": digest(config), "environments": environments, "slots": slots,
        "complete_user_input": complete, "training_configuration": training,
        "runtime_compatible": False, "formal_training_ready": False, "external_provider_verified": False,
        "official_sources_verified": False, "historical_rules_verified": False, "native_executed": False}


def store_intake(registry, value, workspace):
    """Save one immutable preparation record using the existing registry schema.

    This deliberately does not insert runnable deck/environment/opponent records.
    Existing registration and runtime gates remain authoritative for activation.
    """
    if not isinstance(registry, OpponentRegistry):
        raise ContractError("existing typed opponent registry required")
    prepared = prepare_intake(value, workspace)
    if not prepared["complete_user_input"]:
        raise ContractError("all eleven decks, controller assignments and three historical evidence sets are required before registry storage")
    # Recheck the current clock before every write, but retain the original
    # immutable record format. A new calendar day is not a new intake version.
    for environment in prepared["environments"].values():
        environment.pop("cutoff_timing", None)
    registry.put("deck_intake", prepared["intake_id"], prepared)
    return prepared
