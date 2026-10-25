#!/usr/bin/env python3
"""Preflight explicit scenario-course artifacts; games require --run/--pilot.

No installation, data download, random-model fallback or implicit resume.
The incomplete template cannot enable a course. Private state stays local.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--purpose", choices=("train", "validation", "final_eval"), default="train")
    parser.add_argument("--max-matches", type=int)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--pilot", action="store_true")
    mode.add_argument("--template", action="store_true")
    args = parser.parse_args(argv)
    if not args.template and args.config is None: parser.error("--config is required except for --template")
    if not args.run and (args.max_matches is not None or args.purpose != "train"):
        parser.error("--purpose and --max-matches execution options require --run")
    if args.max_matches is not None and args.max_matches < 1:
        parser.error("--max-matches must be positive")
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        output = args.output.open("x", encoding="utf-8")
    except OSError as error:
        print(json.dumps({"status": "blocked", "stage": "output_setup", "error_type": type(error).__name__}))
        return 2
    latest = {}
    def persist(value):
        latest.clear(); latest.update(value)
        output.seek(0); output.truncate()
        json.dump(value, output, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
        output.write("\n"); output.flush(); os.fsync(output.fileno())
    with output:
        persist({"kind": "scenario-course-host-entry", "status": "blocked", "stage": "configuration_preflight",
            "native_executed": False, "csharp_executed": False, "training_updates": 0,
            "formal_training_success_verified": False})
        try:
            from ygo_kito.validation import read_json
            if args.template:
                persist(read_json(ROOT / "configs/scenario-course-template-v1.json"))
                print(json.dumps({"status": "incomplete_template", "execution_started": False, "output": str(args.output)}))
                return 0
            from ygo_kito.scenario_course_host import prepare_course
            host = prepare_course(args.workspace, read_json(args.config))
            if args.run:
                result = host.run(purpose=args.purpose, max_matches=args.max_matches, progress=persist)
            elif args.pilot:
                result = host.timing_pilot(progress=persist)
            else:
                result = host.preflight()
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError, KeyboardInterrupt) as error:
            result = dict(latest)
            result.update(status="partial" if latest.get("status") == "running" else "blocked",
                stage="host_entry_error", error_type=type(error).__name__, error=str(error))
        persist(result)
    code = 0 if result.get("status") in ("ready", "bounded_invocation_finished", "paused", "completed") else 2
    print(json.dumps({"status": result.get("status"), "output": str(args.output), "exit_code": code,
                      "formal_training_success_verified": False}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
