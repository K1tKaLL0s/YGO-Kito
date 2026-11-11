"""Versioned observations/labels preparation. Never imports a model or Torch."""
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import gzip
import json
from pathlib import Path
import sqlite3
import uuid

from ygo_kito.multifactor.contracts import (AnalysisContext, DeckSpec, FactorContractError,
    Factors, FunctionSeed, GRAPH_VERSION, GraphNode, LabelCell, LabelSet, RoleInput, ROLES, StructureLink, UnitSpec, digest)
from ygo_kito.multifactor.functional_units import FunctionalContract
from ygo_kito.multifactor.semantics import build_analysis_graph
from ygo_kito.multifactor.splits import (SPLIT_VERSION, assign_group_splits, build_leakage_groups, referenced_cards)

ROOT = Path(__file__).resolve().parent
VERSION = "axis-dataset-v3"
RECORD_VERSION = "axis-training-record-v3"
SOURCE_KINDS = ("engineering_fixture", "definition_development", "engine_probe", "self_generated_candidate",
                "human_feedback", "weak_context_annotation")
ROLE_SOURCES = ("engineering_fixture", "definition_development", "human_feedback", "weak_context_annotation")


class CacheMismatch(ValueError):
    pass


def read_json(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", "utf-8")


@lru_cache(maxsize=8192)
def _numeric_values(kind,factors,copies,functions,attributes,section,empty_status):
    return GraphNode('numeric-cache',kind,factors,copies,functions,attributes,section,empty_status).numeric_values()


def _node_values(node):
    return _numeric_values(node.kind,node.factors,node.copies,node.functions,node.attributes,node.section,node.empty_status)


def _canonical_graph(graph, budget=4096):
    """Exact, bounded canonical ordering anchored to real cards/sections.

    Metadata refs never order features. Symmetric twins can be exchanged;
    unresolved non-twin symmetry is individualized and searched. Exhaustion
    refuses a cache key instead of merging different graphs by a WL hash.
    """
    nodes = graph.nodes
    indices = {n.ref: i for i, n in enumerate(nodes)}
    attributes = [_node_values(n) for n in nodes]
    anchors = [n.ref if n.kind == "card" and n.ref.startswith("card:") and n.ref[5:].isdigit()
               else "section:" + n.section if n.kind == "section" and n.section else "" for n in nodes]
    edges = [(indices[e.source], indices[e.target], e.kind, e.quantity, e.confidence) for e in graph.edges]
    edge_counts = Counter(edges)
    outgoing, incoming = defaultdict(list), defaultdict(list)
    for a,b,k,q,c in edges:
        outgoing[a].append((b,k,q,c))
        incoming[b].append((a,k,q,c))
    def ranks(values):
        order = {k:i for i,k in enumerate(sorted(set(values)))}
        return tuple(order[k] for k in values)
    initial = ranks(list(zip(anchors,attributes)))
    def refine(colors):
        for _ in range(len(nodes) + 1):
            signatures = [(colors[i], tuple(sorted((k,q,c,colors[j]) for j,k,q,c in outgoing[i])),
                           tuple(sorted((k,q,c,colors[j]) for j,k,q,c in incoming[i]))) for i in range(len(nodes))]
            updated = ranks(signatures)
            if len(set(updated)) == len(set(colors)):
                return updated
            colors = updated
        return colors
    steps = 0
    match_steps = 0
    def equivalent(colors,left,right):
        nonlocal match_steps
        import networkx as nx
        counts=Counter(colors)
        uncertain={i for i,color in enumerate(colors) if counts[color]>1}
        matcher_graph=nx.DiGraph()
        for i in uncertain:
            boundary=(tuple(sorted((colors[j],k,q,c) for j,k,q,c in outgoing[i] if j not in uncertain)),
                      tuple(sorted((colors[j],k,q,c) for j,k,q,c in incoming[i] if j not in uncertain)))
            matcher_graph.add_node(i,boundary=boundary)
        relations=defaultdict(list)
        for a,b,k,q,c in edges:
            if a in uncertain and b in uncertain:
                relations[a,b].append((k,q,c))
        for (a,b),values in relations.items():
            matcher_graph.add_edge(a,b,relations=tuple(sorted(values)))
        first,second=matcher_graph.copy(),matcher_graph.copy()
        for i in uncertain:
            first.nodes[i]['color']=(colors[i],i==left,first.nodes[i]['boundary'])
            second.nodes[i]['color']=(colors[i],i==right,second.nodes[i]['boundary'])
        class BoundedMatcher(nx.algorithms.isomorphism.DiGraphMatcher):
            def candidate_pairs_iter(self):
                for a,b in super().candidate_pairs_iter():
                    if self.G1.nodes[a]['color']==self.G2.nodes[b]['color']:
                        yield a,b
            def syntactic_feasibility(self,a,b):
                nonlocal match_steps
                match_steps+=1
                if match_steps>budget*max(len(nodes),1):
                    raise ValueError('canonical isomorphism budget exhausted')
                return super().syntactic_feasibility(a,b)
        matcher=BoundedMatcher(first,second,node_match=lambda a,b:a['color']==b['color'],
                               edge_match=lambda a,b:a['relations']==b['relations'])
        try:
            return matcher.is_isomorphic()
        finally:
            matcher.reset_recursion_limit()
    def encode(order,full=False):
        positions = {old:new for new,old in enumerate(order)}
        return json.dumps(dict(nodes=[(anchors[i],attributes[i]) if full else initial[i] for i in order],
            edges=sorted((positions[a],positions[b],k,q,c) for a,b,k,q,c in edges)), separators=(",", ":"), allow_nan=False)
    def search(colors):
        nonlocal steps
        steps += 1
        if steps > budget:
            raise ValueError("canonical input budget exhausted; no approximate input_key is cached")
        colors = refine(colors)
        groups = defaultdict(list)
        for i,c in enumerate(colors):
            groups[c].append(i)
        ordered = [v for _,v in sorted(groups.items())]
        ambiguous = [v for v in ordered if len(v)>1]
        if not ambiguous:
            order=[i for group in ordered for i in group]
            return encode(order),order
        twin_groups, unresolved = [], []
        for group in ambiguous:
            first = group[0]
            for other in group[1:]:
                steps += 1
                if steps > budget:
                    raise ValueError("canonical input budget exhausted")
                swap = {first:other, other:first}
                if Counter((swap.get(a,a),swap.get(b,b),k,q,c) for a,b,k,q,c in edges) != edge_counts:
                    unresolved.append(group)
                    break
            else:
                twin_groups.append(group)
        # Each accepted transposition preserves the complete edge multiset.
        # Disjoint twin classes therefore admit every within-class permutation;
        # their arbitrary member order cannot change the encoded graph.
        if not unresolved:
            order=[i for group in ordered for i in group]
            return encode(order),order
        if twin_groups:
            updated = list(colors)
            next_color = max(colors,default=0)+1
            for group in twin_groups:
                for i in group:
                    updated[i] = next_color
                    next_color += 1
            return search(tuple(updated))
        possibilities = []
        representatives = []
        for i in unresolved[0]:
            if any(equivalent(colors,other,i) for other in representatives):
                continue
            representatives.append(i)
            updated = list(colors)
            updated[i] = max(colors, default=0) + 1
            possibilities.append(search(tuple(updated)))
        return min(possibilities,key=lambda result:result[0])
    _,order=search(initial)
    return encode(order,full=True)


def input_key(build, canonical_budget=4096):
    from ygo_kito.multifactor.task_queries import INTENT_FACTORS
    example = build.input
    context = example.analysis_context
    query = None if example.unit_definition is None else dict(members=example.unit_definition.members,
                                                             function_id=example.unit_definition.function_id)
    return digest(dict(graph=_canonical_graph(build.graph, canonical_budget), analysis_mode=example.analysis_mode,
        format=context.format, period=context.period, rule_version=context.rule_version,
        unit=query, visible_state=example.visible_state,
        intent=[channel for name in INTENT_FACTORS for channel in example.context.get(name).channels()]))


def _empty_targets():
    return dict(roles=[], compatibility=[], pairs=[], task_labels=[])


def normalize_targets(value):
    result = _empty_targets()
    if not isinstance(value, dict) or not set(value) <= set(result):
        raise FactorContractError("targets require roles/compatibility/pairs/task_labels")
    result.update(deepcopy(value))
    for name in result:
        if not isinstance(result[name], list):
            raise FactorContractError("target collections must be arrays")
    seen = set()
    for row in result["roles"]:
        if not isinstance(row, list) or len(row)!=2 or not isinstance(row[1], list) or len(row[1])!=len(ROLES) or row[0] in seen:
            raise FactorContractError("distinct legacy role vectors required")
        seen.add(row[0])
        row[1] = [LabelCell.from_dict(c).validate_domain().to_dict() for c in row[1]]
    for name, width in (("compatibility",2),("pairs",3)):
        seen = set()
        for row in result[name]:
            if not isinstance(row,list) or len(row)!=width or tuple(row[:-1]) in seen:
                raise FactorContractError("distinct typed target rows required")
            seen.add(tuple(row[:-1]))
            row[-1] = LabelCell.from_dict(row[-1]).validate_domain().to_dict()
    labels = [LabelSet.from_dict(v) for v in result["task_labels"]]
    if len({(v.task,v.subject) for v in labels}) != len(labels):
        raise FactorContractError("duplicate task annotation scope")
    for name in ("roles","compatibility","pairs"):
        result[name].sort(key=lambda row:tuple(row[:-1]))
    result["task_labels"] = [replace(v,cells=tuple(sorted(v.cells))).to_dict() for v in sorted(labels,key=lambda v:(v.task,v.subject))]
    return result


def _withdraw(cell, status, reason, changes, coordinate):
    old = LabelCell.from_dict(cell)
    new = LabelCell(status=status, confidence=0, evidence_kind=old.evidence_kind,
                    evidence_refs=old.evidence_refs, review_status=old.review_status)
    if old != new:
        changes.append(dict(coordinate=coordinate, before=old.to_dict(), after=new.to_dict(), reason=reason))
    return new.to_dict()


def migrate_targets(raw, example):
    targets = normalize_targets(raw.get("targets", {}))
    meta = raw.get("provenance", {})
    changes = []
    deck = example.insertion.apply(example.deck) if example.insertion is not None else example.deck
    absent = False
    if example.analysis_mode == "deck_analysis" and example.unit_definition is not None and deck is not None:
        if deck.main is not None and deck.extra is not None:
            actual = Counter(dict(deck.main)) + Counter(dict(deck.extra))
            absent = all(actual[c] == 0 for c,_ in example.unit_definition.members)
    for key, cells in targets["roles"]:
        if meta.get("legacy_unreviewed_variant") is True:
            for i in range(len(cells)):
                cells[i] = _withdraw(cells[i], "unknown", "changed_construction_has_no_scoped_role_annotation", changes, ["roles",key,ROLES[i]])
        for i in (2,3):
            if absent:
                cells[i] = _withdraw(cells[i], "not_applicable", "focal_unit_not_present_in_deck", changes, ["roles",key,ROLES[i]])
            elif meta.get("plan_actor_absent") is True or meta.get("actor_presence_unknown") is True:
                cells[i] = _withdraw(cells[i], "unknown", "actor_absence_is_not_structural_negative", changes, ["roles",key,ROLES[i]])
            elif meta.get("legacy_plan_not_in_model_input") is True:
                cells[i] = _withdraw(cells[i], "unknown", "legacy_primary_plan_not_represented_in_v3_observations", changes, ["roles",key,ROLES[i]])
        if meta.get("readiness_only") is True:
            for i in (2,3):
                if LabelCell.from_dict(cells[i]).known and cells[i]["value"] < .5:
                    cells[i] = _withdraw(cells[i], "unknown", "state_readiness_does_not_negate_structural_role", changes, ["roles",key,ROLES[i]])
            cells[4] = _withdraw(cells[4], "unknown", "state_readiness_is_not_transferability", changes, ["roles",key,ROLES[4]])
    task_labels = []
    for value in targets["task_labels"]:
        label_set = LabelSet.from_dict(value)
        cells = dict(label_set.cells)
        for coordinate, cell in cells.items():
            status, reason = None, None
            if meta.get("readiness_only") and label_set.task == "transferability":
                status, reason = "unknown", "state_readiness_is_not_transferability"
            if label_set.task == "state_readiness" and not example.visible_state:
                status, reason = "unknown", "visible_state_not_provided"
            if label_set.task == "receiver_compatibility" and example.analysis_mode == "unit_analysis" and example.deck is None:
                status, reason = "not_applicable", "receiver_not_specified"
            if status:
                cells[coordinate] = LabelCell.from_dict(_withdraw(cell.to_dict(), status, reason, changes,
                                                                 [label_set.task,*label_set.subject,coordinate]))
        task_labels.append(replace(label_set,cells=tuple(cells.items())).to_dict())
    targets["task_labels"] = task_labels
    return targets, changes


def _build(raw, catalog):
    obs = raw["observations"]
    example = RoleInput.from_dict(obs["input"])
    rows = dict(catalog)
    rows.update({int(k):v for k,v in obs.get("card_rows",{}).items()})
    return build_analysis_graph(example, card_rows=rows,
        effect_snapshots={int(k):v for k,v in obs.get("effect_snapshots",{}).items()},
        structure_links=tuple(StructureLink.from_dict(v) for v in obs.get("structure_links",())),
        function_seeds=tuple(FunctionSeed.from_dict(v) for v in obs.get("function_seeds",())),
        unit_contracts=tuple(FunctionalContract.from_dict(v) for v in obs.get("functional_contracts",())),
        source_ref="versioned_preparation_facts")


def _build_record(row,catalog,canonical_budget):
    from ygo_kito.multifactor.task_queries import validate_comparison
    from ygo_kito.multifactor.contracts import fields
    build=_build(row,catalog)
    key=input_key(build,canonical_budget)
    comparison=None
    if row.get("comparison") is not None:
        raw=row["comparison"]
        fields(raw,("right","left_key","right_key","operation"))
        right=_build({"observations":raw["right"]},catalog)
        validate_comparison(build,right,left_key=raw["left_key"],right_key=raw["right_key"],operation=raw["operation"])
        operation=dict(raw["operation"])
        operation["kind"]="replacement" if operation["add"]["quantity"]==operation["remove"]["quantity"] else "mixed_change"
        comparison=dict(raw,right=right.to_dict()["observations"],operation=operation)
        key=digest((key,input_key(right,canonical_budget),comparison["left_key"],comparison["right_key"],operation))
    return build,key,comparison


def _inherit_targets(parent, variant, same_input):
    if "targets" in variant:
        return normalize_targets(variant["targets"])
    if same_input:
        return deepcopy(parent["targets"])
    result = _empty_targets()
    # Only complete-unit portability can be declared invariant to a receiver
    # change. All facts/query/resources must otherwise remain the same.
    scopes = variant.get("invariance_scope", {})
    if scopes.get("transferability") == "unit_definition":
        def intrinsic(row):
            value = deepcopy(row["observations"])
            inp = value["input"]["observations"]
            inp.pop("context_ref",None)
            inp.pop("deck",None)
            inp.pop("visible_state",None)
            inp.pop("insertion",None)
            if inp.get("unit") is not None:
                inp["unit"].pop("unit_id",None)
            return value
        left = RoleInput.from_dict(parent["observations"]["input"])
        right = RoleInput.from_dict(variant["observations"]["input"])
        if left.unit_definition is not None and left.analysis_mode == right.analysis_mode == "unit_analysis" and intrinsic(parent) == intrinsic(variant):
            result["task_labels"] = [deepcopy(v) for v in parent["targets"]["task_labels"] if v["task"] == "transferability"]
    return result


def _merge_cell(a, b, conflicts, coordinate):
    left, right = LabelCell.from_dict(a), LabelCell.from_dict(b)
    if left.status == "unknown":
        return b
    if right.status == "unknown":
        return a
    if left.status == right.status and left.value == right.value:
        refs = tuple(sorted(set(left.evidence_refs) | set(right.evidence_refs)))
        if len(refs)>32:
            conflicts.append(dict(coordinate=coordinate, reason="evidence_reference_overflow", evidence_refs=list(refs)))
        representative = min((left,right), key=lambda v:digest(v.to_dict()))
        return replace(representative, confidence=max(left.confidence,right.confidence), evidence_refs=refs[:32]).to_dict()
    conflicts.append(dict(coordinate=coordinate, reason="same_input_annotation_conflict", values=sorted([a,b],key=digest)))
    return LabelCell(status="conflict", confidence=0, evidence_kind="conflicting_annotations",
                     evidence_refs=tuple(sorted(set(left.evidence_refs) | set(right.evidence_refs)))[:32], review_status="disputed").to_dict()


def merge_records(records):
    unique = {}
    for row in sorted(records, key=lambda r:(r["record_id"],digest(r["targets"]))):
        key = (row["supervision"]["partition"],row["provenance"]["leakage_group"],row["input_key"])
        old = unique.get(key)
        if old is None:
            unique[key] = deepcopy(row)
            continue
        conflicts = old["provenance"].setdefault("annotation_conflicts",[])
        for name in ("roles","compatibility","pairs"):
            rows = {tuple(v[:-1]):v for v in old["targets"][name]}
            for value in row["targets"][name]:
                scope = tuple(value[:-1])
                if scope not in rows:
                    rows[scope] = deepcopy(value)
                elif name == "roles":
                    rows[scope][-1] = [_merge_cell(a,b,conflicts,[name,*scope,ROLES[i]]) for i,(a,b) in enumerate(zip(rows[scope][-1],value[-1]))]
                else:
                    rows[scope][-1] = _merge_cell(rows[scope][-1],value[-1],conflicts,[name,*scope])
            old["targets"][name] = [rows[k] for k in sorted(rows)]
        sets = {(v["task"],tuple(v["subject"])):v for v in old["targets"]["task_labels"]}
        for value in row["targets"]["task_labels"]:
            scope = (value["task"],tuple(value["subject"]))
            if scope not in sets:
                sets[scope] = deepcopy(value)
                continue
            current = sets[scope]
            for coord, cell in value["cells"].items():
                current["cells"][coord] = cell if coord not in current["cells"] else _merge_cell(
                    current["cells"][coord],cell,conflicts,[value["task"],*value["subject"],coord])
            current["annotation_complete"] = current["annotation_complete"] and value["annotation_complete"]
        old["targets"]["task_labels"] = [sets[k] for k in sorted(sets)]
        old["provenance"]["source_record_ids"] = sorted(set(old["provenance"]["source_record_ids"]) | set(row["provenance"]["source_record_ids"]))
        old["provenance"]["label_migration"].extend(row["provenance"]["label_migration"])
        if old["provenance"].get("axis_truth") != row["provenance"].get("axis_truth"):
            old["provenance"].pop("axis_truth",None)
            old["provenance"]["axis_truth_status"] = "conflict"
        if row["provenance"].get("previously_consumed"):
            old["provenance"]["previously_consumed"] = True
        sources = old["supervision"]["cell_sources"]
        for coordinate,values in row["supervision"]["cell_sources"].items():
            combined = sources.get(coordinate,[]) + values
            sources[coordinate] = sorted({digest(v):v for v in combined}.values(),key=digest)
        kinds = sorted(set(old["supervision"]["source_kinds"]) | set(row["supervision"]["source_kinds"]))
        old["supervision"]["source_kinds"] = kinds
        # A mixed record must be admitted per cell by the v3 trainer; it cannot
        # masquerade as one allowed legacy Supervision kind.
        old["supervision"]["kind"] = kinds[0] if len(kinds)==1 else "mixed"
    for row in unique.values():
        if row["targets"]["roles"]:
            row["supervision"]["legacy_semantics_version"] = "construction-role-v7"
        row["provenance"]["label_migration"].sort(key=digest)
        row["provenance"].get("annotation_conflicts",[]).sort(key=digest)
    return [unique[k] for k in sorted(unique)]


def _source_stubs(records):
    """Inspect declared source/variant metadata before generating any graphs."""
    result, identities = [], {}
    for base in records:
        if not isinstance(base,dict) or not isinstance(base.get("record_id"),str) or "observations" not in base:
            raise ValueError("source record needs record_id and observations")
        if base.get("schema_version", "axis-source-record-v3") != "axis-source-record-v3":
            raise ValueError("unsupported source record version")
        allowed = {"input","card_rows","effect_snapshots","structure_links","function_seeds","functional_contracts"}
        if not isinstance(base["observations"],dict) or not set(base["observations"]) <= allowed or "input" not in base["observations"]:
            raise ValueError("source observations contain unknown fields; targets/provenance stay outside")
        parent = deepcopy(base)
        parent.pop("variants",None)
        parent["provenance"] = dict(parent.get("provenance",{}), record_id=parent["record_id"])
        result.append((parent,None))
        for variant in base.get("variants",()):
            if not isinstance(variant,dict) or not isinstance(variant.get("record_id"),str) or not isinstance(variant.get("observations"),dict):
                raise ValueError("variant requires its own id and full changed observations")
            if not set(variant["observations"]) <= allowed or "input" not in variant["observations"]:
                raise ValueError("invalid variant observations")
            child = deepcopy(variant)
            child["provenance"] = dict(parent["provenance"], **child.get("provenance",{}))
            if "targets" in child and not any(k in variant.get("provenance",{}) for k in ("label_available_at","annotation_available_at")):
                child["provenance"].pop("label_available_at",None)
                child["provenance"].pop("annotation_available_at",None)
            child["provenance"].update(record_id=child["record_id"],parent_id=parent["record_id"],
                parent_namespace=parent["provenance"].get("source_namespace","legacy"))
            result.append((child,parent))
    for row,_ in result:
        if row.get("comparison") is not None:
            right=row["comparison"].get("right")
            if not isinstance(right,dict) or not set(right)<=allowed or "input" not in right:
                raise ValueError("comparison right observations must use the same fact whitelist")
        identity = (row["provenance"].get("source_namespace","legacy"),row["record_id"])
        facts = digest((row["observations"],row.get("comparison")))
        if identity in identities and identities[identity] != facts:
            raise ValueError("a source record id identifies different observations")
        identities[identity] = facts
    return result


def prepare_records(records, config, *, catalog=None, emit=None):
    stubs = _source_stubs(records)
    raw = [v for v,_ in stubs]
    split_options = dict(config.get("split",{}))
    split_options.setdefault("seed",config["seed"])
    split_options.setdefault("require_three",False)
    assignments, _ = assign_group_splits(raw, **split_options)
    grouping = build_leakage_groups(raw, near_duplicate_swaps=split_options.get("near_duplicate_swaps",2),
                                   max_near_pairs=split_options.get("max_near_pairs",1000000))
    if emit:
        emit('v3_source_groups',records=len(raw),groups=len(grouping['groups']))
    # Old/consumed sources can be diagnostic holdouts, never a fresh final set.
    eligible, locked = {}, defaultdict(set)
    for i,row in enumerate(raw):
        meta = row.get("provenance",{})
        group = grouping["row_groups"][i]
        eligible[group] = eligible.get(group,True) and meta.get("final_eval_eligible") is True and meta.get("previously_consumed") is False
        requested = row.get("supervision",{}).get("partition")
        if requested is not None and requested not in ("train","validation","test","final_eval","quarantine"):
            raise ValueError("unknown declared source partition")
        if requested in ("test","final_eval") or meta.get("final_eval_only") is True:
            locked[group].add("test")
        elif requested in ("validation","quarantine"):
            locked[group].add(requested)
    for i,fold in enumerate(assignments):
        group = grouping["row_groups"][i]
        locks = locked[group]
        # Restrictive source reservations propagate through the whole component.
        # A protocol holdout never falls back into training through a source lock.
        if "quarantine" in locks or ("validation" in locks and ("test" in locks or fold == "test")):
            fold = "quarantine"
        elif "test" in locks and fold != "quarantine":
            fold = "test"
        elif "validation" in locks and fold != "quarantine":
            fold = "validation"
        if fold == "test" and not eligible[grouping["row_groups"][i]]:
            fold = "retrospective_test"
        assignments[i] = fold
    prepared, parent_cache = [], {}
    for index,(row,parent) in enumerate(stubs):
        if emit and index%128==0:
            emit('v3_prepare_progress',completed=index,total=len(stubs))
        build,key,comparison=_build_record(row,{} if catalog is None else catalog,config.get("canonical_budget",4096))
        if parent is not None:
            parent_key = (parent["provenance"].get("source_namespace","legacy"),parent["record_id"])
            if parent_key not in parent_cache:
                _,parent_input_key,_=_build_record(parent,{} if catalog is None else catalog,config.get("canonical_budget",4096))
                parent_cache[parent_key] = (parent_input_key,
                                            normalize_targets(parent.get("targets",{})))
            old_key, old_targets = parent_cache[parent_key]
            inherited_parent = dict(parent,targets=old_targets)
            row = dict(row,targets=_inherit_targets(inherited_parent,row,key == old_key))
        targets, migration = migrate_targets(row,build.input)
        for label in targets["task_labels"]:
            if label["task"]=="copy_preference" and (comparison is None or tuple(label["subject"])!=(comparison["left_key"],comparison["right_key"])):
                raise ValueError("copy preference labels require matching paired configuration observations")
        nodes = {node.ref for node in build.graph.nodes}
        if any(key not in nodes for key,_ in targets["roles"]) or any(key not in nodes for key,_ in targets["compatibility"]) or any(a not in nodes or b not in nodes for a,b,_ in targets["pairs"]):
            raise ValueError("legacy target coordinates must refer to graph observations")
        fold = assignments[index]
        source_identity = json.dumps([row.get("provenance",{}).get("source_namespace","legacy"),row["record_id"]],separators=(",",":"))
        provenance = dict(row.get("provenance",{}), leakage_group=grouping["row_groups"][index],
            source_record_ids=[source_identity], label_migration=migration,
            graph_diagnostics=list(build.unresolved), natural_candidate_overflow=build.candidates.overflow)
        supervision = deepcopy(row.get("supervision",{}))
        if supervision.get("kind") not in SOURCE_KINDS:
            raise ValueError("an explicit supported supervision kind is required")
        contextual = bool(targets["roles"]) or any(v["task"] in ("axis_position","axis_origin","contribution","function_role") for v in targets["task_labels"])
        if contextual and supervision["kind"] not in ROLE_SOURCES:
            raise ValueError("engine/candidate outcomes cannot supply contextual role truth")
        supervision.update(partition=fold,trainable=fold == "train", label_protocol=config["label_protocol"],
                           label_protocol_sha256=digest(config["label_protocol"]),
                           legacy_semantics_version="construction-role-v7" if targets["roles"] else None)
        supervision["source_kinds"] = [supervision["kind"]]
        supervision["cell_sources"] = {json.dumps([task,list(coordinate)],ensure_ascii=False,separators=(",",":")):
            [dict(kind=supervision["kind"],source_record_id=source_identity,confidence=cell.confidence)]
            for task,coordinate,cell in iter_target_cells(targets) if cell.known}
        prepared.append(dict(schema_version=RECORD_VERSION,record_id="record:"+digest(source_identity)[:32],input_key=key,
            observations=build.to_dict()["observations"],targets=targets,supervision=supervision,provenance=provenance))
        if comparison is not None:
            prepared[-1]["comparison"]=comparison
    prepared = merge_records(prepared)
    if emit:
        emit('v3_prepare_progress',completed=len(stubs),total=len(stubs),merged_rows=len(prepared))
    effective = Counter()
    for row in prepared:
        if row["supervision"]["partition"] != "train":
            continue
        for task,_,cell in iter_target_cells(row["targets"]):
            if cell.known:
                effective[row["provenance"]["leakage_group"],task] += 1
    for row in prepared:
        group = row["provenance"]["leakage_group"]
        row["supervision"]["source_group_weights"] = {task:1/count for (g,task),count in sorted(effective.items()) if g == group}
    counts = Counter(row["supervision"]["partition"] for row in prepared)
    groups = defaultdict(set)
    status_counts, train_labels = Counter(), Counter()
    for row in prepared:
        fold = row["supervision"]["partition"]
        groups[fold].add(row["provenance"]["leakage_group"])
        for task,_,cell in iter_target_cells(row["targets"]):
            status_counts[fold,task,cell.status] += 1
            if fold == "train" and cell.known:
                train_labels[task,str(cell.value)] += 1
    report = dict(version=VERSION, split_version=SPLIT_VERSION,
        split_counts={s:counts[s] for s in ("train","validation","test","retrospective_test","quarantine")},
        source_counts={s:len(groups[s]) for s in ("train","validation","test","retrospective_test","quarantine")},
        label_status_counts=[dict(partition=f,task=t,status=s,count=n) for (f,t,s),n in sorted(status_counts.items())],
        train_label_counts=[dict(task=t,value=v,count=n) for (t,v),n in sorted(train_labels.items())],
        stats=dict(source_rows=len(raw),prepared_rows=len(prepared),merged_rows=len(raw)-len(prepared),
                   migration_cells=sum(len(r["provenance"]["label_migration"]) for r in prepared),
                   known_labels_withdrawn=sum(v["before"]["status"]=="known" and v["after"]["status"]!="known" for r in prepared for v in r["provenance"]["label_migration"])),
        grouping=grouping, new_independent_final=bool(counts["test"]), human_gold=False,
        training_started=False, model_loaded=False, capability_accepted=False)
    return prepared, report


def iter_target_cells(targets):
    for key,cells in targets.get("roles",()):
        for role,cell in zip(ROLES,cells):
            yield "legacy:"+role, (key,), LabelCell.from_dict(cell)
    for name in ("compatibility","pairs"):
        for row in targets.get(name,()):
            yield "legacy:"+name,tuple(row[:-1]),LabelCell.from_dict(row[-1])
    for raw in targets.get("task_labels",()):
        label_set = LabelSet.from_dict(raw)
        for coordinate,cell in label_set.cells:
            yield label_set.task, label_set.subject+(coordinate,),cell


def _path(value):
    path = Path(value)
    return path if path.is_absolute() else ROOT/path


def load_sources(config):
    records = []
    if config.get("records_file"):
        value = read_json(_path(config["records_file"]))
        records.extend(value if isinstance(value,list) else value["records"])
    legacy = config.get("legacy_import")
    if legacy:
        records.extend(load_legacy_sources(config,legacy))
    if not records:
        raise ValueError("no source records; provide records_file or explicit legacy_import")
    if config.get("catalog") and config.get("split",{}).get("protocol") == "cross_period":
        if not config.get("catalog_available_at"):
            raise ValueError("cross_period requires catalog_available_at for the selected catalog snapshot")
        for row in records:
            row.setdefault("provenance",{})["catalog_available_at"] = config["catalog_available_at"]
    selected = set().union(*(referenced_cards(row) for row,_ in _source_stubs(records)))
    catalog = {}
    if config.get("catalog"):
        connection = sqlite3.connect(_path(config["catalog"]).resolve().as_uri()+"?mode=ro",uri=True)
        connection.row_factory = sqlite3.Row
        try:
            codes = sorted(selected)
            for start in range(0,len(codes),800):
                batch = codes[start:start+800]
                query = "select d.*,t.name,t.desc from datas d join texts t on d.id=t.id where d.id in ("+",".join("?" for _ in batch)+") order by d.id"
                for row in connection.execute(query,batch):
                    catalog[row["id"]] = dict(row)
        finally:
            connection.close()
    from legacy_import import resolve_plan
    for row in records:
        meta = row.get("provenance",{})
        if not meta.get("legacy_plan"):
            continue
        example = RoleInput.from_dict(row["observations"]["input"])
        before = Counter(dict(meta["legacy_base_main"])) + Counter(dict(meta["legacy_base_extra"]))
        after = Counter(dict(example.deck.main or ())) + Counter(dict(example.deck.extra or ()))
        if not (set(before) | set(after)) <= set(catalog):
            meta["actor_presence_unknown"] = True
        else:
            a = resolve_plan(meta["legacy_plan"],catalog,before)
            plan = deepcopy(meta["legacy_plan"])
            if not plan.get("entities"):
                plan["entities"] = [dict(surface=v["surface"],name_contains=v["selector"],kind=v["kind"],evidence_quote=v["evidence_quote"]) for v in a["entities"]]
            b = resolve_plan(plan,catalog,after)
            meta["plan_actor_absent"] = any(x["codes"] and not y["codes"] for x,y in zip(a["entities"],b["entities"]))
    return records, catalog


def load_legacy_sources(config, legacy):
    """Read consumed references/shards; old mechanism/role answers stay targets."""
    from legacy_import import audited_targets
    from legacy_import import confidence
    cases = read_json(_path(legacy["cases"]))
    def indexed(path):
        value = read_json(_path(path))
        values = value if isinstance(value,list) else value.get("records",value.get("cases",[]))
        return {r["case_id"]:r for r in values}
    labels = indexed(legacy["labels"])
    plans = indexed(legacy["plans"]) if legacy.get("plans") else {}
    audits = indexed(legacy["audit"]) if legacy.get("audit") else {}
    if legacy.get("low_support"):
        for case_id,value in indexed(legacy["low_support"]).items():
            if case_id in audits:
                audits[case_id]["low_support_scope_resolution"] = value
    generic = indexed(legacy["generic"]) if legacy.get("generic") else {}
    by_id = {c["case_id"]:c for c in cases}
    queries = [(c,None) for c in cases]
    parent = legacy.get("parent_dir")
    if parent:
        parent = _path(parent)
        manifest = read_json(parent/"dataset.json")
        for fold in legacy.get("parent_folds",("train","validation")):
            if fold not in ("train","validation"):
                raise ValueError("legacy importer never opens independent/final holdouts")
            for shard in sorted(manifest["shards"].get(fold,()),key=lambda v:v["file"]):
                path = (parent/shard["file"]).resolve()
                if not path.is_relative_to(parent.resolve()):
                    raise ValueError("legacy shard escapes source directory")
                with gzip.open(path,"rt",encoding="utf-8") as stream:
                    for line in stream:
                        row = json.loads(line)
                        if row.get("reference") in by_id:
                            queries.append((by_id[row["reference"]],row))
    rowids = sorted({int(old["source_rowid"]) for _,old in queries if old is not None})
    decks = {}
    if rowids:
        con = sqlite3.connect(_path(config["deck_cache"]).resolve().as_uri()+"?mode=ro",uri=True)
        try:
            for start in range(0,len(rowids),800):
                batch = rowids[start:start+800]
                for rowid,identity in con.execute("select rowid,identity from decks where rowid in ("+",".join("?" for _ in batch)+") order by rowid",batch):
                    decks[rowid] = json.loads(identity)
        finally:
            con.close()
    result = []
    for case,old in queries:
        case_id = case["case_id"]
        if old is None:
            main,extra = case["main"],case["extra"]
            rowid,variant = case.get("deck_cache_rowid"),case.get("variant","complete")
        else:
            rowid,variant = old["source_rowid"],old.get("variant","complete")
            if rowid not in decks:
                raise ValueError("legacy source deck missing: "+str(rowid))
            main,extra = decks[rowid]
        main_counts,extra_counts = dict(main),dict(extra)
        selected = Counter(dict(case.get("selected_main",()))) + Counter(dict(case.get("selected_extra",())))
        if variant.startswith("missing:"):
            code = int(variant.split(":",1)[1])
            if selected[code]:
                selected[code] -= 1
        members = tuple(sorted((int(c),n) for c,n in selected.items() if n))
        unit = case.get("unit") or {}
        tags = unit.get("function_tags",())
        query = "function:"+tags[0] if len(tags)==1 else "function:unresolved_legacy_request"
        focus = UnitSpec("focal",members,query) if members else None
        # Legacy side data absent from the source is unknown, not an empty Side.
        deck = DeckSpec(tuple((int(c),n) for c,n in main_counts.items()),tuple((int(c),n) for c,n in extra_counts.items()),
                        None if "side" not in case else tuple(tuple(p) for p in case["side"]))
        example = RoleInput("legacy-observation", Factors("context"),(),
            analysis_mode="deck_analysis",analysis_context=AnalysisContext(period=case.get("period","unknown")),deck=deck,unit_definition=focus)
        original = labels.get(case_id,{"roles":[None]*5,"confidence":[0]*5})
        if case_id in plans and case_id in audits and case_id in generic:
            reviewed,trust = audited_targets(dict(case,primary_plan=plans[case_id]),original,audits[case_id],generic)
        else:
            reviewed,trust = original["roles"],original.get("confidence",[0]*5)
        values = reviewed if old is None else old["labels"]
        weights = trust if old is None else old.get("role_confidence",trust)
        cells = []
        for i,value in enumerate(values):
            weight = confidence(weights[i])
            known = value is not None and reviewed[i] is not None and weight >= config.get("minimum_reference_confidence",.55)
            cells.append(LabelCell(int(value>=.5),"known",weight,"legacy_weak_context_annotation",
                ("legacy-reference:"+case_id,),"reviewed").to_dict() if known else LabelCell().to_dict())
        targets = _empty_targets()
        if focus is not None:
            targets["roles"] = [["query:unit",cells]]
        meta = dict(source_namespace=legacy.get("source_namespace","consumed_axis_references"),case_id=case_id,reference=case_id,
            source_rowid=rowid,case_family=case.get("family"),receiver_family=case.get("receiver_family"),
            previously_consumed=True,final_eval_eligible=False,readiness_only=variant in ("counter_condition_unsatisfied","counter_condition_unknown"),
            source_variant=variant, legacy_base_main=case["main"], legacy_base_extra=case["extra"], legacy_plan=plans.get(case_id),
            legacy_plan_not_in_model_input=True,
            reference_use="previously observed; training/development/retrospective only")
        base_deck = DeckSpec(tuple((int(c),n) for c,n in case["main"]),tuple((int(c),n) for c,n in case["extra"]),
                             None if "side" not in case else tuple(tuple(p) for p in case["side"]))
        meta["legacy_unreviewed_variant"] = old is not None and (deck != base_deck or variant.startswith("missing:")) and old.get("input_scope_reviewed") is not True
        scopes = {v["key"]:v["scope"] for v in generic.get(case_id,{}).get("condition_scopes",())}
        if any(v.get("status") in ("unsatisfied","unknown") and scopes.get(v["key"]) != "construction_compatibility"
               for v in unit.get("conditions",())):
            meta["readiness_only"] = True
        rid = "legacy-case:"+case_id if old is None else "legacy-variant:"+digest((case_id,rowid,variant,deck.to_dict()))[:24]
        result.append(dict(schema_version="axis-source-record-v3",record_id=rid,observations={"input":example.to_dict()},
                           targets=targets,supervision=dict(kind="weak_context_annotation"),provenance=meta))
    return result


def preparation_implementation():
    source_paths = [Path(__file__), ROOT/"legacy_import.py"]
    package = ROOT.parent.parent/"src"/"ygo_kito"/"multifactor"
    source_paths += [package/name for name in ("contracts.py","analysis.py","semantics.py","axis_candidates.py","conditions.py","functional_units.py","splits.py")]
    source_paths += [package.parent/name for name in ("effect_mechanisms.py", "effect_count_limits.py",
        "effect_records.py", "effect_blocks.py", "effect_block_rules.py", "construction_inventory.py")]
    return {p.name:digest(p.read_text("utf-8-sig").replace("\r\n","\n")) for p in source_paths}


def verify_preparation_implementation(manifest):
    if manifest.get("preparation_identity",{}).get("implementation")!=preparation_implementation():
        raise CacheMismatch("prepared implementation differs; preserve the data and prepare a new versioned directory")


def preparation_identity(config, records, catalog):
    if config.get("feature_schema") != GRAPH_VERSION or config.get("split_version") != SPLIT_VERSION:
        raise ValueError("explicit current feature_schema and split_version required")
    for key in ("dataset_version","label_protocol","source_versions","seed"):
        if key not in config:
            raise ValueError("preparation config missing "+key)
    implementation=preparation_implementation()
    semantic = {k:deepcopy(config.get(k)) for k in ("feature_schema","split_version","dataset_version","label_protocol",
        "source_versions","seed","split","canonical_budget","prepare","minimum_reference_confidence")}
    identity = dict(version="axis-preparation-identity-v3", semantic_config=semantic, implementation=implementation,
        sources=digest(sorted(records,key=digest)), catalog=digest({str(c):catalog[c] for c in sorted(catalog)}))
    return dict(identity, semantic_id=digest(identity))


def validate_cache(run, expected):
    run = Path(run).resolve()
    manifest = read_json(run/"dataset.json")
    if manifest.get("version") != VERSION or manifest.get("preparation_identity") != expected:
        raise CacheMismatch("dataset cache semantics differ or identity is absent; use a new run directory")
    files = manifest.get("files")
    shards = manifest.get("shards")
    if not isinstance(files,list) or not isinstance(shards,dict) or len({v["file"] for v in files}) != len(files) or sorted(files,key=digest) != sorted([v for entries in shards.values() for v in entries],key=digest):
        raise CacheMismatch("cached shard inventory is incomplete or duplicated")
    for fold,entries in shards.items():
        if sum(v["records"] for v in entries) != manifest.get("split_counts",{}).get(fold):
            raise CacheMismatch("cached partition counts disagree")
    for shard in files:
        path = (run/shard["file"]).resolve()
        if not path.is_relative_to(run):
            raise CacheMismatch("cached shard escapes run directory")
        try:
            with gzip.open(path,"rt",encoding="utf-8") as stream:
                rows = [json.loads(line) for line in stream]
        except (OSError,ValueError) as error:
            raise CacheMismatch("cached shard missing or invalid: "+shard["file"]) from error
        if len(rows) != shard["records"] or digest(rows) != shard["semantic_records"]:
            raise CacheMismatch("cached parsed records differ: "+shard["file"])
    return manifest


def prepare(config, run, emit):
    """Called only by an explicitly authorized preparation run, never on import."""
    run = Path(run).resolve()
    emit('v3_sources_loading')
    records, catalog = load_sources(config)
    emit('v3_sources_loaded',records=len(records),catalog_cards=len(catalog))
    identity = preparation_identity(config,records,catalog)
    if (run/"dataset.json").exists():
        report = validate_cache(run,identity)
        emit("v3_semantic_cache_reused",semantic_id=identity["semantic_id"])
        return report
    if run.exists() and any(run.iterdir()):
        raise CacheMismatch("output contains unbound/partial artifacts; preserve it and use a new directory")
    prepared, report = prepare_records(records,config,catalog=catalog,emit=emit)
    shard_size = config.get("prepare",{}).get("shard_size",256)
    if type(shard_size) is not int or not 1 <= shard_size <= 4096:
        raise ValueError("prepare.shard_size must be 1..4096")
    run.mkdir(parents=True,exist_ok=True)
    lock = run/".prepare.lock"
    with lock.open("x",encoding="utf-8") as stream:
        stream.write(identity["semantic_id"]+"\n")
    stage = run/(".prepare-"+uuid.uuid4().hex)
    stage.mkdir()
    report.update(preparation_identity=identity,files=[],shards={})
    for fold in sorted(report["split_counts"]):
        values = sorted((r for r in prepared if r["supervision"]["partition"]==fold),key=lambda r:(r["input_key"],r["record_id"]))
        report["shards"][fold] = []
        for start in range(0,len(values),shard_size):
            part = values[start:start+shard_size]
            name = f"{fold}-{start//shard_size:05d}.jsonl.gz"
            with gzip.open(stage/name,"wt",encoding="utf-8",newline="\n") as stream:
                for row in part:
                    stream.write(json.dumps(row,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n")
            entry = dict(file=name,records=len(part),queries=len(part),semantic_records=digest(part))
            report["files"].append(entry)
            report["shards"][fold].append(entry)
    write_json(stage/"dataset.json",report)
    # Manifest is committed last. Existing files are never replaced. A failed
    # preparation leaves its own stage/lock for inspection, not a valid cache.
    for path in sorted(stage.iterdir(),key=lambda p:(p.name=="dataset.json",p.name)):
        target = run/path.name
        if target.exists():
            raise CacheMismatch("another writer created an output; no overwrite: "+target.name)
        path.rename(target)
    stage.rmdir()
    lock.unlink()
    emit("v3_data_prepared",split_counts=report["split_counts"],semantic_id=identity["semantic_id"],training_started=False)
    return report
