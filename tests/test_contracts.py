import json
import unittest

from ygo_kito.contracts import ActionSelection, DecisionRequest, validate_selection
from ygo_kito.engine import EngineUnavailable, engine_status, open_engine
from ygo_kito.validation import ContractError

from tests.fixtures import request, selection


class DecisionContractTests(unittest.TestCase):
    def test_round_trip_and_opaque_target_selection(self):
        decision = DecisionRequest.from_dict(request())
        round_trip = DecisionRequest.from_dict(json.loads(json.dumps(decision.to_dict())))
        self.assertEqual(decision, round_trip)
        chosen = validate_selection(round_trip, ActionSelection.from_dict(selection()))
        self.assertEqual(chosen.card_refs, ("opponent-set-1",))
        self.assertIsNone(round_trip.observation.cards[1].card_id)

    def test_hidden_card_identity_is_rejected(self):
        payload = request()
        payload["observation"]["cards"][1]["card_id"] = 999999
        with self.assertRaisesRegex(ContractError, "hidden cards"):
            DecisionRequest.from_dict(payload)

    def test_opponent_private_card_cannot_be_observer_visible(self):
        for zone in ("hand", "spell_trap", "extra"):
            with self.subTest(zone=zone):
                payload = request()
                payload["observation"]["cards"][1].update(zone=zone, visibility="observer", card_id=2)
                with self.assertRaisesRegex(ContractError, "opponent private"):
                    DecisionRequest.from_dict(payload)

    def test_deck_contents_are_not_representable(self):
        payload = request()
        payload["observation"]["cards"][0]["zone"] = "deck"
        with self.assertRaisesRegex(ContractError, "zone"):
            DecisionRequest.from_dict(payload)

    def test_raw_state_or_future_draw_fields_are_rejected_at_each_boundary(self):
        for location in ("root", "context", "observation", "card", "action", "history"):
            with self.subTest(location=location):
                payload = request()
                target = {
                    "root": payload, "context": payload["context"], "observation": payload["observation"],
                    "card": payload["observation"]["cards"][0], "action": payload["actions"][0],
                    "history": payload["observation"]["public_history"][0],
                }[location]
                target["raw_hidden_state"] = {"future_draw": 999999}
                with self.assertRaisesRegex(ContractError, "unexpected fields"):
                    DecisionRequest.from_dict(payload)

    def test_request_identity_prevents_cross_run_duel_and_stale_window(self):
        decision = DecisionRequest.from_dict(request())
        for key in ("run_id", "duel_id", "decision_id"):
            with self.subTest(key=key):
                chosen = selection()
                chosen[key] = "other"
                with self.assertRaisesRegex(ContractError, "mismatched"):
                    validate_selection(decision, ActionSelection.from_dict(chosen))

    def test_unknown_action_is_rejected(self):
        chosen = selection()
        chosen["action_id"] = "invented-action"
        with self.assertRaisesRegex(ContractError, "not in"):
            validate_selection(DecisionRequest.from_dict(request()), ActionSelection.from_dict(chosen))

    def test_duplicate_actions_and_references_or_unknown_targets_are_rejected(self):
        for mutation in ("duplicate_action", "duplicate_card", "unknown_target", "empty_actions"):
            with self.subTest(mutation=mutation):
                payload = request()
                match mutation:
                    case "duplicate_action":
                        payload["actions"].append(dict(payload["actions"][0]))
                    case "duplicate_card":
                        payload["observation"]["cards"].append(dict(payload["observation"]["cards"][0]))
                    case "unknown_target":
                        payload["actions"][0]["card_refs"] = ["not-observed"]
                    case "empty_actions":
                        payload["actions"] = []
                with self.assertRaises(ContractError):
                    DecisionRequest.from_dict(payload)

    def test_types_versions_and_count_shapes_fail_closed(self):
        for mutation in ("schema", "bool_schema", "bool_player", "counts", "no_banlist", "unknown_phase"):
            with self.subTest(mutation=mutation):
                payload = request()
                match mutation:
                    case "schema":
                        payload["schema_version"] = 2
                    case "bool_schema":
                        payload["schema_version"] = True
                    case "bool_player":
                        payload["observation"]["observer"] = True
                    case "counts":
                        payload["observation"]["deck_counts"] = [40]
                    case "no_banlist":
                        del payload["context"]["versions"]["banlist"]
                    case "unknown_phase":
                        payload["observation"]["phase"] = "future"
                with self.assertRaises(ContractError):
                    DecisionRequest.from_dict(payload)

    def test_model_roles_and_lora_are_metadata_only(self):
        payload = request()
        payload["context"]["models"] = [
            {"role": role, "version": "test-only", "lora": None}
            for role in ("duel", "build_goal", "build_optimizer", "coordinator")
        ]
        self.assertEqual(len(DecisionRequest.from_dict(payload).context.models), 4)
        payload["context"]["models"].append(payload["context"]["models"][0])
        with self.assertRaisesRegex(ContractError, "duplicate model"):
            DecisionRequest.from_dict(payload)

    def test_real_engine_is_explicitly_unavailable(self):
        self.assertFalse(engine_status()["implemented"])
        self.assertFalse(engine_status()["ready"])
        with self.assertRaises(EngineUnavailable):
            open_engine()
