"""Host descriptor and old/new curriculum input checks, without a native core.

Synthetic card files and an explicit mocked physical receipt exercise guards;
actual pinned resources/core have a separate explicit integration test module.
"""

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from ygo_kito.build_contracts import BuildTask, DeckParts
from ygo_kito.deck_intake import PERIODS
from ygo_kito.period_host import load_period_host
from ygo_kito.period_runtime import PeriodBuildAssets
from ygo_kito.semantic_curriculum import COURSE, inputs
from ygo_kito.training_input import _profile
from ygo_kito.validation import ContractError
from tests import test_deck_intake as intake_fixtures
from tests.test_construction_logic import fixture_assets


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
        with patch("ygo_kito.group_runner.period_host", return_value=host), \
                patch("ygo_kito.period_host.load_period_host", return_value=host), \
                patch("ygo_kito.group_runner.config_path", side_effect=lambda p: self.root / p):
            profiles, config, actual, _, _ = group_runner.inputs(recipe)
            self.assertEqual(actual, task)
            self.assertEqual(config.game_seeds, (1003,))
            self.assertEqual(config.policy_seed, 2000)
            self.assertEqual(profiles["train"], host.for_runner("train")["profile"])
            self.assertIs(group_runner.runtime_assets(recipe, self.root), host.assets)
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

    def test_missing_data_fails_before_constructing_any_runtime(self):
        self.policy["periods"]["2022-07"]["versions"] = None
        self.save()
        with patch("ygo_kito.period_host.PeriodBuildAssets", side_effect=AssertionError("no default runtime")) as ctor:
            with self.assertRaisesRegex(ContractError, "incomplete"):
                load_period_host(self.recipe, workspace=self.root)
            ctor.assert_not_called()

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
