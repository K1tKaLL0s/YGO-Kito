"""Wire and contract checks only; positive rules evidence is in integration_tests."""

import copy
import json
import struct
import unittest

from tests.fixtures import request
from ygo_kito.contracts import DecisionRequest
from ygo_kito.native_protocol import NativeError, Reader, decode_prompt
from ygo_kito.validation import ContractError


def card(code, controller=0, zone=4, sequence=0, extra=None):
    return struct.pack("<IBBB", code, controller, zone, sequence) + (bytes((extra,)) if extra is not None else b"")


class GeneralProtocolTests(unittest.TestCase):
    def test_option_keeps_description_but_responds_with_index(self):
        p = decode_prompt(14, Reader(struct.pack("<BBII", 0, 2, 9001, 9002)))
        self.assertEqual([o.details.description for o in p.options], [9001, 9002])
        self.assertEqual([o.response for o in p.options], [0, 1])

    def test_battle_activation_and_attack_use_different_native_modes(self):
        wire = bytes((0, 1)) + card(123) + struct.pack("<I", 456) + bytes((1,)) + card(789, extra=1) + bytes((1, 1))
        p = decode_prompt(10, Reader(wire))
        self.assertEqual([(o.kind, o.response) for o in p.options], [("activate", 0), ("attack", 1), ("pass", 2), ("pass", 3)])
        self.assertEqual(p.options[0].details.description, 456)

    def test_tribute_uses_core_release_weights_and_maximum_card_count(self):
        wire = bytes((0, 0, 2, 2, 2)) + card(123, extra=2) + card(456, sequence=1, extra=1)
        p = decode_prompt(20, Reader(wire))
        self.assertEqual([o.response for o in p.options], [bytes((1, 0)), bytes((2, 0, 1))])

    def test_incremental_selection_distinguishes_add_remove_and_finish(self):
        wire = bytes((0, 1, 0, 1, 2, 1)) + card(123, extra=0) + bytes((1,)) + card(456, sequence=1, extra=0)
        p = decode_prompt(26, Reader(wire))
        self.assertEqual([o.details.operation for o in p.options], ["add", "remove", "finish"])
        self.assertEqual([o.response for o in p.options], [b"\x01\x00", b"\x01\x01", -1])

    def test_place_has_explicit_controller_zone_and_sequence(self):
        mask = 0xffffffff ^ (1 << (16 + 8 + 3))
        p = decode_prompt(18, Reader(bytes((0, 1)) + struct.pack("<I", mask)))
        target = p.options[0].details.destination
        self.assertEqual((target.controller, target.zone, target.sequence), (1, "spell_trap", 3))
        self.assertEqual(p.options[0].response, b"\x01\x08\x03")

    def test_large_linear_selection_works_and_explosive_combinations_fail(self):
        def wire(n, low, high):
            return bytes((0, 0, low, high, n)) + b"".join(card(i + 1, zone=16, sequence=i, extra=0) for i in range(n))
        self.assertEqual(len(decode_prompt(15, Reader(wire(40, 1, 1))).options), 40)
        with self.assertRaises(NativeError):
            decode_prompt(15, Reader(wire(40, 10, 20)))

    def test_unknown_truncated_empty_and_opponent_private_choices_fail_closed(self):
        for kind, wire in ((22, b"\x00"), (14, b"\x00\x01"), (14, b"\x00\x00"),
                           (15, b"\x00\x00\x01\x01\x01" + card(123, 1, 2, extra=0))):
            with self.subTest(kind=kind), self.assertRaises(NativeError):
                decode_prompt(kind, Reader(wire))

    def test_new_contract_fields_are_typed_and_do_not_accept_hidden_payloads(self):
        payload = request()
        payload["prompt"] = {"message": 18, "minimum": 1, "maximum": 1}
        payload["actions"][0]["details"] = {"destination": {"controller": 0, "zone": "monster", "sequence": 0}}
        parsed = DecisionRequest.from_dict(payload)
        self.assertEqual(parsed, DecisionRequest.from_dict(json.loads(json.dumps(parsed.to_dict()))))
        bad = copy.deepcopy(payload)
        bad["actions"][0]["details"]["destination"]["raw_hidden_state"] = 1
        with self.assertRaises(ContractError):
            DecisionRequest.from_dict(bad)
        bad = copy.deepcopy(payload)
        bad["observation"]["cards"][1]["attack"] = 1000
        with self.assertRaises(ContractError):
            DecisionRequest.from_dict(bad)
        payload["prompt"]["message"] = True
        with self.assertRaises(ContractError):
            DecisionRequest.from_dict(payload)
