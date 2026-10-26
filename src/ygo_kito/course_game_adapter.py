"""Actual model/registered-bot games for the host-owned BO3 course state.

MatchState owns siding, loser choice and match completion. This module samples
one authorized small game, admits its actual data, and performs at most one
fresh PPO update. It never serializes through the legacy GroupState cursor,
drops an attached adapter, installs tools, or substitutes an opponent/engine.
"""
from collections import Counter
import copy
from dataclasses import asdict, dataclass, replace
import math
from pathlib import Path
import random
import time

import torch
from torch.nn.utils import parametrize

from .agent_registry import identifier
from .bot_deployment import BotSourceRegistry
from .build_contracts import DeckParts, digest
from .build_pipeline import BuildAssets
from .contracts import Versions
from .cpu_training import CpuTrainer, CpuTrainingConfig, config_from_dict as legacy_config_from_dict
from .data_isolation import DataIndex, episode_digest
from .deck_profile import validate_deck_parts, validate_profile
from .device import capture_device_rng, model_device
from .duel_model import FEATURE_VERSION, parameter_digest
from .implementation_identity import assert_source_tree, source_tree_snapshot
from .lora import AdapterSession
from .lora_group import ppo_inputs, ppo_loss
from .native import NativeNormalEngine
from .native_assets import verify_resources
from .period_runtime import PeriodBuildAssets, PeriodNativeEngine
from .training_pilot import _bytes, _check_qualification, _inside, _reference
from .validation import ContractError, fields, integer, member, parse_json, text
from .windbot_projection import WindBotOpponent

REAL_GAME_SOURCE = "live-core-neural-policy-registered-bot"


@dataclass(frozen=True)
class CourseTrainingConfig(CpuTrainingConfig):
    """New course-only 300s limit; the legacy CPU proof keeps its 60s cap."""
    def __post_init__(self):
        seconds = self.episode_seconds
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 300:
            raise ContractError("course episode limit must be finite and within (0,300]")
        # Validate every inherited field through the unchanged legacy rules.
        # This object is not published until construction completes.
        object.__setattr__(self, "episode_seconds", min(seconds, 60.))
        try: super().__post_init__()
        finally: object.__setattr__(self, "episode_seconds", seconds)


def course_config_from_dict(value):
    requested = value.get("episode_seconds", 30.) if isinstance(value, dict) else None
    if type(requested) not in (int, float) or not math.isfinite(requested) or not 0 < requested <= 300:
        raise ContractError("course episode limit must be finite and within (0,300]")
    legacy = legacy_config_from_dict(dict(value, episode_seconds=min(requested, 60.)))
    return CourseTrainingConfig(**dict(legacy.__dict__, episode_seconds=requested))


@dataclass(frozen=True)
class CourseBotRuntime:
    """Pinned host resources, never a callable/provider supplied by a client."""
    registry: BotSourceRegistry
    workspace: Path
    source_id: str
    executor_id: str
    audit: dict
    qualification: dict
    qualification_profile: dict
    mono: str
    opponent_id: str
    source: str = "user_provided"
    variant_root: Path | None = None
    session_seconds: float = 60.

    def __post_init__(self):
        if not isinstance(self.registry, BotSourceRegistry): raise ContractError("actual typed bot source registry required")
        root = Path(self.workspace).resolve(strict=True)
        object.__setattr__(self, "workspace", root)
        member(self.source_id, "desktop source", ("ice", "pure")); text(self.executor_id, "exact Executor")
        identifier(self.opponent_id)
        member(self.source, "bot deck source", ("engineering_fixture", "user_provided", "external_submission"))
        for reference in (self.audit, self.qualification, self.qualification_profile): _reference(reference)
        if not Path(text(self.mono, "explicit Mono path")).is_absolute(): raise ContractError("explicit absolute Mono required")
        if (type(self.session_seconds) not in (int, float) or not math.isfinite(self.session_seconds)
                or not 0 < self.session_seconds <= 300): raise ContractError("bot session cap must be within (0,300]")
        if self.variant_root is not None:
            if self.source_id != "pure": raise ContractError("desktop variant requires Pure")
            object.__setattr__(self, "variant_root", _inside(root, str(self.variant_root), directory=True))


class _FirstTurnObservation:
    def __init__(self, *args, course_observations, **kwargs):
        self._course_observations = course_observations
        course_observations["constructor_started"] = True
        super().__init__(*args, **kwargs)
        course_observations["constructor_completed"] = True

    def next_decision(self):
        request = super().next_decision()
        if request is not None:
            obs = request.observation
            self._course_observations["decision_windows"] += 1
            if self._course_observations["actual_first_core_seat"] is None and obs.turn == 1:
                self._course_observations["actual_first_core_seat"] = obs.turn_player
        return request


class _CourseNativeEngine(_FirstTurnObservation, NativeNormalEngine):
    pass


class _CoursePeriodEngine(_FirstTurnObservation, PeriodNativeEngine):
    pass


def _parts(profile, seat):
    return DeckParts(tuple(profile["decks"][seat]), tuple(profile.get("extras", [[], []])[seat]),
                     tuple(profile.get("sides", [[], []])[seat]))


class CourseGameAdapter:
    """A host callable ``GameSpec -> GameResult`` using actual model objects.

    ``last_episode`` and ``last_receipt`` are private host artifacts, not match
    public views or policy inputs. A failed update is reported with observed
    before/after model and update cursor; the course owner decides rollback.
    """
    def __init__(self, *, assets, match_state, actor_participant_id, trainer, bot_runtime,
                 data_index, experiment_id, purpose, config=None, adapter_session=None,
                 policy_rng=None, evaluation_pairs=(), evaluation_cursor=0):
        from .match_runner import MatchState
        if not isinstance(assets, BuildAssets) or not isinstance(match_state, MatchState):
            raise ContractError("typed rule assets and authorized MatchState required")
        if not isinstance(trainer, CpuTrainer) or not isinstance(bot_runtime, CourseBotRuntime) or not isinstance(data_index, DataIndex):
            raise ContractError("actual trainer, bot runtime and data index required")
        identifier(actor_participant_id); identifier(experiment_id)
        member(purpose, "course partition", ("train", "validation", "final_eval"))
        cfg = trainer.config if config is None else config
        if not isinstance(cfg, CpuTrainingConfig) or cfg.curriculum is not None:
            raise ContractError("explicit unscripted course training configuration required")
        if cfg.model != trainer.model.config or cfg.model != trainer.encoder.config:
            raise ContractError("course feature/model configuration differs from actual actor")
        if adapter_session is not None:
            if (not isinstance(adapter_session, AdapterSession) or adapter_session.config.role != "duel" or
                    adapter_session.model is not trainer.model or adapter_session.detached or not adapter_session.enabled or
                    adapter_session.binding["feature_version"] != FEATURE_VERSION):
                raise ContractError("same actual enabled duel LoRA session required")
            adapter_session.verify_base()
        elif any(parametrize.is_parametrized(m) for m in trainer.model.modules()):
            raise ContractError("attached LoRA must be supplied explicitly, never silently discarded")
        elif {k: v for k, v in asdict(trainer.config).items() if k != "actor_seat"} != {
                k: v for k, v in asdict(cfg).items() if k != "actor_seat"}:
            raise ContractError("base PPO trainer must own the complete saved course config/seeds")
        if purpose != "train" and not evaluation_pairs:
            raise ContractError("held-out games require an explicit private seed/policy schedule")
        seen = set()
        for pair in evaluation_pairs:
            if not isinstance(pair, tuple) or len(pair) != 2: raise ContractError("evaluation seed pairs must be tuples")
            for value in pair: integer(value, "held-out seed", 0, 2**32 - 8)
            if pair[0] in cfg.game_seeds or pair[0] in seen: raise ContractError("held-out seed overlaps training or another held-out game")
            seen.add(pair[0])
        integer(evaluation_cursor, "held-out cursor", 0, len(evaluation_pairs))
        actual_rng = trainer.policy_rng if policy_rng is None else policy_rng
        if not isinstance(actual_rng, torch.Generator) or actual_rng.device.type != "cpu":
            raise ContractError("checkpointed CPU sampling generator required")
        self.assets, self.match_state, self.actor_id = assets, match_state, actor_participant_id
        self.trainer, self.session, self.config, self.policy_rng = trainer, adapter_session, cfg, actual_rng
        self.bot, self.data_index, self.experiment_id, self.purpose = bot_runtime, data_index, experiment_id, purpose
        self._registry_object = bot_runtime.registry
        self._bot_seal = self._bot_identity()
        self.evaluation_pairs, self.evaluation_cursor = tuple(evaluation_pairs), evaluation_cursor
        self.last_receipt = self.last_episode = None
        self._actor_objects = (trainer.model, trainer.encoder, adapter_session, actual_rng)
        self._used_specs = set()
        self._config_sha256 = digest(asdict(cfg))
        self._source_map = source_tree_snapshot(Path(__file__).resolve().parent)
        originals = match_state.original_participants
        if len(originals) != 2 or actor_participant_id not in {p.participant_id for p in originals}:
            raise ContractError("course actor is absent from the actual match")
        self._originals = {p.participant_id: p.deck for p in originals}
        self.bot_id = next(p for p in self._originals if p != actor_participant_id)
        self._bind_original_qualification()

    def _bot_identity(self):
        b = self.bot
        return digest({"source": b.source_id, "executor": b.executor_id, "opponent_id": b.opponent_id,
            "registry_lock": b.registry.lock, "inventory": b.registry.inventory["inventory_sha256"],
            "workspace": str(b.workspace), "audit": b.audit, "qualification": b.qualification,
            "qualification_profile": b.qualification_profile, "mono": b.mono, "source_label": b.source,
            "variant_root": None if b.variant_root is None else str(b.variant_root), "session_seconds": b.session_seconds})

    @classmethod
    def from_group(cls, state, **options):
        """Extract the live effective model/session, not legacy saved base bytes."""
        from .group_runner import GroupState
        if not isinstance(state, GroupState) or not state.sessions or "duel" not in state.sessions:
            raise ContractError("actual adapted group required")
        if "trainer" in options or "adapter_session" in options:
            raise ContractError("group actor/session cannot be replaced")
        options.setdefault("policy_rng", state.policy_rng)
        return cls(trainer=state.duel, adapter_session=state.sessions["duel"], **options)

    def _runtime_options(self, profile, actor_seat, *, qualification=False):
        audit_path, _ = _bytes(self.bot.workspace, self.bot.audit)
        if qualification or not isinstance(self.assets, PeriodBuildAssets):
            h = self.assets.receipt["resources"]
            revision = profile.get("adapter_revision")
            pools = {3: "native-protocol-history-v3", 4: "native-private-selection-v4", 5: "native-private-knowledge-v5"}
            if revision not in pools: raise ContractError("course needs explicit modern legal observations")
            versions = Versions(self.assets.receipt["source_commits"]["core"], h["scripts"], h["cards"],
                h["client_protocol"], pools[revision], "2026.10:" + h["banlist"])
            context = None
        else:
            versions = Versions.from_dict(self.assets.environment["versions"])
            context = self.assets.period_context
        return dict(source_id=self.bot.source_id, native_root=self.assets.root, profile=profile, seat=1-actor_seat,
            versions=versions, environment_id="course" if qualification else self.assets.environment["environment_id"],
            opponent_id=self.bot.opponent_id, source=self.bot.source, build_audit_path=audit_path,
            build_audit_sha256=self.bot.audit["sha256"], mono=self.bot.mono, workspace=self.bot.workspace,
            period_context=context, variant_root=self.bot.variant_root, session_seconds=self.bot.session_seconds)

    def _bind_original_qualification(self):
        _, profile_raw = _bytes(self.bot.workspace, self.bot.qualification_profile)
        _, qualification_raw = _bytes(self.bot.workspace, self.bot.qualification)
        profile, proof = parse_json(profile_raw.decode("utf-8")), parse_json(qualification_raw.decode("utf-8"))
        validate_profile(profile)
        actor_seat = integer(proof.get("actor_seat"), "qualification actor seat", 0, 1)
        original = self._originals[self.bot_id]
        qualified = _parts(profile, 1-actor_seat)
        if any(Counter(getattr(original, z)) != Counter(getattr(qualified, z)) for z in ("main", "extra", "side")):
            raise ContractError("original bot deck differs from its actually qualified listing")
        options = self._runtime_options(profile, actor_seat, qualification=True)
        opponent = self.bot.registry.training_adapter(self.bot.executor_id, **options)
        case = {"source_id": self.bot.source_id, "executor_id": self.bot.executor_id,
                "actor_seat": actor_seat, "qualification": self.bot.qualification}
        if self.bot.variant_root is not None: case["variant"] = True
        _check_qualification(self.bot.workspace, case, profile, self.bot.registry, opponent,
                             dict(options, receipt=self.assets.receipt))
        self._qualification_sha256 = self.bot.qualification["sha256"]

    def _validate_profile(self, spec):
        profile = spec.profile()
        if isinstance(self.assets, PeriodBuildAssets): profile = self.assets.validate_profile(profile)
        else:
            validate_profile(profile)
            for seat in (0, 1): validate_deck_parts(_parts(profile, seat).to_dict(), self.assets.rows, self.assets.limits)
        for participant in spec.participants:
            before, after = self._originals[participant.participant_id], participant.deck
            if (any(len(getattr(before, z)) != len(getattr(after, z)) for z in ("main", "extra", "side")) or
                    Counter(before.main+before.extra+before.side) != Counter(after.main+after.extra+after.side)):
                raise ContractError("game spec does not preserve this match's original card inventory and sizes")
        if any(code not in self.trainer.encoder.index for p in spec.participants for z in ("main", "extra", "side")
               for code in getattr(p.deck, z)):
            raise ContractError("course card is absent from the actual actor vocabulary")
        return profile

    def training_fingerprint(self):
        """Actual weights/optimizers/RNG/cursors, excluding held-out scheduling."""
        from .group_runner import tree_digest
        t = self.trainer
        return tree_digest({"model": t.model.state_dict(), "optimizer": t.optimizer.state_dict(),
            "scheduler": t.scheduler.state_dict(), "trainer_cursor": (t.updates, t.episode_cursor),
            "pending": getattr(t, "_pending_episode_digest", None), "trainer_policy_rng": t.policy_rng.get_state(),
            "policy_rng": self.policy_rng.get_state(), "batch_rng": t.batch_rng.get_state(),
            "adapter": None if self.session is None else self.session.state(),
            "global_rng": capture_device_rng(model_device(t.model)), "python_rng": random.getstate(),
            "module_modes": [m.training for m in t.model.modules()]})

    def state_metadata(self):
        optimizer = self.trainer.optimizer if self.session is None else self.session.optimizer
        steps = [float(v["step"]) for v in optimizer.state.values() if "step" in v]
        return {"schema_version": 1, "kind": "course-live-game-adapter", "purpose": self.purpose,
            "device": str(model_device(self.trainer.model)), "feature_version": FEATURE_VERSION,
            "model_sha256": parameter_digest(self.trainer.model), "vocab_sha256": self.trainer.encoder.vocab_sha256,
            "lora": None if self.session is None else {"version": self.session.version_id(),
                "base_sha256": self.session.verify_base(), "updates": self.session.updates, "enabled": self.session.enabled},
            "training_cursor": self.trainer.episode_cursor if self.session is None else self.session.updates,
            "observed_optimizer_step_max": max(steps, default=0),
            "evaluation_cursor": self.evaluation_cursor, "config_sha256": self._config_sha256,
            "qualification_sha256": self._qualification_sha256, "source_map_sha256": digest(self._source_map),
            "original_bot_deck_sha256": digest(self._originals[self.bot_id].to_dict())}

    def _index(self, spec, episode):
        binding = episode["summary"]["opponent_binding"]
        dataset_id = "course-" + self.purpose + "-" + digest(binding)[:24]
        artifact_id = "game-" + digest([self.experiment_id, spec.match_id, spec.game_number, self.purpose])[:40]
        self.data_index.freeze({"dataset_id": dataset_id, "experiment_id": self.experiment_id, "purpose": self.purpose,
            "family": "duel", "versions": episode["steps"][0]["request"].context.to_dict()["versions"],
            "opponents": [binding], "task_sha256": None})
        self.data_index.ingest_episode(dataset_id, artifact_id, episode)
        if self.purpose == "train": self.data_index.admit_episode(artifact_id, episode)
        return {"dataset_id": dataset_id, "artifact_id": artifact_id, "episode_sha256": episode_digest(episode)}

    def __call__(self, spec):
        from .match_runner import GameSpec, GameResult
        if not isinstance(spec, GameSpec): raise ContractError("typed authorized game spec required")
        self.match_state.assert_game_spec(spec)
        key = (spec.match_id, spec.game_number)
        if key in self._used_specs: raise ContractError("small game already attempted; no implicit replay")
        self._used_specs.add(key)
        before = self.state_metadata()
        record = self.last_receipt = {"kind": "course-small-game-host-receipt", "status": "started", "before": before,
            "match_id": spec.match_id, "game_number": spec.game_number, "partition": self.purpose,
            "model_update_started": False, "model_update_completed": False, "sample_completed": False,
            "formal_match_completion_claimed": False}
        self.last_episode = None
        watched = {"constructor_started": False, "constructor_completed": False,
                   "actual_first_core_seat": None, "decision_windows": 0}
        started = time.monotonic(); elapsed = None; native_decisions = 0; result_winner = None
        fingerprint = self.training_fingerprint() if self.purpose != "train" else None
        modes = [(m, m.training) for m in self.trainer.model.modules()]
        anomaly = None; current = None
        try:
            assert_source_tree(Path(__file__).resolve().parent, self._source_map)
            if (self.trainer.model, self.trainer.encoder, self.session, self.policy_rng) != self._actor_objects:
                raise ContractError("course actor objects changed after binding")
            if self.bot.registry is not self._registry_object or self._bot_identity() != self._bot_seal:
                raise ContractError("course bot source/Executor/audit configuration changed")
            if digest(asdict(self.config)) != self._config_sha256: raise ContractError("course config changed")
            for reference in (self.bot.audit, self.bot.qualification, self.bot.qualification_profile): _bytes(self.bot.workspace, reference)
            if isinstance(self.assets, PeriodBuildAssets): self.assets.assert_integrity()
            elif verify_resources(self.assets.root) != self.assets.receipt: raise ContractError("course native resources changed")
            if self.session is not None:
                self.session.verify_base()
                if self.session.model is not self.trainer.model or not self.session.enabled or self.session.detached:
                    raise ContractError("effective actor adapter changed")
            profile = self._validate_profile(spec); seat = spec.seat_of(self.actor_id)
            opponent = self.bot.registry.training_adapter(self.bot.executor_id, **self._runtime_options(profile, seat))
            if not isinstance(opponent, WindBotOpponent): raise ContractError("actual audited typed bot required")
            opponent.assert_runtime(self.assets.root, profile, seat)
            current = copy.copy(self.trainer)
            current.config = replace(self.config, actor_seat=seat)
            current.policy_rng = self.policy_rng
            if self.session is not None: current.updates = current.episode_cursor = self.session.updates
            def factory(root, **options):
                if Path(root).resolve() != self.assets.root: raise ContractError("course engine root changed")
                if isinstance(self.assets, PeriodBuildAssets):
                    return _CoursePeriodEngine(self.assets, course_observations=watched, **options)
                return _CourseNativeEngine(root, course_observations=watched, **options)
            kwargs = {}
            if self.purpose != "train":
                if self.evaluation_cursor >= len(self.evaluation_pairs): raise ContractError("held-out schedule exhausted")
                kwargs["seed"], kwargs["policy_seed"] = self.evaluation_pairs[self.evaluation_cursor]
            episode = current.sample_episode(self.assets.root, profile, purpose=self.purpose,
                opponent_adapter=opponent, engine_factory=factory, **kwargs)
            self.last_episode = episode; record["sample_completed"] = True
            summary = episode["summary"]; native_decisions = summary["native_decisions"]
            elapsed = summary["elapsed_seconds"]
            if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed <= 0:
                raise ContractError("small game lacks actual positive sampler timing")
            if watched["actual_first_core_seat"] != 0:
                raise ContractError("selected-first participant not confirmed by public turn1 core observation")
            result_winner = summary["outcome"]["winner"]
            record.update(actor_core_seat=seat, seat_order=list(spec.seat_order), profile_sha256=digest(profile),
                opponent_binding=copy.deepcopy(opponent.binding), trajectory_sha256=summary["trajectory_sha256"],
                sample_policy_sha256=episode["policy_sha256"], sample_policy_version=episode["policy_version"])
            record["data"] = self._index(spec, episode)
            if self.purpose == "train":
                record["model_update_started"] = True
                if self.session is None:
                    update = current.update(episode)
                    self.trainer.updates, self.trainer.episode_cursor = current.updates, current.episode_cursor
                    self.trainer._pending_episode_digest = current._pending_episode_digest
                else:
                    if episode["policy_version"] != self.session.updates:
                        raise ContractError("course LoRA requires this small game's fresh policy version")
                    values = ppo_inputs(episode, current, self.session)
                    update = self.session.step(ppo_loss(self.session, values, current.config))
                record.update(model_update_completed=True, update=update)
            else: self.evaluation_cursor += 1
            record["status"] = "completed"
        except (ContractError, OSError, ValueError, KeyError, TypeError, RuntimeError, KeyboardInterrupt) as error:
            anomaly = type(error).__name__
            record.update(status="failed_or_uncertain", error={"type": anomaly, "message": str(error)}, retry_allowed=False)
        finally:
            if current is not None:
                record["observed_sampler_cursor"] = current.episode_cursor
                record["observed_sampler_updates"] = current.updates
                if self.session is None and record["model_update_started"]:
                    # The optimizer is shared with the actual trainer. Even if
                    # a post-step check failed, retain observed counters instead
                    # of describing changed weights as an unexecuted update.
                    self.trainer.updates, self.trainer.episode_cursor = current.updates, current.episode_cursor
                    self.trainer._pending_episode_digest = getattr(current, "_pending_episode_digest", None)
            if self.purpose != "train":
                for module, mode in modes: module.training = mode
                unchanged = self.training_fingerprint() == fingerprint
                record["frozen_training_state_unchanged"] = unchanged
                if not unchanged:
                    anomaly = "frozen_training_state_changed"; record["status"] = "failed_or_uncertain"
            record.update(after=self.state_metadata(), observations=dict(watched), wall_seconds=time.monotonic()-started)
        return GameResult(game_number=spec.game_number, winner_core_seat=result_winner if anomaly is None else None,
            actual_first_core_seat=watched["actual_first_core_seat"], terminal=anomaly is None,
            evidence_source=REAL_GAME_SOURCE, elapsed_seconds=elapsed if elapsed is not None else record["wall_seconds"],
            native_decisions=native_decisions, anomaly=anomaly)
