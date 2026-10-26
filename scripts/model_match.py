#!/usr/bin/env python3
"""Preflight a pinned CPU model pair; --run executes one functional BO1/BO3.

Inference only. No training, timing pilot, fetch, C# dependency or formal counts.
All private proof and seed schedules stay in the dedicated .cache state root.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args(argv)
    output = None
    try:
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            output = args.output.open("x", encoding="utf-8")
        from ygo_kito.validation import read_json
        from ygo_kito import model_match_host
        spec = read_json(args.spec)
        result = (model_match_host.run if args.run else model_match_host.preflight)(args.workspace, spec)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, KeyboardInterrupt) as error:
        result = {"kind": "model-match-functional-v1", "status": "blocked", "error_type": type(error).__name__,
            "error": str(error), "training_updates": 0, "formal_matches": 0, "formal_games": 0}
    try:
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)+"\n"
        if output is not None: output.write(encoded)
        sys.stdout.write(encoded)
    finally:
        if output is not None: output.close()
    return 0 if result["status"] in ("ready", "completed") else 2


if __name__ == "__main__": raise SystemExit(main())
