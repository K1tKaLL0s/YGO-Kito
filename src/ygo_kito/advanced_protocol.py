"""Bounded translations of the pinned playerop.cpp, never card-effect rules.

All card-name predicates use the public callback catalogue. Native indices,
private deck positions and opponent declarations in progress remain private.
"""
from itertools import combinations, permutations
from math import comb, factorial
import struct

from .contracts import ActionDetails, Placement, PromptInfo, SearchChoice
from .native_protocol import DecodedPrompt, NativeError, NativeOption

MESSAGES = (18, 22, 24, 25, 132, 140, 141, 142, 143)


def declarable(row, code, opcodes):
    """Pinned is_declarable stack language; reject undefined signed overflow.

    The adapter's callback supplies rule_code=0. Alias/token checks and set-code
    semantics therefore match that exact callback, not a newer database schema.
    """
    if row["alias"] or row["type"] & 0x4000:
        return False
    stack = []
    for op in opcodes:
        if 0x40000000 <= op <= 0x40000005:
            if len(stack) < 2:
                raise NativeError("malformed declaration stack")
            b, a = stack.pop(), stack.pop()
            values = (lambda: a+b, lambda: a-b, lambda: a*b,
                      lambda: (abs(a)//abs(b)) * (-1 if (a<0) != (b<0) else 1) if b else 0,
                      lambda: int(bool(a) and bool(b)), lambda: int(bool(a) or bool(b)))
            value = values[op - 0x40000000]()
        elif op in (0x40000006, 0x40000007) or 0x40000100 <= op <= 0x40000104:
            if not stack:
                raise NativeError("malformed unary declaration stack")
            a = stack.pop()
            if op == 0x40000006: value = -a
            elif op == 0x40000007: value = int(not a)
            elif op == 0x40000100: value = int(code == a)
            elif op == 0x40000101:
                sets = [(row["setcode"] % 2**64 >> (16*i)) & 0xffff for i in range(4)]
                value = int(any(s and (s & 0xfff) == (a & 0xfff) and s & (a & 0xf000) == a & 0xf000 for s in sets))
            else:
                value = row[("type", "race", "attribute")[op - 0x40000102]] & a
        else:
            if 0x40000000 <= op < 0x50000000:
                raise NativeError("unknown declaration opcode")
            value = op if op < 2**31 else op - 2**32
        if not -2**31 <= value < 2**31:
            raise NativeError("declaration signed arithmetic overflow")
        stack.append(value)
    if len(stack) != 1:
        raise NativeError("declaration predicate stack is not singular")
    return bool(stack[0])


def decode_advanced(kind, reader, resolve, catalog):
    player = reader.u8()
    if player not in (0, 1):
        raise NativeError("invalid advanced prompt player")
    options, choices = [], ()
    info = PromptInfo(kind)

    def add(name, refs=(), value=None, response=0, details=None):
        options.append(NativeOption(name, tuple(refs), value, response, details))
        # Card declarations can offer the entire public catalogue. Do not
        # silently truncate it to the small neural prototype's 2048-action cap.
        if len(options) > (50000 if kind == 142 else 2048):
            raise NativeError("advanced choices exceed bounded enumeration")

    if kind == 22:
        counter, total, count = reader.u16(), reader.u16(), reader.u8()
        if not 0 < count <= 32 or not total:
            raise NativeError("invalid counter selection size")
        refs, caps = [], []
        for _ in range(count):
            code, owner, zone, seq, cap = reader.u32(), reader.u8(), reader.u8(), reader.u8(), reader.u16()
            if not code or zone not in (4, 8) or not cap:
                raise NativeError("invalid counter candidate")
            refs.append(resolve(player, owner, zone, seq))
            caps.append(cap)
        if len(set(refs)) != count or sum(caps) < total:
            raise NativeError("duplicate/insufficient counter candidates")
        # Enumerate exactly the offered bounded integer allocations. State cap
        # also bounds impossible partial branches, not just successful actions.
        states = 0
        def visit(index, remaining, alloc):
            nonlocal states
            states += 1
            if states > 16384:
                raise NativeError("counter allocation exceeds search budget")
            if index == count:
                if not remaining:
                    add("select", refs, total, struct.pack("<" + "H"*count, *alloc),
                        ActionDetails(counter_type=counter, quantities=tuple(alloc)))
                return
            low, high = max(0, remaining-sum(caps[index+1:])), min(caps[index], remaining)
            for value in range(low, high+1):
                visit(index+1, remaining-value, alloc+[value])
        visit(0, total, [])
        info = PromptInfo(kind, total, total)
    elif kind in (18,24):
        count, forbidden = reader.u8(), reader.u32()
        places = [(owner, loc, seq) for relative, owner in ((0, player), (1, 1-player))
                  for loc, shift in ((4, 0), (8, 8)) for seq in range(7 if loc == 4 else 8)
                  if not forbidden & (1 << (seq+shift+16*relative))]
        size=max(1,count)
        if count > 21 or kind==24 and not count or count>len(places) or comb(len(places), size) > 2048:
            raise NativeError("disabled field choices exceed bounded response/enumeration")
        info = PromptInfo(kind, count, count, kind==18 and count==0)
        for selected in combinations(places, size):
            placements=tuple(Placement(p,"monster" if z==4 else "spell_trap",s) for p,z,s in selected)
            add("select", value=selected[0][2] if kind==18 and size==1 else count, response=bytes(x for p in selected for x in p),
                details=ActionDetails(destination=placements[0]) if kind==18 and size==1 else ActionDetails(destinations=placements))
        if kind==18 and count==0:
            add("pass",response=bytes((player,0,0)),details=ActionDetails(operation="cancel"))
    elif kind == 25:
        count = reader.u8()
        if not 0 < count <= 6 or factorial(count) > 2048:
            raise NativeError("sorting exceeds bounded permutation budget")
        native = [(reader.u32(), reader.u8(), reader.u8(), reader.u8(), i) for i in range(count)]
        if any(not c or p not in (0,1) or z not in (1,2,4,8,16,32,64) for c,p,z,s,i in native):
            raise NativeError("unsupported sorting location/identity")
        # Sort display identities, never original deck positions. Equal copies
        # remain indistinguishable but all native permutations are retained.
        ordered = sorted(native, key=lambda c: (c[0], c[1], c[2]))
        choices = tuple(SearchChoice(f"ordering-{i}", c, p, "ordering") for i,(c,p,z,s,n) in enumerate(ordered))
        for order in permutations(range(count)):
            ranks = [0]*count
            for rank, i in enumerate(order):
                ranks[ordered[i][4]] = rank
            add("order", (choices[i].ref for i in order), response=bytes(ranks))
        add("pass", response=b"\xff", details=ActionDetails(operation="cancel"))
        info = PromptInfo(kind, count, count, True)
    elif kind in (140, 141):
        count, available = reader.u8(), reader.u32()
        valid = (1 << (26 if kind == 140 else 7))-1
        if available & ~valid:
            raise NativeError("declaration mask exceeds pinned race/attribute range")
        bits = [1 << i for i in range(26 if kind == 140 else 7) if available & (1 << i)]
        if count > len(bits) or comb(len(bits), count) > 2048:
            raise NativeError("declaration combinations exceed bounded scope")
        info = PromptInfo(kind, count, count)
        for selected in combinations(bits, count):
            mask = sum(selected)
            add("number", value=mask, response=mask)
    elif kind == 142:
        opcodes = tuple(reader.u32() for _ in range(reader.u8()))
        if not opcodes or catalog is None or len(catalog) > 50000:
            raise NativeError("card declaration needs a bounded public callback catalogue")
        for code, row in sorted(catalog.items()):
            if declarable(row, code, opcodes):
                add("number", value=code, response=code)
    elif kind == 143:
        for i in range(reader.u8()):
            add("number", value=reader.u32(), response=i)
    elif kind == 132:
        for value in (1, 2, 3):
            add("number", value=value, response=value)
    else:
        raise NativeError("unknown advanced decision")
    if reader.offset != len(reader.data) or not options:
        raise NativeError("malformed/empty advanced prompt")
    return DecodedPrompt(player, info, tuple(options), choices)
