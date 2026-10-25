#!/usr/bin/env python3
"""Check every fixed bot listing; actual bounded C# games require --execute.

No installation, network, model training, paid calls or source fallback. The
default engineering actor is the existing native smoke pool, not formal data.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ygo_kito.bot_deployment import BotSourceRegistry
from ygo_kito.bot_qualification import prepare_qualification, execute_qualification, normal_engineering_actor
from ygo_kito.validation import ContractError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--lock", type=Path, default=ROOT / "configs/bot-sources-v1.json")
    parser.add_argument("--installed-root", type=Path, required=True)
    parser.add_argument("--native-root", type=Path, required=True)
    parser.add_argument("--actor-profile", type=Path)
    parser.add_argument("--actor-seat", type=int, choices=(0, 1), default=0)
    parser.add_argument("--variant-root", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--audits", type=Path, help='JSON source/variant ID -> {"path":...,"sha256":...}')
    parser.add_argument("--mono", type=Path)
    parser.add_argument("--bot-id", action="append", help="Exact bot SHA identity; default all desktop candidates")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--max-decisions", type=int, default=3000)
    args = parser.parse_args()
    try:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        output = args.report.open("x", encoding="utf-8")
    except OSError as error:
        print(json.dumps({"error": str(error), "stage": "report_setup", "exit_code": 2,
                          "native_executed": False, "csharp_executed": False}))
        return 2
    execution_call_started = False
    def persist(value):
        output.seek(0); output.truncate()
        json.dump(value, output, ensure_ascii=False, indent=2); output.write("\n")
        output.flush(); os.fsync(output.fileno())
    try:
        persist({"schema_version": 1, "kind": "bot-qualification-progress", "status": "not_completed",
                 "stage": "preflight", "native_executed": False, "csharp_executed": False,
                 "normal_duel_verified": False, "training_updates": 0})
        registry = BotSourceRegistry(json.loads(args.lock.read_text()), args.installed_root)
        actor = (json.loads(args.actor_profile.read_text()) if args.actor_profile
                 else normal_engineering_actor(args.native_root))
        result = prepare_qualification(registry, args.native_root, actor, actor_seat=args.actor_seat,
                                       variant_root=args.variant_root)
        code = 0
        if args.execute:
            if args.audits is None or args.mono is None:
                raise ContractError("actual complete audit references and explicit Mono path required; no game executed")
            audits = json.loads(args.audits.read_text())
            persist({"schema_version": 1, "kind": "bot-qualification-progress", "status": "not_completed",
                     "stage": "execution_requested", "native_executed": None, "csharp_executed": None,
                     "normal_duel_verified": False, "training_updates": 0})
            execution_call_started = True
            result = execute_qualification(registry, result, args.native_root, actor,
                audits=audits, mono=args.mono, workspace=args.workspace,
                selected_bot_ids=args.bot_id, seed=args.seed, seconds=args.seconds,
                max_decisions=args.max_decisions, variant_root=args.variant_root)
            code = 0 if result["all_selected_normal_verified"] else 2
    except (ContractError, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        result, code = {"error": str(error), "stage": "qualification_plan_or_explicit_preflight",
                        "native_executed": None if execution_call_started else False,
                        "csharp_executed": None if execution_call_started else False, "training_updates": 0}, 2
    with output:
        persist(result)
    print(json.dumps({"report": str(args.report), "exit_code": code,
                      "native_executed": result.get("native_executed"), "csharp_executed": result.get("csharp_executed")}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
