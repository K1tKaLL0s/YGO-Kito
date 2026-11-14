"""Versioned, effect-scoped observations for public planning and model input.

These records retain uncertainty and source text. They are neither legal-action
certificates nor a replacement interpretation of the legacy 18 feature slots.
The versioned coarse view refines processing verbs and payments; unresolved
selectors and conditions remain visible in the same records.
"""
from copy import deepcopy
import re
from collections import Counter, defaultdict

from .rule_references import effect_reference_requests

EFFECT_RECORD_VERSION = "public-effect-records-v4"
LUA_EFFECT_RECORD_VERSION = "public-effect-records-v7"
SUMMARY_VERSION = "public-mechanism-summary-v2"
SUMMARY_FIELDS = (
    "fusion_target", "synchro_target", "xyz_target", "tuner",
    "effects", "costs", "known_cost_quantity", "unknown_cost_quantity",
    "targets", "restrictions", "unknown_effects", "grave_triggers",
    "summon_triggers", "fusion_operations", "special_summon_operations",
    "grave_operations", "recover_operations", "draw_operations", "interaction_operations",
    "from_hand", "from_grave", "to_field", "to_grave", "to_deck",
    "known_limit_maximum", "shared_or_player_limits", "unknown_limits",
    "known_activation_conditions", "self_costs", "opponent_costs",
    "unknown_cost_owner", "unknown_resource_quantity",
)
SUMMARY_WIDTH = len(SUMMARY_FIELDS)


def _public_data(value):
    """Use JSON array shapes in detached records, including legacy zone tuples."""
    if isinstance(value,dict):return {k:_public_data(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [_public_data(v) for v in value]
    return value

_ZONE = {"额外卡组":"extra", "融合卡组":"extra", "手卡": "hand", "场上": "field", "墓地": "grave", "卡组": "deck"}
_PAYMENTS = (
    ("send_grave", re.compile(r"(?:丢弃|舍弃)(?P<quantity>\d+)张手卡"), "hand", "grave", "self"),
    ("send_grave", re.compile(r"从(?P<owner>自己|对方)(?:的)?(?P<zone>手卡|场上|墓地|卡组)"
                              r"(?:把|将|选)?(?P<quantity>\d+)[只张][^，,。；;]{0,60}?送去墓地"), None, "grave", None),
    ("send_grave", re.compile(r"(?:把|将)(?P<owner>自己|对方)(?:的)?(?P<zone>手卡|场上|墓地|卡组)"
                              r"(?:的)?(?P<quantity>\d+)[只张][^，,。；;]{0,60}?送去墓地"), None, "grave", None),
    ("pay_lp", re.compile(r"支付(?P<quantity>\d+)(?P<multiple>的倍数的)?(?:基本分|LP|分)"), None, None, "self"),
)


def _cost_records(effect, *, head=None, self_banish_origin=None):
    """Keep individual explicit payments, without merging different effects."""
    from .effect_blocks import source_zones
    head = effect.trigger.get("source", "") if head is None else head
    head = re.sub(r'[^，,。；;]*(?:场合|之际|成功|时)(?:（[^（）]*）)?(?=[，,。；;]|$)',
                  lambda m:' '*len(m[0]),head)
    # A targeting clause is not part of the preceding payment. Keep the
    # original span of each payment instead of consuming the next "除外".
    head = re.sub(r'(?<!可)以(?!外|上|下|来|后|前|及)[^。；;]*?为对象', '', head).strip('，, ')
    found = []
    for kind, pattern, zone, destination, owner in _PAYMENTS:
        for match in pattern.finditer(head):
            # A trigger describing a discard is not a payment instruction.
            if "场合" in head[match.end():] or "成功" in head[match.end():]:
                continue
            if any(match.start() < end and start < match.end() for start, end, _ in found):
                continue
            groups = match.groupdict()
            controller = {"自己": "self", "对方": "opponent"}.get(groups.get("owner"), owner or "unknown")
            origin = _ZONE.get(groups.get("zone"), zone)
            found.append((match.start(), match.end(), {
                "kind": kind, "reason": "cost", "quantity": int(groups["quantity"]),
                "quantity_status": "explicit", "owner": controller,
                "owner_status": "recognized" if controller != "unknown" else "unknown",
                "from_zones": [origin] if origin else [], "to_zone": destination,
                "resource": "lp" if kind == "pay_lp" else "cards", "source": match[0],
            }))
            if groups.get('multiple'):
                found[-1][2].update(quantity=None,quantity_status='chosen_multiple',unit=int(groups['quantity']))
    # Reuse this single payment record path for the coarse dictionary too.
    # Only the activation head is eligible, never a resolution or a trigger.
    additional = (
        ('banish',r'(?:把|将)(?:自己(?:的)?)?(?P<n>\d+)[只张]手卡(?:里侧)?除外','hand','banished'),
        ('send_grave',r'从(?:自己(?:的)?)?卡组(?:上面|顶端)(?:把|将)?(?P<up_to>最多)?(?P<n>\d+)张卡送去墓地','deck','grave'),
        ('send_grave',r'(?:把|将)?这张卡从手卡(?:丢弃|舍弃)','hand','grave'),
        ('send_grave',r'(?:把|将)?这张卡从手卡送去墓地','hand','grave'),
        ('send_grave',r'(?:从手卡)?(?:丢弃|舍弃)(?P<n>\d+)[只张][^，,。；;]{0,35}','hand','grave'),
        ('detach',r'(?:把|将)?这张卡(?P<n>\d+)个超量素材取除','xyz_material','grave'),
        ('banish',r'(?P<self_grave>(?:把|将)?(?:自己的?)?墓地的这张卡|(?:把|将)?这张卡从(?:自己的?)?墓地'
                  r'|从(?:自己的?)?墓地(?:把|将)这张卡)(?:里侧)?除外','grave','banished'),
        ('banish',r'(?:把|将|从)(?:(?:自己|对方)(?:的)?)?(?:额外卡组|融合卡组|手卡|墓地|场上|卡组)[^，,。；;]{0,70}?除外',None,'banished'),
        ('release',r'(?:把|将)(?:自己(?:的)?)?[^，,。；;]{1,60}解放','field','grave'),
    )
    if self_banish_origin is not None:
        additional += (('banish', r'(?P<self_field>(?:把|将)这张卡)(?:里侧)?除外', self_banish_origin, 'banished'),)
    for kind, pattern, origin, destination in additional:
        for match in re.finditer(pattern,head):
            tail = head[match.end():].split('，',1)[0].split(',',1)[0]
            if re.search(r'场合|成功|时',tail):continue
            # Prefer the more specific form over a legacy broad payment span.
            if any(match.start()<end and start<match.end() for start,end,_ in found):continue
            n=match.groupdict().get('n')
            if n is None:
                count=re.search(r'(\d+)[只张个]',match[0]); n=count[1] if count else None
            this_card = any(match.groupdict().get(k) is not None for k in ('self_grave', 'self_field'))
            if this_card or '这张卡从手卡' in match[0]:n=1
            matched_origin=origin or next((v for k,v in _ZONE.items() if k in match[0]),None)
            origins=source_zones(match[0]) or ([matched_origin] if matched_origin else [])
            matched_owner='opponent' if '对方' in match[0] else 'self'
            found.append((match.start(),match.end(),dict(kind=kind,reason='cost',
                quantity=int(n) if n is not None else None,quantity_status='explicit' if n is not None else 'unknown',
                owner=matched_owner,owner_status='recognized',from_zones=origins,to_zone=destination,
                resource='cards',source=match[0],random=bool(re.search(r'卡组(?:上面|顶端)|随机',match[0])),face_down='里侧' in match[0])))
            if this_card:
                found[-1][2]['subject'] = 'this_card'
            if origin == 'deck' and kind == 'send_grave' and found[-1][2]['random']:
                found[-1][2]['selector_query'] = {'selector': '卡'}
                if match.groupdict().get('up_to') and int(n) > 1:
                    found[-1][2].update(quantity=None, quantity_status='choice', quantity_options=list(range(1, int(n) + 1)))
            options = re.search(r'(\d+)[只张]?(?:或者|或)(\d+)[只张]', match[0])
            if options:
                found[-1][2].update(quantity=None, quantity_status='choice',
                    quantity_options=sorted({int(options[1]), int(options[2])}))
            if origins == ['extra'] and re.fullmatch(
                    r'(?:把|将|从)(?:(?:自己|对方)(?:的)?)?(?:额外卡组|融合卡组)(?:的)?(?:把|将|选)?'
                    r'(?:卡)?\d+[只张]?(?:(?:或者|或)\d+[只张])?(?:里侧(?:表示)?的)?(?:卡)?'
                    r'(?:随机)?(?:里侧(?:表示)?)?除外', match[0]):
                found[-1][2]['selector_query'] = {'selector':'卡'}
                if re.search(r'里侧(?:表示)?的卡', match[0]):
                    found[-1][2]['selector_query']['face_up'] = False
            if re.fullmatch(r'(?:把|将)(?:自己(?:的)?)?\d+[只张]手卡(?:里侧)?除外',match[0]):
                found[-1][2]['selector_query']={'selector':'卡'}
    from .construction_inventory import requirement
    for match in re.finditer(r'[^，,。；;]+',head):
        parsed = requirement(match[0],'costs')
        if parsed and parsed.get('action') in ('送去墓地','除外'):
            found = [(a,b,item) for a,b,item in found if not (a<match.end() and match.start()<b)]
            found.append((match.start(),match.end(),dict(kind='send_grave' if parsed['action']=='送去墓地' else 'banish',
                reason='cost',quantity=parsed['minimum'],quantity_status='explicit',owner=parsed['owner'],
                owner_status='recognized',from_zones=parsed['origins'],to_zone='grave' if parsed['action']=='送去墓地' else 'banished',
                resource='cards',source=match[0],selector_query=parsed['query'],
                **({'origin_states': parsed['origin_states']} if parsed.get('origin_states') else {}),
                **({'exclude_source_copy':True} if parsed.get('exclude_source_copy') else {}))))
    result = [item for _, _, item in sorted(found)]
    for cost in effect.costs:
        if any(item["source"] in cost.get("source", "") or cost.get("source", "") in item["source"] for item in result):
            continue
        item = deepcopy(cost)
        source = item.get("source", "")
        if source and source not in head:
            continue
        owner = "opponent" if "对方" in source else "self" if "自己" in source else "unknown"
        item.update(owner=owner, owner_status="recognized" if owner != "unknown" else "unknown",
                    quantity_status="explicit" if item.get("quantity") is not None else "unknown",
                    resource="cards", to_zone="grave" if item["kind"] == "send_grave" else None)
        result.append(item)
    from .effect_text import merge_payments
    result = merge_payments(result,head)
    for index, item in enumerate(result):
        item.update(cost_index=index, effect_index=effect.index)
    return result


def _targets(head):
    """Separate complete target phrases from conditions and payments."""
    from .effect_blocks import source_zones
    rows=[]
    for match in re.finditer(r'(?<!可)以(?!外|上|下|来|后|前|及)([^。；;]+?)为对象',head):
        raw=match[1]
        if raw == '攻击怪兽':
            rows.append(dict(kind='target',selector='怪兽',selector_query={'type':1},
                zones=['field'],quantity=1,owner='opponent',source=match[0]))
            continue
        masked=re.sub(r'[「『][^」』]*[」』]','',raw)
        owners=set(re.findall(r'自己|对方|双方',masked))
        owner={'自己':'self','对方':'opponent','双方':'both'}.get(next(iter(owners)), 'unknown') if len(owners)==1 else 'unknown'
        amounts=re.findall(r'(\d+)[只张]',masked)
        zones=source_zones(raw) or source_zones('从'+raw)
        if not zones and re.match(r'^除外(?:的|状态)',raw):zones=['banished']
        selector=re.sub(r'^(?:(?:自己|对方|双方)(?:的)?|(?:墓地|手卡|卡组|场上|除外状态|除外)(?:的)?|\d+[只张])+','',raw)
        rows.append(dict(kind='target',selector=selector,zones=zones,
            quantity=int(amounts[0]) if len(amounts)==1 else None,owner=owner,source=match[0]))
    return rows


def _absence_condition(text):
    from .construction_inventory import selector
    match = re.fullmatch(r'(?:(自己[·、]对方回合)[，,])?自己(场上|墓地)没有(.+?)存在的场合', text)
    if match:
        query = selector(match[3])
        if query:
            return dict(kind='absence', owner='self', zone=_ZONE[match[2]], query=query,
                timing='before_payment', maximum=0, source=text,
                event='either_turn' if match[1] else 'conditional_activation')
    return None


def _excavation_processing(record):
    """Bind a revealed set, its selected subset and its remaining entities."""
    operations = record['operations']
    reveals = [op for op in operations if op['kind']=='reveal_deck']
    if len(reveals)!=1:
        return
    reveal = reveals[0]
    paid = re.fullmatch(r'把除外数量的卡从自己卡组上面翻开',reveal['source'])
    fixed = (re.fullmatch(r'从自己卡组上面把(\d+)张卡翻开',reveal['source']) or
        re.fullmatch(r'从自己卡组上面翻开(\d+)张(?:卡)?',reveal['source']))
    returned = re.fullmatch(r'从自己卡组上面翻开(\d+)张并回到卡组',reveal['source'])
    paid = bool(paid and len(record['costs'])==1 and record['costs'][0]['kind']=='banish')
    if paid or fixed:
        reveal.update(from_zones=['deck'],owner='self',random=True)
        if paid:reveal['quantity_binding']=dict(cost_index=record['costs'][0]['cost_index'],divisor=1)
        else:reveal['quantity']=int(fixed[1])
        chosen = [op for op in operations if re.fullmatch(r'从那之中选(\d+)张加入手卡',op['source'])]
        leftovers = [op for op in operations if re.fullmatch(r'剩下的卡(?:用喜欢的顺序)?回到卡组(?:下面)?',op['source'])]
        if len(chosen)==1 and any(op['kind']=='return_deck' for op in leftovers):
            choice=chosen[0]
            count=int(re.search(r'选(\d+)张',choice['source'])[1])
            choice.pop('selector',None);choice.pop('selector_query',None)
            choice.update(from_zones=['deck'],to_zone='hand',owner='self',quantity=count,random=True,
                selection_method='choose_from_excavated',selection_group=reveal['block_id'])
            reveal.update(processing_role='auxiliary',selection_group=reveal['block_id'])
            for op in leftovers:
                op.update(processing_role='auxiliary',selection_group=reveal['block_id'],
                    from_zones=['deck'],to_zone='deck',owner='self',random=True)
                if '下面' in op['source']:op['deck_position']='bottom'
                if '喜欢的顺序' in op['source']:op['placement_order']='chosen'
                if paid:op['quantity_binding']=dict(cost_index=record['costs'][0]['cost_index'],divisor=1,subtract=count)
                else:op['quantity']=int(fixed[1])-count
    if returned:
        attack = [op for op in operations if re.fullmatch(
            r'这个回合这张卡可以作出最多有所翻开之中的调整数量的攻击',op['source'])]
        if len(attack)==1:
            amount=int(returned[1])
            attack[0].update(quantity=1,owner='self',subject='this_card',
                amount_rule=dict(kind='revealed_tuner_count',maximum=amount),
                outcome_requirement=dict(query={'type_all':0x1001},minimum=2,origin='deck',owner='self'))
            for op in operations:
                if op['source']==reveal['source']:
                    op.update(processing_role='auxiliary',selection_group=reveal['block_id'],
                        quantity=amount,from_zones=['deck'],owner='self',random=True)
    auxiliary={op['block_id'] for op in operations if op.get('processing_role')=='auxiliary'}
    for op in operations:
        if op.get('depends_on'):
            op['depends_on']=[ref for ref in op['depends_on'] if ref not in auxiliary]


def _bind_revealed_summon(record):
    from .construction_inventory import requirement
    operations = record['operations']
    for reveal, banish, summon in zip(operations, operations[1:], operations[2:]):
        if (reveal['kind'] != 'reveal' or reveal.get('from_zones') != ['hand'] or reveal.get('quantity') != 1
                or reveal.get('owner') != 'self' or not reveal.get('selector_query')
                or banish['kind'] != 'banish' or summon['kind'] != 'normal_summon'
                or banish['block_id'] not in summon.get('depends_on', ())
                or not re.fullmatch(r'(?:给人观看|展示)的怪兽召唤', summon['source'])):
            continue
        distinct = re.fullmatch(r'和(?:给人观看|展示)的怪兽卡名不同的(1张.+?)从卡组除外', banish['source'])
        if not distinct:
            continue
        selected = requirement('把' + distinct[1] + '从卡组除外', 'operations')
        if selected is None:
            continue
        reveal['processing_role'] = 'auxiliary'
        reference = reveal['block_id']
        banish.update(selector_query=selected['query'], from_zones=['deck'], to_zone='banished',
                      quantity=1, owner='self', random=False, different_name_from_reveal=reference)
        summon.update(selector_query=deepcopy(reveal['selector_query']), from_zones=['hand'], to_zone='field',
                      quantity=1, owner='self', random=False, subject_ref=reference, selection_method='revealed_card')


def _bind_hand_send_deck_summon(record, body, blocks):
    """Bind the complete fixed hand-to-GY, then Deck-summon clause."""
    operations, costs = record['operations'], record['costs']
    if (len(operations) != 2 or record['targets'] or record['block_view']['alternatives']
            or len(costs) != 1 or costs[0].get('quantity') != 1
            or costs[0].get('to_zone') not in ('grave', 'banished') or costs[0].get('quantity_options')):
        # The activation consumes one card, which cannot supply a later
        # hand or Deck selection. Other payment contracts stay separate.
        return
    send, summon = operations
    if (send['kind'] != 'send_grave' or send.get('to_zone') != 'grave'
            or summon['kind'] != 'special_summon' or summon.get('from_zones') != ['deck']
            or summon.get('to_zone') != 'field' or summon.get('owner') != 'self'
            or summon.get('random') is not False
            or not summon.get('selector_query')
            or any(op['phase'] != 'resolution' or op.get('optional') or op.get('choice') for op in operations)):
        return
    selection = re.fullmatch(r'选自己(?:的)?([1-9][0-9]*)张手卡送去墓地', send['source'])
    if not selection or not re.fullmatch(
            re.escape(send['source']) + r'[，,]\s*' + re.escape(summon['source']) + r'[。．.]?', body.strip()):
        return
    quantity = int(selection[1])
    if send.get('quantity') not in (None, quantity):
        return
    # The second movement is contingent on this card reaching the GY. The
    # hand movement is part of the summon processing, with its own entity.
    movement = dict(from_zones=['hand'], owner='self', selector_query={'selector': '卡'},
                    quantity=quantity, random=False)
    send.update(movement, processing_role='auxiliary', observed_operation=deepcopy(send))
    blocks[send['block_id']]['qualifiers'].update(deepcopy(movement))
    summon['depends_on'] = [send['block_id']]


def _xyz_overlay_procedure(record, row):
    from .construction_inventory import selector
    view = record['block_view']
    if len(view['procedure_blocks']) != 1 or record['operations'] or record['costs'] or record['targets']:
        return None
    block, = view['procedure_blocks']
    if block['kind'] != 'xyz_summon' or block['phase'] != 'summon_procedure':
        return None
    source = block['source']
    clause = re.fullmatch(
        r'(?:这张卡|「(?P<subject>[^」]+)」)'
        r'(?:(?P<battle>在超量怪兽进行过战斗的回合)有(?P<battle_count>\d+)次|'
        r'(?P<main2>在自己主要阶段2)有(?P<main2_count>\d+)次|1回合(?P<turn_count>\d+)次)?'
        r'也能在自己场上的(?P<selector>[^。；;，,]+?)上面(?:把这张卡)?重叠来超量召唤[。.]?', source)
    if clause is None or clause['subject'] not in (None, row.get('name')):
        return None
    query = selector(clause['selector'])
    if query is None:
        return None
    remainder = record['source_text'].replace(source, '', 1)
    for description in view['description_blocks']:
        if description['kind'] == 'printed_materials':
            remainder = remainder.replace(description['source'], '', 1)
    if remainder.strip(' \r\n\t。.'):
        return None
    condition = ('xyz_monster_battled_this_turn' if clause['battle'] else
                 'own_main_phase_2' if clause['main2'] else 'unconditional')
    maximum = clause['battle_count'] or clause['main2_count'] or clause['turn_count']
    procedure = dict(kind='xyz_overlay', source=source, from_zone='extra', to_zone='field',
        quantity=1, starts_chain=False, condition={'kind': condition}, transfers_xyz_materials=True,
        material=dict(query=query, minimum=1, source=clause['selector'], origin='field',
            owner='self', category='material', summon_type='xyz'))
    if maximum:
        procedure['per_turn_maximum'] = int(maximum)
    block['qualifiers'].update(deepcopy(procedure))
    return procedure


def _refine_record(record,row,head,body,mode):
    """Refine public observations; leave the checkpoint's legacy features intact."""
    from .effect_blocks import source_zones
    grave_self_payment = False
    for cost in record['costs']:
        if cost.get('subject') == 'this_card' and cost['from_zones']:
            grave_self_payment |= cost['from_zones'] == ['grave']
            cost.update(source_card_id=record['card_id'],
                selector_query={'predicate': {'field': 'card_ids', 'value': [record['card_id']]}})
        if cost.get('exclude_source_copy'):
            cost['source_card_id']=record['card_id']
        if re.fullmatch(r'(?:把|将)?这张卡从手卡(?:送去墓地|丢弃|舍弃)',cost.get('source','')):
            cost['selector_query']={'predicate':{'field':'card_ids','value':[record['card_id']]}}
    targets=_targets(head)
    if not targets:
        for target in record['targets']:
            targets.extend(_targets(target.get('source','')) or [dict(target,owner=target.get('owner','unknown'))])
    record['targets']=targets
    condition=head
    for item in (*record['costs'],*targets):
        condition=condition.replace(item['source'],'',1)
    condition=condition.strip('，,：:。 ')
    # The leading counter qualifies this effect, rather than its activation
    # state. Remove only the exact clause recognized by the shared counter.
    for limit in record['count_limits']:
        if limit.get('status') == 'known' and limit.get('scope') == 'this_card_effect':
            condition = re.sub(r'^'+re.escape(limit['source'])+r'(?:[，,]\s*|$)', '', condition)
    equipment = None
    if row.get('type',0)&0x40000:
        equip = re.match(r'([^。]+)才能装备[。.]', record['source_text'])
        if equip:
            from .construction_inventory import selector
            text = equip[1]
            legacy = re.fullmatch(r'名字带有「([^」]+)」的(?:(\d+)星的)?怪兽', text)
            if legacy:
                text = (legacy[2]+'星的' if legacy[2] else '')+'「'+legacy[1]+'」怪兽'
            query = selector(text)
            if query:
                equipment = dict(query=query, minimum=1, source=equip[0], origin='field', owner='self')
                record['equipment_condition'] = equipment
                record.setdefault('activation_requirements', []).append(equipment)
    events={'自己主要阶段':'own_main_phase','自己·对方回合':'either_turn',
        '自己或者对方回合':'either_turn','对方回合':'opponent_turn',
        '这张卡被效果送去墓地的场合':'sent_to_grave',
        '这张卡从场上送去墓地的场合':'sent_to_grave',
        '这张卡特殊召唤成功的场合':'special_summon',
        '这张卡召唤成功的场合':'normal_summon',
        '对方对怪兽的召唤成功的场合':'opponent_normal_summon',
        '这张卡召唤·特殊召唤成功的场合':'normal_or_special_summon',
        '这张卡反转的场合':'flip',
        '魔法·陷阱卡发动时':'spell_trap_activation',
        '对方把场上的怪兽的效果发动时':'opponent_field_monster_effect_activation'}
    def known_event(text):
        if text in events:return events[text]
        if text == '这张卡上级召唤成功的场合':
            record['trigger'].update(zone='field', summon_kind='tribute_summon', controller='self')
            return 'tribute_summon'
        recovery = re.fullmatch(r'这张卡除外中的状态[，,]自己场上有(.+?)召唤的场合', text)
        tribute = re.fullmatch(r'这张卡在墓地存在的状态[，,]自己对(.+?)的上级召唤成功的场合', text)
        if recovery or tribute:
            from .construction_inventory import selector
            query = selector((recovery or tribute)[1])
            if query:
                record['trigger'].update(zone='banished' if recovery else 'grave', controller='self',
                    event_selector=query, event_zone='field',
                    summon_kind='normal_summon' if recovery else 'tribute_summon')
                record.setdefault('activation_requirements', []).append(dict(query=query, minimum=1, source=text,
                    origin='hand', owner='self', exclude_source_copy=True, source_card_id=record['card_id']))
                return 'own_monster_normal_summon' if recovery else 'own_monster_tribute_summon'
        destruction = re.fullmatch(r'(自己(?:的)?场上的这张卡|这张卡(?:从(?:自己(?:的)?)?场上)?)'
            r'被(?P<method>战斗[·、]效果|战斗|效果)?破坏(?:并)?送去墓地(?:的场合|时)', text)
        if destruction:
            if '场上' in destruction[1]:
                record['trigger']['origin'] = 'field'
            method = destruction['method']
            if method in ('战斗', '效果'):
                record['trigger']['destruction_method'] = 'battle' if method == '战斗' else 'effect'
            return 'destroyed_and_sent_to_grave'
        main_start = re.fullmatch(r'(自己|对方)(?:的)?主要阶段([12])开始时', text)
        if main_start:
            return ('own' if main_start[1]=='自己' else 'opponent')+'_main_phase_'+main_start[2]+'_start'
        phase=re.fullmatch(r'(自己|对方|自己[·、]对方|自己或者对方)(?:的)?(准备|主要|结束)阶段',text)
        if phase:
            return {'自己':'own','对方':'opponent'}.get(phase[1],'either')+'_'+{'准备':'standby','主要':'main','结束':'end'}[phase[2]]+'_phase'
        response=re.fullmatch(r'(自己|对方)?(?:的)?怪兽的效果[·、]魔法[·、]陷阱卡发动时',text)
        if response:
            return {'自己':'own','对方':'opponent'}.get(response[1],'either')+'_card_or_monster_effect_activation'
        if text == '要让场上的卡破坏的效果的发动时':
            return 'card_destruction_effect_activation'
        if text == '对方的攻击宣言时':
            return 'opponent_attack_declaration'
        if text == '对方怪兽进行战斗的攻击宣言时':
            return 'attack_declaration_involving_opponent_monster'
        if text in ('陷阱卡发动时，连锁那个发动才能把这个效果在墓地',
                    '陷阱卡发动时,连锁那个发动才能把这个效果在墓地'):
            record['trigger'].update(zone='grave', chain_relation='direct_response')
            return 'trap_card_activation'
        returned = re.fullmatch(r'这个([①②③④⑤⑥⑦⑧⑨⑩])的效果除外的回合的结束阶段', text)
        if returned:
            record['trigger'].update(related_effect_index='①②③④⑤⑥⑦⑧⑨⑩'.index(returned[1])+1,
                related_operation='banish', zone='banished')
            return 'effect_banished_end_phase'
        return None
    event=known_event(condition)
    absent = _absence_condition(condition)
    if absent:
        record['activation_state_conditions'] = [absent]
        event = absent['event']
    if condition=='可以' and record['block_view'].get('alternatives'):
        condition=''  # “可以从以下效果选择1个发动” is the complete shared boundary.
    presence = re.fullmatch(r'(?:(场上有怪兽召唤·特殊召唤的场合)[，,]若)?自己场上有(.+?)存在(?:的场合)?(?:[，,](.+))?', condition)
    if presence:
        from .construction_inventory import selector
        query = selector(presence[2])
        timing=known_event(presence[3]) if presence[3] else ('monster_summoned_on_field' if presence[1] else 'conditional_activation')
        if query and timing:
            event = timing
            record['activation_requirements'] = [dict(query=query, minimum=1, source=condition,
                origin='field', owner='self')]
    ordinary_spell=(mode=='unmarked' and row.get('type',0)&2 and not row.get('type',0)&(0x20000|0x40000|0x80000)
        and not re.search(r'(?:场合|时|阶段|作为代价|才能|支付)',body.split('。',1)[0]))
    ordinary_trap = (mode == 'unmarked' and row.get('type', 0) == 4
        and re.fullmatch(r'从(?:自己)?卡组把\d+张陷阱卡送去墓地[。.]?', body))
    if ordinary_spell or ordinary_trap or equipment:
        event = 'card_activation'
    if event == 'own_monster_tribute_summon':
        for cost in record['costs']:
            if cost['source'] == '把这张卡除外':
                cost.update(kind='banish', from_zones=['grave'], to_zone='banished', quantity=1,
                    quantity_status='explicit', owner='self', owner_status='recognized', random=False,
                    selector_query={'predicate':{'field':'card_ids','value':[record['card_id']]}})
    if (mode=='activated' and (event or not condition)) or ordinary_spell or ordinary_trap or equipment:
        event=event or ('own_main_phase' if grave_self_payment or row.get('type',0)&1 else 'card_activation')
        record['trigger'].update(event=event,reason='effect' if event=='sent_to_grave' else 'not_applicable',
            additional_conditions='none_in_recognized_activation_clause')
        if event in ('sent_to_grave', 'destroyed_and_sent_to_grave'):record['trigger']['zone']='grave'
        if event=='sent_to_grave' and '被效果' not in condition:record['trigger']['reason']=None
        elif event in ('special_summon','normal_summon','normal_or_special_summon'):record['trigger']['zone']='field'
        elif row.get('type', 0) & 0x80000 and event in ('own_main_phase', 'opponent_normal_summon'):
            record['trigger']['zone'] = 'field'
        if event == 'opponent_normal_summon':
            record['trigger'].update(controller='opponent', event_zone='field', summon_kind='normal_summon')
        record['conditions'].update(status='recognized',additional_conditions='none_in_recognized_activation_clause')
        record['knowledge'].update(activation_boundary='recognized',costs='observed' if record['costs'] else 'none_in_recognized_activation_clause',
            targets='observed' if targets else 'none_in_recognized_activation_clause')
        record['unknown']=[v for v in record['unknown'] if v not in (
            'activation_boundary','activation_condition','additional_activation_conditions','cost_or_condition')]
    if grave_self_payment:
        record['trigger']['zone'] = 'grave'
    # No printed count clause means no printed once-per-turn limit, rather
    # than an unknown counter. An unrecognized count clause stays unknown.
    from .effect_count_limits import _count_clauses,parse_count_limits
    printed=row.get('desc','')
    if re.search(r'【怪兽(?:效果|描述)】',printed):
        parts=re.split(r'【怪兽(?:效果|描述)】',printed,maxsplit=1)
        printed=parts[0] if record.get('scope')=='pendulum' else parts[1]
    prelude=re.split(r'[①②③④⑤⑥⑦⑧⑨⑩]\s*[：:]',printed,maxsplit=1)[0]
    # Structural activation locks in the shared prelude also qualify the
    # numbered effect. The legacy scanner does not observe this wording.
    from .effect_block_rules import structural_records
    for rule in structural_records(prelude,row,record.get('scope','monster'))[0]:
        referenced=re.search(r'(?:这个卡名|这张卡)的([①②③④⑤⑥⑦⑧⑨⑩]+)的?效果',rule['source'])
        if referenced and record['effect_index'] not in ['①②③④⑤⑥⑦⑧⑨⑩'.index(v)+1 for v in referenced[1]]:
            continue
        rule.setdefault('block_id',record['effect_key']+':restriction:prelude:'+str(len(record['card_restrictions'])))
        rule.setdefault('group',record['effect_key'])
        prior = next((r for r in record['card_restrictions']
                      if r['kind'] == rule['kind'] and r['source'] == rule['source']), None)
        if prior is None:
            record['card_restrictions'].append(rule)
        elif rule.get('condition') in ('source_clause', 'this_card_in_zone', 'this_card_in_monster_zone'):
            prior.update({key: rule[key] for key in ('condition', 'from_zones') if key in rule})
    for lock in re.finditer(r'((?:这个卡名|这张卡)的([①②③④⑤⑥⑦⑧⑨⑩]+)的?效果1回合各能使用\d+次[，,]'
                            r'这些效果发动的回合[，,]自己不能(?:把怪兽)?特殊召唤)(?:[。\n]|$)', prelude):
        indices = ['①②③④⑤⑥⑦⑧⑨⑩'.index(i) + 1 for i in lock[2]]
        if record['effect_index'] in indices:
            restriction = dict(kind='cannot_special_summon', source=lock[1], scope='player', controller='self',
                               condition='effect_activation', duration='turn', whole_turn=True,
                               tag={'dimension':'restriction','value':'特殊召唤限制'},
                               block_id=record['effect_key']+':restriction:prelude',group=record['effect_key'])
            record['restrictions'].append(restriction)
            record['block_view']['restrictions'].append(deepcopy(restriction))
    count_words=r'(?:1|１|一)回合|决斗中.*(?:次|度)'
    reviewed={limit['source'] for index in range(1,11) for limit in parse_count_limits(index,prelude,'')
        if limit['status']=='known'} if re.search(count_words,prelude) else set()
    reviewed.update(limit['source'] for limit in record['count_limits'] if limit['status'] == 'known')
    for restrictions, field in ((record, 'restrictions'), (record, 'card_restrictions'),
                                (record['block_view'], 'restrictions')):
        restrictions[field] = [rule for rule in restrictions[field]
            if rule['kind'] != 'activation_count_limit'
            or not all(part.strip() in reviewed for part in re.split(r'[，,]', rule['source']))]
    has_count=bool(re.search(count_words,record['source_text']) or any(
        re.search(count_words,clause) and clause not in reviewed for clause in _count_clauses(prelude)))
    if not has_count or record['count_limits'] and all(c['status']=='known' for c in record['count_limits']):
        record['unknown']=[v for v in record['unknown'] if v!='count_limit']
    from .construction_inventory import requirement
    blocks={b['block_id']:b for b in record['block_view']['blocks']}
    inline={}
    for op in record['operations']:

        complete_source=blocks.get(op.get('block_id'),{}).get('source',op.get('source',''))
        selection_source = complete_source.removeprefix('可以') if op.get('optional') else complete_source
        parsed=requirement(selection_source,'operations')
        if parsed and op['kind'] in ('send_grave','search_or_recover','search','recover','add_hand',
                'return','return_deck','return_extra_deck','return_hand','banish','release','special_summon',
                'normal_summon','tribute_summon','reveal','add_extra'):
            op.update(source=complete_source, selector_query=parsed['query'],quantity=parsed['minimum'],
                from_zones=parsed['origins'],owner=parsed['owner'],random=False)
            if len(parsed['actions'])>1:inline.setdefault(complete_source,[]).append(op)
        source=op.get('source','')
        if op['kind'] == 'destroy' and re.fullmatch(r'(?:把|将)?这张卡破坏', source):
            op.update(subject='this_card', quantity=1, owner='self', random=False)
        if op['kind'] in ('reveal_deck','return_deck','reorder_deck','search_or_recover','extra_attack'):
            # A legacy short movement span cannot discard its complete set
            # reference, quantity rule or selection instruction.
            op['source']=complete_source
            source=complete_source
        different = re.search(r'和那只怪兽卡名不同的',complete_source)
        if different:
            candidate = complete_source.replace(different[0],'',1)
            if re.match(r'^\d+[只张]',candidate):candidate='把'+candidate
            parsed_reference = requirement(candidate,'operations')
            if parsed_reference and len(record['costs'])==1:
                op.update(source=complete_source,selector_query=parsed_reference['query'],
                    from_zones=parsed_reference['origins'],quantity=parsed_reference['minimum'],
                    owner=parsed_reference['owner'],random=False,different_name_from_cost=record['costs'][0]['cost_index'])
        generated = re.fullmatch(r'在自己场上把(\d+)只「([^」]+衍生物)」[（(]'
            r'([^·]+族)·(地|水|炎|风|光|暗|神)·(\d+)星·攻/守(\d+)[）)]特殊召唤', complete_source)
        if generated and op['kind']=='special_summon':
            from .effect_mechanisms import RACES
            if generated[3] in RACES:
                op.update(source=complete_source, from_zones=[], owner='self', quantity=int(generated[1]),
                    random=False, generation=dict(kind='token', name=generated[2], race=RACES[generated[3]],
                        attribute={'地':1,'水':2,'炎':4,'风':8,'光':16,'暗':32,'神':64}[generated[4]],
                        level=int(generated[5]), atk=int(generated[6]), **{'def':int(generated[6])}))
        placement = re.fullmatch(r'(?:可以再|可以)?从卡组把(\d+)张「([^」]+)」在自己的魔法与陷阱区域表侧表示放置',
            complete_source)
        if placement and op['kind']=='place':
            op.update(source=complete_source, selector_query={'exact_name':placement[2]},
                quantity=int(placement[1]), from_zones=['deck'], to_zone='field', owner='self',random=False)
        for connector in record['block_view'].get('connectors', ()):
            if connector.get('target')==op.get('block_id'):
                state = _absence_condition(connector.get('condition_source',''))
                if state:
                    op.setdefault('state_conditions',[]).append(dict(state,timing='before_operation'))
        refers=bool(re.match(r'(?:(?:把|将|给|让|选|选择|破坏|除外|装备|特殊召唤)\s*)?'
            r'(?:那(?:\d+)?(?:张|只|些)|作为对象|对象的)',source))
        explicit_origins=source_zones(source)
        if explicit_origins and re.search(r'同名怪兽|攻击力以下|守备力以下|原本的种族|原本种族',source):refers=False
        exact_target=(len(targets)==1 and targets[0].get('quantity') is not None and (
            targets[0]['quantity']==1 or re.search(r'那些|对象的',source)))
        if refers and targets and not exact_target:
            op.update(quantity=None,owner='unknown')
            record['unknown'].append('ambiguous_target_reference')
        if refers and exact_target:
            target=targets[0]
            op['target_ref']=0
            op['selector']=target['selector']
            op['from_zones']=explicit_origins or list(target['zones'])
            op['quantity']=target['quantity']
            if not re.search(r'自己|对方|双方',re.sub(r'「[^」]*」','',source)):
                op['owner']=target['owner']
        if (not targets and source=='那张卡回到持有者卡组' and op['kind']=='return_deck'
                and event and event.endswith('_activation') and any(
                    previous['kind']=='negate' and previous.get('order',0)<op.get('order',0)
                    for previous in record['operations'])):
            op.update(subject='activated_card',quantity=1,owner='both',random=False)
        if '这张卡' in source and op['kind'] in ('special_summon','send_grave','banish','return_hand'):
            op.setdefault('selector_query',{'predicate':{'field':'card_ids','value':[record['card_id']]}})
            if op.get('quantity') is None:op['quantity']=1
            if op.get('owner') in (None,'unknown'):op['owner']='self'
            if not op.get('from_zones'):op['from_zones']=source_zones(source)
            if not op.get('from_zones') and source.startswith('场上的这张卡'):
                op['from_zones'] = ['field']
            if (op['kind']=='special_summon' and record['trigger'].get('event')=='sent_to_grave'
                    and not source_zones(source)):
                op['from_zones']=['grave']
            if op['kind']=='special_summon' and event=='effect_banished_end_phase':
                op['from_zones'] = ['banished']
        if event == 'own_monster_normal_summon' and source == '这张卡加入手卡' and op['kind'] == 'search_or_recover':
            op.update(selector_query={'predicate':{'field':'card_ids','value':[record['card_id']]}},
                      quantity=1, owner='self', from_zones=['banished'], to_zone='hand', random=False)
        if op['kind'] == 'destroy' and source == '那个效果无效并破坏' and event == 'card_destruction_effect_activation':
            op.update(subject='activated_card', quantity=1, owner='both', random=False)
        if op['kind']=='negate' and source=='那个效果无效并破坏' and event=='card_destruction_effect_activation':
            op.update(subject='activated_effect', quantity=1, owner='both')
        if op['kind']=='negate_attack' and source=='那次攻击无效' and event=='opponent_attack_declaration':
            op.update(subject='declared_attack',quantity=1,owner='opponent')
        if op['kind']=='draw':
            ratio = re.search(r'除外的卡每有(\d+)张', body)
            payments = [c for c in record['costs'] if c['kind']=='banish']
            if ratio and len(payments)==1:
                op['quantity_binding'] = dict(cost_index=payments[0]['cost_index'], divisor=int(ratio[1]))
        if op['kind'] == 'stats':
            scaled = re.fullmatch(r'这张卡的攻击力(?:直到回合结束时)?上升'
                r'因(?:为)?这个效果(?:的)?发动(?:而)?送去墓地的数量[×x](\d+)', complete_source)
            payments = [c for c in record['costs'] if c['kind'] == 'send_grave' and c.get('to_zone') == 'grave']
            if scaled and len(payments) == 1:
                op['amount_rule'] = dict(kind='per_payment_card', cost_index=payments[0]['cost_index'],
                    multiplier=int(scaled[1]))
        if equipment:
            if op['kind']=='stats' and re.fullmatch(r'装备怪兽的原本攻击力变成(\d+)倍', op['source']):
                op.update(subject='equipped_monster', phase='continuous', duration='while_equipped',
                    value_rule={'kind':'original_atk_multiple','multiplier':int(re.search(r'(\d+)倍',op['source'])[1])})
            position = blocks.get(op.get('block_id'),{}).get('source_span',[0])[0]
            clause = record['source_text'][record['source_text'].rfind('。',0,position)+1:].split('。',1)[0]
            delayed = re.fullmatch(r'发动后第(\d+)次的?自己(?:的)?准备阶段时这张卡破坏[，,]'
                r'自己受到装备怪兽的原本攻击力数值的伤害', clause)
            if delayed and op['kind'] in ('destroy','damage'):
                op.update(phase='delayed', timing={'phase':'own_standby','occurrence':int(delayed[1]),
                    'after':'this_card_activation'}, quantity=1, owner='self',
                    subject='this_card' if op['kind']=='destroy' else 'controller')
                if op['kind']=='destroy':op.update(from_zones=['field'],to_zone='grave')
                else:op['amount_rule']={'kind':'equipped_monster_original_atk'}
        if op['kind']=='damage_change' and re.fullmatch(r'直到回合结束时对方受到的全部伤害变成一半',complete_source):
            op.update(owner='opponent',subject='damage_received',quantity=1,
                amount_rule=dict(kind='multiply',fraction=[1,2]),applies_after='this_card_activation')
    if (len(record['operations']) == 2 and len(targets) == 1 and not record['costs']
            and re.fullmatch(r'从自己的手卡[·、]墓地选1只「[^」]+」怪兽特殊召唤[，,]'
                             r'作为对象的怪兽送去墓地[。.]?', body)):
        summon, send = record['operations']
        if summon['kind'] == 'special_summon' and send['kind'] == 'send_grave' and send.get('target_ref') == 0:
            # The summon must succeed for the original target to be sent.
            # Both movements are simultaneous for timing.
            group = summon['block_id']
            summon['simultaneous_group'] = group
            send.update(simultaneous_group=group, depends_on=[summon['block_id']])
    _bind_revealed_summon(record)
    _excavation_processing(record)
    _bind_hand_send_deck_summon(record, body, blocks)
    for op in record['operations']:
        if op['kind']=='grave_destination_replace':
            rule = re.search(r'直到下个回合的结束时[，,]被送去墓地的卡不去墓地而除外',body)
            if rule:
                op.update(source=rule[0], quantity=1,owner='both',from_zones=[],to_zone=None,
                    replacement_rule=dict(from_destination='grave',to_destination='banished',
                        duration='next_turn_end',controller='both',applies_after='resolution'))
                record['restrictions'].append(dict(kind='grave_destination_replace',source=rule[0],
                    scope='player',controller='both',condition='effect_use',duration='next_turn_end',whole_turn=False))
    if row.get('type',0)&1 and not record['trigger'].get('zone'):
        self_cost = [c for c in record['costs'] if '这张卡从手卡' in c['source']]
        self_summon = [op for op in record['operations'] if '这张卡' in op['source']
            and op['kind']=='special_summon' and op.get('from_zones')==['hand']]
        if self_cost or self_summon:
            record['trigger']['zone']='hand'
        elif event in ('own_main_phase','normal_summon','special_summon','normal_or_special_summon'):
            record['trigger']['zone']='field'
    if event == 'attack_declaration_involving_opponent_monster':
        affected = next((op for op in record['operations'] if op['kind'] == 'stats'
                         and op['source'] == '那只对方怪兽攻击力变成0'), None)
        if affected:
            affected.update(subject='opponent_battling_monster', quantity=1)
            for op in record['operations']:
                if op['kind'] == 'negate' and op['source'] == '效果无效化':
                    op.update(subject='opponent_battling_monster', subject_ref=affected['block_id'],
                              owner='opponent', quantity=1)
            for rule in (*record['restrictions'], *record['block_view']['restrictions']):
                if (rule['kind'] == 'cannot_change_position' and re.fullmatch(
                        r'那只对方怪兽攻击力变成0[，,]不能把表示形式变更[，,]效果无效化', rule['source'])):
                    rule.update(scope='this_effect_affected_monster', subject_ref=affected['block_id'],
                                controller='opponent', condition='affected_by_this_effect')
    # A future operation acts on the entity produced by this effect. Preserve
    # the timing and identity; it cannot supply an immediate removal function.
    summons = [op for op in record['operations'] if op['kind'] in (
        'special_summon','fusion_summon','synchro_summon','xyz_summon','link_summon','ritual_summon')]
    if len(summons)==1:
        summon = summons[0]
        trap_monster = re.fullmatch(
            r'这张卡变成通常怪兽[（(]([^·]+)·([地水炎风光暗神])·(\d+)星·攻(\d+)/守(\d+)[）)]'
            r'在怪兽区域特殊召唤[（(]不当作陷阱卡使用[）)]', summon['source'])
        if event == 'trap_card_activation' and summon['kind'] == 'special_summon' and trap_monster:
            from .effect_mechanisms import RACES
            race = RACES.get(trap_monster[1])
            if race is not None:
                summon.update(from_zones=['grave'], owner='self', subject='this_card',
                    result_entity={'type': 'normal_monster', 'race': race,
                        'attribute': {'地': 1, '水': 2, '炎': 4, '风': 8, '光': 16, '暗': 32, '神': 64}[trap_monster[2]],
                        'level': int(trap_monster[3]), 'atk': int(trap_monster[4]), 'def': int(trap_monster[5]),
                        'treated_as_trap': False})
                for op in record['operations']:
                    if op['kind'] == 'type_change' and op['source'] == summon['source']:
                        op['processing_role'] = 'auxiliary'
                    elif op['kind'] == 'unaffected' and op['source'] == '这个效果特殊召唤的这张卡不受怪兽的效果影响':
                        op.update(subject='summoned_by_this_effect', subject_ref=summon['block_id'],
                                  owner='self', quantity=1, protected_from='monster_effects',
                                  depends_on=[summon['block_id']])
                for rule in (*record['restrictions'], *record['block_view']['restrictions']):
                    if rule['kind'] == 'effect_exemption' and re.fullmatch(
                            r'这个效果特殊召唤的这张卡不受怪兽的效果影响(?:[，,]从场上离开的场合除外)?',
                            rule['source']):
                        rule.update(scope='this_effect_summoned_card', subject_ref=summon['block_id'],
                                    condition='summoned_by_this_effect')
        for op in record['operations']:
            if op['kind'] not in ('destroy','banish'):
                continue
            block = blocks.get(op.get('block_id'), {})
            position = block.get('source_span', [0])[0]
            sentence_start = record['source_text'].rfind('。', 0, position)+1
            clause = record['source_text'][sentence_start:].split('。',1)[0]
            if op['kind']=='banish' and re.fullmatch(
                    r'这个效果特殊召唤的(?:怪兽|这张卡)(?:不受怪兽的效果影响[，,])?从场上离开的场合除外',clause):
                op.update(phase='replacement', subject='summoned_by_this_effect',
                    subject_ref=summon['block_id'], from_zones=['field'],to_zone='banished')
            timing = re.search(r'(?:这个回合的)?结束阶段(?:时)?(?:破坏|除外)', clause)
            if timing and re.search(r'这个效果特殊召唤的怪兽', clause):
                op.update(phase='delayed', timing='end_phase', subject_ref=summon['block_id'],
                    subject='summoned_by_this_effect', quantity=summon.get('quantity'), owner='self',
                    from_zones=['field'], to_zone='banished' if op['kind']=='banish' else 'grave')
        for rule in record['restrictions']:
            if rule['kind']=='cannot_attack' and re.fullmatch(
                    r'这个效果特殊召唤的怪兽不能攻击(?:[，,]结束阶段破坏)?', rule['source']):
                rule.update(scope='this_effect_summoned_card', subject_ref=summon['block_id'],
                    condition='summoned_by_this_effect')
    # A fully known summon procedure is not an activated effect with a missing
    # activation boundary. Its condition remains explicit for later binding.
    procedure=re.fullmatch(r'(?P<left>自己|对方)场上的怪兽数量比(?P<right>自己|对方)场上的怪兽(?P<comparison>多|少)的场合[，,]这张卡可以从手卡特殊召唤[。.]?',record['source_text'])
    if mode!='activated' and procedure and record['block_view']['procedure_blocks']:
        record['summon_procedure']=dict(from_zone='hand',to_zone='field',quantity=1,
            condition={'kind':'monster_count','left':{'自己':'self','对方':'opponent'}[procedure['left']],
                'comparison':{'多':'greater','少':'less'}[procedure['comparison']],
                'right':{'自己':'self','对方':'opponent'}[procedure['right']]},
            source=record['source_text'],starts_chain=False)
    if mode != 'activated' and record.get('scope') == 'monster' and row.get('type', 0) & 0x800000:
        overlay = _xyz_overlay_procedure(record, row)
        if overlay:
            record['summon_procedure'] = overlay
    if record.get('summon_procedure'):
        record['block_view']['status']='summon_procedure'
        record['knowledge']['activation_boundary']='not_applicable_summon_procedure'
        record['unknown']=[v for v in record['unknown'] if v not in ('activation_boundary','activation_condition',
            'additional_activation_conditions','resolution','unparsed_resolution_or_restriction')]
    fusion=re.fullmatch(r'融合怪兽卡决定的(?P<self>包含墓地的这张卡的)?融合素材怪兽从自己的'
        r'(?P<zones>手卡(?:[·、]场上)?(?:[·、]墓地)?)用喜欢的顺序回到持有者卡组下面[，,]'
        r'把那1只融合怪兽从额外卡组融合召唤[。.]?',body)
    if fusion:
        record['fusion_material_selection']=dict(owner='self',from_zones=[_ZONE[z] for z in re.split(r'[·、]',fusion['zones'])],
            to_zone='deck_bottom',requires_this_card=bool(fusion['self']),source=fusion[0])
    specific_summon_locks = {rule['source'] for rule in record['restrictions']
        if rule['kind'] == 'cannot_special_summon' and re.fullmatch(
            r'这个效果(?:的)?发动后[，,]直到(?:下次的?自己回合的结束时|回合结束时)自己不是'
            r'(?:[地水炎风光暗神]属性怪兽不能特殊召唤|'
            r'[^。；;，,]+族(?:融合|同调|超量|连接|仪式)怪兽不能从额外卡组特殊召唤)', rule['source'])}
    if specific_summon_locks:
        for scope in (record, record['block_view']):
            scope['restrictions'] = [rule for rule in scope['restrictions']
                if rule['kind'] != 'cannot_summon' or rule['source'] not in specific_summon_locks]
    # The coarse legacy scanner may have missed a verb already represented by
    # the scoped block view. Clear only a body fully covered by those spans.
    remaining=body
    for op in record['operations']:
        if op.get('phase') == 'delayed' and op.get('timing') == 'end_phase' and op.get('timing_source'):
            remaining = remaining.replace(op['timing_source'], '')
    for item in sorted((*record['block_view']['blocks'],*record['block_view']['restrictions']),
                       key=lambda item:len(item.get('source','')), reverse=True):
        remaining=remaining.replace(item.get('source',''),'')
    if any(op.get('depends_on') for op in record['operations']):
        remaining=re.sub(r'那之后|然后|之后','',remaining)
    if any(op.get('duration')=='turn' for op in record['operations']):
        remaining=remaining.replace('这个回合','')
    if any(isinstance(op.get('quantity_binding'),dict) for op in record['operations']):
        remaining=re.sub(r'除外的卡每有\d+张[，,]?(?:自己(?:从卡组)?)?', '', remaining)
    if equipment:
        remaining=remaining.replace(equipment['source'],'')
    for op in record['operations']:
        for state in op.get('state_conditions',()):
            remaining = remaining.replace(state['source'],'')
        if op.get('applies_after')=='this_card_activation':
            remaining=re.sub(r'这张卡的发动后[，,]', '', remaining)
        if op.get('replacement_rule'):
            remaining=remaining.replace(op['source'],'')
            # The block covers the replacement body; its inherited duration
            # may already have been removed with that exact body span.
            remaining=re.sub(r'直到下个回合的结束时[，,]', '', remaining)
    if record['operations'] and not remaining.strip('。．.，,：:；; 　\n'):
        record['unknown']=[v for v in record['unknown'] if v not in ('resolution','unparsed_resolution_or_restriction')]
        if equipment:
            record['unknown']=[v for v in record['unknown'] if v!='unnumbered_effect_boundaries']
    record['block_view']['unknown']=list(record['unknown'])
    operations, grouped = [], {}
    for op in record['operations']:
        complete = re.fullmatch(r'(从(?:自己的?)?(?:卡组|墓地|除外状态)把)'
            r'(\d+[只张](?:「[^」]+」|[^和])+?)和(\d+[只张].+?)(加入手卡)', op['source'])
        if op['kind'] not in ('search_or_recover', 'add_hand', 'search', 'recover') or not complete:
            operations.append(op)
            continue
        selections = [requirement(complete[1] + part + complete[4], 'operations') for part in complete.group(2, 3)]
        if any(not selection for selection in selections):
            operations.append(op)
            continue
        group = op['block_id']
        expanded = [dict(op, block_id=group + ':output:' + str(i), simultaneous_group=group,
            selector_query=selection['query'], quantity=selection['minimum'], from_zones=selection['origins'],
            owner=selection['owner'], random=False) for i, selection in enumerate(selections, 1)]
        operations.extend(expanded)
        grouped[group] = [row['block_id'] for row in expanded]
    if grouped:
        for op in operations:
            if op.get('depends_on'):
                op['depends_on'] = [new for old in op['depends_on'] for new in grouped.get(old, [old])]
        record['operations'] = operations
    # One complete selection with two printed outcomes is two alternative
    # uses of that entity. Reuse the existing option consumer and allocator.
    if not record['block_view'].get('alternatives') and len(inline)==1 and len(next(iter(inline.values())))==2:
        branches={}
        alternatives=next(iter(inline.values()))
        common=[op for op in record['operations'] if op not in alternatives]
        projected=[]
        for i,selected in enumerate(alternatives,1):
            choice='option:'+str(i)
            operations=deepcopy([op for op in record['operations'] if op in common or op is selected])
            remap={op['block_id']:op['block_id']+':'+choice for op in operations}
            remap.update({op['block_id']:remap[selected['block_id']] for op in alternatives})
            for op in operations:
                op.update(choice=choice,block_id=remap[op['block_id']])
                if op.get('depends_on'):op['depends_on']=[remap.get(v,v) for v in op['depends_on']]
            scoped=deepcopy(record)
            scoped.update(operations=operations,branch_records={})
            branches[choice]={k:scoped[k] for k in ('source_text','trigger','conditions','costs','targets',
                'operations','unknown','knowledge','block_view','activation_requirements') if k in scoped}
            projected.extend(operations)
        record['operations']=projected
        record['branch_records']=branches


def operation_record(record, operation):
    """The shared activation plus the selected option's own complete clauses."""
    branch = record.get('branch_records', {}).get((operation or {}).get('choice'))
    if branch:
        return dict(record, **branch, branch_records={})
    if record.get('branch_records'):
        # A common-prefix or otherwise unassigned operation is not an option
        # recursively containing the original options. Keep its exact gap.
        return dict(record,branch_records={},costs=record.get('shared_costs',[]),targets=record.get('shared_targets',[]),
            unknown=[*record['unknown'],'unscoped_choice_operation'])
    return record


def _scope_payment_choices(record):
    """Reuse option-scoped processing for a finite printed payment choice."""
    from itertools import product
    branches = record.get('branch_records') or {'':record}
    expanded = {}
    for parent, branch in branches.items():
        costs = branch['costs']
        options = [c.get('quantity_options', [c.get('quantity')]) for c in costs]
        if not any(c.get('quantity_options') for c in costs):
            if parent:
                expanded[parent] = deepcopy(branch)
            continue
        for values in product(*options):
            choice = (parent+'/' if parent else '')+'payment:'+','.join(map(str,values))
            scoped = deepcopy(branch)
            for cost, quantity in zip(scoped['costs'], values):
                cost.update(quantity=quantity, quantity_status='explicit_choice', choice=choice)
            operations = scoped['operations']
            remap = {op['block_id']:op['block_id']+':'+choice for op in operations}
            for op in operations:
                op.update(choice=choice, block_id=remap[op['block_id']])
                if op.get('depends_on'):
                    op['depends_on'] = [remap.get(v,v) for v in op['depends_on']]
                for field in ('selection_group','subject_ref','different_name_from_reveal'):
                    if op.get(field) in remap:op[field]=remap[op[field]]
                binding = op.get('quantity_binding')
                if isinstance(binding,dict) and 'cost_index' in binding:
                    amount = values[binding['cost_index']]
                    op['quantity'] = amount // binding.get('divisor',1)-binding.get('subtract',0)
            expanded[choice] = {k:scoped[k] for k in ('source_text','trigger','conditions','costs',
                'targets','operations','unknown','knowledge','block_view','activation_requirements',
                'fusion_material_selection','activation_state_conditions') if k in scoped}
    if expanded and any('/payment:' in c or c.startswith('payment:') for c in expanded):
        record['branch_records'] = expanded
        for category in ('costs','targets','operations'):
            record[category] = [deepcopy(v) for branch in expanded.values() for v in branch[category]]


def _scope_choices(record, row):
    from types import SimpleNamespace
    from .effect_blocks import activation_parts, POSITION_ACTIVATION_OPTIONS
    if not record['block_view'].get('alternatives'):
        return
    shared_head=activation_parts(record['source_text'].split('●',1)[0])[0]
    record['shared_costs']=_cost_records(SimpleNamespace(trigger={},costs=(),index=record['effect_index']),head=shared_head)
    quantity_payment = re.search(r'[^，,。]*(?:超量素材|指示物)的?以下数量取除',shared_head)
    if not quantity_payment and re.search(r'取除[^。]*数量的以下效果|取除数量的以下效果',record['source_text']):
        quantity_payment=any(c['kind'] in ('detach','remove_counter') for c in record['shared_costs'])
    variable_costs = deepcopy(record['shared_costs']) if quantity_payment else []
    if quantity_payment:record['shared_costs']=[]
    record['shared_targets']=_targets(shared_head)
    # A completely recognized resolution before the option list is shared by
    # each alternative. Bind copies to their option; never recurse option:0
    # through the aggregate record or require two alternatives together.
    prefix = record['source_text'].split('●', 1)[0]
    position_choice = POSITION_ACTIVATION_OPTIONS.fullmatch(prefix)
    shared = [op for op in record['operations'] if op.get('choice') == 'option:0'
              and op.get('phase') == 'resolution']
    rest = re.sub(r'从以下(?:效果)?选择1个发动[。．.\s]*$', '', prefix)
    blocks = {b['block_id']:b for b in record['block_view']['blocks']}
    for op in shared:
        rest = rest.replace(blocks.get(op.get('block_id'), {}).get('source', op['source']), '', 1)
    complete_prefix = bool(shared) and not rest.strip('。．.，,：:；; 　\n')
    branches = {}
    for number, match in enumerate(re.finditer(r'●([^●]+)', record['source_text']), 1):
        choice = 'option:'+str(number)
        operations = [deepcopy(op) for op in record['operations'] if op.get('choice') == choice]
        if not operations:
            for container in (record,record['block_view']):
                if 'unrecognized_operation' not in container['unknown']:
                    container['unknown'].append('unrecognized_operation')
            continue
        text = match[1].strip()
        position = re.match(r'(攻击|守备)表示[：:]', text) if position_choice else None
        head, body, _, mode = activation_parts(text)
        if position and mode == 'activated':
            head = head.removeprefix(position[0])
        scoped = deepcopy(record)
        scoped.update(source_text=text, operations=operations, branch_records={})
        scoped['block_view']['blocks'] = [b for b in scoped['block_view']['blocks'] if b.get('branch') == number]
        scoped['block_view']['alternatives'] = None
        scoped['costs'] = deepcopy(record['shared_costs']) + _cost_records(
            SimpleNamespace(trigger={}, costs=(), index=record['effect_index']),
            head=head if mode == 'activated' else '', self_banish_origin='field' if position else None)
        if quantity_payment:
            threshold = re.match(r'(\d+)(?:个)?[：:]',text)
            if threshold:
                for payment in variable_costs:
                    payment=deepcopy(payment)
                    payment.update(quantity=int(threshold[1]),quantity_status='explicit',quantity_source=threshold[0])
                    scoped['costs'].append(payment)
            else:
                scoped['unknown'].append('option_payment_quantity')
        scoped['targets'] = deepcopy(record['shared_targets']) + _targets(head)
        if position:
            # Its position selects the applicable effect. A printed shared
            # activation condition is not a second effect or a field search.
            scoped['trigger'] = dict(record['trigger'], event='own_main_phase', zone='field',
                source=prefix.strip(), additional_conditions='none_in_recognized_activation_clause',
                battle_position='attack' if position[1] == '攻击' else 'defense')
            if position_choice['pendulum']:
                scoped['trigger']['summon_kind'] = 'pendulum_summon'
            scoped['conditions'] = dict(record['conditions'], source=prefix.strip(), status='unknown')
        _refine_record(scoped, row, head, body, mode)
        if position:
            scoped['block_view']['target_refs'] = list(range(len(scoped['targets'])))
        scoped['unknown']=[v for v in scoped['unknown'] if v!='unnumbered_effect_boundaries']
        scoped['block_view']['unknown']=list(scoped['unknown'])
        # An option with only processing inherits the shared activation. An
        # option with a printed activation clause keeps its own condition.
        if not position and mode == 'unmarked' and record['conditions']['status'] == 'recognized':
            scoped['trigger'] = deepcopy(record['trigger'])
            scoped['conditions'] = deepcopy(record['conditions'])
        for nested, selected in (scoped.get('branch_records') or {None:scoped}).items():
            selected=deepcopy(selected)
            selected_choice=choice+'/'+nested if nested else choice
            selected['unknown']=[v for v in selected['unknown'] if v!='unnumbered_effect_boundaries']
            if not position and mode=='unmarked' and record['conditions']['status']=='recognized':
                selected['trigger']=deepcopy(scoped['trigger'])
                selected['conditions']=deepcopy(scoped['conditions'])
            if position and mode == 'unmarked' and not set(selected['unknown']) & {
                    'resolution', 'unparsed_resolution_or_restriction', 'unrecognized_operation'}:
                selected['conditions'].update(status='recognized', additional_conditions='none_in_recognized_activation_clause')
                selected['unknown'] = [v for v in selected['unknown'] if v not in
                    ('activation_boundary', 'activation_condition', 'additional_activation_conditions', 'cost_or_condition')]
                selected['block_view']['unknown'] = list(selected['unknown'])
            if complete_prefix:
                common = deepcopy(shared)
                remap = {op['block_id']:op['block_id']+':'+selected_choice for op in common}
                for op in common:
                    op.update(block_id=remap[op['block_id']])
                    if op.get('depends_on'):
                        op['depends_on'] = [remap.get(v, v) for v in op['depends_on']]
                selected['operations']=[*common,*selected['operations']]
                selected['source_text']=prefix+text
            for item in (*selected['costs'], *selected['targets'], *selected['operations']):
                item['choice'] = selected_choice
            branches[selected_choice] = {k: selected[k] for k in (
                'source_text', 'trigger', 'conditions', 'costs', 'targets', 'operations', 'unknown', 'knowledge', 'block_view',
                'activation_requirements', 'fusion_material_selection','activation_state_conditions') if k in selected}
    if branches:
        record['branch_records'] = branches
        refined = {op['block_id']:op for branch in branches.values() for op in branch['operations']}
        assigned={choice.split('/')[0] for choice in branches}
        unscoped=[op for op in record['operations'] if op.get('choice') not in assigned
                  and not (complete_prefix and op in shared)]
        record['operations']=sorted([*refined.values(),*unscoped],key=lambda op:op.get('order',0))
        wrapper = re.fullmatch(r'(?:可以)?从以下(?:效果)?选择1个发动[。．.\s]*',prefix.strip())
        if (not unscoped and (wrapper or complete_prefix or position_choice) and all(not set(branch['unknown']) &
                {'resolution','unparsed_resolution_or_restriction','unrecognized_operation'} for branch in branches.values())):
            resolved = {'resolution', 'unparsed_resolution_or_restriction'}
            if position_choice and all(branch['conditions']['status'] == 'recognized' for branch in branches.values()):
                resolved.update(('activation_boundary', 'activation_condition', 'additional_activation_conditions', 'cost_or_condition'))
            record['unknown']=[v for v in record['unknown'] if v not in resolved]
            record['block_view']['unknown']=list(record['unknown'])
        # Keep the public aggregate for existing readers; consumers select the
        # owning option before requiring a target or payment.
        for category in ('costs', 'targets'):
            record[category] = [deepcopy(v) for branch in branches.values() for v in branch[category]]


def effect_records(profile, *, semantic_version, row=None):
    """Return detached records; source/card identity is provenance, not a feature."""
    from .effect_blocks import activation_parts, block_view, record_operations
    from .construction_inventory import printed_extra_material_slots
    row = row or {'id':profile.card_id,'type':0}
    scope = 'monster' if row.get('type',0)&1 else 'spell_trap'
    from .effect_count_limits import parse_count_limits

    scoped = [(scope,profile)]
    # The underlying model features retain their original v2 representation;
    # public records separate two printed effect sections with repeated numbers.
    if row.get('type',0)&0x1000000 and re.search(r'【怪兽(?:效果|描述)】',row.get('desc','')):
        from .effect_mechanisms import analyze_card
        pendulum,monster=re.split(r'【怪兽(?:效果|描述)】',row['desc'],maxsplit=1)
        scoped=[(name,analyze_card(dict(row,desc=text),profile.cards_sha256))
                for name,text in (('pendulum',pendulum),('monster',monster))]
    result = []
    for scope,section in scoped:
        from .effect_text import unnumbered_parts
        from .effect_mechanisms import analyze_card, NUMBERED
        from dataclasses import replace
        effects=[]
        section_text = row.get('desc','')
        if len(scoped)>1:
            sections=re.split(r'【怪兽(?:效果|描述)】',section_text,maxsplit=1)
            section_text=sections[0] if scope=='pendulum' else sections[1]
        materials = list(section.materials)
        if not materials and scope == 'monster':
            materials = printed_extra_material_slots(dict(row, desc=section_text.lstrip()))
        prelude=NUMBERED.split(section_text,maxsplit=1)[0] if NUMBERED.search(section_text) else ''
        section_limits = []
        if ('灵摆效果' if scope == 'pendulum' else '怪兽效果') in prelude:
            section_limits = [limit for limit in parse_count_limits(0, prelude, '', section=scope)
                              if limit['subject'].get('section') is not None]
        for effect in section.effects:
            parts=unnumbered_parts(effect.text) if effect.index==0 else [effect.text]
            if len(parts)==1:
                effects.append(effect)
            else:
                for part in parts:
                    effects.extend(replace(e,index=effect.index) for e in analyze_card(dict(row,desc=part),profile.cards_sha256).effects)
        first_prelude=len(effects)
        if prelude.strip():
            # Append public prelude observations without renumbering existing
            # numbered effects or turning a count-only prelude into an effect.
            effects.extend(analyze_card(dict(row,desc=prelude),profile.cards_sha256).effects)
        for pos,effect in enumerate(effects):
            head,_,_,mode = activation_parts(effect.text)
            legacy_payment=re.match(r'支付\d+(?:的倍数的)?(?:基本分|LP|分)(?:发动)?[。；;]',effect.text)
            cost_head=head if mode=='activated' else legacy_payment[0] if legacy_payment else ''
            if mode=='activated':
                leading=re.match(r'支付(?:\d+(?:的倍数的)?(?:基本分|LP|分)|一半(?:基本分|LP))[。；;]',activation_parts(effect.text)[1])
                if leading:cost_head+='。'+leading[0]
            costs = _cost_records(effect,head=cost_head)
            record = {
                "record_version": EFFECT_RECORD_VERSION, "semantic_version": semantic_version, "card_id": profile.card_id,
                "cards_sha256": profile.cards_sha256, "text_sha256": profile.text_sha256,
                "effect_index": effect.index, "source_text": effect.text,
                "scope": scope, "effect_key": f"{scope}:{effect.index}:{pos}",
                "trigger": deepcopy(effect.trigger),
                "conditions": {"source": effect.trigger.get("source", ""),
                               "status": "recognized" if effect.conditions_known else "unknown",
                               "additional_conditions": effect.trigger.get("additional_conditions", "unknown")},
                "costs": costs, "targets": deepcopy(list(effect.targets)), "operations": deepcopy(list(effect.operations)),
                "count_limits": deepcopy([*effect.count_limits, *section_limits]),
                "restrictions": deepcopy(list(effect.restrictions)),
                "card_restrictions": deepcopy(list(section.restrictions)),
                "printed_materials": deepcopy(materials),
                "knowledge": deepcopy(effect.knowledge),
                "unknown": list(dict.fromkeys((*section.unknown, *effect.unknown))),
                "legality_verified": False,
            }
            record["rule_references"] = effect_reference_requests(record)
            record["block_view"] = block_view(record,row)
            summon_conditions=[d['source'] for d in record['block_view']['description_blocks'] if d['kind']=='summon_condition']
            for field in ('restrictions','card_restrictions'):
                record[field]=[r for r in record[field] if not (r['kind']=='cannot_activate' and any(
                    r.get('source') and (r['source'] in s or s in r['source']) for s in summon_conditions))]
            for payment in record['block_view']['cost_blocks']:
                if payment['phase']=='activation_payment' and not any(c['kind']==payment['kind']
                    and (c['source'] in payment['source'] or payment['source'] in c['source']) for c in record['costs']):
                    record['costs'].append(dict(payment['qualifiers'],kind=payment['kind'],source=payment['source'],
                        cost_index=len(record['costs']),effect_index=effect.index))
            procedure_sources=[b['source'] for b in record['block_view']['procedure_blocks'] if b['phase']=='summon_procedure']
            if procedure_sources:
                record['costs']=[c for c in record['costs'] if not any(c.get('source') and c['source'] in s for s in procedure_sources)]
                record['block_view']['cost_blocks']=[c for c in record['block_view']['cost_blocks'] if not (
                    c['phase']=='activation_payment' and any(c['source'] in s for s in procedure_sources))]
            record['non_activation_costs']=[dict(c['qualifiers'],phase=c['phase'],source=c['source'],block_id=c['block_id'])
                                            for c in record['block_view']['cost_blocks'] if c['phase']!='activation_payment']
            for restriction in record['block_view']['restrictions']:
                prior = next((r for r in record['restrictions']
                    if r['kind'] == restriction['kind'] and r['source'] == restriction['source']), None)
                if prior is None:
                    record['restrictions'].append(deepcopy(restriction))
                elif restriction.get('condition') in ('source_clause', 'this_card_in_zone', 'this_card_in_monster_zone'):
                    prior.update({key: deepcopy(restriction[key]) for key in ('condition', 'from_zones') if key in restriction})
            record['count_limits']=deepcopy(record['block_view']['count_limits'])
            record['operations'] = record_operations(record)
            _refine_record(record,row,head,activation_parts(effect.text)[1],mode)
            _scope_choices(record,row)
            _scope_payment_choices(record)
            from .effect_text import finalize_record
            finalize_record(record)
            from .effect_rulings import apply_reviewed_ruling
            apply_reviewed_ruling(record,row)
            for operation in record['operations']:
                if operation.get('selector_query'):
                    operation['selector_source'] = operation['source']
            for branch in record.get('branch_records',{}).values():
                for operation in branch['operations']:
                    if operation.get('selector_query'):
                        operation['selector_source'] = operation['source']
            record['resource_changes'] = [dict(item,phase='activation_payment') for item in record['costs']]
            record['resource_changes'] += deepcopy(record['non_activation_costs'])
            record['resource_changes'] += [dict(item) for item in record['operations'] if item.get('from_zones') or item.get('to_zone')]
            record['knowledge']['operation_projection'] = record['block_view']['version']
            if pos>=first_prelude and prelude.strip() and not (
                    record['block_view']['blocks'] or record['block_view']['cost_blocks'] or record['block_view']['procedure_blocks']
                    or any(d['kind'] not in ('printed_materials','no_pendulum_effect','count_limit_description') for d in record['block_view']['description_blocks'])):
                continue  # Shared counts/restrictions already belong to their numbered effects.
            result.append(record)
    return tuple(_public_data(record) for record in result)


_LUA_NAMED_SCOPES = {"same_name_this_effect", "same_name_shared_effects", "same_name_all_effects"}
_LUA_SUMMON_EVENTS = {"normal_summon", "special_summon"}
_PRINTED_SELF_SEND = re.compile(
    r"(?:把|将)(?:自己(?:的)?)?(?:手卡(?:[·、]|或者|或)场上|场上(?:[·、]|或者|或)手卡)的这张卡送去墓地"
)


def merge_lua_effect_sources(records, source, script_code, *, same_printing=True):
    """Attach Lua evidence to the matching printed effect and refine supported facts."""
    if not records:
        return
    if not same_printing:
        for record in records:
            record["record_version"] = LUA_EFFECT_RECORD_VERSION
            record["lua_source"] = dict(status="distinct_alias_text", script_card_id=script_code,
                                        alignment="unresolved")
        return
    deck_sends = {record["effect_index"] - 1 for record in records if record["effect_index"] > 0
                  and any(op["kind"] in ("send_grave", "mill") and op.get("from_zones") == ["deck"]
                          for op in record["operations"])}
    self_send_costs = {record["effect_index"] - 1 for record in records if record["effect_index"] > 0
                       and any(_PRINTED_SELF_SEND.fullmatch(cost.get("source", "")) for cost in record["costs"])}
    script = source.summarize_effects(script_code, deck_send_indices=deck_sends,
                                      self_send_cost_indices=self_send_costs)
    groups = defaultdict(list)
    for registration in script["registrations"]:
        groups[registration.get("description_index")].append(registration)
    indices = Counter(record["effect_index"] for record in records)
    source_info = {k: v for k, v in script.items() if k != "registrations"}
    for record in records:
        record["record_version"] = LUA_EFFECT_RECORD_VERSION
        index = record["effect_index"]
        windows = groups.get(index - 1, ())
        printed_event = record["trigger"].get("event")
        events = {window["event"] for window in windows}
        matches = events == (_LUA_SUMMON_EVENTS if printed_event == "normal_or_special_summon" else {printed_event})
        if index <= 0 or indices[index] != 1 or not printed_event or not windows or not matches:
            record["lua_source"] = dict(source_info, alignment="unresolved")
            if windows:
                record["lua_source"]["candidate_spans"] = [window["registration_span"] for window in windows]
            continue
        record["lua_source"] = dict(source_info, alignment="matched", registrations=list(windows))
        if index - 1 in deck_sends:
            _merge_lua_deck_send(record)
        if index - 1 in self_send_costs:
            _merge_lua_self_send_cost(record)

    aligned = [record for record in records if record["lua_source"]["alignment"] == "matched"]
    candidates = {}
    for record in aligned:
        lua = record["lua_source"]
        windows = lua["registrations"]
        if not any("count_limit" in window for window in windows):
            continue
        if (script["status"] != "parsed" or len({window["family"] for window in windows}) != 1
                or any(any(window.get(callback) != windows[0].get(callback)
                           for callback in ("condition", "cost", "target", "operation", "value"))
                       for window in windows[1:])):
            lua["count_status"] = "unresolved_registration"
            continue
        counts = {source.turn_count(window) for window in windows}
        if len(counts) != 1 or None in counts:
            lua["count_status"] = "unsupported_or_inconsistent_counter"
            continue
        printed = record["count_limits"]
        if (len(printed) != 1 or printed[0]["status"] != "known" or printed[0].get("period") != "turn"
                or printed[0].get("scope") not in _LUA_NAMED_SCOPES or printed[0].get("count_event") != "use"):
            lua["count_status"] = "printed_limit_unresolved"
            continue
        maximum, code = counts.pop()
        candidates[record["effect_key"]] = (maximum, code)

    # A partial binding of a shared counter would allow one effect to evade
    # its printed limit. Require the same mapping in both directions.
    records_by_code = defaultdict(set)
    for key, (_, code) in candidates.items():
        records_by_code[code].add(key)
    occurrences = Counter()
    for registration in script["registrations"]:
        args = registration.get("count_limit", {}).get("values", ())
        if len(args) >= 2 and args[1] is not None:
            occurrences[args[1]] += 1
    windows_by_code = Counter()
    for record in aligned:
        candidate = candidates.get(record["effect_key"])
        if candidate is not None:
            windows_by_code[candidate[1]] += len(record["lua_source"]["registrations"])
    for record in aligned:
        key = record["effect_key"]
        if key not in candidates:
            continue
        lua = record["lua_source"]
        maximum, code = candidates[key]
        limit, = record["count_limits"]
        same_code = records_by_code[code]
        matching_scope = _printed_counter_members(records, record, limit)
        if (limit["maximum"] != maximum or same_code != matching_scope or occurrences[code] != windows_by_code[code]
                or any(candidates[member] != (maximum, code) for member in same_code)):
            lua["count_status"] = "printed_counter_conflict"
            continue
        counter = dict(script_card_id=script_code, code=code)
        branch_views = [branch["block_view"] for branch in record.get("branch_records", {}).values()]
        for view in (record["block_view"], *branch_views):
            for item in view["count_limits"]:
                if item == limit:
                    item["lua_counter"] = dict(counter)
        limit["lua_counter"] = counter
        lua["count_status"] = "bound"


def _has_rule_code_filter(query):
    return "predicate" in query or any(_has_rule_code_filter(child) for child in query.get("any", ()))


def _merge_lua_deck_send(record):
    from .construction_inventory import query_supported, requirement, selector
    from .effect_blocks import _unquote, activation_parts

    lua = record["lua_source"]
    windows = lua["registrations"]
    observed = windows[0].get("deck_send", {})
    if (observed.get("status") != "resolved" or len({window["family"] for window in windows}) != 1
            or any(window.get("deck_send") != observed for window in windows[1:])):
        lua["deck_send_status"] = "unresolved_callback"
        return

    operations = record["operations"]
    if len(operations) != 1 or record.get("branch_records") or record["targets"]:
        lua["deck_send_status"] = "unresolved_printed_scope"
        return
    operation, = operations
    if (operation["kind"] != "send_grave" or operation.get("from_zones") != ["deck"]
            or operation.get("to_zone") != "grave" or operation.get("owner") != "self"
            or operation.get("reason") != "effect" or operation.get("phase") != "resolution"
            or operation.get("random") is not False or operation.get("quantity") != observed["quantity"]
            or "target_ref" in operation or operation.get("optional") or operation.get("amount_rule")):
        lua["deck_send_status"] = "printed_movement_conflict"
        return
    block = next((block for block in record["block_view"]["blocks"]
                  if block["block_id"] == operation["block_id"] and block["kind"] == "send_grave"), None)
    body = activation_parts(record["source_text"])[1].strip().rstrip("。．.；;")
    if (block is None or block["source"].strip() != body
            or re.search(r"最多|至多|最少|全部|任意数量|\d+[只张](?:以上|以下)", _unquote(body))
            or any(mark in record["unknown"] for mark in ("resolution", "unparsed_resolution_or_restriction"))):
        lua["deck_send_status"] = "unresolved_printed_scope"
        return
    if (operation.get("selector_query") or selector(operation.get("selector", ""))
            or requirement(block["source"], "operations")):
        lua["deck_send_status"] = "printed_selector_retained"
        return
    query = observed["selector_query"]
    # A generic filter cannot fill a missing printed domain. IsCode filters
    # rule names, while the existing card_ids predicate matches row IDs.
    if query == {"selector": "卡"} or _has_rule_code_filter(query) or not query_supported(query):
        lua["deck_send_status"] = "unresolved_inventory_selector"
        return

    operation.update(selector_query=deepcopy(query), selector_source=operation["source"])
    block["qualifiers"].update(selector_query=deepcopy(query), owner="self",
                               quantity=operation["quantity"])
    for change in record["resource_changes"]:
        if change.get("block_id") == operation["block_id"] and change.get("reason") == "effect":
            change.update(selector_query=deepcopy(query), selector_source=operation["source"])
    lua["deck_send_status"] = "selector_bound"


def _merge_lua_self_send_cost(record):
    from .effect_blocks import activation_parts

    lua = record["lua_source"]
    windows = lua["registrations"]
    observed = windows[0].get("self_send_cost", {})
    if (observed.get("status") != "resolved" or len({window["family"] for window in windows}) != 1
            or any(window.get("self_send_cost") != observed for window in windows[1:])):
        lua["self_send_cost_status"] = "unresolved_callback"
        return
    head, _, _, mode = activation_parts(record["source_text"])
    if (mode != "activated" or record["trigger"].get("event") != "own_main_phase"
            or len(record["costs"]) != 1 or record["targets"] or record.get("branch_records")
            or not _PRINTED_SELF_SEND.fullmatch(head.strip())):
        lua["self_send_cost_status"] = "unresolved_printed_scope"
        return
    cost, = record["costs"]
    if (cost["source"] != head.strip() or cost["kind"] != "send_grave" or cost.get("reason") != "cost"
            or cost.get("to_zone") != "grave" or set(cost.get("from_zones", ())) != set(observed["from_zones"])
            or cost.get("owner") not in ("unknown", "self") or cost.get("resource") != "cards"
            or cost.get("quantity") != 1 or cost.get("quantity_options") or cost.get("quantity_variants")
            or cost.get("random") or cost.get("discard")):
        lua["self_send_cost_status"] = "printed_payment_conflict"
        return
    if cost.get("selector_query"):
        lua["self_send_cost_status"] = "printed_selector_retained"
        return
    block = next((block for block in record["block_view"]["cost_blocks"]
                  if block["phase"] == "activation_payment" and block["kind"] == cost["kind"]
                  and block["source"] == cost["source"]), None)
    original_change = dict(cost, phase="activation_payment")
    changes = [change for change in record["resource_changes"] if change == original_change]
    if block is None or len(changes) != 1:
        lua["self_send_cost_status"] = "unresolved_printed_projection"
        return
    code = record["card_id"]
    bound = dict(subject="this_card", source_card_id=code, owner="self", owner_status="recognized",
                 quantity_status="explicit", selector_query={"predicate": {"field": "card_ids", "value": [code]}})
    cost.update(deepcopy(bound), observed_payment=deepcopy(cost))
    block["qualifiers"].update(deepcopy(bound))
    changes[0].update(deepcopy(bound))
    lua["self_send_cost_status"] = "bound"


def _printed_counter_members(records, record, limit):
    scope = limit.get("scope")
    if scope == "same_name_this_effect":
        return {record["effect_key"]}
    subject = limit.get("subject", {})
    section = subject.get("section")
    indices = subject.get("effect_indices", ())
    return {item["effect_key"] for item in records
            if (section is None or item["scope"] == section)
            and (scope != "same_name_shared_effects" or item["effect_index"] in indices)
            and any(other.get("status") == "known" and other.get("scope") == scope
                    and other.get("count_event") == "use" and other.get("source") == limit["source"]
                    and other.get("period") == "turn" and other.get("maximum") == limit["maximum"]
                    for other in item["count_limits"])}


def mechanism_summary(catalog, codes):
    """ID-independent bounded means, supplementary to legacy card features.

    Exact payment quantities and associations remain in effect_records; this
    fixed-width model summary deliberately does not claim to be lossless.
    Repeated IDs count as actual deck copies. Empty decks have zero observations.
    """
    codes = tuple(codes)
    total = [0.] * SUMMARY_WIDTH
    for code in codes:
        row = catalog.assets.rows[code]
        records = catalog.effect_records(code)
        # Existing checkpoints use the original movement observations for
        # these features. Static refinements retain them beside the new fields.
        costs = [item.get("observed_payment", item) for record in records for item in record["costs"]]
        operations = [item for record in records for item in record["operations"] if item.get("reason") == "effect"]
        changes = [item.get("observed_operation", item)
                   for record in records for item in record["resource_changes"]]
        limits = [item for record in records for item in record["count_limits"]]
        kinds = [item["kind"] for item in operations]
        values = [float(bool(row.get("type", 0) & flag)) for flag in (0x40, 0x2000, 0x800000, 0x1000)]
        values += [len(records)/8, len(costs)/8,
                   sum(item["quantity"] for item in costs if item.get("quantity") is not None and item.get("resource") == "cards")/16,
                   sum(item.get("quantity") is None for item in costs)/8,
                   sum(len(r["targets"]) for r in records)/8,
                   (len(catalog.card(code).restrictions)+sum(len(r["restrictions"]) for r in records))/8,
                   sum(bool(r["unknown"]) for r in records)/8,
                   sum(r["trigger"].get("event") == "sent_to_grave" for r in records)/8,
                   sum(r["trigger"].get("event") in ("normal_or_special_summon", "special_summon") for r in records)/8,
                   kinds.count("fusion_summon")/8, kinds.count("special_summon")/8,
                   sum(k in ("mill", "send_grave") for k in kinds)/8,
                   kinds.count("search_or_recover")/8, kinds.count("draw")/8,
                   sum(k in ("negate", "destroy") for k in kinds)/8]
        values += [sum(zone in item.get("from_zones", ()) for item in changes)/8 for zone in ("hand", "grave")]
        values += [sum(item.get("to_zone") == zone for item in changes)/8 for zone in ("field", "grave")]
        values += [sum(item.get("to_zone") in ("deck", "deck_bottom") for item in changes)/8,
                   sum(item["maximum"] for item in limits if item.get("maximum") is not None)/16,
                   sum(item.get("scope", "").startswith("player_") or item.get("subject", {}).get("kind") == "same_name_shared_effects" for item in limits)/8,
                   sum(item.get("status") == "unknown" for item in limits)/8,
                   sum(r["conditions"]["status"] == "recognized" for r in records)/8]
        values += [sum(item.get("owner") == owner for item in costs)/8 for owner in ("self", "opponent", "unknown")]
        values += [sum(item.get("quantity") is None for item in changes)/8]
        for index, value in enumerate(values):
            total[index] += min(value, 1.) / len(codes)
    return total
