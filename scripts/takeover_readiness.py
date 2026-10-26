#!/usr/bin/env python3
"""Print a read-only takeover audit; this command cannot launch training."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/"src"))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace",type=Path,default=ROOT)
    parser.add_argument("--config",type=Path)
    args=parser.parse_args(argv)
    from ygo_kito.takeover_readiness import collect
    from ygo_kito.validation import ContractError
    try:
        config=None if args.config is None else json.loads(args.config.read_text(encoding="utf-8"))
        report=collect(args.workspace,config)
    except (OSError,ValueError,KeyError,TypeError,RuntimeError,ContractError) as error:
        # Never interpolate arbitrary file content, paths or exception text.
        print(json.dumps({"kind":"cpu-takeover-readiness-report","mode":"audit_only","status":"invalid_or_unreadable_input",
            "error_type":type(error).__name__,"training_started":False,"native_executed":False}))
        return 2
    print(json.dumps(report,ensure_ascii=False,allow_nan=False,sort_keys=True,indent=2))
    return 0


if __name__=="__main__":raise SystemExit(main())
