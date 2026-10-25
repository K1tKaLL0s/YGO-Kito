import copy
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ygo_kito.training_plan import BudgetBook, validate_plan, required_training_gates, LEGACY_GATES
from ygo_kito.validation import ContractError, read_json

ROOT = Path(__file__).resolve().parents[1]


class TrainingPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "budget.sqlite3"
        self.plan = read_json(ROOT / "configs/training-plan-v1.json")
        self.book = BudgetBook(self.path, self.plan, role="trainer", source="synthetic_contract_test", create=True)

    def event(self, ident="usage-1", **changes):
        return dict({"event_id": ident, "stage_id": "throughput-small-train", "gpu_count": 1, "wall_seconds": 3600,
                     "activity": "train", "outcome": "completed", "amount": None, "currency": None,
                     "expected_revision": 0}, **changes)

    def test_saved_plan_retains_approved_allocation_and_pending_gates(self):
        p = validate_plan(self.plan)
        self.assertEqual([r["gpu_hours"] for r in p["stages"]], [5, 25, 25, 20, 10, 15])
        self.assertEqual(p["gpu_hours_limit"], 100)
        self.assertFalse(p["paid_execution_authorized"])
        self.assertEqual(p["stop_remaining_quota_percent"], 20)
        self.assertIsNone(p["machine_type"])
        self.assertTrue(all(v is None for v in p["environment_artifacts"].values()))
        self.assertNotIn("P-01", p["required_gates"])
        self.assertEqual(required_training_gates(p), p["required_gates"])

    def test_old_plan_keeps_its_identity_without_requiring_a_pc_product(self):
        legacy = dict(self.plan, plan_id="three-environments-v1", required_gates=list(LEGACY_GATES))
        self.assertEqual(validate_plan(legacy), legacy)
        self.assertNotIn("P-01", required_training_gates(legacy))
        # Reading old metadata must not rewrite an existing ledger's hash.
        path = Path(self.tmp.name) / "old-plan.sqlite3"
        old = BudgetBook(path, legacy, role="trainer", source="synthetic_contract_test", create=True)
        self.assertEqual(old.status()["events"], 0)
        self.assertEqual(old.plan, legacy)

    def test_setup_download_idle_and_failed_multi_gpu_time_all_count(self):
        activities = (("setup", "completed", 2, 1800), ("download", "failed", 1, 3600),
                      ("idle", "uncertain", 1, 3600), ("train", "timeout", 2, 3600))
        for revision, (activity, outcome, gpus, seconds) in enumerate(activities):
            status = self.book.record(self.event("event-" + str(revision), activity=activity, outcome=outcome,
                                                gpu_count=gpus, wall_seconds=seconds, expected_revision=revision))
        self.assertEqual(status["gpu_instance_hours_used"], 5)
        self.assertEqual(status["gpu_instance_hours_remaining"], 95)
        check = self.book.check({"stage_id": "throughput-small-train", "gpu_count": 1, "max_wall_seconds": 1, "expected_revision": 4})
        self.assertFalse(check["within_recorded_budget"])
        self.assertFalse(check["execution_authorized"])
        self.assertFalse(check["reservation_created"])
        self.assertEqual(len(self.book.history()), 4)

    def test_usage_is_idempotent_and_revision_conflicts_do_not_add_rows(self):
        event = self.event()
        a = self.book.record(event)
        self.assertEqual(self.book.record(event), a)
        with self.assertRaises(ContractError):
            self.book.record(self.event("other", expected_revision=0))
        with self.assertRaises(ContractError):
            self.book.record(dict(event, wall_seconds=5000))
        with self.assertRaises(ContractError):
            self.book.record(dict(self.event("source-forgery", expected_revision=1), source="real_engine"))
        self.assertEqual(self.book.status()["events"], 1)

    def test_reported_overrun_is_preserved_and_next_admission_stops(self):
        status = self.book.record(self.event(wall_seconds=101 * 3600, outcome="failed"))
        self.assertTrue(status["over_budget"])
        self.assertEqual(status["gpu_instance_hours_remaining"], -1)
        check = self.book.check({"stage_id": "failure-revalidation-reserve", "gpu_count": 1, "max_wall_seconds": 1, "expected_revision": 1})
        self.assertFalse(check["within_recorded_budget"])
        self.assertEqual(self.book.history()[0]["wall_seconds"], 101 * 3600)

    def test_cpu_and_unknown_cost_are_not_misreported_as_free_gpu_training(self):
        status = self.book.record(self.event(gpu_count=0, activity="setup"))
        self.assertEqual(status["gpu_instance_hours_used"], 0)
        self.assertEqual(status["cpu_wall_seconds_reported_separately"], 3600)
        self.assertEqual(status["unknown_amount_events"], 1)
        self.assertEqual(status["reported_amounts_by_currency"], {})
        status = self.book.record(self.event("reported-cost", expected_revision=1, wall_seconds=60, amount="99.33", currency="CNY"))
        self.assertEqual(status["reported_amounts_by_currency"], {"CNY": "99.33"})
        self.assertFalse(status["billing_verified"])
        self.assertFalse(status["cloud_stop_confirmed"])

    def test_roles_source_database_ownership_and_launch_rejection(self):
        monitor = BudgetBook(self.path, self.plan, role="monitor", source="synthetic_contract_test")
        request = {"schema_version": 1, "id": "denied", "method": "usage.record", "params": self.event()}
        self.assertEqual(monitor.dispatch(request)["error"]["code"], "PERMISSION_DENIED")
        request["method"] = "training.start"
        self.assertEqual(self.book.dispatch(request)["error"]["code"], "PERMISSION_DENIED")
        with self.assertRaises(ContractError):
            BudgetBook(self.path, self.plan, role="trainer", source="host_reported_unverified")
        missing = Path(self.tmp.name) / "missing.sqlite3"
        with self.assertRaises(ContractError):
            BudgetBook(missing, self.plan)
        self.assertFalse(missing.exists())
        foreign = Path(self.tmp.name) / "foreign.sqlite3"
        with sqlite3.connect(foreign) as db:
            db.execute("CREATE TABLE other(value INTEGER)")
        with self.assertRaises(ContractError):
            BudgetBook(foreign, self.plan)

    def test_configuration_and_numeric_boundaries_fail_closed(self):
        for changes in ({"paid_execution_authorized": True}, {"gpu_hours_limit": 101},
                        {"gpu_hours_limit": float("nan")}, {"stop_remaining_quota_percent": 5},
                        {"external_api_amount_limit": "2.0"}, {"currency": "CNY"}):
            with self.assertRaises(ContractError):
                validate_plan(dict(self.plan, **changes))
        changed = copy.deepcopy(self.plan)
        changed["stages"][0]["gpu_hours"] = 50
        with self.assertRaises(ContractError):
            validate_plan(changed)
        for changes in ({"gpu_count": True}, {"wall_seconds": float("inf")}, {"amount": "nan", "currency": "CNY"}):
            with self.assertRaises(ContractError):
                self.book.record(self.event(**changes))


if __name__ == "__main__":
    unittest.main()
