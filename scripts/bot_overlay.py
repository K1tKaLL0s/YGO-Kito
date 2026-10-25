#!/usr/bin/env python3
"""Prepare/verify/install a distinct exact-source Monarch506 desktop overlay.

Never compiles, starts Mono, builds Android, opens a room, or uses the network.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ygo_kito.bot_overlay import (bundle_overlay, install_overlay_bundle, prepare_overlay,
                                  verify_overlay, verify_overlay_bundle)
from ygo_kito.validation import ContractError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=ROOT / "configs/bot-sources-v1.json")
    parser.add_argument("--report", type=Path)
    sub = parser.add_subparsers(dest="operation", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--roots", type=Path, required=True)
    p.add_argument("--destination", type=Path, required=True)
    p = sub.add_parser("verify")
    p.add_argument("--root", type=Path, required=True)
    p = sub.add_parser("bundle")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    for name in ("verify-bundle", "install"):
        p = sub.add_parser(name)
        p.add_argument("--archive", type=Path, required=True)
        if name == "install": p.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        lock = json.loads(args.lock.read_text(encoding="utf-8"))
        if args.operation == "prepare":
            result = prepare_overlay(lock, json.loads(args.roots.read_text()), args.destination)
        elif args.operation == "verify": result = verify_overlay(lock, args.root)
        elif args.operation == "bundle": result = bundle_overlay(lock, args.root, args.archive)
        elif args.operation == "verify-bundle": result = verify_overlay_bundle(lock, args.archive)
        else: result = install_overlay_bundle(lock, args.archive, args.destination)
        code = 0
    except (ContractError, OSError, ValueError, KeyError, TypeError) as error:
        result, code = {"error": str(error), "outcome": "preparation_failed", "runtime_loaded": False}, 2
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2); handle.write("\n")
    else: print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
