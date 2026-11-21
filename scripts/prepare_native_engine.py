"""Fetch pinned upstream source and build locally. Never downloads executable binaries.

Run from the repository with PYTHONPATH=src .venv/bin/python scripts/prepare_native_engine.py.
Only explicit execution performs downloads/builds; tests and CLI never install anything.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time

from ygo_kito.native_assets import LOCK_PATH, digest, load_period_script_lock, resource_hashes, resource_paths, verify_resources


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


def prepare_period_scripts(root: Path, base: Path, package: Path, lock_id: str):
    """Prepare a separately sealed native root from existing approved resources."""
    lock, binding = load_period_script_lock(lock_id)
    base_receipt = verify_resources(base)
    if "period_script_lock" in base_receipt or base_receipt["resources"] != lock["base_resources"]:
        raise RuntimeError("base resource receipt does not match the period script lock")
    if root == base or root.is_relative_to(base) or root.exists():
        raise FileExistsError("the period resource root must be a new directory outside the base")
    for filename, script in lock["files"].items():
        if (Path(filename).name != filename or not filename.endswith(".lua")
                or (base / "engine-src/scripts" / filename).exists() or digest(package / filename) != script["sha256"]):
            raise RuntimeError(f"period script is not the locked addition: {filename}")
    root.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=root.parent, prefix="native-period-") as scratch:
        staged = Path(scratch) / "root"
        for path in resource_paths(base).values():
            target = staged / path.relative_to(base)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        for directory in ("core", "lua", "scripts"):
            relative = Path("engine-src") / directory
            shutil.copytree(base / relative, staged / relative, symlinks=True, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(".git"))
        for filename in lock["files"]:
            shutil.copy2(package / filename, staged / "engine-src/scripts" / filename)
        resources = dict(lock["base_resources"], scripts=lock["scripts_sha256"])
        receipt = dict(base_receipt, resources=resources, period_script_lock=binding)
        (staged / "engine-build/receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        verify_resources(staged)
        if root.exists():
            raise FileExistsError("the period resource root was created during preparation")
        staged.rename(root)
    print(json.dumps(dict(ok=True, root=str(root), period_script_lock=binding, scripts_sha256=resources["scripts"])))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(".cache"))
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--period-script-lock", help="Prepare a new resource root for an approved period script lock")
    parser.add_argument("--base-native-root", type=Path, help="Existing native root for the selected period lock")
    parser.add_argument("--script-package", type=Path, help="Local directory with the approved Lua files")
    args = parser.parse_args()
    inputs = (args.period_script_lock, args.base_native_root, args.script_package)
    if any(inputs):
        if not all(inputs) or args.rebuild:
            parser.error("period preparation requires --period-script-lock, --base-native-root and --script-package")
        prepare_period_scripts(args.root.resolve(), args.base_native_root.resolve(), args.script_package.resolve(),
                               args.period_script_lock)
    else:
        prepare(args.root.resolve(), rebuild=args.rebuild)
