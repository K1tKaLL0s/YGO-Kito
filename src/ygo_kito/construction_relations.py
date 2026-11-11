"""Bounded, effect-scoped construction support; never a game-state executor.

Inputs are source-backed facts. A supported relation retains its conditions.
All/any groups are explicit, physical inventory and usage limits are separate,
and integer allocation uses the shared bounded allocator.
"""

from collections import Counter, defaultdict, deque
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from functools import lru_cache, wraps
from itertools import chain
from math import comb
import re
from time import perf_counter

from .validation import ContractError, integer, member, text


def _tuple(value, kind, label):
    if not isinstance(value, tuple) or any(not isinstance(v, kind) for v in value):
        raise ContractError(f"{label} requires a tuple of {kind.__name__}")


def _strings(value, label):
    _tuple(value, str, label)
    for v in value:
        text(v, label)


@dataclass(frozen=True)
class Resource:
    kind: str
    zone: str | None = None
    origin: str | None = None
    reason: str | None = None
    event: str | None = None
    selection: str | None = None
    attributes: tuple[str, ...] = ()

    def __post_init__(self):
        text(self.kind, "resource kind")
        for value in (self.zone, self.origin, self.reason, self.event, self.selection):
            if value is not None:
                text(value, "resource condition")
        _strings(self.attributes, "resource attributes")

    def accepts(self, supply):
        return (self.kind == supply.kind and all(
            getattr(self, k) is None or getattr(self, k) == getattr(supply, k)
            for k in ("zone", "origin", "reason", "event", "selection"))
            and set(self.attributes) <= set(supply.attributes))


@dataclass(frozen=True)
class Need:
    need_id: str
    resource: Resource
    quantity: int = 1
    mode: str = "consume"
    # A consumed entity's resulting state; absence is not a guessed movement.
    destination: str | None = None

    def __post_init__(self):
        text(self.need_id, "need ID")
        if not isinstance(self.resource, Resource):
            raise ContractError("need requires Resource")
        integer(self.quantity, "required quantity", 1)
        member(self.mode, "resource use", ("consume", "presence"))
        if self.destination is not None:
            text(self.destination, "consumed entity destination")
            if self.mode != "consume":
                raise ContractError("only consumption has a resulting destination")


@dataclass(frozen=True)
class InputGroup:
    operator: str
    items: tuple

    def __post_init__(self):
        member(self.operator, "input operator", ("all", "any"))
        if not isinstance(self.items, tuple) or not self.items or any(
                not isinstance(v, (Need, InputGroup)) for v in self.items):
            raise ContractError("input group requires explicit nonempty needs/groups")
        # Bound expression size before recursive matching; no Boolean expansion.
        stack = [(self, 0)]
        size = 0
        while stack:
            item, depth = stack.pop()
            size += 1
            if depth > 16 or size > 2048:
                raise ContractError("input expression exceeds structural bound")
            if isinstance(item, InputGroup):
                stack.extend((v, depth + 1) for v in item.items)
        ids = [v.need_id for v in _needs(self)]
        if len(ids) != len(set(ids)):
            raise ContractError("repeat quantities explicitly; duplicate need within an expression")


def _needs(group):
    if group is None:
        return
    if isinstance(group, Need):
        yield group
    else:
        for item in group.items:
            yield from _needs(item)


@dataclass(frozen=True)
class PoolRecovery:
    fact_id: str
    before: str
    after: str
    # Complete return prerequisites are paid before the prior consumption, or
    # between that consumption and this one return event. No inferred timing.
    cost_timing: str = "unspecified"

    def __post_init__(self):
        for value in (self.fact_id, self.before, self.after):
            text(value, "sourced ordered recovery")
        if self.before == self.after:
            raise ContractError("recovery requires distinct ordered needs")
        member(self.cost_timing, "return cost timing", ("unspecified", "before", "between"))


@dataclass(frozen=True)
class ResourcePool:
    pool_id: str
    source: str
    capacity: int | None = None
    inventory: tuple[tuple[str, int], ...] = ()
    reusable_if: str | None = None
    # The sourced return occurs between these two named consumption needs.
    # One return is not an unlimited replenishment of the pool.
    recovery_between: tuple[str, ...] = ()
    recoveries: tuple[PoolRecovery, ...] = ()
    # Counters scale with copies without reserving those cards as payments.
    count_inventory: tuple[tuple[str, int], ...] = ()

    def __post_init__(self):
        text(self.pool_id, "pool ID")
        text(self.source, "pool source")
        _tuple(self.inventory, tuple, "pool inventory")
        for pair in self.inventory:
            if len(pair) != 2:
                raise ContractError("inventory pool requires zone/card pairs")
            member(pair[0], "pool zone", ("main", "extra"))
            integer(pair[1], "pool card", 1)
        if len(set(self.inventory)) != len(self.inventory):
            raise ContractError("duplicate inventory pool member")
        if self.capacity is not None:
            integer(self.capacity, "pool capacity", 0)
        if self.inventory and self.capacity is not None:
            raise ContractError("pool capacity is either inventory-derived or fixed")
        _tuple(self.count_inventory, tuple, 'counter inventory')
        if self.count_inventory and (self.inventory or self.capacity is None):
            raise ContractError('copy counter requires a fixed per-copy capacity')
        for pair in self.count_inventory:
            if len(pair)!=2:
                raise ContractError('counter requires zone/card pairs')
            member(pair[0], 'counter zone', ('main','extra'))
            integer(pair[1], 'counter card', 1)
        if len(set(self.count_inventory))!=len(self.count_inventory):
            raise ContractError('duplicate counter member')
        if self.reusable_if is not None:
            text(self.reusable_if, "supported recovery fact ID")
        _strings(self.recovery_between, "ordered recovery needs")
        if self.recovery_between and (not self.reusable_if or len(self.recovery_between) != 2
                or len(set(self.recovery_between)) != 2):
            raise ContractError("recovery requires two distinct ordered needs and a return fact")
        _tuple(self.recoveries, PoolRecovery, "pool recoveries")
        if len(set(self.recoveries)) != len(self.recoveries):
            raise ContractError("duplicate pool recovery")


def _recoveries(pool):
    legacy = (PoolRecovery(pool.reusable_if, *pool.recovery_between),) if pool.recovery_between else ()
    return tuple(dict.fromkeys((*legacy, *pool.recoveries)))


@dataclass(frozen=True)
class Claim:
    pool_id: str
    quantity: int = 1
    mode: str = "consume"

    def __post_init__(self):
        text(self.pool_id, "claim pool")
        integer(self.quantity, "claim quantity", 1)
        member(self.mode, "claim mode", ("consume", "presence"))


@dataclass(frozen=True)
class ResourceTransfer:
    """Sourced movement of existing entities, never additional inventory."""
    source: str
    origin: str | None
    destination: str | None
    owner: str | None = None
    controller: str | None = None
    selection: str | None = None
    # None is unresolved; an empty tuple is a resolved selector with no member.
    inventory: tuple[tuple[str, int], ...] | None = None
    reason: str | None = None
    # A rule follows only the entities moved to the field by this event.
    leave_destination: str | None = None
    leave_source: str | None = None

    def __post_init__(self):
        text(self.source, "transfer source")
        for value in (self.origin, self.destination, self.reason, self.leave_destination, self.leave_source):
            if value is not None:
                text(value, "transfer state")
        for value in (self.owner, self.controller):
            if value is not None:
                text(value, "transfer party")
        if self.selection is not None:
            member(self.selection, "transfer selection", ("targeted", "random", "unknown"))
        if ((self.leave_destination is None) != (self.leave_source is None)
                or self.leave_destination is not None and self.destination != "field"):
            raise ContractError("sourced leave rule requires a transfer to the field")
        if self.inventory is not None:
            _tuple(self.inventory, tuple, "transfer inventory")
            for pair in self.inventory:
                if len(pair) != 2:
                    raise ContractError("transfer inventory requires zone/card pairs")
                member(pair[0], "transfer inventory zone", ("main", "extra"))
                integer(pair[1], "transfer inventory card", 1)
            if len(set(self.inventory)) != len(self.inventory):
                raise ContractError("duplicate transfer inventory member")


@dataclass(frozen=True)
class RelationFact:
    fact_id: str
    effect_ref: str
    output: Resource
    source: str
    card_id: int | None = None
    zone: str = "main"
    quantity: int | None = 1
    inputs: InputGroup | None = None
    output_pool: str | None = None
    inventory_scaled: bool = False
    claims: tuple[Claim, ...] = ()
    conditions: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    # Explicitly different alternatives of one effect reserve different choices.
    choice: str = "joint"
    transfer: ResourceTransfer | None = None

    def __post_init__(self):
        for v in (self.fact_id, self.effect_ref, self.source, self.choice):
            text(v, "relation identity/source")
        if not isinstance(self.output, Resource):
            raise ContractError("relation output requires Resource")
        member(self.zone, "relation inventory zone", ("main", "extra"))
        if self.card_id is not None:
            integer(self.card_id, "relation card", 1)
        if self.quantity is not None:
            integer(self.quantity, "supply quantity", 1)
        if self.inputs is not None and not isinstance(self.inputs, InputGroup):
            raise ContractError("relation inputs require explicit all/any group")
        if type(self.inventory_scaled) is not bool or (self.inventory_scaled and self.card_id is None):
            raise ContractError("inventory-scaled supply requires a card")
        if self.output_pool is not None:
            text(self.output_pool, "output pool")
        _tuple(self.claims, Claim, "resource claims")
        if len({c.pool_id for c in self.claims}) != len(self.claims):
            raise ContractError("combine duplicate pool claims explicitly")
        _strings(self.conditions, "relation conditions")
        _strings(self.unknown, "relation unknowns")
        if self.transfer is not None and not isinstance(self.transfer, ResourceTransfer):
            raise ContractError("relation transfer requires ResourceTransfer")


@dataclass(frozen=True)
class UseRequirement:
    use_id: str
    inputs: InputGroup
    source: str
    required: bool = True
    priority: int = 0
    functional_use_ids: tuple[str, ...] = ()

    def __post_init__(self):
        text(self.use_id, "use ID")
        text(self.source, "use source")
        if not isinstance(self.inputs, InputGroup) or type(self.required) is not bool:
            raise ContractError("use requires explicit inputs and required flag")
        integer(self.priority, "use priority", 0)
        _strings(self.functional_use_ids, "bound functional uses")


@dataclass(frozen=True)
class JointConstraint:
    constraint_id: str
    uses: tuple[str, ...]
    kind: str
    source: str

    def __post_init__(self):
        text(self.constraint_id, "constraint ID")
        text(self.source, "constraint source")
        _strings(self.uses, "constraint uses")
        if len(set(self.uses)) < 2 or len(set(self.uses)) != len(self.uses):
            raise ContractError("joint constraint requires distinct uses")
        member(self.kind, "joint constraint", ("incompatible", "order_unknown", "all", "before"))


@dataclass(frozen=True)
class ProbabilityRequest:
    request_id: str
    cards: tuple[int, ...]
    draws: int
    source: str
    objectives: tuple[str, ...] = ("acquired", "retained")

    def __post_init__(self):
        text(self.request_id, "probability ID")
        text(self.source, "probability source")
        _tuple(self.cards, int, "probability cards")
        if not self.cards or len(set(self.cards)) != len(self.cards):
            raise ContractError("probability requires distinct card IDs")
        for c in self.cards:
            integer(c, "probability card", 1)
        integer(self.draws, "draw count", 0)
        _strings(self.objectives, "probability objectives")
        for v in self.objectives:
            member(v, "probability objective", ("acquired", "retained"))


@dataclass(frozen=True)
class RelationBudget:
    cards: int = 128
    facts: int = 1024
    needs: int = 1024
    matches: int = 30000
    updates: int = 30000
    candidates: int = 32
    # A matching time slice does not reduce the allocator's state space.
    allocations: int = 30000

    def __post_init__(self):
        for k, v in asdict(self).items():
            integer(v, f"{k} budget", 0)


@dataclass(frozen=True)
class RelationContext:
    uses: tuple[UseRequirement, ...]
    facts: tuple[RelationFact, ...] = ()
    pools: tuple[ResourcePool, ...] = ()
    constraints: tuple[JointConstraint, ...] = ()
    probabilities: tuple[ProbabilityRequest, ...] = ()
    # Only these already-selected/recalled IDs may be read from the catalog.
    catalog_cards: tuple[int, ...] = ()
    budget: RelationBudget = field(default_factory=RelationBudget)

    def __post_init__(self):
        for values, kind, key in ((self.uses, UseRequirement, "use_id"),
                (self.facts, RelationFact, "fact_id"), (self.pools, ResourcePool, "pool_id"),
                (self.constraints, JointConstraint, "constraint_id"),
                (self.probabilities, ProbabilityRequest, "request_id")):
            _tuple(values, kind, key)
            if len({getattr(v, key) for v in values}) != len(values):
                raise ContractError(f"duplicate {key}")
        _tuple(self.catalog_cards, int, "catalog cards")
        if len(set(self.catalog_cards)) != len(self.catalog_cards):
            raise ContractError("duplicate catalog card")
        for c in self.catalog_cards:
            integer(c, "catalog card", 1)
        if not isinstance(self.budget, RelationBudget):
            raise ContractError("typed relation budget required")
        ids = {u.use_id for u in self.uses}
        if any(not set(c.uses) <= ids for c in self.constraints):
            raise ContractError("constraint references absent use")


def _context(context):
    value = context if isinstance(context, RelationContext) else context.relations
    if not isinstance(value, RelationContext):
        raise ContractError("explicit RelationContext required")
    return value


@dataclass
class RelationIndex:
    context: RelationContext
    facts: dict
    pools: dict
    matches: dict
    needs: dict
    owners: dict
    dependents: dict
    incomplete_needs: set
    truncated_facts: bool
    observations: dict
    counters: dict
    unresolved_cards: tuple = ()
    catalog: object = field(default=None, repr=False)
    catalog_snapshot: dict = field(default_factory=dict, repr=False)
    name_groups: tuple = ()
    continuation: dict | None = field(default=None, repr=False)
    matched_state: dict | None = field(default=None, repr=False)


def relation_index(catalog, context, *, continuation=None, should_stop=None):
    """Read only the bounded caller scope, then match ports once for all edits."""
    ctx = _context(context)
    started = perf_counter()
    facts = {}
    pools = {p.pool_id: p for p in ctx.pools}
    observations = {}
    truncated = False
    imported = 0
    cache_hits = 0
    unresolved_cards, snapshot = [], {}
    for f in sorted(ctx.facts, key=lambda f: f.fact_id):
        if len(facts) >= ctx.budget.facts:
            truncated = True
            break
        facts[f.fact_id] = _normal_summon_input(f)
    cards = sorted(ctx.catalog_cards)
    for position, code in enumerate(cards):
        if position >= ctx.budget.cards or len(facts) >= ctx.budget.facts:
            truncated = True
            break
        if catalog is None:
            raise ContractError("catalog required for requested card observations")
        before = getattr(catalog, "_profiles", {}).get(code)
        records = catalog.effect_records(code)
        profile = catalog.card(code)
        cache_hits += before is profile
        observations[code] = {"records": deepcopy(records), "materials": deepcopy(profile.materials),
                              "unknown": list(profile.unknown), "text_sha256": profile.text_sha256}
        imported += 1
        row = catalog.assets.rows[code]
        snapshot[code] = (row.get("desc"), row.get("alias"), row.get("type"))
        if any(r["unknown"] and not r["operations"] for r in records) or (profile.unknown and not records):
            unresolved_cards.append(code)
        zone = "extra" if row.get("type", 0) & (0x40 | 0x2000 | 0x800000 | 0x4000000) else "main"
        names = {c: min(group) for group in getattr(context, "same_name_groups", ()) for c in group}
        same_name = names.get(code, row.get("alias") or code)
        imported_facts = _record_facts(code, records, zone=zone, same_name=same_name)
        material = _material_fact(code, profile, zone)
        for f, new_pools in chain(imported_facts, ((material, ()),) if material else ()):
            if len(facts) >= ctx.budget.facts:
                truncated = True
                break
            if f.fact_id in facts:
                raise ContractError("catalog/explicit relation ID collision")
            facts[f.fact_id] = _normal_summon_input(f)
            for p in new_pools:
                if p.pool_id in pools and pools[p.pool_id] != p:
                    raise ContractError("inconsistent shared catalog limit")
                pools[p.pool_id] = p
    for f in facts.values():
        if any(c.pool_id not in pools for c in f.claims) or (f.output_pool and f.output_pool not in pools):
            raise ContractError("relation references absent resource pool")
        if f.inventory_scaled and (f.quantity != 1 or not f.output_pool or
                (f.zone, f.card_id) not in pools[f.output_pool].inventory):
            raise ContractError("physical supply requires unit copies and an inventory pool")
    if any(fid not in facts for p in pools.values()
           for fid in ({p.reusable_if} if p.reusable_if else set()) | {r.fact_id for r in p.recoveries}) and not truncated:
        raise ContractError("recovery references absent fact")
    parties = {n.resource.attributes for f in facts.values() for n in _needs(f.inputs)
               if n.resource.kind == 'normal_summon_allowance'}
    for attributes in sorted(parties):
        key = 'rule:normal_summon:' + ':'.join(attributes)
        if key in facts:
            raise ContractError('normal summon rule ID is reserved')
        if len(facts) >= ctx.budget.facts:
            truncated = True
            break
        facts[key] = RelationFact(key, key, Resource('normal_summon_allowance', attributes=attributes),
            'rule: one normal summon or Set per turn')
    needs, owners = {}, defaultdict(set)
    for owner, group in [("fact:" + f.fact_id, f.inputs) for f in facts.values()] + [
            ("use:" + u.use_id, u.inputs) for u in ctx.uses]:
        for need in _needs(group):
            if need.need_id in needs and needs[need.need_id] != need:
                raise ContractError("same need ID has conflicting definitions")
            needs[need.need_id] = need
            owners[need.need_id].add(owner)
    buckets = defaultdict(list)
    attributes = defaultdict(set)
    for f in facts.values():
        buckets[f.output.kind].append(f.fact_id)
        for attribute in f.output.attributes:
            attributes[f.output.kind,attribute].add(f.fact_id)
    matches, incomplete, dependents = {}, set(), defaultdict(set)
    def port(value):return {**asdict(value),'attributes':list(value.attributes)}
    ports=dict(outputs={k:port(v.output) for k,v in facts.items()},requirements={k:port(v.resource) for k,v in needs.items()})
    ordered=sorted(needs.items());start_i=start_j=prior_checks=0
    if continuation is not None:
        if (continuation.get('version')!='relation-matching-v1' or continuation.get('ports')!=ports):
            raise ContractError('relation matching continuation belongs to different ports')
        start_i,start_j=continuation['cursor'];prior_checks=continuation['checks']
        if (type(start_i) is not int or not 0<=start_i<=len(ordered) or type(start_j) is not int or start_j<0):
            raise ContractError('invalid relation matching cursor')
        matches=deepcopy(continuation['matches'])
    attempts=0;pending=None
    for i,(key,need) in enumerate(ordered):
        matches.setdefault(key,[])
        if i<start_i:continue
        candidates=set(buckets[need.resource.kind])
        for attribute in need.resource.attributes:
            candidates.intersection_update(attributes[need.resource.kind,attribute])
        candidates=sorted(candidates)
        offset=start_j if i==start_i else 0
        if offset>len(candidates):raise ContractError('relation matching cursor exceeds candidate bucket')
        if i-start_i>=ctx.budget.needs:
            pending=(i,offset);break
        for j in range(offset,len(candidates)):
            if attempts>=ctx.budget.matches or should_stop is not None and should_stop():
                pending=(i,j);break
            fid=candidates[j];attempts+=1
            if need.resource.accepts(facts[fid].output):matches[key].append(fid)
        if pending is not None:break
    if pending is not None:
        incomplete.update(key for key,_ in ordered[pending[0]:])
    for key in needs:
        matches.setdefault(key,[])
        if truncated:incomplete.add(key)
        for fid in matches[key]:
            if fid not in facts or not needs[key].resource.accepts(facts[fid].output):
                raise ContractError('saved relation match does not satisfy the requested port')
            dependents[fid].update(owners[key])
    matched_state=dict(version='relation-matching-v1',ports=ports,cursor=list(pending) if pending else [len(ordered),0],
        checks=prior_checks+attempts,matches=deepcopy(matches))
    progress=matched_state if pending is not None else None
    consumer_owners = {fid: set(values) for fid, values in dependents.items()}
    for pid, pool in pools.items():
        for recovery in ({pool.reusable_if} if pool.reusable_if else set()) | {r.fact_id for r in pool.recoveries}:
            for fid, fact in facts.items():
                if fact.output_pool == pid or any(c.pool_id == pid for c in fact.claims):
                    dependents[recovery].add("fact:" + fid)
                    # The supplier's own state may stay unchanged when a return
                    # appears. Recheck its consuming owners directly as well.
                    dependents[recovery].update(consumer_owners.get(fid, ()))
    return RelationIndex(ctx, facts, pools, matches, needs, dict(owners), dict(dependents),
        incomplete, truncated, observations, {"F": len(facts), "A": len(needs), "M": prior_checks+attempts,
        "L": sum(map(len, matches.values())), "R": sum(len(f.claims) for f in facts.values()),
        "catalog_cards": imported, "catalog_cache_hits": cache_hits,
        "index_seconds": perf_counter() - started}, tuple(unresolved_cards), catalog, snapshot,
        getattr(context, "same_name_groups", ()), progress, matched_state)


def _material_fact(code, profile, zone):
    if not profile.materials:
        return None
    inputs = tuple(Need(f"catalog:{code}:material:{i}", Resource("material", attributes=(
        f"{item['kind']}:{item['value']}",)), item["count"]) for i, item in enumerate(profile.materials))
    return RelationFact(f"catalog:{code}:materials", f"catalog:{code}:material-rule",
        Resource("material_ready", attributes=(f"target:{code}",)),
        "material-rule:" + profile.text_sha256, code, zone, inputs=InputGroup("all", inputs),
        conditions=("material_access_and_movement_from_supplied_relations",))


def _normal_summon_input(fact):
    """Reserve a summon only for an actual summon, not an alternative effect."""
    action = fact.output.kind in ('normal_summon', 'tribute_summon', 'normal_set')
    event = fact.output.kind == 'activation' and fact.output.event in ('normal_summon', 'tribute_summon')
    existing = tuple(_needs(fact.inputs))
    if action and fact.output.reason == 'effect':
        return fact  # A summon performed by an effect has its own permission.
    # A receiving trigger already depends on its actual summoning operation.
    if not (action or event) or any(n.resource.kind in ('normal_summon_allowance','functional_operation') for n in existing):
        return fact
    actor = fact.transfer.controller if fact.transfer else None
    actor = actor or next((a.split(':',1)[1] for a in fact.output.attributes if a.startswith('controller:')), 'self')
    allowance = Need(fact.fact_id+':normal_summon_count',
        Resource('normal_summon_allowance', attributes=('controller:'+actor,)))
    return replace(fact, inputs=InputGroup('all',tuple(v for v in (fact.inputs,allowance) if v is not None)))


def _leave_field_rule(record, operation):
    """Only the observed summoning effect may attach its own leave rule."""
    if not record or not operation or operation.get("kind") != "special_summon" or operation.get("to_zone") != "field":
        return None
    rules = [r for r in (*record["card_restrictions"], *record["restrictions"]) if r["kind"] == "leave_field_banish"]
    if (not rules or any(r not in record["restrictions"] or r.get("scope") != "this_effect_summoned_card"
            or r.get("condition") != "summoned_by_this_effect" or r.get("duration") != "until_leave_field"
            or not r.get("source") for r in rules)):
        return None
    return "; ".join(sorted({r["source"] for r in rules}))


def _operation_transfer(operation, source, inventory=None, dependencies=None, controller=None, record=None):
    if operation.get('generation') or operation.get('replacement_rule'):
        return None  # Creating a token does not transfer a configured card.
    origins, destination = operation.get("from_zones", ()), operation.get("to_zone")
    if not origins and destination is None:
        return None
    position = operation.get("deck_position")
    if destination == "deck" and position is not None:
        destination = {"top": "deck_top", "bottom": "deck_bottom"}.get(position)
    members, parsed = None, None
    if (inventory is not None and dependencies is not None and len(inventory) <= 512
            and operation.get('owner')=='self'):
        from .construction_inventory import matches, requirement, selector, query_supported
        query = operation.get("selector_query") or (selector(operation["selector"]) if operation.get("selector") else None)
        parsed = requirement(operation.get("source", ""), "operations")
        if operation.get('selector_source',operation.get('source')) != operation.get('source'):
            query = None  # A text revision cannot retain a stale narrower selector.
        query = query or (parsed["query"] if parsed else None)
        query = dependencies.resolve_query(query) if query else None
        if (query_supported(query) and 'face_up' not in query
                and all(code in dependencies.rows for _, code in inventory)):
            candidates = {pair for pair in inventory if matches(dependencies.rows[pair[1]], query)}
            eligible = {pair: dependencies.candidate_status(pair[1], dict(category="operations", operation=operation))[0]
                        for pair in candidates}
            if all(value is not None for value in eligible.values()):
                members = tuple(sorted(pair for pair, value in eligible.items() if value))
    leave_source = _leave_field_rule(record, operation)
    return ResourceTransfer(source, origins[0] if len(origins) == 1 else None, destination,
        operation.get("owner"), operation.get("controller", controller),
        "random" if operation.get("random") is True else "targeted" if operation.get("random") is False or parsed else None,
        members, operation.get("reason"), "banished" if leave_source else None, leave_source)


def _record_outputs(record):
    """An observed non-flavor record can supply adoption without a benefit."""
    if record.get('summon_procedure'):
        return ()  # The configuration adapter supplies this non-scoring entry.
    if record["operations"]:
        leave_sources = {r["source"] for r in record["restrictions"] if r["kind"] == "leave_field_banish"}
        mapped = any(_leave_field_rule(record, op) for op in record["operations"])
        # Some coarse records also project this future replacement as an
        # immediate banish operation. Its benefit is not independent of the
        # sourced lifecycle already attached to the summon.
        return tuple((i, op) for i, op in enumerate(record["operations"]) if op.get('phase') not in ('delayed','replacement')
            and op.get('processing_role')!='auxiliary' and not (
            mapped and op.get("kind") == "banish" and op.get("source") in leave_sources
            and op.get("from_zones") == ["field"] and op.get("to_zone") == "banished"
            and op.get("quantity") is None))
    return () if record.get("block_view", {}).get("status") == "flavor" else ((None, None),)


_RESTRICTION_ALIASES = {"cannot_summon": "cannot_normal_summon", "cannot_set": "cannot_normal_summon",
    "cannot_attack": "cannot_declare_attack"}
_PLAYER_RESTRICTIONS = frozenset({"cannot_normal_summon", "extra_fusion_only", "cannot_declare_attack",
    "cannot_special_summon_from_extra", "cannot_special_summon", "cannot_draw", "cannot_add_hand",
    "cannot_send_grave", "cannot_banish", "cannot_return", "cannot_release", "cannot_activate",
    'grave_destination_replace', *_RESTRICTION_ALIASES})
_INTRINSIC_RESTRICTIONS = frozenset({"cannot_normal_summon_this_card", "cannot_special_summon_this_card",
    *("cannot_be_"+kind+"_material" for kind in ("fusion", "synchro", "xyz", "link", "ritual"))})


def _restriction_contract(restriction):
    """Adapt complete observed clauses; coarse labels never discharge qualifiers."""
    allowed = {"kind", "source", "scope", "controller", "owner", "condition", "duration", "whole_turn",
        "includes_set", "from_zones", "to_zone", "reason", "tag", "block_id", "group", "source_span",
        "evidence_refs", "observed_source", "context_source", "unknown", "allowed_summons"}
    if set(restriction) - allowed:
        return None
    kind = restriction["kind"]
    source = restriction.get("source", "")
    if kind == "cannot_summon":
        kind = ("cannot_normal_summon" if "通常召唤" in source else
                "cannot_special_summon_from_extra" if "额外卡组" in source and "特殊召唤" in source else
                "cannot_special_summon" if "特殊召唤" in source else kind)
    elif kind == "cannot_set":
        kind = "cannot_normal_summon" if "通常召唤" in source else kind
    else:
        kind = _RESTRICTION_ALIASES.get(kind, kind)
    if kind in _INTRINSIC_RESTRICTIONS:
        rule = dict(restriction)
        if (rule.get("scope") != "this_card" or rule.get("duration") not in ("intrinsic", "while_applicable")
                or any(rule.get(k) for k in ("selector", "selector_query", "exceptions", "except", "unknown",
                                            "controller", "owner", "whole_turn", "to_zone", "reason"))):
            return None
        material_names = {'fusion':'融合','synchro':'同调','xyz':'超量','link':'连接','ritual':'仪式'}
        material = next((name for key,name in material_names.items() if kind == 'cannot_be_'+key+'_material'), None)
        body = (r"不能作为" + material + r"(?:召唤的)?素材" if material else
                {"cannot_normal_summon_this_card": r"不能通常召唤(?P<set>（盖放）|\(盖放\))?",
                 "cannot_special_summon_this_card": r"不能特殊召唤"}[kind])
        match = re.fullmatch(r"(?:这张卡)?" + body, rule.get("source", "").strip())
        conditional = None
        if material and not match:
            conditional = re.fullmatch(r"这张卡在(?P<zone>手卡|墓地|场上|怪兽区域)存在(?:的场合)?[，,]" + body,
                                       rule.get("source", "").strip())
        if not match and not conditional:
            return None
        if conditional and rule["duration"] != "while_applicable":
            return None
        zone = {"手卡": "hand", "墓地": "grave", "场上": "field", "怪兽区域": "field"}.get(
            conditional["zone"] if conditional else None)
        condition = "this_card_in_monster_zone" if conditional and conditional["zone"] == "怪兽区域" else (
            "this_card_in_zone" if conditional else "this_card")
        if (rule.get("condition", "this_card") not in ("this_card", condition)
                or rule.get("from_zones", [zone] if zone else []) != ([zone] if zone else [])):
            return None
        rule.update(condition=condition)
        if zone:
            rule["from_zones"] = [zone]
        if kind == "cannot_normal_summon_this_card":
            includes_set = bool(match["set"])
            if rule.get("includes_set") is not None and rule["includes_set"] is not includes_set:
                return None
            rule["includes_set"] = includes_set
        elif rule.get("includes_set") is not None:
            return None
        return rule
    if kind not in _PLAYER_RESTRICTIONS or kind == "cannot_summon":
        return None
    rule = dict(restriction, kind=kind)
    if kind=='grave_destination_replace':
        if re.fullmatch(r'直到下个回合的结束时[，,]被送去墓地的卡不去墓地而除外',source):
            return dict(rule,controller='both',condition='effect_use',duration='next_turn_end',whole_turn=False)
        return None
    if kind=='cannot_activate' and re.fullmatch(r'(?:(?:这个卡名的卡(?:在)?1回合只能发动1张)[，,])?'
            r'这张卡发动的回合[，,]自己不能把特殊召唤的怪兽以外的场上的怪兽的效果发动',source):
        return dict(rule,controller='self',condition='effect_activation',duration='turn',whole_turn=True,
            required_state='special_summoned')
    if kind in ('cannot_special_summon','cannot_special_summon_from_extra'):
        prelude=re.fullmatch(r'(?:这个卡名|这张卡)的([①②③④⑤⑥⑦⑧⑨⑩]+)的?效果1回合各能使用\d+次[，,]'
            r'这些效果发动的回合[，,]自己不能(?:把怪兽)?特殊召唤',source)
        if prelude and rule.get('scope','player')=='player' and rule.get('controller','self')=='self' and rule.get('whole_turn',True) is True:
            return dict(rule,controller='self',condition='effect_activation',duration='turn',whole_turn=True)
        limited=re.fullmatch(r'(?P<when>这个回合|发动这个效果的回合|这个效果(?:的)?发动后[，,]直到回合结束时)[，,]?'
            r'(?P<player>自己|对方|双方)(?:若非(?P<unless>.+?)则|不是(?P<except>.+?))不能特殊召唤',source)
        if limited:
            from .effect_mechanisms import RACES
            text=limited['unless'] or limited['except'];predicate=None
            level=re.fullmatch(r'等级或者阶级是(\d+)以上的怪兽',text)
            if level and 1<=int(level[1])<=13:
                minimum=int(level[1])
                predicate={'all':[{'field':'level_between','value':[minimum,13]},
                    {'not':{'field':'type_all','value':0x4000000}}]}
            elif text in {name+'怪兽' for name in RACES}:
                predicate={'field':'race_any','value':RACES[text[:-2]]}
            else:
                types={'融合怪兽':0x41,'同调怪兽':0x2001,'超量怪兽':0x800001,'连接怪兽':0x4000001,'仪式怪兽':0x81}
                if text in types:predicate={'field':'type_all','value':types[text]}
                attribute=re.fullmatch(r'(地|水|炎|风|光|暗|神)属性怪兽',text)
                if attribute:predicate={'field':'attribute_any','value':{'地':1,'水':2,'炎':4,'风':8,'光':16,'暗':32,'神':64}[attribute[1]]}
            player={'自己':'self','对方':'opponent','双方':'both'}[limited['player']]
            whole='发动后' not in limited['when']
            if (predicate is None or rule.get('scope','player')!='player'
                    or rule.get('controller',player)!=player
                    or rule.get('owner',player)!=player
                    or rule.get('whole_turn',whole) is not whole
                    or rule.get('allowed_summons',predicate)!=predicate
                    or any(rule.get(k) for k in ('unknown','selector','selector_query','exceptions','except','reason','to_zone'))):
                return None
            return dict(rule,controller=player,condition='effect_activation',duration='turn',
                whole_turn=whole,allowed_summons=predicate)
    bodies = {
        "cannot_draw": r"(?P<player>自己|对方|双方)不能(?P<draw_reason>用卡的效果|用效果)?抽卡",
        "cannot_add_hand": r"(?P<player>自己|对方|双方)不能(?:从(?P<zone>卡组|墓地|除外状态)把卡|把卡)加入手卡",
        "cannot_special_summon_from_extra": r"(?P<player>自己|对方|双方)不能从额外卡组(?:把怪兽)?特殊召唤",
        "cannot_normal_summon": r"(?P<player>自己|对方|双方)不能通常召唤(?P<set>（盖放）|\(盖放\))?",
        "cannot_special_summon": r"(?P<player>自己|对方|双方)不能(?:(?:从(?P<zone>手卡|卡组|墓地|除外状态|场上))?把怪兽)?特殊召唤",
        "cannot_declare_attack": r"(?P<player>自己|对方|双方)不能(?:进行)?攻击宣言",
        "extra_fusion_only": r"(?P<player>自己|对方|双方)不能从额外卡组把融合怪兽以外的怪兽特殊召唤",
        "cannot_send_grave": r"(?P<player>自己|对方|双方)不能(?P<why>作为代价|用效果)?(?:从(?P<zone>手卡|卡组|墓地|场上)把卡|把卡)送去墓地",
        "cannot_banish": r"(?P<player>自己|对方|双方)不能(?P<why>作为代价|用效果)?(?:从(?P<zone>手卡|卡组|墓地|场上)把卡|把卡)除外",
        "cannot_return": r"(?P<player>自己|对方|双方)不能(?P<why>作为代价|用效果)?(?:从(?P<zone>手卡|卡组|墓地|场上)把卡|把卡)(?:返回|回到)(?P<destination>手卡|卡组|额外卡组)",
        "cannot_release": r"(?P<player>自己|对方|双方)不能(?P<why>作为代价|用效果)?(?:把怪兽)?解放",
        "cannot_activate": r"(?P<player>自己|对方|双方)不能发动(?:卡的)?效果",
        "cannot_set": r"(?P<player>自己|对方|双方)不能盖放(?:卡)?",
    }
    if kind in bodies:
        match = re.fullmatch(r"(?P<when>这张卡在怪兽区域存在|这个效果发动后|这张卡(?:的)?发动后|"
                             r"发动这个效果的回合|这张卡发动的回合)[，,](?:直到回合结束时[，,]?)?"
                             + bodies[kind], rule.get("source", ""))
        if match:
            when = match["when"]
            controller = {"自己": "self", "对方": "opponent", "双方": "both"}[match["player"]]
            condition = "this_card_in_monster_zone" if when == "这张卡在怪兽区域存在" else "effect_activation"
            coarse_effect = (kind == "cannot_normal_summon" and "includes_set" in rule
                or kind == "extra_fusion_only") and rule.get("condition") == "effect_use"
            if (rule.get("scope", "player") != "player" or rule.get("controller", controller) != controller
                    or rule.get("condition", condition) != condition and not coarse_effect):
                return None
            duration = "while_applicable" if condition == "this_card_in_monster_zone" else "turn"
            compatible_whole = when in ("发动这个效果的回合", "这张卡发动的回合") and rule.get("duration") == "whole_turn"
            if "tag" not in rule and not coarse_effect and not compatible_whole and rule.get("duration", duration) != duration:
                return None
            rule.update(scope="player", controller=controller, condition=condition,
                        duration=duration)
            if condition != "this_card_in_monster_zone":
                whole = when in ("发动这个效果的回合", "这张卡发动的回合")
                if rule.get("whole_turn") is not None and rule["whole_turn"] is not whole:
                    return None
                rule["whole_turn"] = whole
            if kind=='cannot_draw' and match['draw_reason']:
                if rule.get('reason') not in (None,'effect'):
                    return None
                rule['reason']='effect'
            if kind == "cannot_normal_summon":
                includes_set = bool(match["set"])
                if rule.get("includes_set") is not None and rule["includes_set"] is not includes_set:
                    return None
                rule["includes_set"] = includes_set
                if rule.get("from_zones"):
                    return None  # This complete clause contains no origin qualifier.
            if kind == "cannot_add_hand":
                zone = match.groupdict().get("zone")
                origins = {"卡组": "deck", "墓地": "grave", "除外状态": "banished"}
                if zone:
                    if rule.get("from_zones", [origins[zone]]) != [origins[zone]]:
                        return None
                    rule["from_zones"] = [origins[zone]]
                elif rule.get("from_zones"):
                    return None
            if kind in ("cannot_special_summon", "cannot_send_grave", "cannot_banish", "cannot_return", "cannot_release"):
                parts = match.groupdict()
                origins = {"手卡":"hand", "卡组":"deck", "墓地":"grave", "场上":"field", "除外状态":"banished"}
                parsed = {"from_zones": [origins[parts["zone"]]] if parts.get("zone") else None,
                    "to_zone": {"手卡":"hand", "卡组":"deck", "额外卡组":"extra"}.get(parts.get("destination")),
                    "reason": {"作为代价":"cost", "用效果":"effect"}.get(parts.get("why"))}
                for field, value in parsed.items():
                    observed = rule.get(field)
                    if observed is not None and not (field == "from_zones" and observed == [] and value is None) and observed != value:
                        return None
                    if value is not None:
                        rule[field] = value
        elif "tag" in rule:
            # Structural records retain their entire source because their
            # kind alone does not resolve exceptions, subjects or timing.
            return None
    if (not rule.get("source") or rule.get("scope", "player") != "player"
            or rule.get("controller", rule.get("owner")) not in ("self", "opponent", "both")
            or any(rule.get(k) for k in ("selector", "selector_query", "exceptions", "except", "unknown"))):
        return None
    rule["controller"] = rule.get("controller", rule.get("owner"))
    if rule.get("owner") is not None and rule["owner"] != rule["controller"]:
        return None
    condition, duration = rule.get("condition"), rule.get("duration")
    if condition == "this_card_in_monster_zone":
        if duration != "while_applicable" or rule.get("whole_turn") is not None:
            return None
    elif condition in ("effect_use", "effect_activation"):
        whole = rule.get("whole_turn", True if duration == "whole_turn" else None)
        if type(whole) is not bool or duration not in (None, "turn", "whole_turn"):
            return None
        if duration == "whole_turn" and not whole:
            return None
        rule["whole_turn"] = whole
    else:
        return None
    if kind in ("cannot_special_summon_from_extra", "extra_fusion_only"):
        if rule.get("from_zones", ["extra"]) != ["extra"]:
            return None
        rule["from_zones"] = ["extra"]
    if kind == "cannot_draw" and rule.get("from_zones", ["deck"]) != ["deck"]:
        return None
    if kind == "cannot_add_hand" and (not isinstance(rule.get("from_zones", []), (list, tuple))
            or any(z not in ("deck", "grave", "banished", "field", "extra") for z in rule.get("from_zones", []))):
        return None
    if kind == "cannot_normal_summon" and (rule.get("includes_set") is not None and type(rule["includes_set"]) is not bool
            or not isinstance(rule.get("from_zones", []), (list, tuple))
            or any(z not in ("hand", "grave", "deck", "field", "extra", "banished") for z in rule.get("from_zones", []))):
        return None
    if kind == "cannot_declare_attack" and rule.get("from_zones"):
        return None
    if (not isinstance(rule.get("from_zones", []), (list, tuple))
            or any(z not in ("hand", "deck", "grave", "field", "extra", "banished", "xyz_material") for z in rule.get("from_zones", []))
            or rule.get("to_zone") not in (None, "hand", "deck", "grave", "field", "extra", "banished")
            or rule.get("reason") not in (None, "effect", "cost")):
        return None
    return rule


def _record_applicability(record):
    restrictions = (*record["card_restrictions"], *record["restrictions"])
    rules = [_restriction_contract(r) for r in restrictions]
    if (not record["operations"] and restrictions
            and record.get("block_view", {}).get("status") == "restriction"
            and not record["costs"] and not record["targets"] and not record["count_limits"]
            and all(r and r.get("condition") == "this_card_in_monster_zone" for r in rules)):
        return Resource("effect_applicability", zone="field",
            attributes=(f"card:{record['card_id']}", "controller:self", "state:monster_zone"))
    return None


def _record_facts(code, records, *, zone="main", same_name=None, inventory=None, dependencies=None, controller=None, functional=False):
    """Preserve recognized observations, without guessing opaque selectors.

    Costs/targets/trigger clauses become explicit input ports. A host may supply
    their sourced support. Unknown fields stay on the affected effect. No use of
    route_ready, no full-text parsing, and no catalog-wide material search.
    """
    records = tuple(records)
    index_counts = Counter(record["effect_index"] for record in records)
    scoped_counts = Counter((record.get('scope'),record['effect_index']) for record in records)
    for position, record in enumerate(records):
        ref = f"catalog:{code}:{record['effect_index']}"
        source = f"{record['semantic_version']}:{record['text_sha256']}:{record['effect_index']}"
        inputs, unknown, conditions, claims, pools = [], list(record["unknown"]), [], [], []
        if functional and record['count_limits'] and all(c.get('status')=='known' for c in record['count_limits']):
            # Static uses reserve the printed count. No negated activation is
            # being executed, so its unknown refund policy is not a prerequisite.
            unknown = [v for v in unknown if v!='count_negation_policy']
        repeated = index_counts[record["effect_index"]] > 1
        if repeated:
            # Pendulum and monster sections can both number an effect ①.
            # Preserve each observed text segment without merging its ports
            # or claiming that the parser has resolved the section's scope.
            ref += f":record:{position}"
            source += f":record:{position}"
            if not record.get('scope') or scoped_counts[record.get('scope'),record['effect_index']]>1:
                unknown.append("repeated_effect_number_scope_unresolved")
        if record.get('branch_records'):
            from .effect_records import operation_record
            for oi, operation in _record_outputs(record):
                scoped = deepcopy(operation_record(record, operation))
                scoped.update(operations=[operation], relation_ref=ref+':'+operation['choice'],
                    operation_refs={op.get('block_id'):ref+':op:'+str(index) for index,op in _record_outputs(record)})
                for fact, branch_pools in _record_facts(code, (scoped,), zone=zone, same_name=same_name,
                        inventory=inventory, dependencies=dependencies, controller=controller, functional=functional):
                    yield replace(fact, fact_id=ref+':op:'+str(oi), effect_ref=ref), branch_pools
            continue
        ref = record.get('relation_ref', ref)
        restrictions = (*record["card_restrictions"], *record["restrictions"])
        # A fully observed continuous restriction has an applicability state,
        # rather than an unobserved activation or once-per-turn claim. Presence
        # in the deck still supplies no evidence of this field state.
        field_applicability = _record_applicability(record)
        trigger = record["trigger"]
        if field_applicability:
            unknown = [v for v in unknown if v not in ("activation_boundary", "activation_condition",
                "additional_activation_conditions", "count_limit", "resolution", "unparsed_resolution_or_restriction")]
            inputs.append(Need(ref + ":applicability", field_applicability, mode="presence"))
        elif trigger.get("event") in ("unknown", None):
            unknown.append("activation_condition_unknown")
        else:
            inputs.append(Need(ref + ":trigger", Resource("activation", zone=trigger.get("zone"),
                reason=trigger.get("reason"), event=trigger["event"], attributes=(f"card:{code}",)), mode="presence"))
        if not field_applicability and record["conditions"]["status"] != "recognized":
            unknown.append("additional_activation_conditions")
        for category in ("costs", "targets"):
            for i, item in enumerate(record[category]):
                quantity = item.get("quantity")
                attributes = (item.get("source") or ref + f":{category}:{i}",)
                if category == "costs" and item.get('subject') == 'this_card' and item.get('source_card_id') == code:
                    attributes += ('source_card:' + str(code),)
                resource = Resource("payment" if category == "costs" else "target",
                    reason=item.get("reason"), attributes=attributes)
                state_payment = item.get('consumes_card') is False or item.get('resource') in ('public_state','card_state')
                inputs.append(Need(ref + f":{category}:{i}", resource, quantity or 1,
                                   "consume" if category == "costs" and not state_payment else "presence"))
                if category=='costs' and state_payment:
                    unknown.append(f"costs:{i}:state_change_requires_binding")
                if quantity is None:
                    unknown.append(f"{category}:{i}:quantity_unknown")
        for i, limit in enumerate(record["count_limits"]):
            scope = limit.get("scope", "unknown")
            # Each-option limits are not a single shared one-use pool. Keep
            # their scoped record until this adapter can allocate per option.
            if limit.get("status") == "known" and scope.startswith("same_name"):
                suffix = str(record["effect_index"]) if scope in ("same_name_this_effect",'same_name_summon_method') else scope
                if scope == 'same_name_each_option':
                    choices = {op.get('choice') for op in record['operations']}
                    if len(choices) != 1 or None in choices:
                        unknown.append(f"count_scope:{i}:{scope}")
                        continue
                    suffix += ':'+next(iter(choices))
                if repeated and scope == "same_name_this_effect":
                    suffix += f":record:{position}"
                pid = f"catalog-limit:{same_name or code}:{suffix}"
                pools.append(ResourcePool(pid, limit["source"], capacity=limit["maximum"]))
                claims.append(Claim(pid))
            elif limit.get('status')=='known' and scope=='this_card_effect':
                pid = f'catalog-effect-limit:{code}:{record.get("effect_key", position)}'
                pools.append(ResourcePool(pid, limit['source'], capacity=limit['maximum'],
                    count_inventory=((zone,code),)))
                claims.append(Claim(pid))
            else:
                unknown.append(f"count_scope:{i}:{scope}")
        for restriction in restrictions:
            conditions.append("restriction:" + restriction["source"])
            unknown.append("restriction_joint_scope_unresolved")
        for i, op in _record_outputs(record):
            if op is None:
                yield RelationFact(ref + ":adoption", ref, Resource("effect_adoption", attributes=(ref,)),
                    source, code, zone, inputs=InputGroup("all", tuple(inputs)) if inputs else None,
                    claims=tuple(claims), conditions=tuple(conditions), unknown=tuple(sorted(set(unknown)))), pools
                continue
            origin = op.get("from_zones", ())
            attrs = tuple(v for v in ("selector:" + op["selector"] if op.get("selector") else None,
                                      "owner:" + op["owner"] if op.get("owner") else None) if v)
            extra_unknown = list(unknown)
            operation_conditions=list(conditions)
            operation_inputs=list(inputs)
            for connector in record.get('block_view',{}).get('connectors',()):
                if connector.get('target')==op.get('block_id') and connector.get('condition_source'):
                    operation_conditions.append('operation_condition:'+connector['condition_source'])
                    if not any(state['source']==connector['condition_source'] for state in op.get('state_conditions',())):
                        extra_unknown.append('operation_condition_unresolved')
            if op.get('depends_on'):
                observed = {v.get('block_id'): v for _, v in _record_outputs(record)}
                refs = record.get('operation_refs') or {v.get('block_id'): ref+':op:'+str(j)
                    for j, v in _record_outputs(record)}
                if functional and any(previous in observed and observed[previous].get('choice') == op.get('choice')
                                      for previous in op['depends_on']):
                    # The prerequisite already reserves this same activation,
                    # costs and target. Picking them again can change the target.
                    operation_inputs.clear()
                for previous in op['depends_on']:
                    group = op.get('simultaneous_group')
                    simultaneous = group and observed.get(previous, {}).get('simultaneous_group') == group
                    operation_conditions.append(('required_same_processing:' if simultaneous else 'preceding_operation:') + previous)
                    if previous in refs and functional:
                        operation_inputs.append(Need(ref+':preceding:'+str(i)+':'+previous,
                            Resource('functional_operation',attributes=(refs[previous],)),mode='presence'))
                    elif previous not in refs:
                        extra_unknown.append('operation_sequence_unresolved:'+previous)
            if len(origin) > 1:
                if not (record.get('fusion_material_selection') and op['kind']=='return_fusion_materials') and (
                        dependencies is None or dependencies.item_requirement(op,'operations') is None):
                    extra_unknown.append("multiple_origin_choice")
            if op.get("reason") not in ("effect", "cost"):
                extra_unknown.append("operation_reason_unknown")
            selection = "random" if op.get("random") else "targeted" if op.get("random") is False else None
            resource = Resource(op["kind"], op.get("to_zone"), origin[0] if len(origin) == 1 else None,
                op.get("reason"), "sent_to_grave" if op.get("to_zone") == "grave" else None,
                selection, attrs)
            observed = RelationFact(ref + f":op:{i}", ref, resource, source, code, zone,
                quantity=op.get("quantity"), inputs=InputGroup("all", tuple(operation_inputs)) if operation_inputs else None,
                claims=tuple(claims), conditions=tuple(operation_conditions), unknown=tuple(sorted(set(extra_unknown))),
                choice=op.get('choice','joint'), transfer=_operation_transfer(op, source, inventory, dependencies, controller, record))
            yield _normal_summon_input(observed), pools


def _blank(status="missing", reason=None):
    return {"status": status, "gaps": [reason] if reason else [], "unknown": [],
            "conditions": [], "suppliers": [], "bottlenecks": [], "usage": {}, "possible_usage": {},
            "alternatives": [], "conflicts": [], "condition_expression": ("all", ()),
            "support_expression": ("all", ()), "quantities": {}}


def _unknown_support(row):
    # Retain sourced atom identities through all/any branches. They are not
    # independent per consumer when the same prerequisite feeds two uses.
    if row["status"] == "unknown" and row["support_expression"] == ("all", ()):
        row["support_expression"] = _expression("all", [
            ("atom", "unresolved:"+v) for v in row["unknown"] or row["gaps"] or ("unspecified",)])
    return row


class _AllocationPending(Exception):
    """An unfinished local enumeration, never a missing rule or failed fact."""


def _cursor_value(value):
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return [[_cursor_value(k), _cursor_value(v)] for k, v in sorted(value.items(), key=lambda p: repr(p[0]))]
    if isinstance(value, (list, tuple)):
        return [_cursor_value(v) for v in value]
    return value


def _restore_relation(value):
    if isinstance(value, dict):
        result = {k: _restore_relation(v) for k, v in value.items()}
        for key in ('support_expression', 'condition_expression'):
            if key in result:
                def expression(v):
                    return (v[0], tuple(expression(x) for x in v[1])) if v[0] in ('all', 'any') else (
                        v[0], tuple(v[1]) if isinstance(v[1], list) else v[1])
                result[key] = expression(result[key])
        if 'slot' in result and isinstance(result['slot'], list):
            result['slot'] = tuple(result['slot'])
        for key in ('inventory', 'count_inventory'):
            pairs = result.get(key)
            if isinstance(pairs, list) and all(isinstance(pair, (list, tuple)) and len(pair) == 2
                    and isinstance(pair[0], str) and type(pair[1]) is int for pair in pairs):
                result[key] = tuple(tuple(pair) for pair in pairs)
        return result
    if isinstance(value, tuple):
        return tuple(_restore_relation(v) for v in value)
    return [_restore_relation(v) for v in value] if isinstance(value, list) else value


class _AllocationWork:
    def __init__(self, budget, should_stop=None, *, preview=False):
        self.remaining = max(0, budget)
        self.should_stop = should_stop
        self.steps = 0
        self.operations = {}
        self.shared_operations = None
        self.preview = preview

    def record(self, kind, inputs):
        from .build_contracts import digest
        key = kind + ':' + digest(_cursor_value(inputs))
        operations = self.shared_operations if kind == 'shared' and self.shared_operations is not None else self.operations
        return operations.setdefault(key, {})

    def check(self):
        if self.remaining <= 0 or self.should_stop is not None and self.should_stop():
            raise _AllocationPending()

    def tick(self, record):
        if record.get('started'):
            return
        self.check()
        self.remaining -= 1
        self.steps += 1
        record['started'] = True


def _allocation_record(index, kind, inputs):
    work = getattr(index, '_allocation_work', None)
    return (work.record(kind, inputs) if work is not None else {}), work


def _cached_allocation(index_position, key_positions):
    """Keep completed children of the currently active relation unit only."""
    def decorate(function):
        @wraps(function)
        def call(*args, **kwargs):
            record, work = _allocation_record(args[index_position], 'result:' + function.__name__,
                ([args[i] if i < len(args) else None for i in key_positions], kwargs))
            if work is None:
                return function(*args, **kwargs)
            if 'result' not in record:
                record['result'] = deepcopy(function(*args, **kwargs))
            return _restore_relation(deepcopy(record['result']))
        return call
    return decorate


def _shared_allocation(index, tree, stock, *, existential):
    from .multifactor.conditions import SolverBudget, condition_to_dict, solve_requirements
    record, work = _allocation_record(index, 'shared', (condition_to_dict(tree),
        [r.to_dict() for r in stock], existential))
    if 'result' in record:
        return _restore_relation(deepcopy(record['result']))
    while True:
        if work is not None:
            work.check()
        states = max(1, min(1000000, work.remaining if work is not None else index.context.budget.allocations))
        value = solve_requirements(tree, stock, coverage=True,
            budget=SolverBudget(max_states=states, max_solutions=1 if existential else 128),
            continuation=record.get('continuation'), should_stop=work.should_stop if work is not None else None,
            existential=existential)
        if work is not None:
            work.remaining -= value['explored_states']
            work.steps += value['explored_states']
        # Existential consumers need one known witness. Alternative-set consumers
        # must retain every branch before their containing ALL decides resources.
        complete = value['enumeration_complete'] or (existential or work is not None and work.preview) and value['satisfied'] is True
        if complete or work is None:
            break
        record['continuation'] = value['continuation']
        if not value['explored_states']:
            raise _AllocationPending()
    record['result'] = {k: v for k, v in value.items() if k not in ('resources', 'continuation')}
    record.pop('continuation', None)
    return value


def _usage_input(row):
    """Recheck derived resource conclusions without dropping source unknowns."""
    value = deepcopy(row)
    base = value.pop("resource_base", None)
    if base is not None:
        value.update(deepcopy(base))
    value.pop("recovery_allocation", None)
    value.pop('inventory_allocation', None)
    value.pop("recovery_returns", None)
    value.pop("return_selections", None)
    value.pop("transfer_states", None)
    return value


def _usage_result(value, base, capacities):
    for pid, entries in value["possible_usage"].items():
        capacity = capacities.get(pid)
        if capacity is not None and _demand(entries) > capacity and (
                _demand(value["usage"].get(pid, {})) <= capacity):
            value["unknown"].append("alternative_allocation:" + pid)
    value["resource_base"] = {k: deepcopy(base[k]) for k in
                              ("status", "unknown", "support_expression", "conflicts")}
    value["status"] = ("missing" if value["conflicts"] or base["status"] == "missing" else
                       "unknown" if value["unknown"] or base["status"] == "unknown" else "supported")
    atoms = [("atom", "resource:" + v) for v in sorted(set(value["unknown"]) - set(base["unknown"]))]
    value["support_expression"] = _expression("all", [value["support_expression"], *atoms])
    return _unknown_support(value)


def _expression(operator, items):
    values = set()
    for value in items:
        if value[0] == "unresolved":
            return value
        if value[0] == operator:
            values.update(value[1])
        else:
            values.add(value)
    # True under OR is True. Flattening/deduplication is not DNF expansion.
    if operator == "any" and ("all", ()) in values:
        return ("all", ())
    if operator == 'all' and ('any',()) in values:
        return ('any',())
    # Keep shared prerequisites once: (A and B) or (A and C) has the
    # identical condition A and (B or C). This avoids expanding repeated
    # support in converging effect relations; no supplier branch is removed.
    opposite='all' if operator=='any' else 'any'
    if len(values)>1:
        terms=[set(v[1]) if v[0]==opposite else {v} for v in values]
        common=set.intersection(*terms)
        if common:
            remainder=_expression(operator,[_expression(opposite,part-common) for part in terms])
            return _expression(opposite,[*common,remainder])
        if operator=='any' and all(v[0]=='all' for v in values):
            occurrences=Counter(term for part in terms for term in part)
            shared=sorted((term for term,n in occurrences.items() if n>1),key=lambda term:(-occurrences[term],repr(term)))
            if shared:
                term=shared[0]
                containing=[part-{term} for part in terms if term in part]
                remaining=[v for v in values if term not in set(v[1])]
                grouped=_expression('all',[term,_expression('any',[_expression('all',part) for part in containing])])
                return _expression('any',[grouped,*remaining])
    return next(iter(values)) if len(values) == 1 else (operator, tuple(sorted(values, key=repr)))


def _weaker(left, right):
    """Sufficient structural implication for positive condition expressions."""
    if left == right or left == ("all", ()):
        return True
    if left[0] == "all":
        return all(_weaker(v, right) for v in left[1])
    if right[0] == "any":
        return all(_weaker(left, v) for v in right[1])
    if left[0] == "any":
        return any(_weaker(v, right) for v in left[1])
    if right[0] == "all":
        return any(_weaker(left, v) for v in right[1])
    return False


def _merge_usage(rows):
    result = {}
    for row in rows:
        for pool, entries in row.items():
            target = result.setdefault(pool, {})
            for token, amount in entries.items():
                target[token] = max(target.get(token, 0), amount)
    return result


def _demand(entries):
    return max(sum(v for k, v in entries.items() if not k.startswith("presence:")),
               max((v for k, v in entries.items() if k.startswith("presence:")), default=0))


def _common_usage(rows, token):
    if not rows:
        return {}
    pools = set.intersection(*(set(r) for r in rows))
    result = {}
    for p in pools:
        # Preserve shared activation identity where all alternatives agree.
        if all(r[p] == rows[0][p] for r in rows):
            result[p] = dict(rows[0][p])
        else:
            result[p] = {token: min(_demand(r[p]) for r in rows)}
    return result


def _possible_usage(rows, token):
    result = {}
    for p in set().union(*(set(r) for r in rows)):
        entries = [r[p] for r in rows if p in r]
        result[p] = dict(entries[0]) if all(e == entries[0] for e in entries) else {
            token: max(_demand(e) for e in entries)}
    return result


def _inventory(skeleton):
    copies = {c for m in skeleton.modules if m.selected for c in m.cards}
    return Counter((c.zone, c.card_id) for c in copies)


def _capacity(index, counts):
    result = {key: sum(counts[k] for k in pool.inventory) if pool.inventory else pool.capacity
              for key, pool in index.pools.items()}
    for key, pool in index.pools.items():
        if pool.count_inventory:
            result[key] *= sum(counts[k] for k in pool.count_inventory)
    for f in index.facts.values():
        if f.output_pool is None:
            amount = f.quantity
            if amount is not None and f.inventory_scaled:
                amount *= counts[(f.zone, f.card_id)]
            if f.card_id is not None and not counts[(f.zone, f.card_id)]:
                amount = 0
            key = "output:" + f.effect_ref + ":" + f.output.kind
            if key in result and result[key] is not None and amount is not None:
                result[key] = max(result[key], amount)
            else:
                result[key] = amount
    return result


def _zone_support(actual, required):
    if actual is None or required is None:
        return None
    if actual == required or required == "deck" and actual in ("deck_top", "deck_bottom"):
        return True
    if actual == "deck" and required in ("deck_top", "deck_bottom"):
        return None
    return False


def _transfer_available_zone(fact, counts, deck_events=1):
    destination = fact.transfer.destination
    quantity = fact.quantity
    if quantity is not None and fact.inventory_scaled:
        quantity *= counts[(fact.zone, fact.card_id)]
    # An unordered group at one end of the deck does not put every member in
    # the single end position. Other deck movements can change that position.
    if destination in ("deck_top", "deck_bottom") and (quantity != 1 or deck_events != 1):
        return "deck"
    return destination


def _usage_needs(index):
    pending = [(u.inputs, "use:" + u.use_id) for u in index.context.uses]
    pending.extend((f.inputs, "effect:" + f.effect_ref + ":" + f.choice) for f in index.facts.values() if f.inputs)
    result = {}
    while pending:
        item, prefix = pending.pop()
        if isinstance(item, InputGroup):
            pending.extend((v, prefix + ":" + str(i)) for i, v in enumerate(item.items))
        else:
            result[("presence:" if item.mode == "presence" else "consume:") + prefix + ":" + item.need_id] = item
    return result


def _pool_transfer(index, pid, fid, before):
    """Adapt complete legacy return assertions to the same physical check."""
    observed = index.facts[fid].transfer
    if observed is not None:
        return observed
    afters = [index.needs[r.after] for r in _recoveries(index.pools[pid])
              if r.fact_id == fid and before is not None and r.before == before.need_id]
    destinations = {n.resource.zone for n in afters}
    if (before is None or before.destination is None or not afters or len(destinations) != 1
            or None in destinations or not index.pools[pid].inventory):
        return None
    return ResourceTransfer('legacy ordered return: '+index.facts[fid].source, before.destination,
        next(iter(destinations)), 'self', 'self', 'targeted', index.pools[pid].inventory, 'rule')


def _allocate_transfer_inventory(result, index, counts, active, schedule, returns, selectors, selections, ports):
    """Prepare finite per-copy state views, then use the shared allocator.

    Choosing return identities is the same bounded outer branching as choosing
    return quantities. Every reservation, fee and overlap is still solved by
    solve_requirements; no returned stock or additional physical copy is made.
    """
    from .multifactor.conditions import ConditionGroup, Resource as Stock, STAGES, _next_combination
    needs = _usage_needs(index)
    groups, options = [], []
    incomplete = False
    for (pid, token), rows in sorted(returns.items()):
        for amount, release, fid in rows:
            before = needs.get(token)
            transfer = _pool_transfer(index, pid, fid, before)
            if (transfer is None or before is None or before.resource.zone is None
                    or transfer.destination is None or transfer.inventory is None or not index.pools[pid].inventory):
                result["unknown"].append("recovery_transfer_state_unresolved:" + fid)
                return
            slots = [(card, copy) for card in sorted(set(index.pools[pid].inventory) & set(transfer.inventory))
                     for copy in range(counts[card])]
            groups.append((pid, token, release, fid, before, transfer))
            options.append((slots, amount))
    members = sorted({card for p in active for card in index.pools[p].inventory})
    if sum(counts[c] for c in members) > 512:
        result["unknown"].append("inventory_allocation_budget")
        return
    record, work = _allocation_record(index, 'transfer-identities',
        (result, groups, options, schedule, ports))
    if not record:
        record.update(cursor=[list(range(amount)) for slots, amount in options]
            if all(len(slots) >= amount for slots, amount in options) else None,
            incomplete=False, transfer_failures=[])
    transfer_failures = record['transfer_failures']
    def advance():
        cursor = record['cursor']
        for i in range(len(cursor) - 1, -1, -1):
            next_indices = _next_combination(cursor[i], len(options[i][0]))
            if next_indices is not None:
                record['cursor'] = cursor[:i] + [next_indices] + [
                    list(range(amount)) for _slots, amount in options[i + 1:]]
                record.pop('started', None)
                return
        record['cursor'] = None
        record.pop('started', None)
    deck_events = len({fid for _, _, _, fid, _, t in groups if t.destination in ("deck", "deck_top", "deck_bottom")})
    while record['cursor'] is not None:
        if work is not None:
            work.tick(record)
        chosen = [tuple(slots[i] for i in indices) for (slots, _amount), indices in zip(options, record['cursor'])]
        movements = defaultdict(list)
        for group, slots in zip(groups, chosen):
            for slot in slots:
                movements[slot].append(group)
        profiles, transitions, pending = {}, [], []
        valid = True
        for slot, events in sorted(movements.items()):
            events.sort(key=lambda g: (g[2], g[1], g[3]))
            zone, start, leave, leave_source, leave_fact = events[0][4].resource.zone, 0, None, None, None
            segments = []
            for pid, token, release, fid, before, transfer in events:
                ready = _zone_support(zone, before.resource.zone)
                if schedule[token] + 1 < start or ready is False:
                    valid = False
                    break
                destination = before.destination
                if zone == "field" and leave is not None and destination != "field":
                    if destination in ("grave", "hand", "deck", "deck_top", "deck_bottom", "extra", "banished"):
                        destination = leave
                    else:
                        pending.append("recovery_transfer_leave_destination:" + fid)
                        destination = None
                origin = _zone_support(destination, transfer.origin)
                if origin is False:
                    if len(transfer_failures) < 16:
                        failure = dict(fact_id=fid, before=token,
                            slot=(f"physical:{slot[0][0]}:{slot[0][1]}", slot[1]),
                            declared_destination=before.destination, consumed_destination=destination,
                            required_origin=transfer.origin, leave_fact_id=leave_fact, leave_source=leave_source)
                        if failure not in transfer_failures:
                            transfer_failures.append(failure)
                    valid = False
                    break
                if ready is None or origin is None:
                    pending.append("recovery_transfer_origin_or_position:" + fid)
                segments.append((start, release, zone))
                transitions.append(dict(fact_id=fid, pool_id=pid, before=token,
                    slot=(f"physical:{slot[0][0]}:{slot[0][1]}", slot[1]),
                    consumed_zone=zone, declared_destination=before.destination,
                    consumed_destination=destination, origin=transfer.origin, destination=transfer.destination,
                    available_zone=transfer.destination if index.facts[fid].transfer is None else _transfer_available_zone(index.facts[fid], counts, deck_events),
                    leave_destination=leave, leave_source=leave_source, leave_fact_id=leave_fact))
                if not (zone == transfer.destination == destination == "field"):
                    leave, leave_source, leave_fact = None, None, None
                if transfer.leave_destination is not None:
                    leave, leave_source, leave_fact = transfer.leave_destination, transfer.leave_source, fid
                zone = transfer.destination if index.facts[fid].transfer is None else _transfer_available_zone(index.facts[fid], counts, deck_events)
                start = release + 1
            if not valid:
                break
            segments.append((start, 3, zone))
            profiles[slot] = segments
        if not valid:
            advance()
            continue
        stock, slot_names = [], {}
        for card in members:
            aliases = tuple(p for p in sorted(active) if card in index.pools[p].inventory)
            wanted = {needs[t].resource.zone for p, t, _ in ports if p in aliases and t in needs}
            for copy in range(counts[card]):
                slot = card, copy
                physical = f"physical:{card[0]}:{card[1]}:copy:{copy}"
                slot_names[physical] = (f"physical:{card[0]}:{card[1]}", copy)
                selected_aliases = tuple(selectors[p, t, fid] for (p, t, _, fid, _, _), selected in zip(groups, chosen)
                                         if slot in selected)
                pids = aliases + selected_aliases
                # Unmoved copies retain the host's explicitly supplied access
                # views. Moved copies have exactly one known zone per segment.
                segments = profiles.get(slot, [(0, 3, z) for z in sorted(wanted or {None}, key=repr)])
                for start, end, zone in segments:
                    if start > end:
                        continue
                    for view in sorted({zone, *wanted}, key=repr):
                        supported = _zone_support(zone, view) if view is not None else True
                        if supported is False:
                            continue
                        stock.append(Stock("inventory", pids[0], 1, selectors=pids,
                            pool_id=physical, resource_id=physical, stage=STAGES[start],
                            available_until=STAGES[end], state_zone=view, known=supported is True,
                            source="sourced physical transfer"))
        for p in sorted(active):
            pool = index.pools[p]
            if not pool.inventory:
                stock.append(Stock("inventory", p, pool.capacity, pool_id="logical:" + p,
                    available_until="post_resolution", source=pool.source))
        if len(stock) > 512:
            record['incomplete'] = True
            advance()
            continue
        children = tuple(replace(c, state_zone=needs[t].resource.zone)
                         if index.pools[p].inventory and t in needs else c for p, t, c in ports)
        while len(children) > 16:
            children = tuple(ConditionGroup("all", children[i:i+16]) for i in range(0, len(children), 16))
        allocation = _shared_allocation(index, ConditionGroup('all', children), tuple(stock), existential=True)
        if allocation["satisfied"] is True:
            witness = next(b for b in allocation["branches"] if b["satisfied"] is True)
            if pending:
                record['incomplete'] = True
                advance()
                continue
            result["recovery_allocation"] = [dict(r, slot=slot_names.get(r["slot"][0], r["slot"]))
                                              for r in witness["matched_resources"]]
            result["return_selections"] = selections
            result["transfer_states"] = transitions
            return
        record['incomplete'] |= allocation['satisfied'] is None
        advance()
    if incomplete or record['incomplete']:
        result["unknown"].append("recovery_transfer_state_or_allocation_budget")
    else:
        result["conflicts"].append(dict(pool="physical_inventory", reason="distinct_integer_state_allocation",
            transfer_failures=transfer_failures))


def _allocate_inventory_usage(result, index, counts, schedule=None, returns=None):
    """Map overlapping selector pools to the existing integer allocator."""
    from .multifactor.conditions import Condition, ConditionGroup, Resource as Stock, STAGES
    active = {p: entries for p, entries in result["usage"].items()
              if entries and p in index.pools and (index.pools[p].inventory or schedule is not None)}
    if not active:
        return
    members = sorted({card for p in active for card in index.pools[p].inventory})
    if (len(members) > 512 or len(active) > 128 or any(counts[c] > 99 for c in members)
            or any(n > 4096 for entries in active.values() for n in entries.values())):
        result["unknown"].append("inventory_allocation_budget")
        return
    return_selectors, selections = {}, {}
    usage_needs = _usage_needs(index)
    for (pid, token), released in sorted((returns or {}).items()):
        for _, _, fid in released:
            transfer = _pool_transfer(index, pid, fid, usage_needs.get(token))
            if transfer is not None and transfer.inventory is not None and index.pools[pid].inventory:
                alias = "return-selection:" + str(len(return_selectors))
                return_selectors[pid, token, fid] = alias
                selections[alias] = dict(fact_id=fid, pool_id=pid, before=token, inventory=transfer.inventory)
    aliases = {card: tuple(p for p in sorted(active) if card in index.pools[p].inventory) + tuple(
        alias for (pid, _, _), alias in return_selectors.items()
        if card in index.pools[pid].inventory and card in selections[alias]["inventory"]) for card in members}
    if any(len(pids) > 128 for pids in aliases.values()):
        result["unknown"].append("inventory_allocation_budget")
        return
    stock = tuple(Stock("inventory", pids[0], counts[card], selectors=pids,
        pool_id=f"physical:{card[0]}:{card[1]}", resource_id=f"physical:{card[0]}:{card[1]}",
        available_until="post_resolution", source="candidate inventory")
        for card in members if counts[card]
        for pids in [aliases[card]])
    for p in sorted(active):
        pool = index.pools[p]
        if not pool.inventory:
            if pool.capacity is None or pool.capacity > 99:
                result["unknown"].append("recovery_allocation_budget:" + p)
                return
            stock += (Stock("inventory", p, pool.capacity, pool_id="logical:"+p,
                available_until="post_resolution", source=pool.source),)
    needs, ports = [], []
    for p, entries in sorted(active.items()):
        for token, n in sorted(entries.items()):
            if token.startswith("presence:"):
                needs.append(Condition("inventory", p, n, consume_mode="reusable"))
                ports.append((p, token, needs[-1]))
                continue
            start = STAGES[(schedule or {}).get(token, 0) + 1]
            released = (returns or {}).get((p, token), ())
            for amount, after, fid in released:
                needs.append(Condition("inventory", return_selectors.get((p, token, fid), p), amount, stage=start,
                    consume_mode="occupy", until_stage=STAGES[after]))
                ports.append((p, token, needs[-1]))
            remaining = n - sum(amount for amount, _, _ in released)
            if remaining:
                needs.append(Condition("inventory", p, remaining, stage=start))
                ports.append((p, token, needs[-1]))
    needs = tuple(needs)
    if len(stock) > 512 or any(s.quantity > 99 for s in stock) or any(n.quantity > 4096 for n in needs):
        result["unknown"].append("inventory_allocation_budget")
        return
    if any(index.facts[fid].transfer is not None for rows in (returns or {}).values() for _, _, fid in rows):
        return _allocate_transfer_inventory(result, index, counts, active, schedule, returns,
            return_selectors, selections, ports)
    children = needs
    while len(children) > 16:
        children = tuple(ConditionGroup("all", children[i:i+16]) for i in range(0, len(children), 16))
    allocation = _shared_allocation(index, ConditionGroup("all", children), stock, existential=True)
    if allocation["satisfied"] is False:
        result["conflicts"].append(dict(pool="physical_inventory", reason="distinct_integer_allocation"))
    elif allocation["satisfied"] is None:
        result["unknown"].append("inventory_allocation_budget")
    else:
        result['inventory_allocation'] = allocation['branches'][0]['matched_resources']
    if allocation['satisfied'] is True and schedule is not None:
        result["recovery_allocation"] = allocation["branches"][0]["matched_resources"]
        if selections:
            result["return_selections"] = selections


def _check_static_usage(result, index, capacities):
    for pid, entries in result["usage"].items():
        amount, capacity = _demand(entries), capacities.get(pid)
        if capacity is None:
            result["unknown"].append("capacity:" + pid)
        elif amount > capacity:
            result["conflicts"].append({"pool": pid, "required": amount, "capacity": capacity})
    counts = getattr(index, "_active_counts", None)
    if counts is not None:
        _allocate_inventory_usage(result, index, counts)
    return result


def _recovery_allocations(selected, usage, index, budget, *, work_state=None, work=None):
    """Bound integer releases by both the event total and its prior consumers."""
    groups = sorted({(r.fact_id, pid, before) for pid, r, before, _, _ in selected})
    quantities = {fid: index.facts[fid].quantity for fid, _, _ in groups}
    for fid, quantity in tuple(quantities.items()):
        fact = index.facts[fid]
        if quantity is None:
            return [None], False, 1
        if fact.inventory_scaled:
            quantities[fid] *= index._active_counts[(fact.zone, fact.card_id)]
    state = work_state if work_state is not None else {}
    if not state:
        state.update(stack=[dict(position=0, plan=[])], plans=[], steps=0)
    pending, plans, steps = state['stack'], state['plans'], 0
    while pending:
        if work is not None:
            work.check()
            work.remaining -= 1
            work.steps += 1
        elif steps >= budget:
            return [{tuple(key): n for key, n in plan} for plan in plans], True, steps
        steps += 1
        state['steps'] += 1
        frame = pending[-1]
        position, plan = frame['position'], frame['plan']
        if position == len(groups):
            pending.pop()
            plans.append(plan)
            continue
        fid, pid, before = key = groups[position]
        maximum = min(quantities[fid] - sum(n for (f, _, _), n in plan if f == fid),
            usage[pid][before] - sum(n for (_, p, b), n in plan if (p, b) == (pid, before)))
        amount = frame.setdefault('amount', 1)
        if amount <= maximum:
            frame['amount'] += 1
            pending.append(dict(position=position + 1, plan=plan + [[list(key), amount]]))
        else:
            pending.pop()
    return [{tuple(key): n for key, n in plan} for plan in plans], False, steps


def _check_recovery_transfer(value, pid, recovery, index, deck_events=1):
    transfer = index.facts[recovery.fact_id].transfer
    if transfer is None:
        return  # Existing typed return assertions retain their established meaning.
    suffix = ":" + recovery.fact_id
    for label in ("owner", "controller"):
        party = getattr(transfer, label)
        if party == "opponent":
            value["conflicts"].append(dict(pool=pid, reason="recovery_transfer_" + label + "_mismatch"))
        elif party != "self":
            value["unknown"].append("recovery_transfer_" + label + suffix)
    before, after = index.needs[recovery.before], index.needs[recovery.after]
    if transfer.destination is None or before.resource.zone is None:
        value["unknown"].append("recovery_transfer_destination" + suffix)
    # The per-copy lifecycle checks the actual origin, including a preceding
    # summon event's leave replacement. A declared default destination alone
    # cannot decide that entity's resulting zone.
    if transfer.origin is None or before.destination is None:
        value["unknown"].append("recovery_transfer_origin" + suffix)
    next_zone = _zone_support(_transfer_available_zone(index.facts[recovery.fact_id], index._active_counts, deck_events),
                             after.resource.zone)
    if next_zone is None:
        value["unknown"].append("recovery_transfer_next_zone_or_position" + suffix)
    elif next_zone is False:
        value["conflicts"].append(dict(pool=pid, reason="recovery_transfer_next_zone_mismatch"))
    if transfer.reason not in ("effect", "cost", "rule"):
        value["unknown"].append("recovery_transfer_reason" + suffix)
    if transfer.selection != "targeted":
        value["unknown"].append("recovery_transfer_selection" + suffix)
    if not index.pools[pid].inventory or transfer.inventory is None:
        value["unknown"].append("recovery_transfer_inventory" + suffix)
    elif not set(index.pools[pid].inventory) & set(transfer.inventory):
        value["conflicts"].append(dict(pool=pid, reason="recovery_transfer_entity_mismatch"))


@_cached_allocation(3, (0, 1, 2))
def _recovery_branch(result, selected, amounts, index, capacities):
    """One node per sourced event; finite releases reuse the existing stock."""
    value = _usage_input(result)
    value.pop("branches", None)
    source_states, prerequisite_schedules = {}, set()
    for _, recovery, _, _, state in selected:
        if state.get("recovery_returns") or (state.get("resource_base") and
                set(state["unknown"]) - set(state["resource_base"]["unknown"])):
            prerequisite_schedules.add(recovery.fact_id)
        state = _usage_input(state)
        if recovery.fact_id in source_states and source_states[recovery.fact_id] != state:
            value["conflicts"].append(dict(pool="recovery_source", reason="incompatible_return_alternatives"))
            return _usage_result(value, result, capacities)
        source_states[recovery.fact_id] = state
    for fid, state in source_states.items():
        for key in ("conditions", "unknown", "suppliers", "bottlenecks"):
            value[key] = sorted(set(value[key]) | set(state[key]))
        value["suppliers"] = sorted(set(value["suppliers"]) | {fid})
        for key in ("support_expression", "condition_expression"):
            value[key] = _expression("all", [value[key], state[key]])
        value["usage"] = _merge_usage((value["usage"], state["usage"]))
        if state["status"] == "unknown" and value["status"] == "supported":
            value["status"] = "unknown"
    value["possible_usage"] = deepcopy(value["usage"])
    base = deepcopy(value)
    deck_events = len({r.fact_id for _, r, _, _, _ in selected if index.facts[r.fact_id].transfer is not None
                       and index.facts[r.fact_id].transfer.destination in ("deck", "deck_top", "deck_bottom")})
    for pid, recovery, _, _, _ in selected:
        _check_recovery_transfer(value, pid, recovery, index, deck_events)
    if value["conflicts"]:
        return _usage_result(value, base, capacities)
    if amounts is None:
        value["unknown"].extend("recovery_quantity:" + fid for fid in source_states
                                if index.facts[fid].quantity is None)
        return _usage_result(value, base, capacities)
    edges, releases = [], defaultdict(list)
    tokens = {t for entries in value["usage"].values() for t in entries if not t.startswith("presence:")}
    events = {fid: "return:" + fid for fid in source_states}
    for pid, recovery, before, after, _ in selected:
        state, event = source_states[recovery.fact_id], events[recovery.fact_id]
        edges.extend(((before, event, 0), (event, after, 1)))
        costs = {t for entries in state["usage"].values() for t in entries if not t.startswith("presence:")}
        overlap = any(p in state["possible_usage"] for p in index.pools
                      if p == pid or set(index.pools[p].inventory) & set(index.pools[pid].inventory))
        if overlap and recovery.cost_timing == "unspecified":
            value["unknown"].append("recovery_cost_order:" + recovery.fact_id)
        for token in costs:
            edges.append((token, event, 0))
            if recovery.cost_timing == "before":
                edges.append((token, before, 1))
            elif recovery.cost_timing == "between":
                edges.append((before, token, 1))
    if any(v.startswith("recovery_cost_order:") for v in value["unknown"]):
        return _usage_result(value, base, capacities)
    use_tokens = defaultdict(set)
    for use in index.context.uses:
        pending = [(use.inputs, "use:"+use.use_id)]
        while pending:
            group, prefix = pending.pop()
            if isinstance(group, InputGroup):
                pending.extend((item, prefix+":"+str(i)) for i, item in enumerate(group.items))
            elif group.mode == "consume":
                token = "consume:"+prefix+":"+group.need_id
                if token in tokens:
                    use_tokens[use.use_id].add(token)
    for constraint in index.context.constraints:
        if constraint.kind == "before":
            for left, right in zip(constraint.uses, constraint.uses[1:]):
                edges.extend((a, b, 1) for a in sorted(use_tokens[left]) for b in sorted(use_tokens[right]))
    schedule, remaining = {}, tokens | set(events.values())
    while remaining:
        ready = sorted(t for t in remaining if not any(b == t and a in remaining for a, b, _ in edges))
        if not ready:
            value["conflicts"].append(dict(pool="recovery_order", reason="inconsistent_recovery_order"))
            return _usage_result(value, base, capacities)
        for token in ready:
            schedule[token] = max((schedule[a] + distance for a, b, distance in edges if b == token), default=0)
        remaining -= set(ready)
    if max((schedule[t] for t in tokens), default=0) > 2:
        value["unknown"].append("recovery_stage_budget:" + ",".join(sorted(events)))
        return _usage_result(value, base, capacities)
    for (fid, pid, before), amount in amounts.items():
        releases[pid, before].append((amount, schedule[events[fid]] + 1, fid))
    returned, uncertain_order = dict(releases), False
    for pid, before in returned:
        # Unordered consumers may be legally placed after the return. A failed
        # simultaneous allocation cannot disprove that unassessed ordering.
        connected = {before}
        for _ in range(len(schedule)):
            expanded = connected | {b for a, b, _ in edges if a in connected} | {a for a, b, _ in edges if b in connected}
            if expanded == connected:
                break
            connected = expanded
        for p, entries in value["usage"].items():
            if p == pid or p in index.pools and set(index.pools[p].inventory) & set(index.pools[pid].inventory):
                uncertain_order |= any(t not in connected for t in entries if not t.startswith("presence:"))
    # Logical non-pool outputs remain single-use supplies; only explicitly
    # declared pools participate in temporal allocation.
    for p, entries in value["usage"].items():
        if p not in index.pools and capacities.get(p) is not None and _demand(entries) > capacities[p]:
            value["conflicts"].append(dict(pool=p, required=_demand(entries), capacity=capacities[p]))
    _allocate_inventory_usage(value, index, index._active_counts, schedule, returned)
    if uncertain_order and value["conflicts"]:
        optimistic = _blank("supported")
        optimistic["usage"] = deepcopy(value["usage"])
        for (p, token), rows in returned.items():
            amount = sum(n for n, _, _ in rows)
            optimistic["usage"][p][token] -= amount
            if not optimistic["usage"][p][token]:
                del optimistic["usage"][p][token]
            optimistic["usage"][p]["presence:returned:"+token] = amount
        _check_static_usage(optimistic, index, capacities)
        if not optimistic["conflicts"]:
            value["conflicts"] = []
            value["unknown"].append("recovery_order:unsequenced_consumption:" + ",".join(sorted(tokens)))
    if prerequisite_schedules and value["conflicts"] and all(
            c["pool"] == "physical_inventory" for c in value["conflicts"]):
        # The selected return's own proof may need a different return schedule.
        # This allocation did not enumerate that extra event, so its failed
        # simultaneous placement cannot disprove the full prerequisite graph.
        value["conflicts"] = []
        value["unknown"].append("recovery_prerequisite_schedule:" + ",".join(sorted(prerequisite_schedules)))
    value["recovery_returns"] = [dict(fact_id=fid, pool_id=pid, before=before, quantity=amount,
        release_stage=schedule[events[fid]] + 1,
        **({"transfer": asdict(index.facts[fid].transfer)} if index.facts[fid].transfer is not None else {}))
        for (fid, pid, before), amount in sorted(amounts.items())]
    return _usage_result(value, base, capacities)


@_cached_allocation(1, (0,))
def _check_usage(result, index, capacities, states):
    result = _usage_input(result)
    if result["condition_expression"][0] == "unresolved":
        result["unknown"].append("condition_expression_budget")
    checked = _check_static_usage(deepcopy(result), index, capacities)
    if checked["conflicts"] and not result["conflicts"]:
        candidates, fallback = [], []
        tokens = {t for entries in result["usage"].values() for t in entries if t.startswith("consume:")}
        for pid, pool in sorted(index.pools.items()):
            if pid not in result["usage"]:
                continue
            if pool.reusable_if and not pool.recovery_between and states.get(pool.reusable_if, {}).get("status") != "missing":
                fallback.append("recovery_order:" + pid)
            for recovery in _recoveries(pool):
                before = [t for t in result["usage"][pid] if t.startswith("consume:") and t.endswith(":"+recovery.before)]
                after = [t for t in tokens if t.endswith(":"+recovery.after)]
                if (before and not after and recovery.after in index.needs
                        and states.get(recovery.fact_id, {}).get("status") != "missing"):
                    # A containing ALL may supply the named later consumer.
                    # This subgroup has not disproved that larger schedule.
                    fallback.append("recovery_order:" + pid + ":scope:" + recovery.after)
                if not before or not after:
                    continue
                if len(before) != 1 or len(after) != 1:
                    fallback.append("recovery_order:" + pid)
                    continue
                state = states.get(recovery.fact_id)
                if state is None:
                    fallback.append("recovery_support:" + pid)
                elif state["status"] != "missing":
                    options = [b for b in state.get("branches", [state]) if b["status"] != "missing"]
                    candidates.append([(pid, recovery, before[0], after[0], b) for b in options])
                    if state.get("branches_incomplete"):
                        fallback.append("recovery_branch_budget:" + pid)
        from .multifactor.conditions import _next_combination
        candidates = [rows for rows in candidates if rows]
        record, work = _allocation_record(index, 'recovery', (result, candidates))
        if not record:
            record.update(subset=[0] if candidates else None, choice=[0], rows=[], plan_cursor=0)
        rows = record['rows']
        while record['subset'] is not None:
            if work is not None:
                work.tick(record)
            subset = [candidates[i] for i in record['subset']]
            selected = tuple(options[i] for options, i in zip(subset, record['choice']))
            quantities, _ = _allocation_record(index, 'recovery-quantities', (selected, result['usage']))
            plans, incomplete, _steps = _recovery_allocations(selected, result['usage'], index,
                index.context.budget.allocations, work_state=quantities, work=work)
            if incomplete:
                fallback.append('recovery_quantity_budget')
            while record['plan_cursor'] < len(plans):
                rows.append(_recovery_branch(result, selected, plans[record['plan_cursor']], index, capacities))
                record['plan_cursor'] += 1
            choice = _next_product(record['choice'], [len(options) for options in subset])
            if choice is not None:
                record['choice'] = choice
            else:
                selected_indices = _next_combination(record['subset'], len(candidates))
                if selected_indices is None:
                    size = len(record['subset']) + 1
                    selected_indices = list(range(size)) if size <= len(candidates) else None
                record['subset'] = selected_indices
                record['choice'] = [0] * len(selected_indices or [])
            record['plan_cursor'] = 0
            record.pop('started', None)
        if fallback:
            unknown = deepcopy(result)
            unknown["unknown"].extend(fallback)
            rows.append(_usage_result(unknown, result, capacities))
        if rows:
            checked = _combine_summary(rows, "any", "recovery", index, capacities, states)
            checked["branches"] = [r for r in rows if r["status"] != "missing"] or rows
            return checked
    return _usage_result(checked, result, capacities)


@_cached_allocation(3, (0, 1, 2))
def _combine_summary(rows, operator, key, index, capacities, states):
    if not rows:
        return _blank("supported")
    result = _blank()
    if operator == "any":
        supported = [r for r in rows if r["status"] == "supported"]
        selected = supported or [r for r in rows if r["status"] == "unknown"] or rows
        result["status"] = "supported" if supported else "unknown" if any(
            r["status"] == "unknown" for r in rows) else "missing"
        result["usage"] = _common_usage([r["usage"] for r in selected], "alternative:" + key)
        result["possible_usage"] = _possible_usage([r["possible_usage"] for r in selected], "choice:" + key)
        # OR does not require its alternatives jointly. Allocation is checked by
        # a containing ALL, not against the union of alternative reservations.
        result["bottlenecks"] = sorted(set.intersection(*(set(r["bottlenecks"]) for r in selected)))
        result["alternatives"] = [r["conditions"] for r in selected]
        result["conditions"] = sorted(set.intersection(*(set(r["conditions"]) for r in selected)))
        result["condition_expression"] = _expression("any", [r["condition_expression"] for r in selected])
        result["support_expression"] = _expression("any", [r["support_expression"] for r in selected])
        for name in ("gaps", "unknown", "suppliers"):
            result[name] = sorted({v for r in selected for v in r[name]})
        if result["status"] == "missing":
            result["conflicts"] = [c for r in selected for c in r["conflicts"]]
        result["quantities"] = {k: v for r in selected for k, v in r["quantities"].items()}
        if result["condition_expression"][0] == "unresolved":
            result["unknown"].append("condition_expression_budget")
            if result["status"] == "supported":
                result["status"] = "unknown"
        return _unknown_support(result)
    rows = [_usage_input(r) for r in rows]
    result["status"] = "missing" if any(r["status"] == "missing" for r in rows) else "unknown" if any(
        r["status"] == "unknown" for r in rows) else "supported"
    for name in ("gaps", "unknown", "conditions", "suppliers", "bottlenecks"):
        result[name] = sorted({v for r in rows for v in r[name]})
    result["alternatives"] = [a for r in rows for a in r["alternatives"]]
    result["condition_expression"] = _expression("all", [r["condition_expression"] for r in rows])
    result["support_expression"] = _expression("all", [r["support_expression"] for r in rows])
    result["conflicts"] = [c for r in rows for c in r["conflicts"]]
    result["quantities"] = {k: v for r in rows for k, v in r["quantities"].items()}
    result["usage"] = _merge_usage(r["usage"] for r in rows)
    result["possible_usage"] = _merge_usage(r["possible_usage"] for r in rows)
    return _check_usage(result, index, capacities, states)


def _combine(rows, operator, key, index, capacities, states, *, existential=False):
    """Keep alternatives intact until the enclosing ALL checks their resources."""
    if not rows:
        return _blank("supported")
    record, work = _allocation_record(index, 'exists' if existential else 'combine', (rows, operator, key))
    if 'result' in record:
        return _restore_relation(deepcopy(record['result']))
    exhausted = any(r.get("branches_incomplete", False) for r in rows)
    options = [[{k: deepcopy(v) for k, v in b.items() if k not in ("branches", "branches_incomplete")}
                for b in r.get("branches", [r])] for r in rows]
    if not record:
        record.update(cursor=([0, 0] if operator == 'any' else [0] * len(options))
            if all(options) else None, branches=[])
    branches = record['branches']
    while record['cursor'] is not None:
        if work is not None and work.preview and any(b['status'] == 'supported' for b in branches):
            exhausted = True
            break
        # Old saves recorded the in-flight child's work in the outer memo.
        # Finish that choice there before starting a cursor-local memo.
        legacy_child = record.get('started') and 'child_operations' not in record
        if work is not None:
            try:
                work.tick(record)
            except _AllocationPending:
                if not work.preview:
                    raise
                exhausted = True
                break
        cursor = record['cursor']
        selected = [options[cursor[0]][cursor[1]]] if operator == 'any' else [
            choices[i] for choices, i in zip(options, cursor)]
        parent_operations = work.operations if work is not None else None
        parent_shared = work.shared_operations if work is not None else None
        if work is not None and not legacy_child:
            work.operations = record.setdefault('child_operations', {})
            # Identical allocator inputs can recur across distinct branches.
            if parent_shared is None:
                work.shared_operations = parent_operations
        try:
            branch = _combine_summary(list(selected), "all", key, index, capacities, states)
        except _AllocationPending:
            if work is None or not work.preview:
                raise
            exhausted = True
            break
        finally:
            if work is not None:
                work.operations = parent_operations
                work.shared_operations = parent_shared
        values = branch.get('branches', [branch])
        if existential:
            witness = next((value for value in values if value['status'] == 'supported'), None)
            if witness is not None:
                result = _combine_summary([witness], 'any', key, index, capacities, states)
                result['branches'] = [witness]
                record['result'] = deepcopy(result)
                return result
        branches.extend(values)
        if operator == 'any':
            row, item = cursor
            record['cursor'] = ([row, item + 1] if item + 1 < len(options[row]) else
                [row + 1, 0] if row + 1 < len(options) else None)
        else:
            record['cursor'] = _next_product(cursor, [len(v) for v in options])
        record.pop('child_operations', None)
        record.pop('started', None)
    result = _combine_summary(branches, 'any', key, index, capacities, states) if branches or not exhausted else _blank('unknown')
    # Failed branches cannot supply a later ALL. Keep uncertain branches even
    # when a known alternative exists: that known one may conflict downstream.
    result["branches"] = [b for b in branches if b["status"] != "missing"] or branches
    result["branches_incomplete"] = exhausted
    if exhausted and result["status"] != "supported":
        result["status"] = "unknown"
        result["unknown"].append("branch_allocation_budget:" + key)
        result["support_expression"] = ("atom", "branch_allocation_budget:" + key)
    result = _unknown_support(result)
    record['result'] = deepcopy(result)
    return result


def _next_product(cursor, sizes):
    result = list(cursor)
    for i in range(len(result) - 1, -1, -1):
        if result[i] + 1 < sizes[i]:
            result[i] += 1
            result[i + 1:] = [0] * (len(result) - i - 1)
            return result
    return None


def _map_branches(row, transform, key, index, capacities, states):
    branches = row.get("branches")
    if not branches:
        return transform(_usage_input(row))
    values = [transform(_usage_input(b)) for b in branches]
    result = _combine(values, "any", key, index, capacities, states)
    result["branches_incomplete"] |= row.get("branches_incomplete", False)
    if result["branches_incomplete"] and result["status"] != "supported":
        result["status"] = "unknown"
        result["unknown"].append("branch_allocation_budget:"+key)
        result["support_expression"] = ("atom", "branch_allocation_budget:"+key)
    return _unknown_support(result)


def _partial_allocations(partial, quantity, budget, *, work_state=None, work=None):
    """Enumerate bounded supply quantities; entity matching stays in the allocator.

    Alternatives from one output pool cannot be added together. Only suppliers
    actually selected by a quantity branch bring their prerequisites with them.
    """
    pools = sorted(partial)
    maximum = [max(v[0] for v in partial[p]) for p in pools]
    suffix = [0] * (len(pools) + 1)
    for i in range(len(pools) - 1, -1, -1):
        suffix[i] = suffix[i + 1] + maximum[i]
    state = work_state if work_state is not None else {}
    if not state:
        state.update(stack=[dict(position=0, remaining=quantity, selected=[])], allocations=[], steps=0)
    pending, allocations, steps = state['stack'], state['allocations'], 0
    while pending:
        if work is not None:
            work.check()
            work.remaining -= 1
            work.steps += 1
        elif steps >= max(0, budget):
            return [tuple((p, n, partial[p][i][1], partial[p][i][2]) for p, n, i in a)
                    for a in allocations], True
        steps += 1
        state['steps'] += 1
        frame = pending[-1]
        position, remaining, selected = frame['position'], frame['remaining'], frame['selected']
        if remaining == 0:
            pending.pop()
            allocations.append(selected)
            continue
        if position == len(pools) or suffix[position] < remaining:
            pending.pop()
            continue
        pool = pools[position]
        low = max(0, remaining - suffix[position + 1])
        if 'row' not in frame:
            frame.update(row=0, amount=max(1, low), skip=low == 0)
        row, amount = frame['row'], frame['amount']
        if row < len(partial[pool]):
            cap = min(partial[pool][row][0], remaining)
            if amount <= cap:
                frame['amount'] += 1
                pending.append(dict(position=position + 1, remaining=remaining - amount,
                    selected=selected + [[pool, amount, row]]))
            else:
                frame.update(row=row + 1, amount=max(1, low))
        elif frame['skip']:
            frame['skip'] = False
            pending.append(dict(position=position + 1, remaining=remaining, selected=selected))
        else:
            pending.pop()
    return [tuple((p, n, partial[p][i][1], partial[p][i][2]) for p, n, i in a) for a in allocations], False


@_cached_allocation(1, (0, 5, 6))
def _group(group, index, states, counts, capacities, prefix, blocked=None, *, existential=False):
    if group is None:
        return _blank("supported")
    if isinstance(group, InputGroup):
        from .construction_recognition import allocate_relation_group
        allocation = None if any(_recoveries(p) for p in index.pools.values()) else (
            allocate_relation_group(group, index, states, counts, capacities, prefix, blocked, existential=existential))
        if allocation is not None:
            if allocation["status"] == "missing":
                missing = [n.need_id for n in _needs(group)
                           if allocation["quantities"].get(n.need_id, {}).get("shortfall_lower", 0)]
                allocation["gaps"] = sorted(missing) or allocation["gaps"]
            return allocation
        return _combine([_group(v, index, states, counts, capacities, prefix + f":{i}", blocked)
                         for i, v in enumerate(group.items)], group.operator, prefix, index, capacities, states,
                        existential=existential)
    need = group
    rows = []
    partial = {}
    possible_amounts = {}
    unbounded = False
    for fid in index.matches.get(need.need_id, ()):
        fact = index.facts[fid]
        state = states[fid]
        if state["status"] == "missing":
            continue
        if blocked and blocked in state["suppliers"]:
            alternatives = [b for b in state.get("branches", [state]) if blocked not in b["suppliers"]]
            if not alternatives:
                continue
            state = _combine(alternatives, "any", prefix+":cycle-free", index, capacities, states)
        amount = fact.quantity
        if amount is not None and fact.inventory_scaled:
            amount *= counts[(fact.zone, fact.card_id)]
        capacity = capacities.get(fact.output_pool) if fact.output_pool else amount
        if amount is not None and capacity is not None:
            amount = min(amount, capacity)
        row = deepcopy(state)
        pool = fact.output_pool or "output:" + fact.effect_ref + ":" + fact.output.kind
        if amount is None:
            unbounded = True
        else:
            possible_amounts[pool] = max(possible_amounts.get(pool, 0), amount)
        if amount is None:
            row["status"] = "unknown"
            row["unknown"].append("supply_quantity:" + fid)
        capacities.setdefault(pool, amount)
        if amount is not None and amount < need.quantity:
            if amount > 0:
                partial.setdefault(pool, []).append((amount, row, fid))
            continue
        token = ("presence:" if need.mode == "presence" else "consume:") + prefix + ":" + need.need_id
        def reserve(branch):
            if amount is None:
                branch["status"] = "unknown"
                branch["unknown"].append("supply_quantity:"+fid)
                branch["support_expression"] = _expression("all", [branch["support_expression"], ("atom", "quantity:"+fid)])
            branch["usage"] = _merge_usage((branch["usage"], {pool: {token: need.quantity}}))
            branch["possible_usage"] = deepcopy(branch["usage"])
            branch["suppliers"] = sorted(set(branch["suppliers"]) | {fid})
            branch["bottlenecks"] = sorted(set(branch["bottlenecks"]) | {pool})
            return _check_usage(branch, index, capacities, states)
        rows.append(_map_branches(row, reserve, prefix, index, capacities, states))
    total = sum(max(v[0] for v in options) for options in partial.values())
    if total >= need.quantity:
        allocation_state, work = _allocation_record(index, 'partial', (partial, need.quantity))
        allocations, exhausted = _partial_allocations(partial, need.quantity, index.context.budget.allocations,
            work_state=allocation_state, work=work)
        for selected in allocations:
            joint = _combine([v[2] for v in selected], "all", need.need_id, index, capacities, states)
            def reserve_partial(branch):
                for pool, amount, _, fid in selected:
                    token = ("presence:" if need.mode == "presence" else "consume:") + prefix + ":" + need.need_id
                    branch["usage"] = _merge_usage((branch["usage"], {pool: {token: amount}}))
                    branch["suppliers"] = sorted(set(branch["suppliers"]) | {fid})
                branch["possible_usage"] = deepcopy(branch["usage"])
                return _check_usage(branch, index, capacities, states)
            rows.append(_map_branches(joint, reserve_partial, prefix+":quantity", index, capacities, states))
        if exhausted:
            unresolved = _blank("unknown")
            unresolved["unknown"] = ["quantity_subset_allocation:" + need.need_id]
            rows.append(_unknown_support(unresolved))
    unclassified = [c for c in index.unresolved_cards if counts[("main", c)] or counts[("extra", c)]]
    uncertain_scope = need.need_id in index.incomplete_needs or bool(unclassified) or unbounded
    upper = None if uncertain_scope else sum(possible_amounts.values())
    if not rows:
        result = _blank("unknown" if uncertain_scope or upper >= need.quantity else "missing", need.need_id)
        if need.need_id in index.incomplete_needs:
            result["unknown"] = ["budget_uncovered:" + need.need_id]
        result["unknown"].extend("unclassified_catalog_effect:" + str(c) for c in unclassified)
        if result["status"] == "unknown" and not result["unknown"]:
            result["unknown"].append("conditional_quantity_supply:" + need.need_id)
    else:
        result = _combine(rows, "any", prefix + ":" + need.need_id, index, capacities, states, existential=existential)
    result["quantities"][need.need_id] = {"required": need.quantity, "capacity_upper": upper,
        "shortfall_lower": None if upper is None else max(0, need.quantity-upper)}
    return _unknown_support(result)


@dataclass
class RelationEvaluation:
    data: dict
    index: RelationIndex = field(repr=False)
    counts: Counter = field(repr=False)
    fact_states: dict = field(repr=False)
    use_states: dict = field(repr=False)

    def to_dict(self):
        return deepcopy(self.data)


def order_possible(members, edges):
    """The shared finite before-constraint check used by static relations."""
    members = set(members)
    outgoing = defaultdict(set)
    indegree = dict.fromkeys(members,0)
    for a,b in set(edges):
        if a in members and b in members:
            outgoing[a].add(b)
            indegree[b] += 1
    ready = [u for u in members if not indegree[u]]
    visited = 0
    while ready:
        visited += 1
        for target in outgoing[ready.pop()]:
            indegree[target] -= 1
            if not indegree[target]:
                ready.append(target)
    return visited==len(members)


def evaluate_relations(skeleton, context, index, *, previous=None, inventory_counts=None,
                       continuation=None, should_stop=None, resumable=False, existential=False):
    """Least supported closure on a finite graph; no source means no support.

    A previous evaluation reuses unaffected states, not a second matching pass.
    Shared usage and probabilities are cheap global summaries of current states.
    """
    ctx = _context(context)
    if existential and (len(ctx.uses) != 1 or not ctx.uses[0].required or ctx.constraints):
        raise ContractError('existence-only relation evaluation requires one isolated use')
    if not isinstance(index, RelationIndex) or index.context != ctx:
        raise ContractError("relation index belongs to another context")
    if index.name_groups != getattr(context, "same_name_groups", ()):
        raise ContractError("same-name identities changed; rebuild the relation index")
    for code, snapshot in index.catalog_snapshot.items():
        row = index.catalog.assets.rows.get(code, {})
        if snapshot != (row.get("desc"), row.get("alias"), row.get("type")):
            raise ContractError("catalog facts changed; rebuild the affected relation index")
    if hasattr(context, "task"):
        from .construction_layers import _inventory as validate_inventory
        validate_inventory(skeleton, context)
    started = perf_counter()
    counts = _inventory(skeleton) if inventory_counts is None else Counter(inventory_counts)
    if inventory_counts is not None and (hasattr(context, "task")
            or previous is not None and previous.data.get('inventory_projection') is None
            or any(z not in ("main", "extra") or type(n) is not int or n < 0 for (z, _), n in counts.items())):
        raise ContractError("direction inventory projection requires isolated static relation context")
    if inventory_counts is not None:
        physical = Counter(skeleton.inventory.main+skeleton.inventory.extra+skeleton.inventory.side)
        projected = Counter()
        for (_, code), n in counts.items():
            projected[code] += n
        if any(n > physical[code] for code,n in projected.items()):
            raise ContractError("direction projection cannot invent physical copies")
    index._active_counts = counts
    capacities = _capacity(index, counts)
    affected = {"fact:" + fid for fid in index.facts} | {"use:" + u.use_id for u in ctx.uses}
    reused = False
    if previous is not None and previous.index is index and not previous.data["budget"]["update_exhausted"]:
        changed = {k for k in counts.keys() | previous.counts.keys() if counts[k] != previous.counts[k]}
        changed_pools = {pid for pid, p in index.pools.items() if (set(p.inventory)|set(p.count_inventory)) & changed}
        affected = {"fact:" + fid for fid, f in index.facts.items() if (f.zone, f.card_id) in changed
                    or f.output_pool in changed_pools or any(c.pool_id in changed_pools for c in f.claims)}
        pending = deque(affected)
        if any(code in index.unresolved_cards for _, code in changed):
            affected = {"fact:" + fid for fid in index.facts} | {"use:" + u.use_id for u in ctx.uses}
            pending = deque(affected)
        while pending:
            owner = pending.popleft()
            if owner.startswith("fact:"):
                for target in index.dependents.get(owner[5:], ()):
                    if target not in affected:
                        affected.add(target)
                        pending.append(target)
        reused = True
    from .build_contracts import digest
    binding=digest(dict(facts=[asdict(f) for f in index.facts.values()],uses=[asdict(u) for u in ctx.uses],
        pools=[asdict(p) for p in index.pools.values()],constraints=[asdict(c) for c in ctx.constraints],
        inventory=sorted((z,c,n) for (z,c),n in counts.items()),
        **({'existential': True} if existential else {})))
    def same_state(left, right):
        # Allocation witnesses contain ordered tuples; JSON represents them
        # as lists. That representation change is not a new resource fact.
        if isinstance(left,dict) and isinstance(right,dict):
            return left.keys()==right.keys() and all(same_state(v,right[k]) for k,v in left.items())
        if isinstance(left,(list,tuple)) and isinstance(right,(list,tuple)):
            return len(left)==len(right) and all(same_state(a,b) for a,b in zip(left,right))
        return left==right
    if continuation is not None:
        if (continuation.get('version') not in ('relation-updates-v1', 'relation-updates-v2') or continuation.get('binding')!=binding
                or set(continuation.get('states',{}))!=set(index.facts)
                or not set(continuation.get('queue',()))<=set(index.facts)):
            raise ContractError('relation update continuation belongs to a different inventory or graph')
        states=_restore_relation(continuation['states']);queue=deque(continuation['queue'])
    else:
        states = {fid: deepcopy(previous.fact_states[fid]) if reused and "fact:" + fid not in affected
                  else _blank("missing", "unseeded_or_missing_input:" + fid) for fid in index.facts}
        queue = deque(sorted(o[5:] for o in affected if o.startswith("fact:")))
    uses = _restore_relation(deepcopy(continuation.get('uses', {}))) if continuation else {}
    joint_groups = _restore_relation(deepcopy(continuation.get('joint_groups', {}))) if continuation else {}
    active = _restore_relation(deepcopy(continuation.get('active'))) if continuation else None
    use_cursor = continuation.get('use_cursor', 0) if continuation else 0
    joint_cursor = continuation.get('joint_cursor', 0) if continuation else 0
    prior_allocation_steps = continuation.get('allocation_steps', 0) if continuation else 0
    work = _AllocationWork(ctx.budget.allocations, should_stop)
    queued, updates, allocation_pending = set(queue), 0, False
    joint_definitions = [('required-uses', [u.use_id for u in ctx.uses if u.required])] + [
        (c.constraint_id, list(c.uses)) for c in ctx.constraints if c.kind == 'all']

    def unit(kind, identity, compute):
        nonlocal active
        if active is None:
            active = dict(kind=kind, identity=identity, operations={})
        if active['kind'] != kind or active['identity'] != identity:
            raise ContractError('relation allocation continuation has an inconsistent active unit')
        work.operations = active['operations']
        index._allocation_work = work
        value = compute()
        active = None
        return value

    def fact_value(fid):
        f = index.facts[fid]
        if f.card_id is not None and not counts[(f.zone, f.card_id)]:
            return _blank('missing', 'component:' + fid)
        value = _group(f.inputs, index, states, counts, capacities, 'effect:' + f.effect_ref + ':' + f.choice, fid)
        def activate(branch):
            branch['conditions'] = sorted(set(branch['conditions']) | set(f.conditions))
            branch['condition_expression'] = _expression('all', [branch['condition_expression'],
                *(('atom', condition) for condition in f.conditions)])
            branch['unknown'] = sorted(set(branch['unknown']) | set(f.unknown))
            branch['support_expression'] = _expression('all', [branch['support_expression'],
                *(('atom', 'fact:' + fid + ':' + v) for v in f.unknown)])
            claims = {c.pool_id: {('presence:' if c.mode == 'presence' else 'activation:') +
                f.effect_ref + ':' + f.choice: c.quantity} for c in f.claims}
            branch['usage'] = _merge_usage((branch['usage'], claims))
            branch['possible_usage'] = deepcopy(branch['usage'])
            branch['bottlenecks'] = sorted(set(branch['bottlenecks']) | set(claims))
            return _check_usage(branch, index, capacities, states)
        return _map_branches(value, activate, fid, index, capacities, states)

    def joint_value(key, members):
        if existential:
            return uses[members[0]]
        # A terminal joint needs an existence proof, rather than the Cartesian
        # product of every use's complete witness set. Direct, unconditional
        # supplies are already supported by the same shared allocator.
        if members and not any(_recoveries(p) for p in index.pools.values()):
            from .construction_recognition import allocate_relation_group
            inputs = tuple(u.inputs for u in ctx.uses if u.use_id in members)
            needs = [n.need_id for group in inputs for n in _needs(group)]
            pending, size, depth = [(group, 1) for group in inputs], 1, 0
            while pending:
                item, level = pending.pop()
                size += 1
                depth = max(depth, level)
                if isinstance(item, InputGroup):
                    pending.extend((child, level + 1) for child in item.items)
            if len(needs) == len(set(needs)) and size <= 2048 and depth <= 16:
                value = allocate_relation_group(InputGroup('all', inputs), index, states, counts, capacities,
                    key, existential=True)
                if value is not None:
                    return value
        return _combine([uses[uid] for uid in members], 'all', key, index, capacities, states)

    try:
        while queue and updates < ctx.budget.updates:
            if should_stop is not None and should_stop():
                break
            fid = queue[0]
            value = unit('fact', fid, lambda: fact_value(fid))
            queue.popleft()
            queued.remove(fid)
            updates += 1
            if value != states[fid] and not same_state(value, states[fid]):
                states[fid] = value
                for owner in sorted(index.dependents.get(fid, ())):
                    if owner.startswith('fact:') and owner[5:] not in queued:
                        queue.append(owner[5:])
                        queued.add(owner[5:])
        if not queue:
            while use_cursor < len(ctx.uses):
                if should_stop is not None and should_stop():
                    raise _AllocationPending()
                u = ctx.uses[use_cursor]
                uses[u.use_id] = unit('use', u.use_id, lambda: deepcopy(previous.use_states[u.use_id])
                    if reused and 'use:' + u.use_id not in affected else
                    _group(u.inputs, index, states, counts, capacities, 'use:' + u.use_id, existential=existential))
                use_cursor += 1
            while joint_cursor < len(joint_definitions):
                if should_stop is not None and should_stop():
                    raise _AllocationPending()
                key, members = joint_definitions[joint_cursor]
                joint_groups[key] = unit('joint', key, lambda: joint_value(key, members))
                joint_cursor += 1
    except _AllocationPending:
        allocation_pending = True
    finally:
        index._allocation_work = None
    exhausted = bool(queue) or use_cursor < len(ctx.uses) or joint_cursor < len(joint_definitions)
    progress = (dict(version='relation-updates-v2', binding=binding, states=deepcopy(states),
        queue=list(queue), active=active, uses=deepcopy(uses), use_cursor=use_cursor,
        joint_groups=deepcopy(joint_groups), joint_cursor=joint_cursor,
        allocation_steps=prior_allocation_steps + work.steps) if exhausted else None)
    if progress is not None and resumable:
        data=dict(version='construction-layer-evaluation-v1',layer='relations',continuation=progress,
            budget=dict(update_exhausted=True),work=dict(updates=updates, allocation_states=work.steps,
                total_allocation_states=prior_allocation_steps + work.steps))
        return RelationEvaluation(data,index,counts,states,{})
    if exhausted:
        # Every downstream result of unfinished closure is unassessed, not a
        # negative example. Known independent components remain usable.
        pending = deque(queue)
        unresolved = set(queue)
        while pending:
            fid = pending.popleft()
            for owner in index.dependents.get(fid, ()):
                if owner.startswith("fact:") and owner[5:] not in unresolved:
                    unresolved.add(owner[5:])
                    pending.append(owner[5:])
        for fid in unresolved:
            states[fid] = _blank("unknown")
            states[fid]["unknown"] = ["update_budget:" + fid]
    if exhausted:
        # Provisional readout for the non-resumable API. Its calculations never
        # overwrite the saved active unit or the completed closure prefix.
        preview = _AllocationWork(ctx.budget.allocations, should_stop, preview=True)
        index._allocation_work = preview
        def provisional(compute, label):
            preview.operations = {}
            try:
                return compute()
            except _AllocationPending:
                value = _blank('unknown')
                value['unknown'] = ['allocation_pending:' + label]
                return _unknown_support(value)
        try:
            if allocation_pending and queue:
                # Known prefixes may prove support in this readout while the
                # actual saved fact remains uncommitted until enumeration ends.
                preview_queue, preview_queued = deque(queue), set(queue)
                preview_updates = 0
                while preview_queue and preview_updates < ctx.budget.updates:
                    fid = preview_queue.popleft()
                    preview_queued.remove(fid)
                    preview.operations = deepcopy(active['operations']) if (
                        active and active['kind'] == 'fact' and active['identity'] == fid) else {}
                    try:
                        value = fact_value(fid)
                    except _AllocationPending:
                        continue
                    preview_updates += 1
                    if not same_state(value, states[fid]):
                        states[fid] = value
                        for owner in index.dependents.get(fid, ()):
                            if owner.startswith('fact:') and owner[5:] not in preview_queued:
                                preview_queue.append(owner[5:])
                                preview_queued.add(owner[5:])
            for u in ctx.uses[use_cursor:]:
                uses[u.use_id] = provisional(lambda: _group(u.inputs, index, states, counts, capacities,
                    'use:' + u.use_id, existential=existential), u.use_id)
            for key, members in joint_definitions[joint_cursor:]:
                joint_groups[key] = provisional(lambda: joint_value(key, members), key)
        finally:
            index._allocation_work = None
    joint = joint_groups['required-uses']
    constraints = []
    required_ids = {u.use_id for u in ctx.uses if u.required}
    joint_groups["required-uses"] = joint
    group_members = {c.constraint_id: set(c.uses) for c in ctx.constraints if c.kind == "all"}
    group_members["required-uses"] = required_ids
    for c in ctx.constraints:
        if all(uses[uid]["status"] != "missing" for uid in c.uses):
            constraints.append(asdict(c))
            for group_id, members in group_members.items():
                if not set(c.uses) <= members:
                    continue
                target = joint_groups[group_id]
                if c.kind == "incompatible":
                    target["status"] = "missing"
                    target["gaps"].append(c.constraint_id)
                elif c.kind == "order_unknown" and target["status"] != "missing":
                    target["status"] = "unknown"
                    target["unknown"].append(c.constraint_id)
                    target["support_expression"] = _expression("all", [target["support_expression"],
                        ("atom", "constraint:"+c.constraint_id)])
    for group_id, members in group_members.items():
        edges = [(a, b) for c in ctx.constraints if c.kind == "before" and set(c.uses) <= members
                 for a, b in zip(c.uses, c.uses[1:])]
        if not order_possible(members, edges):
            joint_groups[group_id]["status"] = "missing"
            joint_groups[group_id]["gaps"].append("inconsistent_use_order")
    probabilities = {}
    for p in ctx.probabilities:
        m = sum(skeleton.inventory.main.count(c) for c in p.cards)
        if hasattr(context, "task"):
            size = context.task.sizes["main"]
        else:
            size = len(skeleton.inventory.main)
        probabilities[p.request_id] = {**single_event_probabilities(size, m, p.draws),
            "source": p.source, "objectives": list(p.objectives)}
    public = {}
    for u in sorted(ctx.uses, key=lambda u: u.use_id):
        public[u.use_id] = {**deepcopy(uses[u.use_id]), "required": u.required, "priority": u.priority,
                            "source": u.source, "inputs": asdict(u.inputs)}
    data = {"version": "construction-layer-evaluation-v1", "layer": "relations",
        "uses": public, "joint_required": joint, "constraints": constraints,
        "joint_groups": {key: dict(value, use_ids=sorted(group_members[key])) for key, value in joint_groups.items()},
        "probabilities": probabilities, "inventory": skeleton.inventory.to_dict(),
        "inventory_projection": [{"zone":z,"card_id":c,"copies":n} for (z,c),n in sorted(counts.items())] if inventory_counts is not None else None,
        "slots": {z: sum(v for (zone, _), v in counts.items() if zone == z) for z in ("main", "extra")},
        "budget": {"incomplete_needs": sorted(index.incomplete_needs), "truncated_facts": index.truncated_facts,
                   "update_exhausted": exhausted, "allocation_pending": allocation_pending,
                   "condition_node_limit": None,
                   "condition_uncovered_uses": sorted(k for k, v in uses.items() if "condition_expression_budget" in v["unknown"])},
        "work": {**index.counters, "updates": updates, "allocation_states": work.steps,
                 "total_allocation_states": prior_allocation_steps + work.steps,
                 "affected_uses": sum("use:" + u.use_id in affected for u in ctx.uses),
                 "incremental": reused, "evaluation_seconds": perf_counter() - started},
        "observations": deepcopy(index.observations),
        'resource_pools': {key:asdict(value) for key,value in sorted(index.pools.items())},
        "fact_records": {key: asdict(value) for key, value in sorted(index.facts.items())},
        "task": context.task.to_dict() if hasattr(context, "task") else None}
    if progress is not None:data['continuation']=progress
    return RelationEvaluation(data, index, counts, states, uses)


def update_relations(previous, skeleton, context):
    return evaluate_relations(skeleton, context, previous.index, previous=previous)


def single_event_probabilities(size, copies, draws):
    integer(size, "population", 0)
    integer(copies, "copies", 0, size)
    integer(draws, "draws", 0, size)
    acquired, retained = _single_event_values(size, copies, draws)
    return {"population": size, "copies": copies, "draws": draws,
            "acquired": acquired, "retained": retained,
            "assumption": "uniform_initial_single_sample_without_prior_movement"}


@lru_cache(maxsize=4096)
def _single_event_values(size, copies, draws):
    def choose(n, k):
        return comb(n, k) if 0 <= k <= n else 0
    denominator = choose(size, draws)
    return (1 - choose(size - copies, draws) / denominator,
            1 - choose(size - copies, draws - copies) / denominator)


@dataclass(frozen=True)
class ConfigurationComparison:
    status: str
    preferred: str | None
    changes: dict
    advantages_before: tuple[str, ...]
    advantages_after: tuple[str, ...]
    unresolved: tuple[str, ...]

    def to_dict(self):
        return asdict(self)


def compare_configurations(before, after, context):
    ctx = _context(context)
    if before.index.context != ctx or after.index.context != ctx:
        raise ContractError("comparisons require the same original task purposes")
    a, b = before.data, after.data
    if a["task"] != b["task"]:
        raise ContractError("comparison cannot change the original task")
    gains, losses, unknown = [], [], []
    required_changes = []
    for u in ctx.uses:
        x, y = a["uses"][u.use_id], b["uses"][u.use_id]
        if x["status"] != y["status"]:
            if "unknown" in (x["status"], y["status"]):
                unknown.append("support:" + u.use_id)
            else:
                target = gains if y["status"] == "supported" else losses
                target.append("support:" + u.use_id)
                if u.required:
                    required_changes.append((u.priority, target is gains))
        elif x["status"] == "missing":
            old, new = set(x["gaps"]), set(y["gaps"])
            if new < old:
                gains.append("gap_repaired:" + u.use_id)
                if u.required:
                    required_changes.append((u.priority, True))
            elif old < new:
                losses.append("gap_added:" + u.use_id)
                if u.required:
                    required_changes.append((u.priority, False))
            elif old != new:
                gains.append("different_gap:" + u.use_id)
                losses.append("different_gap:" + u.use_id)
            for key in x["quantities"].keys() & y["quantities"].keys():
                old_gap, new_gap = x["quantities"][key]["shortfall_lower"], y["quantities"][key]["shortfall_lower"]
                if old_gap is not None and new_gap is not None and old_gap != new_gap:
                    (gains if new_gap < old_gap else losses).append("quantity_gap:" + key)
                    if u.required:
                        required_changes.append((u.priority, new_gap < old_gap))
        if x["status"] == y["status"] and x["unknown"] == y["unknown"]:
            old_condition, new_condition = x["condition_expression"], y["condition_expression"]
            if old_condition != new_condition:
                easier, harder = _weaker(new_condition, old_condition), _weaker(old_condition, new_condition)
                if easier and not harder:
                    gains.append("conditions:" + u.use_id)
                elif harder and not easier:
                    losses.append("conditions:" + u.use_id)
                elif not (easier and harder):
                    gains.append("conditions:" + u.use_id)
                    losses.append("conditions:" + u.use_id)
            for field_name in ("bottlenecks",):
                old, new = set(x[field_name]), set(y[field_name])
                if new < old:
                    gains.append(field_name + ":" + u.use_id)
                elif old < new:
                    losses.append(field_name + ":" + u.use_id)
                elif old != new:
                    gains.append(field_name + ":" + u.use_id)
                    losses.append(field_name + ":" + u.use_id)
        elif x["unknown"] != y["unknown"]:
            unknown.append("conditions:" + u.use_id)
    ja, jb = a["joint_required"], b["joint_required"]
    if ja["status"] != jb["status"]:
        if "unknown" in (ja["status"], jb["status"]):
            unknown.append("joint_required")
        else:
            (gains if jb["status"] == "supported" else losses).append("joint_required")
            required_changes.append((max((u.priority for u in ctx.uses if u.required), default=0),
                                     jb["status"] == "supported"))
    for p in ctx.probabilities:
        for objective in p.objectives:
            x, y = a["probabilities"][p.request_id][objective], b["probabilities"][p.request_id][objective]
            if x != y:
                (gains if y > x else losses).append(f"{objective}:{p.request_id}")
    delta = {z: b["slots"][z] - a["slots"][z] for z in ("main", "extra")}
    for z, difference in delta.items():
        if difference:
            (gains if difference < 0 else losses).append("slots:" + z)
    direction = None
    if required_changes:
        priority = max(v[0] for v in required_changes)
        signs = {v[1] for v in required_changes if v[0] == priority}
        if len(signs) == 1 and not unknown:
            direction = "after" if True in signs else "before"
    if direction:
        status = "preferred"
    elif gains and losses:
        status = "tradeoff"
    elif unknown:
        status = "undetermined"
    elif gains or losses:
        status, direction = "preferred", "after" if gains else "before"
    else:
        status = "equivalent"
    edits = {}
    for z in ("main", "extra", "side"):
        x, y = Counter(a["inventory"][z]), Counter(b["inventory"][z])
        edits[z] = {"added": sorted((y-x).elements()), "removed": sorted((x-y).elements())}
    return ConfigurationComparison(status, direction, {"cards": edits, "slots": delta,
        "uses": {u.use_id: {"before": a["uses"][u.use_id]["status"], "after": b["uses"][u.use_id]["status"],
                 "details": {k: {"before": a["uses"][u.use_id][k], "after": b["uses"][u.use_id][k]}
                             for k in ("gaps", "unknown", "condition_expression", "bottlenecks", "conflicts", "quantities")
                             if a["uses"][u.use_id][k] != b["uses"][u.use_id][k]}}
                 for u in ctx.uses}}, tuple(sorted(set(losses))), tuple(sorted(set(gains))), tuple(sorted(set(unknown))))
