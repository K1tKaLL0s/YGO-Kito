#!/usr/bin/env python3
"""Pinned source fetch and offline checks. Never launches a bot or compiler."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ygo_kito.bot_deployment import (BotSourceRegistry, approval_packet, create_bundle,
                                     fetch_sources, install_sources, inventory, verify_bundle, SourceFetchStopped)
from ygo_kito.validation import ContractError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=ROOT / "configs/bot-sources-v1.json")
    parser.add_argument("--output", type=Path)
    sub = parser.add_subparsers(dest="operation", required=True)
    p = sub.add_parser("fetch")
    p.add_argument("--destination", type=Path, required=True)
    p.add_argument("--timeout", type=float, default=30)
    for name in ("inventory", "bundle"):
        p = sub.add_parser(name)
        p.add_argument("--roots", type=Path, required=True, help="JSON mapping each fixed source ID to its explicit source directory")
        if name == "bundle": p.add_argument("--archive", type=Path, required=True)
    for name in ("verify", "install"):
        p = sub.add_parser(name)
        p.add_argument("--archive", type=Path, required=True)
        if name == "install": p.add_argument("--destination", type=Path, required=True)
    p = sub.add_parser("registry")
    p.add_argument("--installed-root", type=Path, required=True)
    p = sub.add_parser("approval-packet")
    p.add_argument("--source-id", choices=("ice", "pure"), required=True)
    p.add_argument("--source-directory", type=Path, required=True)
    p.add_argument("--deck-name", default="ChaosRitual")
    p.add_argument("--port", type=int, default=7911)
    args = parser.parse_args()
    try:
        lock = json.loads(args.lock.read_text(encoding="utf-8"))
        if args.operation == "fetch": result = fetch_sources(lock, args.destination, timeout=args.timeout)
        elif args.operation in ("inventory", "bundle"):
            roots = json.loads(args.roots.read_text(encoding="utf-8"))
            result = inventory(lock, roots) if args.operation == "inventory" else create_bundle(lock, roots, args.archive)
        elif args.operation == "verify": result = verify_bundle(args.archive, lock)
        elif args.operation == "install": result = install_sources(args.archive, lock, args.destination)
        elif args.operation == "registry":
            registry = BotSourceRegistry(lock, args.installed_root)
            result = {"source_registry_loaded": True, "bots": [asdict(s) for s in registry.statuses()], "training_connected": False}
        else:
            result = approval_packet(lock, args.source_id, args.source_directory, deck_name=args.deck_name, port=args.port)
        code = 0
    except SourceFetchStopped as error:
        result, code = {"error": str(error), "fetch_stopped": error.details, "training_connected": False}, 2
    except (ContractError, OSError, ValueError, KeyError, TypeError) as error:
        result, code = {"error": str(error), "training_connected": False}, 2
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle: handle.write(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
