"""Canonical course requests through the existing construction model path."""

from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.run_construction import isolate_trial_kernel
from tests.test_autonomous_construction import fixture
from ygo_kito.autonomous_construction import AutonomousConstructionKernel
from ygo_kito.build_contracts import BuildTask
from ygo_kito.coordinator_model import CoordinatorTrainer
from ygo_kito.course_construction_request import course_construction_text
from ygo_kito.scenario_course import ScenarioCourse
from ygo_kito.validation import ContractError


def parse_course_default(period):
    return CoordinatorTrainer.parse_construction_request(course_construction_text(period), expected_period=period)


class FormalConstructionRequestTests(unittest.TestCase):
    def test_coordinator_parses_paraphrases_with_no_period_to_theme_lookup(self):
        examples = (
            ("给我组一套能参赛的珠泪哀歌，按２０２２．７的禁限卡表来。", "2022-07", "tearlaments"),
            ("用22年10月的OCG环境构筑珠泪，我想拿去打比赛。", "2022-10", "tearlaments"),
            ("用 26 年 10 月 OCG 的卡池，卡组有竞争力就好，主题随你。", "2026-10", None),
            ("请在2610环境下构筑一套卡组，我想拿去比赛。", "2026-10", None),
            ("请用2207卡池做一套有竞争力的卡组，主题不限。", "2022-07", None),
        )
        for text, period, theme in examples:
            with self.subTest(text=text):
                self.assertEqual(CoordinatorTrainer.parse_construction_request(text, expected_period=period),
                    {"text": text, "period_id": period, "theme": theme, "objective": "competitive"})

    def test_coordinator_reports_incompatible_or_unsupported_intent(self):
        examples = (
            ("2207或2210随便，组一套可以参赛的珠泪。", "one supported period"),
            ("请给我一个能打比赛的珠泪构筑。", "one supported period"),
            ("用2207禁限卡表组珠泪，只打娱乐，不追求竞技强度。", "affirmative competitive goal"),
            ("用2207组珠泪或神碑，要有竞争力。", "unsupported or conflicting theme"),
            ("用2610的环境，主题：黄金国，能参赛。", "unsupported or conflicting theme"),
            ("请构筑2610环境下的银河眼卡组，要有竞技实力。", "unsupported named theme"),
            ("请构筑2610环境下的银河眼竞技卡组。", "unsupported named theme"),
            ("不要构筑2207环境下的珠泪卡组，我希望它具备竞技实力。", "declines building a deck"),
            ("用2207环境组竞技珠泪，然后进入CB推理。", "another unsupported operation"),
            ("用2207组一套能参赛的珠泪，至少12张珠泪卡。", "card-count requirements"),
        )
        for text, reason in examples:
            with self.subTest(text=text), self.assertRaisesRegex(ContractError, reason):
                CoordinatorTrainer.parse_construction_request(text)
        with self.assertRaisesRegex(ContractError, "differs from the loaded period"):
            CoordinatorTrainer.parse_construction_request(course_construction_text("2022-10"), expected_period="2022-07")

    def test_coordinator_parses_english_and_japanese_fixed_and_autonomous_requests(self):
        examples = (
            ("Build a competitive Tearlaments deck for the July 2022 OCG format.", "2022-07", "tearlaments"),
            ("Please make a tournament-ready Tearlaments deck using the Oct. 2022 banlist.", "2022-10", "tearlaments"),
            ("Build me a deck for the October 2026 format. It should be competitive.", "2026-10", None),
            ("2022年7月OCG環境でティアラメンツの大会向けデッキを構築してください。", "2022-07", "tearlaments"),
            ("2210のレギュレーションで競技向けのティアラメンツデッキを組んでください。", "2022-10", "tearlaments"),
            ("2026年10月のOCG環境で、大会で使えるデッキを組んでください。テーマはお任せします。", "2026-10", None),
            ("2610で競技性のあるデッキを組んでください。", "2026-10", None),
        )
        for text, period, theme in examples:
            with self.subTest(text=text):
                self.assertEqual(CoordinatorTrainer.parse_construction_request(text, expected_period=period),
                    {"text": text, "period_id": period, "theme": theme, "objective": "competitive"})

    def test_coordinator_keeps_english_and_japanese_request_boundaries(self):
        examples = (
            ("Build a competitive Sky Striker deck for October 2026.", "unsupported named theme"),
            ("Don't build a competitive Tearlaments deck for July 2022.", "declines building"),
            ("Build a non-competitive Tearlaments deck for July 2022.", "affirmative competitive goal"),
            ("Build a competitive deck for October 2026, then run CB.", "another unsupported operation"),
            ("2026年10月環境で銀河眼の競技向けデッキを組んでください。", "unsupported named theme"),
            ("2022年7月環境の競技向けティアラメンツデッキは組まないでください。", "declines building"),
            ("2022年7月環境のデッキを作成してください。競技向けは不要です。", "affirmative competitive goal"),
            ("2022年7月環境の競技デッキをティアラメンツ抜きで作成してください。", "unsupported or conflicting theme"),
        )
        for text, reason in examples:
            with self.subTest(text=text), self.assertRaisesRegex(ContractError, reason):
                CoordinatorTrainer.parse_construction_request(text)

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
                request = parse_course_default(period)
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
        request = parse_course_default("2026-10")
        self.assertIsNone(request["theme"])
        self.assertEqual(request["text"], "请构筑一套2610环境下的卡组，我希望这套卡组有足够的竞技实力。")
        proposals = kernel.propose_tasks(construction_request=request)
        self.assertGreater(proposals["enumerated_theme_count"], 1)
        selected = kernel.select_task(proposals)
        self.assertEqual(selected["goal_proposal_origin"], "model_autonomous_theme")
        self.assertEqual(selected["selection_method"], "model_ranked_task_choice")
        self.assertEqual(selected["task"]["requirements"], [])
        wrong = deepcopy(request)
        wrong["period_id"] = "2022-07"
        with self.assertRaisesRegex(ContractError, "differs from the loaded period"):
            kernel.select_task(construction_request=wrong)

    def test_trial_without_budget_override_has_only_its_own_resumable_selection(self):
        original = self.kernel("2022-07")
        previous = original.select_task()
        original._session(previous)
        models = SimpleNamespace(builder=original.builder, coordinator=original.coordinator, kernel=original)
        trial = isolate_trial_kernel(models)
        text = "按2022年7月禁限卡表给我做珠泪哀歌，要能参赛。"
        request = trial.coordinator.parse_construction_request(text, expected_period="2022-07")
        selected = trial.select_task(construction_request=request)
        self.assertEqual(set(trial.selections), {selected["candidate_id"]})
        self.assertEqual(set(original.selections), {previous["candidate_id"]})
        self.assertEqual(set(original.sessions), {previous["candidate_id"]})
        restored = isolate_trial_kernel(models)
        with patch.object(restored.coordinator, "parse_construction_request") as parse:
            restored.load_state_dict(trial.state_dict())
        parse.assert_not_called()
        self.assertEqual(list(restored.selections.values()), [selected])
        self.assertEqual(selected["construction_request"]["text"], text)

    def test_formal_quality_uses_current_period_and_respects_matching_host_policy(self):
        kernel = self.kernel("2022-10")
        request = parse_course_default("2022-10")
        task = BuildTask.from_dict(kernel.select_task(construction_request=request)["task"])
        with patch("ygo_kito.construction_progress.host_construction_quality") as resolve:
            kernel.quality_for_task(task)
            self.assertEqual(resolve.call_args.kwargs["period_id"], "2022-10")
            self.assertEqual(resolve.call_args.kwargs["theme_id"], "setcode-181")

        kernel = self.kernel("2026-10")
        request = parse_course_default("2026-10")
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
        request = parse_course_default("2022-07")
        selection = {"status": "model_selected_task", "candidate_id": "new", "construction_request": request}
        kernel = SimpleNamespace(select_task=Mock(return_value=selection))
        course.formal_construction = True
        course.config = {"period_id": "2022-07"}
        coordinator = SimpleNamespace(parse_construction_request=Mock(wraps=CoordinatorTrainer.parse_construction_request))
        course.models = SimpleNamespace(kernel=kernel, coordinator=coordinator)
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
        coordinator.parse_construction_request.assert_called_once_with(request["text"], expected_period="2022-07")
        kernel.select_task.assert_called_once_with(construction_request=request)
        self.assertEqual(course.selection, selection)
        self.assertIsNone(course.deck)
        self.assertIsNone(course.construction)
        self.assertEqual(course.events[0]["previous_task"], "old")
