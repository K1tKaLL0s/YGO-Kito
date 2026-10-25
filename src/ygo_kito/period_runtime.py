"""Explicit period inputs over the pinned core, without historical qualification.

The assets must match the physical card/banlist files already verified by
BuildAssets. Only the selected limits, release allowlist and visible version
context vary. Native ABI/response handling stays in the existing adapter.
"""

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import inspect
from pathlib import Path
import pickle

from .agent_registry import RUNTIME_POOLS, identifier
from .build_contracts import DeckParts, digest
from .build_pipeline import BuildAssets
from .contracts import Versions
from .deck_intake import PERIODS, _date, _environment, cutoff_timing
from .deck_profile import validate_deck_parts, validate_profile
from .effect_duel import choose_effect_duel_action
from .native import NativeNormalEngine
from .native_assets import verify_resources
from .opponent_pool import FrozenOpponent, LOCAL_DRIVERS, SNAPSHOT_DRIVER, PublicRulePolicy, PublicSnapshotPolicy
from .validation import ContractError, fields, integer, member, text


def _sha256(value, label):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ContractError(label + " requires a lowercase SHA-256")


def _period_binding(assets, profile, opponent_id, seat, driver_version, source, controller, implementation, model_sha256=None, provenance=None):
    record = {"opponent_id": opponent_id, "environment_id": assets.environment["environment_id"], "controller": controller,
              "driver_version": driver_version, "source": source, "period_context": assets.period_context}
    if provenance is not None:
        record["model_provenance"] = provenance
    def deck(player):
        return {"main": profile["decks"][player], "extra": profile.get("extras", [[], []])[player],
                "side": profile.get("sides", [[], []])[player]}
    other, own = deck(seat), deck(1 - seat)
    return {"schema_version": 1, "opponent_id": opponent_id, "environment_id": assets.environment["environment_id"],
        "registered_record_sha256": digest(record), "opponent_deck_sha256": digest(other), "own_deck_sha256": digest(own),
        "profile_sha256": digest(profile), "driver_version": driver_version, "driver_implementation_sha256": implementation,
        "source": source, "controller": controller, "strength_qualified": False, "external_provider_verified": False,
        "model_sha256": model_sha256, "opponent_deck_content_sha256": digest({z: sorted(cards) for z, cards in other.items()})}


class PeriodBuildAssets(BuildAssets):
    """Real catalog/receipt plus explicitly sourced period restrictions.

    A current core and an engineering release manifest establish executable
    input plumbing only. Official source accuracy, errata and period-specific
    rules remain unverified, including after a successful native fixture.
    """

    def __init__(self, root, period_id, environment, workspace, *, adapter_revision=5, evidence_source="user_supplied"):
        member(period_id, "training period", PERIODS)
        integer(adapter_revision, "period adapter revision", 1, 5)
        member(evidence_source, "period evidence source", ("user_supplied", "engineering_fixture"))
        fields(environment, {"release_cutoff", "banlist_effective", "banlist_section", "catalog", "releases", "banlist"})
        _date(environment["release_cutoff"], "explicit period release cutoff")
        if environment["banlist_effective"] != period_id + "-01":
            raise ContractError("period banlist effective date differs")
        self.workspace = Path(workspace).resolve()
        self._environment_input = deepcopy(environment)
        self._environment_input_sha256 = digest(environment)
        evidence, parsed = _environment(self.workspace, period_id, self._environment_input)
        if parsed is None:
            raise ContractError("period catalog/release/banlist evidence is incomplete or invalid")
        super().__init__(root)
        if (evidence["artifacts"]["catalog"]["sha256"] != self.receipt["resources"]["cards"] or
                evidence["artifacts"]["banlist"]["sha256"] != self.receipt["resources"]["banlist"]):
            raise ContractError("period catalog/banlist must match the actual pinned native resources")
        rows, limits, allowed = parsed
        if any(any(self.rows.get(c, {}).get(k) != rows[c][k] for k in ("id", "alias", "ot", "type")) for c in allowed):
            raise ContractError("period public card facts differ from the actual native catalog")
        self.period_id, self.adapter_revision, self.evidence_source = period_id, adapter_revision, evidence_source
        self.allowed_card_ids = frozenset(allowed)
        self.limits = limits
        self.period_context = {"period_id": period_id, "release_cutoff": environment["release_cutoff"],
            "catalog_sha256": evidence["artifacts"]["catalog"]["sha256"],
            "release_manifest_sha256": evidence["artifacts"]["releases"]["sha256"],
            "banlist_sha256": evidence["artifacts"]["banlist"]["sha256"], "banlist_section": environment["banlist_section"]}
        hashes = self.receipt["resources"]
        versions = Versions(self.receipt["source_commits"]["core"], hashes["scripts"], hashes["cards"],
            hashes["client_protocol"], RUNTIME_POOLS[adapter_revision], environment["banlist_section"] + ":" + hashes["banlist"])
        self.environment = {"environment_id": "period-runtime-" + period_id, "versions": asdict(versions),
                            "authority": "custom", "release_cutoff": environment["release_cutoff"]}
        self._period_seal = digest({"context": self.period_context, "environment": self.environment,
                                   "allowed": sorted(self.allowed_card_ids), "limits": self.limits,
                                   "adapter_revision": self.adapter_revision, "evidence_source": self.evidence_source})
        self._row_seal = digest({c: self.rows[c] for c in sorted(self.allowed_card_ids)})
        self._opponents = {}
        self.historical_rules_verified = False
        self.official_sources_verified = False

    def environment_for(self, kind):
        # The host selected one explicit observation/adapter contract for this
        # period. Goal kinds cannot silently switch that framing or its cutoff.
        return deepcopy(self.environment)

    def assert_integrity(self, *, physical=True):
        if not cutoff_timing(self._environment_input["release_cutoff"])["cutoff_reached"]:
            raise ContractError("selected OCG cutoff has not arrived in Asia/Tokyo")
        if digest(self._environment_input) != self._environment_input_sha256:
            raise ContractError("period source configuration changed after binding")
        seal = digest({"context": self.period_context, "environment": self.environment,
                       "allowed": sorted(self.allowed_card_ids), "limits": self.limits,
                       "adapter_revision": self.adapter_revision, "evidence_source": self.evidence_source})
        if (seal != self._period_seal or digest({c: self.rows[c] for c in sorted(self.allowed_card_ids)}) != self._row_seal):
            raise ContractError("period runtime resources/context changed after binding")
        for opponent in getattr(self, "_opponents", {}).values():
            if isinstance(opponent, PeriodSnapshotOpponent):
                opponent.assert_snapshot_integrity(check_file=physical)
        if not physical:
            return
        if verify_resources(self.root) != self.receipt:
            raise ContractError("period native physical resources changed after binding")
        evidence, parsed = _environment(self.workspace, self.period_id, self._environment_input)
        if parsed is None or evidence["artifacts"]["releases"]["sha256"] != self.period_context["release_manifest_sha256"]:
            raise ContractError("period release evidence changed after binding")

    def check_task(self, task):
        super().check_task(task)
        if not set(task.pool) <= self.allowed_card_ids:
            raise ContractError("construction pool exceeds the explicit period release allowlist")

    def validate_profile(self, profile):
        validate_profile(profile)
        actual = profile.get("adapter_revision", 2 if profile["schema_version"] == 2 else 1)
        if actual != self.adapter_revision:
            raise ContractError("period profile adapter differs from the explicitly bound runtime")
        for seat in (0, 1):
            deck = {"main": profile["decks"][seat], "extra": profile.get("extras", [[], []])[seat],
                    "side": profile.get("sides", [[], []])[seat]}
            validate_deck_parts(deck, self.rows, self.limits, allowed=self.allowed_card_ids)
        return deepcopy(profile)

    def adapt_goal_profile(self, profile):
        """Frame a trusted verifier profile for this explicitly selected adapter.

        Verifiers build their own minimal profiles. Adapt only that observation
        framing; retain every card, its section, seat and order. Engine creation
        itself still requires an already matching revision and rechecks sources.
        """
        self.assert_integrity(physical=False)
        validate_profile(profile)
        result = {"schema_version": 1 if self.adapter_revision == 1 else 2,
                  "name": profile["name"], "decks": deepcopy(profile["decks"])}
        extras = deepcopy(profile.get("extras", [[], []]))
        sides = deepcopy(profile.get("sides", [[], []]))
        if self.adapter_revision == 1:
            if any(extras):
                raise ContractError("the selected period adapter cannot preserve the goal extra deck")
            result["sides"] = sides
        else:
            result.update(extras=extras, sides=sides)
            if self.adapter_revision >= 3:
                result["adapter_revision"] = self.adapter_revision
        return self.validate_profile(result)

    def engine_factory(self, root, **options):
        if Path(root).resolve() != self.root:
            raise ContractError("period engine cannot use another physical resource root")
        return PeriodNativeEngine(self, **options)

    def bind_rule_opponent(self, profile, opponent_id, *, seat=1, driver_version=LOCAL_DRIVERS[0], source=None):
        self.assert_integrity(physical=False)
        source = source or ("engineering_fixture" if self.evidence_source == "engineering_fixture" else "user_provided")
        opponent = PeriodRuleOpponent(self, profile, opponent_id, seat, driver_version, source)
        self._opponents[digest(opponent.binding)] = opponent
        return opponent

    def bind_snapshot_opponent(self, profile, opponent_id, checkpoint, checkpoint_sha256, model_sha256, *,
                               model_source, migration, seat=1, source=None):
        self.assert_integrity(physical=False)
        source = source or ("engineering_fixture" if self.evidence_source == "engineering_fixture" else "user_provided")
        opponent = PeriodSnapshotOpponent(self, profile, opponent_id, seat, source, checkpoint, checkpoint_sha256,
                                          model_sha256, model_source, migration)
        self._opponents[digest(opponent.binding)] = opponent
        return opponent

    def assert_training_opponent(self, binding, profile):
        self.assert_integrity(physical=False)
        opponent = self._opponents.get(digest(binding))
        if opponent is None or opponent.binding != binding:
            raise ContractError("no actual period opponent matches the supplied frozen binding")
        opponent.assert_runtime(self.root, profile, 1 - opponent.seat, _verify_physical=False)

    def opponent_for(self, binding, profile):
        self.assert_training_opponent(binding, profile)
        return self._opponents[digest(binding)]

    def rebind_rule_opponent(self, binding, actor_deck, *, purpose=None):
        """Re-freeze the actual policy/profile after a construction edit."""
        if purpose is not None:
            member(purpose, "opponent partition", ("train", "validation", "final_eval"))
        if not isinstance(actor_deck, DeckParts):
            raise ContractError("typed actor deck required for a period opponent rebind")
        previous = self._opponents.get(digest(binding))
        if previous is None or previous.binding != binding:
            raise ContractError("cannot rebind an unknown period opponent")
        previous.assert_runtime(self.root, previous.profile, 1 - previous.seat)
        profile, actor = deepcopy(previous.profile), 1 - previous.seat
        profile["decks"][actor] = list(actor_deck.main)
        if profile["schema_version"] == 2:
            profile["extras"][actor] = list(actor_deck.extra)
            profile["sides"][actor] = list(actor_deck.side)
        elif actor_deck.extra:
            raise ContractError("the bound profile revision cannot carry an edited extra deck")
        elif "sides" in profile or actor_deck.side:
            profile.setdefault("sides", [[], []])[actor] = list(actor_deck.side)
        if isinstance(previous, PeriodSnapshotOpponent):
            return self.bind_snapshot_opponent(profile, binding["opponent_id"], previous._checkpoint_reference,
                previous._checkpoint_sha256, previous.binding["model_sha256"], seat=previous.seat, source=binding["source"],
                model_source=previous.model_provenance["model_source"], migration=previous.model_provenance["migration"])
        return self.bind_rule_opponent(profile, binding["opponent_id"], seat=previous.seat,
            driver_version=binding["driver_version"], source=binding["source"])


class PeriodNativeEngine(NativeNormalEngine):
    def __init__(self, assets, *, deck_profile, scenario="effect-duel", **options):
        if not isinstance(assets, PeriodBuildAssets) or scenario != "effect-duel":
            raise ContractError("period native execution requires typed assets and an explicit effect-duel profile")
        # All source/date/allowed-list checks happen before NativeNormalEngine
        # loads the library or creates a core duel; no response or ABI is changed.
        assets.assert_integrity()
        profile = assets.validate_profile(deck_profile)
        self._period_assets = assets
        super().__init__(assets.root, scenario=scenario, deck_profile=profile, **options)
        self.context = replace(self.context, versions=Versions.from_dict(assets.environment["versions"]))
        self.period_context = deepcopy(assets.period_context)
        self.historical_rules_verified = False

    def _deck_limits(self):
        return dict(self._period_assets.limits)


class PeriodRuleOpponent(FrozenOpponent):
    """The existing visible rule policy with a real period-bound frozen profile.

    Subclassing preserves the existing CpuTrainer typed opponent boundary. This
    does not call FrozenOpponent's current-only registry projection. The record
    digest describes this explicit frozen configuration, without claiming a
    provider connection or historical rule/strength qualification.
    """

    def __init__(self, assets, profile, opponent_id, seat, driver_version, source):
        identifier(opponent_id)
        integer(seat, "period opponent seat", 0, 1)
        member(driver_version, "implemented period rule driver", LOCAL_DRIVERS)
        member(source, "period opponent source", ("user_provided", "external_submission", "engineering_fixture"))
        if assets.evidence_source == "engineering_fixture" and source != "engineering_fixture":
            raise ContractError("engineering period evidence cannot be promoted to user-supplied data")
        self.assets, self.seat, self.profile = assets, seat, assets.validate_profile(profile)
        self._profile = self.profile
        self.versions = Versions.from_dict(assets.environment["versions"])
        facts = {code: {"type": row["type"], "level": row["level"] & 255, "attack": row["atk"], "defense": row["def"]}
                 for code, row in assets.rows.items()}
        self.policy = PublicRulePolicy(driver_version, seat, self.versions, facts)
        self.binding = _period_binding(assets, self.profile, opponent_id, seat, driver_version, source, "rule_baseline",
            digest(inspect.getsource(PublicRulePolicy) + inspect.getsource(choose_effect_duel_action)))
        self._binding_sha256 = digest(self.binding)
        self.historical_rules_verified = False
        self.official_sources_verified = False

    def select(self, request):
        return self.policy.choose(request)

    def rebind(self, actor_deck, purpose=None):
        return self.assets.rebind_rule_opponent(self.binding, actor_deck, purpose=purpose)

    def assert_runtime(self, root, profile, actor_seat, *, _verify_physical=True):
        self.assets.assert_integrity(physical=_verify_physical)
        self.assets.validate_profile(profile)
        if (Path(root).resolve() != self.assets.root or self.seat != 1 - actor_seat or
                digest(self.binding) != self._binding_sha256 or digest(profile) != self.binding["profile_sha256"] or
                self.versions != Versions.from_dict(self.assets.environment["versions"])):
            raise ContractError("period opponent deck/driver/seat/runtime changed after freezing")


class PeriodSnapshotOpponent(PeriodRuleOpponent):
    """Frozen project CPU policy, with explicit source and inference migration.

    The source checkpoint remains unchanged. Its training profile/context is
    distinct from the current frozen match, including after an actor rebind.
    No optimizer, training seeds, artifact paths or provenance enter the policy.
    """

    def __init__(self, assets, profile, opponent_id, seat, source, checkpoint, checkpoint_sha256, model_sha256, model_source, migration):
        import torch
        from .cpu_training import config_from_dict
        from .device import checkpoint_execution
        from .duel_model import FEATURE_VERSION
        identifier(opponent_id)
        integer(seat, "period opponent seat", 0, 1)
        member(source, "period opponent source", ("user_provided", "external_submission", "engineering_fixture"))
        if assets.evidence_source == "engineering_fixture" and source != "engineering_fixture":
            raise ContractError("engineering period evidence cannot be promoted to user-supplied data")
        text(model_source, "snapshot model source")
        if len(model_source) > 512:
            raise ContractError("snapshot model source exceeds its metadata bound")
        member(migration, "snapshot inference migration", ("same-period-inference", "explicit-inference-migration"))
        _sha256(checkpoint_sha256, "snapshot artifact")
        _sha256(model_sha256, "snapshot model")
        self.assets, self.seat, self.profile = assets, seat, assets.validate_profile(profile)
        self._profile = self.profile
        self.versions = Versions.from_dict(assets.environment["versions"])
        reference = Path(checkpoint)
        self._checkpoint_reference = reference if reference.is_absolute() else assets.workspace / reference
        self._checkpoint = self._checkpoint_reference.resolve()
        self._checkpoint_sha256 = checkpoint_sha256
        self._snapshot_location_sha256 = digest([str(self._checkpoint_reference), str(self._checkpoint), checkpoint_sha256])
        if not self._checkpoint.is_relative_to(assets.workspace) or not self._checkpoint.is_file():
            raise ContractError("snapshot must be an explicit local workspace artifact")
        try:
            raw = self._checkpoint.read_bytes()
        except OSError as error:
            raise ContractError("snapshot artifact cannot be read") from error
        if hashlib.sha256(raw).hexdigest() != checkpoint_sha256:
            raise ContractError("snapshot artifact checksum differs")
        try:
            state = torch.load(self._checkpoint, map_location="cpu", weights_only=True)
            fields(state, {"schema_version", "role", "boundary", "config", "binding", "card_ids", "vocab_sha256", "model",
                "optimizer", "scheduler", "updates", "episode_cursor", "model_sha256", "rng"}, {"execution", "device_rng"})
            checkpoint_execution(state, requested="cpu")
            binding = fields(state["binding"], {"feature_version", "resources", "source_commits", "profile_sha256"},
                {"python_implementation_sha256", "python", "torch", "registered_opponent_pool", "period_context", "versions"})
            _sha256(binding["profile_sha256"], "source snapshot profile")
            if (type(state["schema_version"]) is not int or state["schema_version"] != 1 or state["role"] != "duel" or
                    state["boundary"] != "complete-episode" or binding["feature_version"] != FEATURE_VERSION or
                    binding["resources"] != assets.receipt["resources"] or binding["source_commits"] != assets.receipt["source_commits"] or
                    state["model_sha256"] != model_sha256):
                raise ContractError("snapshot is not a compatible completed CPU duel checkpoint")
            config = config_from_dict(state["config"])
            integer(state["updates"], "snapshot updates", 1, len(config.game_seeds))
            integer(state["episode_cursor"], "snapshot completed cursor", state["updates"], state["updates"])
            if not assets.allowed_card_ids <= set(state["card_ids"]):
                raise ContractError("snapshot vocabulary does not cover the explicit period card pool")
            source_context, source_versions = binding.get("period_context"), binding.get("versions")
            if (source_context is None) != (source_versions is None):
                raise ContractError("snapshot source period context and versions must be bound together")
            if source_context is not None:
                fields(source_context, {"period_id", "release_cutoff", "catalog_sha256", "release_manifest_sha256", "banlist_sha256", "banlist_section"})
                member(source_context["period_id"], "snapshot source period", PERIODS)
                _date(source_context["release_cutoff"], "snapshot source cutoff")
                source_v = Versions.from_dict(source_versions)
                text(source_context["banlist_section"], "snapshot source banlist section")
                for key in ("catalog_sha256", "release_manifest_sha256", "banlist_sha256"):
                    _sha256(source_context[key], "source period " + key)
                if (source_context["catalog_sha256"] != binding["resources"]["cards"] or
                        source_context["banlist_sha256"] != binding["resources"]["banlist"] or
                        source_v.core != binding["source_commits"]["core"] or source_v.scripts != binding["resources"]["scripts"] or
                        source_v.protocol != binding["resources"]["client_protocol"] or source_v.cards != binding["resources"]["cards"] or source_v.banlist !=
                        source_context["banlist_section"] + ":" + binding["resources"]["banlist"]):
                    raise ContractError("snapshot source period resource versions differ")
            if migration == "same-period-inference" and (source_context != assets.period_context or source_versions != assets.environment["versions"]):
                raise ContractError("same-period snapshot requires its exact source period/cutoff/versions")
            self.policy = PublicSnapshotPolicy(seat, self.versions, state)
        except ContractError:
            raise
        except (OSError, EOFError, pickle.UnpicklingError, KeyError, TypeError, ValueError, RuntimeError) as error:
            raise ContractError("snapshot artifact/model state is incompatible") from error
        self.model_provenance = {"model_source": model_source, "migration": migration,
            "artifact_sha256": checkpoint_sha256, "source_binding_sha256": digest(binding),
            "source_profile_sha256": binding["profile_sha256"], "source_period_context": deepcopy(source_context),
            "source_versions": deepcopy(source_versions), "target_period_context": deepcopy(assets.period_context),
            "target_profile_sha256": digest(self.profile), "vocab_sha256": state["vocab_sha256"],
            "model_config_sha256": digest(state["config"]["model"]),
            "feature_version": binding["feature_version"], "completed_boundary": state["boundary"], "completed_updates": state["updates"],
            "historical_training_verified": False, "strength_qualified": False}
        self._provenance_sha256 = digest(self.model_provenance)
        self.binding = _period_binding(assets, self.profile, opponent_id, seat, SNAPSHOT_DRIVER, source, "local_snapshot",
            digest(inspect.getsource(PublicSnapshotPolicy)), model_sha256, self.model_provenance)
        self._binding_sha256 = digest(self.binding)
        self.historical_rules_verified = False
        self.official_sources_verified = False
        self.assert_snapshot_integrity()

    def assert_snapshot_integrity(self, *, check_file=True):
        from .duel_model import parameter_digest
        if (digest(self.model_provenance) != self._provenance_sha256 or
                digest(self.binding) != self._binding_sha256 or digest(self.profile) != self.binding["profile_sha256"] or
                digest([str(self._checkpoint_reference), str(self._checkpoint), self._checkpoint_sha256]) != self._snapshot_location_sha256 or
                parameter_digest(self.policy.model) != self.binding["model_sha256"] or
                self.policy.model_sha256 != self.binding["model_sha256"] or self.policy.model.training or
                any(p.requires_grad for p in self.policy.model.parameters()) or
                self.policy.seat != self.seat or self.policy.versions != self.versions or
                self.policy.encoder.vocab_sha256 != self.model_provenance["vocab_sha256"] or
                digest(list(self.policy.encoder.card_ids)) != self.model_provenance["vocab_sha256"] or
                self.policy.encoder.index != {c: i + 1 for i, c in enumerate(self.policy.encoder.card_ids)} or
                digest(asdict(self.policy.encoder.config)) != self.model_provenance["model_config_sha256"] or
                digest(asdict(self.policy.model.config)) != self.model_provenance["model_config_sha256"]):
            raise ContractError("frozen period snapshot model/provenance changed")
        if check_file:
            try:
                checksum = hashlib.sha256(self._checkpoint.read_bytes()).hexdigest()
            except OSError as error:
                raise ContractError("frozen period snapshot artifact is unavailable") from error
            if (self._checkpoint_reference.resolve() != self._checkpoint or
                    not self._checkpoint.is_relative_to(self.assets.workspace) or checksum != self._checkpoint_sha256):
                raise ContractError("frozen period snapshot artifact changed")

    def assert_runtime(self, root, profile, actor_seat, *, _verify_physical=True):
        super().assert_runtime(root, profile, actor_seat, _verify_physical=_verify_physical)
        self.assert_snapshot_integrity()
