"""Integrity receipts for locally built, pinned native smoke resources."""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from .engine import EngineUnavailable

LOCK_PATH = Path(__file__).resolve().parents[2] / "configs/native-sources.lock.json"
PERIOD_SCRIPT_LOCKS = LOCK_PATH.parent / "native-period-script-locks"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scripts_digest(path: Path) -> str:
    h = hashlib.sha256()
    for entry in sorted(path.rglob("*.lua")):
        h.update(entry.relative_to(path).as_posix().encode() + b"\0")
        h.update(bytes.fromhex(digest(entry)))
    return h.hexdigest()


def resource_paths(root: Path) -> dict[str, Path]:
    src = root / "engine-src"
    return {
        "library": root / "engine-build/libocgcore.so",
        "cards": src / "database/locales/zh-CN/cards.cdb",
        "banlist": src / "client/lflist.conf",
        "core_api": src / "core/ocgapi.h",
        "core_constants": src / "core/common.h",
        "card_data_abi": src / "core/card_data.h",
        "client_config": src / "client/gframe/config.h",
        "client_protocol": src / "client/gframe/duelclient.cpp",
    }


def resource_hashes(root: Path) -> dict[str, str]:
    files = resource_paths(root)
    return {**{key: digest(path) for key, path in files.items()}, "scripts": scripts_digest(root / "engine-src/scripts")}


def load_period_script_lock(lock_id: str) -> tuple[dict, dict]:
    if not isinstance(lock_id, str) or not re.fullmatch(r"[0-9a-z][0-9a-z-]*", lock_id):
        raise EngineUnavailable("invalid period script lock identity")
    path = PERIOD_SCRIPT_LOCKS / (lock_id + ".json")
    try:
        content = path.read_bytes()
        lock = json.loads(content)
        if lock["schema_version"] != 1 or lock["source_lock_sha256"] != digest(LOCK_PATH):
            raise EngineUnavailable("period script lock does not apply to this native source lock")
        upstream = lock["upstream"]
        committed_at = datetime.fromisoformat(upstream["committed_at"])
        if committed_at.utcoffset() is None:
            raise EngineUnavailable("period script lock requires an explicit source timezone")
        source_date = committed_at.astimezone(ZoneInfo("Asia/Tokyo")).date().isoformat()
        binding = dict(id=lock_id, sha256=hashlib.sha256(content).hexdigest(), period_id=lock["period_id"],
                       commit=upstream["commit"], source_date=source_date)
        return lock, binding
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise EngineUnavailable("period script lock unavailable or invalid") from error


def verify_resources(root: Path) -> dict:
    try:
        receipt = json.loads((root / "engine-build/receipt.json").read_text())
        if receipt["source_lock_sha256"] != digest(LOCK_PATH):
            raise EngineUnavailable("native source lock changed; rebuild explicitly")
        if "period_script_lock" in receipt:
            lock, binding = load_period_script_lock(receipt["period_script_lock"]["id"])
            resources = dict(lock["base_resources"], scripts=lock["scripts_sha256"])
            if receipt["period_script_lock"] != binding or receipt["resources"] != resources:
                raise EngineUnavailable("native receipt differs from the locked period script package")
        if receipt["resources"] != resource_hashes(root):
            raise EngineUnavailable("native resource integrity mismatch; rebuild explicitly")
        return receipt
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise EngineUnavailable("native resources unavailable; run scripts/prepare_native_engine.py") from error
