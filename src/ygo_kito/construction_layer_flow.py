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
from .card_identity import rule_name_id
from .construction_layers import (
    AxisModule, FunctionEvidence, FunctionRequirement, LayerContext,
    RoleAssessment, SkeletonSpec, evaluate_layers,
)
from .construction_relations import (
    Claim, InputGroup, LP_PAYMENT_POOL, Need, RelationBudget, RelationContext, RelationFact, Resource,
    ResourcePool, ResourceTransfer, UseRequirement, relation_index,
    _needs, _record_facts, _record_outputs, _record_applicability, _leave_field_rule,
    _restriction_contract, _PLAYER_RESTRICTIONS, _INTRINSIC_RESTRICTIONS,
)
from .validation import ContractError
from .effect_records import operation_record


NORMALIZATION_VERSION = "construction-function-normalization-v72"
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
                        source = scoped['trigger'].get('lua_activation', 'printed static applicability: '+scoped['source_text'])
                        evidence = (source,) if scoped['trigger'].get('lua_activation') else ()
                        added.append(RelationFact(key, key, resource, source,
                            code, 'extra' if code in available.extra else 'main', inputs=inputs,
                            claims=(Claim(physical(code)[1]),) if hand_handler else (),
                            conditions=('static applicability: '+event, *evidence),
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
                        # The slot index distinguishes costs with identical printed text.
                        slot = need.need_id.rsplit(":", 1)[1]
                        item = scoped[category][int(slot)] if slot.isdecimal() and int(slot) < len(scoped[category]) else None
                        if item is None:
                            unbound.add(need.need_id)
                            continue
                        if item.get('resource') == 'lp' and (type(item.get('quantity')) is int or need.lp_divisor is not None):
                            pid = LP_PAYMENT_POOL
                            pools.setdefault(pid, ResourcePool(pid, 'rule: initial 8000 LP; payment leaves positive LP', capacity=7999))
                            origins = tuple(p["reference"] for p in item.get("lua_lp_payment", ()))
                            source = origins[0] if origins else 'static LP payment capacity'
                            added.append(RelationFact(key, key, resource, source, quantity=7999, output_pool=pid,
                                                     conditions=origins))
                            continue
                        req = dependencies.item_requirement(item, category)
                        if req is None:
                            unbound.add(need.need_id)
                            continue
                        lua_target = req.get('lua_target', {})
                        if req['owner'] in ('opponent', 'either') and category == 'targets':
                            # Legal input domain of the effect. The actual
                            # object and face-up state belong to the duel.
                            domain = req['owner'] + ' object range: ' + req['source']
                            source = next(iter(lua_target), 'printed ' + domain)
                            added.append(RelationFact(key, key, resource, source,
                                quantity=req['minimum'], conditions=('configuration purpose: ' + domain,)))
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
                                source = next(iter(lua_target), 'complete static selector: ' + req['source'])
                                added.append(RelationFact(key, key, resource, source,
                                    quantity=len(available.main)+len(available.extra), output_pool=pid))
                                continue
                            for target in stock:
                                section, pid = physical(target)
                                target_key = key+':'+str(target)
                                source = next(iter(lua_target), 'complete static selector: ' + req['source'])
                                added.append(RelationFact(target_key, target_key, resource, source,
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


def _settled_operation(operation, native):
    moves = native["observed_moves"]
    moved = moves[0]
    callback = native["registration"]["callbacks"]["operation"]
    source = f"{callback['file']}:{callback['lines'][0]}"
    fields = dict(kind=moved["kind"], from_zones=[moved["origin"]] if moved.get("origin") else [],
        to_zone=moved.get("destination"), owner=moved["owner"], reason="effect", source=source,
        block_id=operation["block_id"], quantity=sum(row.get("quantity", 1) for row in moves),
        phase=operation.get("phase", "resolution"))
    if moved.get("negation"):
        fields["negation"] = moved["negation"]
    if moved.get("native_call", {}).get("method") == "DiscardDeck":
        fields["random"] = True
    return fields


def _settled_operation_fact(fact, operation, native, pools):
    source = "native-receipt:" + native["receipt"]
    projection = _settled_operation(operation, native)
    claims = []
    for stock in native["stock_claims"]:
        section, code = stock["zone"], stock["card"]
        key = "configuration:physical:" + str(code)
        pools.setdefault(key, ResourcePool(key, "candidate physical copies", inventory=((section, code),)))
        claims.append(Claim(key, stock["quantity"]))
    _activation_claims(fact, native["registration"], native["rule_id"], source, pools, claims)
    paid = sum(payment["amount"] for payment in native["payments"])
    if paid:
        pools.setdefault(LP_PAYMENT_POOL, ResourcePool(LP_PAYMENT_POOL,
            "rule: initial 8000 LP; payment leaves positive LP", capacity=7999))
        claims.append(Claim(LP_PAYMENT_POOL, paid))
    moves = native["observed_moves"]
    transfer = None
    if projection["from_zones"] and projection["to_zone"]:
        members = tuple(sorted({(row["zone"], row["card"]) for row in native["stock"]
                                if row["card"] in native["observed_card_ids"]}))
        transfer = ResourceTransfer(source, moves[0]["origin"], moves[0]["destination"], moves[0]["owner"],
            "self", "random" if projection.get("random") else None, members or None, "effect")
    # This witnessed processing supplies its own activation, targets and costs.
    # Unclassified lasting effects still require their own source evidence.
    unknown = tuple(gap for gap in fact.unknown if gap.endswith((
        ":unparsed_resolution_or_restriction", "restriction_joint_scope_unresolved")))
    return replace(fact, source=source, inputs=None, claims=tuple(claims), conditions=(source,),
                   unknown=unknown, quantity=projection["quantity"], transfer=transfer)


def _activation_claims(fact, registration, local_id, source, pools, claims):
    limit = registration["count_maximum"]
    counter = registration["count_code"]
    if limit and not counter & 0x40000000:
        shared = (counter & 0x0fffffff) not in (0, 1)
        name = str(counter) if shared else local_id
        key = "native-activation-limit:" + name
        copies = () if shared else ((fact.zone, fact.card_id),)
        pools.setdefault(key, ResourcePool(key, source, capacity=limit, count_inventory=copies))
        claims.append(Claim(key))


def _aggregate_claims(claims):
    """Combine claims targeting the same pool into explicit quantities."""
    grouped = {}
    for claim in claims:
        prev = grouped.get(claim.pool_id)
        if prev is None:
            grouped[claim.pool_id] = claim
        elif prev.mode == "consume" and claim.mode == "consume":
            grouped[claim.pool_id] = Claim(claim.pool_id, prev.quantity + claim.quantity, "consume")
        elif prev.mode == "consume" or claim.mode == "consume":
            grouped[claim.pool_id] = Claim(claim.pool_id, max(prev.quantity, claim.quantity), "consume")
        else:
            grouped[claim.pool_id] = Claim(claim.pool_id, max(prev.quantity, claim.quantity), "presence")
    return tuple(grouped.values())


def _select_diverse_options(options, key_fn, limit=16):
    """Deterministically select up to `limit` options maximizing covered material codes."""
    if len(options) <= limit:
        return list(options)
    remaining = [(idx, opt, set(key_fn(opt))) for idx, opt in enumerate(options)]
    selected, covered = [], set()
    while remaining and len(selected) < limit:
        best_pos = max(
            range(len(remaining)),
            key=lambda pos: (len(remaining[pos][2] - covered), -len(remaining[pos][2]), -remaining[pos][0]),
        )
        _, opt, keys = remaining.pop(best_pos)
        selected.append(opt)
        covered |= keys
        if not any(item[2] - covered for item in remaining):
            selected.extend(item[1] for item in remaining[:limit - len(selected)])
            break
    return selected


def _summon_recipe_assignment(fact, check, facts, pools, *, kind="fusion", lp_already_charged=False,
                              ready_resource=None, dag_available=False, include_alternatives=True, rows=None):
    """Supply native Fusion or Ritual recipe alternatives to the shared allocator."""
    resource = Resource(f"{kind}_assignment", attributes=(fact.fact_id,))
    target_section = "extra" if kind == "fusion" else "main"
    grouped = defaultdict(list)
    for opt in check.get("options", ()):
        target = opt["target"]
        t_lv = ((rows or {}).get(target, {}).get("level", 0) & 255) if rows else 0
        if dag_available and rows and any(
            m.get("section") == "extra" and ((rows.get(m["card_id"], {}).get("level", 0) & 255), m["card_id"]) >= (t_lv, target)
            for m in opt.get("materials", ())
        ):
            continue
        grouped[target].append(opt)
    assigned = set()
    ordered_targets = sorted(
        grouped,
        key=lambda t: (
            min((sum(1 for m in o.get("materials", ()) if m.get("section") == "extra") for o in grouped[t]), default=0),
            ((rows or {}).get(t, {}).get("level", 0) & 255) if rows else 0,
            t,
        ),
    )
    target_res_kinds = {}
    for t_rank, target in enumerate(ordered_targets):
        ordered_opts = sorted(
            grouped[target],
            key=lambda o: (
                sum(1 for m in o.get("materials", ()) if m.get("section") == "extra"),
                len(o.get("materials", ())),
                tuple(m["card_id"] for m in o.get("materials", ())),
            ),
        )
        deduped_opts, seen_opt_keys = [], set()
        for opt in ordered_opts:
            opt_sig = (
                tuple(sorted((m.get("section"), m["card_id"], m.get("location")) for m in opt.get("materials", ()))),
                int(opt.get("lp_cost") or 0),
            )
            if opt_sig not in seen_opt_keys:
                seen_opt_keys.add(opt_sig)
                deduped_opts.append(opt)
        capped = _select_diverse_options(
            deduped_opts,
            lambda o: {m["card_id"] for m in o.get("materials", ())},
            limit=2 if kind == "ritual" else 1,
        )
        for option in capped:
            lp_cost = int(option.get("lp_cost") or 0) if not lp_already_charged else 0
            key = (
                target,
                lp_cost,
                tuple(sorted(Counter(
                    (m["section"], m["card_id"], m.get("location") if (dag_available and m.get("section") == "extra") else None)
                    for m in option.get("materials", ())
                ).items())),
            )
            if key in assigned:
                continue
            assigned.add(key)
            opt_idx = len(assigned)
            phys_counts = Counter()
            phys_counts[target_section, target] += 1
            claims, opt_needs = [], []
            fmat_slots = Counter()
            for m_idx, mat in enumerate(option.get("materials", ())):
                m_id = mat["card_id"]
                if dag_available and mat.get("section") == "extra" and mat.get("location") == 0x04:
                    slot = fmat_slots[m_id]
                    fmat_slots[m_id] += 1
                    mpool = f"native-dag:material:{m_id}:{slot}"
                    pools.setdefault(mpool, ResourcePool(mpool, "native board material slot", capacity=1))
                    claims.append(Claim(mpool, 1))
                    opt_needs.append(Need(
                        f"{fact.fact_id}:{kind}:{opt_idx}:fmat:{m_idx}",
                        Resource("field_entry", attributes=(f"card:{m_id}", f"slot:{slot}")),
                        mode="presence",
                    ))
                else:
                    phys_counts[mat["section"], m_id] += 1
            for (sec, code), count in sorted(phys_counts.items()):
                pool = "configuration:physical:" + str(code)
                pools.setdefault(pool, ResourcePool(pool, "candidate physical copies", inventory=((sec, code),)))
                claims.append(Claim(pool, count))
            if lp_cost > 0:
                pools.setdefault(LP_PAYMENT_POOL, ResourcePool(LP_PAYMENT_POOL,
                    "rule: initial 8000 LP; payment leaves positive LP", capacity=7999))
                claims.append(Claim(LP_PAYMENT_POOL, lp_cost))
            if ready_resource is not None:
                opt_needs.append(Need(f"{fact.fact_id}:{kind}:{opt_idx}:ready", ready_resource, mode="presence"))
            choice = f"{kind}:{opt_idx}"
            out_kind = f"{kind}_assignment" if (include_alternatives or t_rank == 0) else f"{kind}_target_assignment"
            target_res_kinds[target] = out_kind
            out = Resource(out_kind, attributes=(fact.fact_id, f"target:{target}"))
            facts.append(RelationFact(
                fact.fact_id + ":" + choice, fact.effect_ref, out, fact.source, fact.card_id, fact.zone,
                inputs=InputGroup("all", tuple(opt_needs)) if opt_needs else None,
                claims=_aggregate_claims(claims), choice=choice,
            ))
    if isinstance(check, dict):
        check["target_resource_kinds"] = target_res_kinds
    if not assigned:
        if check.get("status") == "unknown" or check.get("actual_duel_state_required") or check.get("uncovered_targets"):
            unk_reason = (
                ("ritual_material_search_incomplete",)
                if kind == "ritual" and check.get("uncovered_targets")
                else (f"{kind}_state_or_target_unresolved",)
            )
            facts.append(RelationFact(
                f"{fact.fact_id}:{kind}:unknown", fact.effect_ref, resource, fact.source, fact.card_id, fact.zone,
                inputs=(InputGroup("all", (Need(f"{fact.fact_id}:{kind}:unk:ready", ready_resource, mode="presence"),))
                        if ready_resource is not None else None),
                unknown=unk_reason, choice=f"{kind}:unknown",
            ))
        elif kind == "fusion":
            return fact.inputs
        return InputGroup("all", tuple(v for v in (fact.inputs, Need(fact.fact_id + ":recipe", resource, mode="presence")) if v is not None))
    if kind == "fusion" and include_alternatives:
        # The native predicate reports a witness per recipient. Additional recipes
        # for the same recipient may matter to an explicit joint requirement.
        facts.append(RelationFact(
            fact.fact_id + ":fusion:alternatives", fact.effect_ref, resource, fact.source, fact.card_id, fact.zone,
            inputs=(InputGroup("all", (Need(fact.fact_id + ":alt:ready", ready_resource, mode="presence"),))
                    if ready_resource is not None else None),
            unknown=("additional_fusion_assignments_unqueried",), choice="fusion:alternatives",
        ))
    return InputGroup("all", tuple(v for v in (fact.inputs, Need(fact.fact_id + ":recipe", resource, mode="presence")) if v is not None))


def _wire_native_summon_dag_and_gates(available, records, extra_ids, dependencies, aliases, rel_facts, rel_pools,
                                      rel_uses, operation_facts, static_facts_meta, effect_ready_facts,
                                      fusion_proofs, ritual_proofs):
    """Build Unified Field-Entry & Summon-Procedure DAG and wire downstream payoff gates."""
    from .construction_inventory import matches, query_supported

    identity = (tuple(available.main), tuple(available.extra))
    stock = dependencies.native_summon_stock.get(identity)
    if not stock:
        return
    monster_rules = stock.get("monster_rules", {})
    counts = Counter((z, c) for z in ("main", "extra") for c in getattr(available, z))
    main_set = set(available.main)
    extra_set = set(extra_ids) & set(available.extra)
    present = sorted(main_set | extra_set)

    NS_POOL = "dag:pool:normal_summon:self"
    EMPTY_OWN_MZONE_POOL = "dag:pool:empty_own_mzone:self"
    PEND_POOL = "dag:pool:pendulum_summon:self"
    EMZ_POOL = "dag:pool:extra_pend_emz:self"
    rel_pools.setdefault(NS_POOL, ResourcePool(NS_POOL, "rule: one Normal Summon or Set per turn", capacity=1))
    rel_pools.setdefault(EMPTY_OWN_MZONE_POOL, ResourcePool(EMPTY_OWN_MZONE_POOL, "empty own monster zone entry allowance", capacity=1))
    rel_pools.setdefault(PEND_POOL, ResourcePool(PEND_POOL, "rule: one Pendulum Summon per turn", capacity=1))
    rel_pools.setdefault(EMZ_POOL, ResourcePool(EMZ_POOL, "rule: one Extra Monster Zone per turn setup", capacity=1))

    def phys_pool(sec, c):
        key = f"configuration:physical:{c}"
        rel_pools.setdefault(key, ResourcePool(key, "candidate physical copies", inventory=((sec, c),)))
        return key

    def mat_pool(c, slot):
        key = f"native-dag:material:{c}:{slot}"
        rel_pools.setdefault(key, ResourcePool(key, "native board material slot", capacity=1))
        return key

    def link_arrow_pool(c, arrows):
        key = f"dag:link_arrows:{c}"
        rel_pools.setdefault(key, ResourcePool(key, f"link downward arrow zones for {c}", capacity=arrows))
        return key

    def extra_ns_pool(src, ri):
        key = f"dag:extra_ns:{src}:{ri}"
        rel_pools.setdefault(key, ResourcePool(key, "effect-granted extra normal summon allowance", capacity=1))
        return key

    dag_fids = {f.fact_id for f in rel_facts}

    def add_dag(fid, eff_ref, output, source, card_id, zone, *, inputs=None, claims=(), conditions=(),
                unknown=(), choice="joint", quantity=1):
        if fid in dag_fids:
            return
        dag_fids.add(fid)
        rel_facts.append(RelationFact(
            fid, eff_ref, output, source, card_id, zone, quantity=quantity,
            inputs=inputs, claims=_aggregate_claims(claims), conditions=conditions,
            unknown=unknown, choice=choice,
        ))

    def row_sec(c):
        return "extra" if (c in extra_set and c not in main_set) else "main"

    # Compute slot capacities per monster from multi-copy recipes
    slot_need = Counter()
    for kind_key in ("contact_fusion", "xyz", "synchro", "link"):
        for opt in stock.get(kind_key, ()):
            mc = Counter(item["card_id"] for item in opt.get("materials", ()))
            for c, n in mc.items():
                if n > slot_need[c]:
                    slot_need[c] = n
            if kind_key == "synchro":
                for c, n in Counter(item["card_id"] for item in opt.get("tuners", ())).items():
                    if n > slot_need[c]:
                        slot_need[c] = n
    for check in (*fusion_proofs.values(), *ritual_proofs.values()):
        for opt in check.get("options", ()):
            mc = Counter(m["card_id"] for m in opt.get("materials", ()) if m.get("location") == 0x04)
            for c, n in mc.items():
                if n > slot_need[c]:
                    slot_need[c] = n
    slot_cap = {
        c: max(1, min(counts[row_sec(c), c], max(1, slot_need[c])))
        for c in present if dependencies.rows.get(c, {}).get("type", 0) & 1
    }

    # Check if any Lv5+ normal summon exists, and build compact Tribute fodder facts
    tribute_summoners = []
    fodder_priority = []
    for m in sorted(main_set):
        rule = monster_rules.get(m)
        row = dependencies.rows.get(m, {})
        if not rule or not (row.get("type", 0) & 1):
            continue
        is_rit = bool(row["type"] & 0x80)
        can_ns = (not rule.get("cannot_normal_summon")) and (not rule.get("nomi_restricted")) and (not is_rit)
        lv = rule.get("level") or (row.get("level", 0) & 255) or 1
        has_flip = bool(rule.get("is_flip") or any(rec.get("trigger", {}).get("event") == "flip" for rec in records.get(m, ())))
        for slot in range(slot_cap[m]):
            if can_ns and lv <= 4:
                eff = f"dag:ns:{m}:{slot}"
                add_dag(eff, eff, Resource("field_entry", attributes=(f"card:{m}", f"slot:{slot}", "summon:normal", "proper:yes", "pre_scale:yes")),
                        "normal_summon_rule", m, "main", claims=(Claim(phys_pool("main", m), 1), Claim(NS_POOL, 1)))
                if has_flip:
                    feff = f"dag:flip:{m}:{slot}"
                    add_dag(feff, feff, Resource("flip_entry", attributes=(f"card:{m}", f"slot:{slot}")),
                            "flip_summon_rule", m, "main", claims=(Claim(phys_pool("main", m), 1), Claim(NS_POOL, 1)))
                    add_dag(f"{feff}:fe", feff, Resource("field_entry", attributes=(f"card:{m}", f"slot:{slot}", "summon:flip", "proper:yes", "pre_scale:yes")),
                            "flip_summon_rule", m, "main", claims=(Claim(phys_pool("main", m), 1), Claim(NS_POOL, 1)))
            elif can_ns and lv >= 5:
                tribute_summoners.append((m, slot, 1 if lv <= 6 else 2, has_flip))
            for proc in rule.get("inherent_ss_procs", ()):
                if proc.get("holds_empty_board") or proc.get("holds_with_opponent_monster"):
                    peff = f"dag:inh_ss:{m}:{proc['proc_index']}:{slot}"
                    attrs = [f"card:{m}", f"slot:{slot}", "summon:special", "proper:yes", "pre_scale:yes"]
                    claims = [Claim(phys_pool("main", m), 1)]
                    if proc.get("requires_empty_own_mzone"):
                        attrs.append("entry:empty_own_mzone")
                        claims.append(Claim(EMPTY_OWN_MZONE_POOL, 1))
                    add_dag(peff, peff, Resource("field_entry", attributes=tuple(attrs)),
                            "inherent_special_summon_proc", m, "main", claims=tuple(claims))
        if lv <= 4:
            if rule.get("inherent_ss_procs") or rule.get("is_pendulum"):
                fodder_priority.append((0, m))
            elif any(op.get("kind") == "special_summon" and op.get("subject") == "this_card"
                     for rec in records.get(m, ()) for op in rec.get("operations", ())):
                fodder_priority.append((0, m))
            elif can_ns:
                fodder_priority.append((1, m))

    if tribute_summoners:
        fodder_pairs = []
        for _, f in sorted(fodder_priority)[:3]:
            fodder_pairs.append((f, 0))
            if slot_cap.get(f, 1) >= 2 and len(fodder_pairs) < 3:
                fodder_pairs.append((f, 1))
        for f, f_slot in fodder_pairs[:3]:
            tfid = f"dag:tb:{f}:{f_slot}"
            sec = row_sec(f)
            add_dag(tfid, tfid, Resource("tribute_body"), "tribute_fodder", f, sec, quantity=1,
                    inputs=InputGroup("all", (Need(f"{tfid}:fe", Resource("field_entry", attributes=(f"card:{f}", f"slot:{f_slot}")), mode="presence"),)),
                    claims=(Claim(mat_pool(f, f_slot), 1),))
        for m, slot, tribs, has_flip in tribute_summoners:
            eff = f"dag:trib_ns:{m}:{slot}"
            add_dag(eff, eff,
                    Resource("field_entry", attributes=(f"card:{m}", f"slot:{slot}", "summon:normal", "summon:tribute", "proper:yes", "pre_scale:yes")),
                    "tribute_summon_rule", m, "main",
                    inputs=InputGroup("all", (Need(f"{eff}:t", Resource("tribute_body"), quantity=tribs, mode="consume"),)),
                    claims=(Claim(phys_pool("main", m), 1), Claim(NS_POOL, 1)))
            if has_flip:
                feff = f"dag:flip_t:{m}:{slot}"
                add_dag(feff, feff, Resource("flip_entry", attributes=(f"card:{m}", f"slot:{slot}")),
                        "flip_summon_rule", m, "main",
                        inputs=InputGroup("all", (Need(f"{feff}:t", Resource("tribute_body"), quantity=tribs, mode="consume"),)),
                        claims=(Claim(phys_pool("main", m), 1), Claim(NS_POOL, 1)))

    def extra_tier(cid, is_alt=False):
        if cid not in extra_set:
            return (0, 0, cid)
        if is_alt:
            return (5, monster_rules.get(cid, {}).get("rank") or 12, cid)
        row = dependencies.rows.get(cid, {})
        ctype = row.get("type", 0)
        if ctype & 0x4000000:
            lr = monster_rules.get(cid, {}).get("link_rating") or (row.get("level", 0) & 255) or 1
            return (4, lr, cid)
        if ctype & 0x800000:
            rk = monster_rules.get(cid, {}).get("rank") or (row.get("level", 0) & 255) or 1
            return (3, rk, cid)
        if ctype & 0x2000:
            lv = monster_rules.get(cid, {}).get("level") or (row.get("level", 0) & 255) or 1
            return (2, lv, cid)
        lv = monster_rules.get(cid, {}).get("level") or (row.get("level", 0) & 255) or 1
        return (1, lv, cid)

    scale_placer_cards = {
        src for src in present for rec in records.get(src, ())
        if rec.get("block_view", {}).get("status") == "native_static"
        and any(op.get("kind") == "place_pendulum_scales" for op in rec.get("operations", ()))
    }

    # Collect downward-arrow Link monsters upfront for EMZ / Linked-MMZ zone placement
    link_arrows = {}
    for lopt in stock.get("link", ()):
        tc = lopt["target"]
        arrows = max(0, int(lopt.get("downward_arrows") or 0))
        if arrows > link_arrows.get(tc, 0):
            link_arrows[tc] = arrows

    def emit_emz_or_linked_zone(base_fid, target, target_sec, slot, attrs, source, hub_res, *,
                                  allow_free_emz=True, excluded_links=()):
        if allow_free_emz:
            efid = f"{base_fid}:emz"
            add_dag(efid, efid, Resource("field_entry", attributes=(*attrs, "zone:emz")),
                    source, target, target_sec,
                    inputs=InputGroup("all", (Need(f"{efid}:hub", hub_res, mode="presence"),)),
                    claims=(Claim(EMZ_POOL, 1),))
        target_tier = extra_tier(target) if target_sec == "extra" else (3, 0, target)
        for p_link, p_arrows in sorted(link_arrows.items()):
            if p_link == target or p_link in excluded_links or p_arrows <= 0:
                continue
            if target_sec == "extra" and not (extra_tier(p_link) < target_tier):
                continue
            lfid = f"{base_fid}:lnk:{p_link}"
            add_dag(lfid, lfid, Resource("field_entry", attributes=(*attrs, "zone:mmz_linked")),
                    source, target, target_sec,
                    inputs=InputGroup("all", (
                        Need(f"{lfid}:hub", hub_res, mode="presence"),
                        Need(f"{lfid}:par", Resource("active_link_arrows", attributes=(f"card:{p_link}",)), mode="presence"),
                    )),
                    claims=(Claim(link_arrow_pool(p_link, p_arrows), 1),))

    # Static effect-driven Extra NS & Special Summon & place_pendulum_scales
    def backing_fact_id(src_code, r_idx, o_idx):
        uid = operation_facts.get((src_code, r_idx, o_idx))
        if uid is not None:
            return uid.removeprefix("functional:")
        return next((v.removeprefix("functional:") for (c0, r0, _), v in sorted(operation_facts.items())
                     if c0 == src_code and r0 == r_idx), None)

    placed_scale_effects = []
    ess_count = Counter()
    for src in sorted(set(available.main + available.extra) & records.keys()):
        for ri, record in enumerate(records[src]):
            if record.get("block_view", {}).get("status") != "native_static":
                continue
            trig = record.get("trigger", {})
            for oi_all, op_item in enumerate(record.get("operations", ())):
                all_variants = [(0, op_item), *((1 + ai, alt) for ai, alt in enumerate(op_item.get("alternative_operations", ())))]
                for v_idx, vop in all_variants:
                    kind = vop.get("kind")
                    src_fid = backing_fact_id(src, ri, oi_all)
                    if src_fid is None:
                        continue
                    src_out = Resource("effect_ready", attributes=(src_fid,)) if src_fid in effect_ready_facts else Resource("functional_operation", attributes=(src_fid,))
                    if kind == "extra_normal_summon_supply" or vop.get("grants_extra_normal_summon"):
                        q = vop.get("selector_query") or {"type": 1}
                        if not query_supported(q):
                            continue
                        epool = extra_ns_pool(src, ri)
                        for m in sorted(main_set):
                            rule = monster_rules.get(m, {})
                            row = dependencies.rows.get(m, {})
                            if not (row.get("type", 0) & 1) or (row["type"] & 0x80) or rule.get("cannot_normal_summon") or rule.get("nomi_restricted"):
                                continue
                            if m == src and counts["main", m] < 2 and trig.get("event") in ("normal_summon", "normal_or_special_summon", "special_summon", "ignition"):
                                continue
                            if not matches(row, q):
                                continue
                            lv = rule.get("level") or (row.get("level", 0) & 255) or 1
                            tribs = 0 if lv <= 4 else (1 if lv <= 6 else 2)
                            if tribs and not tribute_summoners:
                                continue
                            for slot in range(slot_cap[m]):
                                efid = f"dag:ext_ns:{src}:{ri}:{oi_all}:{v_idx}:{m}:{slot}"
                                needs = [Need(f"{efid}:src", src_out, mode="presence")]
                                if tribs:
                                    needs.append(Need(f"{efid}:tr", Resource("tribute_body"), quantity=tribs, mode="consume"))
                                add_dag(efid, efid,
                                        Resource("field_entry", attributes=(f"card:{m}", f"slot:{slot}", "summon:normal", "proper:yes", "pre_scale:yes")),
                                        "extra_normal_summon", m, "main",
                                        inputs=InputGroup("all", tuple(needs)),
                                        claims=(Claim(phys_pool("main", m), 1), Claim(epool, 1)))
                    elif kind == "special_summon" and vop.get("owner", "self") == "self" and not vop.get("random"):
                        from_zones = set(vop.get("from_zones", ()))
                        ignore_cond = bool(vop.get("ignore_summoning_conditions"))
                        if vop.get("subject") == "this_card":
                            m = src
                            sec = row_sec(m)
                            rule = monster_rules.get(m, {})
                            needs_prop = (sec == "extra" and from_zones <= {"grave", "banished"}
                                          and rule.get("revive_limit") and not ignore_cond)
                            for slot in range(slot_cap.get(m, 1)):
                                efid = f"dag:ess_self:{src}:{ri}:{oi_all}:{v_idx}:{slot}"
                                needs = [Need(f"{efid}:src", src_out, mode="presence")]
                                if needs_prop:
                                    needs.append(Need(f"{efid}:prop", Resource("proper_summon", attributes=(f"card:{m}",)), mode="presence"))
                                prop_tag = "proper:no" if sec == "extra" else "proper:yes"
                                add_dag(efid, efid,
                                        Resource("field_entry", attributes=(f"card:{m}", f"slot:{slot}", "summon:special", prop_tag, "pre_scale:yes")),
                                        "effect_special_summon_self", m, sec,
                                        inputs=InputGroup("all", tuple(needs)),
                                        claims=(Claim(phys_pool(sec, m), 1),))
                        elif vop.get("selector_query"):
                            q = vop["selector_query"]
                            if not query_supported(q):
                                continue
                            can_main = bool(from_zones & {"hand", "deck", "grave", "banished", "pzone"})
                            can_extra = bool(from_zones & {"extra", "grave", "banished"})
                            for m in present:
                                row = dependencies.rows.get(m, {})
                                if not (row.get("type", 0) & 1):
                                    continue
                                sec = row_sec(m)
                                if (sec == "main" and not can_main) or (sec == "extra" and not can_extra):
                                    continue
                                rule = monster_rules.get(m, {})
                                if rule.get("nomi_restricted") and not ignore_cond:
                                    continue
                                if not matches(row, q):
                                    continue
                                is_rit = bool(row["type"] & 0x80)
                                needs_prop = False
                                if sec == "main" and (rule.get("revive_limit") or is_rit) and not ignore_cond:
                                    if from_zones & {"grave", "banished"}:
                                        needs_prop = True
                                    else:
                                        continue
                                if sec == "extra" and from_zones <= {"grave", "banished"} and not ignore_cond:
                                    needs_prop = True
                                if src == m and counts[sec, m] < 2 and trig.get("zone") == "field":
                                    continue
                                if trig.get("zone") == "field" and (row_sec(src) == "extra" or (row_sec(src) == "main" and sec == "main" and src >= m)):
                                    continue
                                if sec == "main" and rule.get("inherent_ss_procs"):
                                    continue
                                if ess_count[m] >= 1:
                                    continue
                                ess_count[m] += 1
                                for slot in range(slot_cap.get(m, 1)):
                                    efid = f"dag:ess:{src}:{ri}:{oi_all}:{v_idx}:{m}:{slot}"
                                    needs = [Need(f"{efid}:src", src_out, mode="presence")]
                                    if needs_prop:
                                        needs.append(Need(f"{efid}:prop", Resource("proper_summon", attributes=(f"card:{m}",)), mode="presence"))
                                    prop_tag = "proper:no" if (sec == "extra" or is_rit) else "proper:yes"
                                    attrs = (f"card:{m}", f"slot:{slot}", "summon:special", prop_tag, "pre_scale:yes")
                                    # MR5: Link/Pendulum Special Summoned from Extra Deck require EMZ or downward Link arrow
                                    if sec == "extra" and "extra" in from_zones and (row["type"] & (0x4000000 | 0x1000000)):
                                        hub_res = Resource("extra_cheated_hub", attributes=(efid,))
                                        add_dag(f"{efid}:hub", f"{efid}:hub", hub_res, "effect_special_summon", m, "extra",
                                                inputs=InputGroup("all", tuple(needs)), claims=(Claim(phys_pool("extra", m), 1),))
                                        emit_emz_or_linked_zone(efid, m, "extra", slot, attrs, "effect_special_summon", hub_res)
                                    else:
                                        add_dag(efid, efid, Resource("field_entry", attributes=attrs),
                                                "effect_special_summon", m, sec,
                                                inputs=InputGroup("all", tuple(needs)),
                                                claims=(Claim(phys_pool(sec, m), 1),))
                    elif kind == "place_pendulum_scales" and v_idx == 0:
                        placed_scale_effects.append((src, ri, record, vop, src_fid))

    # Fusion & Ritual field_entry + proper_summon (cap suppliers per target to avoid branch multiplication)
    for pkind, proofs, sec in (("fusion", fusion_proofs, "extra"), ("ritual", ritual_proofs, "main")):
        target_supplier_count = Counter()
        # Prefer Spell/Trap fusion sources (which do not require monster field/GY gates) first
        ordered_proofs = sorted(
            proofs.items(),
            key=lambda kv: (1 if (dependencies.rows.get(kv[0][0], {}).get("type", 0) & 1) else 0, kv[0]),
        )
        for (src, ri, oi), proof in ordered_proofs:
            src_fid = operation_facts[src, ri, oi].removeprefix("functional:")
            res_kinds = proof.get("target_resource_kinds", {})
            for target in sorted(res_kinds if res_kinds else {opt["target"] for opt in proof.get("options", ())}):
                if target_supplier_count[target] >= (2 if pkind == "ritual" else 1):
                    continue
                target_supplier_count[target] += 1
                res_kind = res_kinds.get(target, f"{pkind}_assignment")
                req_res = Resource(res_kind, attributes=(src_fid, f"target:{target}"))
                add_dag(f"dag:{pkind}_prop:{src}:{ri}:{oi}:{target}", f"dag:{pkind}_prop:{src}:{ri}:{oi}:{target}",
                        Resource("proper_summon", attributes=(f"card:{target}",)), f"{pkind}_summon_rule", target, sec,
                        inputs=InputGroup("all", (Need(f"dag:{pkind}_p:{src}:{ri}:{oi}:{target}", req_res, mode="presence"),)))
                is_pend_extra = (sec == "extra" and (dependencies.rows[target]["type"] & 0x1000000))
                for slot in range(slot_cap.get(target, 1)):
                    feid = f"dag:{pkind}_fe:{src}:{ri}:{oi}:{target}:{slot}"
                    attrs = (f"card:{target}", f"slot:{slot}", f"summon:{pkind}", "summon:special", "proper:yes", "pre_scale:yes")
                    if is_pend_extra:
                        emit_emz_or_linked_zone(feid, target, sec, slot, attrs, f"{pkind}_summon_rule", req_res)
                    else:
                        add_dag(feid, feid, Resource("field_entry", attributes=attrs), f"{pkind}_summon_rule", target, sec,
                                inputs=InputGroup("all", (Need(f"{feid}:rec", req_res, mode="presence"),)))
        if pkind == "ritual":
            for (src, ri, oi), proof in ordered_proofs:
                src_fid = operation_facts[src, ri, oi].removeprefix("functional:")
                src_ready = Resource("effect_ready", attributes=(src_fid,)) if src_fid in effect_ready_facts else Resource("functional_operation", attributes=(src_fid,))
                for target in sorted(proof.get("uncovered_targets", ())):
                    if target_supplier_count[target] >= 1:
                        continue
                    target_supplier_count[target] += 1
                    add_dag(f"dag:ritual_prop_unk:{src}:{ri}:{oi}:{target}",
                            f"dag:ritual_prop_unk:{src}:{ri}:{oi}:{target}",
                            Resource("proper_summon", attributes=(f"card:{target}",)),
                            "ritual_summon_rule", target, sec,
                            inputs=InputGroup("all", (Need(f"dag:ritual_pu:{src}:{ri}:{oi}:{target}", src_ready, mode="presence"),)),
                            unknown=("ritual_material_search_incomplete",))
                    for slot in range(slot_cap.get(target, 1)):
                        feid = f"dag:ritual_fe_unk:{src}:{ri}:{oi}:{target}:{slot}"
                        attrs = (f"card:{target}", f"slot:{slot}", "summon:ritual", "summon:special", "proper:yes", "pre_scale:yes")
                        add_dag(feid, feid, Resource("field_entry", attributes=attrs),
                                "ritual_summon_rule", target, sec,
                                inputs=InputGroup("all", (Need(f"{feid}:src", src_ready, mode="presence"),)),
                                unknown=("ritual_material_search_incomplete",))

    # Ground Main-monster enterability from actual DAG facts emitted so far (+ Pendulum windows),
    # so conditional inherent procs like Gigantes never crowd out feasible Extra/Effect SS routes.
    pend_open_lvs = set()
    for popt in stock.get("pendulum", ()):
        pl, pr = popt["left"], popt["right"]
        if pl == pr and counts["main", pl] < 2:
            continue
        pmin, pmax = popt["min_scale"], popt["max_scale"]
        if pmax - pmin >= 2:
            for t in popt.get("hand_targets", ()):
                t_id = t["card_id"] if isinstance(t, dict) else t
                tlv = (monster_rules.get(t_id, {}).get("pendulum_level")
                       or monster_rules.get(t_id, {}).get("level")
                       or (dependencies.rows.get(t_id, {}).get("level", 0) & 255) or 1)
                if pmin < tlv < pmax:
                    pend_open_lvs.add(t_id)
    main_can_ns = set()
    pre_scale_uncond_non_ns = set()
    pre_scale_anytime_non_ns = set()
    pre_scale_non_ns = set()
    pre_scale_entry = set()
    for rf in rel_facts:
        if rf.card_id in main_set and rf.output.kind == "field_entry":
            if rf.fact_id.startswith(("dag:ns:", "dag:trib_ns:")):
                pre_scale_entry.add(rf.card_id)
                main_can_ns.add(rf.card_id)
            elif rf.fact_id.startswith(("dag:inh_ss:", "dag:ess_self:", "dag:ritual_fe:")):
                pre_scale_entry.add(rf.card_id)
                pre_scale_non_ns.add(rf.card_id)
                if "entry:empty_own_mzone" not in rf.output.attributes:
                    pre_scale_uncond_non_ns.add(rf.card_id)
                    pre_scale_anytime_non_ns.add(rf.card_id)
            elif rf.fact_id.startswith(("dag:ess:", "dag:ext_ns:")):
                parts = rf.fact_id.split(":")
                if len(parts) >= 3 and parts[2].isdigit() and int(parts[2]) in extra_set:
                    continue  # Extra-deck-sourced SS/extra-NS cannot supply pre-Extra materials without circular dependency
                pre_scale_entry.add(rf.card_id)
                pre_scale_non_ns.add(rf.card_id)
                if "entry:empty_own_mzone" not in rf.output.attributes:
                    if rf.fact_id.startswith("dag:ext_ns:"):
                        pre_scale_uncond_non_ns.add(rf.card_id)
                    pre_scale_anytime_non_ns.add(rf.card_id)

    main_has_uncond_non_ns = pre_scale_uncond_non_ns | pend_open_lvs
    main_has_anytime_non_ns = pre_scale_anytime_non_ns | pend_open_lvs
    main_has_non_ns_entry = pre_scale_non_ns | pend_open_lvs
    main_has_entry = pre_scale_entry | pend_open_lvs

    def _main_pool_conflict(mats, non_ns_set, anytime_set):
        ns_only = sum(1 for m in mats if m["card_id"] in main_set and m["card_id"] not in non_ns_set)
        empty_only_no_ns = sum(1 for m in mats if m["card_id"] in main_set and m["card_id"] not in anytime_set and m["card_id"] not in main_can_ns)
        limited_pool = sum(1 for m in mats if m["card_id"] in main_set and m["card_id"] not in anytime_set)
        return max(0, ns_only - 1) + max(0, empty_only_no_ns - 1) + max(0, limited_pool - 2)

    # Contact Fusion, Synchro, Xyz, Link
    max_xyz_attached = Counter()

    def wire_extra_proc_group(proc_kind, options, *, summon_tag):
        grouped = defaultdict(list)
        for opt in options:
            target = opt["target"]
            is_alt = bool(opt.get("is_alternate_overlay")) if proc_kind == "xyz" else False
            t_tier = extra_tier(target, is_alt)
            if any(not (extra_tier(m["card_id"], False) < t_tier) for m in opt.get("materials", ())):
                continue
            grouped[(target, is_alt)].append(opt)
        for (target, is_alt), target_opts in sorted(grouped.items(), key=lambda kv: extra_tier(kv[0][0], kv[0][1])):
            is_scale_placer = target in scale_placer_cards
            entry_set = pre_scale_entry if is_scale_placer else main_has_entry
            non_ns_set = pre_scale_non_ns if is_scale_placer else main_has_non_ns_entry
            uncond_set = pre_scale_uncond_non_ns if is_scale_placer else main_has_uncond_non_ns
            anytime_set = pre_scale_anytime_non_ns if is_scale_placer else main_has_anytime_non_ns
            # Prioritize options whose Main materials are all enterable and avoid NS/empty-board pool conflicts
            ordered_opts = sorted(
                target_opts,
                key=lambda o: (
                    sum(1 for m in o.get("materials", ()) if m["card_id"] in main_set and m["card_id"] not in entry_set),
                    -max((max_xyz_attached.get(m["card_id"], 0) for m in o.get("materials", ())), default=0)
                    if (proc_kind == "xyz" and is_alt) else 0,
                    _main_pool_conflict(o.get("materials", ()), non_ns_set, anytime_set),
                    max(0, sum(1 for m in o.get("materials", ()) if m["card_id"] in main_set and m["card_id"] not in non_ns_set) - 1),
                    max(0, sum(1 for m in o.get("materials", ()) if m["card_id"] in main_set and m["card_id"] not in uncond_set) - 1),
                    sum(1 for m in o.get("materials", ()) if m["card_id"] in extra_set),
                    len(o.get("materials", ())),
                    tuple(m["card_id"] for m in o.get("materials", ())),
                ),
            )
            deduped_opts, seen_opt_keys = [], set()
            for opt in ordered_opts:
                opt_sig = (
                    tuple(sorted((m["card_id"], m.get("location")) for m in opt.get("materials", ()))),
                    tuple(sorted(t["card_id"] for t in opt.get("tuners", ()))),
                    opt.get("requires_external_state"),
                )
                if opt_sig not in seen_opt_keys:
                    seen_opt_keys.add(opt_sig)
                    deduped_opts.append(opt)
            opt_limit = 1
            if proc_kind == "xyz" and deduped_opts:
                best = deduped_opts[0]
                bmats = best.get("materials", ())
                if is_alt:
                    b0 = bmats[0]["card_id"] if len(bmats) == 1 else None
                    opt_limit = 1 if (b0 is not None and max_xyz_attached.get(b0, 0) >= 2) else 2
                else:
                    clean_std = (
                        all(m["card_id"] not in main_set or m["card_id"] in entry_set for m in bmats)
                        and _main_pool_conflict(bmats, non_ns_set, anytime_set) == 0
                        and sum(1 for m in bmats if m["card_id"] in main_set and m["card_id"] not in uncond_set) <= 1
                        and not any(m["card_id"] in extra_set for m in bmats)
                    )
                    opt_limit = 1 if clean_std else 2
            capped = _select_diverse_options(
                deduped_opts,
                lambda o: {m["card_id"] for m in o.get("materials", ())},
                limit=opt_limit,
            )
            target_hub_id = f"dag:{proc_kind}_thub:{target}:{int(is_alt)}"
            target_hub_res = Resource(f"{proc_kind}_target_hub", attributes=(target_hub_id,))
            target_climb_id = f"dag:{proc_kind}_tclimb:{target}:{int(is_alt)}"
            target_climb_res = Resource(f"{proc_kind}_target_climb", attributes=(target_climb_id,))
            has_any_opt, has_climb_opt = False, False
            req_pre_scale = ("pre_scale:yes",) if target in scale_placer_cards else ()
            std_attached_groups = defaultdict(list)
            for idx, opt in enumerate(capped):
                hub_id = f"dag:{proc_kind}:{target}:{int(is_alt)}:{idx}"
                hub_res = Resource(f"{proc_kind}_hub", attributes=(hub_id,))
                hub_conds = (opt["requires_external_state"],) if opt.get("requires_external_state") else ()
                needs, claims = [], [Claim(phys_pool("extra", target), 1)]
                mslots = Counter()
                uses_link_mat = False
                for m_i, mat in enumerate(opt.get("materials", ())):
                    m_id = mat["card_id"]
                    if dependencies.rows.get(m_id, {}).get("type", 0) & 0x4000000:
                        uses_link_mat = True
                    mloc = mat.get("location")
                    if mloc is None or mloc == 0x04:
                        ms = mslots[m_id]
                        mslots[m_id] += 1
                        needs.append(Need(f"{hub_id}:m:{m_i}",
                            Resource("field_entry", attributes=(f"card:{m_id}", f"slot:{ms}", *req_pre_scale)), mode="presence"))
                        claims.append(Claim(mat_pool(m_id, ms), 1))
                    else:
                        claims.append(Claim(phys_pool(mat["section"], m_id), 1))
                add_dag(hub_id, hub_id, hub_res, f"{proc_kind}_summon_procedure", target, "extra",
                        inputs=InputGroup("all", tuple(needs)) if needs else None,
                        claims=tuple(claims), conditions=hub_conds)
                has_any_opt = True
                add_dag(f"{hub_id}:th", f"{hub_id}:th", target_hub_res, f"{proc_kind}_summon_procedure", target, "extra",
                        inputs=InputGroup("all", (Need(f"{hub_id}:thn", hub_res, mode="presence"),)))
                if uses_link_mat:
                    has_climb_opt = True
                    add_dag(f"{hub_id}:tc", f"{hub_id}:tc", target_climb_res, f"{proc_kind}_summon_procedure", target, "extra",
                            inputs=InputGroup("all", (Need(f"{hub_id}:tcn", hub_res, mode="presence"),)))
                if proc_kind == "xyz":
                    mat_res = Resource("xyz_materials", attributes=(f"card:{target}",))
                    if is_alt and len(opt.get("materials", ())) == 1:
                        alt_eff_ref = f"dag:xyz_mat:{target}:alt"
                        add_dag(f"{hub_id}:xm:0", alt_eff_ref, mat_res,
                                "xyz_attached_materials", target, "extra", quantity=1,
                                inputs=InputGroup("all", (Need(f"{hub_id}:xmh", hub_res, mode="presence"),)),
                                conditions=hub_conds, choice=f"alt:{idx}:0")
                        base_id = opt["materials"][0]["card_id"]
                        max_inherit = min(3, int(max_xyz_attached.get(base_id, 0)))
                        max_xyz_attached[target] = max(max_xyz_attached[target], 1 + max_inherit)
                        if max_inherit > 0:
                            base_mat_res = Resource("xyz_materials", attributes=(f"card:{base_id}",))
                            for inh_k in range(1, max_inherit + 1):
                                add_dag(f"{hub_id}:xm:inh:{inh_k}", alt_eff_ref, mat_res,
                                        "xyz_attached_materials", target, "extra", quantity=1 + inh_k,
                                        inputs=InputGroup("all", (
                                            Need(f"{hub_id}:xmh", hub_res, mode="presence"),
                                            Need(f"{hub_id}:xmi:{inh_k}", base_mat_res, quantity=inh_k, mode="consume"),
                                        )),
                                        conditions=hub_conds, choice=f"alt:{idx}:{inh_k}")
                    else:
                        attached = max(1, int(opt.get("attached_count") or len(opt.get("materials", ()))))
                        max_xyz_attached[target] = max(max_xyz_attached[target], attached)
                        std_attached_groups[(attached, hub_conds)].append((idx, hub_id, hub_res))
            if proc_kind == "xyz" and std_attached_groups:
                mat_res = Resource("xyz_materials", attributes=(f"card:{target}",))
                for g_i, ((attached, g_conds), group_rows) in enumerate(sorted(std_attached_groups.items())):
                    att_hub_id = f"dag:xyz_ahub:{target}:{attached}:{g_i}"
                    att_hub_res = Resource("xyz_attached_hub", attributes=(att_hub_id,))
                    for _, h_id, h_res in group_rows:
                        add_dag(f"{h_id}:ag:{g_i}", f"{h_id}:ag:{g_i}", att_hub_res,
                                "xyz_attached_materials", target, "extra",
                                inputs=InputGroup("all", (Need(f"{h_id}:agn", h_res, mode="presence"),)),
                                conditions=g_conds)
                    add_dag(f"dag:xyz:{target}:0:xm:{attached}:{g_i}", f"dag:xyz_mat:{target}:std", mat_res,
                            "xyz_attached_materials", target, "extra", quantity=attached,
                            inputs=InputGroup("all", (Need(f"{att_hub_id}:n", att_hub_res, mode="presence"),)),
                            conditions=g_conds, choice=f"direct:0:{g_i}")
            if has_any_opt:
                add_dag(f"{target_hub_id}:prop", f"{target_hub_id}:prop", Resource("proper_summon", attributes=(f"card:{target}",)),
                        f"{proc_kind}_summon_procedure", target, "extra",
                        inputs=InputGroup("all", (Need(f"{target_hub_id}:ph", target_hub_res, mode="presence"),)))
                for slot in range(slot_cap.get(target, 1)):
                    attrs = (f"card:{target}", f"slot:{slot}", f"summon:{summon_tag}", "summon:special", "proper:yes", "pre_scale:yes")
                    if proc_kind == "link":
                        emit_emz_or_linked_zone(f"{target_hub_id}:s{slot}", target, "extra", slot, attrs,
                            "link_summon_procedure", target_hub_res, allow_free_emz=True)
                        if has_climb_opt:
                            inh_id = f"{target_hub_id}:s{slot}:emz_climb"
                            add_dag(inh_id, inh_id, Resource("field_entry", attributes=(*attrs, "zone:emz")),
                                    "link_summon_procedure", target, "extra",
                                    inputs=InputGroup("all", (Need(f"{inh_id}:hub", target_climb_res, mode="presence"),)))
                    else:
                        feid = f"{target_hub_id}:s{slot}:fe"
                        add_dag(feid, feid, Resource("field_entry", attributes=attrs),
                                f"{proc_kind}_summon_procedure", target, "extra",
                                inputs=InputGroup("all", (Need(f"{feid}:h", target_hub_res, mode="presence"),)))

    wire_extra_proc_group("contact_fusion", stock.get("contact_fusion", ()), summon_tag="fusion")
    wire_extra_proc_group("synchro", stock.get("synchro", ()), summon_tag="synchro")
    wire_extra_proc_group("xyz", stock.get("xyz", ()), summon_tag="xyz")
    wire_extra_proc_group("link", stock.get("link", ()), summon_tag="link")

    # Link downward arrow providers (`stay_on_field` in EMZ consumes material slot 0 so Link material consumption conflicts)
    for lc, larrows in sorted(link_arrows.items()):
        if larrows > 0:
            link_arrow_pool(lc, larrows)
            sfid = f"dag:link_arrows:{lc}"
            add_dag(sfid, sfid, Resource("active_link_arrows", attributes=(f"card:{lc}",)), "link_downward_arrows", lc, "extra",
                    inputs=InputGroup("all", (Need(f"{sfid}:fe", Resource("field_entry", attributes=(f"card:{lc}", "slot:0", "zone:emz")), mode="presence"),)),
                    claims=(Claim(mat_pool(lc, 0), 1),))

    # Pendulum windows (Hand-placed scales + Effect-placed scales such as D/D/D Gilgamesh)
    def card_level(m):
        return (monster_rules.get(m, {}).get("pendulum_level")
                or monster_rules.get(m, {}).get("level")
                or (dependencies.rows.get(m, {}).get("level", 0) & 255)
                or 1)

    hand_pend_seen = {}
    for opt in stock.get("pendulum", ()):
        l, r = opt["left"], opt["right"]
        pair_key = (min(l, r), max(l, r))
        if l == r and counts["main", l] < 2:
            continue
        if pair_key not in hand_pend_seen:
            hand_pend_seen[pair_key] = opt

    # Limit per interval if a pure Pendulum deck has dozens of redundant pairs
    interval_buckets = defaultdict(list)
    for pair_key, opt in sorted(hand_pend_seen.items()):
        interval_buckets[(opt["min_scale"], opt["max_scale"])].append((pair_key, opt))
    selected_pend_windows = [
        item for bucket in interval_buckets.values() for item in bucket[:8]
    ]
    hand_pend_levels, extra_pend_targets, extra_proper_pend_targets = set(), set(), set()
    for pair_key, opt in selected_pend_windows:
        l, r = pair_key
        min_s, max_s = opt["min_scale"], opt["max_scale"]
        if max_s - min_s < 2:
            continue
        hub_id = f"dag:pwin:hand:{l}:{r}"
        hub_res = Resource("pendulum_window_hub", attributes=(f"pair:{l}:{r}",))
        p_claims = [Claim(PEND_POOL, 1)]
        if l == r:
            p_claims.append(Claim(phys_pool("main", l), 2))
        else:
            p_claims.extend((Claim(phys_pool("main", l), 1), Claim(phys_pool("main", r), 1)))
        add_dag(hub_id, hub_id, hub_res, "pendulum_scale_window", l, "main", claims=tuple(p_claims))
        win_levels = set()
        for t in opt.get("hand_targets", ()):
            t_id = t["card_id"] if isinstance(t, dict) else t
            lv = card_level(t_id)
            if min_s < lv < max_s:
                win_levels.add(lv)
                hand_pend_levels.add(lv)
        for t in opt.get("extra_targets", ()):
            t_id = t["card_id"] if isinstance(t, dict) else t
            lv = card_level(t_id)
            if min_s < lv < max_s:
                win_levels.add(lv)
                extra_pend_targets.add(t_id)
        for t in opt.get("extra_proper_targets", ()):
            t_id = t["card_id"] if isinstance(t, dict) else t
            lv = card_level(t_id)
            if min_s < lv < max_s:
                win_levels.add(lv)
                extra_proper_pend_targets.add(t_id)
        for lv in sorted(win_levels):
            blv = f"{hub_id}:lv:{lv}"
            add_dag(blv, blv, Resource("pendulum_scale_level", attributes=(f"lv:{lv}",)),
                    "pendulum_scale_window", l, "main",
                    inputs=InputGroup("all", (Need(f"{blv}:h", hub_res, mode="presence"),)))

    for lv in sorted(hand_pend_levels):
        for m in sorted(main_set):
            row = dependencies.rows.get(m, {})
            if not (row.get("type", 0) & 1) or (row["type"] & 0x80) or monster_rules.get(m, {}).get("nomi_restricted"):
                continue
            if card_level(m) != lv:
                continue
            for slot in range(slot_cap.get(m, 1)):
                pfid = f"dag:pend_h:{m}:{slot}"
                add_dag(pfid, pfid,
                        Resource("field_entry", attributes=(f"card:{m}", f"slot:{slot}", "summon:pendulum", "summon:special", "proper:yes", "pre_scale:yes")),
                        "pendulum_summon_hand", m, "main",
                        inputs=InputGroup("all", (Need(f"{pfid}:sc", Resource("pendulum_scale_level", attributes=(f"lv:{lv}",)), mode="presence"),)),
                        claims=(Claim(phys_pool("main", m), 1),))

    # Effect-placed Pendulum scale windows (e.g. Gilgamesh e2 with D/D summon restriction)
    for src, ri, record, vop, src_fid in placed_scale_effects:
        sq = vop.get("selector_query") or {"type": 1}
        if not query_supported(sq):
            continue
        pend_cands = [c for c in sorted(main_set) if monster_rules.get(c, {}).get("is_pendulum") and matches(dependencies.rows[c], sq)]
        distinct_names = bool(vop.get("distinct_names"))
        allowed_pred = next((r["allowed_summons"] for r in record.get("restrictions", ()) if r.get("allowed_summons")), None)
        allowed_q = {"predicate": allowed_pred} if allowed_pred and query_supported({"predicate": allowed_pred}) else None
        pairs = []
        for i, c1 in enumerate(pend_cands):
            for c2 in pend_cands[i + 1:]:
                if distinct_names and rule_name_id(dependencies.rows, c1) == rule_name_id(dependencies.rows, c2):
                    continue
                r1, r2 = monster_rules[c1], monster_rules[c2]
                candidates_lr = ((r1["lscale"], r2["rscale"]), (r2["lscale"], r1["rscale"]))
                best_span = max(((min(a, b), max(a, b)) for a, b in candidates_lr), key=lambda ab: ab[1] - ab[0])
                if best_span[1] - best_span[0] >= 2:
                    pairs.append((c1, c2, best_span[0], best_span[1]))
        pairs = _select_diverse_options(pairs, lambda p: {p[0], p[1]}, limit=24)
        ready_res = Resource("effect_ready", attributes=(src_fid,)) if src_fid in effect_ready_facts else Resource("functional_operation", attributes=(src_fid,))
        eff_pend_levels = set()
        for c1, c2, min_s, max_s in pairs:
            sp_fid = f"dag:pscales:{src}:{ri}:{c1}:{c2}"
            sp_res = Resource("placed_pendulum_scales", attributes=(f"source:{src_fid}", f"pair:{c1}:{c2}"))
            add_dag(sp_fid, sp_fid, sp_res, "effect_placed_pendulum_scales", src, row_sec(src),
                    inputs=InputGroup("all", (Need(f"{sp_fid}:r", ready_res, mode="presence"),)),
                    claims=(Claim(phys_pool("main", c1), 1), Claim(phys_pool("main", c2), 1)))
            ehub_id = f"dag:pwin:eff:{src}:{ri}:{c1}:{c2}"
            ehub_res = Resource("pendulum_window_hub_eff", attributes=(ehub_id,))
            add_dag(ehub_id, ehub_id, ehub_res, "pendulum_scale_window_effect", src, row_sec(src),
                    inputs=InputGroup("all", (Need(f"{ehub_id}:sp", sp_res, mode="presence"),)),
                    claims=(Claim(PEND_POOL, 1),))
            matched_lvs = set()
            for m in present:
                row = dependencies.rows.get(m, {})
                if not (row.get("type", 0) & 1) or (row["type"] & 0x80) or monster_rules.get(m, {}).get("nomi_restricted"):
                    continue
                if allowed_q is not None and not matches(row, allowed_q):
                    continue
                lv = card_level(m)
                if min_s < lv < max_s and (m in main_set or (m in extra_set and (row["type"] & 0x1000000))):
                    matched_lvs.add(lv)
                    if m in main_set:
                        eff_pend_levels.add(lv)
                    elif m in extra_set:
                        extra_proper_pend_targets.add(m)
            for lv in sorted(matched_lvs):
                blv = f"{ehub_id}:lv:{lv}"
                add_dag(blv, blv, Resource("pendulum_eff_scale_level", attributes=(f"src:{src}:{ri}", f"lv:{lv}")),
                        "pendulum_scale_window_effect", src, row_sec(src),
                        inputs=InputGroup("all", (Need(f"{blv}:h", ehub_res, mode="presence"),)))
        for lv in sorted(eff_pend_levels):
            for m in sorted(main_set):
                row = dependencies.rows.get(m, {})
                if not (row.get("type", 0) & 1) or (row["type"] & 0x80) or monster_rules.get(m, {}).get("nomi_restricted"):
                    continue
                if allowed_q is not None and not matches(row, allowed_q):
                    continue
                if card_level(m) != lv:
                    continue
                for slot in range(slot_cap.get(m, 1)):
                    pfid = f"dag:pend_eff:{src}:{ri}:{m}:{slot}"
                    add_dag(pfid, pfid,
                            Resource("field_entry", attributes=(f"card:{m}", f"slot:{slot}", "summon:pendulum", "summon:special", "proper:yes")),
                            "pendulum_summon_hand_effect_scales", m, "main",
                            inputs=InputGroup("all", (Need(f"{pfid}:sc", Resource("pendulum_eff_scale_level", attributes=(f"src:{src}:{ri}", f"lv:{lv}")), mode="presence"),)),
                            claims=(Claim(phys_pool("main", m), 1),))

    # Face-up Extra Pendulum & Composite Extra/Pendulum entries (EMZ / Link downward arrows + proper_summon if Composite Extra)
    for m in sorted(extra_pend_targets):
        lv = card_level(m)
        hub_id = f"dag:pend_ex_hub:{m}"
        hub_res = Resource("pendulum_extra_hub", attributes=(hub_id,))
        add_dag(hub_id, hub_id, hub_res, "pendulum_extra_faceup", m, "main",
                inputs=InputGroup("all", (Need(f"{hub_id}:sc", Resource("pendulum_scale_level", attributes=(f"lv:{lv}",)), mode="presence"),)),
                claims=(Claim(phys_pool("main", m), 1),))
        emit_emz_or_linked_zone(f"dag:pend_ex:{m}", m, "main", 0, (f"card:{m}", "zone:extra_faceup", "summon:pendulum"),
                                "pendulum_extra_faceup", hub_res)
        add_dag(f"dag:pend_ex_emz:{m}", f"dag:pend_ex_emz:{m}",
                Resource("pendulum_extra_entry", attributes=(f"card:{m}",)), "pendulum_extra_faceup", m, "main",
                inputs=InputGroup("all", (Need(f"dag:pend_ex_emz:{m}:h", hub_res, mode="presence"),)), claims=(Claim(EMZ_POOL, 1),))
        for p_link, p_arrows in sorted(link_arrows.items()):
            if p_arrows <= 0:
                continue
            plid = f"dag:pend_ex_lnk:{m}:{p_link}"
            add_dag(plid, plid, Resource("pendulum_extra_entry", attributes=(f"card:{m}",)),
                    "pendulum_extra_faceup", m, "main",
                    inputs=InputGroup("all", (
                        Need(f"{plid}:h", hub_res, mode="presence"),
                        Need(f"{plid}:p", Resource("active_link_arrows", attributes=(f"card:{p_link}",)), mode="presence"),
                    )),
                    claims=(Claim(link_arrow_pool(p_link, p_arrows), 1),))
    for m in sorted(extra_proper_pend_targets):
        lv = card_level(m)
        sec = row_sec(m)
        hub_id = f"dag:pend_exp_hub:{m}"
        hub_res = Resource("pendulum_extra_proper_hub", attributes=(hub_id,))
        add_dag(hub_id, hub_id, hub_res, "pendulum_composite_extra_reentry", m, sec,
                inputs=InputGroup("all", (
                    Need(f"{hub_id}:sc", Resource("pendulum_scale_level", attributes=(f"lv:{lv}",)), mode="presence"),
                    Need(f"{hub_id}:prop", Resource("proper_summon", attributes=(f"card:{m}",)), mode="presence"),
                )))
        add_dag(f"dag:pend_exp_emz:{m}", f"dag:pend_exp_emz:{m}",
                Resource("pendulum_extra_entry", attributes=(f"card:{m}",)), "pendulum_composite_extra_reentry", m, sec,
                inputs=InputGroup("all", (Need(f"dag:pend_exp_emz:{m}:h", hub_res, mode="presence"),)), claims=(Claim(EMZ_POOL, 1),))
        for p_link, p_arrows in sorted(link_arrows.items()):
            if p_arrows <= 0:
                continue
            plid = f"dag:pend_exp_lnk:{m}:{p_link}"
            add_dag(plid, plid, Resource("pendulum_extra_entry", attributes=(f"card:{m}",)),
                    "pendulum_composite_extra_reentry", m, sec,
                    inputs=InputGroup("all", (
                        Need(f"{plid}:h", hub_res, mode="presence"),
                        Need(f"{plid}:p", Resource("active_link_arrows", attributes=(f"card:{p_link}",)), mode="presence"),
                    )),
                    claims=(Claim(link_arrow_pool(p_link, p_arrows), 1),))

    # Identify only cards that actually have downstream GY send gates, and require independent non-sent_to_grave starters
    needed_eff_gy, needed_hd_gy = set(), set()
    for code, ri, oi, fact_idx, scoped_record, operation, fusion, ritual in static_facts_meta:
        trig = scoped_record.get("trigger", {})
        if (dependencies.rows.get(code, {}).get("type", 0) & 1) and trig.get("zone") == "grave" and trig.get("event") == "sent_to_grave":
            if trig.get("required_reason") == "effect":
                needed_eff_gy.add(code)
            elif trig.get("previous_location") == "hand_or_deck":
                needed_hd_gy.add(code)

    eff_gy_count, hd_gy_count = Counter(), Counter()
    # Order GY send suppliers so non-field starters (hand/spell_trap) come before field monsters
    gy_sources = sorted(
        ((src, ri, srec) for src in (set(available.main + available.extra) & records.keys())
         for ri, srec in enumerate(records[src])
         if srec.get("block_view", {}).get("status") == "native_static"
         and srec.get("trigger", {}).get("event") != "sent_to_grave"),
        key=lambda item: (1 if item[2].get("trigger", {}).get("zone") == "field" and (dependencies.rows.get(item[0], {}).get("type", 0) & 1) else 0, item[0], item[1]),
    )
    for src, ri, srec in gy_sources:
        if True:
            src_fid = backing_fact_id(src, ri, 0)
            if src_fid is None:
                continue
            src_out = Resource("functional_operation", attributes=(src_fid,))
            s_ops = [*srec.get("operations", ()), *(alt for op in srec.get("operations", ()) for alt in op.get("alternative_operations", ())), *srec.get("extra_operation_requirements", ())]
            for sop_i, sop in enumerate(s_ops):
                if sop.get("kind") == "send_grave" and sop.get("owner", "self") == "self":
                    fz = set(sop.get("from_zones", ()))
                    is_rand = bool(sop.get("random"))
                    sq = sop.get("selector_query") or ({"type": 7} if is_rand else None)
                    if sq and not query_supported(sq):
                        continue
                    for m in sorted(needed_eff_gy | needed_hd_gy):
                        sec = row_sec(m)
                        # Extra Deck monsters depend on Main Deck starters/fusers to enter field; never back-feed Main Deck GY gates
                        if row_sec(src) == "extra" and sec == "main":
                            continue
                        if (sec == "main" and not (fz & {"hand", "deck", "field", "extra"})) or (sec == "extra" and not (fz & {"extra", "field"})):
                            continue
                        if sq and not matches(dependencies.rows[m], sq):
                            continue
                        if sec == "main" and fz <= {"hand", "deck"} and m == src and counts[sec, m] < 2:
                            continue
                        if m in needed_eff_gy and eff_gy_count[m] < 2:
                            eff_gy_count[m] += 1
                            needs = [Need(f"dag:sgy:{src}:{ri}:{sop_i}:{m}:s", src_out, mode="presence")]
                            if sec == "extra" and "field" in fz and "extra" not in fz:
                                needs.append(Need(f"dag:sgy:{src}:{ri}:{sop_i}:{m}:fe", Resource("field_entry", attributes=(f"card:{m}",)), mode="presence"))
                            efid = f"dag:eff_gy:{src}:{ri}:{sop_i}:{m}"
                            add_dag(efid, efid, Resource("effect_sent_to_grave", attributes=(f"card:{m}",)),
                                    "effect_send_to_grave", src, row_sec(src), inputs=InputGroup("all", tuple(needs)))
                        if m in needed_hd_gy and sec == "main" and (fz & {"hand", "deck"}) and hd_gy_count[m] < 2:
                            hd_gy_count[m] += 1
                            hdid = f"dag:hd_gy_e:{src}:{ri}:{sop_i}:{m}"
                            add_dag(hdid, hdid, Resource("hand_deck_sent_to_grave", attributes=(f"card:{m}",)),
                                    "effect_hand_deck_to_grave", src, row_sec(src),
                                    inputs=InputGroup("all", (Need(f"{hdid}:s", src_out, mode="presence"),)))
            for ci, scost in enumerate(srec.get("costs", ())):
                if scost.get("to_zone") == "grave" and (set(scost.get("from_zones", ())) & {"hand", "deck"}) and scost.get("kind") != "xyz_detach":
                    sq = scost.get("selector_query")
                    if sq and not query_supported(sq):
                        continue
                    for m in sorted(needed_hd_gy & main_set):
                        if hd_gy_count[m] >= 2 or (m == src and counts["main", m] < 2):
                            continue
                        if sq and not matches(dependencies.rows[m], sq):
                            continue
                        hd_gy_count[m] += 1
                        hdid = f"dag:hd_gy_c:{src}:{ri}:{ci}:{m}"
                        add_dag(hdid, hdid, Resource("hand_deck_sent_to_grave", attributes=(f"card:{m}",)),
                                "cost_hand_deck_to_grave", src, row_sec(src),
                                inputs=InputGroup("all", (Need(f"{hdid}:s", src_out, mode="presence"),)))

    # Wire downstream payoff gates & return_to_deck event suppliers onto static facts
    for code, ri, oi, fact_idx, scoped_record, operation, fusion, ritual in static_facts_meta:
        orig_fact = rel_facts[fact_idx]
        target_idx = effect_ready_facts.get(orig_fact.fact_id, fact_idx)
        target_fact = rel_facts[target_idx]
        trig = scoped_record.get("trigger", {})
        trig_zone, trig_ev = trig.get("zone"), trig.get("event")
        row = dependencies.rows.get(code, {})
        is_monster = bool(row.get("type", 0) & 1)
        sec = row_sec(code)
        extra_needs, extra_claims = [], []
        has_xyz_detach = any(c.get("kind") == "xyz_detach" for c in scoped_record.get("costs", ()))
        if is_monster and trig_zone == "field":
            if not has_xyz_detach:
                req_type = trig.get("required_summon_type")
                if trig_ev == "flip":
                    extra_needs.append(Need(f"dag:gate:{code}:{ri}:{oi}:flip", Resource("flip_entry", attributes=(f"card:{code}",)), mode="presence"))
                elif req_type in ("fusion", "synchro", "xyz", "link", "pendulum", "ritual", "normal", "special"):
                    extra_needs.append(Need(f"dag:gate:{code}:{ri}:{oi}:stype", Resource("field_entry", attributes=(f"card:{code}", f"summon:{req_type}")), mode="presence"))
                elif trig_ev == "normal_summon":
                    extra_needs.append(Need(f"dag:gate:{code}:{ri}:{oi}:ns", Resource("field_entry", attributes=(f"card:{code}", "summon:normal")), mode="presence"))
                elif trig_ev == "special_summon":
                    extra_needs.append(Need(f"dag:gate:{code}:{ri}:{oi}:ss", Resource("field_entry", attributes=(f"card:{code}", "summon:special")), mode="presence"))
                else:
                    extra_needs.append(Need(f"dag:gate:{code}:{ri}:{oi}:fe", Resource("field_entry", attributes=(f"card:{code}",)), mode="presence"))
            if any(c.get("subject") == "this_card" and c.get("kind") != "xyz_detach" for c in scoped_record.get("costs", ())):
                extra_claims.append(Claim(mat_pool(code, 0), 1))
        if is_monster and trig_zone in ("grave", "banished") and (trig.get("previous_location") == "field" or trig_ev in ("destroyed", "battle_destroyed", "leave_field")):
            req_type = trig.get("required_summon_type")
            if req_type in ("fusion", "synchro", "xyz", "link", "pendulum", "ritual", "normal", "special"):
                extra_needs.append(Need(f"dag:gate:{code}:{ri}:{oi}:pft", Resource("field_entry", attributes=(f"card:{code}", f"summon:{req_type}")), mode="presence"))
            else:
                extra_needs.append(Need(f"dag:gate:{code}:{ri}:{oi}:pf", Resource("field_entry", attributes=(f"card:{code}",)), mode="presence"))
        if is_monster and trig_zone == "grave" and trig_ev == "sent_to_grave":
            if trig.get("required_reason") == "effect":
                extra_needs.append(Need(f"dag:gate:{code}:{ri}:{oi}:egy", Resource("effect_sent_to_grave", attributes=(f"card:{code}",)), mode="presence"))
            elif trig.get("previous_location") == "hand_or_deck":
                extra_needs.append(Need(f"dag:gate:{code}:{ri}:{oi}:hdgy", Resource("hand_deck_sent_to_grave", attributes=(f"card:{code}",)), mode="presence"))
        if trig_ev == "return_to_deck":
            rtd_attr = f"target:{orig_fact.fact_id}"
            extra_needs.append(Need(f"dag:gate:{code}:{ri}:{oi}:rtd", Resource("event:return_to_deck", attributes=(rtd_attr,)), mode="presence"))
            eg_q = trig.get("event_group_query")
            eg_ok = eg_q if (eg_q and query_supported(eg_q)) else None
            rtd_count = 0
            # Fusion spells/effects that return materials to Deck (e.g. Tearlaments Scheiren/Havnis/Merrli)
            for (f_src, f_ri, f_oi), f_proof in sorted(fusion_proofs.items()):
                if rtd_count >= 2:
                    break
                if not records[f_src][f_ri].get("fusion_returns_to_deck"):
                    continue
                if any((eg_ok is None or matches(dependencies.rows[m["card_id"]], eg_ok))
                       for opt in f_proof.get("options", ()) for m in opt.get("materials", ())):
                    rtd_count += 1
                    f_uid = operation_facts[f_src, f_ri, f_oi].removeprefix("functional:")
                    add_dag(f"dag:rtd_fus:{code}:{ri}:{oi}:{f_src}:{f_ri}:{f_oi}",
                            f"dag:rtd_fus:{code}:{ri}:{oi}:{f_src}:{f_ri}:{f_oi}",
                            Resource("event:return_to_deck", attributes=(rtd_attr,)),
                            "fusion_returns_material_to_deck", f_src, row_sec(f_src),
                            inputs=InputGroup("all", (Need(f"dag:rtd_f:{code}:{ri}:{oi}:{f_src}:{f_ri}:{f_oi}", Resource("functional_operation", attributes=(f_uid,)), mode="presence"),)))
            # Ordinary return_deck operations
            for s_code, s_ri, s_oi, s_fidx, s_rec, s_op, _, _ in static_facts_meta:
                if rtd_count >= 2:
                    break
                if s_op and s_op.get("kind") == "return_deck" and s_op.get("owner", "self") == "self":
                    sq = s_op.get("selector_query")
                    sq_ok = sq if (sq and query_supported(sq)) else None
                    if any(dependencies.rows.get(m) and (sq_ok is None or matches(dependencies.rows[m], sq_ok))
                           and (eg_ok is None or matches(dependencies.rows[m], eg_ok)) for m in present):
                        rtd_count += 1
                        add_dag(f"dag:rtd_op:{code}:{ri}:{oi}:{s_code}:{s_ri}:{s_oi}",
                                f"dag:rtd_op:{code}:{ri}:{oi}:{s_code}:{s_ri}:{s_oi}",
                                Resource("event:return_to_deck", attributes=(rtd_attr,)),
                                "return_to_deck_operation", s_code, row_sec(s_code),
                                inputs=InputGroup("all", (Need(f"dag:rtd_o:{code}:{ri}:{oi}:{s_code}:{s_ri}:{s_oi}", Resource("functional_operation", attributes=(rel_facts[s_fidx].fact_id,)), mode="presence"),)))
        if extra_needs or extra_claims:
            base_inputs = target_fact.inputs
            if extra_needs:
                base_items = base_inputs.items if (base_inputs and base_inputs.operator == "all") else ((base_inputs,) if base_inputs is not None else ())
                new_inputs = InputGroup("all", (*base_items, *extra_needs))
            else:
                new_inputs = base_inputs
            new_claims = _aggregate_claims((*target_fact.claims, *extra_claims))
            rel_facts[target_idx] = replace(target_fact, inputs=new_inputs, claims=new_claims)

    # Guarantee strict DAG acyclicity across all relation facts so fixed-point propagation finishes in one pass
    _secondary_dag_prefixes = (
        "dag:ess:", "dag:ess_self:", "dag:ext_ns:",
        "dag:pend_eff:", "dag:pwin:eff:", "dag:pscales:",
        "dag:rtd_", "dag:eff_gy:", "dag:hd_gy_", "dag:tb:",
    )
    _primary_dag_prefixes = (
        "dag:ns:", "dag:trib_ns:", "dag:inh_ss:", "dag:flip:",
        "dag:contact_fusion:", "dag:contact_fusion_", "dag:synchro:", "dag:synchro_",
        "dag:xyz:", "dag:xyz_", "dag:link:", "dag:link_",
        "dag:fusion_", "dag:ritual_", "dag:pend_h:", "dag:pwin:hand:",
    )

    def _dag_drop_rank(fid):
        if fid.startswith(_secondary_dag_prefixes):
            return 0
        if fid.startswith(_primary_dag_prefixes):
            return 2
        return 1

    while True:
        out_buckets = defaultdict(list)
        for idx, f in enumerate(rel_facts):
            out_buckets[f.output.kind].append(idx)
        adj = defaultdict(set)
        for idx, f in enumerate(rel_facts):
            for n in _needs(f.inputs):
                for s_idx in out_buckets.get(n.resource.kind, ()):
                    if s_idx != idx and n.resource.accepts(rel_facts[s_idx].output):
                        adj[idx].add(s_idx)
        state_color = {}
        stack = []
        cyclic_dag_indices = set()

        def dfs_cycle(u):
            state_color[u] = 1
            stack.append(u)
            for v in sorted(adj.get(u, ())):
                if v in cyclic_dag_indices or u in cyclic_dag_indices:
                    continue
                c = state_color.get(v, 0)
                if c == 1:
                    cycle_slice = stack[stack.index(v):]
                    dag_nodes = [(pos, w) for pos, w in enumerate(cycle_slice) if rel_facts[w].fact_id.startswith("dag:")]
                    drop = min(dag_nodes, key=lambda pw: (_dag_drop_rank(rel_facts[pw[1]].fact_id), -pw[0]))[1] if dag_nodes else None
                    if drop is not None:
                        cyclic_dag_indices.add(drop)
                elif c == 0:
                    dfs_cycle(v)
            stack.pop()
            state_color[u] = 2

        for idx in range(len(rel_facts)):
            if state_color.get(idx, 0) == 0 and idx not in cyclic_dag_indices:
                dfs_cycle(idx)
        if not cyclic_dag_indices:
            break
        rel_facts[:] = [f for idx, f in enumerate(rel_facts) if idx not in cyclic_dag_indices]

    # Diagnostic sentinel UseRequirements (never scored; exposes special_entries & face-up extra pendulum status)
    for m in sorted(slot_cap):
        suid = f"dag:special_entry:{m}"
        rel_uses.append(UseRequirement(suid, InputGroup("all", (Need(suid, Resource("field_entry", attributes=(f"card:{m}", "slot:0", "summon:special")), mode="presence"),)),
                                       suid, required=False))
    for m in sorted(extra_pend_targets | extra_proper_pend_targets):
        puid = f"dag:pend_extra:{m}"
        rel_uses.append(UseRequirement(puid, InputGroup("all", (Need(puid, Resource("pendulum_extra_entry", attributes=(f"card:{m}",)), mode="presence"),)),
                                       puid, required=False))


def _functional_relations(deck, available, records, aliases, extra_ids, context, budget, dependencies, config,
                          *, continuation=None, should_stop=None, previous_projections=None, projection='resident',
                          native_authority=False):
    """Evaluate one inventory projection; Side never enters the resident call."""
    from .construction_relations import evaluate_relations
    rel_facts, rel_pools, rel_uses, operation_facts = [], {}, [], {}
    fusion_proofs, ritual_proofs = {}, {}
    static_facts_meta, effect_ready_facts = [], {}
    extra_set = set(extra_ids)
    present = set(available.main + available.extra)
    dag_available = bool(native_authority and dependencies.native_summon_stock.get((tuple(available.main), tuple(available.extra))))
    members = tuple(sorted({(zone, code) for zone in ("main", "extra") for code in getattr(available, zone)}))
    for code in sorted(present & records.keys()):
        zone = "extra" if code in extra_ids else "main"
        # These are selected uses of the candidate's own effects. Movement
        # ownership still comes from the operation, independently of its actor.
        if native_authority:
            observed = [(RelationFact(operation["block_id"], record["effect_key"],
                Resource(operation["kind"]), operation["source"], code, zone), ())
                for record in records[code] for _, operation in _record_outputs(record)]
        else:
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
            native = dependencies.witnessed_processing(available, scoped_record, operation, inventory=deck, scope=projection)
            authoritative = native is not None
            static_rule = scoped_record["block_view"]["status"] == "native_static"
            ritual = None
            if static_rule:
                fusion = dependencies.fusion_check(available, code, scoped_record)
                ritual = dependencies.ritual_check(available, code, scoped_record) if fusion is None else None
                checks, processing = [], None
                if scoped_record.get("type_matched_deck_send"):
                    processing = dependencies.processing_check(available, scoped_record, operation, physical_inventory=deck)
                claims, extra_needs = [], []
                _activation_claims(fact, scoped_record["rule_registration"], scoped_record["effect_key"],
                                   fact.source, rel_pools, claims)
                lp_charged = False
                self_cost_deferred = False
                for ci, cost in enumerate(scoped_record.get("costs", ())):
                    if cost.get("resource") == "lp" and type(cost.get("quantity")) is int and cost["quantity"] > 0:
                        rel_pools.setdefault(LP_PAYMENT_POOL, ResourcePool(LP_PAYMENT_POOL,
                            "rule: initial 8000 LP; payment leaves positive LP", capacity=7999))
                        claims.append(Claim(LP_PAYMENT_POOL, cost["quantity"]))
                        lp_charged = True
                    elif cost.get("kind") == "xyz_detach":
                        extra_needs.append(Need(
                            f"{fact.fact_id}:xyz_detach:{ci}",
                            Resource("xyz_materials", attributes=(f"card:{code}",)),
                            quantity=max(1, int(cost.get("quantity") or 1)),
                            mode="consume",
                        ))
                    elif cost.get("subject") == "this_card":
                        if dag_available and scoped_record["trigger"].get("zone") == "field" and (dependencies.rows[code]["type"] & 1):
                            self_cost_deferred = True
                        else:
                            key = "configuration:physical:" + str(code)
                            rel_pools.setdefault(key, ResourcePool(key, "candidate physical copies", inventory=((zone, code),)))
                            claims.append(Claim(key, 1))
                if fusion is not None or ritual is not None:
                    kind_name = "fusion" if fusion is not None else "ritual"
                    check_obj = fusion if fusion is not None else ritual
                    ready_res = Resource("effect_ready", attributes=(fact.fact_id,))
                    effect_ready_facts[fact.fact_id] = len(rel_facts)
                    rel_facts.append(RelationFact(
                        fact.fact_id + ":ready", fact.effect_ref + ":ready", ready_res, fact.source,
                        code, zone, claims=_aggregate_claims(claims),
                    ))
                    claims = []
                    recipe = _summon_recipe_assignment(
                        fact, check_obj, rel_facts, rel_pools,
                        kind=kind_name, lp_already_charged=lp_charged,
                        ready_resource=ready_res, dag_available=dag_available,
                        include_alternatives=bool(context is not None and context.relations.uses),
                        rows=dependencies.rows,
                    )
                    target_sec = "extra" if fusion is not None else "main"
                    members = tuple(sorted({(target_sec, row["target"]) for row in check_obj["options"]}))
                    origin = "extra" if fusion is not None else "hand"
                    if ritual is not None:
                        checks.append(ritual)
                        ritual_proofs[code, ri, oi] = ritual
                else:
                    complete = dependencies._check(available, rows, distinct=True)
                    checks.append(complete)
                    avail_counts = Counter((z, c) for z in ("main", "extra") for c in getattr(available, z))
                    for r in complete["requirements"]:
                        cat = r.get("category")
                        matched_ids = r.get("matching_card_ids", ())
                        if not matched_ids:
                            continue
                        if cat == "costs":
                            if self_cost_deferred or (any(c.get("subject") == "this_card" for c in scoped_record.get("costs", ()))
                                    and r.get("query", {}).get("predicate") == {"field": "card_ids", "value": [code]}):
                                continue
                            inv = tuple(sorted({("extra" if c in extra_set else "main", c) for c in matched_ids}))
                            if inv and sum(avail_counts[p] for p in inv) <= max(4, r["minimum"] + 2):
                                ckey = "configuration:deck-objects:" + digest(inv)
                                rel_pools.setdefault(ckey, ResourcePool(ckey, "eligible candidate cost copies", inventory=inv))
                                claims.append(Claim(ckey, r["minimum"]))
                        elif cat == "operations" and r.get("operation") is None:
                            inv = tuple(sorted({("extra" if c in extra_set else "main", c) for c in matched_ids}))
                            if inv and sum(avail_counts[p] for p in inv) <= max(4, r["minimum"] + 2):
                                ckey = "configuration:deck-objects:" + digest(inv)
                                rel_pools.setdefault(ckey, ResourcePool(ckey, "eligible prerequisite operation copies", inventory=inv))
                                claims.append(Claim(ckey, r["minimum"]))
                    op_req = next((r for r in complete["requirements"]
                                   if r.get("category") == "operations" and r.get("operation") == operation), None)
                    members = tuple(sorted({("extra" if c in extra_set else "main", c)
                                            for c in (op_req["matching_card_ids"] if op_req is not None else ())}))
                    if operation and operation.get("kind") == "place_pendulum_scales" and dag_available:
                        ready_res = Resource("effect_ready", attributes=(fact.fact_id,))
                        effect_ready_facts[fact.fact_id] = len(rel_facts)
                        rel_facts.append(RelationFact(
                            fact.fact_id + ":ready", fact.effect_ref + ":ready", ready_res, fact.source,
                            code, zone, claims=_aggregate_claims(claims),
                        ))
                        claims = []
                        recipe = InputGroup("all", tuple(v for v in (
                            fact.inputs,
                            Need(f"{fact.fact_id}:pscales", Resource("placed_pendulum_scales", attributes=(f"source:{fact.fact_id}",)), mode="presence"),
                        ) if v is not None))
                    else:
                        op_qty = max(1, int(operation.get("quantity") or 1)) if operation else 1
                        if (members and operation and operation.get("owner", "self") == "self"
                                and operation.get("from_zones") and not operation.get("random")
                                and sum(avail_counts[p] for p in members) <= max(4, op_qty + 2)):
                            key = "configuration:deck-objects:" + digest(members)
                            rel_pools.setdefault(key, ResourcePool(key, "eligible candidate deck copies", inventory=members))
                            claims.append(Claim(key, op_qty))
                        recipe = fact.inputs
                    origin = operation["from_zones"][0] if (operation and operation.get("from_zones")) else None
                combined_inputs = recipe
                if extra_needs:
                    base_items = combined_inputs.items if (combined_inputs and combined_inputs.operator == "all") else (
                        (combined_inputs,) if combined_inputs is not None else ())
                    combined_inputs = InputGroup("all", (*base_items, *extra_needs))
                transfer = (
                    ResourceTransfer(
                        fact.source, origin, operation["to_zone"], "self", "self",
                        "random" if operation.get("random") else "targeted", members, "effect",
                    )
                    if (operation and origin and operation.get("to_zone") and operation.get("owner", "self") == "self" and members)
                    else None
                )
                qty = max(1, int(operation.get("quantity") or 1)) if (operation and operation.get("quantity")) else 1
                fact = replace(fact, inputs=combined_inputs, claims=_aggregate_claims(claims), quantity=qty, transfer=transfer)
            elif authoritative:
                checks, fusion, processing = [native], None, None
                fact = _settled_operation_fact(fact, operation, native, rel_pools)
            elif native_authority:
                checks, fusion, processing = [], None, None
                fact = replace(fact, unknown=("native_configuration_or_direction_unwitnessed",))
            else:
                checks = [dependencies.summon_trigger_check(code, scoped_record),
                          dependencies._check(available, cost_rows, distinct=True),
                          dependencies._check(available, [r for r in rows if r["category"] != "costs"])]
                fusion = dependencies.fusion_check(available, code, scoped_record)
                processing = dependencies.processing_check(available, scoped_record, operation, physical_inventory=deck)
            if fusion:
                checks.append(fusion)
                if operation and operation['kind'] == 'fusion_summon':
                    fusion_proofs[code, ri, oi] = fusion
                if operation and operation['kind']=='return_fusion_materials':
                    # The quantity depends on the chosen printed recipe. This
                    # is a static function port, not a concrete recovery event.
                    fact=replace(fact,quantity=1,transfer=None)
            if processing:
                checks.append(processing)
                binding = scoped_record.get('type_matched_deck_send')
                if binding and operation['block_id'] == binding['send'] and fact.transfer:
                    fact = replace(fact, transfer=replace(fact.transfer,
                        inventory=tuple(('main', c) for c in processing['possible_send_card_ids'])))
            if context is not None and not native_authority and not authoritative:
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
            material = None if native_authority or authoritative else dependencies.summon_material_check(available, code)
            if material:
                checks.append(material)
            inventory_port = Resource("functional_inventory", attributes=(fact.fact_id,))
            inventory_key = fact.fact_id+":inventory"
            if not any(r["status"] == "missing" for r in checks):
                gaps = tuple("inventory_selector:"+str(i) for i,r in enumerate(checks) if r["status"] == "unknown"
                    and (r.get('unknown_selectors') or r.get('unknown_restrictions') or not r.get('requirements')))
                gaps += tuple("complete_selector:"+r.get("source", "") for r in effect_specs[ri]["unknown"]
                              if not authoritative and r['category'] not in ('costs', 'targets')
                              and ("operation" not in r or r["operation"] == operation)
                              and r.get('choice') in (None, (operation or {}).get('choice')))
                rel_facts.append(RelationFact(inventory_key, inventory_key, inventory_port,
                    "complete candidate inventory", code, zone, unknown=gaps))
            inputs = InputGroup("all", tuple(v for v in (fact.inputs,
                Need(inventory_key, inventory_port, mode="presence")) if v is not None))
            unknown = fact.unknown
            if processing and processing['status'] == 'unknown':
                unknown += (processing['reason'],)
            fact_idx = len(rel_facts)
            rel_facts.append(replace(fact, output=output, quantity=fact.quantity if fact.transfer else 1,
                inputs=inputs, unknown=unknown))
            if static_rule:
                static_facts_meta.append((code, ri, oi, fact_idx, scoped_record, operation, fusion, ritual))
            rel_pools.update((p.pool_id, p) for p in pools)
            uid = "functional:" + fact.fact_id
            rel_uses.append(UseRequirement(uid, InputGroup("all", (Need(uid, output, mode="presence"),)),
                fact.source, required=False))
            operation_facts[code, ri, oi] = uid
    if native_authority:
        _wire_native_summon_dag_and_gates(
            available, records, extra_ids, dependencies, aliases, rel_facts, rel_pools,
            rel_uses, operation_facts, static_facts_meta, effect_ready_facts, fusion_proofs, ritual_proofs,
        )
    if not native_authority:
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
    theme_profile = config.get('theme_profile')
    if theme_profile and (theme_profile['goals'] or theme_profile.get('rule_basis') == 'locked_period_core'):
        from .construction_theme import theme_pairs
        static_operations = {key: value for key, value in operation_facts.items()
                             if not native_authority or records[key[0]][key[1]]["block_view"]["status"] == "native_static"}
        pairs, pending = theme_pairs(static_operations, records,
            dependencies, available, theme_profile, budget, fusion_proofs,
            continuation=(continuation or {}).get('theme'), should_stop=should_stop, work_state=theme_state)
        if pending is not None:
            return dict(calculation_pending=dict(theme=pending)), operation_facts
    # These facts already exist in the selected finite inventory. Their count
    # is data extent, not missing information. Work is sliced below instead.
    need_count=len({n.need_id for f in rel_facts for n in _needs(f.inputs)}|
        {n.need_id for u in rel_uses for n in _needs(u.inputs)})
    allowance_count=len({n.resource.attributes for f in rel_facts for n in _needs(f.inputs)
        if n.resource.kind=='normal_summon_allowance'})
    fact_total = len(rel_facts) + allowance_count
    scale_full = native_authority and budget.matches >= 64 and budget.updates >= 32 and budget.allocations >= 16
    structural=replace(budget,facts=max(budget.facts,fact_total),
        needs=max(budget.needs,need_count),
        matches=max(budget.matches, need_count * max(1, fact_total)) if scale_full else budget.matches,
        updates=max(budget.updates, (fact_total + len(rel_uses)) * 8) if scale_full else budget.updates,
        allocations=max(budget.allocations, 8192) if scale_full else budget.allocations)
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
    calls = [] if native_authority else _targeted_calls(deck, available, records, dependencies, operation_facts)
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


def _bind_functional_support(facts, projections, available, specs, catalog, context, condition, config, sources,
                             *, native_authority=False):
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
            if not native_authority and grave_rule and semantic["to_zone"] == "grave" and semantic["owner"] == "self":
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
                    tuple(req.source for req in context.relations.uses if req.use_id in group["use_ids"]),
                    native_authority=native_authority))
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


def _bind_automatic_themes(facts, projections, config, condition, sources, *, native_authority=False):
    from .construction_theme import PRIMARY, SECONDARY
    profile = config.get('theme_profile')
    if profile is None:
        return
    if profile['gaps'] and (not native_authority or profile.get("rule_basis") == "locked_period_core"):
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
                    'theme_compatibility', (*source.evidence_refs, *receiver.evidence_refs))
            elif pair.get('derived_goal'):
                facts['use_details'][receiver.use_id]['explicit_task_goal'] = True
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
                _relation_support(capacity, 'automatic-capacity:' + use.use_id, use.scope_id, condition, use.evidence_refs,
                                  native_authority=native_authority)])
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
    native_configurations = []
    for use in bound:
        detail = facts["use_details"].get(use + ":" + scope, {})
        proof = detail.get("inventory_checks", {}).get("native") or {}
        if proof.get("configurations"):
            native_configurations.append(set(proof["configurations"]))
    if len(native_configurations) > 1 and not set.intersection(*native_configurations):
        gap = "native_side_joint_configuration_unwitnessed"
        return {**group, "status": "unknown", "gaps": [*group["gaps"], gap],
                "unknown": [*group.get("unknown", ()), gap],
                "support_expression": ("atom", gap + ":" + digest(sorted(bound)))}
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
        action = operation.get("kind")
        if not action:
            continue
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
        operation = detail.get('operation') or {}
        if operation.get('own_destruction'):
            from .construction_inventory import matches
            refs = use.evidence_refs
            affected = []
            if operation.get('mandatory_trigger') or use.use_id in relevant:
                for target in facts['uses']:
                    if (target.scope_id != use.scope_id or target.use_id not in relevant
                            or not precedes(use.use_id, target.use_id) or precedes(target.use_id, use.use_id)):
                        continue
                    victim = details[target.use_id]
                    zone = victim.get('trigger', {}).get('zone')
                    if zone not in ('field', 'spell_trap', 'pzone'):
                        continue
                    if operation.get('subject') == 'this_card':
                        sources_hit = tuple(sorted(set(use.source_ids) & set(target.source_ids)))
                        if not sources_hit:
                            continue
                        certain = True
                    elif operation.get('whole_group'):
                        location = operation.get('own_location_mask') or 0
                        if not location & (4 if zone == 'field' else 8):
                            continue
                        query = operation.get('selector_query')
                        if query and not matches(facts['card_properties'][str(victim['card_id'])], query):
                            continue
                        sources_hit = target.source_ids
                        certain = True if operation.get('unfiltered_group') else None
                    else:
                        continue
                    key = 'impact:' + digest((use.use_id, target.use_id, 'own_destruction'))
                    applicability = condition(key, certain, 'own_destruction_before_field_use', refs)
                    facts['impacts'].append(UseImpact(key, use.use_id, (target.use_id,),
                        ('base', *target.theme_eligible), ('own_destruction',), refs, applicability,
                        use.scope_id, sources_hit))
                    affected.append(target.use_id)
            facts['unpriced_effects'].append(dict(kind='own_destruction', source_id=use.use_id,
                affected_use_ids=affected, evidence_refs=list(refs)))
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
    if getattr(catalog.assets, "rule_authority", None) == "locked_period_core":
        from .construction_native import NATIVE_EVIDENCE_VERSION, NATIVE_RULE_VERSION
        assets = catalog.assets
        trace = assets.construction_rule_trace
        registration = getattr(assets, "native_registration_source", None)
        return digest(dict(resources=assets.receipt, period=assets.period_context,
                           native_rules=NATIVE_RULE_VERSION, native_evidence=NATIVE_EVIDENCE_VERSION,
                           stock=getattr(registration, "stock_binding", None),
                           trace=trace.binding if trace is not None else None))
    from .effect_mechanisms import SEMANTIC_VERSION
    from .effect_records import EFFECT_RECORD_VERSION, LUA_EFFECT_RECORD_VERSION
    from .effect_blocks import BLOCK_VERSION, BLOCK_REVISION, LUA_BLOCK_REVISION
    binding = dict(cards=catalog.cards_sha256, semantic=SEMANTIC_VERSION,
                   records=EFFECT_RECORD_VERSION, blocks=BLOCK_VERSION, revision=BLOCK_REVISION)
    lua = catalog.lua_binding
    if lua is not None:
        binding.update(lua=lua, records=LUA_EFFECT_RECORD_VERSION, revision=LUA_BLOCK_REVISION)
    if getattr(catalog.assets, "period_context", None) is not None:
        from .construction_native import NATIVE_EVIDENCE_VERSION, NATIVE_RULE_VERSION
        binding.update(native_rules=NATIVE_RULE_VERSION, native_evidence=NATIVE_EVIDENCE_VERSION)
    return digest(binding)


def reference_asset_binding(catalog, deck):
    assets = catalog.assets
    rows = {str(code): assets.rows.get(code) for code in sorted(set(deck.main + deck.extra + deck.side))}
    aliases = {rule_name_id(assets.rows, int(code)) for code, row in rows.items() if row is not None}
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


def _relation_support(row, key, scope, condition, evidence, *, native_authority=False):
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
            if (not native_authority and children.startswith('fact:catalog-text:')
                    and not children.endswith(':turn_event_unobserved')):
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
               "different_name_from_reveal", "subject_ref", "state_conditions", "event_condition"}
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


_ALWAYS_INTERRUPTION_KINDS = frozenset({
    "negate_activation", "negate_effect", "negate_summon",
    "prevent_activation", "prevent_summon", "prevent_special_summon",
    "prevent_effect", "prevent_draw", "prevent_search",
    "special_summon_limit", "banish_replacement", "effect_change", "change_effect",
})
_OPPONENT_DISRUPTION_KINDS = frozenset({
    "destroy", "banish", "send_grave", "return_hand", "return_deck",
    "change_position", "control_change", "take_control", "attach_xyz_material",
    "discard", "hand_rip", "flip_facedown", "shuffle_deck", "release", "tribute",
})


def _is_interruption_use(record, operation, semantics):
    """Classify interruption uses strictly by mechanism/target/trigger, never by card ID or axis."""
    if not operation:
        return False
    kind = (semantics or {}).get("kind") or operation.get("kind") or ""
    owner = (semantics or {}).get("owner") or operation.get("owner")
    if kind in _ALWAYS_INTERRUPTION_KINDS or kind.startswith(("negate_", "prevent_", "disable_")):
        return owner in (None, "opponent", "both")
    if kind in _OPPONENT_DISRUPTION_KINDS:
        return owner in ("opponent", "both")
    if kind == "draw":
        ev = operation.get("event_condition")
        if isinstance(ev, dict) and ev.get("player") == "opponent":
            return True
        trig = (record or {}).get("trigger", {})
        if isinstance(trig, dict) and trig.get("opponent_reactive") is True:
            return True
    return False


def _projected_side_swap(task, deck, assets, projection, extra_ids, specs, context):
    """Propose a legal exchange from projected support; price the resulting inventory separately."""
    from .construction_native import _side_inventory
    from .construction_inventory import matches, query_supported
    # A size-preserving swap cannot complete a partial inventory.
    if any(len(getattr(deck, zone)) != size for zone, size in task.sizes.items()):
        return []
    relation, operation_ids = projection
    functions = defaultdict(set)
    for (code, effect, operation), uid in operation_ids.items():
        if operation is not None and relation['uses'].get(uid, {}).get('status') == 'supported':
            functions[code].add((effect, operation))
    copies = Counter(deck.main + deck.extra)
    support = defaultdict(set)
    side_partners = defaultdict(set)
    for consumer in set(copies) | set(deck.side):
        for effect in specs.get(consumer, ((), ()))[0]:
            for need in effect['requirements']:
                query = need.get('query')
                if not query or not query_supported(query) or any(matches(assets.rows[c], query) for c in copies):
                    continue
                for incoming in set(deck.side):
                    if incoming != consumer and matches(assets.rows[incoming], query):
                        if consumer in copies:
                            support[incoming].add(consumer)
                        else:
                            side_partners[consumer].add(incoming)
    candidates = []
    for incoming in sorted(set(deck.side)):
        zone = 'extra' if incoming in extra_ids else 'main'
        for outgoing in sorted(set(getattr(deck, zone))):
            if incoming == outgoing:
                continue
            priority = len(functions[incoming]) / (copies[incoming] + 1) - len(functions[outgoing]) / copies[outgoing]
            priority += len(support[incoming] - ({outgoing} if copies[outgoing] == 1 else set()))
            partners = side_partners[incoming]
            if partners and len(getattr(deck, zone)) == 1 and all((p in extra_ids) == (incoming in extra_ids) for p in partners):
                continue
            if priority > 0:
                candidates.append((-priority, zone, incoming, outgoing))
    moves = []
    moved_in, moved_out = set(), Counter()
    joint = context and any(c.kind == 'all' for c in context.relations.constraints)
    for _, zone, incoming, outgoing in sorted(candidates):
        if incoming in moved_in or moved_out[outgoing] == copies[outgoing]:
            continue
        if moves and not joint and not any(
                incoming in side_partners[c] or c in side_partners[incoming] for c in moved_in):
            continue
        proposed = [*moves, dict(zone=zone, incoming=incoming, outgoing=outgoing)]
        if assets.accepts(task, _side_inventory(deck, proposed)):
            moves = proposed
            moved_in.add(incoming)
            moved_out[outgoing] += 1
    return moves


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
    native_authority = getattr(catalog.assets, "rule_authority", None) == "locked_period_core"
    profile = config.get('theme_profile')
    if profile and (profile['task_sha256'] != task.sha256 or profile.get('card_texts') and (
            profile.get('cards_sha256') != catalog.cards_sha256
            or not native_authority and any(int(c) not in task.pool or int(c) not in catalog.assets.rows
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
    aliases = {str(c): rule_name_id(catalog.assets.rows, c) for c in codes}
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
    if native_authority:
        facts['inventory_binding'] = reference_asset_binding(catalog, deck)
    facts['card_properties']={str(c):{key:catalog.assets.rows[c].get(key,0) for key in
        ('id','name','type','level','race','attribute','atk','def','setcode')} for c in codes}
    relation_binding=asdict(context.relations) if context is not None else None
    if relation_binding is not None:relation_binding.pop('budget',None)
    native_rules = getattr(catalog.assets, "construction_rules", None)
    requires_route = task.goal["kind"] != "deck_constraints" or "route_goal" in task.goal
    role = ("reference" if layer_evaluation is not None and layer_evaluation["axis"].get("logic") is None
            else "candidate")
    frontier = native_rules.frontier_binding(task, deck, role, policy) if native_rules is not None else None
    query_routes = requires_route or frontier is not None
    binding=digest(dict(task=task.sha256,inventory=inventory,policy=policy,
        assets=facts['asset_version'],normalization=NORMALIZATION_VERSION,
        relations=relation_binding,evidence=None if callable(quality_evidence) else quality_evidence,
        logic=layer_evaluation['axis'].get('logic') if layer_evaluation is not None else None,
        native_frontier=frontier, inventory_binding=facts.get('inventory_binding')))
    if continuation is not None and (continuation.get('version')!='functional-normalization-work-v1'
            or continuation.get('binding')!=binding):
        raise ContractError('normalization continuation belongs to different inputs')
    work=deepcopy(continuation or dict(version='functional-normalization-work-v1',binding=binding,
        asset_version=facts['asset_version'],normalization_version=NORMALIZATION_VERSION,
        native_frontier=frontier,inventory_binding=facts.get('inventory_binding'),
        read_cursor=0,specifications={},projections={},active=None))
    if work_state is not None:
        work_state.clear();work_state.update(work)
    dependencies = InventoryDependencies(catalog, requirement_limit=budget.facts)
    dependencies._specifications={int(c):tuple(value) for c,value in work['specifications'].items()}
    if reuse is not None and (
        reuse.get('asset_version') != facts['asset_version']
        or reuse.get('normalization_version') != NORMALIZATION_VERSION
    ):
        for cache in ('specifications', 'projections', 'family_prices'):
            reuse[cache].clear()
        reuse['asset_version'] = facts['asset_version']
        reuse['normalization_version'] = NORMALIZATION_VERSION
    shared_specs = reuse['specifications'] if reuse is not None else None
    active_codes = codes if "side" in config["required_scope"] else sorted(set(deck.main + deck.extra))
    if native_authority and "rule_sources" not in work:
        from .native_registrations import NativeRegistryError
        source = getattr(catalog.assets, "native_registration_source", None)
        try:
            initialized = source.for_cards(active_codes) if source is not None else {}
        except NativeRegistryError as error:
            initialized = {}
            work["rule_source_error"] = str(error)
        work["rule_sources"] = {str(code): value for code, value in initialized.items()}
    if native_rules is not None and "native_rule_evidence" not in work:
        query_options = {"queries": ()} if native_authority and not query_routes else {}
        native = native_rules.evaluate(task, deck, role=role, policy=policy, should_stop=should_stop,
                                       continuation=work.get("native_query_work"), **query_options)
        if native["status"] == "paused":
            work["native_query_work"] = native["continuation"]
            facts["calculation_pending"] = work
            return facts
        work.pop("native_query_work", None)
        work["native_rule_evidence"] = native
        if work_state is not None:
            work_state["native_rule_evidence"] = native
    records, specs, remaining = {}, {}, budget.facts
    count=0
    while work['read_cursor']<len(codes):
        if remaining<=0 or count>=budget.cards or should_stop is not None and should_stop():
            facts['calculation_pending']=work
            return facts
        code=codes[work['read_cursor']]
        cached = shared_specs.get(code) if shared_specs is not None else None
        if native_authority:
            from .construction_static_rules import static_rule_specs
            declaration = work["rule_sources"].get(str(code))
            effect_specs, materials = [], []
            if declaration is not None:
                if cached is not None:
                    (effect_specs, materials), source_status = cached[1:]
                else:
                    effect_specs, source_status = static_rule_specs(catalog.assets, code, declaration, dependencies)
                    if shared_specs is not None:
                        shared_specs[code] = (catalog.assets.rows[code], (effect_specs, materials), source_status)
                work.setdefault("static_rules", {})[str(code)] = source_status
        elif cached is not None and cached[0] == catalog.assets.rows[code]:
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
    missing_scripts = {}
    static_rules = work.get("static_rules", {})
    if native_authority:
        facts["static_rules"] = deepcopy(static_rules)
        if "rule_source_error" in work:
            facts["rule_source_error"] = work["rule_source_error"]
    if native_rules is not None:
        from .construction_native_settlement import install_execution_contracts
        lua = catalog.assets.effect_lua_source
        if lua is not None:
            missing_scripts = {code: script for code in codes
                               if (script := lua.missing_required_card_script(catalog.assets.rows, code)) is not None}
        facts["native_rule_evidence"] = deepcopy(work["native_rule_evidence"])
        facts["native_rule_evidence"]["authority"] = "locked_period_core"
        classified = {(int(code), digest(row["rule"])) for code, card in static_rules.items()
                      for row in card["registrations"] if row["status"] in ("function", "alternate_trigger")}
        if query_routes:
            install_execution_contracts(facts["native_rule_evidence"], specs, catalog.assets,
                                        dependencies.native_execution_contracts, classified=classified)
        records = {code: tuple(effect["record"] for effect in value[0]) for code, value in specs.items()}

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
    side_plans = work.get('side_plans')
    if deck.side and "side" in config["required_scope"]:
        for direction in config["side_directions"]:
            allowed = {s for s, item in sources.items() if item["zone"] != "side"
                       or task.sizes[item["destination"]] > 0}
            if side_plans is not None:
                from .construction_native import _side_inventory
                moves = side_plans[direction]
                exchanged = _side_inventory(deck, moves)
                allowed = selected['resident'].copy()
                for move in moves:
                    leaving = max(s for s in allowed if sources[s]['zone'] == move['zone']
                                  and sources[s]['card_id'] == move['outgoing'])
                    entering = min(s for s in sources if s not in allowed and sources[s]['zone'] == 'side'
                                  and sources[s]['card_id'] == move['incoming'])
                    allowed.remove(leaving)
                    allowed.add(entering)
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
            if side_plans is not None:
                available[direction] = exchanged
                facts['side_contexts'][direction].update(swaps=moves, deck=exchanged.to_dict())
    if native_authority:
        from .native_registrations import NativeRegistryError

        registration = getattr(catalog.assets, "native_registration_source", None)
        fusion_rows = {record["effect_key"]: (code, record["effect_index"], record["fusion_stock_location"])
            for code, values in records.items() for record in values if "fusion_stock_location" in record}
        ritual_rows = {record["effect_key"]: (code, record["effect_index"])
            for code, values in records.items() for record in values
            if any(op.get("ritual_stock_query") for op in record.get("operations", ()))}
        lua_constants = getattr(getattr(catalog.assets, "effect_lua_source", None), "_constants", None) or {}
        chain_material = lua_constants.get("EFFECT_CHAIN_MATERIAL")
        alternate = bool(chain_material is not None and fusion_rows and any(
            row["rule"]["event"] == chain_material
            for source in static_rules.values() for row in source["registrations"]))
        has_summon_stock = callable(getattr(registration, "summon_stock", None))
        has_fusion_stock = callable(getattr(registration, "fusion_stock", None))
        for scope, view in available.items():
            stock = view.main + view.extra
            f_requests = {key: row for key, row in fusion_rows.items() if row[0] in stock}
            r_requests = {key: row for key, row in ritual_rows.items() if row[0] in stock}
            identity = (tuple(view.main), tuple(view.extra))
            if has_summon_stock and identity not in dependencies.native_summon_stock:
                if should_stop is not None and should_stop():
                    facts["calculation_pending"] = work
                    return facts
                cache = work.setdefault("summon_stock", {})
                key = digest((identity, sorted(f_requests.items()), sorted(r_requests.items()), alternate))
                if key not in cache:
                    try:
                        cache[key] = registration.summon_stock(*identity, f_requests, r_requests, alternate=alternate)
                    except NativeRegistryError as error:
                        facts["rule_source_error"] = str(error)
                        work["rule_source_error"] = str(error)
                        cache[key] = {}
                raw = cache[key]
                if isinstance(raw, dict) and raw:
                    normalized = dict(raw)
                    if isinstance(normalized.get("monster_rules"), dict):
                        normalized["monster_rules"] = {int(k): v for k, v in normalized["monster_rules"].items()}
                else:
                    normalized = {}
                dependencies.native_summon_stock[identity] = normalized
                dependencies.native_fusion_stock[identity] = normalized.get("fusion", {})
            elif not has_summon_stock and has_fusion_stock and f_requests and identity not in dependencies.native_fusion_stock:
                if should_stop is not None and should_stop():
                    facts["calculation_pending"] = work
                    return facts
                cache = work.setdefault("fusion_stock", {})
                key = digest((identity, sorted(f_requests.items()), alternate))
                if key not in cache:
                    try:
                        cache[key] = registration.fusion_stock(*identity, f_requests, alternate=alternate)
                    except NativeRegistryError as error:
                        facts["rule_source_error"] = str(error)
                        work["rule_source_error"] = str(error)
                        cache[key] = {}
                dependencies.native_fusion_stock[identity] = cache[key]
    projections={}
    for scope,view in available.items():
        saved=work['projections'].get(scope)
        if saved is None:
            identical=next((other for other in projections if available[other].main==view.main
                            and available[other].extra==view.extra),None)
            if identical is not None and not native_authority:
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
            projection=scope, native_authority=native_authority)
        if relation.get('calculation_pending'):
            work['active']=dict(scope=scope,work=relation['calculation_pending'])
            facts['calculation_pending']=work
            return facts
        projections[scope]=(relation,operation_facts)
        work['projections'][scope]=dict(relation=relation,
            operation_facts=[[list(key),value] for key,value in operation_facts.items()])
        work['active']=None
    if facts['side_contexts'] and side_plans is None:
        work['side_plans'] = {d: _projected_side_swap(task, deck, catalog.assets, projections[d], extra_ids, specs, context)
                              for d in facts['side_contexts']}
        work['projections'] = {'resident': work['projections']['resident']}
        return normalize_function_uses(task, deck, catalog, policy=policy, budget=budget, context=context,
            layer_evaluation=layer_evaluation, quality_evidence=quality_evidence, continuation=work,
            should_stop=should_stop, work_state=work_state, reuse=reuse)
    relation, operation_facts = projections["resident"]
    for use in context.relations.uses if context is not None else ():
        if use.required:
            row = relation["uses"][use.use_id]
            # A complete joint witness includes every original requirement.
            # Its global return schedule can discharge a subgroup's resource
            # unknown without changing that subgroup's standalone assessment.
            if row["status"] == "unknown" and relation["joint_required"]["status"] == "supported":
                row = relation["joint_required"]
            expr = _relation_support(row, "required:"+use.use_id, "resident", condition, (use.source,),
                                     native_authority=native_authority)
            facts["hard_requirements"].append(dict(requirement_id=use.use_id, origin=use.source, condition=expr))
    if any(u.required for u in (context.relations.uses if context is not None else ())):
        expr = _relation_support(relation["joint_required"], "required:joint", "resident", condition,
                                 ("original-task:" + task.sha256,), native_authority=native_authority)
        facts["hard_requirements"].append(dict(requirement_id="joint_required", origin="original-task:" + task.sha256, condition=expr))
    if requires_route:
        route = task.goal.get("route_goal", task.goal)
        opening = Counter(route["starting_conditions"]["requires_opening_hand"])
        required = {route["card_id"], *task.goal.get("required_activations", ()),
                    *task.goal.get("required_chain_resolutions", ())}
        missing = bool(opening - Counter(deck.main)) or not required <= set(deck.main + deck.extra)
        support = False if missing else None
        if not missing and native_authority:
            from .construction_native_settlement import observed_goal_receipt
            receipt = observed_goal_receipt(route, task.goal, facts["native_rule_evidence"])
            if receipt is not None:
                facts["native_rule_evidence"]["goal_receipt"] = receipt
                support = True
        elif not missing and route['kind'] in ('link_summon', 'ritual_summon', 'effect_resolution'):
            from .basic_cb_inference import static_route_support
            support = static_route_support(route, deck, catalog,
                required_effects=(*task.goal.get('required_activations', ()), *task.goal.get('required_chain_resolutions', ())))
        expr = condition("required:original_goal", support,
            "original_goal_static_support", ("original-task:" + task.sha256,))
        facts["hard_requirements"].append(dict(requirement_id="original_goal", origin="original-task:" + task.sha256, condition=expr))

    special_entries = {}
    fusion_recipients = {scope: {option["target"]
        for row in dependencies.native_fusion_stock.get((tuple(view.main), tuple(view.extra)), {}).values()
        for option in row["options"]} for scope, view in available.items()}
    for zone, cards in inventory.items():
        for code in sorted(set(cards)):
            card_key = f"{zone}:{code}"
            if code not in records:
                facts["coverage_details"][card_key] = dict(status="deferred", reason="normalization_read_budget")
                continue
            effect_specs, materials = specs[code]
            missing_source = missing_scripts.get(code) if zone != "side" or "side" in config["required_scope"] else None
            effect_details = []
            printed_groups = Counter((record.get("scope"), record["effect_index"]) for record in records[code])
            for ri, record in enumerate(records[code]):
                eid = "effect:" + digest(dict(card=aliases[str(code)], text=record["text_sha256"],
                    scope=record.get("scope"), position=record.get("effect_key", str(ri))))
                ref = f"catalog:{code}:{record.get('effect_key', ri)}:{record['text_sha256']}"
                view = record.get("block_view", {})
                static_rule = view.get("status") == "native_static"
                empty_reviewed = view.get("status") in ("flavor", "summon_description", "summon_procedure", "restriction", "cost_only")
                covered = bool(record["operations"]) or empty_reviewed
                # A coarse action does not acknowledge unrelated unparsed text.
                semantic_gaps = [u for u in view.get("unknown", record.get("unknown", ()))
                                 if u in ("no_recognized_function", "unrecognized_operation", "effect_boundary_unknown")]
                if not covered and not semantic_gaps:
                    semantic_gaps = list(record.get("unknown") or ("no_recognized_function",))
                if missing_source:
                    semantic_gaps.append("missing_rule_source")
                effect_details.append(dict(effect_id=eid, effect_ref=ref, status="evaluated" if covered and not semantic_gaps else "unknown",
                    record=deepcopy(record), gaps=semantic_gaps))
                if printed_groups[record.get("scope"), record["effect_index"]] > 1:
                    effect_details[-1]["diagnostics"] = ["repeated_effect_number_scope_unresolved"]
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
                    card_sources = tuple(s for s, item in sources.items() if item["zone"] == zone and item["card_id"] == code)
                    for scope, view in available.items():
                        source_ids = tuple(s for s in card_sources if s in selected[scope])
                        if not source_ids:
                            continue
                        key = uid if scope == "resident" else uid + ":" + scope
                        native = dependencies.witnessed_processing(view, scoped_record, operation, inventory=deck, scope=scope)
                        authoritative = native is not None and native.get("authority") == "native"
                        ritual = None
                        if static_rule:
                            fusion = dependencies.fusion_check(view, code, scoped_record)
                            ritual = dependencies.ritual_check(view, code, scoped_record) if fusion is None else None
                            checked = (dependencies._check(view, requirement_rows, distinct=True)
                                       if fusion is None and ritual is None else None)
                            objects = material = summon_trigger = processing = complete_payment = None
                            if scoped_record.get("type_matched_deck_send"):
                                processing = dependencies.processing_check(view, scoped_record, operation, physical_inventory=deck)
                            used_operation, use_semantics = operation, semantics
                        elif authoritative or native_authority:
                            checked = objects = material = fusion = summon_trigger = processing = complete_payment = None
                            used_operation = _settled_operation(operation, native) if authoritative else operation
                            use_semantics = _function_semantics({"block_view": {}}, used_operation)
                        else:
                            checked = dependencies._check(view, costs, distinct=True) if costs else None
                            summon_trigger = dependencies.summon_trigger_check(code, scoped_record)
                            objects = dependencies._check(view, other)
                            material = dependencies.summon_material_check(view, code)
                            fusion = dependencies.fusion_check(view, code, scoped_record)
                            processing = dependencies.processing_check(view, scoped_record, operation, physical_inventory=deck)
                            complete_payment = dependencies.summon_material_check(view, code, costs=costs) if costs and material else None
                            used_operation, use_semantics = operation, semantics
                        if complete_payment and complete_payment["status"] == "missing" and checked["status"] != "missing" and material["status"] != "missing":
                            complete_payment["status"] = "unknown"
                            complete_payment["reason"] = "cost_material_transfer_order"
                        absent = any(r and r["status"] == "missing" for r in (checked, objects, material, summon_trigger, fusion, ritual, processing))
                        own = condition(key + ":inventory", not absent and set(source_ids) <= selected[scope],
                                        "complete_inventory_requirement", refs)
                        current_relation, operation_facts = projections[scope]
                        if (scope,code) not in special_entries:
                            if native_authority:
                                se_state = current_relation["uses"].get(f"dag:special_entry:{code}")
                                if se_state is not None:
                                    se_status = se_state.get("status")
                                    special_entries[scope, code] = (
                                        True if se_status == "supported" else False if se_status == "missing" else None
                                    )
                                else:
                                    special_entries[scope,code] = True if code in fusion_recipients[scope] else next((
                                        True for receipt in facts["native_rule_evidence"]["receipts"] if query_routes
                                        if not receipt["query"].get("side_swaps")
                                        for case in receipt.get("native_executions", ()) for move in case["operations"]
                                        if move.get("card") == code and move["kind"] in _SPECIAL_SUMMONS
                                        and move["owner"] == "self"), None)
                            else:
                                special_entries[scope,code]=_special_summon_supported(code,view,records,
                                    dependencies,current_relation,operation_facts,physical_inventory=deck)
                        state = current_relation["uses"].get(operation_facts.get((code, ri, oi)), {})
                        support = _relation_support(state, key, scope, condition, refs,
                                                    native_authority=native_authority)
                        # The relation already binds unresolved inventory selectors to their source.
                        transfer = condition(key+":cost_material_transfer", None if complete_payment and complete_payment["status"] == "unknown" else True,
                                             "cost_material_transfer_order", refs)
                        self_condition = _all_support([own, support, transfer])
                        if missing_source:
                            source_ref = "lua:" + missing_source["file"] + ":" + missing_source["scripts_sha256"]
                            self_condition = _all_support([self_condition, condition(key + ":rule_source", None,
                                "missing_rule_source", (*refs, source_ref))])
                        if processing and processing['status'] == 'unknown':
                            self_condition = _all_support([self_condition,
                                condition(key+':processing', None, processing['reason'], refs)])
                        themes, unknown_theme_predicates = [], []
                        for rule in config["theme_rules"] if operation is not None else ():
                            if 'task_goal' in rule['predicate']:
                                continue
                            fields = dict(kind=use_semantics["kind"], from_zone=use_semantics["from_zones"][0] if len(use_semantics["from_zones"]) == 1 else None,
                                to_zone=use_semantics["to_zone"], owner=use_semantics["owner"], reason=use_semantics["reason"],
                                grave_related="grave" in use_semantics["from_zones"] or use_semantics["to_zone"] == "grave" or record["trigger"].get("zone") == "grave")
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
                            contributes=(operation is not None and (not native_authority or static_rule)
                                and not (observed.get("own_destruction") and observed.get("owner") == "self")),
                            is_interruption=(operation is not None and (not native_authority or static_rule)
                                             and _is_interruption_use(record, used_operation, use_semantics)))
                        prior = next((u for u in facts["uses"] if u.use_id == key), None)
                        if prior is None:
                            facts["uses"].append(use)
                        elif prior != use:
                            raise ContractError(f"conflicting function support for card {code}, effect {ri}, processing {oi}")
                        facts["use_details"][key] = dict(effect_id=eid, function_id=family, card_id=code,
                            relation_fact_id=(operation_facts.get((code, ri, oi)) or '').removeprefix('functional:'),
                            semantics=use_semantics, operation=deepcopy(used_operation), trigger=deepcopy(scoped_record["trigger"]),
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
                                ritual=ritual, processing=processing), relation=state)
                        if prerequisites:
                            facts["use_details"][key]["processing_prerequisites"] = deepcopy(prerequisites)
                        if native is not None:
                            facts["use_details"][key]["inventory_checks"]["native"] = deepcopy(native)
                        if authoritative:
                            facts["use_details"][key]["historical_operation"] = deepcopy(operation)
                        if static_rule:
                            facts["use_details"][key]["rule_registration"] = deepcopy(record["rule_registration"])
                        from .construction_theme import configured_primary_goal, function_goal, primary_goal
                        facts['use_details'][key].update(operation_key=(code, ri, oi),
                            goal_id=digest(function_goal(record, operation)) if operation is not None else None)
                        op_req = (next((r for r in checked["requirements"]
                                        if r.get("category") == "operations" and r.get("operation") == operation), None)
                                  if checked else None)
                        if used_operation is not None and used_operation['kind'] in _SPECIAL_SUMMONS:
                            if fusion is not None:
                                facts['use_details'][key]['summoned_card_ids'] = _summoned_inventory(
                                    scoped_record, operation, objects, fusion)
                            elif ritual is not None:
                                facts['use_details'][key]['summoned_card_ids'] = sorted({
                                    option['target'] for option in ritual['options']}
                                    | set(ritual.get('uncovered_targets', ())))
                            elif static_rule:
                                if used_operation.get("subject") == "this_card":
                                    facts['use_details'][key]['summoned_card_ids'] = [code]
                                else:
                                    facts['use_details'][key]['summoned_card_ids'] = (
                                        sorted(op_req["matching_card_ids"]) if op_req is not None else ()
                                    )
                            elif authoritative:
                                facts['use_details'][key]['summoned_card_ids'] = native['observed_card_ids']
                            elif not native_authority:
                                facts['use_details'][key]['summoned_card_ids'] = _summoned_inventory(
                                    scoped_record, operation, objects, fusion)
                        if config.get('theme_profile'):
                            if static_rule:
                                outcomes = (
                                    tuple(row["target"] for row in fusion["options"]) if fusion is not None else
                                    tuple(row["target"] for row in ritual["options"]) if ritual is not None else
                                    op_req["matching_card_ids"] if (op_req is not None and not operation.get("random")) else ()
                                )
                                facts['use_details'][key]['explicit_task_goal'] = configured_primary_goal(
                                    config['theme_profile'], code, use_semantics, outcomes,
                                    record["rule_registration"]["event"], catalog.assets.rows)
                            elif native_authority:
                                facts["use_details"][key]["explicit_task_goal"] = False
                            else:
                                facts['use_details'][key]['explicit_task_goal'] = primary_goal(
                                    config['theme_profile'],code,record,operation,dependencies)
            if native_authority:
                active = zone != "side" or "side" in config["required_scope"]
                declaration = static_rules.get(str(code))
                source_available = missing_source is None and declaration is not None and not declaration["diagnostics"]
                has_unknown_reg = bool(declaration and any(
                    r.get("status") == "unknown" and r.get("rule", {}).get("scope") == "card"
                    for r in declaration.get("registrations", ())
                ))
                all_effects_ok = all(e["status"] == "evaluated" for e in effect_details)
                # Keep non-blocking scope="field" auxiliary registrations from blocking coverage,
                # while refusing to sign off "evaluated" when any card-scope registration or card effect is unknown.
                coverage[card_key] = "unknown" if active and (not source_available or has_unknown_reg or not all_effects_ok) else "evaluated"
            else:
                coverage[card_key] = "evaluated" if not missing_source and all(
                    e["status"] == "evaluated" for e in effect_details) else "unknown"
            details = dict(status=coverage[card_key], effects=effect_details)
            if missing_source:
                details["rule_source"] = dict(status="missing_rule_source", **missing_source)
            elif native_authority and active and not source_available:
                details["reason"] = "native_registration_unavailable"
            facts["coverage_details"][card_key] = details
    if "side" not in config["required_scope"]:
        facts["scope_status"]["side"] = "not_applicable"
    elif deck.side and any(coverage.get(f"side:{code}") != "evaluated" for code in deck.side):
        facts["scope_status"]["side"] = "deferred"
    _bind_functional_support(facts, projections, available, specs, catalog, context, condition, config, sources,
                             native_authority=native_authority)
    _bind_automatic_themes(facts, projections, config, condition, sources, native_authority=native_authority)
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
        if native_authority:
            if set(detail.get("summoned_card_ids", ())).intersection(allowed):
                return True
            native = detail["inventory_checks"].get("native")
            return True if native and set(native["observed_card_ids"]).intersection(allowed) else None
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
        cards = () if getattr(self.catalog.assets, "rule_authority", None) == "locked_period_core" else value.relations.catalog_cards
        return replace(value, relations=replace(value.relations, catalog_cards=cards, budget=RelationBudget(**{
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
            names[rule_name_id(self.binding.assets.rows, code)].append(code)
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
                same_name=rule_name_id(self.binding.assets.rows, code),
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
            {str(c):rule_name_id(self.binding.assets.rows, c) for c in codes},
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
        native_rules = getattr(self.catalog.assets, "construction_rules", None)
        frontier = native_rules.frontier_binding(task, deck, "reference", policy) if native_rules is not None else None
        binding = dict(version=REFERENCE_BINDING_VERSION, assets=reference_asset_binding(self.catalog, deck),
            inputs=digest(dict(task=task.sha256, reference=descriptor, policy=policy, normalization=NORMALIZATION_VERSION,
                relations=relation_binding, evidence=evidence_binding, native_frontier=frontier)))
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
        if "native_rule_evidence" in quality:
            role = "reference" if layer["axis"].get("logic") is None else "candidate"
            self.catalog.assets.construction_rules.record_quality(quality, role)
        return quality, None, None

    def evaluate(self, task, graph, rows, proposals, order, context=None, *, policy=None,
                 quality_evidence=None, should_stop=None, evaluated=None, calculations=None, on_progress=None,
                 comparison_progress=None, _comparisons=None, evaluation_cursor=0, unbound_indices=()):
        """Evaluate before ordering; a budget leaves pending candidates intact."""
        from types import SimpleNamespace
        from .construction_quality import (SUPPORTED_FUNCTIONAL_QUALITY_VERSIONS, functional_quality_config,
            functional_pass_policy, EvaluationComparisons, restore_comparison_progress)
        functional = policy is not None and (policy.get("quality") or {}).get("evaluator_version") in SUPPORTED_FUNCTIONAL_QUALITY_VERSIONS
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
        native_rules = getattr(self.catalog.assets, "construction_rules", None)
        native_authority = getattr(self.catalog.assets, "rule_authority", None) == "locked_period_core"
        for i, row in list(evaluations.items()):
            q = row.get("quality_evaluation")
            if (i not in order or q is None or q["deck_sha256"] != digest(rows[i]["deck"].to_dict())
                    or q["task_sha256"] != task_sha or q["logic_sha256"] != logic_sha
                    or q["policy_sha256"] != policy_sha):
                raise ContractError("saved candidate evaluation binding differs")
            evaluation_comparisons.bind(q)
            if (q.get('evaluation_timed_out') or q['asset_version'] != asset_version
                    or q['normalization_version'] != NORMALIZATION_VERSION
                    or native_authority and q.get('inventory_binding') != reference_asset_binding(self.catalog, rows[i]['deck'])
                    or (native_rules is not None and q.get('native_rule_evidence', {}).get('frontier') !=
                        native_rules.frontier_binding(task, rows[i]['deck'], 'candidate', policy))
                    or not native_authority and any(
                        e['record']['text_sha256'] != self.catalog.card(int(key.split(':')[1])).text_sha256
                        for key, detail in q.get('coverage_details', {}).items() for e in detail.get('effects', ()))):
                del evaluations[i]
        stop_reason = None
        evaluated_now = 0
        reuse = dict(specifications={}, projections={}, family_prices={})
        schedule = order[evaluation_cursor:] + order[:evaluation_cursor]
        next_position = 0
        for position, i in enumerate(schedule):
            next_position = position
            if i in evaluations or (not native_authority and i not in proposals and i not in unbound_indices):
                continue
            if evaluated_now >= self.limit(task, context):
                stop_reason = 'candidate_evaluation_budget'
                break
            stop_reason = should_stop() if should_stop is not None else None
            if stop_reason:
                break
            # The ordinary layer adapter is reused with exactly one candidate.
            # Neither its read budget nor its inventory depends on batch peers.
            deck = rows[i]["deck"]
            if native_authority:
                layer = self._project_layers(task, graph, SimpleNamespace(deck=deck), context)
            elif i in proposals:
                layer = self._project_layers(task, graph, proposals[i], context)
            else:
                inventory_context = context or LayerContext(task, graph, (), relations=RelationContext((), budget=self.budget))
                layer = evaluate_layers(SkeletonSpec(deck, ()), inventory_context, self.catalog)
            quality, work, stop_reason = self.evaluate_inventory(task, deck, layer, context,
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
        native_authority = getattr(self.catalog.assets, "rule_authority", None) == "locked_period_core"
        if native_authority and context is None:
            context = LayerContext(task, graph, (), relations=RelationContext((), budget=self.budget))
            return evaluate_layers(SkeletonSpec(proposal.deck, ()), context, assets=self.binding.assets)
        automatic = context is None
        context = context or self._automatic_context(task, graph, {0: proposal})
        from .construction_inventory import InventoryDependencies
        inventory = InventoryDependencies(self.catalog, requirement_limit=self.budget.facts) if automatic and self.budget.facts else None
        if native_authority and context.relations.catalog_cards:
            context = replace(context, relations=replace(context.relations, catalog_cards=()))
        index = relation_index(None if native_authority else self.catalog, context)
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
