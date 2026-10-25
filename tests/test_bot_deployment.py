"""Synthetic inert C# text fixtures, not builds, installed bots or real duels."""

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request

from ygo_kito import bot_deployment as bots
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]


class BotDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.roots = {key: self.root / key for key in bots.PINS}
        self.lock = {"schema_version": 1, "kind": "pinned-maintained-bot-sources-v1", "sources": [], "theme_aliases": {"Alpha": {"labels": ["明确合成名"]}}}
        # Real fixed-source counts are never relaxed by production code. Only
        # this scoped fixture policy replaces counts for its tiny inert sources.
        self.addCleanup(patch.stopall)
        patch.object(bots, "COUNTS", {"ice": (1, 1), "pure": (1, 1), "library": (1, 0), "mobile-config": (0, 0)}).start()
        for ident, (repo, pin) in bots.PINS.items():
            root = self.roots[ident]
            root.mkdir()
            library, mobile = ident == "library", ident == "mobile-config"
            prefix = "libWindbot/" if library else ""
            source = {"source_id": ident, "repository": repo, "commit": pin,
                "scope": "configuration-only" if mobile else "all-text-source-and-resources",
                "license": {"path": "LICENSE", "spdx": "GPL-2.0-only" if mobile else "MIT"},
                "project": None if mobile else prefix + "WindBot.csproj", "files": [], "withheld_binary_resources": [],
                "expected_executor_files": 0 if mobile else 1, "expected_ydk_files": 1 if ident in ("ice", "pure") else 0}
            self.lock["sources"].append(source)
            self.write(ident, "LICENSE", b"Synthetic fixture notice. Not a third-party payload.\n")
            if mobile:
                self.write(ident, "mobile/assets/data/conf/bot.conf", "!明确合成名\nDeck=Alpha Name='Local Fixture'\nFixture only\nTEST_ONLY\n".encode())
            else:
                self.write(ident, prefix + "Game/AI/Decks/AlphaExecutor.cs",
                           b'// [Deck("Ignored", "AI_Other")]\n[Deck("Alpha", "AI_Alpha")] public class AlphaExecutor : DefaultExecutor {}\n')
                self.write(ident, source["project"], b'<Project><ItemGroup><Compile Include="Game\\AI\\Decks\\*.cs" /></ItemGroup></Project>')
                if not library: self.write(ident, "Decks/AI_Alpha.ydk", b"#main\n123\n#extra\n!side\n")

    def write(self, ident, path, raw):
        p = self.roots[ident] / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        source = next(s for s in self.lock["sources"] if s["source_id"] == ident)
        source["files"] = [f for f in source["files"] if f["path"] != path]
        source["files"].append({"path": path, "sha256": hashlib.sha256(raw).hexdigest(),
                              "git_blob_sha1": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(), "bytes": len(raw)})

    def archive(self, name="sources.tar.gz"):
        path = self.root / name
        bots.create_bundle(self.lock, self.roots, path)
        return path

    def test_full_discovery_keeps_origins_and_aliases_while_grouping_identical_bytes(self):
        result = bots.inventory(self.lock, self.roots)
        self.assertEqual(len(result["origins"]), 3)
        self.assertEqual(len(result["byte_identical_implementation_groups"]), 1)
        self.assertEqual(len({r["bot_id"] for r in result["origins"]}), 3)
        self.assertTrue(all(r["configuration_aliases"][0]["display_name"] == "明确合成名" for r in result["origins"]))
        self.assertTrue(all(len(r["deck_resource_candidates"]) == 2 for r in result["origins"]))
        self.assertFalse(result["training_connected"])
        self.assertEqual(result["missing_deck_resources"], [])

    def test_different_fork_implementations_and_deck_variants_are_not_erased(self):
        self.write("pure", "Game/AI/Decks/AlphaExecutor.cs", b'[Deck("Alpha", "AI_Alpha")] class DifferentExecutor : DefaultExecutor {}')
        self.write("pure", "Decks/AI_Alpha.ydk", b"#main\n456\n#extra\n!side\n")
        result = bots.inventory(self.lock, self.roots)
        self.assertEqual(len(result["byte_identical_implementation_groups"]), 2)
        self.assertTrue(all(r["resource_binding_status"] == "explicit_variant_required" for r in result["origins"]))

    def test_missing_or_extra_executor_and_changed_source_bytes_fail(self):
        path = self.roots["ice"] / "Game/AI/Decks/AlphaExecutor.cs"
        original = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(ContractError, "file set differs"): bots.inventory(self.lock, self.roots)
        path.write_bytes(original + b" ")
        with self.assertRaisesRegex(ContractError, "byte identity differs"): bots.inventory(self.lock, self.roots)
        path.write_bytes(original)
        extra = path.with_name("SecretExecutor.cs")
        extra.write_bytes(original)
        with self.assertRaisesRegex(ContractError, "file set differs"): bots.inventory(self.lock, self.roots)

    def test_subsets_conditional_compile_and_external_policy_only_are_rejected(self):
        for project in (b'<Project><ItemGroup><Compile Include="Game/AI/Decks/Other.cs" /></ItemGroup></Project>',
            b'<Project><ItemGroup Condition="false"><Compile Include="Game/AI/Decks/*.cs" /></ItemGroup></Project>',
            b'<Project><ItemGroup Condition="ExternalPolicyOnly"><Compile Include="Game/AI/Decks/*.cs" /></ItemGroup></Project>'):
            with self.subTest(project=project):
                self.write("ice", "WindBot.csproj", project)
                with self.assertRaises(ContractError): bots.inventory(self.lock, self.roots)

    def test_unparsed_or_out_of_scope_deck_declarations_are_not_silently_skipped(self):
        self.write("ice", "Game/AI/Decks/AlphaExecutor.cs", b'[Deck(NAME, "AI_Alpha")] class AlphaExecutor : DefaultExecutor {}')
        with self.assertRaisesRegex(ContractError, "unparsed"): bots.inventory(self.lock, self.roots)

    def test_configuration_only_scope_does_not_accept_gpl_client_source(self):
        self.write("mobile-config", "Client.cs", b"inert extra client fixture")
        with self.assertRaisesRegex(ContractError, "GPL client"): bots.inventory(self.lock, self.roots)

    def test_wrong_pin_license_counts_and_paths_fail_before_loading(self):
        for key, value in (("commit", "0" * 40), ("expected_executor_files", 0), ("license", {"path": "LICENSE", "spdx": "unknown"})):
            bad = deepcopy(self.lock)
            bad["sources"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ContractError): bots.validate_lock(bad)
        bad = deepcopy(self.lock)
        bad["sources"][0]["files"][0]["path"] = "../outside"
        with self.assertRaises(ContractError): bots.validate_lock(bad)

    def test_source_symlink_is_rejected(self):
        path = self.roots["ice"] / "LICENSE"
        target = self.root / "same-notice"
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
        with self.assertRaises(ContractError): bots.inventory(self.lock, self.roots)

    def test_deterministic_packet_verification_install_and_typed_registry(self):
        first, second = self.archive(), self.archive("other.tar.gz")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertFalse(bots.verify_bundle(first, self.lock)["runtime_ready"])
        destination = self.root / "source-install"
        receipt = bots.install_sources(first, self.lock, destination)
        self.assertEqual(receipt["state"], "prepared")
        registry = bots.BotSourceRegistry(self.lock, destination)
        states = registry.statuses()
        self.assertEqual(len(states), 3)
        self.assertTrue(all(s.source_state == bots.PreparationState.LOADED for s in states))
        self.assertTrue(all(not s.runtime_loaded and not s.normal_duel_verified and not s.strength_verified and not s.history_verified for s in states))
        with self.assertRaisesRegex(ContractError, "missing loopback YGOPro game-host"):
            registry.training_adapter(states[0].bot_id)
        with self.assertRaisesRegex(ContractError, "no overwrite"): bots.install_sources(first, self.lock, destination)

    def test_loaded_registry_rechecks_source_and_memory_seals(self):
        destination = self.root / "loaded"
        bots.install_sources(self.archive(), self.lock, destination)
        registry = bots.BotSourceRegistry(self.lock, destination)
        registry.inventory["training_connected"] = True
        with self.assertRaisesRegex(ContractError, "metadata changed"): registry.statuses()
        registry = bots.BotSourceRegistry(self.lock, destination)
        (destination / "ice/LICENSE").write_bytes(b"changed")
        with self.assertRaises(ContractError): registry.resolve(next(iter(registry._by_id)))

    def test_archive_extra_symlink_missing_and_tampered_members_are_rejected(self):
        original = self.archive()
        with tarfile.open(original, "r:gz") as archive:
            members = [(m.name, archive.extractfile(m).read()) for m in archive]
        for case in ("extra", "symlink", "missing", "changed", "bad-inventory"):
            path = self.root / (case + ".tar.gz")
            with tarfile.open(path, "w:gz") as archive:
                for index, (name, data) in enumerate(members):
                    if case == "missing" and index == 0: continue
                    if case == "changed" and name != bots.MANIFEST: data += b" "
                    if case == "bad-inventory" and name == bots.MANIFEST:
                        d = json.loads(data); d["inventory_sha256"] = "0" * 64; data = json.dumps(d).encode()
                    m = tarfile.TarInfo(name); m.size = len(data); archive.addfile(m, io.BytesIO(data))
                if case in ("extra", "symlink"):
                    m = tarfile.TarInfo("ice/unexpected")
                    if case == "symlink": m.type, m.linkname = tarfile.SYMTYPE, "../../outside"
                    archive.addfile(m, io.BytesIO())
            with self.subTest(case=case), self.assertRaises(ContractError): bots.verify_bundle(path, self.lock)
            with self.subTest(case=case), self.assertRaises(ContractError): bots.install_sources(path, self.lock, self.root / (case + "-dest"))
            self.assertFalse((self.root / (case + "-dest")).exists())

    def test_approval_packet_is_explicit_full_build_loopback_and_never_executes(self):
        packet = bots.approval_packet(self.lock, "ice", self.roots["ice"])
        self.assertFalse(packet["executed"])
        self.assertFalse(packet["training_connected"])
        self.assertIn("Host=127.0.0.1", packet["run_argv"])
        self.assertIn("/p:ExternalPolicyOnly=false", packet["build_argv"])
        self.assertFalse(packet["toolchain_version_frozen"])
        with self.assertRaises(ContractError): bots.approval_packet(self.lock, "library", self.roots["library"])
        with self.assertRaises(ContractError): bots.approval_packet(self.lock, "ice", self.roots["ice"], deck_name="x;curl")

    def test_config_parser_preserves_named_choices_without_running_commands(self):
        rows = bots.configuration_aliases("!Name\nDeck='Alpha Beta' Name=Local\nDescription\nFLAG\n")
        self.assertEqual(rows[0]["parameters"]["Deck"], "Alpha Beta")
        self.assertFalse(rows[0]["executed"])
        for text in ("!Truncated\nDeck=X", "!Bad\nDeck='X\nD\nF\n", "!Bad\nDeck=X Deck=Y\nD\nF\n"):
            with self.subTest(text=text), self.assertRaises(ContractError): bots.configuration_aliases(text)

    def fake_fetch(self, *, alter=None, failure_at=None, failure=None):
        payloads = {"https://raw.githubusercontent.com/" + s["repository"] + "/" + s["commit"] + "/" + quote(f["path"], safe="/"):
                    (self.roots[s["source_id"]] / f["path"]).read_bytes()
                    for s in self.lock["sources"] for f in s["files"]}
        calls = []
        class Response(io.BytesIO):
            def __init__(self, url, content):
                super().__init__(content)
                self.url, self.status = url, 200
                self.headers = {"Content-Length": str(len(content))}
            def geturl(self): return self.url
        def open_fixture(request, *, timeout):
            calls.append(request.full_url)
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.get_header("Accept-encoding"), "identity")
            self.assertEqual(timeout, 3)
            self.assertIn(request.full_url, payloads)
            if failure_at == len(calls): raise failure
            response = Response(request.full_url, payloads[request.full_url])
            if alter is not None: alter(response)
            return response
        return open_fixture, calls

    def test_fetch_fixed_urls_deduplicates_blobs_then_registry_and_bundle_work(self):
        opener, calls = self.fake_fetch()
        destination = self.root / "fetched"
        receipt = bots.fetch_sources(self.lock, destination, opener=opener, timeout=3)
        expected_blobs = {f["git_blob_sha1"] for s in self.lock["sources"] for f in s["files"]}
        self.assertEqual(len(calls), len(expected_blobs))
        self.assertEqual(receipt["downloaded_unique_blobs"], len(expected_blobs))
        self.assertEqual(receipt["withheld_binary_files_downloaded"], 0)
        self.assertEqual(receipt["transport"], "injected_transport_contract_check")
        self.assertFalse(receipt["runtime_loaded"])
        roots = json.loads((destination / "roots.json").read_text())
        self.assertEqual(roots, receipt["roots"])
        self.assertTrue(all(Path(p).is_dir() for p in roots.values()))
        self.assertEqual(len(bots.BotSourceRegistry(self.lock, destination).statuses()), 3)
        packet = self.root / "fetched.tar.gz"
        bots.create_bundle(self.lock, roots, packet)
        self.assertFalse(bots.verify_bundle(packet, self.lock)["runtime_ready"])
        calls.clear()
        with self.assertRaisesRegex(ContractError, "no overwrite"):
            bots.fetch_sources(self.lock, destination, opener=opener, timeout=3)
        self.assertEqual(calls, [])

    def test_fetch_denial_stops_once_discards_partial_tree_and_does_not_leak_proxy_details(self):
        failures = [HTTPError("https://fixed-target", 403, "proxy-secret-must-not-appear", {}, None),
                    HTTPError("https://fixed-target", 429, "rate limit", {}, None),
                    URLError("proxy-secret-must-not-appear")]
        for ordinal, failure in enumerate(failures):
            opener, calls = self.fake_fetch(failure_at=2, failure=failure)
            destination = self.root / ("denied-" + str(ordinal))
            with self.subTest(error=type(failure).__name__), self.assertRaises(bots.SourceFetchStopped) as raised:
                bots.fetch_sources(self.lock, destination, opener=opener, timeout=3)
            self.assertEqual(len(calls), 2)
            self.assertEqual(raised.exception.details["url"], calls[-1])
            self.assertEqual(raised.exception.details["completed_unique_downloads"], 1)
            self.assertFalse(raised.exception.details["retried"])
            self.assertFalse(destination.exists())
            self.assertEqual(list(self.root.glob(".bot-fetch-*")), [])
            self.assertNotIn("proxy-secret", str(raised.exception))
            self.assertNotIn("proxy-secret", json.dumps(raised.exception.details))

    def test_fetch_rejects_redirect_status_final_url_encoding_and_declared_length(self):
        alterations = [lambda r: setattr(r, "status", 302), lambda r: setattr(r, "url", "https://alternate.invalid/file"),
            lambda r: r.headers.update({"Content-Encoding": "gzip"}),
            lambda r: r.headers.update({"Content-Length": str(len(r.getvalue()) + 1)})]
        for index, alter in enumerate(alterations):
            opener, calls = self.fake_fetch(alter=alter)
            destination = self.root / ("response-" + str(index))
            with self.subTest(index=index), self.assertRaises(bots.SourceFetchStopped):
                bots.fetch_sources(self.lock, destination, opener=opener, timeout=3)
            self.assertEqual(len(calls), 1)
            self.assertFalse(destination.exists())
        handler = bots._NoSourceRedirect()
        request = Request("https://raw.githubusercontent.com/fixed/pin/file")
        with self.assertRaises(HTTPError):
            handler.redirect_request(request, None, 302, "Found", {}, "https://alternate.invalid/file")

    def test_fetch_size_hash_tamper_and_missing_length_oversized_body_fail_closed(self):
        def changed(response):
            raw = response.getvalue()
            response.seek(0); response.write(bytes([raw[0] ^ 1]) + raw[1:]); response.seek(0)
        def oversized(response):
            raw = response.getvalue() + b"unexpected"
            response.seek(0); response.write(raw); response.seek(0)
            response.headers = {}
        for index, alter in enumerate((changed, oversized)):
            opener, calls = self.fake_fetch(alter=alter)
            destination = self.root / ("tamper-" + str(index))
            with self.subTest(index=index), self.assertRaisesRegex(bots.SourceFetchStopped, "source_byte_identity_differs"):
                bots.fetch_sources(self.lock, destination, opener=opener, timeout=3)
            self.assertEqual(len(calls), 1)
            self.assertFalse(destination.exists())

    def test_fetch_no_redirect_opener_preserves_default_configuration_and_has_no_retry(self):
        fake, calls = self.fake_fetch()
        class Opener:
            open = staticmethod(fake)
        with patch.object(bots, "build_opener", return_value=Opener()) as build:
            receipt = bots.fetch_sources(self.lock, self.root / "default-contract", timeout=3)
        self.assertEqual(len(build.call_args.args), 1)
        self.assertIsInstance(build.call_args.args[0], bots._NoSourceRedirect)
        self.assertEqual(receipt["transport"], "fixed_https_download")
        self.assertGreater(len(calls), 0)  # Entire transport here was mocked; no network success is claimed.

    def test_fetch_destination_appearing_mid_download_is_preserved(self):
        destination = self.root / "appeared"
        def create(response):
            destination.mkdir(exist_ok=True)
            (destination / "owner").write_text("keep")
        fake, _ = self.fake_fetch(alter=create)
        with self.assertRaisesRegex(ContractError, "appeared during fetch"):
            bots.fetch_sources(self.lock, destination, opener=fake, timeout=3)
        self.assertEqual((destination / "owner").read_text(), "keep")
        self.assertFalse((destination / "ice").exists())


class FixedBotSourceMetadataTests(unittest.TestCase):
    def test_real_lock_accounts_for_all_reviewed_origins_and_precise_theme_labels(self):
        lock = bots.validate_lock(json.loads((ROOT / "configs/bot-sources-v1.json").read_text()))
        self.assertEqual([(s["expected_executor_files"], s["expected_ydk_files"]) for s in lock["sources"]], [(73, 71), (74, 73), (73, 0), (0, 0)])
        self.assertEqual(sum(len(s["files"]) for s in lock["sources"]), 815)
        self.assertIn("现代荷鲁斯", lock["theme_aliases"]["Horus"]["excludes"])
        self.assertIn("光暗龙", lock["theme_aliases"]["ChaosRitual"]["excludes"])
        self.assertIn("耀圣", lock["theme_aliases"]["Elfnote"]["labels"])


if __name__ == "__main__":
    unittest.main()
