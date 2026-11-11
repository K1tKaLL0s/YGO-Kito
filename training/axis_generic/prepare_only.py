"""Explicit v3 data preparation entry; no model/device imports or optimizer."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent.parent / "src"))

import runtime  # noqa: E402
from prepare_v3 import prepare, read_json as read  # noqa: E402


def emit(event, **kwargs):
    print(json.dumps({"event": event, **kwargs}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Explicit versioned preparation config, e.g. config.v3.json")
    args = parser.parse_args()
    config = read(args.config)
    if config.get("feature_schema") != "axis-graph-v3":
        parser.error("v3 feature_schema required; old config/runs remain read-only")
    runtime.warn_if_hash_seed_unset()
    runtime.seed_preparation(config["seed"])
    run = Path(config["run_dir"])
    report = prepare(config, run, emit)
    print(json.dumps({key: report[key] for key in ("version", "split_counts", "source_counts", "stats")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
