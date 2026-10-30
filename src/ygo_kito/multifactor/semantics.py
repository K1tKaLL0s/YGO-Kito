"""Narrow dict adapter for the separate effect window; no upstream code import.

Only positive, observed operations enter factors. Missing operations, unparsed
clauses and unverified opening reachability remain unknown. Not a text parser.
"""

from .contracts import FactorContractError, Factors, Group, Observation, text

SUPPORTED_SEMANTIC_VERSION = "public-effect-clauses-v2"
OPERATION_FACTORS = {
    "send_grave": "effect_send_grave", "mill": "effect_mill",
    "search_or_recover": None, "special_summon": "effect_special_summon",
    "negate": "effect_negate", "destroy": "effect_destroy", "draw": "effect_draw",
    "return_fusion_materials": "effect_recover", "fusion_summon": "effect_fusion",
}


def group_from_semantics(snapshot, *, key, source_ref, measured=None, confidence=0.0, uncertainty=1.0):
    """Consume CardSemantics.to_dict() or an explicitly partial manual snapshot.

    measured is optional, independently sourced group Factors from the host.
    It cannot silently overwrite a semantic observation. Reliability is supplied
    by the host; defaults carry no claimed calibration. Player locks here only
    mark their presence; actual conflicts/reachability require context or engine.
    """
    text(source_ref, "semantic source reference")
    if not isinstance(snapshot, dict) or snapshot.get("semantic_version") != SUPPORTED_SEMANTIC_VERSION:
        raise FactorContractError("unsupported effect semantic version")
    if not isinstance(snapshot.get("effects"), (list, tuple)):
        raise FactorContractError("semantic effects sequence required")
    factors, notes = {}, ["partial observations; no route or role labels derived"]
    text_hash = snapshot.get("text_sha256")
    if text_hash is not None and (not isinstance(text_hash, str) or len(text_hash) != 64
                                  or any(c not in "0123456789abcdef" for c in text_hash)):
        raise FactorContractError("semantic text digest must be SHA256 or null")
    source = source_ref + (":text_sha256=" + text_hash if text_hash else ":text_digest_unknown")
    notes.extend("card:" + str(value) for value in snapshot.get("unknown", ()))
    restrictions = list(snapshot.get("restrictions", ()))

    def observed(name):
        factors[name] = Observation(1.0, confidence, uncertainty, source)

    for effect in snapshot["effects"]:
        if not isinstance(effect, dict):
            raise FactorContractError("semantic effect object required")
        index = effect.get("index", "unknown")
        notes.extend(f"effect:{index}:unknown:{value}" for value in effect.get("unknown", ()))
        notes.append(f"effect:{index}:trigger={effect.get('trigger', {})}")
        notes.append(f"effect:{index}:costs={effect.get('costs', ())}")
        notes.append(f"effect:{index}:count_limits={effect.get('count_limits', ())}")
        restrictions.extend(effect.get("restrictions", ()))
        for op in effect.get("operations", ()):
            if not isinstance(op, dict):
                raise FactorContractError("semantic operation object required")
            if op.get("reason") != "effect" or not op.get("source"):
                notes.append(f"effect:{index}:untrusted_operation:{op.get('kind')}")
                continue
            notes.append(f"effect:{index}:observed_operation:{op}")
            kind = op.get("kind")
            if kind == "search_or_recover":
                zones = op.get("from_zones", ())
                # Broad mixed-zone observations do not certify both functions.
                if zones in (("deck",), ["deck"]):
                    observed("effect_search")
                elif zones in (("grave",), ["grave"]):
                    observed("effect_recover")
                else:
                    notes.append(f"effect:{index}:search_or_recover_origin_unresolved")
            elif OPERATION_FACTORS.get(kind):
                observed(OPERATION_FACTORS[kind])
            else:
                notes.append(f"effect:{index}:unsupported_operation:{kind}")
        for count in effect.get("count_limits", ()):
            if (isinstance(count, dict) and count.get("status") == "known" and
                    count.get("maximum") == 1 and count.get("period") == "turn" and count.get("source")):
                observed("effect_once_per_turn")
    for restriction in restrictions:
        if not isinstance(restriction, dict):
            raise FactorContractError("semantic restriction object required")
        notes.append("scoped_restriction:" + str(restriction))
        if restriction.get("scope") == "player" and restriction.get("source"):
            observed("effect_player_lock")
    if measured is not None:
        if not isinstance(measured, Factors) or measured.family != "group":
            raise FactorContractError("independently sourced group factors required")
        if factors.keys() & dict(measured.items).keys():
            raise FactorContractError("semantic factor overwrite requires explicit upstream reconciliation")
        factors.update(measured.items)
    refs = () if snapshot.get("card_id") is None else ("card:" + str(snapshot["card_id"]),)
    return Group(key, Factors.from_mapping("group", factors), refs, tuple(notes))
