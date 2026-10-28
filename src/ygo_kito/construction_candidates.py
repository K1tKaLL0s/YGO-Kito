"""Bounded construction portfolios and source-bound candidate feedback.

Public axes propose packages, not effect semantics or quality labels. A paired
result belongs to an entire deck/plan; it never assigns credit to one card.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from itertools import combinations_with_replacement, islice, product
import json

from .build_contracts import DeckParts, ZONES, digest
from .validation import ContractError, canonical_json

OUTCOME_KIND = "construction-paired-candidate-v1"
FILL_KIND = "construction-fill-observation-v1"


def _record_evidence(session, source, row, evidence_sha256):
    message=canonical_json(row)
    if len(message)>1024:raise ContractError("bounded construction feedback exceeded its message budget")
    session.record_feedback(source,message)
    session.history.append({"stage":"construction_evidence","goal_sha256":session.goal_sha256,
        "task_sha256":session.task.sha256,"message_sha256":digest(message),"evidence_sha256":evidence_sha256})


def attributed_feedback(session):
    """Free-form or RPC-supplied messages cannot impersonate measured evidence."""
    anchors={h["message_sha256"] for h in session.history if h.get("stage")=="construction_evidence"
             and h.get("task_sha256")==session.task.sha256 and h.get("goal_sha256")==session.goal_sha256}
    return [f for f in session.feedback if digest(f["message"]) in anchors]


def graph_signature(graph):
    """Exclude revision, ancestry, node names and display notes from identity."""
    raw = graph.to_dict() if hasattr(graph, "to_dict") else graph
    nodes = {n["node_id"]: i for i, n in enumerate(raw["nodes"])}
    return digest({"nodes": [sorted(n["tags"], key=canonical_json) for n in raw["nodes"]],
        "edges": sorted((nodes[e["source"]], nodes[e["target"]], e["kind"]) for e in raw["connectors"]),
        "entries": sorted(nodes[n] for n in raw["entry_nodes"]),
        "goals": sorted(nodes[n] for n in raw["goal_nodes"])})


def public_axis_groups(assets, ids):
    groups = defaultdict(list)
    for code in sorted(ids):
        packed = assets.rows[code]["setcode"] % (1 << 64)
        for value in {(packed >> shift) & 0xfff for shift in range(0, 64, 16)} - {0}:
            groups[value].append(code)
    return [("setcode-" + format(value, "x"), tuple(cards))
            for value, cards in sorted(groups.items()) if len(cards) >= 2]


def changes(before, after):
    return {z: {"added": sorted((Counter(getattr(after, z))-Counter(getattr(before, z))).elements()),
                "removed": sorted((Counter(getattr(before, z))-Counter(getattr(after, z))).elements())}
            for z in ZONES}


def outcomes(feedback, task_sha256):
    result = []
    for item in feedback:
        if item.get("source") != "duel":
            continue
        try:
            row = json.loads(item["message"])
        except (ValueError, TypeError, KeyError):
            continue
        if (not isinstance(row, dict) or row.get("kind") != OUTCOME_KIND or
                row.get("task") != task_sha256 or row.get("status") not in ("preferred", "other", "unknown")):
            continue
        if any(not isinstance(row.get(k), str) or len(row[k]) != 64 for k in ("comparison", "deck", "graph", "before")):
            continue
        if row not in result:
            result.append(row)
    return result


def evidence_order(feedback, task_sha256, key):
    rows = outcomes(feedback, task_sha256)
    positive = {r[key] for r in rows if r["status"] == "preferred"}
    negative = {r[key] for r in rows if r["status"] == "other"}
    # Conflicting comparisons and inconclusive results remain unranked.
    return {value: 1 for value in positive-negative} | {value: -1 for value in negative-positive}


def record_fill_observation(session, proposal, result):
    rejected = result["status"] in ("hard_constraint_failure", "theme_axis_not_satisfied",
        "text_review_unsatisfied", "text_evidence_mismatch")
    row = {"kind": FILL_KIND, "task": session.task.sha256, "deck": digest(proposal.deck.to_dict()),
           "graph": graph_signature(session.logic), "status": "rejected_binding" if rejected else "unknown",
           "reason": result["status"], "goal_impossible": False}
    _record_evidence(session,"fill",row,digest(result))


def rejected_binding(feedback, task_sha256, graph):
    signature = graph_signature(graph)
    for item in feedback:
        if item.get("source") != "fill":continue
        try:row = json.loads(item["message"])
        except (ValueError, TypeError, KeyError):continue
        if (isinstance(row,dict) and row.get("kind")==FILL_KIND and row.get("task")==task_sha256
                and row.get("graph")==signature and row.get("status")=="rejected_binding"
                and row.get("goal_impossible") is False):return True
    return False


def record_comparison(session, assets, comparison, contexts, *, auxiliary=None):
    """Accept the existing validated paired evidence, preserving null labels."""
    from .model_build_feedback import validate_model_comparison
    decks = validate_model_comparison(session.task, assets, comparison)
    if len(contexts) != len(decks):
        raise ContractError("each measured candidate needs its exact construction context")
    for deck, context in zip(decks, contexts):
        if context["deck"] != deck.to_dict():
            raise ContractError("paired outcome must bind its exact constructed deck")
        graph_signature(context["logic"])
    preferred = comparison["preferred_index"]
    evidence_sha = comparison["comparison_sha256"]
    if auxiliary is not None:
        from .model_auxiliary import validate_auxiliary_comparison
        validate_auxiliary_comparison(session.task, assets, auxiliary)
        if auxiliary["original_win_comparison"] != comparison:
            raise ContractError("auxiliary feedback belongs to other paired games")
        if preferred is None:
            preferred, evidence_sha = auxiliary["preferred_index"], auxiliary["auxiliary_sha256"]
    before = digest(decks[0].to_dict())
    for index, (deck, context) in enumerate(zip(decks, contexts)):
        row = {"kind": OUTCOME_KIND, "task": session.task.sha256, "comparison": evidence_sha,
               "before": before, "deck": digest(deck.to_dict()), "graph": graph_signature(context["logic"]),
               "status": "unknown" if preferred is None else "preferred" if index == preferred else "other"}
        package = changes(decks[0], deck)
        if sum(len(v["added"]) for v in package.values()) <= 6:
            row["package"] = package
        message = canonical_json(row)
        if not any(f.get("source") == "duel" and f.get("message") == message for f in session.feedback):
            _record_evidence(session,"duel",row,evidence_sha)
    return {"comparison_sha256": evidence_sha, "preferred_index": preferred,
            "attribution": "whole_candidate_not_individual_cards", "graph_quality_label": False}


def _removals(task, assets, base, zone, amount, *, protected=None):
    required = {r["card_id"]: r["minimum"] for r in task.requirements if r["zone"] == zone}
    counts = Counter(getattr(base, zone))
    for code, quantity in (protected or {}).items():
        required[code]=max(required.get(code,0),min(quantity,counts[code]))
    available = {c: n-required.get(c, 0) for c, n in counts.items() if n > required.get(c, 0)}
    # Interleave both ends, so a low-ID prefix cannot consume the whole budget.
    ids = sorted(available)
    ordered = [ids[i//2] if i % 2 == 0 else ids[-1-i//2] for i in range(len(ids))]
    result = []
    for selected in islice(combinations_with_replacement(ordered, amount), 256):
        if all(n <= available[c] for c, n in Counter(selected).items()):
            result.append(selected)
        if len(result) == 12:
            break
    return result


def axis_edits(task, assets, base, *, mechanism_groups=()):
    from .build_pipeline import EXTRA_TYPES
    packages=[]
    for name, group in public_axis_groups(assets, task.pool):
        incoming = {z: [] for z in ZONES}
        for zone in ("main", "extra"):
            cards = [c for c in group if bool(assets.rows[c]["type"] & EXTRA_TYPES) == (zone == "extra")
                     and c not in getattr(base, zone)]
            incoming[zone] = cards[:(2 if zone == "main" else 1)] if task.sizes[zone] else []
        wanted={z:Counter(c for c in getattr(base,z) if c in group)+Counter(incoming[z]) for z in ZONES}
        packages.append((name,incoming,wanted,"shared_public_setcode_not_effect_or_strength_proof","public_catalog_setcode"))
    # Optional integration seam for the separate effect/semantics owner. Each
    # sourced mechanism supplies its entire zone-specific package, including
    # quantities; this editor never invents its effects or card identities.
    for group in mechanism_groups[:8]:
        if (not isinstance(group,dict) or set(group)!={"group_id","zones","source"} or
                not isinstance(group["group_id"],str) or not group["group_id"] or
                not isinstance(group["source"],str) or not group["source"] or
                not isinstance(group["zones"],dict) or set(group["zones"])!=set(ZONES)):
            raise ContractError("sourced mechanism group_id/zones/source required")
        wanted={z:Counter(group["zones"][z]) for z in ZONES}
        if (sum(sum(c.values()) for c in wanted.values())>6 or
                any(type(code) is not int or code not in task.pool or n>3 for c in wanted.values() for code,n in c.items())):
            raise ContractError("mechanism package exceeds the task pool/copy/edit bounds")
        incoming={z:sorted((wanted[z]-Counter(getattr(base,z))).elements()) for z in ZONES}
        packages.append(("mechanism:"+group["group_id"],incoming,wanted,"host_sourced_mechanism_not_strength_proof",group["source"]))
    for name,incoming,wanted,basis,source in packages:
        # A package has at least two linked identities. Across-zone packages
        # are constructed together; illegal intermediate single swaps are OK.
        if not sum(map(len,incoming.values())) or len(set().union(*(set(c) for c in wanted.values())))<2:
            continue
        options = [_removals(task, assets, base, z, len(incoming[z]),protected=wanted[z]) if incoming[z] else [()] for z in ZONES]
        found = 0
        for removed in islice(product(*options), 256):
            parts = base.to_dict()
            for z, old in zip(ZONES, removed):
                for code in old:
                    parts[z].remove(code)
                parts[z].extend(incoming[z]); parts[z].sort()
            deck = DeckParts.from_dict(parts)
            if (all(Counter(getattr(deck,z))[code]>=n for z in ZONES for code,n in wanted[z].items())
                    and assets.accepts(task, deck)):
                yield {"deck": deck, "strategy": "axis:" + name,"proposal_basis":basis,"proposal_source":source,
                       "protected_package":{z:sorted(wanted[z].elements()) for z in ZONES}}
                found += 1
                if found == 2:
                    break


def portfolio(task, assets, *, base=None, initial=(), singles=(), feedback=(), require_edit=False,mechanism_groups=None):
    """Keep distinct generation families before truncation or learned scoring."""
    buckets = defaultdict(list)
    if base is not None and not require_edit:
        buckets["incumbent"].append({"deck": base, "strategy": "incumbent"})
    for deck in initial:
        buckets["fresh"].append({"deck": deck, "strategy": "fresh"})
    starts = [base] if base is not None else list(initial[:2])
    if mechanism_groups is None:mechanism_groups=getattr(assets,"construction_mechanism_groups",())
    if not isinstance(mechanism_groups,(list,tuple)):raise ContractError("bounded mechanism groups must be a sequence")
    for start in starts:
        for row in axis_edits(task, assets, start,mechanism_groups=mechanism_groups):
            buckets[row["strategy"]].append(row)
    for deck in singles:
        zone = next((z for z in ZONES if getattr(base, z) != getattr(deck, z)), "main")
        buckets["single:" + zone].append({"deck": deck, "strategy": "single:" + zone})
    # Replay an observed whole edit only in the exact original context. This
    # proposes a candidate; it is not a transferable per-card value estimate.
    if base is not None:
        for row in outcomes(feedback, task.sha256):
            if row["status"] != "preferred" or row["before"] != digest(base.to_dict()) or "package" not in row:
                continue
            parts = base.to_dict()
            try:
                for z in ZONES:
                    for code in row["package"][z]["removed"]:
                        parts[z].remove(code)
                    parts[z].extend(row["package"][z]["added"]); parts[z].sort()
                deck = DeckParts.from_dict(parts)
            except (KeyError, TypeError, ValueError, ContractError):
                continue
            if digest(deck.to_dict()) == row["deck"] and assets.accepts(task, deck):
                buckets["observed-package"].append({"deck": deck, "strategy": "observed-package"})
    keys = list(buckets)
    # Small budgets still reserve space for a group and each playable region.
    keys.sort(key=lambda k: (0 if k == "incumbent" else 1 if k == "observed-package" else
                             2 if k.startswith("axis:") else 3 if k.startswith("single:") else 4, k))
    result, seen = [], set()
    while keys and len(result) < min(32, task.candidate_budget):
        for key in keys[:]:
            if not buckets[key]:
                keys.remove(key); continue
            row = buckets[key].pop(0); deck = row["deck"]; identity = digest(deck.to_dict())
            if identity in seen or require_edit and deck == base:
                continue
            assets.validate(task, deck); seen.add(identity)
            row.update(deck_sha256=identity, changes=None if base is None else changes(base, deck),
                       strength_status="unknown", goal_preserved=True)
            result.append(row)
            if len(result) == min(32, task.candidate_budget):
                break
    preference = evidence_order(feedback, task.sha256, "deck")
    result.sort(key=lambda r: -preference.get(r["deck_sha256"], 0))
    return result


def retained_order(rows, scores, feedback, task_sha256, *, limit=3):
    """Neural ranking inside a bounded, strategy-diverse survivor set."""
    preference = evidence_order(feedback, task_sha256, "deck")
    ranked = sorted(range(len(rows)), key=lambda i: (-preference.get(rows[i]["deck_sha256"], 0), -scores[i], i))
    selected, strategies = [], set()
    # Keep the highest ranked proposal, then reserve alternatives by strategy.
    for i in ranked:
        if not selected or rows[i]["strategy"] not in strategies:
            selected.append(i); strategies.add(rows[i]["strategy"])
        if len(selected) >= limit:
            break
    selected.extend(i for i in ranked if i not in selected)
    return selected


def task_checked(candidate):
    if not isinstance(candidate,dict):return False
    validation=candidate.get("validation",{})
    return (validation.get("status") in ("task_goal_verified_logic_unproven","list_constraints_verified_logic_unproven")
            and validation.get("best_deck")==candidate.get("deck"))


def comparable_candidates(result, incumbent, *, limit=3):
    """Task-checked candidates can be compared while their basic CB is unknown."""
    rows = [deepcopy(incumbent), deepcopy(result["best"])]
    rows.extend(deepcopy(r) for r in result.get("retained_candidates", ()) if task_checked(r))
    unique = {}
    # Keep the primary proposal and an incumbent; spend the remaining place on
    # a group strategy before a duplicate single-card variation.
    alternatives = sorted(rows[2:], key=lambda r: (not r.get("strategy", "").startswith("axis:"), r.get("strategy", "")))
    for row in rows[:2] + alternatives:
        if not task_checked(row):continue
        unique.setdefault(digest(row["deck"]), row)
        if len(unique) == limit:
            break
    return list(unique.values())


def strict_portfolio_winner(size, pairs):
    wins = {i: set() for i in range(size)}
    for a, b, preferred in pairs:
        if preferred is not None:
            winner, loser = (a, b) if preferred == 0 else (b, a)
            wins[winner].add(loser)
    return next((i for i in range(size) if len(wins[i]) == size-1), None)


def select_retained(result, candidate):
    """Select an already emitted fourth-role option, preserving its provenance."""
    if candidate["deck"] == result["best"]["deck"]:
        return deepcopy(result)
    if not any(r["deck"] == candidate["deck"] and task_checked(r) for r in result.get("retained_candidates", ())):
        raise ContractError("deployment candidate was not emitted and task checked by the fourth role")
    selected = deepcopy(result)
    selected.update(best=deepcopy(candidate), verified_best=deepcopy(candidate),
                    construction_candidate=deepcopy(candidate), basic_cb=deepcopy(candidate["basic_cb"]),
                    task_verified=True,cb_verified=bool(candidate.get("cb_verified")))
    phase = selected["phases"][-1]
    phase["portfolio_selection"] = {"source": "completed_fair_comparison", "deck_sha256": digest(candidate["deck"]),
                                   "original_primary_deck_sha256": digest(phase["proposal_deck"])}
    phase["proposal_deck"] = deepcopy(candidate["deck"]);phase["accepted_deck"] = deepcopy(candidate["deck"])
    phase["proposal_changes"] = changes(DeckParts.from_dict(phase["input_deck"]),DeckParts.from_dict(candidate["deck"]))
    fill = phase["stage_3"];fill["best_deck"] = deepcopy(candidate["deck"])
    fill["selected_attempt_index"] = next(i for i,r in enumerate(fill["attempts"])
        if r.get("concrete_proposal",{}).get("deck") == candidate["deck"])
    return selected
