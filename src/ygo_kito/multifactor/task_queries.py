"""Finite output vocabulary and fact-defined query domains; no Torch or labels."""
from .contracts import (GRAPH_ATTRIBUTES, GRAPH_FUNCTIONS, GRAPH_KINDS, GRAPH_RELATIONS, GRAPH_VERSION,
                        CONTEXT_FACTORS, ROLES, TASK_DOMAINS, AnalysisGraph, FactorContractError, RoleInput, digest)

QUERY_VERSION = "axis-queries-v3-paired-configurations"
BINARY_COORDINATES = {
    "mechanism": GRAPH_FUNCTIONS + ("once_per_turn", "summon_lock", "cost", "target", "recycle"),
    "axis_membership": ("member",), "axis_function": GRAPH_FUNCTIONS,
    "function_role": ("starter", "extender", "terminal", "recovery", "interaction", "resource", "bridge"),
    "contribution": ("carrier", "enhancer"),
    "pair_relation": ("dependency", "substitute", "support", "conflict"),
}
CATEGORY_COORDINATES = {"axis_position":"position", "axis_origin":"origin", "transferability":"portability",
                        "receiver_compatibility":"compatibility", "copy_preference":"preference"}
LEGACY_TASKS = tuple("legacy:"+r for r in ROLES) + ("legacy:compatibility", "legacy:pairs")
LEARNED_TASKS = LEGACY_TASKS + tuple(BINARY_COORDINATES) + tuple(CATEGORY_COORDINATES)
CONTEXTUAL_TASKS = ("legacy:strategic_core", "legacy:support_role", "legacy:generic_utility",
                    "axis_position", "axis_origin", "function_role", "contribution")
SOURCE_KINDS = ("engineering_fixture", "definition_development", "engine_probe", "self_generated_candidate", "human_feedback", "weak_context_annotation")
ROLE_SOURCES = ("engineering_fixture", "definition_development", "human_feedback", "weak_context_annotation")
INTENT_FACTORS=tuple(name for name in CONTEXT_FACTORS if not name.startswith("plan_"))


def query_key(task, subject, coordinate):
    import json
    return json.dumps([task,list(subject)],ensure_ascii=False,separators=(",",":")) if coordinate is None or task in LEGACY_TASKS else json.dumps(
        [task,[*subject,coordinate]],ensure_ascii=False,separators=(",",":"))


def encoder_fingerprint():
    return digest(dict(graph=GRAPH_VERSION,attributes=GRAPH_ATTRIBUTES,functions=GRAPH_FUNCTIONS,kinds=GRAPH_KINDS,
        relations=GRAPH_RELATIONS,transform="signed-log1p-v1",context_width=15,state_scopes="explicit-v1",
        intent_factors=INTENT_FACTORS,intent_channels="value*confidence/known/confidence/uncertainty",
        intent_scope="conditional readout only; intrinsic heads exclude intent"))


def feature_fingerprint():
    return digest(dict(encoder=encoder_fingerprint(),query_version=QUERY_VERSION,binary=BINARY_COORDINATES,categorical=CATEGORY_COORDINATES,
        domains=TASK_DOMAINS,legacy=LEGACY_TASKS,context="physical context plus explicit intent; no opaque text or identity embeddings"))


def observation_view(value):
    """Only observations cross the encoder boundary; all other blocks ignored."""
    from .semantics import GraphBuild
    if isinstance(value,GraphBuild):
        if value.input.analysis_mode is None:
            raise FactorContractError('legacy observations cannot use the v3 graph encoder')
        return value.input,value.graph,value.candidates.to_dict()
    if not isinstance(value,dict):
        raise FactorContractError("GraphBuild or v3 graph record required")
    obs = value.get("observations",value)
    if set(obs) != {"input","graph","candidates"}:
        raise FactorContractError("exact v3 input/graph/candidates observation block required")
    example = RoleInput.from_dict(obs['input'])
    if example.analysis_mode is None:
        raise FactorContractError('legacy observations cannot use the v3 graph encoder')
    return example,AnalysisGraph.from_dict(obs['graph']),obs['candidates']


def validate_comparison(left,right,*,left_key,right_key,operation):
    """The same frozen question and an actual declared replacement of inventory."""
    from collections import Counter
    from dataclasses import replace
    from .contracts import CopyChange, DECK_SECTIONS
    a,ga,ca=observation_view(left)
    b,gb,cb=observation_view(right)
    def fixed_context(example):
        resources=example.analysis_context.public_resources
        if resources is None:
            return example.analysis_context
        fixed=[]
        for resource in resources:
            if resource.source!="actual_candidate_inventory":
                fixed.append(resource)
                continue
            zone=resource.deck_section
            code=int(resource.selector[5:]) if resource.selector.startswith("card:") and resource.selector[5:].isdigit() else None
            stock=None if example.deck is None or zone not in DECK_SECTIONS else getattr(example.deck,zone)
            if (stock is None or dict(stock).get(code,0)!=resource.quantity or resource.capacity!=resource.quantity or
                    resource.resource_type!="card" or resource.resource_id!=f"inventory:{zone}:{code}" or resource.pool_id!=resource.resource_id):
                raise FactorContractError("comparison inventory resources must match actual section quantities")
        return replace(example.analysis_context,public_resources=tuple(fixed))
    if (a.context_ref!=b.context_ref or a.context!=b.context or fixed_context(a)!=fixed_context(b) or a.visible_state!=b.visible_state or
            a.unit_definition is None or b.unit_definition is None or a.unit_definition.function_id!=b.unit_definition.function_id or
            a.deck is None or b.deck is None or a.insertion is not None or b.insertion is not None or
            not isinstance(operation,dict) or set(operation)-{"add","remove","kind"} or not operation.get("add") or not operation.get("remove")):
        raise FactorContractError("copy comparison requires the same goal/function/rules and actual add/remove")
    add,remove=(v if isinstance(v,CopyChange) else CopyChange.from_dict(v) for v in (operation["add"],operation["remove"]))
    if operation.get("kind","replacement" if add.quantity==remove.quantity else "mixed_change")!=("replacement" if add.quantity==remove.quantity else "mixed_change"):
        raise FactorContractError("comparison operation kind contradicts its actual quantities")
    changed={s:None if getattr(a.deck,s) is None else Counter(dict(getattr(a.deck,s))) for s in DECK_SECTIONS}
    for change,sign in ((remove,-1),(add,1)):
        stock=changed[change.section]
        if stock is None or sign==-1 and stock[change.card_id]<change.quantity:
            raise FactorContractError("comparison operation edits unknown/unavailable inventory")
        stock[change.card_id]+=sign*change.quantity
    expected={s:None if stock is None else tuple(sorted((c,n) for c,n in stock.items() if n)) for s,stock in changed.items()}
    if any(getattr(b.deck,s)!=expected[s] for s in DECK_SECTIONS) or a.deck==b.deck:
        raise FactorContractError("comparison operation does not produce its declared right configuration")
    for example,graph,candidates,key in ((a,ga,ca,left_key),(b,gb,cb,right_key)):
        if key not in query_domain(example,graph,candidates)["units"]:
            raise FactorContractError("comparison query is not an observed complete unit")
    return a,b


def comparison_for_record(row):
    from .contracts import fields
    comparison=row.get("comparison")
    fields(comparison,("right","left_key","right_key","operation"))
    validate_comparison(row,comparison["right"],left_key=comparison["left_key"],right_key=comparison["right_key"],operation=comparison["operation"])
    return comparison


def record_graph_size(row):
    _,graph,_=observation_view(row)
    n,e,count=len(graph.nodes),len(graph.edges),1
    if isinstance(row,dict) and row.get("comparison") is not None:
        right=comparison_for_record(row)["right"]
        _,g,_=observation_view(right)
        n+=len(g.nodes);e+=len(g.edges);count+=1
    return n,e,count


def record_sources(row,*,label_protocol_sha256=None):
    """Validate actual cell provenance, including evaluation and calibration."""
    from .training import Targets
    from .contracts import unit
    if not isinstance(row,dict) or row.get("schema_version")!="axis-training-record-v3":
        raise FactorContractError("prepared v3 record required")
    supervision=row["supervision"]
    protocol=supervision.get("label_protocol")
    if (not isinstance(protocol,str) or not protocol or supervision.get("label_protocol_sha256")!=digest(protocol) or
            label_protocol_sha256 is not None and supervision["label_protocol_sha256"]!=label_protocol_sha256):
        raise FactorContractError("record label protocol/binding differs")
    group=row.get("provenance",{}).get("leakage_group")
    if not isinstance(group,str) or not group:
        raise FactorContractError("record source group missing")
    declared=supervision.get("source_kinds")
    if not isinstance(declared,list) or not declared or len(set(declared))!=len(declared) or set(declared)-set(SOURCE_KINDS):
        raise FactorContractError("record supervision kinds missing/unsupported")
    unit(supervision.get("confidence",1.),"record confidence")
    actual=set()
    for task,subject,coordinate,cell in Targets.from_dict(row["targets"]).graph_cells():
        if not cell.known or task=="state_readiness":
            continue
        sources=supervision.get("cell_sources",{}).get(query_key(task,subject,coordinate))
        if not isinstance(sources,list) or not sources:
            raise FactorContractError("known label has no original cell provenance")
        for source in sources:
            kind=source.get("kind")
            if (kind not in SOURCE_KINDS or task in CONTEXTUAL_TASKS and kind not in ROLE_SOURCES or
                    not isinstance(source.get("source_record_id"),str) or not source["source_record_id"]):
                raise FactorContractError("cell source cannot supply this task's truth")
            unit(source.get("confidence"),"cell source confidence")
            actual.add(kind)
    if actual-set(declared):
        raise FactorContractError("record source header hides its actual cell sources")
    return set(declared)|actual


def query_domain(example,graph,candidates):
    nodes = {n.ref:n for n in graph.nodes}
    if candidates.get("producer") != "natural_input_facts":
        raise FactorContractError("observation candidates must be natural; training queries stay in supervision")
    axes = tuple(v["candidate_id"] for v in candidates["candidates"])
    units = tuple(v["candidate_id"] for v in candidates["units"])
    if any(ref not in nodes for ref in axes+units):
        raise FactorContractError("candidate endpoint absent from graph")
    cards = tuple(n.ref for n in graph.nodes if n.kind=="card")
    focal = ("query:unit",) if "query:unit" in nodes else ()
    unit_refs = tuple(dict.fromkeys(focal+units+axes+cards))
    return dict(nodes=nodes,axes=axes,units=unit_refs,members=tuple(dict.fromkeys(cards+units)),
                mechanism=tuple(n.ref for n in graph.nodes if n.kind in ("card","effect","function")),virtual={})


def training_domain(domain,candidates,queries):
    """Training-only support sets borrow an existing fact query's whole scope.

    Each spec has source_candidate_ref and members. Functions/conditions/modes
    come exclusively from that observed candidate; no gold metadata is trusted.
    The encoder graph and natural candidate list are never changed.
    """
    from .axis_candidates import AxisCandidate
    from .contracts import GraphNode,Factors,fields
    from .functional_units import BranchConditions
    if not isinstance(queries,(list,tuple)) or len(queries)>4096:
        raise FactorContractError('training-query budget exceeded; no partial domain')
    result = dict(domain,nodes=dict(domain['nodes']),virtual=dict(domain['virtual']))
    observed = {v['candidate_id']:v for v in candidates['candidates']+candidates['units']}
    for spec in queries:
        fields(spec,('source_candidate_ref','members'))
        source = observed.get(spec['source_candidate_ref'])
        if source is None or not isinstance(spec['members'],list):
            raise FactorContractError('training query requires an observed function/condition scope')
        value = AxisCandidate(source['function_ref'],tuple(tuple(p) for p in spec['members']),tuple(source['functions']),
            tuple(BranchConditions.from_dict(v) for v in source['conditions']),tuple(tuple(v) for v in source['mode_choices']),
            source['confidence'],tuple(source['evidence_refs']))
        if any(ref not in domain['nodes'] or domain['nodes'][ref].kind!='card' for ref,_ in value.members):
            raise FactorContractError('training support references an unobserved physical member')
        ref = value.candidate_id
        if ref in result['virtual'] and result['virtual'][ref]['source']!=source['candidate_id']:
            raise FactorContractError('duplicate injected query has ambiguous observed scope')
        if ref in result['nodes']:
            continue
        result['virtual'][ref] = dict(members=value.members,source=source['candidate_id'])
        result['nodes'][ref] = GraphNode(ref,'axis' if len(value.members)>1 else 'function',Factors('group'),functions=value.functions)
        result['units'] += (ref,)
        if len(value.members)>1:
            result['axes'] += (ref,)
        else:
            result['members'] += (ref,)
    return result


def missing_axis_query(domain,task,subject,coordinate):
    """A gold axis absent from the fact domain is a miss, never a new feature."""
    if task not in ('axis_membership','axis_function','axis_position','axis_origin'):
        return False
    if task in BINARY_COORDINATES and coordinate not in BINARY_COORDINATES[task] or task in CATEGORY_COORDINATES and coordinate!=CATEGORY_COORDINATES[task]:
        return False
    return len(subject)==(2 if task=='axis_membership' else 1) and subject[0] not in domain['nodes']


def validate_query(domain,task,subject,coordinate):
    """Membership in a fact-defined Cartesian domain; targets never extend it."""
    subject = tuple(subject)
    if task=="copy_preference":
        raise FactorContractError("copy preference requires two complete configurations and a declared operation")
    if task in BINARY_COORDINATES:
        if coordinate not in BINARY_COORDINATES[task]:
            raise FactorContractError("unknown binary query coordinate")
    elif task in CATEGORY_COORDINATES:
        if coordinate != CATEGORY_COORDINATES[task]:
            raise FactorContractError("unknown categorical query coordinate")
    elif task in LEGACY_TASKS:
        if coordinate != "value":
            raise FactorContractError("legacy query coordinate must be value")
    else:
        raise FactorContractError("task is not a learned v3 head")
    if task == "axis_membership":
        valid = len(subject)==2 and subject[0] in domain["axes"] and subject[1] in domain["members"]
    elif task in ("axis_function","axis_position","axis_origin"):
        valid = len(subject)==1 and subject[0] in domain["axes"]
    elif task == "mechanism":
        valid = len(subject)==1 and subject[0] in domain["mechanism"]
    elif task in ("function_role","contribution","transferability"):
        valid = len(subject) in (2,3) and subject[0] in domain["units"] and subject[-1] in tuple("function:"+f for f in GRAPH_FUNCTIONS)
        if task=="transferability" and len(subject)==1:
            valid = subject[0] in domain["units"] and len(domain["nodes"][subject[0]].functions)==1
        if len(subject)==3:
            valid = valid and subject[1] in domain["mechanism"]
    elif task in ("pair_relation","legacy:pairs"):
        valid = len(subject)==2 and subject[0] in domain["units"] and subject[1] in domain["units"] and subject[0]!=subject[1]
    else:
        valid = len(subject)==1 and subject[0] in domain["units"]
    if not valid:
        raise FactorContractError("query outside the observation-defined domain")
    return subject


def iter_queries(domain, task):
    """Complete lazy query space. Callers may stream every query in blocks."""
    if task=="copy_preference":
        raise FactorContractError("copy preference has no single-graph query space")
    if task in BINARY_COORDINATES:
        coordinates = BINARY_COORDINATES[task]
    elif task in CATEGORY_COORDINATES:
        coordinates = (CATEGORY_COORDINATES[task],)
    elif task in LEGACY_TASKS:
        coordinates = ("value",)
    else:
        raise FactorContractError("unknown learned query task")
    if task=="axis_membership":
        subjects = ((a,c) for a in domain["axes"] for c in domain["members"])
    elif task in ("axis_function","axis_position","axis_origin"):
        subjects = ((a,) for a in domain["axes"])
    elif task=="mechanism":
        subjects = ((a,) for a in domain["mechanism"])
    elif task in ("function_role","contribution","transferability"):
        from itertools import chain
        subjects = chain(((u,"function:"+f) for u in domain["units"] for f in GRAPH_FUNCTIONS),
            ((u,m,"function:"+f) for u in domain["units"] for m in domain["mechanism"] for f in GRAPH_FUNCTIONS),
            ((u,) for u in domain["units"] if task=="transferability" and len(domain["nodes"][u].functions)==1))
    elif task in ("pair_relation","legacy:pairs"):
        subjects = ((a,b) for a in domain["units"] for b in domain["units"] if a!=b)
    else:
        subjects = ((u,) for u in domain["units"])
    for subject in subjects:
        for coordinate in coordinates:
            yield task,subject,coordinate
