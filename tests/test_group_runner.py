from copy import deepcopy
from pathlib import Path
import unittest

from ygo_kito.group_runner import PHASES, inputs
from ygo_kito.training_runner import validate_recipe
from ygo_kito.validation import ContractError, read_json

ROOT = Path(__file__).resolve().parents[1]


class GroupRecipeTests(unittest.TestCase):
    def test_group_recipe_keeps_four_independent_adapters_and_every_cycle_validation(self):
        recipe = validate_recipe(read_json(ROOT / "configs/group-runner-v1.json"))
        profiles, config, task, lora, adapters = inputs(recipe)
        self.assertEqual(set(adapters), {"duel", "build_goal", "build_optimizer", "coordinator"})
        self.assertEqual(recipe["validate_every"], 1)
        self.assertEqual(len(config.game_seeds), recipe["max_updates"])
        self.assertNotIn(recipe["bootstrap_seed"], config.game_seeds)
        self.assertTrue(all(c.max_updates == recipe["max_updates"] for c in adapters.values()))
        self.assertEqual(task.source, "engineering_fixture")
        self.assertEqual(lora["calibration"], "pending")

    def test_group_recipe_rejects_data_overlap_missing_evaluation_and_path_escape(self):
        base = read_json(ROOT / "configs/group-runner-v1.json")
        for mutate in (lambda v: v.update(bootstrap_seed=v["train"]["seed_start"]),
                       lambda v: v.update(validate_every=2), lambda v: v.update(stages_per_worker=0),
                       lambda v: v.update(task="configs/../outside.json"),
                       lambda v: v["cpu_config"].update(actor_seat=1)):
            recipe = deepcopy(base)
            mutate(recipe)
            with self.assertRaises(ContractError):
                validate_recipe(recipe)
        self.assertEqual(PHASES[-2:], ("evaluate", "feedback"))


if __name__ == "__main__":
    unittest.main()
