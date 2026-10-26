"""Loopback YGOPro LAN transport for an explicitly selected real WindBot.

Only typed, recipient-filtered host facts enter the client. Responses select
existing legal actions; this module neither reads native response maps nor
calls ctypes. Source builds, rule coverage and bot strength are separate facts.
"""
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
import math
import hashlib
import json
from pathlib import Path
import secrets
import select
import socket
import struct
import subprocess
import threading
import time

from .build_contracts import DeckParts, digest
from .contracts import DecisionRequest
from .validation import ContractError, canonical_json, fields, integer, text

CTOS_RESPONSE, CTOS_DECK, CTOS_INFO, CTOS_JOIN = 1, 2, 16, 18
STOC_GAME, STOC_JOIN, STOC_TYPE, STOC_END = 1, 18, 19, 22
LOCATION = {"deck": 1, "hand": 2, "monster": 4, "spell_trap": 8,
            "graveyard": 16, "banished": 32, "extra": 64, "overlay": 128}


class WindBotUnsupported(ContractError):
    """Exact legal transport facts are missing; never substitute a generic AI."""


class WindBotTransportError(ContractError):
    pass


def _u8(value):
    return struct.pack("<B", integer(value, "LAN byte", 0, 255))


def _u16(value):
    return struct.pack("<H", integer(value, "LAN uint16", 0, 65535))


def _u32(value):
    return struct.pack("<I", integer(value, "LAN uint32", 0, 2**32 - 1))


def _i32(value):
    integer(value, "LAN int32 bits", -2**31, 2**32 - 1)
    return struct.pack("<I", value & 0xffffffff)


def packet(kind, payload=b""):
    if not isinstance(payload, bytes):
        raise ContractError("LAN packet payload must be bytes")
    body = _u8(kind) + payload
    if len(body) > 65535:
        raise WindBotUnsupported("LAN packet exceeds fixed protocol limit")
    return _u16(len(body)) + body


@dataclass(frozen=True)
class WindBotSlot:
    ref: str
    controller: int
    location: int
    sequence: int
    subsequence: int = 0

    def __post_init__(self):
        text(self.ref, "LAN-local reference")
        integer(self.controller, "LAN controller", 0, 1)
        integer(self.location, "LAN location", 0, 255)
        if self.location not in (1, 2, 4, 8, 16, 32, 64, 132, 136, 192):
            raise ContractError("unsupported LAN card location")
        integer(self.sequence, "LAN-local sequence", 0, 255)
        integer(self.subsequence, "LAN-local material sequence", 0, 127)


@dataclass(frozen=True)
class WindBotMessage:
    kind: int
    fields: dict

    def __post_init__(self):
        integer(self.kind, "recipient-filtered LAN message", 0, 255)
        if not isinstance(self.fields, dict):
            raise ContractError("named recipient-filtered message fields required")


@dataclass(frozen=True)
class WindBotTransportFrame:
    observer: int
    request_sha256: str
    state_version: str
    messages: tuple[WindBotMessage, ...]
    slots: tuple[WindBotSlot, ...]
    prompt_facts: dict = field(default_factory=dict)

    def __post_init__(self):
        integer(self.observer, "LAN observer", 0, 1)
        text(self.state_version, "LAN state version")
        from .coord_contracts import sha256
        sha256(self.request_sha256)
        if (not isinstance(self.messages, tuple) or len(self.messages) > 4096 or
                any(not isinstance(m, WindBotMessage) for m in self.messages)):
            raise ContractError("bounded typed recipient-filtered messages required")
        if (not isinstance(self.slots, tuple) or len(self.slots) > 512 or
                any(not isinstance(s, WindBotSlot) for s in self.slots)):
            raise ContractError("bounded LAN-local slot registry required")
        if len({s.ref for s in self.slots}) != len(self.slots):
            raise ContractError("duplicate LAN-local reference")
        if not isinstance(self.prompt_facts, dict):
            raise ContractError("named prompt facts required")


class WindBotWindow:
    """A host-bound LAN prompt and its exact action-ID response decoder."""
    def __init__(self, request, frame, *, observer, deadline, clock=time.monotonic):
        if not isinstance(request, DecisionRequest) or not isinstance(frame, WindBotTransportFrame):
            raise ContractError("typed legal request and recipient-filtered frame required")
        if (request.context.seed is not None or request.observation.observer != observer or
                frame.observer != observer or frame.request_sha256 != digest(request.to_dict())):
            raise ContractError("LAN frame differs from its fixed legal observer/request")
        if type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline <= clock():
            raise WindBotTransportError("LAN decision deadline has expired")
        self.request, self.frame = DecisionRequest.from_dict(json.loads(canonical_json(request.to_dict()))), deepcopy(frame)
        self.observer, self.deadline, self.clock, self.used = observer, deadline, clock, False
        self.slots = {s.ref: s for s in self.frame.slots}
        self.cards = {c.ref: c for c in (*request.observation.cards, *request.search_choices, *request.selection_choices)}
        if set(self.slots) - self.cards.keys():
            raise ContractError("LAN slot references a card absent from this legal request")
        for ref, slot in self.slots.items():
            card = self.cards[ref]
            controller = getattr(card, "controller", getattr(card, "owner", None))
            zone = getattr(card, "zone", "deck")
            if controller != slot.controller or (slot.location & 0x7f if slot.location & 0x80 else slot.location) != (
                    LOCATION[zone] if zone != "overlay" else slot.location & 0x7f):
                raise ContractError("LAN slot changes a legal card's controller/zone")
        self.responses, self.selection_refs, self.sum_refs = {}, None, None
        self._public_confirmations_used = set()
        self.message = self._prompt()

    def _card(self, ref, *, tail=False):
        if ref not in self.slots:
            raise WindBotUnsupported("legal card has no exact LAN-local slot: " + ref)
        card, slot = self.cards[ref], self.slots[ref]
        code = getattr(card, "card_id", None) or 0
        if getattr(card, "visibility", None) == "hidden":
            code = 0
        body = _u32(code) + bytes((slot.controller, slot.location, slot.sequence))
        return body + _u8(slot.subsequence) if tail else body

    def _response(self, payload, action):
        old = self.responses.get(payload)
        if old is not None and old != action.action_id:
            raise WindBotUnsupported("LAN response would ambiguously identify several legal actions")
        self.responses[payload] = action.action_id

    def _prompt(self):
        if self.request.prompt is None:
            raise WindBotUnsupported("LAN requires an explicit supported prompt")
        kind, actions, facts = self.request.prompt.message, self.request.actions, self.frame.prompt_facts
        body = _u8(self.observer)
        if kind in (10, 11):
            groups = [[] for _ in range(2 if kind == 10 else 6)]
            passes = {}
            for action in actions:
                if action.kind == "pass" or action.details and action.details.operation == "shuffle":
                    passes[action.value] = action
                    continue
                if len(action.card_refs) != 1:
                    raise WindBotUnsupported("LAN command needs one exact card reference")
                if kind == 10:
                    mode = {"activate": 0, "attack": 1}.get(action.kind)
                else:
                    mode = {"summon": 0, "special_summon": 1, "position": 2, "activate": 5}.get(action.kind)
                    if action.kind == "set":
                        mode = facts.get("idle_set_modes", {}).get(action.action_id)
                        if mode not in (3, 4):
                            raise WindBotUnsupported("idle set needs its exact offered monster/spell mode")
                if mode is None:
                    raise WindBotUnsupported("unsupported legal LAN command kind")
                groups[mode].append(action)
            for mode, group in enumerate(groups):
                body += _u8(len(group))
                for index, action in enumerate(group):
                    body += self._card(action.card_refs[0])
                    if mode == (0 if kind == 10 else 5):
                        if action.details is None or action.details.description is None:
                            raise WindBotUnsupported("activation description is unavailable")
                        body += _u32(action.details.description)
                    if kind == 10 and mode == 1:
                        direct = facts.get("direct_attack", {}).get(action.action_id)
                        if type(direct) is not bool:
                            raise WindBotUnsupported("battle command needs the actual direct-attack flag")
                        body += _u8(int(direct))
                    self._response(_i32((index << 16) | mode), action)
            values = (2, 3) if kind == 10 else (6, 7, 8)
            if set(passes) - set(values):
                raise WindBotUnsupported("unknown command phase/shuffle value")
            for value in values:
                body += _u8(int(value in passes))
                if value in passes:
                    self._response(_i32(value), passes[value])
        elif kind in (12, 13):
            descriptions = {a.details.description for a in actions if a.details is not None}
            if len(descriptions) != 1:
                raise WindBotUnsupported("yes/no requires one exact public/private description")
            if kind == 12:
                refs = {a.card_refs for a in actions}
                if len(refs) != 1 or len(next(iter(refs))) != 1:
                    raise WindBotUnsupported("effect yes/no lacks its offered card")
                body += self._card(next(iter(refs))[0], tail=True)
            body += _u32(next(iter(descriptions)))
            for action in actions:
                if action.kind not in ("yes", "no"):
                    raise WindBotUnsupported("unexpected yes/no action")
                self._response(_i32(int(action.kind == "yes")), action)
        elif kind in (14, 143):
            body += _u8(len(actions))
            for index, action in enumerate(actions):
                body += _u32(action.value)
                self._response(_i32(index), action)
        elif kind == 19:
            code = facts.get("position_card_id")
            if code is None:
                raise WindBotUnsupported("position prompt card identity was not retained by the legal DTO")
            mask = 0
            for action in actions:
                if action.kind != "position" or action.value not in (1, 2, 4, 8):
                    raise WindBotUnsupported("unsupported position choice")
                mask |= action.value
                self._response(_i32(action.value), action)
            body += _u32(code) + _u8(mask)
        elif kind in (15, 20):
            prompt = self.request.prompt
            refs = tuple(dict.fromkeys(ref for action in actions for ref in action.card_refs))
            self.selection_refs = refs
            body += bytes((int(prompt.cancelable), prompt.minimum, prompt.maximum)) + _u8(len(refs))
            for ref in refs:
                if kind == 20:
                    weight = facts.get("tribute_weights", {}).get(ref)
                    if type(weight) is not int or not 1 <= weight <= 255:
                        raise WindBotUnsupported("tribute selection requires exact offered release weights")
                    body += self._card(ref) + _u8(weight)
                else:
                    body += self._card(ref, tail=True)
            for action in actions:
                if action.kind == "pass":
                    self._response(_i32(-1), action)
                elif action.kind == "select":
                    key = ("cards", frozenset(refs.index(ref) for ref in action.card_refs))
                    self._response(key, action)
                else:
                    raise WindBotUnsupported("unsupported select-card action")
        elif kind in (18, 24):
            count = self.request.prompt.minimum
            if count is None:
                raise WindBotUnsupported("placement prompt requires its exact count")
            available = 0
            for action in actions:
                if action.kind == "pass":
                    self._response(b"\0\0\0", action)
                    continue
                detail = action.details
                places = (detail.destination,) if detail and detail.destination is not None else detail.destinations if detail else ()
                if not places or len(places) != max(1, count):
                    raise WindBotUnsupported("placement action lacks exact destination facts")
                positions = []
                for place in places:
                    relative = int(place.controller != self.observer)
                    bit = place.sequence + (0 if place.zone == "monster" else 8) + relative * 16
                    available |= 1 << bit
                    positions.append((bit, place))
                response = b"".join(bytes((p.controller, LOCATION[p.zone], p.sequence)) for _, p in sorted(positions))
                self._response(response, action)
            body += _u8(count) + _u32(0xffffffff ^ available)
        elif kind == 22:
            refs = actions[0].card_refs
            counter = actions[0].details.counter_type if actions[0].details else None
            total = self.request.prompt.minimum
            if counter is None or total is None:
                raise WindBotUnsupported("counter prompt requires its exact type/total")
            body += _u16(counter) + _u16(total) + _u8(len(refs))
            for ref in refs:
                cap = facts.get("counter_caps", {}).get(ref)
                if type(cap) is not int or not 1 <= cap <= 65535:
                    raise WindBotUnsupported("counter prompt requires exact offered capacities")
                body += self._card(ref) + _u16(cap)
            for action in actions:
                if action.card_refs != refs or action.details is None or action.details.counter_type != counter:
                    raise WindBotUnsupported("counter choices disagree on their offered candidates")
                self._response(b"".join(_u16(v) for v in action.details.quantities), action)
        elif kind == 23:
            spec = self.request.sum_selection
            if spec is None:
                raise WindBotUnsupported("sum prompt requires its actual numeric constraints")
            body = _u8(int(spec.mode != "equal")) + body + _u32(spec.target) + _u8(spec.minimum_optional) + _u8(spec.maximum_optional)
            self.sum_refs = (tuple(c.ref for c in spec.mandatory), tuple(c.ref for c in spec.optional))
            for group in (spec.mandatory, spec.optional):
                body += _u8(len(group))
                for candidate in group:
                    values = candidate.values
                    if len(values) not in (1, 2) or len(values) == 2 and (values[0] > 65535 or values[1] >= 32768):
                        raise WindBotUnsupported("sum contributions cannot be represented by this client")
                    packed = values[0] | (values[1] << 16) if len(values) == 2 else values[0] if values[0] < 65536 else values[0] | 0x80000000
                    body += self._card(candidate.ref) + _u32(packed)
            mandatory, optional = self.sum_refs
            for action in actions:
                if not set(mandatory) <= set(action.card_refs):
                    raise WindBotUnsupported("sum action drops mandatory offered cards")
                selected = frozenset(optional.index(ref) for ref in action.card_refs if ref not in mandatory)
                self._response(("sum", selected), action)
        elif kind == 25:
            refs = tuple(c.ref for c in self.request.search_choices)
            body += _u8(len(refs)) + b"".join(self._card(ref) for ref in refs)
            for action in actions:
                if action.kind == "pass":
                    self._response(b"\xff", action)
                elif len(action.card_refs) == len(refs) and set(action.card_refs) == set(refs):
                    self._response(bytes(action.card_refs.index(ref) for ref in refs), action)
                else:
                    raise WindBotUnsupported("sorting choices must exactly permute the offered cards")
        elif kind == 26:
            prompt = self.request.prompt
            body += bytes((int(prompt.finishable), int(prompt.cancelable), prompt.minimum, prompt.maximum))
            groups = [[a for a in actions if a.details and a.details.operation == operation] for operation in ("add", "remove")]
            index = 0
            for group in groups:
                body += _u8(len(group))
                for action in group:
                    if len(action.card_refs) != 1:
                        raise WindBotUnsupported("unselect action requires one offered card")
                    body += self._card(action.card_refs[0], tail=True)
                    self._response(bytes((1, index)), action)
                    index += 1
            for action in actions:
                if action.kind == "pass":
                    self._response(_i32(-1), action)
        elif kind in (132, 140, 141, 142):
            if kind in (140, 141):
                count = self.request.prompt.minimum
                mask = 0
                for action in actions:
                    mask |= action.value
                body += _u8(count) + _u32(mask)
            elif kind == 142:
                opcodes = facts.get("declaration_opcodes")
                if not isinstance(opcodes, (tuple, list)) or not opcodes:
                    raise WindBotUnsupported("card declaration requires its exact public predicate opcodes")
                body += _u8(len(opcodes)) + b"".join(_u32(v) for v in opcodes)
            for action in actions:
                self._response(_i32(action.value), action)
        elif kind == 16:
            activate = [a for a in actions if a.kind == "activate"]
            hints = facts.get("chain_hints")
            if not isinstance(hints, (list, tuple)) or len(hints) != 2:
                raise WindBotUnsupported("chain prompt requires both actual hints")
            body += _u8(len(activate)) + _u8(facts.get("chain_special_count")) + b"".join(_u32(v) for v in hints)
            for index, action in enumerate(activate):
                detail = facts.get("chain", {}).get(action.action_id)
                if not isinstance(detail, dict) or type(detail.get("forced")) is not bool or len(action.card_refs) != 1:
                    raise WindBotUnsupported("chain choice lacks actual forced/flag facts")
                fields(detail, {"flag", "forced"})
                body += _u8(detail["flag"]) + _u8(int(detail["forced"])) + self._card(action.card_refs[0], tail=True)
                body += _u32(action.details.description if action.details else action.value)
                self._response(_i32(index), action)
            for action in actions:
                if action.kind == "pass":
                    self._response(_i32(-1), action)
                elif action.kind != "activate":
                    raise WindBotUnsupported("unexpected chain action")
        else:
            raise WindBotUnsupported("LAN prompt requires an explicit codec: " + str(kind))
        if len(self.responses) != len(actions):
            raise WindBotUnsupported("not every current legal action has an exact LAN response")
        return packet(STOC_GAME, _u8(kind) + body)

    def translate(self, payload, *, request, state_version):
        if (self.used or self.clock() >= self.deadline or state_version != self.frame.state_version or
                not isinstance(request, DecisionRequest) or digest(request.to_dict()) != self.frame.request_sha256):
            raise WindBotTransportError("expired, consumed or changed LAN decision window")
        if not isinstance(payload, bytes) or len(payload) > 256:
            raise WindBotTransportError("bounded CTOS response bytes required")
        key = payload
        if self.selection_refs is not None and payload != _i32(-1):
            if not payload or len(payload) != payload[0] + 1 or len(set(payload[1:])) != payload[0]:
                raise WindBotTransportError("malformed or duplicate LAN selection indexes")
            if any(i >= len(self.selection_refs) for i in payload[1:]):
                raise WindBotTransportError("LAN selection index outside current candidates")
            key = ("cards", frozenset(payload[1:]))
        if self.sum_refs is not None:
            mandatory, optional = self.sum_refs
            if (not payload or payload[0] + 1 != len(payload) or payload[0] < len(mandatory)
                    or any(payload[1:1 + len(mandatory)])):
                raise WindBotTransportError("sum response lacks exact mandatory padding/count")
            selected = payload[1 + len(mandatory):]
            if len(set(selected)) != len(selected) or any(i >= len(optional) for i in selected):
                raise WindBotTransportError("sum response repeats or invents optional candidates")
            key = ("sum", frozenset(selected))
        action_id = self.responses.get(key)
        if action_id is None:
            raise WindBotTransportError("CTOS response does not match a current legal action")
        self.used = True
        return next(a for a in self.request.actions if a.action_id == action_id)


def _wire_slot(value):
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise ContractError("named event requires a four-byte recipient-filtered slot")
    player, location, sequence, position = value
    integer(player, "event controller", 0, 1)
    if location not in (0, 1, 2, 4, 8, 16, 32, 64, 132, 136, 192):
        raise WindBotUnsupported("unknown recipient-filtered event location")
    if location == 1 and sequence != 0:
        raise ContractError("original deck order cannot enter recipient-filtered events")
    return bytes((player, location)) + _u8(sequence) + _u8(position)


def _public_slot(slot):
    return (bool(slot[1] & 128) or slot[1] == 16 or slot[1] in (4, 8, 32, 64) and bool(slot[3] & 5)
            or slot[1] in (4, 8) and bool(slot[3] & 128))


QUERY_SCALARS = (("code", 1), ("position", 2), ("alias", 4), ("type", 8), ("level", 16),
    ("rank", 32), ("attribute", 64), ("race", 128), ("attack", 256), ("defense", 512),
    ("base_attack", 1024), ("base_defense", 2048))


def _zone_count(window, player, location):
    observation = window.request.observation
    if location == 1:
        return observation.deck_counts[player]
    if location == 2:
        return observation.hand_counts[player]
    if location in (4, 8):
        return 7 if location == 4 else 8
    zone = {16: "graveyard", 32: "banished", 64: "extra"}.get(location)
    if zone is None:
        raise WindBotUnsupported("unknown public count location")
    return sum(c.controller == player and c.zone == zone for c in observation.cards)


def _local_vector_bound(window, player, location):
    count = _zone_count(window, player, location)
    swap_vector = location in (1, 16, 64) and any(m.kind == 35 and m.fields.get("player") == player
                                                for m in window.frame.messages)
    # A grave/deck exchange conserves this public union, including grave Extra
    # cards returned to Extra. Its old deck may exceed the final deck count.
    swapped_count = sum(_zone_count(window, player, z) for z in (1, 16, 64)) if swap_vector else 0
    if location not in (4, 8):
        for message in window.frame.messages:
            d = message.fields
            if message.kind == 50:
                # MSG_MOVE.previous is a four-byte slot. MSG_POS_CHANGE (53)
                # uses the same field name for one position byte and does not
                # change any zone's card count. Decode only the move schema;
                # malformed move slots still fail the ordinary wire contract.
                previous = d.get("previous")
                _wire_slot(previous)
                if tuple(previous)[:2] == (player, location):
                    count += 1
                if swap_vector and previous[0] == player and previous[1] in (1, 16, 64):
                    swapped_count += 1
            elif message.kind == 90 and location == 1 and d.get("player") == player:
                count += len(d.get("card_ids", ()))
            if swap_vector and message.kind == 90 and d.get("player") == player:
                swapped_count += len(d.get("card_ids", ()))
    return min(max(count, swapped_count), 256)


def _redaction_record(card, player, location, window):
    """Erase an anonymous client's stale facts, without asserting zero stats."""
    scalar_names = {name for name, _ in QUERY_SCALARS} - {"position"}
    scalar_names |= {"status", "lscale", "rscale", "link", "link_marker"}
    fields(card, scalar_names | {"sequence", "equip", "targets", "overlay", "counters"})
    sequence = integer(card["sequence"], "anonymous redaction slot", 0, 255)
    if (any(type(card[key]) is not int or card[key] != 0 for key in scalar_names)
            or card["equip"] not in ((0, 0, 0, 0), [0, 0, 0, 0])
            or any(not isinstance(card[key], (list, tuple)) or card[key] for key in ("targets", "overlay", "counters"))):
        raise ContractError("anonymous redaction requires complete zero/empty unknown sentinels")
    # An erasure can precede a removal in this frame. Bound that old local
    # vector with public counts and public event arities, never native indices.
    if sequence >= _local_vector_bound(window, player, location):
        raise ContractError("anonymous redaction exceeds the publicly bounded local vector")
    flags = sum(flag for name, flag in QUERY_SCALARS if name != "position")
    flags |= 0x4000 | 0x8000 | 0x10000 | 0x20000 | 0x80000 | 0x200000 | 0x400000 | 0x800000
    # All included fields are four bytes; LINK has its extra marker word.
    body = b"\0" * (4 * (len(scalar_names) + 4))
    return _u32(8 + len(body)) + _u32(flags) + body


def _query_record(card, player, location, window, *, redact=False):
    if redact:
        return _redaction_record(card, player, location, window)
    allowed = {name for name, _ in QUERY_SCALARS} | {"sequence", "equip", "targets", "overlay", "counters",
        "owner", "status", "lscale", "rscale", "link", "link_marker"}
    fields(card, {"sequence"}, allowed - {"sequence"})
    sequence = integer(card["sequence"], "query sequence", 0, 255)
    matches = [s for s in window.slots.values() if (s.controller, s.location, s.sequence) == (player, location, sequence)]
    visible = window.cards[matches[0].ref] if len(matches) == 1 else None
    if len(matches) > 1:
        raise ContractError("query slot has ambiguous legal card associations")
    if len(card) > 1 and (visible is None or getattr(visible, "visibility", None) == "hidden"):
        # Public materials do not reveal a face-down host's identity or stats.
        # Admit only the complete ordered material list already present in the
        # fixed player's legal observation; a source query cannot add identities.
        material_slots = sorted((s for s in window.slots.values()
            if s.location == (location | 128) and s.controller == player and s.sequence == sequence),
            key=lambda s: s.subsequence)
        materials = [window.cards[s.ref] for s in material_slots]
        public_overlay = (visible is not None and location == 4 and set(card) == {"sequence", "overlay"}
            and visible.material_count == len(material_slots)
            and [s.subsequence for s in material_slots] == list(range(len(material_slots)))
            and all(c.visibility == "public" and c.zone == "overlay" and c.attached_to == visible.ref
                    for c in materials)
            and isinstance(card["overlay"], (tuple, list))
            and list(card["overlay"]) == [c.card_id for c in materials])
        if not public_overlay:
            raise ContractError("query facts cannot expose a missing or hidden card")
    flags, body = 0, b""
    for name, flag in QUERY_SCALARS:
        if name not in card:
            continue
        value = card[name]
        if name == "code" and value != visible.card_id:
            raise ContractError("query identity differs from the legal player card")
        if name in ("attack", "defense") and getattr(visible, name, None) is not None and value != getattr(visible, name):
            raise ContractError("query combat stat contradicts the legal player card")
        flags |= flag
        body += _wire_slot((player, location, sequence, value)) if name == "position" else _i32(value)
    if "equip" in card:
        flags |= 0x4000
        body += _wire_slot(card["equip"])
    if "targets" in card:
        flags |= 0x8000
        body += _u32(len(card["targets"])) + b"".join(_wire_slot(s) for s in card["targets"])
    if "overlay" in card:
        flags |= 0x10000
        body += _u32(len(card["overlay"])) + b"".join(_u32(c) for c in card["overlay"])
    if "counters" in card:
        flags |= 0x20000
        body += _u32(len(card["counters"]))
        for counter in card["counters"]:
            fields(counter, {"type", "count"})
            body += _u16(counter["type"]) + _u16(counter["count"])
    for name, flag in (("owner", 0x40000), ("status", 0x80000), ("lscale", 0x200000), ("rscale", 0x400000)):
        if name in card:
            if name == "owner" and card[name] != getattr(visible, "owner", None):
                raise ContractError("query owner contradicts the legal player card")
            flags |= flag
            body += _u32(card[name])
    if "link" in card or "link_marker" in card:
        if not {"link", "link_marker"} <= card.keys():
            raise ContractError("both link count and marker are required")
        flags |= 0x800000
        body += _u32(card["link"]) + _u32(card["link_marker"])
    return _u32(8 + len(body)) + _u32(flags) + body


def _public_confirmation(message, window):
    """Validate a past public 31 against this frame's fresh history interval."""
    d, facts = message.fields, window.frame.prompt_facts
    ref = text(d["public_ref"], "public confirmation history reference")
    interval = fields(facts.get("public_history_range"), {"start", "end"})
    history = window.request.observation.public_history
    start = integer(interval["start"], "fresh public history start", 0, len(history))
    end = integer(interval["end"], "fresh public history end", start, len(history))
    if end != len(history):
        raise ContractError("public confirmation history interval must end at this request")
    proofs = facts.get("public_confirmations")
    if not isinstance(proofs, dict) or ref not in proofs:
        raise ContractError("public confirmation lacks its current frame binding")
    proof = fields(proofs[ref], {"message_index"})
    index = integer(proof["message_index"], "bound public confirmation message", 0, len(window.frame.messages) - 1)
    bound = window.frame.messages[index]
    if bound.kind != 31 or bound.fields != d:
        raise ContractError("public confirmation does not match its exact frame message")
    matches = [event for event in history[start:end] if event.event_id == ref]
    if ref in window._public_confirmations_used or len(matches) != 1:
        raise ContractError("public confirmation is old, repeated or absent from this frame's history")
    event = matches[0]
    if (event.kind != "reveal" or event.details is None or event.details.message != 31
            or event.details.player != d["player"] or len(event.card_ids) != len(event.details.locations)):
        raise ContractError("public confirmation requires its exact broadcast history record")
    expected = Counter()
    for code, place in zip(event.card_ids, event.details.locations):
        if place.zone not in ("hand", "monster", "spell_trap", "graveyard", "banished", "extra"):
            raise WindBotUnsupported("public historical confirmation requires a supported non-deck object")
        expected[(code, place.controller, LOCATION[place.zone],
                  None if place.zone in ("hand", "extra") else place.sequence)] += 1
    actual = Counter()
    seen = set()
    for card in d["cards"]:
        fields(card, {"card_id", "controller", "location", "sequence"})
        player, zone, sequence = card["controller"], card["location"], card["sequence"]
        integer(card["card_id"], "historical public identity", 1, 2**32 - 1)
        integer(player, "historical local controller", 0, 1)
        integer(zone, "historical local zone", 0, 255)
        integer(sequence, "historical local sequence", 0, 255)
        if zone not in (2, 4, 8, 16, 32, 64):
            raise WindBotUnsupported("public historical confirmation requires a supported non-deck object")
        if sequence >= _local_vector_bound(window, player, zone) or (player, zone, sequence) in seen:
            raise ContractError("public confirmation exceeds its historical public local vector")
        seen.add((player, zone, sequence))
        actual[(card["card_id"], player, zone, None if zone in (2, 64) else sequence)] += 1
    if actual != expected:
        raise ContractError("public confirmation differs from its exact broadcast identity/location multiset")
    window._public_confirmations_used.add(ref)


def game_message(message, window):
    """Encode an explicit recipient-filtered host event, never an engine buffer."""
    if not isinstance(message, WindBotMessage):
        raise ContractError("typed recipient-filtered message required")
    k, d = message.kind, message.fields
    prefix = b""
    if k == 4:
        fields(d, {"player_type", "duel_rule", "life_points", "deck_counts", "extra_counts"})
        if d["player_type"] != window.observer:
            raise ContractError("start packet changes the fixed observer")
        integer(d["duel_rule"], "start rule", 1, 5)
        body = _u8(d["player_type"]) + _u8(d["duel_rule"])
        for pair in (d["life_points"], d["deck_counts"], d["extra_counts"]):
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise ContractError("start requires explicit paired public counts")
        body += b"".join(_u32(v) for v in d["life_points"])
        for p in (0, 1):
            integer(d["deck_counts"][p], "initial main count", 40, 60)
            integer(d["extra_counts"][p], "initial extra count", 0, 15)
        body += b"".join(_u16(d["deck_counts"][p]) + _u16(d["extra_counts"][p]) for p in (0, 1))
    elif k in (6, 7):
        fields(d, {"player", "location", "cards"}, {"sequence", "redact"})
        integer(d["player"], "query player", 0, 1)
        if d["location"] not in (1, 2, 4, 8, 16, 32, 64):
            raise WindBotUnsupported("unsupported query location")
        body = _u8(d["player"]) + _u8(d["location"])
        cards = d["cards"]
        if not isinstance(cards, (list, tuple)) or len(cards) > 128:
            raise ContractError("bounded named query records required")
        if k == 7:
            if len(cards) != 1 or cards[0]["sequence"] != d.get("sequence"):
                raise ContractError("update-card requires its single exact sequence")
            body += _u8(d["sequence"])
        elif "sequence" in d or [c["sequence"] for c in cards] != list(range(len(cards))):
            raise ContractError("update-data requires every slot in sequence order")
        if k == 6 and d["location"] in (4, 8) and len(cards) != (7 if d["location"] == 4 else 8):
            raise ContractError("field update-data requires all fixed slots, including empty records")
        redact = d.get("redact", False)
        if type(redact) is not bool or redact and k != 7:
            raise ContractError("anonymous redaction requires a single exact update-card")
        body += b"".join(_query_record(c, d["player"], d["location"], window, redact=redact) for c in cards)
    elif k == 2:
        fields(d, {"hint", "player", "value"})
        player = integer(d["player"], "hint source player", 0, 1)
        hint = integer(d["hint"], "routed hint type", 1, 11)
        if not (hint in (10, 11) or hint in (1, 2, 3, 5) and player == window.observer
                or hint in (4, 6, 7, 8, 9) and 1 - player == window.observer):
            raise ContractError("private hint does not belong to the fixed LAN recipient")
        body = _u8(d["hint"]) + _u8(d["player"]) + _u32(d["value"])
    elif k == 5:
        fields(d, {"winner", "reason"})
        integer(d["winner"], "public winner", 0, 2)
        body = _u8(d["winner"]) + _u8(d["reason"])
    elif k in (30, 42):
        fields(d, {"player", "card_ids"})
        integer(d["player"], "public confirmation player", 0, 1)
        codes = d["card_ids"]
        if (not isinstance(codes, (tuple, list)) or len(codes) > 128 or
                any(type(c) is not int or not 1 <= c <= 2**32 - 1 for c in codes)):
            raise ContractError("bounded public confirmation identities required")
        if not any(e.details is not None and e.details.message == k and e.details.player == d["player"]
                   and Counter(e.card_ids) == Counter(codes) for e in window.request.observation.public_history):
            raise ContractError("public confirmation lacks its legal order-free history evidence")
        # Fixed Ice/Pure intentionally have no handlers for these messages.
        # Preserve only the broadcast identity multiset, never deck positions.
        location = 1 if k == 30 else 64
        body = _u8(d["player"]) + _u8(len(codes))
        body += b"".join(_u32(c) + bytes((d["player"], location, 0)) for c in sorted(codes))
    elif k == 31:
        fields(d, {"player", "skip_panel", "cards"}, {"knowledge_ref", "public_ref"})
        integer(d["player"], "confirm player", 0, 1)
        skip = d["skip_panel"]
        if type(skip) is bool:
            skip = int(skip)
        integer(skip, "confirm skip panel", 0, 1)
        if not isinstance(d["cards"], (tuple, list)) or len(d["cards"]) > 128:
            raise ContractError("bounded public confirm-card facts required")
        body = _u8(d["player"]) + _u8(skip) + _u8(len(d["cards"]))
        knowledge_ref = d.get("knowledge_ref")
        public_ref = d.get("public_ref")
        if public_ref is not None:
            if knowledge_ref is not None:
                raise ContractError("public and private confirmation proofs cannot be mixed")
            _public_confirmation(message, window)
        if knowledge_ref is not None:
            text(knowledge_ref, "private confirmation knowledge reference")
            for card in d["cards"]:
                fields(card, {"card_id", "controller", "location", "sequence"})
            reveals = [r for r in window.request.private_reveals if r.ref == knowledge_ref]
            if d["player"] != window.observer or len(reveals) != 1:
                raise ContractError("private confirmation is not bound to this observer's legal revelation")
            expected = Counter((c.controller, LOCATION[c.zone], c.card_id) for c in reveals[0].cards)
            actual = Counter((c.get("controller"), c.get("location"), c.get("card_id")) for c in d["cards"])
            if actual != expected:
                raise ContractError("private confirmation differs from its exact legal identity multiset")
            if list(d["cards"]) != sorted(d["cards"], key=lambda c: (c["controller"], c["card_id"])):
                raise ContractError("private confirmation must use canonical order-free local objects")
        seen, local_counts = set(), Counter()
        for card in d["cards"]:
            fields(card, {"card_id", "controller", "location", "sequence"})
            address = (card["controller"], card["location"], card["sequence"])
            if public_ref is not None:
                body += _u32(card["card_id"]) + b"".join(_u8(v) for v in address)
                continue
            if knowledge_ref is not None:
                integer(card["controller"], "private local controller", 0, 1)
                sequence = integer(card["sequence"], "private local deck slot", 0, 255)
                if (card["location"] != 1 or sequence >= _local_vector_bound(window, card["controller"], 1)
                        or sequence != local_counts[card["controller"]]
                        or address in seen):
                    raise ContractError("private confirmation exceeds its public local deck vector")
                local_counts[card["controller"]] += 1
                seen.add(address)
                body += _u32(card["card_id"]) + b"".join(_u8(v) for v in address)
                continue
            if card["location"] not in (2, 4, 8, 16, 32, 64):
                raise WindBotUnsupported("confirm-card deck order and unknown locations are unsupported")
            _wire_slot((*address, 0))
            matches = [window.cards[s.ref] for s in window.slots.values()
                if (s.controller, s.location, s.sequence) == address]
            if (address in seen or len(matches) != 1 or getattr(matches[0], "visibility", "hidden") == "hidden"
                    or card["card_id"] != matches[0].card_id):
                raise ContractError("confirm-card identity is not bound to its current legal visible slot")
            seen.add(address)
            body += _u32(card["card_id"]) + b"".join(_u8(v) for v in address)
    elif k == 35:
        fields(d, {"player", "old_grave_types"})
        player, rows = integer(d["player"], "swap player", 0, 1), d["old_grave_types"]
        if not isinstance(rows, (tuple, list)) or len(rows) > 128:
            raise ContractError("swap requires the complete old public grave classification")
        public_grave_ids = {c.card_id for c in window.request.observation.cards
            if c.zone == "graveyard" and c.visibility == "public"}
        public_grave_ids.update(code for event in window.request.observation.public_history
            if event.details is not None and any(place.zone == "graveyard" for place in event.details.locations)
            for code in event.card_ids)
        for sequence, row in enumerate(rows):
            fields(row, {"sequence", "card_id", "type"})
            if (row["sequence"] != sequence or sequence >= _local_vector_bound(window, player, 16)
                    or row["card_id"] not in public_grave_ids):
                raise ContractError("swap classification differs from its ordered public grave evidence")
            integer(row["type"], "catalog base type", 1, 2**32 - 1)
            # The trusted projection binds this TYPE to the locked public CDB's
            # immutable data.type, which the core uses to return Extra cards.
            # SetId alone does not initialize ClientCard.Type; refresh before
            # the pinned client's IsExtraCard bookkeeping, never after it.
            record = _u32(16) + _u32(1 | 8) + _u32(row["card_id"]) + _u32(row["type"])
            prefix += packet(STOC_GAME, bytes((7, player, 16, sequence)) + record)
        body = _u8(player)
    elif k in (32, 40):
        fields(d, {"player"})
        integer(d["player"], "public event player", 0, 1)
        body = _u8(d["player"])
    elif k == 36:
        fields(d, {"location", "slots"})
        slots = d["slots"]
        if (d["location"] not in (4, 8) or not isinstance(slots, (tuple, list))
                or not 2 <= len(slots) <= 5):
            raise ContractError("set shuffle requires two to five exact main-field slots")
        for slot in slots:
            _wire_slot(slot)
            if slot[1] != d["location"] or slot[2] > 4 or slot[3] & 0x7f not in (2, 8):
                raise ContractError("set shuffle has a different zone or a non-set/main-zone slot")
        if len({s[0] for s in slots}) != 1 or len({tuple(s[:3]) for s in slots}) != len(slots):
            raise ContractError("set shuffle cannot mix players or repeat public slots")
        # Destination zero is the pinned client's explicit unknown mapping.
        # Never forward a raw permutation or preserve its randomized list order.
        body = _u8(d["location"]) + _u8(len(slots))
        body += b"".join(_wire_slot(s) for s in sorted(slots)) + b"\0" * (4 * len(slots))
    elif k == 37:
        fields(d, set())
        body = b""
    elif k == 38:
        fields(d, {"player", "card_id", "faceup"})
        integer(d["player"], "public deck-top player", 0, 1)
        integer(d["card_id"], "public deck-top identity", 1, 2**31 - 1)
        if type(d["faceup"]) is not bool or not any(e.details is not None and e.details.message == 38
                and e.details.player == d["player"] and d["card_id"] in e.card_ids
                for e in window.request.observation.public_history):
            raise ContractError("deck-top identity lacks its legal public history")
        body = _u8(d["player"]) + b"\0" + _u32(d["card_id"] | (0x80000000 if d["faceup"] else 0))
    elif k == 41:
        fields(d, {"phase"})
        if d["phase"] not in (1, 2, 4, 8, 16, 32, 64, 128, 256, 512):
            raise WindBotUnsupported("exact public phase mask is required")
        body = _u16(d["phase"])
    elif k in (33, 39, 90):
        fields(d, {"player", "card_ids"})
        integer(d["player"], "draw/shuffle player", 0, 1)
        if not isinstance(d["card_ids"], (tuple, list)) or len(d["card_ids"]) > 128:
            raise ContractError("bounded masked card list required")
        for code in d["card_ids"]:
            _u32(code)
        if d["player"] != window.observer:
            public_cards = {c.card_id for c in window.request.observation.cards if c.visibility == "public"}
            public_cards.update(code for e in window.request.observation.public_history for code in e.card_ids)
            public_hand = {c.card_id for c in window.request.observation.cards
                           if c.visibility == "public" and c.controller == d["player"] and c.zone == "hand"}
            if k == 90:
                exposes_private = any(code and (not code & 0x80000000 or (code & 0x7fffffff) not in public_cards)
                                      for code in d["card_ids"])
            elif k == 33:
                exposes_private = any(code and code not in public_hand for code in d["card_ids"])
            else:
                exposes_private = any(d["card_ids"])
            if exposes_private:
                raise ContractError("opponent private draw/shuffle identity cannot enter LAN")
        body = _u8(d["player"]) + _u8(len(d["card_ids"])) + b"".join(_u32(c) for c in d["card_ids"])
    elif k == 50:
        fields(d, {"card_id", "previous", "current", "reason"})
        _u32(d["card_id"])
        _wire_slot(d["previous"])
        _wire_slot(d["current"])
        if d["card_id"] and not any(s[0] == window.observer or _public_slot(s)
                                    for s in (d["previous"], d["current"])):
            raise ContractError("private opponent move identity cannot enter LAN")
        body = _u32(d["card_id"]) + _wire_slot(d["previous"]) + _wire_slot(d["current"]) + _u32(d["reason"])
    elif k == 53:
        fields(d, {"card_id", "player", "location", "sequence", "previous", "current"})
        _u32(d["card_id"])
        previous = (d["player"], d["location"], d["sequence"], d["previous"])
        current = (d["player"], d["location"], d["sequence"], d["current"])
        _wire_slot(previous)
        _wire_slot(current)
        if d["card_id"] and d["player"] != window.observer and not (_public_slot(previous) or _public_slot(current)):
            raise ContractError("private opponent position-change identity cannot enter LAN")
        body = (_u32(d["card_id"]) + _wire_slot((d["player"], d["location"], d["sequence"], d["previous"]))
                + _u8(d["current"]))
    elif k == 54:
        fields(d, {"slot"})
        body = _u32(0) + _wire_slot(d["slot"])
    elif k == 55:
        fields(d, {"first_card_id", "first", "second_card_id", "second"})
        body = b""
        for code, slot in ((d["first_card_id"], d["first"]), (d["second_card_id"], d["second"])):
            if code and slot[0] != window.observer and not _public_slot(slot):
                raise ContractError("private opponent swap identity cannot enter LAN")
            body += _u32(code) + _wire_slot(slot)
    elif k == 56:
        fields(d, {"mask"})
        body = _u32(d["mask"])
    elif k in (60, 62, 64):
        fields(d, {"card_id", "slot"})
        _wire_slot(d["slot"])
        if d["card_id"] and d["slot"][0] != window.observer and not _public_slot(d["slot"]):
            raise ContractError("private opponent summon identity cannot enter LAN")
        body = _u32(d["card_id"]) + _wire_slot(d["slot"])
    elif k in (61, 63, 65, 74, 112, 113, 114):
        fields(d, set())
        body = b""
    elif k == 70:
        fields(d, {"card_id", "card_type", "slot", "chain_location", "description", "link"})
        _wire_slot(d["slot"])
        player, location, sequence, _ = d["slot"]
        if location & 128 or location == 0 or sequence > 127:
            raise WindBotUnsupported("chain handler requires a persistent supported LAN-local card object")
        integer(d["card_type"], "public chain catalog base type", 1, 2**32 - 1)
        if not any(e.details is not None and e.details.message == 70 and d["card_id"] in e.card_ids
                   for e in window.request.observation.public_history):
            raise ContractError("chain classification lacks its legal public activation identity")
        # OnChaining invokes real Executor callbacks immediately. A newly
        # published private-area identity has no initialized Type from SetId.
        # Existing field/grave/banished objects may carry a dynamic Type, which
        # a printed catalog classification must never overwrite.
        if location in (1, 2, 64):
            record = _u32(16) + _u32(1 | 8) + _u32(d["card_id"]) + _u32(d["card_type"])
            prefix = packet(STOC_GAME, bytes((7, player, location, sequence)) + record)
        chain = d["chain_location"]
        if not isinstance(chain, (list, tuple)) or len(chain) != 3:
            raise ContractError("exact public chain trigger location required")
        body = _u32(d["card_id"]) + _wire_slot(d["slot"]) + b"".join(_u8(v) for v in chain) + _u32(d["description"]) + _u8(d["link"])
    elif k in (71, 72, 73, 75, 76):
        fields(d, {"link"})
        body = _u8(d["link"])
    elif k in (81, 83):
        fields(d, {"slots", "player"} if k == 81 else {"slots"})
        if not isinstance(d["slots"], (tuple, list)) or len(d["slots"]) > 128:
            raise ContractError("bounded recipient-filtered selected slots required")
        body = _u8(d["player"]) if k == 81 else b""
        if k == 81:
            integer(d["player"], "public random player", 0, 1)
        body += _u8(len(d["slots"])) + b"".join(_wire_slot(s) for s in d["slots"])
    elif k in (91, 92, 94, 100):
        fields(d, {"player", "amount"})
        body = _u8(d["player"]) + _u32(d["amount"])
    elif k in (93, 96, 97, 110):
        fields(d, {"first", "second"})
        body = _wire_slot(d["first"]) + _wire_slot(d["second"])
    elif k == 111:
        fields(d, {"attacker", "attacker_attack", "attacker_defense", "attacker_destroyed",
                   "defender", "defender_attack", "defender_defense", "defender_destroyed"})
        body = (_wire_slot(d["attacker"]) + _i32(d["attacker_attack"]) + _i32(d["attacker_defense"]) + _u8(d["attacker_destroyed"])
                + _wire_slot(d["defender"]) + _i32(d["defender_attack"]) + _i32(d["defender_defense"]) + _u8(d["defender_destroyed"]))
    elif k in (101, 102):
        fields(d, {"counter_type", "player", "location", "sequence", "count"})
        body = _u16(d["counter_type"]) + bytes((d["player"], d["location"], d["sequence"])) + _u16(d["count"])
    elif k == 95:
        # Legacy LAN client support only: this locked core does not emit 95,
        # and the current Native public-history consumer still rejects it.
        fields(d, {"slot"})
        body = _wire_slot(d["slot"])
    elif k == 120:
        fields(d, {"card_id", "slot"})
        if d["slot"][0] != window.observer:
            raise ContractError("another player's private missed effect cannot enter LAN")
        body = _u32(d["card_id"]) + _wire_slot(d["slot"])
    elif k in (130, 131):
        fields(d, {"player", "values"})
        integer(d["player"], "public random player", 0, 1)
        if not isinstance(d["values"], (tuple, list)) or len(d["values"]) > 128:
            raise ContractError("bounded public random outcomes required")
        for value in d["values"]:
            integer(value, "public random outcome", 0 if k == 130 else 1, 1 if k == 130 else 6)
        body = _u8(d["player"]) + _u8(len(d["values"])) + bytes(d["values"])
    elif k == 133:
        fields(d, {"values"})
        if not isinstance(d["values"], (tuple, list)) or len(d["values"]) != 2:
            raise ContractError("exactly two public RPS outcomes required")
        for value in d["values"]:
            integer(value, "public RPS outcome", 1, 3)
        body = _u8(d["values"][0] | (d["values"][1] << 2))
    elif k == 160:
        fields(d, {"slot", "hint", "value"})
        body = _wire_slot(d["slot"]) + _u8(d["hint"]) + _u32(d["value"])
    elif k == 165:
        fields(d, {"player", "hint", "value"})
        integer(d["player"], "public player-hint player", 0, 1)
        body = _u8(d["player"]) + _u8(d["hint"]) + _u32(d["value"])
    elif k == 170:
        fields(d, {"card_id"})
        body = _u32(d["card_id"])
    else:
        raise WindBotUnsupported("recipient-filtered event needs an exact codec: " + str(k))
    return prefix + packet(STOC_GAME, _u8(k) + body)


def _unicode_fixed(raw):
    if len(raw) != 40:
        raise WindBotTransportError("fixed UTF-16 room field has the wrong size")
    try:
        value = raw.decode("utf-16-le")
    except UnicodeError as error:
        raise WindBotTransportError("invalid UTF-16 room field") from error
    content, _, padding = value.partition("\0")
    if padding.strip("\0"):
        raise WindBotTransportError("nonzero room field padding")
    return content


class WindBotRoom:
    """One authenticated loopback connection; any timeout permanently closes it."""
    def __init__(self, deck, *, observer, duel_rule, protocol_version=0x1362, timeout=10., wall_seconds=120., host="127.0.0.1", clock=time.monotonic):
        if not isinstance(deck, DeckParts) or host != "127.0.0.1":
            raise ContractError("fixed own deck and IPv4 loopback-only room required")
        integer(observer, "fixed room observer", 0, 1)
        integer(duel_rule, "explicit room rule", 1, 5)
        integer(protocol_version, "fixed client protocol version", 1, 65535)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ContractError("bounded room timeout required")
        if type(wall_seconds) not in (int, float) or not math.isfinite(wall_seconds) or not 0 < wall_seconds <= 600:
            raise ContractError("bounded complete room lifetime required")
        self.deck, self.observer, self.duel_rule = deck, observer, duel_rule
        self.protocol_version, self.timeout, self.clock = protocol_version, timeout, clock
        self.room_deadline = clock() + wall_seconds
        self.token, self.connection, self.started, self.closed = secrets.token_hex(8), None, False, False
        self.process_outcome = None  # Set only by the owned session's exit/reap check.
        self._exchange = threading.Lock()
        self.seen_versions = set()
        self._history_count, self._history_prefix_sha256 = 0, digest([])
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind((host, 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.closed = True
        for sock in (self.connection, self.listener):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def _receive(self, deadline):
        def exact(size):
            data = b""
            while len(data) < size:
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise WindBotTransportError("loopback WindBot deadline expired")
                self.connection.settimeout(remaining)
                chunk = self.connection.recv(size - len(data))
                if not chunk:
                    raise WindBotTransportError("loopback WindBot disconnected")
                data += chunk
            return data
        size = struct.unpack("<H", exact(2))[0]
        if not 1 <= size <= 65535:
            raise WindBotTransportError("invalid LAN frame length")
        body = exact(size)
        return body[0], body[1:]

    def _send(self, data, deadline):
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise WindBotTransportError("loopback WindBot deadline expired")
        self.connection.settimeout(remaining)
        self.connection.sendall(data)

    def accept(self):
        if self.closed or self.connection is not None:
            raise WindBotTransportError("room cannot accept or replace a connection")
        deadline = min(self.room_deadline, self.clock() + self.timeout)
        try:
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise WindBotTransportError("loopback WindBot deadline expired")
            self.listener.settimeout(remaining)
            self.connection, address = self.listener.accept()
            self.listener.close()
            if address[0] != "127.0.0.1":
                raise WindBotTransportError("non-loopback client refused")
            info, joined, deck_checked, ready = False, False, False, False
            for _ in range(16):
                kind, body = self._receive(deadline)
                if kind == 23 and not joined:  # ExternalAddress is harmless metadata, never routing.
                    if len(body) > 520 or len(body) < 5 or body[:4] != b"\0" * 4:
                        raise WindBotTransportError("invalid external-address metadata")
                elif kind == CTOS_INFO and not info:
                    if not _unicode_fixed(body):
                        raise WindBotTransportError("empty client name")
                    info = True
                elif kind == CTOS_JOIN and info and not joined:
                    if (len(body) != 48 or struct.unpack_from("<H", body)[0] != self.protocol_version or
                            _unicode_fixed(body[8:]) != self.token):
                        raise WindBotTransportError("wrong room token or client protocol")
                    self._send(packet(STOC_JOIN, _u32(0) + bytes((0, 0, self.duel_rule))), deadline)
                    self._send(packet(STOC_TYPE, _u8(self.observer)), deadline)
                    joined = True
                elif kind == CTOS_DECK and joined and not deck_checked:
                    if len(body) < 8:
                        raise WindBotTransportError("truncated uploaded deck")
                    total, side = struct.unpack_from("<II", body)
                    if total > 75 or side > 15 or len(body) != 8 + 4 * (total + side):
                        raise WindBotTransportError("uploaded deck counts differ")
                    codes = struct.unpack_from("<" + "I" * (total + side), body, 8)
                    if Counter(codes[:total]) != Counter((*self.deck.main, *self.deck.extra)) or Counter(codes[total:]) != Counter(self.deck.side):
                        raise WindBotTransportError("WindBot uploaded a different fixed deck")
                    deck_checked = True
                elif kind == 34 and joined and not ready and not body:
                    ready = True
                else:
                    raise WindBotTransportError("unexpected or duplicate lobby packet")
                if deck_checked and ready:
                    return {"status": "loopback_client_connected", "deck_sha256": digest(self.deck.to_dict()),
                            "executor_identity_verified": False, "native_executed": False}
            raise WindBotTransportError("bounded lobby packet budget exhausted")
        except (OSError, ContractError, ValueError) as error:
            self.close()
            if isinstance(error, ContractError):
                raise
            raise WindBotTransportError("loopback lobby transport failed") from error

    def choose(self, request, frame):
        if self.closed or self.connection is None:
            raise WindBotTransportError("explicit accepted loopback connection required")
        if not self._exchange.acquire(blocking=False):
            raise WindBotTransportError("only one active LAN decision exchange is allowed")
        try:
            if not isinstance(frame, WindBotTransportFrame):
                raise ContractError("typed recipient-filtered frame required")
            if frame.state_version in self.seen_versions:
                raise WindBotTransportError("LAN state version cannot be replayed")
            if select.select([self.connection], [], [], 0)[0]:
                raise WindBotTransportError("unsolicited or stale data before a new LAN window")
            deadline = min(self.room_deadline, self.clock() + self.timeout)
            window = WindBotWindow(request, frame, observer=self.observer, deadline=deadline, clock=self.clock)
            snapshot = window.frame
            history = window.request.to_dict()["observation"]["public_history"]
            if (len(history) < self._history_count or
                    digest(history[:self._history_count]) != self._history_prefix_sha256):
                raise ContractError("LAN public history prefix changed or was truncated")
            interval = snapshot.prompt_facts.get("public_history_range")
            if interval is not None:
                fields(interval, {"start", "end"})
                integer(interval["start"], "connection public history start", 0, len(history))
                integer(interval["end"], "connection public history end", 0, len(history))
                if interval["start"] != self._history_count or interval["end"] != len(history):
                    raise ContractError("LAN public confirmation history does not belong to the new frame")
            starts = sum(m.kind == 4 for m in snapshot.messages)
            if starts != int(not self.started) or not self.started and (not snapshot.messages or snapshot.messages[0].kind != 4):
                raise WindBotUnsupported("continuous LAN game requires exactly one initial Start")
            if not self.started:
                initial = snapshot.messages[0].fields
                if (initial.get("duel_rule") != self.duel_rule or initial["deck_counts"][self.observer] != len(self.deck.main)
                        or initial["extra_counts"][self.observer] != len(self.deck.extra)):
                    raise ContractError("Start differs from the fixed room rule/own deck counts")
            updates = [game_message(m, window) for m in snapshot.messages]
            if sum(map(len, updates)) + len(window.message) > 2 * 1024 * 1024:
                raise WindBotUnsupported("recipient-filtered frame exceeds the bounded send size")
            self.seen_versions.add(frame.state_version)
            for data in (*updates, window.message):
                self._send(data, deadline)
            self.started = True
            kind, body = self._receive(deadline)
            if kind != CTOS_RESPONSE:
                raise WindBotTransportError("only one current CTOS response is accepted")
            action = window.translate(body, request=request, state_version=frame.state_version)
            self._history_count, self._history_prefix_sha256 = len(history), digest(history)
            return action
        except (OSError, ContractError, ValueError, TypeError, KeyError, IndexError, struct.error) as error:
            self.close()  # Never let a late reply enter a subsequent decision.
            if isinstance(error, ContractError):
                raise
            raise WindBotTransportError("loopback decision transport failed") from error
        finally:
            self._exchange.release()


class _OwnedWindBotProcess:
    """Close and reap this exact Popen child, including at the room deadline."""
    def __init__(self, process, room):
        self.process, self.room = process, room
        self.lock = threading.Lock()
        self.outcome = None

    def shutdown(self, reason):
        with self.lock:
            if self.outcome is not None:
                return deepcopy(self.outcome)
            self.room.close()
            stage, returncode = "room_closed", None
            try:
                try:
                    returncode = self.process.wait(timeout=1.)
                except subprocess.TimeoutExpired:
                    stage = "terminated"
                    self.process.terminate()
                    try:
                        returncode = self.process.wait(timeout=1.)
                    except subprocess.TimeoutExpired:
                        stage = "killed"
                        self.process.kill()
                        returncode = self.process.wait(timeout=1.)
                if type(returncode) is not int:
                    raise WindBotTransportError("owned WindBot did not provide a reaped exit status")
                self.outcome = {"reason": reason, "shutdown": stage, "returncode": returncode,
                    "reaped": True, "uncertain": False}
            except (OSError, subprocess.TimeoutExpired, ContractError) as error:
                self.outcome = {"reason": reason, "shutdown": "uncertain", "returncode": None,
                    "reaped": False, "uncertain": True, "error_type": type(error).__name__}
            self.room.process_outcome = deepcopy(self.outcome)
            return deepcopy(self.outcome)


def windbot_command(mono, executable, database, deck_file, executor, *, room, allowed_executors, dialog="default"):
    """Exact argv for a complete source build; no shell, HTTP or random deck fallback."""
    if not isinstance(room, WindBotRoom) or room.closed or executor not in allowed_executors:
        raise ContractError("open local room and exact pinned Executor inventory required")
    if not isinstance(executor, str) or not executor or len(executor) > 128 or any(ord(c) < 32 for c in executor):
        raise ContractError("exact source-declared executor name required")
    if not isinstance(dialog, str) or not dialog or len(dialog) > 80 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in dialog):
        raise ContractError("fixed dialog identifier required")
    paths = [str(Path(p).resolve(strict=True)) for p in (mono, executable, database, deck_file)]
    if any(not Path(p).is_file() for p in paths):
        raise ContractError("explicit tool, complete build, catalog and YDK files required")
    return [paths[0], paths[1], "ServerMode=False", "Host=127.0.0.1", "Port=" + str(room.port),
            "HostInfo=" + room.token, "DbPath=" + paths[2], "DeckFile=" + paths[3], "Deck=" + executor,
            "Dialog=" + dialog, "Chat=False", "Debug=False", "Version=" + str(room.protocol_version), "Name=Kito-WindBot"]


@contextmanager
def windbot_session(deck, *, observer, duel_rule, mono, executable, database, deck_file, executor,
                    allowed_executors, working_directory, expected_sha256, timeout=10., wall_seconds=120.,
                    protocol_version=0x1362, dialog="default", mono_environment=None):
    """Run a host-approved complete build with an isolated, bounded local room.

    Build/license/period qualification belongs to the source registry. This
    function rechecks the actual copied runtime files; it never downloads,
    compiles, selects a random executor or uses a shell. Shutdown signals target
    only the exact child it owns; the native engine and other processes are untouched.
    """
    directory = Path(working_directory).resolve(strict=True)
    if not directory.is_dir():
        raise ContractError("explicit isolated WindBot runtime directory required")
    paths = {"mono": Path(mono).resolve(strict=True), "executable": Path(executable).resolve(strict=True),
             "database": Path(database).resolve(strict=True), "deck_file": Path(deck_file).resolve(strict=True)}
    fields(expected_sha256, set(paths))
    from .coord_contracts import sha256
    for name, path in paths.items():
        sha256(expected_sha256[name])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256[name]:
            raise ContractError("approved WindBot runtime file checksum differs: " + name)
        if name != "mono" and not path.is_relative_to(directory):
            raise ContractError("WindBot executable/catalog/deck must stay in its isolated runtime directory")
    environment = {"PATH": str(paths["mono"].parent) + ":/usr/bin:/bin", "LANG": "C.UTF-8"}
    supplied = mono_environment or {}
    fields(supplied, set(), {"MONO_CFG_DIR", "MONO_PATH", "LD_LIBRARY_PATH"})
    for key, value in supplied.items():
        text(value, "explicit Mono environment path")
        environment[key] = value
    owner, watchdog = None, None
    with WindBotRoom(deck, observer=observer, duel_rule=duel_rule, timeout=timeout,
                     wall_seconds=wall_seconds, protocol_version=protocol_version) as room:
        argv = windbot_command(*(paths[k] for k in ("mono", "executable", "database", "deck_file")), executor,
                               room=room, allowed_executors=allowed_executors, dialog=dialog)
        # A unique file contains only this client process's own output. Host
        # training logs, policy seeds and raw engine audit are never supplied.
        log_path = directory / ("windbot-" + secrets.token_hex(8) + ".log")
        with log_path.open("xb") as log:
            try:
                process = subprocess.Popen(argv, cwd=directory, env=environment, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, shell=False, close_fds=True)
                owner = _OwnedWindBotProcess(process, room)
                # A caller stalled between prompts must not extend the child's
                # lifetime. Cleanup is serialized with the context's finally.
                watchdog = threading.Timer(max(0., room.room_deadline - room.clock()),
                    lambda: owner.shutdown("room_deadline_expired"))
                watchdog.daemon = True
                watchdog.start()
                room.accept()
                yield room
            finally:
                room.close()
                if watchdog is not None:
                    watchdog.cancel()
                if owner is not None and owner.shutdown("session_closed")["uncertain"]:
                    raise WindBotTransportError("owned WindBot child exit/reap is uncertain; runtime stopped")
