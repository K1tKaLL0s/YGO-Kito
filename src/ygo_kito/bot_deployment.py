"""Pinned WindBot source deployment, with no compiler or process calls.

Loaded here means a validated source registry, never an instantiated C# policy.
An actual legal-seat LAN/DTO transport is required before a bot can be a trainer
opponent. Static source hashes do not confer duel, strength or history status.
Only fetch_sources performs network I/O, to fixed pinned raw GitHub file URLs.
"""

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from copy import deepcopy
import fnmatch
import gzip
import hashlib
import io
import json
import math
import re
import shlex
import shutil
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .build_contracts import digest
from .validation import ContractError, canonical_json, fields

PINS = {
    "ice": ("IceYGO/windbot", "dec0535f8669dca01457a898890a968139711b19"),
    "pure": ("purerosefallen/windbot", "1b8f89537afe930ce96d2fc8d57b0e91b1f96457"),
    "library": ("mercury233/libWindbot", "4d8cae5f08c8cd474fc65402bd163971d59bd3c8"),
    "mobile-config": ("fallenstardust/YGOMobile-cn-ko-en", "6207d220dd5c027ec97e4b400ac60ef50eaf1bd3"),
}
COUNTS = {"ice": (73, 71), "pure": (74, 73), "library": (73, 0), "mobile-config": (0, 0)}
MANIFEST = "bot-deployment-manifest.json"
MAX_FILE = 4 * 1024 * 1024  # Largest reviewed x64 sqlite DLL is 3,285,504 bytes.
MAX_TOTAL = 32 * 1024 * 1024
DECK_DIR = re.compile(r"(?:^|/)Game/AI/Decks/[^/]+\.cs$")
STRING = r'"(?:\\.|[^"\\])*"'
DECK_ATTRIBUTE = re.compile(r'\[\s*Deck\s*\(\s*(' + STRING + r')\s*,\s*(' + STRING + r')(?:\s*,\s*(' + STRING + r'))?\s*\)\s*\]')
TOKEN = re.compile(r'@"(?:""|[^"])*"|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*.*?\*/', re.S)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


class SourceFetchStopped(ContractError):
    """Bounded public-target diagnostic; never includes proxy credentials."""
    def __init__(self, source_id, path, url, completed, *, status=None, reason="request_failed"):
        self.details = {"source_id": source_id, "path": path, "url": url, "http_status": status,
                        "completed_unique_downloads": completed, "reason": reason,
                        "retried": False, "fallback_attempted": False, "destination_published": False}
        super().__init__("fixed bot source fetch stopped: " + reason + "; no retry or alternate target")


class _NoSourceRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "source redirects are not followed", headers, fp)


def _check_bytes(raw, entry):
    return (len(raw) == entry["bytes"] and _sha(raw) == entry["sha256"]
            and _git_blob(raw) == entry["git_blob_sha1"])


def _path(value):
    if (not isinstance(value, str) or "\\" in value or "\0" in value or ":" in value
            or not value or value.startswith("/") or any(p in ("", ".", "..") for p in value.split("/"))):
        raise ContractError("source path must be a normalized relative POSIX path")
    return PurePosixPath(value).as_posix()


def _read(root, relative):
    relative = _path(relative)
    root = Path(root).resolve()
    path = root / relative
    if any(p.is_symlink() for p in (path, *path.parents) if p != root and p.is_relative_to(root)):
        raise ContractError("source symlinks are not accepted")
    if not path.resolve().is_relative_to(root) or not path.is_file() or path.stat().st_size > MAX_FILE:
        raise ContractError("source is absent, too large or outside its root: " + relative)
    return path.read_bytes()


def validate_lock(lock):
    fields(lock, {"schema_version", "kind", "sources", "theme_aliases"})
    if type(lock["schema_version"]) is not int or lock["schema_version"] != 1 or lock["kind"] != "pinned-maintained-bot-sources-v1":
        raise ContractError("unsupported maintained bot source lock")
    seen = set()
    for source in lock["sources"]:
        fields(source, {"source_id", "repository", "commit", "scope", "license", "project", "files", "withheld_binary_resources", "expected_executor_files", "expected_ydk_files"})
        ident = source["source_id"]
        if ident in seen or ident not in PINS or (source["repository"], source["commit"]) != PINS[ident]:
            raise ContractError("source is duplicate or differs from its approved fixed pin")
        seen.add(ident)
        expected_scope = "configuration-only" if ident == "mobile-config" else "all-reviewed-source-and-build-resources"
        if source["scope"] != expected_scope:
            raise ContractError("source scope differs; a reduced Executor scope is forbidden")
        if (source["expected_executor_files"], source["expected_ydk_files"]) != COUNTS[ident]:
            raise ContractError("source counts differ from the actual reviewed fixed tree")
        if source["license"]["spdx"] != ("GPL-2.0-only" if ident == "mobile-config" else "MIT"):
            raise ContractError("source license notice must remain explicit")
        paths = []
        for f in source["files"]:
            fields(f, {"path", "git_blob_sha1", "sha256", "bytes"})
            paths.append(_path(f["path"]))
            if (type(f["bytes"]) is not int or not 0 <= f["bytes"] <= MAX_FILE
                    or not isinstance(f["sha256"], str) or not re.fullmatch("[0-9a-f]{64}", f["sha256"])
                    or not isinstance(f["git_blob_sha1"], str) or not re.fullmatch("[0-9a-f]{40}", f["git_blob_sha1"])):
                raise ContractError("source byte identity is invalid")
        if len(set(paths)) != len(paths) or not paths or source["license"]["path"] not in paths:
            raise ContractError("source paths duplicate or license is absent")
        if source["project"] is not None and source["project"] not in paths:
            raise ContractError("declared build project is absent")
        if len([p for p in paths if DECK_DIR.search(p)]) != source["expected_executor_files"]:
            raise ContractError("lock does not account for every Executor source")
        if len([p for p in paths if p.lower().endswith(".ydk")]) != source["expected_ydk_files"]:
            raise ContractError("lock does not account for every YDK resource")
        if ident == "mobile-config" and set(paths) != {"LICENSE", "mobile/assets/data/conf/bot.conf"}:
            raise ContractError("the GPL client is outside the approved config-only scope")
    if seen != set(PINS):
        raise ContractError("all four approved source origins are required")
    return deepcopy(lock)


def verify_sources(lock, roots):
    lock = validate_lock(lock)
    if set(roots) != set(PINS):
        raise ContractError("explicit source roots must cover all four fixed origins")
    total = 0
    for source in lock["sources"]:
        root = Path(roots[source["source_id"]]).resolve()
        expected = {f["path"] for f in source["files"]}
        actual = {p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file() and ".git" not in p.relative_to(root).parts}
        # Withheld binaries are listed, never treated as source-install success.
        allowed_extra = {f["path"] for f in source["withheld_binary_resources"]}
        if actual - expected - allowed_extra or expected - actual:
            raise ContractError("source file set differs; no silent source/Executor omission")
        for entry in source["files"]:
            raw = _read(root, entry["path"])
            total += len(raw)
            if (len(raw) != entry["bytes"] or _sha(raw) != entry["sha256"] or _git_blob(raw) != entry["git_blob_sha1"]):
                raise ContractError("source byte identity differs: " + entry["path"])
    if total > MAX_TOTAL:
        raise ContractError("source packet exceeds its bounded size")
    return lock


def _uncomment(source):
    return TOKEN.sub(lambda m: " " if m.group().startswith(("//", "/*")) else m.group(), source)


def _project(source, files):
    if "<!DOCTYPE" in source.upper() or "<!ENTITY" in source.upper():
        raise ContractError("build XML declarations are not accepted")
    try:
        root = ET.fromstring(source)
    except ET.ParseError as error:
        raise ContractError("invalid build project XML") from error
    patterns, references, packages, imports, postbuild, frameworks, platforms, resource_patterns = [], [], [], [], [], [], [], []
    def walk(node, conditional=False):
        conditional = conditional or bool(node.attrib.get("Condition"))
        if node.tag.rsplit("}", 1)[-1] == "Compile" and conditional:
            raise ContractError("conditional Compile cannot prove complete Executor inclusion")
        yield node
        for child in node:
            yield from walk(child, conditional)
    for node in walk(root):
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "Compile":
            pattern = node.attrib.get("Include", "").replace("\\", "/")
            if not pattern or "$" in pattern or node.attrib.get("Exclude") or node.attrib.get("Remove"):
                raise ContractError("unsupported reduced/dynamic Compile declaration")
            patterns.append(pattern)
        if tag == "Reference": references.append(node.attrib["Include"])
        if tag == "PackageReference": packages.append(dict(node.attrib))
        if tag == "Import": imports.append(dict(node.attrib))
        if tag == "PostBuildEvent" and node.text and node.text.strip(): postbuild.append(node.text)
        if tag == "TargetFrameworkVersion" and node.text: frameworks.append(node.text)
        if tag == "PlatformTarget" and node.text: platforms.append(node.text)
        if tag in ("None", "Content", "EmbeddedResource") and node.attrib.get("Include"):
            resource_patterns.append(node.attrib["Include"].replace("\\", "/"))
        if tag == "ApplicationIcon" and node.text:
            resource_patterns.append(node.text.replace("\\", "/"))
        # Do not interpret a conditional group as proof of complete compilation.
        if "ExternalPolicyOnly" in str(node.attrib):
            raise ContractError("ExternalPolicyOnly source subsets are forbidden")
    compiled = sorted(p for p in files if any(fnmatch.fnmatchcase(p, pattern) for pattern in patterns))
    missing = sorted(p for p in files if DECK_DIR.search(p) and p not in compiled)
    if missing:
        raise ContractError("build omits declared Executor sources: " + ", ".join(missing))
    missing_resources = [p for p in resource_patterns if not any(c in p for c in "*?$") and p not in files]
    if missing_resources:
        raise ContractError("build resource inputs are absent: " + ", ".join(missing_resources))
    return {"frameworks": sorted(set(frameworks)), "platform_targets": sorted(set(platforms)),
            "references": references, "packages": packages, "imports": imports,
            "postbuild_events": postbuild, "compile_patterns": patterns,
            "resource_patterns": resource_patterns,
            "resource_input_files": sorted(p for p in files if any(fnmatch.fnmatchcase(p, pattern) for pattern in resource_patterns)),
            "compiled_executor_files": sorted(p for p in compiled if DECK_DIR.search(p)),
            "build_executed": False}


def configuration_aliases(text):
    """Read the upstream four-line bot.conf records without evaluating commands."""
    rows, lines, index = [], text.splitlines(), 0
    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if not line.startswith("!"):
            continue
        if index + 3 > len(lines):
            raise ContractError("truncated four-line bot.conf record")
        command, description, flags = [s.strip() for s in lines[index:index + 3]]
        index += 3
        try:
            tokens = shlex.split(command)
        except ValueError as error:
            raise ContractError("invalid bot.conf quoting") from error
        values = {}
        for token in tokens:
            if "=" not in token:
                raise ContractError("bot.conf contains a non-assignment token")
            key, value = token.split("=", 1)
            if key in values:
                raise ContractError("bot.conf repeats a command parameter")
            values[key] = value
        rows.append({"display_name": line[1:], "parameters": values,
                     "description": description, "flags": flags.split(), "executed": False})
    return rows


def inventory(lock, roots):
    lock = verify_sources(lock, roots)
    origins, projects, ydks, missing_decks, aliases = [], {}, {}, [], []
    for source in lock["sources"]:
        ident = source["source_id"]
        files = {x["path"]: x for x in source["files"]}
        root = roots[ident]
        ydks[ident] = {p: files[p]["sha256"] for p in files if p.lower().endswith(".ydk")}
        for path in files:
            if path.endswith("bot.conf"):
                aliases.extend(dict(a, source_id=ident, source_path=path)
                               for a in configuration_aliases(_read(root, path).decode("utf-8-sig")))
        if source["project"]:
            project_dir = str(PurePosixPath(source["project"]).parent)
            prefix = "" if project_dir == "." else project_dir + "/"
            project_files = [p[len(prefix):] for p in files if p.startswith(prefix)]
            projects[ident] = _project(_read(root, source["project"]).decode("utf-8-sig"), project_files)
        for path, entry in files.items():
            if not path.endswith(".cs"):
                continue
            text = _uncomment(_read(root, path).decode("utf-8-sig"))
            declarations = list(DECK_ATTRIBUTE.finditer(text))
            if len(declarations) != len(re.findall(r"\[\s*Deck\s*\(", text)):
                raise ContractError("unparsed Deck declaration: " + path)
            if declarations and not DECK_DIR.search(path):
                raise ContractError("Deck declaration outside the reviewed discovery scope: " + path)
            if not DECK_DIR.search(path):
                continue
            names = re.findall(r"\bclass\s+(\w+)\s*:\s*\w+", text)
            if not names or not declarations:
                raise ContractError("Executor lacks an explicit class/Deck registration: " + path)
            for declaration in declarations:
                name, deck, level = [json.loads(x) if x is not None else None for x in declaration.groups()]
                origin = {"source_id": ident, "source_path": path, "class_name": names[0],
                    "deck_name": name, "deck_file": deck, "level": level,
                    "git_blob_sha1": entry["git_blob_sha1"], "sha256": entry["sha256"],
                    "theme_aliases": deepcopy(lock["theme_aliases"].get(name, {}))}
                origin["bot_id"] = digest(origin)
                origins.append(origin)
    # Keep exact code variants, while grouping byte-identical shared origins.
    groups = {}
    for origin in origins:
        key = origin["sha256"]
        groups.setdefault(key, []).append(origin["bot_id"])
        candidates = [{"source_id": ident, "path": path, "sha256": sha}
            for ident, decks in ydks.items() for path, sha in decks.items()
            if PurePosixPath(path).stem.casefold() == origin["deck_file"].casefold()]
        origin["deck_resource_candidates"] = candidates
        origin["configuration_aliases"] = [deepcopy(a) for a in aliases
            if a["parameters"].get("Deck", "").casefold() == origin["deck_name"].casefold()]
        origin["resource_binding_status"] = ("requires_explicit_deck" if not candidates else
            "explicit_variant_required" if len({c["sha256"] for c in candidates}) > 1 else "source_resource_identified")
        if not candidates:
            missing_decks.append({"bot_id": origin["bot_id"], "deck_file": origin["deck_file"], "source_id": origin["source_id"]})
    result = {"schema_version": 1, "kind": "maintained-bot-source-inventory", "source_lock_sha256": digest(lock),
        "origins": origins, "byte_identical_implementation_groups": groups, "projects": projects,
        "ydk_files": ydks, "missing_deck_resources": missing_decks, "configuration_aliases": aliases,
        "withheld_binary_resources": {s["source_id"]: s["withheld_binary_resources"] for s in lock["sources"]},
        "runtime_loaded": False, "native_executed": False, "third_party_executed": False,
        "training_connected": False, "history_verified": False, "strength_verified": False}
    result["inventory_sha256"] = digest(result)
    return result


def fetch_sources(lock, destination, *, opener=None, timeout=30):
    """Fetch pinned inert source bytes once per blob, then publish a new root.

    The optional callable opener is a test/host dependency, not an RPC option.
    The default preserves normal system proxy handling and certificate checks,
    refuses redirects, and has no retry, alternate host or proxy selection.
    A failed download never publishes the destination or partial source tree.
    """
    lock = validate_lock(lock)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise ContractError("source GET timeout must be finite and within 300 seconds")
    files = [(s, f) for s in lock["sources"] for f in s["files"]]
    if sum(f["bytes"] for _, f in files) > MAX_TOTAL:
        raise ContractError("source packet exceeds its bounded size")
    identities = {}
    for _, entry in files:
        identity = (entry["sha256"], entry["bytes"])
        previous = identities.setdefault(entry["git_blob_sha1"], identity)
        if previous != identity:
            raise ContractError("one Git blob has conflicting locked SHA256/size identities")
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ContractError("source destination exists; no overwrite")
    transport = "fixed_https_download" if opener is None else "injected_transport_contract_check"
    if opener is None:
        # build_opener retains the default ProxyHandler; do not disable or
        # replace a configured proxy to get around a rejected source request.
        opener = build_opener(_NoSourceRedirect()).open
    if not callable(opener):
        raise ContractError("source opener must implement the request/timeout callable contract")
    destination.parent.mkdir(parents=True, exist_ok=True)
    downloaded = {}
    with tempfile.TemporaryDirectory(prefix=".bot-fetch-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "sources"
        staging.mkdir()
        for source, entry in files:
            blob = entry["git_blob_sha1"]
            url = ("https://raw.githubusercontent.com/" + source["repository"] + "/" + source["commit"]
                   + "/" + quote(entry["path"], safe="/"))
            if blob not in downloaded:
                try:
                    request = Request(url, headers={"Accept-Encoding": "identity"}, method="GET")
                    with opener(request, timeout=timeout) as response:
                        status = response.status
                        if status != 200:
                            raise SourceFetchStopped(source["source_id"], entry["path"], url, len(downloaded),
                                                     status=status, reason="http_status_rejected")
                        if response.geturl() != url:
                            raise SourceFetchStopped(source["source_id"], entry["path"], url, len(downloaded), reason="redirect_rejected")
                        encoding = response.headers.get("Content-Encoding", "identity").lower()
                        if encoding != "identity":
                            raise SourceFetchStopped(source["source_id"], entry["path"], url, len(downloaded), reason="content_encoding_rejected")
                        length = response.headers.get("Content-Length")
                        if length is not None and (not length.isascii() or not length.isdecimal() or int(length) != entry["bytes"]):
                            raise SourceFetchStopped(source["source_id"], entry["path"], url, len(downloaded), reason="declared_length_differs")
                        chunks, size = [], 0
                        while size <= entry["bytes"]:
                            chunk = response.read(min(65536, entry["bytes"] + 1 - size))
                            if not isinstance(chunk, bytes):
                                raise SourceFetchStopped(source["source_id"], entry["path"], url, len(downloaded), reason="invalid_response_bytes")
                            if not chunk:
                                break
                            chunks.append(chunk)
                            size += len(chunk)
                        raw = b"".join(chunks)
                except HTTPError as error:
                    raise SourceFetchStopped(source["source_id"], entry["path"], url, len(downloaded),
                                             status=error.code, reason="http_request_denied") from None
                except (URLError, OSError, TimeoutError) as error:
                    raise SourceFetchStopped(source["source_id"], entry["path"], url, len(downloaded),
                                             reason="transport_" + type(error).__name__) from None
                if not _check_bytes(raw, entry):
                    raise SourceFetchStopped(source["source_id"], entry["path"], url, len(downloaded), reason="source_byte_identity_differs")
                downloaded[blob] = raw
            raw = downloaded[blob]
            if not _check_bytes(raw, entry):
                raise ContractError("deduplicated source does not match its locked byte identity")
            path = staging / source["source_id"] / entry["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            path.chmod(0o600)
        roots = {ident: str((destination / ident).resolve()) for ident in PINS}
        discovered = inventory(lock, {ident: staging / ident for ident in PINS})
        result = {"state": "prepared", "source_files": len(files), "downloaded_unique_blobs": len(downloaded),
            "downloaded_unique_bytes": sum(map(len, downloaded.values())), "transport": transport,
            "source_lock_sha256": digest(lock), "inventory_sha256": discovered["inventory_sha256"],
            "withheld_binary_files_downloaded": 0,
            "pinned_binary_build_files": sum(f["path"].lower().endswith((".dll", ".ico", ".bmp")) for _, f in files), "roots": roots,
            "runtime_loaded": False, "third_party_executed": False, "training_connected": False}
        (staging / "roots.json").write_text(canonical_json(roots) + "\n", encoding="utf-8")
        (staging / "fetch-receipt.json").write_text(canonical_json(result) + "\n", encoding="utf-8")
        if destination.exists() or destination.is_symlink():
            raise ContractError("source destination appeared during fetch; no overwrite")
        staging.rename(destination)
    return result


def create_bundle(lock, roots, output):
    """Build an offline deterministic source packet; never fetch or run code."""
    lock = verify_sources(lock, roots)
    discovered = inventory(lock, roots)
    manifest = {"schema_version": 1, "kind": "maintained-bot-source-bundle", "lock": lock,
                "inventory_sha256": discovered["inventory_sha256"], "runtime_ready": False}
    payloads = {s["source_id"] + "/" + f["path"]: _read(roots[s["source_id"]], f["path"])
                for s in lock["sources"] for f in s["files"]}
    payloads[MANIFEST] = (canonical_json(manifest) + "\n").encode()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as zipped:
        with tarfile.open(fileobj=zipped, mode="w") as archive:
            for name, content in sorted(payloads.items()):
                member = tarfile.TarInfo(name)
                member.size, member.mode, member.mtime = len(content), 0o600, 0
                archive.addfile(member, io.BytesIO(content))
    return {"archive_sha256": _sha(output.read_bytes()), "source_files": len(payloads) - 1,
            "inventory_sha256": discovered["inventory_sha256"], "runtime_ready": False}


def _packet(archive, expected_lock):
    expected_lock = validate_lock(expected_lock)
    archive = Path(archive)
    if archive.stat().st_size > MAX_TOTAL:
        raise ContractError("compressed source packet exceeds the size bound")
    expected = {s["source_id"] + "/" + f["path"]: f for s in expected_lock["sources"] for f in s["files"]}
    allowed_members = set(expected) | {MANIFEST}
    data, total = {}, 0
    try:
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar:
                name = _path(member.name)
                total += member.size
                if (name not in allowed_members or not member.isfile() or name in data
                        or not 0 <= member.size <= MAX_FILE or total > MAX_TOTAL):
                    raise ContractError("source archive contains duplicate, linked or oversized members")
                data[name] = tar.extractfile(member).read()
    except (tarfile.TarError, OSError, EOFError) as error:
        raise ContractError("source archive cannot be read") from error
    if MANIFEST not in data:
        raise ContractError("source archive manifest is missing")
    manifest = json.loads(data.pop(MANIFEST).decode("utf-8"))
    fields(manifest, {"schema_version", "kind", "lock", "inventory_sha256", "runtime_ready"})
    if (manifest["schema_version"] != 1 or manifest["kind"] != "maintained-bot-source-bundle"
            or manifest["lock"] != expected_lock or manifest["runtime_ready"] is not False):
        raise ContractError("source packet does not match the trusted fixed-source lock")
    if set(data) != set(expected):
        raise ContractError("source packet omits or adds files")
    for name, raw in data.items():
        entry = expected[name]
        if len(raw) != entry["bytes"] or _sha(raw) != entry["sha256"] or _git_blob(raw) != entry["git_blob_sha1"]:
            raise ContractError("source packet member checksum differs")
    return manifest, data


def verify_bundle(archive, lock):
    manifest, data = _packet(archive, lock)
    with tempfile.TemporaryDirectory(prefix="bot-source-verify-") as temporary:
        root = Path(temporary)
        _write_sources(root, data)
        actual = inventory(lock, {ident: root / ident for ident in PINS})
    if actual["inventory_sha256"] != manifest["inventory_sha256"]:
        raise ContractError("packet discovery differs from its manifest")
    return {"verified_source_files": len(data), "source_lock_sha256": digest(lock),
            "inventory_sha256": manifest["inventory_sha256"], "runtime_ready": False}


def _write_sources(root, data):
    for name, raw in data.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o600)


def install_sources(archive, lock, destination):
    """Install only validated inert source bytes to a new directory, not a bot."""
    manifest, data = _packet(archive, lock)
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ContractError("source destination exists; no overwrite")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bot-source-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "sources"
        staging.mkdir()
        _write_sources(staging, data)
        actual = inventory(lock, {ident: staging / ident for ident in PINS})
        if actual["inventory_sha256"] != manifest["inventory_sha256"]:
            raise ContractError("installed discovery differs from the source packet")
        (staging / MANIFEST).write_text(canonical_json(manifest) + "\n", encoding="utf-8")
        staging.rename(destination)
    return {"state": "prepared", "installed_source_files": len(data),
            "source_lock_sha256": digest(lock), "inventory_sha256": actual["inventory_sha256"],
            "runtime_loaded": False, "training_connected": False}


class PreparationState(str, Enum):
    PREPARED = "prepared"
    LOADED = "loaded_source_registry"


@dataclass(frozen=True)
class BotStatus:
    bot_id: str
    source_id: str
    deck_name: str
    source_state: PreparationState
    runtime_loaded: bool = False
    normal_duel_verified: bool = False
    strength_verified: bool = False
    history_verified: bool = False
    training_connected: bool = False


class BotSourceRegistry:
    """Typed full registry. Loading validates sources; it does not execute C#."""
    def __init__(self, lock, installed_root):
        self.lock = validate_lock(lock)
        self.root = Path(installed_root).resolve()
        self.inventory = inventory(self.lock, {ident: self.root / ident for ident in PINS})
        self._seal = digest(self.inventory)
        self._by_id = {row["bot_id"]: row for row in self.inventory["origins"]}
        if len(self._by_id) != len(self.inventory["origins"]):
            raise ContractError("source registry has duplicate bot identities")

    def statuses(self):
        if digest(self.inventory) != self._seal:
            raise ContractError("source registry metadata changed after loading")
        verify_sources(self.lock, {ident: self.root / ident for ident in PINS})
        return tuple(BotStatus(r["bot_id"], r["source_id"], r["deck_name"], PreparationState.LOADED)
                     for r in self.inventory["origins"])

    def resolve(self, bot_id):
        self.statuses()
        if bot_id not in self._by_id:
            raise ContractError("unknown fixed-source bot identity")
        return deepcopy(self._by_id[bot_id])

    def training_adapter(self, executor_id, *, source_id=None, native_root=None, profile=None, seat=1,
                         versions=None, environment_id=None, opponent_id=None, source="user_provided",
                         build_audit_path=None, build_audit_sha256=None, mono=None,
                         workspace=None, period_context=None, variant_root=None, session_seconds=None):
        """Build the actual managed-room adapter only after a complete real audit.

        Source registration remains independent of this gate. The default room
        factory launches the full audited C# executable in an isolated directory;
        there is no provider fixture or fallback if audit/tool/transport is absent.
        """
        from .agent_registry import identifier
        from .bot_build_audit import file_sha, validate_audit_result
        from .contracts import Versions
        from .deck_profile import validate_profile
        from .build_contracts import DeckParts
        from .validation import integer, member
        from .windbot_projection import WindBotOpponent
        from .windbot_room import WindBotRoom, windbot_session
        from contextlib import contextmanager
        from .implementation_identity import source_tree_snapshot, assert_source_tree
        session_seconds = 120 if session_seconds is None else session_seconds
        if type(session_seconds) not in (int, float) or not math.isfinite(session_seconds) or not 0 < session_seconds <= 300:
            raise ContractError("explicit bot session limit must be finite and within (0, 300] seconds")
        self.statuses()
        matches = [r for r in self.inventory["origins"] if r["bot_id"] == executor_id or
                   (r["source_id"] == source_id and r["class_name"] == executor_id)]
        if len(matches) != 1:
            raise ContractError("exact fixed-source Executor identity is absent or ambiguous")
        definition = deepcopy(matches[0])
        if definition["source_id"] not in ("ice", "pure") or source_id != definition["source_id"]:
            raise ContractError("only an explicitly selected complete desktop Executor can run")
        if build_audit_path is None or build_audit_sha256 is None:
            raise ContractError("actual full-Executor build/resource/constructor audit is required; source registry alone cannot run")
        workspace = Path(workspace or self.root.parent).resolve()
        def local(value):
            if value is None:
                raise ContractError("explicit runtime audit/resource path required")
            path = Path(value).resolve(strict=True)
            if not path.is_relative_to(workspace) or not path.is_file():
                raise ContractError("runtime evidence/resources must stay inside the explicit workspace")
            return path
        audit_path = local(build_audit_path)
        if file_sha(audit_path) != build_audit_sha256:
            raise ContractError("build audit file checksum differs")
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        runtime_source = self.root / source_id
        variant = None
        if variant_root is not None:
            from .bot_overlay import runtime_overlay_identity
            if source_id != "pure":
                raise ContractError("the exact desktop overlay has a Pure base only")
            runtime_source = Path(variant_root).resolve(strict=True)
            if not runtime_source.is_relative_to(workspace) or not runtime_source.is_dir():
                raise ContractError("variant tree must remain inside the explicit workspace")
            variant = runtime_overlay_identity(self.lock, runtime_source)
        fields(audit, {"schema_version", "kind", "source_id", "repository", "commit", "source_lock_sha256",
            "inventory_sha256", "assembly_path", "assembly_sha256", "source_root", "source_roots",
            "audit_source_sha256", "audit_output_path", "audit_output_sha256", "toolchain", "cards",
            "expected_bots", "evidence_source", "runtime_loaded", "constructors_verified", "audit",
            "normal_duel_verified", "strength_verified", "history_verified", "training_connected"} |
            ({"variant"} if variant is not None else set()))
        expected_kind = "complete-desktop-bot-overlay-build-audit" if variant is not None else "complete-desktop-bot-build-audit"
        if (type(audit.get("schema_version")) is not int or audit.get("schema_version") != 1 or audit.get("kind") != expected_kind or
                audit.get("source_id") != source_id or (audit.get("repository"), audit.get("commit")) != PINS[source_id] or
                audit.get("evidence_source") != "actual_complete_assembly_audit" or audit.get("runtime_loaded") is not True or
                audit.get("constructors_verified") is not True or audit.get("source_lock_sha256") != digest(self.lock) or
                audit.get("inventory_sha256") != self.inventory["inventory_sha256"] or
                any(audit[k] is not False for k in ("normal_duel_verified", "strength_verified", "history_verified", "training_connected")) or
                Path(audit.get("source_root", "")).resolve() != runtime_source or
                (variant is not None and audit.get("variant") != variant) or
                audit.get("audit_source_sha256") != file_sha(Path(__file__).resolve().parents[2] / "scripts/BotAssemblyAudit.cs")):
            raise ContractError("real complete assembly audit does not match this exact source registry")
        fields(audit["cards"], {"path", "sha256"})
        assembly, database, audit_output = local(audit["assembly_path"]), local(audit["cards"]["path"]), local(audit["audit_output_path"])
        expected_bots = audit["expected_bots"]
        expected = {("WindBot.Game.AI.Decks." + r["class_name"], r["deck_name"], r["deck_file"], r["level"] or "Normal")
                    for r in self.inventory["origins"] if r["source_id"] == source_id}
        if (len(expected_bots) != COUNTS[source_id][0] or
                {(b["full_type"], b["deck_name"], b["deck_file"], b["level"]) for b in expected_bots} != expected):
            raise ContractError("build audit omitted or changed a full source Executor")
        if file_sha(audit_output) != audit["audit_output_sha256"] or json.loads(audit_output.read_text()) != audit["audit"]:
            raise ContractError("runtime reflection output differs from its build receipt")
        validate_audit_result({"bots": expected_bots, "assembly_path": str(assembly)}, audit["audit"], construct=True)
        if file_sha(assembly) != audit["assembly_sha256"] or file_sha(database) != audit["cards"]["sha256"]:
            raise ContractError("runtime assembly/catalog differs from the actual build audit")
        selected = [b for b in expected_bots if b["full_type"] == "WindBot.Game.AI.Decks." + definition["class_name"]]
        for bot in expected_bots:
            deck = local(bot["selected_deck"]["path"])
            if file_sha(deck) != bot["selected_deck"]["sha256"]:
                raise ContractError("an audited Executor YDK source changed")
        if len(selected) != 1:
            raise ContractError("selected Executor was not audited uniquely")
        if mono is None or not Path(mono).is_absolute():
            raise ContractError("host Mono path must be explicit and absolute")
        executable = Path(mono).resolve(strict=True)
        if not executable.is_file() or not shutil.which(str(executable)):
            raise ContractError("explicit installed official Mono executable is unavailable")
        tools = fields(audit["toolchain"], {"mono", "compiler", "msbuild"})
        tool_seals = {}
        for tool in tools.values():
            fields(tool, {"path", "sha256"})
            path = Path(tool["path"])
            if not path.is_absolute() or not path.is_file() or file_sha(path) != tool["sha256"]:
                raise ContractError("audited Mono/build tool identity differs")
            tool_seals[str(path.resolve())] = tool["sha256"]
        if Path(tools["mono"]["path"]).resolve() != executable or tools["mono"]["sha256"] != file_sha(executable):
            raise ContractError("selected Mono differs from the actual constructor audit toolchain")
        if not isinstance(versions, Versions) or versions.cards != audit["cards"]["sha256"]:
            raise ContractError("typed runtime versions/catalog differ from the actual C# audit")
        integer(seat, "bot seat", 0, 1); validate_profile(profile)
        profile, period_context = deepcopy(profile), deepcopy(period_context)
        identifier(environment_id); identifier(opponent_id)
        member(source, "bot evidence source", ("engineering_fixture", "user_provided", "external_submission"))
        def deck_for(player):
            return DeckParts(tuple(profile["decks"][player]), tuple(profile.get("extras", [[], []])[player]),
                             tuple(profile.get("sides", [[], []])[player]))
        other, own = deck_for(seat), deck_for(1 - seat)
        record = {"bot_id": definition["bot_id"], "source_id": source_id, "source_lock_sha256": digest(self.lock),
            "audit_sha256": build_audit_sha256, "assembly_sha256": audit["assembly_sha256"], "cards": audit["cards"],
            "period_context": deepcopy(period_context), "environment_id": environment_id,
            "profile_sha256": digest(profile), "versions": asdict(versions), "toolchain": tools,
            "session_seconds": session_seconds}
        if variant is not None:
            record["variant"] = variant
        implementation_root = Path(__file__).resolve().parent
        implementation_digest = source_tree_snapshot(implementation_root)
        binding = {"schema_version": 1, "opponent_id": opponent_id, "environment_id": environment_id,
            "registered_record_sha256": digest(record), "opponent_deck_sha256": digest(other.to_dict()),
            "own_deck_sha256": digest(own.to_dict()), "profile_sha256": digest(profile),
            "driver_version": ("windbot-" + source_id + "-" + definition["bot_id"][:24] if variant is None else
                               "windbot-pure-overlay-" + digest({"variant": variant, "bot_id": definition["bot_id"]})[:24]),
            "driver_implementation_sha256": digest({"source": definition["sha256"], "assembly": audit["assembly_sha256"],
                "python_modules": implementation_digest, **({"variant": variant} if variant is not None else {})}),
            "source": source, "controller": "bot", "strength_qualified": False, "external_provider_verified": False,
            "model_sha256": None, "opponent_deck_content_sha256": digest({k: sorted(v) for k, v in other.to_dict().items()})}
        seals = {str(audit_path): build_audit_sha256, str(assembly): audit["assembly_sha256"],
                 str(database): audit["cards"]["sha256"], str(audit_output): audit["audit_output_sha256"],
                 **tool_seals}
        for bot in expected_bots: seals[bot["selected_deck"]["path"]] = bot["selected_deck"]["sha256"]
        active = {}
        lock_seal = digest(self.lock)
        def validator():
            assert_source_tree(implementation_root, implementation_digest)
            if digest(self.lock) != lock_seal:
                raise ContractError("bot source lock changed after runtime binding")
            self.statuses()
            if variant is not None and runtime_overlay_identity(self.lock, runtime_source) != variant:
                raise ContractError("exact desktop overlay changed after runtime binding")
            for path, sha in {**seals, **active}.items():
                if not Path(path).is_file() or file_sha(path) != sha:
                    raise ContractError("actual bot source/audit/assembly/catalog/YDK/tool state changed")
        @contextmanager
        def actual_room(opponent):
            validator()
            runtime_parent = workspace / ".cache/windbot-runtime"
            runtime_parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=source_id + "-", dir=runtime_parent) as temporary:
                directory = Path(temporary)
                deployed = {"executable": directory / "WindBot.exe", "database": directory / "cards.cdb", "deck_file": directory / "match.ydk"}
                shutil.copyfile(assembly, deployed["executable"]); shutil.copyfile(database, deployed["database"])
                ydk = "#main\n" + "\n".join(map(str, other.main)) + "\n#extra\n" + "\n".join(map(str, other.extra)) + "\n!side\n" + "\n".join(map(str, other.side)) + "\n"
                deployed["deck_file"].write_text(ydk, encoding="utf-8")
                component = next(s for s in self.lock["sources"] if s["source_id"] == source_id)
                for f in component["files"]:
                    if f["path"].startswith("Dialogs/"):
                        target = directory / f["path"]; target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(runtime_source / f["path"], target)
                    elif f["path"].startswith("ThirdParty/sqlite/"):
                        target = directory / f["path"].removeprefix("ThirdParty/sqlite/")
                        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(runtime_source / f["path"], target)
                shutil.copyfile(runtime_source / "App.config", directory / "WindBot.exe.config")
                active.update({str(p): file_sha(p) for p in directory.rglob("*") if p.is_file()})
                try:
                    with windbot_session(other, observer=seat, duel_rule=5, mono=executable,
                            executable=deployed["executable"], database=deployed["database"], deck_file=deployed["deck_file"],
                            executor=definition["deck_name"], allowed_executors={b["deck_name"] for b in expected_bots},
                            working_directory=directory, wall_seconds=session_seconds,
                            expected_sha256={"mono": seals[str(executable)], **{k: file_sha(p) for k, p in deployed.items()}}) as room:
                        yield room
                finally:
                    active.clear()
        adapter = WindBotOpponent(root=native_root, profile=profile, seat=seat, versions=versions, binding=binding,
            runtime_validator=validator, room_factory=actual_room)
        adapter.rebind = lambda new_profile: self.training_adapter(executor_id, source_id=source_id, native_root=native_root,
            profile=new_profile, seat=seat, versions=versions, environment_id=environment_id, opponent_id=opponent_id,
            source=source, build_audit_path=audit_path, build_audit_sha256=build_audit_sha256, mono=executable,
            workspace=workspace, period_context=period_context, variant_root=runtime_source if variant is not None else None,
            session_seconds=session_seconds)
        return adapter


def approval_packet(lock, source_id, source_directory, *, deck_name="ChaosRitual", port=7911):
    """Prepare reviewable commands, without downloading, compiling or starting."""
    lock = validate_lock(lock)
    if source_id not in ("ice", "pure"):
        raise ContractError("only the reviewed full desktop executables are build candidates; Android library build is excluded")
    if not isinstance(deck_name, str) or not re.fullmatch(r"[A-Za-z0-9 _-]{1,64}", deck_name):
        raise ContractError("explicit source-declared test Deck name required")
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ContractError("explicit unprivileged loopback test port required")
    source = next(s for s in lock["sources"] if s["source_id"] == source_id)
    directory = str(Path(source_directory).resolve())
    return {"schema_version": 1, "kind": "third-party-build-run-approval-packet", "executed": False,
        "source_id": source_id, "repository": source["repository"], "commit": source["commit"],
        "source_lock_sha256": digest(lock), "working_directory": directory,
        "toolchain_present": {x: shutil.which(x) is not None for x in ("mono", "msbuild", "xbuild", "dotnet")},
        "toolchain_install_candidate": ["apt-get", "install", "--no-install-recommends", "mono-devel"],
        "toolchain_version_frozen": False,
        "build_argv": ["msbuild", "WindBot.csproj", "/t:Build", "/p:Configuration=Release", "/p:Platform=AnyCPU", "/p:ExternalPolicyOnly=false", "/p:RunPostBuildEvent=Never"],
        "run_argv": ["mono", "bin/Release/WindBot.exe", "Name=KitoLoopbackAudit", "Deck=" + deck_name,
                     "Host=127.0.0.1", "Port=" + str(port), "Chat=False", "Debug=False"],
        "runtime_blockers": ["Mono/MSBuild version and Linux framework references not installed/frozen",
            "Linux system libsqlite3 is required; the pinned Windows DLL resources do not prove Linux loading",
            "actual pinned cards.cdb and selected YDK/dialog resource binding must be explicit",
            "loopback YGOPro room host to Kito ctypes/seat-DTO legal-action bridge is not implemented or tested"],
        "excluded": ["libWindbot Android/Xamarin/Embeddinator PostBuildEvent", "WindBot.Test1 hardcoded public host",
                     "remote game servers", "paid services", "native fault tests"],
        "risks": ["toolchain install changes packages and requires separate approval",
                  "compiling third-party C# permits its MSBuild imports/tasks to execute",
                  "running C# and sqlite native dependencies requires a bounded isolated loopback harness"],
        "training_connected": False}
