"""Loopback protocol contracts with a Python peer, never a running WindBot."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tests.fixtures import request as fixture_request
from ygo_kito.build_contracts import DeckParts, digest
from ygo_kito.contracts import DecisionRequest
from ygo_kito.validation import ContractError, canonical_json
from ygo_kito.windbot_room import (WindBotMessage, WindBotRoom, WindBotSlot, WindBotTransportFrame,
    WindBotWindow, WindBotTransportError, WindBotUnsupported, game_message, packet, windbot_command, windbot_session)


def legal_request(kind=11):
    raw = fixture_request()
    raw["context"]["seed"] = None
    raw["prompt"] = {"message": kind}
    raw["actions"] = [{"action_id": "normal", "kind": "summon", "card_refs": ["own-hand-1"]},
                      {"action_id": "end", "kind": "pass", "card_refs": [], "value": 7}]
    return DecisionRequest.from_dict(raw)


def frame_for(request, *, version="v1", messages=(), facts=None):
    return WindBotTransportFrame(0, digest(request.to_dict()), version, tuple(messages),
        (WindBotSlot("own-hand-1", 0, 2, 0), WindBotSlot("opponent-set-1", 1, 8, 0)), facts or {})


def request_dict(request):
    return json.loads(canonical_json(request.to_dict()))


def start_message():
    return WindBotMessage(4, {"player_type": 0, "duel_rule": 5, "life_points": (8000, 8000),
        "deck_counts": (40, 40), "extra_counts": (0, 0)})


def unknown_record(sequence):
    record = {name: 0 for name in ("code", "alias", "type", "level", "rank", "attribute", "race",
        "attack", "defense", "base_attack", "base_defense", "status", "lscale", "rscale", "link", "link_marker")}
    return dict(record, sequence=sequence, equip=(0, 0, 0, 0), targets=[], overlay=[], counters=[])


def exact(sock, count):
    result = b""
    while len(result) < count:
        part = sock.recv(count - len(result))
        if not part:
            raise EOFError("Python protocol fixture disconnected")
        result += part
    return result


def receive(sock):
    size = struct.unpack("<H", exact(sock, 2))[0]
    result = exact(sock, size)
    return result[0], result[1:]


class WindBotWindowTests(unittest.TestCase):
    def window(self, request=None, frame=None, clock=lambda: 1.):
        request = request or legal_request()
        frame = frame or frame_for(request)
        return WindBotWindow(request, frame, observer=0, deadline=10., clock=clock)

    def test_idle_packet_and_response_map_to_current_action_without_native_indices(self):
        request = legal_request(); frame = frame_for(request); window = self.window(request, frame)
        self.assertEqual(window.message[2:4], bytes((1, 11)))
        self.assertEqual(window.translate(struct.pack("<i", 0), request=request, state_version="v1").action_id, "normal")
        with self.assertRaisesRegex(WindBotTransportError, "consumed"):
            window.translate(struct.pack("<i", 7), request=request, state_version="v1")
        with self.assertRaisesRegex(WindBotTransportError, "current legal action"):
            self.window().translate(struct.pack("<i", 999), request=request, state_version="v1")

    def test_missing_set_and_attack_flags_are_not_guessed_from_printed_catalog(self):
        raw = request_dict(legal_request()); raw["actions"][0]["kind"] = "set"
        request = DecisionRequest.from_dict(raw)
        with self.assertRaisesRegex(WindBotUnsupported, "set needs"):
            self.window(request, frame_for(request))
        window = self.window(request, frame_for(request, facts={"idle_set_modes": {"normal": 4}}))
        self.assertEqual(window.translate(struct.pack("<i", 4), request=request, state_version="v1").action_id, "normal")
        raw["prompt"]["message"] = 10; raw["actions"][0]["kind"] = "attack"
        raw["actions"][1]["value"] = 3
        raw["observation"]["cards"][0].update(zone="monster", position=1, visibility="public")
        request = DecisionRequest.from_dict(raw)
        frame = WindBotTransportFrame(0, digest(request.to_dict()), "v1", (),
            (WindBotSlot("own-hand-1", 0, 4, 0), WindBotSlot("opponent-set-1", 1, 8, 0)))
        with self.assertRaisesRegex(WindBotUnsupported, "direct-attack"):
            self.window(request, frame)

    def test_selection_indexes_are_only_local_and_must_match_an_existing_action(self):
        raw = fixture_request(); raw["context"]["seed"] = None
        raw["prompt"] = {"message": 15, "minimum": 1, "maximum": 1, "cancelable": True}
        request = DecisionRequest.from_dict(raw); frame = frame_for(request)
        window = self.window(request, frame)
        # Hidden identity is zero in the generated select-card record.
        self.assertEqual(window.message[9:13], b"\0" * 4)
        self.assertEqual(window.translate(b"\x01\x00", request=request, state_version="v1").action_id, "choice-1")
        for bad in (b"\x02\x00\x00", b"\x01\x01", b"\x00", b"\x01"):
            with self.subTest(bad=bad), self.assertRaises(WindBotTransportError):
                self.window(request, frame).translate(bad, request=request, state_version="v1")

    def test_seed_observer_digest_deadline_and_state_changes_are_rejected(self):
        request = legal_request(); frame = frame_for(request)
        raw = request_dict(request); raw["context"]["seed"] = 7
        with self.assertRaisesRegex(ContractError, "observer/request"):
            self.window(DecisionRequest.from_dict(raw), frame)
        with self.assertRaises(ContractError):
            WindBotWindow(request, frame, observer=1, deadline=10., clock=lambda: 1.)
        changed = request_dict(request); changed["decision_id"] = "different"
        for current, version in ((DecisionRequest.from_dict(changed), "v1"), (request, "stale")):
            with self.assertRaises(WindBotTransportError):
                self.window().translate(struct.pack("<i", 0), request=current, state_version=version)
        ticks = [1.]
        window = self.window(clock=lambda: ticks[0]); ticks[0] = 10.
        with self.assertRaisesRegex(WindBotTransportError, "expired"):
            window.translate(struct.pack("<i", 0), request=request, state_version="v1")

    def test_visible_queries_are_named_bound_and_hidden_cards_have_zero_flags(self):
        window = self.window()
        visible = game_message(WindBotMessage(7, {"player": 0, "location": 2, "sequence": 0,
            "cards": [{"sequence": 0, "code": 1, "position": 0, "level": 4, "owner": 0}]}), window)
        self.assertEqual(visible[2:7], bytes((1, 7, 0, 2, 0)))
        hidden = game_message(WindBotMessage(7, {"player": 1, "location": 8, "sequence": 0,
            "cards": [{"sequence": 0}]}), window)
        self.assertEqual(hidden[-8:], struct.pack("<II", 8, 0))
        for card in ({"sequence": 0, "code": 12345}, {"sequence": 0, "level": 8}):
            with self.assertRaisesRegex(ContractError, "hidden"):
                game_message(WindBotMessage(7, {"player": 1, "location": 8, "sequence": 0, "cards": [card]}), window)
        with self.assertRaisesRegex(ContractError, "identity differs"):
            game_message(WindBotMessage(7, {"player": 0, "location": 2, "sequence": 0,
                "cards": [{"sequence": 0, "code": 999}]}), window)
        with self.assertRaises(ContractError):
            game_message(WindBotMessage(7, {"player": 0, "location": 2, "sequence": 0,
                "cards": [{"sequence": 0, "raw": b"secret"}]}), window)

    def test_opponent_private_event_ids_and_unknown_message_shapes_are_rejected(self):
        window = self.window()
        with self.assertRaisesRegex(ContractError, "private draw"):
            game_message(WindBotMessage(90, {"player": 1, "card_ids": [999]}), window)
        with self.assertRaisesRegex(ContractError, "private opponent move"):
            game_message(WindBotMessage(50, {"card_id": 999, "previous": (1, 1, 0, 8),
                "current": (1, 2, 0, 0), "reason": 0}), window)
        self.assertEqual(game_message(WindBotMessage(90, {"player": 1, "card_ids": [0]}), window)[-4:], b"\0" * 4)
        public_move = game_message(WindBotMessage(50, {"card_id": 123, "previous": (1, 4, 0, 136),
            "current": (1, 4, 1, 136), "reason": 0}), window)
        self.assertEqual(struct.unpack_from("<I", public_move, 4)[0], 123)
        public_material = game_message(WindBotMessage(50, {"card_id": 123, "previous": (1, 1, 0, 8),
            "current": (1, 132, 0, 0), "reason": 0}), window)
        self.assertEqual(struct.unpack_from("<I", public_material, 4)[0], 123)
        with self.assertRaisesRegex(ContractError, "deck order"):
            game_message(WindBotMessage(50, {"card_id": 1, "previous": (0, 1, 33, 8),
                "current": (0, 2, 0, 0), "reason": 0}), window)
        with self.assertRaises(WindBotUnsupported):
            game_message(WindBotMessage(255, {}), window)
        with self.assertRaises(ContractError):
            game_message(WindBotMessage(40, {"player": 0, "seed": 7}), window)

    def test_hint_recipients_follow_the_locked_server_in_both_directions(self):
        window = self.window()
        for hint in range(1, 12):
            for source in (0, 1):
                allowed = hint in (10, 11) or hint in (1, 2, 3, 5) and source == 0 or hint in (4, 6, 7, 8, 9) and source == 1
                facts = {"hint": hint, "player": source, "value": 123}
                with self.subTest(hint=hint, source=source):
                    if allowed:
                        self.assertEqual(game_message(WindBotMessage(2, facts), window),
                            packet(1, bytes((2, hint, source)) + struct.pack("<I", 123)))
                    else:
                        with self.assertRaisesRegex(ContractError, "fixed LAN recipient"):
                            game_message(WindBotMessage(2, facts), window)
        with self.assertRaises(ContractError):
            game_message(WindBotMessage(2, {"hint": 12, "player": 0, "value": 123}), window)

    def test_confirm_cards_requires_current_visible_local_slots_and_never_deck_order(self):
        raw = request_dict(legal_request())
        raw["observation"]["cards"].append({"ref": "public-hand", "owner": 1,
            "controller": 1, "zone": "hand", "visibility": "public", "card_id": 123})
        request = DecisionRequest.from_dict(raw)
        frame = frame_for(request)
        frame = WindBotTransportFrame(0, digest(request.to_dict()), "v1", (),
            frame.slots + (WindBotSlot("public-hand", 1, 2, 0),))
        window = self.window(request, frame)
        card = {"card_id": 123, "controller": 1, "location": 2, "sequence": 0}
        payload = game_message(WindBotMessage(31, {"player": 0, "skip_panel": False, "cards": [card]}), window)
        self.assertEqual(payload[3:], bytes((31, 0, 0, 1)) + struct.pack("<I", 123) + bytes((1, 2, 0)))
        for changed in (dict(card, card_id=999), dict(card, sequence=1),
                        {"card_id": 999, "controller": 1, "location": 8, "sequence": 0}):
            with self.subTest(changed=changed), self.assertRaisesRegex(ContractError, "current legal visible slot"):
                game_message(WindBotMessage(31, {"player": 0, "skip_panel": True, "cards": [changed]}), window)
        with self.assertRaisesRegex(WindBotUnsupported, "deck order"):
            game_message(WindBotMessage(31, {"player": 0, "skip_panel": False,
                "cards": [dict(card, controller=0, location=1, sequence=0)]}), window)

    def test_public_confirmation_can_precede_a_move_after_its_old_hand_object_disappears(self):
        raw = request_dict(legal_request()); raw["observation"]["hand_counts"][1] = 0
        raw["observation"]["public_history"].append({"event_id": "broadcast-confirm", "kind": "reveal",
            "card_ids": [123], "details": {"message": 31, "player": 0,
                "locations": [{"controller": 1, "zone": "hand"}]}})
        request = DecisionRequest.from_dict(raw)
        facts = {"player": 0, "skip_panel": False, "public_ref": "broadcast-confirm",
            "cards": [{"card_id": 123, "controller": 1, "location": 2, "sequence": 0}]}
        confirm = WindBotMessage(31, facts)
        move = WindBotMessage(50, {"card_id": 123, "previous": (1, 2, 0, 0), "current": (1, 16, 0, 1), "reason": 0})
        proof = {"public_history_range": {"start": 0, "end": len(request.observation.public_history)},
            "public_confirmations": {"broadcast-confirm": {"message_index": 0}}}
        def make_window(changed_facts=facts, changed_proof=proof):
            return self.window(request, frame_for(request, messages=(WindBotMessage(31, changed_facts), move), facts=changed_proof))
        window = make_window()
        self.assertFalse(any(c.controller == 1 and c.zone == "hand" for c in request.observation.cards))
        self.assertEqual(game_message(confirm, window)[3:], bytes((31, 0, 0, 1)) + struct.pack("<I", 123) + bytes((1, 2, 0)))
        self.assertTrue(game_message(move, window))
        with self.assertRaisesRegex(ContractError, "old, repeated"):
            game_message(confirm, window)
        for changed in (dict(facts, public_ref="not-this-frame"), dict(facts, player=1),
                        dict(facts, cards=[dict(facts["cards"][0], card_id=999)]),
                        dict(facts, cards=[dict(facts["cards"][0], sequence=1)])):
            with self.subTest(changed=changed), self.assertRaises(ContractError):
                game_message(WindBotMessage(31, changed), make_window(changed))
        for changed in (dict(proof, public_history_range={"start": len(request.observation.public_history), "end": len(request.observation.public_history)}),
                        dict(proof, public_confirmations={"broadcast-confirm": {"message_index": 1}})):
            with self.subTest(changed=changed), self.assertRaises(ContractError):
                game_message(confirm, make_window(changed_proof=changed))

    def test_historical_public_field_sequence_is_exact_and_equal_content_needs_distinct_refs(self):
        raw = request_dict(legal_request())
        for ref in ("broadcast-a", "broadcast-b"):
            raw["observation"]["public_history"].append({"event_id": ref, "kind": "reveal", "card_ids": [123],
                "details": {"message": 31, "player": 0, "locations": [{"controller": 1, "zone": "monster", "sequence": 2}]}})
        request = DecisionRequest.from_dict(raw)
        messages = tuple(WindBotMessage(31, {"player": 0, "skip_panel": False, "public_ref": ref,
            "cards": [{"card_id": 123, "controller": 1, "location": 4, "sequence": 2}]}) for ref in ("broadcast-a", "broadcast-b"))
        facts = {"public_history_range": {"start": 1, "end": 3},
            "public_confirmations": {m.fields["public_ref"]: {"message_index": i} for i, m in enumerate(messages)}}
        window = self.window(request, frame_for(request, messages=messages, facts=facts))
        self.assertTrue(game_message(messages[0], window)); self.assertTrue(game_message(messages[1], window))
        changed = WindBotMessage(31, dict(messages[0].fields, cards=[dict(messages[0].fields["cards"][0], sequence=3)]))
        window = self.window(request, frame_for(request, messages=(changed,), facts=dict(facts,
            public_confirmations={"broadcast-a": {"message_index": 0}})))
        with self.assertRaisesRegex(ContractError, "identity/location multiset"):
            game_message(changed, window)

    def test_face_down_host_queries_only_admit_the_complete_public_material_list(self):
        raw = request_dict(legal_request())
        raw["observation"]["cards"] += [{"ref": "hidden-host", "owner": None, "controller": 1,
            "zone": "monster", "visibility": "hidden", "card_id": None, "position": 8, "material_count": 1},
            {"ref": "public-material", "owner": None, "controller": 1, "zone": "overlay",
             "visibility": "public", "card_id": 123, "attached_to": "hidden-host"}]
        request = DecisionRequest.from_dict(raw)
        frame = frame_for(request)
        frame = WindBotTransportFrame(0, digest(request.to_dict()), "v1", (), frame.slots + (
            WindBotSlot("hidden-host", 1, 4, 0), WindBotSlot("public-material", 1, 132, 0, 0)))
        window = self.window(request, frame)
        def query(card):
            return game_message(WindBotMessage(7, {"player": 1, "location": 4, "sequence": 0,
                "cards": [card]}), window)
        self.assertEqual(query({"sequence": 0, "overlay": [123]})[-16:], struct.pack("<IIII", 16, 0x10000, 1, 123))
        for card in ({"sequence": 0, "overlay": []}, {"sequence": 0, "overlay": [999]},
                     {"sequence": 0, "overlay": [123], "code": 9}):
            with self.subTest(card=card), self.assertRaisesRegex(ContractError, "hidden"):
                query(card)

    def test_private_deck_confirmation_is_bound_to_an_exact_order_free_legal_revelation(self):
        raw = request_dict(legal_request())
        raw["private_reveals"] = [{"ref": "legal-past-confirmation", "observer": 0, "message": 31,
            "cards": [{"card_id": code, "controller": 1, "zone": "deck"} for code in (123, 456)]}]
        request = DecisionRequest.from_dict(raw)
        window = self.window(request, frame_for(request))
        rows = [dict(card_id=code, controller=1, location=1, sequence=i) for i, code in enumerate((123, 456))]
        facts = {"player": 0, "skip_panel": True, "knowledge_ref": "legal-past-confirmation", "cards": rows}
        encoded = game_message(WindBotMessage(31, facts), window)
        self.assertEqual(encoded[3:7], bytes((31, 0, 1, 2)))
        self.assertEqual(encoded[7:], struct.pack("<I", 123) + bytes((1, 1, 0)) + struct.pack("<I", 456) + bytes((1, 1, 1)))
        for change in (dict(facts, player=1), dict(facts, knowledge_ref="unknown"),
                       dict(facts, cards=rows[:1]), dict(facts, cards=list(reversed(rows))),
                       dict(facts, cards=[dict(rows[0], sequence=38), rows[1]]),
                       dict(facts, cards=[dict(rows[0], card_id=999), rows[1]])):
            with self.subTest(change=change), self.assertRaises(ContractError):
                game_message(WindBotMessage(31, change), window)

    def test_unknown_reset_is_complete_zero_only_and_uses_public_old_vector_bounds(self):
        request = legal_request()
        departure = WindBotMessage(50, {"card_id": 0, "previous": (1, 2, 1, 0),
            "current": (1, 16, 0, 1), "reason": 0})
        window = self.window(request, frame_for(request, messages=(departure,)))
        def query(record, **extra):
            return game_message(WindBotMessage(7, dict(player=1, location=2, sequence=record["sequence"],
                cards=[record], redact=True, **extra)), window)
        reset = query(unknown_record(1))  # One card left; one public departure permits its old slot 1.
        record_size, flags = struct.unpack_from("<II", reset, 7)
        self.assertEqual(record_size, 88)
        self.assertEqual(len(reset), record_size + 7)
        self.assertFalse(flags & (2 | 0x40000))  # Neither private position nor invented ownership.
        self.assertEqual(reset[15:], b"\0" * 80)
        for record in (dict(unknown_record(1), attack=1), {"sequence": 1, "code": 0}, unknown_record(2),
                       dict(unknown_record(1), targets=[(1, 4, 0, 0)])):
            with self.subTest(record=record), self.assertRaises(ContractError):
                query(record)
        with self.assertRaisesRegex(ContractError, "single exact"):
            game_message(WindBotMessage(6, {"player": 1, "location": 2, "cards": [unknown_record(0)], "redact": True}), window)

    def test_swap_old_deck_reset_uses_public_conserved_zone_counts(self):
        raw = request_dict(legal_request())
        raw["observation"]["deck_counts"][1] = 2
        raw["observation"]["cards"] += [{"ref": f"grave-{i}", "owner": 1, "controller": 1,
            "zone": "graveyard", "visibility": "public", "card_id": 123} for i in range(30)]
        request = DecisionRequest.from_dict(raw)
        window = self.window(request, frame_for(request, messages=(WindBotMessage(35, {"player": 1, "old_grave_types": []}),)))
        facts = dict(player=1, location=1, sequence=29, cards=[unknown_record(29)], redact=True)
        self.assertTrue(game_message(WindBotMessage(7, facts), window))
        with self.assertRaisesRegex(ContractError, "publicly bounded"):
            game_message(WindBotMessage(7, dict(facts, sequence=32, cards=[unknown_record(32)])), window)

    def test_position_change_scalar_previous_does_not_break_nonfield_queries_or_redaction(self):
        request = legal_request()
        position = WindBotMessage(53, {"card_id": 123, "player": 0, "location": 4,
            "sequence": 0, "previous": 1, "current": 4})
        window = self.window(request, frame_for(request, messages=(position,)))
        self.assertEqual(game_message(position, window), packet(1, bytes((53,)) + struct.pack('<I', 123) + bytes((0, 4, 0, 1, 4))))
        for invalid in ([1], float('nan')):
            with self.subTest(invalid_previous=invalid), self.assertRaises(ContractError):
                game_message(WindBotMessage(53, dict(position.fields, previous=invalid)), window)
        for location in (1, 2):
            with self.subTest(location=location):
                self.assertTrue(game_message(WindBotMessage(7, {"player": 1, "location": location,
                    "sequence": 0, "cards": [{"sequence": 0}]}), window))
                self.assertTrue(game_message(WindBotMessage(7, {"player": 1, "location": location,
                    "sequence": 0, "cards": [unknown_record(0)], "redact": True}), window))

    def test_mixed_move_and_position_change_only_move_expands_old_vector(self):
        request = legal_request()
        position = WindBotMessage(53, {"card_id": 0, "player": 1, "location": 4,
            "sequence": 0, "previous": 8, "current": 1})
        for location in (1, 2):
            departure = WindBotMessage(50, {"card_id": 0, "previous": (1, location, 0, 0),
                "current": (1, 16, 0, 1), "reason": 0})
            window = self.window(request, frame_for(request, messages=(departure, position)))
            count = request.observation.deck_counts[1] if location == 1 else request.observation.hand_counts[1]
            def reset(sequence):
                return game_message(WindBotMessage(7, {"player": 1, "location": location,
                    "sequence": sequence, "cards": [unknown_record(sequence)], "redact": True}), window)
            with self.subTest(location=location):
                self.assertTrue(reset(count))  # Exactly the one public MSG50 departure.
                with self.assertRaisesRegex(ContractError, 'publicly bounded'):
                    reset(count + 1)

    def test_malformed_move_previous_scalar_is_contract_error_during_vector_validation(self):
        request = legal_request()
        malformed = WindBotMessage(50, {"card_id": 0, "previous": 8,
            "current": (1, 16, 0, 1), "reason": 0})
        window = self.window(request, frame_for(request, messages=(malformed,)))
        with self.assertRaises(ContractError):
            game_message(malformed, window)
        with self.assertRaises(ContractError):
            game_message(WindBotMessage(7, {"player": 1, "location": 2, "sequence": 0,
                "cards": [unknown_record(0)], "redact": True}), window)

    def test_position_change_does_not_remove_swap_public_union_bound(self):
        raw = request_dict(legal_request())
        raw['observation']['deck_counts'][1] = 2
        raw['observation']['cards'] += [{"ref": f"grave-position-{i}", "owner": 1, "controller": 1,
            "zone": "graveyard", "visibility": "public", "card_id": 123} for i in range(30)]
        request = DecisionRequest.from_dict(raw)
        messages = (WindBotMessage(35, {"player": 1, "old_grave_types": []}),
            WindBotMessage(53, {"card_id": 0, "player": 1, "location": 4,
                "sequence": 0, "previous": 8, "current": 1}))
        window = self.window(request, frame_for(request, messages=messages))
        def reset(sequence):
            return game_message(WindBotMessage(7, {"player": 1, "location": 1, "sequence": sequence,
                "cards": [unknown_record(sequence)], "redact": True}), window)
        self.assertTrue(reset(31))
        with self.assertRaisesRegex(ContractError, 'publicly bounded'):
            reset(32)

    def test_public_top_confirmations_keep_multisets_without_original_positions(self):
        raw = request_dict(legal_request())
        for kind in (30, 42):
            raw["observation"]["public_history"].append({"event_id": f"top-{kind}", "kind": "reveal",
                "card_ids": [456, 123], "details": {"message": kind, "player": 1}})
        raw["observation"]["public_history"].append({"event_id": "top-38", "kind": "reveal",
            "card_ids": [123], "details": {"message": 38, "player": 1}})
        request = DecisionRequest.from_dict(raw); window = self.window(request, frame_for(request))
        for kind, zone in ((30, 1), (42, 64)):
            first = game_message(WindBotMessage(kind, {"player": 1, "card_ids": [456, 123]}), window)
            second = game_message(WindBotMessage(kind, {"player": 1, "card_ids": [123, 456]}), window)
            self.assertEqual(first, second)
            self.assertEqual(first[6:], struct.pack("<I", 123) + bytes((1, zone, 0)) + struct.pack("<I", 456) + bytes((1, zone, 0)))
            with self.assertRaisesRegex(ContractError, "history evidence"):
                game_message(WindBotMessage(kind, {"player": 1, "card_ids": [999]}), window)
        top = game_message(WindBotMessage(38, {"player": 1, "card_id": 123, "faceup": True}), window)
        self.assertEqual(top[4:], bytes((1, 0)) + struct.pack("<I", 123 | 0x80000000))
        with self.assertRaises(ContractError):
            game_message(WindBotMessage(38, {"player": 1, "card_id": 123, "faceup": True, "offset": 9}), window)

    def test_set_shuffle_canonicalizes_old_slots_and_never_sends_hidden_permutation(self):
        slots = [(1, 4, 3, 8), (1, 4, 1, 8)]
        window = self.window()
        first = game_message(WindBotMessage(36, {"location": 4, "slots": slots}), window)
        self.assertEqual(first, game_message(WindBotMessage(36, {"location": 4, "slots": list(reversed(slots))}), window))
        self.assertEqual(first[4:], bytes((4, 2, 1, 4, 1, 8, 1, 4, 3, 8)) + b"\0" * 8)
        for change in (dict(location=4, slots=slots, destinations=list(reversed(slots))),
                       dict(location=4, slots=[slots[0], (1, 4, 5, 8)]),
                       dict(location=4, slots=[slots[0], (0, 4, 1, 8)]),
                       dict(location=4, slots=[slots[0], (1, 4, 1, 1)]),
                       dict(location=4, slots=slots * 3)):
            with self.subTest(change=change), self.assertRaises(ContractError):
                game_message(WindBotMessage(36, change), window)

    def test_other_existing_native_events_have_exact_named_layouts(self):
        a, b = (0, 4, 1, 1), (1, 4, 3, 4)
        layouts = ((35, {"player": 1, "old_grave_types": []}, b"\1"), (37, {}, b""),
            (54, {"slot": a}, b"\0" * 4 + bytes(a)),
            (55, {"first_card_id": 123, "first": a, "second_card_id": 456, "second": b},
                struct.pack("<I", 123) + bytes(a) + struct.pack("<I", 456) + bytes(b)),
            (56, {"mask": 0x10001}, struct.pack("<I", 0x10001)),
            (81, {"player": 0, "slots": [a, b]}, bytes((0, 2)) + bytes(a) + bytes(b)),
            (83, {"slots": [a]}, bytes((1,)) + bytes(a)),
            (95, {"slot": a}, bytes(a)),  # Legacy client codec, not a current core emitted event.
            (120, {"card_id": 123, "slot": a}, struct.pack("<I", 123) + bytes(a)),
            (130, {"player": 0, "values": [0, 1]}, bytes((0, 2, 0, 1))),
            (131, {"player": 1, "values": [1, 6]}, bytes((1, 2, 1, 6))),
            (133, {"values": [2, 3]}, bytes((14,))),
            (160, {"slot": a, "hint": 2, "value": 123}, bytes(a) + b"\2" + struct.pack("<I", 123)),
            (165, {"player": 1, "hint": 6, "value": 999}, bytes((1, 6)) + struct.pack("<I", 999)),
            (170, {"card_id": 123}, struct.pack("<I", 123)))
        for kind, facts, body in layouts:
            with self.subTest(kind=kind):
                self.assertEqual(game_message(WindBotMessage(kind, facts), self.window())[3:], bytes((kind,)) + body)
        for kind, facts in ((120, {"card_id": 123, "slot": b}),
                            (130, {"player": 1, "values": [2]}), (131, {"player": 1, "values": [0]}),
                            (133, {"values": [0, 1]}),
                            (55, {"first_card_id": 0, "first": a, "second_card_id": 999, "second": (1, 2, 0, 0)})):
            with self.subTest(kind=kind), self.assertRaises(ContractError):
                game_message(WindBotMessage(kind, facts), self.window())

    def test_swap_refreshes_public_catalog_classification_before_client_bookkeeping(self):
        raw = request_dict(legal_request())
        raw["observation"]["public_history"].append({"event_id": "old-extra-to-grave", "kind": "move",
            "card_ids": [123], "details": {"message": 50, "locations": [{"controller": 1, "zone": "graveyard", "sequence": 0}]}})
        request = DecisionRequest.from_dict(raw)
        facts = {"player": 1, "old_grave_types": [{"sequence": 0, "card_id": 123, "type": 0x800001}]}
        window = self.window(request, frame_for(request, messages=(WindBotMessage(35, facts),)))
        encoded = game_message(WindBotMessage(35, facts), window)
        update_size = struct.unpack_from("<H", encoded)[0]
        update, swap = encoded[:update_size + 2], encoded[update_size + 2:]
        self.assertEqual(update, packet(1, bytes((7, 1, 16, 0)) + struct.pack("<IIII", 16, 9, 123, 0x800001)))
        self.assertEqual(swap, packet(1, bytes((35, 1))))
        with self.assertRaises(ContractError):
            game_message(WindBotMessage(35, {"player": 1}), window)
        for row in ({"sequence": 0, "card_id": 999, "type": 0x800001},
                    {"sequence": 1, "card_id": 123, "type": 0x800001},
                    {"sequence": 0, "card_id": 123, "type": 0}):
            with self.subTest(row=row), self.assertRaises(ContractError):
                game_message(WindBotMessage(35, {"player": 1, "old_grave_types": [row]}), window)

    def test_first_public_activation_initializes_catalog_type_before_executor_callback(self):
        raw = request_dict(legal_request())
        raw["observation"]["public_history"].append({"event_id": "hand-trap-activation", "kind": "activate",
            "card_ids": [1], "details": {"message": 70}})
        request = DecisionRequest.from_dict(raw); window = self.window(request, frame_for(request))
        facts = {"card_id": 1, "card_type": 17, "slot": (0, 2, 0, 0), "chain_location": (0, 2, 0),
                 "description": 16, "link": 1}
        encoded = game_message(WindBotMessage(70, facts), window)
        update_size = struct.unpack_from("<H", encoded)[0]
        self.assertEqual(encoded[:update_size + 2], packet(1, bytes((7, 0, 2, 0)) + struct.pack("<IIII", 16, 9, 1, 17)))
        self.assertEqual(encoded[update_size + 2:], packet(1, bytes((70,)) + struct.pack("<I", 1)
            + bytes((0, 2, 0, 0, 0, 2, 0)) + struct.pack("<I", 16) + b"\1"))
        # A field trap monster may already have a legal dynamic monster Type;
        # its printed trap Type must not replace that state before OnChaining.
        field = game_message(WindBotMessage(70, dict(facts, card_type=4, slot=(0, 4, 0, 1))), window)
        self.assertEqual(field[3], 70)
        self.assertEqual(struct.unpack_from("<H", field)[0] + 2, len(field))
        for change in (dict(facts, card_type=0), dict(facts, card_id=999)):
            with self.subTest(change=change), self.assertRaises(ContractError):
                game_message(WindBotMessage(70, change), window)
        with self.assertRaisesRegex(WindBotUnsupported, "persistent"):
            game_message(WindBotMessage(70, dict(facts, slot=(0, 132, 0, 0))), window)

    def test_legacy_unequip_codec_does_not_claim_current_native_consumer_support(self):
        from ygo_kito.native_protocol import NativeError, Reader
        from ygo_kito.public_history import consume
        with self.assertRaisesRegex(NativeError, "unsupported revision-3 native event 95"):
            consume(SimpleNamespace(), 95, Reader(bytes((0, 8, 0, 0))), {})

    def test_exact_battle_layout_matches_the_fixed_client_reader(self):
        payload = game_message(WindBotMessage(111, {"attacker": (0, 4, 0, 1), "attacker_attack": 1000,
            "attacker_defense": 900, "attacker_destroyed": 0, "defender": (1, 4, 1, 4),
            "defender_attack": 700, "defender_defense": 800, "defender_destroyed": 1}), self.window())
        self.assertEqual(len(payload), 30)  # length + STOC + GameMsg + exact 26-byte battle body.
        self.assertEqual(struct.unpack_from("<ii", payload, 8), (1000, 900))

    def test_placement_bytes_only_select_offered_destinations(self):
        raw = request_dict(legal_request())
        raw["prompt"] = {"message": 18, "minimum": 1, "maximum": 1}
        raw["actions"] = [{"action_id": "zone-" + str(i), "kind": "select", "card_refs": [], "value": i,
            "details": {"destination": {"controller": 0, "zone": "monster", "sequence": i}}} for i in (2, 3)]
        request = DecisionRequest.from_dict(raw); frame = frame_for(request)
        self.assertEqual(self.window(request, frame).translate(bytes((0, 4, 3)), request=request,
            state_version="v1").action_id, "zone-3")
        with self.assertRaises(WindBotTransportError):
            self.window(request, frame).translate(bytes((0, 4, 4)), request=request, state_version="v1")

    def test_tribute_weights_and_chain_forced_flags_must_be_explicit(self):
        raw = request_dict(legal_request())
        raw["observation"]["cards"][0].update(zone="monster", visibility="public", position=1)
        raw["prompt"] = {"message": 20, "minimum": 1, "maximum": 1}
        raw["actions"] = [{"action_id": "release", "kind": "select", "card_refs": ["own-hand-1"], "value": 1}]
        request = DecisionRequest.from_dict(raw)
        slots = (WindBotSlot("own-hand-1", 0, 4, 0), WindBotSlot("opponent-set-1", 1, 8, 0))
        frame = WindBotTransportFrame(0, digest(request.to_dict()), "v1", (), slots)
        with self.assertRaisesRegex(WindBotUnsupported, "release weights"):
            self.window(request, frame)
        frame = WindBotTransportFrame(0, digest(request.to_dict()), "v1", (), slots, {"tribute_weights": {"own-hand-1": 1}})
        self.assertEqual(self.window(request, frame).translate(b"\x01\x00", request=request, state_version="v1").action_id, "release")
        raw["prompt"] = {"message": 16}
        raw["actions"] = [{"action_id": "chain", "kind": "activate", "card_refs": ["own-hand-1"],
                           "value": 32, "details": {"description": 32}}]
        request = DecisionRequest.from_dict(raw)
        facts = {"chain_hints": (0, 0), "chain_special_count": 0, "chain": {"chain": {"flag": 0, "forced": True}}}
        frame = WindBotTransportFrame(0, digest(request.to_dict()), "v1", (), slots, facts)
        self.assertEqual(self.window(request, frame).translate(struct.pack("<i", 0), request=request, state_version="v1").action_id, "chain")
        facts["chain"]["chain"].pop("forced")
        with self.assertRaisesRegex(WindBotUnsupported, "forced/flag"):
            self.window(request, WindBotTransportFrame(0, digest(request.to_dict()), "v1", (), slots, facts))

    def test_sum_uses_typed_constraints_and_rejects_changed_mandatory_padding(self):
        raw = request_dict(legal_request())
        raw["observation"]["cards"].append({"ref": "own-second", "owner": 0, "controller": 0,
            "zone": "monster", "visibility": "public", "card_id": 2, "position": 1})
        raw["prompt"] = {"message": 23, "minimum": 1, "maximum": 1}
        raw["sum_selection"] = {"mode": "equal", "target": 5, "minimum_optional": 1, "maximum_optional": 1,
            "mandatory": [{"ref": "own-hand-1", "values": [2]}], "optional": [{"ref": "own-second", "values": [3]}]}
        raw["actions"] = [{"action_id": "sum", "kind": "select", "card_refs": ["own-hand-1", "own-second"],
                           "value": 2, "details": {"operation": "sum"}}]
        request = DecisionRequest.from_dict(raw)
        slots = (*frame_for(request).slots, WindBotSlot("own-second", 0, 4, 0))
        frame = WindBotTransportFrame(0, digest(request.to_dict()), "v1", (), slots)
        self.assertEqual(self.window(request, frame).translate(b"\x02\x00\x00", request=request, state_version="v1").action_id, "sum")
        for payload in (b"\x02\x01\x00", b"\x03\x00\x00\x00", b"\x02\x00\x01"):
            with self.subTest(payload=payload), self.assertRaises(WindBotTransportError):
                self.window(request, frame).translate(payload, request=request, state_version="v1")


class WindBotLoopbackTests(unittest.TestCase):
    def session_fixture(self, directory, process, *, wall_seconds=2.):
        import hashlib
        paths = {key: directory / key for key in ("mono", "executable", "database", "deck_file")}
        for path in paths.values():
            path.write_bytes(b"non-executable-owned-process-fixture")
        seals = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in paths.items()}
        return windbot_session(DeckParts(tuple([1] * 40)), observer=0, duel_rule=5, **paths,
            executor="Fixture", allowed_executors={"Fixture"}, working_directory=directory,
            expected_sha256=seals, wall_seconds=wall_seconds)

    def test_session_cleanup_targets_and_reaps_only_its_owned_child(self):
        class OwnedProcess:
            def __init__(self, timeouts):
                self.timeouts = timeouts; self.terminates = self.kills = self.waits = 0
            def wait(self, timeout):
                self.waits += 1
                if self.waits <= self.timeouts:
                    raise subprocess.TimeoutExpired("explicit-owned-process-fixture", timeout)
                return 0 if not self.terminates else -9 if self.kills else -15
            def terminate(self): self.terminates += 1
            def kill(self): self.kills += 1
        for timeouts, stage in ((0, "room_closed"), (1, "terminated"), (2, "killed")):
            child = OwnedProcess(timeouts)
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                with patch("ygo_kito.windbot_room.subprocess.Popen", return_value=child) as popen, \
                        patch.object(WindBotRoom, "accept", return_value={"fixture": True}):
                    with self.session_fixture(Path(temp), child) as room:
                        self.assertIsNone(room.process_outcome)
                    self.assertTrue(room.closed)
                    self.assertEqual(room.process_outcome["shutdown"], stage)
                    self.assertTrue(room.process_outcome["reaped"])
                    self.assertFalse(room.process_outcome["uncertain"])
                    self.assertEqual(child.terminates, int(timeouts > 0))
                    self.assertEqual(child.kills, int(timeouts > 1))
                    popen.assert_called_once()
                    self.assertFalse(popen.call_args.kwargs["shell"])

    def test_owned_child_reap_failure_is_uncertain_and_never_success(self):
        class Unreaped:
            def wait(self, timeout): raise subprocess.TimeoutExpired("explicit-unreaped-fixture", timeout)
            def terminate(self): pass
            def kill(self): pass
        with tempfile.TemporaryDirectory() as temp:
            with patch("ygo_kito.windbot_room.subprocess.Popen", return_value=Unreaped()), \
                    patch.object(WindBotRoom, "accept", return_value={"fixture": True}):
                with self.assertRaisesRegex(WindBotTransportError, "exit/reap is uncertain"):
                    with self.session_fixture(Path(temp), None) as room:
                        pass
                self.assertTrue(room.closed)
                self.assertFalse(room.process_outcome["reaped"])
                self.assertTrue(room.process_outcome["uncertain"])

    def test_session_deadline_reaps_owned_child_even_between_prompts(self):
        stopped = threading.Event()
        class OwnedProcess:
            def __init__(self): self.waits = 0; self.terminates = 0
            def wait(self, timeout):
                self.waits += 1
                if self.waits == 1: raise subprocess.TimeoutExpired("owned-deadline-fixture", timeout)
                stopped.set(); return -15
            def terminate(self): self.terminates += 1
            def kill(self): raise AssertionError("fixture exits on normal terminate")
        child = OwnedProcess()
        with tempfile.TemporaryDirectory() as temp:
            with patch("ygo_kito.windbot_room.subprocess.Popen", return_value=child), \
                    patch.object(WindBotRoom, "accept", return_value={"fixture": True}):
                with self.session_fixture(Path(temp), child, wall_seconds=.03) as room:
                    self.assertTrue(stopped.wait(1.))
                    self.assertTrue(room.closed)
                self.assertEqual(room.process_outcome["reason"], "room_deadline_expired")
                self.assertTrue(room.process_outcome["reaped"])
                self.assertEqual(child.terminates, 1)

    def test_expired_room_lifetime_cannot_start_a_fresh_lobby_timeout(self):
        ticks = [0.]
        with WindBotRoom(DeckParts(tuple([1] * 40)), observer=0, duel_rule=5,
                        timeout=10., wall_seconds=1., clock=lambda: ticks[0]) as room:
            ticks[0] = 2.
            with self.assertRaisesRegex(WindBotTransportError, "deadline expired"):
                room.accept()
            self.assertTrue(room.closed)

    def start_peer(self, room, *, reply=struct.pack("<i", 0), wrong_deck=False, token=None, wait=0., duplicate=False, hold=None):
        errors = []
        def peer():
            try:
                with socket.create_connection(("127.0.0.1", room.port), timeout=2.) as sock:
                    sock.settimeout(2.)
                    name = "Python-wire-fixture".encode("utf-16-le").ljust(40, b"\0")
                    info = (token if token is not None else room.token).encode("utf-16-le").ljust(40, b"\0")
                    sock.sendall(packet(16, name) + packet(18, struct.pack("<H", room.protocol_version) + b"\xcc\xcc\0\0\0\0" + info))
                    self.assertEqual(receive(sock)[0], 18)
                    self.assertEqual(receive(sock)[0], 19)
                    cards = list(room.deck.main) + list(room.deck.extra) + list(room.deck.side)
                    if wrong_deck: cards[0] = 999
                    sock.sendall(packet(2, struct.pack("<II", len(room.deck.main) + len(room.deck.extra), len(room.deck.side))
                        + b"".join(struct.pack("<I", c) for c in cards)) + packet(34))
                    if wrong_deck: return
                    self.assertEqual(receive(sock)[1][0], 4)
                    self.assertEqual(receive(sock)[1][0], 11)
                    if wait: time.sleep(wait)
                    sock.sendall(packet(1, reply) * (2 if duplicate else 1))
                    if hold is not None:
                        hold.wait(2.)
            except (EOFError, BrokenPipeError, ConnectionResetError):
                pass  # Expected when the host rejects or times out a fixture.
            except BaseException as error:
                errors.append(error)
        thread = threading.Thread(target=peer, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3.)
        return thread, errors

    def test_actual_socket_handshake_deck_binding_and_current_action_selection(self):
        with WindBotRoom(DeckParts(tuple([1] * 40)), observer=0, duel_rule=5, timeout=1.) as room:
            thread, errors = self.start_peer(room)
            result = room.accept()
            self.assertFalse(result["executor_identity_verified"])
            request = legal_request()
            action = room.choose(request, frame_for(request, messages=(start_message(),)))
            self.assertEqual(action.action_id, "normal")
            thread.join(2.); self.assertEqual(errors, [])
            with self.assertRaises(WindBotTransportError):
                room.choose(request, frame_for(request, messages=()))
            self.assertTrue(room.closed)

    def test_wrong_deck_and_late_response_close_connection_without_reusing_window(self):
        with WindBotRoom(DeckParts(tuple([1] * 40)), observer=0, duel_rule=5, timeout=.1) as room:
            _, errors = self.start_peer(room, wrong_deck=True)
            with self.assertRaisesRegex(WindBotTransportError, "different fixed deck"):
                room.accept()
            self.assertTrue(room.closed); self.assertEqual(errors, [])
        with WindBotRoom(DeckParts(tuple([1] * 40)), observer=0, duel_rule=5, timeout=.1) as room:
            thread, errors = self.start_peer(room, wait=.2)
            room.accept(); request = legal_request()
            with self.assertRaises(WindBotTransportError):
                room.choose(request, frame_for(request, messages=(start_message(),)))
            self.assertTrue(room.closed)
            thread.join(2.); self.assertEqual(errors, [])

    def test_duplicate_previous_response_is_not_used_for_a_new_window(self):
        with WindBotRoom(DeckParts(tuple([1] * 40)), observer=0, duel_rule=5, timeout=1.) as room:
            thread, errors = self.start_peer(room, duplicate=True)
            room.accept(); request = legal_request()
            room.choose(request, frame_for(request, messages=(start_message(),)))
            with self.assertRaisesRegex(WindBotTransportError, "unsolicited or stale"):
                room.choose(request, frame_for(request, version="v2"))
            self.assertTrue(room.closed)
            thread.join(2.); self.assertEqual(errors, [])

    def test_connection_history_range_cannot_replay_or_replace_a_consumed_prefix(self):
        for mutation in ("replay-range", "changed-prefix", "truncated-prefix"):
            hold = threading.Event()
            with self.subTest(mutation=mutation), WindBotRoom(DeckParts(tuple([1] * 40)), observer=0, duel_rule=5, timeout=1.) as room:
                thread, errors = self.start_peer(room, hold=hold)
                try:
                    room.accept(); request = legal_request()
                    facts = {"public_history_range": {"start": 0, "end": 1}}
                    room.choose(request, frame_for(request, messages=(start_message(),), facts=facts))
                    raw = request_dict(request); raw["decision_id"] += "-next"
                    if mutation == "changed-prefix": raw["observation"]["public_history"][0]["card_ids"] = [999]
                    if mutation == "truncated-prefix": raw["observation"]["public_history"] = []
                    next_request = DecisionRequest.from_dict(raw)
                    with self.assertRaisesRegex(ContractError, "public (confirmation )?history"):
                        room.choose(next_request, frame_for(next_request, version="v2", facts=facts))
                    self.assertTrue(room.closed)
                finally:
                    hold.set(); thread.join(2.)
                self.assertEqual(errors, [])

    def test_launcher_is_explicit_non_server_loopback_and_rejects_unknown_executor(self):
        with tempfile.TemporaryDirectory() as temporary, WindBotRoom(DeckParts(tuple([1] * 40)), observer=0, duel_rule=5) as room:
            paths = [Path(temporary) / name for name in ("mono", "WindBot.exe", "cards.cdb", "fixed.ydk")]
            for path in paths: path.write_bytes(b"contract-fixture-only-not-a-build")
            argv = windbot_command(*paths, "FixedExecutor", room=room, allowed_executors={"FixedExecutor"})
            for flag in ("ServerMode=False", "Host=127.0.0.1", "Deck=FixedExecutor", "Chat=False", "Debug=False"):
                self.assertIn(flag, argv)
            self.assertIn("DeckFile=" + str(paths[3].resolve()), argv)
            spaced = windbot_command(*paths, "Toadally Awesome", room=room, allowed_executors={"Toadally Awesome"})
            self.assertIn("Deck=Toadally Awesome", spaced)  # One argv element; never a shell string.
            with self.assertRaises(ContractError):
                windbot_command(*paths, "Unknown", room=room, allowed_executors={"FixedExecutor"})
        with self.assertRaises(ContractError):
            WindBotRoom(DeckParts(tuple([1] * 40)), observer=0, duel_rule=5, host="0.0.0.0")

    def test_unapproved_runtime_hash_is_rejected_before_a_process_or_room_starts(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            paths = {name: directory / name for name in ("mono", "executable", "database", "deck_file")}
            for path in paths.values(): path.write_bytes(b"unapproved-contract-fixture")
            with self.assertRaisesRegex(ContractError, "runtime file checksum differs"):
                with windbot_session(DeckParts(tuple([1] * 40)), observer=0, duel_rule=5, **paths,
                        executor="FixedExecutor", allowed_executors={"FixedExecutor"}, working_directory=directory,
                        expected_sha256={name: "0" * 64 for name in paths}):
                    self.fail("unapproved file must not reach the launch body")


if __name__ == "__main__":
    unittest.main()
