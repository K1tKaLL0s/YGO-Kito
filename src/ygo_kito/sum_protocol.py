"""MSG23 wire constraints translated from the pinned GPL YGOPro playerop.cpp.

This enumerates native-offered numerical choices; card eligibility is the core's
decision. Native optional indices and mandatory response padding never leave it.
"""
from functools import lru_cache
from itertools import combinations
from math import comb

from .contracts import ActionDetails, PromptInfo, SumCandidate, SumSelection
from .native_protocol import NativeError, NativeOption, DecodedPrompt


def contributions(value):
    low, high = value & 0xffff, value >> 16
    if high & 0x8000:
        return (value & 0x7fffffff,)
    return (low, high) if high else (low,)


def accepted(values, target, mode):
    if not values:
        return False
    if mode == 1:
        lower = [min(v) for v in values]
        return sum(max(v) for v in values) >= target and sum(lower) - min(lower) < target
    @lru_cache(None)
    def check(index, acc, smallest):
        if check.cache_info().misses > 8192:
            raise NativeError("native sum arithmetic exceeds bounded state budget")
        if acc == 0 or index == len(values):
            return False
        if index == len(values) - 1:
            return any(acc == v and acc + smallest > v for v in values[index])
        return any(acc > v and check(index + 1, acc - v, min(smallest, v)) for v in values[index])
    return check(0, target, 0xffff)


def decode_sum(reader, resolve):
    mode, player, target = reader.u8(), reader.u8(), reader.u32()
    if mode not in (0, 1) or player not in (0, 1) or not 0 < target < 2**31:
        raise NativeError("invalid native sum header")
    minimum, maximum = reader.u8(), reader.u8()
    groups = []
    for _ in range(2):
        group = []
        for _ in range(reader.u8()):
            code, owner, zone, sequence, packed = reader.u32(), reader.u8(), reader.u8(), reader.u8(), reader.u32()
            if not code:
                raise NativeError("sum candidate identity unavailable")
            group.append(SumCandidate(resolve(player, owner, zone, sequence), contributions(packed)))
        groups.append(group)
    mandatory, optional = groups
    if (reader.offset != len(reader.data) or minimum > maximum or len(mandatory) > 63
            or len(mandatory) + len(optional) > 128 or len({c.ref for g in groups for c in g}) != sum(map(len, groups))):
        raise NativeError("malformed/duplicate/out-of-budget sum candidates")
    if target + 0xffff >= 2**31 or sum(max(c.values) for c in mandatory + optional) >= 2**31:
        raise NativeError("sum arithmetic exceeds pinned signed-integer range")
    low, high = (minimum, min(maximum, len(optional))) if mode == 0 else (0, len(optional))
    # Never silently drop core-offered combinations outside the 64-byte response.
    if high + len(mandatory) > 63 or low > high or sum(comb(len(optional), k) for k in range(low, high + 1)) > 2048:
        raise NativeError("sum choices exceed bounded enumeration")
    options = []
    for size in range(low, high + 1):
        for selected in combinations(range(len(optional)), size):
            cards = mandatory + [optional[i] for i in selected]
            if accepted([c.values for c in cards], target, mode):
                response = bytes((len(cards), *([0] * len(mandatory)), *selected))
                options.append(NativeOption("select", tuple(c.ref for c in cards), len(cards), response, ActionDetails(operation="sum")))
    if not options:
        raise NativeError("native sum prompt has no supported legal response")
    spec = SumSelection("equal" if mode == 0 else "minimal_at_least", target, minimum, maximum, tuple(mandatory), tuple(optional))
    return DecodedPrompt(player, PromptInfo(23, minimum, maximum), tuple(options), sum_selection=spec)
