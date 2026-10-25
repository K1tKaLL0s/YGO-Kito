"""Synthetic outcome contracts only: 1000 rows are not 1000 played matches."""

import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ygo_kito.build_contracts import digest
from ygo_kito.coord_contracts import FeedbackPolicy, rule_route
from ygo_kito.coordinator import Coordinator
from ygo_kito.validation import ContractError, canonical_json

ROOT = Path(__file__).resolve().parents[1]
TASK = json.loads((ROOT / "configs/build-engineering-v1.json").read_text())
DECK = json.loads((ROOT / "docs/reports/2026-10-23-m3b-best-deck.json").read_text())


def message(method, params=None):
    return {"schema_version": 1, "id": "contract-request", "method": method, "params": params or {}}


class CoordinatorContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger.sqlite3"
        self.policy = FeedbackPolicy()
        self.coord = Coordinator(self.path, self.policy, role="coordinator", source="synthetic_contract_test", create=True)
        self.candidate = {"candidate_id": "candidate", "parent_candidate_id": None, "task": TASK, "deck": DECK,
                          "build_models": {"build_goal": "1" * 64, "build_optimizer": "2" * 64}}
        self.call(self.coord, "handoff.submit", self.candidate)
        self.scope = {"actor_policy_sha256": "3" * 64, "duel_lora": None,
                      "opponents": [{"opponent_id": "fixture-rule", "deck_sha256": "4" * 64, "driver_sha256": "5" * 64, "weight": 1.}],
                      "initiative_weights": [1., 0.], "unit": "BO1", "prediction_target": "win_rate", "versions": TASK["environment"]["versions"]}
        self.forecast = {"forecast_id": "forecast", "candidate_id": "candidate", "probability": .9, "origin_role": "coordinator",
                         "model_sha256": "6" * 64, "calibration": "pending", "scope": self.scope}
        self.call(self.coord, "forecast.register", self.forecast)

    def host(self, role):
        return Coordinator(self.path, self.policy, role=role, source="synthetic_contract_test")

    def call(self, host, method, params=None):
        result = host.dispatch(message(method, params))
        self.assertTrue(result["ok"], result)
        return result["result"]

    def synthetic_results(self, count, outcomes=None):
        """Lease fixtures matching one validated job envelope; no engine simulation."""
        template = self.call(self.coord, "job.schedule", {"job_id": "fixture-template", "forecast_id": "forecast", "seed": 7, "purpose": "evaluation"})
        rows = []
        with self.coord._db() as db, db:
            for i in range(count):
                job_id = f"synthetic-job-{i}"
                info = dict(template, job_id=job_id, seed=i)
                db.execute("INSERT INTO jobs VALUES(?,?,?,'leased','fixture-worker')", (job_id, "forecast", canonical_json(info)))
                rows.append({"result_id": f"synthetic-result-{i}", "job_id": job_id, "worker_id": "fixture-worker", "forecast_id": "forecast",
                             "candidate_id": "candidate", "scope_sha256": template["scope_sha256"], "source": "synthetic_contract_test", "unit": "BO1",
                             "outcome": outcomes[i] if outcomes else "loss", "audit_sha256": digest({"synthetic_index": i}), "diagnosis": "unknown"})
        return rows

    def test_predeclared_early_and_intermediate_checks_warn_and_force_before_round_numbers(self):
        rows = self.synthetic_results(1000)
        status = self.call(self.host("duel_worker"), "results.append", {"results": rows})["forecast"]
        self.assertEqual(status["matches"], 1000)
        self.assertEqual(status["wins"], 0)
        self.assertEqual([c["matches"] for c in status["checks"]], list(self.policy.checkpoints))
        alerts = {a["kind"]: a["n"] for a in status["alerts"]}
        self.assertLess(alerts["reevaluate"], 100)
        self.assertTrue(100 < alerts["mandatory_rebuild"] < 1000)
        self.assertTrue(status["mandatory_rebuild"])
        self.assertEqual(status["source"], "synthetic_contract_test")
        route = self.call(self.coord, "route", {"candidate_id": "candidate", "forecast_id": "forecast", "remaining_tasks": 1,
                            "advisory": {"route": "evaluate_duel", "model_sha256": "7" * 64, "calibration": "pending"}})
        self.assertEqual(route["action"], "build_goal")
        self.assertEqual(route["mode"], "rule_authoritative")
        denied = self.coord.dispatch(message("job.schedule", {"job_id": "skip-rebuild", "forecast_id": "forecast", "seed": 8, "purpose": "evaluation"}))
        self.assertFalse(denied["ok"])

    def test_wins_do_not_trigger_and_failure_draw_records_are_not_filtered(self):
        rows = self.synthetic_results(100, ["win"] * 95 + ["draw", "loss", "timeout", "crash", "invalid_action"])
        status = self.call(self.host("duel_worker"), "results.append", {"results": rows})["forecast"]
        self.assertEqual(status["matches"], 100)
        self.assertEqual(status["observed_win_rate"], .95)
        self.assertEqual(status["score_mean"], .95)
        self.assertFalse(status["alerts"])
        self.assertEqual(sum(status["outcome_counts"].values()), 100)
        self.assertTrue(all(status["outcome_counts"][k] == 1 for k in ("draw", "timeout", "crash", "invalid_action")))

    def test_duplicate_result_is_idempotent_and_conflicting_or_cross_source_batch_rolls_back(self):
        rows = self.synthetic_results(2)
        worker = self.host("duel_worker")
        self.call(worker, "results.append", {"results": [rows[0]]})
        self.call(worker, "results.append", {"results": [rows[0]]})
        self.assertEqual(self.coord.forecast_status("forecast")["matches"], 1)
        bad = dict(rows[0], outcome="win")
        self.assertFalse(worker.dispatch(message("results.append", {"results": [rows[1], bad]}))["ok"])
        self.assertEqual(self.coord.forecast_status("forecast")["matches"], 1)
        for mutation in ({"source": "real_engine"}, {"unit": "BO3"}, {"scope_sha256": "0" * 64}, {"worker_id": "other-worker"}):
            self.assertFalse(worker.dispatch(message("results.append", {"results": [dict(rows[1], **mutation)]}))["ok"])
        self.assertEqual(self.coord.forecast_status("forecast")["matches"], 1)

    def test_lower_prediction_new_forecast_or_driver_cannot_erase_lineage_alert(self):
        self.call(self.host("duel_worker"), "results.append", {"results": self.synthetic_results(125)})
        for value in (dict(self.forecast, probability=.1), dict(self.forecast, forecast_id="renamed", probability=.1)):
            self.assertFalse(self.coord.dispatch(message("forecast.register", value))["ok"])
        scope = dict(self.scope, actor_policy_sha256="a" * 64)
        self.call(self.coord, "forecast.register", dict(self.forecast, forecast_id="new-driver", scope=scope))
        self.assertEqual(self.coord.forecast_status("new-driver")["matches"], 0)
        self.assertEqual(self.coord.forecast_status("forecast")["matches"], 125)
        self.assertTrue(self.coord.forecast_status("new-driver")["mandatory_rebuild"])
        self.assertFalse(self.coord.dispatch(message("job.schedule", {"job_id": "new-driver-bypass", "forecast_id": "new-driver", "seed": 4, "purpose": "evaluation"}))["ok"])

    def test_mandatory_requires_new_reconstruction_after_alert_not_an_existing_child(self):
        seen = {digest({zone: sorted(cards) for zone, cards in self.candidate["deck"].items()})}
        def child(ident, parent):
            request = copy.deepcopy(self.candidate)
            request.update(candidate_id=ident, parent_candidate_id=parent["candidate_id"], deck=copy.deepcopy(parent["deck"]))
            for position, old in enumerate(parent["deck"]["main"]):
                for code in request["task"]["pool"]:
                    if code == old or parent["deck"]["main"].count(code) >= 3:
                        continue
                    request["deck"]["main"] = list(parent["deck"]["main"])
                    request["deck"]["main"][position] = code
                    signature = digest({zone: sorted(cards) for zone, cards in request["deck"].items()})
                    if signature not in seen:
                        result = self.call(self.coord, "handoff.submit", request)
                        seen.add(signature)
                        return result
            self.fail("synthetic contract fixture has no distinct child deck")

        first = child("existing-child", self.candidate)
        early = child("too-early-grandchild", first)
        self.call(self.coord, "forecast.register", dict(self.forecast, forecast_id="child-forecast", candidate_id=first["candidate_id"]))
        worker = self.host("duel_worker")
        for index in range(125):
            job = self.call(self.coord, "job.schedule", {"job_id": "child-job-" + str(index), "forecast_id": "child-forecast",
                "seed": index, "purpose": "engineering_validation"})
            self.call(worker, "job.claim", {"job_id": job["job_id"], "worker_id": "fixture-worker"})
            self.call(worker, "results.append", {"results": [{"result_id": "child-result-" + str(index),
                "job_id": job["job_id"], "worker_id": "fixture-worker", "forecast_id": "child-forecast",
                "candidate_id": first["candidate_id"], "scope_sha256": job["scope_sha256"],
                "source": "synthetic_contract_test", "unit": "BO1", "outcome": "loss",
                "audit_sha256": digest({"synthetic_index": index}), "diagnosis": "unknown"}]})
        self.assertEqual(first["rebuild_after_forecasts"], [])
        self.assertEqual(early["rebuild_after_forecasts"], [])
        for candidate in (first, early):
            forecast_id = "child-forecast" if candidate is first else "early-forecast"
            if candidate is early:
                self.call(self.coord, "forecast.register", dict(self.forecast, forecast_id=forecast_id, candidate_id=candidate["candidate_id"]))
            route = self.call(self.coord, "route", {"candidate_id": candidate["candidate_id"], "forecast_id": forecast_id,
                "remaining_tasks": 1, "advisory": None})
            self.assertFalse(route["rebuild_validation_eligible"])
            denied = self.coord.dispatch(message("job.schedule", {"job_id": candidate["candidate_id"] + "-bypass",
                "forecast_id": forecast_id, "seed": 200, "purpose": "rebuild_validation"}))
            self.assertFalse(denied["ok"])
            self.assertIn("after the current mandatory alerts", denied["error"]["message"])
        # Retrying the exact old handoff must preserve its original empty anchor.
        retry = {key: first[key] for key in self.candidate}
        self.assertEqual(self.call(self.coord, "handoff.submit", retry), first)
        environment_only = copy.deepcopy(retry)
        environment_only.update(candidate_id="environment-only-child", parent_candidate_id=first["candidate_id"])
        environment_only["task"]["environment"]["environment_id"] += "-new-context"
        same_deck = self.call(self.coord, "handoff.submit", environment_only)
        self.assertEqual(same_deck["rebuild_after_forecasts"], ["child-forecast"])
        same_route = self.call(self.coord, "route", {"candidate_id": same_deck["candidate_id"], "forecast_id": None,
            "remaining_tasks": 1, "advisory": None})
        self.assertFalse(same_route["rebuild_validation_eligible"])
        reparented = copy.deepcopy(retry)
        reparented.update(candidate_id="old-deck-new-parent", parent_candidate_id="candidate")
        reparented["task"]["environment"]["environment_id"] += "-reparented-context"
        renamed = self.call(self.coord, "handoff.submit", reparented)
        self.assertEqual(renamed["rebuild_after_forecasts"], ["child-forecast"])
        renamed_scope = dict(self.scope, actor_policy_sha256="a" * 64)
        self.call(self.coord, "forecast.register", dict(self.forecast, forecast_id="renamed-forecast",
            candidate_id=renamed["candidate_id"], scope=renamed_scope))
        denied = self.coord.dispatch(message("job.schedule", {"job_id": "reparented-bypass", "forecast_id": "renamed-forecast",
            "seed": 200, "purpose": "rebuild_validation"}))
        self.assertFalse(denied["ok"])
        # A previously used core that is different from the mandatory failure
        # is still eligible for explicitly versioned reconstruction/validation.
        old_core = copy.deepcopy(self.candidate)
        old_core.update(candidate_id="revalidate-old-core", parent_candidate_id=first["candidate_id"])
        old_core["task"]["environment"]["environment_id"] += "-revalidated-context"
        recovered_core = self.call(self.coord, "handoff.submit", old_core)
        core_route = self.call(self.coord, "route", {"candidate_id": recovered_core["candidate_id"], "forecast_id": None,
            "remaining_tasks": 1, "advisory": None})
        self.assertTrue(core_route["rebuild_validation_eligible"])
        rebuilt = child("post-alert-reconstruction", early)
        self.assertEqual(rebuilt["rebuild_after_forecasts"], ["child-forecast"])
        self.call(self.coord, "forecast.register", dict(self.forecast, forecast_id="rebuilt-forecast", candidate_id=rebuilt["candidate_id"]))
        route = self.call(self.coord, "route", {"candidate_id": rebuilt["candidate_id"], "forecast_id": "rebuilt-forecast",
            "remaining_tasks": 1, "advisory": None})
        self.assertTrue(route["rebuild_validation_eligible"])
        accepted = self.call(self.coord, "job.schedule", {"job_id": "post-alert-job", "forecast_id": "rebuilt-forecast",
            "seed": 201, "purpose": "rebuild_validation"})
        self.assertEqual(accepted["candidate_id"], rebuilt["candidate_id"])
        self.assertTrue(self.coord.forecast_status("child-forecast")["mandatory_rebuild"])
        self.assertEqual(self.coord.forecast_status("child-forecast")["matches"], 125)

    def test_forecast_is_required_before_job_and_fixed_roles_cannot_override_permissions(self):
        self.assertFalse(self.coord.dispatch(message("job.schedule", {"job_id": "no-forecast", "forecast_id": "missing", "seed": 1, "purpose": "evaluation"}))["ok"])
        for role, method, params in (("monitor", "forecast.register", self.forecast), ("duel_worker", "handoff.submit", self.candidate),
                                     ("coordinator", "results.append", {"results": []}), ("build_goal", "job.schedule", {})):
            reply = self.host(role).dispatch(message(method, params))
            self.assertEqual(reply["error"]["code"], "PERMISSION_DENIED")
        bad = dict(message("status"), role="coordinator")
        self.assertFalse(self.host("monitor").dispatch(bad)["ok"])

    def test_same_deck_order_new_ids_or_goal_changes_cannot_discard_parent(self):
        changed = copy.deepcopy(self.candidate)
        changed["candidate_id"] = "renamed-deck"
        changed["deck"]["main"].reverse()
        for parent in (None, "candidate"):
            changed["parent_candidate_id"] = parent
            self.assertFalse(self.coord.dispatch(message("handoff.submit", changed))["ok"])
        changed["deck"]["main"][0] = 69247929
        changed["task"]["goal"]["card_id"] = changed["task"]["pool"][0]
        changed["task"]["goal"]["starting_conditions"]["requires_opening_hand"] = [changed["task"]["pool"][0]]
        changed["task"]["requirements"].append({"zone": "main", "card_id": changed["task"]["pool"][0], "minimum": 1, "maximum": 3})
        self.assertFalse(self.coord.dispatch(message("handoff.submit", changed))["ok"])

    def test_policy_source_foreign_database_and_missing_readonly_state_are_protected(self):
        for kwargs in ({"policy": FeedbackPolicy(margin=.2), "source": "synthetic_contract_test"},
                       {"policy": self.policy, "source": "real_engine"}):
            with self.assertRaises(ContractError):
                Coordinator(self.path, role="monitor", **kwargs)
        with self.assertRaises(ContractError):
            Coordinator(Path(self.temp.name) / "missing.sqlite", self.policy)
        other = Path(self.temp.name) / "foreign.sqlite"
        with sqlite3.connect(other) as db:
            db.execute("CREATE TABLE unrelated(value TEXT)")
        with self.assertRaises(ContractError):
            Coordinator(other, self.policy, role="coordinator", create=True)
        with sqlite3.connect(other) as db:
            self.assertEqual([r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")], ["unrelated"])

    def test_alpha_spending_and_uncertainty_are_explicit_and_predeclared(self):
        self.assertIsNone(self.policy.assess(24, 0., .9, 1))
        first, second = [self.policy.assess(100, 0., .9, k) for k in (1, 2)]
        self.assertLess(second["per_look_alpha"], first["per_look_alpha"])
        self.assertGreater(second["upper_bound"], first["upper_bound"])
        self.assertEqual(first["calibration"], "pending")
        for value in ({"checkpoints": [100, 1000]}, {"margin": float("nan")}, {"family_alpha": 0}, {"calibration": "validated"}):
            with self.assertRaises(ContractError):
                FeedbackPolicy.from_dict(value)

    def test_zero_budget_cannot_be_overridden_even_for_queued_mandatory_rebuild(self):
        self.call(self.host("duel_worker"), "results.append", {"results": self.synthetic_results(125)})
        result = self.call(self.coord, "route", {"candidate_id": "candidate", "forecast_id": "forecast", "remaining_tasks": 0, "advisory": None})
        self.assertEqual(result["action"], "stop")
        self.assertTrue(result["rebuild_required"])

    def test_job_claim_is_exclusive_and_uncertain_work_is_not_blindly_retried(self):
        self.call(self.coord, "job.schedule", {"job_id": "exclusive-job", "forecast_id": "forecast", "seed": 9, "purpose": "evaluation"})
        worker = self.host("duel_worker")
        self.call(worker, "job.claim", {"job_id": "exclusive-job", "worker_id": "worker-1"})
        self.assertFalse(worker.dispatch(message("job.claim", {"job_id": "exclusive-job", "worker_id": "worker-2"}))["ok"])
        self.assertFalse(self.coord.dispatch(message("job.schedule", {"job_id": "overscheduled", "forecast_id": "forecast", "seed": 10, "purpose": "evaluation"}))["ok"])
