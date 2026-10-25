"""Exact, separately identified desktop overlay; never compiles or runs code.

The unchanged Pure and library pins stay immutable. A new complete Pure tree
receives only the exact library Monarch506 file plus its original MIT notice.
"""
from copy import deepcopy
import gzip
import io
import json
from pathlib import Path
import tarfile
import tempfile

from . import bot_deployment as sources
from .build_contracts import digest
from .validation import ContractError, canonical_json

VARIANT_ID = "pure-with-library-monarch506-exact-v1"
MANIFEST = "bot-overlay-manifest.json"
TARGET = "Game/AI/Decks/Monarch506Executor.cs"
DONOR = "libWindbot/" + TARGET
NOTICE = "THIRD_PARTY_LICENSES/libWindbot-MIT.txt"
PURE_ASSIGNMENT = b'UseNerfedCardEffects = !Config.GetBool("UsePreErrataEffects", false);'
LIBRARY_ASSIGNMENT = b'UseNerfedCardEffects = false; // TODO'


def overlay_manifest(lock):
    lock = sources.validate_lock(lock)
    base = next(s for s in lock["sources"] if s["source_id"] == "pure")
    donor = next(s for s in lock["sources"] if s["source_id"] == "library")
    def entry(source, path):
        matches = [f for f in source["files"] if f["path"] == path]
        if len(matches) != 1:
            raise ContractError("exact Monarch506 overlay source/notice is absent")
        return deepcopy(matches[0])
    old, new = entry(base, TARGET), entry(donor, DONOR)
    files = {f["path"]: deepcopy(f) for f in base["files"]}
    files[TARGET] = {**new, "path": TARGET}
    files[NOTICE] = {**entry(donor, donor["license"]["path"]), "path": NOTICE}
    return {"schema_version": 1, "kind": "exact-desktop-bot-overlay", "variant_id": VARIANT_ID,
        "source_lock_sha256": digest(lock), "base": {"repository": base["repository"], "commit": base["commit"]},
        "donor": {"repository": donor["repository"], "commit": donor["commit"], "path": DONOR},
        "replacement": {"path": TARGET, "base_sha256": old["sha256"], "donor_sha256": new["sha256"]},
        "expected_executor_files": sources.COUNTS["pure"][0], "files": files,
        "runtime_loaded": False, "normal_duel_verified": False, "history_verified": False, "strength_verified": False}


def _manifest_bytes(manifest):
    return (canonical_json(manifest) + "\n").encode("utf-8")


def _verify_payload(lock, payload):
    expected = overlay_manifest(lock)
    if set(payload) != set(expected["files"]) | {MANIFEST} or payload[MANIFEST] != _manifest_bytes(expected):
        raise ContractError("overlay membership/manifest differs from its exact two fixed sources")
    for name, entry in expected["files"].items():
        if not sources._check_bytes(payload[name], entry):
            raise ContractError("overlay source/resource byte identity differs: " + name)
    project = sources._project(payload["WindBot.csproj"].decode("utf-8-sig"), expected["files"])
    if project["postbuild_events"] or len(project["compiled_executor_files"]) != sources.COUNTS["pure"][0]:
        raise ContractError("overlay must preserve the full desktop Executor build without post-build execution")
    return expected


def _payload(root):
    root = Path(root).resolve()
    result = {}
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ContractError("overlay source symlinks are not accepted")
        if path.is_file():
            name = path.relative_to(root).as_posix()
            raw = sources._read(root, name)
            total += len(raw)
            if total > sources.MAX_TOTAL:
                raise ContractError("overlay exceeds the bounded source packet size")
            result[name] = raw
    return result


def verify_overlay(lock, root):
    manifest = _verify_payload(lock, _payload(root))
    return {"verified": True, "variant_id": VARIANT_ID, "variant_sha256": digest(manifest),
        "files": len(manifest["files"]), "manifest": manifest, "runtime_loaded": False}


def runtime_overlay_identity(lock, root):
    checked = verify_overlay(lock, root)
    manifest = checked["manifest"]
    return {"variant_id": VARIANT_ID, "manifest_sha256": checked["variant_sha256"],
        "manifest_file_sha256": sources._sha(sources._read(root, MANIFEST)),
        "base": manifest["base"], "donor": manifest["donor"], "replacement": manifest["replacement"]}


def _install(lock, payload, destination):
    manifest = _verify_payload(lock, payload)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ContractError("overlay destination must be new; no overwrite")
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bot-overlay-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "source"
        staging.mkdir()
        for name, raw in payload.items():
            path = staging / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            path.chmod(0o600)
        verify_overlay(lock, staging)
        staging.rename(destination)
    return {"state": "prepared", "variant_id": VARIANT_ID, "variant_sha256": digest(manifest),
        "files": len(manifest["files"]), "runtime_loaded": False, "training_connected": False}


def prepare_overlay(lock, roots, destination):
    data = sources.inventory(lock, roots)
    destination = Path(destination)
    if destination.is_symlink():
        raise ContractError("overlay destination must not be a symlink")
    destination = destination.resolve()
    if any(destination == Path(p).resolve() or destination.is_relative_to(Path(p).resolve()) for p in roots.values()):
        raise ContractError("overlay must use a separate new tree outside all immutable source roots")
    manifest = overlay_manifest(lock)
    base = sources._read(roots["pure"], TARGET)
    donor = sources._read(roots["library"], DONOR)
    if base.count(PURE_ASSIGNMENT) != 1 or base.replace(PURE_ASSIGNMENT, LIBRARY_ASSIGNMENT) != donor:
        raise ContractError("fixed Monarch506 files differ beyond the explicitly reviewed assignment")
    expected = [r for r in data["origins"] if r["source_id"] in ("pure", "library") and r["class_name"] == "Monarch506Executor"]
    if len(expected) != 2 or len({(r["deck_name"], r["deck_file"], r["level"]) for r in expected}) != 1:
        raise ContractError("exact overlay Deck registration differs between its sources")
    payload = {name: sources._read(roots["pure"], name) for name in manifest["files"] if name != NOTICE}
    payload[TARGET] = donor
    library = next(s for s in lock["sources"] if s["source_id"] == "library")
    payload[NOTICE] = sources._read(roots["library"], library["license"]["path"])
    payload[MANIFEST] = _manifest_bytes(manifest)
    return _install(lock, payload, destination)


def bundle_overlay(lock, root, archive):
    payload = _payload(root)
    manifest = _verify_payload(lock, payload)
    archive = Path(archive)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("xb") as output:
        with gzip.GzipFile(filename="", fileobj=output, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as handle:
                for name, raw in sorted(payload.items()):
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = len(raw), 0o600
                    handle.addfile(info, io.BytesIO(raw))
    return {"variant_id": VARIANT_ID, "variant_sha256": digest(manifest), "files": len(manifest["files"]),
        "archive_sha256": sources._sha(archive.read_bytes()), "runtime_loaded": False}


def _archive_payload(archive):
    payload, total = {}, 0
    with tarfile.open(archive, "r:gz") as handle:
        for member in handle:
            if (not member.isfile() or sources._path(member.name) != member.name or member.name in payload
                    or member.size < 0 or member.size > sources.MAX_FILE):
                raise ContractError("unsafe/duplicate overlay archive member")
            total += member.size
            if total > sources.MAX_TOTAL:
                raise ContractError("overlay archive exceeds bounded size")
            payload[member.name] = handle.extractfile(member).read()
    return payload


def verify_overlay_bundle(lock, archive):
    manifest = _verify_payload(lock, _archive_payload(archive))
    return {"verified": True, "variant_id": VARIANT_ID, "variant_sha256": digest(manifest),
        "files": len(manifest["files"]), "runtime_loaded": False}


def install_overlay_bundle(lock, archive, destination):
    return _install(lock, _archive_payload(archive), destination)
