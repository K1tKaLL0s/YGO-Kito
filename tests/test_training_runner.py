from contextlib import closing
from copy import deepcopy
from pathlib import Path
import tempfile
import time
import unittest

from ygo_kito.local_training import _connect, get_row, put_row
from ygo_kito.training_plan import BudgetBook
from ygo_kito.training_runner import validate_recipe, recipe_inputs, settle_usage, sync_usage
from ygo_kito.validation import ContractError, canonical_json, read_json

ROOT = Path(__file__).resolve().parents[1]


class RunnerContractTests(unittest.TestCase):
    def test_hundred_hour_plan_is_preserved_and_runner_has_a_distinct_finite_cpu_budget(self):
        recipe = validate_recipe(read_json(ROOT / "configs/cpu-runner-v1.json"))
        self.assertEqual(recipe["max_updates"], 4)
        self.assertEqual(recipe["wall_seconds"], 180.)
        plan = read_json(ROOT / "configs/training-plan-v1.json")
        self.assertEqual(plan["gpu_hours_limit"], 100.)
        self.assertFalse(plan["paid_execution_authorized"])
        profiles, config = recipe_inputs(recipe)
        self.assertEqual(len(config.game_seeds), recipe["max_updates"])
        self.assertNotEqual(profiles["train"]["decks"], profiles["validation"]["decks"])

    def test_overlap_driver_aliasing_cursor_override_and_unbounded_config_fail_closed(self):
        base = read_json(ROOT / "configs/cpu-runner-v1.json")
        for mutate in (lambda v: v["validation"].update(seeds=[1724]),
                       lambda v: v["validation"].update(opponent=v["train"]["opponent"]),
                       lambda v: v["cpu_config"].update(game_seeds=[1, 2]),
                       lambda v: v.update(wall_seconds=float("inf")),
                       lambda v: v.update(max_updates=100001),
                       lambda v: v["train"].update(profile="../private.json")):
            value = deepcopy(base)
            mutate(value)
            with self.assertRaises(ContractError):
                validate_recipe(value)
        base["validation"]["profile"] = base["train"]["profile"]
        with self.assertRaisesRegex(ContractError, "actual deck-list variant"):
            recipe_inputs(validate_recipe(base))

    def test_usage_outbox_retries_are_idempotent_and_a_new_attempt_is_new_usage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            row = {"run_id": "synthetic-outbox-case", "recipe": {}, "generation": "attempt-one",
                   "active_seconds": 10., "segment_started": time.monotonic() - 2., "wall_limit_seconds": 100.,
                   "usage_outbox": [], "metrics": {}, "budget_plan": read_json(ROOT / "configs/training-plan-v1.json")}
            settle_usage(row, "uncertain", "synthetic_elapsed_unit_case")
            first_active = row["active_seconds"]
            settle_usage(row, "uncertain", "synthetic_elapsed_unit_case")
            self.assertEqual(len(row["usage_outbox"]), 1)
            row.update(generation="attempt-two", segment_started=time.monotonic() - 1.)
            settle_usage(row, "completed", "synthetic_elapsed_unit_case")
            self.assertGreater(row["active_seconds"], first_active)
            with closing(_connect(root, create=True)) as db, db:
                db.execute("INSERT INTO runs VALUES(?,?)", (row["run_id"], canonical_json(row)))
            sync_usage(root, row["run_id"])
            book = BudgetBook(root / "cpu-usage.sqlite3", row["budget_plan"])
            original = book.history()
            self.assertEqual(len(original), 2)
            with closing(_connect(root)) as db, db:
                saved = get_row(db, row["run_id"])
                for event in saved["usage_outbox"]:
                    event["exported"] = False
                put_row(db, saved)
            sync_usage(root, row["run_id"])
            sync_usage(root, row["run_id"])
            self.assertEqual(book.history(), original)
            self.assertEqual(book.status()["gpu_instance_hours_used"], 0)
            self.assertEqual(book.status()["unknown_amount_events"], 2)


if __name__ == "__main__":
    unittest.main()
