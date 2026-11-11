"""Source-declared AND dependency closure for a specified function and context.

This identifies the minimal membership implied by supplied necessary rules. It
does not discover card effects, prove complete rule legality, or label members.
Alternative routes use separate contracts; no card names are special-cased.
"""

from collections import Counter
from dataclasses import asdict, dataclass, field

from .contracts import FactorContractError, Factors, Observation, digest, fields, text
from .conditions import (Condition, ConditionGroup, Resource, SolverBudget,
                         condition_from_dict, condition_to_dict, solve_requirements)

FUNCTION_TAGS = ("negate_activation", "destroy", "draw", "search", "recover", "send_grave", "mill", "special_summon", "starter", "follow_up", "tribute")
UNIT_FACTORS = ("unit_minimum_size", "unit_joint_dependency", "unit_available_fraction",
                "unit_dependencies_reviewed", "unit_conditions_satisfied") + tuple("requested_function_" + tag for tag in FUNCTION_TAGS)


@dataclass(frozen=True)
class MemberAmount:
    ref: str
    quantity: int = 1

    def __post_init__(self):
        text(self.ref, "member reference")
        if type(self.quantity) is not int or not 1 <= self.quantity <= 3:
            raise FactorContractError("member quantity must be 1..3")


@dataclass(frozen=True)
class BranchConditions:
    structure: Condition | ConditionGroup | None = None
    state: Condition | ConditionGroup | None = None

    def __post_init__(self):
        for scope in ("structure", "state"):
            tree = getattr(self, scope)
            if tree is not None and not isinstance(tree, (Condition, ConditionGroup)):
                raise FactorContractError("branch conditions require typed trees")
        if self.structure is not None:
            stack = [self.structure]
            while stack:
                node = stack.pop()
                if isinstance(node, Condition):
                    if node.stage != "deck":
                        raise FactorContractError("structural branch condition must use deck stage")
                else:
                    stack.extend(node.children)

    def to_dict(self):
        return {scope: None if getattr(self, scope) is None else condition_to_dict(getattr(self, scope)) for scope in ("structure", "state")}

    @classmethod
    def from_dict(cls, value):
        fields(value, ("structure", "state"))
        return cls(*(None if value[s] is None else condition_from_dict(value[s]) for s in ("structure", "state")))


@dataclass(frozen=True)
class Dependency:
    owner: str
    required: tuple[MemberAmount, ...]
    source: str
    # Additional requirement: at least one of these groups must be fully
    # available. Empty means "no alternative branch is required".
    alternatives: tuple[tuple[MemberAmount, ...], ...] = ()
    conditions: BranchConditions = field(default_factory=BranchConditions)
    alternative_conditions: tuple[BranchConditions, ...] = ()

    def __post_init__(self):
        text(self.owner, "dependency owner")
        text(self.source, "dependency source")
        if not self.required and not self.alternatives:
            raise FactorContractError("dependency needs required members or an alternative group")
        if self.required:
            _members(self.required, "required companions")
        if (not isinstance(self.alternatives, tuple) or len(self.alternatives) > 8 or
                any(not isinstance(group, tuple) for group in self.alternatives)):
            raise FactorContractError("bounded tuple alternative groups required")
        for group in self.alternatives:
            _members(group, "alternative companions")
        if not isinstance(self.conditions, BranchConditions):
            raise FactorContractError("typed dependency branch conditions required")
        if not isinstance(self.alternative_conditions, tuple) or (self.alternative_conditions and
                len(self.alternative_conditions) != len(self.alternatives)) or any(
                not isinstance(v, BranchConditions) for v in self.alternative_conditions):
            raise FactorContractError("one condition scope per alternative required")


@dataclass(frozen=True)
class KnownCondition:
    key: str
    status: str
    source: str
    scope: str = "state"

    def __post_init__(self):
        text(self.key, "function condition")
        text(self.source, "condition source")
        if self.status not in ("satisfied", "unsatisfied", "unknown"):
            raise FactorContractError("condition must retain satisfied/unsatisfied/unknown")
        if self.scope not in ("structure", "state"):
            raise FactorContractError("condition scope must be structure/state")


def _members(values, label):
    if (not isinstance(values, tuple) or not 1 <= len(values) <= 64 or
            any(not isinstance(value, MemberAmount) for value in values) or
            len({value.ref for value in values}) != len(values)):
        raise FactorContractError(f"bounded distinct typed {label} required")


@dataclass(frozen=True)
class FunctionalContract:
    key: str
    context_ref: str
    function_ref: str
    roots: tuple[MemberAmount, ...]
    dependencies: tuple[Dependency, ...]
    reviewed_members: tuple[str, ...]
    conditions: tuple[KnownCondition, ...]
    source: str
    period_ref: str | None = None
    function_tags: tuple[str, ...] = ()
    requirements: Condition | ConditionGroup | None = None
    state_requirements: Condition | ConditionGroup | None = None

    def __post_init__(self):
        for name in ("key", "context_ref", "function_ref", "source"):
            text(getattr(self, name), name)
        if self.period_ref is not None:
            text(self.period_ref, "period reference")
        for name in ("requirements", "state_requirements"):
            tree = getattr(self, name)
            if tree is not None and not isinstance(tree, (Condition, ConditionGroup)):
                raise FactorContractError("typed " + name + " required")
        if self.requirements is not None:
            stack = [self.requirements]
            while stack:
                node = stack.pop()
                if isinstance(node, Condition):
                    if node.stage != "deck":
                        raise FactorContractError("structural requirements must use deck stage; use state_requirements for state")
                else:
                    stack.extend(node.children)
        _members(self.roots, "function roots")
        if (not isinstance(self.function_tags, tuple) or any(tag not in FUNCTION_TAGS for tag in self.function_tags) or
                len(set(self.function_tags)) != len(self.function_tags)):
            raise FactorContractError("distinct supported function tags or explicit empty/unknown required")
        if (not isinstance(self.dependencies, tuple) or len(self.dependencies) > 128 or
                any(not isinstance(value, Dependency) for value in self.dependencies)):
            raise FactorContractError("bounded typed dependency rules required")
        if (not isinstance(self.reviewed_members, tuple) or len(self.reviewed_members) > 64 or
                len(set(self.reviewed_members)) != len(self.reviewed_members)):
            raise FactorContractError("distinct reviewed membership scopes required")
        for value in self.reviewed_members:
            text(value, "reviewed member")
        if (not isinstance(self.conditions, tuple) or not 1 <= len(self.conditions) <= 32 or
                any(not isinstance(value, KnownCondition) for value in self.conditions) or
                len({value.key for value in self.conditions}) != len(self.conditions)):
            raise FactorContractError("explicit distinct function/context conditions required")

    def to_dict(self):
        # JSON arrays are used consistently with RoleInput.to_dict().
        return dict(key=self.key, context_ref=self.context_ref, function_ref=self.function_ref,
                    roots=[asdict(value) for value in self.roots],
                    dependencies=[dict(owner=rule.owner, required=[asdict(value) for value in rule.required],
                                       alternatives=[[asdict(value) for value in group] for group in rule.alternatives],
                                       conditions=rule.conditions.to_dict(),
                                       alternative_conditions=[v.to_dict() for v in rule.alternative_conditions],
                                       source=rule.source)
                                  for rule in self.dependencies], reviewed_members=list(self.reviewed_members),
                    conditions=[asdict(value) for value in self.conditions], source=self.source, period_ref=self.period_ref,
                    function_tags=list(self.function_tags),
                    requirements=None if self.requirements is None else condition_to_dict(self.requirements),
                    state_requirements=None if self.state_requirements is None else condition_to_dict(self.state_requirements))

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise FactorContractError("functional contract object required")
        value = dict(value)
        value.setdefault("requirements", None)
        value.setdefault("state_requirements", None)
        fields(value, ("key", "context_ref", "function_ref", "roots", "dependencies", "reviewed_members", "conditions", "source", "period_ref", "function_tags", "requirements", "state_requirements"))
        for name in ("roots", "dependencies", "reviewed_members", "conditions", "function_tags"):
            if not isinstance(value[name], list):
                raise FactorContractError("functional contract collections must be JSON arrays")
        roots = tuple(MemberAmount(**fields(item, ("ref", "quantity"))) for item in value["roots"])
        dependencies = []
        for item in value["dependencies"]:
            if not isinstance(item, dict):
                raise FactorContractError("dependency object required")
            item = dict(item)
            item.setdefault("alternatives", [])
            item.setdefault("conditions", BranchConditions().to_dict())
            item.setdefault("alternative_conditions", [])
            if set(item) != {"owner", "required", "source", "alternatives", "conditions", "alternative_conditions"}:
                raise FactorContractError("dependency fields must include owner, required, source and optional alternatives")
            if not isinstance(item["required"], list) or not isinstance(item.get("alternatives", []), list):
                raise FactorContractError("dependency required/alternative members must be JSON arrays")
            alternatives = tuple(tuple(MemberAmount(**fields(v, ("ref", "quantity"))) for v in group)
                                 for group in item.get("alternatives", []))
            if not isinstance(item["alternative_conditions"], list):
                raise FactorContractError("alternative_conditions array required")
            dependencies.append(Dependency(item["owner"], tuple(MemberAmount(**fields(v, ("ref", "quantity")))
                                                                for v in item["required"]), item["source"], alternatives,
                                           BranchConditions.from_dict(item["conditions"]),
                                           tuple(BranchConditions.from_dict(v) for v in item["alternative_conditions"])))
        known_conditions = []
        for item in value["conditions"]:
            if not isinstance(item, dict):
                raise FactorContractError("known condition object required")
            item = dict(item)
            item.setdefault("scope", "state")
            known_conditions.append(KnownCondition(**fields(item, ("key", "status", "source", "scope"))))
        return cls(value["key"], value["context_ref"], value["function_ref"], roots, tuple(dependencies),
                   tuple(value["reviewed_members"]), tuple(known_conditions), value["source"], value["period_ref"], tuple(value["function_tags"]),
                   None if value["requirements"] is None else condition_from_dict(value["requirements"]),
                   None if value["state_requirements"] is None else condition_from_dict(value["state_requirements"]))


def minimum_member_branches(contract, *, budget=SolverBudget()):
    """Close each alternative recursively; presence quantities use max, not sum."""
    if not isinstance(contract, FunctionalContract) or not isinstance(budget, SolverBudget):
        raise FactorContractError("typed functional contract and budget required")
    roots = {m.ref: m.quantity for m in contract.roots}
    stack = [(roots, frozenset(), (), ())]
    completed, steps, overflow = {}, 0, False
    while stack:
        members, expanded, choices, bindings = stack.pop()
        steps += 1
        if steps > budget.max_states:
            overflow = True
            break
        if len(members) > 64 or sum(members.values()) > 128:
            overflow = True
            continue
        pending = next((i for i, rule in enumerate(contract.dependencies)
                        if i not in expanded and rule.owner in members), None)
        if pending is None:
            member_key = tuple(sorted(members.items()))
            bound = [b.to_dict() for b in bindings if b.structure is not None or b.state is not None]
            key = (member_key, digest(bound))
            if key not in completed:
                if len(completed) >= budget.max_solutions:
                    overflow = True
                    break
                completed[key] = dict(branch_id="members:" + digest(key)[:20], members=dict(member_key),
                                      branch_conditions=bound,
                                      function_ref=contract.function_ref, choices=[choices],
                                      witness_refs=sorted({contract.source} | {contract.dependencies[i].source for i in expanded}))
            elif choices not in completed[key]["choices"]:
                completed[key]["choices"].append(choices)
            continue
        rule = contract.dependencies[pending]
        common = dict(members)
        for member in rule.required:
            common[member.ref] = max(common.get(member.ref, 0), member.quantity)
        alternatives = rule.alternatives or ((),)
        ordered = sorted(enumerate(alternatives), key=lambda v: tuple(sorted((m.ref, m.quantity) for m in v[1])))
        for choice, group in reversed(ordered):
            branch = dict(common)
            for member in group:
                branch[member.ref] = max(branch.get(member.ref, 0), member.quantity)
            picked = choices + ((pending, choice),) if rule.alternatives else choices
            scoped = bindings + (rule.conditions,)
            if rule.alternative_conditions:
                scoped += (rule.alternative_conditions[choice],)
            stack.append((branch, expanded | {pending}, picked, scoped))
    return dict(branches=[completed[k] for k in sorted(completed)], overflow=overflow,
                enumeration_complete=not overflow, explored_states=steps, function_ref=contract.function_ref)


def minimum_members(contract, *, branch_id=None):
    closure = minimum_member_branches(contract)
    branches = closure["branches"]
    if branch_id is not None:
        selected = next((b for b in branches if b["branch_id"] == branch_id), None)
        if selected is None:
            raise FactorContractError("unknown functional branch_id")
        return dict(selected["members"])
    if closure["overflow"] or len(branches) != 1:
        raise FactorContractError("explicit branch selection required; use minimum_member_branches")
    return dict(branches[0]["members"])


def assess_unit(contract, available_refs, *, resources=(), coverage=False,
                state_provided=False, branch_id=None, budget=SolverBudget()):
    if type(state_provided) is not bool:
        raise FactorContractError("state_provided must be boolean")
    if type(coverage) is not bool and (not isinstance(coverage, tuple) or any(
            not isinstance(v, tuple) or len(v) != 6 for v in coverage)):
        raise FactorContractError("coverage requires bool or six-field scopes")
    if branch_id is not None:
        text(branch_id, "branch_id")
    if not isinstance(available_refs, (tuple, list)) or len(available_refs) > 128:
        raise FactorContractError("bounded available member references required")
    for ref in available_refs:
        text(ref, "available member reference")
    if not isinstance(resources, (tuple, list)) or any(not isinstance(r, Resource) for r in resources):
        raise FactorContractError("typed external resources required")
    available = Counter(available_refs)
    closure = minimum_member_branches(contract, budget=budget)
    declared = closure["branches"]
    if branch_id is not None and not any(b["branch_id"] == branch_id for b in declared):
        raise FactorContractError("unknown functional branch_id")
    structure_conditions = [c for c in contract.conditions if c.scope == "structure"]
    state_conditions = [c for c in contract.conditions if c.scope == "state"]
    stock = tuple(Resource("member", ref, count, resource_id="member:" + ref, source=contract.source)
                  for ref, count in sorted(available.items())) + tuple(resources)
    member_coverage = tuple(("member", ref, "self", "deck", None, None)
                            for ref in sorted(set(available) | {r for b in declared for r in b["members"]}))
    effective_coverage = True if coverage is True else member_coverage + (() if coverage is False else tuple(coverage))
    branches = []
    for definition in declared:
        required = definition["members"]
        missing = {r: n - available[r] for r, n in required.items() if available[r] < n}
        excess = {r: n - required.get(r, 0) for r, n in available.items() if n > required.get(r, 0)}
        unreviewed = sorted(set(required) - set(contract.reviewed_members))
        atoms = tuple(Condition("member", r, n, consume_mode="reusable") for r, n in required.items())
        if contract.requirements is not None:
            atoms += (contract.requirements,)
        bound = tuple(BranchConditions.from_dict(v) for v in definition["branch_conditions"])
        atoms += tuple(b.structure for b in bound if b.structure is not None)
        # Membership may exceed the per-group fanout; nest bounded ALL groups.
        while len(atoms) > 16:
            atoms = tuple(ConditionGroup("all", atoms[i:i + 16]) for i in range(0, len(atoms), 16))
        tree = atoms[0] if len(atoms) == 1 else ConditionGroup("all", atoms)
        assessment = solve_requirements(tree, stock, coverage=effective_coverage, budget=budget)
        structural = assessment["structural_status"]
        if any(c.status == "unsatisfied" for c in structure_conditions):
            structural = "conflict"
        elif unreviewed or any(c.status == "unknown" for c in structure_conditions):
            if structural == "complete":
                structural = "unknown"
        ready = structural == "complete"
        exact = ready and not excess
        state_result = None
        readiness = "unknown"
        if state_provided:
            if structural in ("partial", "conflict") or any(c.status == "unsatisfied" for c in state_conditions):
                readiness = "blocked"
            elif ready:
                state_terms = (() if contract.state_requirements is None else (contract.state_requirements,)) + tuple(b.state for b in bound if b.state is not None)
                if state_terms:
                    # Structural reservations and state demands share one solve.
                    state_terms = (tree,) + state_terms
                    while len(state_terms) > 16:
                        state_terms = tuple(ConditionGroup("all", state_terms[i:i + 16]) for i in range(0, len(state_terms), 16))
                    state_tree = ConditionGroup("all", state_terms)
                    state_result = solve_requirements(state_tree, stock, coverage=effective_coverage,
                                                      budget=budget, state_provided=True)
                    readiness = state_result["state_readiness"]
                elif state_conditions and all(c.status == "satisfied" for c in state_conditions):
                    readiness = "executable"
                if any(c.status == "unknown" for c in state_conditions) and readiness == "executable":
                    readiness = "unknown"
        branches.append(dict(**definition, minimum_members=required, missing_members=missing,
                             excess_members=excess, unreviewed_members=unreviewed,
                             structural_status=structural, membership_ready=ready,
                             minimal_membership_complete=exact, exact_minimum=exact,
                             state_readiness=readiness, requirement_assessment=assessment,
                             state_assessment=state_result,
                             external_requirements=dict(members=missing,
                                 conditions={c.key: c.status for c in contract.conditions if c.status != "satisfied"},
                                 residual_conditions=[v for b in assessment["branches"] for v in b["residual_conditions"]])))
    visible = [b for b in branches if branch_id is None or b["branch_id"] == branch_id]
    feasible = [b for b in visible if b["membership_ready"]]
    # Scalar compatibility fields refer only to a unique complete definition.
    summary = visible[0] if len(visible) == 1 else feasible[0] if len(feasible) == 1 else None
    structural = ("complete" if feasible else "unknown" if closure["overflow"] or any(b["structural_status"] == "unknown" for b in visible)
                  else "conflict" if visible and all(b["structural_status"] == "conflict" for b in visible) else "partial")
    readiness = ("executable" if any(b["state_readiness"] == "executable" for b in visible) else
                 "blocked" if visible and not closure["overflow"] and all(b["state_readiness"] == "blocked" for b in visible) else "unknown")
    sizes = {sum(b["members"].values()) for b in visible}
    roots = {m.ref for m in contract.roots}
    members = None if summary is None else summary["members"]
    conditions = {c.key: c.status for c in contract.conditions}
    return dict(function_ref=contract.function_ref, context_ref=contract.context_ref, contract_ref=contract.key,
                branches=branches, chosen_branch=branch_id, structural_status=structural,
                state_readiness=readiness, overflow=closure["overflow"] or any(b["requirement_assessment"]["overflow"] for b in visible),
                enumeration_complete=closure["enumeration_complete"] and all(b["requirement_assessment"]["enumeration_complete"] for b in visible),
                minimum_members=members, missing_members=None if summary is None else summary["missing_members"],
                excess_members=None if summary is None else summary["excess_members"],
                unreviewed_members=None if summary is None else summary["unreviewed_members"],
                conditions=conditions, membership_ready=bool(feasible),
                minimal_membership_complete=not closure["overflow"] and any(b["minimal_membership_complete"] for b in visible),
                exact_minimum=not closure["overflow"] and any(b["exact_minimum"] for b in visible),
                alternative_requirements=[dict(branch_id=b["branch_id"], members=b["members"], structural_status=b["structural_status"], satisfied=b["membership_ready"]) for b in branches],
                missing_any={} if feasible else {b["branch_id"]: b["missing_members"] for b in visible if b["missing_members"]},
                external_requirements=None if summary is None else summary["external_requirements"],
                internal_satisfied=None if members is None else dict(members={r: min(n, available[r]) for r, n in members.items()}),
                current_function_ready=True if readiness == "executable" else False if readiness == "blocked" else None,
                current_readiness_is_not_generic_role=True, function_tags=list(contract.function_tags),
                function_features_known=bool(contract.function_tags),
                genericity_scope="unknown" if closure["overflow"] else "single_card" if sizes == {1} else "strict_joint" if len(sizes) == 1 else "branch_dependent",
                minimality_scope="source-declared per-function member branches; resource witnesses are independent",
                member_roles=[] if members is None else [dict(member_ref=r, quantity=n,
                    participation="initiator" if r in roots else "required_companion", generic_utility=None,
                    inherited_from_package=False) for r, n in sorted(members.items())],
                period_ref=contract.period_ref, source=contract.source, rule_authority=False)


def derived_unit_factors(contract, available_refs):
    if contract is None:
        return Factors("group")
    result = assess_unit(contract, available_refs)
    required = result["minimum_members"]
    values = {"requested_function_" + tag: 1.0 for tag in contract.function_tags}
    if required is not None and not result["overflow"]:
        amount = sum(required.values())
        available = Counter(available_refs)
        values.update(unit_minimum_size=amount / 128, unit_joint_dependency=float(amount > 1),
                      unit_available_fraction=sum(min(available[r], n) for r, n in required.items()) / amount,
                      unit_dependencies_reviewed=len(set(required) & set(contract.reviewed_members)) / len(required))
    structural_conditions = [c for c in contract.conditions if c.scope == "structure"]
    if structural_conditions and all(c.status != "unknown" for c in structural_conditions):
        values["unit_conditions_satisfied"] = float(all(c.status == "satisfied" for c in structural_conditions))
    return Factors.from_mapping("group", {k: Observation(v, 1, 0, contract.source) for k, v in values.items()})
