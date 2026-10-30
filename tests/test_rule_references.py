"""Direct rule lookup/wiring contracts; these are not engine ruling tests."""
from copy import deepcopy
import unittest

import torch

from tests.test_duel_effect_limits import binding, view, event, activated, ROWS
from tests.test_duel_planning import PROJECTION_EFFECTS
from ygo_kito.duel_planning import DuelPlanner
from ygo_kito.effect_mechanisms import MechanismCatalog
from ygo_kito.rule_references import effect_reference_requests, library_reference, lookup_rule


class RuleReferenceTests(unittest.TestCase):
    def test_exact_lookup_preserves_synthesis_and_unknown_without_mutating_library(self):
        reference = lookup_rule("NAMED_CARD_ACTIVATION_ONCE")
        self.assertEqual(reference["status"], "reference_only")
        self.assertEqual(reference["rule"]["evidence_status"],
                         "official_rule_synthesis_direct_named_qa_not_found")
        self.assertFalse(reference["applied_to_decision"])
        self.assertEqual(len(reference["unresolved"]), 4)
        self.assertIn("qa_22010", reference["source_records"])
        reference["rule"]["evidence_status"] = "changed"
        self.assertNotEqual(lookup_rule("NAMED_CARD_ACTIVATION_ONCE")["rule"]["evidence_status"], "changed")
        self.assertEqual(lookup_rule("unreviewed_generic_activation")["status"], "unknown")
        self.assertEqual(len(library_reference()["rule_ids"]), 25)
        catalog = object.__new__(MechanismCatalog)
        self.assertEqual(catalog.rule_reference("USE_TURN_NEGATED")["rule_id"], "USE_TURN_NEGATED")

    def test_structured_effect_reference_keeps_unknown_policy_and_distinct_scope(self):
        record = {"card_id": 20, "effect_index": 2, "text_sha256": "1" * 64,
                  "count_limits": [{"status": "known", "scope": "same_name_card",
                                    "count_event": "card_activation", "period": "turn",
                                    "negation_policy": {"activation_negated": "unknown"}}]}
        original = deepcopy(record)
        reference = effect_reference_requests(record)[0]
        self.assertEqual(record, original)
        self.assertEqual(reference["rule_id"], "NAMED_CARD_ACTIVATION_ONCE")
        self.assertEqual(reference["binding"]["effect_index"], 2)
        self.assertEqual(reference["parsed_negation_policy"]["activation_negated"], "unknown")
        self.assertEqual(reference["binding"]["outcome"], "unknown_requires_engine_event")
        record["count_limits"][0]["scope"] = "unknown"
        record["source_text"] = "activate use negate"
        self.assertEqual(effect_reference_requests(record), [])

    def test_real_planner_receipt_exposes_exact_binding_and_observed_negation_for_review(self):
        b = binding("qa22010")
        planner = DuelPlanner(facts=ROWS, effect_records=PROJECTION_EFFECTS, effect_limit_bindings=(b,))
        history = (event("applied", "chain", 73, link=9), activated("trap"),
                   event("negation", "chain", 75, link=1))
        logits, receipt = planner.evaluate(view(history), torch.zeros(3))
        self.assertTrue(bool(torch.isfinite(logits).all()))
        self.assertEqual(receipt["interruption_rules"]["root_legality"], "engine_provided")
        query = receipt["interruption_rules"]["counter_queries"][0]
        self.assertEqual(query["remaining"], 1)
        reference = query["rule_review"]
        self.assertEqual(reference["rule_id"], "CARD_ACTIVATION_COUNT")
        self.assertFalse(reference["applied_to_decision"])
        self.assertEqual(reference["binding"]["effects"], [[20, 321], [21, 337]])
        self.assertEqual(reference["binding"]["application_event_id"], "applied")
        self.assertEqual(reference["binding"]["events"][0]["event_id"], "trap")
        self.assertEqual(reference["binding"]["events"][0]["outcome"], "activation_negated")


if __name__ == "__main__":
    unittest.main()
