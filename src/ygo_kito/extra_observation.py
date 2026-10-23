"""Player-visible extra/banished/attached material projection for profile v2.

Extra sequence indices stay private. Unknown material owner is represented as
unknown, never guessed from the host controller. Hidden host materials are not
queried for an opponent; this intentionally conservative case remains partial.
"""
from dataclasses import replace
import ctypes

from .contracts import CardView
from .native_protocol import NativeError, Reader, visible_ref


def extend(engine, observer, cards):
    engine._extra_refs = {}
    engine._material_refs = {}
    for player in (0, 1):
        for sequence in range(engine._count(player, 32)):
            position = engine._query(player, 32, sequence, 2)[1]
            public = bool(position & 5)
            visible = public or player == observer
            code, owner = None, None
            if visible:
                code, owner, _, _ = engine._visible_data(player, 32, sequence)
            cards.append(CardView(f"p{player}.banished.{sequence}", owner, player, "banished",
                                  "public" if public else "observer" if visible else "hidden", code, position))
        visible_extra, hidden = [], 0
        for sequence in range(engine._count(player, 64)):
            position = engine._query(player, 64, sequence, 2)[1]
            public = bool(position & 5)
            if player == observer or public:
                code, owner, _, _ = engine._visible_data(player, 64, sequence)
                visible_extra.append((code, position, sequence, owner, public))
            else:
                hidden += 1
        for ordinal, (code, position, sequence, owner, public) in enumerate(sorted(visible_extra)):
            ref = f"p{player}.extra.visible-{ordinal}"
            engine._extra_refs[(player, sequence)] = ref
            cards.append(CardView(ref, owner, player, "extra", "public" if public else "observer", code, position))
        for index in range(hidden):
            cards.append(CardView(f"p{player}.extra.hidden-{index}", None, player, "extra", "hidden", None, 8))
    for index, host in enumerate(tuple(cards)):
        if host.zone != "monster" or host.visibility == "hidden":
            continue
        sequence = int(host.ref.rsplit(".", 1)[1])
        buffer = (ctypes.c_uint8 * 1024)()
        length = engine.lib.query_card(engine.handle, host.controller, 4, sequence, 0x10000, buffer, 0)
        if not 12 <= length <= len(buffer):
            raise NativeError("material query length differs")
        reader = Reader(bytes(buffer[:length]))
        if reader.u32() != length or reader.u32() != 0x10000:
            raise NativeError("material query flags differ")
        count = reader.u32()
        if count > 128 or length != 12 + 4 * count:
            raise NativeError("material query count differs")
        cards[index] = replace(host, material_count=count)
        for material in range(count):
            code = reader.u32()
            ref = host.ref + f".material.{material}"
            engine._material_refs[(host.controller, 4, sequence, material)] = ref
            owner = engine._overlay_owners.get((host.controller, 4, sequence, material))
            cards.append(CardView(ref, owner, host.controller, "overlay", "public" if host.visibility == "public" else "observer",
                                  code, attached_to=host.ref))
    return cards


def resolve(engine, player, controller, location, sequence, subsequence=None):
    if location == 64:
        ref = engine._extra_refs.get((controller, sequence))
    elif location & 0x80:
        ref = engine._material_refs.get((controller, location & 0x7f, sequence, subsequence))
    elif location == 32:
        ref = f"p{controller}.banished.{sequence}" if controller in (0, 1) else None
    else:
        return visible_ref(player, controller, location, sequence, subsequence)
    if ref is None:
        raise NativeError("extended selection outside visible registered references")
    return ref


def moved(engine, previous, current):
    if previous[1] & 0x80:
        key = (previous[0], previous[1] & 0x7f, previous[2], previous[3])
        owner = engine._overlay_owners.pop(key, None)
        for old in sorted(tuple(engine._overlay_owners)):
            if old[:3] == key[:3] and old[3] > key[3]:
                engine._overlay_owners[old[:3] + (old[3] - 1,)] = engine._overlay_owners.pop(old)
    else:
        owner = engine._known_owners.pop(tuple(previous[:3]), None)
        # Xyz materials first attach while the host is still in EXTRA (0xc0),
        # then its own MOVE relocates the host and all material references.
        attached = {key[3]: engine._overlay_owners.pop(key) for key in tuple(engine._overlay_owners)
                    if key[:3] == tuple(previous[:3])}
        if not current[1] & 0x80:
            for sub, known_owner in attached.items():
                engine._overlay_owners[tuple(current[:3]) + (sub,)] = known_owner
        if previous[1] in (2, 16, 32, 64):
            for old in sorted(tuple(engine._known_owners)):
                if old[:2] == tuple(previous[:2]) and old[2] > previous[2]:
                    engine._known_owners[old[:2] + (old[2] - 1,)] = engine._known_owners.pop(old)
            for old in sorted(tuple(engine._overlay_owners)):
                if old[:2] == tuple(previous[:2]) and old[2] > previous[2]:
                    engine._overlay_owners[old[:2] + (old[2] - 1, old[3])] = engine._overlay_owners.pop(old)
    if current[1] & 0x80:
        engine._overlay_owners[(current[0], current[1] & 0x7f, current[2], current[3])] = owner
    elif current[1] != 1 and owner is not None:
        engine._known_owners[tuple(current[:3])] = owner
