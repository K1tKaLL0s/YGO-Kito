"""Actual four-role adapter updates and a real frozen-adapter evaluation.

The bases are small engineering checkpoints, not validated competitive bases.
One fresh native trajectory is used for two bounded PPO adapter epochs.
"""

import copy
import hashlib
from pathlib import Path

import torch
from torch.distributions import Categorical
from torch.nn import functional as F

from .agent_monitor import RunMonitor, RunReporter
from .agent_registry import identifier
from .build_contracts import DeckParts, digest
from .build_model import FEATURE_VERSION as BUILD_FEATURES
from .build_pipeline import BuildAssets, alternate_build
from .build_training import engineering_dataset
from .coord_contracts import FeedbackPolicy, ROUTES
from .coordinator import Coordinator
from .coordinator_model import FEATURE_VERSION as COORD_FEATURES, context_tensor, engineering_examples
from .duel_model import FEATURE_VERSION as DUEL_FEATURES, parameter_digest
from .lora import AdapterConfig, AdapterSession, ROLES, tensor_digest
from .model_group import (ROOT, call, execute_duel_job, group_binding, restore_group, route_with_model,
                          run_model_group_smoke, save_group)
from .validation import ContractError, canonical_json, fields, integer, read_json


def adapter_configs(value):
    fields(value, {"schema_version", "base_version", "calibration", "scope", "adapters"})
    integer(value["schema_version"], "LoRA group config schema", 1, 1)
    identifier(value["base_version"])
    if (value["schema_version"] != 1 or value["calibration"] != "pending" or
            value["scope"] != "structural-engineering-not-transfer-ability" or not isinstance(value["adapters"], list)):
        raise ContractError("explicit pending engineering LoRA configuration required")
    rows = [AdapterConfig.from_dict(c) for c in value["adapters"]]
    if len(rows) != 4 or {c.role for c in rows} != set(ROLES) or any(c.max_updates != 2 for c in rows):
        raise ContractError("CPU group proof requires four roles and two adapter updates each")
    if len({c.adapter_id for c in rows}) != 4:
        raise ContractError("role adapters must have independent identities")
    return {c.role: c for c in rows}


def construction_loss(role, session, builder, task, data):
    records = data["goals"] if role == "build_goal" else data["pairs"]
    rows = [records[i] for i in torch.randperm(len(records), generator=session.rng).tolist()]
    session.model.train()
    if role == "build_goal":
        decks = [DeckParts.from_dict(r["deck"]) for r in rows]
        scores = session.model(builder.encoder.batch(task, decks))
        return F.binary_cross_entropy_with_logits(scores, torch.tensor([r["label"] for r in rows]))
    decks = [DeckParts.from_dict(r[k]) for r in rows for k in ("better", "worse")]
    scores = session.model(builder.encoder.batch(task, decks)).reshape(-1, 2)
    return F.softplus(scores[:, 1] - scores[:, 0]).mean()


def coordinator_loss(session):
    rows = engineering_examples()["records"]
    rows = [rows[i] for i in torch.randperm(len(rows), generator=session.rng).tolist()]
    session.model.train()
    logits, forecasts = session.model(torch.tensor([context_tensor(r["context"]) for r in rows]))
    return (F.cross_entropy(logits, torch.tensor([ROUTES.index(r["route_label"]) for r in rows])) +
            F.mse_loss(forecasts, torch.tensor([r["synthetic_probability_anchor"] for r in rows])))


def ppo_inputs(episode, sampler, session):
    if episode["policy_sha256"] != parameter_digest(session.model) or episode["source"] != "live-core-actor-seat":
        raise ContractError("LoRA PPO batch must originate from this initial live policy")
    steps, cfg = episode["steps"], sampler.config
    advantages, following, gae = [], 0., 0.
    for step in reversed(steps):
        delta = step["reward"] + cfg.gamma * following - step["old_value"]
        gae = delta + cfg.gamma * cfg.gae_lambda * gae
        advantages.append(gae)
        following = step["old_value"]
    advantages = torch.tensor(list(reversed(advantages)))
    returns = advantages + torch.tensor([s["old_value"] for s in steps])
    indices = torch.randperm(len(steps), generator=session.rng)[:cfg.batch_size]
    chosen = [steps[i] for i in indices.tolist()]
    adv = advantages[indices]
    adv = (adv - adv.mean()) / (adv.std(unbiased=False) + 1e-8)
    return {"batch": sampler.encoder.batch([s["request"] for s in chosen]),
            "actions": torch.tensor([s["action_index"] for s in chosen]),
            "old_log_probs": torch.tensor([s["old_log_prob"] for s in chosen]),
            "advantages": adv, "returns": returns[indices], "samples": len(chosen)}


def ppo_loss(session, values, config):
    session.model.train()
    logits, predicted = session.model(values["batch"])
    distribution = Categorical(logits=logits)
    ratio = (distribution.log_prob(values["actions"]) - values["old_log_probs"]).exp()
    policy = -torch.minimum(ratio * values["advantages"], ratio.clamp(1 - config.clip_ratio, 1 + config.clip_ratio) * values["advantages"]).mean()
    return policy + config.value_weight * ((predicted - values["returns"]) ** 2).mean() - config.entropy_weight * distribution.entropy().mean()


def output(model, batch):
    model.eval()
    with torch.no_grad():
        value = model(batch)
    return {str(i): x.detach().clone() for i, x in enumerate(value if isinstance(value, tuple) else (value,))}


def run_lora_group_smoke(root, state_root, run_id, task, lora_config, policy=None):
    identifier(run_id)
    if len(run_id) > 40:
        raise ContractError("LoRA proof run ID exceeds bounded suffix budget")
    configs = adapter_configs(lora_config)
    policy = policy or FeedbackPolicy()
    state_root = Path(state_root).resolve()
    run = state_root / "runs" / run_id
    if run.exists():
        raise ContractError("LoRA run exists; choose a new ID")
    reporter = RunReporter(state_root)
    snapshot = {"schema_version": 1, "run_id": run_id, "state": "running", "revision": 0,
                "model_versions": {r: configs[r].adapter_id for r in ROLES}, "metrics": reporter.resources(),
                "checkpoint_ids": [], "source": "trainer"}
    reporter.publish(snapshot)
    try:
        base_id = run_id + "-base"
        base_proof = run_model_group_smoke(root, state_root, base_id, task, policy)
        assets, profile = BuildAssets(root), read_json(ROOT / "configs/effect-duel-v1.json")
        binding = group_binding(task, assets, policy)
        base_file = state_root / "runs" / base_id / "checkpoints/group-before-duel.weights"
        recovered = restore_group(base_file, run / "base-components", assets, binding)
        builder, duel, coordinator = (recovered[k] for k in ("builder", "duel", "coordinator"))
        # Keep the completed canonical base ledger; never replace it with the
        # earlier pending snapshot recovered for the model components.
        host = Coordinator(state_root / "runs" / base_id / "coordinator.sqlite3", policy,
                           role="coordinator", source="real_engine", assets=assets)
        if host.forecast_status("group-forecast")["matches"] != 1:
            raise ContractError("prior canonical base history must remain present")
        data = engineering_dataset(task, assets)
        models = dict(builder.models, duel=duel.model, coordinator=coordinator.model)
        contexts = {r: {"base_group_binding": binding, "lora_config_sha256": digest(lora_config),
                        "task_sha256": task.sha256, "supervision_sha256": data["supervision_sha256"],
                        "feature_version": DUEL_FEATURES if r == "duel" else COORD_FEATURES if r == "coordinator" else BUILD_FEATURES} for r in ROLES}
        sessions = {r: AdapterSession(models[r], configs[r], {"base_version": lora_config["base_version"],
                       "feature_version": contexts[r]["feature_version"], "context_sha256": digest(contexts[r])}) for r in ROLES}
        # A shallow sampler shares only the actual actor/encoder. Its policy RNG
        # and episode cursor are independent of the frozen base trainer cursor.
        sampler = copy.copy(duel)
        sampler.policy_rng = torch.Generator(device="cpu").manual_seed(duel.config.policy_seed + 10)
        sampler.episode_cursor = 0
        training_episode = sampler.sample_episode(assets.root, profile)
        ppo = ppo_inputs(training_episode, sampler, sessions["duel"])
        probe_decks = [DeckParts.from_dict(data["goals"][0]["deck"])]
        probes = {r: builder.encoder.batch(task, probe_decks) for r in builder.models}
        probes["duel"] = ppo["batch"]
        probes["coordinator"] = torch.tensor([context_tensor(r["context"]) for r in engineering_examples()["records"]])
        baseline_outputs = {r: output(models[r], probes[r]) for r in ROLES}
        updates = []
        for epoch in range(2):
            for role in ("build_goal", "build_optimizer"):
                updates.append(sessions[role].step(construction_loss(role, sessions[role], builder, task, data)))
            updates.append(dict(sessions["duel"].step(ppo_loss(sessions["duel"], ppo, duel.config)),
                                source="live-core-ppo-adapter-epoch", trajectory_sha256=training_episode["summary"]["trajectory_sha256"],
                                epoch=epoch + 1, total_epochs=2, batch_samples=ppo["samples"]))
            updates.append(dict(sessions["coordinator"].step(coordinator_loss(sessions["coordinator"])),
                                source="synthetic-rule-imitation-and-probability-anchors"))
        rollback = {}
        for role, session in sessions.items():
            adapted = output(models[role], probes[role])
            session.set_enabled(False)
            disabled = output(models[role], probes[role])
            exact = all(torch.equal(baseline_outputs[role][k], disabled[k]) for k in disabled)
            changed = any(not torch.equal(baseline_outputs[role][k], adapted[k]) for k in adapted)
            if not exact or not changed:
                raise ContractError("adapter must affect output and roll back exactly to its base")
            session.set_enabled(True)
            rollback[role] = {"base_output_sha256": tensor_digest(baseline_outputs[role]),
                              "adapted_output_sha256": tensor_digest(adapted), "disabled_output_sha256": tensor_digest(disabled),
                              "exact_base_output_restore": exact, "active_output_changed": changed, "base_sha256": session.verify_base()}
        receipts = {r: sessions[r].save(run / "adapters" / (r + ".weights")) for r in ROLES}
        versions = {r: sessions[r].version_id() for r in ROLES}
        construction = alternate_build(task, assets, builder.models, builder.encoder,
                                       lora_versions={r: versions[r] for r in builder.models})
        if len(construction["stages"]) != 4:
            raise ContractError("adapted construction must retain four real verified stages")
        old = call(host, "candidate.read", {"candidate_id": "group-candidate"})
        same_deck = digest(construction["best_deck"]) == old["deck_sha256"]
        candidate_id = "group-candidate" if same_deck else "lora-candidate"
        if not same_deck:
            call(host, "handoff.submit", {"candidate_id": candidate_id, "parent_candidate_id": "group-candidate", "task": task.to_dict(),
                 "deck": construction["best_deck"], "build_models": {r: parameter_digest(models[r]) for r in builder.models}})
        _, advice = route_with_model(host, coordinator, candidate_id, None, 1)
        scope = dict(base_proof["forecast"]["scope"], actor_policy_sha256=parameter_digest(duel.model), duel_lora=versions["duel"])
        forecast = call(host, "forecast.register", {"forecast_id": "lora-forecast", "candidate_id": candidate_id,
                        "probability": advice["probability"], "origin_role": "coordinator", "model_sha256": parameter_digest(coordinator.model),
                        "calibration": "pending", "scope": scope})
        job = call(host, "job.schedule", {"job_id": "lora-evaluation", "forecast_id": "lora-forecast", "seed": 24, "purpose": "engineering_validation"})
        cursor = {"job_id": job["job_id"], "forecast_id": "lora-forecast", "run_id": run_id, "task": task}
        checkpoint = run / "checkpoints/group-adapted-before-duel.weights"
        saved = save_group(checkpoint, builder, duel, coordinator, data, host, task, assets, policy, profile,
                           dict(cursor, task=task.to_dict()), adapters=sessions)
        meta = {"schema_version": 1, "run_id": run_id, "checkpoint_id": "group-adapted-before-duel",
                "artifact_bytes": saved["artifact_bytes"], "artifact_sha256": saved["artifact_sha256"], "step": 8}
        checkpoint.with_suffix(".json").write_text(canonical_json(meta) + "\n")
        snapshot = dict(snapshot, revision=1, checkpoint_ids=["group-adapted-before-duel"], metrics=dict(reporter.resources(), steps=8))
        reporter.publish(snapshot)
        RunMonitor(state_root).checkpoint(run_id, "group-adapted-before-duel")
        expected = {r: s.compatibility() for r, s in sessions.items()}
        canonical = execute_duel_job(host, duel, coordinator, assets, profile, cursor, adapter=sessions["duel"])
        repeat = restore_group(checkpoint, run / "adapted-recovery", assets, binding, expected_adapters=expected)
        repeated = execute_duel_job(repeat["host"], repeat["duel"], repeat["coordinator"], assets, profile,
                                   dict(repeat["cursor"], task=repeat["task"]), adapter=repeat["adapters"]["duel"])
        equal = (canonical["result"] == repeated["result"] and canonical["duel"] == repeated["duel"] and
                 canonical["ledger_state_sha256"] == repeated["ledger_state_sha256"] and
                 all(repeat["adapters"][r].version_id() == versions[r] for r in ROLES))
        if not equal:
            raise ContractError("adapted group actual evaluation/recovery diverged")
        unloaded = {r: s.unload() for r, s in repeat["adapters"].items()}
        metrics = dict(reporter.resources(), steps=8, episodes=2, loss=updates[-1]["loss"])
        result = {"schema_version": 1, "ok": True, "scope": "structural-lora-four-role-engineering-not-transfer-ability",
                  "binding": binding, "lora_config": lora_config, "contexts": contexts, "updates": updates,
                  "adapter_versions": versions, "adapter_compatibility": expected, "adapter_artifacts": receipts,
                  "rollback": rollback, "unloaded_base_hashes": unloaded, "base_proof": {"run_id": base_id,
                      "file_sha256": hashlib.sha256((state_root / "runs" / base_id / "proof.json").read_bytes()).hexdigest(),
                      "model_hashes": base_proof["model_hashes"], "canonical_optimizer_calls": 7,
                      "physical_complete_games": 3, "competitive_ability_validated": False},
                  "construction": construction, "candidate_reused_from_base": same_deck, "forecast": forecast, "job": job,
                  "training_duel": {k: v for k, v in training_episode["summary"].items() if k != "actor_inference_ms"},
                  "evaluation": canonical, "prior_base_forecast_matches_preserved": host.forecast_status("group-forecast")["matches"],
                  "checkpoint": saved, "restore_verified": equal, "history": host.history(), "metrics": metrics,
                  "canonical_adapter_optimizer_calls": 8, "canonical_all_optimizer_calls_including_base": 15,
                  "adapter_training_episodes": 1, "canonical_adapter_evaluation_matches": 1,
                  "physical_complete_games_including_base_and_recovery": 6,
                  "statistical_calibration": "pending", "transfer_ability_validated": False, "competitive_ability_validated": False,
                  "hardware": base_proof["hardware"], "cost": base_proof["cost"]}
        (run / "proof.json").write_text(canonical_json(result) + "\n")
        reporter.publish(dict(snapshot, state="completed", revision=2, metrics=metrics))
        return result
    except Exception:
        old = reporter.snapshot(run_id)
        reporter.publish(dict(old, state="failed", revision=old["revision"] + 1, metrics=reporter.resources()))
        raise
