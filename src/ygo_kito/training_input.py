"""Period-aware input loading for the existing profile/opponent/index interfaces.

No sampler, model, process or native engine is started here. Historical intake
is rechecked, and loading requires an explicitly period-aware host runtime;
today's BuildAssets cannot acquire historical validity by changing a label.
"""

from copy import deepcopy
from dataclasses import dataclass

from .agent_registry import RUNTIME_POOLS, identifier
from .build_contracts import DeckParts, digest
from .contracts import Versions
from .data_isolation import DataIndex, PURPOSES, opponent_identity
from .deck_intake import PERIODS, SLOTS, _environment, prepare_intake, validate_intake
from .deck_profile import validate_deck_parts, validate_profile
from .validation import ContractError, array, fields, integer, member, text


def _sha(value, name):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ContractError(name + " requires a lowercase SHA-256")


def _profile(main, other, revision):
    if revision == 1 and (main.extra or other.extra):
        raise ContractError("adapter revision one cannot silently omit received extra decks")
    profile = {"schema_version": 1 if revision == 1 else 2,
               "name": "registered-main-deck-match" if revision == 1 else f"registered-v{revision}-match",
               "decks": [list(main.main), list(other.main)]}
    if revision != 1:
        profile["extras"] = [list(main.extra), list(other.extra)]
    if revision != 1 or main.side or other.side:
        profile["sides"] = [list(main.side), list(other.side)]
    if revision >= 3:
        profile["adapter_revision"] = revision
    validate_profile(profile)
    return profile


def validate_policy(value):
    d = fields(value, {"schema_version", "training_input_id", "source", "periods"})
    integer(d["schema_version"], "training input schema", 1, 1)
    identifier(d["training_input_id"])
    member(d["source"], "training input source", ("user_supplied", "synthetic_contract_test"))
    for period, spec in fields(d["periods"], set(PERIODS)).items():
        fields(spec, {"main_slot", "versions", "adapter_revision", "partitions"})
        if spec["main_slot"] not in SLOTS[:3]:
            raise ContractError("each period requires an explicit main-deck slot")
        integer(spec["adapter_revision"], "profile adapter revision", 1, 5)
        if spec["versions"] is not None:
            versions = Versions.from_dict(spec["versions"])
            if versions.card_pool != RUNTIME_POOLS[spec["adapter_revision"]]:
                raise ContractError("period version and profile adapter differ")
        for part in fields(spec["partitions"], set(PURPOSES)).values():
            fields(part, {"opponents", "seeds", "policy_seed"})
            if part["opponents"] is not None:
                opponents = array(part["opponents"], "partition opponents")
                if not 1 <= len(opponents) <= 8:
                    raise ContractError("each partition needs one to eight actual opponent bindings")
                for opponent in opponents:
                    fields(opponent, {"slot_id", "binding"})
                    if not isinstance(opponent["slot_id"], str) or opponent["slot_id"] not in SLOTS[3:]:
                        raise ContractError("unknown opponent intake slot")
                    if not isinstance(opponent["binding"], dict):
                        raise ContractError("actual frozen opponent binding required")
            if part["seeds"] is not None:
                seeds = array(part["seeds"], "partition seeds")
                if not 1 <= len(seeds) <= 100000:
                    raise ContractError("explicit bounded partition seeds required")
                for seed in seeds:
                    integer(seed, "partition seed", 0, 2**32 - 8)
                if len(set(seeds)) != len(seeds):
                    raise ContractError("partition seeds must be unique")
            if part["policy_seed"] is not None:
                integer(part["policy_seed"], "partition policy RNG seed", 0, 2**32 - 8)
    return deepcopy(d)


def _binding(raw, slot, main, profile, *, source):
    fields(raw, {"schema_version", "opponent_id", "environment_id", "registered_record_sha256", "opponent_deck_sha256",
        "own_deck_sha256", "profile_sha256", "driver_version", "driver_implementation_sha256", "source", "controller",
        "strength_qualified", "external_provider_verified", "model_sha256", "opponent_deck_content_sha256"})
    integer(raw["schema_version"], "opponent binding schema", 1, 1)
    identifier(raw["opponent_id"])
    identifier(raw["environment_id"])
    for key in ("registered_record_sha256", "opponent_deck_sha256", "own_deck_sha256", "profile_sha256",
                "driver_implementation_sha256", "opponent_deck_content_sha256"):
        _sha(raw[key], key)
    if raw["model_sha256"] is not None:
        _sha(raw["model_sha256"], "frozen model")
    for key in ("strength_qualified", "external_provider_verified"):
        if type(raw[key]) is not bool:
            raise ContractError("opponent qualification flags must be booleans")
    controller = slot["controller"]
    if raw["controller"] != controller["controller"] or raw["driver_version"] != controller["driver_version"]:
        raise ContractError("frozen opponent driver differs from its received slot")
    if raw["source"] not in (("engineering_fixture",) if source == "synthetic_contract_test" else ("user_provided", "external_submission")):
        raise ContractError("fixture and user-supplied opponent evidence must remain separate")
    if raw["controller"] == "local_snapshot" and raw["model_sha256"] != controller["model"]:
        raise ContractError("snapshot identity differs from its assigned model")
    if (raw["opponent_deck_sha256"] != slot["deck_sha256"] or raw["own_deck_sha256"] != digest(main.to_dict()) or
            raw["profile_sha256"] != digest(profile) or raw["opponent_deck_content_sha256"] !=
            digest({zone: sorted(cards) for zone, cards in slot["deck"].items()})):
        raise ContractError("frozen opponent is not bound to the actual received decks/profile")
    return deepcopy(raw)


def compile_training_inputs(intake, policy, workspace):
    """Compile genuine supplied lists and bindings; blanks produce a closed plan."""
    intake, policy = validate_intake(intake), validate_policy(policy)
    prepared = prepare_intake(intake, workspace)
    unmet = []
    if not prepared["complete_user_input"]:
        unmet.append("complete eleven-deck intake and three independent historical evidence sets are required")
    for period, spec in policy["periods"].items():
        if spec["versions"] is None:
            unmet.append(period + ": explicit actual runtime versions missing")
        for purpose, part in spec["partitions"].items():
            for key in ("opponents", "seeds", "policy_seed"):
                if part[key] is None:
                    unmet.append(period + "/" + purpose + ": missing " + key)
    if unmet:
        return {"status": "pending_input", "unmet": unmet, "input_source": policy["source"],
                "intake_sha256": digest(intake), "policy_sha256": digest(policy), "formal_training_ready": False}
    slots = {s["slot_id"]: s for s in prepared["slots"]}
    periods, opponents_seen, seeds_seen, used_slots, used_main_slots = {}, {}, {}, set(), set()
    for period in PERIODS:
        spec, evidence = policy["periods"][period], prepared["environments"][period]
        versions = Versions.from_dict(spec["versions"])
        if versions.cards != evidence["artifacts"]["catalog"]["sha256"] or versions.banlist != (
                evidence["banlist_section"] + ":" + evidence["artifacts"]["banlist"]["sha256"]):
            raise ContractError("period runtime cards/banlist versions differ from supplied historical sources")
        main = slots[spec["main_slot"]]
        used_main_slots.add(main["slot_id"])
        if period not in main["periods"]:
            raise ContractError("main-deck slot was not assigned to this period")
        deck = DeckParts.from_dict(main["deck"])
        context = {"period_id": period, "release_cutoff": evidence["release_cutoff"],
            "catalog_sha256": evidence["artifacts"]["catalog"]["sha256"],
            "release_manifest_sha256": evidence["artifacts"]["releases"]["sha256"],
            "banlist_sha256": evidence["artifacts"]["banlist"]["sha256"], "banlist_section": evidence["banlist_section"]}
        physical = digest({k: spec["versions"][k] for k in ("core", "scripts", "cards", "protocol", "banlist")})
        partitions = {}
        for purpose in PURPOSES:
            part = spec["partitions"][purpose]
            for seed in part["seeds"]:
                key = (physical, seed)
                if key in seeds_seen and seeds_seen[key] != purpose:
                    raise ContractError("same physical runtime seed crosses train/validation/final partitions")
                seeds_seen[key] = purpose
            bindings, profiles, seen = [], [], set()
            for assigned in part["opponents"]:
                slot = slots[assigned["slot_id"]]
                if period not in slot["periods"]:
                    raise ContractError("opponent slot was not assigned to this period")
                used_slots.add(slot["slot_id"])
                profile = _profile(deck, DeckParts.from_dict(slot["deck"]), spec["adapter_revision"])
                binding = _binding(assigned["binding"], slot, deck, profile, source=policy["source"])
                identity = opponent_identity(binding)
                if identity in seen:
                    raise ContractError("opponent aliases repeat one actual version within a partition")
                seen.add(identity)
                if identity in opponents_seen and opponents_seen[identity] != purpose:
                    raise ContractError("same actual opponent version crosses train/validation/final partitions")
                opponents_seen[identity] = purpose
                bindings.append(binding)
                profiles.append(profile)
            dataset = {"dataset_id": policy["training_input_id"] + "-" + period + "-" + purpose,
                "experiment_id": policy["training_input_id"], "purpose": purpose, "family": "duel",
                "versions": deepcopy(spec["versions"]), "opponents": bindings, "task_sha256": None}
            identifier(dataset["dataset_id"])
            partitions[purpose] = {"main_slot": main["slot_id"], "main_deck": deck.to_dict(),
                "opponent_slots": [o["slot_id"] for o in part["opponents"]], "profiles": profiles,
                "opponent_bindings": bindings, "seeds": part["seeds"], "policy_seed": part["policy_seed"],
                "dataset_spec": dataset}
        periods[period] = {"context": context, "versions": deepcopy(spec["versions"]), "partitions": partitions}
    if used_slots != set(SLOTS[3:]):
        raise ContractError("training inputs must explicitly account for all eight received opponent slots")
    if used_main_slots != set(SLOTS[:3]):
        raise ContractError("training inputs must explicitly account for all three received main-deck slots")
    result = {"status": "compiled_not_runtime_validated", "training_input_id": policy["training_input_id"],
        "input_source": policy["source"], "intake_sha256": digest(intake), "policy_sha256": digest(policy),
        "periods": periods, "runtime_loaded": False, "formal_training_ready": False, "native_executed": False}
    result["binding_sha256"] = digest(result)
    return result


@dataclass(frozen=True)
class LoadedTrainingInputs:
    manifest: dict
    assets: dict

    def _check_manifest(self):
        value = deepcopy(self.manifest)
        expected = value.pop("binding_sha256", None)
        if expected != digest(value):
            raise ContractError("loaded training input manifest was changed after validation")

    def for_runner(self, period, purpose, *, episode_cursor=0):
        """Return existing runner-compatible DTOs for one explicit sampling slot."""
        self._check_manifest()
        member(period, "training period", PERIODS)
        member(purpose, "training partition", PURPOSES)
        spec = self.manifest["periods"][period]["partitions"][purpose]
        integer(episode_cursor, "partition episode cursor", 0, len(spec["seeds"]) - 1)
        index = episode_cursor % len(spec["profiles"])
        runtime = self.assets[period]
        if (runtime.period_context != self.manifest["periods"][period]["context"] or
                runtime.environment.get("release_cutoff") != runtime.period_context["release_cutoff"] or
                runtime.environment.get("versions") != self.manifest["periods"][period]["versions"]):
            raise ContractError("period runtime changed after training input validation")
        runtime.assert_training_opponent(deepcopy(spec["opponent_bindings"][index]), deepcopy(spec["profiles"][index]))
        return {"period_context": deepcopy(self.manifest["periods"][period]["context"]),
            "input_binding_sha256": self.manifest["binding_sha256"], "input_source": self.manifest["input_source"],
            "purpose": purpose, "profile": deepcopy(spec["profiles"][index]),
            "main_deck": DeckParts.from_dict(spec["main_deck"]), "versions": Versions.from_dict(spec["dataset_spec"]["versions"]),
            "opponent_binding": deepcopy(spec["opponent_bindings"][index]), "dataset_spec": deepcopy(spec["dataset_spec"]),
            "seed": spec["seeds"][episode_cursor], "policy_seed": spec["policy_seed"], "assets": self.assets[period]}

    def freeze_partition(self, index, period, purpose):
        if not isinstance(index, DataIndex):
            raise ContractError("existing typed DataIndex required")
        selection = self.for_runner(period, purpose)
        return index.freeze(selection["dataset_spec"])

    def require_task(self, period, task):
        """An old current/custom task cannot be silently projected to history."""
        self._check_manifest()
        from .build_contracts import BuildTask
        if not isinstance(task, BuildTask):
            raise ContractError("existing typed construction task required")
        member(period, "training period", PERIODS)
        if task.environment.get("release_cutoff") != self.manifest["periods"][period]["context"]["release_cutoff"]:
            raise ContractError("construction task does not preserve the explicit historical cutoff")
        self.assets[period].check_task(task)
        return task


def load_training_inputs(intake, policy, workspace, *, runtime_assets):
    """Load real period-aware assets; absent or today's unscoped assets fail closed.

    The host implements assert_training_opponent(binding, profile) against its
    actual frozen driver/registry. Merely putting a hash in configuration cannot
    enable a driver. No bundled synthetic implementation satisfies production.
    """
    manifest = compile_training_inputs(intake, policy, workspace)
    if manifest["status"] != "compiled_not_runtime_validated":
        raise ContractError("training input loading blocked by missing user/environment/partition data")
    if not isinstance(runtime_assets, dict) or set(runtime_assets) != set(PERIODS):
        raise ContractError("three actual period-aware host runtimes are required")
    from pathlib import Path
    for period in PERIODS:
        assets = runtime_assets[period]
        check_physical = getattr(assets, "assert_integrity", None)
        if callable(check_physical):
            check_physical()
        context = manifest["periods"][period]["context"]
        if getattr(assets, "period_context", None) != context:
            raise ContractError("runtime is not explicitly bound to this historical period/cutoff/source set")
        environment = getattr(assets, "environment", {})
        if environment.get("release_cutoff") != context["release_cutoff"] or environment.get("versions") != manifest["periods"][period]["versions"]:
            raise ContractError("runtime historical environment differs; no current-environment projection is allowed")
        resources = getattr(assets, "receipt", {}).get("resources", {})
        versions = manifest["periods"][period]["versions"]
        if (resources.get("cards") != context["catalog_sha256"] or resources.get("banlist") != context["banlist_sha256"] or
                resources.get("scripts") != versions["scripts"] or resources.get("client_protocol") != versions["protocol"] or
                getattr(assets, "receipt", {}).get("source_commits", {}).get("core") != versions["core"]):
            raise ContractError("period runtime resource receipt differs from the supplied physical sources")
        _, expected = _environment(Path(workspace).resolve(), period, intake["environments"][period])
        if expected is None:
            raise ContractError("historical source changed during training input loading")
        rows, limits, allowed = expected
        if assets.limits != limits or any(any(assets.rows.get(c, {}).get(k) != rows[c][k] for k in ("id", "alias", "ot", "type")) for c in allowed):
            raise ContractError("runtime card facts or banlist differ from the independently checked historical listing")
        assert_opponent = getattr(assets, "assert_training_opponent", None)
        if not callable(assert_opponent):
            raise ContractError("host must verify actual period-compatible frozen opponent bindings")
        for part in manifest["periods"][period]["partitions"].values():
            main = DeckParts.from_dict(part["main_deck"])
            validate_deck_parts(main.to_dict(), assets.rows, assets.limits, allowed=allowed)
            for binding, profile in zip(part["opponent_bindings"], part["profiles"]):
                other = {"main": profile["decks"][1], "extra": profile.get("extras", [[], []])[1],
                         "side": profile.get("sides", [[], []])[1]}
                validate_deck_parts(other, assets.rows, assets.limits, allowed=allowed)
                assert_opponent(deepcopy(binding), deepcopy(profile))
    return LoadedTrainingInputs(deepcopy(manifest), dict(runtime_assets))
