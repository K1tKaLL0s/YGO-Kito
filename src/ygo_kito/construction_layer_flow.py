"""Source-bound layer projection and partial ordering inside concrete filling.

No new model features, generation, action search or scalar quality score. The
    host can supply a fixed LayerContext; ordinary catalog filling evaluates
printed configuration capabilities without requiring a current duel state.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
from itertools import islice

from .build_contracts import digest
from .construction_layers import (
    AxisModule, FunctionEvidence, FunctionRequirement, LayerContext,
    RoleAssessment, SkeletonSpec, evaluate_layers,
)
from .construction_relations import (
    Claim, InputGroup, Need, RelationBudget, RelationContext, RelationFact, Resource,
    ResourcePool, ResourceTransfer, UseRequirement, relation_index,
    _needs, _record_facts, _record_outputs, _record_applicability, _leave_field_rule,
    _restriction_contract, _PLAYER_RESTRICTIONS, _INTRINSIC_RESTRICTIONS,
)
from .validation import ContractError
from .effect_records import operation_record


NORMALIZATION_VERSION = "construction-function-normalization-v51"
REFERENCE_BINDING_VERSION = "construction-reference-binding-v1"


def _mapped_restriction(record, restriction):
    if (restriction['kind']=='equip_condition' and record.get('equipment_condition')
            and record['equipment_condition']['source'].rstrip('。.')==restriction['source']):
        return True
    if (restriction['kind'] == 'own_effect_activation_timing'
            and restriction.get('scope') == 'this_effect'
            and restriction.get('condition') == 'this_card_sent_to_grave'
            and restriction.get('duration') == 'sent_to_grave_turn'
            and restriction['source'] == '这个效果在这张卡送去墓地的回合不能发动'
            and restriction in record.get('restrictions', ())):
        return True
    if (restriction['kind'] == 'cannot_change_position'
            and restriction.get('scope') == 'this_effect_affected_monster'
            and restriction.get('condition') == 'affected_by_this_effect'
            and restriction.get('controller') == 'opponent'
            and any(op.get('block_id') == restriction.get('subject_ref')
                    and op.get('subject') == 'opponent_battling_monster' for op in record['operations'])):
        return True
    if (restriction['kind'] == 'effect_exemption'
            and restriction.get('scope') == 'this_effect_summoned_card'
            and restriction.get('condition') == 'summoned_by_this_effect'
            and any(op['kind'] == 'unaffected' and op.get('protected_from') == 'monster_effects'
                    and op.get('subject_ref') == restriction.get('subject_ref') for op in record['operations'])):
        return True
    if (restriction.get('scope')=='this_effect_summoned_card'
            and restriction.get('subject_ref') in {op.get('block_id') for op in record['operations']}
            and restriction.get('condition')=='summoned_by_this_effect'
            and restriction['kind']=='cannot_attack'):
        return True
    contract = _restriction_contract(restriction)
    # Entity prohibitions are mapped only at card scope, where the inventory
    # adapter checks the actual summoned entity or fusion-material candidate.
    return bool(contract and (contract.get("scope", "player") == "player"
        or restriction in record.get("card_restrictions", ()))) or (
        restriction["kind"] == "leave_field_banish" and restriction in record["restrictions"]
        and any(_leave_field_rule(record, op) for op in record["operations"]))


def _fusion_revival_route(code, available, records, dependencies, operation_facts, facts, fusion_proofs, key):
    """Join a completed fusion and the immediate field exit of its selected card."""
    slot = ("extra", code)
    if code not in available.extra:
        return None
    entries = [Need(f"{key}:fusion:{i}", facts[operation_facts[source]].output, mode="presence")
               for i, (source, proof) in enumerate(fusion_proofs.items())
               if any(option["target"] == code for option in proof["options"])]
    if not entries:
        return None
    exits = []
    for (source, ri, oi), uid in operation_facts.items():
        fact = facts[uid]
        move = fact.transfer
        if (move is None or move.destination != "grave" or move.reason != "effect" or move.owner != "self"
                or move.controller != "self" or move.selection != "targeted" or slot not in (move.inventory or ())
                or fact.quantity != 1):
            continue
        record = records[source][ri]
        operation = record["operations"][oi]
        if (operation["kind"] != "send_grave" or "field" not in operation["from_zones"]
                or operation.get("simultaneous_group") or operation_record(record, operation)["operations"][-1] != operation):
            continue
        eligible, _ = dependencies.candidate_status(code, dict(category="operations",
            operation=dict(operation, from_zones=["field"])))
        if eligible is True:
            exits.append(Need(f"{key}:exit:{len(exits)}", fact.output, mode="presence"))
    return InputGroup("all", (InputGroup("any", tuple(entries)), InputGroup("any", tuple(exits)))) if exits else None


def _hand_deck_grave_route(code, controller, available, operation_facts, facts, key):
    """Bind a legal prior movement from the named player's hand or deck."""
    if code not in available.main:
        return None
    sources = []
    copies = available.main.count(code)
    for (source, _, _), uid in operation_facts.items():
        fact = facts[uid]
        move = fact.transfer
        if (move is None or move.destination != "grave" or move.origin not in ("hand", "deck")
                or move.owner not in (controller, "both") or move.reason not in ("effect", "cost")):
            continue
        if source == code and (controller == "self" or copies < 2):
            continue
        if controller == "self" and (("main", code) not in (move.inventory or ())
                and not (move.origin == "deck" and move.selection == "random")):
            continue
        sources.append(Need(f"{key}:send:{len(sources)}", fact.output, mode="presence"))
    return InputGroup("any", tuple(sources)) if sources else None


def _configuration_relations(available, records, dependencies, aliases, operation_facts, facts, pools, context,
                             *, compact_stock=False, fusion_proofs=None):
    """Static applicability and complete stock, without a current duel state.

    An activation port describes a printed use, not an event witnessed in a
    duel. Opponent selectors describe response coverage, not an invented board.
    Only explicitly joint uses reserve their shared resources together.
    """
    from .construction_inventory import matches
    from .effect_records import operation_record
    rows = dependencies.rows
    host = context.relations.facts if context is not None else ()
    added, unbound, processed = [], set(), set()
    present = set(available.main + available.extra)
    facts_by_use = {"functional:" + fact.fact_id: fact for fact in facts}

    def supplied(resource):
        return any(resource.accepts(f.output) for f in host)

    def physical(code):
        section = 'extra' if code in available.extra else 'main'
        key = 'configuration:physical:'+str(code)
        pools.setdefault(key, ResourcePool(key, 'candidate physical copies', inventory=((section, code),)))
        return section, key

    for code in sorted(present & records.keys()):
        entries = []
        for ri, record in enumerate(records[code]):
            procedure = record.get('summon_procedure')
            if not procedure or procedure.get('kind') == 'xyz_overlay':
                continue
            permitted, _ = dependencies.candidate_status(code, dict(category='operations',
                operation=dict(kind='special_summon', from_zones=[procedure['from_zone']], controller='self')))
            predicate = procedure['condition']
            if permitted is False or predicate['left'] == predicate['right']:
                continue
            claims = []
            for limit in record['count_limits']:
                if limit.get('status') == 'known' and limit.get('scope') == 'same_name_summon_method':
                    pid = 'catalog-limit:'+str(aliases[str(code)])+':'+str(record['effect_index'])
                    pools.setdefault(pid, ResourcePool(pid, limit['source'], capacity=limit['maximum']))
                    claims.append(Claim(pid))
            key = 'configuration:'+str(code)+':procedure:'+str(ri)
            port = Resource('summon_procedure', attributes=('card:'+str(code),))
            section, _ = physical(code)
            added.append(RelationFact(key, key, port, procedure['source'], code, section,
                claims=tuple(claims), conditions=('printed summon condition: '+str(predicate),),
                unknown=('summon_procedure_eligibility',) if permitted is None else ()))
            entries.append(port)
        for ri, record in enumerate(records[code]):
            keys = {u.removeprefix('functional:'):oi for (c, r, oi), u in operation_facts.items() if (c, r) == (code, ri)}
            for fact in (f for f in facts if f.fact_id in keys):
                oi = keys[fact.fact_id]
                scoped = operation_record(record, record['operations'][oi] if oi is not None else None)
                for need in _needs(fact.inputs):
                    if need.need_id in processed:
                        continue
                    processed.add(need.need_id)
                    resource = need.resource
                    if supplied(resource):
                        continue
                    key = 'configuration:purpose:'+need.need_id
                    if resource.kind == 'activation':
                        event = resource.event
                        if scoped["trigger"].get("latest_entry") == "fusion_summon":
                            route = _fusion_revival_route(code, available, records, dependencies, operation_facts,
                                                         facts_by_use, fusion_proofs or {}, key)
                            source = scoped["trigger"]["source"]
                            section, pid = physical(code)
                            moved = ResourceTransfer(source, "field", "grave", "self", "self",
                                "targeted", ((section, code),), "effect") if route else None
                            added.append(RelationFact(key, key, resource, source, code, section, inputs=route,
                                output_pool=pid if route else None, transfer=moved,
                                conditions=("same card: fusion summon, then effect send from monster zone",),
                                unknown=() if route else ("latest_fusion_send_route_unobserved",)))
                            continue
                        if controller := scoped["trigger"].get("hand_deck_controller"):
                            route = _hand_deck_grave_route(code, controller, available, operation_facts, facts_by_use, key)
                            added.append(RelationFact(key, key, resource, scoped["trigger"]["source"],
                                code, "main", inputs=route, conditions=("sent from hand or deck: " + controller,),
                                unknown=() if route else ("hand_deck_grave_route_unobserved",)))
                            continue
                        if event in (None, 'unknown'):
                            continue
                        # Intrinsic summon restrictions and printed materials
                        # are checked separately against this configuration.
                        checks = dependencies.summon_trigger_check(code, scoped)
                        if checks['status'] == 'missing':
                            continue
                        inputs = None
                        if scoped['trigger'].get('related_effect_index') is not None:
                            parents = {operation_facts[(code,r,j)].removeprefix('functional:')
                                for r, earlier in enumerate(records[code])
                                if earlier['effect_index']==scoped['trigger']['related_effect_index']
                                for j, op in _record_outputs(earlier) if op is not None
                                and op['kind']==scoped['trigger']['related_operation']
                                and (code,r,j) in operation_facts}
                            ports = [f.output for f in facts if f.fact_id in parents]
                            if not ports:
                                continue
                            inputs = InputGroup('any',tuple(Need(key+':related:'+str(i), port,
                                mode='presence') for i,port in enumerate(ports)))
                        if entries and event not in ('normal_summon', 'sent_to_grave'):
                            entry = InputGroup('any', tuple(Need(key+':entry:'+str(i), port, mode='presence')
                                for i, port in enumerate(entries)))
                            inputs = InputGroup('all',(inputs,entry)) if inputs else entry
                        if event == 'normal_or_special_summon':
                            normal,_=dependencies.candidate_status(code,dict(category='operations',
                                operation=dict(kind='normal_summon',from_zones=['hand'],controller='self')))
                            if normal is True:
                                allowance=Need(key+':normal',Resource('normal_summon_allowance',attributes=('controller:self',)))
                                inputs=InputGroup('any',(allowance,inputs)) if inputs else InputGroup('all',(allowance,))
                        hand_handler = (scoped['trigger'].get('zone') == 'hand' and any(
                            cost.get('exclude_source_copy') and cost.get('source_card_id') == code
                            and cost.get('from_zones') == ['hand'] for cost in scoped['costs']))
                        added.append(RelationFact(key, key, resource, 'printed static applicability: '+scoped['source_text'],
                            code, 'extra' if code in available.extra else 'main', inputs=inputs,
                            claims=(Claim(physical(code)[1]),) if hand_handler else (),
                            conditions=('static applicability: '+event,),
                            unknown=('summon_configuration_uncovered',) if checks['status'] == 'unknown' else ()))
                    elif resource.kind == 'effect_applicability' and 'state:occurred_this_turn' in resource.attributes:
                        # The candidate includes the card. Whether the event
                        # happened to it this turn is an independent condition.
                        observation = 'catalog-text:' + need.need_id.removeprefix('catalog:') + ':turn_event_unobserved'
                        added.append(RelationFact(key, key, resource, 'printed turn condition: '+scoped['source_text'],
                            code, 'extra' if code in available.extra else 'main', unknown=(observation,)))
                    elif resource.kind == 'effect_applicability' and _record_applicability(scoped):
                        added.append(RelationFact(key,key,resource,'printed continuous applicability: '+scoped['source_text'],
                            code,'extra' if code in available.extra else 'main',conditions=('static continuous applicability',)))
                    elif resource.kind in ('payment', 'target'):
                        category = 'costs' if resource.kind == 'payment' else 'targets'
                        item = next((v for v in scoped[category] if v.get('source') in resource.attributes), None)
                        if item is None:
                            unbound.add(need.need_id)
                            continue
                        if item.get('resource') == 'lp' and type(item.get('quantity')) is int:
                            pid = 'configuration:payable_lp'
                            pools.setdefault(pid, ResourcePool(pid, 'rule: initial 8000 LP; payment leaves positive LP', capacity=7999))
                            added.append(RelationFact(key, key, resource, 'static LP payment capacity', quantity=7999, output_pool=pid))
                            continue
                        req = dependencies.item_requirement(item, category)
                        if req is None:
                            unbound.add(need.need_id)
                            continue
                        if req['owner'] == 'opponent' and category == 'targets':
                            # Quantity belongs to the printed capability. It is
                            # not a report that those opponent cards now exist.
                            added.append(RelationFact(key, key, resource, 'printed opponent object range: '+req['source'],
                                quantity=req['minimum'], conditions=('configuration purpose: opponent object range '+req['source'],)))
                        elif req['owner'] == 'self':
                            stock = [target for target in sorted(present) if matches(rows[target], req['query'])
                                and (req['origin'] not in ('hand', 'deck') or target in available.main)
                                and (req['origin'] != 'extra' or target in available.extra)]
                            if compact_stock and stock:
                                # A resident use needs a legal allocation. Put
                                # equivalent candidates in one pool while the
                                # allocator still distinguishes physical copies.
                                pid = key+':stock'
                                members = tuple(('extra' if c in available.extra else 'main', c) for c in stock)
                                pools[pid] = ResourcePool(pid, req['source'], inventory=members)
                                added.append(RelationFact(key, key, resource, 'complete static selector: '+req['source'],
                                    quantity=len(available.main)+len(available.extra), output_pool=pid))
                                continue
                            for target in stock:
                                section, pid = physical(target)
                                target_key = key+':'+str(target)
                                added.append(RelationFact(target_key, target_key, resource, 'complete static selector: '+req['source'],
                                    target, section, output_pool=pid, inventory_scaled=True))
                        else:
                            unbound.add(need.need_id)
    return added, unbound


def _bind_unparsed_requirements(fact, unbound):
    # Keep a missing printed selector on its effect, without inventing supply.
    gaps = []
    def bind(group):
        if isinstance(group, Need):
            if group.need_id in unbound:
                gaps.append('catalog-text:' + group.need_id.removeprefix('catalog:') + ':unparsed_' + group.resource.kind)
                return None
            return group
        if group is None or group.operator != 'all':
            return group
        items = tuple(item for child in group.items if (item := bind(child)) is not None)
        return InputGroup('all', items) if items else None
    inputs = bind(fact.inputs)
    return replace(fact, inputs=inputs, unknown=(*fact.unknown, *gaps)) if gaps else fact


def _functional_relations(deck, available, records, aliases, extra_ids, context, budget, dependencies, config,
                          *, continuation=None, should_stop=None, previous_projections=None, projection='resident'):
    """Evaluate one inventory projection; Side never enters the resident call."""
    from .construction_relations import evaluate_relations
    rel_facts, rel_pools, rel_uses, operation_facts = [], {}, [], {}
    fusion_proofs = {}
    present = set(available.main + available.extra)
    members = tuple(sorted({(zone, code) for zone in ("main", "extra") for code in getattr(available, zone)}))
    for code in sorted(present & records.keys()):
        zone = "extra" if code in extra_ids else "main"
        # These are selected uses of the candidate's own effects. Movement
        # ownership still comes from the operation, independently of its actor.
        observed = list(_record_facts(code, records[code], zone=zone, same_name=aliases[str(code)],
            inventory=members, dependencies=dependencies, controller="self",functional=True))
        positions = [(ri, oi) for ri, r in enumerate(records[code]) for oi, _ in _record_outputs(r)]
        for (ri, oi), (fact, pools) in zip(positions, observed):
            output = Resource("functional_operation", attributes=(fact.fact_id,))
            effect_specs, materials = dependencies.specs(code)
            operation = records[code][ri]["operations"][oi] if oi is not None else None
            scoped_record = operation_record(records[code][ri], operation)
            rows = [r for r in effect_specs[ri]["requirements"]
                    if ("operation" not in r or r["operation"] == operation)
                    and r.get('choice') in (None, (operation or {}).get('choice'))]
            cost_rows = [r for r in rows if r["category"] == "costs"]
            native = (dependencies.witnessed_processing(available, scoped_record, operation, inventory=deck)
                      if projection == "resident" else None)
            checks = [dependencies.summon_trigger_check(code, scoped_record),
                      dependencies._check(available, cost_rows, distinct=True),
                      dependencies._check(available, [r for r in rows if r["category"] != "costs"])]
            fusion=dependencies.fusion_check(available,code,scoped_record)
            if fusion:
                checks.append(fusion)
                if operation and operation['kind'] == 'fusion_summon':
                    fusion_proofs[code, ri, oi] = fusion
                if operation and operation['kind']=='return_fusion_materials':
                    # The quantity depends on the chosen printed recipe. This
                    # is a static function port, not a concrete recovery event.
                    fact=replace(fact,quantity=1,transfer=None)
            processing = dependencies.processing_check(available, scoped_record, operation,physical_inventory=deck)
            if processing:
                checks.append(processing)
                binding = scoped_record.get('type_matched_deck_send')
                if binding and operation['block_id'] == binding['send'] and fact.transfer:
                    fact = replace(fact, transfer=replace(fact.transfer,
                        inventory=tuple(('main', c) for c in processing['possible_send_card_ids'])))
            if context is not None:
                def supplied_external(req):
                    if req.get('owner','self') == 'self' or req['category'] not in ('costs','targets'):
                        return False
                    kind = 'payment' if req['category']=='costs' else 'target'
                    items = scoped_record[req['category']]
                    item = next((v for v in items if v.get('source')==req['source']),{})
                    resource = Resource(kind,reason=item.get('reason'),attributes=(req['source'],))
                    return any(resource.accepts(f.output) and f.quantity is not None and f.quantity>=req['minimum']
                               for f in context.relations.facts)
                checks[1] = dependencies._check(available,[r for r in cost_rows if not supplied_external(r)],distinct=True)
                checks[2] = dependencies._check(available,[r for r in rows if r['category']!='costs' and not supplied_external(r)])
            material = dependencies.summon_material_check(available, code)
            if material:
                checks.append(material)
            if native and native["status"] == "inventory_present":
                checks.append(native)
                if fact.transfer and fact.transfer.inventory is None:
                    fact = replace(fact, transfer=replace(fact.transfer, selection="targeted",
                        inventory=tuple(("main", c) for c in native["observed_card_ids"])))
            inventory_port = Resource("functional_inventory", attributes=(fact.fact_id,))
            inventory_key = fact.fact_id+":inventory"
            if not any(r["status"] == "missing" for r in checks):
                gaps = tuple("inventory_selector:"+str(i) for i,r in enumerate(checks) if r["status"] == "unknown"
                    and (r.get('unknown_selectors') or r.get('unknown_restrictions') or not r.get('requirements')))
                gaps += tuple("complete_selector:"+r.get("source", "") for r in effect_specs[ri]["unknown"]
                              if r['category'] not in ('costs', 'targets')
                              and ("operation" not in r or r["operation"] == operation)
                              and not (native and operation is not None and r.get("operation") == operation)
                              and r.get('choice') in (None, (operation or {}).get('choice')))
                rel_facts.append(RelationFact(inventory_key, inventory_key, inventory_port,
                    "complete candidate inventory", code, zone, unknown=gaps))
            inputs = InputGroup("all", tuple(v for v in (fact.inputs,
                Need(inventory_key, inventory_port, mode="presence")) if v is not None))
            unknown = fact.unknown
            if native and native["status"] == "inventory_present":
                unknown = tuple(gap for gap in unknown if not gap.endswith(":activation_condition_unparsed"))
                fact = replace(fact, conditions=(*fact.conditions, "native-receipt:" + native["receipt"]))
            if processing and processing['status'] == 'unknown':
                unknown += (processing['reason'],)
            rel_facts.append(replace(fact, output=output, quantity=fact.quantity if fact.transfer else 1,
                inputs=inputs, unknown=unknown))
            rel_pools.update((p.pool_id, p) for p in pools)
            uid = "functional:" + fact.fact_id
            rel_uses.append(UseRequirement(uid, InputGroup("all", (Need(uid, output, mode="presence"),)),
                fact.source, required=False))
            operation_facts[code, ri, oi] = uid
    compact_stock = context is None and len(available.main) <= len(deck.main) and len(available.extra) <= len(deck.extra)
    configured, unbound = _configuration_relations(available, records, dependencies, aliases,
        operation_facts, rel_facts, rel_pools, context, compact_stock=compact_stock, fusion_proofs=fusion_proofs)
    rel_facts = [_bind_unparsed_requirements(f, unbound) for f in rel_facts]
    rel_facts.extend(configured)
    if context is not None:
        rel_facts.extend(context.relations.facts)
        for pool in context.relations.pools:
            if pool.pool_id in rel_pools and rel_pools[pool.pool_id] != pool:
                raise ContractError("host resource pool conflicts with catalog")
            rel_pools[pool.pool_id] = pool
        rel_uses.extend(context.relations.uses)
    pairs, theme_state = [], {}
    if config.get('theme_profile', {}).get('goals'):
        from .construction_theme import theme_pairs
        pairs, pending = theme_pairs(operation_facts, records,
            dependencies, available, config['theme_profile'], budget, fusion_proofs,
            continuation=(continuation or {}).get('theme'), should_stop=should_stop, work_state=theme_state)
        if pending is not None:
            return dict(calculation_pending=dict(theme=pending)), operation_facts
    # These facts already exist in the selected finite inventory. Their count
    # is data extent, not missing information. Work is sliced below instead.
    need_count=len({n.need_id for f in rel_facts for n in _needs(f.inputs)}|
        {n.need_id for u in rel_uses for n in _needs(u.inputs)})
    allowance_count=len({n.resource.attributes for f in rel_facts for n in _needs(f.inputs)
        if n.resource.kind=='normal_summon_allowance'})
    structural=replace(budget,facts=max(budget.facts,len(rel_facts)+allowance_count),
        needs=max(budget.needs,need_count))
    relation_context = RelationContext(tuple(rel_uses), tuple(rel_facts),
        tuple(rel_pools.values()), constraints=context.relations.constraints if context is not None else (), budget=structural)
    copies = tuple(c for c in SkeletonSpec(deck, ()).copies() if c.zone != "side")
    skeleton = SkeletonSpec(deck, (AxisModule("functional:inventory", "complete resident inventory", copies, ()),))
    counts = Counter((z, c) for z in ("main", "extra") for c in getattr(available, z))
    unresolved = tuple(sorted(present - records.keys()))
    previous = previous_projections.pop(projection, None) if previous_projections is not None else None
    if (previous is not None and previous.index.context == relation_context
            and previous.index.unresolved_cards == unresolved and continuation is None):
        index = previous.index
    else:
        previous = None
        matching=(continuation or {}).get('matching')
        while True:
            index = relation_index(None, relation_context,continuation=matching,should_stop=should_stop)
            if index.continuation is None:break
            matching=index.continuation
            if should_stop is None or should_stop() or budget.matches==0:
                return dict(calculation_pending=dict(theme=theme_state or None,matching=matching)),operation_facts
        index.unresolved_cards = unresolved
    updating=(continuation or {}).get('updating')
    while True:
        evaluation = evaluate_relations(skeleton, relation_context, index, previous=previous, inventory_counts=counts,
            continuation=updating, should_stop=should_stop, resumable=True)
        relation = evaluation.data
        if not relation.get('continuation'):break
        updating=relation['continuation']
        if should_stop is None or should_stop() or budget.updates==0 or budget.allocations==0:
            return dict(calculation_pending=dict(theme=theme_state or None,matching=index.matched_state,updating=updating)),operation_facts
    if previous_projections is not None:
        previous_projections[projection] = evaluation
    calls = _targeted_calls(deck, available, records, dependencies, operation_facts)
    return dict(relation, theme_pairs=pairs, targeted_calls=calls), operation_facts


def _targeted_calls(deck, available, records, dependencies, operation_facts):
    """Record direct named access for density pricing, without activation dependencies."""
    from .construction_inventory import _activation_target, _has_self_grave_payment, matches
    from .construction_theme import operation_query

    recipients = defaultdict(set)
    for code in set(available.main) & records.keys():
        for record in records[code]:
            trigger = record['trigger']
            if trigger.get('event') in ('sent_to_grave', 'special_summon', 'normal_summon', 'normal_or_special_summon'):
                recipients[trigger['event'], trigger.get('reason')].add(code)
    calls = []
    for (code, ri, oi), uid in operation_facts.items():
        if oi is None:
            continue
        record = records[code][ri]
        operation = record['operations'][oi]
        origins = operation.get('from_zones', ())
        if (operation.get('owner') != 'self' or operation.get('random') or not origins
                or operation.get('quantity') is None):
            continue
        if operation.get('to_zone') == 'grave':
            events = ('sent_to_grave',)
            reasons = (None, operation.get('reason'))
        elif operation.get('to_zone') == 'field' and operation['kind'] == 'special_summon':
            events = ('special_summon', 'normal_or_special_summon')
            reasons = (None, 'not_applicable')
        elif operation.get('to_zone') == 'field' and operation['kind'] in ('normal_summon', 'tribute_summon'):
            events = ('normal_summon', 'normal_or_special_summon')
            reasons = (None, 'not_applicable')
        else:
            continue
        query = operation_query(operation, dependencies)
        if query is None:
            continue
        revealed = None
        if operation.get('selection_method') == 'revealed_card':
            proof = dependencies.processing_check(available, operation_record(record, operation), operation,
                physical_inventory=deck)
            revealed = {c for option in (proof or {}).get('options', ())
                if (option['result'] or {}).get('status') == 'inventory_present' for c in option['revealed_card_ids']}
        for event in events:
            for reason in reasons:
                for target in sorted(recipients.get((event, reason), ())):
                    if ((revealed is not None and target not in revealed) or
                            not matches(dependencies.rows[target], query)):
                        continue
                    if not any(dependencies.candidate_status(target, dict(category='operations',
                            operation=dict(operation, from_zones=[origin])))[0] is True for origin in origins):
                        continue
                    if operation.get('simultaneous_group'):
                        proof = dependencies.simultaneous_processing(available, operation_record(record, operation),
                            operation, card_id=target)
                        if proof is not None and proof['status'] != 'inventory_present':
                            continue
                    activation_target = _activation_target(record, operation)
                    if activation_target and (activation_target.get('availability_timing') == 'before_activation_payment'
                                              or _has_self_grave_payment(record)):
                        if dependencies.summon_choice_check(available, record, operation, (target,),
                                                            physical_inventory=deck) is not True:
                            continue
                    calls.append(dict(source=uid.removeprefix('functional:'), target=target, event=event, reason=reason))
    return calls


def _bind_functional_support(facts, projections, available, specs, catalog, context, condition, config, sources):
    from .construction_inventory import InventoryDependencies, matches, selector, requirement, query_supported
    dependencies = InventoryDependencies(catalog)
    theme_rules = {r['rule_id']:r['predicate'] for r in config['theme_rules']}
    supported = {(u.scope_id, facts['use_details'][u.use_id]['relation_fact_id'])
        for u in facts['uses'] if u.contributes and u.self_condition is True}
    calls = {}
    for scope, (relation, _) in projections.items():
        for call in relation['targeted_calls']:
            if (scope, call['source']) in supported:
                calls.setdefault((scope, call['target'], call['event'], call['reason']), call['source'])
    revised = []
    for use in facts["uses"]:
        detail = facts["use_details"][use.use_id]
        semantic, scope = detail["semantics"], use.scope_id
        present = set(available[scope].main + available[scope].extra)
        themes = []
        for rule_id, old in use.theme_conditions:
            predicate = theme_rules[rule_id]
            grave_rule = (predicate.get('grave_related') is True or any(
                'grave' in ([predicate[k]] if isinstance(predicate.get(k),str) else predicate.get(k,()))
                for k in ('from_zone','to_zone')))
            value = None if grave_rule else True
            if detail["trigger"].get("zone") == "grave" or "grave" in semantic["from_zones"]:
                value = True  # Its own complete grave use is checked separately.
            if grave_rule and semantic["to_zone"] == "grave" and semantic["owner"] == "self":
                operation = detail["operation"]
                query = operation.get("selector_query") or (selector(operation["selector"]) if operation.get("selector") else None)
                parsed = requirement(operation.get("source", ""), "operations")
                query = query or (parsed["query"] if parsed else None)
                query = dependencies.resolve_query(query) if query else None
                receivers = []
                for other in facts["uses"]:
                    if not other.contributes:
                        continue
                    target = facts["use_details"][other.use_id]
                    trigger = target["trigger"]
                    if (other.scope_id != scope or target["card_id"] not in present
                            or trigger.get("event") != "sent_to_grave"
                            or trigger.get("reason") not in (None, semantic["reason"])):
                        continue
                    if semantic["from_zones"] == ["deck"] and target["card_id"] not in available[scope].main:
                        continue
                    if query and not query_supported(query):
                        receivers.append(None)
                        continue
                    if query and not matches(catalog.assets.rows[target["card_id"]], query):
                        continue
                    if not operation.get("random") and query is None:
                        receivers.append(None)
                        continue
                    checks = target["inventory_checks"]
                    if any(v and v["status"] == "missing" for v in checks.values()):
                        receivers.append(False)
                        continue
                    code_specs = specs[target["card_id"]][0]
                    row = next((r for r in code_specs if r["record"]["trigger"] == trigger
                                and target["operation"] in r["record"]["operations"]), None)
                    receivers.append(True if row and not row["unknown"] and not row["record"]["costs"]
                        and not row["record"]["restrictions"] and not row["record"]["unknown"]
                        and row["record"]["conditions"]["status"] == "recognized" else None)
                value = True if True in receivers else None if None in receivers or not present <= specs.keys() else False
            if rule_id in detail.get("unknown_theme_predicates", ()):
                value = None
            # Retain unknown semantic predicates instead of treating them as a hit.
            rules = facts["fact_details"].get(old, {}) if isinstance(old, str) else {}
            if isinstance(old, str):
                facts["variables"][old] = value
                rules["receiver_status"] = "supported" if value is True else "failed" if value is False else "unknown"
            themes.append((rule_id, old))
        relation = projections[scope][0]
        joint_conditions = []
        for group_id, group in relation.get("joint_groups", {}).items():
            bound = {uid for req in (context.relations.uses if context is not None else ())
                     if req.use_id in group["use_ids"] for uid in req.functional_use_ids}
            base_id = use.use_id.removesuffix(":" + scope) if scope != "resident" else use.use_id
            if base_id in bound:
                if scope != 'resident':
                    group = _side_joint_capacity(group, bound, facts, scope, relation, sources)
                status = group["status"]
                joint_conditions.append(_relation_support(group, "joint:"+group_id, scope, condition,
                    tuple(req.source for req in context.relations.uses if req.use_id in group["use_ids"])))
                detail.setdefault("joint_groups", []).append(deepcopy(group))
        mode = use.valuation_mode
        if mode == "main_density" and use.self_condition is True and detail["relation"].get("status") == "supported":
            direct = calls.get((scope, detail['card_id'], detail['trigger'].get('event'), detail['trigger'].get('reason')))
            if direct is not None:
                mode = "called"
                detail["called_by"] = direct
            for supplier in detail["relation"].get("suppliers", ()):
                record = relation["fact_records"].get(supplier, {})
                output = record.get("output", {})
                if (output.get("kind") == "activation" and output.get("origin") in ('deck','hand','grave','banished','field','extra')
                        and output.get('selection') != 'random'
                        and f"card:{detail['card_id']}" in output.get("attributes", ())
                        and output.get("event") == detail["trigger"].get("event")):
                    mode = "called"
                    detail["called_by"] = supplier
                    break
        base_id = use.use_id.removesuffix(":" + scope) if scope != "resident" else use.use_id
        required_by = sorted({req.source for req in (context.relations.uses if context is not None else ())
                              if req.required and base_id in req.functional_use_ids})
        revised.append(replace(use, theme_conditions=tuple(themes), valuation_mode=mode,
            joint_condition=_all_support(joint_conditions), required=use.required or bool(required_by),
            requirement_origin=use.requirement_origin or ("; ".join(required_by) if required_by else None)))
    facts["uses"] = revised
    # Multiple proofs of the same actual function/source share one valuation.
    # A proven concrete call applies to that function, not the card's other effects.
    called = {(u.scope_id, u.score_family_id, source) for u in revised if u.valuation_mode == "called" for source in u.source_ids}
    facts["uses"] = [replace(u, valuation_mode="called") if all((u.scope_id,u.score_family_id,s) in called for s in u.source_ids)
                     else u for u in revised]
    if context is not None:
        actual = {identity for u in revised for identity in (u.use_id,
            u.use_id.removesuffix(':'+u.scope_id) if u.scope_id != 'resident' else u.use_id)}
        unresolved = {uid for req in context.relations.uses for uid in req.functional_use_ids
                      if uid not in actual and projections["resident"][0]["uses"][req.use_id]["status"] != "missing"}
        # Removing the actual source can make its original requirement fail.
        # A binding to a missing source is not evidence for that source, and a
        # supported requirement still cannot name an unrelated absent use.
        if unresolved:
            if "deferred" in facts["coverage"].values():
                facts["scope_status"]["joint"] = "deferred"
            else:
                raise ContractError("joint requirement binds absent functional uses")


def _bind_automatic_themes(facts, projections, config, condition, sources):
    from .construction_theme import PRIMARY, SECONDARY
    profile = config.get('theme_profile')
    if profile is None:
        return
    if profile['gaps']:
        facts.setdefault('unknown_scope', []).extend('theme:' + gap for gap in profile['gaps'])
        facts['scope_status']['functions'] = 'deferred'
    goals = {g['goal_id'] for g in profile['goals']}
    by_position = {(u.scope_id, *facts['use_details'][u.use_id]['operation_key']): u
                   for u in facts['uses'] if u.contributes}
    preparations = defaultdict(list)
    for scope, (relation, _) in projections.items():
        if scope != 'resident':
            side = facts['side_contexts'][scope]
            capacity = side['capacity']
            resource_positions = {sources[s]['card_id']: (sources[s]['destination'], sources[s]['card_id'])
                for s in side['source_ids']}
        for pair in relation['theme_pairs']:
            source = by_position.get((scope, *pair['source']))
            receiver = by_position.get((scope, *pair['receiver']))
            if source is None or receiver is None:
                continue
            connection = pair['connection']
            compatible = True
            if connection['gaps']:
                compatible = condition('theme:' + digest((source.use_id, receiver.use_id)), None,
                    'printed_theme_compatibility', (*source.evidence_refs, *receiver.evidence_refs))
            own = _all_support([compatible, receiver.self_condition])
            joint = own
            if scope != 'resident':
                footprint = {resource_positions[code] for code in (pair['source'][0], pair['receiver'][0])}
                resources = (resource_positions[code] for code in connection['resources'] if code in resource_positions)
                fits = any(all(n <= capacity[zone]
                    for zone, n in Counter(z for z, _ in footprint | {resource}).items())
                    for resource in resources)
                joint = _all_support([own, fits])
            preparations[source.use_id].append((receiver, own, joint, connection))
    revised = []
    facts['theme_witnesses'] = {}
    def any_support(items):
        return _support_group('any',items)
    for use in facts['uses']:
        detail = facts['use_details'][use.use_id]
        themes, joint = list(use.theme_conditions), list(use.theme_joint_conditions)
        joint_condition = use.joint_condition
        if use.contributes and use.scope_id != 'resident':
            relation = projections[use.scope_id][0]
            capacity = _side_joint_capacity(detail['relation'], {use.use_id.removesuffix(':' + use.scope_id)},
                facts, use.scope_id, relation, sources, required_sources=())
            joint_condition = _all_support([joint_condition,
                _relation_support(capacity, 'automatic-capacity:' + use.use_id, use.scope_id, condition, use.evidence_refs)])
        if use.contributes and (detail['goal_id'] in goals or detail.get('explicit_task_goal')):
            themes.append((PRIMARY, True))
            detail['automatic_goal'] = dict(role='primary', percentage=100, goal_id=detail['goal_id'])
        elif use.use_id in preparations:
            rows = preparations[use.use_id]
            themes.append((SECONDARY, any_support([row[1] for row in rows])))
            joint.append((SECONDARY, any_support([row[2] for row in rows])))
            facts['theme_witnesses'][use.use_id] = [dict(receiver_use_id=r.use_id,
                receiver_source_ids=list(r.source_ids), joint_condition=expr) for r, _, expr, _ in rows]
            detail['automatic_goal'] = dict(role='secondary', percentage=50,
                counterparts=[dict(use_id=r.use_id, connection=connection) for r, _, _, connection in rows])
        revised.append(replace(use, theme_conditions=tuple(themes), theme_eligible=tuple(k for k, _ in themes),
            theme_joint_conditions=tuple(joint), joint_condition=joint_condition))
    facts['uses'] = revised


def _side_joint_capacity(group, bound, facts, scope, relation, sources, *, required_sources=None):
    """Check the physical sources needed by one direction's supplied proof."""
    if group['status'] == 'missing':
        return group
    capacities = facts['side_contexts'][scope]['capacity']
    required = (set(required_sources) if required_sources is not None else
        {s for u in facts['uses'] if u.scope_id == scope
            and u.use_id.removesuffix(':'+scope) in bound for s in u.source_ids})
    used = Counter(sources[s]['destination'] for s in required)
    shortage = [z for z,n in used.items() if n > capacities[z]]
    if shortage:
        return {**group, 'status':'missing', 'gaps':[*group['gaps'],*('swap_capacity:'+z for z in shortage)]}
    # The existing allocator identifies every physical payment/material copy.
    # A consumption without a declared return cannot share that copy.
    branches = group.get('branches') or [group]
    unknown, conditional = False, []
    for branch in branches:
        if branch['status'] == 'missing':
            continue
        consumed = Counter()
        for pid,entries in branch.get('usage',{}).items():
            pool = relation.get('resource_pools',{}).get(pid,{})
            inventory = pool.get('inventory',())
            zones = {z for z,_ in inventory}
            if len(zones) == 1 and not pool.get('recoveries') and not pool.get('recovery_between') and not pool.get('reusable_if'):
                consumed[next(iter(zones))] += sum(n for t,n in entries.items() if not t.startswith('presence:'))
        if any(n > capacities[z] for z,n in consumed.items()):
            continue
        footprint = set(required)
        for supplier in branch.get('suppliers',()):
            record = relation.get('fact_records',{}).get(supplier,{})
            code = record.get('card_id')
            if code is None or any(sources[s]['card_id']==code for s in footprint):
                continue
            options = sorted(s for s,v in sources.items() if v['card_id']==code)
            if options:
                footprint.add(options[0])
        forced = Counter(sources[s]['destination'] for s in footprint)
        if any(n > capacities[z] for z,n in forced.items()):
            continue
        for allocation in branch.get('inventory_allocation',branch.get('recovery_allocation',())):
            physical,copy = allocation.get('slot',(None,None))
            if not isinstance(physical,str) or not physical.startswith('physical:'):
                continue
            parts = physical.split(':')
            zone,code = parts[1],int(parts[2])
            choices = sorted(s for s,v in sources.items() if v['destination']==zone and v['card_id']==code)
            if type(copy) is int and copy < len(choices):
                footprint.add(choices[copy])
        counts = Counter(sources[s]['destination'] for s in footprint)
        if all(n <= capacities[z] for z,n in counts.items()):
            # A transfer's objects also occupy deck slots even if they have no
            # effect of their own in this proof. Check the necessary integer
            # space against its complete selector using the existing stock.
            impossible = False
            for supplier in branch.get('suppliers', ()):
                record = relation.get('fact_records', {}).get(supplier, {})
                move, quantity = record.get('transfer'), record.get('quantity')
                if (not move or move.get('owner') != 'self' or move.get('inventory') is None
                        or type(quantity) is not int):
                    continue
                stock = {tuple(v) for v in move['inventory']}
                matching = {s for s,v in sources.items() if (v['destination'],v['card_id']) in stock}
                for zone, capacity in capacities.items():
                    minimum = max(0, quantity - sum(sources[s]['destination'] != zone for s in matching))
                    covered = sum(sources[s]['destination'] == zone for s in footprint & matching)
                    if counts[zone] + max(0, minimum-covered) > capacity:
                        impossible = True
            if impossible:
                continue
            if branch['status'] == 'supported':
                return group
            conditional.append(branch)
            continue
        unknown = True
    if conditional:
        expressions = [b['support_expression'] for b in conditional]
        if unknown or group.get('branches_incomplete'):
            expressions.append(('atom','swap_capacity_allocation:'+scope+':'+':'.join(sorted(bound))))
        return {**group, 'status':'unknown', 'branches':conditional,
            'support_expression':('any', tuple(expressions)),
            'unknown':sorted({v for b in conditional for v in b.get('unknown', ())})}
    if unknown or group.get('branches_incomplete'):
        return {**group,'status':'unknown','unknown':[*group['unknown'],'swap_capacity_allocation'],
            'support_expression':('atom','swap_capacity_allocation:'+scope+':'+':'.join(sorted(bound)))}
    return {**group,'status':'missing','gaps':[*group['gaps'],'swap_capacity']}


_SPECIAL_SUMMONS = {"special_summon", "fusion_summon", "synchro_summon", "xyz_summon",
                    "link_summon", "pendulum_summon", "ritual_summon"}


def _summoned_inventory(record, operation, objects, fusion):
    """Read the selected summon object from the same static check as scoring."""
    if operation.get('kind') not in _SPECIAL_SUMMONS:
        return ()
    if operation['kind'] == 'fusion_summon' and fusion is not None:
        return sorted({option['target'] for option in fusion['options']} | set(fusion['uncovered_targets']))
    if operation.get('subject') == 'this_card':
        return [record['card_id']]
    requirements = objects['requirements']
    selected = [r for r in requirements if r['category'] == 'operations' and r.get('operation') == operation]
    target_ref = operation.get('target_ref')
    if type(target_ref) is int and 0 <= target_ref < len(record['targets']):
        source = record['targets'][target_ref]['source']
        selected.extend(r for r in requirements if r['category'] == 'targets' and r['source'] == source)
    return sorted(set.intersection(*(set(r['matching_card_ids']) for r in selected))) if selected else ()


def _restriction_match(rule, detail, card_properties=None, *, summon_choice=None):
    """Match the actual processing or payment, with unknown kept local."""
    kind = rule["kind"]
    if kind=='cannot_activate' and rule.get('required_state')=='special_summoned':
        card = (card_properties or {}).get(str(detail.get('card_id')), {})
        if not card.get('type',0)&1 or (detail.get('operation') or {}).get('phase')!='resolution':
            return False
        trigger=detail.get('trigger',{})
        if trigger.get('zone') in ('hand','grave','banished'):
            return False
        if trigger.get('event')=='special_summon':
            return False
        if trigger.get('event') in ('normal_summon', 'tribute_summon'):
            return True
        supported=detail.get('special_summon_supported')
        return not supported if type(supported) is bool else None
    special = _SPECIAL_SUMMONS
    actions = {
        "cannot_normal_summon": {"normal_summon", "tribute_summon"},
        "cannot_special_summon": special,
        "cannot_special_summon_from_extra": special,
        "extra_fusion_only": special,
        "cannot_summon": special | {"normal_summon", "tribute_summon", "flip_summon"},
        "cannot_declare_attack": {"attack", "battle", "battle_damage"},
        "cannot_attack": {"attack", "battle", "battle_damage"},
        "cannot_draw": {"draw"}, "cannot_send_grave": {"send_grave", "mill"},
        'grave_destination_replace':{'send_grave','mill'},
        "cannot_banish": {"banish"}, "cannot_return": {"return_hand", "return_deck"},
        "cannot_release": {"release"}, "cannot_set": {"set", "set_card", "normal_set", "monster_set"},
    }
    raw = detail.get("operation") or {}
    entries = [detail["semantics"], *detail.get("costs", ()), *detail.get("processing_prerequisites", ())]
    matches = []
    for operation in entries:
        action = operation["kind"]
        unknown = False
        if kind == "cannot_activate":
            if operation is not entries[0] or detail.get("applicability") == "this_card_in_monster_zone":
                continue
            phase = raw.get("phase")
            if phase in ("continuous", "summon_procedure", "rule"):
                continue
            unknown = phase != "resolution"
        elif kind == "cannot_add_hand":
            if operation.get("to_zone") != "hand":
                if operation.get("to_zone") is not None or action not in ("draw", "search", "recover", "add_hand", "return_hand"):
                    continue
                unknown = True
        elif kind == "cannot_normal_summon" and action in ("normal_set", "monster_set"):
            if rule.get("includes_set") is False:
                continue
            unknown = rule.get("includes_set") is not True
        elif action not in actions.get(kind, ()):
            continue
        activation_zone = detail.get('trigger', {}).get('zone') if kind == 'cannot_activate' else None
        origins = ({activation_zone} if activation_zone else set()) if kind == 'cannot_activate' else (
            set(operation.get("from_zones", ())))
        allowed = rule.get("from_zones")
        if kind in ("cannot_special_summon_from_extra", "extra_fusion_only"):
            allowed = ["extra"]
            if kind == "extra_fusion_only":
                if action == "fusion_summon":
                    continue
                unknown |= action not in ("synchro_summon", "xyz_summon", "link_summon")
        if allowed:
            if origins and not origins & set(allowed):
                continue
            unknown |= not origins or not origins <= set(allowed)
        excluded = False
        for key in ("to_zone", "reason"):
            if rule.get(key) is not None:
                if operation.get(key) is not None and operation[key] != rule[key]:
                    excluded = True
                    break
                unknown |= operation.get(key) is None
        if excluded:
            continue
        player = rule.get("controller", rule.get("owner"))
        actor = operation.get("owner") if kind in ("cannot_draw", "cannot_add_hand") else (
            operation.get("controller", raw.get("controller", "self")))
        if player in ("self", "opponent") and actor in ("self", "opponent") and player != actor:
            continue
        unknown |= actor not in ("self", "opponent") and not (
            kind in ("cannot_draw", "cannot_add_hand") and actor == "both")
        if rule.get('allowed_summons') and action in special:
            from .build_semantics import matches as predicate_matches
            properties = card_properties or {}
            candidates = [(code, properties.get(str(code))) for code in detail.get('summoned_card_ids', ())]
            if candidates and all(row is not None for _, row in candidates):
                permitted = tuple(code for code, row in candidates if predicate_matches(row, rule['allowed_summons']))
                if len(permitted) == len(candidates):
                    continue
                if permitted:
                    proof = summon_choice(permitted) if summon_choice is not None else None
                    if proof is True:
                        continue
                    unknown |= proof is None
            else:
                unknown = True
        matches.append(None if unknown else True)
    return True if True in matches else None if matches else False


def _bind_mandatory_impacts(facts, context, condition, *, summon_choice=None):
    from .construction_quality import UseImpact, support_state
    from .construction_relations import order_possible

    origin = 'printed restrictions and original joint requirements'
    facts['hard_requirements'] = [r for r in facts.get('hard_requirements', ()) if r['origin']!=origin]
    # Only explicitly declared order and dependencies inside a printed
    # effect can establish order for a restriction.
    details = facts['use_details']
    identities = defaultdict(set)
    for use in facts['uses']:
        identities[use.use_id].add(use.use_id)
        identities[use.use_id.removesuffix(':'+use.scope_id)].add(use.use_id)
    def bound_ids(ids):
        return set().union(*(identities[uid] for uid in ids))
    by_id = {u.use_id:u for u in facts['uses']}
    order = set()
    if context is not None:
        bound = {r.use_id:bound_ids(r.functional_use_ids) for r in context.relations.uses}
        order = {(a, b) for c in context.relations.constraints if c.kind == "before"
                 for left, right in zip(c.uses, c.uses[1:]) for a in bound[left] for b in bound[right]
                 if by_id[a].scope_id==by_id[b].scope_id}
    operation_uses = defaultdict(set)
    for use in facts['uses']:
        operation = details[use.use_id].get('operation') or {}
        if operation.get('block_id'):
            operation_uses[use.scope_id, use.effect_id, operation['block_id']].add(use.use_id)
    support_order = set()
    for use in facts['uses']:
        for previous in (details[use.use_id].get('operation') or {}).get('depends_on', ()):
            support_order.update((uid, use.use_id)
                for uid in operation_uses[use.scope_id, use.effect_id, previous])
    for left, right in support_order:
        first = details[left].get('operation') or {}
        second = details[right].get('operation') or {}
        if not first.get('simultaneous_group') or first['simultaneous_group'] != second.get('simultaneous_group'):
            order.add((left, right))

    def support_members(members):
        members = set(members)
        previous = set()
        while previous != members:
            previous = set(members)
            members.update(a for a, b in support_order if b in members)
        return members

    outgoing = defaultdict(set)
    for a,b in order:outgoing[a].add(b)
    reachable = {}
    def precedes(a,b):
        if a not in reachable:
            visited, pending = set(), list(outgoing[a])
            while pending:
                node = pending.pop()
                if node in visited:continue
                visited.add(node);pending.extend(outgoing[node]-visited)
            reachable[a] = visited
        return b in reachable[a]
    groups = {'required':{u.use_id for u in facts['uses'] if u.required}}
    if context is not None:
        bound = {r.use_id:bound_ids(r.functional_use_ids) for r in context.relations.uses}
        groups['required'].update(set().union(*(bound[r.use_id] for r in context.relations.uses if r.required)))
        groups.update({c.constraint_id:set().union(*(bound[uid] for uid in c.uses))
            for c in context.relations.constraints if c.kind=='all'})
    groups = {key: support_members(members) for key, members in groups.items()}
    group_edges = {key:set(order) for key in groups}
    group_conflicts = set()
    records = {effect.get("effect_id"): effect["record"] for coverage in facts["coverage_details"].values()
               for effect in coverage.get("effects", ())}
    relevant = {u.use_id for u in facts["uses"] if (u.contributes or u.required)
                and support_state(u.self_condition, facts["variables"]) is not False
                and support_state(u.joint_condition, facts["variables"]) is not False}
    shared_uses = set().union(*(members for members in groups.values() if len(members) > 1))
    side_views = {scope: digest((view['source_ids'], view['capacity']))
        for scope, view in facts.get('side_contexts', {}).items()}
    called = {detail['called_by'] for detail in details.values() if 'called_by' in detail}
    contracts = {uid: [(_restriction_contract(r), r) for r in details[uid]['restrictions']] for uid in relevant}
    summon_locks = defaultdict(set)
    for uid, rows in contracts.items():
        for rule, _ in rows:
            if rule and rule.get('allowed_summons'):
                summon_locks[by_id[uid].scope_id].add(digest(rule['allowed_summons']))
    for use in facts["uses"]:
        detail = facts["use_details"][use.use_id]
        checks = detail["restriction_checks"] = []
        record = records.get(use.effect_id)
        seen = set()
        for contract, restriction in contracts.get(use.use_id, ((None, r) for r in detail["restrictions"])):
            if contract is not None:
                key = digest({k: v for k, v in contract.items()
                    if k not in ('tag', 'block_id', 'group', 'source_span')})
                if key in seen:
                    continue
                seen.add(key)
            check = dict(restriction=deepcopy(restriction), affected_use_ids=[])
            checks.append(check)
            if use.use_id not in relevant:
                check["status"] = "not_adopted" if not use.contributes and not use.required else "source_unavailable"
                continue
            kind = restriction["kind"]
            scope = restriction.get('scope')
            if kind == "must_attack" and contract is not None:
                # The core enforces attack eligibility on the handler and gates
                # voluntary phase transitions. Card effects do not use that command.
                check["status"] = "battle_command_constraint"
                check["phases"] = ["main1", "battle"]
                continue
            if (scope in ('this_effect', 'this_effect_summoned_card', 'this_effect_affected_monster')
                    and record and _mapped_restriction(record, restriction)):
                check['status'] = 'effect_activation_timing' if scope == 'this_effect' else 'result_entity_restriction'
                continue
            if kind in ("battle_protection", "effect_protection"):
                # These are functional effects in the public block dictionary,
                # not prohibitions on the player's other actions. Their own
                # applicability remains in the corresponding functional use.
                check["status"] = "function_effect"
                continue
            if kind not in _PLAYER_RESTRICTIONS:
                if kind not in _INTRINSIC_RESTRICTIONS and (record is None or not _mapped_restriction(record, restriction)):
                    check["status"] = "unmapped"
                else:
                    check["status"] = "inventory_or_transfer"
                continue
            if contract is None and restriction.get('scope') in (
                    'this_card', 'this_effect', 'this_effect_summoned_card', 'this_effect_affected_monster'):
                check['status'] = 'unmapped'
                continue
            rule = contract or restriction
            kind = rule["kind"]
            for target in facts["uses"]:
                if target.scope_id != use.scope_id or target.use_id == use.use_id or target.use_id not in relevant:
                    continue
                before = precedes(target.use_id, use.use_id)
                after = precedes(use.use_id, target.use_id)
                if rule.get("lua_summon_lock") and (use.effect_id == target.effect_id or before and not after):
                    continue
                other = facts["use_details"][target.use_id]
                # Keep the object choice when it can change a joint requirement,
                # a priced recipient, or the interaction of distinct restrictions.
                choice = None
                if (summon_choice is not None and rule.get('allowed_summons')
                        and len(summon_locks[use.scope_id]) == 1
                        and use.effect_id != target.effect_id and target.use_id not in shared_uses
                        and other.get('relation_fact_id') not in called
                        and other.get('automatic_goal', {}).get('role') != 'secondary'):
                    choice = lambda allowed: summon_choice(use.scope_id, detail['card_id'], other, allowed)
                affected = _restriction_match(rule, other, facts.get('card_properties'), summon_choice=choice)
                if affected is False:
                    continue
                check["affected_use_ids"].append(target.use_id)
                whole = rule.get("whole_turn", rule.get("duration") == "whole_turn" or None)
                if whole is False and use.effect_id == target.effect_id:
                    continue  # A lock does not prohibit its own resolution or another proof of it.
                value = True if whole is True else (after if whole is False else None)
                continuous = (rule.get("condition") == detail.get("applicability") == "this_card_in_monster_zone"
                    and rule.get("duration") == "while_applicable")
                if continuous:
                    value = True  # The adoption's own support includes this exact field state.
                # An unresolved recipient cannot make an inactive lock apply.
                if (not contract or (affected is None and value is True)
                        or not continuous and rule.get("condition") not in ("effect_use", "effect_activation")):
                    value = None
                if rule.get("lua_summon_lock") and after:
                    # A relative order alone does not bind the turn in which
                    # the second use is performed.
                    value = None
                if value is not None and affected is True:
                    for group_id, members in groups.items():
                        if {use.use_id,target.use_id} <= members:
                            if whole is True or after and before:
                                group_conflicts.add(group_id)
                            elif whole is False:
                                group_edges[group_id].add((target.use_id,use.use_id))
                impact_id = "impact:" + digest((use.use_id, target.use_id, restriction))
                applicability = impact_id
                if value is None and (whole is True and affected is None or rule.get("lua_summon_lock")):
                    # Adoption is separate from applicability. The same
                    # registration, recipient stock and order share its test.
                    stock = side_views.get(use.scope_id, use.scope_id)
                    target_key = target.use_id.removesuffix(':' + use.scope_id)
                    parts = (use.effect_id, target_key, restriction, stock)
                    if rule.get("lua_summon_lock"):
                        parts += (after,)
                    applicability = "impact:" + digest(parts)
                refs = (restriction["source"], *restriction.get("evidence_refs", ()))
                expr = condition(applicability, value, "mandatory_restriction:" + kind, refs)
                facts["impacts"].append(UseImpact(impact_id, use.use_id, (target.use_id,),
                    ("base", *target.theme_eligible), (kind,), refs, expr,
                    use.scope_id, target.source_ids))
            check["status"] = ("mapped" if contract else "unknown_conditions") if check["affected_use_ids"] else "outside_affected_uses"
    for group_id, members in groups.items():
        if len(members)>1 and (group_id in group_conflicts or not order_possible(members, group_edges[group_id])):
            facts.setdefault('hard_requirements', []).append(dict(
                requirement_id='restriction_order:'+group_id,
                origin=origin, condition=False))


def functional_asset_version(catalog):
    from .effect_mechanisms import SEMANTIC_VERSION
    from .effect_records import EFFECT_RECORD_VERSION, LUA_EFFECT_RECORD_VERSION
    from .effect_blocks import BLOCK_VERSION, BLOCK_REVISION, LUA_BLOCK_REVISION
    binding = dict(cards=catalog.cards_sha256, semantic=SEMANTIC_VERSION,
                   records=EFFECT_RECORD_VERSION, blocks=BLOCK_VERSION, revision=BLOCK_REVISION)
    lua = catalog.lua_binding
    if lua is not None:
        binding.update(lua=lua, records=LUA_EFFECT_RECORD_VERSION, revision=LUA_BLOCK_REVISION)
    if getattr(catalog.assets, "period_context", None) is not None:
        from .construction_native import NATIVE_RULE_VERSION
        binding["native_rules"] = NATIVE_RULE_VERSION
    return digest(binding)


def reference_asset_binding(catalog, deck):
    assets = catalog.assets
    rows = {str(code): assets.rows.get(code) for code in sorted(set(deck.main + deck.extra + deck.side))}
    aliases = {row.get("alias") or row["id"] for row in rows.values() if row is not None}
    return digest(dict(asset_version=functional_asset_version(catalog), rows=rows,
        limits={str(code): assets.limits.get(code, 3) for code in sorted(aliases)},
        resources=assets.receipt, period=getattr(assets, "period_context", None)))


def _support_group(operator, items):
    """Keep every condition within the existing per-group contract limit."""
    identity=operator=='all'
    if any(v is not identity and type(v) is bool for v in items):
        return not identity
    items=[v for v in items if v is not identity]
    if not items:return identity
    while len(items)>128:
        items=[{operator:items[i:i+128]} for i in range(0,len(items),128)]
    return items[0] if len(items)==1 else {operator:items}


def _all_support(items):
    """Do not keep unrelated unknowns under an already impossible condition."""
    return _support_group('all',items)


def _relation_support(row, key, scope, condition, evidence):
    if row.get("status") == "supported":
        return True
    if row.get("status") == "missing":
        return False
    expression=row.get('support_expression',('unresolved',()))
    def complete(value):
        return value[0]=='atom' or value[0] in ('all','any') and all(complete(v) for v in value[1])
    branches=row.get('branches',())
    if (expression[0]=='unresolved' and branches and not row.get('branches_incomplete')
            and all(complete(b['support_expression']) for b in branches)):
        # The allocator already retained every complete alternative. Reuse
        # their conditions directly when the short summary was truncated.
        expression=('any',tuple(b['support_expression'] for b in branches))
    def convert(expression):
        operator, children = expression
        if operator == "atom":
            if children.startswith('fact:catalog-text:') and not children.endswith(':turn_event_unobserved'):
                # The printed clause has one interpretation for this asset
                # version. Its unresolved application to the current resource
                # projection cannot be inferred from the other inventory.
                rule = condition('relation:' + children, None, children, evidence)
                application = condition(f'relation:applicability:{scope}:{children}', None,
                                        'catalog_clause_applicability', evidence)
                return _all_support([rule, application])
            return condition(f'relation:{scope}:{children}', None, children, evidence)
        if operator in ("all", "any"):
            return _support_group(operator,[convert(v) for v in children])
        reason='relation_expression_budget' if operator=='unresolved' else 'effect_support_and_access'
        return condition(key+":execution:"+scope,None,reason,evidence)
    return convert(expression)


def _special_summon_supported(code, available, records, dependencies, relation, operation_facts, *, physical_inventory):
    """Read configured entry proofs from the existing relation result."""
    from .construction_inventory import _activation_target, _has_self_grave_payment, matches
    possible = False
    special = {'special_summon','fusion_summon','synchro_summon','xyz_summon','link_summon','ritual_summon'}
    for supplier, entries in records.items():
        for ri, record in enumerate(entries):
            for oi, operation in _record_outputs(record):
                if (operation is None or operation['kind'] not in special or operation.get('random')
                        or operation.get('generation')):
                    continue
                req = dependencies.item_requirement(operation,'operations')
                if not req or req['owner']!='self' or not matches(dependencies.rows[code],req['query']):
                    continue
                state = relation['uses'].get(operation_facts.get((supplier,ri,oi)), {})
                status = state.get('status')
                if status in ('supported', 'unknown') and operation.get('simultaneous_group'):
                    proof = dependencies.simultaneous_processing(available, operation_record(record, operation),
                        operation, card_id=code)
                    if proof is not None:
                        if proof['status'] == 'missing':
                            continue
                        if proof['status'] == 'unknown':
                            status = 'unknown'
                activation_target = _activation_target(record, operation)
                if (status in ('supported', 'unknown') and (
                        record.get('type_matched_deck_send', {}).get('revival') == operation['block_id']
                        or activation_target and (activation_target.get('availability_timing') == 'before_activation_payment'
                                                  or _has_self_grave_payment(record)))):
                    legal = dependencies.summon_choice_check(available, operation_record(record, operation), operation,
                                                             (code,), physical_inventory=physical_inventory)
                    if legal is False:
                        continue
                    if legal is None:
                        status = 'unknown'
                if status == 'supported':
                    return True
                possible |= status == 'unknown'
    if code in available.extra:
        checked = dependencies.summon_material_check(available, code)
        if checked:
            if checked['status']=='inventory_present':return True
            possible |= checked['status']=='unknown'
    return None if possible else False


def _function_semantics(record, operation):
    """Identity is an observed operation, never a graph node or proof count."""
    from .construction_inventory import selector
    block = next((b for b in record.get("block_view", {}).get("blocks", ())
                  if b["block_id"] == operation.get("block_id")), {})
    kind = block.get("kind", operation["kind"])
    origins = sorted(set(operation.get("from_zones", ())))
    if kind in ("search", "recover", "add_hand", "search_or_recover"):
        kind = "search" if origins == ["deck"] else "recover" if origins in (["grave"], ["banished"]) else "add_hand"
    if kind == "mill":
        kind = "send_grave"
    # Quantities and timing describe a use of a function; splitting them does
    # not create another first-copy benefit. Keep other observed result fields.
    ignored = {"kind", "source", "block_id", "effect_key", "order", "depends_on", "choice",
               "phase", "quantity", "quantity_status", "quantity_options", "quantity_binding", "count", "from_zones", "selector",
               "selector_query", "selector_source", "reason", "owner", "to_zone", "random", "observed_operation",
               "selection_group", "simultaneous_group", "outcome_requirement", "different_name_from_cost",
               "different_name_from_reveal", "subject_ref", "state_conditions"}
    query = operation.get("selector_query")
    if query is None and operation.get("selector"):
        query = selector(operation["selector"])
    if query is not None:
        query = {k: v for k, v in query.items() if k != "selector"}
    return dict(kind=kind, from_zones=origins, to_zone=operation.get("to_zone"),
        owner=operation.get("owner"), reason=operation.get("reason"),
        selection="random" if operation.get("random") is True else "targeted" if operation.get("random") is False else None,
        selector=query, unresolved_selector=operation.get("selector") if query is None else None,
        result={k: deepcopy(v) for k, v in operation.items() if k not in ignored})


def normalize_function_uses(task, deck, catalog, *, policy, budget=None, context=None,
                            layer_evaluation=None, quality_evidence=None,
                            continuation=None, should_stop=None, work_state=None, reuse=None):
    """Project each candidate's complete inventory into the functional contract.

    The catalog observes effects; this adapter checks their configuration
    resources and relationships, and the quality module alone prices them.
    It neither requests a current duel state nor asserts particular random hits.
    """
    from .construction_inventory import InventoryDependencies
    from .construction_quality import (FUNCTIONAL_SCOPE, FunctionalUse, UseImpact,
        functional_quality_config, physical_sources)
    from .effect_mechanisms import EXTRA_TYPES
    config = functional_quality_config(policy.get("quality"))
    profile = config.get('theme_profile')
    if profile and (profile['task_sha256'] != task.sha256 or profile.get('card_texts') and (
            profile.get('cards_sha256') != catalog.cards_sha256
            or any(int(c) not in task.pool or int(c) not in catalog.assets.rows
                or catalog.card(int(c)).text_sha256 != text for c, text in profile['card_texts'].items()))):
        raise ContractError('automatic theme profile needs host rederivation for this task/catalog')
    budget = budget or RelationBudget()
    inventory = deck.to_dict()
    if layer_evaluation is not None and (layer_evaluation["axis"]["inventory"] != inventory
            or digest(layer_evaluation["axis"]["task"]) != task.sha256):
        raise ContractError("normalization layers belong to another candidate/task")
    codes = sorted(set(deck.main + deck.extra + deck.side))
    if any(c not in catalog.assets.rows for c in codes):
        raise ContractError("candidate card is absent from its bound catalog")
    aliases = {str(c): catalog.assets.rows[c].get("alias") or c for c in codes}
    extra_ids = [c for c in codes if catalog.assets.rows[c]["type"] & EXTRA_TYPES]
    sources = physical_sources(inventory, aliases, extra_ids)
    coverage = {f"{z}:{c}": "deferred" for z, cards in inventory.items() for c in cards}
    facts = dict(version="construction-quality-facts-v1", normalization_version=NORMALIZATION_VERSION,
        task_sha256=task.sha256, deck_sha256=digest(inventory),
        asset_version=functional_asset_version(catalog),
        uses=[], impacts=[], variables={}, constraints=[], coverage=coverage,
        scope_status={k: "evaluated" for k in FUNCTIONAL_SCOPE},
        source_aliases=aliases, extra_card_ids=extra_ids, unpriced_effects=[],
        coverage_details={}, use_details={}, fact_details={}, hard_requirements=[])
    facts['inventory']=inventory
    facts['card_properties']={str(c):{key:catalog.assets.rows[c].get(key,0) for key in
        ('id','name','type','level','race','attribute','atk','def','setcode')} for c in codes}
    relation_binding=asdict(context.relations) if context is not None else None
    if relation_binding is not None:relation_binding.pop('budget',None)
    binding=digest(dict(task=task.sha256,inventory=inventory,policy=policy,
        assets=facts['asset_version'],normalization=NORMALIZATION_VERSION,
        relations=relation_binding,evidence=None if callable(quality_evidence) else quality_evidence,
        logic=layer_evaluation['axis'].get('logic') if layer_evaluation is not None else None))
    if continuation is not None and (continuation.get('version')!='functional-normalization-work-v1'
            or continuation.get('binding')!=binding):
        raise ContractError('normalization continuation belongs to different inputs')
    work=deepcopy(continuation or dict(version='functional-normalization-work-v1',binding=binding,
        asset_version=facts['asset_version'],normalization_version=NORMALIZATION_VERSION,
        read_cursor=0,specifications={},projections={},active=None))
    if work_state is not None:
        work_state.clear();work_state.update(work)
    dependencies = InventoryDependencies(catalog, requirement_limit=budget.facts)
    dependencies._specifications={int(c):tuple(value) for c,value in work['specifications'].items()}
    if reuse is not None and reuse.get('asset_version') != facts['asset_version']:
        for cache in ('specifications', 'projections', 'family_prices'):
            reuse[cache].clear()
        reuse['asset_version'] = facts['asset_version']
    shared_specs = reuse['specifications'] if reuse is not None else None
    records, specs, remaining = {}, {}, budget.facts
    count=0
    while work['read_cursor']<len(codes):
        if remaining<=0 or count>=budget.cards or should_stop is not None and should_stop():
            facts['calculation_pending']=work
            return facts
        code=codes[work['read_cursor']]
        cached = shared_specs.get(code) if shared_specs is not None else None
        if cached is not None and cached[0] == catalog.assets.rows[code]:
            effect_specs, materials = cached[1]
        else:
            effect_specs, materials = dependencies.specs(code)
            if shared_specs is not None:
                shared_specs[code] = (dict(catalog.assets.rows[code]), (effect_specs, materials))
        remaining-=max(1,sum(1+len(e['record']['operations'])+len(e['requirements'])+len(e['unknown'])
            for e in effect_specs)+len(materials))
        work['specifications'][str(code)]=[effect_specs,materials]
        work['read_cursor']+=1;count+=1
    specs={int(c):tuple(value) for c,value in work['specifications'].items()}
    records={code:tuple(e['record'] for e in value[0]) for code,value in specs.items()}
    dependencies._specifications=specs
    native_rules = getattr(catalog.assets, "construction_rules", None)
    if native_rules is not None:
        if "native_rule_evidence" not in work:
            role = ("reference" if layer_evaluation is not None and layer_evaluation["axis"].get("logic") is None
                    else "candidate")
            native = native_rules.evaluate(task, deck, records, role=role, should_stop=should_stop)
            if native["status"] == "paused":
                facts["calculation_pending"] = work
                return facts
            work["native_rule_evidence"] = native
        facts["native_rule_evidence"] = work["native_rule_evidence"]
        for evidence in facts["native_rule_evidence"]["receipts"]:
            identity = evidence["identity"]
            if identity.get("status") == "bound":
                key = (evidence["query"]["card"], identity["effect_key"], identity["block"])
                dependencies.native_witnesses.setdefault(key, []).append(evidence)

    def condition(key, value, reason, evidence):
        # Comparisons verify the task and asset versions before joining this
        # namespace. Applicability, stock and history use deck-bound keys.
        if not key.startswith('relation:fact:catalog-text:'):
            key += ":candidate:" + facts["deck_sha256"]
        previous = facts["variables"].setdefault(key, value)
        if previous != value:
            raise ContractError("normalization has conflicting facts: " + key)
        facts["fact_details"][key] = dict(reason_code=reason, evidence_refs=list(evidence))
        return key if value is None else value

    from types import SimpleNamespace
    # These are resource views, never claimed to be legal exchanged DeckParts.
    available = {"resident": SimpleNamespace(main=deck.main, extra=deck.extra)}
    selected = {"resident": {s for s, item in sources.items() if item["zone"] != "side"}}
    facts["side_contexts"] = {}
    if deck.side and "side" in config["required_scope"]:
        for direction in config["side_directions"]:
            allowed = {s for s, item in sources.items() if item["zone"] != "side"
                       or task.sizes[item["destination"]] > 0}
            inbound = Counter(sources[s]["destination"] for s in allowed if sources[s]["zone"] == "side")
            over = [z for z in ("main", "extra") if inbound[z] > task.sizes[z]]
            names = Counter(str(sources[s]["name_key"]) for s in allowed)
            if any(n > 3 for n in names.values()):
                raise ContractError("direction projection exceeds same-name physical limit")
            selected[direction] = allowed
            available[direction] = SimpleNamespace(**{z: tuple(sources[s]["card_id"] for s in sorted(allowed)
                if sources[s]["destination"] == z) for z in ("main", "extra")})
            facts["side_contexts"][direction] = dict(origin="side", source_ids=sorted(allowed),
                inbound=dict(inbound), capacity={z: task.sizes[z] for z in ("main", "extra")},
                status="evaluated", gaps=[],
                alternatives_require_subsets=bool(over),
                excluded_source_ids=sorted(set(sources)-allowed), main_size=len(deck.main))
    projections={}
    for scope,view in available.items():
        saved=work['projections'].get(scope)
        if saved is None:
            identical=next((other for other in projections if available[other].main==view.main
                            and available[other].extra==view.extra),None)
            if identical is not None:
                # Relation calculation has no direction argument. The caller
                # still binds this read-only result to its own scope below.
                saved=work['projections'][identical]
                work['projections'][scope]=saved
                if (work.get('active') or {}).get('scope')==scope:work['active']=None
        if saved is not None:
            projections[scope]=(saved['relation'],{tuple(key):value for key,value in saved['operation_facts']})
            continue
        active=work.get('active')
        relation,operation_facts=_functional_relations(deck,view,records,aliases,extra_ids,context,budget,
            dependencies,config,continuation=active['work'] if active and active['scope']==scope else None,
            should_stop=should_stop, previous_projections=reuse['projections'] if reuse is not None else None,
            projection='resident' if scope == 'resident' else 'side')
        if relation.get('calculation_pending'):
            work['active']=dict(scope=scope,work=relation['calculation_pending'])
            facts['calculation_pending']=work
            return facts
        projections[scope]=(relation,operation_facts)
        work['projections'][scope]=dict(relation=relation,
            operation_facts=[[list(key),value] for key,value in operation_facts.items()])
        work['active']=None
    relation, operation_facts = projections["resident"]
    for use in context.relations.uses if context is not None else ():
        if use.required:
            row = relation["uses"][use.use_id]
            # A complete joint witness includes every original requirement.
            # Its global return schedule can discharge a subgroup's resource
            # unknown without changing that subgroup's standalone assessment.
            if row["status"] == "unknown" and relation["joint_required"]["status"] == "supported":
                row = relation["joint_required"]
            expr = _relation_support(row, "required:"+use.use_id, "resident", condition, (use.source,))
            facts["hard_requirements"].append(dict(requirement_id=use.use_id, origin=use.source, condition=expr))
    if any(u.required for u in (context.relations.uses if context is not None else ())):
        expr = _relation_support(relation["joint_required"], "required:joint", "resident", condition,
                                 ("original-task:" + task.sha256,))
        facts["hard_requirements"].append(dict(requirement_id="joint_required", origin="original-task:" + task.sha256, condition=expr))
    if task.goal["kind"] != "deck_constraints" or "route_goal" in task.goal:
        route = task.goal.get("route_goal", task.goal)
        opening = Counter(route["starting_conditions"]["requires_opening_hand"])
        required = {route["card_id"], *task.goal.get("required_activations", ()),
                    *task.goal.get("required_chain_resolutions", ())}
        missing = bool(opening - Counter(deck.main)) or not required <= set(deck.main + deck.extra)
        support = False if missing else None
        if not missing and route['kind'] in ('link_summon', 'ritual_summon', 'effect_resolution'):
            from .basic_cb_inference import static_route_support
            support = static_route_support(route, deck, catalog,
                required_effects=(*task.goal.get('required_activations', ()), *task.goal.get('required_chain_resolutions', ())))
        expr = condition("required:original_goal", support,
            "original_goal_static_support", ("original-task:" + task.sha256,))
        facts["hard_requirements"].append(dict(requirement_id="original_goal", origin="original-task:" + task.sha256, condition=expr))

    special_entries = {}
    for zone, cards in inventory.items():
        for code in sorted(set(cards)):
            card_key = f"{zone}:{code}"
            if code not in records:
                facts["coverage_details"][card_key] = dict(status="deferred", reason="normalization_read_budget")
                continue
            effect_specs, materials = specs[code]
            effect_details = []
            for ri, record in enumerate(records[code]):
                eid = "effect:" + digest(dict(card=aliases[str(code)], text=record["text_sha256"],
                    scope=record.get("scope"), position=record.get("effect_key", str(ri))))
                ref = f"catalog:{code}:{record.get('effect_key', ri)}:{record['text_sha256']}"
                view = record.get("block_view", {})
                empty_reviewed = view.get("status") in ("flavor", "summon_description", "summon_procedure", "restriction", "cost_only")
                covered = bool(record["operations"]) or empty_reviewed
                # A coarse action does not acknowledge unrelated unparsed text.
                semantic_gaps = [u for u in view.get("unknown", record.get("unknown", ()))
                                 if u in ("no_recognized_function", "unrecognized_operation", "effect_boundary_unknown")]
                if not covered and not semantic_gaps:
                    semantic_gaps = list(record.get("unknown") or ("no_recognized_function",))
                effect_details.append(dict(effect_id=eid, effect_ref=ref, status="evaluated" if covered and not semantic_gaps else "unknown",
                    record=deepcopy(record), gaps=semantic_gaps))
                deferred_draws = (op for op in record["operations"]
                    if op.get("phase") == "delayed" and op["kind"] == "draw" and op.get("owner") == "opponent")
                for burden in (*record.get("costs", ()), *record.get("non_activation_costs", ()), *deferred_draws):
                    facts["unpriced_effects"].append(dict(effect_id=eid, source_id=card_key,
                        kind="unpriced_effect", resource=deepcopy(burden), evidence_refs=[ref]))
                for oi, operation in _record_outputs(record):
                    observed = operation if operation is not None else {"kind": "effect_adoption"}
                    semantics = _function_semantics(record, observed)
                    family = "function:" + digest(semantics) if operation is not None else "adoption:" + eid
                    # A processing step such as reveal/shuffle does not become a
                    # second search benefit when it only completes that search.
                    if semantics["kind"] in ("inspect", "reveal", "shuffle"):
                        searches = [other for other in record["operations"] if _function_semantics(record, other)["kind"] == "search"]
                        if searches and not operation.get('independent_function'):
                            if not any(other.get('source') == operation.get('source') for other in searches):
                                effect_details[-1]['status'] = 'unknown'
                                effect_details[-1]['gaps'].append('processing_function_role_unresolved')
                            continue
                    uid = "use:" + digest(dict(effect=eid, function=family, zone=zone, card_id=code,
                        processing_position=(ri,oi), quantity=observed.get("quantity"),
                        choice=observed.get("choice", "configuration")))
                    refs = (ref,)
                    requirement_rows = [r for r in effect_specs[ri]["requirements"]
                        if ("operation" not in r or r["operation"] == operation)
                        and r.get('choice') in (None, (operation or {}).get('choice'))]
                    scoped_record = operation_record(record, operation)
                    prerequisites = [op for op in scoped_record["operations"]
                        if op["block_id"] in observed.get("depends_on", ())
                        and op.get("processing_role") == "auxiliary"]
                    costs = [r for r in requirement_rows if r["category"] == "costs"]
                    other = [r for r in requirement_rows if r["category"] != "costs"]
                    source_ids = tuple(s for s, item in sources.items() if item["zone"] == zone and item["card_id"] == code)
                    for scope, view in available.items():
                        if scope == "resident" and zone == "side":
                            continue
                        key = uid if scope == "resident" else uid + ":" + scope
                        checked = dependencies._check(view, costs, distinct=True) if costs else None
                        native = (dependencies.witnessed_processing(view, scoped_record, operation, inventory=deck)
                                  if scope == "resident" else None)
                        summon_trigger = dependencies.summon_trigger_check(code, scoped_record)
                        objects = dependencies._check(view, other)
                        material = dependencies.summon_material_check(view, code)
                        fusion=dependencies.fusion_check(view,code,scoped_record)
                        processing=dependencies.processing_check(view,scoped_record,operation,physical_inventory=deck)
                        complete_payment = dependencies.summon_material_check(view, code, costs=costs) if costs and material else None
                        if complete_payment and complete_payment["status"] == "missing" and checked["status"] != "missing" and material["status"] != "missing":
                            complete_payment["status"] = "unknown"
                            complete_payment["reason"] = "cost_material_transfer_order"
                        absent = any(r and r["status"] == "missing" for r in (checked, objects, material, summon_trigger, fusion, processing))
                        own = condition(key + ":inventory", not absent and set(source_ids) <= selected[scope],
                                        "complete_inventory_requirement", refs)
                        current_relation, operation_facts = projections[scope]
                        if (scope,code) not in special_entries:
                            special_entries[scope,code]=_special_summon_supported(code,view,records,
                                dependencies,current_relation,operation_facts,physical_inventory=deck)
                        state = current_relation["uses"].get(operation_facts.get((code, ri, oi)), {})
                        support = _relation_support(state, key, scope, condition, refs)
                        # The relation already binds unresolved inventory selectors to their source.
                        transfer = condition(key+":cost_material_transfer", None if complete_payment and complete_payment["status"] == "unknown" else True,
                                             "cost_material_transfer_order", refs)
                        self_condition = _all_support([own, support, transfer])
                        if processing and processing['status'] == 'unknown':
                            self_condition = _all_support([self_condition,
                                condition(key+':processing', None, processing['reason'], refs)])
                        themes, unknown_theme_predicates = [], []
                        for rule in config["theme_rules"] if operation is not None else ():
                            if 'task_goal' in rule['predicate']:
                                continue
                            fields = dict(kind=semantics["kind"], from_zone=semantics["from_zones"][0] if len(semantics["from_zones"]) == 1 else None,
                                to_zone=semantics["to_zone"], owner=semantics["owner"], reason=semantics["reason"],
                                grave_related="grave" in semantics["from_zones"] or semantics["to_zone"] == "grave" or record["trigger"].get("zone") == "grave")
                            matched = [None if fields[k] is None else fields[k] in v if isinstance(v, list) else fields[k] == v
                                       for k, v in rule["predicate"].items()]
                            if False in matched:
                                continue
                            if None in matched:
                                unknown_theme_predicates.append(rule["rule_id"])
                            theme = condition(key + ":theme:" + rule["rule_id"], None,
                                              "theme_predicate_and_static_support", refs)
                            themes.append((rule["rule_id"], theme))
                        use = FunctionalUse(key, eid, family, family, source_ids,
                            "called" if code in extra_ids else "main_density", refs, self_condition,
                            scope_id=scope, theme_conditions=tuple(themes), theme_eligible=tuple(k for k, _ in themes),
                            contributes=operation is not None)
                        prior = next((u for u in facts["uses"] if u.use_id == key), None)
                        if prior is None:
                            facts["uses"].append(use)
                        elif prior != use:
                            raise ContractError(f"conflicting function support for card {code}, effect {ri}, processing {oi}")
                        facts["use_details"][key] = dict(effect_id=eid, function_id=family, card_id=code,
                            relation_fact_id=(operation_facts.get((code, ri, oi)) or '').removeprefix('functional:'),
                            semantics=semantics, operation=deepcopy(operation), trigger=deepcopy(scoped_record["trigger"]),
                            special_summon_supported=special_entries[scope,code],
                            applicability="this_card_in_monster_zone" if _record_applicability(record) else None,
                            costs=deepcopy(scoped_record["costs"]), materials=deepcopy(record["printed_materials"]),
                            activation_state_conditions=deepcopy(scoped_record.get('activation_state_conditions', ())),
                            count_limits=deepcopy(record["count_limits"]),
                            restrictions=deepcopy([*record["card_restrictions"], *record["restrictions"]]),
                            unknown_theme_predicates=unknown_theme_predicates,
                            self_reason_codes=[name for name, value in (("inventory",own),("execution",support)) if value is False],
                            inventory_checks=dict(costs=checked, objects=objects, materials=material,
                                complete_payment=complete_payment, summon_trigger=summon_trigger, fusion=fusion,
                                processing=processing), relation=state)
                        if prerequisites:
                            facts["use_details"][key]["processing_prerequisites"] = deepcopy(prerequisites)
                        if native is not None:
                            facts["use_details"][key]["inventory_checks"]["native"] = deepcopy(native)
                        from .construction_theme import function_goal, primary_goal
                        facts['use_details'][key].update(operation_key=(code, ri, oi),
                            goal_id=digest(function_goal(record, operation)) if operation is not None else None)
                        if operation is not None and operation['kind'] in _SPECIAL_SUMMONS:
                            facts['use_details'][key]['summoned_card_ids'] = _summoned_inventory(
                                scoped_record, operation, objects, fusion)
                        if config.get('theme_profile'):
                            facts['use_details'][key]['explicit_task_goal'] = primary_goal(
                                config['theme_profile'],code,record,operation,dependencies)
            coverage[card_key] = "evaluated" if all(e["status"] == "evaluated" for e in effect_details) else "unknown"
            facts["coverage_details"][card_key] = dict(status=coverage[card_key], effects=effect_details)
    if "side" not in config["required_scope"]:
        facts["scope_status"]["side"] = "not_applicable"
    elif deck.side and any(coverage.get(f"side:{code}") != "evaluated" for code in deck.side):
        facts["scope_status"]["side"] = "deferred"
    _bind_functional_support(facts, projections, available, specs, catalog, context, condition, config, sources)
    _bind_automatic_themes(facts, projections, config, condition, sources)
    @lru_cache(maxsize=None)
    def check_summon_choice(operation_key, allowed):
        code, ri, oi = operation_key
        record = records[code][ri]
        operation = record['operations'][oi]
        scoped = operation_record(record, operation)
        resident = available['resident']
        if operation['kind'] == 'fusion_summon':
            fusion = dependencies.fusion_check(resident, code, scoped)
            if fusion is not None:
                if any(option['target'] in allowed for option in fusion['options']):
                    return True
                return None if set(allowed) & set(fusion['uncovered_targets']) else False
        return dependencies.summon_choice_check(resident, scoped, operation, allowed, physical_inventory=deck)

    resident_cards = set(deck.main + deck.extra)
    def summon_choice(scope, source_code, detail, allowed):
        if scope == 'resident':
            return check_summon_choice(detail['operation_key'], allowed)
        # An assignment in the original deck already fits the Side limits.
        # A shortage there says nothing about the added Side resources.
        if {source_code, detail['card_id']} <= resident_cards:
            resident_allowed = tuple(code for code in allowed if code in resident_cards)
            if resident_allowed and check_summon_choice(detail['operation_key'], resident_allowed) is True:
                return True
        return None

    _bind_mandatory_impacts(facts, context, condition, summon_choice=summon_choice)
    if work_state is not None:
        work_state.clear();work_state.update(work)
    facts.pop('inventory')
    facts.pop('card_properties')
    if quality_evidence is not None:
        supplement = quality_evidence(task, deck, layer_evaluation) if callable(quality_evidence) else quality_evidence
        _merge_function_evidence(facts, supplement)
    return facts


def _merge_function_evidence(facts, supplement):
    """A sourced host supplement can resolve unknowns, never replace bad facts."""
    from .construction_quality import FunctionalUse, UseImpact
    if not isinstance(supplement, dict):
        raise ContractError("functional evidence provider must return a mapping")
    for key in ("losses", "slot_uses", "generic_fits", "duplicate_purposes", "side_deck"):
        if supplement.get(key):
            label = "loss" if key == "losses" else key.rstrip("s")
            raise ContractError("legacy_" + label + "_requires_semantic_rebind")
    if not supplement:
        return
    binding = {k: facts[k] for k in ("version", "task_sha256", "deck_sha256", "asset_version")}
    if any(supplement.get(k) != v for k, v in binding.items()) or not supplement.get("source") or not supplement.get("evidence_refs"):
        raise ContractError("functional supplement requires candidate/asset binding and sourced evidence")
    allowed = set(binding) | {"source", "evidence_refs", "variables", "uses", "impacts", "constraints", "coverage", "scope_status"}
    if set(supplement) - allowed:
        raise ContractError("functional supplement contains unsupported fields")
    for key, value in supplement.get("variables", {}).items():
        if key in facts["variables"] and facts["variables"][key] is not None and facts["variables"][key] != value:
            raise ContractError("host fact conflicts with observed fact: " + key)
        facts["variables"][key] = value
        facts["fact_details"].setdefault(key, {}).update(host_source=supplement["source"], evidence_refs=list(supplement["evidence_refs"]))
    for field, kind, identity in (("uses", FunctionalUse, "use_id"), ("impacts", UseImpact, "impact_id")):
        for row in supplement.get(field, ()):
            if not isinstance(row, kind):
                raise ContractError("functional supplement requires typed " + field)
            prior = next((v for v in facts[field] if getattr(v, identity) == getattr(row, identity)), None)
            if prior is not None and prior != row:
                raise ContractError("host supplement conflicts with observed " + field)
            if prior is None:
                facts[field].append(row)
    facts["constraints"].extend(deepcopy(supplement.get("constraints", ())))
    for field in ("coverage", "scope_status"):
        for key, value in supplement.get(field, {}).items():
            if key not in facts[field]:
                raise ContractError("host coverage is outside this candidate/scope")
            facts[field][key] = value


class ConstructionLayerAdapter:
    def __init__(self, binding_adapter, *, context_provider=None, budget=None):
        from .construction_binding import CatalogBindingAdapter
        if not isinstance(binding_adapter, CatalogBindingAdapter):
            raise ContractError("layers require the source-bound catalog binding adapter")
        if context_provider is not None and not callable(context_provider):
            raise ContractError("host layer context provider must be callable")
        self.binding = binding_adapter
        self.catalog = binding_adapter.semantic_catalog
        self.context_provider = context_provider
        self.budget = budget if budget is not None else RelationBudget()
        self._prepared_reference = None
        if not isinstance(self.budget, RelationBudget):
            raise ContractError("typed layer flow budget required")

    def context(self, task, graph):
        """Resolve host purposes before any new candidate binding/catalog reads."""
        if self.context_provider is None:
            return None
        task_sha256, logic_sha256 = task.sha256, graph.sha256
        value = self.context_provider(task, graph)
        if not isinstance(value, LayerContext) or value.relations is None:
            raise ContractError("host must return LayerContext with explicit relations")
        if (value.task.sha256 != task_sha256 or value.logic.sha256 != logic_sha256
                or task.sha256 != task_sha256 or graph.sha256 != logic_sha256):
            raise ContractError("host layer context changed the original task or logic")
        return replace(value, relations=replace(value.relations, budget=RelationBudget(**{
            key: min(getattr(self.budget, key), getattr(value.relations.budget, key))
            for key in self.budget.__dataclass_fields__})))

    def limit(self, task, context):
        return min(32, task.candidate_budget, self.budget.candidates,
                   context.relations.budget.candidates if context else 32)

    def _automatic_context(self, task, graph, proposals):
        from types import SimpleNamespace
        from .construction_inventory import InventoryDependencies
        codes = sorted({c for p in proposals.values() for c in p.deck.main + p.deck.extra})
        inspected = codes[:self.budget.cards]
        zones = {c: "extra" if self.binding.assets.rows[c]["type"] & 0x4802040 else "main" for c in codes}
        bound = defaultdict(set)
        for proposal in proposals.values():
            for binding in proposal.bindings:
                bound[binding.node_id].update(binding.card_ids)
        names = defaultdict(list)
        for code in task.pool:
            names[self.binding.assets.rows[code].get("alias") or code].append(code)
        groups = tuple(tuple(v) for v in names.values() if len(v) > 1)
        requirements, roles, uses, facts, pools = [], [], [], [], {}
        fact_ids = set()
        def add_fact(fact):
            # One overflow item lets relation_index report truncation. Do not
            # build an unbounded proxy graph before applying its fact budget.
            if fact.fact_id not in fact_ids and len(facts) <= self.budget.facts:
                facts.append(fact)
                fact_ids.add(fact.fact_id)
        source = "selected-logic:" + graph.sha256
        # The catalog's existing parser is the sole effect observer here.
        from .construction_inventory import qualified_effect_node
        observed, static_records, operation_facts, effect_facts = {}, {}, {}, {}
        dependencies=InventoryDependencies(self.catalog)
        view=SimpleNamespace(**{z:tuple(c for c in codes if zones[c]==z) for z in ('main','extra')})
        members=tuple((zones[c],c) for c in codes)
        remaining = self.budget.facts
        for code in inspected:
            if remaining == 0:
                break
            specs,_=dependencies.specs(code)
            static_records[code]=[spec['record'] for spec in specs]
            observed[code] = list(islice(_record_facts(code, static_records[code], zone=zones[code],
                same_name=self.binding.assets.rows[code].get("alias") or code,
                inventory=members,dependencies=dependencies,controller='self',static=True), remaining))
            remaining -= len(observed[code])
            positions=[(ri,oi) for ri,record in enumerate(static_records[code]) for oi,_ in _record_outputs(record)]
            operation_facts.update(((code,ri,oi),'functional:'+fact.fact_id)
                for (ri,oi),(fact,_) in zip(positions,observed[code]))
            effect_facts[code] = {
                (static_records[code][ri]['effect_key'], static_records[code][ri]['operations'][oi].get('block_id')): pair
                for (ri, oi), pair in zip(positions, observed[code]) if oi is not None
            }
        raw_facts=[fact for pairs in observed.values() for fact,_ in pairs]
        configured, unbound = _configuration_relations(view,static_records,dependencies,
            {str(c):self.binding.assets.rows[c].get('alias') or c for c in codes},
            operation_facts,raw_facts,pools,None)
        for fact in configured:add_fact(fact)
        inspected = set(observed)
        for node in graph.nodes:
            functional = any(t.dimension in ("effect", "effect_type", "role") for t in node.tags)
            qualified = qualified_effect_node(node)
            exact_hits, judgments = {}, {}
            for code in codes:
                if code not in inspected:
                    if code in bound[node.node_id]:
                        judgments[code] = (None, "card_read_budget_uncovered")
                    continue
                statuses = [self.binding._tag_status(self.binding.assets.rows[code], tag) for tag in node.tags
                            if not qualified or tag.dimension not in ('field', 'race', 'effect', 'effect_type')]
                if qualified:
                    exact_hits[code] = dependencies.draft_matches(code, node, records=static_records[code],
                                                                  fact_tags=self.binding.fact_tags)
                    statuses.append(('satisfied' if exact_hits[code] else 'unknown', 'qualified printed effect'))
                values = [s for s, _ in statuses]
                q = (0 if "unsatisfied" in values else None if "unknown" in values else 1 if functional else .5)
                if code in bound[node.node_id] or q in (1, .5):
                    judgments[code] = (q, "; ".join(dict.fromkeys(note for _, note in statuses)))
            module = "node:" + node.node_id
            node_zones = sorted({zones[c] for c in judgments}) or ["main"]
            # A graph made only of theme/race facts still lacks a functional
            # relation specification; empty requirements cannot certify it.
            output = Resource("flow_function", attributes=(node.node_id,))
            uses.append(UseRequirement(module, InputGroup("all", (Need(module, output, mode="presence"),)),
                source, required=node.node_id in graph.goal_nodes))
            add_fact(RelationFact(module + ":unresolved", module + ":unresolved", output, source,
                unknown=("coarse_function_execution_unresolved:" + node.node_id,)))
            if functional:
                for zone in node_zones:
                    requirements.append(FunctionRequirement(f"{module}:{zone}", zone, source,
                        (node.node_id,), (module,), required=node.node_id in graph.goal_nodes and len(node_zones) == 1,
                        mode="investment" if zone == "main" else "target"))
            for code, (q, note) in judgments.items():
                evidence = () if not functional else (FunctionEvidence(f"{module}:{zones[code]}",
                    "covered" if q == 1 else "missing" if q == 0 else "unknown", note,
                    conditions=("effect_availability_checked_separately",)),)
                roles.append(RoleAssessment(module, zones[code], code, q, note, evidence))
                if not functional or q != 1 or code not in observed:
                    continue
                if qualified:
                    for record, operation in exact_hits[code]:
                        pair = effect_facts[code].get((record['effect_key'], operation.get('block_id')))
                        if pair is None:
                            continue
                        fact, shared = pair
                        fact = _bind_unparsed_requirements(fact, unbound)
                        add_fact(replace(fact, fact_id=f"flow:{node.node_id}:{fact.fact_id}",
                                         output=output, quantity=1))
                        pools.update((p.pool_id, p) for p in shared)
                    continue
                # Only existing parser-backed tags have an effect association.
                # Explicit card/tag reviews still cover layer one; an opaque
                # association stays unknown in layer two.
                tags = {t.value for t in node.tags if t.dimension == "effect"}
                if any(t.dimension in ("effect_type", "role") for t in node.tags):
                    continue  # No effect association for these extra judgments.
                profile = self.catalog.card(code)
                for fact, shared in observed[code]:
                    matches = (tags == {"卡组送墓"} and fact.output.kind in ("mill", "send_grave")
                               and fact.output.origin == "deck" and fact.output.reason == "effect")
                    matches |= (tags == {"墓地融合"} and fact.output.kind == "fusion_summon"
                                and any(fact.effect_ref == f"catalog:{code}:{e.index}" for e in profile.grave_fusion))
                    if matches:
                        fact = _bind_unparsed_requirements(fact, unbound)
                        add_fact(replace(fact, fact_id=f"flow:{node.node_id}:{fact.fact_id}",
                            output=output, quantity=1))
                        pools.update((p.pool_id, p) for p in shared)
        # Material rules are required only for a target explicitly fixed by
        # the original task, never for every extra card in a candidate.
        target = task.goal.get("card_id")
        if task.goal["kind"] != "normal_summon" and target in inspected and self.catalog.card(target).materials:
            from .effect_mechanisms import material_matches
            uses.append(UseRequirement("task:materials", InputGroup("all", (Need("task:materials",
                Resource("material_ready", attributes=(f"target:{target}",)), mode="presence"),)),
                "original-task:" + task.sha256))
            for item in self.catalog.card(target).materials:
                for code in sorted(inspected):
                    if not material_matches(self.binding.assets.rows[code], item):
                        continue
                    pid = f"flow:physical:{code}"
                    pools[pid] = ResourcePool(pid, "candidate physical inventory", inventory=((zones[code], code),))
                    key = f"flow:material:{code}:{item['kind']}:{item['value']}"
                    add_fact(RelationFact(key, key, Resource("material", attributes=(
                        f"{item['kind']}:{item['value']}",)), "material-rule:" + self.catalog.card(target).text_sha256,
                        code, zones[code], output_pool=pid, inventory_scaled=True,
                        unknown=("material_access_and_movement_unspecified",)))
        relations = RelationContext(tuple(uses), tuple(facts), tuple(pools.values()),
            catalog_cards=tuple(codes), budget=self.budget)
        return LayerContext(task, graph, tuple(requirements), tuple(roles), groups, relations)

    def reference_inputs(self, task, graph, reference, descriptor, *, policy, quality_evidence=None,
                         completed_binding=None):
        """Check the fixed reference identity and prepare evaluation inputs on a miss."""
        from types import SimpleNamespace
        from .build_contracts import DeckParts
        from .construction_quality import FunctionalUse, UseImpact

        if (not isinstance(reference, dict)
                or reference.get('reference_id') != descriptor['reference_id']
                or reference.get('source') != descriptor['source']
                or reference.get('environment') != task.environment):
            raise ContractError('reference_identity_source_or_environment_differs')
        deck = DeckParts.from_dict(reference.get('deck'))
        inventory = deck.to_dict()
        if digest(inventory) != descriptor['deck_sha256']:
            raise ContractError('reference_inventory_differs')

        host = self.context(task, graph)
        relations, relation_binding, host_budget = None, None, None
        if host is not None:
            relations = host.relations
            required = tuple(u for u in relations.uses if u.required)
            ids = {u.use_id for u in required}
            constraints = tuple(c for c in relations.constraints if set(c.uses) <= ids)
            relations = RelationContext(required, relations.facts, relations.pools,
                constraints=constraints, budget=relations.budget)
            host_budget = relations.budget
            relation_binding = asdict(relations)
            relation_binding.pop("budget")
        layer, evidence, evidence_binding = None, None, None
        if quality_evidence is not None:
            layer = dict(axis=dict(task=task.to_dict(), inventory=inventory, logic=None))
            evidence = quality_evidence(task, deck, layer)
            if not isinstance(evidence, dict):
                raise ContractError("functional evidence provider must return a mapping")
            evidence_binding = dict(evidence)
            for key, kind in (("uses", FunctionalUse), ("impacts", UseImpact)):
                if key not in evidence:
                    continue
                if not isinstance(evidence[key], (tuple, list)) or any(
                        not isinstance(row, kind) for row in evidence[key]):
                    raise ContractError("functional supplement requires typed " + key)
                evidence_binding[key] = [asdict(row) for row in evidence[key]]
        binding = dict(version=REFERENCE_BINDING_VERSION, assets=reference_asset_binding(self.catalog, deck),
            inputs=digest(dict(task=task.sha256, reference=descriptor, policy=policy, normalization=NORMALIZATION_VERSION,
                relations=relation_binding, evidence=evidence_binding)))
        if binding == completed_binding:
            return deck, binding, None
        if self._prepared_reference is not None:
            previous_binding, previous_budget, inputs = self._prepared_reference
            if previous_binding == binding and previous_budget == host_budget:
                return deck, binding, inputs

        self.catalog.assets.validate(task, deck)
        if layer is None:
            layer = dict(axis=dict(task=task.to_dict(), inventory=inventory, logic=None))
        context = SimpleNamespace(relations=relations) if relations is not None else None
        supplement = (lambda *_, frozen=deepcopy(evidence): frozen) if evidence is not None else None
        inputs = dict(layer=layer, context=context, policy=deepcopy(policy), quality_evidence=supplement)
        self._prepared_reference = binding, host_budget, inputs
        return deck, binding, inputs

    def evaluate_inventory(self, task, deck, layer, context, *, policy, quality_evidence=None,
                           should_stop=None, calculation=None, reuse=None):
        """Complete or suspend one inventory under the common evaluation policy."""
        from .construction_quality import evaluate_functional_quality

        while True:
            work = {}
            facts = normalize_function_uses(task, deck, self.catalog, policy=policy,
                budget=self.budget, context=context, layer_evaluation=layer, quality_evidence=quality_evidence,
                continuation=calculation, should_stop=should_stop, work_state=work, reuse=reuse)
            if not facts.get('calculation_pending'):
                break
            calculation = facts['calculation_pending']
            stop = should_stop() if should_stop is not None else None
            if stop or should_stop is None or not all((self.budget.cards, self.budget.facts,
                    self.budget.matches, self.budget.updates, self.budget.allocations)):
                return None, calculation, stop or 'relation_calculation_budget'
        quality = evaluate_functional_quality(layer, policy=policy, facts=facts, should_stop=should_stop,
            continuation=work.get('quality'), resumable=True,
            family_prices=reuse['family_prices'] if reuse is not None else None)
        if quality.get('calculation_pending') or quality.get('evaluation_timed_out'):
            if quality.get('calculation_pending'):
                work['quality'] = quality['calculation_pending']
            stop = should_stop() if should_stop is not None else None
            return None, work, stop or 'quality_evaluation_budget'
        return quality, None, None

    def evaluate(self, task, graph, rows, proposals, order, context=None, *, policy=None,
                 quality_evidence=None, should_stop=None, evaluated=None, calculations=None, on_progress=None,
                 comparison_progress=None, _comparisons=None, evaluation_cursor=0):
        """Evaluate before ordering; a budget leaves pending candidates intact."""
        from .construction_quality import (FUNCTIONAL_QUALITY_VERSION, functional_quality_config,
            functional_pass_policy, EvaluationComparisons, restore_comparison_progress)
        functional = policy is not None and (policy.get("quality") or {}).get("evaluator_version") == FUNCTIONAL_QUALITY_VERSION
        if not functional:
            raise ContractError('candidate selection requires the current functional quality policy')
        functional_quality_config(policy.get("quality"))
        functional_pass_policy(policy.get("pass"))
        if any(i not in order or rows[i]["deck"] != proposal.deck for i, proposal in proposals.items()):
            raise ContractError("functional proposal inventory differs from its candidate")
        evaluation_comparisons = _comparisons or EvaluationComparisons()
        evaluations = dict(evaluated or {})
        calculations = dict(calculations or {})
        task_sha, logic_sha, policy_sha = task.sha256, graph.sha256, digest(policy)
        asset_version = functional_asset_version(self.catalog)
        for i, row in list(evaluations.items()):
            q = row.get("quality_evaluation")
            if (i not in order or q is None or q["deck_sha256"] != digest(rows[i]["deck"].to_dict())
                    or q["task_sha256"] != task_sha or q["logic_sha256"] != logic_sha
                    or q["policy_sha256"] != policy_sha):
                raise ContractError("saved candidate evaluation binding differs")
            evaluation_comparisons.bind(q)
            if (q.get('evaluation_timed_out') or q['asset_version'] != asset_version
                    or q['normalization_version'] != NORMALIZATION_VERSION
                    or any(e['record']['text_sha256'] != self.catalog.card(int(key.split(':')[1])).text_sha256
                        for key, detail in q.get('coverage_details', {}).items() for e in detail.get('effects', ()))):
                del evaluations[i]
        stop_reason = None
        evaluated_now = 0
        reuse = dict(specifications={}, projections={}, family_prices={})
        schedule = order[evaluation_cursor:] + order[:evaluation_cursor]
        next_position = 0
        for position, i in enumerate(schedule):
            next_position = position
            if i in evaluations or i not in proposals:
                continue
            if evaluated_now >= self.limit(task, context):
                stop_reason = 'candidate_evaluation_budget'
                break
            stop_reason = should_stop() if should_stop is not None else None
            if stop_reason:
                break
            # The ordinary layer adapter is reused with exactly one candidate.
            # Neither its read budget nor its inventory depends on batch peers.
            layer = self._project_layers(task, graph, proposals[i], context)
            quality, work, stop_reason = self.evaluate_inventory(task, proposals[i].deck, layer, context,
                policy=policy, quality_evidence=quality_evidence, should_stop=should_stop,
                calculation=calculations.get(i), reuse=reuse)
            if work is not None:
                calculations[i] = work
                next_position = position + 1
                break
            calculations.pop(i,None)
            status = "complete" if quality["complete"] else "deferred" if quality["deferred"] else "unknown"
            if quality["complete"] and any(r["status"] != "satisfied" for r in quality["hard_requirements"]):
                status = "hard_requirement_failed"
            evaluations[i] = dict(layer_evaluation=layer, quality_evaluation=quality, evaluation_status=status)
            evaluated_now += 1
            if on_progress is not None:
                on_progress(evaluations,calculations)
        pending = [i for i in order if i not in evaluations]
        remaining = set(pending)
        next_candidate = next((i for i in schedule[next_position:] + schedule[:next_position]
                               if i in remaining), None)
        pairs, comparisons, progress = [], {}, None
        complete = not pending
        if not pending:
            from itertools import combinations
            qualities = {i: evaluations[i]['quality_evaluation'] for i in order}
            bound_order = [[i, qualities[i]['evaluation_id']] for i in order]
            jobs = list(combinations(order, 2))
            done = []
            if comparison_progress is not None:
                saved_order, saved_pairs = restore_comparison_progress(comparison_progress)
                if saved_order == bound_order:
                    done = list(saved_pairs)
                    for (a, b), result in zip(jobs, done):
                        evaluation_comparisons.restore_pair(qualities[a], qualities[b], result)
            for a, b in jobs[len(done):]:
                stop_reason = should_stop() if should_stop is not None else None
                if stop_reason:
                    break
                done.append(evaluation_comparisons.compare(qualities[a], qualities[b]))
            complete = len(done) == len(jobs)
            if complete and should_stop is not None:
                stop_reason = should_stop()
                complete = not stop_reason
            progress = dict(version='functional-comparison-progress-v1', order=bound_order,
                            next_pair=len(done), pairs=done)
            progress['sha256'] = digest(progress)
            for (a, b), result in zip(jobs, done):
                comparisons[a, b] = result
                winner = a if result['preferred'] == 'before' else b if result['preferred'] == 'after' else None
                pairs.append(dict(before=a, after=b, preferred_index=winner, **result))
        eligible = [i for i in order if evaluations.get(i, {}).get("evaluation_status") == "complete"]
        eligible.sort(key=lambda i: -evaluations[i]["quality_evaluation"]["score"]["value"])
        selected = eligible + [i for i in order if i not in eligible]
        return selected, evaluations, dict(status="evaluated" if complete else "pending", pairs=pairs,
            comparison_cycles=[], legacy_order=list(order), evaluated_indices=sorted(evaluations),
            pending_indices=pending, evaluation_cursor=order.index(next_candidate) if next_candidate is not None else len(order),
            selection_complete=complete, stop_reason=stop_reason, comparison_progress=progress,
            calculation_progress={str(i):value for i,value in calculations.items() if i in pending},
            context_source="host" if context is not None else "per_candidate_catalog", _comparisons=comparisons)

    def _project_layers(self, task, graph, proposal, context=None):
        """Produce one candidate's axis and relation diagnostics, without ranking."""
        automatic = context is None
        context = context or self._automatic_context(task, graph, {0: proposal})
        from .construction_inventory import InventoryDependencies
        inventory = InventoryDependencies(self.catalog, requirement_limit=self.budget.facts) if automatic and self.budget.facts else None
        index = relation_index(self.catalog, context)
        # Relation inventory is the selected skeleton, not the full list.
        # Project components actually referenced by a use and its dependencies;
        # unrelated catalog observations remain outside the skeleton.
        pending = [n for use in context.relations.uses for n in _needs(use.inputs)]
        visited, components = set(), {}
        while pending:
            need = pending.pop()
            for fid in index.matches.get(need.need_id, ()):
                if fid in visited:
                    continue
                visited.add(fid)
                fact = index.facts[fid]
                if fact.card_id is not None:
                    components[fact.zone, fact.card_id] = fact.source
                for pid in ([fact.output_pool] if fact.output_pool else []) + [c.pool_id for c in fact.claims]:
                    for pair in index.pools[pid].inventory:
                        components[pair] = index.pools[pid].source
                pending.extend(_needs(fact.inputs))
        existing = {(a.zone, a.card_id) for a in context.assessments}
        component_roles = tuple(RoleAssessment("relation:components", zone, code, 1, source,
            note="explicit resource component; availability remains in relation conditions")
            for (zone, code), source in sorted(components.items()) if (zone, code) not in existing)
        context = replace(context, assessments=(*context.assessments, *component_roles))
        members = defaultdict(set)
        for role in context.assessments:
            members[role.module_id].add((role.zone, role.card_id))
        module_ids = sorted(set(members) | {m for r in context.requirements for m in r.module_ids})
        required_zones = {mid: tuple(sorted({r.zone for r in context.requirements if r.required and mid in r.module_ids}))
                          for mid in module_ids}
        deck = proposal.deck
        copies = SkeletonSpec(deck, ()).copies()
        present = {(c.zone, c.card_id) for c in copies}
        roles = tuple(a for a in context.assessments if (a.zone, a.card_id) in present)
        dependencies = (inventory.evaluate(deck, graph,
            codes=sorted({c.card_id for c in copies if c.zone != 'side'})[:self.budget.cards])
            if inventory else None)
        if dependencies is not None:
            # Direction matching (q) stays separate from the function's
            # usable investment. A known absent prerequisite cannot earn K/E.
            def project(a, e):
                states = [inventory.function_status(dependencies, a.card_id, node)
                    for req in context.requirements if req.function_id == e.function_id for node in req.node_ids]
                status = 'missing' if 'missing' in states else 'unknown' if 'unknown' in states else None
                return (replace(e, status=status, conditions=(*e.conditions,
                    'necessary_inventory_dependency_' + status)) if status and e.status != 'missing' else e)
            roles = tuple(replace(a, functions=tuple(project(a,e) for e in a.functions)) for a in roles)
        modules = tuple(AxisModule(mid, "source-bound task function", tuple(c for c in copies if
            (c.zone, c.card_id) in members[mid]), required_zones[mid])
            for mid in module_ids)
        spec = SkeletonSpec(deck, modules)
        current = replace(context, assessments=roles)
        evaluation = evaluate_layers(spec, current, self.catalog, assets=self.binding.assets, index=index)
        if dependencies is not None:
            evaluation['relations']['inventory_dependencies'] = dependencies
        return evaluation


def order_by_layers(order, incoming):
    """Stable order and cycle detection for the current quality preference graph."""
    pending, selected = list(order), []
    while pending:
        ready = next((i for i in pending if not incoming.get(i, set()).intersection(pending)), None)
        if ready is None:return selected + pending, pending
        selected.append(ready);pending.remove(ready)
    return selected, []
