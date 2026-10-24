"""Positive four-role worker/checkpoint path; no fault injection or signals.

The tiny existing engineering course is not a user roster or ability test.
Run this module explicitly; do not substitute the fault acceptance suite.
"""
import json
from copy import deepcopy
from pathlib import Path
import tempfile
import time
import unittest

from ygo_kito.group_runner import snapshot, verified
from ygo_kito.local_training import LocalCpuBackend, alive
from ygo_kito.validation import read_json

ROOT = Path(__file__).resolve().parents[1]


class NormalGroupWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = Path(tempfile.mkdtemp(prefix="group-normal-", dir=ROOT / ".cache"))
        recipe = read_json(ROOT / "configs/group-runner-v1.json")
        recipe.update(max_updates=1, stages_per_worker=7, wall_seconds=180.)
        recipe["execution"] = {"schema_version": 1, "device": "cpu", "dtype": "float32"}
        recipe["allocated_gpu_count"] = 0
        cls.run_recipe(recipe)

    @classmethod
    def run_recipe(cls, recipe):
        cls.backend = LocalCpuBackend(cls.directory, ROOT / ".cache", recipe=recipe)
        initial = cls.backend.prepare("normal-group")
        cls.backend.control(run_id="normal-group", operation="start", expected_revision=initial["revision"],
                            request_id="normal-group-start")
        deadline = time.monotonic() + 220
        while time.monotonic() < deadline:
            cls.row = cls.backend.refresh("normal-group")
            if cls.row["state"] != "running" and not alive(cls.row):
                break
            time.sleep(.1)
        if cls.row["state"] != "completed":
            # Keep a live or failed worker's state/logs intact. No timeout kill.
            raise AssertionError("normal group did not complete: " + cls.row["state"] + "; inspect " + str(cls.directory))
        if cls.backend.children["normal-group"].wait(timeout=10) != 0:
            raise AssertionError("normal group worker exited with an error; inspect " + str(cls.directory))
        cls.restored = verified(cls.directory, cls.row)
        cls.receipt = {"scope": "real-core-positive-four-role-worker-and-checkpoint",
            "state": cls.row["state"], "cursor": cls.restored.cursor(),
            "metrics": cls.row["metrics"], "execution": cls.row["recipe"]["execution"],
            "role_adapter_updates": {r: s.updates for r, s in cls.restored.sessions.items()},
            "training_state_sha256": cls.restored.training_fingerprint(),
            "frozen_evaluations": len(cls.restored.evaluations),
            "fault_injection_performed": False, "user_decks_received": False,
            "competitive_ability_validated": False, "gpu_execution_validated": False}
        cls.receipt["period_inputs_used"] = "period_inputs" in recipe
        target = ROOT / ".cache/pretraining-engine" / ("period-group-normal-proof.json" if "period_inputs" in recipe else "group-normal-proof.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(cls.receipt, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_all_four_actual_models_adapt_and_reach_normal_frozen_evaluation(self):
        self.assertEqual(self.restored.cursor(), {"cycle": 1, "phase": "done", "committed_stages": 7})
        self.assertEqual(self.row["metrics"]["optimizer_updates"], 8)
        self.assertEqual(self.receipt["role_adapter_updates"],
                         {"build_goal": 1, "build_optimizer": 1, "duel": 1, "coordinator": 1})
        self.assertEqual(len(self.restored.evaluations), 1)
        event = next(e["payload"] for e in self.restored.events if e["event_id"] == "cycle-1-evaluate")
        self.assertTrue(event["training_state_unchanged"])
        self.assertTrue(all(s.verify_base() == s.base_sha256 for s in self.restored.sessions.values()))

    def test_final_registered_checkpoint_restores_models_optimizers_rng_and_cursor(self):
        expected = self.restored.training_fingerprint()
        again = verified(self.directory, self.row)
        self.assertEqual(expected, again.training_fingerprint())
        self.assertEqual(snapshot(self.restored), snapshot(again))
        self.assertEqual(self.restored.host.state_digest(), again.host.state_digest())


class NormalPeriodGroupWorkerTests(NormalGroupWorkerTests):
    @classmethod
    def setUpClass(cls):
        from integration_tests.test_period_runtime import engineering_period_fixture
        from ygo_kito.deck_intake import PERIODS
        cls.directory = Path(tempfile.mkdtemp(prefix="period-group-normal-", dir=ROOT / ".cache"))
        cls.config_folder = tempfile.TemporaryDirectory(prefix="period-group-worker-", dir=ROOT / "configs")
        directory = Path(cls.config_folder.name)
        def save(name, data):
            path = directory / name
            path.write_text(json.dumps(data), encoding="utf-8")
            return str(path.relative_to(ROOT))
        intake, policy, assets, codes = engineering_period_fixture(cls.directory)
        for env in intake["environments"].values():
            for kind in ("catalog", "releases", "banlist"):
                env[kind]["path"] = ".cache/" + env[kind]["path"]
        period = "2022-10"
        partition = policy["periods"][period]["partitions"]
        partition["train"]["seeds"] = [2001, 2002]
        descriptor = {"schema_version": 1, "period_id": period,
            "intake": save("intake.json", intake), "policy": save("policy.json", policy),
            "native_roots": {p: ".cache" for p in PERIODS}}
        # Mutually exclusive list constraints make held-out construction lists
        # distinct. All card dates below are declared engineering input dates.
        task = {"schema_version": 4, "task_id": "period-worker-train", "environment": assets[period].environment,
            "goal": {"kind": "deck_constraints", "constraints": [
                {"id": "normal-count", "zones": ["main"], "predicate": {"field": "type_all", "value": 17}, "minimum": 40, "maximum": 40},
                {"id": "heldout-card", "zones": ["main"], "predicate": {"field": "card_ids", "value": [codes[0]]}, "minimum": 0, "maximum": 0}],
                "preferences": [{"id": "explicit-engineering-preference", "zones": ["main"],
                    "predicate": {"field": "card_ids", "value": [codes[-1]]}, "weight": 1}]},
            "sizes": {"main": 40, "extra": 0, "side": 0}, "pool": codes,
            "requirements": [], "annotations": [], "source": "engineering_fixture", "candidate_budget": 4}
        heldout = deepcopy(task)
        heldout["task_id"] = "period-worker-validation"
        heldout["goal"]["constraints"][1].update(minimum=1, maximum=3)
        course = {"schema_version": 1, "source": "indexed-semantic-course-v1", "period_id": period,
            "environment": assets[period].environment, "budget_seconds": 1,
            "validation_task": save("heldout.json", heldout)}
        recipe = read_json(ROOT / "configs/group-runner-v1.json")
        recipe.update(period_inputs=save("host.json", descriptor), task=save("task.json", task),
            construction_curriculum=save("course.json", course), max_updates=1, stages_per_worker=7,
            bootstrap_seed=2001, wall_seconds=180., allocated_gpu_count=0,
            execution={"schema_version": 1, "device": "cpu", "dtype": "float32"})
        recipe["train"].update(seed_start=2002, seed_stride=1)
        recipe["validation"].update(seeds=partition["validation"]["seeds"], policy_seed=partition["validation"]["policy_seed"])
        cls.run_recipe(recipe)

    @classmethod
    def tearDownClass(cls):
        if not alive(cls.row):
            cls.config_folder.cleanup()

    def test_period_index_and_actual_opponents_remain_bound_after_restore(self):
        self.assertIsNotNone(self.restored.data_index)
        self.assertEqual(self.restored.assets.period_context["period_id"], "2022-10")
        self.assertEqual(self.restored.assets.period_context["release_cutoff"], "2022-10-01")
        self.assertEqual(self.restored.data_index.summary()["artifacts"], 5)
        self.assertEqual(len(self.restored.data_marks), 3)
        self.assertTrue(all("opponent_binding" in e["payload"]["duel"] for e in self.restored.events
                            if e["event_id"] in ("bootstrap", "cycle-1-duel_train")))
        self.assertFalse(self.restored.assets.historical_rules_verified)


if __name__ == "__main__":
    unittest.main()
