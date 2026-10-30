"""Source-declared AND dependency closure for a specified function and context.

This identifies the minimal membership implied by supplied necessary rules. It
does not discover card effects, prove complete rule legality, or label members.
Alternative routes use separate contracts; no card names are special-cased.
"""

from collections import Counter
from dataclasses import asdict, dataclass

from .contracts import FactorContractError, Factors, Observation, fields, text

FUNCTION_TAGS = ("negate_activation", "destroy", "draw", "search", "recover", "send_grave", "mill", "special_summon", "starter", "follow_up")
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
class Dependency:
    owner: str
    required: tuple[MemberAmount, ...]
    source: str

    def __post_init__(self):
        text(self.owner, "dependency owner")
        text(self.source, "dependency source")
        _members(self.required, "required companions")


@dataclass(frozen=True)
class KnownCondition:
    key: str
    status: str
    source: str

    def __post_init__(self):
        text(self.key, "function condition")
        text(self.source, "condition source")
        if self.status not in ("satisfied", "unsatisfied", "unknown"):
            raise FactorContractError("condition must retain satisfied/unsatisfied/unknown")


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

    def __post_init__(self):
        for name in ("key", "context_ref", "function_ref", "source"):
            text(getattr(self, name), name)
        if self.period_ref is not None:
            text(self.period_ref, "period reference")
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
                    dependencies=[dict(owner=rule.owner, required=[asdict(value) for value in rule.required], source=rule.source)
                                  for rule in self.dependencies], reviewed_members=list(self.reviewed_members),
                    conditions=[asdict(value) for value in self.conditions], source=self.source, period_ref=self.period_ref,
                    function_tags=list(self.function_tags))

    @classmethod
    def from_dict(cls, value):
        fields(value, ("key", "context_ref", "function_ref", "roots", "dependencies", "reviewed_members", "conditions", "source", "period_ref", "function_tags"))
        for name in ("roots", "dependencies", "reviewed_members", "conditions", "function_tags"):
            if not isinstance(value[name], list):
                raise FactorContractError("functional contract collections must be JSON arrays")
        roots = tuple(MemberAmount(**fields(item, ("ref", "quantity"))) for item in value["roots"])
        dependencies = []
        for item in value["dependencies"]:
            fields(item, ("owner", "required", "source"))
            if not isinstance(item["required"], list):
                raise FactorContractError("dependency required members must be a JSON array")
            dependencies.append(Dependency(item["owner"], tuple(MemberAmount(**fields(v, ("ref", "quantity")))
                                                                for v in item["required"]), item["source"]))
        return cls(value["key"], value["context_ref"], value["function_ref"], roots, tuple(dependencies),
                   tuple(value["reviewed_members"]), tuple(KnownCondition(**fields(item, ("key", "status", "source")))
                                                             for item in value["conditions"]), value["source"], value["period_ref"], tuple(value["function_tags"]))


def minimum_members(contract):
    """Least fixed point of source-declared necessities; shared quantities use max.

    Each rule's quantity is for the entire declared function, not multiplied by
    copies of its owner. Function repetitions need their own explicit contract.
    """
    if not isinstance(contract, FunctionalContract):
        raise FactorContractError("typed functional contract required")
    required = {member.ref: member.quantity for member in contract.roots}
    changed = True
    while changed:
        changed = False
        for rule in contract.dependencies:
            if rule.owner not in required:
                continue
            for member in rule.required:
                if required.get(member.ref, 0) < member.quantity:
                    required[member.ref] = member.quantity
                    changed = True
        if len(required) > 64 or sum(required.values()) > 128:
            raise FactorContractError("functional closure exceeds membership budget")
    return required


def assess_unit(contract, available_refs):
    required = minimum_members(contract)
    available = Counter(available_refs)
    missing = {key: count - available[key] for key, count in required.items() if available[key] < count}
    excess = {key: count - required.get(key, 0) for key, count in available.items() if count > required.get(key, 0)}
    unreviewed = sorted(set(required) - set(contract.reviewed_members))
    conditions = {condition.key: condition.status for condition in contract.conditions}
    conditions_ok = all(value == "satisfied" for value in conditions.values())
    ready = not missing and not unreviewed and conditions_ok
    exact = ready and not excess
    roots = {member.ref for member in contract.roots}
    return dict(function_ref=contract.function_ref, context_ref=contract.context_ref, contract_ref=contract.key,
                minimum_members=required, missing_members=missing, excess_members=excess, unreviewed_members=unreviewed,
                conditions=conditions, membership_ready=ready, exact_minimum=exact,
                function_tags=list(contract.function_tags), function_features_known=bool(contract.function_tags),
                genericity_scope="single_card" if sum(required.values()) == 1 else "strict_joint",
                minimality_scope="only source-declared roots and necessary AND dependencies; not engine certification",
                member_roles=[dict(member_ref=ref, quantity=count,
                                   participation="initiator" if ref in roots else "required_companion",
                                   generic_utility=None, inherited_from_package=False) for ref, count in sorted(required.items())],
                period_ref=contract.period_ref, source=contract.source, rule_authority=False)


def derived_unit_factors(contract, available_refs):
    if contract is None:
        return Factors("group")
    result = assess_unit(contract, available_refs)
    required = result["minimum_members"]
    amount = sum(required.values())
    available = Counter(available_refs)
    coverage = len(set(required) & set(contract.reviewed_members)) / len(required)
    values = dict(unit_minimum_size=amount / 128, unit_joint_dependency=float(amount > 1),
                  unit_available_fraction=sum(min(available[key], n) for key, n in required.items()) / amount,
                  unit_dependencies_reviewed=coverage)
    values.update({"requested_function_" + tag: 1.0 for tag in contract.function_tags})
    if all(condition.status != "unknown" for condition in contract.conditions):
        values["unit_conditions_satisfied"] = float(all(condition.status == "satisfied" for condition in contract.conditions))
    return Factors.from_mapping("group", {key: Observation(value, 1, 0, contract.source) for key, value in values.items()})
