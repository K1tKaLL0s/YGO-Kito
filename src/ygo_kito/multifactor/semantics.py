"""Narrow dict adapter for the separate effect window; no upstream code import.

Only positive, observed operations enter factors. Missing operations, unparsed
clauses and unverified opening reachability remain unknown. Not a text parser.
"""

from dataclasses import dataclass, replace
from collections import Counter, defaultdict
from itertools import combinations, product
import re

from .contracts import (AnalysisGraph, FactorContractError, Factors, FunctionSeed, GraphEdge,
                        GraphNode, GRAPH_ATTRIBUTES, GRAPH_FUNCTIONS, Group, Observation,
                        RoleInput, StructureLink, digest, text, unit)
from .axis_candidates import CandidateBudget, CandidateSet, generate_axis_candidates
from .conditions import Condition
from .functional_units import BranchConditions, FunctionalContract, minimum_member_branches

SUPPORTED_SEMANTIC_VERSION = "public-effect-clauses-v2"
OPERATION_FACTORS = {
    "send_grave": "effect_send_grave", "mill": "effect_mill",
    "search_or_recover": None, "special_summon": "effect_special_summon",
    "negate": "effect_negate", "destroy": "effect_destroy", "draw": "effect_draw",
    "return_fusion_materials": "effect_recover", "fusion_summon": "effect_fusion",
}


def group_from_semantics(snapshot, *, key, source_ref, measured=None, confidence=0.0, uncertainty=1.0):
    """Consume CardSemantics.to_dict() or an explicitly partial manual snapshot.

    measured is optional, independently sourced group Factors from the host.
    It cannot silently overwrite a semantic observation. Reliability is supplied
    by the host; defaults carry no claimed calibration. Player locks here only
    mark their presence; actual conflicts/reachability require context or engine.
    """
    text(source_ref, "semantic source reference")
    if not isinstance(snapshot, dict) or snapshot.get("semantic_version") != SUPPORTED_SEMANTIC_VERSION:
        raise FactorContractError("unsupported effect semantic version")
    if not isinstance(snapshot.get("effects"), (list, tuple)):
        raise FactorContractError("semantic effects sequence required")
    factors, notes = {}, ["partial observations; no route or role labels derived"]
    text_hash = snapshot.get("text_sha256")
    if text_hash is not None and (not isinstance(text_hash, str) or len(text_hash) != 64
                                  or any(c not in "0123456789abcdef" for c in text_hash)):
        raise FactorContractError("semantic text digest must be SHA256 or null")
    source = source_ref + (":text_sha256=" + text_hash if text_hash else ":text_digest_unknown")
    notes.extend("card:" + str(value) for value in snapshot.get("unknown", ()))
    restrictions = list(snapshot.get("restrictions", ()))

    def observed(name):
        factors[name] = Observation(1.0, confidence, uncertainty, source)

    for effect in snapshot["effects"]:
        if not isinstance(effect, dict):
            raise FactorContractError("semantic effect object required")
        index = effect.get("index", "unknown")
        notes.extend(f"effect:{index}:unknown:{value}" for value in effect.get("unknown", ()))
        notes.append(f"effect:{index}:trigger={effect.get('trigger', {})}")
        notes.append(f"effect:{index}:costs={effect.get('costs', ())}")
        notes.append(f"effect:{index}:count_limits={effect.get('count_limits', ())}")
        restrictions.extend(effect.get("restrictions", ()))
        for op in effect.get("operations", ()):
            if not isinstance(op, dict):
                raise FactorContractError("semantic operation object required")
            if op.get("reason") != "effect" or not op.get("source"):
                notes.append(f"effect:{index}:untrusted_operation:{op.get('kind')}")
                continue
            notes.append(f"effect:{index}:observed_operation:{op}")
            kind = op.get("kind")
            if kind == "search_or_recover":
                if op.get('selection_group') or op.get('random') is True:
                    continue
                zones = op.get("from_zones", ())
                # Broad mixed-zone observations do not certify both functions.
                if zones in (("deck",), ["deck"]):
                    observed("effect_search")
                elif zones in (("grave",), ["grave"], ("banished",), ["banished"]):
                    observed("effect_recover")
                else:
                    notes.append(f"effect:{index}:search_or_recover_origin_unresolved")
            elif OPERATION_FACTORS.get(kind):
                observed(OPERATION_FACTORS[kind])
            else:
                notes.append(f"effect:{index}:unsupported_operation:{kind}")
        for count in effect.get("count_limits", ()):
            if (isinstance(count, dict) and count.get("status") == "known" and
                    count.get("maximum") == 1 and count.get("period") == "turn" and count.get("source")):
                observed("effect_once_per_turn")
    for restriction in restrictions:
        if not isinstance(restriction, dict):
            raise FactorContractError("semantic restriction object required")
        notes.append("scoped_restriction:" + str(restriction))
        if restriction.get("scope") == "player" and restriction.get("source"):
            observed("effect_player_lock")
    if measured is not None:
        if not isinstance(measured, Factors) or measured.family != "group":
            raise FactorContractError("independently sourced group factors required")
        if factors.keys() & dict(measured.items).keys():
            raise FactorContractError("semantic factor overwrite requires explicit upstream reconciliation")
        factors.update(measured.items)
    refs = () if snapshot.get("card_id") is None else ("card:" + str(snapshot["card_id"]),)
    return Group(key, Factors.from_mapping("group", factors), refs, tuple(notes))


@dataclass(frozen=True)
class GraphBudget:
    nodes: int = 16384
    edges: int = 131072
    relation_checks: int = 32768
    node_block: int = 128
    edge_block: int = 2048

    def __post_init__(self):
        for name, maximum in (("nodes", 16384), ("edges", 131072), ("relation_checks", 1000000),
                              ("node_block", 16384), ("edge_block", 131072)):
            if type(getattr(self, name)) is not int or not 1 <= getattr(self, name) <= maximum:
                raise FactorContractError("invalid graph budget: " + name)


@dataclass(frozen=True)
class GraphBuild:
    input: RoleInput
    graph: AnalysisGraph
    candidates: CandidateSet
    unresolved: tuple
    budget: GraphBudget

    def numeric_blocks(self):
        return self.graph.numeric_blocks(node_budget=self.budget.node_block, edge_budget=self.budget.edge_block)

    def to_dict(self):
        return dict(schema_version="axis-graph-record-v3", observations=dict(input=self.input.to_dict(),
                    graph=self.graph.to_dict(), candidates=self.candidates.to_dict()),
                    provenance=dict(unresolved=list(self.unresolved), feature_producer="multifactor.semantics"))


def _operation_functions(op):
    if op.get("reason") != "effect" or not op.get("source"):
        return ()
    kind = op.get("kind")
    if kind == "search_or_recover":
        if op.get('selection_group') or op.get('random') is True:
            return ()
        origin = tuple(op.get("from_zones", ()))
        return ("search",) if origin == ("deck",) else ("recover",) if origin in (("grave",), ("banished",)) else ()
    if kind in ('normal_summon', 'tribute_summon') and op.get('selector_query'):
        return ('follow_up',)
    if op.get('owner') == 'opponent' and (kind == 'response_lock' or kind == 'position' and '变成里侧守备表示' in op['source']):
        return ('interfere',)
    if kind == 'negate' and op.get('block_id') and not re.search(r'发动(?:和效果)?无效', op['source']):
        return ('interfere',)
    mapped = {"negate": "negate_activation", "return_fusion_materials": "recover",
              "return_deck": "return_cards_to_deck", "place": "resource_supply",
              "grave_destination_replace": "resource_conversion", "ritual_summon": "ritual",
              "link_summon": "link", "synchro_summon": "synchro", "xyz_summon": "xyz"}.get(kind, kind)
    return (mapped,) if mapped in GRAPH_FUNCTIONS else ()


def _operation_attributes(op, *, reason=None):
    if not isinstance(op, dict):
        raise FactorContractError("operation/cost/target fact must be an object")
    values = {"quantity": op.get("quantity") if type(op.get("quantity")) is int else None}
    reason = op.get("reason") if reason is None else reason
    if reason in ("effect", "cost", "procedure"):
        values["reason_" + reason] = 1
    if op.get("owner") in ("self", "opponent"):
        values["owner_" + op["owner"]] = 1
    for zone in op.get("from_zones", ()):
        zone = "banish" if zone == "banished" else zone
        if "from_" + zone in GRAPH_ATTRIBUTES:
            values["from_" + zone] = 1
    zone = op.get("to_zone")
    if zone == "banished":
        zone = "banish"
    if isinstance(zone, str) and "to_" + zone in GRAPH_ATTRIBUTES:
        values["to_" + zone] = 1
    return tuple(sorted(values.items()))


def _card_features(row, snapshot, source, confidence):
    factors = {} if snapshot is None else dict(group_from_semantics(snapshot, key="card", source_ref=source,
                                       confidence=confidence, uncertainty=1 - confidence).factors.items)
    attrs = {}
    if row is not None:
        card_type = row.get("type")
        if type(card_type) is int:
            for key, bit in (("type_monster_fraction", 1), ("type_spell_fraction", 2), ("type_trap_fraction", 4),
                             ("type_quickplay_fraction", 0x10000), ("type_fusion_fraction", 0x40),
                             ("type_synchro_fraction", 0x2000), ("type_xyz_fraction", 0x800000),
                             ("type_link_fraction", 0x4000000), ("type_ritual_fraction", 0x80)):
                factors[key] = Observation(float(bool(card_type & bit)), 1, 0, source)
        for field, key in (("atk", "attack"), ("def", "defense"), ("level", "level")):
            value = row.get(field)
            if type(value) is int and value >= 0:
                attrs[key] = value & 255 if field == "level" else value
        for field, count in (("race", 26), ("attribute", 7)):
            if type(row.get(field)) is int:
                attrs.update({f"{field}_bit_{i}": float(bool(row[field] & (1 << i))) for i in range(count)})
    if snapshot is None:
        attrs["unparsed"] = 1
    else:
        attrs["unparsed"] = float(bool(snapshot.get("unknown")))
    return Factors.from_mapping("group", factors), tuple(sorted(attrs.items()))


def build_analysis_graph(example, *, card_rows=None, effect_snapshots=None, structure_links=(),
                         function_seeds=(), unit_contracts=(), source_ref="supplied_effect_facts",
                         confidence=0.55, catalog_digest="", budget=GraphBudget(),
                         candidate_budget=CandidateBudget()):
    """Shared v3 observations -> graph and natural candidates, without Torch.

    Only supplied facts and literal catalog metadata are read. Training records,
    labels, family names, route answers and model outputs are not arguments.
    Unparsed clauses remain explicit residual obligations, never free effects.
    """
    if not isinstance(example, RoleInput) or example.analysis_mode is None or not isinstance(budget, GraphBudget):
        raise FactorContractError("build_analysis_graph requires a v3 RoleInput and GraphBudget")
    text(source_ref, "graph fact source")
    unit(confidence, "graph fact confidence")
    rows = {} if card_rows is None else card_rows
    snapshots = {} if effect_snapshots is None else effect_snapshots
    if not isinstance(rows, dict) or not isinstance(snapshots, dict):
        raise FactorContractError("card_rows/effect_snapshots require code-keyed mappings")
    if not isinstance(structure_links, tuple) or any(not isinstance(v, StructureLink) for v in structure_links):
        raise FactorContractError("typed structure links required")
    if not isinstance(function_seeds, tuple) or any(not isinstance(v, FunctionSeed) for v in function_seeds):
        raise FactorContractError("typed function seeds required")
    if not isinstance(unit_contracts, tuple) or any(not isinstance(v, FunctionalContract) for v in unit_contracts):
        raise FactorContractError("typed source-declared combination contracts required")
    if len({(v.context_ref, v.key) for v in unit_contracts}) != len(unit_contracts):
        raise FactorContractError("combination contracts require distinct scoped keys")
    observed_links = {}
    for link in structure_links:
        key = link.structural_key()
        old = observed_links.get(key)
        observed_links[key] = link if old is None else replace(old, confidence=max(old.confidence, link.confidence),
            evidence_refs=tuple(sorted(set(old.evidence_refs) | set(link.evidence_refs))))
    structure_links = tuple(observed_links[k] for k in sorted(observed_links))
    deck = example.insertion.apply(example.deck) if example.insertion is not None else example.deck
    counts = {s: None if deck is None or getattr(deck, s) is None else dict(getattr(deck, s)) for s in ("main", "extra", "side")}
    member_refs = {f"card:{code}" for section in counts.values() if section is not None for code in section}
    if example.unit_definition is not None:
        member_refs.update(f"card:{code}" for code, _ in example.unit_definition.members)
    public_resources = example.analysis_context.public_resources
    if public_resources is not None:
        for resource in public_resources:
            member_refs.update(s for s in (resource.selector,) + resource.selectors if s.startswith("card:") and s[5:].isdigit())
    for link in structure_links:
        member_refs.update((link.source, link.target))
    seeds = list(function_seeds)
    member_refs.update(r for seed in seeds for r, _ in seed.members)
    unresolved, links = [], list(structure_links)
    for contract in unit_contracts:
        if contract.context_ref != example.context_ref:
            raise FactorContractError("combination facts must bind the current input context")
        if contract.period_ref is not None and example.analysis_context.period not in ("unknown", contract.period_ref):
            raise FactorContractError("combination facts belong to a different period")
        member_refs.update(m.ref for m in contract.roots)
        for dependency in contract.dependencies:
            member_refs.add(dependency.owner)
            member_refs.update(m.ref for m in dependency.required)
            member_refs.update(m.ref for alternative in dependency.alternatives for m in alternative)
        closure = minimum_member_branches(contract)
        if closure["overflow"]:
            unresolved.append(dict(reason="COMBINATION_CLOSURE_BUDGET", contract_ref=contract.key))
            continue  # Do not let a truncated, ID-ordered branch prefix become input.
        functions = tuple(sorted(set(contract.function_tags) & set(GRAPH_FUNCTIONS)))
        for branch in closure["branches"]:
            conditions = tuple(BranchConditions.from_dict(v) for v in branch["branch_conditions"])
            if contract.requirements is not None or contract.state_requirements is not None:
                conditions += (BranchConditions(contract.requirements, contract.state_requirements),)
            # Legacy opaque predicates remain unresolved, not rewritten as free.
            for known in contract.conditions:
                atom = Condition("declared_predicate", known.key, consume_mode="reusable",
                                 stage="deck" if known.scope == "structure" else "activation")
                conditions += (BranchConditions(structure=atom) if known.scope == "structure" else BranchConditions(state=atom),)
            if set(branch["members"]) - set(contract.reviewed_members):
                unresolved.append(dict(reason="DEPENDENCY_REVIEW_UNKNOWN", contract_ref=contract.key, branch_id=branch["branch_id"]))
            members = tuple(sorted(branch["members"].items()))
            member_refs.update(r for r, _ in members)
            seeds.append(FunctionSeed(contract.function_ref, members, functions, conditions,
                                      confidence=confidence, evidence_refs=tuple(branch["witness_refs"])))

    nodes, edges, resource_nodes = {}, {}, []
    def add_node(node):
        if node.ref in nodes and nodes[node.ref] != node:
            raise FactorContractError("conflicting graph node facts: " + node.ref)
        nodes[node.ref] = node
        if len(nodes) > budget.nodes:
            raise FactorContractError("graph node budget exceeded; no truncated graph is returned")

    def connect(source, target, kind, quantity=1, trust=1.0, evidence=()):
        if source == target:
            return
        key = (source, target, kind, quantity)
        edge = GraphEdge(source, target, kind, quantity, trust, tuple(evidence))
        old = edges.get(key)
        if old is not None:
            edge = replace(edge, confidence=max(old.confidence, trust),
                           evidence_refs=tuple(sorted(set(old.evidence_refs) | set(evidence))))
        edges[key] = edge
        if len(edges) > budget.edges:
            raise FactorContractError("graph edge budget exceeded; no truncated graph is returned")

    def condition_nodes(parent, branch_conditions, prefix):
        def visit(tree, ref, scope):
            if isinstance(tree, Condition):
                kind = "resource_" + tree.resource_type
                kind = kind if kind in GRAPH_ATTRIBUTES else "resource_other"
                attrs = {"scope_" + scope: 1, "quantity": tree.quantity, tree.consume_mode: 1, "stage_" + tree.stage: 1, kind: 1}
                if tree.until_stage is not None:
                    attrs["until_" + tree.until_stage] = 1
                if tree.owner in ("self", "opponent"):
                    attrs["owner_" + tree.owner] = 1
                if tree.state_zone is not None and "zone_" + tree.state_zone in GRAPH_ATTRIBUTES:
                    attrs["zone_" + tree.state_zone] = 1
                add_node(GraphNode(ref, "condition", Factors("group"), attributes=tuple(sorted(attrs.items())),
                                   section=tree.deck_section, evidence_refs=(source_ref,)))
                if tree.selector in nodes:
                    connect(ref, tree.selector, "requires", tree.quantity)
                for resource, resource_ref in resource_nodes:
                    if resource.resource_type == tree.resource_type and tree.selector in (resource.selector,) + resource.selectors:
                        # A supply cue retains its time/owner/zone fields on the
                        # resource node; this edge is not a feasibility verdict.
                        connect(ref, resource_ref, "provides", tree.quantity)
            else:
                add_node(GraphNode(ref, "condition", Factors("group"), attributes=(("scope_" + scope, 1), ("condition_" + tree.op, 1), ("min_count", tree.min_count))))
                for i, child in enumerate(tree.children):
                    child_ref = ref + f":{i}"
                    visit(child, child_ref, scope)
                    connect(ref, child_ref, "alternative" if tree.op in ("any", "at_least_k") else "requires")
            return ref
        for i, conditions in enumerate(branch_conditions):
            for scope in ("structure", "state"):
                tree = getattr(conditions, scope)
                if tree is not None:
                    ref = visit(tree, f"{prefix}:{i}:{scope}", scope)
                    connect(parent, ref, "has_condition")

    for section in ("main", "extra", "side"):
        stock = counts[section]
        total = None if stock is None else sum(stock.values())
        section_copies = tuple(total if s == section else None for s in ("main", "extra", "side"))
        add_node(GraphNode("section:" + section, "section", Factors("group"), copies=section_copies, section=section,
                           empty_status="unknown" if total is None else "empty" if total == 0 else "nonempty"))

    # Build all card nodes before resolving references, including absent required
    # members. Missing snapshots do not make effect absence a known zero.
    resolved = {}
    token_sources = defaultdict(set)
    for ref in sorted(member_refs):
        code = int(ref[5:]) if ref.startswith("card:") and ref[5:].isdigit() else None
        row = rows.get(code)
        snapshot = snapshots.get(code)
        if row is not None and (not isinstance(row, dict) or row.get("id", code) != code):
            raise FactorContractError("catalog row/card endpoint mismatch")
        if snapshot is None and row is not None and isinstance(row.get("desc"), str):
            from ..effect_mechanisms import analyze_card, SEMANTIC_VERSION
            from ..effect_records import effect_records
            profile = analyze_card(dict(row, id=code), catalog_digest)
            snapshot = profile.to_dict()
            snapshot['effects'] = [dict(record, text=record['source_text'], index=record['effect_index'],
                restrictions=record['restrictions'] + record['card_restrictions'])
                for record in effect_records(profile, semantic_version=SEMANTIC_VERSION, row=row)]
        if snapshot is not None and (not isinstance(snapshot, dict) or snapshot.get("card_id") not in (None, code)):
            raise FactorContractError("effect snapshot/card endpoint mismatch")
        source = source_ref + ":" + ref
        factors, attrs = _card_features(row, snapshot, source, confidence)
        quantities = tuple(None if code is None or counts[s] is None else counts[s].get(code, 0) for s in ("main", "extra", "side"))
        functions = () if snapshot is None else tuple(sorted({f for effect in snapshot["effects"]
                                             for op in effect.get("operations", ()) for f in _operation_functions(op)}))
        add_node(GraphNode(ref, "card", factors, quantities, functions, attrs, evidence_refs=(source,)))
        for section, quantity in zip(("main", "extra", "side"), quantities):
            if quantity:
                connect("section:" + section, ref, "contains", quantity)
        if snapshot is None:
            unresolved.append(dict(reason="MISSING_EFFECT_FACTS", member_ref=ref))
        else:
            resolved[ref] = snapshot
            if counts['main'] is None or counts['main'].get(code, 0):
                for effect in snapshot['effects']:
                    for op in effect.get('operations', ()):
                        generation = op.get('generation') or {}
                        if generation.get('kind') == 'token' and op.get('owner') == 'self':
                            token_sources[generation['name']].add(ref)

    pool_capacities, known_capacities = {}, {}
    for i, resource in enumerate(public_resources or ()):
        pool = resource.pool_id or resource.resource_id or f"anonymous:{i}"
        capacity = resource.quantity if resource.capacity is None else resource.capacity
        if pool in pool_capacities and pool_capacities[pool] != capacity:
            raise FactorContractError("resource pool aliases have inconsistent capacities")
        pool_capacities[pool] = capacity
        if resource.known:
            known_capacities[pool] = capacity
    resource_count = None if public_resources is None else len(pool_capacities)
    add_node(GraphNode("public_resources", "resource", Factors("group"),
                       attributes=(("quantity", resource_count),),
                       empty_status="unknown" if resource_count is None else "empty" if resource_count == 0 else "nonempty"))
    for i, resource in enumerate(public_resources or ()):
        resource_ref = f"resource_fact:{i}"
        pool = resource.pool_id or resource.resource_id or f"anonymous:{i}"
        pool_ref = "resource_pool:" + digest(pool)[:24]
        capacity = resource.quantity if resource.capacity is None else resource.capacity
        if pool_ref not in nodes:
            add_node(GraphNode(pool_ref, "resource", Factors("group"), attributes=(("capacity", known_capacities.get(pool)),)))
        kind = "resource_" + resource.resource_type
        kind = kind if kind in GRAPH_ATTRIBUTES else "resource_other"
        attrs = {"quantity": resource.quantity if resource.known else None,
                 "observation_known": float(resource.known), "stage_" + resource.stage: 1, kind: 1}
        if resource.available_until is not None:
            attrs["until_" + resource.available_until] = 1
        if resource.owner in ("self", "opponent"):
            attrs["owner_" + resource.owner] = 1
        zone = resource.state_zone or (resource.zone if resource.zone not in ("main", "extra", "side") else None)
        if zone is not None and "zone_" + zone in GRAPH_ATTRIBUTES:
            attrs["zone_" + zone] = 1
        section = resource.deck_section or (resource.zone if resource.zone in ("main", "extra", "side") else None)
        add_node(GraphNode(resource_ref, "resource", Factors("group"), attributes=tuple(sorted(attrs.items())),
                           section=section, evidence_refs=(resource.source,)))
        resource_nodes.append((resource, resource_ref))
        connect("public_resources", resource_ref, "contains")
        connect(pool_ref, resource_ref, "contains")
        for endpoint in (resource.selector,) + resource.selectors:
            if endpoint in member_refs:
                connect(resource_ref, endpoint, "provides")

    # Retain the full declared dependency graph even when candidate closure is
    # over budget. An unknown candidate set must not erase its input facts.
    for contract in unit_contracts:
        contract_ref = "contract:" + digest((contract.key, contract.function_ref))[:24]
        add_node(GraphNode(contract_ref, "function", Factors("group"), functions=tuple(sorted(set(contract.function_tags) & set(GRAPH_FUNCTIONS))),
                           evidence_refs=(contract.source,)))
        for root in contract.roots:
            connect(contract_ref, root.ref, "contains", root.quantity)
        for i, dependency in enumerate(contract.dependencies):
            dependency_ref = contract_ref + f":rule:{i}"
            add_node(GraphNode(dependency_ref, "dependency", Factors("group"), attributes=(("condition_all", 1),), evidence_refs=(dependency.source,)))
            connect(contract_ref, dependency_ref, "contains")
            connect(dependency.owner, dependency_ref, "requires")
            for member in dependency.required:
                connect(dependency_ref, member.ref, "requires", member.quantity)
            condition_nodes(dependency_ref, (dependency.conditions,), dependency_ref + ":conditions")
            for j, alternative in enumerate(dependency.alternatives):
                alternative_ref = dependency_ref + f":alternative:{j}"
                add_node(GraphNode(alternative_ref, "dependency", Factors("group"), attributes=(("condition_all", 1),)))
                connect(dependency_ref, alternative_ref, "alternative")
                for member in alternative:
                    connect(alternative_ref, member.ref, "requires", member.quantity)
                if dependency.alternative_conditions:
                    condition_nodes(alternative_ref, (dependency.alternative_conditions[j],), alternative_ref + ":conditions")
        condition_nodes(contract_ref, (BranchConditions(contract.requirements, contract.state_requirements),), contract_ref + ":conditions")
        for i, known in enumerate(contract.conditions):
            predicate_ref = contract_ref + f":predicate:{i}"
            add_node(GraphNode(predicate_ref, "condition", Factors("group"),
                attributes=(("unparsed", 1), ("stage_deck" if known.scope == "structure" else "stage_activation", 1)),
                evidence_refs=(known.source,)))
            connect(contract_ref, predicate_ref, "has_condition")
            unresolved.append(dict(reason="DECLARED_PREDICATE_REQUIRES_HOST_MAPPING", contract_ref=contract.key,
                                   predicate=known.key, scope=known.scope, declared_status=known.status, source=known.source))

    relation_checks, relation_overflow = 0, False
    generated_start, automatic_edge_keys = len(links), set()
    allocation_seeds = []
    from ..construction_inventory import selector, matches, query_supported, requirement
    for ref in sorted(resolved):
        snapshot = resolved[ref]
        for effect_position, effect in enumerate(snapshot["effects"]):
            effect_ref = ref + f":effect:{effect_position}"
            effect_source = f"{source_ref}:{ref}:effect:{effect_position}"
            partial = dict(snapshot, effects=[effect])
            effect_factors = group_from_semantics(partial, key="effect", source_ref=effect_source,
                                                  confidence=confidence, uncertainty=1 - confidence).factors
            effect_attrs = {"unparsed": float(bool(effect.get("unknown")))}
            for limit in effect.get("count_limits", ()):
                if not isinstance(limit, dict):
                    raise FactorContractError("count limit fact must be an object")
                if limit.get("status") != "known":
                    continue
                scope = limit.get("scope", "")
                if scope.startswith("same_name"):
                    effect_attrs["limit_by_name"] = 1
                elif scope in ("this_card", "this_card_effect", "card_instance"):
                    effect_attrs["limit_by_instance"] = 1
                event = limit.get("count_event")
                if event == "use":
                    effect_attrs["limit_use"] = 1
                elif event in ("card_activation", "effect_activation"):
                    effect_attrs["limit_activation"] = 1
            add_node(GraphNode(effect_ref, "effect", effect_factors,
                               attributes=tuple(sorted(effect_attrs.items())), evidence_refs=(effect_source,)))
            connect(ref, effect_ref, "contains")
            for i, limit in enumerate(effect.get("count_limits", ())):
                limit_ref = effect_ref + f":limit:{i}"
                attrs = {"count_maximum": limit.get("maximum") if type(limit.get("maximum")) is int else None,
                         "unparsed": float(limit.get("status") != "known")}
                scope, event = limit.get("scope", ""), limit.get("count_event")
                if scope.startswith("same_name"):
                    attrs["limit_by_name"] = 1
                elif scope in ("this_card", "this_card_effect", "card_instance"):
                    attrs["limit_by_instance"] = 1
                if event == "use":
                    attrs["limit_use"] = 1
                elif event in ("card_activation", "effect_activation"):
                    attrs["limit_activation"] = 1
                    attrs["limit_" + event] = 1
                add_node(GraphNode(limit_ref, "condition", Factors("group"), attributes=tuple(sorted(attrs.items())), evidence_refs=(effect_source,)))
                connect(effect_ref, limit_ref, "has_condition")
            raw = effect.get("text", "")
            options = [v.strip() for v in raw.split("●")[1:] if v.strip()] if "●" in raw and re.search(r"以下.*?选择.*?(?:1|一)个", raw) else []
            mode_refs = []
            for i, _ in enumerate(options):
                mode_ref = effect_ref + f":mode:{i}"
                mode_refs.append(mode_ref)
                add_node(GraphNode(mode_ref, "mode", Factors("group"), evidence_refs=(effect_source,)))
                connect(effect_ref, mode_ref, "contains")
            for left in mode_refs:
                for right in mode_refs:
                    connect(left, right, "alternative")
            simultaneous = defaultdict(list)
            for op_index, op in enumerate(effect.get("operations", ())):
                functions = _operation_functions(op)
                if not functions:
                    if op.get("reason") == "effect":
                        unresolved.append(dict(reason="UNSEEN_OR_UNRESOLVED_FUNCTION", effect_ref=effect_ref, operation=op_index))
                    continue
                matched_options = [i for i, value in enumerate(options) if op.get("source") and op["source"] in value]
                choice = op.get('choice')
                if options and len(matched_options) != 1 and not choice:
                    unresolved.append(dict(reason="MODE_ASSIGNMENT_UNKNOWN", effect_ref=effect_ref, operation=op_index))
                    continue
                mode = matched_options[0] if len(matched_options) == 1 else None
                function_ref = effect_ref + f":op:{op_index}"
                modes = ((effect_ref, choice),) if choice else () if mode is None else ((effect_ref, str(mode)),)
                residual = BranchConditions(state=Condition("effect_clause", function_ref, stage="activation", consume_mode="reusable"))
                add_node(GraphNode(function_ref, "function", Factors("group"), functions=functions,
                                   attributes=_operation_attributes(op), evidence_refs=(effect_source,)))
                connect(mode_refs[mode] if mode is not None else effect_ref, function_ref, "realizes")
                condition_nodes(function_ref, (residual,), function_ref + ":conditions")
                seeds.append(FunctionSeed(function_ref, ((ref, 1),), functions, (residual,), modes, confidence, (effect_source,)))
                if op.get('selection_method') == 'revealed_card':
                    comparison = next((entry for entry in effect['operations']
                                       if entry.get('different_name_from_reveal') == op.get('subject_ref')), None)
                    if (comparison is None or not query_supported(op.get('selector_query'))
                            or not query_supported(comparison.get('selector_query'))):
                        unresolved.append(dict(reason='REVEALED_CARD_SCOPE_UNKNOWN', function_ref=function_ref))
                        continue
                    stock = counts['main'] or {}
                    summonable = [code for code in stock if code in rows and matches(rows[code], op['selector_query'])]
                    banishable = [code for code in stock if code in rows and matches(rows[code], comparison['selector_query'])]
                    for shown, banished in product(summonable, banishable):
                        relation_checks += 1
                        if relation_checks > budget.relation_checks:
                            relation_overflow = True
                            break
                        left, right = rows[shown], rows[banished]
                        if ((left.get('alias') or shown) == (right.get('alias') or banished)
                                or left.get('name') == right.get('name')):
                            continue
                        chosen = Counter((ref, f'card:{shown}', f'card:{banished}'))
                        if any(stock.get(int(member[5:]), 0) < n for member, n in chosen.items()):
                            continue
                        choices = modes + ((function_ref + ':revealed_card', f'card:{shown}'),
                                           (function_ref + ':banished_card', f'card:{banished}'))
                        allocation_seeds.append(FunctionSeed(function_ref, tuple(sorted(chosen.items())), ('banish', 'follow_up'),
                            (residual,), choices, confidence, (effect_source,)))
                    continue
                trigger = effect.get('trigger', {}).get('source', '') or ''
                token = re.search(r'自己场上有「([^」]+衍生物)」存在', trigger)
                if token and '或者' not in trigger and '或有' not in trigger:
                    producers = sorted(token_sources.get(token[1], set()) - {ref})
                    for producer in producers:
                        links.append(StructureLink(ref, producer, 'requires' if len(producers) == 1 else 'provides', functions, function_ref,
                            required=len(producers) == 1, confidence=confidence, evidence_refs=(effect_source,)))
                        connect(producer, function_ref, 'provides', trust=confidence, evidence=(effect_source,))
                        automatic_edge_keys.add((producer, function_ref, 'provides', 1))
                relation_kind = {"search": "calls", "recover": "recycles", "special_summon": "calls",
                    "send_grave": "provides", "fusion_summon": "calls", "ritual": "calls",
                    "resource_supply": "provides"}.get(functions[0])
                if functions == ('follow_up',):
                    query = op.get('selector_query', {})
                    if set(query) - {'selector', 'type'}:
                        relation_kind = 'calls'
                if (relation_kind is None or op.get('owner') in ('opponent', 'both') or op.get('generation')
                        or op.get('random') is True or op.get('different_name_from_cost') is not None
                        or op.get('different_name_from_reveal') is not None):
                    continue
                query = op.get('selector_query') or selector(op.get("selector") or "")
                parsed = None
                if query is None:
                    parsed = requirement(op.get("selector") or op.get("source", ""), "targets")
                    query = None if parsed is None else parsed["query"]
                if not query_supported(query):
                    unresolved.append(dict(reason="UNPARSED_TARGET_SELECTOR", function_ref=function_ref))
                    continue
                amount = op.get("quantity") if type(op.get("quantity")) is int and op["quantity"] > 0 else (
                    parsed["minimum"] if parsed is not None else None)
                if amount is None:
                    unresolved.append(dict(reason="TARGET_QUANTITY_UNKNOWN", function_ref=function_ref))
                    continue
                targets = []
                group_key = (op['simultaneous_group'], choice) if 'simultaneous_group' in op else None
                origins = set(op.get('from_zones') or ())
                sections = ('extra',) if origins == {'extra'} else ('main',) if origins and origins <= {'hand', 'deck'} else ('main', 'extra')
                self_target = (group_key is not None and op.get('target_ref') is not None
                               and origins == {'field'} and op.get('owner') == 'self')
                for target in sorted(member_refs):
                    if (target == ref and not self_target
                            or not target.startswith("card:") or not target[5:].isdigit()):
                        continue
                    relation_checks += 1
                    if relation_checks > budget.relation_checks:
                        relation_overflow = True
                        break
                    code = int(target[5:])
                    target_row = rows.get(code)
                    if target_row is not None and matches(target_row, query):
                        quantity = (amount if deck is None else sum((counts[section] or {}).get(code, 0) for section in sections))
                        if not quantity:
                            continue
                        targets.extend([target] * min(quantity, amount))
                        if amount != 1 or group_key is not None:
                            continue
                        target_choice = modes + ((function_ref + ":target_choice", target),)
                        placement = op['kind'] == 'place' and 'exact_name' in query
                        link = StructureLink(ref, target, relation_kind, () if placement else functions,
                            None if placement else function_ref,
                            quantity=amount, confidence=confidence, mode_choices=target_choice, evidence_refs=(effect_source,))
                        links.append(link)
                        connect(function_ref, target, relation_kind, trust=confidence, evidence=(effect_source,))
                        automatic_edge_keys.add((function_ref, target, relation_kind, 1))
                if group_key is not None:
                    simultaneous[group_key].append((function_ref, functions, residual, modes, targets, amount, sections))
                elif amount > 1 and not relation_overflow:
                    groups = set()
                    for group in combinations(targets, amount):
                        relation_checks += 1
                        if relation_checks > budget.relation_checks:
                            relation_overflow = True
                            break
                        groups.add(tuple(sorted(Counter(group).items())))
                    for group in sorted(groups):
                        allocation_seeds.append(FunctionSeed(function_ref, tuple(sorted(((ref, 1), *group))),
                            functions, (residual,), modes + ((function_ref + ':target_choice', digest(group)),),
                            confidence, (effect_source,)))
            for group in simultaneous.values():
                if len(group) < 2 or relation_overflow:
                    continue
                options_by_output = []
                for _, _, _, _, targets, amount, _ in group:
                    selections = set()
                    for selected in combinations(targets, amount):
                        relation_checks += 1
                        if relation_checks > budget.relation_checks:
                            relation_overflow = True
                            break
                        selections.add(selected)
                    options_by_output.append(sorted(selections))
                    if relation_overflow:
                        break
                if relation_overflow:
                    break
                function_ref, functions, residual, modes, _, _, sections = group[0]
                for chosen in product(*options_by_output):
                    relation_checks += 1
                    if relation_checks > budget.relation_checks:
                        relation_overflow = True
                        break
                    selected = Counter(target for selection in chosen for target in selection)
                    if deck is not None and any(sum((counts[section] or {}).get(int(target[5:]), 0)
                            for section in sections) < quantity for target, quantity in selected.items()):
                        continue
                    # An explicit field target may be the activating card.
                    selected.setdefault(ref, 1)
                    members = tuple(sorted(selected.items()))
                    allocation_seeds.append(FunctionSeed(function_ref, members, functions, (residual,),
                        modes + ((function_ref + ':target_choice', digest(chosen)),), confidence, (effect_source,)))
            for category in ("costs", "targets"):
                for position, item in enumerate(effect.get(category, ())):
                    obligation = effect_ref + f":{category}:{position}"
                    attrs = _operation_attributes(item, reason="cost" if category == "costs" else None)
                    add_node(GraphNode(obligation, "condition", Factors("group"), attributes=attrs, evidence_refs=(effect_source,)))
                    connect(effect_ref, obligation, "consumes" if category == "costs" else "requires")
        # Reuse the existing exact material selector; all matches remain
        # conditional candidates rather than full summon assignments.
        for position, material in enumerate(snapshot.get("materials", ())):
            from ..effect_mechanisms import material_matches
            scope = ref + f":material:{position}"
            residual = BranchConditions(state=Condition("material_assignment", scope, stage="activation", consume_mode="reusable"))
            seeds.append(FunctionSeed(scope, ((ref, 1),), ("fusion_summon",), (residual,), confidence=confidence, evidence_refs=(source_ref,)))
            for target in sorted(member_refs):
                if target == ref or not target.startswith("card:") or not target[5:].isdigit():
                    continue
                relation_checks += 1
                if relation_checks > budget.relation_checks:
                    relation_overflow = True
                    break
                row = rows.get(int(target[5:]))
                if row is not None and material_matches(row, material):
                    quantity = material.get("count", 1)
                    links.append(StructureLink(ref, target, "material", ("fusion_summon",), scope,
                        quantity=quantity, confidence=confidence, evidence_refs=(source_ref,)))
                    connect(target, ref, "material", quantity, confidence, (source_ref,))
                    automatic_edge_keys.add((target, ref, "material", quantity))

    # A printed Link material line supplies a procedure candidate. A known
    # field-to-GY trigger on that material can use the same conditional move.
    from ..construction_inventory import printed_link_material
    for target_ref in sorted(resolved):
        target_code = int(target_ref[5:])
        material = printed_link_material(rows.get(target_code, {}))
        if material is None or counts['extra'] is None or not counts['extra'].get(target_code):
            continue
        rating = material['rating']
        if rating != 1 or rating < material['minimum'] or material['exact'] and rating != material['minimum']:
            continue
        if material['normal_summoned'] and rating > 1:
            continue
        stock = [f'card:{code}' for code, count in (counts['main'] or {}).items()
                 if code in rows and matches(rows[code], material['query']) for _ in range(min(count, rating))]
        scope = target_ref + ':printed_link_materials'
        residual = BranchConditions(state=Condition('material_assignment', scope, stage='activation', consume_mode='reusable'))
        seen = set()
        for selected in combinations(stock, rating):
            relation_checks += 1
            if relation_checks > budget.relation_checks:
                relation_overflow = True
                break
            members = tuple(sorted(((target_ref, 1), *Counter(selected).items())))
            if members in seen:
                continue
            seen.add(members)
            allocation_seeds.append(FunctionSeed(scope, members, ('link',), (residual,),
                confidence=confidence, evidence_refs=(source_ref + ':' + scope,)))
            if rating == 1:
                source = selected[0]
                for position, effect in enumerate(resolved[source]['effects']):
                    if (effect.get('trigger', {}).get('event') != 'sent_to_grave'
                            or not re.search(r'这张卡从场上送去墓地', effect.get('source_text', effect.get('text', '')))):
                        continue
                    for op_index, operation in enumerate(effect.get('operations', ())):
                        functions = _operation_functions(operation)
                        if functions:
                            function_ref = source + f':effect:{position}:op:{op_index}'
                            links.append(StructureLink(source, target_ref, 'provides', functions, function_ref,
                                confidence=confidence, evidence_refs=(source_ref + ':' + scope,)))

    if relation_overflow:
        # Target enumeration is one transaction. Keep all card/effect facts,
        # withhold the incomplete automatic match set, and report its budget.
        links = links[:generated_start]
        for key in automatic_edge_keys:
            edges.pop(key, None)
    else:
        seeds.extend(allocation_seeds)

    if example.unit_definition is not None:
        requested = example.unit_definition.function_id
        requested = requested[9:] if requested.startswith("function:") else requested
        functions = (requested,) if requested in GRAPH_FUNCTIONS else ()
        query_ref = "query:unit"
        add_node(GraphNode(query_ref, "function", Factors("group"), functions=functions,
                           attributes=(("unseen_function", float(not functions)),)))
        for code, quantity in example.unit_definition.members:
            connect(query_ref, f"card:{code}", "contains", quantity)

    def mode_guards(parent, modes):
        for scope, choice in modes:
            mode_ref = scope + ":mode:" + choice
            if mode_ref not in nodes:
                mode_ref = "mode_choice:" + digest((scope, choice))[:24]
                group_ref = "mode_scope:" + digest(scope)[:24]
                if group_ref not in nodes:
                    add_node(GraphNode(group_ref, "effect", Factors("group"), attributes=(("unparsed", 1),)))
                if mode_ref not in nodes:
                    add_node(GraphNode(mode_ref, "mode", Factors("group")))
                    siblings = [e.target for e in edges.values() if e.source == group_ref and e.kind == "contains"]
                    for sibling in siblings:
                        connect(mode_ref, sibling, "alternative")
                        connect(sibling, mode_ref, "alternative")
                    connect(group_ref, mode_ref, "contains")
            connect(parent, mode_ref, "has_condition")

    for link in structure_links:
        if link.condition is not None or link.mode_choices:
            scope = "structure_link:" + link.structural_key()[:24]
            add_node(GraphNode(scope, "dependency", Factors("group")))
            connect(link.source, scope, "requires" if link.required else "realizes")
            connect(scope, link.target, link.kind, link.quantity, link.confidence, link.evidence_refs)
            if link.condition is not None:
                condition_nodes(scope, (link.condition,), scope + ":conditions")
            mode_guards(scope, link.mode_choices)
        else:
            connect(link.source, link.target, link.kind, link.quantity, link.confidence, link.evidence_refs)
    member_features = {ref: nodes[ref].numeric_values() for ref in member_refs}
    candidates = generate_axis_candidates(tuple(seeds), tuple(links), member_features=member_features, budget=candidate_budget)
    extra_reasons = []
    if relation_overflow:
        extra_reasons.append("fact_relation_budget")
    if any(v["reason"] == "COMBINATION_CLOSURE_BUDGET" for v in unresolved):
        extra_reasons.append("combination_closure_budget")
    if extra_reasons:
        candidates = replace(candidates, overflow=True, reasons=tuple(sorted(set(candidates.reasons) | set(extra_reasons))))
    for candidate in candidates.units + candidates.candidates:
        ref = candidate.candidate_id
        kind = "axis" if len(candidate.members) > 1 else "function"
        add_node(GraphNode(ref, kind, Factors("group"), functions=candidate.functions,
                           attributes=(("quantity", sum(n for _, n in candidate.members)),), evidence_refs=candidate.evidence_refs))
        dependency = ref + ":dependency"
        add_node(GraphNode(dependency, "dependency", Factors("group")))
        connect(ref, dependency, "requires")
        for member, quantity in candidate.members:
            connect(dependency, member, "requires", quantity)
        condition_nodes(ref, candidate.conditions, ref + ":conditions")
        mode_guards(ref, candidate.mode_choices)
    for candidate in candidates.candidates:
        for parent in candidate.parent_ids:
            if parent in nodes:
                connect(candidate.candidate_id, parent, "parent_axis")
    graph = AnalysisGraph(tuple(nodes[k] for k in sorted(nodes)), tuple(edges[k] for k in sorted(edges)))
    return GraphBuild(example, graph, candidates, tuple(unresolved), budget)
