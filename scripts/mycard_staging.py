#!/usr/bin/env python3
"""Stage public popular themes only; offline by default, --fetch is explicit."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv=None):
    from ygo_kito.mycard_staging import (MAX_BYTES, SOURCES, WINDOWS, PublicFetchStopped, fetch_themes, stage_themes)
    from ygo_kito.validation import ContractError
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--input", type=Path, help="existing public-response bytes; makes no network request")
    mode.add_argument("--fetch", action="store_true", help="one public GET, then stop; no auth or retries")
    parser.add_argument("--window", choices=WINDOWS, default="day")
    parser.add_argument("--source", choices=SOURCES, default="mycard-athletic")
    parser.add_argument("--collected-at", help="actual original collection ISO timestamp for offline bytes; never inferred")
    parser.add_argument("--cache-root", type=Path, default=ROOT/".cache/mycard-theme-staging")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.fetch and args.collected_at is not None: parser.error("--collected-at is offline evidence only")
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        output = args.output.open("x", encoding="utf-8")
    except OSError as error:
        print(json.dumps({"status": "blocked", "stage": "output_setup", "error_type": type(error).__name__}))
        return 2
    with output:
        result = {"kind": "mycard-popular-theme-staging-v1", "status": "blocked", "network_attempted": False,
                  "execution_enabled": False, "formal_training_ready": False}
        def persist(value):
            output.seek(0); output.truncate()
            json.dump(value, output, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
            output.write("\n"); output.flush(); os.fsync(output.fileno())
        persist(result)
        try:
            collection = None
            if args.fetch:
                result["network_attempted"] = None; persist(result)
                raw, collection = fetch_themes(args.cache_root, window=args.window, source=args.source)
                collected_at = collection["collected_at"]
                result.update(network_attempted=True, public_collection=collection)
                persist(result)
            else:
                with args.input.open("rb") as source: raw = source.read(MAX_BYTES + 1)
                collected_at = args.collected_at
            result = stage_themes(raw, window=args.window, source=args.source, collected_at=collected_at)
            result["network_attempted"] = args.fetch
            if collection is not None: result["public_collection"] = collection
        except PublicFetchStopped as error:
            result.update(status="fetch_failed", network_attempted=True, public_collection=error.receipt)
        except (ContractError, OSError, ValueError, TypeError, RecursionError) as error:
            result.update(status="blocked", error_type=type(error).__name__, error=str(error))
        persist(result)
    code = 0 if result["status"] == "staged_pending_source_review" else 2
    print(json.dumps({"status": result["status"], "theme_count": result.get("theme_count", 0),
        "output": str(args.output), "network_attempted": result.get("network_attempted"), "formal_training_ready": False, "exit_code": code}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
