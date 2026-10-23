"""Bounded real-core, on-policy CPU PPO/update/checkpoint engineering proof.

Only one actor's legal player requests become training samples. Engine seeds,
opponent requests and complete native audit messages stay outside model inputs.
Checkpoint recovery is verified at complete-episode boundaries, never mid-duel.
"""

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import sqlite3
import time

import torch
from torch.distributions import Categorical

from .agent_monitor import RunMonitor, RunReporter
from .agent_registry import identifier
from .contracts import ActionSelection
from .duel_model import DuelActorCritic, DuelModelConfig, FEATURE_VERSION, PlayerEncoder, parameter_digest
from .effect_duel import choose_effect_duel_action, public_card_facts
from .native import NativeError, NativeNormalEngine
from .native_assets import verify_resources
from .normal_duel import request_digest
from .hierarchical_policy import score_requests, sample_index, validate_receipt
from .validation import ContractError, canonical_json, fields, integer


@dataclass(frozen=True)
class CpuTrainingConfig:
    model: DuelModelConfig = field(default_factory=DuelModelConfig)
    model_seed: int = 123
    policy_seed: int = 456
    batch_seed: int = 789
    actor_seat: int = 0
    batch_size: int = 32
    native_decision_limit: int = 1500
    episode_seconds: float = 30.
    learning_rate: float = .001
    gamma: float = .99
    gae_lambda: float = .95
    clip_ratio: float = .2
    value_weight: float = .5
    entropy_weight: float = .01
    grad_clip: float = .5
    lr_decay: float = .99
    game_seeds: tuple = (1724, 24)
    curriculum: str | None = None

    def __post_init__(self):
        if self.curriculum not in (None,"large-declaration"):
            raise ContractError("unsupported versioned CPU prompt curriculum")
        if not isinstance(self.model, DuelModelConfig):
            raise ContractError("training requires a bounded duel model configuration")
        integer(self.actor_seat, "actor seat", 0, 1)
        integer(self.batch_size, "CPU batch size", 1, 32)
        integer(self.native_decision_limit, "native decision limit", 1, 3000)
        for key in ("model_seed", "policy_seed", "batch_seed"):
            integer(getattr(self, key), key, 0, 2**32 - 8)
        for key in ("episode_seconds", "learning_rate", "gamma", "gae_lambda", "clip_ratio", "value_weight", "entropy_weight", "grad_clip", "lr_decay"):
            value = getattr(self, key)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ContractError("training values must be finite and positive")
        if (self.episode_seconds > 60 or self.learning_rate > .01 or self.clip_ratio >= 1
                or max(self.gamma, self.gae_lambda, self.lr_decay) > 1):
            raise ContractError("training configuration exceeds CPU proof budget")
        if not isinstance(self.game_seeds, tuple) or not 1 <= len(self.game_seeds) <= 100000:
            raise ContractError("CPU training requires 1..100000 declared game seeds")
        if len(set(self.game_seeds)) != len(self.game_seeds):
            raise ContractError("training game seeds must be unique")
        for seed in self.game_seeds:
            integer(seed, "game seed", 0, 2**32 - 8)


def config_from_dict(value):
    allowed = set(CpuTrainingConfig.__dataclass_fields__) | {"schema_version"}
    d = dict(fields(value, set(), allowed))
    integer(d.pop("schema_version", 1), "CPU training config schema", 1, 1)
    d["model"] = DuelModelConfig(**fields(d.get("model", {}), set(), set(DuelModelConfig.__dataclass_fields__)))
    if "game_seeds" in d:
        if not isinstance(d["game_seeds"], (list, tuple)):
            raise ContractError("game seeds must be an array")
        d["game_seeds"] = tuple(d["game_seeds"])
    return CpuTrainingConfig(**d)


def resource_binding(root, profile):
    receipt = verify_resources(root.resolve())
    implementation = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        implementation.update(path.name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return {"source_commits": receipt["source_commits"], "resources": receipt["resources"],
            "profile_sha256": hashlib.sha256(canonical_json(profile).encode()).hexdigest(),
            "python_implementation_sha256": implementation.hexdigest(),
            "python": platform.python_version(), "torch": str(torch.__version__), "feature_version": FEATURE_VERSION}


def cpu_name():
    if platform.system() == "Linux":
        try:
            with Path("/proc/cpuinfo").open() as info:
                for line in info:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or None


class CpuTrainer:
    def __init__(self, config, card_ids):
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        torch.manual_seed(config.model_seed)
        random.seed(config.model_seed)
        self.config, self.encoder = config, PlayerEncoder(card_ids, config.model)
        self.model = DuelActorCritic(config.model, len(card_ids)).to("cpu")
        self.optimizer = torch.optim.AdamW(self.model.parameters(), lr=config.learning_rate, weight_decay=0., foreach=False, fused=False)
        self.scheduler = torch.optim.lr_scheduler.StepLR(self.optimizer, step_size=1, gamma=config.lr_decay)
        self.policy_rng = torch.Generator(device="cpu").manual_seed(config.policy_seed)
        self.batch_rng = torch.Generator(device="cpu").manual_seed(config.batch_seed)
        self.updates, self.episode_cursor = 0, 0
        self._pending_episode_digest=None

    def sample_episode(self, root, profile, *, purpose="train", seed=None,
                       policy_seed=None, opponent="visible-effects-first-v1",opponent_adapter=None):
        if purpose not in ("train", "validation","final_eval") or opponent not in ("visible-effects-first-v1", "visible-effects-last-option-v1"):
            raise ContractError("unsupported sample purpose or fixed opponent")
        if opponent_adapter is not None:
            from .opponent_pool import FrozenOpponent
            if not isinstance(opponent_adapter,FrozenOpponent) or self.config.curriculum is not None:
                raise ContractError('registered opponents require their typed adapter and an unscripted sampler')
            opponent_adapter.assert_runtime(root,profile,self.config.actor_seat)
        if purpose == "train" and (seed is not None or policy_seed is not None):
            raise ContractError("training seed/RNG must come from the checkpoint cursor")
        if purpose == "train" and self.episode_cursor >= len(self.config.game_seeds):
            raise ContractError("declared engineering episode budget exhausted")
        cfg = self.config
        curriculum=cfg.curriculum
        policy_hash, version = parameter_digest(self.model), self.updates
        if purpose == "train":
            seed, sampler_rng = cfg.game_seeds[self.episode_cursor], self.policy_rng
        else:
            integer(seed, "held-out game seed", 0, 2**32 - 8)
            integer(policy_seed, "held-out policy seed", 0, 2**32 - 8)
            if seed in cfg.game_seeds:
                raise ContractError("validation seed overlaps training")
            sampler_rng = torch.Generator(device="cpu").manual_seed(policy_seed)
        # Seeds and opponent versions are controller metadata, never model features.
        steps, audit, latencies = [], [], []
        self.model.eval()
        started = time.monotonic()
        # Independent view randomness is private controller state; use the
        # checkpointed sampler stream rather than leaking the duel RNG rank.
        selection_key=None
        if profile.get('adapter_revision') in (4,5):
            words=torch.randint(0,2**63-1,(2,),generator=sampler_rng).tolist()
            selection_key=b''.join(w.to_bytes(8,'big') for w in words).hex()
        with NativeNormalEngine(root, scenario="effect-duel", deck_profile=profile, seed=seed,selection_key=selection_key) as engine:
            facts = public_card_facts(root)
            driver,assigned=(None,())
            if curriculum is not None:
                from .private_cases import prompt_curriculum
                driver,assigned=prompt_curriculum(curriculum,profile,engine._rows)
            request = engine.next_decision()
            while request is not None:
                if len(audit) >= cfg.native_decision_limit or time.monotonic() - started > cfg.episode_seconds:
                    raise NativeError("CPU sample budget exhausted; no terminal reward/update claimed")
                if request.observation.observer == cfg.actor_seat and (driver is None or request.prompt.message in assigned):
                    tick = time.perf_counter()
                    with torch.no_grad():
                        logits, values = score_requests(self.model,self.encoder,[request])
                        distribution = Categorical(logits=logits)
                        index, hierarchy = sample_index(logits[0],generator=sampler_rng,max_actions=cfg.model.max_actions)
                    action = request.actions[index]
                    steps.append({"request": request, "action_index": index,
                                  "old_log_prob": float(distribution.log_prob(torch.tensor([index]))[0]),
                                  "old_value": float(values[0]), "reward": 0., "hierarchy": hierarchy})
                    latencies.append((time.perf_counter() - tick) * 1000)
                else:
                    action = (opponent_adapter.policy.choose(request) if opponent_adapter is not None else
                              driver.choose(request,after_case=bool(steps)) if driver is not None else choose_effect_duel_action(request, facts))
                    if opponent_adapter is None and opponent == "visible-effects-last-option-v1" and request.prompt.message == 14:
                        action = request.actions[-1]
                audit.append({"player": request.observation.observer, "request_sha256": request_digest(request), "action_id": action.action_id})
                engine.submit(ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id))
                request = engine.next_decision()
            if engine.outcome is None or engine.events[-1]["kind"] != 5 or not steps:
                raise NativeError("CPU sample lacks actual core terminal result")
            winner = engine.outcome["winner"]
            reward = (1. if winner == cfg.actor_seat else -1.) if winner in (0, 1) else 0.
            steps[-1]["reward"] = reward
            summary = {"source": "live-core-actor-seat", "policy_version": version, "policy_sha256": policy_hash,
                       "purpose": purpose, "opponent": opponent if driver is None else "engineering-prefix-then-visible-normal-v1",
                       "seed_audit_only": seed, "actor_seat": cfg.actor_seat, "turns": engine.turn,
                       "native_decisions": len(audit), "actor_samples": len(steps), "outcome": engine.outcome,
                       "terminal_reward": reward, "elapsed_seconds": time.monotonic() - started,
                       "actor_inference_ms": latencies,
                       "trajectory_sha256": hashlib.sha256(canonical_json(audit).encode()).hexdigest()}
            if curriculum is not None:
                summary['curriculum']={'kind':'engineering-scripted-prefix-and-baseline-continuation',
                                       'case':curriculum,'policy_messages':list(assigned),'competitive_evaluation':False}
                summary['real_core_events_sha256']=hashlib.sha256(canonical_json(engine.events).encode()).hexdigest()
                summary['callback_errors']=len(engine.callback_errors)
            private_audit=None
            if opponent_adapter is not None:
                summary['opponent']='registered:'+opponent_adapter.binding['driver_version']
                summary['opponent_binding']=json.loads(canonical_json(opponent_adapter.binding))
                private_audit={'schema_version':1,'kind':'registered-opponent-private-replay-v1','name':'registered-opponent-engineering',
                               'profile':profile,'seed_audit_only':seed,'selection_key_audit_only':engine._selection_seed,
                               'resources':engine.receipt,'responses':audit,'events':engine.events,'outcome':engine.outcome,
                               'final_observations':[json.loads(canonical_json(asdict(engine._observation(p)))) for p in (0,1)],
                               'result':{'turns':engine.turn,'life_points':engine.life_points},'opponent_binding':summary['opponent_binding']}
        if purpose == "train":
            self.episode_cursor += 1
        episode={"source": "live-core-actor-seat", "policy_version": version, "policy_sha256": policy_hash,
                "purpose": purpose, "steps": steps, "summary": summary}
        if private_audit is not None:episode['_private_audit']=private_audit
        if purpose=='train':
            from .data_isolation import episode_digest
            self._pending_episode_digest=episode_digest(episode)
        return episode

    def update(self, episode):
        if episode.get("purpose") != "train" or episode["source"] != "live-core-actor-seat" or episode["policy_version"] != self.updates or episode["policy_sha256"] != parameter_digest(self.model):
            raise ContractError("PPO rejects stale/off-policy or non-live-core data")
        steps, cfg = episode["steps"], self.config
        if not steps or self.episode_cursor != self.updates + 1:
            raise ContractError("PPO requires one fresh complete episode per update")
        for step in steps:
            if 'hierarchy' in step:
                validate_receipt(step['hierarchy'],action_count=len(step['request'].actions),action_index=step['action_index'],
                                 old_log_prob=step['old_log_prob'],max_actions=cfg.model.max_actions)
            elif len(step['request'].actions)>cfg.model.max_actions:
                raise ContractError('large-action PPO requires its actual hierarchical sampling receipt')
        from .data_isolation import DataAdmission,episode_digest
        if getattr(self,'_pending_episode_digest',None)!=episode_digest(episode):
            raise ContractError('PPO episode is not the actual fresh training sample; held-out relabeling rejected')
        if '_data_admission' in episode:
            admission=episode['_data_admission']
            if not isinstance(admission,DataAdmission):raise ContractError('typed data admission required')
            admission.assert_episode(episode)
        advantages, following_value, gae = [], 0., 0.
        for step in reversed(steps):
            delta = step["reward"] + cfg.gamma * following_value - step["old_value"]
            gae = delta + cfg.gamma * cfg.gae_lambda * gae
            advantages.append(gae)
            following_value = step["old_value"]
        advantages = torch.tensor(list(reversed(advantages)), dtype=torch.float32)
        old_values = torch.tensor([s["old_value"] for s in steps])
        returns = advantages + old_values
        indices = torch.randperm(len(steps), generator=self.batch_rng)[:cfg.batch_size]
        chosen = [steps[i] for i in indices.tolist()]
        actions = torch.tensor([s["action_index"] for s in chosen])
        old_log_probs = torch.tensor([s["old_log_prob"] for s in chosen])
        advantage = advantages[indices]
        # Centering a single real decision would erase its entire reward
        # signal. Keep that raw advantage; multi-sample PPO retains scaling.
        if advantage.numel() > 1:
            advantage = (advantage - advantage.mean()) / (advantage.std(unbiased=False) + 1e-8)
        self.model.train()
        logits, values = score_requests(self.model,self.encoder,[s["request"] for s in chosen])
        dist = Categorical(logits=logits)
        ratio = (dist.log_prob(actions) - old_log_probs).exp()
        policy_loss = -torch.minimum(ratio * advantage, ratio.clamp(1 - cfg.clip_ratio, 1 + cfg.clip_ratio) * advantage).mean()
        value_loss = ((values - returns[indices]) ** 2).mean()
        entropy = dist.entropy().mean()
        loss = policy_loss + cfg.value_weight * value_loss - cfg.entropy_weight * entropy
        if not torch.isfinite(loss):
            raise ContractError("non-finite PPO loss; update refused")
        before = {name: p.detach().clone() for name, p in self.model.named_parameters()}
        self.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        grad_norm = float(torch.nn.utils.clip_grad_norm_(self.model.parameters(), cfg.grad_clip, error_if_nonfinite=True))
        self.optimizer.step()
        self.scheduler.step()
        changed = sum(int(torch.count_nonzero(before[n] != p.detach())) for n, p in self.model.named_parameters())
        delta = math.sqrt(sum(float(((before[n] - p.detach()) ** 2).sum()) for n, p in self.model.named_parameters()))
        head_delta = math.sqrt(sum(float(((before[n] - p.detach()) ** 2).sum()) for n, p in self.model.named_parameters() if n.startswith("policy_head")))
        self.updates += 1
        self._pending_episode_digest=None
        if not changed or not grad_norm or not delta:
            raise ContractError("no actual nonzero parameter update occurred")
        return {"optimizer_step": self.updates, "batch_samples": len(chosen), "episode_samples": len(steps),
                "loss": float(loss.detach()), "policy_loss": float(policy_loss.detach()), "value_loss": float(value_loss.detach()),
                "entropy": float(entropy.detach()), "gradient_norm_before_clip": grad_norm,
                "changed_parameter_elements": changed, "parameter_delta_l2": delta, "policy_head_delta_l2": head_delta,
                "before_sha256": episode["policy_sha256"], "after_sha256": parameter_digest(self.model),
                "learning_rate_next": self.optimizer.param_groups[0]["lr"]}


def save_checkpoint(trainer, directory, checkpoint_id, binding, *, allow_initial=False):
    identifier(checkpoint_id)
    initial = allow_initial is True and trainer.updates == trainer.episode_cursor == 0
    if not initial and (trainer.updates < 1 or trainer.episode_cursor != trainer.updates):
        raise ContractError("checkpoint requires an updated complete-episode boundary")
    path = directory / f"{checkpoint_id}.weights"
    state = {"schema_version": 1, "role": "duel", "boundary": "initial" if initial else "complete-episode", "config": asdict(trainer.config),
             "binding": binding, "card_ids": list(trainer.encoder.card_ids), "vocab_sha256": trainer.encoder.vocab_sha256,
             "model": trainer.model.state_dict(), "optimizer": trainer.optimizer.state_dict(), "scheduler": trainer.scheduler.state_dict(),
             "updates": trainer.updates, "episode_cursor": trainer.episode_cursor, "model_sha256": parameter_digest(trainer.model),
             "rng": {"torch": torch.get_rng_state(), "policy": trainer.policy_rng.get_state(),
                     "batch": trainer.batch_rng.get_state(), "python": random.getstate()}}
    directory.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        torch.save(state, output)
        output.flush()
        os.fsync(output.fileno())
    return path


def load_checkpoint(path, expected_binding, *, allow_initial=False):
    state = torch.load(path, map_location="cpu", weights_only=True)
    fields(state, {"schema_version", "role", "boundary", "config", "binding", "card_ids", "vocab_sha256", "model", "optimizer", "scheduler", "updates", "episode_cursor", "model_sha256", "rng"})
    initial = allow_initial is True and state["boundary"] == "initial" and state["updates"] == state["episode_cursor"] == 0
    if type(state["schema_version"]) is not int or state["schema_version"] != 1 or state["role"] != "duel" or (state["boundary"] != "complete-episode" and not initial) or state["binding"] != expected_binding:
        raise ContractError("checkpoint schema/boundary/resources differ")
    config = config_from_dict(state["config"])
    integer(state["updates"], "checkpoint updates", 0 if initial else 1, len(config.game_seeds))
    integer(state["episode_cursor"], "checkpoint episode cursor", 0 if initial else 1, len(config.game_seeds))
    if state["episode_cursor"] != state["updates"]:
        raise ContractError("checkpoint cursor/update boundary differs")
    trainer = CpuTrainer(config, state["card_ids"])
    trainer.model.load_state_dict(state["model"], strict=True)
    trainer.optimizer.load_state_dict(state["optimizer"])
    trainer.scheduler.load_state_dict(state["scheduler"])
    if trainer.encoder.vocab_sha256 != state["vocab_sha256"] or parameter_digest(trainer.model) != state["model_sha256"]:
        raise ContractError("checkpoint model/vocabulary checksum differs")
    trainer.updates, trainer.episode_cursor = state["updates"], state["episode_cursor"]
    torch.set_rng_state(state["rng"]["torch"])
    trainer.policy_rng.set_state(state["rng"]["policy"])
    trainer.batch_rng.set_state(state["rng"]["batch"])
    random.setstate(state["rng"]["python"])
    return trainer


def run_cpu_training_smoke(root, state_root, run_id, profile, config=None):
    identifier(run_id)
    root, state_root = Path(root).resolve(), Path(state_root).resolve()
    run = state_root / "runs" / run_id
    if run.exists():
        raise ContractError("training run already exists; choose a new run ID")
    cfg = config or CpuTrainingConfig()
    binding = resource_binding(root, profile)
    with sqlite3.connect((root / "engine-src/database/locales/zh-CN/cards.cdb").as_uri() + "?mode=ro", uri=True) as db:
        card_ids = [row[0] for row in db.execute("SELECT id FROM datas WHERE id>0 AND id<4294967296 ORDER BY id")]
    trainer = CpuTrainer(cfg, card_ids)
    reporter = RunReporter(state_root)
    base = {"schema_version": 1, "run_id": run_id, "state": "running", "revision": 0,
            "model_versions": {"duel": "cpu-duel-prototype-v1"}, "metrics": reporter.resources(), "checkpoint_ids": [], "source": "trainer"}
    reporter.publish(base)
    summaries, updates = [], []
    checkpoint_metadata = []

    def publish_progress(state):
        metrics = dict(reporter.resources(), steps=len(updates), episodes=len(summaries))
        if updates:
            metrics.update(loss=updates[-1]["loss"],
                           reward_mean=sum(s["terminal_reward"] for s in summaries) / len(summaries),
                           samples_per_second=sum(s["actor_samples"] for s in summaries) / metrics["elapsed_seconds"])
        revision = reporter.snapshot(run_id)["revision"] + 1
        reporter.publish(dict(base, state=state, revision=revision, metrics=metrics,
                              checkpoint_ids=[m["checkpoint_id"] for m in checkpoint_metadata]))
        return metrics

    def persist_update():
        step = trainer.updates
        checkpoint_id = f"step-{step}"
        path = save_checkpoint(trainer, run / "checkpoints", checkpoint_id, binding)
        metadata = {"schema_version": 1, "run_id": run_id, "checkpoint_id": checkpoint_id,
                    "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "artifact_bytes": path.stat().st_size, "step": step}
        path.with_suffix(".json").write_text(canonical_json(metadata) + "\n")
        checkpoint_metadata.append(metadata)
        publish_progress("running")
        RunMonitor(state_root).checkpoint(run_id, checkpoint_id)
        return path

    try:
        first = trainer.sample_episode(root, profile)
        summaries.append(first["summary"])
        updates.append(trainer.update(first))
        cp1 = persist_update()
        second = trainer.sample_episode(root, profile)
        summaries.append(second["summary"])
        updates.append(trainer.update(second))
        persist_update()
        expected = parameter_digest(trainer.model)
        recovered = load_checkpoint(cp1, binding)
        restored_episode = recovered.sample_episode(root, profile)
        restored_update = recovered.update(restored_episode)
        verified = (restored_episode["summary"]["trajectory_sha256"] == second["summary"]["trajectory_sha256"] and
                    parameter_digest(recovered.model) == expected and restored_update == updates[1])
        if not verified:
            raise ContractError("actual checkpoint continuation diverged")
        metrics = publish_progress("running")
        result = {"ok": True, "scope": "bounded-duel-only-cpu-engineering-training", "competitive_ability_validated": False,
                  "source": "real-core-on-policy-parameter-updates", "binding": binding, "model_config": asdict(cfg.model),
                  "training_config": asdict(cfg), "vocabulary_sha256": trainer.encoder.vocab_sha256,
                  "parameter_count": sum(p.numel() for p in trainer.model.parameters()), "device": "cpu", "cpu_threads": 1,
                  "hardware": {"platform": platform.platform(), "machine": platform.machine(), "processor": cpu_name(),
                               "logical_cpu_count": os.cpu_count(),
                               "cpu_affinity_count": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
                               "torch_cuda_build": torch.version.cuda},
                  "cost": {"new_paid_instances_started": 0, "external_api_calls": 0,
                           "cloud_development_cpu_cost": "not-exposed"},
                  "measurement_scope": "after-initial-model-optimizer-setup; includes recovery replay; RSS is process lifetime peak",
                  "episodes": summaries, "updates": updates, "canonical_updates": 2, "physical_optimizer_calls": 3,
                  "restore_verified": verified, "restored_second_trajectory_sha256": restored_episode["summary"]["trajectory_sha256"],
                  "checkpoints": checkpoint_metadata, "metrics": metrics, "models_in_this_run": ["duel"]}
        (run / "proof.json").write_text(canonical_json(result) + "\n")
        reporter.publish(dict(reporter.snapshot(run_id), state="completed",
                              revision=reporter.snapshot(run_id)["revision"] + 1))
        return result
    except Exception:
        publish_progress("failed")
        raise
