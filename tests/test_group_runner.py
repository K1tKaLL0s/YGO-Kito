from copy import deepcopy
from pathlib import Path
import unittest

from ygo_kito.group_runner import PHASES, inputs
from ygo_kito.training_runner import validate_recipe
from ygo_kito.validation import ContractError, read_json

ROOT = Path(__file__).resolve().parents[1]


class GroupRecipeTests(unittest.TestCase):
    def test_explicit_cpu_recipe_is_compatible_and_gpu_allocation_is_never_inferred(self):
        base=read_json(ROOT / "configs/group-runner-v1.json")
        explicit=deepcopy(base)
        explicit['execution']={'schema_version':1,'device':'cpu','dtype':'float32'}
        explicit['allocated_gpu_count']=0
        self.assertEqual(inputs(validate_recipe(base))[2],inputs(validate_recipe(explicit))[2])
        for bad in ({'schema_version':1,'device':'cpu','dtype':'float16'},
                    {'schema_version':1,'device':'meta','dtype':'float32'}):
            candidate=deepcopy(explicit);candidate['execution']=bad
            with self.assertRaises(ContractError):validate_recipe(candidate)
        explicit['allocated_gpu_count']=1
        with self.assertRaises(ContractError):validate_recipe(explicit)
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
