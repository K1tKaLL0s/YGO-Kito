"""Integrity receipts for locally built, pinned native smoke resources."""

import hashlib
import json
from pathlib import Path

from .engine import EngineUnavailable

LOCK_PATH = Path(__file__).resolve().parents[2] / "configs/native-sources.lock.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scripts_digest(path: Path) -> str:
    h = hashlib.sha256()
    for entry in sorted(path.rglob("*.lua")):
        h.update(entry.relative_to(path).as_posix().encode() + b"\0")
        h.update(bytes.fromhex(digest(entry)))
    return h.hexdigest()


def resource_hashes(root: Path) -> dict[str, str]:
    src = root / "engine-src"
    files = {
        "library": root / "engine-build/libocgcore.so",
        "cards": src / "database/locales/zh-CN/cards.cdb",
        "banlist": src / "client/lflist.conf",
        "core_api": src / "core/ocgapi.h",
        "core_constants": src / "core/common.h",
        "card_data_abi": src / "core/card_data.h",
        "client_config": src / "client/gframe/config.h",
        "client_protocol": src / "client/gframe/duelclient.cpp",
    }
    return {**{key: digest(path) for key, path in files.items()}, "scripts": scripts_digest(src / "scripts")}


def verify_resources(root: Path) -> dict:
    try:
        receipt = json.loads((root / "engine-build/receipt.json").read_text())
        if receipt["source_lock_sha256"] != digest(LOCK_PATH):
            raise EngineUnavailable("native source lock changed; rebuild explicitly")
        if receipt["resources"] != resource_hashes(root):
            raise EngineUnavailable("native resource integrity mismatch; rebuild explicitly")
        return receipt
    except (OSError, KeyError, ValueError) as error:
        raise EngineUnavailable("native resources unavailable; run scripts/prepare_native_engine.py") from error
