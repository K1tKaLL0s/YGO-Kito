"""Bounded construction portfolios and source-bound candidate feedback.

Public axes propose packages, not effect semantics or quality labels. A paired
result belongs to an entire deck/plan; it never assigns credit to one card.
"""
from collections import Counter, defaultdict, deque
from itertools import combinations_with_replacement, islice, product
import json
from math import isfinite

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
    node_features = []
    for node in raw["nodes"]:
        tags = sorted(node["tags"], key=canonical_json)
        node_features.append({"tags": tags, "requirements": node["requirements"]}
                             if "requirements" in node else tags)
    return digest({"nodes": node_features,
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


def axis_ideas(task, assets, base, *, mechanism_groups=(), candidate_ids=None, edits=None):
    from .build_pipeline import EXTRA_TYPES, DeckEdits

    edits = edits if edits is not None else DeckEdits(task, assets, base)
    packages=[]
    for name, group in public_axis_groups(assets, task.pool if candidate_ids is None else candidate_ids):
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
            change = {z: {"added": incoming[z], "removed": list(old)} for z, old in zip(ZONES, removed)}
            if edits.rejection(change) is None:
                yield {"changes": change, "strategy": "axis:" + name, "proposal_basis": basis,
                       "proposal_source": source, "protected_package": {z: sorted(wanted[z].elements()) for z in ZONES}}
                found += 1
                if found == 2:
                    break


def portfolio(task, assets, *, base=None, initial=(), singles=(), feedback=(), require_edit=False,
              mechanism_groups=None, trace=None, graph=None, candidate_ids=None, edits=None, search_offset=0, rank_ideas=None, recognized_cards=()):
    """Choose edit ideas across search directions, then build only the chosen lists."""
    from .build_pipeline import DeckEdits, candidate_limit
    from .construction_inventory import repair_ideas

    buckets = defaultdict(deque)
    if base is not None and not require_edit:
        buckets["incumbent"].append({"deck": base, "strategy": "incumbent"})
    for deck in initial:
        buckets["fresh"].append({"deck": deck, "strategy": "fresh"})

    preference = evidence_order(feedback, task.sha256, "deck")
    if base is not None:
        edits = edits if edits is not None else DeckEdits(task, assets, base)
        if mechanism_groups is None:
            mechanism_groups = getattr(assets, "construction_mechanism_groups", ())
        if not isinstance(mechanism_groups, (list, tuple)):
            raise ContractError("bounded mechanism groups must be a sequence")
        for row in axis_ideas(task, assets, base, mechanism_groups=mechanism_groups,
                              candidate_ids=candidate_ids, edits=edits):
            buckets[row["strategy"]].append(row)
        buckets["dependency:inventory"].extend(repair_ideas(task, assets, base, graph=graph, edits=edits))
        for row in singles:
            buckets[row["strategy"]].append(row)

        before = digest(base.to_dict())
        for row in outcomes(feedback, task.sha256):
            if row["status"] != "preferred" or row["before"] != before or "package" not in row:
                continue
            try:
                if edits.rejection(row["package"]):
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            buckets["observed-package"].append({"changes": row["package"], "strategy": "observed-package",
                                                 "expected_deck_sha256": row["deck"]})

    families = {}
    for key, bucket in sorted(buckets.items()):
        if not bucket:
            continue
        if key.startswith("axis:"):
            names = ["axis"]
        elif key.startswith(("single:", "transfer:")):
            names = ["edit:" + z for z in bucket[0]["edited_zones"]]
        else:
            names = [key]
        for name in names:
            families.setdefault(name, []).append(key)

    # Rotate axes and the edited sections as the search advances. Keep an
    # incumbent available when a legal existing deck may still be the best.
    rotate = lambda items: items[search_offset % len(items):] + items[:search_offset % len(items)] if items else items
    if "axis" in families:
        families["axis"] = rotate(families["axis"])
    for zone in ZONES:
        name = "edit:" + zone
        if name in families:
            keys = families[name]
            if zone == "main":
                keys.sort(key=lambda key: (not key.startswith("transfer:"), key))
            families[name] = rotate(keys)
    directions = [name for name in ("dependency:inventory", "axis", *("edit:" + z for z in ZONES))
                  if name in families]
    turn = search_offset // candidate_limit(task) % max(1, len(directions))
    family_order = [name for name in ("incumbent", "observed-package", "fresh") if name in families]
    family_order.extend(directions[turn:] + directions[:turn])
    if recognized_cards:
        def lost_mechanisms(row):
            change = row["changes"]
            added = Counter(card for zone in ("main", "extra") for card in change[zone]["added"])
            removed = Counter(card for zone in ("main", "extra") for card in change[zone]["removed"])
            return sum(quantity for card, quantity in (removed - added).items() if card in recognized_cards)
        for key in buckets:
            if key.startswith(("axis:", "single:", "transfer:")):
                buckets[key] = deque(sorted(buckets[key], key=lost_mechanisms))
    ranked = []
    if rank_ideas is not None and edits is not None:
        # Score at most two edits per strategy and two strategies per direction.
        # Feedback replay and strictly improving repairs retain their priority.
        rankable = dict.fromkeys(key for name, keys in families.items()
                                 if name == "axis" or name.startswith("edit:")
                                 for key in keys[:2])
        ranked = [row for key in rankable for row in islice(buckets[key], 2)]
        if ranked:
            scores = rank_ideas([edits.inventory(row["changes"]) for row in ranked])
            if len(scores) != len(ranked) or any(not isfinite(score) for score in scores):
                raise ContractError("invalid model scores for edit ideas")
            for row, score in zip(ranked, scores):
                row["idea_model_score"] = score
            for key in rankable:
                buckets[key] = deque(sorted(buckets[key], key=lambda row: -row.get("idea_model_score", -float("inf"))))
            for name, keys in families.items():
                if name == "axis" or name.startswith("edit:"):
                    keys.sort(key=lambda key: -buckets[key][0].get("idea_model_score", -float("inf")))
    proposed = {key: len(rows) for key, rows in buckets.items() if rows}
    limit = candidate_limit(task)
    admitted = Counter()
    filtered = Counter()
    result, seen, rounds, materialized = [], set(), 0, 0
    while families and len(result) < limit and materialized < limit:
        rounds += 1
        for name in family_order:
            keys = families.get(name, [])
            while keys:
                key = keys.pop(0)
                if not buckets[key]:
                    continue
                row = buckets[key].popleft()
                if buckets[key]:
                    keys.append(key)
                deck = row.get("deck")
                change = row.get("changes")
                if edits is not None:
                    if change is None:
                        change = changes(base, deck)
                    identity = tuple(tuple(sorted(Counter(change[z]["added"]).items())) +
                                     (None,) + tuple(sorted(Counter(change[z]["removed"]).items())) for z in ZONES)
                    unchanged = all(not change[z]["added"] and not change[z]["removed"] for z in ZONES)
                else:
                    identity = deck
                    unchanged = False
                if identity in seen or (require_edit and unchanged):
                    filtered["duplicate_deck" if identity in seen else "unchanged_when_edit_required"] += 1
                    continue
                seen.add(identity)
                if deck is None:
                    deck = edits.materialize(change)
                    materialized += 1
                deck_sha = digest(deck.to_dict())
                if row.pop("expected_deck_sha256", deck_sha) != deck_sha:
                    filtered["observed_package_changed"] += 1
                    if materialized == limit:
                        break
                    continue
                assets.validate(task, deck)
                row.update(deck=deck, deck_sha256=deck_sha, changes=change, strength_status="unknown",
                           goal_preserved=True, portfolio_admission={"family": name, "round": rounds,
                           "basis": "generation_opportunity_not_quality"})
                result.append(row)
                admitted[name] += 1
                break
            if not keys:
                families.pop(name, None)
            if len(result) == limit or materialized == limit:
                break
    if trace is not None:
        trace.update(candidate_budget=limit, proposed_strategy_counts=proposed, family_order=family_order,
                     admitted_by_family=dict(admitted), rounds=rounds, filtered=dict(filtered),
                     materialized_edit_count=materialized, ranked_edit_ideas=len(ranked),
                     recognized_mechanism_cards=len(recognized_cards), remaining_ideas=sum(map(len, buckets.values())),
                     budget_order_is_quality_label=False)
    result.sort(key=lambda r: -preference.get(r["deck_sha256"], 0))
    return result


def task_checked(candidate):
    if not isinstance(candidate,dict):return False
    validation=candidate.get("validation",{})
    return (validation.get("status") in ("task_goal_verified_logic_unproven","list_constraints_verified_logic_unproven")
            and validation.get("best_deck")==candidate.get("deck"))
