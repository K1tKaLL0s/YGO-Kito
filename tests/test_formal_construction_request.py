"""Canonical course requests through the existing construction model path."""

from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.run_construction import isolate_trial_kernel
from tests.test_autonomous_construction import fixture
from ygo_kito.autonomous_construction import AutonomousConstructionKernel
from ygo_kito.build_contracts import BuildTask
from ygo_kito.course_construction_request import course_construction_request
from ygo_kito.scenario_course import ScenarioCourse
from ygo_kito.validation import ContractError


class FormalConstructionRequestTests(unittest.TestCase):
    def kernel(self, period):
        task, assets, builder, coordinator = fixture()
        assets.period_id = period
        assets.rows[1]["setcode"] = 385
        goal = {
            "kind": "deck_constraints",
            "constraints": [
                {"id": "old-main", "zones": ["main"], "predicate": {"field": "setcode", "value": 385},
                 "minimum": 12, "maximum": 60},
                {"id": "old-extra", "zones": ["extra"], "predicate": {"field": "setcode", "value": 385},
                 "minimum": 3, "maximum": 15},
            ],
            "preferences": [],
        }
        return AutonomousConstructionKernel(
            builder, coordinator, assets=assets, host_available_ids=assets.rows,
            source_binding={"construction_goal": goal}, allowed_theme_ids=("setcode-181",),
        )

    def test_historical_requests_replace_only_live_task_and_survive_resume(self):
        for period, code in (("2022-07", "2207"), ("2022-10", "2210")):
            with self.subTest(period=period):
                kernel = self.kernel(period)
                legacy = kernel.select_task()
                request = course_construction_request(period)
                batches = []
                model = kernel.builder.models["build_goal"]
                with model.register_forward_pre_hook(lambda _, args: batches.append(args[0]["numbers"][0, 0].tolist())):
                    selected = kernel.select_task(construction_request=request)
                text = f"请构筑一套{code}环境下的珠泪卡组，我希望这套卡组有足够的竞技实力。"
                self.assertEqual(request["text"], text)
                self.assertEqual(selected["construction_request"], request)
                self.assertEqual(selected["theme"]["theme_id"], "setcode-181")
                self.assertEqual(selected["task"]["requirements"], [])
                self.assertEqual(selected["task"]["annotations"], [])
                self.assertEqual([c["minimum"] for c in selected["task"]["goal"]["constraints"]], [1])
                self.assertEqual([c["minimum"] for c in legacy["task"]["goal"]["constraints"]], [12, 3, 1])
                self.assertEqual(batches[0][:6], [float(period == "2022-07"), float(period == "2022-10"), 0., 1., 0., 1.])
                session, _ = kernel._session(selected)
                self.assertEqual(session.logic_context("build_goal")["construction_request"], request)
                state = kernel.state_dict()
                kernel.load_state_dict(state)
                self.assertEqual(kernel.selections[selected["candidate_id"]], selected)
                self.assertEqual(kernel.selections[legacy["candidate_id"]], legacy)
                self.assertEqual(kernel.sessions[selected["candidate_id"]].request, text)

    def test_2610_has_no_user_axis_and_uses_actual_goal_model_choice(self):
        kernel = self.kernel("2026-10")
        request = course_construction_request("2026-10")
        self.assertIsNone(request["theme"])
        self.assertEqual(request["text"], "请构筑一套2610环境下的卡组，我希望这套卡组有足够的竞技实力。")
        proposals = kernel.propose_tasks(construction_request=request)
        self.assertGreater(proposals["enumerated_theme_count"], 1)
        selected = kernel.select_task(proposals)
        self.assertEqual(selected["goal_proposal_origin"], "model_autonomous_theme")
        self.assertEqual(selected["selection_method"], "model_ranked_task_choice")
        self.assertEqual(selected["task"]["requirements"], [])
        wrong = deepcopy(request)
        wrong["theme"] = "tearlaments"
        with self.assertRaisesRegex(ContractError, "differs from the loaded period"):
            kernel.select_task(construction_request=wrong)

    def test_trial_without_budget_override_has_only_its_own_resumable_selection(self):
        original = self.kernel("2022-07")
        previous = original.select_task()
        original._session(previous)
        models = SimpleNamespace(builder=original.builder, coordinator=original.coordinator, kernel=original)
        trial = isolate_trial_kernel(models)
        selected = trial.select_task(construction_request=course_construction_request("2022-07"))
        self.assertEqual(set(trial.selections), {selected["candidate_id"]})
        self.assertEqual(set(original.selections), {previous["candidate_id"]})
        self.assertEqual(set(original.sessions), {previous["candidate_id"]})
        restored = isolate_trial_kernel(models)
        restored.load_state_dict(trial.state_dict())
        self.assertEqual(list(restored.selections.values()), [selected])

    def test_formal_quality_uses_current_period_and_respects_matching_host_policy(self):
        kernel = self.kernel("2022-10")
        request = course_construction_request("2022-10")
        task = BuildTask.from_dict(kernel.select_task(construction_request=request)["task"])
        with patch("ygo_kito.construction_progress.host_construction_quality") as resolve:
            kernel.quality_for_task(task)
            self.assertEqual(resolve.call_args.kwargs["period_id"], "2022-10")
            self.assertEqual(resolve.call_args.kwargs["theme_id"], "setcode-181")

        kernel = self.kernel("2026-10")
        request = course_construction_request("2026-10")
        task = BuildTask.from_dict(kernel.select_task(construction_request=request)["task"])
        with patch.dict(kernel.source_binding, {"construction_quality_reference_id": "main-01-source-v1"}), \
                patch("ygo_kito.construction_progress.host_construction_quality") as resolve:
            kernel.quality_for_task(task)
            self.assertEqual(resolve.call_args.kwargs["period_id"], "2026-10")
            self.assertIsNone(resolve.call_args.kwargs["reference_id"])
        supplied_reference = {"environment": task.environment}
        with patch.dict(kernel.source_binding, {"construction_quality_policy": {},
                                               "construction_quality_reference": supplied_reference}), \
                patch("ygo_kito.construction_progress.quality_policy", return_value={"policy": "explicit"}):
            self.assertEqual(kernel.quality_for_task(task), ({"policy": "explicit"}, supplied_reference))

    def test_training_starts_fresh_once_after_an_old_match_is_closed(self):
        course = object.__new__(ScenarioCourse)
        request = course_construction_request("2022-07")
        selection = {"status": "model_selected_task", "candidate_id": "new", "construction_request": request}
        kernel = SimpleNamespace(select_task=Mock(return_value=selection))
        course.formal_construction = True
        course.config = {"period_id": "2022-07"}
        course.models = SimpleNamespace(kernel=kernel)
        course.selection = {"candidate_id": "old"}
        course.deck = course.construction = object()
        course.events = []
        course.pending = object()
        course.frozen_evaluation = None
        course.prepare_course_construction()
        kernel.select_task.assert_not_called()
        self.assertEqual(course.selection, {"candidate_id": "old"})
        course.pending = None
        course.prepare_course_construction()
        course.prepare_course_construction()
        kernel.select_task.assert_called_once_with(construction_request=request)
        self.assertEqual(course.selection, selection)
        self.assertIsNone(course.deck)
        self.assertIsNone(course.construction)
        self.assertEqual(course.events[0]["previous_task"], "old")
