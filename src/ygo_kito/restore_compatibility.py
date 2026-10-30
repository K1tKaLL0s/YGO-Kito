"""Structural compatibility for restoring an existing course checkpoint.

Source-file bytes remain audit evidence, not a restore gate.  A checkpoint is
compatible when its course definition, model architecture/resources and
restore-required data agree.  Added modules, unrelated edits and line-ending
changes are reported as drift; they do not force a new migration.  A real
structural change (task, period resources, rules, vocabulary, model layout,
opponents or config) still fails closed.
"""
from copy import deepcopy

# These are content identities of the implementation tree, not of the course
# definition.  They are retained for audit, but are not a restore condition.
AUDIT_ONLY_COURSE_KEYS = ("source_map",)
AUDIT_ONLY_MODEL_KEYS = ("source_files",)


def _structural(value, ignored):
    if not isinstance(value, dict):
        return deepcopy(value)
    return {key: deepcopy(item) for key, item in value.items() if key not in ignored}


def structural_course_binding(binding):
    """Course binding without implementation-file byte maps."""
    result = _structural(binding, AUDIT_ONLY_COURSE_KEYS)
    if isinstance(result.get("models"), dict):
        result["models"] = _structural(result["models"], AUDIT_ONLY_MODEL_KEYS)
    return result


def structural_models_binding(binding):
    return _structural(binding, AUDIT_ONLY_MODEL_KEYS)


def course_binding_compatibility(saved, current):
    """Return ``{compatible, reasons, ignored}`` for a saved course binding.

    ``reasons`` names the structural domains that actually differ, so a failed
    restore reports what changed instead of a generic stale-checkpoint error.
    """
    left = structural_course_binding(saved)
    right = structural_course_binding(current)
    if left == right:
        return {"compatible": True, "reasons": [], "ignored": list(AUDIT_ONLY_COURSE_KEYS)}
    reasons = []
    for key in sorted(set(left) | set(right)):
        if left.get(key) != right.get(key):
            reasons.append("binding." + key)
    return {"compatible": False, "reasons": reasons, "ignored": list(AUDIT_ONLY_COURSE_KEYS)}


def models_binding_compatibility(saved, current):
    left = structural_models_binding(saved)
    right = structural_models_binding(current)
    if left == right:
        return {"compatible": True, "reasons": [], "ignored": list(AUDIT_ONLY_MODEL_KEYS)}
    reasons = []
    for key in sorted(set(left) | set(right)):
        if left.get(key) != right.get(key):
            reasons.append("models.binding." + key)
    return {"compatible": False, "reasons": reasons, "ignored": list(AUDIT_ONLY_MODEL_KEYS)}


def source_drift(saved_map, current_map):
    """Changed/added/removed implementation files, reported without gating."""
    saved_map = saved_map if isinstance(saved_map, dict) else {}
    current_map = current_map if isinstance(current_map, dict) else {}
    changed = sorted(key for key in set(saved_map) & set(current_map)
                     if saved_map[key] != current_map[key])
    return {"changed": changed,
            "added": sorted(set(current_map) - set(saved_map)),
            "removed": sorted(set(saved_map) - set(current_map))}
