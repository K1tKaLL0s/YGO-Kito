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


def axis_edits(task, assets, base, *, mechanism_groups=(), candidate_ids=None):
    from .build_pipeline import EXTRA_TYPES
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


def portfolio(task, assets, *, base=None, initial=(), singles=(), feedback=(), require_edit=False,mechanism_groups=None,trace=None,graph=None,candidate_ids=None):
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
        for row in axis_edits(task, assets, start,mechanism_groups=mechanism_groups,candidate_ids=candidate_ids):
            buckets[row["strategy"]].append(row)
    from .construction_inventory import repair_candidates
    for start in starts[:2]:
        # Proposal generation only: public dependency facts, original task and
        # ordinary portfolio budget. No reference deck or manual target list.
        # A strict improvement chain is generated within its own fixed budget.
        # Admit its endpoint before prefixes so portfolio truncation does not
        # systematically exclude the completed repair. Final ranking is still
        # performed by the original models and candidate layers.
        repairs = list(repair_candidates(task, assets, start, graph=graph))
        buckets['dependency:inventory'].extend(reversed(repairs))
    for deck in singles:
        zones = [z for z in ZONES if Counter(getattr(base,z)) != Counter(getattr(deck,z))]
        if not zones:continue
        same_inventory = Counter(base.main+base.extra+base.side)==Counter(deck.main+deck.extra+deck.side)
        strategy = ("single:" if len(zones)==1 else "transfer:" if same_inventory else "multi_zone:")+"+".join(zones)
        buckets[strategy].append({"deck": deck, "strategy": strategy,"edited_zones":zones,
            "proposal_basis":"atomic_cross_zone_inventory_exchange" if len(zones)>1 and same_inventory else
                "bounded_multi_zone_edit" if len(zones)>1 else "bounded_single_zone_substitution"})
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
    families = {}
    for key in sorted(buckets):
        if key.startswith("axis:"):
            names = ["axis_and_mechanism_packages"]
        elif key.startswith(("single:","transfer:","multi_zone:")):
            names = ["edit:"+z for z in ZONES if z in buckets[key][0]["edited_zones"]]
        else:names = [key]
        for name in names:families.setdefault(name,[]).append(key)
    # A catalog with many axes must not consume all slots before a playable
    # editing region is reached. Each family gets one admission per round;
    # strategies within it rotate too. This allocates search opportunity, not
    # a zone bonus in the learned score or the final retention order.
    family_order = [name for name in ("incumbent","observed-package","dependency:inventory","fresh","axis_and_mechanism_packages",
        *("edit:"+z for z in ZONES)) if name in families]
    generated_counts = {key:len(rows) for key,rows in buckets.items()}
    admitted = dict.fromkeys(family_order,0)
    result, seen, filtered, rounds = [], set(), Counter(), 0
    while families and len(result) < min(32, task.candidate_budget):
        rounds += 1
        for name in family_order:
            keys = families.get(name,[])
            while keys:
                key = keys.pop(0)
                if not buckets[key]:continue
                row = buckets[key].pop(0)
                if buckets[key]:keys.append(key)
                deck = row["deck"]; identity = digest(deck.to_dict())
                if identity in seen:
                    filtered["duplicate_deck"] += 1; continue
                if require_edit and deck == base:
                    filtered["unchanged_when_edit_required"] += 1; continue
                assets.validate(task, deck); seen.add(identity)
                row.update(deck_sha256=identity, changes=None if base is None else changes(base, deck),
                    strength_status="unknown", goal_preserved=True,
                    portfolio_admission={"family":name,"round":rounds,"basis":"generation_opportunity_not_quality"})
                result.append(row); admitted[name] += 1
                break
            if not keys:families.pop(name,None)
            if len(result) == min(32, task.candidate_budget):break
    if trace is not None:
        trace.update(candidate_budget=task.candidate_budget,generated_strategy_counts=generated_counts,
            family_order=family_order,admitted_by_family=admitted,rounds=rounds,filtered=dict(filtered),
            remaining_generated_rows=sum(map(len,buckets.values())),
            axis_internal_filter_trace="not_available",budget_order_is_quality_label=False)
    preference = evidence_order(feedback, task.sha256, "deck")
    result.sort(key=lambda r: -preference.get(r["deck_sha256"], 0))
    return result


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


def quality_selection_allowed(result, candidate):
    if (candidate.get('quality_evaluation') or {}).get('score', {}).get('unit') == 'functional_log2':
        from .construction_quality import compare_functional_quality
        from .construction_learning import _current_quality
        _current_quality(candidate['quality_evaluation'])
        for row in result.get('retained_candidates',()):
            if task_checked(row) and row.get('quality_evaluation'):
                _current_quality(row['quality_evaluation'])
        return not any(compare_functional_quality(candidate['quality_evaluation'], row['quality_evaluation'])['preferred'] == 'after'
            for row in result.get('retained_candidates', ()) if task_checked(row) and row.get('quality_evaluation'))
    return False


def select_retained(result, candidate, *, selection, assets=None):
    """Select an emitted optimizer option with its own construction pass."""
    from .construction_progress import FUNCTIONAL_GATE_VERSION, _quality_binding, resumable_optimizer_phase
    gate=candidate.get('construction_gate') or {}
    if gate.get('version') != FUNCTIONAL_GATE_VERSION:
        raise ContractError('retained candidate requires current functional quality reevaluation')
    if (gate.get('status')!='passed' or gate.get('deck_sha256')!=digest(candidate['deck'])):
        raise ContractError('retained candidate has not passed its own construction gate')
    task_sha=(result.get('continuation') or {}).get('task_sha256')
    if gate.get('task_sha256') != task_sha or (candidate.get('quality_evaluation') or {}).get('task_sha256') != task_sha:
        raise ContractError('retained gate belongs to another original task')
    if assets is None:
        raise ContractError('retained selection requires current assets for reevaluation checks')
    if _quality_binding(gate['policy'], candidate.get('quality_evaluation'), DeckParts.from_dict(candidate['deck'])) != gate['quality_binding']:
        raise ContractError('retained gate quality binding differs')
    if gate['policy'] != (result.get('continuation') or {}).get('quality_policy'):
        raise ContractError('retained gate belongs to another fixed policy')
    from .construction_layer_flow import functional_asset_version
    from .effect_mechanisms import MechanismCatalog
    if candidate['quality_evaluation']['asset_version'] != functional_asset_version(MechanismCatalog(assets)):
        raise ContractError('retained candidate assets require reevaluation')
    catalog = MechanismCatalog(assets)
    if any(e['record']['text_sha256'] != catalog.card(int(k.split(':')[1])).text_sha256
           for k,v in candidate['quality_evaluation'].get('coverage_details',{}).items() for e in v.get('effects',())):
        raise ContractError('retained candidate card facts require reevaluation')
    source=selection.get('source')
    allowed=('updated_model_with_quality_order','completed_frozen_portfolio_comparisons')
    if (source not in allowed or
            selection.get('candidate_deck_sha256') != digest(candidate['deck'])):
        raise ContractError('retained selection requires its actual selection source and inventory')
    if not quality_selection_allowed(result,candidate):
        raise ContractError('retained selection contradicts an established construction preference')
    if candidate["deck"] == result["best"]["deck"]:
        return deepcopy(result)
    if not any(r["deck"] == candidate["deck"] and task_checked(r) for r in result.get("retained_candidates", ())):
        raise ContractError("deployment candidate was not emitted and task checked by the optimizer")
    selected = deepcopy(result)
    selected.update(best=deepcopy(candidate), verified_best=deepcopy(candidate),
                    construction_candidate=deepcopy(candidate), basic_cb=deepcopy(candidate["basic_cb"]),
                    construction_gate=deepcopy(gate),
                    task_verified=True,cb_verified=bool(candidate.get("cb_verified")))
    continuation=selected.get('continuation')
    if continuation:
        continuation['candidate_version']+=1
        version=continuation['candidate_version']
        gate=deepcopy(gate);gate['candidate_version']=version
        continuation.update(candidate=deepcopy(candidate),gate=gate,status='passed')
        continuation['candidate']['deck_sha256']=digest(candidate['deck'])
        continuation['handoffs'].append(dict(role='build_optimizer',candidate_version=version,
            input_deck_sha256=digest(result['best']['deck']),output_deck_sha256=digest(candidate['deck'])))
        selected['handoffs']=deepcopy(continuation['handoffs']);selected['construction_gate']=gate
        for key in ('best','verified_best','construction_candidate'):
            selected[key].update(candidate_version=version,construction_gate=deepcopy(gate))
            selected[key]['basic_cb'].update(candidate_version=version,construction_gate=deepcopy(gate))
        selected['basic_cb']=deepcopy(selected['best']['basic_cb'])
    phase = selected["phases"][-1] if selected['phases'] else selected['continuation']['last_optimizer_phase']
    phase["portfolio_selection"] = {"source": source, "evidence":deepcopy(selection), "deck_sha256": digest(candidate["deck"]),
                                   "original_primary_deck_sha256": digest(phase["proposal_deck"])}
    phase["proposal_deck"] = deepcopy(candidate["deck"]);phase["accepted_deck"] = deepcopy(candidate["deck"])
    phase["proposal_changes"] = changes(DeckParts.from_dict(phase["input_deck"]),DeckParts.from_dict(candidate["deck"]))
    fill = phase["stage_3"];fill["best_deck"] = deepcopy(candidate["deck"])
    fill["selected_attempt_index"] = next(i for i,r in enumerate(fill["attempts"])
        if r.get("concrete_proposal",{}).get("deck") == candidate["deck"])
    if candidate.get("layer_evaluation") is not None:
        # A later fair comparison may select another optimizer output.
        # Its inventory/evidence must follow the selected list, while the
        # original layer decision remains available as provenance.
        chosen = candidate["candidate_index"]
        reason = {"rule":source, "candidate_index":chosen,
            "initial_layer_selection":deepcopy(fill.get("layer_selection")),
            "layer_comparison":deepcopy(candidate.get("layer_comparison"))}
        fill.update(layer_evaluation=deepcopy(candidate["layer_evaluation"]), layer_selection=reason)
        fill['quality_evaluation']=deepcopy(candidate['quality_evaluation'])
        phase['quality_evaluation']=deepcopy(candidate['quality_evaluation'])
        phase['gate']=deepcopy(gate)
        for name in ("best", "verified_best", "construction_candidate"):
            selected[name]["layer_selection"] = deepcopy(reason)
        trace = fill.get("candidate_trace")
        if trace is not None:
            trace.update(selected_candidate_index=chosen, selected_attempt_index=fill["selected_attempt_index"],
                selection_rule=source, selection_reason=deepcopy(reason))
            for row in trace["candidates"]:
                row["selected"] = row["candidate_index"] == chosen
                row["comparison_with_initial_selection"] = row.pop("comparison_with_selected", None)
                row["comparison_with_selected"] = next((deepcopy(p) for p in trace.get("layers", {}).get("pairs", [])
                    if {p["before"], p["after"]} == {row["candidate_index"], chosen}), None)
    if continuation:
        continuation['candidate']=deepcopy(selected['construction_candidate'])
        continuation['candidate']['deck_sha256']=digest(candidate['deck'])
        continuation['last_optimizer_phase']=resumable_optimizer_phase(phase)
    return selected
