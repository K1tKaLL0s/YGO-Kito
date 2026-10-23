"""Declarative main-deck inputs; rule legality is checked against the locked database."""

from collections import Counter

from .validation import ContractError, array, fields, integer, text


def validate_profile(value):
    version = integer(value.get("schema_version") if isinstance(value, dict) else None, "deck profile schema", 1, 2)
    d = fields(value, {"schema_version", "name", "decks"} | ({"extras", "sides"} if version == 2 else set()))
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
    if version == 2:
        for zone in ("extras", "sides"):
            parts = array(d[zone], zone)
            if len(parts) != 2:
                raise ContractError("extended profile requires two extra/side lists")
            for codes in parts:
                if len(array(codes, zone)) > 15:
                    raise ContractError("extended profile section exceeds 15")
                for code in codes:
                    integer(code, "extended profile card", 1, 2**32 - 1)
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


def validate_deck_parts(deck, rows, limits, *, allowed=None):
    """Shared main/extra/side listing checks, not card-effect or route validation."""
    fields(deck, {"main", "extra", "side"})
    for zone in ("main", "extra", "side"):
        array(deck[zone], zone)
        for code in deck[zone]:
            integer(code, "card ID", 1, 2**32 - 1)
    if len(deck["extra"]) > 15 or len(deck["side"]) > 15:
        raise ContractError("extra/side deck exceeds 15 cards")
    validate_main_deck(deck["main"], rows, limits, allowed=allowed)
    counts = Counter()
    for code in deck["main"] + deck["extra"] + deck["side"]:
        row = rows.get(code)
        if not row or not row["ot"] & 1 or (allowed is not None and code not in allowed):
            raise ContractError("card absent from declared OCG pool")
        if row["type"] & 0x4000:  # TYPE_TOKEN in the locked core common.h.
            raise ContractError("tokens cannot be listed in a deck")
        counts[row["alias"] or code] += 1
    if any(count > limits.get(code, 3) for code, count in counts.items()):
        raise ContractError("combined main/extra/side alias limit exceeded")
    if any(not rows[code]["type"] & (0x40 | 0x2000 | 0x800000 | 0x4000000) for code in deck["extra"]):
        raise ContractError("non-extra-deck card in extra deck")
