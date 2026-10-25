"""Synthetic wire/DTO tests; real scripts are tested separately in integration_tests."""
import copy
import json
import struct
import unittest
from types import SimpleNamespace

from tests.fixtures import request
from ygo_kito.contracts import DecisionRequest
from ygo_kito.native_protocol import NativeError, Reader, decode_deck_choices, decode_prompt
from ygo_kito.sum_protocol import accepted, contributions
from ygo_kito.extra_observation import moved, resolve, shuffled_hand
from ygo_kito.native import NativeNormalEngine
from ygo_kito.validation import ContractError


def sum_wire(mandatory, optional, *, target=5, minimum=1, maximum=4, mode=0):
    result = bytes((mode, 0)) + struct.pack("<I", target) + bytes((minimum, maximum))
    for group in (mandatory, optional):
        result += bytes((len(group),))
        for sequence, packed in group:
            result += struct.pack("<IBBBI", 100 + sequence, 0, 4, sequence, packed)
    return result


class SumExtraProtocolTests(unittest.TestCase):
    def decode(self, wire):
        return decode_prompt(23, Reader(wire), allow_sum=True)

    def test_mandatory_padding_and_two_distinct_optional_sets(self):
        decoded = self.decode(sum_wire([(0, 2)], [(1, 3), (2, 3)]))
        self.assertEqual([o.response for o in decoded.options], [b"\x02\x00\x00", b"\x02\x00\x01"])
        self.assertEqual([o.refs for o in decoded.options], [("p0.monster.0", "p0.monster.1"), ("p0.monster.0", "p0.monster.2")])
        self.assertEqual(decoded.sum_selection.target, 5)
        self.assertTrue(all(o.details.operation == "sum" for o in decoded.options))
        with self.assertRaises(NativeError):
            decode_prompt(23, Reader(sum_wire([(0, 2)], [(1, 3)])))  # Legacy profiles remain gated.

    def test_alternative_packed_values_and_native_minimal_at_least_semantics(self):
        self.assertEqual(contributions(0x00050002), (2, 5))
        self.assertEqual(contributions(0x80010002), (65538,))
        decoded = self.decode(sum_wire([], [(0, 0x00050002)], minimum=1, maximum=1))
        self.assertEqual(decoded.options[0].response, b"\x01\x00")
        # Mode 1 uses min/max contributions and minimality, not exact-sum equality.
        decoded = self.decode(sum_wire([], [(0, 4), (1, 3)], target=6, minimum=0, maximum=0, mode=1))
        self.assertEqual([o.response for o in decoded.options], [b"\x02\x00\x01"])
        self.assertFalse(accepted([(3,), (3,), (3,)], 6, 1))
        self.assertFalse(accepted([(0,), (5,)], 5, 0))

    def test_duplicate_truncated_empty_huge_and_unrepresentable_prompts_fail_closed(self):
        valid = sum_wire([(0, 2)], [(1, 3)])
        invalid = [valid[:-1], valid + b"\x00", sum_wire([(0, 2)], [(0, 3)]),
                   sum_wire([], [(0, 2)], target=5),
                   valid[:1] + b"\x02" + valid[2:],
                   sum_wire([], [(i, 1) for i in range(16)], minimum=0, maximum=16),
                   sum_wire([], [(0, 0xffffffff)], minimum=1, maximum=1)]
        for wire in invalid:
            with self.subTest(wire=wire[:10]), self.assertRaises(NativeError):
                self.decode(wire)

    def test_multi_deck_choices_are_bounded_order_free_and_native_mapping_private(self):
        first = [(300, 0, 1, 31), (100, 0, 1, 0), (200, 0, 1, 2)]
        second = [(200, 0, 1, 99), (300, 0, 1, 18), (100, 0, 1, 27)]
        choices, actions = decode_deck_choices(0, 2, 2, first)
        other, different = decode_deck_choices(0, 2, 2, second)
        self.assertEqual(choices, other)
        self.assertEqual([a[:3] for a in actions], [a[:3] for a in different])
        self.assertEqual(actions[0][3], bytes((2, 1, 2)))
        self.assertEqual(different[0][3], bytes((2, 2, 0)))
        for items, low, high in ((first, 3, 2), ([(i+1, 0, 1, i) for i in range(20)], 2, 10),
                                 ([(1, 1, 1, 0)], 1, 1), ([(1, 0, 1, 0), (2, 0, 16, 0)], 1, 1)):
            with self.assertRaises(NativeError):
                decode_deck_choices(0, low, high, items)

    def test_material_host_and_sum_visibility_round_trip_and_privacy_rejection(self):
        data = request()
        data["context"]["seed"] = None
        data["observation"]["cards"] = [
            {"ref": "host", "owner": 0, "controller": 0, "zone": "monster", "visibility": "public", "card_id": 100, "material_count": 1},
            {"ref": "mat", "owner": None, "controller": 0, "zone": "overlay", "visibility": "public", "card_id": 101, "attached_to": "host"}]
        data["prompt"] = {"message": 23, "minimum": 1, "maximum": 1}
        data["actions"] = [{"action_id": "sum", "kind": "select", "card_refs": ["host", "mat"], "details": {"operation": "sum"}}]
        data["sum_selection"] = {"mode": "equal", "target": 5, "minimum_optional": 1, "maximum_optional": 1,
                                 "mandatory": [{"ref": "host", "values": [2]}], "optional": [{"ref": "mat", "values": [3]}]}
        parsed = DecisionRequest.from_dict(data)
        self.assertEqual(parsed, DecisionRequest.from_dict(json.loads(json.dumps(parsed.to_dict()))))
        for mutation in ("host", "controller", "hidden", "prompt", "unknown", "hidden-host", "count"):
            bad = copy.deepcopy(data)
            if mutation == "host": bad["observation"]["cards"][1]["attached_to"] = "absent"
            elif mutation == "controller": bad["observation"]["cards"][1]["controller"] = 1
            elif mutation == "hidden": bad["observation"]["cards"][1].update(visibility="hidden", card_id=None)
            elif mutation == "prompt": bad["prompt"]["message"] = 15
            elif mutation == "hidden-host": bad["observation"]["cards"][0].update(visibility="hidden", owner=None, card_id=None)
            elif mutation == "count": bad["observation"]["cards"][0]["material_count"] = 2
            else: bad["sum_selection"]["native_indices"] = [0, 1]
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                DecisionRequest.from_dict(bad)

    def test_host_relocation_detach_owner_indices_and_hidden_region_resolution(self):
        # Pure projection unit test with synthetic MOVE coordinates/known owners.
        engine = SimpleNamespace(_known_owners={(0, 4, 0): 1, (0, 4, 1): 0}, _overlay_owners={},
                                 _extra_refs={}, _material_refs={}, _banished_refs={})
        moved(engine, (0, 4, 0, 1), (0, 192, 0, 0))
        moved(engine, (0, 4, 1, 1), (0, 192, 0, 1))
        moved(engine, (0, 64, 0, 8), (0, 4, 2, 1))
        self.assertEqual(engine._overlay_owners, {(0, 4, 2, 0): 1, (0, 4, 2, 1): 0})
        moved(engine, (0, 132, 2, 0), (1, 16, 0, 1))
        self.assertEqual(engine._overlay_owners, {(0, 4, 2, 0): 0})
        self.assertEqual(engine._known_owners[(1, 16, 0)], 1)
        for zone, sub in ((32, None), (64, None), (132, 0)):
            with self.assertRaises(NativeError):
                resolve(engine, 0, 1, zone, 0, sub)
        engine._banished_refs[(0, 0)] = "own-visible-banished"
        self.assertEqual(resolve(engine, 0, 0, 32, 0), "own-visible-banished")

    def test_invalid_prompt_player_fails_before_any_native_query(self):
        engine = object.__new__(NativeNormalEngine)
        engine.general_actions = engine.extended_actions = True
        engine._observation = lambda *_: self.fail("invalid player reached the native observation query")
        for kind, wire in ((15, b"\x02"), (23, b"\x00\x02"), (23, b"\x00")):
            with self.assertRaises(NativeError):
                engine._prompt(kind, Reader(wire))

    def test_hand_shuffle_invalidates_only_unverified_hand_owner_associations(self):
        # Synthetic ownership-cache projection; no claim of executing a shuffle effect.
        engine = SimpleNamespace(_known_owners={(0, 2, 0): 1, (1, 2, 0): 0, (0, 4, 0): 0},
                                 _overlay_owners={(0, 4, 0, 0): 1}, _revealed_hand=[{0: 123}, {0: 456}])
        shuffled_hand(engine, 0)
        self.assertEqual(engine._known_owners, {(1, 2, 0): 0, (0, 4, 0): 0})
        self.assertEqual(engine._overlay_owners, {(0, 4, 0, 0): 1})
        shuffled_hand(engine, 1)
        self.assertEqual(engine._known_owners, {(0, 4, 0): 0})
