"""Coordinator-side construction request parsing in Chinese, English and Japanese."""

import unittest

from ygo_kito.coordinator_model import CoordinatorTrainer
from ygo_kito.course_construction_request import course_construction_text
from ygo_kito.validation import ContractError


class CoordinatorConstructionRequestTests(unittest.TestCase):
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
