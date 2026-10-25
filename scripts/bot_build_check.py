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
from ygo_kito.bot_build_audit import BuildAuditError, execute_plan, failure_report, prepare_plan, prepare_overlay_plan
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
    p.add_argument("--variant-root", type=Path, help="explicit separately verified exact Monarch506 overlay; does not modify original pins")
    p.add_argument("--timeout", type=float, default=180)
    for tool in ("mono", "compiler", "msbuild"): p.add_argument("--" + tool, type=Path)
    args = p.parse_args()
    try:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        report_handle = args.report.open("x", encoding="utf-8")
    except OSError:
        print(json.dumps(failure_report("exclusive report destination unavailable; no build attempted", stage="report_setup")))
        return 2
    plan = None
    try:
        lock = json.loads(args.lock.read_text(encoding="utf-8"))
        roots = json.loads(args.roots.read_text())
        if args.variant_root is not None:
            if args.source_id != "pure":
                raise ContractError("the exact overlay has an explicit Pure desktop base only")
            plan = prepare_overlay_plan(lock, roots, args.variant_root, args.cards_cdb, args.cards_sha256, args.build_directory)
        else:
            plan = prepare_plan(lock, roots, args.source_id, args.cards_cdb, args.cards_sha256, args.build_directory)
        if not args.execute:
            result = plan
        else:
            result = execute_plan(lock, plan, mono=args.mono, compiler=args.compiler, msbuild=args.msbuild,
                                  construct=args.construct, timeout=args.timeout)
        code = 0
    except BuildAuditError as error:
        result, code = error.report, 2
    except (ContractError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        message = str(error) if isinstance(error, ContractError) else "required input could not be read or parsed"
        result, code = failure_report(message, plan=plan), 2
    with report_handle:
        json.dump(result, report_handle, ensure_ascii=False, indent=2); report_handle.write("\n")
    print(json.dumps({"report": str(args.report), "runtime_loaded": result.get("runtime_loaded", False), "exit_code": code}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
