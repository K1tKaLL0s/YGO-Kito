"""Explicit first-layer axis statistics; no search, execution or model scoring.

The host supplies the original task, selected coarse logic and source-backed
role judgments. Function IDs denote that task's *specific* functions, including
zone, reason and selection method where relevant. No card-name recipes are
inferred. Explicit composition/portfolio adapters at the end call layer two.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from types import MappingProxyType

from .build_contracts import BuildTask, DeckParts, ZONES
from .construction_logic import ConstructionLogic
from .validation import ContractError, integer, member, text

EVALUATION_VERSION = "construction-layer-evaluation-v1"
AXIS_ZONES = ("main", "extra")


def _tuple_of(value, kind, label):
    if not isinstance(value, tuple) or any(not isinstance(item, kind) for item in value):
        raise ContractError(f"{label} requires a tuple of {kind.__name__}")


def _texts(value, label):
    _tuple_of(value, str, label)
    for item in value:
        text(item, label)


@dataclass(frozen=True, order=True)
class CardCopy:
    """Stable inventory reference, numbered within (zone, card ID), not a game entity."""

    zone: str
    card_id: int
    copy_index: int = 1

    def __post_init__(self):
        member(self.zone, "copy zone", ZONES)
        integer(self.card_id, "card ID", 1, 2**32 - 1)
        integer(self.copy_index, "copy index", 1, 3)


@dataclass(frozen=True)
class AxisModule:
    module_id: str
    purpose: str
    cards: tuple[CardCopy, ...] = ()
    required_zones: tuple[str, ...] = ("main",)
    selected: bool = True

    def __post_init__(self):
        text(self.module_id, "module ID")
        text(self.purpose, "module purpose")
        _tuple_of(self.cards, CardCopy, "module cards")
        if len(set(self.cards)) != len(self.cards) or any(c.zone == "side" for c in self.cards):
            raise ContractError("module cards must be distinct main/extra inventory references")
        _texts(self.required_zones, "required zones")
        for zone in self.required_zones:
            member(zone, "required zone", AXIS_ZONES)
        if len(set(self.required_zones)) != len(self.required_zones):
            raise ContractError("duplicate required zone")
        if type(self.selected) is not bool or (not self.selected and self.cards):
            raise ContractError("unselected modules cannot allocate cards")


@dataclass(frozen=True)
class SkeletonSpec:
    inventory: DeckParts
    modules: tuple[AxisModule, ...]
    unassigned_purposes: dict[CardCopy, str] = field(default_factory=dict)
    vacancy_purposes: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.inventory, DeckParts):
            raise ContractError("skeleton requires DeckParts inventory")
        _tuple_of(self.modules, AxisModule, "modules")
        if len({m.module_id for m in self.modules}) != len(self.modules):
            raise ContractError("duplicate module ID")
        available = set(self.copies())
        allocated = {c for m in self.modules for c in m.cards}
        if not allocated <= available:
            raise ContractError("module references absent inventory copies")
        if not isinstance(self.unassigned_purposes, (dict, MappingProxyType)):
            raise ContractError("unassigned purposes must map inventory references to text")
        for card, purpose in self.unassigned_purposes.items():
            if not isinstance(card, CardCopy) or card not in available - allocated:
                raise ContractError("unassigned purpose references an absent or allocated copy")
            text(purpose, "unassigned purpose")
        if not isinstance(self.vacancy_purposes, (dict, MappingProxyType)):
            raise ContractError("vacancy purposes must map zones to text")
        for zone, purpose in self.vacancy_purposes.items():
            member(zone, "vacancy zone", ZONES)
            text(purpose, "vacancy purpose")
        object.__setattr__(self, "unassigned_purposes", MappingProxyType(dict(self.unassigned_purposes)))
        object.__setattr__(self, "vacancy_purposes", MappingProxyType(dict(self.vacancy_purposes)))

    def copies(self):
        return tuple(CardCopy(zone, code, index)
                     for zone in ZONES
                     for code, count in sorted(Counter(getattr(self.inventory, zone)).items())
                     for index in range(1, count + 1))


@dataclass(frozen=True)
class FunctionRequirement:
    """One task-specific function; alternative cards share its ID, inputs do not.

    Empty module_ids means all selected modules. A supplied input has a source
    explanation and contributes no card investment. Targeted tools use 'target'
    mode: coverage and K, without an independent-entry density.
    """

    function_id: str
    zone: str
    source: str
    node_ids: tuple[str, ...]
    module_ids: tuple[str, ...] = ()
    required: bool = True
    mode: str = "investment"
    given_input: str | None = None

    def __post_init__(self):
        for value, label in ((self.function_id, "function ID"), (self.source, "requirement source")):
            text(value, label)
        member(self.zone, "function zone", AXIS_ZONES)
        member(self.mode, "function mode", ("investment", "target"))
        for values in (self.node_ids, self.module_ids):
            _texts(values, "function references")
            if len(set(values)) != len(values):
                raise ContractError("duplicate function reference")
        if not self.node_ids or type(self.required) is not bool:
            raise ContractError("function requires coarse-logic nodes and a boolean required flag")
        if self.given_input is not None:
            text(self.given_input, "given input source/explanation")


@dataclass(frozen=True)
class FunctionEvidence:
    function_id: str
    status: str
    source: str
    conditions: tuple[str, ...] = ()
    effect_refs: tuple[str, ...] = ()
    per_resolution: int | None = None

    def __post_init__(self):
        text(self.function_id, "evidence function")
        member(self.status, "function evidence", ("covered", "missing", "unknown"))
        text(self.source, "function evidence source")
        _texts(self.conditions, "conditions")
        _texts(self.effect_refs, "effect references")
        if self.per_resolution is not None:
            integer(self.per_resolution, "per-resolution quantity", 1)


@dataclass(frozen=True)
class RoleAssessment:
    module_id: str
    zone: str
    card_id: int
    q: float | None
    source: str
    functions: tuple[FunctionEvidence, ...] = ()
    note: str = ""

    def __post_init__(self):
        text(self.module_id, "assessment module")
        member(self.zone, "assessment zone", AXIS_ZONES)
        integer(self.card_id, "assessed card", 1, 2**32 - 1)
        if self.q is not None and (type(self.q) not in (int, float) or self.q not in (0, .5, 1)):
            raise ContractError("q must be 0, 0.5, 1 or None for unknown")
        text(self.source, "role source")
        text(self.note, "role note", empty=True)
        _tuple_of(self.functions, FunctionEvidence, "function evidence")
        if self.q != 1 and any(f.status == "covered" for f in self.functions):
            raise ContractError("only q=1 may provide positive function coverage")
        if self.q == 0 and any(f.status != "missing" for f in self.functions):
            raise ContractError("explicitly mismatched roles cannot supply uncertain functions")
        statuses = defaultdict(set)
        for evidence in self.functions:
            statuses[evidence.function_id].add(evidence.status)
        if any("missing" in values and len(values) > 1 for values in statuses.values()):
            raise ContractError("contradictory evidence for one function")


@dataclass(frozen=True)
class LayerContext:
    task: BuildTask
    logic: ConstructionLogic
    requirements: tuple[FunctionRequirement, ...]
    assessments: tuple[RoleAssessment, ...] = ()
    same_name_groups: tuple[tuple[int, ...], ...] = ()
    relations: object | None = None

    def __post_init__(self):
        if not isinstance(self.task, BuildTask) or not isinstance(self.logic, ConstructionLogic):
            raise ContractError("layer context requires the original BuildTask and selected ConstructionLogic")
        _tuple_of(self.requirements, FunctionRequirement, "requirements")
        _tuple_of(self.assessments, RoleAssessment, "role assessments")
        if self.relations is not None:
            from .construction_relations import RelationContext
            if not isinstance(self.relations, RelationContext):
                raise ContractError("relations must be an explicit RelationContext")
            codes = set(self.relations.catalog_cards)
            codes.update(f.card_id for f in self.relations.facts if f.card_id is not None)
            codes.update(code for p in self.relations.pools for _, code in p.inventory)
            codes.update(code for p in self.relations.probabilities for code in p.cards)
            if not codes <= set(self.task.pool):
                raise ContractError("relations reference cards outside original task pool")
        if len({r.function_id for r in self.requirements}) != len(self.requirements):
            raise ContractError("duplicate function requirement")
        nodes = {node.node_id for node in self.logic.nodes}
        if any(not set(r.node_ids) <= nodes for r in self.requirements):
            raise ContractError("function references an absent coarse-logic node")
        keys = [(a.module_id, a.zone, a.card_id) for a in self.assessments]
        if len(set(keys)) != len(keys):
            raise ContractError("duplicate role assessment")
        _tuple_of(self.same_name_groups, tuple, "same-name groups")
        seen = set()
        for group in self.same_name_groups:
            if len(group) < 2:
                raise ContractError("same-name groups require at least two card IDs")
            for code in group:
                integer(code, "same-name card ID", 1, 2**32 - 1)
                if code in seen or code not in self.task.pool:
                    raise ContractError("overlapping or out-of-pool same-name groups")
                seen.add(code)
        # Keep the original goal and budgets detached from caller-owned dicts.
        object.__setattr__(self, "task", BuildTask.from_dict(self.task.to_dict()))


def _inventory(skeleton, context):
    """Validate references; allocated slots share one partition discount ledger."""
    copies = skeleton.copies()
    names = {code: min(group) for group in context.same_name_groups for code in group}
    counts = Counter(names.get(c.card_id, c.card_id) for c in copies)
    if any(n > 3 for n in counts.values()):
        raise ContractError("same-name inventory exceeds three across main/extra/side")
    if any(c.card_id not in context.task.pool for c in copies):
        raise ContractError("inventory card outside original task pool")
    for zone in ZONES:
        if len(getattr(skeleton.inventory, zone)) > context.task.sizes[zone]:
            raise ContractError("inventory exceeds original task section size")
    modules = {m.module_id: m for m in skeleton.modules}
    requirements = {r.function_id: r for r in context.requirements}
    if any(not set(r.module_ids) <= modules.keys() for r in context.requirements):
        raise ContractError("requirement references an absent module")
    for assessment in context.assessments:
        module = modules.get(assessment.module_id)
        if module is None or not any((c.zone, c.card_id) == (assessment.zone, assessment.card_id)
                                     for c in module.cards):
            raise ContractError("assessment does not refer to this candidate's module inventory")
        for evidence in assessment.functions:
            req = requirements.get(evidence.function_id)
            if (req is None or req.zone != assessment.zone
                    or (req.module_ids and assessment.module_id not in req.module_ids)):
                raise ContractError("evidence references an absent or out-of-scope function")
    allocated = {c for module in skeleton.modules for c in module.cards}
    return copies, _discount_weights(allocated, names), names


def _discount_weights(copies, names):
    ranks = Counter()
    weights = {}
    for card in sorted(copies):
        key = (card.zone, names.get(card.card_id, card.card_id))
        ranks[key] += 1
        # Tenths avoid cumulative floating-point error. All module views share
        # this ledger; only copies in the evaluated scope consume its discount.
        weights[card] = 10 if ranks[key] == 1 else (9 if card.zone == "main" else 8)
    return weights


def _function_copies(req, modules, assessments):
    scoped = [m for m in modules if not req.module_ids or m.module_id in req.module_ids]
    supported, unknown, evidence_rows = set(), set(), set()
    for module in scoped:
        for card in module.cards:
            if card.zone != req.zone:
                continue
            role = assessments.get((module.module_id, card.zone, card.card_id))
            evidence = [e for e in role.functions if e.function_id == req.function_id] if role else []
            if role and role.q == 1 and any(e.status == "covered" for e in evidence):
                supported.add(card)
            elif any(e.status == "unknown" for e in evidence) or (
                    not evidence and (role is None or role.q is None)):
                unknown.add(card)
            evidence_rows.update(evidence)
    return scoped, supported, unknown - supported, evidence_rows


def _best_q(values):
    # The overview asks whether this physical slot supports ANY selected module.
    # q=1 settles that question; an unresolved alternative to q<1 stays unknown.
    if 1 in values:
        return 1
    if None in values:
        return None
    return max(values)


def _ratio(cards, q_by_copy, weights=None, *, applicable=True):
    unknown = [c for c in cards if q_by_copy[c] is None]
    known = sum(q_by_copy[c] * (weights[c] / 10 if weights else 1)
                for c in cards if q_by_copy[c] is not None)
    status = "not_applicable" if not applicable else "unknown" if unknown else "known"
    return {"status": status, "value": (None if status != "known" else
                                          known / len(cards) if cards else 0.0),
            "known_numerator": round(known, 10), "denominator": len(cards),
            "unknown_copies": [asdict(c) for c in sorted(unknown)]}


def _function_row(req, modules, assessments, weights, section_size, axis_size):
    scoped, supported, unknown, evidence_rows = _function_copies(req, modules, assessments)
    status = ("given_input" if req.given_input is not None else
              "not_adopted" if req.module_ids and not scoped else
              "covered" if supported else "unknown" if unknown else "missing")
    invested = req.zone == "main" and req.mode == "investment" and req.given_input is None
    effective = sum(weights[c] for c in supported) / 10 if invested else None
    return {"status": status, "required": req.required, "zone": req.zone, "mode": req.mode,
            "source": req.source, "node_ids": sorted(req.node_ids), "given_input": req.given_input,
            "K": len(supported), "E": effective,
            "axis_density": effective / axis_size if invested and axis_size else None,
            "deck_density": effective / section_size if invested and section_size else None,
            "axis_denominator": axis_size, "deck_denominator": section_size,
            "quantity_status": "partial" if unknown else "known",
            "supported_copies": [asdict(c) for c in sorted(supported)],
            "unknown_copies": [asdict(c) for c in sorted(unknown)],
            "evidence": [asdict(e) for e in sorted(evidence_rows, key=lambda e: (
                e.status, e.source, e.conditions, e.effect_refs,
                -1 if e.per_resolution is None else e.per_resolution))]}


def _view(modules, requirements, assessments, weights, function_weights, task):
    cards = sorted({c for m in modules for c in m.cards})
    role_values = defaultdict(list)
    role_rows = []
    for module in modules:
        for zone, code in sorted({(c.zone, c.card_id) for c in module.cards}):
            role = assessments.get((module.module_id, zone, code))
            refs = [c for c in module.cards if (c.zone, c.card_id) == (zone, code)]
            for card in refs:
                role_values[card].append(role.q if role else None)
            role_rows.append({"module_id": module.module_id, "zone": zone, "card_id": code,
                              "copies": len(refs), "q": role.q if role else None,
                              "source": role.source if role else None, "note": role.note if role else "role not assessed"})
    q_by_copy = {c: _best_q(values) for c, values in role_values.items()}
    partitions, gaps = {}, []
    for zone in AXIS_ZONES:
        section = [c for c in cards if c.zone == zone]
        required = any(zone in m.required_zones for m in modules) or any(
            r.zone == zone and r.required and r.given_input is None
            and (not r.module_ids or any(m.module_id in r.module_ids for m in modules)) for r in requirements)
        applicable = bool(section) or required
        partitions[zone] = {"allocated": len(section), "required": required,
                            "A": _ratio(section, q_by_copy, applicable=applicable)}
        if zone == "extra":
            partitions[zone]["U"] = _ratio(section, q_by_copy, weights, applicable=applicable)
        if required and not section:
            gaps.append({"kind": "empty_required_partition", "zone": zone})
    functions = {}
    for req in sorted(requirements, key=lambda r: r.function_id):
        row = _function_row(req, modules, assessments, function_weights[req.function_id],
                            task.sizes[req.zone], partitions[req.zone]["allocated"])
        functions[req.function_id] = row
        if req.required and row["status"] in ("missing", "unknown"):
            gaps.append({"kind": "function_" + row["status"], "function_id": req.function_id})
    return {"partitions": partitions, "roles": role_rows, "functions": functions, "gaps": gaps}


def evaluate_axis(skeleton: SkeletonSpec, context: LayerContext):
    """Return detached, JSON-ready r3.1 statistics for one explicitly chosen skeleton.

    A and U are None when affected by unknown roles; their known numerator is
    retained. K/E count known supporting copies, with separate unknown copies.
    No density is a probability, yield, total score or declaration of legality.
    """
    if not isinstance(skeleton, SkeletonSpec) or not isinstance(context, LayerContext):
        raise ContractError("typed SkeletonSpec and LayerContext required")
    copies, weights, names = _inventory(skeleton, context)
    selected = sorted((m for m in skeleton.modules if m.selected), key=lambda m: m.module_id)
    assessments = {(a.module_id, a.zone, a.card_id): a for a in context.assessments}
    # Each function discounts its real supporting union. Unassigned/unsupported
    # copies cannot consume that function's first-copy contribution.
    function_weights = {r.function_id: _discount_weights(_function_copies(r, selected, assessments)[1], names)
                        for r in context.requirements}
    modules = {}
    for module in sorted(skeleton.modules, key=lambda m: m.module_id):
        if not module.selected:
            modules[module.module_id] = {"status": "not_adopted", "purpose": module.purpose}
            continue
        requirements = tuple(r for r in context.requirements if not r.module_ids or module.module_id in r.module_ids)
        modules[module.module_id] = {"status": "selected", "purpose": module.purpose,
            **_view([module], requirements, assessments, weights, function_weights, context.task)}
    overview = _view(selected, context.requirements, assessments, weights, function_weights, context.task)
    allocated = {c for m in selected for c in m.cards}
    slots = {}
    for zone in ZONES:
        current = [c for c in copies if c.zone == zone]
        unassigned = sorted(set(current) - allocated)
        vacant = context.task.sizes[zone] - len(current)
        slots[zone] = {"budget": context.task.sizes[zone], "inventory": len(current),
                       "allocated": len(current) - len(unassigned),
                       "unassigned": len(unassigned), "vacant": vacant,
                       "remaining": len(unassigned) + vacant,
                       "status": "deferred" if zone == "side" else "projected",
                       "unassigned_copies": [dict(asdict(c), status="deferred" if zone == "side" else "unassigned",
                            purpose=skeleton.unassigned_purposes.get(c)) for c in unassigned],
                       "vacancy_purpose": skeleton.vacancy_purposes.get(zone)}
    represented = {node for r in context.requirements for node in r.node_ids}
    logic_gaps = [{"kind": "unaccounted_logic_function", "node_id": n.node_id,
                   "tags": [asdict(t) for t in n.tags]}
                  for n in context.logic.nodes if n.node_id not in represented
                  and any(t.dimension in ("effect", "effect_type", "role") for t in n.tags)]
    task_gaps = []
    for requirement in context.task.requirements:
        count = getattr(skeleton.inventory, requirement["zone"]).count(requirement["card_id"])
        if count > requirement["maximum"]:
            raise ContractError("inventory exceeds original task card maximum")
        if count < requirement["minimum"]:
            task_gaps.append(dict(requirement, present=count))
    return {"version": EVALUATION_VERSION, "layer": "axis", "task_id": context.task.task_id,
            "task": context.task.to_dict(), "logic": context.logic.to_dict(),
            "inventory": skeleton.inventory.to_dict(), "slots": slots, "modules": modules,
            "overview": overview, "logic_gaps": logic_gaps, "task_requirement_gaps": task_gaps,
            "inventory_complete": all(slots[z]["vacant"] == 0 for z in ZONES),
            "discount_ledger": [dict(asdict(c), effective=weights[c] / 10) for c in sorted(weights)],
            "function_discount_ledgers": {name: [dict(asdict(c), effective=ledger[c] / 10)
                                                  for c in sorted(ledger)]
                                          for name, ledger in sorted(function_weights.items())}}


def evaluate_layers(skeleton, context, catalog=None, *, assets=None, index=None, previous=None,
                    return_state=False):
    """Return a combined record; optionally also return reusable relation state.

    Full inventories reuse the host's list validator. return_state=True returns
    (record, RelationEvaluation) for hosts evaluating a series of local edits.
    """
    from .construction_relations import evaluate_relations, relation_index
    axis = evaluate_axis(skeleton, context)
    if axis["inventory_complete"]:
        validator = assets if assets is not None else getattr(catalog, "assets", None)
        if validator is None:
            raise ContractError("complete layer evaluation requires assets.validate")
        validator.validate(context.task, skeleton.inventory)
        validation = "list_constraints_verified"
    else:
        validation = "partial_inventory"
    if index is None:
        index = relation_index(catalog, context)
    relation = evaluate_relations(skeleton, context, index, previous=previous)
    result = {"version": EVALUATION_VERSION, "layer": "combined", "axis": axis,
              "relations": relation.to_dict(), "validation": validation}
    return (result, relation) if return_state else result


def evaluate_portfolio_layers(rows, skeletons, context, catalog=None, *, assets=None,
                              generation_work=None):
    """Consume existing rows; bound reads/evaluations before touching the catalog.

    Row order, identity and old scoring fields are copied verbatim. This adapter
    neither generates nor sorts candidates. The host reports upstream work
    separately, since a final retention cap is not a generation budget.
    """
    from .construction_relations import compare_configurations, relation_index
    if not isinstance(rows, (list, tuple)) or not isinstance(skeletons, (list, tuple)) or len(rows) != len(skeletons):
        raise ContractError("portfolio requires aligned finite rows and per-row skeletons")
    if context.relations is None:
        raise ContractError("portfolio requires relation context")
    limit = min(32, context.task.candidate_budget, context.relations.budget.candidates)
    accepted = min(limit, len(rows))
    # Zero budget means no semantic reads, matches, validation or evaluation.
    index = relation_index(catalog, context) if accepted else None
    result, baseline = [], None
    for i in range(accepted):
        row, spec = rows[i], skeletons[i]
        if not isinstance(row, dict) or not isinstance(spec, SkeletonSpec):
            raise ContractError("portfolio requires dictionary rows and SkeletonSpec")
        deck = row.get("deck")
        if isinstance(deck, dict):
            deck = DeckParts.from_dict(deck)
        if deck != spec.inventory:
            raise ContractError("candidate skeleton inventory differs from its own row")
        if "layer_evaluation" in row or "layer_comparison" in row:
            raise ContractError("refusing to overwrite existing candidate layer results")
        output, evaluation = evaluate_layers(spec, context, catalog, assets=assets, index=index,
                                             previous=baseline, return_state=True)
        value = deepcopy(row)
        value["layer_evaluation"] = output
        value["layer_comparison"] = None if baseline is None else compare_configurations(baseline, evaluation, context).to_dict()
        if baseline is None:
            baseline = evaluation
        result.append(value)
    return {"version": EVALUATION_VERSION, "rows": result,
            "budget": {"candidate_limit": limit, "evaluated": accepted,
                       "uncovered_positions": list(range(accepted, len(rows)))},
            "upstream_generation_work": deepcopy(generation_work)}
