"""Source-bound static deck audits, separate from historical rules or strength.

No downloading, card-effect inference, registration, provider, or native engine.
The current pinned CDB supplies listing attributes, not historical availability.
"""
from collections import Counter
from pathlib import Path
import hashlib
import sqlite3

from .agent_registry import identifier, parse_ydk
from .build_contracts import digest
from .deck_intake import (PERIODS, _artifact, _date, _sha, read_listing_catalog,
                          read_selected_banlist, cutoff_timing)
from .deck_profile import validate_deck_parts, validate_profile
from .validation import ContractError, array, canonical_json, fields, integer, member, parse_json, text

KINDS = {"catalog": "community_current_catalog_not_historical_pool",
         "banlist": "community_selected_sections_not_official_full_table",
         "releases": "supplied_release_listing_not_official_verified",
         "profile": "repository_engineering_sample_not_user_deck",
         "ydk": "third_party_sample_not_user_deck"}


def _commit(value, label):
    if value is not None and (not isinstance(value, str) or len(value) != 40
                             or any(c not in "0123456789abcdef" for c in value)):
        raise ContractError(label + " must be a full lowercase Git hash or null")


def validate_source_index(value):
    d = fields(value, {"schema_version", "kind", "sources", "periods", "samples"})
    integer(d["schema_version"], "historical source index schema", 1, 1)
    if d["kind"] != "historical-listing-source-index-v1" or not isinstance(d["sources"], dict) or not d["sources"]:
        raise ContractError("explicit historical listing source index required")
    for source_id, source in d["sources"].items():
        identifier(source_id)
        fields(source, {"kind", "dataset_kind", "artifact", "origin"})
        member(source["kind"], "listing source kind", tuple(KINDS))
        if source["dataset_kind"] != KINDS[source["kind"]]:
            raise ContractError("source must retain its explicit non-official sample/evidence kind")
        artifact = fields(source["artifact"], {"path", "sha256", "source"})
        text(artifact["path"], "listing artifact path"); text(artifact["source"], "listing artifact source")
        _sha(artifact["sha256"])
        origin = fields(source["origin"], {"repository", "commit", "path", "url", "git_blob_sha1"})
        for key in ("repository", "path", "url"):
            text(origin[key], "source origin " + key)
        _commit(origin["commit"], "source commit"); _commit(origin["git_blob_sha1"], "source Git blob")
    for period, env in fields(d["periods"], set(PERIODS)).items():
        fields(env, {"release_cutoff", "banlist_effective", "banlist_section", "catalog_source", "banlist_source", "release_source"})
        if env["release_cutoff"] is not None: _date(env["release_cutoff"], "explicit release cutoff")
        if env["banlist_effective"] != period + "-01":
            raise ContractError("audit banlist effective date differs from its period")
        text(env["banlist_section"], "explicit audit banlist section")
        for key, kind in (("catalog_source", "catalog"), ("banlist_source", "banlist"), ("release_source", "releases")):
            if key == "release_source" and env[key] is None: continue
            identifier(env[key])
            if env[key] not in d["sources"] or d["sources"][env[key]]["kind"] != kind:
                raise ContractError("period source reference is absent or has the wrong kind")
    seen = set()
    for sample in array(d["samples"], "listing samples"):
        fields(sample, {"sample_id", "source_id", "profile_seat"})
        identifier(sample["sample_id"]); identifier(sample["source_id"])
        if sample["sample_id"] in seen or sample["source_id"] not in d["sources"]:
            raise ContractError("duplicate sample or missing sample source")
        seen.add(sample["sample_id"])
        kind = d["sources"][sample["source_id"]]["kind"]
        if kind == "profile": integer(sample["profile_seat"], "profile sample seat", 0, 1)
        elif kind != "ydk" or sample["profile_seat"] is not None:
            raise ContractError("sample requires an explicit profile seat or a pinned YDK")
    if not 1 <= len(seen) <= 512:
        raise ContractError("bounded nonempty listing sample set required")
    return parse_json(canonical_json(d))


def source_reference(source_id, source):
    origin, artifact = source["origin"], source["artifact"]
    return {"source_id": source_id, "source_pin": origin["commit"], "source_path": origin["path"],
            "source_url": origin["url"], "artifact_sha256": artifact["sha256"],
            "git_blob_sha1": origin["git_blob_sha1"], "local_path": artifact["path"], "data_license_verified": False}


def _load_source(workspace, source):
    path, raw = _artifact(workspace, source["artifact"])
    blob = source["origin"]["git_blob_sha1"]
    if blob is not None and hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() != blob:
        raise ContractError("source Git blob checksum differs")
    return path, raw


def _release_records(raw, period, env):
    value = fields(parse_json(raw.decode("utf-8")), {"schema_version", "period_id", "release_cutoff", "cards"})
    integer(value["schema_version"], "release manifest schema", 1, 1)
    if value["period_id"] != period or value["release_cutoff"] != env["release_cutoff"]:
        raise ContractError("release manifest must match its explicit audit period/cutoff")
    result = {}
    for record in array(value["cards"], "release records"):
        fields(record, {"card_id", "ocg_release_date"})
        integer(record["card_id"], "released card ID", 1, 2**32 - 1)
        _date(record["ocg_release_date"], "OCG release date")
        if record["card_id"] in result: raise ContractError("duplicate release record")
        result[record["card_id"]] = record
    return result


def _sample_deck(source, raw, sample):
    locations = {}
    if source["kind"] == "ydk":
        content = raw.decode("utf-8-sig")
        deck = parse_ydk(content)
        zone = None
        for number, line in enumerate(content.splitlines(), 1):
            item = line.strip()
            if item in ("#main", "#extra", "!side"):
                zone = {"#main": "main", "#extra": "extra", "!side": "side"}[item]
            elif item and not item.startswith("#"):
                locations.setdefault(int(item), []).append({"zone": zone, "line": number,
                    "row_sha256": hashlib.sha256(line.encode("utf-8")).hexdigest()})
    else:
        profile = parse_json(raw.decode("utf-8-sig")); validate_profile(profile)
        seat = sample["profile_seat"]
        deck = {"main": profile["decks"][seat], "extra": profile.get("extras", [[], []])[seat],
                "side": profile.get("sides", [[], []])[seat]}
        for zone, key in (("main", "decks"), ("extra", "extras"), ("side", "sides")):
            for offset, code in enumerate(deck[zone]):
                locations.setdefault(code, []).append({"zone": zone, "json_pointer": f"/{key}/{seat}/{offset}",
                                                      "row_sha256": digest(code)})
    for zone in ("main", "extra", "side"):
        for code in deck[zone]: integer(code, "sample card ID", 1, 2**32 - 1)
    return deck, locations


def _period_sources(index, workspace, loaded, period, env):
    report, result = {"release_cutoff": env["release_cutoff"], "banlist_effective": env["banlist_effective"],
                      "banlist_section": env["banlist_section"], "sources": {}, "unmet": [],
                      "cutoff_timing": cutoff_timing(env["release_cutoff"])}, {}
    for key in ("catalog_source", "banlist_source", "release_source"):
        source_id = env[key]
        if source_id is None:
            report["sources"][key] = {"status": "not_supplied"}
            report["unmet"].append("release source not supplied")
            continue
        source = index["sources"][source_id]
        try:
            if source_id not in loaded: loaded[source_id] = _load_source(workspace, source)
            _, raw = loaded[source_id]
            if key == "catalog_source":
                result["catalog"] = read_listing_catalog(workspace, source["artifact"])
            elif key == "banlist_source":
                result["banlist"] = read_selected_banlist(workspace, source["artifact"], env["banlist_section"])
            else:
                result["releases"] = _release_records(raw, period, env)
            report["sources"][key] = dict(source_reference(source_id, source), status="artifact_checked_not_official_authenticated")
        except (OSError, ContractError, sqlite3.Error, UnicodeError) as error:
            report["sources"][key] = {"status": "unavailable" if isinstance(error, OSError) else "invalid",
                "source_id": source_id, "reason": str(error) if isinstance(error, ContractError) else "source artifact unavailable or malformed"}
            report["unmet"].append(key + " unavailable or invalid")
    if env["release_cutoff"] is None: report["unmet"].append("release cutoff not supplied")
    elif not report["cutoff_timing"]["cutoff_reached"]:
        report["unmet"].append("selected OCG cutoff has not arrived in Asia/Tokyo; staging only")
    return report, result


def _evidence(index, source_id, row):
    return dict(source_reference(source_id, index["sources"][source_id]), row_sha256=digest(row),
                source_authenticity_verified=False, card_effects_inferred=False)


def _check_deck(index, period, env, assets, deck, source_id, locations):
    rows, limits, release = assets.get("catalog"), assets.get("banlist"), assets.get("releases")
    counts = Counter(deck["main"] + deck["extra"] + deck["side"])
    unknown = sorted(set(counts) - (rows.keys() if rows is not None else set()))
    structure = {"status": "unverified_catalog_unavailable"}
    if not 40 <= len(deck["main"]) <= 60 or len(deck["extra"]) > 15 or len(deck["side"]) > 15:
        structure = {"status": "rejected", "reason": "section sizes outside existing listing limits"}
    elif rows is not None:
        try:
            validate_deck_parts(deck, rows, {})
            structure = {"status": "valid_under_pinned_catalog_and_standard_copy_limit"}
        except ContractError as error:
            structure = {"status": "unverified_unknown_catalog_cards" if unknown else "rejected", "reason": str(error)}
    totals = Counter()
    if rows is not None:
        for code, count in counts.items():
            if code in rows: totals[rows[code]["alias"] or code] += count
    violations = []
    if limits is not None and rows is not None:
        violations = [{"alias_card_id": code, "count": count, "limit": limits.get(code, 3),
                       "evidence": _evidence(index, env["banlist_source"], {"card_id": code, "limit": limits[code]})
                                   if code in limits else {"rule": "standard_combined_copy_limit_3"}}
                      for code, count in sorted(totals.items()) if count > limits.get(code, 3)]
    banlist = {"status": "rejected" if violations else "unverified_source_unavailable" if limits is None or rows is None
               else "unverified_unknown_catalog_cards" if unknown else "checked_under_selected_community_section",
               "violations": violations}
    unknown_release, after_cutoff, not_yet_released, card_rows = [], [], [], []
    timing = cutoff_timing(env["release_cutoff"])
    today = _date(timing["as_of_date"], "current Japan date")
    cutoff = _date(env["release_cutoff"], "explicit release cutoff") if env["release_cutoff"] is not None else None
    for code in sorted(counts):
        row = {"card_id": code, "count": counts[code], "zones": {zone: deck[zone].count(code) for zone in deck},
               "catalog_status": "known_in_pinned_catalog" if rows is not None and code in rows else "unknown_in_catalog",
               "available_in_period": False, "released_as_of_jst": False}
        row["deck_evidence"] = dict(source_reference(source_id, index["sources"][source_id]),
                                    occurrences=locations[code], card_effects_inferred=False)
        if rows is not None and code in rows:
            row["catalog_evidence"] = _evidence(index, env["catalog_source"], rows[code])
        entry = release.get(code) if release is not None else None
        if entry is None:
            unknown_release.append(code); row["release_status"] = "unknown_release_date"
        else:
            row["release_evidence"] = _evidence(index, env["release_source"], entry)
            row["ocg_release_date"] = entry["ocg_release_date"]
            released = _date(entry["ocg_release_date"], "OCG release date")
            row["released_as_of_jst"] = released <= today
            if cutoff is not None and released > cutoff:
                after_cutoff.append(code)
            if released > today:
                not_yet_released.append(code)
                row["release_status"] = "not_yet_released_staging_only"
            elif cutoff is None: row["release_status"] = "cutoff_unspecified"
            elif released > cutoff:
                row["release_status"] = "after_cutoff"
            else:
                row["release_status"] = ("within_cutoff_under_supplied_evidence" if timing["cutoff_reached"]
                                         else "candidate_within_future_cutoff_staging_only")
                row["available_in_period"] = (timing["cutoff_reached"] and rows is not None and code in rows
                    and bool(rows[code]["ot"] & 1) and not bool(rows[code]["type"] & 0x4000)
                    and limits is not None and limits.get(rows[code]["alias"] or code, 3) > 0)
        card_rows.append(row)
    release_report = {"status": "cutoff_unspecified" if cutoff is None else "not_yet_released_cards" if not_yet_released
                      else "future_cutoff_staging_only" if not timing["cutoff_reached"]
                      else "after_cutoff_cards" if after_cutoff
                      else "unknown_release_dates" if unknown_release else "checked_under_supplied_release_listing",
                      "unknown_card_ids": unknown_release, "after_cutoff_card_ids": after_cutoff,
                      "not_yet_released_card_ids": not_yet_released}
    rejected = bool(violations or after_cutoff or structure["status"] == "rejected")
    checked = (not rejected and not unknown and timing["cutoff_reached"] and not unknown_release and not not_yet_released
               and structure["status"] == "valid_under_pinned_catalog_and_standard_copy_limit"
               and banlist["status"] == "checked_under_selected_community_section")
    return {"period_id": period, "structure": structure, "catalog_unknown_card_ids": unknown,
            "release": release_report, "banlist": banlist, "rows": card_rows, "cutoff_timing": timing,
            "historical_listing_status": "blocked_cutoff_unspecified" if cutoff is None else
                                         "blocked_future_cutoff_staging_only" if not timing["cutoff_reached"] else
                                         "rejected" if rejected else "checked_under_supplied_evidence" if checked else "unverified",
            "historical_rules_verified": False, "official_sources_verified": False}


def audit_listings(value, workspace):
    """Return separate static findings; an audit completing is not legality."""
    index, workspace = validate_source_index(value), Path(workspace).resolve()
    loaded, periods, assets = {}, {}, {}
    for period, env in index["periods"].items():
        periods[period], assets[period] = _period_sources(index, workspace, loaded, period, env)
    samples = []
    for sample in index["samples"]:
        source_id = sample["source_id"]; source = index["sources"][source_id]
        result = {"sample_id": sample["sample_id"], "dataset_kind": source["dataset_kind"],
                  "source": source_reference(source_id, source), "checks": [], "user_deck": False}
        try:
            if source_id not in loaded: loaded[source_id] = _load_source(workspace, source)
            deck, locations = _sample_deck(source, loaded[source_id][1], sample)
            result.update(status="parsed_static_sample", deck_sha256=digest(deck),
                          section_sizes={zone: len(cards) for zone, cards in deck.items()})
            result["checks"] = [_check_deck(index, period, env, assets[period], deck, source_id, locations)
                                for period, env in index["periods"].items()]
        except (OSError, ContractError, UnicodeError) as error:
            result.update(status="sample_unavailable_or_invalid", reason=str(error) if isinstance(error, ContractError) else "sample artifact unavailable or malformed")
        samples.append(result)
    return {"schema_version": 1, "kind": "source-bound-static-historical-listing-audit",
            "index_sha256": digest(index), "periods": periods, "samples": samples,
            "native_executed": False, "third_party_code_executed": False, "user_decks_received": False,
            "official_sources_verified": False, "historical_rules_verified": False,
            "driver_strength_qualified": False, "formal_training_ready": False}
