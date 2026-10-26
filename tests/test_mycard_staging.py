"""Synthetic public-theme bytes and patched urllib only; no live network."""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from ygo_kito import mycard_staging as staging
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]


def sample(**changes):
    row = {"name": "synthetic-theme", "recent_time": "2026-10-06", "source": "mycard-athletic",
           "count": "00123", "tags": ["synthetic-only"],
           "matchup": {"opponent-theme": {"count": "9", "win": "7", "range": "unknown"}}}
    row.update(changes)
    return row


def encoded(rows=None):
    return json.dumps([sample()] if rows is None else rows, ensure_ascii=False).encode("utf-8")


class Response(io.BytesIO):
    def __init__(self, raw, *, status=200, url=None):
        super().__init__(raw); self.status = status; self.url = url or staging.request_url()
        self.headers = {"Content-Type": "application/json"}
    def getcode(self): return self.status
    def geturl(self): return self.url


class ThemeStagingTests(unittest.TestCase):
    def test_stale_day_and_opaque_statistics_are_preserved_without_strength_claims(self):
        raw = encoded()
        result = staging.stage_themes(raw, collected_at="2026-10-26T10:00:00Z")
        theme = result["themes"][0]
        self.assertEqual(theme["recent_time"], "2026-10-06")
        self.assertEqual(theme["freshness"]["recent_date_age_days"], 20)
        self.assertEqual(theme["freshness"]["status"], "reported_recent_time_older_than_requested_day")
        self.assertEqual(theme["count_raw"], "00123")
        self.assertEqual(theme["matchup"], sample()["matchup"])
        self.assertEqual(result["raw_response"]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertIsNone(result["statistics_window"]["reported_start"])
        self.assertFalse(result["strategy_strength_verified"])
        self.assertFalse(result["listing_legality_verified"])
        self.assertFalse(result["formal_training_ready"])
        self.assertEqual(result["review"]["data_usage_permission"], "unknown_pending")

    def test_offline_processing_never_invents_collection_time_or_statistical_window(self):
        result = staging.stage_themes(encoded(), window="season")
        self.assertIsNone(result["collection"]["collected_at"])
        self.assertEqual(result["themes"][0]["freshness"]["status"], "collection_time_unknown")
        self.assertIsNone(result["themes"][0]["freshness"]["recent_date_age_days"])
        self.assertIsNone(result["statistics_window"]["reported_end"])
        with self.assertRaises(ContractError): staging.stage_themes(encoded(), collected_at="2026-10-26")

    def test_strict_top_shape_and_primary_fields_do_not_guess_wrappers(self):
        for value in ({"data": [sample()]}, None, ["theme"], [dict(sample(), count=123)], [{"name": "only"}]):
            with self.subTest(value=type(value).__name__), self.assertRaises(ContractError):
                staging.stage_themes(json.dumps(value).encode())
        for raw in (b"", b"not-json", b"\xff", b'[NaN]'):
            with self.subTest(raw=raw), self.assertRaises(ContractError): staging.stage_themes(raw)

    def test_windows_sources_and_duplicate_theme_rows_are_not_silently_combined(self):
        for window in staging.WINDOWS:
            self.assertIn("type="+window, staging.request_url(window))
        for args in (("year", "mycard-athletic"), ("day", "unknown-source"), ("day&token=x", "mycard-athletic")):
            with self.assertRaises(ContractError): staging.request_url(*args)
        rows = [sample(), sample(source="another-reported-source", count="4")]
        result = staging.stage_themes(encoded(rows))
        self.assertEqual(result["theme_count"], 2)
        self.assertEqual([r["count_raw"] for r in result["themes"]], ["00123", "4"])
        self.assertFalse(result["themes"][1]["source_matches_request"])

    def test_single_public_get_has_no_auth_and_caches_exact_response_bytes(self):
        raw = encoded(); requests = []
        def opened(request, timeout):
            requests.append(request)
            self.assertEqual(request.full_url, staging.request_url())
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(timeout, 20)
            self.assertFalse({k.lower() for k, _ in request.header_items()} & {"authorization", "cookie", "proxy-authorization"})
            return Response(raw)
        with TemporaryDirectory() as t, patch.object(staging, "_open_public", side_effect=opened):
            returned, receipt = staging.fetch_themes(t)
            self.assertEqual(returned, raw); self.assertEqual(len(requests), 1)
            self.assertEqual(receipt["request_count"], 1)
            self.assertEqual(Path(receipt["raw_response"]["path"]).read_bytes(), raw)
            self.assertEqual(receipt["raw_response"]["sha256"], hashlib.sha256(raw).hexdigest())
            saved = json.loads(Path(receipt["metadata_path"]).read_text())
            self.assertEqual(saved["collected_at"], receipt["collected_at"])
            self.assertEqual(saved["source"], "mycard-athletic")

    def test_http_or_transport_failure_stops_after_one_attempt_without_secret_error_text(self):
        errors = [HTTPError(staging.request_url(), 403, "denied", {}, None),
                  HTTPError(staging.request_url(), 429, "slow", {}, None),
                  URLError("Tunnel connection failed: 403 Forbidden private-proxy-detail")]
        for error in errors:
            with self.subTest(error=type(error).__name__), TemporaryDirectory() as t, \
                    patch.object(staging, "_open_public", side_effect=error) as opened:
                with self.assertRaises(staging.PublicFetchStopped) as raised: staging.fetch_themes(t)
                self.assertEqual(opened.call_count, 1)
                receipt = raised.exception.receipt
                self.assertFalse(receipt["retry_allowed"])
                self.assertEqual(len(list(Path(t).glob("fetch-*.json"))), 1)
                self.assertNotIn("private-proxy-detail", json.dumps(receipt))
                if isinstance(error, URLError) and not isinstance(error, HTTPError): self.assertIsNone(receipt["http_status"])

    def test_redirect_identity_and_response_size_fail_without_followup_request(self):
        for response in (Response(encoded(), status=302), Response(encoded(), url="https://example.invalid/other"), Response(b"")):
            with self.subTest(status=response.status), TemporaryDirectory() as t, \
                    patch.object(staging, "_open_public", return_value=response) as opened:
                with self.assertRaises(staging.PublicFetchStopped): staging.fetch_themes(t)
                self.assertEqual(opened.call_count, 1)
        self.assertIsNone(staging._NoRedirect().redirect_request(None, None, 302, None, None, "https://example.invalid"))
        with TemporaryDirectory() as t, patch.object(staging, "MAX_BYTES", 4), \
                patch.object(staging, "_open_public", return_value=Response(b"12345")):
            with self.assertRaises(staging.PublicFetchStopped): staging.fetch_themes(t)

    def test_cli_offline_is_network_free_and_existing_output_blocks_fetch(self):
        spec = importlib.util.spec_from_file_location("mycard_staging_cli_fixture", ROOT/"scripts/mycard_staging.py")
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        with TemporaryDirectory() as t:
            root = Path(t); source = root/"theme-fixture.json"; source.write_bytes(encoded())
            out = root/"staged.json"
            with patch.object(staging, "_open_public", side_effect=AssertionError("no live network")) as opened:
                self.assertEqual(cli.main(["--input", str(source), "--output", str(out),
                    "--collected-at", "2026-10-26T10:00:00Z"]), 0)
                opened.assert_not_called()
                original = out.read_bytes()
                self.assertEqual(cli.main(["--fetch", "--output", str(out), "--cache-root", str(root/"cache")]), 2)
                opened.assert_not_called(); self.assertEqual(out.read_bytes(), original)
            result = json.loads(out.read_text())
            self.assertFalse(result["network_attempted"])
            self.assertEqual(result["channel"], "theme_reference_candidates")

    def test_received_but_unsupported_shape_retains_collection_receipt(self):
        spec = importlib.util.spec_from_file_location("mycard_shape_cli_fixture", ROOT/"scripts/mycard_staging.py")
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        with TemporaryDirectory() as t, patch.object(staging, "_open_public", return_value=Response(b'{"data":[]}')) as opened:
            out = Path(t)/"blocked.json"
            self.assertEqual(cli.main(["--fetch", "--output", str(out), "--cache-root", str(Path(t)/"cache")]), 2)
            self.assertEqual(opened.call_count, 1)
            result = json.loads(out.read_text())
            self.assertTrue(result["network_attempted"])
            self.assertEqual(result["public_collection"]["status"], "received")
            self.assertIn("unsupported-top-shape", result["error"])
            self.assertTrue(Path(result["public_collection"]["raw_response"]["path"]).is_file())


if __name__ == "__main__": unittest.main()
