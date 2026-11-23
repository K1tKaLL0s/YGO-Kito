"""Shared per-copy contribution evidence and the lexicographic candidate order."""
import unittest

from ygo_kito.build_contracts import DeckParts
from ygo_kito.construction_fill import _lexicographic_key, _review_slots
from ygo_kito.construction_quality import slot_ledger


def _use(card_id, status, *, checks=None, card=None):
    return dict(card_id=card_id, relation={"status": status}, inventory_checks=checks or {},
                card=card if card is not None else card_id)


def _facts(details, inventory, coverage=None, unpriced=()):
    return {"use_details": details,
            "coverage": coverage or {f"{zone}:{code}": "evaluated"
                                     for zone, cards in inventory.items() for code in cards},
            "source_aliases": {}, "unpriced_effects": list(unpriced), "inventory": inventory}


class SlotLedgerTests(unittest.TestCase):
    def test_copies_are_attributed_from_the_shared_use_facts(self):
        details = {
            "1:a": _use(1, "supported"),
            "2:a": _use(2, "missing"),
            "3:a": _use(3, "unknown"),
            "4:a": _use(4, "missing"),
            "5:a": _use(5, "missing"),
            "6:a": _use(6, "missing"),
            "mat:scarce": _use(1, "supported", checks={"materials": {"requirements": [
                {"matching_card_ids": [4], "minimum": 2, "confirmed_available": 1}]}}),
            "mat:abundant": _use(1, "supported", checks={"objects": {"requirements": [
                {"matching_card_ids": [5], "minimum": 2, "confirmed_available": 40}]}}),
        }
        inventory = {"main": [1, 1, 2, 2, 2, 3, 4, 5, 6], "extra": [], "side": []}
        ledger = slot_ledger(_facts(details, inventory, unpriced=[{"card_id": 6, "kind": "unparsed"}]), inventory)
        cards = ledger["cards"]
        self.assertEqual(cards["main:1"]["status"], "contributed")
        self.assertEqual(cards["main:1"]["copies"], 2)
        self.assertEqual(cards["main:2"]["status"], "proven_no_contribution")
        self.assertEqual(cards["main:2"]["copies"], 3)
        self.assertEqual(cards["main:3"]["status"], "undetermined")
        self.assertEqual(cards["main:4"]["status"], "undetermined")
        self.assertIn("scarce_support_supply", cards["main:4"]["reasons"])
        self.assertEqual(cards["main:5"]["status"], "proven_no_contribution")
        self.assertEqual(cards["main:6"]["status"], "undetermined")
        self.assertEqual(ledger["main_no_contribution"], 4)
        self.assertEqual(ledger["main_undetermined"], 3)
        self.assertEqual(ledger["main_contribution_interval"], [4, 7])

    def test_unevaluated_coverage_keeps_a_copy_undetermined(self):
        details = {"2:a": _use(2, "missing")}
        inventory = {"main": [2, 2], "extra": [], "side": []}
        coverage = {"main:2": "deferred"}
        ledger = slot_ledger(_facts(details, inventory, coverage), inventory)
        self.assertEqual(ledger["cards"]["main:2"]["status"], "undetermined")
        self.assertEqual(ledger["cards"]["main:2"]["reasons"], ["coverage_deferred"])
        self.assertEqual(ledger["main_no_contribution"], 0)

    def test_side_copies_are_judged_in_their_own_scope(self):
        details = {"6:a:side": _use(6, "supported"), "7:a:side": _use(7, "missing")}
        inventory = {"main": [1], "extra": [], "side": [6, 7]}
        ledger = slot_ledger(_facts(details, inventory), inventory)
        self.assertEqual(ledger["zones"]["side"],
                         {"copies": 2, "contributed": 1, "proven_no_contribution": 1, "undetermined": 0})
        self.assertEqual(ledger["cards"]["side:6"]["status"], "contributed")
        self.assertEqual(ledger["cards"]["side:7"]["status"], "proven_no_contribution")

    def test_duplicate_copies_of_a_supported_card_are_contributed_not_dead(self):
        details = {"1:a": _use(1, "supported")}
        inventory = {"main": [1, 1, 1], "extra": [], "side": []}
        ledger = slot_ledger(_facts(details, inventory), inventory)
        self.assertEqual(ledger["cards"]["main:1"]["status"], "contributed")
        self.assertEqual(ledger["main_no_contribution"], 0)


class LexicographicOrderTests(unittest.TestCase):
    @staticmethod
    def _evaluation(proven, value, complete=True):
        return {"total": {"complete": complete}, "slot_ledger": {"main_no_contribution": proven},
                "score": {"value": value}}

    def test_fewer_proven_dead_copies_win_before_score(self):
        better = self._evaluation(0, 50.0)
        higher = self._evaluation(2, 90.0)
        self.assertLess(_lexicographic_key(better, 1), _lexicographic_key(higher, 0))

    def test_equal_dead_count_falls_back_to_score(self):
        low = self._evaluation(1, 60.0)
        high = self._evaluation(1, 70.0)
        self.assertLess(_lexicographic_key(high, 5), _lexicographic_key(low, 0))

    def test_incomplete_evaluation_never_jumps_a_complete_one(self):
        incomplete = {"total": {"complete": False}, "slot_ledger": {"main_no_contribution": 0},
                      "score": {"value": 0.0}}
        complete = self._evaluation(3, 10.0)
        self.assertLess(_lexicographic_key(complete, 4), _lexicographic_key(incomplete, 0))


class ReviewSlotPriorityTests(unittest.TestCase):
    def test_proven_dead_main_copies_lead_the_s2_review(self):
        deck = DeckParts((1, 2, 2, 3), (7,), ())
        quality = {
            "static_rules": {"version": "fixture"},
            "side_contexts": {},
            "use_details": {"1:a": _use(1, "missing"), "2:a": _use(2, "missing")},
            "slot_ledger": {"cards": {"main:2": {"zone": "main", "card_id": 2, "copies": 2,
                                                 "status": "proven_no_contribution"},
                                      "main:1": {"zone": "main", "card_id": 1, "copies": 1,
                                                 "status": "undetermined"}}},
        }
        slots = _review_slots(deck, quality)
        self.assertEqual(slots[0]["reason"], "proven_no_contribution")
        self.assertEqual(slots[0]["card"], 2)
        self.assertEqual(slots[0]["copies"], 2)
        self.assertTrue(any(slot["card"] == 1 and slot["reason"] == "missing_support" for slot in slots))


if __name__ == "__main__":
    unittest.main()
