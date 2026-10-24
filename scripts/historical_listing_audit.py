"""Read-only pinned listing audit; no download, registry or engine execution."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "src"))

from ygo_kito.historical_listing import audit_listings
from ygo_kito.validation import ContractError, read_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--index", type=Path, default=ROOT / "configs/historical-listing-sources-v1.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = audit_listings(read_json(args.index), args.workspace)
    except (OSError, ContractError) as error:
        print(json.dumps({"ok": False, "error": str(error), "native_executed": False}, ensure_ascii=False))
        return 2
    if args.output is None:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"output": str(args.output), "samples": len(report["samples"]), "periods": list(report["periods"]),
                          "native_executed": False, "historical_rules_verified": False, "formal_training_ready": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
