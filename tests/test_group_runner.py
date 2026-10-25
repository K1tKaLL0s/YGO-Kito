from copy import deepcopy
from pathlib import Path
import unittest

from ygo_kito.group_runner import PHASES, inputs, _scheduled_validation_cursor, _validation_job_purpose
from ygo_kito.data_isolation import opponent_identity
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


class GroupEvaluationContractTests(unittest.TestCase):
    """Real ledger/identity contracts over explicit synthetic data; no duels."""
    def setUp(self):
        from tests.test_coordinator import CoordinatorContractTests
        from tests.test_training_input import TrainingInputTests
        self.ledger = CoordinatorContractTests()
        self.ledger.setUp()
        self.addCleanup(self.ledger.doCleanups)
        self.training = TrainingInputTests()
        self.training.setUp()
        self.addCleanup(self.training.doCleanups)
        # Deliberately reverse ID order: ledger normalization is independent
        # from the host's profile order and actual sampled opponent.
        self.bindings = [self.training.binding("2022-07", i)["binding"] for i in (2, 1)]
        self.partition = {"opponent_bindings": self.bindings, "seeds": [1, 2], "policy_seed": 9001}

    def scheduled(self):
        scope = deepcopy(self.ledger.scope)
        scope["opponents"] = [{"opponent_id": b["opponent_id"], "deck_sha256": b["opponent_deck_sha256"],
                               "driver_sha256": opponent_identity(b), "weight": .5} for b in self.bindings]
        forecast = self.ledger.call(self.ledger.coord, "forecast.register",
            dict(self.ledger.forecast, forecast_id="multi-opponent", scope=scope))
        job = self.ledger.call(self.ledger.coord, "job.schedule",
            {"job_id": "multi-job", "forecast_id": "multi-opponent", "seed": 1, "purpose": "engineering_validation"})
        return scope, forecast, job

    def test_leased_opponent_identity_overrides_round_robin_and_scope_order(self):
        supplied, forecast, job = self.scheduled()
        self.assertNotEqual(supplied["opponents"], forecast["scope"]["opponents"])
        self.assertEqual(job["scope"], forecast["scope"])
        self.assertEqual(job["seed"], self.partition["seeds"][0])
        self.assertNotEqual(job["opponent"]["opponent_id"], self.bindings[0]["opponent_id"])
        cursor = _scheduled_validation_cursor(self.partition, job["opponent"])
        self.assertEqual(cursor, 1)
        binding = self.bindings[cursor]
        self.assertEqual(binding["opponent_id"], job["opponent"]["opponent_id"])
        self.assertEqual(opponent_identity(binding), job["opponent"]["driver_sha256"])
        self.assertEqual(self.partition["seeds"], [1, 2])
        self.assertEqual(self.partition["policy_seed"], 9001)

    def test_leased_identity_mismatch_duplicates_and_unselected_bindings_are_rejected(self):
        _, _, job = self.scheduled()
        for key, value in (("opponent_id", "unregistered"), ("deck_sha256", "0" * 64), ("driver_sha256", "0" * 64)):
            with self.subTest(key=key), self.assertRaisesRegex(ContractError, "no unique binding"):
                _scheduled_validation_cursor(self.partition, dict(job["opponent"], **{key: value}))
        duplicate = deepcopy(self.partition)
        duplicate["opponent_bindings"].append(dict(self.bindings[0], opponent_id="renamed-alias"))
        duplicate["seeds"].append(3)
        with self.assertRaisesRegex(ContractError, "repeats one actual opponent identity"):
            _scheduled_validation_cursor(duplicate, job["opponent"])
        with self.assertRaisesRegex(ContractError, "no unique binding"):
            _scheduled_validation_cursor(dict(self.partition, seeds=[1]), job["opponent"])

    def test_mandatory_rebuild_uses_child_validation_without_clearing_alerts(self):
        from tests.test_coordinator import message
        # Synthetic leased outcomes exercise the actual statistical/ledger
        # path. These are not played matches or native engine evidence.
        rows = self.ledger.synthetic_results(125)
        worker = self.ledger.host("duel_worker")
        self.ledger.call(worker, "results.append", {"results": rows})
        self.ledger.call(worker, "job.claim", {"job_id": "fixture-template", "worker_id": "fixture-worker"})
        self.ledger.call(worker, "results.append", {"results": [dict(rows[0], result_id="template-result", job_id="fixture-template")]})
        route = self.ledger.call(self.ledger.coord, "route", {"candidate_id": "candidate", "forecast_id": "forecast",
            "remaining_tasks": 1, "advisory": None})
        self.assertTrue(route["context"]["rebuild_required"])
        with self.assertRaisesRegex(ContractError, "changed child candidate"):
            _validation_job_purpose(self.ledger.candidate, route)
        changed = deepcopy(self.ledger.candidate)
        changed.update(candidate_id="rebuilt-child", parent_candidate_id="candidate")
        changed["deck"]["main"][0] = next(c for c in changed["task"]["pool"] if c != changed["deck"]["main"][0])
        candidate = self.ledger.call(self.ledger.coord, "handoff.submit", changed)
        self.ledger.call(self.ledger.coord, "forecast.register",
            dict(self.ledger.forecast, forecast_id="child-forecast", candidate_id=candidate["candidate_id"]))
        child_route = self.ledger.call(self.ledger.coord, "route", {"candidate_id": candidate["candidate_id"],
            "forecast_id": "child-forecast", "remaining_tasks": 1, "advisory": None})
        ordinary = {"job_id": "child-evaluation", "forecast_id": "child-forecast", "seed": 9, "purpose": "engineering_validation"}
        self.assertFalse(self.ledger.coord.dispatch(message("job.schedule", ordinary))["ok"])
        purpose = _validation_job_purpose(candidate, child_route)
        self.assertEqual(purpose, "rebuild_validation")
        job = self.ledger.call(self.ledger.coord, "job.schedule", dict(ordinary, purpose=purpose))
        self.assertEqual(job["purpose"], "rebuild_validation")
        self.assertTrue(self.ledger.coord.forecast_status("forecast")["mandatory_rebuild"])
        self.assertTrue(self.ledger.coord.forecast_status("child-forecast")["mandatory_rebuild"])
        self.assertEqual(_validation_job_purpose(self.ledger.candidate,
                         {"action": "register_forecast", "context": {"rebuild_required": False}}),
                         "engineering_validation")

    def test_warning_route_accepts_an_optimizer_candidate_without_clearing_warning(self):
        rows = self.ledger.synthetic_results(25)
        worker = self.ledger.host("duel_worker")
        self.ledger.call(worker, "results.append", {"results": rows})
        self.ledger.call(worker, "job.claim", {"job_id": "fixture-template", "worker_id": "fixture-worker"})
        self.ledger.call(worker, "results.append", {"results": [dict(rows[0], result_id="template-result", job_id="fixture-template")]})
        changed = deepcopy(self.ledger.candidate)
        changed.update(candidate_id="optimized-child", parent_candidate_id="candidate")
        changed["deck"]["main"][0] = next(c for c in changed["task"]["pool"] if c != changed["deck"]["main"][0])
        candidate = self.ledger.call(self.ledger.coord, "handoff.submit", changed)
        route = self.ledger.call(self.ledger.coord, "route", {"candidate_id": candidate["candidate_id"],
            "forecast_id": None, "remaining_tasks": 1, "advisory": None})
        self.assertEqual(route["action"], "build_optimizer")
        self.assertTrue(route["context"]["warning"])
        self.assertFalse(route["context"]["rebuild_required"])
        purpose = _validation_job_purpose(candidate, route)
        self.ledger.call(self.ledger.coord, "forecast.register",
            dict(self.ledger.forecast, forecast_id="optimized-forecast", candidate_id=candidate["candidate_id"]))
        job = self.ledger.call(self.ledger.coord, "job.schedule", {"job_id": "optimized-evaluation",
            "forecast_id": "optimized-forecast", "seed": 9, "purpose": purpose})
        self.assertEqual(job["purpose"], "engineering_validation")
        self.assertEqual(self.ledger.coord.forecast_status("forecast")["matches"], 26)
        self.assertTrue(self.ledger.coord.forecast_status("forecast")["alerts"])
        for action in ("diagnose", "train_duel", "stop"):
            with self.subTest(action=action), self.assertRaisesRegex(ContractError, "forecast stage"):
                _validation_job_purpose(candidate, dict(route, action=action))


if __name__ == "__main__":
    unittest.main()
