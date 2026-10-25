"""Fetch pinned upstream source and build locally. Never downloads executable binaries.

Run from the repository with PYTHONPATH=src .venv/bin/python scripts/prepare_native_engine.py.
Only explicit execution performs downloads/builds; tests and CLI never install anything.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

from ygo_kito.native_assets import LOCK_PATH, digest, resource_hashes


def run(command, **kwargs):
    return subprocess.run(command, check=True, timeout=240, **kwargs)


def output(command):
    return subprocess.check_output(command, text=True, timeout=30).strip()


def prepare(root: Path, *, rebuild: bool = False):
    lock = json.loads(LOCK_PATH.read_text())
    src = root / "engine-src"
    src.mkdir(parents=True, exist_ok=True)
    for name, source in lock["sources"].items():
        target = src / name
        fresh = not target.exists()
        if fresh:
            command = ["git", "clone", "--no-checkout", "--filter=blob:none", "--depth=1", source["url"], str(target)]
            run(command)
        if not fresh and output(["git", "-C", str(target), "status", "--porcelain", "--untracked-files=no"]):
            raise RuntimeError(f"refusing to overwrite modified source: {name}")
        current = output(["git", "-C", str(target), "rev-parse", "HEAD"])
        if current != source["commit"]:
            run(["git", "-C", str(target), "fetch", "--depth=1", "origin", source["commit"]])
        if source.get("sparse"):
            run(["git", "-C", str(target), "sparse-checkout", "set", *source["sparse"]])
        run(["git", "-C", str(target), "checkout", "--detach", source["commit"]])
        if output(["git", "-C", str(target), "rev-parse", "HEAD"]) != source["commit"]:
            raise RuntimeError("source checkout did not match lock")
    for path, name in (("ocgcore", "core"), ("script", "scripts")):
        entry = output(["git", "-C", str(src / "client"), "ls-tree", "HEAD", path]).split()
        if len(entry) < 3 or entry[2] != lock["sources"][name]["commit"]:
            raise RuntimeError("client submodule pins do not match locked core/scripts")
    config_text = (src / "client/gframe/config.h").read_text()
    if "PRO_VERSION = " + lock["protocol"]["client_version_hex"] not in config_text:
        raise RuntimeError("client protocol version differs from lock")
    build = root / "engine-build"
    build.mkdir(exist_ok=True)
    # Follow pinned core/premake/lua.lua: compile Lua as C++, omit entry points/linit.
    excluded = {"lua.c", "luac.c", "linit.c", "onelua.c", "ltests.c"}
    def tracked_sources(name, suffix):
        names = output(["git", "-C", str(src / name), "ls-files"]).splitlines()
        return [src / name / p for p in sorted(names) if "/" not in p and p.endswith(suffix) and p not in excluded]
    sources = tracked_sources("core", ".cpp") + tracked_sources("lua", ".c")
    command = ["g++", "-std=c++17", "-O1", "-fPIC", "-shared", "-DOCGCORE_EXPORT_FUNCTIONS", "-DLUA_USE_LINUX",
               "-I" + str(src / "lua"), *map(str, sources), "-ldl", "-lm", "-o", str(build / "libocgcore.so")]
    if (build / "libocgcore.so").exists() and not rebuild:
        raise RuntimeError("library already exists; pass --rebuild to replace this generated file")
    start = time.monotonic()
    with (build / "build.log").open("w") as log:
        run(command, stdout=log, stderr=subprocess.STDOUT)
    receipt = {"schema_version": 1, "built_at_utc": datetime.now(timezone.utc).isoformat(),
               "source_lock_sha256": digest(LOCK_PATH), "source_commits": {key: s["commit"] for key, s in lock["sources"].items()},
               "resources": resource_hashes(root), "compiler": output(["g++", "--version"]).splitlines()[0],
               "build_seconds": round(time.monotonic() - start, 3), "command": command}
    (build / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"ok": True, "receipt": str(build / "receipt.json"), "build_seconds": receipt["build_seconds"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(".cache"))
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    prepare(args.root.resolve(), rebuild=args.rebuild)
