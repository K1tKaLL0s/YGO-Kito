"""Revision 3 public history, following pinned core AND single_duel routing.

The full internal trace is never copied. Only typed public facts enter DTOs.
Private deck confirmations, sorting positions and simultaneous pending RPS
answers have no public-history entry. Published past facts survive shuffles.
"""
import struct

from .contracts import PublicEvent, PublicEventDetails, PublicLocation
from .native_protocol import NativeError

ZONES = {0: "none", 1: "deck", 2: "hand", 4: "monster", 8: "spell_trap", 16: "graveyard", 32: "banished", 64: "extra"}
PHASES = {1: "draw", 2: "standby", 4: "main1", 8: "battle", 16: "battle", 32: "battle", 64: "battle", 128: "battle", 256: "main2", 512: "end"}


def location(slot):
    p, z, s, pos = slot
    if p not in (0, 1):
        raise NativeError("invalid historical controller")
    if z & 0x80:
        # Overlay's fourth byte is a material index, never a position.
        # During Xyz construction a host can still be in EXTRA (0xc0).
        # Its sequence is private even though material identities were public.
        return PublicLocation(p, "overlay", s if (z & 0x7f) in (4,8) else None)
    if z not in ZONES:
        raise NativeError("unknown public history location")
    if z in (4,8,32,64) and pos & ~0x8f:
        raise NativeError("unknown native position flag")
    return PublicLocation(p, ZONES[z], s if z in (4,8,16,32) else None,
                          pos & 15 if z in (4,8,32,64) else None)


def public_slot(slot):
    return slot[1] == 16 or slot[1] in (4,8,32,64) and bool(slot[3] & 5) or slot[1] in (4,8) and bool(slot[3] & 0x80)


def emit(engine, kind, message, codes=(), **kwargs):
    if len(engine._public_history) >= 50000:
        raise NativeError("public history exceeds explicit event budget")
    # No raw event dictionary, global event index or unapproved extra key enters.
    event = PublicEvent(f"public-{len(engine._public_history)}", kind,
                        tuple(c for c in codes if c), PublicEventDetails(message, **kwargs))
    engine._public_history.append(event)


def consume(engine, kind, r, audit):
    """Consume one non-decision message. Unknown/tag/debug messages fail closed."""
    if kind == 2:
        hint, player, value = r.u8(), r.u8(), r.u32()
        if player not in (0,1):
            raise NativeError("invalid hint player")
        # single_duel.cpp broadcasts CARD/ZONE. Other hints have ONE recipient.
        # Race/attribute/card/number become common knowledge only when this is
        # the echo of the chooser's submitted declaration: chooser already knew
        # its own value, and the hint now delivers it to the opponent. Scripted
        # private OPSELECTED/EFFECT or unmatched hints are never broadcast here.
        declared=getattr(engine,'_public_declarations',{}).pop((hint,player),None)
        if hint in (10,11) or hint in (6,7,8,9) and declared==value:
            emit(engine, "announce", kind, (value,) if hint in (8,10) else (), player=player, value=value, description=hint)
    elif kind == 40:
        engine.turn_player = r.u8()
        if engine.turn_player not in (0,1):
            raise NativeError("invalid turn player")
        engine.turn += 1
        audit.update(player=engine.turn_player, turn=engine.turn)
        emit(engine, "turn", kind, player=engine.turn_player, turn=engine.turn)
    elif kind == 41:
        value = r.u16()
        if value not in PHASES:
            raise NativeError("unknown native phase")
        engine.phase = PHASES[value]
        audit["phase"] = engine.phase
        emit(engine, "phase", kind, player=engine.turn_player, turn=engine.turn, phase=engine.phase)
    elif kind in (32,35):
        p = r.u8()
        if p not in (0,1): raise NativeError("invalid shuffle player")
        from .private_knowledge import forget_slots
        forget_slots(engine,p,1 if kind==32 else 16)
        if kind==35:forget_slots(engine,p,1)  # grave/deck swap changes BOTH arrays
        engine._known_owners = {k:v for k,v in engine._known_owners.items() if k[:2] != (p,16)} if kind == 35 else engine._known_owners
        audit["player"] = p
        emit(engine, "shuffle", kind, player=p)
    elif kind in (33,39,90):
        p, count = r.u8(), r.u8()
        if p not in (0,1): raise NativeError("invalid hand/extra event player")
        from .private_knowledge import forget_slots
        forget_slots(engine,p,2 if kind in (33,90) else 64)
        if kind==90:forget_slots(engine,p,1)
        codes = tuple(r.u32() for _ in range(count))
        audit.update(player=p, count=count)
        engine._revealed_hand[p].clear()
        if kind == 33:
            from .extra_observation import shuffled_hand
            shuffled_hand(engine,p)
        if kind == 39:
            engine._known_owners = {k:v for k,v in engine._known_owners.items() if k[:2] != (p,64)}
        # DRAW identities are private unless the core's public-faceup bit is
        # present. The other records are intentionally identity-free.
        emit(engine, "move" if kind == 90 else "shuffle", kind,
             (c & 0x7fffffff for c in codes if c & 0x80000000) if kind == 90 else (), player=p, amount=count)
    elif kind == 50:
        code, previous, current, reason = r.u32(), r.take(4), r.take(4), r.u32()
        from .private_knowledge import public_move
        public_move(engine,code,previous,current,public_slot(previous))
        from .extra_observation import moved
        moved(engine, previous, current)
        for slot in (previous,current):
            if slot[1] == 2: engine._revealed_hand[slot[0]].clear()
        audit.update(from_zone=previous[1], to_zone=current[1], player=current[0], reason=reason)
        visible = public_slot(previous) or public_slot(current) or getattr(engine,"knowledge_actions",False) and bool(current[1]&0x80)
        if visible and code: audit["public_card"] = code
        # Core emits zero-code DECK->DECK moves while sorting. Their count and
        # positions are not public decisions and must not leak into history.
        if previous[1] == current[1] == 1:
            return
        emit(engine,"move",kind,(code,) if visible else (),player=current[0],reason=reason,
             locations=(location(previous),location(current)))
    elif kind in (60,62,64):
        code,slot = r.u32(),r.take(4)
        public = bool(slot[3] & 5)
        audit.update(player=slot[0],zone=slot[1],slot=slot[2],position=slot[3])
        if public: audit["public_summoning_card"] = code
        emit(engine,"summon",kind,(code,) if public else (),player=slot[0],locations=(location(slot),))
    elif kind in (61,63,65):
        emit(engine,"summon",kind)
    elif kind == 53:
        code = r.u32()
        p,z,s,old,new = r.take(5)
        audit.update(player=p,zone=z,slot=s,previous_position=old,position=new)
        if (old|new)&5: audit["public_card"] = code
        emit(engine,"position",kind,(code,) if (old|new)&5 else (),player=p,
             locations=(location((p,z,s,old)),location((p,z,s,new))))
    elif kind == 54:
        _code, slot = r.u32(),r.take(4)
        emit(engine,"move",kind,player=slot[0],locations=(location(slot),))
    elif kind == 55:
        c1,s1,c2,s2 = r.u32(),r.take(4),r.u32(),r.take(4)
        # Swapping public-field associations invalidates ownership caches.
        engine._known_owners.clear()
        engine._overlay_owners.clear()
        from .private_knowledge import forget_material_associations
        forget_material_associations(engine)
        emit(engine,"move",kind,tuple(c for c,s in ((c1,s1),(c2,s2)) if public_slot(s)),locations=(location(s1),location(s2)))
    elif kind == 56:
        emit(engine,"disabled",kind,value=r.u32())
    elif kind == 70:
        code,slot = r.u32(),r.take(4)
        p,z,s,description,link = r.u8(),r.u8(),r.u8(),r.u32(),r.u8()
        audit.update(public_card=code,player=p,zone=z,slot=s,description=description,link=link)
        emit(engine,"activate",kind,(code,),player=p,link=link,description=description,locations=(location(slot),))
    elif kind in (71,72,73,75,76):
        link = r.u8()
        audit["link"] = link
        emit(engine,"chain",kind,link=link)
    elif kind == 74:
        emit(engine,"chain",kind)
    elif kind in (81,83):
        p = r.u8() if kind == 81 else None
        slots = tuple(r.take(4) for _ in range(r.u8()))
        audit["targets"] = [list(s[:3]) for s in slots]
        emit(engine,"random" if kind==81 else "target",kind,player=p,locations=tuple(location(s) for s in slots))
    elif kind in (91,92,94,100):
        p,amount = r.u8(),r.u32()
        if p not in (0,1): raise NativeError("invalid LP player")
        engine.life_points[p] = amount if kind==94 else engine.life_points[p]+amount if kind==92 else max(0,engine.life_points[p]-amount)
        audit.update(player=p,amount=amount,lp=engine.life_points[p])
        emit(engine,"lp",kind,player=p,amount=amount,life_points=tuple(engine.life_points))
    elif kind in (93,96,97):
        slots = (r.take(4),r.take(4))
        emit(engine,"equip" if kind==93 else "target",kind,locations=tuple(location(s) for s in slots))
    elif kind in (101,102):
        counter,p,z,s,count = r.u16(),r.u8(),r.u8(),r.u8(),r.u16()
        audit.update(counter_type=counter,player=p,zone=z,slot=s,count=count)
        emit(engine,"counter",kind,player=p,value=counter,amount=count,locations=(location((p,z,s,0)),))
    elif kind == 110:
        a,d = r.take(4),r.take(4)
        audit.update(attacker_player=a[0],attacker_zone=a[1],attacker_slot=a[2],defender_player=d[0],defender_zone=d[1],defender_slot=d[2])
        emit(engine,"attack",kind,player=a[0],locations=(location(a),location(d)))
    elif kind == 111:
        data=r.take(26)
        aa,ad,da,dd=struct.unpack_from('<ii',data,4)+struct.unpack_from('<ii',data,17)
        audit.update(attacker_player=data[0],defender_player=data[13],attacker_atk=aa,defender_atk=da)
        emit(engine,"battle",kind,locations=(location(data[:4]),location(data[13:17])),values=(aa,ad,data[12],da,dd,data[25]))
    elif kind in (112,113,114):
        emit(engine,"battle",kind)
    elif kind == 120:
        # single_duel.cpp routes missed optional timing ONLY to its controller.
        # Its identity/occurrence cannot be a public fact for the other player.
        r.take(8)
    elif kind in (130,131):
        p,count=r.u8(),r.u8()
        values=tuple(r.u8() for _ in range(count))
        if p not in (0,1) or any(v not in ((0,1) if kind==130 else range(1,7)) for v in values):
            raise NativeError("invalid coin/dice event")
        emit(engine,"random",kind,player=p,values=values)
    elif kind == 133:
        hands=r.u8()
        if hands & ~15 or any(v not in (1,2,3) for v in (hands&3,hands>>2)):
            raise NativeError("invalid public RPS result")
        emit(engine,"random",kind,values=(hands&3,hands>>2))
    elif kind in (30,31,42):
        p=r.u8()
        if p not in (0,1): raise NativeError("invalid confirmation player")
        if kind==31: r.u8()  # skip_panel
        cards=tuple((r.u32(),r.u8(),r.u8(),r.u8()) for _ in range(r.u8()))
        if any(not c or own not in (0,1) or z not in ZONES for c,own,z,s in cards):
            raise NativeError("invalid confirmation card")
        engine._confirmation_pause=True
        # Actual single_duel.cpp routing: ConfirmCards where first card is in
        # DECK goes only to the requested viewer. Other confirmations and
        # ConfirmDecktop/Extratop are broadcast. Never infer this from a name.
        public=kind!=31 or not cards or cards[0][2]!=1
        if not public:
            from .private_knowledge import remember_confirmation
            remember_confirmation(engine,p,cards)
        audit.update(viewer=p,public_cards=[c for c,own,z,s in cards] if public else [])
        if public:
            for c,own,z,s in cards:
                if z==2: engine._revealed_hand[own][s]=c
            emit(engine,"reveal",kind,(c for c,own,z,s in cards),player=p,
                 locations=tuple(location((own,z,s,0)) for c,own,z,s in cards))
    elif kind == 36:
        zone,count=r.u8(),r.u8()
        if zone not in (4,8) or count>7: raise NativeError("unsupported set shuffle")
        # Hidden permutation: even though raw payload has both mappings,
        # publish only the original publicly known slots, never destinations.
        old=tuple(r.take(4) for _ in range(count))
        r.take(4*count)
        engine._known_owners.clear()
        engine._overlay_owners.clear()
        from .private_knowledge import forget_material_associations
        forget_material_associations(engine)
        emit(engine,"shuffle",kind,amount=count,locations=tuple(location(s) for s in old))
    elif kind == 37:
        from .private_knowledge import forget_slots
        forget_slots(engine,zone=1)
        emit(engine,"shuffle",kind)
    elif kind == 38:
        p,_offset,packed=r.u8(),r.u8(),r.u32()
        if p not in (0,1): raise NativeError("invalid revealed deck player")
        emit(engine,"reveal",kind,(packed&0x7fffffff,),player=p)
    elif kind == 160:
        slot,hint,value=r.take(4),r.u8(),r.u32()
        # Unlike MSG_MISSED_EFFECT this record is broadcast by single_duel.cpp,
        # even for face-down status hints. Keep its public numeric meaning but
        # strip private hand/deck/extra positions just like every other record.
        emit(engine,"hint",kind,(value,) if hint==2 else (),locations=(location(slot),),value=value,description=hint)
    elif kind == 165:
        p,hint,value=r.u8(),r.u8(),r.u32()
        emit(engine,"hint",kind,player=p,value=value,description=hint)
    elif kind == 170:
        emit(engine,"result",kind,(r.u32(),))
    elif kind == 5:
        winner,reason=r.u8(),r.u8()
        if winner not in (0,1,2): raise NativeError("invalid result winner")
        engine.outcome={"winner":winner,"reason_code":reason}
        audit.update(engine.outcome)
        emit(engine,"result",kind,value=winner,reason=reason)
    else:
        raise NativeError(f"unsupported revision-3 native event {kind}; no result fabricated")
