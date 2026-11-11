"""Group split and reporting metric tests."""
import unittest

from ygo_kito.multifactor import (
    FactorContractError, LabelCell, assign_group_splits, binary_metrics, group_rows, leakage_group, macro_f1,
)


class GroupSplitTests(unittest.TestCase):
    def test_group_never_crosses_split_and_is_deterministic(self):
        rows = [{"source_rowid": group, "reference": f"ref{group}"} for group in range(12) for _ in range(2)]
        labels, summary = assign_group_splits(rows, seed=7)
        self.assertEqual(len(labels), len(rows))
        by_group = {}
        for row, split in zip(rows, labels):
            key = leakage_group(row)
            self.assertEqual(by_group.setdefault(key, split), split)
        self.assertEqual(sum(item["rows"] for item in summary.values()), len(rows))
        again, _ = assign_group_splits(rows, seed=7)
        self.assertEqual(labels, again)
        self.assertEqual(len(group_rows(rows)), 12)

    def test_too_few_groups_is_rejected(self):
        with self.assertRaises(ValueError):
            assign_group_splits([{"source_rowid": 1}, {"source_rowid": 2}])
        with self.assertRaises(ValueError):
            assign_group_splits([{"source_rowid": n} for n in range(6)], train=0.5, dev=0.5, test=0.5)


class MetricTests(unittest.TestCase):
    def test_unknown_and_unanswered_are_not_correct(self):
        cells = [
            (LabelCell(1.0, "known"), 0.9),   # tp
            (LabelCell(0.0, "known"), 0.1),   # tn
            (LabelCell(1.0, "known"), None),  # unanswered, not correct
            (LabelCell(status="unknown"), 0.9),  # ignored
        ]
        result = binary_metrics(cells)
        self.assertEqual((result["known"], result["answered"]), (3, 2))
        self.assertEqual(result["tp"], 1)
        self.assertEqual(result["tn"], 1)
        self.assertEqual(result["fn"], 1)
        self.assertAlmostEqual(result["f1"], 2 / 3)
        self.assertAlmostEqual(result["coverage"], 2 / 3)
        self.assertAlmostEqual(result["selective_accuracy"], 1.0)
        self.assertAlmostEqual(result["overall_accuracy"], 2 / 3)
        self.assertAlmostEqual(macro_f1({"a": {"f1": 1.0}, "b": {"f1": 0.5}}), 0.75)

    def test_macro_needs_a_known_task(self):
        with self.assertRaises(FactorContractError):
            macro_f1({"a": {"f1": None}})


if __name__ == "__main__":
    unittest.main()
