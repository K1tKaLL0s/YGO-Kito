"""Public popularity themes, retained as untrusted reference staging only.

This independent JSON adapter does not import deck lists or game datasets.
Collection is an explicit single public GET; parsing itself has no network.
"""
from datetime import date, datetime, timezone
import hashlib
import math
import os
from pathlib import Path
import re
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, HTTPRedirectHandler, build_opener

from .validation import ContractError, canonical_json, member, parse_json, text

ENDPOINT = "https://api.mycard.moe/ygopro/analytics/deck/type"
WINDOWS = ("day", "week", "halfmonth", "month", "season")
SOURCES = ("mycard-athletic",)
MAX_BYTES = 16 * 1024 * 1024
MAX_ROWS = 10000


def request_url(window="day", source="mycard-athletic"):
    member(window, "public popularity window", WINDOWS)
    member(source, "verified public popularity source", SOURCES)
    return ENDPOINT + "?" + urlencode({"type": window, "source": source})


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc(value):
    text(value, "observed collection timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContractError("collection timestamp must be ISO datetime with an explicit timezone") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError("collection timestamp requires an explicit timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _freshness(recent_time, collected_at, window):
    # This date is the field reported by the service, not an inferred start/end
    # of its statistical window or proof that its counters are live.
    match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:$|[T ])", recent_time)
    try: recent = date.fromisoformat(match.group(1)) if match else None
    except ValueError: recent = None
    result = {"reported_recent_date": recent.isoformat() if recent else None,
              "recent_date_age_days": None, "status": "reported_time_unparsed" if recent is None else "collection_time_unknown"}
    if recent is not None and collected_at is not None:
        age = (datetime.fromisoformat(collected_at.replace("Z", "+00:00")).date() - recent).days
        result.update(recent_date_age_days=age,
            status="reported_time_after_collection" if age < 0 else
                   "reported_recent_time_older_than_requested_day" if window == "day" and age > 1 else
                   "reported_recent_time_older_than_collection_date" if age > 1 else
                   "reported_date_near_collection_not_verified_live")
    return result


def stage_themes(raw, *, window="day", source="mycard-athletic", collected_at=None):
    """Parse the evidenced list shape; never guess wrappers or numeric meaning.

    count remains the original string; tags and matchup remain opaque JSON.
    Neither matchup nor count is converted into a win rate or denominator.
    """
    url = request_url(window, source)
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise ContractError("bounded nonempty UTF-8 popularity response bytes required")
    try: payload = parse_json(raw.decode("utf-8"))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ContractError("unsupported popularity JSON encoding or shape") from error
    if not isinstance(payload, list): raise ContractError("unsupported-top-shape: expected the evidenced popularity list")
    if len(payload) > MAX_ROWS: raise ContractError("popularity response exceeds the declared row bound")
    observed = _utc(collected_at) if collected_at is not None else None
    themes = []
    for ordinal, row in enumerate(payload):
        if not isinstance(row, dict) or {"name", "recent_time", "source", "count"} - row.keys():
            raise ContractError("unsupported popularity theme row")
        for key in ("name", "recent_time", "source", "count"):
            text(row[key], "source theme " + key)
            if len(row[key]) > (512 if key == "name" else 128):
                raise ContractError("popularity source scalar exceeds its bound")
        theme = {"source_row": ordinal, "name": row["name"], "recent_time": row["recent_time"],
                 "source": row["source"], "count_raw": row["count"],
                 "freshness": _freshness(row["recent_time"], observed, window),
                 "source_matches_request": row["source"] == source}
        for key in ("tags", "matchup"):
            if key in row: theme[key] = row[key]
        theme["source_record_sha256"] = hashlib.sha256(canonical_json(row).encode("utf-8")).hexdigest()
        themes.append(theme)
    return {"schema_version": 1, "kind": "mycard-popular-theme-staging-v1", "channel": "theme_reference_candidates",
        "status": "staged_pending_source_review", "request": {"url": url, "window": window, "source": source},
        "collection": {"collected_at": observed, "processed_at": _now(),
                       "collection_time_status": "provided_observation" if observed else "unknown_pending"},
        "raw_response": {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)},
        "statistics_window": {"requested_label": window, "reported_start": None, "reported_end": None,
                              "status": "actual_statistical_window_not_established_by_recent_time"},
        "themes": themes, "theme_count": len(themes),
        "review": {"ruleset": None, "banlist_effective": None, "release_cutoff": None,
                   "data_usage_permission": "unknown_pending", "training_admission": "not_applicable_theme_staging"},
        "execution_enabled": False, "formal_training_ready": False,
        "listing_legality_verified": False, "strategy_strength_verified": False}


class PublicFetchStopped(ContractError):
    def __init__(self, receipt):
        self.receipt = receipt
        super().__init__("public popularity fetch stopped; no retry or alternate endpoint")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_public(request, timeout):
    return build_opener(_NoRedirect()).open(request, timeout=timeout)


def _publish(path, raw):
    with path.open("xb") as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())


def fetch_themes(cache_root, *, window="day", source="mycard-athletic", timeout=20):
    """One fixed unauthenticated request, bounded body, immutable raw cache.

    No cookie jar, credentials, redirect, retries, pagination or other endpoint.
    Tests patch the internal standard-library transport; callers cannot supply
    a transport and label its fixture output as an actual public collection.
    """
    url = request_url(window, source)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ContractError("public request timeout must be within (0,60] seconds")
    cache = Path(cache_root).resolve(); cache.mkdir(parents=True, exist_ok=True)
    receipt = {"schema_version": 1, "kind": "mycard-popular-theme-public-fetch-v1", "url": url,
        "window": window, "source": source, "started_at": _now(), "collected_at": None,
        "request_count": 1, "status": "failed", "http_status": None, "retry_allowed": False}
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "YGO-Kito-theme-staging/1"}, method="GET")
    raw = None
    try:
        with _open_public(request, timeout) as response:
            status = response.getcode()
            receipt["http_status"] = status
            if response.geturl() != url or status != 200:
                raise ContractError("unexpected response identity or status")
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES or not raw: raise ContractError("empty or oversized popularity response")
            receipt.update(status="received", collected_at=_now(), content_type=response.headers.get("Content-Type"))
    except HTTPError as error:
        receipt.update(error_type="HTTPError", http_status=error.code,
                       failure="redirect_blocked" if 300 <= error.code < 400 else "http_error")
    except URLError:
        # A proxy tunnel's text is not an origin HTTP response, and may contain
        # private environment details. Preserve its class without echoing it.
        receipt.update(error_type="URLError", failure="transport_error")
    except (OSError, TimeoutError, ContractError) as error:
        receipt.update(error_type=type(error).__name__, failure="bounded_request_failed")
    if receipt["status"] == "received":
        sha = hashlib.sha256(raw).hexdigest(); path = cache / (sha + ".json")
        if path.exists():
            if path.read_bytes() != raw: raise ContractError("existing response cache differs from its content identity")
        else: _publish(path, raw)
        receipt["raw_response"] = {"path": str(path), "sha256": sha, "bytes": len(raw)}
    receipt["finished_at"] = _now()
    metadata = cache / ("fetch-" + secrets.token_hex(12) + ".json")
    _publish(metadata, (canonical_json(receipt) + "\n").encode("utf-8"))
    receipt["metadata_path"] = str(metadata)
    if receipt["status"] != "received": raise PublicFetchStopped(receipt)
    return raw, receipt
