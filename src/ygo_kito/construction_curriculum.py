"""Explicit frozen real-comparison source for the four-role CPU runner.

Supervised reuse is distinct from on-policy PPO. Validation artifacts are never
training labels. Small visible-rule opponents remain engineering-only evidence.
"""
from .build_contracts import DeckParts, digest
from .build_feedback import DRIVER, compare_candidates, real_game_dataset, validate_comparison
from .validation import ContractError, array, fields, integer, read_json

FIELD = "construction_curriculum"


def inputs(recipe, task):
    from .group_runner import config_path
    if FIELD not in recipe:
        return None
    config = read_json(config_path(recipe[FIELD]))
    from .semantic_curriculum import COURSE,inputs as semantic_inputs
    if config.get('source')==COURSE:return semantic_inputs(recipe,task)
    fields(config, {"schema_version", "source", "train", "validation", "comparison_seconds"})
    integer(config["schema_version"], "construction schema", 1, 1)
    if config["source"] != "explicit-frozen-real-comparison-engineering-v1":
        raise ContractError("unsupported construction curriculum source")
    seconds = config["comparison_seconds"]
    if type(seconds) not in (int, float) or not 0 < seconds <= 120:
        raise ContractError("construction comparison budget outside CPU range")
    result = {"config": config}
    for partition in ("train", "validation"):
        source = read_json(config_path(config[partition]))
        fields(source, {"schema_version", "source", "task_file", "candidates", "opponent", "paired_seeds", "actor_seats", "driver", "purpose", "independent_ability_evaluation"})
        integer(source["schema_version"], "construction source schema", 1, 1)
        if (source["source"] != "engineering_fixture_not_user_decks"
                or source["task_file"] != recipe["task"] or source["driver"] != DRIVER or source["actor_seats"] != [0, 1]
                or source["purpose"] != "construction_" + partition or source["independent_ability_evaluation"] is not False
                or read_json(config_path(source["task_file"])) != task.to_dict()):
            raise ContractError("construction source task/partition/driver differs")
        candidates = [DeckParts.from_dict(d) for d in array(source["candidates"], "curriculum candidates")]
        if len(candidates) != 2 or candidates[0] == candidates[1]:
            raise ContractError("curriculum requires two distinct candidates")
        seeds = array(source["paired_seeds"], "construction seeds")
        if not 2 <= len(seeds) <= 8 or len(set(seeds)) != len(seeds):
            raise ContractError("distinct paired construction seeds required")
        for seed in seeds:
            integer(seed, "construction seed", 0, 2**32 - 8)
        DeckParts.from_dict(source["opponent"])
        result[partition] = source
    duel_seeds = {recipe["bootstrap_seed"], *recipe["validation"]["seeds"],
                  *(recipe["train"]["seed_start"] + i * recipe["train"]["seed_stride"] for i in range(recipe["max_updates"]))}
    train_seeds, validation_seeds = (set(result[p]["paired_seeds"]) for p in ("train", "validation"))
    def unordered(deck):
        return {k: sorted(v) for k, v in deck.items()}
    if (train_seeds & validation_seeds or (train_seeds | validation_seeds) & duel_seeds
            or unordered(result["train"]["opponent"]) == unordered(result["validation"]["opponent"])):
        raise ContractError("construction train/validation seeds or opponents overlap")
    result["binding_sha256"] = digest({"task": task.sha256, "config": config, "train": result["train"], "validation": result["validation"]})
    return result


def run_comparison(state, partition, generation):
    from .local_training import run_path
    from .training_runner import atomic_json, file_receipt
    cfg = inputs(state.row["recipe"], state.task)
    source = cfg[partition]
    comparison, traces = compare_candidates(state.task, state.assets, [DeckParts.from_dict(d) for d in source["candidates"]],
        DeckParts.from_dict(source["opponent"]), seeds=tuple(source["paired_seeds"]),
        purpose=source["purpose"], seconds=cfg["config"]["comparison_seconds"])
    run = run_path(state.state_root, state.row["run_id"])
    path = run / "data" / source["purpose"] / f"{state.event_id()}-{generation}.json"
    artifact = {"kind": "private-audit-not-policy-input", "partition": source["purpose"], "binding_sha256": cfg["binding_sha256"],
                "comparison": comparison, "traces": traces}
    atomic_json(path, artifact)
    return comparison, file_receipt(path, run)


def initialize(state, generation):
    from .semantic_curriculum import configured,initialize as semantic_initialize
    if configured(state.row['recipe']):return semantic_initialize(state,generation)
    cfg = inputs(state.row["recipe"], state.task)
    if cfg is None:
        from .build_training import engineering_dataset
        return engineering_dataset(state.task, state.assets)
    comparison, artifact = run_comparison(state, "train", generation)
    data = real_game_dataset(state.task, state.assets, comparison)
    state.construction_state = {"binding_sha256": cfg["binding_sha256"], "train_artifact": artifact,
                                "consumed": [], "validation": []}
    return data


def consume(state, role):
    from .semantic_curriculum import configured,consume as semantic_consume
    if configured(state.row['recipe']):return semantic_consume(state,role)
    if state.construction_state is None:
        return
    marker = {"event_id": state.event_id(), "role": role, "partition": "construction_train",
              "supervision_sha256": state.data["supervision_sha256"],
              "artifact_sha256": state.construction_state["train_artifact"]["sha256"]}
    if any(m["event_id"] == marker["event_id"] and m["role"] == role for m in state.construction_state["consumed"]):
        raise ContractError("construction stage already consumed its supervised data")
    state.construction_state["consumed"].append(marker)


def validate_state(state, *, artifacts=False):
    from .semantic_curriculum import configured,validate_state as semantic_validate
    if configured(state.row['recipe']):return semantic_validate(state,artifacts=artifacts)
    from .local_training import run_path
    from .training_runner import read_artifact
    cfg = inputs(state.row["recipe"], state.task)
    warm = "bootstrap" in state.consumed
    if cfg is None or not warm:
        if state.construction_state is not None:
            raise ContractError("unconfigured/untrained group cannot claim real comparison curriculum")
        return
    saved = fields(state.construction_state, {"binding_sha256", "train_artifact", "consumed", "validation"})
    if saved["binding_sha256"] != cfg["binding_sha256"] or state.data["source"] != "engineering_real_game_pair_v1":
        raise ContractError("construction curriculum source binding differs")
    expected = [("bootstrap", r) for r in ("build_goal", "build_optimizer")]
    for event in state.consumed[1:]:
        for role in ("build_goal", "build_optimizer"):
            if event.endswith("-" + role):
                expected.append((event, role))
    actual = []
    for m in saved["consumed"]:
        fields(m, {"event_id", "role", "partition", "supervision_sha256", "artifact_sha256"})
        if (m["partition"] != "construction_train" or m["supervision_sha256"] != state.data["supervision_sha256"]
                or m["artifact_sha256"] != saved["train_artifact"]["sha256"]):
            raise ContractError("construction consumption source/partition differs")
        actual.append((m["event_id"], m["role"]))
    if actual != expected or [m["event_id"] for m in saved["validation"]] != [e for e in state.consumed if e.endswith("-evaluate")]:
        raise ContractError("construction consumed/validation markers differ from committed stages")
    for marker in saved["validation"]:
        fields(marker, {"event_id", "artifact", "comparison_sha256", "partition"})
        if marker["partition"] != "construction_validation":
            raise ContractError("construction validation marker has a training partition")
    if artifacts:
        run = run_path(state.state_root, state.row["run_id"])
        for partition, receipt in [("train", saved["train_artifact"]), *[("validation", m["artifact"]) for m in saved["validation"]]]:
            artifact = read_artifact(run, receipt)
            fields(artifact, {"kind", "partition", "binding_sha256", "comparison", "traces"})
            comparison = artifact["comparison"]
            validate_comparison(state.task, state.assets, comparison)
            source = cfg[partition]
            if (artifact["partition"] != source["purpose"] or artifact["binding_sha256"] != cfg["binding_sha256"]
                    or comparison["plan"]["purpose"] != source["purpose"] or comparison["plan"]["candidates"] != source["candidates"]
                    or comparison["plan"]["opponent"] != source["opponent"] or comparison["plan"]["paired_seeds_audit_only"] != source["paired_seeds"]
                    or len(artifact["traces"]) != len(comparison["games"])
                    or [digest(t) for t in artifact["traces"]] != [g["trace_sha256"] for g in comparison["games"]]):
                raise ContractError("construction persisted comparison/trace does not match frozen source")
            if partition == "train" and any(pair["evidence"] != comparison for pair in state.data["pairs"]):
                raise ContractError("checkpoint training labels differ from persisted actual comparisons")
            if partition == "validation" and not any(m["artifact"] == receipt and m["comparison_sha256"] == comparison["comparison_sha256"]
                                                      for m in saved["validation"]):
                raise ContractError("validation marker comparison differs from its artifact")
            for game, trace in zip(comparison["games"], artifact["traces"]):
                validate_trace(game, trace, state.assets)


def validate_trace(game, trace, assets):
    """Pair an audit with its outcome; hashing alone cannot resolve contradictions."""
    fields(trace, {"schema_version", "kind", "seed", "versions", "profile", "responses", "events", "outcome", "turns", "life_points"})
    integer(trace["schema_version"], "paired trace schema", 1, 1)
    versions = fields(trace["versions"], {"source_commits", "resources", "adapter_schema", "python", "policy", "option_preference"})
    if (trace["schema_version"] != 1 or trace["kind"] != "effect-duel-replay-not-policy-input"
            or digest(trace) != game["trace_sha256"] or digest(trace["profile"]) != game["profile_sha256"]
            or trace["seed"] != game["seed_audit_only"] or trace["outcome"] != game["outcome"]
            or trace["turns"] != game["turns"] or len(array(trace["responses"], "trace responses")) != game["decisions"]
            or not trace["events"] or trace["events"][-1]["kind"] != 5
            or {k: trace["events"][-1].get(k) for k in ("winner", "reason_code")} != game["outcome"]
            or versions["source_commits"] != assets.receipt["source_commits"] or versions["resources"] != assets.receipt["resources"]
            or versions["policy"] != DRIVER or versions["option_preference"] != "first"
            or versions["adapter_schema"] != "native-extra-material-v2"):
        raise ContractError("comparison game contradicts its persisted real trace or runtime versions")


def candidates(state):
    from .semantic_curriculum import configured
    if configured(state.row['recipe']):return None
    if state.construction_state is None:
        return None
    return [DeckParts.from_dict(d) for d in state.data["pairs"][0]["evidence"]["plan"]["candidates"]]


def alternate(state):
    """Model-ranked goal/optimizer/goal/optimizer, real-pair best incumbent."""
    import torch
    from .build_pipeline import apply_changes, deck_changes, verify_goal
    from .duel_model import parameter_digest
    from .semantic_curriculum import configured
    if configured(state.row['recipe']):
        from .build_pipeline import alternate_build
        return alternate_build(state.task,state.assets,state.builder.models,state.builder.encoder,base=DeckParts.from_dict(state.deck),
                               lora_versions={r:state.sessions[r].version_id() for r in state.builder.models})
    bank = candidates(state)
    comparison = state.data["pairs"][0]["evidence"]
    current, stages, verified = DeckParts.from_dict(state.deck), [], []
    for i in range(4):
        role = "build_goal" if i % 2 == 0 else "build_optimizer"
        model = state.builder.models[role]
        model.eval()
        with torch.no_grad():
            scores = model(state.builder.encoder.batch(state.task, bank))
        if not torch.isfinite(scores).all():
            raise ContractError("nonfinite real curriculum construction scores")
        chosen = int(scores.argmax())
        deck = bank[chosen]
        proof = verify_goal(state.task, deck, state.assets, attempts=64, seconds=30.)
        if proof["status"] != "verified_success":
            raise ContractError("model-selected curriculum candidate has no verified goal route")
        changes = deck_changes(current, deck)
        if apply_changes(current, changes) != deck:
            raise ContractError("curriculum construction changes do not reproduce the proposed deck")
        stages.append({"stage": i, "role": role, "task_sha256": state.task.sha256, "deck": deck.to_dict(), "changes": changes,
                       "validation": proof, "model_sha256": parameter_digest(model), "lora_version": state.sessions[role].version_id(),
                       "model_score_uncalibrated": float(scores[chosen]), "frozen_pair_engineering_score": comparison["mean_scores"][chosen]})
        verified.append(chosen)
        current = deck
    best = max(verified, key=lambda index: comparison["mean_scores"][index])
    return {"stages": stages, "best_deck": bank[best].to_dict(),
            "best_criterion": "frozen-real-rule-driver-pair-mean-engineering-only",
            "comparison_sha256": comparison["comparison_sha256"], "competitive_quality_validated": False}


def evaluate(state, generation):
    from .semantic_curriculum import configured,evaluate as semantic_evaluate
    if configured(state.row['recipe']):return semantic_evaluate(state,generation)
    comparison, receipt = run_comparison(state, "validation", generation)
    state.construction_state["validation"].append({"event_id": state.event_id(), "artifact": receipt,
        "comparison_sha256": comparison["comparison_sha256"], "partition": "construction_validation"})
    return {"comparison_sha256": comparison["comparison_sha256"], "mean_scores": comparison["mean_scores"],
            "partition": "construction_validation", "training_labels_created": False,
            "competitive_ability_validated": False}
