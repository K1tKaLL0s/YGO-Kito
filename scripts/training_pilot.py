#!/usr/bin/env python3
"""Preflight a pinned CPU model/bot BO1 pilot; --run explicitly samples only.

No training, installation, download, BO3 emulation or fallback. --template writes
an intentionally incomplete host spec; fill its real artifact identities first.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ygo_kito.training_pilot import prepare_pilot
from ygo_kito.validation import ContractError, read_json


def template():
    return {"schema_version": 1, "kind": "cpu-frozen-model-bot-timing-pilot", "mode": "bo1",
        "snapshot": {"kind": "completed-duel-checkpoint", "path": None, "sha256": None,
            "source_binding_sha256": None, "model_sha256": None, "migration": "explicit-frozen-inference"},
        "bot_sources": {"lock": {"path": "configs/bot-sources-v1.json", "sha256": None},
            "installed_root": None, "mono": None, "audits": {"ice": {"path": None, "sha256": None}}},
        "cases": [{"case_id": "fill-explicit-case", "profile": {"path": None, "sha256": None},
            "qualification": {"path": None, "sha256": None},
            "actor_seat": 0, "source_id": "ice", "executor_id": None,
            "seeds": [{"game_seed": 10001, "policy_seed": 20001}],
            "coverage": ["fill-actual-case-scope"], "evidence_source": "engineering_fixture"}],
        "limits": {"episode_seconds": 120, "native_decision_limit": 3000},
        "reserved_evaluation_seeds": []}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--native-root", type=Path, default=ROOT / ".cache")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--run", action="store_true")
    group.add_argument("--template", action="store_true")
    args = parser.parse_args(argv)
    if not args.template and args.config is None: parser.error("--config is required except for --template")
    # Establish exclusive, durable output before any optional execution. Never
    # overwrite an old timing/failure receipt to select a more favourable run.
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        output = args.output.open("x", encoding="utf-8")
    except OSError as error:
        print(json.dumps({"status": "blocked", "stage": "output_setup", "error": str(error), "training_updates": 0}))
        return 2
    latest = {}
    def persist(value):
        latest.clear(); latest.update(value)
        output.seek(0); output.truncate()
        json.dump(value, output, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
        output.write("\n"); output.flush(); os.fsync(output.fileno())
    with output:
        if args.template:
            persist(template())
            print(json.dumps({"output": str(args.output), "status": "incomplete_template", "execution_started": False}))
            return 0
        persist({"schema_version": 1, "kind": "cpu-bo1-timing-pilot", "status": "blocked",
                 "stage": "configuration_preflight", "training_updates": 0, "native_executed": False,
                 "csharp_execution_attempted": False, "formal_games": 0})
        try:
            pilot = prepare_pilot(args.workspace, args.native_root, read_json(args.config))
            result = pilot.run(progress=persist) if args.run else pilot.preflight()
        except (ContractError, OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            result = dict(latest)
            result.update(status="partial" if latest.get("status") == "running" else "blocked",
                stage="unexpected_pilot_error" if latest.get("status") == "running" else "configuration_preflight",
                error_type=type(error).__name__, error=str(error))
        persist(result)
    code = 0 if result["status"] in ("ready", "completed") else 2
    print(json.dumps({"output": str(args.output), "status": result["status"], "exit_code": code,
                      "training_updates": 0, "formal_games": 0}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
