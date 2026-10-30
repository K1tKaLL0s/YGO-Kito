"""Targeted, standard-library checks for the private construction evaluator."""
import importlib.util
import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import sys
import unittest


_PATH = Path(__file__).parents[1] / "src" / "ygo_kito" / "reference_scoring.py"
_SPEC = importlib.util.spec_from_file_location("reference_scoring_test_target", _PATH)
scoring = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = scoring
_SPEC.loader.exec_module(scoring)

_SCOPE = "2022-07/anonymous-goal/frozen-reference-v1"
_KNOWN = {key: "known" for key in ("conditions", "costs", "limits", "resources", "conflicts")}


def block(kind, fact="effect-one", **changes):
    values = dict(kind=kind, fact_id=fact, quote="effect one", knowledge=dict(_KNOWN))
    values.update(changes)
    return scoring.Block(**values)


def card(key, *blocks, copies=1, alias=None, zone="main", **changes):
    text = "effect one; effect two; public condition; public payment"
    values = dict(key=key, alias=alias or key, zone=zone, copies=copies, text=text,
                  text_sha256=sha256(text.encode()).hexdigest(), blocks=tuple(blocks))
    values.update(changes)
    return scoring.CardReview(**values)


def deck(*cards, main_size=40):
    """Fill legal main capacity with source-bound, uncredited unknown cards."""
    rows = list(cards)
    remaining = main_size - sum(row.copies for row in rows if row.zone == "main")
    if remaining < 0:
        raise ValueError("requested main_size is smaller than supplied cards")
    index = 0
    while remaining:
        copies = min(3, remaining)
        rows.append(card(f"anonymous-filler-{index}", copies=copies, unknowns=("unreviewed_function",)))
        index += 1
        remaining -= copies
    return rows


def policy(**changes):
    values = dict(theme="pearl_grave_fusion", priors=scoring.PEARL_PRIORS.copy(), reference_score=70,
                  reference_period_id="2022-07", calibration_scope=_SCOPE, reference_raw=10.0)
    values.update(changes)
    return scoring.Policy(**values)


def evaluate(cards, units=(), **changes):
    args = dict(policy=policy(), legality="legal", scope=_SCOPE)
    args.update(changes)
    return scoring.score_construction(cards, units, **args)


def pair_unit():
    # Anonymous entities stand for a conditional counter plus its required
    # otherwise-unproductive partner. No card-name or ID behavior is involved.
    return scoring.FunctionalUnit(
        key="counter-partner-unit", category="conditional_generic", description="conditional counter unit",
        points=5.0, relation="counter requires partner availability", family="counter-partner",
        relation_status="reviewed_feasible",
        requirements=(
            scoring.Requirement(kinds=("negate",), zones=("main",), entities=("counter",)),
            scoring.Requirement(kinds=("body",), zones=("main",), entities=("partner",)),
        ), conditions=("own field condition", "partner accessible"), risks=("drawn partner burden",))


class ReferenceScoringTest(unittest.TestCase):
    def test_broad_and_narrow_labels_for_same_fact_take_maximum(self):
        result = evaluate(deck(card("engine", block("grave_related"), block("grave_fusion"))))
        self.assertAlmostEqual(result["raw_block_points"], 1.5)
        self.assertEqual(len(result["cards"][0]["blocks"]), 1)
        self.assertEqual(result["cards"][0]["blocks"][0]["kind"], "grave_fusion")

    def test_independent_effects_keep_independent_value(self):
        result = evaluate(deck(card("engine", block("grave_fusion"),
                                    block("grave_draw", fact="effect-two", quote="effect two"))))
        self.assertAlmostEqual(result["raw_block_points"], 2.5)
        self.assertEqual(len(result["cards"][0]["blocks"]), 2)

    def test_shared_choice_modes_do_not_claim_two_uses(self):
        result = evaluate(deck(card("engine", block("targeted_send", choice_group="shared-choice"),
                                    block("search", fact="effect-two", quote="effect two", choice_group="shared-choice"))))
        self.assertAlmostEqual(result["raw_block_points"], 1.25)

    def test_repeated_copies_diminish_and_different_names_share_channel_cap(self):
        single = evaluate(deck(card("counter", block("negate"))))
        triple = evaluate(deck(card("counter", block("negate"), copies=3)))
        self.assertAlmostEqual(single["raw_block_points"], 1.25)
        self.assertAlmostEqual(triple["raw_block_points"], 1.25 * (1 + 0.35 + 0.1))
        names = [card(f"independent-name-{i}", block("negate"), copies=3) for i in range(10)]
        saturated = evaluate(deck(*names))
        self.assertAlmostEqual(saturated["raw_block_points"], scoring.PEARL_PRIORS["negate"][2])
        self.assertLess(saturated["raw_block_points"], triple["raw_block_points"] * len(names))

    def test_main_deck_dilution_is_real_even_with_source_complete_fillers(self):
        forty = evaluate(deck(card("access", block("targeted_send")), main_size=40))
        sixty = evaluate(deck(card("access", block("targeted_send")), main_size=60))
        self.assertAlmostEqual(forty["raw_block_points"], 1.25)
        self.assertAlmostEqual(sixty["raw_block_points"], 1.25 * 40 / 60)
        self.assertLess(sixty["score"], forty["score"])

    def test_illegal_alias_copies_cannot_earn_total_or_attributed_score(self):
        rows = deck(card("copy-main", block("negate"), alias="shared-listing", copies=3),
                    card("copy-side", block("negate"), alias="shared-listing", zone="side"))
        result = evaluate(rows, side_plan_verified=True)
        self.assertEqual(result["legality"], "illegal")
        self.assertEqual(result["raw_score"], 0)
        self.assertEqual(result["score"], 0)
        self.assertTrue(result["force_optimization"])
        self.assertTrue(all(row["score_contribution"] == 0 for row in result["cards"]))

    def test_main_side_alias_allocation_is_independent_of_input_order(self):
        main = card("main-instance", block("negate"), alias="same-listing")
        side = card("side-instance", block("negate"), alias="same-listing", copies=2, zone="side")
        first = deck(main, side)
        second = deck(side, main)
        self.assertEqual(scoring.inventory_digest(first), scoring.inventory_digest(second))
        left, right = (evaluate(rows, side_plan_verified=True) for rows in (first, second))
        self.assertEqual(left["legality"], "legal")
        self.assertAlmostEqual(left["raw_score"], right["raw_score"])
        self.assertEqual(left["score"], right["score"])

    def test_unknown_cost_or_condition_zeroes_only_affected_function(self):
        for dimension in _KNOWN:
            knowledge = dict(_KNOWN, **{dimension: "unknown"})
            result = evaluate(deck(card("engine", block("grave_fusion", knowledge=knowledge),
                                        block("draw", fact="effect-two", quote="effect two"))))
            with self.subTest(dimension=dimension):
                self.assertAlmostEqual(result["raw_block_points"], scoring.PEARL_PRIORS["draw"][0])
                self.assertFalse(any(row["context_one_copy"] for row in result["cards"][0]["blocks"]
                                     if row["kind"] == "grave_fusion"))
        for status in ("unknown", "unavailable"):
            self.assertEqual(evaluate(deck(card("engine", block("grave_fusion", status=status))))["raw_score"], 0)

    def test_context_discounts_multiply_for_exact_function(self):
        row = card("counter", block("negate", feasibility=0.8, cost_factor=0.5,
                                    count_factor=0.5, resource_factor=0.5, conflict_factor=0.5))
        self.assertAlmostEqual(evaluate(deck(row))["raw_block_points"], 1.25 * 0.8 * 0.5 ** 4)

    def test_quote_and_digest_binding_reject_changed_or_invented_source(self):
        valid = card("source", block("draw"))
        corruptions = (
            replace(valid, text=valid.text + "changed"),
            replace(valid, text_sha256="0" * 64),
            replace(valid, blocks=(block("draw", quote="not in actual card text"),)),
            replace(valid, blocks=(block("draw", quote=""),)),
            replace(valid, blocks=(block("draw", fact=""),)),
        )
        for corruption in corruptions:
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                evaluate(deck(corruption))

    def test_calibration_assigns_complete_reference_seventy_and_threshold_fifty_six(self):
        rows = deck(card("engine", block("grave_fusion"), block("targeted_send", fact="effect-two", quote="effect two")))
        reference = scoring.calibrate_reference(rows, policy=policy(reference_raw=None), legality="legal", scope=_SCOPE,
                                                expected_inventory_digest=scoring.inventory_digest(rows))
        audit = evaluate(rows, policy=reference)
        self.assertEqual(audit["score"], 70)
        self.assertEqual(audit["threshold"], 56)
        self.assertFalse(audit["force_optimization"])
        self.assertEqual(audit["basic_cb_verified"], None)
        self.assertAlmostEqual(sum(row["score_contribution"] for row in audit["cards"]), 70)

    def test_calibration_rejects_missing_source_or_changed_inventory(self):
        rows = deck(card("engine", block("draw")))
        expected = scoring.inventory_digest(rows)
        incomplete = deck(card("replacement", block("draw")))
        missing_text = list(rows)
        missing_text[0] = replace(rows[0], text="", text_sha256=sha256(b"").hexdigest(), blocks=(), unknowns=("missing_card_text",))
        for bad in ([], incomplete, missing_text):
            with self.subTest(case=bad), self.assertRaises(ValueError):
                scoring.calibrate_reference(bad, policy=policy(reference_raw=None), legality="legal", scope=_SCOPE,
                                            expected_inventory_digest=expected)
        with self.assertRaises((ValueError, TypeError)):
            scoring.calibrate_reference(rows, policy=policy(reference_raw=None), legality="legal", scope=_SCOPE)

    def test_uncalibrated_score_cannot_meet_threshold_and_scope_must_match(self):
        rows = deck(card("engine", block("draw")))
        audit = evaluate(rows, policy=policy(reference_raw=None))
        self.assertFalse(audit["calibrated"])
        self.assertIsNone(audit["score"])
        self.assertTrue(audit["force_optimization"])
        self.assertFalse(audit["score_threshold_met"])
        with self.assertRaises(ValueError):
            evaluate(rows, scope="2022-10/anonymous-goal/other-reference")
        with self.assertRaises(ValueError):
            scoring.calibrate_reference(rows, policy=policy(reference_raw=None), legality="legal", scope="wrong-scope",
                                        expected_inventory_digest=scoring.inventory_digest(rows))

    def test_returned_score_and_optimization_signal_use_same_threshold_precision(self):
        rows = deck(card("engine", block("targeted_send")))
        near = 55.9999999
        audit = evaluate(rows, policy=policy(reference_raw=1.25 * 70 / near))
        self.assertEqual(audit["force_optimization"], audit["score"] < audit["threshold"])
        self.assertEqual(audit["score_threshold_met"], audit["score"] >= audit["threshold"])

    def test_conditional_pair_needs_both_entities_not_one_card_with_two_labels(self):
        counter = card("counter", block("negate"))
        partner = card("partner", block("body"))
        complete = evaluate(deck(counter, partner), (pair_unit(),))
        self.assertEqual(complete["categories"]["conditional_generic"], 5)
        for one in (counter, partner, card("counter", block("negate"), block("body", fact="effect-two", quote="effect two"))):
            result = evaluate(deck(one), (pair_unit(),))
            with self.subTest(entity=one.key):
                self.assertEqual(result["categories"]["conditional_generic"], 0)
                self.assertTrue(result["units"][0]["unmet"])
        unavailable_partner = replace(partner, blocks=(block("body", status="unavailable"),))
        self.assertEqual(evaluate(deck(counter, unavailable_partner), (pair_unit(),))["categories"]["conditional_generic"], 0)

    def test_unit_family_deduplication_and_category_cap(self):
        rows = deck(card("counter", block("negate")), card("partner", block("body")))
        unit = pair_unit()
        duplicate = replace(unit, key="another-unit-id", description="same relation under another label")
        audit = evaluate(rows, (unit, duplicate))
        self.assertEqual(audit["categories"]["conditional_generic"], 5)
        self.assertEqual(sum(row["deduplicated"] for row in audit["units"]), 1)
        capped = evaluate(rows, (replace(unit, points=100),))
        self.assertEqual(capped["categories"]["conditional_generic"], policy().category_caps["conditional_generic"])

    def test_public_result_excludes_private_entities_sources_and_reference_breakdown(self):
        private = "PRIVATE_CARD_ID_12345678_AND_PRIVATE_NAME"
        rows = deck(card(private, block("grave_fusion")))
        audit = evaluate(rows)
        public = scoring.public_result(audit)
        rendered = json.dumps(public)
        self.assertNotIn(private, rendered)
        self.assertNotIn("effect one", rendered)
        for field in ("cards", "units", "unknowns", "reference_raw", "raw_score", "raw_block_points", "categories"):
            self.assertNotIn(field, public)
        self.assertEqual(public["score"], audit["score"])
        self.assertEqual(public["force_optimization"], audit["force_optimization"])


if __name__ == "__main__":
    unittest.main()
