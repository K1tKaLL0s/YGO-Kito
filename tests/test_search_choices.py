"""Contract/unit checks; these are not real-script success evidence."""

import json
import unittest

from tests.fixtures import request
from ygo_kito.contracts import DecisionRequest
from ygo_kito.native import NativeError, decode_deck_choices
from ygo_kito.validation import ContractError
from ygo_kito.search_cases import run_search_case
from pathlib import Path


class SearchChoicesTests(unittest.TestCase):
    def test_malformed_replay_version_fails_before_resource_loading(self):
        replay = {"schema_version": True, "kind": "search-trigger-replay-not-policy-input", "route": "field-twice",
                  "seed": 9154, "versions": {}, "decks": [], "responses": [], "events": [], "result": {}}
        with self.assertRaises(ContractError):
            run_search_case(Path('/tmp/nonexistent-ygo-search-test'), replay=replay)

    def test_legal_search_choices_are_scoped_to_chooser_and_no_deck_positions(self):
        payload = request()
        payload["search_choices"] = [{"ref": "search-0", "card_id": 123, "owner": 0}]
        payload["actions"] = [{"action_id": "choose", "kind": "select", "card_refs": ["search-0"]}]
        parsed = DecisionRequest.from_dict(payload)
        self.assertEqual(parsed, DecisionRequest.from_dict(json.loads(json.dumps(parsed.to_dict()))))
        payload["search_choices"][0]["owner"] = 1
        with self.assertRaises(ContractError):
            DecisionRequest.from_dict(payload)
        payload["search_choices"][0].update(owner=0, deck_sequence=12)
        with self.assertRaises(ContractError):
            DecisionRequest.from_dict(payload)

    def test_native_order_and_sequence_do_not_enter_public_choices(self):
        choices, options = decode_deck_choices(0, 1, 1, [(200, 0, 1, 17), (100, 0, 1, 3)])
        other, other_options = decode_deck_choices(0, 1, 1, [(100, 0, 1, 29), (200, 0, 1, 1)])
        self.assertEqual(choices, other)
        self.assertEqual([o[:3] for o in options], [o[:3] for o in other_options])
        self.assertNotEqual(options[0][3], other_options[0][3])  # Private native mapping remains correct.

    def test_single_selection_is_linear_and_unsupported_cases_fail_closed(self):
        choices, options = decode_deck_choices(0, 1, 1, [(i + 1, 0, 1, i) for i in range(100)])
        self.assertEqual((len(choices), len(options)), (100, 100))
        for minimum, maximum, items in ((1, 2, [(1, 0, 1, 0)]), (1, 1, [(0, 0, 1, 0)]), (1, 1, [(2, 1, 1, 0)])):
            with self.assertRaises(NativeError):
                decode_deck_choices(0, minimum, maximum, items)
