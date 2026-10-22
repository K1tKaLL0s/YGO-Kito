"""Bounded codecs for the pinned core's playerop.cpp; no card rules or hidden queries.

Unit protocol fixtures prove decoding/rejection, never successful engine execution.
Responses and original deck indices stay inside the adapter.
"""

from dataclasses import dataclass
from itertools import combinations
from math import comb
import struct

from .contracts import ActionDetails, Placement, PromptInfo, SearchChoice


class NativeError(RuntimeError):
    pass


class Reader:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def take(self, count):
        end = self.offset + count
        if count < 0 or end > len(self.data):
            raise NativeError("truncated native message")
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return struct.unpack("<H", self.take(2))[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]


@dataclass(frozen=True)
class NativeOption:
    kind: str
    refs: tuple
    value: int | None
    response: int | bytes
    details: ActionDetails | None = None


@dataclass(frozen=True)
class DecodedPrompt:
    player: int
    info: PromptInfo
    options: tuple[NativeOption, ...]
    search_choices: tuple[SearchChoice, ...] = ()


def visible_ref(player, controller, location, sequence):
    if controller not in (0, 1) or (location == 2 and controller != player):
        raise NativeError("selection outside player-visible hand")
    zone = {2: "hand", 4: "monster", 8: "spell_trap", 16: "graveyard"}.get(location)
    if zone is None or (location == 4 and sequence > 6) or (location == 8 and sequence > 7):
        raise NativeError("selection outside supported visible zones")
    return f"p{controller}.{zone}.{sequence}"


def decode_deck_choices(player, minimum, maximum, candidates):
    """Discard native order/deck positions while keeping response indices private."""
    if minimum != 1 or maximum != 1 or not 0 < len(candidates) <= 128:
        raise NativeError("only bounded single-card deck choices are supported")
    if any(owner != player or zone != 1 or not code for code, owner, zone, _ in candidates):
        raise NativeError("blind/opponent/mixed deck selection is unsupported")
    choices, options = [], []
    for ordinal, (native_index, (code, owner, _zone, _sequence)) in enumerate(sorted(enumerate(candidates), key=lambda item: item[1][0])):
        ref = f"search-choice-{ordinal}"
        choices.append(SearchChoice(ref, code, owner))
        options.append(("select", (ref,), 1, bytes((1, native_index))))
    return tuple(choices), options


def decode_prompt(kind, reader):
    """All choices are bounded, native-offered operations; unsupported messages raise."""
    if kind not in (10, 11, 12, 13, 14, 15, 16, 18, 19, 20, 26):
        raise NativeError(f"unsupported native prompt {kind}")
    player = reader.u8()
    if player not in (0, 1):
        raise NativeError("invalid native prompt player")
    info, options, choices = PromptInfo(kind), [], ()

    def add(action, refs=(), value=None, response=0, details=None):
        options.append(NativeOption(action, tuple(refs), value, response, details))
        if len(options) > 2048:
            raise NativeError("native choices exceed action budget")

    def card(with_subsequence=False):
        code, owner, zone, sequence = reader.u32(), reader.u8(), reader.u8(), reader.u8()
        extra = reader.u8() if with_subsequence else None
        return code, owner, zone, sequence, extra

    def activation(index, response):
        _code, owner, zone, sequence, _ = card()
        description = reader.u32()
        if owner != player:
            raise NativeError("activation outside own controlled zones")
        add("activate", (visible_ref(player, owner, zone, sequence),), description, response,
            ActionDetails(description=description))

    if kind == 10:
        for i in range(reader.u8()):
            activation(i, i << 16)
        for i in range(reader.u8()):
            _code, owner, zone, sequence, _direct = card(True)
            if owner != player or zone != 4:
                raise NativeError("attack outside controlled monster zone")
            add("attack", (visible_ref(player, owner, zone, sequence),), response=(i << 16) | 1)
        for value in (2, 3):
            if reader.u8():
                add("pass", value=value, response=value)
    elif kind == 11:
        for mode, name in enumerate(("summon", "special_summon", "position", "set", "set", "activate")):
            for i in range(reader.u8()):
                if mode == 5:
                    activation(i, (i << 16) | mode)
                else:
                    _code, owner, zone, sequence, _ = card()
                    if owner != player:
                        raise NativeError("idle action outside controlled zones")
                    add(name, (visible_ref(player, owner, zone, sequence),), response=(i << 16) | mode)
        for value in (6, 7, 8):
            if reader.u8():
                add("select" if value == 8 else "pass", value=value, response=value,
                    details=ActionDetails(operation="shuffle") if value == 8 else None)
    elif kind in (12, 13):
        refs = ()
        if kind == 12:
            _code, owner, zone, sequence, _ = card(True)
            refs = (visible_ref(player, owner, zone, sequence),)
        description = reader.u32()
        add("yes", refs, description, 1, ActionDetails(description=description))
        add("no", refs, description, 0, ActionDetails(description=description))
    elif kind == 14:
        info = PromptInfo(kind, 1, 1)
        for i in range(reader.u8()):
            description = reader.u32()
            add("select", value=description, response=i, details=ActionDetails(description=description))
    elif kind in (15, 20):
        cancelable, minimum, maximum, count = reader.u8(), reader.u8(), reader.u8(), reader.u8()
        info = PromptInfo(kind, minimum, maximum, bool(cancelable))
        candidates = [card(True) for _ in range(count)]
        if kind == 15 and any(c[2] == 1 for c in candidates):
            choices, raw = decode_deck_choices(player, minimum, maximum, [c[:4] for c in candidates])
            for name, refs, value, response in raw:
                add(name, refs, value, response)
        else:
            refs = [visible_ref(player, c[1], c[2], c[3]) for c in candidates]
            if kind == 20 and any(c[2] != 4 or not c[4] for c in candidates):
                raise NativeError("tribute candidate lacks native release weight or monster zone")
            top = min(maximum, count)
            low = minimum if kind == 15 else 0
            if count > 128 or sum(comb(count, k) for k in range(low, top + 1)) > 2048:
                raise NativeError("selection exceeds bounded action enumeration")
            for size in range(low, top + 1):
                for selected in combinations(range(count), size):
                    # This is the pinned core's encoded min weight / max count check,
                    # not a hand-written tribute rule for any card.
                    if kind == 20 and sum(candidates[i][4] for i in selected) < minimum:
                        continue
                    add("select", (refs[i] for i in selected), size, bytes((size, *selected)))
        if cancelable:
            add("pass", response=-1, details=ActionDetails(operation="cancel"))
    elif kind == 16:
        count, _special = reader.u8(), reader.u8()
        reader.take(8)
        forced = False
        for i in range(count):
            _flag, required = reader.u8(), reader.u8()
            _code, owner, zone, sequence, _ = card(True)
            description = reader.u32()
            if owner != player:
                raise NativeError("chain outside controlled visible zones")
            add("activate", (visible_ref(player, owner, zone, sequence),), description, i,
                ActionDetails(description=description))
            forced |= bool(required)
        info = PromptInfo(kind, cancelable=not forced)
        if not forced:
            add("pass", response=-1)
    elif kind == 18:
        count, forbidden = reader.u8(), reader.u32()
        if count not in (0, 1):
            raise NativeError("multi-place selection is unsupported")
        info = PromptInfo(kind, count, count, count == 0)
        for relative in (0, 1):
            owner = player if relative == 0 else 1 - player
            for location, shift, zone in ((4, 0, "monster"), (8, 8, "spell_trap")):
                for sequence in range(7 if location == 4 else 8):
                    if not forbidden & (1 << (sequence + shift + relative * 16)):
                        add("select", value=sequence, response=bytes((owner, location, sequence)),
                            details=ActionDetails(destination=Placement(owner, zone, sequence)))
        if count == 0:
            add("pass", response=bytes((player, 0, 0)), details=ActionDetails(operation="cancel"))
    elif kind == 19:
        reader.u32()
        positions = reader.u8()
        for position in (1, 2, 4, 8):
            if positions & position:
                add("position", value=position, response=position)
    elif kind == 26:
        finishable, cancelable, minimum, maximum = reader.u8(), reader.u8(), reader.u8(), reader.u8()
        info = PromptInfo(kind, minimum, maximum, bool(cancelable), bool(finishable))
        offset = 0
        for operation in ("add", "remove"):
            candidates = [card(True) for _ in range(reader.u8())]
            if offset + len(candidates) > 128:
                raise NativeError("unselect candidates exceed bounded scope")
            for i, c in enumerate(candidates):
                add("select", (visible_ref(player, c[1], c[2], c[3]),), int(operation == "add"),
                    bytes((1, offset + i)), ActionDetails(operation=operation))
            offset += len(candidates)
        if finishable or cancelable:
            add("pass", response=-1, details=ActionDetails(operation="finish" if finishable else "cancel"))
    else:
        raise NativeError(f"unsupported native prompt {kind}")
    if reader.offset != len(reader.data) or not options:
        raise NativeError("malformed or empty native decision")
    return DecodedPrompt(player, info, tuple(options), choices)
