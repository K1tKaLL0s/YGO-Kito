"""Bounded observer knowledge from actual client routing, never hidden queries.

Deck confirmations are historical multisets. Their temporary slot aliases die
on a shuffle or any move touching that array. Public overlay MOVE identities
survive a position change, just as the pinned client's overlay objects do.
"""
from .contracts import PrivateReveal, RevealedCard
from .native_protocol import NativeError


def remember_confirmation(engine, viewer, cards):
    if not getattr(engine,"knowledge_actions",False) or not cards:
        return
    if any(zone != 1 for _, _, zone, _ in cards):
        # The server routes by the first location. Mixed private confirmations
        # need a separately reviewed contract rather than silently broadening it.
        raise NativeError("mixed private confirmation is unsupported")
    ref = f"private-reveal-{engine._private_reveal_counters[viewer]}"
    engine._private_reveal_counters[viewer] += 1
    reveal = PrivateReveal(ref, viewer, tuple(RevealedCard(c, p, "deck") for c, p, _, _ in sorted(cards)))
    records = engine._private_reveals[viewer]
    records.append(reveal)
    if len(records) > 32:
        evicted = records.pop(0).ref
        engine._private_revealed_slots[viewer] = {
            k: v for k, v in engine._private_revealed_slots[viewer].items() if v[1] != evicted}
    for code, controller, zone, sequence in cards:
        engine._private_revealed_slots[viewer][(controller, zone, sequence)] = (code, ref)


def forget_slots(engine, controller=None, zone=None):
    if not getattr(engine,"knowledge_actions",False):
        return
    for viewer in (0, 1):
        engine._private_revealed_slots[viewer] = {
            k: v for k, v in engine._private_revealed_slots[viewer].items()
            if not ((controller is None or k[0] == controller) and (zone is None or k[1] == zone))}


def public_move(engine, code, previous, current, previous_public):
    if not getattr(engine,"knowledge_actions",False):
        return
    for slot in (previous, current):
        if slot[1] in (1, 2, 16, 32, 64):
            forget_slots(engine, slot[0], slot[1])
    materials = engine._public_materials
    if previous[1] & 0x80:
        key = (previous[0], previous[1] & 0x7f, previous[2], previous[3])
        prior = materials.pop(key, None)
        owner = prior[1] if prior is not None else None
        for old in sorted(tuple(materials)):
            if old[:3] == key[:3] and old[3] > key[3]:
                materials[old[:3] + (old[3] - 1,)] = materials.pop(old)
    else:
        owner = engine._known_owners.get(tuple(previous[:3])) if previous_public else None
        attached = {key[3]: materials.pop(key) for key in tuple(materials) if key[:3] == tuple(previous[:3])}
        if not current[1] & 0x80:
            for sub, identity in attached.items():
                materials[tuple(current[:3]) + (sub,)] = identity
        if previous[1] in (2, 16, 32, 64):
            for old in sorted(tuple(materials)):
                if old[:2] == tuple(previous[:2]) and old[2] > previous[2]:
                    materials[old[:2] + (old[2] - 1, old[3])] = materials.pop(old)
    if current[1] & 0x80:
        # single_duel.cpp sends the nonzero identity to BOTH players on every
        # MOVE into OVERLAY. Raw previous hand/deck positions are never retained.
        if not code:
            raise NativeError("public overlay move has no identity")
        materials[(current[0], current[1] & 0x7f, current[2], current[3])] = (code, owner)


def forget_material_associations(engine):
    if getattr(engine,"knowledge_actions",False):
        engine._public_materials.clear()
