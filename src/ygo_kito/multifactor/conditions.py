"""Bounded shared integer allocation. Facts are supplied, never inferred here.

A branch owns its reservations. Coverage must be declared before absence proves
failure; physical pool aliases share slots even when selectors differ.
"""
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json

from .contracts import FactorContractError, fields, text

STAGES = ("deck", "activation", "resolution", "post_resolution")
CONSUME_MODES = ("consume", "occupy", "retain", "reusable")
OPS = ("all", "any", "at_least_k", "not")
DECK_SECTIONS = ("main", "extra", "side")


def _optional(value, label):
    if value is not None:
        text(value, label)


def _stage_interval(stage, until):
    if stage not in STAGES or until is not None and until not in STAGES:
        raise FactorContractError("resource/condition: unknown stage")
    if until is not None and STAGES.index(until) < STAGES.index(stage):
        raise FactorContractError("resource/condition: reversed availability interval")


@dataclass(frozen=True)
class Resource:
    resource_type: str
    selector: str
    quantity: int = 1
    owner: str = "self"
    stage: str = "deck"
    zone: str | None = None  # Legacy input only; normalized by section/zone below.
    distinct_group: str | None = None
    reusable: bool = False
    resource_id: str | None = None
    pool_id: str | None = None
    capacity: int | None = None
    deck_section: str | None = None
    state_zone: str | None = None
    available_until: str | None = None
    selectors: tuple[str, ...] = ()
    known: bool = True
    source: str = "declared"
    initial_zones: tuple[str, ...] | None = None

    def __post_init__(self):
        for k in ("resource_type", "selector", "owner", "source"):
            text(getattr(self, k), "resource." + k)
        _stage_interval(self.stage, self.available_until)
        if type(self.quantity) is not int or not 0 <= self.quantity <= 99:
            raise FactorContractError("resource.quantity: integer 0..99 required")
        if self.capacity is not None and (type(self.capacity) is not int or not self.quantity <= self.capacity <= 4096):
            raise FactorContractError("resource.capacity: integer >= quantity and <=4096 required")
        for k in ("zone", "distinct_group", "resource_id", "pool_id", "state_zone"):
            _optional(getattr(self, k), "resource." + k)
        if self.deck_section is not None and self.deck_section not in DECK_SECTIONS:
            raise FactorContractError("resource.deck_section: unknown section")
        if type(self.reusable) is not bool or type(self.known) is not bool:
            raise FactorContractError("resource.known/reusable: booleans required")
        if not isinstance(self.selectors, tuple) or len(self.selectors) > 128:
            raise FactorContractError("resource.selectors: bounded tuple required")
        for v in self.selectors:
            text(v, "resource.selector alias")
        if self.initial_zones is not None:
            if not isinstance(self.initial_zones, tuple) or not self.initial_zones or len(set(self.initial_zones)) != len(self.initial_zones):
                raise FactorContractError('resource.initial_zones: distinct nonempty tuple required')
            for value in self.initial_zones:
                text(value, 'resource initial zone')

    def to_dict(self):
        value = asdict(self)
        value["selectors"] = list(self.selectors)
        return value

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or not {"resource_type", "selector"} <= set(value) or not set(value) <= set(cls.__dataclass_fields__):
            raise FactorContractError("resource: unknown/missing fields")
        value = dict(value)
        if "selectors" in value:
            if not isinstance(value["selectors"], list):
                raise FactorContractError("resource.selectors: JSON array required")
            value["selectors"] = tuple(value["selectors"])
        if value.get('initial_zones') is not None:
            if not isinstance(value['initial_zones'], list):
                raise FactorContractError('resource.initial_zones: JSON array required')
            value['initial_zones'] = tuple(value['initial_zones'])
        return cls(**value)


@dataclass(frozen=True)
class Condition:
    resource_type: str
    selector: str
    quantity: int = 1
    owner: str = "self"
    stage: str = "deck"
    consume_mode: str = "consume"
    distinct_group: str | None = None
    deck_section: str | None = None
    state_zone: str | None = None
    until_stage: str | None = None
    state_origins: tuple[str, ...] | None = None
    state_destination: str | None = None
    state_absent: bool = False
    state_binding: str | None = None
    state_exclude_binding: str | None = None
    state_destination_replace: tuple[str, str] | None = None
    state_random: bool = False
    state_destination_required: bool = False

    def __post_init__(self):
        for k in ("resource_type", "selector", "owner"):
            text(getattr(self, k), "condition." + k)
        _stage_interval(self.stage, self.until_stage)
        if self.consume_mode not in CONSUME_MODES:
            raise FactorContractError("condition.consume_mode: unknown mode")
        if type(self.quantity) is not int or not 1 <= self.quantity <= 4096:
            raise FactorContractError("condition.quantity: integer 1..4096 required")
        if self.deck_section is not None and self.deck_section not in DECK_SECTIONS:
            raise FactorContractError("condition.deck_section: unknown section")
        _optional(self.distinct_group, "condition.distinct_group")
        _optional(self.state_zone, "condition.state_zone")
        if self.consume_mode in ("consume", "reusable") and self.until_stage is not None:
            raise FactorContractError("condition.until_stage only applies to occupy/retain")
        if self.state_origins is not None:
            if (not isinstance(self.state_origins, tuple) or not self.state_origins
                    or len(set(self.state_origins)) != len(self.state_origins) or self.consume_mode != 'reusable'):
                raise FactorContractError('condition.state_origins: distinct zones and reusable mode required')
            for value in self.state_origins:
                text(value, 'condition state origin')
        _optional(self.state_destination, 'condition state destination')
        if type(self.state_absent) is not bool or (self.state_destination is not None or self.state_absent) and self.state_origins is None:
            raise FactorContractError('state movement/absence requires explicit origins')
        if self.state_absent and (self.state_destination is not None or self.quantity != 1):
            raise FactorContractError('state absence requires one non-moving predicate')
        if type(self.state_random) is not bool or self.state_random and (self.state_origins is None or self.state_absent):
            raise FactorContractError('random state selection requires explicit origins')
        if type(self.state_destination_required) is not bool or self.state_destination_required and self.state_destination is None:
            raise FactorContractError('required destination needs an explicit movement')
        for value in (self.state_binding, self.state_exclude_binding):
            _optional(value, 'condition state binding')
        if (self.state_binding or self.state_exclude_binding) and self.state_origins is None:
            raise FactorContractError('state binding requires a state condition')
        if self.state_destination_replace is not None:
            if (not isinstance(self.state_destination_replace, tuple) or len(self.state_destination_replace) != 2
                    or len(set(self.state_destination_replace)) != 2 or self.consume_mode != 'reusable'
                    or self.state_origins is not None or self.quantity != 1):
                raise FactorContractError('state destination replacement requires two distinct zones and no movement')
            for value in self.state_destination_replace:
                text(value, 'state replacement zone')


@dataclass(frozen=True)
class ConditionGroup:
    op: str
    children: tuple
    min_count: int = 1

    def __post_init__(self):
        if self.op not in OPS or not isinstance(self.children, tuple) or not 1 <= len(self.children) <= 16 or any(
                not isinstance(v, (Condition, ConditionGroup)) for v in self.children):
            raise FactorContractError("condition group: known operator and 1..16 typed children required")
        if self.op == "at_least_k":
            if type(self.min_count) is not int or not 1 <= self.min_count <= len(self.children):
                raise FactorContractError("at_least_k: invalid min_count")
        elif self.min_count != 1:
            raise FactorContractError("min_count only applies to at_least_k")
        if self.op == "not":
            if len(self.children) != 1:
                raise FactorContractError("not requires exactly one predicate subtree")
            stack = list(self.children)
            while stack:
                child = stack.pop()
                if isinstance(child, Condition):
                    if child.consume_mode != "reusable" or child.distinct_group is not None or child.state_random:
                        raise FactorContractError("not only accepts non-reserving reusable predicates")
                else:
                    stack.extend(child.children)


def condition_to_dict(node):
    if isinstance(node, Condition):
        payload = asdict(node)
        # Preserve the input binding of pre-existing deterministic cursors.
        for key in ('state_random', 'state_destination_required'):
            if not payload[key]:
                del payload[key]
        return dict(kind="atom", **payload)
    if isinstance(node, ConditionGroup):
        return dict(kind="group", op=node.op, min_count=node.min_count,
                    children=[condition_to_dict(v) for v in node.children])
    raise FactorContractError("typed condition required")


def condition_from_dict(value, _depth=0):
    if _depth > 16 or not isinstance(value, dict):
        raise FactorContractError("condition tree: invalid object or depth >16")
    if value.get("kind") == "atom":
        payload = {k: v for k, v in value.items() if k != "kind"}
        if not {"resource_type", "selector"} <= set(payload) or not set(payload) <= set(Condition.__dataclass_fields__):
            raise FactorContractError("condition atom: unknown/missing fields")
        if payload.get('state_origins') is not None:
            if not isinstance(payload['state_origins'], list):
                raise FactorContractError('condition.state_origins: JSON array required')
            payload['state_origins'] = tuple(payload['state_origins'])
        if payload.get('state_destination_replace') is not None:
            if not isinstance(payload['state_destination_replace'], list):
                raise FactorContractError('state_destination_replace: JSON array required')
            payload['state_destination_replace'] = tuple(payload['state_destination_replace'])
        return Condition(**payload)
    fields(value, ("kind", "op", "min_count", "children"))
    if value["kind"] != "group" or not isinstance(value["children"], list):
        raise FactorContractError("condition group: children array required")
    return ConditionGroup(value["op"], tuple(condition_from_dict(v, _depth + 1) for v in value["children"]), value["min_count"])


@dataclass(frozen=True)
class SolverBudget:
    max_depth: int = 16
    max_states: int = 4096
    max_solutions: int = 128

    def __post_init__(self):
        for k, limit in (("max_depth", 64), ("max_states", 1000000), ("max_solutions", 4096)):
            if type(getattr(self, k)) is not int or not 1 <= getattr(self, k) <= limit:
                raise FactorContractError("solver budget: invalid " + k)


@dataclass(frozen=True)
class _State:
    reservations: tuple = ()
    pending: tuple = ()
    choices: tuple = ()
    slot_zones: tuple = ()
    state_bindings: tuple = ()
    destination_replacements: tuple = ()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      default=lambda item: asdict(item))


def _digest(value):
    return sha256(_json(value).encode('utf-8')).hexdigest()


def _next_combination(indices, size):
    """The next lexicographic combination, without replaying its prefix."""
    result = list(indices)
    for i in range(len(result) - 1, -1, -1):
        if result[i] < size - len(result) + i:
            result[i] += 1
            result[i + 1:] = range(result[i] + 1, result[i] + len(result) - i)
            return result
    return None


def _action(value):
    return dict(value, slot=tuple(value['slot']))


def _restore_state(value):
    pending = []
    for row in value['pending']:
        row = dict(row)
        if 'condition' in row:
            condition = dict(row['condition'])
            for key in ('state_origins', 'state_destination_replace'):
                if condition.get(key) is not None:
                    condition[key] = tuple(condition[key])
            row['condition'] = condition
        pending.append(row)
    return _State(tuple(_action(row) for row in value['reservations']), tuple(pending),
        tuple((path, tuple(selected)) for path, selected in value['choices']),
        tuple((tuple(slot), tuple(zones)) for slot, zones in value['slot_zones']),
        tuple((key, tuple(tuple(slot) for slot in slots)) for key, slots in value['state_bindings']),
        tuple(tuple(row) for row in value['destination_replacements']))


def _restore_frames(values):
    result = []
    for value in values:
        frame = dict(value, state=_restore_state(value['state']))
        if 'candidates' in frame:
            frame['candidates'] = [_action(row) for row in frame['candidates']]
        if frame.get('child') is not None:
            frame['child'] = _restore_frames(frame['child'])
        for key in ('witness', 'possible'):
            if frame.get(key) is not None:
                frame[key] = _restore_state(frame[key])
        result.append(frame)
    return result


def _restore_branch(value):
    branch = dict(value)
    branch['choices'] = [(path, tuple(selected)) for path, selected in value['choices']]
    for key in ('matched_resources', 'consumed', 'occupied', 'retained'):
        branch[key] = [_action(row) for row in value[key]]
    if 'slot_zones' in value:
        branch['slot_zones'] = [dict(row, slot=tuple(row['slot'])) for row in value['slot_zones']]
    # Restore the tuple-valued fields of residual condition contracts too.
    branch['residual_conditions'] = list(_restore_state(dict(reservations=[],
        pending=value['residual_conditions'], choices=[], slot_zones=[], state_bindings=[],
        destination_replacements=[])).pending)
    return branch


class _Search:
    def __init__(self, resources, coverage, budget):
        self.resources, self.coverage, self.budget = resources, coverage, budget
        self.steps, self.depth_blocked = 0, False
        self.failures = []
        self.capacities = {}
        self.pools = []
        self.initial_zones = {}
        self.resource_index = defaultdict(list)
        self.matches_by_condition = {}
        for i, r in enumerate(resources):
            for selector in dict.fromkeys((r.selector, *r.selectors)):
                self.resource_index[r.resource_type, selector, r.owner].append(i)
            pool = r.pool_id or r.resource_id or f"stock:{i}"
            capacity = r.quantity if r.capacity is None else r.capacity
            if pool in self.capacities and self.capacities[pool] != capacity:
                raise FactorContractError("resource pool aliases must declare consistent capacity: " + pool)
            self.capacities[pool] = capacity
            self.pools.append(pool)
            if r.initial_zones is not None:
                if pool in self.initial_zones and self.initial_zones[pool] != r.initial_zones:
                    raise FactorContractError('physical state aliases require identical initial zones')
                self.initial_zones[pool] = r.initial_zones

    def complete(self, condition):
        key = (condition.resource_type, condition.selector, condition.owner, condition.stage,
               condition.deck_section, condition.state_zone)
        return self.coverage is True or self.coverage is not False and key in self.coverage

    def matches(self, c, r):
        section = r.deck_section or (r.zone if r.zone in DECK_SECTIONS else None)
        zone = r.state_zone or (r.zone if r.zone not in DECK_SECTIONS else None)
        end = r.available_until or r.stage
        return (c.resource_type == r.resource_type and c.selector in (r.selector,) + r.selectors and c.owner == r.owner
                and STAGES.index(r.stage) <= STAGES.index(c.stage) <= STAGES.index(end)
                and (c.deck_section is None or section == c.deck_section)
                and (c.state_zone is None or zone == c.state_zone)
                and (c.until_stage is None or STAGES.index(c.until_stage) <= STAGES.index(end))
                and section != "side")

    def matching(self, condition):
        if condition not in self.matches_by_condition:
            key = condition.resource_type, condition.selector, condition.owner
            self.matches_by_condition[condition] = tuple(
                i for i in self.resource_index.get(key, ()) if self.matches(condition, self.resources[i]))
        return self.matches_by_condition[condition]

    @staticmethod
    def reservations_by_slot(state):
        result = defaultdict(list)
        for action in state.reservations:
            result[action['slot']].append(action)
        return result

    def fixed_shortage(self):
        """Prove infeasibility for a bounded conjunction of fixed consumptions."""
        demands = []
        for condition, depth, path, _ in self.nodes:
            if depth > self.budget.max_depth:
                return False
            if isinstance(condition, ConditionGroup):
                if condition.op != 'all':
                    return False
            elif condition.consume_mode != 'consume' or condition.state_origins is not None:
                return False
            else:
                demands.append((condition, path))
        if len(demands) < 2 or sum(condition.quantity for condition, _ in demands) > 64:
            return False

        slots_by_need = []
        for condition, path in demands:
            stock = self.matching(condition)
            if any(not self.resources[i].known for i in stock):
                return False
            slots = dict.fromkeys((self.pools[i], copy) for i in stock for copy in range(self.resources[i].quantity))
            if len(slots) < condition.quantity:
                self.failure(dict(path=path, required=condition.quantity, available=len(slots),
                                  selector=condition.selector, blocked=[], reason='MISSING_RESOURCE'))
                return True
            if len(slots) > 512:
                return False
            slots_by_need.extend([(condition, path, slots)] * condition.quantity)

        # Augmenting paths can move a previous match when another demand has
        # fewer options. Failure after all reassignments proves a shared shortage.
        owners = {}

        def assign(need, visited):
            for slot in slots_by_need[need][2]:
                if slot in visited:
                    continue
                visited.add(slot)
                if slot not in owners or assign(owners[slot], visited):
                    owners[slot] = need
                    return True
            return False

        for need, (condition, path, slots) in enumerate(slots_by_need):
            visited = set()
            if not assign(need, visited):
                blocked = [dict(pool=pool, slot=slot, selector=condition.selector, reason='RESOURCE_ALREADY_RESERVED')
                           for pool, slot in sorted(visited)[:16]]
                self.failure(dict(path=path, required=condition.quantity,
                                  available=sum(slots_by_need[owners[slot]][1] == path for slot in slots),
                                  selector=condition.selector, blocked=blocked, reason='RESOURCE_ALREADY_RESERVED'))
                return True
        return False

    def compatible(self, action, previous):
        if action["slot"] != previous["slot"]:
            return True
        if action["distinct_group"] is not None and action["distinct_group"] == previous["distinct_group"]:
            return False
        overlap = max(action["start"], previous["start"]) <= min(action["end"], previous["end"])
        if not overlap:
            return True
        modes = {action["mode"], previous["mode"]}
        if "consume" in modes:
            return False
        if "occupy" in modes and "retain" not in modes:
            return False
        return True

    def atomic_frame(self, c, state, path, todo, node_id):
        if c.state_destination_replace is not None:
            values = dict(state.destination_replacements)
            values[c.state_destination_replace[0]] = c.state_destination_replace[1]
            return self.walk(todo, replace(state, destination_replacements=tuple(sorted(values.items()))))
        if c.state_origins is not None:
            return self.state_frame(c, state, path, todo, node_id)
        matched, uncertain, blocked = {}, False, []
        reserved = self.reservations_by_slot(state)
        for i in self.matching(c):
            resource = self.resources[i]
            if not resource.known:
                uncertain = True
                continue
            # Aliases refer to the same first N physical slots in their pool.
            for slot in range(resource.quantity):
                physical = (self.pools[i], slot)
                action = dict(slot=physical, mode=c.consume_mode, start=STAGES.index(c.stage),
                              end=3 if c.consume_mode == "consume" else STAGES.index(c.until_stage or c.stage),
                              distinct_group=c.distinct_group, source=resource.source,
                              resource_id=resource.resource_id or f"stock:{i}", condition=path, selector=c.selector)
                if all(self.compatible(action, old) for old in reserved.get(physical, ())):
                    matched.setdefault(physical, action)
                elif len(blocked) < 16:
                    blocked.append(dict(pool=self.pools[i], slot=slot, selector=c.selector,
                                        reason="RESOURCE_ALREADY_RESERVED"))
        candidates = list(matched.values())
        if len(candidates) < c.quantity:
            self.failure(dict(path=path, required=c.quantity, available=len(candidates),
                selector=c.selector, blocked=blocked,
                reason="RESOURCE_ALREADY_RESERVED" if blocked else "MISSING_RESOURCE"))
        return dict(kind='atom', state=state, todo=todo, node=node_id, candidates=candidates,
            cursor=list(range(c.quantity)) if len(candidates) >= c.quantity else None,
            pending=uncertain or not self.complete(c))

    def state_frame(self, c, state, path, todo, node_id):
        """Use the same physical slots through a sourced static sequence."""
        zones = dict(state.slot_zones)
        bindings = dict(state.state_bindings)
        candidates, unknown = {}, False
        forbidden = set(c.state_origins)
        reserved = self.reservations_by_slot(state)
        for i in self.matching(c):
            resource = self.resources[i]
            pool = self.pools[i]
            if not resource.known or pool not in self.initial_zones:
                unknown = True
                continue
            for copy in range(resource.quantity):
                slot = pool, copy
                if c.state_binding in bindings and slot not in bindings[c.state_binding]:
                    continue
                if slot in bindings.get(c.state_exclude_binding, ()):
                    continue
                current = set(zones.get(slot, self.initial_zones[pool]))
                if c.state_absent:
                    remaining = current - forbidden
                    if not remaining:
                        return None
                    zones[slot] = tuple(sorted(remaining))
                elif current & forbidden:
                    if c.state_destination_required and self.destination(c, state, pool) != c.state_destination:
                        continue
                    action = dict(slot=slot, mode='reusable', start=0, end=0,
                        distinct_group=c.distinct_group, source=resource.source,
                        resource_id=resource.resource_id or f'stock:{i}', condition=path, selector=c.selector)
                    if all(self.compatible(action, old) for old in reserved.get(slot, ())):
                        candidates.setdefault(slot, action)
        if c.state_absent:
            return self.walk(todo, replace(state, slot_zones=tuple(sorted(zones.items())),
                pending=state.pending + ((dict(path=path, condition=asdict(c), reason='OBSERVATION_INCOMPLETE'),)
                                        if unknown or not self.complete(c) else ())))
        if len(candidates) < c.quantity:
            self.failure(dict(path=path, required=c.quantity, available=len(candidates),
                selector=c.selector, blocked=[], reason='STATE_RESOURCE_MISSING'))
        frame = dict(kind='atom', state=state, todo=todo, node=node_id,
            candidates=list(candidates.values()),
            cursor=list(range(c.quantity)) if len(candidates) >= c.quantity else None,
            pending=unknown or not self.complete(c))
        if c.state_random:
            frame.update(kind='random', child=None, witness=None, possible=None, successes=0, failures=0)
        return frame

    def failure(self, value):
        if value not in self.failures:
            self.failures.append(value)

    def destination(self, condition, state, pool):
        destination = dict(state.destination_replacements).get(condition.state_destination, condition.state_destination)
        if self.initial_zones[pool] == ('uncreated',) and destination not in (None, 'field'):
            return 'ceased'
        return destination

    def allocated(self, c, state, chosen):
        if c.state_origins is not None:
            zones, bindings = dict(state.slot_zones), dict(state.state_bindings)
            updated = dict(zones)
            for row in chosen:
                slot = row['slot']
                current = set(zones.get(slot, self.initial_zones[slot[0]])) & set(c.state_origins)
                destination = self.destination(c, state, slot[0])
                updated[slot] = ((destination,) if destination is not None
                                 else tuple(sorted(current)))
            if c.state_binding:
                bindings = dict(bindings, **{c.state_binding: tuple(row['slot'] for row in chosen)})
            return replace(state, reservations=state.reservations + tuple(chosen),
                          slot_zones=tuple(sorted(updated.items())), state_bindings=tuple(sorted(bindings.items())))
        return replace(state, reservations=state.reservations + tuple(chosen))

    @staticmethod
    def walk(todo, state):
        return dict(kind='walk', todo=todo, state=state)

    def bind_tree(self, tree):
        self.nodes = []
        def visit(node, depth, path):
            index = len(self.nodes)
            self.nodes.append(None)
            children = [] if isinstance(node, Condition) else [
                visit(child, depth + 1, path + ('.not' if node.op == 'not' else f'.{i}'))
                for i, child in enumerate(node.children)]
            self.nodes[index] = node, depth, path, children
            return index
        visit(tree, 0, 'root')

    def advance_random(self, stack, frame):
        node, _, path, _ = self.nodes[frame['node']]
        if frame['child'] is not None:
            outcome = self.advance(frame['child'])
            if outcome is not None and not outcome.pending:
                if frame['witness'] is None:
                    frame['witness'] = outcome
                frame['successes'] += 1
                frame['child'] = None
            elif outcome is not None and frame['possible'] is None:
                frame['possible'] = outcome
            if frame['child'] == []:
                if frame['possible'] is not None:
                    # One unresolved identity already prevents a definite verdict.
                    stack.pop()
                    outcome = frame['possible']
                    return replace(outcome, pending=outcome.pending + (
                        dict(path=path, reason='RANDOM_IDENTITY_CONDITIONAL'),))
                frame['failures'] += 1
                frame['child'] = None
            return None

        indices = frame['cursor']
        if indices is not None and not frame['todo']:
            # With no remaining observation, every legal identity has the same verdict.
            stack.pop()
            chosen = [dict(frame['candidates'][i], random=True) for i in indices]
            return self.allocated(node, frame['state'], chosen)
        if indices is None or frame['successes'] and frame['failures']:
            stack.pop()
            witness = frame['witness']
            if frame['pending']:
                possible = witness or frame['state']
                return replace(possible, pending=possible.pending + (dict(path=path,
                    condition=asdict(node), reason='OBSERVATION_INCOMPLETE'),))
            if witness is None or not frame['failures']:
                return witness
            return replace(witness, pending=witness.pending + (
                dict(path=path, reason='RANDOM_IDENTITY_CONDITIONAL'),))

        frame['cursor'] = _next_combination(indices, len(frame['candidates']))
        chosen = [dict(frame['candidates'][i], random=True) for i in indices]
        frame['possible'] = None
        frame['child'] = [self.walk(frame['todo'], self.allocated(node, frame['state'], chosen))]
        return None

    def advance(self, stack):
        """One serializable DFS transition, including active predicate or random subtrees."""
        frame = stack[-1]
        state, todo = frame['state'], frame['todo']
        if frame['kind'] == 'random':
            return self.advance_random(stack, frame)
        if frame['kind'] == 'not':
            if frame['child']:
                result = self.advance(frame['child'])
                if result is not None:
                    if not result.pending:
                        stack.pop()  # A known witness refutes the negation.
                    else:
                        frame['unknown'] = True
            else:
                stack.pop()
                if frame['unknown']:
                    state = replace(state, pending=state.pending + (
                        dict(path=frame['path'], reason='NEGATION_UNKNOWN'),))
                stack.append(self.walk(todo, state))
            return None
        if frame['kind'] == 'walk':
            if not todo:
                stack.pop()
                return state
            node_id, *rest = todo
            node, depth, path, children = self.nodes[node_id]
            if depth > self.budget.max_depth:
                self.depth_blocked = True
                return None
            stack.pop()
            if isinstance(node, Condition):
                next_frame = self.atomic_frame(node, state, path, rest, node_id)
                if next_frame is not None:
                    stack.append(next_frame)
            elif node.op == 'not':
                # Negation tests supplied observation, independently of outer reservations.
                stack.append(dict(kind='not', state=state, todo=rest, path=path,
                    unknown=False, child=[self.walk(children, _State())]))
            elif node.op == 'all':
                stack.append(self.walk(children + rest, state))
            else:
                k = 1 if node.op == 'any' else node.min_count
                stack.append(dict(kind='select', node=node_id, state=state, todo=rest,
                    cursor=list(range(k))))
            return None
        node, _depth, path, children = self.nodes[frame['node']]
        indices = frame['cursor']
        if frame['kind'] == 'select':
            if indices is None:
                stack.pop()
            else:
                frame['cursor'] = _next_combination(indices, len(children))
                picked = replace(state, choices=state.choices + ((path, tuple(indices)),))
                stack.append(self.walk([children[i] for i in indices] + todo, picked))
        elif indices is not None:
            frame['cursor'] = _next_combination(indices, len(frame['candidates']))
            chosen = [frame['candidates'][i] for i in indices]
            stack.append(self.walk(todo, self.allocated(node, state, chosen)))
        elif frame['pending']:
            frame['pending'] = False
            pending = dict(path=path, condition=asdict(node), reason='OBSERVATION_INCOMPLETE')
            stack.append(self.walk(todo, replace(state, pending=state.pending + (pending,))))
        else:
            stack.pop()
        return None


def solve_requirements(tree, resources, *, coverage=False, budget=SolverBudget(), state_provided=False,
                       continuation=None, should_stop=None, existential=False):
    """Return separate allocation witnesses, with explicit unknown and overflow.

    coverage=True asserts a complete stock for this expression. Alternatively
    declare complete atomic scopes as six-tuples (type, selector, owner, stage,
    deck_section, state_zone). Default open-world stock never proves absence.
    Resource availability across stages requires an explicit available_until;
    transformed/recovered resources must be supplied as separate sourced facts.
    A random state selection checks the remaining sequence for each possible
    identity. Its witness represents a checked outcome, with a pending reason
    when success depends on the unknown identity.
    Existential consumers may prove a fixed shortage directly by matching.
    """
    if not isinstance(tree, (Condition, ConditionGroup)) or not isinstance(budget, SolverBudget):
        raise FactorContractError("typed condition tree and SolverBudget required")
    if not isinstance(resources, (tuple, list)) or len(resources) > 512 or any(not isinstance(r, Resource) for r in resources):
        raise FactorContractError("bounded typed resource stock required")
    if type(coverage) is not bool:
        if not isinstance(coverage, tuple) or any(not isinstance(k, tuple) or len(k) != 6 for k in coverage):
            raise FactorContractError("coverage requires bool or immutable six-field scopes")
    if type(state_provided) is not bool:
        raise FactorContractError("state_provided must be boolean")
    stock = tuple(resources)
    search = _Search(stock, coverage, budget)
    search.bind_tree(tree)
    binding = _digest(dict(tree=condition_to_dict(tree), resources=[r.to_dict() for r in stock],
        coverage=coverage, state_provided=state_provided))
    branches, seen, total_steps = [], set(), 0
    stack = [search.walk([0], _State())]
    if continuation is not None:
        if (not isinstance(continuation, dict) or continuation.get('version') != 'shared-allocation-dfs-v1'
                or continuation.get('binding') != binding):
            raise FactorContractError('allocation continuation belongs to different inputs or version')
        stack = _restore_frames(continuation['stack'])
        branches = [_restore_branch(row) for row in continuation['branches']]
        seen = set(continuation['seen'])
        search.failures = list(continuation['failures'])
        total_steps = continuation['total_explored_states']
    prior_count = len(branches)
    while stack and search.steps < budget.max_states and len(branches) - prior_count < budget.max_solutions:
        if should_stop is not None and should_stop():
            break
        search.steps += 1
        if (existential and coverage is True and continuation is None and search.steps == 1
                and search.fixed_shortage()):
            stack.clear()
            break
        result = search.advance(stack)
        if search.depth_blocked:
            break
        if result is None:
            continue
        # Equivalent witnesses only; do not combine independent allocations.
        signature = _digest((tuple((r["slot"], r["mode"], r["start"], r["end"], r["distinct_group"], r["condition"]) for r in result.reservations),
                     result.pending, result.choices, result.slot_zones, result.state_bindings, result.destination_replacements))
        if signature in seen:
            continue
        seen.add(signature)
        known = not result.pending
        reservations = list(result.reservations)
        branches.append(dict(branch_id=f"allocation:{len(branches)}", satisfied=True if known else None,
                             structural_status="complete" if known else "unknown",
                             choices=list(result.choices), matched_resources=reservations,
                             consumed=[r for r in reservations if r["mode"] == "consume"],
                             occupied=[r for r in reservations if r["mode"] == "occupy"],
                             retained=[r for r in reservations if r["mode"] == "retain"],
                             residual_conditions=list(result.pending), conflicts=[]))
        if result.slot_zones:
            branches[-1]['slot_zones'] = [dict(slot=slot, zones=list(zones)) for slot, zones in result.slot_zones]
    proven = [b for b in branches if b["satisfied"] is True]
    overflow = bool(stack)
    satisfied = True if proven else None if branches or overflow else False
    status = "complete" if satisfied is True else "unknown" if satisfied is None else "partial"
    # No union of witness stock or consumption at the top level.
    unique = proven[0] if len(proven) == 1 and not overflow else None
    consumed = [] if unique is None else unique["consumed"]
    used = {tuple(r["slot"]) for r in consumed}
    remaining = tuple(replace(r, quantity=sum((search.pools[i], j) not in used for j in range(r.quantity))) for i, r in enumerate(stock))
    progress = None if not stack else json.loads(_json(dict(version='shared-allocation-dfs-v1',
        binding=binding, stack=stack, branches=branches, seen=sorted(seen), failures=search.failures,
        total_explored_states=total_steps + search.steps)))
    return dict(satisfied=satisfied, structural_status=status,
                state_readiness=("executable" if satisfied is True else "blocked" if satisfied is False else "unknown") if state_provided else "unknown",
                chosen_branch=None, branches=branches, consumed=consumed, resources=remaining,
                missing=[] if satisfied is True else [dict(reason="REQUIREMENT_UNRESOLVED" if satisfied is None else "REQUIREMENT_UNSATISFIED")],
                overflow=overflow, enumeration_complete=not overflow, explored_states=search.steps,
                total_explored_states=total_steps + search.steps, continuation=progress,
                rejected_allocations=search.failures,
                conflicts=[v for v in search.failures if v["blocked"]] if satisfied is False else [],
                rule_authority=False)
