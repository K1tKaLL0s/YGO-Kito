#!/usr/bin/env python3
"""Prepare a complete desktop-bot audit, or explicitly build/load approved pins.

Requires an already installed official Mono toolchain; never installs packages.
The default only writes a plan. --execute loads third-party code, and --construct
also initializes its catalog/constructors. No room or public endpoint is opened.
"""
import argparse
import json
from pathlib import Path
import sys
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ygo_kito.bot_build_audit import execute_plan, prepare_plan
from ygo_kito.validation import ContractError


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lock", type=Path, default=ROOT / "configs/bot-sources-v1.json")
    p.add_argument("--roots", type=Path, required=True)
    p.add_argument("--source-id", choices=("ice", "pure"), required=True)
    p.add_argument("--cards-cdb", type=Path, required=True)
    p.add_argument("--cards-sha256", required=True)
    p.add_argument("--build-directory", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--construct", action="store_true")
    for tool in ("mono", "compiler", "msbuild"): p.add_argument("--" + tool, type=Path)
    args = p.parse_args()
    try:
        lock = json.loads(args.lock.read_text(encoding="utf-8"))
        plan = prepare_plan(lock, json.loads(args.roots.read_text()), args.source_id,
                            args.cards_cdb, args.cards_sha256, args.build_directory)
        if not args.execute:
            result = plan
        elif any(getattr(args, t) is None for t in ("mono", "compiler", "msbuild")):
            raise ContractError("all explicit verified Mono/compiler/MSBuild paths are required; no execution")
        else:
            result = execute_plan(lock, plan, mono=args.mono, compiler=args.compiler, msbuild=args.msbuild,
                                  construct=args.construct)
        code = 0
    except (ContractError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        result, code = {"error": str(error), "runtime_loaded": False, "training_connected": False}, 2
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2); handle.write("\n")
    print(json.dumps({"report": str(args.report), "runtime_loaded": result.get("runtime_loaded", False), "exit_code": code}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
