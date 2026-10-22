"""Synthetic DTO contracts test encoding/masking, never rule or playing strength."""

import copy
import unittest

try:
    import torch
except ModuleNotFoundError as error:
    if error.name != "torch":
        raise
    torch = None

from ygo_kito.contracts import DecisionRequest
from ygo_kito.validation import ContractError
from tests.fixtures import request

if torch is not None:
    from ygo_kito.cpu_training import config_from_dict
    from ygo_kito.duel_model import DuelActorCritic, DuelModelConfig, PlayerEncoder


def player_request():
    payload = request()
    payload["context"]["seed"] = None
    return payload


@unittest.skipIf(torch is None, "optional CPU PyTorch unavailable; model tests not passed")
class DuelModelContractTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(123)
        self.config = DuelModelConfig()
        self.encoder = PlayerEncoder([1, 2, 3], self.config)
        self.model = DuelActorCritic(self.config, 3).eval()

    def test_forward_masks_padding_to_exact_zero_probability_and_has_a_value(self):
        two = player_request()
        one = copy.deepcopy(two)
        one["actions"].pop()
        batch = self.encoder.batch([DecisionRequest.from_dict(one), DecisionRequest.from_dict(two)], pad_actions_to=4)
        logits, values = self.model(batch)
        self.assertEqual(tuple(logits.shape), (2, 4))
        self.assertEqual(tuple(values.shape), (2,))
        self.assertTrue(torch.isfinite(values).all())
        probabilities = logits.softmax(-1)
        self.assertTrue(torch.equal(probabilities[~batch["action_mask"]], torch.zeros(5)))
        self.assertTrue(torch.allclose(probabilities.sum(-1), torch.ones(2)))
        batch["action_mask"][0] = False
        with self.assertRaisesRegex(ContractError, "legal action"):
            self.model(batch)

    def test_opaque_ids_and_hidden_ownership_are_not_features(self):
        first = player_request()
        second = copy.deepcopy(first)
        second["context"]["run_id"] = "different-run"
        second["duel_id"], second["decision_id"] = "different-duel", "different-window"
        second["observation"]["cards"][1]["owner"] = 0
        for i, card in enumerate(second["observation"]["cards"]):
            original = card["ref"]
            card["ref"] = f"new-card-{i}"
            for action in second["actions"]:
                action["card_refs"] = [card["ref"] if ref == original else ref for ref in action["card_refs"]]
        for i, action in enumerate(second["actions"]):
            action["action_id"] = f"new-action-{i}"
        second["observation"]["public_history"][0]["event_id"] = "different-event"
        a, b = [self.encoder.encode(DecisionRequest.from_dict(x)) for x in (first, second)]
        self.assertTrue(all(torch.equal(a[key], b[key]) for key in a))

    def test_legal_visible_card_and_life_changes_reach_the_network(self):
        first, second = player_request(), player_request()
        second["observation"]["cards"][0]["card_id"] = 2
        second["observation"]["life_points"][0] = 4000
        a, b = [self.encoder.batch([DecisionRequest.from_dict(x)]) for x in (first, second)]
        self.assertFalse(torch.equal(a["tokens"], b["tokens"]))
        with torch.no_grad():
            outputs = [self.model(batch) for batch in (a, b)]
        self.assertFalse(torch.equal(outputs[0][1], outputs[1][1]))

    def test_order_value_and_placement_are_distinguishable_candidates(self):
        data = player_request()
        refs = [c["ref"] for c in data["observation"]["cards"]]
        data["actions"] = [
            {"action_id": "order-1", "kind": "order", "card_refs": refs},
            {"action_id": "order-2", "kind": "order", "card_refs": list(reversed(refs))},
            {"action_id": "number-1", "kind": "number", "card_refs": [], "value": 1},
            {"action_id": "number-2", "kind": "number", "card_refs": [], "value": 2},
            {"action_id": "place-1", "kind": "select", "card_refs": [], "details": {
                "destination": {"controller": 0, "zone": "monster", "sequence": 0}}},
            {"action_id": "place-2", "kind": "select", "card_refs": [], "details": {
                "destination": {"controller": 0, "zone": "monster", "sequence": 1}}},
        ]
        encoded = self.encoder.encode(DecisionRequest.from_dict(data))
        self.assertFalse(torch.equal(encoded["pointers"][0], encoded["pointers"][1]))
        self.assertFalse(torch.equal(encoded["action_numbers"][2], encoded["action_numbers"][3]))
        self.assertFalse(torch.equal(encoded["actions"][4], encoded["actions"][5]))

    def test_seed_audit_raw_records_hidden_identity_and_unknown_card_fail_closed(self):
        with self.assertRaisesRegex(ContractError, "without an RNG seed"):
            self.encoder.encode(DecisionRequest.from_dict(request()))
        with self.assertRaises(ContractError):
            self.encoder.encode({"raw_engine_audit": []})
        for field, value in (("card_id", 2), ("attack", 2000), ("defense", 1000)):
            data = player_request()
            data["observation"]["cards"][1][field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                self.encoder.encode(DecisionRequest.from_dict(data))
        data = player_request()
        data["observation"]["cards"][0]["card_id"] = 999
        with self.assertRaisesRegex(ContractError, "vocabulary"):
            self.encoder.encode(DecisionRequest.from_dict(data))

    def test_input_and_configuration_budgets_reject_instead_of_truncating_candidates(self):
        typed = DecisionRequest.from_dict(player_request())
        for config in (DuelModelConfig(max_tokens=2), DuelModelConfig(max_actions=1)):
            with self.assertRaisesRegex(ContractError, "budget"):
                PlayerEncoder([1], config).batch([typed])
        for value in ({"device": "cuda"}, {"batch_size": 33}, {"game_seeds": "bad"},
                      {"schema_version": 2}, {"model": {"width": 129}}, {"learning_rate": float("inf")}):
            with self.subTest(value=value), self.assertRaises(ContractError):
                config_from_dict(value)
        with self.assertRaises(ContractError):
            self.encoder.batch([])
        with self.assertRaises(ContractError):
            PlayerEncoder([True], self.config)
