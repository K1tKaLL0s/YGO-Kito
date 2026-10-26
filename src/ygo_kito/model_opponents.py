"""Frozen CPU neural opponents captured from actual project models.

An initial network is an explicit engineering opponent, never pretrained ability.
Only public vocabulary, model configuration and independent effective weights
reach its policy. Resources, source provenance, decks and seeds stay with hosts.
This inference format does not relax any existing training-checkpoint loader.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import io
from pathlib import Path
import pickle
import re

import torch
from torch.nn.utils import parametrize

from .agent_registry import identifier
from .build_contracts import DeckParts, digest
from .build_pipeline import BuildAssets
from .contracts import ActionSelection, Versions, validate_selection
from .cpu_training import CpuTrainer
from .deck_profile import validate_deck_parts, validate_profile
from .device import model_device
from .duel_model import DuelActorCritic, DuelModelConfig, FEATURE_VERSION, PlayerEncoder, parameter_digest
from .implementation_identity import assert_source_tree, source_tree_snapshot
from .lora import AdapterSession
from .native_assets import verify_resources
from .opponent_pool import FrozenOpponent, PublicSnapshotPolicy
from .period_runtime import PeriodBuildAssets
from .validation import ContractError, fields, integer, member, text

KIND = "frozen-effective-duel-inference-v1"
# One isolation family across greedy/sampling choices. A changed RNG, label or
# mode cannot turn the same weights/deck into an independent held-out opponent.
DRIVER = "frozen-effective-duel-neural-policy-v1"


def _tree(value):
    from .group_runner import tree_digest
    return tree_digest(value)


def _sha(value, label):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ContractError(label + " requires lowercase SHA256")
    return value


def _resources(assets):
    if not isinstance(assets, BuildAssets): raise ContractError("actual typed native assets required")
    if isinstance(assets, PeriodBuildAssets): assets.assert_integrity()
    elif verify_resources(assets.root) != assets.receipt: raise ContractError("model opponent native resources changed")
    return deepcopy({k: assets.receipt[k] for k in ("resources", "source_commits")})


def _versions(assets, revision=5):
    if isinstance(assets, PeriodBuildAssets): return Versions.from_dict(assets.environment["versions"])
    pools = {3: "native-protocol-history-v3", 4: "native-private-selection-v4", 5: "native-private-knowledge-v5"}
    if revision not in pools: raise ContractError("model opponent requires modern legal observations")
    r = assets.receipt["resources"]
    return Versions(assets.receipt["source_commits"]["core"], r["scripts"], r["cards"],
        r["client_protocol"], pools[revision], "2026.10:" + r["banlist"])


def _path(workspace, value):
    root = Path(workspace).resolve(strict=True)
    path = (root / value).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ContractError("model snapshot must stay within its explicit workspace")
    return path


def _network(config, cards, weights):
    # Initializing a validation/inference object must not consume learner RNG.
    with torch.random.fork_rng(devices=[]): model = DuelActorCritic(config, len(cards)).to("cpu")
    template = model.state_dict()
    if not isinstance(weights, dict) or set(weights) != set(template):
        raise ContractError("snapshot model parameter names differ")
    for name, tensor in weights.items():
        if (not isinstance(tensor, torch.Tensor) or tensor.device.type != "cpu" or
                tensor.dtype != torch.float32 or tensor.layout != torch.strided or
                tensor.shape != template[name].shape or not torch.isfinite(tensor).all()):
            raise ContractError("snapshot model shape/device/dtype/finite check failed")
    model.load_state_dict(weights, strict=True)
    model.eval(); model.requires_grad_(False)
    return model


class FrozenDuelSnapshot:
    """Independent, checksummed inference weights; no optimizer or game secrets."""
    def __init__(self, state):
        d = fields(state, {"schema_version", "kind", "feature_version", "model_config", "card_ids",
            "vocab_sha256", "model", "model_sha256", "provenance", "state_sha256"})
        if (type(d["schema_version"]) is not int or d["schema_version"] != 1 or d["kind"] != KIND or
                d["feature_version"] != FEATURE_VERSION): raise ContractError("snapshot schema/features differ")
        cfg = DuelModelConfig(**fields(d["model_config"], set(DuelModelConfig.__dataclass_fields__)))
        if not isinstance(d["card_ids"], list): raise ContractError("snapshot public vocabulary must be an array")
        encoder = PlayerEncoder(d["card_ids"], cfg)
        if encoder.vocab_sha256 != d["vocab_sha256"]: raise ContractError("snapshot vocabulary checksum differs")
        p = fields(d["provenance"], {"source_label", "source_binding_sha256", "resources", "period_context",
            "source_versions", "source_model_sha256", "base_sha256", "adapter", "base_updates", "base_episodes",
            "source_stage", "materialization", "ability_verified"})
        text(p["source_label"], "snapshot source label")
        if len(p["source_label"]) > 512: raise ContractError("snapshot source label exceeds bound")
        for k in ("source_binding_sha256", "source_model_sha256", "base_sha256"): _sha(p[k], k)
        fields(p["resources"], {"resources", "source_commits"})
        source_v = Versions.from_dict(p["source_versions"])
        r = p["resources"]["resources"]
        if (not isinstance(r, dict) or not isinstance(p["resources"]["source_commits"], dict) or
                any(not isinstance(r.get(k), str) or not r[k] for k in ("scripts", "cards", "client_protocol", "banlist"))):
            raise ContractError("snapshot pinned resource metadata differs")
        if (source_v.core != p["resources"]["source_commits"].get("core") or source_v.scripts != r.get("scripts") or
                source_v.cards != r.get("cards") or source_v.protocol != r.get("client_protocol") or
                not source_v.banlist.endswith(":" + r.get("banlist", ""))):
            raise ContractError("snapshot source versions differ from its pinned resources")
        integer(p["base_updates"], "source base updates", 0, 100000)
        integer(p["base_episodes"], "source base completed episodes", p["base_updates"], p["base_updates"])
        member(p["source_stage"], "snapshot source stage", ("engineering_initial", "updated_weights"))
        if p["ability_verified"] is not False: raise ContractError("snapshot cannot certify model ability")
        if p["period_context"] is not None:
            from .group_initialization import _context
            context = p["period_context"]
            if not isinstance(context, dict): raise ContractError("snapshot source period context must be an object")
            _context(context, {"release_cutoff": context.get("release_cutoff"), "versions": p["source_versions"]})
        adapter = p["adapter"]
        if adapter is not None:
            fields(adapter, {"version", "base_sha256", "config_sha256", "updates"})
            for k in ("version", "base_sha256", "config_sha256"): _sha(adapter[k], "source adapter " + k)
            integer(adapter["updates"], "source adapter updates", 0, 10000)
            if adapter["base_sha256"] != p["base_sha256"]: raise ContractError("snapshot source adapter base differs")
        updates = p["base_updates"] + (0 if adapter is None else adapter["updates"])
        if p["source_stage"] != ("engineering_initial" if updates == 0 else "updated_weights"):
            raise ContractError("snapshot initial/updated provenance differs from actual counters")
        if p["materialization"] != ("exact-effective-lora-to-cpu" if adapter is not None else "exact-base-to-cpu"):
            raise ContractError("snapshot weight selection is not explicit")
        _sha(d["model_sha256"], "snapshot model"); _sha(d["state_sha256"], "snapshot state")
        if _tree({k: v for k, v in d.items() if k != "state_sha256"}) != d["state_sha256"]:
            raise ContractError("snapshot state checksum differs")
        model = _network(cfg, d["card_ids"], d["model"])
        if parameter_digest(model) != d["model_sha256"]: raise ContractError("snapshot model checksum differs")
        self._state = deepcopy(d)
        self._seal = d["state_sha256"]

    @classmethod
    def capture(cls, trainer, *, assets, adapter_session=None, source_binding, source_label):
        if not isinstance(trainer, CpuTrainer): raise ContractError("actual project duel trainer required")
        if not isinstance(source_binding, dict) or not source_binding: raise ContractError("explicit host source binding required")
        text(source_label, "snapshot source label")
        if model_device(trainer.model).type != "cpu": raise ContractError("self-play snapshot capture is CPU only")
        if trainer.config.model != trainer.model.config or trainer.config.model != trainer.encoder.config:
            raise ContractError("source actual model/encoder config differs")
        encoder = PlayerEncoder(list(trainer.encoder.card_ids), trainer.config.model)
        if encoder.index != trainer.encoder.index or encoder.vocab_sha256 != trainer.encoder.vocab_sha256:
            raise ContractError("source public vocabulary mapping changed")
        if getattr(trainer, "_pending_episode_digest", None) is not None or trainer.updates != trainer.episode_cursor:
            raise ContractError("snapshot requires initial or completed-update source boundary")
        resources = _resources(assets)
        if not {i for i in assets.rows if 0 < i < 2**32} <= set(encoder.card_ids):
            raise ContractError("snapshot public vocabulary does not cover the pinned catalogue")
        source_hash = parameter_digest(trainer.model)
        layers = {n for n, m in trainer.model.named_modules() if parametrize.is_parametrized(m)}
        adapter = None
        if adapter_session is None:
            if layers: raise ContractError("actual attached LoRA must be supplied explicitly")
            base = source_hash
            weights = {k: v.detach().cpu().clone() for k, v in trainer.model.state_dict().items()}
        else:
            s = adapter_session
            if (not isinstance(s, AdapterSession) or s.model is not trainer.model or s.config.role != "duel" or
                    s.detached or not s.enabled or s.binding["feature_version"] != FEATURE_VERSION or
                    layers != set(s.config.targets) or any(set(m.parametrizations) != {"weight"}
                        for m in s.layers.values())): raise ContractError("same actual enabled duel LoRA required")
            base = s.verify_base()
            weights = {k: v.detach().cpu().clone() for k, v in trainer.model.state_dict().items()
                if ".parametrizations." not in k}
            # Read the actual effective Linear.weight, without suspending or
            # modifying the learner's parametrization, modes, gradients or RNG.
            for name, layer in s.layers.items(): weights[name + ".weight"] = layer.weight.detach().cpu().clone()
            adapter = {"version": s.version_id(), "base_sha256": base, "config_sha256": digest(s.config.to_dict()),
                "updates": s.updates}
        model = _network(trainer.config.model, encoder.card_ids, weights)
        provenance = {"source_label": source_label, "source_binding_sha256": digest(source_binding),
            "resources": resources, "period_context": deepcopy(getattr(assets, "period_context", None)),
            "source_versions": asdict(_versions(assets)), "source_model_sha256": source_hash, "base_sha256": base,
            "adapter": adapter, "base_updates": trainer.updates, "base_episodes": trainer.episode_cursor,
            "source_stage": "engineering_initial" if trainer.updates + (0 if adapter is None else adapter["updates"]) == 0 else "updated_weights",
            "materialization": "exact-base-to-cpu" if adapter is None else "exact-effective-lora-to-cpu", "ability_verified": False}
        state = {"schema_version": 1, "kind": KIND, "feature_version": FEATURE_VERSION,
            "model_config": asdict(trainer.config.model), "card_ids": list(encoder.card_ids), "vocab_sha256": encoder.vocab_sha256,
            "model": weights, "model_sha256": parameter_digest(model), "provenance": provenance}
        state["state_sha256"] = _tree(state)
        return cls(state)

    @classmethod
    def from_state(cls, state): return cls(state)

    def assert_integrity(self):
        if self._state.get("state_sha256") != self._seal or _tree({k: v for k, v in self._state.items() if k != "state_sha256"}) != self._seal:
            raise ContractError("frozen snapshot content changed")

    def to_state(self):
        self.assert_integrity()
        return deepcopy(self._state)

    def identity(self):
        self.assert_integrity()
        return {k: deepcopy(self._state[k]) for k in ("kind", "feature_version", "state_sha256", "model_sha256", "vocab_sha256", "provenance")}

    def save(self, workspace, path):
        destination = _path(workspace, path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output: torch.save(self.to_state(), output)
        return {"path": str(destination.relative_to(Path(workspace).resolve())),
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}

    @classmethod
    def load(cls, workspace, path, sha256):
        _sha(sha256, "snapshot artifact")
        source = _path(workspace, path)
        try:
            raw = source.read_bytes()
            if hashlib.sha256(raw).hexdigest() != sha256: raise ContractError("snapshot artifact checksum differs")
            state = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
            return cls.from_state(state)
        except (OSError, EOFError, pickle.UnpicklingError, RuntimeError, TypeError, KeyError) as error:
            raise ContractError("snapshot artifact cannot be loaded") from error


class SamplingSnapshotPolicy(PublicSnapshotPolicy):
    """Exact NN-distribution sampling; RNG is private controller state only."""
    def __init__(self, seat, versions, state, *, snapshot_sha256, policy_rng):
        if not isinstance(policy_rng, torch.Generator) or policy_rng.device.type != "cpu":
            raise ContractError("sampled model policy requires an owned CPU generator")
        super().__init__(seat, versions, state)
        self.policy_rng, self.snapshot_sha256, self.decisions = policy_rng, snapshot_sha256, 0

    def choose(self, request):
        from .hierarchical_policy import score_requests, sample_index
        if request.observation.observer != self.seat or request.context.seed is not None or request.context.versions != self.versions:
            raise ContractError("sampled snapshot opponent seat/version boundary differs")
        with torch.no_grad():
            logits, _ = score_requests(self.model, self.encoder, [request])
            index, _ = sample_index(logits[0], generator=self.policy_rng, max_actions=self.encoder.config.max_actions)
        action = request.actions[index]
        validate_selection(request, ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id))
        self.decisions += 1
        return action

    def sampling_state(self):
        """Host-only complete boundary state, never a DecisionRequest feature."""
        return {"schema_version": 1, "snapshot_sha256": self.snapshot_sha256, "model_sha256": self.model_sha256,
            "policy_mode": "sample", "rng_state": self.policy_rng.get_state().tolist(), "decisions": self.decisions}

    def restore_sampling_state(self, state):
        d = fields(state, {"schema_version", "snapshot_sha256", "model_sha256", "policy_mode", "rng_state", "decisions"})
        if (type(d["schema_version"]) is not int or d["schema_version"] != 1 or d["snapshot_sha256"] != self.snapshot_sha256 or
                d["model_sha256"] != self.model_sha256 or d["policy_mode"] != "sample"):
            raise ContractError("sampled policy state belongs to another snapshot/mode")
        integer(d["decisions"], "sampled policy decision count", 0, 100000)
        if (not isinstance(d["rng_state"], list) or len(d["rng_state"]) != len(self.policy_rng.get_state()) or
                any(type(x) is not int or not 0 <= x <= 255 for x in d["rng_state"])):
            raise ContractError("sampled policy RNG byte state differs")
        value = torch.tensor(d["rng_state"], dtype=torch.uint8)
        try: torch.Generator(device="cpu").set_state(value)
        except RuntimeError as error: raise ContractError("sampled policy RNG state is invalid") from error
        self.policy_rng.set_state(value); self.decisions = d["decisions"]


@dataclass(frozen=True)
class ModelOpponentRuntime:
    snapshot: FrozenDuelSnapshot
    opponent_id: str
    source: str = "engineering_fixture"
    migration: str = "same-period-inference"
    policy_mode: str = "greedy"

    def __post_init__(self):
        if not isinstance(self.snapshot, FrozenDuelSnapshot): raise ContractError("typed frozen neural snapshot required")
        identifier(self.opponent_id)
        member(self.source, "model opponent source", ("engineering_fixture", "user_provided", "external_submission"))
        member(self.migration, "snapshot inference migration", ("same-period-inference", "explicit-inference-migration"))
        member(self.policy_mode, "neural opponent policy mode", ("greedy", "sample"))
        object.__setattr__(self, "_seal", digest(self.identity()))

    def identity(self):
        return {"kind": "course-frozen-neural-opponent", "opponent_id": self.opponent_id, "source": self.source,
            "migration": self.migration, "snapshot": self.snapshot.identity(), "strength_qualified": False,
            "policy_mode": self.policy_mode, "formal_common_deck_evaluation": False}

    def assert_integrity(self):
        if digest(self.identity()) != self._seal: raise ContractError("frozen model runtime changed")

    def assert_assets(self, assets):
        """Read-only preflight, before a deck, engine or training update exists."""
        self.assert_integrity()
        state = self.snapshot.to_state(); source = state["provenance"]
        if source["resources"] != _resources(assets): raise ContractError("snapshot pinned native resources differ")
        if self.migration == "same-period-inference" and (source["period_context"] != getattr(assets, "period_context", None) or
                source["source_versions"] != asdict(_versions(assets))):
            raise ContractError("same-period snapshot source context/versions differ")
        if not {i for i in assets.rows if 0 < i < 2**32} <= set(state["card_ids"]):
            raise ContractError("snapshot vocabulary does not cover target catalogue")

    def bind(self, assets, profile, seat, *, policy_rng=None):
        return ModelSnapshotOpponent(assets, profile, seat, self, policy_rng=policy_rng)


class ModelSnapshotOpponent(FrozenOpponent):
    """Typed sampler adapter; its policy contains no host resources or decks."""
    def __init__(self, assets, profile, seat, runtime, *, policy_rng=None):
        if not isinstance(runtime, ModelOpponentRuntime): raise ContractError("typed model runtime required")
        runtime.assert_assets(assets); integer(seat, "model opponent seat", 0, 1)
        state = runtime.snapshot.to_state(); provenance = state["provenance"]
        profile = deepcopy(profile)
        if isinstance(assets, PeriodBuildAssets): profile = assets.validate_profile(profile)
        else:
            validate_profile(profile)
            for p in (0, 1):
                validate_deck_parts({"main": profile["decks"][p], "extra": profile.get("extras", [[], []])[p],
                    "side": profile.get("sides", [[], []])[p]}, assets.rows, assets.limits)
        versions = _versions(assets, profile.get("adapter_revision"))
        target_context = deepcopy(getattr(assets, "period_context", None))
        if runtime.migration == "same-period-inference" and (provenance["period_context"] != target_context or
                provenance["source_versions"] != asdict(versions)):
            raise ContractError("same-period snapshot source context/versions differ")
        # This is the entire policy input state. No host provenance, deck,
        # artifact path, optimizer, model seed, replay or native handle is copied.
        safe = {"config": {"model": state["model_config"]}, "card_ids": state["card_ids"],
            "model": state["model"], "vocab_sha256": state["vocab_sha256"], "model_sha256": state["model_sha256"]}
        if runtime.policy_mode == "sample":
            self.policy = SamplingSnapshotPolicy(seat, versions, safe, snapshot_sha256=state["state_sha256"], policy_rng=policy_rng)
        else:
            if policy_rng is not None: raise ContractError("greedy neural opponent does not consume a sampling RNG")
            self.policy = PublicSnapshotPolicy(seat, versions, safe)
        self._policy_rng = policy_rng
        self.assets, self.runtime, self.profile, self._profile, self.seat, self.versions = assets, runtime, profile, profile, seat, versions
        self._source_map = source_tree_snapshot(Path(__file__).resolve().parent)
        def deck(p): return {"main": profile["decks"][p], "extra": profile.get("extras", [[], []])[p], "side": profile.get("sides", [[], []])[p]}
        self.binding = {"schema_version": 1, "opponent_id": runtime.opponent_id,
            "environment_id": assets.environment["environment_id"], "registered_record_sha256": digest(runtime.identity()),
            "opponent_deck_sha256": digest(deck(seat)), "own_deck_sha256": digest(deck(1-seat)), "profile_sha256": digest(profile),
            "driver_version": DRIVER, "driver_implementation_sha256": digest(self._source_map), "source": runtime.source,
            "controller": "local_snapshot", "strength_qualified": False, "external_provider_verified": False,
            "model_sha256": state["model_sha256"], "opponent_deck_content_sha256": digest({z: sorted(v) for z, v in deck(seat).items()}),
            "snapshot_sha256": state["state_sha256"], "period_context": target_context,
            "source_period_context": deepcopy(provenance["period_context"]), "inference_migration": runtime.migration,
            "policy_mode": runtime.policy_mode}
        self._seal = digest({"binding": self.binding, "seat": seat, "versions": asdict(versions), "root": str(assets.root),
            "model_config": state["model_config"], "card_ids": state["card_ids"]})

    def assert_runtime(self, root, profile, actor_seat):
        self.runtime.assert_assets(self.assets)
        assert_source_tree(Path(__file__).resolve().parent, self._source_map)
        state = self.runtime.snapshot.to_state()
        actual = {"binding": self.binding, "seat": self.seat, "versions": asdict(self.versions), "root": str(self.assets.root),
            "model_config": asdict(self.policy.model.config), "card_ids": list(self.policy.encoder.card_ids)}
        if (Path(root).resolve() != self.assets.root or self.seat != 1-actor_seat or digest(actual) != self._seal or
                digest(profile) != self.binding["profile_sha256"] or digest(self.profile) != self.binding["profile_sha256"] or
                self.policy.seat != self.seat or self.policy.versions != self.versions or
                model_device(self.policy.model).type != "cpu" or self.policy.encoder.config != self.policy.model.config or
                any(m.training for m in self.policy.model.modules()) or any(p.requires_grad for p in self.policy.model.parameters()) or
                parameter_digest(self.policy.model) != state["model_sha256"] or self.policy.model_sha256 != state["model_sha256"] or
                self.policy.encoder.vocab_sha256 != state["vocab_sha256"] or
                self.policy.encoder.index != {c: i + 1 for i, c in enumerate(state["card_ids"])}):
            raise ContractError("frozen model opponent runtime/profile/seat/weights changed")
        if self.runtime.policy_mode == "sample" and (not isinstance(self.policy, SamplingSnapshotPolicy) or
                self.policy.policy_rng is not self._policy_rng or self.policy.policy_rng.device.type != "cpu" or
                self.policy.snapshot_sha256 != state["state_sha256"]):
            raise ContractError("sampled model opponent controller RNG changed")
