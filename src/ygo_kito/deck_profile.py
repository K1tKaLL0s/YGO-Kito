"""Declarative main-deck inputs; rule legality is checked against the locked database."""

from collections import Counter

from .validation import ContractError, array, fields, integer, text


def validate_profile(value):
    d = fields(value, {"schema_version", "name", "decks"})
    integer(d["schema_version"], "deck profile schema", 1, 1)
    text(d["name"], "deck profile name")
    decks = array(d["decks"], "decks")
    if len(decks) != 2:
        from .validation import ContractError
        raise ContractError("deck profile requires exactly two main decks")
    result = []
    for deck in decks:
        codes = array(deck, "main deck")
        for code in codes:
            integer(code, "card ID", 1, 2**32 - 1)
        result.append(tuple(codes))
    return tuple(result)


def validate_main_deck(codes, rows, limits, *, allowed=None, strict_40=False):
    if not (len(codes) == 40 if strict_40 else 40 <= len(codes) <= 60):
        raise ContractError("main deck size outside supported range")
    aliases = Counter()
    for code in codes:
        integer(code, "card ID", 1, 2**32 - 1)
        row = rows.get(code)
        if not row or not row["ot"] & 1 or (allowed is not None and code not in allowed):
            raise ContractError("card outside declared database/pool")
        if row["type"] & (0x40 | 0x2000 | 0x800000 | 0x4000000):
            raise ContractError("extra-deck card cannot be placed in main deck")
        aliases[row["alias"] or code] += 1
    if any(count > limits.get(code, 3) for code, count in aliases.items()):
        raise ContractError("deck aliases exceed combined copy limit")
