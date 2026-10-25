"""Tiny synthetic fitting checks the classifier code, never general capability."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from ygo_kito.build_intent import DEFAULT_LEXICON, DomainTerm, classify_build_intent
from ygo_kito.intent_model import IntentFeatureConfig, LinearIntentClassifier
from ygo_kito.validation import ContractError


EXAMPLES = [
    {"text": text, "label": label}
    for label, texts in (
        ("narrow", ("用珠泪构筑", "植物族卡组", "龙族除外卡组", "以月辉字段构筑", "Runick deck", "plants for milling")),
        ("broad", ("我要堆墓", "只想除外", "堆墓为主，珠泪可选", "不要珠泪和神碑，只要堆墓", "milling, e.g. Runick", "banishing deck")),
        ("ambiguous", ("植物或者堆墓", "植物族或者龙族堆墓", "珠泪和神碑二选一", "星织加堆墓", "不知道做什么", "either plants or milling")),
    ) for text in texts
]


class IntentModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = LinearIntentClassifier()
        cls.report = cls.model.fit(EXAMPLES, epochs=180, learning_rate=3.0)

    def test_real_fit_changes_weights_decreases_loss_and_emits_learned_scores(self):
        self.assertEqual(self.report["optimizer_steps"], 180)
        self.assertEqual(self.report["example_count"], 18)
        self.assertLess(self.report["final_loss"], self.report["initial_loss"])
        self.assertTrue(any(weight != 0 for row in self.model.weights for weight in row))
        for example in EXAMPLES:
            with self.subTest(text=example["text"]):
                result = self.model.predict(example["text"])
                self.assertEqual(result.kind, example["label"])
                scores = dict(result.scores)
                self.assertAlmostEqual(sum(scores.values()), 1.0)
                self.assertEqual(result.confidence, max(scores.values()))
                ranked = sorted(scores.values(), reverse=True)
                self.assertEqual(result.margin, ranked[0] - ranked[1])
                self.assertEqual(result.classifier_status, "cpu_synthetic_trained")
                self.assertFalse(result.to_dict()["generalization_verified"])
                self.assertFalse(result.to_dict()["confidence_calibrated"])

    def test_untrained_classifier_abstains_even_when_auxiliary_rule_is_certain(self):
        result = LinearIntentClassifier().predict("植物族堆墓")
        self.assertEqual(result.kind, "ambiguous")
        self.assertIn("untrained_classifier", result.reasons)
        self.assertEqual(result.classifier_status, "untrained")
        self.assertAlmostEqual(result.confidence, 1 / 3)
        self.assertEqual(result.margin, 0)
        self.assertEqual(classify_build_intent("植物族堆墓", classifier=LinearIntentClassifier()).kind, "ambiguous")

    def test_auxiliary_scope_rules_do_not_decide_the_learned_label(self):
        # Deliberately contrary labels test implementation independence; they are
        # not a useful language dataset or a claim that the flipped goal is right.
        rows = [{"text": "珠泪", "label": "broad"},
                {"text": "堆墓", "label": "narrow"},
                {"text": "怎么办", "label": "ambiguous"}]
        contrary = LinearIntentClassifier()
        contrary.fit(rows, epochs=150, learning_rate=3.0)
        self.assertEqual(classify_build_intent("珠泪").kind, "narrow")
        self.assertEqual(contrary.predict("珠泪").kind, "broad")
        self.assertEqual(contrary.predict("堆墓").kind, "narrow")

    def test_learned_confidence_margin_and_oov_can_each_abstain(self):
        weak = LinearIntentClassifier()
        weak.fit(EXAMPLES, epochs=1, learning_rate=0.000001)
        self.assertEqual(weak.predict("植物族卡组").kind, "ambiguous")
        self.assertIn("low_learned_confidence", weak.predict("植物族卡组").reasons)
        self.assertIn("low_learned_margin", weak.predict("植物族卡组").reasons)
        unknown = self.model.predict("qzxvkj 987654321 😀🦖🪐")
        self.assertEqual(unknown.kind, "ambiguous")
        self.assertIn("lexical_out_of_vocabulary", unknown.reasons)
        self.assertLess(unknown.lexical_coverage, self.model.config.min_lexical_coverage)
        margin_model = LinearIntentClassifier(config=replace(IntentFeatureConfig(), min_margin=1.0))
        margin_model.fit(EXAMPLES, epochs=100, learning_rate=3.0)
        self.assertIn("low_learned_margin", margin_model.predict("植物族卡组").reasons)

    def test_exact_save_load_binds_weights_vocabulary_config_and_lexicon(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "intent.json"
            self.model.save(path)
            restored = LinearIntentClassifier.load(path, lexicon=DEFAULT_LEXICON, config=IntentFeatureConfig())
            self.assertEqual(restored.sha256, self.model.sha256)
            for example in EXAMPLES:
                self.assertEqual(restored.predict(example["text"]).to_dict(), self.model.predict(example["text"]).to_dict())
            with self.assertRaises(FileExistsError):
                self.model.save(path)
            with self.assertRaises(ContractError):
                LinearIntentClassifier.load(path, config=replace(IntentFeatureConfig(), char_max=2))
            with self.assertRaises(ContractError):
                LinearIntentClassifier.load(path, lexicon=DEFAULT_LEXICON.extended(DomainTerm("新轴", "theme")))
            payload = json.loads(path.read_text())
            payload["state"]["weights"][0][0] += 1
            path.write_text(json.dumps(payload))
            with self.assertRaises(ContractError):
                LinearIntentClassifier.load(path)

    def test_lexicon_or_feature_reassignment_requires_a_new_model(self):
        model = LinearIntentClassifier()
        model.lexicon = DEFAULT_LEXICON.extended(DomainTerm("新轴", "theme"))
        with self.assertRaises(ContractError):
            model.predict("新轴")
        with self.assertRaises(ContractError):
            self.model.predict("堆墓", lexicon=DEFAULT_LEXICON.extended(DomainTerm("新轴", "theme")))
        model = LinearIntentClassifier()
        model.config = replace(IntentFeatureConfig(), char_max=2)
        with self.assertRaises(ContractError):
            model.fit(EXAMPLES)

    def test_untrained_checkpoint_round_trip_remains_untrained(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "untrained.json"
            LinearIntentClassifier().save(path)
            restored = LinearIntentClassifier.load(path)
            self.assertEqual(restored.predict("堆墓").kind, "ambiguous")
            self.assertFalse(restored.trained)

    def test_bad_training_configuration_and_rows_are_rejected(self):
        for config in ({"char_min": True}, {"char_min": 4, "char_max": 1}, {"min_confidence": float("nan")}):
            with self.subTest(config=config), self.assertRaises(ContractError):
                IntentFeatureConfig(**config)
        for rows in ([], [{"text": "珠泪", "label": "narrow"}] * 3,
                     [{"text": "x", "label": "unknown"}] * 3):
            with self.subTest(rows=rows), self.assertRaises(ContractError):
                LinearIntentClassifier().fit(rows)
        with self.assertRaises(ContractError):
            LinearIntentClassifier().fit(EXAMPLES, epochs=True)
        with self.assertRaises(ContractError):
            LinearIntentClassifier().fit(EXAMPLES, learning_rate=float("inf"))
        with self.assertRaises(ContractError):
            classify_build_intent("堆墓", classifier=object())


if __name__ == "__main__":
    unittest.main()
