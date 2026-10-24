"""Detach public receipts from private route replay selection material."""


def without_private_selection_key(value):
    """Copy receipt containers, omitting only this exact private replay key."""
    if isinstance(value, dict):
        return {key: without_private_selection_key(item) for key, item in value.items()
                if key != "private_selection_key_audit_only"}
    if isinstance(value, list):
        return [without_private_selection_key(item) for item in value]
    if isinstance(value, tuple):
        return tuple(without_private_selection_key(item) for item in value)
    return value
