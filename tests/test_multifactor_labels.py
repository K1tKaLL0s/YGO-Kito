"""LabelCell keeps unknown/conflict/not-applicable distinct from a known zero."""
import json
import unittest

from ygo_kito.multifactor import FactorContractError, LabelCell


class LabelCellTests(unittest.TestCase):
    def test_known_and_unknown_roundtrip(self):
        known = LabelCell(1.0, "known", 0.8, "effect_verified", ("effect:1",), "reviewed")
        self.assertTrue(known.known)
        self.assertEqual(LabelCell.from_dict(json.loads(json.dumps(known.to_dict()))), known)
        unknown = LabelCell(status="unknown", confidence=0.0)
        self.assertFalse(unknown.known)
        self.assertIsNone(unknown.value)
        self.assertEqual(LabelCell.from_dict(json.loads(json.dumps(unknown.to_dict()))), unknown)
        for status in ("conflict", "not_applicable"):
            cell = LabelCell(status=status, confidence=0.0, review_status="resolved")
            self.assertFalse(cell.known)
            self.assertIsNone(cell.value)

    def test_invalid_cells_are_rejected(self):
        with self.assertRaises(FactorContractError):
            LabelCell(None, "known")
        with self.assertRaises(FactorContractError):
            LabelCell(0.0, "unknown")
        with self.assertRaises(FactorContractError):
            LabelCell(0.5, "not_a_status")
        with self.assertRaises(FactorContractError):
            LabelCell(0.5, "known", 1.2)
        with self.assertRaises(FactorContractError):
            LabelCell(1.0, "known", 1.0, "effect_verified", ("a", "a"))
        with self.assertRaises(FactorContractError):
            LabelCell(1.0, "known", 1.0, "effect_verified", (), "unsupported")


if __name__ == "__main__":
    unittest.main()
