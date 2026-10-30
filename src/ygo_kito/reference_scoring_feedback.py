"""Thin host seam: score feedback and low-score hint counter are independent
of the existing predicted-win-rate sampling thresholds and basic-CB gate.
"""
from .reference_scoring import public_result


def record_scoring_feedback(audit, tracker, *, evaluation_id, candidate_digest,
                            cycle_id, goal_id, period_id):
    """Call once after each completed construction, before duel admission.

    Persist the returned tracker state with the construction cycle. A replay
    with the same evaluation ID or cycle/candidate is harmless. An uncalibrated
    report requests optimization but is not invented as a numeric failed grade.
    The host owns optimization scheduling and the independently required CB.
    """
    if period_id == "2026-10":
        raise ValueError("2610 is autonomous; old reference threshold and hints are not applicable")
    score = public_result(audit)
    if audit.get("reference_score") is None or audit.get("threshold") is None:
        raise ValueError("reference feedback requires an explicitly configured reference comparison")
    if audit.get("evaluation_context") != {"goal_id": goal_id, "period_id": period_id}:
        raise ValueError("score evaluation is not bound to this goal and period")
    if abs(tracker.policy.reference_score - audit["reference_score"]) > 1e-9 or abs(
            tracker.policy.reference_score * tracker.policy.minimum_ratio - audit["threshold"]) > 1e-9:
        raise ValueError("score and hint policy thresholds must match")
    if audit["score"] is None:
        return {"score": score, "force_optimization": True,
                "optimization_reason": "construction_score_unavailable",
                "hint": None, "counted": False, "hint_state": tracker.to_dict()}
    event = tracker.evaluate(evaluation_id=evaluation_id, candidate_digest=candidate_digest,
                             cycle_id=cycle_id, goal_id=goal_id, period_id=period_id,
                             score=audit["score"])
    return {"score": score, "force_optimization": audit["force_optimization"],
            "optimization_reason": "construction_score_below_reference_ratio" if audit["force_optimization"] else None,
            "hint_event": event, "hint_state": tracker.to_dict()}
