"""JSON CLI for infrastructure checks, never a simulated duel demonstration."""

import argparse
import json
from pathlib import Path
import platform
import sqlite3
import sys
import tomllib

from . import __version__
from .config import load_config
from .contracts import ActionSelection, DecisionRequest, validate_selection
from .engine import EngineUnavailable, engine_status, open_engine
from .native import NativeError, run_native_smoke
from .storage import Store
from .validation import ContractError, canonical_json, integer, read_json


def parser():
    result = argparse.ArgumentParser(prog="ygo-kito", description=__doc__)
    result.add_argument("--config", type=Path, help="TOML configuration; place before command")
    sub = result.add_subparsers(dest="command", required=True)
    for command in ("status", "config-check", "db-init", "duel-run"):
        sub.add_parser(command)
    sub.add_parser("cards-import").add_argument("input", type=Path)
    sub.add_parser("card-show").add_argument("card_id", type=int)
    sub.add_parser("request-check").add_argument("input", type=Path)
    action = sub.add_parser("action-check")
    action.add_argument("request", type=Path)
    action.add_argument("selection", type=Path)
    native = sub.add_parser("native-smoke", help="one real normal summon; requires explicitly prepared native sources")
    native.add_argument("--root", type=Path, default=Path(".cache"))
    native.add_argument("--seed", type=int, default=7)
    duel = sub.add_parser("native-duel", help="complete a duel in the explicit normal-monster pool")
    duel.add_argument("--root", type=Path, default=Path(".cache"))
    duel.add_argument("--seed", type=int, default=7)
    duel.add_argument("--trace", type=Path)
    replay = sub.add_parser("native-replay", help="replay saved native responses and compare all events")
    replay.add_argument("input", type=Path)
    replay.add_argument("--root", type=Path, default=Path(".cache"))
    effects = sub.add_parser("native-effects", help="two selected real-script cost/chain cases")
    effects.add_argument("--root", type=Path, default=Path(".cache"))
    effects.add_argument("--route", choices=("negate", "resolve"), default="negate")
    effects.add_argument("--seed", type=int, default=1724)
    effects.add_argument("--trace", type=Path)
    effects_replay = sub.add_parser("native-effect-replay")
    effects_replay.add_argument("input", type=Path)
    effects_replay.add_argument("--root", type=Path, default=Path(".cache"))
    search = sub.add_parser("native-search", help="selected real deck-search/trigger/count-limit cases")
    search.add_argument("--root", type=Path, default=Path(".cache"))
    search.add_argument("--route", choices=("field-twice", "deck-grave", "cross-turn", "shared-name", "activation-lock", "activation-control"), default="field-twice")
    search.add_argument("--seed", type=int)
    search.add_argument("--trace", type=Path)
    search_replay = sub.add_parser("native-search-replay")
    search_replay.add_argument("input", type=Path)
    search_replay.add_argument("--root", type=Path, default=Path(".cache"))
    effect_duel = sub.add_parser("native-effect-duel", help="complete a real duel for an explicit effect-deck profile")
    effect_duel.add_argument("--root", type=Path, default=Path(".cache"))
    effect_duel.add_argument("--profile", type=Path, default=Path("configs/effect-duel-v1.json"))
    effect_duel.add_argument("--seed", type=int, default=7)
    effect_duel.add_argument("--option-preference", choices=("first", "last"), default="first")
    effect_duel.add_argument("--trace", type=Path)
    effect_duel_replay = sub.add_parser("native-effect-duel-replay")
    effect_duel_replay.add_argument("input", type=Path)
    effect_duel_replay.add_argument("--root", type=Path, default=Path(".cache"))
    train = sub.add_parser("duel-train-cpu", help="bounded real-core CPU parameter-update/recovery proof; no provider or paid resource launch")
    train.add_argument("--root", type=Path, default=Path(".cache"))
    train.add_argument("--state-root", type=Path, default=Path(".cache/agent"))
    train.add_argument("--run-id", required=True)
    train.add_argument("--profile", type=Path, default=Path("configs/effect-duel-v1.json"))
    train.add_argument("--training-config", type=Path, default=Path("configs/cpu-training-smoke.json"))
    build_check = sub.add_parser("build-check", help="validate a typed building task and three card-list sections; no route/quality claim")
    build_check.add_argument("--root", type=Path, default=Path(".cache"))
    build_check.add_argument("--task", type=Path, default=Path("configs/build-engineering-v1.json"))
    build_check.add_argument("--deck", type=Path, required=True)
    build_train = sub.add_parser("build-train-cpu", help="bounded independent goal/optimizer CPU updates, recovery and real conditional goal checks")
    build_train.add_argument("--root", type=Path, default=Path(".cache"))
    build_train.add_argument("--state-root", type=Path, default=Path(".cache/agent"))
    build_train.add_argument("--run-id", required=True)
    build_train.add_argument("--task", type=Path, default=Path("configs/build-engineering-v1.json"))
    build_train.add_argument("--training-config", type=Path, default=Path("configs/build-training-smoke.json"))
    group = sub.add_parser("model-group-cpu", help="one bounded real group workflow with pre-registered forecast and pending-job recovery")
    group.add_argument("--root", type=Path, default=Path(".cache"))
    group.add_argument("--state-root", type=Path, default=Path(".cache/agent"))
    group.add_argument("--run-id", required=True)
    group.add_argument("--task", type=Path, default=Path("configs/build-engineering-v1.json"))
    group.add_argument("--feedback-policy", type=Path, default=Path("configs/coordinator-feedback-engineering.json"))
    lora = sub.add_parser("lora-group-cpu", help="actual frozen-base four-role LoRA updates and native evaluation/recovery; no paid launch")
    lora.add_argument("--root", type=Path, default=Path(".cache"))
    lora.add_argument("--state-root", type=Path, default=Path(".cache/agent"))
    lora.add_argument("--run-id", required=True)
    lora.add_argument("--task", type=Path, default=Path("configs/build-engineering-v1.json"))
    lora.add_argument("--lora-config", type=Path, default=Path("configs/lora-engineering-v1.json"))
    lora.add_argument("--feedback-policy", type=Path, default=Path("configs/coordinator-feedback-engineering.json"))
    control = sub.add_parser("coordinator-call", help="fixed-role JSON coordination/monitor tools; no arbitrary commands or paid jobs")
    control.add_argument("input", type=Path)
    control.add_argument("--ledger", type=Path, required=True)
    control.add_argument("--role", choices=("monitor", "coordinator", "build_goal", "build_optimizer", "duel_worker"), default="monitor")
    control.add_argument("--source", choices=("real_engine", "synthetic_contract_test"), default="real_engine")
    control.add_argument("--root", type=Path, default=Path(".cache"))
    control.add_argument("--feedback-policy", type=Path, default=Path("configs/coordinator-feedback-engineering.json"))
    control.add_argument("--create", action="store_true")
    preflight = sub.add_parser("training-preflight", help="local CPU health and pending training gates; no credentials or paid launch")
    preflight.add_argument("--root", type=Path, default=Path(".cache"))
    preflight.add_argument("--plan", type=Path, default=Path("configs/training-plan-v1.json"))
    budget = sub.add_parser("budget-call", help="fixed-role host-reported usage ledger; never starts or stops resources")
    budget.add_argument("input", type=Path)
    budget.add_argument("--ledger", type=Path, required=True)
    budget.add_argument("--plan", type=Path, default=Path("configs/training-plan-v1.json"))
    budget.add_argument("--role", choices=("monitor", "trainer"), default="monitor")
    budget.add_argument("--source", choices=("host_reported_unverified", "synthetic_contract_test"), default="host_reported_unverified")
    budget.add_argument("--create", action="store_true")
    for name in ("agent-serve", "agent-call"):
        agent = sub.add_parser(name, help="host-scoped local JSON tools; no provider or training launch")
        if name == "agent-call":
            agent.add_argument("input", type=Path)
        agent.add_argument("--role", choices=("monitor", "trainer", "manager", "opponent"), default="monitor")
        agent.add_argument("--state-root", type=Path, default=Path(".cache/agent"))
        agent.add_argument("--root", type=Path, default=Path(".cache"))
        agent.add_argument("--seat", type=int, choices=(0, 1), default=1)
        agent.add_argument("--profile", type=Path)
        agent.add_argument("--seed", type=int, default=7)
        agent.add_argument("--decision-timeout", type=float, default=30)
        agent.add_argument("--opponent-id")
        agent.add_argument("--own-deck-id")
        agent.add_argument("--controller-source", choices=("unverified_external", "local_contract_fixture"), default="unverified_external")
        agent.add_argument("--provider", default="unverified")
        agent.add_argument("--model", default="unverified")
        agent.add_argument("--local-cpu-control", action="store_true", help="trusted host opt-in for prepared, bounded local CPU workers only")
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config(args.config)
        match args.command:
            case "status":
                output = {"version": __version__, "python": platform.python_version(),
                          "sqlite": sqlite3.sqlite_version, "config": config.to_dict(), "engine": engine_status()}
            case "config-check":
                output = {"ok": True, "config": config.to_dict()}
            case "db-init":
                Store.initialize(config.database)
                output = {"ok": True, "database": str(config.database), "schema_version": 1}
            case "cards-import":
                dataset = read_json(args.input)
                with Store(config.database) as store:
                    cards, annotations = store.import_dataset(dataset)
                output = {"ok": True, "processed_cards": cards, "processed_annotations": annotations,
                          "rules_verified": False}
            case "card-show":
                integer(args.card_id, "card_id", 1, 2**63 - 1)
                with Store(config.database) as store:
                    card = store.get_card(args.card_id)
                    if card is None:
                        raise ContractError("card_id not found")
                    output = {"card": card.to_dict(), "annotations": [a.to_dict() for a in store.annotations(args.card_id)]}
            case "request-check" | "action-check":
                request = DecisionRequest.from_dict(read_json(args.input if args.command == "request-check" else args.request))
                output = {"ok": True, "validation": "contract_only", "rules_verified": False,
                          "run_id": request.context.run_id, "duel_id": request.duel_id,
                          "decision_id": request.decision_id, "action_count": len(request.actions)}
                if args.command == "action-check":
                    selection = ActionSelection.from_dict(read_json(args.selection))
                    output["action_id"] = validate_selection(request, selection).action_id
            case "duel-run":
                open_engine()  # Always raises until a real compatible adapter is implemented.
                raise EngineUnavailable("no runnable engine backend")
            case "native-smoke":
                output = run_native_smoke(args.root, args.seed)
            case "duel-train-cpu":
                try:
                    from .cpu_training import config_from_dict, run_cpu_training_smoke
                except ModuleNotFoundError as error:
                    if error.name != "torch":
                        raise
                    raise EngineUnavailable("CPU PyTorch required for this optional command; infrastructure commands do not require it") from None
                output = run_cpu_training_smoke(args.root, args.state_root, args.run_id,
                                               read_json(args.profile), config_from_dict(read_json(args.training_config)))
            case "build-check":
                from .build_contracts import BuildTask, DeckParts
                from .build_pipeline import BuildAssets
                output = dict(BuildAssets(args.root).validate(BuildTask.from_dict(read_json(args.task)),
                                                             DeckParts.from_dict(read_json(args.deck))),
                              ok=True, route_status="not_evaluated", construction_quality_status="not_evaluated")
            case "build-train-cpu":
                try:
                    from .build_training import config_from_dict, run_build_training_smoke
                except ModuleNotFoundError as error:
                    if error.name != "torch":
                        raise
                    raise EngineUnavailable("CPU PyTorch required for this optional command") from None
                from .build_contracts import BuildTask
                output = run_build_training_smoke(args.root, args.state_root, args.run_id,
                                                 BuildTask.from_dict(read_json(args.task)), config_from_dict(read_json(args.training_config)))
            case "training-preflight":
                from .training_preflight import cpu_preflight
                output = cpu_preflight(args.root, read_json(args.plan))
                print(canonical_json(output))
                return 0 if output["ok"] else 2
            case "budget-call":
                from .training_plan import BudgetBook
                book = BudgetBook(args.ledger, read_json(args.plan), role=args.role, source=args.source, create=args.create)
                output = book.dispatch(read_json(args.input))
                print(canonical_json(output))
                return 0 if output["ok"] else 2
            case "lora-group-cpu":
                try:
                    from .lora_group import run_lora_group_smoke
                    from .build_contracts import BuildTask
                    from .coord_contracts import FeedbackPolicy
                except ImportError:
                    raise EngineUnavailable("CPU PyTorch required for LoRA group proof") from None
                output = run_lora_group_smoke(args.root, args.state_root, args.run_id, BuildTask.from_dict(read_json(args.task)),
                                             read_json(args.lora_config), FeedbackPolicy.from_dict(read_json(args.feedback_policy)))
            case "model-group-cpu":
                try:
                    from .model_group import run_model_group_smoke
                except ModuleNotFoundError as error:
                    if error.name != "torch":
                        raise
                    raise EngineUnavailable("CPU PyTorch required for model-group proof") from None
                from .build_contracts import BuildTask
                from .coord_contracts import FeedbackPolicy
                output = run_model_group_smoke(args.root, args.state_root, args.run_id, BuildTask.from_dict(read_json(args.task)),
                                               FeedbackPolicy.from_dict(read_json(args.feedback_policy)))
            case "coordinator-call":
                from .coord_contracts import FeedbackPolicy
                from .coordinator import Coordinator
                payload = read_json(args.input)
                assets = None
                if (args.role in ("coordinator", "build_goal", "build_optimizer") and args.source == "real_engine"
                        and isinstance(payload, dict) and payload.get("method") == "handoff.submit"):
                    from .build_pipeline import BuildAssets
                    assets = BuildAssets(args.root)
                host = Coordinator(args.ledger, FeedbackPolicy.from_dict(read_json(args.feedback_policy)), role=args.role,
                                   source=args.source, assets=assets, create=args.create)
                output = host.dispatch(payload)
                print(canonical_json(output))
                return 0 if output["ok"] else 2
            case "agent-serve" | "agent-call":
                from .agent_bridge import AgentBridge, serve_bridge
                backend = None
                if args.local_cpu_control:
                    if args.role != "trainer":
                        raise ContractError("local CPU control host must use the trainer role")
                    from .local_training import LocalCpuBackend
                    backend = LocalCpuBackend(args.state_root, args.root)
                bridge = AgentBridge(Path(__file__).resolve().parents[2], args.state_root, args.root,
                    role=args.role, seat=args.seat, profile=read_json(args.profile) if args.profile is not None else None,
                    seed=args.seed, decision_timeout=args.decision_timeout, opponent_id=args.opponent_id,
                    own_deck_id=args.own_deck_id, controller_source=args.controller_source, provider=args.provider, model=args.model,
                    training_backend=backend)
                if args.command == "agent-serve":
                    return serve_bridge(bridge, sys.stdin, sys.stdout)
                try:
                    output = bridge.dispatch(read_json(args.input))
                finally:
                    bridge.close()
                print(canonical_json(output))
                return 0 if output["ok"] else 2
            case "native-effect-duel" | "native-effect-duel-replay":
                from .effect_duel import run_effect_duel
                if args.command == "native-effect-duel":
                    if args.trace is not None and args.trace.exists():
                        raise ContractError("trace already exists; choose a new path")
                    output, trace = run_effect_duel(args.root, read_json(args.profile), seed=args.seed, option_preference=args.option_preference)
                    if args.trace is not None:
                        args.trace.parent.mkdir(parents=True, exist_ok=True)
                        with args.trace.open("x", encoding="utf-8") as handle:
                            handle.write(canonical_json(trace) + "\n")
                else:
                    output, _ = run_effect_duel(args.root, {}, replay=read_json(args.input))
            case "native-duel" | "native-replay" | "native-effects" | "native-effect-replay" | "native-search" | "native-search-replay":
                from .normal_duel import run_normal_duel
                from .effect_cases import run_effect_case
                from .search_cases import run_search_case
                if args.command in ("native-duel", "native-effects", "native-search"):
                    if args.trace is not None and args.trace.exists():
                        raise ContractError("trace already exists; choose a new path")
                    runner = {"native-duel": run_normal_duel, "native-effects": run_effect_case, "native-search": run_search_case}[args.command]
                    kwargs = {"seed": args.seed}
                    if args.command != "native-duel":
                        kwargs["route"] = args.route
                    output, trace = runner(args.root, **kwargs)
                    if args.trace is not None:
                        args.trace.parent.mkdir(parents=True, exist_ok=True)
                        with args.trace.open("x", encoding="utf-8") as handle:
                            handle.write(canonical_json(trace) + "\n")
                else:
                    runner = {"native-replay": run_normal_duel, "native-effect-replay": run_effect_case, "native-search-replay": run_search_case}[args.command]
                    output, _ = runner(args.root, replay=read_json(args.input))
        print(canonical_json(output))
        return 0
    except EngineUnavailable as error:
        code = ("CPU_TRAINING_UNAVAILABLE" if args.command in ("duel-train-cpu", "build-train-cpu", "model-group-cpu", "lora-group-cpu") else
                "NATIVE_RESOURCES_UNAVAILABLE" if args.command == "build-check" else
                "NATIVE_RESOURCES_UNAVAILABLE" if args.command.startswith("native-") else "ENGINE_NOT_IMPLEMENTED")
        message = str(error)
    except NativeError as error:
        code = "NATIVE_ENGINE_ERROR"
        message = str(error)
    except (ContractError, json.JSONDecodeError, tomllib.TOMLDecodeError, UnicodeError) as error:
        code = "INVALID_INPUT"
        # JSON/TOML parser messages may include input fragments; do not expose them.
        message = str(error) if isinstance(error, ContractError) else "malformed input document"
    except (OSError, sqlite3.Error):
        code = "STORAGE_ERROR"
        message = "file/database unavailable; verify path, permissions and schema"
    print(canonical_json({"ok": False, "error": {"code": code, "message": message}}), file=sys.stderr)
    return 2
