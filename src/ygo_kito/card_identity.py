"""Catalog identity shared by release admission and existing model rows."""
from .validation import ContractError


def canonical_card_id(rows, code):
    seen = set()
    while code in rows and rows[code].get('alias'):
        if code in seen:
            raise ContractError('cyclic card alias in catalog')
        seen.add(code)
        target = rows[code]['alias']
        if target in seen:
            raise ContractError('cyclic card alias in catalog')
        source, other = rows[code], rows.get(target,{})
        # alias also covers cards whose rules treat them as the same name.
        # Those can have different effects and release dates (for example,
        # several different Field Spells treated as 海). Only actual alternate
        # printings may inherit a release or an existing model identity.
        if (not all(k in source and k in other for k in ('name','desc','type')) or
                not isinstance(source.get('name'),str) or not source['name'].strip() or
                not isinstance(source.get('desc'),str) or
                any(source[k] != other[k] for k in ('name','desc','type','atk','def','level','race','attribute','setcode')
                    if k in source and k in other)):
            break
        code = target
    return code


def released_identities(rows, released):
    """Alternate same-name IDs inherit the identity's existing release record."""
    identities = {canonical_card_id(rows, c) for c in released}
    return {c for c in rows if canonical_card_id(rows, c) in identities}


def native_card_identity(rows, code):
    """Return the script's printed code and the core's permanent rule name."""
    row = rows[code]
    alias = row.get("alias") or code
    if alias == code or row.get("type", 0) & 0x4000:
        return alias, alias
    # Period assets contain both printed rows. An incomplete catalog can
    # retain its existing mapping until the source printing is available.
    target = rows.get(alias, {})
    if any(not isinstance(item.get(key), str) for item in (row, target) for key in ("name", "desc")):
        return alias, alias
    printed = canonical_card_id(rows, code)
    return printed, rows[printed].get("alias") or printed


def rule_name_id(rows, code):
    return native_card_identity(rows, code)[1]
