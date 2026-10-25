"""Host descriptor and old/new curriculum input checks, without a native core.

Synthetic card files and an explicit mocked physical receipt exercise guards;
actual pinned resources/core have a separate explicit integration test module.
"""

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.deck_intake import PERIODS
from ygo_kito.period_host import load_period_host, period_host_operation, assert_period_hosts_unchanged, _bot_specs
from ygo_kito.period_runtime import PeriodBuildAssets
from ygo_kito.semantic_curriculum import COURSE, inputs
from ygo_kito.training_input import _profile
from ygo_kito.validation import ContractError
from tests import test_deck_intake as intake_fixtures
from tests.test_construction_logic import fixture_assets
from tests.test_period_runtime import synthetic_snapshot_fields, write_snapshot_fields


class PeriodHostTests(unittest.TestCase):
    def setUp(self):
        fixture = intake_fixtures.DeckIntakeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root, self.intake = fixture.root, deepcopy(fixture.config)
        self.receipt = {"source_commits": {"core": "a" * 40}, "resources": {
            "cards": self.intake["environments"]["2022-07"]["catalog"]["sha256"],
            "banlist": self.intake["environments"]["2022-07"]["banlist"]["sha256"],
            "scripts": "b" * 64, "client_protocol": "c" * 64}}
        def unit_base(instance, root):
            instance.root, instance.receipt = Path(root), deepcopy(self.receipt)
            with sqlite3.connect(self.root / "cards.cdb") as db:
                instance.rows = {code: {"id": code, "alias": alias, "ot": ot, "type": kind, "level": 4,
                    "atk": 1000, "def": 1000, "race": 1, "attribute": 1, "setcode": 0,
                    "name": "synthetic", "desc": "synthetic printed text"}
                    for code, alias, ot, kind in db.execute("SELECT id,alias,ot,type FROM datas")}
        base = patch("ygo_kito.period_runtime.BuildAssets.__init__", unit_base)
        base.start(); self.addCleanup(base.stop)
        verification = patch("ygo_kito.period_runtime.verify_resources", side_effect=lambda root: deepcopy(self.receipt))
        verification.start(); self.addCleanup(verification.stop)
        self.policy = {"schema_version": 1, "training_input_id": "host-unit-input", "source": "synthetic_contract_test", "periods": {}}
        for index, slot in enumerate(self.intake["slots"][3:], 1):
            # Distinct received listing content, instead of cosmetic driver IDs.
            deck = slot["deck"]["content"]["main"]
            deck[deck.index(index + 2)] = index + 10
            slot["controller"] = {"controller": "rule_baseline", "provider": None, "model": None,
                                  "driver_version": "visible-effects-first-v1"}
        for ordinal, period in enumerate(PERIODS):
            assets = PeriodBuildAssets(self.root, period, self.intake["environments"][period], self.root,
                                       evidence_source="engineering_fixture")
            actor = DeckParts.from_dict(self.intake["slots"][ordinal]["deck"]["content"])
            phase = {"main_slot": "main-" + str(ordinal + 1).zfill(2), "versions": assets.environment["versions"],
                     "adapter_revision": 5, "partitions": {}}
            for split, purpose in enumerate(("train", "validation", "final_eval")):
                indices = range(1, 7) if purpose == "train" else [7] if purpose == "validation" else [8]
                opponents = []
                for index in indices:
                    slot = self.intake["slots"][index + 2]
                    profile = _profile(actor, DeckParts.from_dict(slot["deck"]["content"]), 5)
                    opponent = assets.bind_rule_opponent(profile, slot["slot_id"])
                    opponents.append({"slot_id": slot["slot_id"], "binding": deepcopy(opponent.binding)})
                phase["partitions"][purpose] = {"opponents": opponents, "seeds": [1000 * (ordinal + 1) + split], "policy_seed": 2000 + split}
            self.policy["periods"][period] = phase
        self.descriptor = {"schema_version": 1, "intake": "configs/intake.json", "policy": "configs/policy.json",
                           "period_id": "2022-07", "native_roots": {p: "." for p in PERIODS}}
        self.recipe = {"period_inputs": "configs/period-host.json"}
        self.save()

    def write(self, name, value):
        path = self.root / "configs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def save(self):
        self.write("intake.json", self.intake)
        self.write("policy.json", self.policy)
        self.write("period-host.json", self.descriptor)

    def test_bot_host_configuration_is_exact_local_and_optional(self):
        self.assertEqual(_bot_specs({}, self.root, ("2022-07",)), ({}, []))
        spec = {"source_id": "ice", "executor_id": "ChaosRitualExecutor", "installed_root": "installed",
                "build_audit": {"path": "audit.json", "sha256": "a" * 64}, "mono": "/usr/bin/mono"}
        value = {"bots": {"2022-07": {"opponent-01": spec}}}
        bots, references = _bot_specs(value, self.root, ("2022-07",))
        self.assertEqual(bots["2022-07"]["opponent-01"], spec)
        self.assertIn("configs/bot-sources-v1.json", references)
        for key, invalid in (("source_id", "library"), ("installed_root", "../outside"),
                             ("mono", "mono"), ("executor_id", "")):
            wrong = deepcopy(value); wrong["bots"]["2022-07"]["opponent-01"][key] = invalid
            with self.subTest(key=key), self.assertRaises(ContractError):
                _bot_specs(wrong, self.root, ("2022-07",))

    def test_bot_dispatch_reaches_the_actual_registry_factory_without_claiming_a_runtime(self):
        # Explicit host-dispatch fixture: no C#, subprocess, socket or native core.
        spec = {"source_id": "ice", "executor_id": "ChaosRitualExecutor", "installed_root": "installed",
                "build_audit": {"path": "audit.json", "sha256": "a" * 64}, "mono": "/usr/bin/mono"}
        self.descriptor.update(scope="selected-period", bots={"2022-07": {"opponent-01": spec}})
        slot = self.intake["slots"][3]
        slot["controller"] = {"controller": "bot", "provider": None, "model": spec["executor_id"],
                              "driver_version": "windbot-lan-v1"}
        expected = self.policy["periods"]["2022-07"]["partitions"]["train"]["opponents"][0]["binding"]
        expected.update(controller="bot", driver_version="windbot-lan-v1")
        for relative in ("audit.json", "installed/bot-deployment-manifest.json", "configs/bot-sources-v1.json"):
            target = self.root / relative; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
        self.save()
        captured = []
        def explicit_dispatch_fixture(assets, profile, opponent_id, registry, **options):
            captured.append((registry, options))
            actual = assets.bind_rule_opponent(profile, opponent_id)
            actual.binding = deepcopy(expected)
            actual._binding_sha256 = digest(actual.binding)
            assets._opponents[digest(actual.binding)] = actual
            return actual
        with patch("ygo_kito.bot_deployment.BotSourceRegistry") as registry, \
             patch.object(PeriodBuildAssets, "bind_bot_opponent", explicit_dispatch_fixture):
            host = load_period_host(self.recipe, workspace=self.root)
        self.assertEqual(len(captured), 1)
        self.assertIs(captured[0][0], registry.return_value)
        self.assertEqual(captured[0][1]["build_audit_sha256"], spec["build_audit"]["sha256"])
        self.assertEqual(host.period_id, "2022-07")
        slot["controller"]["model"] = "WrongExecutor"
        self.save()
        with self.assertRaisesRegex(ContractError, "same exact pinned Executor"):
            load_period_host(self.recipe, workspace=self.root)

    def test_option_absence_preserves_existing_engineering_inputs(self):
        self.assertIsNone(load_period_host({}, workspace=self.root))
        task, val = self.course(period=False)
        with patch("ygo_kito.group_runner.config_path", side_effect=lambda p: self.root / p):
            actual = inputs({"construction_curriculum": "configs/course.json"}, task)
        self.assertEqual(actual["config"]["period_id"], "engineering-custom")
        self.assertEqual(actual["validation_task"], val)

    def test_actual_rule_binding_objects_are_loaded_without_native_duels(self):
        host = load_period_host(self.recipe, workspace=self.root)
        selection = host.for_runner("train")
        actual = host.opponent_for(selection["opponent_binding"], selection["profile"])
        self.assertEqual(actual.binding, selection["opponent_binding"])
        self.assertIs(host.assets, selection["assets"])
        self.assertIsNotNone(host.assets.environment["release_cutoff"])

    def configure_snapshot_fields(self):
        first_profile = self.policy["periods"]["2022-07"]["partitions"]["train"]["opponents"][0]["binding"]
        actor = DeckParts.from_dict(self.intake["slots"][0]["deck"]["content"])
        other = DeckParts.from_dict(self.intake["slots"][3]["deck"]["content"])
        profile = _profile(actor, other, 5)
        state = synthetic_snapshot_fields(self.root, self.receipt, profile)
        path, checksum = write_snapshot_fields(self.root, state)
        controller = {"controller": "local_snapshot", "provider": None, "model": state["model_sha256"],
                      "driver_version": "frozen-duel-greedy-v1"}
        self.intake["slots"][3]["controller"] = controller
        self.descriptor["snapshots"] = {}
        for period in PERIODS:
            assets = PeriodBuildAssets(self.root, period, self.intake["environments"][period], self.root, evidence_source="engineering_fixture")
            phase = self.policy["periods"][period]
            actor = DeckParts.from_dict(next(s for s in self.intake["slots"] if s["slot_id"] == phase["main_slot"])["deck"]["content"])
            profile = _profile(actor, other, 5)
            frozen = assets.bind_snapshot_opponent(profile, first_profile["opponent_id"], path, checksum, state["model_sha256"],
                model_source="untrained-unit-fields-only-not-native-evidence", migration="explicit-inference-migration")
            phase["partitions"]["train"]["opponents"][0]["binding"] = deepcopy(frozen.binding)
            self.descriptor["snapshots"][period] = {"opponent-01": {"path": str(path.relative_to(self.root)), "sha256": checksum,
                "model_source": frozen.model_provenance["model_source"], "migration": "explicit-inference-migration"}}
        self.save()
        return path

    def test_host_loads_snapshot_with_exact_binding_and_rechecks_file_and_model_seals(self):
        import torch
        path = self.configure_snapshot_fields()
        with period_host_operation():
            host = load_period_host(self.recipe, workspace=self.root)
            selected = host.for_runner("train")
            frozen = host.opponent_for(selected["opponent_binding"], selected["profile"])
            self.assertEqual(frozen.binding["controller"], "local_snapshot")
            self.assertFalse(frozen.model_provenance["historical_training_verified"])
            self.assertIs(load_period_host(self.recipe, workspace=self.root), host)
        original = path.read_bytes()
        try:
            with self.assertRaisesRegex(ContractError, "source bytes changed"):
                with period_host_operation():
                    load_period_host(self.recipe, workspace=self.root)
                    path.write_bytes(original + b"\n")
                    assert_period_hosts_unchanged()
        finally:
            path.write_bytes(original)
        with self.assertRaisesRegex(ContractError, "model/provenance changed"):
            with period_host_operation():
                host = load_period_host(self.recipe, workspace=self.root)
                selected = host.for_runner("train")
                model = host.opponent_for(selected["opponent_binding"], selected["profile"]).policy.model
                with torch.no_grad(): next(model.parameters()).add_(1.)
                assert_period_hosts_unchanged()

    def test_host_snapshot_artifact_and_migration_must_be_explicit_and_inside_workspace(self):
        self.configure_snapshot_fields()
        descriptor = deepcopy(self.descriptor)
        for mutation in ("missing", "outside", "model-source", "same-period", "unknown-driver"):
            self.descriptor = deepcopy(descriptor)
            self.intake["slots"][3]["controller"]["driver_version"] = "frozen-duel-greedy-v1"
            spec = self.descriptor["snapshots"]["2022-07"]["opponent-01"]
            if mutation == "missing": del self.descriptor["snapshots"]["2022-07"]["opponent-01"]
            elif mutation == "outside": spec["path"] = "../outside.weights"
            elif mutation == "model-source": spec["model_source"] = "unbound source label"
            elif mutation == "same-period": spec["migration"] = "same-period-inference"
            else: self.intake["slots"][3]["controller"]["driver_version"] = "unimplemented-snapshot"
            self.save()
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                load_period_host(self.recipe, workspace=self.root)

    def test_group_period_inputs_require_indexed_course_and_exact_seed_schedule(self):
        from ygo_kito import group_runner
        self.policy["periods"]["2022-07"]["partitions"]["train"]["seeds"] = [1000, 1003]
        self.save()
        task, _ = self.course(period=True)
        self.write("task.json", task.to_dict())
        source = Path(__file__).resolve().parents[1] / "configs"
        self.write("lora.json", json.loads((source / "lora-engineering-v1.json").read_text()))
        recipe = json.loads((source / "group-runner-v1.json").read_text())
        recipe.update(period_inputs="configs/period-host.json", task="configs/task.json",
            adapters="configs/lora.json", construction_curriculum="configs/course.json", max_updates=1, bootstrap_seed=1000)
        recipe["train"].update(seed_start=1003, seed_stride=1)
        recipe["validation"].update(seeds=[1001], policy_seed=2001)
        host = load_period_host(recipe, workspace=self.root)
        with patch("ygo_kito.group_runner.ROOT", self.root), \
                patch("ygo_kito.period_host.PeriodBuildAssets", wraps=PeriodBuildAssets) as constructor:
            profiles, config, actual, _, _ = group_runner.inputs(recipe)
            self.assertEqual(constructor.call_count, 3, "group inputs and semantic dispatch must share one complete host load")
            self.assertEqual(actual, task)
            self.assertEqual(config.game_seeds, (1003,))
            self.assertEqual(config.policy_seed, 2000)
            self.assertEqual(profiles["train"], host.for_runner("train")["profile"])
            self.assertEqual(group_runner.runtime_assets(recipe, self.root).period_context, host.assets.period_context)
            self.assertEqual(constructor.call_count, 6, "a separate operation must fully reload")
            wrong = deepcopy(recipe)
            wrong["train"]["seed_start"] = 1004
            with self.assertRaisesRegex(ContractError, "seed schedule"):
                group_runner.inputs(wrong)
            wrong = deepcopy(recipe)
            wrong["cpu_config"]["policy_seed"] = 999
            with self.assertRaisesRegex(ContractError, "policy RNG seed"):
                group_runner.inputs(wrong)
            legacy = deepcopy(recipe)
            del legacy["construction_curriculum"]
            with self.assertRaisesRegex(ContractError, "indexed semantic curriculum"):
                group_runner.inputs(legacy)

    def test_operation_reuses_nested_host_and_reloads_after_success_or_exception(self):
        with patch("ygo_kito.period_host.PeriodBuildAssets", wraps=PeriodBuildAssets) as constructor:
            with period_host_operation():
                first = load_period_host(self.recipe, workspace=self.root)
                with period_host_operation():
                    self.assertIs(load_period_host(self.recipe, workspace=self.root), first)
                self.assertEqual(constructor.call_count, 3)
            next_host = load_period_host(self.recipe, workspace=self.root)
            self.assertIsNot(next_host, first)
            self.assertEqual(constructor.call_count, 6)
            with self.assertRaisesRegex(RuntimeError, "ordinary-operation-error"):
                with period_host_operation():
                    load_period_host(self.recipe, workspace=self.root)
                    raise RuntimeError("ordinary-operation-error")
            self.assertEqual(constructor.call_count, 9)
            with period_host_operation():
                load_period_host(self.recipe, workspace=self.root)
            self.assertEqual(constructor.call_count, 12)

    def test_operation_never_shares_different_descriptor_or_workspace(self):
        alternate = deepcopy(self.descriptor)
        alternate["period_id"] = "2022-10"
        self.write("other-host.json", alternate)
        with period_host_operation(), patch("ygo_kito.period_host.PeriodBuildAssets", wraps=PeriodBuildAssets) as constructor:
            first = load_period_host(self.recipe, workspace=self.root)
            other = load_period_host({"period_inputs": "configs/other-host.json"}, workspace=self.root)
            self.assertEqual((first.period_id, other.period_id), ("2022-07", "2022-10"))
            self.assertIsNot(first, other)
            self.assertEqual(constructor.call_count, 6)
            with self.assertRaises((ContractError, FileNotFoundError)):
                load_period_host(self.recipe, workspace=self.root / "different-workspace")

    def test_operation_rehashes_configuration_and_all_source_bytes_on_each_hit(self):
        references = ["configs/period-host.json", "configs/intake.json", "configs/policy.json"]
        references.extend(self.intake["environments"][p][kind]["path"] for p in PERIODS for kind in ("catalog", "releases", "banlist"))
        for reference in sorted(set(references)):
            path = self.root / reference
            original = path.read_bytes()
            try:
                with self.subTest(path=reference), self.assertRaisesRegex(ContractError, "source bytes changed"):
                    with period_host_operation():
                        load_period_host(self.recipe, workspace=self.root)
                        path.write_bytes(original + b"\n")
                        load_period_host(self.recipe, workspace=self.root)
            finally:
                path.write_bytes(original)
        path = self.root / "configs/policy.json"
        original = path.read_bytes()
        try:
            with self.assertRaisesRegex(ContractError, "source bytes changed"):
                with period_host_operation():
                    load_period_host(self.recipe, workspace=self.root)
                    path.write_bytes(original + b" ")  # Even after the final hit, successful exit rechecks bytes.
        finally:
            path.write_bytes(original)

    def test_operation_rejects_mutated_manifest_runtime_path_and_physical_receipt(self):
        for mutation in ("manifest", "root", "workspace", "receipt", "facts"):
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ContractError, "changed|binding"):
                with period_host_operation():
                    host = load_period_host(self.recipe, workspace=self.root)
                    if mutation == "manifest": host.loaded.manifest["formal_training_ready"] = True
                    elif mutation == "root": host.assets.root = self.root / "another-native-root"
                    elif mutation == "workspace": host.assets.workspace = self.root / "another-workspace"
                    elif mutation == "receipt": host.assets.receipt["resources"]["cards"] = "0" * 64
                    else: host.assets.rows[1]["desc"] = "altered public text"
                    load_period_host(self.recipe, workspace=self.root)

    def test_operation_rejects_retargeted_source_even_when_bytes_are_identical(self):
        original = self.root / "configs/policy.json"
        alternate = self.root / "configs/identical-policy.json"
        alternate.write_bytes(original.read_bytes())
        link = self.root / "configs/policy-link.json"
        link.symlink_to(original)
        self.descriptor["policy"] = "configs/policy-link.json"
        self.write("period-host.json", self.descriptor)
        with self.assertRaisesRegex(ContractError, "source path changed"):
            with period_host_operation():
                load_period_host(self.recipe, workspace=self.root)
                link.unlink()
                link.symlink_to(alternate)
                load_period_host(self.recipe, workspace=self.root)

    def test_publication_guard_rejects_source_change_before_publisher_runs(self):
        publisher = Mock()
        path = self.root / "configs/policy.json"
        original = path.read_bytes()
        try:
            with self.assertRaisesRegex(ContractError, "source bytes changed"):
                with period_host_operation():
                    load_period_host(self.recipe, workspace=self.root)
                    path.write_bytes(original + b"\n")
                    assert_period_hosts_unchanged()
                    publisher()
        finally:
            path.write_bytes(original)
        publisher.assert_not_called()

    def test_independent_save_and_stage_reject_new_binding_before_any_write_or_update(self):
        from ygo_kito import group_runner
        state = SimpleNamespace(assets=SimpleNamespace(root=self.root),
            row={"recipe": {}, "binding": {"checkpoint_input": "original"}}, validate_cursor=Mock())
        with patch("ygo_kito.group_runner.binding_for", return_value={"checkpoint_input": "changed"}), \
                patch("ygo_kito.group_runner.execute_stage") as execute, \
                patch("ygo_kito.local_training.write_checkpoint") as checkpoint, \
                patch("torch.save") as save:
            with self.assertRaisesRegex(ContractError, "group save.*changed"):
                group_runner.GroupState.save_to(state, self.root / "must-not-exist.weights")
            with self.assertRaisesRegex(ContractError, "group stage.*changed"):
                group_runner._stage_transaction(state, self.root, "unit", "unit", state.row, Mock())
            state.validate_cursor.assert_not_called()
            execute.assert_not_called()
            checkpoint.assert_not_called()
            save.assert_not_called()

    def test_missing_data_fails_before_constructing_any_runtime(self):
        self.policy["periods"]["2022-07"]["versions"] = None
        self.save()
        with patch("ygo_kito.period_host.PeriodBuildAssets", side_effect=AssertionError("no default runtime")) as ctor:
            with self.assertRaisesRegex(ContractError, "incomplete"):
                load_period_host(self.recipe, workspace=self.root)
            ctor.assert_not_called()

    def test_selected_host_only_loads_current_period_and_leaves_future_cutoff_pending(self):
        for period in ("2022-10", "2026-10"):
            self.intake["environments"][period].update(release_cutoff=None, catalog=None, releases=None, banlist=None)
            self.policy["periods"][period]["versions"] = None
            for part in self.policy["periods"][period]["partitions"].values(): part.update(opponents=None, seeds=None, policy_seed=None)
        for slot in self.intake["slots"][1:3]: slot["deck"] = None
        self.descriptor.update(scope="selected-period", native_roots={"2022-07": "."})
        self.save()
        with period_host_operation(), patch("ygo_kito.period_host.PeriodBuildAssets", wraps=PeriodBuildAssets) as constructor:
            host = load_period_host(self.recipe, workspace=self.root)
            self.assertEqual(constructor.call_count, 1)
            self.assertEqual(set(host.loaded.assets), {"2022-07"})
            self.assertIs(load_period_host(self.recipe, workspace=self.root), host)
            self.assertFalse(host.loaded.manifest["formal_training_ready"])
            self.assertEqual(host.for_runner("train")["period_context"]["period_id"], "2022-07")
            with self.assertRaisesRegex(ContractError, "not selected"):
                host.loaded.for_runner("2026-10", "train")
        self.descriptor.pop("scope")
        self.descriptor["native_roots"] = {p: "." for p in PERIODS}
        self.save()
        with self.assertRaisesRegex(ContractError, "incomplete"):
            load_period_host(self.recipe, workspace=self.root)

    def test_descriptor_cannot_change_to_an_outside_runtime_or_data_path(self):
        for field in ("intake", "policy", "native_roots"):
            descriptor = deepcopy(self.descriptor)
            if field == "native_roots":
                descriptor[field]["2022-07"] = "../outside"
            else:
                descriptor[field] = "../outside.json"
            self.write("period-host.json", descriptor)
            with self.subTest(field=field), self.assertRaisesRegex(ContractError, "workspace"):
                load_period_host(self.recipe, workspace=self.root)
        for path in ("../outside.json", "absolute.json", "configs/../outside.json"):
            with self.subTest(path=path), self.assertRaises(ContractError):
                load_period_host({"period_inputs": path}, workspace=self.root)

    def test_plausible_hash_cannot_replace_the_actual_implemented_driver_binding(self):
        for period in PERIODS:
            for part in self.policy["periods"][period]["partitions"].values():
                for opponent in part["opponents"]:
                    opponent["binding"]["driver_implementation_sha256"] = "0" * 64
        self.save()
        with self.assertRaisesRegex(ContractError, "actual rule driver binding differs"):
            load_period_host(self.recipe, workspace=self.root)

    def course(self, *, period):
        task, _ = fixture_assets()
        raw = task.to_dict()
        raw["schema_version"] = 4
        raw["goal"] = {"kind": "deck_constraints", "constraints": [{"id": "count-normal", "zones": ["main"],
            "predicate": {"field": "type_all", "value": 17}, "minimum": 40, "maximum": 40}], "preferences": []}
        raw["environment"]["versions"]["card_pool"] = "native-private-knowledge-v5"
        if period:
            raw["environment"] = load_period_host(self.recipe, workspace=self.root).assets.environment
        task = BuildTask.from_dict(raw)
        raw["task_id"] = "heldout-task"
        raw["goal"]["constraints"][0]["minimum"] = 39
        validation = BuildTask.from_dict(raw)
        self.write("validation.json", validation.to_dict())
        self.write("course.json", {"schema_version": 1, "source": COURSE, "validation_task": "configs/validation.json",
            "period_id": "2022-07" if period else "engineering-custom", "environment": task.environment, "budget_seconds": 1})
        return task, validation

    def test_semantic_inputs_accept_only_exact_explicit_host_period_and_both_tasks(self):
        task, val = self.course(period=True)
        host = load_period_host(self.recipe, workspace=self.root)
        recipe = dict(self.recipe, construction_curriculum="configs/course.json")
        with patch("ygo_kito.group_runner.config_path", side_effect=lambda p: self.root / p):
            result = inputs(recipe, task, period_host=host)
            self.assertEqual(result["validation_task"], val)
            self.assertEqual(result["config"]["period_id"], "2022-07")
            original_loader = load_period_host
            with patch("ygo_kito.period_host.load_period_host", side_effect=lambda r: original_loader(r, workspace=self.root)) as loader:
                self.assertEqual(inputs(recipe, task)["binding_sha256"], result["binding_sha256"])
                loader.assert_called_once_with(recipe)
            host_other = replace_selected_period(host, "2022-10")
            with self.assertRaisesRegex(ContractError, "match.*host inputs"):
                inputs(recipe, task, period_host=host_other)


def replace_selected_period(host, period):
    from dataclasses import replace
    return replace(host, period_id=period)


if __name__ == "__main__":
    unittest.main()
