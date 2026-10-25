"""Own small synthetic checkpoint-shape fixtures; no optimizer update or core.

Completed cursor fields exercise the artifact contract only. These fixtures do
not claim played episodes, trained weights, historical training or strength.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
from pathlib import Path
import random
import tempfile
import unittest

import torch

from ygo_kito.build_contracts import BuildTask, digest
from ygo_kito.build_model import BuildModelConfig
from ygo_kito.build_training import BuildTrainer, BuildTrainingConfig, save_checkpoint as save_build
from ygo_kito.coordinator_model import CoordinatorModelConfig, CoordinatorTrainer
from ygo_kito.cpu_training import CpuTrainer, CpuTrainingConfig, save_checkpoint as save_duel
from ygo_kito.device import capture_device_rng, execution_metadata
from ygo_kito.duel_model import DuelModelConfig, FEATURE_VERSION as DUEL_FEATURES, parameter_digest
from ygo_kito.group_initialization import PHASES, ROLES, initialize_group_weights, validate_initialization_spec
from ygo_kito.lora import AdapterConfig, AdapterSession
from ygo_kito.validation import ContractError
from tests.test_construction_logic import fixture_assets


def trainers(*, target=False, period=None):
    task, assets = fixture_assets()
    raw = task.to_dict()
    if target:
        raw["task_id"] = "different-period-target"
        raw["pool"] = sorted(set(raw["pool"]) - {2} | {19})
        assets.rows[19] = dict(assets.rows[3], id=19, name="new-synthetic-card")
        raw["annotations"] = raw["annotations"][1:] + [dict(raw["annotations"][0], source="new-fixture-annotation")]
    versions = raw["environment"]["versions"]
    resources = {"cards": versions["cards"], "banlist": versions["banlist"].split(":", 1)[1],
                 "scripts": versions["scripts"], "client_protocol": versions["protocol"]}
    assets.receipt = {"source_commits": {"core": versions["core"]}, "resources": resources}
    if period is not None:
        cutoff, section = {"2022-07": ("2022-09-30", "2022.7"), "2022-10": ("2022-12-31", "2022.10"),
                           "2026-10": ("2026-11-01", "2026.10")}[period]
        raw["environment"]["release_cutoff"] = cutoff
        raw["environment"]["versions"]["banlist"] = section + ":" + resources["banlist"]
        assets.period_context = {"period_id": period, "release_cutoff": cutoff, "catalog_sha256": resources["cards"],
            "release_manifest_sha256": "d" * 64, "banlist_sha256": resources["banlist"], "banlist_section": section}
    task = BuildTask.from_dict(raw); assets.environment = task.environment
    builder = BuildTrainer(task, assets, BuildTrainingConfig(model=BuildModelConfig(width=8, card_width=4, heads=2, feedforward=16, max_tokens=64)))
    duel = CpuTrainer(CpuTrainingConfig(model=DuelModelConfig(width=8, card_width=4, heads=2, feedforward=16,
        max_tokens=64, max_actions=32, history_events=8), game_seeds=(1724,)), [1, 3, 4, 5, 19] if target else [1, 2, 3, 5])
    coordinator = CoordinatorTrainer(CoordinatorModelConfig(hidden=4))
    binding = {"workflow": "four-model-alternating-v1", "feature_version": DUEL_FEATURES,
               "task_sha256": task.sha256, **deepcopy(assets.receipt), "unit_fixture_not_a_real_training_run": True}
    if period is not None: binding["period_context"] = deepcopy(assets.period_context)
    return builder, duel, coordinator, binding


def model_map(group):
    return dict(group[0].models, duel=group[1].model, coordinator=group[2].model)


def own_source(root, *, period=None):
    group = trainers(period=period); builder, duel, coord, binding = group
    # Assign distinguishable values directly; no optimizer step or training.
    for ordinal, (role, model) in enumerate(model_map(group).items(), 1):
        with torch.no_grad():
            for offset, parameter in enumerate(model.parameters()): parameter.fill_(ordinal / 10 + offset / 1000)
            if hasattr(model, "card"):
                for index in range(model.card.num_embeddings): model.card.weight[index].fill_(ordinal + index / 100)
            if hasattr(model, "annotation"):
                for index in range(model.annotation.num_embeddings): model.annotation.weight[index].fill_(ordinal + index / 10)
    supervision = digest("explicit-synthetic-checkpoint-shape-fixture")
    from ygo_kito.build_training import binding_for
    build_path = save_build(builder, root, "source-build", binding_for(builder.task, builder.encoder.assets, {"supervision_sha256": supervision}), allow_initial=True)
    duel_path = save_duel(duel, root, "source-duel", dict(binding, feature_version=DUEL_FEATURES), allow_initial=True)
    build = torch.load(build_path, weights_only=True); actor = torch.load(duel_path, weights_only=True)
    build.update(boundary="complete-role-update-batch", updates={"build_goal": 1, "build_optimizer": 1}, batch_cursor=1)
    actor.update(boundary="complete-episode", updates=1, episode_cursor=1)
    coordinator = deepcopy(coord.state()); coordinator["updates"] = 1
    context = digest({"runner": binding, "supervision": supervision})
    from ygo_kito.group_initialization import FEATURES
    sessions = {}
    for role, model in model_map(group).items():
        target = "head.0" if role.startswith("build_") else "policy_head.0" if role == "duel" else "route_head"
        session = AdapterSession(model, AdapterConfig("source-" + role, role, (target,), rank=1, alpha=2., max_updates=1),
            {"base_version": "synthetic-source", "feature_version": FEATURES[role], "context_sha256": context})
        with torch.no_grad():
            for delta in session.deltas.values(): delta.a.fill_(.2); delta.b.fill_(.3)
        session.updates = 1  # Declared fixture artifact cursor, not a training claim.
        sessions[role] = session.state()
    markers = ["bootstrap"] + ["cycle-1-" + phase for phase in PHASES]
    ledger = b"synthetic-provenance-bytes-not-a-played-ledger"
    source = {"schema_version": 1, "boundary": "complete-workflow-stage", "binding": binding,
        "execution": execution_metadata("cpu"), "device_rng": capture_device_rng("cpu"),
        "components": {"build": build, "duel": actor, "coordinator": coordinator}, "adapters": sessions,
        "cursor": {"cycle": 1, "phase": "done", "committed_stages": 7}, "consumed": markers,
        "events": [{"event_id": marker, "payload": {"source": "synthetic-checkpoint-shape-only"}} for marker in markers],
        "data": {"supervision_sha256": supervision}, "ledger_bytes": ledger, "ledger_sha256": hashlib.sha256(ledger).hexdigest()}
    return source


class GroupInitializationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = own_source(self.root, period="2022-07")
        self.path = self.root / "own-source.weights"

    def spec(self, source=None, weights="effective"):
        source = self.source if source is None else source
        torch.save(source, self.path)
        return {"path": self.path.name, "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
                "weights": weights, "source_binding_sha256": digest(source["binding"])}

    def initialize(self, group, spec):
        return initialize_group_weights(*group[:3], workspace=self.root, spec=spec, target_binding=group[3])

    def test_four_roles_effective_weights_and_stable_card_annotation_remap_keep_new_rows(self):
        spec = self.spec(); group = trainers(target=True, period="2022-10")
        models = model_map(group)
        before = {role: deepcopy(model.state_dict()) for role, model in models.items()}
        identities = {role: [id(p) for p in model.parameters()] for role, model in models.items()}
        receipt = self.initialize(group, spec)
        self.assertEqual(receipt["source_period_context"]["period_id"], "2022-07")
        self.assertEqual(receipt["target_period_context"]["period_id"], "2022-10")
        self.assertFalse(receipt["historical_training_verified"])
        for role, model in models.items():
            base = self.source["components"]["build"]["models"][role] if role.startswith("build_") else self.source["components"][role]["model"]
            meta = self.source["adapters"][role]["compatibility"]; target = meta["config"]["targets"][0]
            a, b = (self.source["adapters"][role]["weights"][target + suffix] for suffix in (".a", ".b"))
            self.assertTrue(torch.equal(model.state_dict()[target + ".weight"], base[target + ".weight"] + (b @ a) * 2.))
            self.assertEqual(identities[role], [id(p) for p in model.parameters()])
            self.assertEqual(parameter_digest(model), receipt["roles"][role]["target_after_sha256"])
            if role != "coordinator":
                old = self.source["components"]["build"]["task"]["pool"] if role.startswith("build_") else self.source["components"]["duel"]["card_ids"]
                new = group[0].encoder.card_ids if role.startswith("build_") else group[1].encoder.card_ids
                self.assertTrue(torch.equal(model.card.weight[new.index(3) + 1], base["card.weight"][old.index(3) + 1]))
                self.assertTrue(torch.equal(model.card.weight[new.index(19) + 1], before[role]["card.weight"][new.index(19) + 1]))
                self.assertTrue(torch.equal(model.card.weight[0], before[role]["card.weight"][0]))
        self.assertEqual(receipt["roles"]["build_goal"]["vocabulary_mapping"]["annotations"]["copied"], 2)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), spec["sha256"])

    def test_explicit_base_choice_is_distinct_from_effective_and_validates_adapters(self):
        base_group, effective_group = trainers(target=True), trainers(target=True)
        self.initialize(base_group, self.spec(weights="base"))
        self.initialize(effective_group, self.spec(weights="effective"))
        for role in ROLES:
            self.assertNotEqual(parameter_digest(model_map(base_group)[role]), parameter_digest(model_map(effective_group)[role]))
        broken = deepcopy(self.source); broken["adapters"]["duel"]["compatibility"]["base_sha256"] = "0" * 64
        with self.assertRaisesRegex(ContractError, "adapter role/base"):
            self.initialize(trainers(target=True), self.spec(broken, weights="base"))

    def test_new_optimizer_scheduler_cursors_and_all_rng_states_stay_fresh(self):
        group = trainers(target=True, period="2022-10"); builder, duel, coord, _ = group
        spec = self.spec()
        rng = {"torch": torch.get_rng_state().clone(), "python": random.getstate(), "build": builder.batch_rng.get_state(),
               "policy": duel.policy_rng.get_state(), "duel_batch": duel.batch_rng.get_state(), "coord": coord.batch_rng.get_state()}
        receipt = self.initialize(group, spec)
        self.assertEqual(random.getstate(), rng["python"])
        self.assertTrue(torch.equal(torch.get_rng_state(), rng["torch"]))
        for key, generator in (("build", builder.batch_rng), ("policy", duel.policy_rng), ("duel_batch", duel.batch_rng), ("coord", coord.batch_rng)):
            self.assertTrue(torch.equal(generator.get_state(), rng[key]))
        self.assertEqual(builder.updates, {"build_goal": 0, "build_optimizer": 0})
        self.assertEqual((builder.batch_cursor, duel.updates, duel.episode_cursor, coord.updates), (0, 0, 0, 0))
        self.assertTrue(all(not optimizer.state for optimizer in (*builder.optimizers.values(), duel.optimizer, coord.optimizer)))
        self.assertTrue(all(scheduler.last_epoch == 0 for scheduler in (*builder.schedulers.values(), duel.scheduler, coord.scheduler)))
        self.assertFalse(receipt["optimizer_state_inherited"]); self.assertFalse(receipt["rng_state_inherited"])
        self.assertFalse(receipt["data_or_ledger_inherited"])

    def test_invalid_feature_binding_role_shape_hash_and_second_role_fail_without_any_target_change(self):
        mutations = [lambda s: s["components"]["build"]["binding"].update(feature_version="old-features"),
            lambda s: s["components"]["duel"].update(role="different-role"),
            lambda s: s["components"]["build"]["model_hashes"].update(build_optimizer="0" * 64),
            lambda s: s["adapters"]["coordinator"]["compatibility"]["binding"].update(context_sha256="0" * 64),
            lambda s: s["components"]["build"].update(vocabulary_sha256="0" * 64),
            lambda s: s["binding"]["period_context"].update(release_cutoff="2022-10-01"),
            lambda s: s["cursor"].update(phase="evaluate"),
            lambda s: s["components"]["duel"]["model"].update(**{"card.weight": torch.zeros(2, 4)})]
        for mutate in mutations:
            source = deepcopy(self.source); mutate(source); group = trainers(target=True, period="2022-10")
            before = {role: parameter_digest(model) for role, model in model_map(group).items()}
            with self.subTest(mutation=mutate), self.assertRaises(ContractError): self.initialize(group, self.spec(source))
            self.assertEqual(before, {role: parameter_digest(model) for role, model in model_map(group).items()})

    def test_fixed_artifact_sha_source_binding_workspace_and_explicit_selection_are_required(self):
        spec = self.spec()
        for change in ({"sha256": "0" * 64}, {"source_binding_sha256": "0" * 64}, {"path": "../outside.weights"}):
            with self.subTest(change=change), self.assertRaises(ContractError):
                self.initialize(trainers(target=True), dict(spec, **change))
        for change in ({"weights": "latest"}, {"native": True}):
            with self.assertRaises(ContractError): validate_initialization_spec(dict(spec, **change))
        missing = dict(spec); missing.pop("weights")
        with self.assertRaises(ContractError): validate_initialization_spec(missing)

    def test_nonfresh_or_wrong_target_task_and_architecture_are_rejected(self):
        spec = self.spec(); group = trainers(target=True)
        group[0].batch_cursor = 1
        with self.assertRaisesRegex(ContractError, "fresh target"): self.initialize(group, spec)
        group = trainers(target=True)
        group[1].optimizer.state[next(group[1].model.parameters())] = {"fixture": True}
        with self.assertRaisesRegex(ContractError, "fresh independent"): self.initialize(group, spec)
        group = trainers(target=True); group[3]["task_sha256"] = "0" * 64
        with self.assertRaisesRegex(ContractError, "target group"): self.initialize(group, spec)
        group = trainers(target=True)
        group[2].config = CoordinatorModelConfig(hidden=8)
        with self.assertRaisesRegex(ContractError, "architecture"): self.initialize(group, spec)

    def test_old_unscoped_engineering_source_is_explicit_not_promoted_to_historical_training(self):
        source = own_source(self.root / "unscoped")
        receipt = self.initialize(trainers(target=True, period="2022-07"), self.spec(source))
        self.assertIsNone(receipt["source_period_context"])
        self.assertEqual(receipt["target_period_context"]["period_id"], "2022-07")
        self.assertFalse(receipt["historical_training_verified"])

    def test_explicit_same_or_reverse_period_migration_records_context_without_changing_target_cutoff(self):
        source = own_source(self.root / "later", period="2026-10")
        group = trainers(target=True, period="2022-07")
        before = group[0].task.environment
        receipt = self.initialize(group, self.spec(source))
        self.assertEqual(receipt["source_period_context"]["period_id"], "2026-10")
        self.assertEqual(receipt["target_period_context"]["period_id"], "2022-07")
        self.assertEqual(group[0].task.environment, before)


if __name__ == "__main__":
    unittest.main()
