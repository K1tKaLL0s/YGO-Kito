"""Natural candidates from supplied function facts, never labels or predictions."""
from dataclasses import dataclass, replace

from .contracts import (FactorContractError, FunctionSeed, StructureLink,
                        _functions, _modes, _ref_amounts, digest, text, unit)
from .functional_units import BranchConditions


@dataclass(frozen=True)
class CandidateBudget:
    rounds: int = 2
    branches_per_seed: int = 8
    checks: int = 65536
    candidates: int = 4096

    def __post_init__(self):
        for name, high in (("rounds", 8), ("branches_per_seed", 128), ("checks", 1000000), ("candidates", 16384)):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= high:
                raise FactorContractError("invalid candidate budget: " + name)


@dataclass(frozen=True)
class AxisCandidate:
    function_ref: str
    members: tuple[tuple[str, int], ...]
    functions: tuple[str, ...]
    conditions: tuple[BranchConditions, ...] = ()
    mode_choices: tuple[tuple[str, str], ...] = ()
    confidence: float = 1.0
    evidence_refs: tuple[str, ...] = ()
    parent_ids: tuple[str, ...] = ()
    used_links: tuple[str, ...] = ()

    def __post_init__(self):
        text(self.function_ref, "candidate function reference")
        _ref_amounts(self.members, "candidate members")
        _functions(self.functions)
        _modes(self.mode_choices)
        unit(self.confidence, "candidate fact confidence")
        if not isinstance(self.conditions, tuple) or any(not isinstance(v, BranchConditions) for v in self.conditions):
            raise FactorContractError("typed candidate branch conditions required")

    def logical_key(self):
        # Identity is used for association/deduplication, never as a feature.
        conditions = sorted((v.to_dict() for v in self.conditions), key=digest)
        return digest(dict(function_ref=self.function_ref, functions=sorted(self.functions),
                           members=sorted(self.members), conditions=conditions, modes=sorted(self.mode_choices)))

    @property
    def candidate_id(self):
        return ("axis:" if len(self.members) > 1 else "unit:") + self.logical_key()[:24]

    def to_dict(self):
        return dict(candidate_id=self.candidate_id, function_ref=self.function_ref,
                    members=[list(v) for v in self.members], functions=list(self.functions),
                    conditions=[v.to_dict() for v in self.conditions], mode_choices=[list(v) for v in self.mode_choices],
                    confidence=self.confidence, evidence_refs=list(self.evidence_refs), parent_ids=list(self.parent_ids))


@dataclass(frozen=True)
class CandidateSet:
    candidates: tuple[AxisCandidate, ...]
    units: tuple[AxisCandidate, ...]
    overflow: bool = False
    reasons: tuple[str, ...] = ()
    rounds_complete: int = 0
    explored_checks: int = 0

    def batches(self, size=32):
        if type(size) is not int or size < 1:
            raise FactorContractError("positive candidate query block size required")
        return tuple(self.candidates[i:i + size] for i in range(0, len(self.candidates), size))

    def to_dict(self):
        return dict(candidates=[v.to_dict() for v in self.candidates], units=[v.to_dict() for v in self.units],
                    overflow=self.overflow, reasons=list(self.reasons), rounds_complete=self.rounds_complete,
                    explored_checks=self.explored_checks, producer="natural_input_facts")


class _LimitReached(Exception):
    pass


class _Ledger:
    def __init__(self, budget):
        self.budget, self.count = budget, 0
        self.reasons = set()

    def tick(self):
        self.count += 1
        if self.count > self.budget.checks:
            self.reasons.add("candidate_check_budget")
            raise _LimitReached


def _merge_modes(left, right):
    result = dict(left)
    for scope, choice in right:
        if scope in result and result[scope] != choice:
            return None
        result[scope] = choice
    return tuple(sorted(result.items()))


def _link_key(link):
    return link.structural_key()


def _applies(candidate, link):
    return (link.function_ref in (None, candidate.function_ref) and
            (not link.functions or bool(set(link.functions) & set(candidate.functions))))


def _attach(candidate, link, other):
    modes = _merge_modes(candidate.mode_choices, link.mode_choices)
    if modes is None:
        return None
    members = dict(candidate.members)
    members[other] = max(members.get(other, 0), link.quantity)
    key = _link_key(link)
    conditions = candidate.conditions
    if link.condition is not None and key not in candidate.used_links:
        conditions += (link.condition,)
    return replace(candidate, members=tuple(sorted(members.items())), conditions=conditions,
                   mode_choices=modes, confidence=min(candidate.confidence, link.confidence),
                   evidence_refs=tuple(sorted(set(candidate.evidence_refs) | set(link.evidence_refs))),
                   used_links=tuple(sorted(set(candidate.used_links) | {key})))


def _close_required(candidate, required, ledger):
    queue = list(sorted(dict(candidate.members)))
    examined = set(candidate.used_links)
    while queue:
        owner = queue.pop()
        for link in required.get(owner, ()):
            ledger.tick()
            key = _link_key(link)
            if key in examined or not _applies(candidate, link):
                continue
            examined.add(key)
            attached = _attach(candidate, link, link.target)
            if attached is None:
                # A scope-specific dependency for another printed mode does not
                # apply. Unconditional dependencies should have no mode guard.
                continue
            new_member = link.target not in dict(candidate.members)
            candidate = attached
            if new_member:
                queue.append(link.target)
    return candidate


def _deduplicate(values):
    result = {}
    for value in values:
        key = value.logical_key()
        old = result.get(key)
        if old is None:
            result[key] = value
        else:
            result[key] = replace(old, confidence=max(old.confidence, value.confidence),
                evidence_refs=tuple(sorted(set(old.evidence_refs) | set(value.evidence_refs))),
                parent_ids=tuple(sorted(set(old.parent_ids) | set(value.parent_ids))),
                used_links=tuple(sorted(set(old.used_links) | set(value.used_links))))
    return tuple(result[k] for k in sorted(result))


def _shape(conditions):
    from .conditions import Condition
    known_resources = {"card", "member", "normal_summon", "lp", "counter", "material", "effect_mode"}
    def tree(node):
        if node is None:
            return None
        if isinstance(node, Condition):
            # Literal selectors are relation endpoints, not ranking features.
            return ("atom", node.resource_type if node.resource_type in known_resources else "other",
                    node.quantity, node.owner if node.owner in ("self", "opponent") else "other",
                    node.stage, node.consume_mode, node.deck_section, node.state_zone, node.until_stage)
        return (node.op, node.min_count, tuple(tree(v) for v in node.children))
    return tuple(sorted((digest((tree(v.structure), tree(v.state))) for v in conditions)))


def _rank(candidate, colors):
    return (-candidate.confidence, -len(candidate.functions),
            digest((sorted((colors.get(r, "unknown"), n) for r, n in candidate.members),
                    sorted(candidate.functions), _shape(candidate.conditions), len(candidate.mode_choices))))


def _take(values, limit, colors, ledger, *, soft_boundary):
    values = sorted(_deduplicate(values), key=lambda v: _rank(v, colors))
    if len(values) <= limit:
        return tuple(values)
    ledger.reasons.add("per_seed_beam" if soft_boundary else "candidate_count_budget")
    boundary = _rank(values[limit - 1], colors)
    # Keep the entire tied group at a soft beam boundary. At a hard global
    # bound omit the entire tied group, rather than select by opaque card ID.
    return tuple(v for v in values if _rank(v, colors) <= boundary) if soft_boundary else tuple(
        v for v in values if _rank(v, colors) < boundary)


def generate_axis_candidates(seeds, links, *, member_features=None, budget=CandidateBudget()):
    """Expand only supplied fact links. 32 is a query batch, never an axis cap.

    Hard check exhaustion discards an incomplete round transactionally, so
    iteration order cannot choose an arbitrary prefix of seeds.
    """
    if not isinstance(seeds, tuple) or any(not isinstance(v, FunctionSeed) for v in seeds):
        raise FactorContractError("immutable function seeds required")
    if not isinstance(links, tuple) or any(not isinstance(v, StructureLink) for v in links) or not isinstance(budget, CandidateBudget):
        raise FactorContractError("typed fact links and candidate budget required")
    features = {} if member_features is None else member_features
    refs = {r for s in seeds for r, _ in s.members} | {r for e in links for r in (e.source, e.target)}
    colors = {r: digest(features.get(r, ())) for r in refs}
    required, neighbors = {}, {}
    for link in links:
        if link.required:
            required.setdefault(link.source, []).append(link)
        elif link.kind in ("calls", "provides", "material", "recycles"):
            for ref in (link.source, link.target):
                neighbors.setdefault(ref, []).append(link)
    for _ in range(2):
        next_colors = {}
        for ref in refs:
            adjacent = tuple(neighbors.get(ref, ())) + tuple(required.get(ref, ()))
            signatures = [(e.kind, e.quantity, e.confidence, sorted(e.functions),
                           colors[e.target if e.source == ref else e.source], e.source == ref) for e in adjacent]
            next_colors[ref] = digest((colors[ref], sorted(signatures)))
        colors = next_colors
    ledger = _Ledger(budget)
    frontier, all_values, completed = {}, (), 0
    try:
        initial = []
        for seed in seeds:
            ledger.tick()
            if not seed.functions:
                continue
            value = _close_required(AxisCandidate(seed.function_ref, tuple(sorted(seed.members)), seed.functions,
                seed.conditions, seed.mode_choices, seed.confidence, seed.evidence_refs), required, ledger)
            initial.append(value)
        all_values = _take(initial, budget.candidates, colors, ledger, soft_boundary=False)
        frontier = {v.logical_key(): (v,) for v in all_values}
        for round_index in range(budget.rounds):
            next_frontier = {}
            additions = []
            for seed_key, values in frontier.items():
                expanded = []
                for candidate in values:
                    for member, _ in candidate.members:
                        for link in neighbors.get(member, ()):
                            ledger.tick()
                            if not _applies(candidate, link):
                                continue
                            other = link.target if link.source == member else link.source
                            if other in dict(candidate.members):
                                continue
                            value = _attach(candidate, link, other)
                            if value is not None:
                                value = _close_required(value, required, ledger)
                                parent = (candidate.candidate_id,) if len(candidate.members) > 1 else ()
                                expanded.append(replace(value, parent_ids=parent))
                chosen = _take(expanded, budget.branches_per_seed, colors, ledger, soft_boundary=True)
                next_frontier[seed_key] = chosen
                additions.extend(chosen)
            all_values = _take(all_values + tuple(additions), budget.candidates, colors, ledger, soft_boundary=False)
            frontier, completed = next_frontier, round_index + 1
    except _LimitReached:
        pass
    # Large parent candidates require a real link between exclusive members.
    # Sharing a bridge member alone never merges two candidate axes.
    unconditional = {}
    for axis in all_values:
        if len(axis.members) > 1 and not axis.conditions:
            members = dict(axis.members)
            for ref in members:
                unconditional.setdefault(ref, []).append((axis, members))
    try:
        parents = []
        for link in links:
            if link.required or link.condition is not None or link.kind not in ("provides", "calls", "material", "recycles"):
                continue
            for left, a in unconditional.get(link.source, ()):
                if link.target in a or not _applies(left, link):
                    continue
                for right, b in unconditional.get(link.target, ()):
                    ledger.tick()
                    if left.function_ref != right.function_ref or link.source in b:
                        continue
                    modes = _merge_modes(left.mode_choices, right.mode_choices)
                    modes = None if modes is None else _merge_modes(modes, link.mode_choices)
                    if modes is None:
                        continue
                    members = dict(a)
                    for ref, n in b.items():
                        members[ref] = max(members.get(ref, 0), n)
                    value = replace(left, members=tuple(sorted(members.items())), mode_choices=modes,
                        functions=tuple(sorted(set(left.functions) | set(right.functions))),
                        confidence=min(left.confidence, right.confidence, link.confidence),
                        evidence_refs=tuple(sorted(set(left.evidence_refs) | set(right.evidence_refs) | set(link.evidence_refs))),
                        parent_ids=tuple(sorted((left.candidate_id, right.candidate_id))))
                    parents.append(_close_required(value, required, ledger))
        all_values = _take(all_values + tuple(parents), budget.candidates, colors, ledger, soft_boundary=False)
    except _LimitReached:
        pass
    # Hard pruning may omit a parent; graph construction only emits edges to
    # present parents and preserves the original parent IDs as metadata.
    return CandidateSet(tuple(v for v in all_values if len(v.members) > 1),
                        tuple(v for v in all_values if len(v.members) == 1), bool(ledger.reasons),
                        tuple(sorted(ledger.reasons)), completed, ledger.count)
