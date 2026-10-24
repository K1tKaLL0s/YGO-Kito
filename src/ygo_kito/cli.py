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
    logic_plan = sub.add_parser("construction-plan", help="non-LLM intent and construction-logic check; no engine or training")
    logic_plan.add_argument("--request", required=True)
    logic_plan.add_argument("--logic", type=Path)
    logic_plan.add_argument("--lexicon", type=Path)
    logic_plan.add_argument("--intent-model", type=Path)
    intent_train = sub.add_parser("construction-intent-fit", help="explicit small CPU synthetic classifier fit; no generalization claim")
    intent_train.add_argument("--input", type=Path, required=True)
    intent_train.add_argument("--output", type=Path, required=True)
    intent_train.add_argument("--lexicon", type=Path)
    intent_train.add_argument("--feature-config", type=Path)
    intent_train.add_argument("--epochs", type=int, default=120)
    intent_train.add_argument("--learning-rate", type=float, default=1.)
    logic_fill = sub.add_parser("construction-fill-check", help="source-bound text/list checks; existing goal verification is explicit")
    logic_fill.add_argument("--request", required=True)
    logic_fill.add_argument("--task", type=Path, required=True)
    logic_fill.add_argument("--logic", type=Path, required=True)
    logic_fill.add_argument("--proposal", type=Path, required=True)
    logic_fill.add_argument("--reviews", type=Path)
    logic_fill.add_argument("--scopes", type=Path)
    logic_fill.add_argument("--lexicon", type=Path)
    logic_fill.add_argument("--intent-model", type=Path)
    logic_fill.add_argument("--root", type=Path, default=Path(".cache"))
    logic_fill.add_argument("--verify-existing-goal", action="store_true", help="invoke the existing supported goal interface; does not verify arbitrary graph edges")
    logic_run = sub.add_parser("construction-run", help="actual existing role-model graph selection, catalog binding and coordinator connection")
    for name in ("task", "intent-model", "required-tags", "binding-data"):
        logic_run.add_argument("--"+name,type=Path,required=True)
    logic_run.add_argument("--request",required=True)
    logic_run.add_argument("--scopes",type=Path)
    logic_run.add_argument("--logic-checkpoint",type=Path)
    logic_run.add_argument("--base",type=Path,help="existing legal list; permits bounded semantic edits without optional MILP")
    logic_run.add_argument("--root",type=Path,default=Path(".cache"))
    logic_run.add_argument("--state-root",type=Path,default=Path(".cache/construction"))
    logic_run.add_argument("--candidate-id")
    logic_run.add_argument("--parent-candidate-id")
    logic_run.add_argument("--verify-existing-goal",action="store_true")
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
    effect_duel.add_argument("--route-task", type=Path, help="explicit conditional extra-goal engineering route, never a trained policy")
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
    catalog = sub.add_parser("catalog-recall", help="public effect/theme/context cross recall; no rule/strength claim")
    catalog.add_argument("--root", type=Path, default=Path(".cache"))
    catalog.add_argument("--task", type=Path, required=True)
    catalog.add_argument("--query", type=Path, required=True)
    discovery = sub.add_parser("goal-discover", help="bounded real-core exploration of a v3 goal without prewritten route")
    discovery.add_argument("--root", type=Path, default=Path(".cache"))
    discovery.add_argument("--task", type=Path, required=True)
    discovery.add_argument("--deck", type=Path, required=True)
    discovery.add_argument("--seconds", type=float, default=10.)
    discovery.add_argument("--attempts", type=int, default=16)
    acceptance = sub.add_parser("discovery-curriculum-acceptance", help="real MSG26/search and two CPU curriculum runs including recovery; no paid launch")
    acceptance.add_argument("--root", type=Path, default=Path(".cache"))
    acceptance.add_argument("--state-root", type=Path, default=Path(".cache/discovery"))
    acceptance.add_argument("--run-id", required=True)
    protocol = sub.add_parser("protocol-history-acceptance", help="bounded real MSG23/remaining prompts and legal public history/replays; CPU only")
    protocol.add_argument("--root", type=Path, default=Path(".cache"))
    protocol.add_argument("--output", type=Path, required=True)
    private = sub.add_parser("private-hierarchy-acceptance", help="real v4 hidden/mixed choices, full-action CPU update and checkpoint proof; nonpaid")
    private.add_argument("--root", type=Path, default=Path(".cache"))
    private.add_argument("--output", type=Path, required=True)
    knowledge=sub.add_parser("private-knowledge-acceptance",help="real v5 private deck/confirmation and facedown host proof; exports only common-public histories")
    knowledge.add_argument("--root",type=Path,default=Path(".cache"))
    knowledge.add_argument("--output",type=Path,required=True)
    foundation=sub.add_parser("foundation-acceptance",help="bounded semantic builds, indexed real-core PPO and executable frozen opponents; public-only export")
    foundation.add_argument("--root",type=Path,default=Path(".cache"))
    foundation.add_argument("--output",type=Path,required=True)
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
    accept = sub.add_parser("engineering-acceptance", help="bounded whole CPU chain, real managed training and explicit owned-worker faults; not formal readiness")
    accept.add_argument("--root", type=Path, default=Path(".cache"))
    accept.add_argument("--state-root", type=Path, default=Path(".cache/acceptance"))
    accept.add_argument("--run-id", required=True)
    runner = sub.add_parser("cpu-runner-acceptance", help="short multiround CPU/validation/recovery proof with an owned-worker fault; no paid training")
    runner.add_argument("--root", type=Path, default=Path(".cache"))
    runner.add_argument("--state-root", type=Path, default=Path(".cache/runner"))
    runner.add_argument("--run-id", required=True)
    runner.add_argument("--recipe", type=Path, default=Path("configs/cpu-runner-v1.json"))
    group_runner = sub.add_parser("group-runner-acceptance", help="two-cycle four-model CPU/LoRA alternation, frozen eval and owned-worker fault; no paid training")
    group_runner.add_argument("--root", type=Path, default=Path(".cache"))
    group_runner.add_argument("--state-root", type=Path, default=Path(".cache/group-runner"))
    group_runner.add_argument("--run-id", required=True)
    group_runner.add_argument("--recipe", type=Path, default=Path("configs/group-runner-v1.json"))
    extra_accept = sub.add_parser("extra-feedback-acceptance", help="real extra goals/complete duels/paired construction updates and recovery; CPU engineering only")
    extra_accept.add_argument("--root", type=Path, default=Path(".cache"))
    extra_accept.add_argument("--state-root", type=Path, default=Path(".cache/extra-feedback"))
    extra_accept.add_argument("--run-id", required=True)
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
        agent.add_argument("--local-training-config", type=Path, help="trusted host CPU round recipe; requires trainer role and explicit local control")
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config(args.config)
        match args.command:
            case "construction-intent-fit":
                from .build_intent import DEFAULT_LEXICON, DomainLexicon
                from .intent_model import IntentFeatureConfig, LinearIntentClassifier
                lexicon = DEFAULT_LEXICON.extended(*DomainLexicon.from_dict(read_json(args.lexicon)).terms) if args.lexicon else None
                feature_config = IntentFeatureConfig.from_dict(read_json(args.feature_config)) if args.feature_config else None
                model = LinearIntentClassifier(lexicon,feature_config)
                output = model.fit(read_json(args.input),epochs=args.epochs,learning_rate=args.learning_rate)
                model.save(args.output)
                output.update(model_sha256=model.sha256,checkpoint=str(args.output),generalization_verified=False)
            case "construction-plan":
                from .build_intent import DEFAULT_LEXICON, DomainLexicon, classify_build_intent
                from .intent_model import LinearIntentClassifier
                from .construction_logic import ConstructionLogic, stage_route
                lexicon = DEFAULT_LEXICON.extended(*DomainLexicon.from_dict(read_json(args.lexicon)).terms) if args.lexicon else None
                classifier = LinearIntentClassifier.load(args.intent_model,lexicon=lexicon) if args.intent_model else LinearIntentClassifier(lexicon)
                intent = classify_build_intent(args.request, lexicon, classifier=classifier)
                output = {"classification": intent.to_dict(), "route": stage_route(intent),
                          "training_status": intent.classifier_status, "graph_execution_verified": False}
                if args.logic:
                    graph = ConstructionLogic.from_dict(read_json(args.logic))
                    output.update(logic=graph.to_dict(), logic_sha256=graph.sha256, graph_structure_valid=True)
            case "construction-fill-check":
                from .build_intent import DEFAULT_LEXICON, DomainLexicon
                from .intent_model import LinearIntentClassifier
                from .build_contracts import BuildTask, DeckParts
                from .build_pipeline import BuildAssets
                from .construction_logic import ConstructionLogic, ConstructionSession, ThemeScope
                from .construction_fill import FillProposal, NodeTextReview, evaluate_fill, existing_goal_verifier
                from .validation import array
                lexicon = DEFAULT_LEXICON.extended(*DomainLexicon.from_dict(read_json(args.lexicon)).terms) if args.lexicon else None
                classifier = LinearIntentClassifier.load(args.intent_model,lexicon=lexicon) if args.intent_model else LinearIntentClassifier(lexicon)
                session = ConstructionSession(args.request, BuildTask.from_dict(read_json(args.task)),lexicon=lexicon,classifier=classifier)
                session.submit_logic(ConstructionLogic.from_dict(read_json(args.logic)), role="user", reason="explicit CLI logic input")
                reviews = [NodeTextReview.from_dict(r) for r in array(read_json(args.reviews), "text reviews")] if args.reviews else []
                if len({r.node_id for r in reviews}) != len(reviews):
                    raise ContractError("duplicate supplied node text reviews")
                indexed = {r.node_id: r for r in reviews}
                def reviewer(node, cards):
                    return indexed.get(node.node_id, NodeTextReview(node.node_id, "unknown", (), (),
                        "CLI-supplied-review", "no supplied concrete text assessment for this node"))
                scopes = tuple(ThemeScope.from_dict(s) for s in array(read_json(args.scopes), "theme scopes")) if args.scopes else ()
                output = evaluate_fill(session, BuildAssets(args.root), FillProposal.from_dict(read_json(args.proposal)),
                    scopes=scopes, text_reviewer=reviewer if reviews else None,
                    verifier=existing_goal_verifier if args.verify_existing_goal else None)
                output["classification"] = session.classification.to_dict()
            case "construction-run":
                from .build_contracts import BuildTask, DeckParts
                from .build_pipeline import BuildAssets
                from .build_training import BuildTrainer, BuildTrainingConfig
                from .construction_logic import ConstructionSession, LogicTag, ThemeScope
                from .construction_model import LogicCodec, LogicModelAdapter
                from .construction_binding import CatalogBindingAdapter
                from .construction_controller import ConstructionController
                from .construction_fill import existing_goal_verifier
                from .coordinator import Coordinator
                from .coordinator_model import CoordinatorTrainer
                from .coord_contracts import FeedbackPolicy
                from .intent_model import LinearIntentClassifier
                from .validation import array
                if args.verify_existing_goal and not args.candidate_id:
                    raise ContractError("explicit candidate ID is required before verified coordinator handoff")
                task=BuildTask.from_dict(read_json(args.task));assets=BuildAssets(args.root)
                builder=BuildTrainer(task,assets,BuildTrainingConfig())
                codec=LogicCodec(tuple(LogicTag.from_dict(t) for t in array(read_json(args.required_tags),"requested logic tags")))
                graph_adapter=LogicModelAdapter.from_builder(builder,codec)
                if args.logic_checkpoint:graph_adapter.load(args.logic_checkpoint)
                binding_adapter=CatalogBindingAdapter.from_dict(assets,read_json(args.binding_data))
                session=ConstructionSession(args.request,task,classifier=LinearIntentClassifier.load(args.intent_model))
                host=Coordinator(args.state_root / "coordinator.sqlite3",FeedbackPolicy(),role="coordinator",
                    source="real_engine",assets=assets,create=True) if args.verify_existing_goal else None
                controller=ConstructionController(graph_adapter,binding_adapter,CoordinatorTrainer(),host=host)
                scopes=tuple(ThemeScope.from_dict(s) for s in array(read_json(args.scopes),"scopes")) if args.scopes else ()
                output=controller.run(session,scopes=scopes,base=DeckParts.from_dict(read_json(args.base)) if args.base else None,candidate_id=args.candidate_id,
                    parent_candidate_id=args.parent_candidate_id,verifier=existing_goal_verifier if args.verify_existing_goal else None)
                output["classification"]=session.classification.to_dict()
            case "catalog-recall":
                from .build_contracts import BuildTask
                from .build_pipeline import BuildAssets
                from .catalog_search import CatalogQuery, recall
                output = {"hits": recall(BuildTask.from_dict(read_json(args.task)), BuildAssets(args.root), CatalogQuery.from_dict(read_json(args.query))),
                          "route_verified": False}
            case "goal-discover":
                from .build_contracts import BuildTask, DeckParts
                from .build_pipeline import BuildAssets
                from .route_search import discover_goal
                output = discover_goal(BuildTask.from_dict(read_json(args.task)), DeckParts.from_dict(read_json(args.deck)), BuildAssets(args.root),
                                       seconds=args.seconds, attempts=args.attempts)
            case "discovery-curriculum-acceptance":
                import signal
                from .discovery_acceptance import run_discovery_acceptance
                if not hasattr(signal, "setitimer"):
                    raise EngineUnavailable("discovery acceptance requires this cloud's Unix process timer")
                old_handler = signal.signal(signal.SIGALRM, signal.SIG_DFL)
                signal.setitimer(signal.ITIMER_REAL, 600.)
                try:
                    output = run_discovery_acceptance(args.root, args.state_root, args.run_id)
                    output["acceptance_cli_wall_limit_seconds"] = 600
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    signal.signal(signal.SIGALRM, old_handler)
            case "protocol-history-acceptance":
                import signal
                from .protocol_acceptance import run_protocol_acceptance
                if not hasattr(signal,"setitimer"):
                    raise EngineUnavailable("protocol acceptance requires this cloud's Unix process timer")
                old_handler=signal.signal(signal.SIGALRM,signal.SIG_DFL)
                signal.setitimer(signal.ITIMER_REAL,120.)
                try:
                    output=run_protocol_acceptance(args.root,args.output)
                finally:
                    signal.setitimer(signal.ITIMER_REAL,0)
                    signal.signal(signal.SIGALRM,old_handler)
            case "private-hierarchy-acceptance":
                import signal
                from .private_acceptance import run_private_acceptance
                if not hasattr(signal,"setitimer"):
                    raise EngineUnavailable("private acceptance requires this cloud's Unix process timer")
                old_handler=signal.signal(signal.SIGALRM,signal.SIG_DFL)
                signal.setitimer(signal.ITIMER_REAL,120.)
                try:
                    output=run_private_acceptance(args.root,args.output)
                finally:
                    signal.setitimer(signal.ITIMER_REAL,0)
                    signal.signal(signal.SIGALRM,old_handler)
            case "private-knowledge-acceptance":
                import signal
                from .knowledge_acceptance import run_knowledge_acceptance
                if not hasattr(signal,"setitimer"):
                    raise EngineUnavailable("private knowledge acceptance requires this cloud's Unix process timer")
                old_handler=signal.signal(signal.SIGALRM,signal.SIG_DFL)
                signal.setitimer(signal.ITIMER_REAL,120.)
                try:
                    output=run_knowledge_acceptance(args.root,args.output)
                finally:
                    signal.setitimer(signal.ITIMER_REAL,0)
                    signal.signal(signal.SIGALRM,old_handler)
            case "foundation-acceptance":
                import signal
                from .foundation_acceptance import run_foundation_acceptance
                if not hasattr(signal,"setitimer"):
                    raise EngineUnavailable("foundation acceptance requires this cloud's Unix process timer")
                old_handler=signal.signal(signal.SIGALRM,signal.SIG_DFL)
                signal.setitimer(signal.ITIMER_REAL,180.)
                try:
                    output=run_foundation_acceptance(args.root,args.output)
                finally:
                    signal.setitimer(signal.ITIMER_REAL,0)
                    signal.signal(signal.SIGALRM,old_handler)
            case "cpu-runner-acceptance":
                from .runner_acceptance import run_runner_acceptance
                output = run_runner_acceptance(args.root, args.state_root, args.run_id, read_json(args.recipe))
            case "group-runner-acceptance":
                from .group_runner_acceptance import run_group_acceptance
                output = run_group_acceptance(args.root, args.state_root, args.run_id, read_json(args.recipe))
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
            case "extra-feedback-acceptance":
                import signal
                from .extra_acceptance import run_extra_feedback_acceptance
                if not hasattr(signal, "setitimer"):
                    raise EngineUnavailable("extra feedback acceptance requires this cloud's Unix process timer")
                old_handler = signal.signal(signal.SIGALRM, signal.SIG_DFL)
                signal.setitimer(signal.ITIMER_REAL, 180.)
                try:
                    output = run_extra_feedback_acceptance(args.root, args.state_root, args.run_id)
                    output["acceptance_cli_wall_limit_seconds"] = 180
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    signal.signal(signal.SIGALRM, old_handler)
            case "engineering-acceptance":
                import signal
                from .engineering_acceptance import run_engineering_acceptance
                if not hasattr(signal, "setitimer"):
                    raise EngineUnavailable("engineering acceptance requires this cloud's Unix process timer")
                old_handler = signal.signal(signal.SIGALRM, signal.SIG_DFL)
                signal.setitimer(signal.ITIMER_REAL, 180.)
                try:
                    output = run_engineering_acceptance(args.root, args.state_root, args.run_id)
                    output["acceptance_cli_wall_limit_seconds"] = 180
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    signal.signal(signal.SIGALRM, old_handler)
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
                if args.local_training_config is not None and not args.local_cpu_control:
                    raise ContractError("local training configuration requires explicit local CPU control")
                if args.local_cpu_control:
                    if args.role != "trainer":
                        raise ContractError("local CPU control host must use the trainer role")
                    from .local_training import LocalCpuBackend
                    backend = LocalCpuBackend(args.state_root, args.root,
                        recipe=read_json(args.local_training_config) if args.local_training_config is not None else None)
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
                    output, trace = run_effect_duel(args.root, read_json(args.profile), seed=args.seed, option_preference=args.option_preference,
                                                    route_task=read_json(args.route_task) if args.route_task else None)
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
        code = ("CPU_TRAINING_UNAVAILABLE" if args.command in ("duel-train-cpu", "build-train-cpu", "model-group-cpu", "lora-group-cpu", "cpu-runner-acceptance", "group-runner-acceptance") else
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
