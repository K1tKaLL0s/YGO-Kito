"""Config-driven local CPU rounds, held-out validation and durable usage outbox.

Only fresh in-memory player trajectories can reach PPO. Stored shards are audit
data, never a resumed/off-policy batch. This is not a cloud resource controller.
"""

from collections import Counter
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import random
import time
from uuid import uuid4

from .build_contracts import digest
from .validation import ContractError, canonical_json, fields, integer, read_json

ROOT = Path(__file__).resolve().parents[2]
OPPONENTS = ("visible-effects-first-v1", "visible-effects-last-option-v1")


def validate_recipe(value):
    if isinstance(value, dict) and value.get("workflow") == "four-model-alternating-v1":
        from .group_runner import validate_recipe as validate_group
        return validate_group(value)
    from .cpu_training import config_from_dict
    from .training_plan import number
    fields(value, {"schema_version", "max_updates", "validate_every", "checkpoint_every", "wall_seconds",
                   "cpu_config", "train", "validation"})
    integer(value["schema_version"], "runner schema", 1, 1)
    count = integer(value["max_updates"], "maximum updates", 1, 100000)
    for key in ("validate_every", "checkpoint_every"):
        integer(value[key], key, 1, count)
    number(value["wall_seconds"], "local active wall budget", minimum=1, maximum=360000)
    fields(value["train"], {"profile", "opponent", "seed_start", "seed_stride"})
    fields(value["validation"], {"profile", "opponent", "seeds", "policy_seed"})
    for part in ("train", "validation"):
        spec = value[part]
        if spec["opponent"] not in OPPONENTS:
            raise ContractError("runner supports only versioned visible-DTO baseline opponents")
        path = spec["profile"]
        if not isinstance(path, str) or not path.startswith("configs/") or not path.endswith(".json") or ".." in Path(path).parts:
            raise ContractError("runner profile must be a repository configs JSON path")
    if value["train"]["opponent"] == value["validation"]["opponent"]:
        raise ContractError("validation must reserve a different fixed opponent driver")
    train = value["train"]
    integer(train["seed_start"], "train seed start", 0, 2**32 - 8)
    integer(train["seed_stride"], "train seed stride", 1, 2**32 - 8)
    seeds = tuple(train["seed_start"] + train["seed_stride"] * i for i in range(count))
    integer(seeds[-1], "last train seed", 0, 2**32 - 8)
    val = value["validation"]
    if not isinstance(val["seeds"], list) or not 1 <= len(val["seeds"]) <= 32:
        raise ContractError("validation needs 1..32 held-out seeds")
    for seed in val["seeds"]:
        integer(seed, "validation seed", 0, 2**32 - 8)
    if len(set(val["seeds"])) != len(val["seeds"]) or set(seeds) & set(val["seeds"]):
        raise ContractError("train/validation seeds must be disjoint and unique")
    integer(val["policy_seed"], "validation policy RNG seed", 0, 2**32 - 8)
    if not isinstance(value["cpu_config"], dict) or "game_seeds" in value["cpu_config"]:
        raise ContractError("runner owns the training data cursor/seeds")
    if value["cpu_config"].get("curriculum") is not None:
        raise ContractError("controlled prompt curriculum needs independently versioned runner train/eval controllers; use the standalone CPU proof")
    config_from_dict(dict(value["cpu_config"], game_seeds=list(seeds)))
    return json.loads(canonical_json(value))


def recipe_inputs(recipe):
    from .cpu_training import config_from_dict
    from .deck_profile import validate_profile
    profiles = {}
    for part in ("train", "validation"):
        path = ROOT / recipe[part]["profile"]
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT / "configs"):
            raise ContractError("profile outside trusted repository configuration")
        profiles[part] = read_json(path)
        validate_profile(profiles[part])
    # A different name or deck order is not a held-out construction.
    if [Counter(d) for d in profiles["train"]["decks"]] == [Counter(d) for d in profiles["validation"]["decks"]]:
        raise ContractError("validation must reserve an actual deck-list variant")
    train = recipe["train"]
    seeds = [train["seed_start"] + train["seed_stride"] * i for i in range(recipe["max_updates"])]
    return profiles, config_from_dict(dict(recipe["cpu_config"], game_seeds=seeds))


def binding_for(root, row):
    from .cpu_training import resource_binding
    result = resource_binding(Path(root), row["profile"])
    if "recipe" in row:
        recipe = validate_recipe(row["recipe"])
        profiles, config = recipe_inputs(recipe)
        if (profiles["train"] != row["profile"] or profiles["validation"] != row["validation_profile"]
                or digest(asdict(config)) != digest(row["config"])):
            raise ContractError("runner profiles/configuration changed; preserve previous run")
        result.update(runner_recipe_sha256=digest(recipe), validation_profile_sha256=digest(profiles["validation"]))
    return result


def atomic_json(path, value):
    """Durable no-overwrite publication in the destination filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / (".staging-" + uuid4().hex)
    try:
        with temporary.open("x") as output:
            output.write(canonical_json(value) + "\n")
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)  # Unlike replace(), refuses an existing artifact.
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def file_receipt(path, run):
    return {"path": path.relative_to(run).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size}


def read_artifact(run, receipt):
    fields(receipt, {"path", "sha256", "bytes"})
    path = run / receipt["path"]
    if path.is_symlink() or not path.resolve().is_relative_to(run.resolve()):
        raise ContractError("round artifact outside the registered run")
    if not path.is_file() or path.stat().st_size != receipt["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != receipt["sha256"]:
        raise ContractError("round data integrity differs")
    return read_json(path)


def shard_for(episode, opponent_binding):
    # No seed, opponent requests, raw native messages or full hidden state here.
    return {"schema_version": 1, "partition": episode["purpose"], "policy_version": episode["policy_version"],
            "policy_sha256": episode["policy_sha256"], "opponent_binding_sha256": opponent_binding,
            "steps": [dict(step, request=step["request"].to_dict()) for step in episode["steps"]]}


def opponent_binding(row, part):
    profile = row["profile"] if part == "train" else row["validation_profile"]
    return digest({"driver": row["recipe"][part]["opponent"], "profile": profile,
                   "implementation": row["binding"]["python_implementation_sha256"],
                   "resources": row["binding"]["resources"]})


def validate_shard(value, trainer, *, purpose, version, policy_sha256, opponent_sha256):
    from .contracts import DecisionRequest
    from dataclasses import replace
    from .hierarchical_policy import MAX_LEAVES,validate_receipt
    fields(value, {"schema_version", "partition", "policy_version", "policy_sha256", "opponent_binding_sha256", "steps"})
    if (value["schema_version"] != 1 or value["partition"] != purpose or value["policy_version"] != version
            or value["policy_sha256"] != policy_sha256 or value["opponent_binding_sha256"] != opponent_sha256):
        raise ContractError("round data partition/policy/opponent binding differs")
    if not isinstance(value["steps"], list) or not value["steps"]:
        raise ContractError("round shard lacks a complete actor trajectory")
    for step in value["steps"]:
        fields(step, {"request", "action_index", "old_log_prob", "old_value", "reward"}, {"hierarchy"})
        request = DecisionRequest.from_dict(step["request"])
        if request.observation.observer != trainer.config.actor_seat:
            raise ContractError("round shard contains another seat's private observation")
        integer(step["action_index"], "shard legal action index", 0, len(request.actions) - 1)
        if len(request.actions)>MAX_LEAVES:raise ContractError('shard legal actions exceed complete policy budget')
        cap=trainer.encoder.config.max_actions
        if 'hierarchy' in step:
            validate_receipt(step['hierarchy'],action_count=len(request.actions),action_index=step['action_index'],
                             old_log_prob=step['old_log_prob'],max_actions=cap)
        elif len(request.actions)>cap:
            raise ContractError('large-action shard lacks its hierarchical policy receipt')
        for start in range(0,len(request.actions),cap):
            trainer.encoder.encode(replace(request,actions=request.actions[start:start+cap]))


def commit_round(row, manifest):
    """Called inside the control DB transaction; same step cannot be counted twice."""
    step = manifest["step"]
    if step != row["metrics"]["steps"] + 1 or manifest["checkpoint_id"] in row["checkpoint_ids"]:
        raise ContractError("round commit is duplicate or skips a durable update")
    row["checkpoint_ids"].append(manifest["checkpoint_id"])
    row["rounds"].append({"step": step, "manifest_sha256": digest(manifest)})
    row["updates"].append({"update": manifest["update"], "duel": manifest["train_summary"]})
    row["validations"].extend(manifest["validation_summaries"])
    if manifest["scheduled_checkpoint"]:
        row["scheduled_checkpoint_ids"].append(manifest["checkpoint_id"])
    row["metrics"].update(steps=step, episodes=step, loss=manifest["update"]["loss"],
                          validation_episodes=len(row["validations"]), committed_rounds=len(row["rounds"]))
    row["history"].append({"event": "actual_optimizer_update_checkpointed", "step": step,
                           "model_sha256": manifest["update"]["after_sha256"], "checkpoint_id": manifest["checkpoint_id"]})


def reconcile_round(state_root, row, trainer):
    """Adopt only a complete validated round; partial publication is quarantined."""
    from .local_training import checkpoint_receipt, run_path
    from .cpu_training import load_checkpoint
    run = run_path(state_root, row["run_id"])
    step = trainer.updates + 1
    checkpoint = run / "checkpoints" / f"local-step-{step}.weights"
    manifest_path = run / "rounds" / f"step-{step}.json"
    if not checkpoint.exists() and not manifest_path.exists():
        return None
    if not checkpoint.exists() or not checkpoint.with_suffix(".json").exists() or not manifest_path.exists():
        quarantine = run / "quarantine" / uuid4().hex
        quarantine.mkdir(parents=True)
        for path in (checkpoint, checkpoint.with_suffix(".json"), manifest_path):
            if path.exists():
                path.replace(quarantine / path.name)
        return {"event": "partial_round_quarantined", "step": step}
    receipt = read_json(checkpoint.with_suffix(".json"))
    if receipt != checkpoint_receipt(row["run_id"], checkpoint, step):
        raise ContractError("unregistered round checkpoint integrity differs")
    restored = load_checkpoint(checkpoint, row["binding"])
    if restored.updates != step or digest(asdict(restored.config)) != digest(row["config"]):
        raise ContractError("unregistered round checkpoint configuration differs")
    manifest = read_json(manifest_path)
    from .duel_model import parameter_digest
    verify_round(run, row, parameter_digest(trainer.model), restored, manifest)
    return {"event": "adopted_verified_complete_round", "manifest": manifest}


def verify_round(run, row, previous_sha256, restored, manifest):
    from .duel_model import parameter_digest
    fields(manifest, {"schema_version", "step", "recipe_sha256", "checkpoint_id", "update", "train_summary",
                      "train_shard", "validation_shards", "validation_summaries", "scheduled_checkpoint"})
    step = restored.updates
    scheduled = step % row["recipe"]["checkpoint_every"] == 0 or step == row["recipe"]["max_updates"]
    if (manifest["schema_version"] != 1 or manifest["step"] != step or manifest["recipe_sha256"] != digest(row["recipe"])
            or manifest["checkpoint_id"] != f"local-step-{step}" or manifest["scheduled_checkpoint"] != scheduled
            or manifest["update"]["optimizer_step"] != step
            or manifest["update"]["before_sha256"] != previous_sha256
            or manifest["update"]["after_sha256"] != parameter_digest(restored.model)):
        raise ContractError("round boundary/recipe/model lineage differs")
    summary = manifest["train_summary"]
    if (summary["purpose"] != "train" or summary["policy_version"] != step - 1
            or summary["seed_audit_only"] != restored.config.game_seeds[step - 1]
            or summary["policy_sha256"] != manifest["update"]["before_sha256"]
            or summary["opponent"] != row["recipe"]["train"]["opponent"]):
        raise ContractError("training round seed/purpose/opponent lineage differs")
    if not manifest["train_shard"]["path"].startswith("data/train/"):
        raise ContractError("training artifact is outside its data partition")
    validate_shard(read_artifact(run, manifest["train_shard"]), restored, purpose="train", version=step - 1,
                   policy_sha256=manifest["update"]["before_sha256"], opponent_sha256=opponent_binding(row, "train"))
    should_validate = step % row["recipe"]["validate_every"] == 0 or step == row["recipe"]["max_updates"]
    expected = row["recipe"]["validation"]["seeds"] if should_validate else []
    if (len(manifest["validation_shards"]) != len(expected) or len(manifest["validation_summaries"]) != len(expected)
            or [v["seed_audit_only"] for v in manifest["validation_summaries"]] != expected):
        raise ContractError("round validation set incomplete")
    for artifact, summary in zip(manifest["validation_shards"], manifest["validation_summaries"]):
        if (not artifact["path"].startswith("data/validation/") or summary["purpose"] != "validation"
                or summary["policy_version"] != step or summary["policy_sha256"] != manifest["update"]["after_sha256"]
                or summary["opponent"] != row["recipe"]["validation"]["opponent"]):
            raise ContractError("validation round purpose/opponent lineage differs")
        validate_shard(read_artifact(run, artifact), restored, purpose="validation", version=step,
                       policy_sha256=manifest["update"]["after_sha256"], opponent_sha256=opponent_binding(row, "validation"))


def verify_committed(state_root, row, trainer):
    from .local_training import run_path
    if trainer.updates != row["metrics"]["steps"] or len(row["rounds"]) != trainer.updates or len(row["updates"]) != trainer.updates:
        raise ContractError("runner checkpoint/data cursor differs from committed rounds")
    if trainer.updates:
        run = run_path(state_root, row["run_id"])
        manifest = read_json(run / "rounds" / f"step-{trainer.updates}.json")
        if digest(manifest) != row["rounds"][-1]["manifest_sha256"] or manifest["update"] != row["updates"][-1]["update"]:
            raise ContractError("committed round manifest differs from transaction journal")
        before = row["updates"][-2]["update"]["after_sha256"] if trainer.updates > 1 else row["initial_model_sha256"]
        verify_round(run, row, before, trainer, manifest)


def settle_usage(row, outcome, measurement):
    """Journal one segment once. A new generation after a fault is real new usage."""
    from .local_training import elapsed
    if row["segment_started"] is None:
        return
    active = elapsed(row)
    delta = max(.001, active - row["active_seconds"])
    event_id = "cpu-" + digest({"run": row["run_id"], "generation": row["generation"]})[:40]
    if not any(e["payload"]["event_id"] == event_id for e in row["usage_outbox"]):
        row["usage_outbox"].append({"payload": {"event_id": event_id, "stage_id": "throughput-small-train", "gpu_count": 0,
                                   "wall_seconds": delta, "activity": "train", "outcome": outcome, "amount": None, "currency": None},
                                   "measurement": measurement, "exported": False})
    row["active_seconds"], row["segment_started"] = active, None


def sync_usage(state_root, run_id):
    """Outbox retry checks the actual ledger first, including uncertain outcomes."""
    from .local_training import _connect, get_row, put_row
    from .training_plan import BudgetBook
    with closing(_connect(state_root)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = get_row(db, run_id)
        if "recipe" not in row:
            return
        book = BudgetBook(Path(state_root) / "cpu-usage.sqlite3", row["budget_plan"], role="trainer", create=True)
        known = {event["event_id"]: event for event in book.history()}
        for event in row["usage_outbox"]:
            payload = event["payload"]
            if payload["event_id"] in known:
                if any(known[payload["event_id"]][key] != value for key, value in payload.items()):
                    raise ContractError("usage outbox/ledger identity conflict")
            else:
                book.record(dict(payload, expected_revision=book.status()["revision"]))
            event["exported"] = True
        row["metrics"].update(usage_segments=len(row["usage_outbox"]),
                              usage_wall_seconds=sum(e["payload"]["wall_seconds"] for e in row["usage_outbox"]))
        put_row(db, row)


def worker_rounds(state_root, run_id, generation, reporter):
    from .local_training import _connect, get_row, put_row, verified_trainer, run_path, write_checkpoint
    from .duel_model import parameter_digest
    trainer_row = None
    with closing(_connect(state_root)) as db:
        trainer_row = get_row(db, run_id)
    trainer = verified_trainer(state_root, trainer_row)
    recipe = trainer_row["recipe"]
    run = run_path(state_root, run_id)
    while trainer.updates < recipe["max_updates"]:
        with closing(_connect(state_root)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = get_row(db, run_id)
            if row["generation"] != generation:
                raise ContractError("runner lease superseded")
            if row["desired"] != "running":
                break
            # Reserve a full bounded episode and scheduled validation before
            # starting new work. The kernel timer still handles unexpected stalls.
            from .local_training import elapsed
            validations_due = (trainer.updates + 1) % recipe["validate_every"] == 0 or trainer.updates + 1 == recipe["max_updates"]
            reserve = trainer.config.episode_seconds * (1 + len(recipe["validation"]["seeds"]) * validations_due) + 3
            if row["wall_limit_seconds"] - elapsed(row) <= reserve:
                row.update(desired="stopped", reason="wall_budget_reserve_reached")
                put_row(db, row)
                break
            row.update(phase="sampling", revision=row["revision"] + 1)
            row["history"].append({"event": "fresh_episode_started", "step": trainer.updates + 1,
                                   "generation": generation, "policy_sha256": parameter_digest(trainer.model)})
            put_row(db, row)
        episode = trainer.sample_episode(Path(row["native_root"]), row["profile"], opponent=recipe["train"]["opponent"])
        with closing(_connect(state_root)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = get_row(db, run_id)
            row["phase"] = "updating"
            put_row(db, row)
        update = trainer.update(episode)
        step = trainer.updates
        train_path = run / "data/train" / f"step-{step}-{generation}.json"
        atomic_json(train_path, shard_for(episode, opponent_binding(row, "train")))
        validations, validation_shards = [], []
        if step % recipe["validate_every"] == 0 or step == recipe["max_updates"]:
            with closing(_connect(state_root)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                current = get_row(db, run_id)
                current["phase"] = "validating"
                put_row(db, current)
            import torch
            rng_before = (trainer.policy_rng.get_state().clone(), trainer.batch_rng.get_state().clone(),
                          torch.get_rng_state().clone(), random.getstate())
            for index, seed in enumerate(recipe["validation"]["seeds"]):
                val = trainer.sample_episode(Path(row["native_root"]), row["validation_profile"], purpose="validation", seed=seed,
                                             policy_seed=recipe["validation"]["policy_seed"], opponent=recipe["validation"]["opponent"])
                path = run / "data/validation" / f"step-{step}-{index}-{generation}.json"
                atomic_json(path, shard_for(val, opponent_binding(row, "validation")))
                validation_shards.append(file_receipt(path, run))
                validations.append({k: v for k, v in val["summary"].items() if k != "actor_inference_ms"})
            if (parameter_digest(trainer.model) != update["after_sha256"] or trainer.episode_cursor != step
                    or not torch.equal(rng_before[0], trainer.policy_rng.get_state())
                    or not torch.equal(rng_before[1], trainer.batch_rng.get_state())
                    or not torch.equal(rng_before[2], torch.get_rng_state()) or rng_before[3] != random.getstate()):
                raise ContractError("validation modified training weights/RNG/cursor")
        with closing(_connect(state_root)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            current = get_row(db, run_id)
            current["phase"] = "saving"
            put_row(db, current)
        # Every optimizer boundary is recoverable. Scheduled archives are separate
        # from this mandatory recovery journal; no pretend reduction in save IO.
        receipt = write_checkpoint(trainer, state_root, row)
        manifest = {"schema_version": 1, "step": step, "recipe_sha256": digest(recipe),
                    "checkpoint_id": receipt["checkpoint_id"], "update": update,
                    "train_summary": {k: v for k, v in episode["summary"].items() if k != "actor_inference_ms"},
                    "train_shard": file_receipt(train_path, run), "validation_shards": validation_shards,
                    "validation_summaries": validations,
                    "scheduled_checkpoint": step % recipe["checkpoint_every"] == 0 or step == recipe["max_updates"]}
        atomic_json(run / "rounds" / f"step-{step}.json", manifest)
        with closing(_connect(state_root)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = get_row(db, run_id)
            commit_round(row, manifest)
            resources = reporter.resources()
            row["metrics"].update(process_cpu_seconds=row["completed_worker_cpu_seconds"] + resources["process_cpu_seconds"],
                                  process_peak_rss_bytes=max(row["metrics"].get("process_peak_rss_bytes", 0), resources.get("process_peak_rss_bytes", 0)))
            row.update(phase="checkpoint_boundary", revision=row["revision"] + 1)
            put_row(db, row)
    return trainer.updates == recipe["max_updates"]
