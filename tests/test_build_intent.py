"""Scope-intent feature tests; no LLM, trained model, native engine or API."""

import unittest

from ygo_kito.build_intent import (
    DEFAULT_LEXICON, DomainLexicon, DomainTerm, IntentClassification, classify_build_intent,
)
from ygo_kito.validation import ContractError


class BuildIntentTests(unittest.TestCase):
    def test_narrow_axis_and_broad_function_take_different_paths(self):
        for request in ("用珠泪构筑", "植物族卡组", "想用龙族完成除外", "build a Runick deck"):
            with self.subTest(request=request):
                self.assertEqual(classify_build_intent(request).kind, "narrow")
        for request in ("我要堆墓", "构筑能抽卡并特殊召唤的卡组", "build a banishing deck"):
            with self.subTest(request=request):
                self.assertEqual(classify_build_intent(request).kind, "broad")

    def test_negation_does_not_make_an_excluded_theme_the_axis(self):
        result = classify_build_intent("不要珠泪，只要堆墓")
        self.assertEqual(result.kind, "broad")
        self.assertEqual(result.excluded_terms, ("珠泪哀歌",))
        self.assertEqual(result.narrow_terms, ())
        self.assertEqual(classify_build_intent("not Runick, I want milling").kind, "broad")
        for request in ("不要用珠泪，只想堆墓", "不以神碑为核心，以堆墓为目标", "不想围绕植物，只要除外",
                        "without a Runick splash, milling", "不要星河织梦主题，只想堆墓"):
            with self.subTest(request=request):
                self.assertEqual(classify_build_intent(request).kind, "broad")
        self.assertEqual(classify_build_intent("植物族，不要除外").kind, "narrow")
        self.assertEqual(classify_build_intent("不要堆墓").kind, "ambiguous")

    def test_optional_splash_is_not_a_required_main_axis(self):
        for request in ("神碑只作外挂，以堆墓为目标", "不只珠泪，任意主题的堆墓都可以", "Runick as an optional splash, focus on milling",
                        "Runick is not required, I want milling", "比如珠泪和神碑，想要堆墓"):
            with self.subTest(request=request):
                result = classify_build_intent(request)
                self.assertEqual(result.kind, "broad")
                self.assertFalse(result.narrow_terms)
        self.assertEqual(classify_build_intent("神碑作主轴，堆墓只是例子").kind, "narrow")

    def test_negative_coordination_and_colloquial_requests_preserve_scope(self):
        for request in ("不要珠泪和神碑，只要堆墓", "不要珠泪、神碑，只要堆墓",
                        "不要珠泪或神碑，只要堆墓", "do not use Tear and Runick, I want milling"):
            with self.subTest(request=request):
                result = classify_build_intent(request)
                self.assertEqual(result.kind, "broad")
                self.assertFalse(result.narrow_terms)
                self.assertEqual(result.excluded_terms, ("珠泪哀歌", "神碑"))
        for request in ("不想玩珠泪，想玩堆墓", "不想打神碑，想玩堆墓", "堆墓为主，珠泪可选",
                        "milling, e.g. Runick", "milling, e.g. Tear and Runick",
                        "不想玩星河织梦主题，只要堆墓", "不要用月辉字段，只想堆墓"):
            with self.subTest(request=request):
                result = classify_build_intent(request)
                self.assertEqual(result.kind, "broad")
                self.assertFalse(result.narrow_terms)
        self.assertEqual(classify_build_intent("不要珠泪和神碑").kind, "ambiguous")

    def test_alternative_axes_are_not_mistaken_for_joint_constraints(self):
        for request in ("植物族或者龙族堆墓", "植物族或龙族堆墓", "植物族/龙族堆墓",
                        "plants or dragons for milling", "珠泪或者神碑", "珠泪和神碑二选一"):
            with self.subTest(request=request):
                result = classify_build_intent(request)
                self.assertEqual(result.kind, "ambiguous")
                self.assertLess(result.confidence, 0.5)
        self.assertEqual(classify_build_intent("植物族和龙族堆墓").kind, "narrow")

    def test_combined_requirement_and_unresolved_alternative_differ(self):
        self.assertEqual(classify_build_intent("植物加堆墓").kind, "narrow")
        self.assertEqual(classify_build_intent("植物族，堆墓或者除外").kind, "narrow")
        self.assertEqual(classify_build_intent("植物堆墓或者除外").kind, "narrow")
        self.assertEqual(classify_build_intent("珠泪配神碑，目标是除外").kind, "narrow")
        for request in ("植物/堆墓到底哪种", "植物或者堆墓", "either plants or milling", "星织加堆墓"):
            with self.subTest(request=request):
                result = classify_build_intent(request)
                self.assertEqual(result.kind, "ambiguous")
                self.assertLess(result.confidence, 0.5)
        self.assertEqual(classify_build_intent("不限种族，用植物堆墓").kind, "ambiguous")
        self.assertEqual(classify_build_intent("要珠泪，不要珠泪").kind, "ambiguous")

    def test_unseen_theme_slots_generalize_without_inventing_metadata(self):
        for request, name in (("以星河织梦主题构筑", "星河织梦"), ("用月辉字段构筑", "月辉"),
                              ('以「玻璃花园」主题构筑', "玻璃花园"), ("archetype: astralweavers", "astralweavers"),
                              ("做个星河织梦主题卡组", "星河织梦"), ("主题：星河织梦", "星河织梦")):
            with self.subTest(request=request):
                result = classify_build_intent(request)
                self.assertEqual(result.kind, "narrow")
                self.assertIn(name, result.narrow_terms)
        self.assertEqual(classify_build_intent("星河织梦").kind, "ambiguous")
        self.assertEqual(classify_build_intent("什么主题卡组").kind, "ambiguous")

    def test_dictionary_extension_handles_aliases_without_changing_classifier(self):
        lexicon = DEFAULT_LEXICON.extended(DomainTerm("星河织梦", "theme", ("星织", "astralweavers")))
        for request in ("想用星织堆墓", "build astralweavers for milling"):
            with self.subTest(request=request):
                result = classify_build_intent(request, lexicon)
                self.assertEqual(result.kind, "narrow")
                self.assertEqual(result.narrow_terms, ("星河织梦",))
        self.assertEqual(classify_build_intent("星织").kind, "ambiguous")
        self.assertEqual(DomainLexicon.from_dict(lexicon.to_dict()), lexicon)
        self.assertEqual(DomainLexicon.from_dict({"terms": [{"canonical": "新主题", "kind": "theme"}]}).terms[0].aliases, ())

    def test_english_aliases_use_token_boundaries_and_unicode_normalization(self):
        self.assertEqual(classify_build_intent("build a teardown millennial deck").kind, "ambiguous")
        self.assertEqual(classify_build_intent("ＴＥＡＲＬＡＭＥＮＴＳ").narrow_terms, ("珠泪哀歌",))
        self.assertEqual(classify_build_intent("a dragonfly deck").kind, "ambiguous")
        self.assertEqual(classify_build_intent("Plant milling").kind, "narrow")

    def test_status_is_explicit_and_result_is_json_compatible(self):
        result = classify_build_intent("堆墓").to_dict()
        self.assertEqual(result["classifier_status"], "engineering_untrained")
        self.assertFalse(result["confidence_calibrated"])
        self.assertIsInstance(result["broad_terms"], list)
        self.assertTrue(result["reasons"])

    def test_bad_inputs_and_conflicting_dictionary_aliases_fail(self):
        for value in (None, "", " ", "a" * 4097):
            with self.subTest(value=str(value)[:20]), self.assertRaises(ContractError):
                classify_build_intent(value)
        with self.assertRaises(ContractError):
            DomainLexicon((DomainTerm("a", "theme", ("same",)), DomainTerm("b", "mechanism", ("same",))))
        with self.assertRaises(ContractError):
            classify_build_intent("堆墓", {})
        for value in ({}, {"terms": [], "extra": True}, {"terms": {}},
                      {"terms": [{"canonical": "a", "kind": "theme", "hidden": 1}]},
                      {"terms": [{"canonical": "a", "kind": "theme", "aliases": "alias"}]}):
            with self.subTest(value=value), self.assertRaises(ContractError):
                DomainLexicon.from_dict(value)
        for confidence in (True, -0.1, 1.1, float("nan"), float("inf"), "high"):
            with self.subTest(confidence=confidence), self.assertRaises(ContractError):
                IntentClassification("narrow", confidence)
        with self.assertRaises(ContractError):
            IntentClassification("broad", 0.1)


if __name__ == "__main__":
    unittest.main()
