"""RoleInput v3 envelope and explicit v2 migration."""
import json
import unittest

from ygo_kito.multifactor import (
    DeckSpec, FactorContractError, RoleInput, UnitSpec, migrate_v2_input,
)
from tests.multifactor_helpers import synthetic_example


class AnalysisInputTests(unittest.TestCase):
    def setUp(self):
        self.v2 = synthetic_example().to_dict()
        self.deck = DeckSpec(main=((100, 3), (101, 2)), extra=((200, 1),), side=())
        self.unit = UnitSpec("unit:1", ((100, 1), (101, 1)), "function:negate_activation")

    def test_unit_analysis_needs_unit_but_not_receiver_deck(self):
        value = migrate_v2_input(self.v2, analysis_mode="unit_analysis", unit=self.unit)
        self.assertEqual(value["schema_version"], "axis-input-v3")
        parsed = RoleInput.from_dict(value)
        value = value["observations"]
        self.assertEqual(value["analysis_mode"], "unit_analysis")
        self.assertEqual(value["unit"]["unit_id"], "unit:1")
        self.assertEqual(value["analysis_context"]["period"], "unknown")
        self.assertIsNone(value["deck"])
        self.assertEqual(parsed.unit_definition, self.unit)
        self.assertEqual(RoleInput.from_dict(parsed.to_dict()), parsed)

    def test_deck_analysis_needs_deck(self):
        value = migrate_v2_input(self.v2, analysis_mode="deck_analysis", deck=self.deck)
        self.assertEqual(value["observations"]["deck"]["main"], [[100, 3], [101, 2]])
        self.assertEqual(self.deck.section_counts(), {"main": 5, "extra": 1, "side": 0})

    def test_missing_required_envelope_is_rejected(self):
        with self.assertRaises(FactorContractError):
            migrate_v2_input(self.v2, analysis_mode="unit_analysis")
        with self.assertRaises(FactorContractError):
            migrate_v2_input(self.v2, analysis_mode="deck_analysis")
        with self.assertRaises(FactorContractError):
            migrate_v2_input(self.v2, analysis_mode="candidate_insert", deck=self.deck)
        with self.assertRaises(FactorContractError):
            migrate_v2_input(self.v2, analysis_mode="state_evaluation")
        with self.assertRaises(FactorContractError):
            migrate_v2_input(self.v2, analysis_mode="unknown")

    def test_deck_and_unit_roundtrip(self):
        self.assertEqual(DeckSpec.from_dict(self.deck.to_dict()), self.deck)
        self.assertEqual(UnitSpec.from_dict(self.unit.to_dict()), self.unit)
        with self.assertRaises(FactorContractError):
            DeckSpec(main=((100, 1), (100, 2)))
        with self.assertRaises(FactorContractError):
            UnitSpec("unit:2", (), "function:x")

    def test_visible_state_required_for_state_evaluation(self):
        value = migrate_v2_input(self.v2, analysis_mode="state_evaluation", unit=self.unit,
                                 visible_state=(("timing", "main_phase"),))
        self.assertEqual(value["observations"]["visible_state"], [["timing", "main_phase"]])
        with self.assertRaises(FactorContractError):
            migrate_v2_input(self.v2, analysis_mode="state_evaluation", visible_state=())


if __name__ == "__main__":
    unittest.main()
