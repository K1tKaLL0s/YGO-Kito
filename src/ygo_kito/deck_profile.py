"""Declarative main-deck inputs; rule legality is checked against the locked database."""

from .validation import array, fields, integer, text


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
