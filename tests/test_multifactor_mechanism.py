"""Mechanism metadata is deck-level and never a role-network input factor."""
import json
import unittest
from dataclasses import replace

import torch

from ygo_kito.multifactor import FactorContractError, Mechanism, RoleInput
from ygo_kito.multifactor.contracts import (
    CONTEXT_FACTORS, GROUP_FACTORS, RELATION_FACTORS, ROUTE_FACTOR_PREFIXES, is_route_factor,
)
from ygo_kito.multifactor.network import encode_batch
from tests.multifactor_helpers import synthetic_example


def mechanism(**overrides):
    value = dict(core_action="destroy", core_action_class="interaction",
                 source_zone="field", destination_zone="grave",
                 payoff=("destroy_trigger",), constraints=("fiend",), win_path="battle",
                 confidence=0.6, source="synthetic mechanism", period_ref=None,
                 condition_zones=(), role="primary")
    value.update(overrides)
    return Mechanism(**value)


class MechanismContractTests(unittest.TestCase):
    def test_roundtrip_and_optional_metadata(self):
        example = synthetic_example()
        tagged = replace(example, mechanism=mechanism())
        self.assertEqual(RoleInput.from_dict(json.loads(json.dumps(tagged.to_dict()))), tagged)
        self.assertNotIn("mechanism", example.to_dict())
        self.assertEqual(RoleInput.from_dict(json.loads(json.dumps(example.to_dict()))), example)

    def test_invalid_vocabulary_is_rejected(self):
        with self.assertRaises(FactorContractError):
            mechanism(core_action="fusion")
        with self.assertRaises(FactorContractError):
            mechanism(payoff=())
        with self.assertRaises(FactorContractError):
            mechanism(win_path="not-a-win-path")

    def test_mechanism_is_not_encoded_as_input(self):
        example = synthetic_example()
        tagged = replace(example, mechanism=mechanism())
        plain = encode_batch((example,))
        with_metadata = encode_batch((tagged,))
        for key in ("groups", "relations", "context", "mask"):
            self.assertTrue(torch.equal(plain[key], with_metadata[key]), key)

    def test_route_factors_are_marked_legacy(self):
        self.assertIn("plan_", ROUTE_FACTOR_PREFIXES)
        self.assertIn("objective_", ROUTE_FACTOR_PREFIXES)
        self.assertTrue(is_route_factor("plan_known"))
        self.assertTrue(is_route_factor("objective_fusion"))
        self.assertFalse(is_route_factor("unit_minimum_size"))
        for name in ("core_action", "core_action_class", "source_zone", "destination_zone",
                     "payoff", "constraints", "win_path", "mechanism"):
            self.assertNotIn(name, GROUP_FACTORS)
            self.assertNotIn(name, CONTEXT_FACTORS)
            self.assertNotIn(name, RELATION_FACTORS)


if __name__ == "__main__":
    unittest.main()
