"""Explicit inference-only headless model-vs-model functional matches.

Preflight reads pinned local resources and snapshots, with no native instance
or DataIndex creation. Only run() opens the normal core. Its small games are
not a timing pilot, formal evaluation, training, or common-deck qualification.
"""
from copy import deepcopy
from dataclasses import asdict
import json
import math
import os
from pathlib import Path

import torch

from .agent_registry import identifier
from .build_contracts import DeckParts, digest
from .build_pipeline import BuildAssets
from .course_game_adapter import CourseGameAdapter, CourseTrainingConfig
from .cpu_training import CpuTrainer
from .data_isolation import DataIndex, episode_projection
from .deck_profile import validate_deck_parts, validate_profile
from .duel_model import DuelModelConfig, parameter_digest
from .implementation_identity import assert_source_tree, source_tree_snapshot
from .match_runner import (FirstOrderPolicy, MatchParticipant, MatchRules, MatchRunner, MatchState,
    PUBLIC_GAME_FIELDS, keep_side)
from .model_opponents import FrozenDuelSnapshot, ModelOpponentRuntime
from .training_pilot import _bytes, _inside, _reference
from .validation import ContractError, fields, integer, member, parse_json, text

KIND = "model-match-functional-v1"
PARTICIPANTS = ("model-a", "model-b")


def validate_spec(value):
    d = fields(value, {"schema_version", "kind", "run_id", "native_root", "profile", "snapshot_a", "snapshot_b",
        "migration_a", "migration_b", "format", "seed_pairs", "episode_seconds", "native_decision_limit",
        "first_participant_id", "first_order", "sideboard_policy", "state_root"},
        {"opponent_policy_mode", "opponent_policy_seeds"})
    integer(d["schema_version"], "model match schema", 1, 1)
    member(d["kind"], "model match kind", (KIND,)); identifier(d["run_id"])
    for key in ("native_root", "state_root"): text(d[key], "explicit " + key)
    for key in ("profile", "snapshot_a", "snapshot_b"): _reference(d[key])
    for key in ("migration_a", "migration_b"):
        member(d[key], "explicit inference migration", ("same-period-inference", "explicit-inference-migration"))
    member(d["format"], "functional match format", ("bo1", "bo3"))
    expected = 1 if d["format"] == "bo1" else 3
    if not isinstance(d["seed_pairs"], list) or len(d["seed_pairs"]) != expected:
        raise ContractError("BO1 requires one private seed pair; BO3 requires three")
    seeds = set()
    for pair in d["seed_pairs"]:
        if not isinstance(pair, list) or len(pair) != 2: raise ContractError("private seed/policy pair required")
        for seed in pair: integer(seed, "private functional seed", 0, 2**32-8)
        if pair[0] in seeds: raise ContractError("functional physical seeds must be unique")
        seeds.add(pair[0])
    seconds = d["episode_seconds"]
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 300:
        raise ContractError("functional episode cap must be within (0,300] seconds")
    integer(d["native_decision_limit"], "functional native decision limit", 1, 3000)
    member(d["first_participant_id"], "initial first participant", PARTICIPANTS)
    fields(d["first_order"], set(PARTICIPANTS))
    for policy in d["first_order"].values(): FirstOrderPolicy(policy)
    member(d["sideboard_policy"], "functional sideboarding", ("keep_side_baseline",))
    result = deepcopy(d)
    result.setdefault("opponent_policy_mode", "greedy")
    member(result["opponent_policy_mode"], "opponent neural policy mode", ("greedy", "sample"))
    if result["opponent_policy_mode"] == "sample":
        policy_seeds = result.get("opponent_policy_seeds")
        if not isinstance(policy_seeds, list) or len(policy_seeds) != expected:
            raise ContractError("sampled opponent requires one/three explicit private policy seeds")
        for seed in policy_seeds: integer(seed, "private opponent policy seed", 0, 2**32-8)
        if len(set(policy_seeds)) != expected: raise ContractError("private opponent policy seeds must be unique")
    elif "opponent_policy_seeds" in result:
        raise ContractError("greedy opponent does not consume private policy seeds")
    return result


def _opponent_rng(spec, game_number):
    if spec["opponent_policy_mode"] == "greedy": return None
    return torch.Generator(device="cpu").manual_seed(spec["opponent_policy_seeds"][game_number-1])


def _state_root(workspace, value):
    path = (workspace / value).resolve()
    cache = (workspace / ".cache").resolve()
    if not cache.is_relative_to(workspace) or not path.is_relative_to(cache) or path == cache:
        raise ContractError("functional private state requires a dedicated workspace .cache directory")
    if path.exists(): raise ContractError("functional state already exists; no overwrite or implicit replay")
    return path


def _write(path, value):
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
        output.write("\n"); output.flush(); os.fsync(output.fileno())


def _parts(profile, seat):
    return DeckParts(tuple(profile["decks"][seat]), tuple(profile.get("extras", [[], []])[seat]),
        tuple(profile.get("sides", [[], []])[seat]))


def _prepare(workspace, value):
    workspace = Path(workspace).resolve(strict=True); d = validate_spec(value)
    root = _state_root(workspace, d["state_root"])
    assets = BuildAssets(_inside(workspace, d["native_root"], directory=True))
    _, raw = _bytes(workspace, d["profile"])
    profile = parse_json(raw.decode("utf-8")); validate_profile(profile)
    if profile.get("schema_version") != 2 or profile.get("adapter_revision") != 5:
        raise ContractError("functional match requires schema2 revision5 legal player DTOs")
    for seat in (0, 1): validate_deck_parts(_parts(profile, seat).to_dict(), assets.rows, assets.limits)
    snapshots, runtimes, policies = {}, {}, []
    for letter, seat in (("a", 0), ("b", 1)):
        snapshots[letter] = FrozenDuelSnapshot.load(workspace, **d["snapshot_"+letter])
        runtime = ModelOpponentRuntime(snapshots[letter], "functional-model-"+letter,
            source="engineering_fixture", migration=d["migration_"+letter],
            policy_mode=d["opponent_policy_mode"] if letter == "b" else "greedy")
        runtime.assert_assets(assets)
        # This binds/validates both decks and creates only a frozen CPU network.
        # It neither constructs a native engine nor opens the private data index.
        opponent = runtime.bind(assets, profile, seat, policy_rng=_opponent_rng(d, 1) if letter == "b" else None)
        opponent.assert_runtime(assets.root, profile, 1-seat)
        policies.append(opponent.policy.model)
        runtimes[letter] = runtime
    if (policies[0] is policies[1] or {p.data_ptr() for p in policies[0].parameters()} &
            {p.data_ptr() for p in policies[1].parameters()}):
        raise ContractError("functional model pair must have independent actual network storage")
    return workspace, d, root, assets, profile, snapshots, runtimes


def _public(d, assets, snapshots):
    a, b = (snapshots[k].identity() for k in ("a", "b"))
    return {"schema_version": 1, "kind": KIND, "run_id": d["run_id"], "status": "ready", "format": d["format"],
        "scope": "CPU snapshot pair and pinned legal profile functional execution only",
        "snapshot_a": a, "snapshot_b": b, "snapshot_identities_equal": a == b,
        "weights_identical": a["model_sha256"] == b["model_sha256"],
        "independent_network_objects": True, "profile_sha256": d["profile"]["sha256"],
        "resources": deepcopy(assets.receipt), "sideboard_policy": d["sideboard_policy"],
        "first_order": deepcopy(d["first_order"]), "scheduled_small_games": len(d["seed_pairs"]),
        "opponent_policy_mode": d["opponent_policy_mode"],
        "native_executed": False, "csharp_execution_attempted": False, "training_updates": 0,
        "execution_updates": {"actor_base": 0, "actor_adapter": 0, "opponent": 0},
        "formal_matches": 0, "formal_games": 0, "timing_pilot": False, "general_speed_verified": False,
        "formal_common_deck_evaluation": False, "strength_qualified": False,
        "completed_functional_matches": 0, "completed_games": 0, "games": [],
        "implementation": source_tree_snapshot(Path(__file__).resolve().parent)}


def preflight(workspace, spec):
    """No native start, DataIndex creation, state directory or weight update."""
    _, d, _, assets, _, snapshots, _ = _prepare(workspace, spec)
    return _public(d, assets, snapshots)


def run(workspace, spec, *, progress=None):
    """One explicit frozen functional match; no automatic retry or training."""
    workspace, d, root, assets, profile, snapshots, runtimes = _prepare(workspace, spec)
    report = _public(d, assets, snapshots); report["status"] = "running"
    assert_source_tree(Path(__file__).resolve().parent, report["implementation"])
    root.mkdir(parents=True, exist_ok=False)
    _write(root / "private-spec.json", d)
    if progress is not None: progress(deepcopy(report))
    state = adapter = trainer = None; before = None
    try:
        saved = snapshots["a"].to_state()
        # This new inference shell deliberately restores no training optimizer,
        # seeds, cursor or source RNG. Every parameter is replaced by the exact
        # already materialized source snapshot before any policy inference.
        reserved = {p[0] for p in d["seed_pairs"]}
        unused = next(i for i in range(4) if i not in reserved)
        config = CourseTrainingConfig(model=DuelModelConfig(**saved["model_config"]), model_seed=0,
            game_seeds=(unused,), episode_seconds=d["episode_seconds"], native_decision_limit=d["native_decision_limit"])
        trainer = CpuTrainer(config, saved["card_ids"])
        trainer.model.load_state_dict(saved["model"], strict=True)
        trainer.model.eval(); trainer.model.requires_grad_(False)
        if parameter_digest(trainer.model) != saved["model_sha256"]: raise ContractError("actor inference shell weights differ")
        participants = tuple(MatchParticipant(pid, _parts(profile, seat)) for seat, pid in enumerate(PARTICIPANTS))
        rules = MatchRules(assets.rows, assets.limits, set(saved["card_ids"]))
        binding = {"kind": KIND, "spec_sha256": digest(d), "snapshot_a": snapshots["a"].identity(),
            "model_opponent": runtimes["b"].identity(), "implementation": report["implementation"]}
        state = MatchState(d["run_id"], participants, rules, binding, d["first_participant_id"], adapter_revision=5)
        index = DataIndex(root / "data-index")
        def new_adapter(cursor):
            return CourseGameAdapter(assets=assets, match_state=state, actor_participant_id="model-a", trainer=trainer,
                model_runtime=runtimes["b"], data_index=index, experiment_id=d["run_id"], purpose="validation",
                evaluation_pairs=tuple(tuple(p) for p in d["seed_pairs"]), evaluation_cursor=cursor,
                opponent_policy_rng=_opponent_rng(d, cursor+1))
        adapter = new_adapter(0)
        before = adapter.training_fingerprint()
        def game(current):
            nonlocal adapter
            if current.game_number > 1 and d["opponent_policy_mode"] == "sample":
                adapter = new_adapter(current.game_number-1)
            # Recheck the original pinned artifacts before every actual game.
            for key in ("profile", "snapshot_a", "snapshot_b"): _bytes(workspace, d[key])
            assert_source_tree(Path(__file__).resolve().parent, report["implementation"])
            _write(root / ("game-"+str(current.game_number)+"-started.json"),
                {"kind": KIND, "match_id": current.match_id, "game_number": current.game_number,
                 "status": "execution_started_no_automatic_replay", "spec_sha256": current.sha256})
            result = adapter(current)
            receipt = deepcopy(adapter.last_receipt)
            report["native_executed"] |= receipt.get("observations", {}).get("constructor_started") is True
            _write(root / ("game-"+str(current.game_number)+"-host.json"), receipt)
            if adapter.last_partial_diagnostics is not None:
                _write(root / ("game-"+str(current.game_number)+"-partial.json"), adapter.last_partial_diagnostics)
            if adapter.last_episode is not None:
                episode = adapter.last_episode
                _write(root / ("game-"+str(current.game_number)+"-private.json"),
                    {"episode": episode_projection(episode), "private_audit": episode.get("_private_audit")})
            return result
        if d["format"] == "bo1":
            current = state.issue_game_spec(); state.record_game(current, game(current))
        else:
            runner = MatchRunner(state, game, {p: keep_side for p in PARTICIPANTS},
                {p: FirstOrderPolicy(d["first_order"][p]) for p in PARTICIPANTS})
            runner.run()
        summary = state.summary()
        report["games"] = [{k: row[k] for k in PUBLIC_GAME_FIELDS} for row in summary["games"]]
        report["completed_games"] = summary["complete_games"]
        complete = (summary["complete_games"] == 1 and summary["game_attempts"] == 1) if d["format"] == "bo1" else state.status == "complete"
        report.update(status="completed" if complete else "failed_or_uncertain", match_state=state.status,
            completed_functional_matches=int(complete), draw_policy=summary["draw_policy"],
            winner_participant_id=summary["games"][0]["winner_participant_id"] if d["format"] == "bo1" else summary["match_winner"],
            actual_first_game_counts={p: sum(g["actual_first_participant_id"] == p for g in summary["games"] if g["completed"]) for p in PARTICIPANTS})
        _write(root / "match-private.json", state.to_dict())
    except (ContractError, OSError, ValueError, KeyError, TypeError, RuntimeError, KeyboardInterrupt) as error:
        report.update(status="failed_or_uncertain", error_type=type(error).__name__, error=str(error), automatic_retry=False)
    finally:
        if adapter is not None and before is not None:
            report["native_executed"] |= (adapter.last_receipt or {}).get("observations", {}).get("constructor_started") is True
            unchanged = adapter.training_fingerprint() == before
            report["actor_training_state_unchanged"] = unchanged
            if not unchanged: report.update(status="failed_or_uncertain", error_type="FrozenStateChanged")
        if trainer is not None:
            report["execution_updates"]["actor_base"] = trainer.updates
            report["training_updates"] = trainer.updates
            report["actor_shell"] = {"kind": "fresh-frozen-inference-shell", "model_sha256": parameter_digest(trainer.model),
                "updates": trainer.updates, "episode_cursor": trainer.episode_cursor, "source_training_state_restored": False}
            if trainer.updates or trainer.episode_cursor: report.update(status="failed_or_uncertain", error_type="UnexpectedTrainingUpdate")
        for letter, snapshot in snapshots.items():
            snapshot.assert_integrity()
        _write(root / "public-result.json", report)
    if progress is not None: progress(deepcopy(report))
    return report
