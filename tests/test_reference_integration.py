from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ygo_kito.reference_scoring import Block, Policy, PEARL_PRIORS, score_construction, calibrate_reference, inventory_digest
from ygo_kito.reference_scoring_adapter import review_deck
from ygo_kito.reference_hints import ReferenceHintTracker
from ygo_kito.reference_scoring_feedback import record_scoring_feedback
from ygo_kito.reference_hint_templates import templates_for_period


class PrivateReferenceIntegrationTest(unittest.TestCase):
    """Requires local private audit reports; excluded from public CPU CI."""
    def test_real_reference_coverage_and_attribution_conservation(self):
        for period in ("2022-07", "2022-10"):
            data = json.loads((ROOT / "reports" / f"{period}-private-audit.json").read_text(encoding="utf-8"))
            self.assertEqual(data["coverage"]["source_instances"], 70)
            self.assertAlmostEqual(sum(c["raw_contribution"] for c in data["cards"]), data["raw_score"], places=5)
            self.assertAlmostEqual(sum(v["raw_attributed"] for v in data["contribution_views"].values()), data["raw_score"], places=5)
            self.assertEqual(data["score"], 70)
            self.assertAlmostEqual(sum(c["score_contribution"] for c in data["cards"]), 70, places=5)


class IntegrationTest(unittest.TestCase):
    def test_same_semantics_with_new_identity_has_same_points(self):
        text = "anonymous effect which sends deck cards to grave"
        digest = sha256(text.encode()).hexdigest()
        registry = {digest: {"blocks": [dict(kind="mill", fact_id="effect-mill", quote=text)]}}
        row = {"desc": text, "alias": 0}
        a = review_deck({"main": [1]}, {1: row}, semantic_registry=registry, reference_example=True)[0]
        b = review_deck({"main": [987654321]}, {987654321: row}, semantic_registry=registry, reference_example=True)[0]
        self.assertEqual(a.blocks[0].factor(), b.blocks[0].factor())
        self.assertEqual(a.blocks[0].kind, b.blocks[0].kind)
        self.assertNotEqual(a.key, b.key)

    def test_fairy_partner_inventory_and_race_are_used_not_zombies(self):
        text = "对方把怪兽的效果发动时，从手卡把这张卡和1只天使族怪兽送去墓地才能发动。那个发动无效并破坏。"
        registry = {sha256(text.encode()).hexdigest(): {"blocks": [dict(kind="negate", fact_id="counter", quote=text)]}}
        rows = {1: {"desc": text, "race": 4}, 2: {"desc": "fairy", "race": 4},
                3: {"desc": "zombie", "race": 16}}
        alone = review_deck({"main": [1] + [3] * 39}, rows, semantic_registry=registry, reference_example=True)[0]
        self.assertEqual(alone.blocks[0].factor(), 0)
        with_fairy = review_deck({"main": [1, 2] + [3] * 38}, rows, semantic_registry=registry, reference_example=True)[0]
        self.assertAlmostEqual(with_fairy.blocks[0].feasibility, 4 / 39)
        duplicate_partner = review_deck({"main": [1, 1] + [3] * 38}, rows, semantic_registry=registry, reference_example=True)[0]
        self.assertAlmostEqual(duplicate_partner.blocks[0].feasibility, 4 / 39)

    def test_candidate_cannot_silently_inherit_reference_feasibility(self):
        text = "source effect requiring a resource"
        registry = {sha256(text.encode()).hexdigest(): {"blocks": [dict(kind="negate", fact_id="counter", quote=text)]}}
        with self.assertRaises(ValueError):
            review_deck({"main": [1]}, {1: {"desc": text}}, semantic_registry=registry)
        reviewed = review_deck({"main": [1]}, {1: {"desc": text}}, semantic_registry=registry,
                              contextualize=lambda row, block, deck, rows: replace(block, status="unknown"))
        self.assertEqual(reviewed[0].blocks[0].factor(), 0)

    def test_shared_mode_keeps_multiple_independent_operations(self):
        from ygo_kito.reference_scoring import CardReview
        text = "effect one; effect two"
        block_a = Block("removal", "remove", "effect one", choice_group="one-or-two", choice_mode="one")
        block_b = Block("hand_effect_send", "send", "effect one", choice_group="one-or-two", choice_mode="one")
        block_c = Block("recycle", "recover", "effect two", choice_group="one-or-two", choice_mode="two")
        card = CardReview("a", "a", "main", 1, text, sha256(text.encode()).hexdigest(), (block_a, block_b, block_c))
        filler = [CardReview(str(i), str(i), "main", 1, "filler", sha256(b"filler").hexdigest()) for i in range(39)]
        score = score_construction([card] + filler, policy=Policy(theme="pearl_grave_fusion",
                                   priors=PEARL_PRIORS.copy(), reference_score=70, reference_period_id="2022-07",
                                   calibration_scope="scope"), scope="scope")
        self.assertEqual(score["raw_block_points"], 1.75)

    def test_low_score_bridge_and_unknown_score_do_not_mix_counters(self):
        tracker = ReferenceHintTracker(templates=templates_for_period("2022-07"))
        audit = {"version": "test", "theme": "pearl_grave_fusion", "scope": "scope", "score": 55,
                 "evaluation_context": {"goal_id": "goal", "period_id": "2022-07"},
                 "reference_score": 70, "threshold": 56, "calibrated": True, "legality": "unknown",
                 "force_optimization": True, "score_threshold_met": False,
                 "basic_cb_verified": None, "interpretation": "prior"}
        for i in (1, 2):
            result = record_scoring_feedback(audit, tracker, evaluation_id=str(i), candidate_digest="candidate",
                                             cycle_id=str(i), goal_id="goal", period_id="2022-07")
        self.assertEqual(result["hint_event"]["hint_stage"], "main_axis")
        replay = record_scoring_feedback(audit, tracker, evaluation_id="2", candidate_digest="candidate",
                                        cycle_id="2", goal_id="goal", period_id="2022-07")
        self.assertFalse(replay["hint_event"]["counted"])
        state = tracker.to_dict()
        unknown = dict(audit, score=None, calibrated=False)
        result = record_scoring_feedback(unknown, tracker, evaluation_id="3", candidate_digest="candidate",
                                        cycle_id="3", goal_id="goal", period_id="2022-07")
        self.assertFalse(result["counted"])
        self.assertEqual(state, tracker.to_dict())
        with self.assertRaises(ValueError):
            record_scoring_feedback(audit, tracker, evaluation_id="wrong-period", candidate_digest="candidate",
                                    cycle_id="wrong-period", goal_id="goal", period_id="2022-10")

    def test_all_period_templates_are_mechanism_only_and_scope_specific(self):
        a = templates_for_period("2022-07")
        b = templates_for_period("2022-10")
        self.assertIn("another_fairy_in_hand", a["generic_tools"]["blocks"][0]["conditions"])
        self.assertNotIn("another_fairy_in_hand", b["generic_tools"]["blocks"][0]["conditions"])
        with self.assertRaises(ValueError):
            templates_for_period("2026-10")
        for templates in (a, b):
            serialized = json.dumps(templates)
            self.assertNotIn("card_id", serialized)
            self.assertNotIn("card_name", serialized)


if __name__ == "__main__": unittest.main()
