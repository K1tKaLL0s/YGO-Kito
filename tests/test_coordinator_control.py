"""Isolated controller contracts. Synthetic rows are not played matches.

The real network, build encoder, SQLite coordinator and course driver execute;
native games are replaced only at the explicitly injected monitoring boundary.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch

# Windows lacks the Linux course locking module. These tests never enter an
# engine/course lock: fail loudly if an isolated test accidentally tries to.
if sys.platform == "win32" and "fcntl" not in sys.modules:
    locking = ModuleType("fcntl")
    locking.LOCK_EX, locking.LOCK_NB, locking.LOCK_UN = 2, 4, 8
    def forbidden_lock(*args):
        raise AssertionError("native/course file locking is outside isolated controller tests")
    locking.flock = forbidden_lock
    sys.modules["fcntl"] = locking

import torch
from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.build_model import BuildEncoder, BuildModelConfig
from ygo_kito.coord_contracts import FeedbackPolicy, ROUTES
from ygo_kito.coordinator import Coordinator
from ygo_kito.coordinator_model import CoordinatorTrainer, CoordinatorModelConfig, public_scope_features, engineering_examples
from ygo_kito.model_group import call, route_with_model
from ygo_kito.validation import ContractError, canonical_json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from local_course_forecast import CourseForecast, canonical_deck
from local_foundation_course import execute_cycle
from local_foundation_course import CycleBudget, CycleBudgetExhausted

TASK = BuildTask.from_dict(json.loads((ROOT / "configs/build-engineering-v1.json").read_text()))
DECK = canonical_deck(DeckParts.from_dict(json.loads((ROOT / "docs/reports/2026-10-23-m3b-best-deck.json").read_text())))


def changed_deck(deck, exclude=()):
    for old in set(deck.main):
        for code in TASK.pool:
            if code != old and deck.main.count(code) < 3:
                cards = list(deck.main); cards[cards.index(old)] = code
                result = canonical_deck(DeckParts(tuple(cards), deck.extra, deck.side))
                if digest(result.to_dict()) not in exclude:
                    return result
    raise AssertionError("fixture needs a distinct deck")


def scope(actor="3", opponent=DECK, unit="BO1"):
    return {"actor_policy_sha256": actor * 64, "duel_lora": None, "opponents": [{"opponent_id": "fixture-opponent",
        "deck_sha256": digest(opponent.to_dict()), "driver_sha256": "5" * 64, "weight": 1.}],
        "initiative_weights": [.5, .5], "unit": unit, "prediction_target": "win_rate", "versions": TASK.environment["versions"]}


def builder():
    # Declared public numeric card facts, not a neural-output stub. The actual
    # BuildEncoder encodes concrete typed goals, inventories and quantities.
    facts = {code: [(code % p) / p for p in (7, 11, 13, 17, 19, 23)] for code in TASK.pool}
    rows={code:dict(id=code,alias=0,ot=1,type=33,race=1,setcode=0,level=4,attribute=1,
                   atk=1000,**{'def':1000},name='synthetic-'+str(code),desc='') for code in TASK.pool}
    assets = SimpleNamespace(check_task=lambda task: None, facts=lambda code: facts[code],rows=rows,
                             receipt={'resources':{'cards':digest(rows)}})
    return SimpleNamespace(encoder=BuildEncoder(TASK, assets, BuildModelConfig()))


def context():
    return deepcopy(engineering_examples()["records"][3]["context"])


def configure_policy(trainer):
    """A deterministic nonconstant policy, with the actual neural forward path."""
    with torch.no_grad():
        for parameter in trainer.model.parameters():
            parameter.zero_()
        trainer.model.scope_projection.weight[0, 0] = 1
        trainer.model.route_head.bias.fill_(-10)
        trainer.model.route_head.weight[ROUTES.index("train_duel"), 0] = -4
        trainer.model.route_head.bias[ROUTES.index("train_duel")] = 2
        trainer.model.route_head.weight[ROUTES.index("evaluate_duel"), 0] = 4
        trainer.model.route_head.bias[ROUTES.index("evaluate_duel")] = -2
        trainer.model.forecast_head.weight[0, 0] = 1
        trainer.model.budget_head.weight[0, 0] = 2


class LedgerFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT.parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.host = Coordinator(self.root / "ledger.sqlite3", FeedbackPolicy(), role="coordinator", source="synthetic_contract_test", create=True)
        self.request = {"candidate_id": "candidate", "parent_candidate_id": None, "task": TASK.to_dict(), "deck": DECK.to_dict(),
            "build_models": {"build_goal": "1" * 64, "build_optimizer": "2" * 64}}
        call(self.host, "handoff.submit", self.request)
        self.register("forecast", "candidate", scope(), .9)

    def register(self, ident, candidate, frozen_scope, probability=.9):
        return call(self.host, "forecast.register", {"forecast_id": ident, "candidate_id": candidate, "probability": probability,
            "origin_role": "coordinator", "model_sha256": "6" * 64, "calibration": "pending", "scope": frozen_scope})

    def results(self, forecast, count, outcome="loss"):
        status = self.host.forecast_status(forecast)
        candidate = status["forecast"]["candidate_id"]
        # Fixture leased envelopes exercise production result admission and
        # policy checks; no native executor or fabricated "real_engine" source.
        worker = Coordinator(self.host.path, self.host.policy, role="duel_worker", source=self.host.source)
        rows = []
        with self.host._db() as db, db:
            for n in range(status["matches"], status["matches"] + count):
                ident = forecast + "-fixture-" + str(n)
                info = {"candidate_id": candidate, "forecast_id": forecast, "scope_sha256": status["scope_sha256"], "scope": status["forecast"]["scope"]}
                db.execute("INSERT INTO jobs VALUES(?,?,?,'leased','fixture')", (ident, forecast, canonical_json(info)))
                rows.append({"result_id": ident, "job_id": ident, "worker_id": "fixture", "forecast_id": forecast, "candidate_id": candidate,
                    "scope_sha256": status["scope_sha256"], "source": self.host.source, "unit": status["forecast"]["scope"]["unit"],
                    "outcome": outcome, "audit_sha256": digest(ident), "diagnosis": "unknown"})
        return call(worker, "results.append", {"results": rows})[forecast]

    def child(self, ident, parent, deck):
        return call(self.host, "handoff.submit", dict(self.request, candidate_id=ident, parent_candidate_id=parent, deck=deck.to_dict()))

    def test_real_policy_controls_action_and_allocation_but_hard_budget_wins(self):
        trainer = CoordinatorTrainer(); configure_policy(trainer)
        a, b = [0.1] * 64, [0.9] * 64
        options = {"allowed_routes": ["train_duel", "evaluate_duel", "stop"], "max_units": 8}
        first, _ = route_with_model(self.host, trainer, "candidate", "forecast", 8, features=a, **options)
        second, _ = route_with_model(self.host, trainer, "candidate", "forecast", 8, features=b, **options)
        self.assertEqual(first["action"], "train_duel")
        self.assertEqual(second["action"], "evaluate_duel")
        self.assertEqual(first["mode"], "learned_control")
        self.assertLess(first["budget_units"], second["budget_units"])
        self.assertLessEqual(second["budget_units"], 8)
        stopped, _ = route_with_model(self.host, trainer, "candidate", "forecast", 0, features=b, max_units=0)
        self.assertEqual((stopped["action"], stopped["budget_units"]), ("stop", 0))
        self.results("forecast", 125)
        mandatory, _ = route_with_model(self.host, trainer, "candidate", "forecast", 8, features=b, **options)
        self.assertEqual(mandatory["action"], "build_goal")
        with self.assertRaises(ContractError):
            call(self.host, "job.schedule", {"job_id": "bypass", "forecast_id": "forecast", "seed": 1, "purpose": "evaluation"})

    def test_scope_counts_are_independent_and_prediction_immutable(self):
        self.results("forecast", 3)
        for key, frozen in (("actor", scope("4")), ("opponent", scope(opponent=changed_deck(DECK))), ("unit", scope(unit="BO3"))):
            self.register(key, "candidate", frozen, .4)
            self.assertEqual(self.host.forecast_status(key)["matches"], 0)
        with self.assertRaises(ContractError):
            self.register("forecast", "candidate", scope(), .1)
        with self.assertRaises(ContractError):
            self.register("renamed", "candidate", scope(), .1)
        self.assertEqual(self.host.forecast_status("forecast")["matches"], 3)

    def test_rebuild_needs_new_child_validation_and_later_cycles_alert_again(self):
        failed = self.results("forecast", 125)
        self.assertTrue(failed["mandatory_rebuild"])
        self.assertTrue(any(a["n"] <= 100 for a in failed["alerts"] if a["kind"] == "reevaluate"))
        with self.assertRaises(ContractError):
            call(self.host, "rebuild.resolve", {"candidate_id": "candidate", "validation_forecast_id": "forecast"})
        changed = changed_deck(DECK)
        self.child("reconstruction", "candidate", changed)
        self.register("validation", "reconstruction", scope("7"), .9)
        with self.assertRaises(ContractError):
            call(self.host, "rebuild.resolve", {"candidate_id": "reconstruction", "validation_forecast_id": "validation"})
        self.results("validation", 25, "win")
        receipt = call(self.host, "rebuild.resolve", {"candidate_id": "reconstruction", "validation_forecast_id": "validation"})
        self.assertTrue(receipt["closed"])
        self.assertFalse(self.host.forecast_status("validation")["mandatory_rebuild"])
        self.assertTrue(self.host.forecast_status("forecast")["alerts"])  # History stays.
        self.register("next-cycle", "reconstruction", scope("8"), .9)
        again = self.results("next-cycle", 1000)
        self.assertTrue(again["mandatory_rebuild"])
        self.assertTrue(any(a["kind"] == "reevaluate" for a in again["alerts"]))

    def test_reconstruction_own_warning_returns_to_build_and_exhausted_window_cannot_spin(self):
        self.results('forecast',125)
        changed=changed_deck(DECK)
        self.child('child','candidate',changed);self.register('child-window','child',scope('7'),.9)
        self.results('child-window',25)
        trainer=CoordinatorTrainer();configure_policy(trainer)
        route,_=route_with_model(self.host,trainer,'child','child-window',8,features=[.9]*64,max_units=8)
        self.assertIn(route['action'],('build_goal','build_optimizer'))
        with self.assertRaises(ContractError):
            call(self.host,'rebuild.resolve',{'candidate_id':'child','validation_forecast_id':'child-window'})
        fresh=changed_deck(changed,exclude=(digest(DECK.to_dict()),digest(changed.to_dict())))
        self.child('fresh','child',fresh);self.register('fresh-window','fresh',scope('8'),.9)
        self.results('fresh-window',25,'win')
        call(self.host,'rebuild.resolve',{'candidate_id':'fresh','validation_forecast_id':'fresh-window'})
        self.assertFalse(self.host.forecast_status('fresh-window')['pending_review'])
        self.results('fresh-window',975,'win')
        route,_=route_with_model(self.host,trainer,'fresh','fresh-window',8,features=[.9]*64,max_units=8)
        self.assertEqual(route['action'],'stop')
        self.assertEqual(route['budget_units'],0)

    def test_warning_review_can_keep_deck_but_cannot_waive_later_mandatory_rebuild(self):
        self.results('forecast',100)
        receipt={'kind':'completed_four_step_construction_review_v2','cycle_id':'review-1-0','task_sha256':TASK.sha256,
            'deployed_deck_sha256':digest(DECK.to_dict()),'trace_sha256':'a'*64,'task_verified':True,'basic_cb_inference_performed':True,
            'roles':['build_goal','build_optimizer','build_goal','build_optimizer'],'reviewed_forecasts':['forecast']}
        self.host.record_construction_review('candidate',receipt)
        self.assertFalse(self.host.forecast_status('forecast')['pending_review'])
        self.assertTrue(self.host.forecast_status('forecast')['alerts'])
        self.results('forecast',25)
        with self.assertRaises(ContractError):self.host.record_construction_review('candidate',receipt)
        self.assertTrue(self.host.forecast_status('forecast')['mandatory_rebuild'])


class ScopedNetworkTests(unittest.TestCase):
    def test_legacy_upgrade_is_explicit_and_preserves_old_tensors_and_moments(self):
        from ygo_kito.duel_model import parameter_digest
        trainer = CoordinatorTrainer(CoordinatorModelConfig(steps=4))
        trainer.step()
        legacy = deepcopy(trainer.state())
        for name in ("scope_projection.weight", "budget_head.weight", "budget_head.bias"):
            legacy["model"].pop(name)
        legacy["optimizer"]["param_groups"][0]["params"] = list(range(8))
        legacy["feature_version"] = "coordinator-aggregate-context-v1"
        legacy["model_sha256"] = parameter_digest(SimpleNamespace(state_dict=lambda: legacy["model"]))
        with self.assertRaises(ContractError):
            CoordinatorTrainer.restore(legacy)
        upgraded, receipt = CoordinatorTrainer.upgrade_aggregate_state(legacy)
        self.assertFalse(receipt["training_executed"])
        for name, value in legacy["model"].items():
            self.assertTrue(torch.equal(value, upgraded["model"][name]))
        for key, values in legacy["optimizer"]["state"].items():
            for name, value in values.items():
                self.assertTrue(torch.equal(value, upgraded["optimizer"]["state"][key][name]))
        self.assertEqual(upgraded["updates"], legacy["updates"])
        CoordinatorTrainer.restore(upgraded)

    def test_concrete_card_goal_opponent_actor_and_unit_reach_model_and_restore(self):
        actual_builder = builder()
        frozen = scope()
        first = public_scope_features(actual_builder, TASK, DECK, frozen, {"fixture-opponent": DECK})
        other = changed_deck(DECK)
        second = public_scope_features(actual_builder, TASK, other, scope("4", unit="BO3"), {"fixture-opponent": DECK})
        self.assertEqual(len(first), 64)
        self.assertNotEqual(first, second)
        trainer = CoordinatorTrainer(CoordinatorModelConfig(steps=4))
        prediction_a, prediction_b = trainer.forecast(context(), first), trainer.forecast(context(), second)
        self.assertNotEqual(prediction_a["probability"], prediction_b["probability"])
        row = {"context": context(), "scope_features": first, "route_label": "evaluate_duel", "forecast_target": .8,
            "budget_target": .25, "provenance": {"dataset_id": "fixture-training", "record_id": "one",
                "source": "explicit-isolated-fixture-not-played-matches", "evidence_sha256": "a" * 64}}
        examples = {"source": "host_logged_supervision_v1", "records": [row], "real_win_rate_supervision": False, "sha256": digest([row])}
        before = trainer.model.budget_head.weight.detach().clone()
        update = trainer.step(examples)
        self.assertEqual(update["budget_supervised_rows"], 1)
        self.assertFalse(torch.equal(before, trainer.model.budget_head.weight))
        restored = CoordinatorTrainer.restore(deepcopy(trainer.state()))
        self.assertEqual(restored.forecast(context(), first), trainer.forecast(context(), first))
        route = deepcopy(trainer.model.route_head.state_dict())
        row.update(route_label=None); row.pop("budget_target"); examples["sha256"] = digest([row])
        trainer.step(examples)
        self.assertTrue(all(torch.equal(route[k], v) for k, v in trainer.model.route_head.state_dict().items()))


class CourseControllerTests(unittest.TestCase):
    def test_basic_cb_handoff_binds_constructed_task_and_deck_without_final_cb(self):
        assets=SimpleNamespace(check_task=lambda t:None,validate=lambda t,d:None)
        proof={'status':'verified_success','task_sha256':TASK.sha256,'deck_sha256':digest(DECK.to_dict())}
        basic={'task_sha256':TASK.sha256,'subject_deck_sha256':digest(DECK.to_dict()),'engine_validation':proof}
        result={'basic_cb':basic,'best':{'deck':DECK.to_dict()},'cb_verified':True,'alternation_completed':True}
        instance=object.__new__(CourseForecast);instance.course=SimpleNamespace(construction=result)
        self.assertEqual(instance._existing_candidate_proof(TASK,DECK,assets),proof)
        result['basic_cb']['subject_deck_sha256']='f'*64
        with self.assertRaises(ContractError):instance._existing_candidate_proof(TASK,DECK,assets)

    def test_expensive_children_share_remaining_deadline_and_noop_monitor_is_not_executed(self):
        elapsed=[0.]
        course=SimpleNamespace(active_seconds=95.,config={'wall_seconds':100},desired='ready',save=lambda:None)
        budget=CycleBudget(course,clock=lambda:elapsed[0])
        class Forecast:
            value={'decisions':[{}],'active_forecast':'fixture'}
            def decide(self,n):return {'action':'build_goal','budget_units':1}
            def status(self):return {'mandatory_rebuild':False}
            def construction_completed(self):raise AssertionError('unfinished construction cannot be accepted')
        seen=[]
        def construction(*args,**kwargs):
            seen.append(kwargs['budget'].remaining())
            elapsed[0]+=4
            kwargs['budget'].check('before_paired_case',required=2)
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp,patch('local_foundation_course.CycleBudget',return_value=budget):
            result=execute_cycle(course,Forecast(),construction,None,Path(tmp),Path(tmp)/'stop',lambda *a,**k:None,1)
        self.assertEqual(seen,[5.]);self.assertTrue(result['paused']);self.assertEqual(result['executed_units'],0)
        self.assertEqual(result['reason'],'construction_budget_boundary')
        class Exhausted(Forecast):
            def decide(self,n):return {'action':'evaluate_duel','budget_units':1}
            def evaluate(self,n,*,budget=None):return 0
        course.active_seconds=0;course.desired='ready'
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp:
            result=execute_cycle(course,Exhausted(),construction,None,Path(tmp),Path(tmp)/'stop',lambda *a,**k:None,1)
        self.assertTrue(result['paused']);self.assertEqual(result['executed_units'],0)
    def test_controller_scopes_survive_restart_without_backfilling_or_losing_counts(self):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp:
            root = Path(tmp)
            legacy = root / "actual-forecast-ledger.json"
            legacy.write_text(json.dumps({"alerts": [], "outcomes": [{"old": True}]}))
            old_bytes = legacy.read_bytes()
            host = Coordinator(root / "ledger.sqlite3", FeedbackPolicy(), role="coordinator", source="synthetic_contract_test", create=True)
            model = CoordinatorTrainer(); configure_policy(model)
            actual_builder = builder()
            course = SimpleNamespace(deck=DECK, _task=lambda: TASK, assets=None,
                stage=lambda:'bots-bo1',
                models=SimpleNamespace(builder=actual_builder, coordinator=model,
                    versions=lambda: {"duel": "3" * 64, "build_goal": "1" * 64, "build_optimizer": "2" * 64}))
            class FixtureController(CourseForecast):
                frozen_scope = scope()
                def _scope(self): return self.frozen_scope, {"fixture-opponent": DECK}
            seen = []
            def monitor(job):
                seen.append(job)
                return {"outcome": "win", "audit_sha256": digest(job), "diagnosis": "none"}
            snapshots={}
            def capture(ident,receipt):
                if ident not in snapshots:snapshots[ident]=deepcopy(course.models)
                return snapshots[ident]
            controller = FixtureController(course, root, host=host, evaluation_runner=monitor,snapshot_factory=capture)
            controller.before(); original = controller.value["active_forecast"]
            controller.evaluate(3)
            self.assertEqual(controller.status()["matches"], 3)
            self.assertEqual(legacy.read_bytes(), old_bytes)
            self.assertFalse(controller.value["trained_artifacts"])
            restored = FixtureController(course, root, host=host, evaluation_runner=monitor,snapshot_factory=capture)
            restored.before()
            self.assertEqual(restored.value["active_forecast"], original)
            self.assertEqual(restored.status()["matches"], 3)
            restored.frozen_scope = scope("4")
            restored.before()
            self.assertEqual(restored.value["active_forecast"], original)
            restored.evaluate(8)
            restored.frozen_scope=scope("5");restored.evaluate(8)
            restored.frozen_scope=scope("6");restored.evaluate(8)
            self.assertEqual(restored.status()["matches"],27)
            self.assertEqual(len(restored.status()["checks"]),1)
            self.assertEqual(len(restored.value['forecasts']),1)
            self.assertEqual(host.forecast_status(original)["matches"],27)
            self.assertEqual(len(seen),27)

    def test_driver_runs_selected_kind_and_budget_between_complete_construction_cycles(self):
        calls = []
        course = SimpleNamespace(active_seconds=0., config={"wall_seconds": 1000}, desired="ready",
            models=SimpleNamespace(duel=SimpleNamespace(config=SimpleNamespace(episode_seconds=30))),
            save=lambda: None, stage=lambda: "bots-bo1", run=lambda n: calls.append(("train", n)))
        state = {"mandatory_rebuild": False, "rebuild_validation_eligible": False}
        class Forecast:
            value = {"active_forecast": "fixture", "decisions": [{}]}
            action = "train_duel"
            def decide(self, cap): return {"action":self.action,"budget_units":min(cap, 2)}
            def status(self): return state
            def before_training(self): calls.append(("sealed",))
            def train_closed_outcomes(self): calls.append(("label",))
            def evaluate(self, n, *, budget=None): calls.append(("evaluate", n));return n
            def construction_completed(self, **kwargs): calls.append(("accepted-child-not-resolved",))
        forecasts = Forecast()
        def construction(*args, **kwargs):
            calls.append(("construction", kwargs["force_rebuild"], kwargs["cycle_id"]))
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as tmp:
            stop = Path(tmp) / "stop"
            execute_cycle(course, forecasts, construction, None, Path(tmp), stop, lambda *a,**k:None, 3)
            self.assertEqual(calls, [("sealed",), ("train", 1), ("label",)] * 2)
            calls.clear(); forecasts.action = "evaluate_duel"
            execute_cycle(course, forecasts, construction, None, Path(tmp), stop, lambda *a,**k:None, 1)
            self.assertEqual(calls, [("evaluate", 1)])
            calls.clear(); forecasts.action = "build_goal"; state["mandatory_rebuild"] = True
            execute_cycle(course, forecasts, construction, None, Path(tmp), stop, lambda *a,**k:None, 1)
            self.assertEqual(calls[0], ("construction", True, "1-0"))
            self.assertTrue(state["mandatory_rebuild"])
            calls.clear(); forecasts.action = "stop"
            result = execute_cycle(course, forecasts, construction, None, Path(tmp), stop, lambda *a,**k:None, 3)
            self.assertTrue(result["paused"])
            self.assertFalse(calls)


if __name__ == "__main__":
    unittest.main()
