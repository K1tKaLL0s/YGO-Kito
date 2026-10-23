from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from ygo_kito.build_contracts import BuildTask, DeckParts
from ygo_kito.construction_curriculum import inputs
from ygo_kito.group_runner import actor_profile, inputs as group_inputs, profile_deck, validate_recipe
from ygo_kito.validation import ContractError, read_json

ROOT = Path(__file__).resolve().parents[1]


class RealCurriculumContractTests(unittest.TestCase):
    def test_explicit_source_keeps_old_default_and_binds_separate_partitions(self):
        old = read_json(ROOT / "configs/group-runner-v1.json")
        task = BuildTask.from_dict(read_json(ROOT / old["task"]))
        self.assertIsNone(inputs(old, task))
        recipe = validate_recipe(read_json(ROOT / "configs/group-real-curriculum-v1.json"))
        profiles, _, task, _, _ = group_inputs(recipe)
        actual = inputs(recipe, task)
        self.assertNotEqual(actual["train"]["opponent"], actual["validation"]["opponent"])
        self.assertFalse(set(actual["train"]["paired_seeds"]) & set(actual["validation"]["paired_seeds"]))
        self.assertNotEqual(profiles["train"], profiles["validation"])
        self.assertEqual(task.goal["kind"], "synchro_summon")

    def test_validation_overlap_wrong_driver_task_or_partition_fails_closed(self):
        recipe = read_json(ROOT / "configs/group-real-curriculum-v1.json")
        task = BuildTask.from_dict(read_json(ROOT / recipe["task"]))
        config = read_json(ROOT / recipe["construction_curriculum"])
        raw = {k: read_json(ROOT / config[k]) for k in ("train", "validation")}
        for mutation in ("overlap", "duel_overlap", "opponent", "purpose", "driver", "task", "schema"):
            values = deepcopy(raw)
            target = values["validation"]
            if mutation == "overlap": target["paired_seeds"] = values["train"]["paired_seeds"]
            elif mutation == "duel_overlap": target["paired_seeds"][0] = recipe["bootstrap_seed"]
            elif mutation == "opponent": target["opponent"] = values["train"]["opponent"]
            elif mutation == "purpose": target["purpose"] = "construction_train"
            elif mutation == "driver": target["driver"] = "unfrozen"
            elif mutation == "task": target["task_file"] = "configs/build-engineering-v1.json"
            elif mutation == "schema": target["schema_version"] = True
            def load(path):
                for name in ("train", "validation"):
                    if str(path) == str(ROOT / config[name]):
                        return values[name]
                return read_json(path)
            with self.subTest(mutation=mutation), patch("ygo_kito.construction_curriculum.read_json", side_effect=load), self.assertRaises(ContractError):
                inputs(recipe, task)

    def test_selected_extra_side_parts_are_not_silently_dropped_from_duel_profiles(self):
        profile = read_json(ROOT / "configs/group-extra-train-v2.json")
        deck = profile_deck(profile, 0)
        altered = DeckParts(deck.main, (78156759,), (32864,))
        actual = actor_profile(profile, altered)
        self.assertEqual(profile_deck(actual, 0), altered)
        self.assertEqual(profile_deck(actual, 1), profile_deck(profile, 1))
        old = {k: profile[k] for k in ("schema_version", "name", "decks")}; old["schema_version"] = 1
        with self.assertRaises(ContractError):
            actor_profile(old, altered)


if __name__ == "__main__":
    unittest.main()
