"""Printed-text boundaries and payments shared by the public effect view.

Only language forms live here. There are no card IDs, theme names or inferred
rule rulings. Positions and public information are state payments, not cards
destroyed/consumed by the relation adapter.
"""
from copy import deepcopy
import json
import re


def mask_names(text):
    return re.sub(r'「[^」]*」|『[^』]*』', lambda m: ' '*len(m[0]), text)


def mask_action_references(text):
    # Adjectival/event references describe an already moved/summoned card.
    # Mask only their verbs, preserving positions in the original sentence.
    pattern = r'(?:加入(?:自己|自身)?手卡|回到(?:自己|持有者)?(?:的)?手卡|丢弃|舍弃|(?:得到|获得)控制权|(?:作为|当作)(?:[^。]{0,22}的)?超量素材|特殊召唤)(?=的)|被同调召唤使用|不能通常召唤的|卡名(?:全部)?不同|可以放置[^。]{0,16}指示物的'
    return re.sub(pattern,lambda m:' '*len(m[0]),text)


def payment_records(head):
    from .effect_blocks import source_zones
    result = []
    for match in re.finditer(r'[^，,。；;\r\n]+',head):
        source = match[0].strip()
        compound=re.split(r'(?:并且|并)(?=支付|把|将|丢弃|除外|解放)',source)
        if len(compound)>1:
            for part in compound:result.extend(payment_records(part))
            continue
        clause = mask_names(source)
        clause = re.sub(r'^.*?[：:]','',clause)
        clause=re.sub(r'（[^（）]*）|\([^()]*\)',lambda m:' '*len(m[0]),clause).strip()
        if re.search(r'(?:场合|成功|时候|时)$',clause) or re.search(r'为对象$|不支付|无需支付|不用支付|不需要支付',clause):
            continue
        if re.search(r'不再|不会被|不去墓地|被(?:送去|送入)墓地$',clause):continue
        kind, resource, destination = None, 'cards', None
        if re.search(r'(?:支付(?:\d+(?:的倍数的)?(?:基本分|LP|分)|一半(?:基本分|LP)|(?:基本分|LP)的一半)|(?:基本分|LP)(?:的)?(?:一半)?支付(?:一半)?)',clause):
            kind, resource = 'pay_lp', 'lp'
        elif re.search(r'指示物[^，]{0,14}(?:取除|除去)|(?:取除|除去)[^，]{0,20}指示物',clause):
            kind, resource = 'remove_counter','counters'
        elif re.search(r'(?:超量)?素材[^，]{0,30}(?:取除|除去)$|(?:取除|除去)[^，]{0,12}超量素材$',clause):
            kind, resource, destination = 'detach','xyz_material','grave'
        elif re.search(r'(?:丢弃|舍弃|丢掉)',clause):
            kind, destination = 'send_grave','grave'
        elif re.search(r'(?:送去|送入|扔进)墓地$',clause):
            kind, destination = 'send_grave','grave'
        elif re.search(r'(?:里侧)?(?:从游戏中)?除外$',clause):
            kind, destination = 'banish','banished'
        elif re.search(r'解放$|(?:作为|当作)(?:祭品|解放)$',clause):
            kind, destination = 'release','grave'
        elif re.search(r'(?:给对方(?:玩家)?|给双方|向对方|给人|对方)(?:观看|确认|展示)$|(?:公开|展示)(?:手卡|这张卡)',clause):
            kind, resource = 'reveal','public_state'
        elif re.search(r'(?:变成|变更为|变为|改成)(?:表侧|里侧)?(?:攻击|守备)表示$',clause):
            kind, resource = 'position','card_state'
        elif re.search(r'(?:回到|返回)(?:持有者|自己)?(?:的)?(?:卡组(?:[·、]额外卡组)?|手卡|额外卡组|融合卡组)(?:最上面|最下面)?$',clause):
            kind = 'return_hand' if '手卡' in clause else 'return_deck' if '卡组·额外卡组' in clause else 'return_extra_deck' if re.search(r'额外卡组|融合卡组',clause) else 'return_deck'
            destination = {'return_hand':'hand','return_deck':'deck','return_extra_deck':'extra'}[kind]
        if not kind:
            continue
        counts = list(re.finditer(r'(\d+)(?:个|张|只)(?!回合)',clause))
        count = int(counts[-1][1]) if counts else 1 if re.search(r'这张卡|自身',clause) else None
        if re.search(r'任意数量|以下数量|以上数量|相同数量|那个数量|全部',clause):
            count = None
        owner = 'opponent' if re.search(r'(?:从|把|将)对方',clause) else 'self'
        zones = source_zones(source)
        if not zones:
            zones = ['hand'] if re.search(r'手卡|丢弃|舍弃',clause) else ['field'] if kind in ('release','position','remove_counter') else []
        if kind=='detach':zones=['xyz_material']
        item = dict(kind=kind,reason='cost',source=source,quantity=count,
            quantity_status='explicit' if count is not None else 'unknown',owner=owner,
            owner_status='recognized',from_zones=zones,to_zone=destination,resource=resource)
        if len(zones)>1 and 'deck' in zones and re.search(r'卡组(?:最)?上面',source):
            item.update(random=None,selection_by_zone={z:'top' if z=='deck' else 'choose' for z in zones})
        bound=re.search(r'最多(\d+)[只张个]|(\d+)[只张个]以上',clause)
        if bound and resource!='lp':
            item.update(quantity=None,quantity_status='chosen_bounded',minimum=1 if bound[1] else int(bound[2]))
            if bound[1]:item['maximum']=int(bound[1])
            if item.get('maximum')==1:item.update(quantity=1,quantity_status='explicit')
        if resource=='cards' and re.search(r'[和及与]',clause) and ('这张卡' in clause or re.search(r'各\d+[只张]',clause)):
            item.update(quantity=None,quantity_status='compound_requires_binding',quantity_source=source)
        if '卡组·额外卡组' in clause and kind=='return_deck':
            item.update(to_zone=None,destination_rule='main_or_extra_by_card_type')
        if kind=='pay_lp':
            number = re.search(r'支付(\d+)|(?:基本分|LP)支付(\d+)',clause)
            item.update(from_zones=[],quantity=int(next(v for v in number.groups() if v)) if number else None)
            if '一半' in clause:item.update(quantity_status='current_fraction',fraction=[1,2])
            elif '倍数' in clause:item.update(quantity=None,quantity_status='chosen_multiple',unit=int(number[1]) if number else None)
            else:item['quantity_status']='explicit' if item['quantity'] is not None else 'unknown'
        if resource in ('public_state','card_state'):item['consumes_card']=False
        if kind=='reveal':item['audience']='both' if '双方' in clause else 'opponent'
        if kind=='position':item['position']='defense' if '守备' in clause else 'attack'
        if kind=='send_grave' and re.search(r'丢弃|舍弃|丢掉',clause):item['discard']=True
        if '里侧' in clause:item['face_down']=True
        if kind=='remove_counter':
            name = re.search(r'([\u4e00-\u9fffA-Za-z]+)指示物',source)
            if name:item['counter_name']=name[1].split('的')[-1]
        result.append(item)
    return result


def merge_payments(existing, head):
    """Replace only overlapping legacy spans, retaining unrelated payments."""
    result = deepcopy(existing)
    for item in payment_records(head):
        overlaps = [c for c in result if c.get('source') and
            (c['source'] in item['source'] or item['source'] in c['source']) and (
                c['kind'] in (item['kind'],'payment') or c['source']==item['source']
                or item['kind']=='banish' and c['kind']=='send_grave' and re.search(r'没有送去墓地|没送去墓地',item['source']))]
        if overlaps and all(c['kind']==item['kind'] and c.get('kind')!='payment' for c in overlaps):
            # Keep detailed selectors already recognized by the inventory parser.
            for c in overlaps:
                if item.get('quantity_status')=='chosen_bounded':
                    c.update({k:v for k,v in item.items() if k in ('quantity','quantity_status','minimum','maximum')})
                if item.get('quantity_status')=='compound_requires_binding':
                    c.update(quantity=None,quantity_status=item['quantity_status'],quantity_source=item['quantity_source'])
                if c.get('source')==item['source']:
                    for k,v in item.items():
                        if k=='from_zones' and set(c.get(k,[]))<set(v):c[k]=v
                        if k=='random' and 'selection_by_zone' in item:c[k]=v
                        if k not in c or c[k] is None:c[k]=v
            continue
        result = [c for c in result if c not in overlaps]
        result.append(item)
    return result


RITUAL_MATERIAL_RELEASE = re.compile(
    r'从自己(?:的)?(?:手卡·场上|场上·手卡|手卡)把等级合计(?:直到|为)(\d+)(以上)?的怪兽解放')


def legacy_payment_boundary(text):
    """Clear older payment→instruction syntax, without moving resolution fees."""
    first_sentence=text.split('。',1)[0]
    for paid in re.finditer(r'支付(?:\d+(?:基本分|LP|分)|一半(?:基本分|LP))|(?:基本分|LP)支付一半',first_sentence):
        before=first_sentence[:paid.start()]
        after=text[paid.end():]
        if re.search(r'控制者|那之后|然后|不支付|无需|不用|双方',before):continue
        if re.match(r'(?:把|将|从|则|让这张卡|选择|才能(?=从|把|特殊召唤)|就可(?=从|把|确认|回复))',after):
            return text[:paid.end()],after,paid.end(),'activated'
    for match in re.finditer(r'[，,。]',text):
        prefix = text[:match.start()]
        if '。' in prefix:
            break
        parts = list(re.finditer(r'[^，,]+',prefix))
        if not parts:
            continue
        last = parts[-1][0]
        if re.search(r'第\d+次的自己准备阶段|发动后',prefix):continue
        payments = payment_records(last)
        if not payments or re.search(r'作为代替|对方也|双方|控制者|每次|每有|的场合|才能(?:召唤|特殊召唤)',last):
            continue
        paid=re.search(r'支付(?:\d+(?:基本分|LP|分)|一半(?:基本分|LP))|(?:基本分|LP)支付一半',last)
        if paid and re.search(r'特殊召唤|抽\d|加入手卡|回到|控制权|攻击力[^。]{0,15}上升',last[paid.end():]):continue
        if '作为祭品' in prefix and re.search(r'仪式召唤|降临',text):continue
        preceding=[p[0] for p in parts[:-1] if not re.search(r'(?:场合|时|之际|阶段|回合)$',p[0])]
        if any(re.search(r'确认|检视|抽|破坏|特殊召唤|加入手卡',p) and not payment_records(p) for p in preceding):continue
        tail = text[match.end():]
        if RITUAL_MATERIAL_RELEASE.fullmatch(last) and re.match(r'\s*从手卡[^。，,]+仪式召唤', tail):
            return None  # The level sum is a material requirement during ritual resolution.
        # A resolution connector joins two operations even if the first
        # verb could also describe an activation payment.
        if not paid and '作为代价' not in last and re.match(r'\s*(?:那之后|之后|然后)', tail):
            return None
        if re.match(r'(?:[「『][^」』]+[」』]的)?(?:这个效果|此效果|除外的时候|那个时候|此时)|[（(]',tail):continue
        if re.search(r'下次[^。]{0,20}阶段之前除外$',last):continue
        if not re.search(r'抽|破坏|无效|加入|召唤|攻击|控制权|确认|上升|下降|变成|回到|放回|返回|效果(?:适用|相同|变成)|伤害|回复|送去墓地|装备|盖放|除外|解放|洗切|排列',tail):
            continue
        if re.search(r'可以|支付|丢弃|舍弃|取除|除去|解放|除外|作为祭品|送去墓地',prefix):
            return prefix,tail,match.end(),'activated'
    return None


def unnumbered_parts(text):
    """Keep separate printed lines/explicit new effects apart from materials."""
    if '●' in text:return [text]
    lines = [s.strip() for s in text.splitlines() if s.strip()]
    groups=lines if len(lines)>1 and not any(s.startswith('●') for s in lines) else [text]
    joined=[]
    for group in groups:
        if joined and re.search(r'发动。$',joined[-1]) and not re.search(r'^(?:1回合|此外|另外|这张卡[^。]{0,30}(?:场合|时))',group):
            # Preserve the exact printed whitespace between an activation head
            # and its following processing line.
            previous=joined.pop();begin=text.index(previous);end=text.index(group,begin+len(previous))+len(group)
            joined.append(text[begin:end])
        else:joined.append(group)
    groups=joined
    return [part for group in groups for part in re.split(r'(?<=。)(?=(?:1回合1次[，,]|此外[，,](?!每次)|另外[，,]|通常魔法发动时|装备怪兽攻击过的战斗阶段中|把[^。]{0,100}作为祭品|可以把装备状态|可以把基本分支付|丢弃\d+张手卡并支付|从这张卡上每除去|可以(?:在[^。]{0,25})?支付|(?:这张卡|装备怪兽|自己场上)[^。，]{0,80}(?:时|场合)[，,]|装备怪兽因战斗破坏))',group)]


def activation_headers(text):
    """All literal activation heads, including effects granted inside bullets."""
    from .effect_blocks import ACTIVATION
    headers=[]
    for marker in ACTIVATION.finditer(text):
        start=max(text.rfind('。',0,marker.start()),text.rfind('\n',0,marker.start()),text.rfind('●',0,marker.start()))+1
        if re.search(r'可以把[^。]+在盖放的回合[^。]*发动',text[start:marker.end()]):continue
        headers.append((start,marker.end(),text[start:marker.start()]))
    for marker in re.finditer(r'[；;]',text):
        start=max(text.rfind('。',0,marker.start()),text.rfind('\n',0,marker.start()),text.rfind('●',0,marker.start()),
                  text.rfind('；',0,marker.start()),text.rfind(';',0,marker.start()))+1
        headers.append((start,marker.end(),text[start:marker.start()]))
    return sorted(set(headers))


def complete_structure(text, row, scope, blocks, costs, procedures, restrictions, descriptions, key):
    """Keep procedures, upkeep and permissions outside resolution functions."""
    from .effect_blocks import LABELS, _qualifiers

    def add(container, kind, source, start, phase, dimension, **qualifiers):
        if any(b['kind']==kind and (source in b.get('source','') or b.get('source','') in source) for b in container):
            return
        container.append(dict(kind=kind,tag={'dimension':dimension,'value':LABELS[kind]},
            phase=phase,source=source,source_span=[start,start+len(source)],order=start,
            qualifiers=dict(_qualifiers(source,kind,[]),**qualifiers),group=key,branch=text[:start].count('●'),
            block_id=f'{key}:{dimension}:extra:{len(container)}'))

    for number,(start,end,head) in enumerate(activation_headers(text)):
        # Event clauses are not a second payment merely because they mention
        # a discard/sending that already happened.
        head=re.sub(r'[^，,。；;]*(?:场合|之际|成功|时)(?:（[^（）]*）)?(?=[，,。；;]|$)',lambda m:' '*len(m[0]),head)
        for payment in payment_records(head):
            source=payment.pop('source')
            if source not in text:continue
            phase='activation_payment' if number==0 else 'conditional_activation_payment'
            add(costs,payment.pop('kind'),source,text.index(source,start),phase,'cost',
                **dict(payment,activation_source=text[start:end],starts_chain=True))

    intrinsic = bool(re.search(r'这张卡不能(?:通常)?召唤|这张卡不能通常召唤',row.get('desc',text)))
    for sentence in re.finditer(r'[^。\r\n]+',text):
        source = sentence[0].strip()
        start = sentence.start()+len(sentence[0])-len(sentence[0].lstrip())
        masked = mask_names(source)
        substitute=re.search(r'为让[^。]{0,100}效果发动而[^。]{0,90}的场合[，,]可以作为代替',masked)
        if substitute:
            original,replacement=source.split('可以作为代替',1)
            add(blocks,'cost_replacement',source,start,'continuous','effect',replaces='activation_payment',
                original_payment_source=original.rstrip('，, '),replacement_payment_source=replacement,
                replacement_payments=payment_records(replacement),starts_chain=False)
            blocks[:]=[b for b in blocks if not (b['kind'] in ('banish','release','send_grave','discard')
                and start<=b['source_span'][0]<start+len(source))]
        overlay_replace=re.search(r'作为取除的1个超量素材的代替而(.+)',source)
        if overlay_replace:
            add(blocks,'cost_replacement',source,start,'continuous','effect',replaces='activation_payment',resource='xyz_material',
                original_quantity=1,replacement_payments=payment_records(overlay_replace[1]),starts_chain=False)
            blocks[:]=[b for b in blocks if not (b['kind'] in ('banish','detach') and start<=b['source_span'][0]<start+len(source))]
        declared=re.search(r'(?<!攻击)(?<!被)(?<!所)宣言(?!攻击|的|过|时)[^。；;，,]{1,45}',masked)
        if declared and (re.search(r'才能发动|[；;]',source) or not any(b['kind']=='declare' and b['source'] in source for b in blocks)):
            raw=source[declared.start():declared.end()]
            descriptions.append(dict(kind='declare',tag={'dimension':'parameter','value':'宣言选择'},
                source=raw,source_span=[start+declared.start(),start+declared.end()],group=key,
                block_id=f'{key}:description:declare:{len(descriptions)}',phase='activation_parameter',legality_verified=False))
        zone=re.search(r'指定[^。]{0,50}区域(\d+)处',source)
        if zone:
            variant=re.search(r'指定的区域可以变成(\d+)处',source)
            descriptions.append(dict(kind='zone_selection',tag={'dimension':'parameter','value':'区域选择'},source=source,
                group=key,block_id=f'{key}:description:zone',phase='activation_parameter',quantity=int(zone[1]),
                quantity_variants=[{'quantity':int(variant[1]),'condition_source':source}] if variant else []))
        quoted_move=re.search(r'「([^」]*位置向[^」]*怪兽区域移动)」处理重复',source)
        if quoted_move:
            add(blocks,'zone_move',quoted_move[1],start+quoted_move.start(1),'resolution','effect',
                repetition_source=source,quantity=None)
        replacement=re.search(r'作为[^。]{0,35}(?:通常抽卡|抽卡阶段[^。]{0,10}抽卡)[^。]{0,10}代替',source)
        if replacement:add(blocks,'draw_replace',source,start,'continuous','effect')
        permission=re.search(r'从手卡发动|从手卡也能用|盖放的回合也能发动',masked)
        if permission and re.search(r'可以|也能',masked):
            prefix=source[:permission.start()]
            for payment in payment_records(prefix):
                payment_source=payment.pop('source')
                add(costs,payment.pop('kind'),payment_source,start+source.index(payment_source),
                    'alternative_activation_payment','cost',**dict(payment,activation_method='from_hand',condition_source=source))
        optional=re.search(r'(?:这张卡)?也能([^。]*?)(?:来发动|[，,]在盖放的回合发动)',source)
        if optional:
            add(blocks,'activation_permission',source,start,'continuous','effect',activation_method='optional_additional_payment')
            for payment in payment_records(optional[1]):
                payment_source=payment.pop('source')
                add(costs,payment.pop('kind'),payment_source,start+source.index(payment_source),
                    'alternative_activation_payment','cost',**dict(payment,activation_method='optional_additional_payment',condition_source=source))
                blocks[:]=[b for b in blocks if not (b['kind'] in ('discard','release','banish','send_grave','reveal')
                    and payment_source in b['source'])]
        if re.search(r'通常抽卡的这张卡[^。]{0,12}持续公开',masked):
            descriptions.append(dict(kind='public_activation_condition',tag={'dimension':'description','value':'公开发动条件'},
                source=source,source_span=[start,start+len(source)],group=key,
                block_id=f'{key}:description:public',required_state='public',activation_method='drawn_this_turn'))
        if re.search(r'那个无效|那次无效',masked):
            local=text[max(text.rfind('●',0,start)+1,text.rfind('。',0,start-1)+1):start]
            if re.search(r'(?:召唤|反转召唤|特殊召唤)之际',local):
                instruction=re.search(r'那个无效|那次无效',source)
                add(blocks,'negate_summon',instruction[0],start+instruction.start(),'resolution','effect',summon_negation=True)
        named_effect_only = re.fullmatch(
            r'(?:这张卡)?(?:只能用|用)?「[^」]+」的效果(?:才能|可以)特殊召唤', source)
        specific_effect=scope=='monster' and bool(named_effect_only or re.search(r'这张卡在用[^。]{0,90}的效果[^。]{0,100}的场合才能特殊召唤|用把[^。]{0,90}解放发动的[^。]{0,90}的效果可以特殊召唤',source))
        from .effect_blocks import ACTIVATION
        is_procedure = scope=='monster' and not specific_effect and not ACTIVATION.search(masked) and not re.search(r'[；;]|(?:场合|时)[：:]',masked) and bool(
            re.search(r'这张卡(?:也)?可以从(?:手卡|墓地|额外卡组)特殊召唤',masked)
            or re.search(r'(?:这张卡可以|可以)支付\d+基本分[，,]?(?:把这张卡)?从手卡特殊召唤',masked)
            or re.search(r'(?:解放|除外|送去墓地|回到[^，]+)(?:的场合)?(?:才能|可以)(?:(?:从|在)[^，]{0,12})?(?:表侧)?(?:攻击|守备)?(?:表示)?特殊召唤',masked)
            or re.search(r'这张卡可以把[^。]{0,70}解放从手卡特殊召唤',masked)
            or re.search(r'(?:这张卡)?(?:也)?可以(?:把|让)[^。]+(?:解放|除外|送去墓地|丢弃|舍弃|回到卡组)[，,]从手卡(?:[·、]墓地)?特殊召唤',masked)
            or (intrinsic and re.search(r'(?:场合|状态)(?:才能|可以)(?:(?:从|在)[^，]{0,12})?特殊召唤',masked))
            or row.get('type',0)&0x800000 and re.search(r'重叠[^。]{0,35}(?:超量召唤|特殊召唤)',masked))
        if is_procedure:
            for b in list(blocks):
                if start<=b['source_span'][0]<start+len(source) and b['kind'] in (
                        'special_summon','xyz_summon','banish','release','send_grave','return_deck','pay_lp'):
                    blocks.remove(b)
            origin = 'extra' if row.get('type',0)&(0x40|0x2000|0x800000|0x4000000) else 'grave' if re.search(r'这张卡(?:也)?可以从墓地',masked) else 'hand'
            explicit_origin=re.search(r'[，,](从(?:手卡(?:[·、]墓地)?|墓地|额外卡组))特殊召唤',source)
            from .effect_blocks import source_zones
            origins=source_zones(explicit_origin[1]) if explicit_origin else [origin]
            kind='xyz_summon' if row.get('type',0)&0x800000 and '重叠' in masked else 'special_summon'
            # The entire sentence is the qualified procedure, including its
            # condition. Its source is not an existing field-card resource.
            add(procedures,kind,source,start,'summon_procedure','summon_procedure',
                from_zones=origins,to_zone='field',quantity=1,starts_chain=False,
                condition_source=source,legality_verified=False)
            prefix=re.split(r'(?:的场合)?(?:才能|可以)(?:(?:从|在)[^，]{0,12})?特殊召唤|(?:把这张卡)?从手卡(?:[·、]墓地)?特殊召唤|重叠',source,maxsplit=1)[0].rstrip('，,')
            for payment in payment_records(prefix):
                payment_source=payment.pop('source')
                if payment_source not in source:continue
                add(procedures,payment.pop('kind'),payment_source,start+source.index(payment_source),
                    'summon_payment','summon_procedure',**payment)
        tribute = scope=='monster' and not re.search(r'发动|[；;]',masked) and bool(re.search(
            r'这张卡[^。]{0,100}(?:解放[^。]{0,15}上级召唤|(?:祭品|解放)作召唤)|只能通过解放[^。]{0,60}来召唤|必须把[^。]{0,55}解放在[^。]{0,15}召唤|这张卡祭品召唤的场合[^。]+任意数量[^。]+作为祭品',masked))
        if re.search(r'可以不把怪兽\d+只解放而',masked):tribute=False
        if any(b['kind'] in ('tribute_reduction','tribute_count') and b['source'] in source for b in blocks):tribute=False
        if tribute:
            amount=re.search(r'(\d+)只[^。]{0,35}(?:解放|祭品)|用(\d+)只祭品',masked)
            add(procedures,'tribute_summon',source,start,'summon_procedure','summon_procedure',
                from_zones=['hand'],to_zone='field',quantity=1,starts_chain=False,
                material_quantity=int(next(v for v in amount.groups() if v)) if amount else None,
                material_selection_source=source,legality_verified=False)
            for b in list(blocks):
                if start<=b['source_span'][0]<start+len(source) and b['kind'] in ('release','normal_summon','tribute_summon'):
                    blocks.remove(b)
        # Ordinary summon source conditions are descriptions, not a spell or
        # other monster's ability to perform the referenced summon.
        condition = specific_effect or scope=='monster' and bool(re.search(
            r'只能用[^。]{0,100}(?:召唤|特殊召唤)|(?:效果|方法)(?:才能|可以)特殊召唤|(?:融合|同调|超量|连接|仪式)召唤成功[^。]{0,20}(?:才能|可以)特殊召唤',masked))
        if condition:
            item=dict(kind='summon_condition',tag={'dimension':'summon_description','value':'召唤条件'},source=source,
                group=key,block_id=f'{key}:description:condition:{len(descriptions)}',source_span=[start,start+len(source)])
            if not any(d['kind']==item['kind'] and d['source']==source for d in descriptions):descriptions.append(item)
        if specific_effect:
            blocks[:]=[b for b in blocks if not (b['kind'] in ('special_summon','send_grave','release') and start<=b['source_span'][0]<start+len(source))]
            restrictions[:]=[r for r in restrictions if not (r['kind']=='cannot_activate' and r['source']==source)]
        if condition and not is_procedure and re.search(r'这张卡(?:只能|只有|必须)|^只能用',source):
            blocks[:]=[b for b in blocks if not (b['kind'].endswith('_summon') and start<=b['source_span'][0]<start+len(source))]
        revival=re.search(r'把这张卡用卡的效果从墓地特殊召唤之际[，,](.+解放)',source)
        if revival:
            for payment in payment_records(revival[1]):
                payment_source=payment.pop('source')
                add(procedures,payment.pop('kind'),payment_source,start+source.index(payment_source),'summon_payment','summon_procedure',
                    **dict(payment,required_for='effect_revival',payer='summoning_player',condition_source=source))
            blocks[:]=[b for b in blocks if not (b['kind']=='release' and start<=b['source_span'][0]<start+len(source))]
        equip_fee=re.search(r'^(.+除外)发动的场合才能给[^。]+装备',source)
        if equip_fee:
            for payment in payment_records(equip_fee[1]):
                payment_source=payment.pop('source')
                add(costs,payment.pop('kind'),payment_source,start+source.index(payment_source),'activation_payment','cost',**payment)
            restrictions.append(dict(kind='equip_condition',tag={'dimension':'restriction','value':'装备条件'},source=source))
            blocks[:]=[b for b in blocks if not (b['kind'] in ('banish','equip') and start<=b['source_span'][0]<start+len(source))]
        upkeep = re.search(r'(?:每次|每\d*个|每到|每回合|自己的结束阶段)',masked) and re.search(r'准备阶段|结束阶段',masked) and (
            '控制者' in masked or re.search(r'不支付|不进行|若不丢弃|否则|或者都不',text)) and not re.search(r'才能发动|可以发动',masked)
        if upkeep:
            # A scheduled maintenance requirement may coexist with an activated
            # effect. It never becomes that effect's activation payment.
            for payment in payment_records(source):
                if re.search(r'不支付|不进行|若不',payment['source']):continue
                payment_source=payment.pop('source')
                add(costs,payment.pop('kind'),payment_source,start+source.index(payment_source),
                    'upkeep_payment','cost',**payment)
            for b in list(blocks):
                if start<=b['source_span'][0]<start+len(source) and b['kind'] in ('send_grave','discard','release','reveal','banish','destroy','return_deck','return_hand'):
                    if b['kind']=='destroy':
                        b['phase']='upkeep'
                        b['qualifiers'].update(subject='this_card',condition_source='upkeep_failure')
                    else:
                        blocks.remove(b)
                        b.update(phase='upkeep_payment',tag={'dimension':'cost','value':LABELS[b['kind']]})
                        b['qualifiers'].update(reason='cost',resource='public_state' if b['kind']=='reveal' else 'cards')
                        if b['kind']=='reveal':b['qualifiers']['consumes_card']=False
                        if not re.search(r'若不|不丢弃',b['source']) and not any(c['kind']==b['kind'] and c['source']==b['source'] for c in costs):costs.append(b)
        upkeep_failure=re.search(r'不能(?:支付|取除|解放|除外)[^。]{0,35}这张卡破坏|或者(?:都)?不(?:进行|支付|解放|回到|取除)[^。]{0,25}让这张卡破坏|或把这张卡破坏',source)
        if upkeep_failure:
            raw=upkeep_failure[0]
            add(blocks,'destroy',raw,start+upkeep_failure.start(),'upkeep','effect',subject='this_card',quantity=1,
                from_zones=['field'],to_zone='grave',condition_source=source)
            for b in blocks:
                if b['kind']=='destroy' and start<=b['source_span'][0]<start+len(source):
                    b['phase']='upkeep';b['qualifiers'].update(subject='this_card',quantity=1,condition_source=source)
        destination=None
        if re.search(r'被同调召唤使用[^。]{0,15}除外|同调素材怪兽不去墓地而除外',source):destination='banished'
        elif re.search(r'解放的怪兽不送去墓地回到持有者手卡',source):destination='hand'
        if destination:
            add(blocks,'grave_destination_replace',source,start,'continuous','effect',to_zone=destination,
                material_reason='synchro' if '同调' in source else 'tribute',condition_source=source)
            blocks[:]=[b for b in blocks if not (b['kind'] in ('banish','send_grave','return_hand')
                and start<=b['source_span'][0]<start+len(source))]
        tribute_replace=re.search(r'可以不把怪兽(\d+)只解放而(.+?)来上级召唤',source)
        if tribute_replace:
            add(blocks,'tribute_replace',source,start,'continuous','effect',original_material_quantity=int(tribute_replace[1]),
                replacement_payments=payment_records(tribute_replace[2]),starts_chain=False)
            blocks[:]=[b for b in blocks if not (b['kind'] in ('banish','send_grave','release','tribute_summon','normal_summon')
                and start<=b['source_span'][0]<start+len(source))]
        resolution_lp=re.search(r'控制者可以支付(\d+)基本分',source)
        if resolution_lp and re.search(r'发动[。；;]',text[:start]):
            add(blocks,'lp_payment',source,start,'resolution','effect',resource='lp',quantity=int(resolution_lp[1]),
                payer_source=source[:resolution_lp.start()+3],optional=True)
        conditional_selection=re.search(r'也能从[^。]+(?:选这个效果装备的怪兽|选加入手卡的怪兽)',source)
        if conditional_selection:
            add(blocks,'selection_expand',source,start,'continuous','effect',selector_source=source,condition_source=text[:start])
        link_sum=re.search(r'连接标记合计直到变成(\d+)为止',source)
        if link_sum:
            for b in blocks:
                if b['kind']=='special_summon' and start<=b['source_span'][0]<start+len(source):
                    b['qualifiers']['selection_sum']={'field':'link_rating','maximum':int(link_sum[1]),'source':source}
        reduced_requirement=re.search(r'指示物每有(\d+)个则少要(\d+)种类',source)
        if reduced_requirement:
            descriptions.append(dict(kind='activation_requirement_modifier',tag={'dimension':'parameter','value':'发动条件数量变更'},
                source=source,group=key,block_id=f'{key}:description:requirement',
                reduction_per_unit=int(reduced_requirement[2]),counter_unit=int(reduced_requirement[1])))
        for b in blocks:
            if not start<=b['source_span'][0]<start+len(source):continue
            bullet_start=text.rfind('●',0,b['source_span'][0])+1
            threshold=re.match(r'(\d+)(个|只|张)?(以上|以下)?[：:]',text[bullet_start:]) if bullet_start else None
            if threshold:
                b['qualifiers']['branch_condition']={'value':int(threshold[1]),'comparison':{'以上':'at_least','以下':'at_most'}.get(threshold[3],'equal'),
                    'source':threshold[0],'basis_source':text.split('●',1)[0]}
            if b['kind']=='win':
                b['phase']='rule_condition'
                b['qualifiers'].update(starts_chain=False,condition_source=source)
            if b['kind']=='effect_grant' and '有这张卡装备的' in source:
                reference=re.search(r'这个卡名的([①②③④⑤⑥⑦⑧⑨⑩])的效果',source)
                b['qualifiers']['recipient']='equipped_monster'
                if reference:b['qualifiers']['effect_reference']={'scope':'this_card_name','effect_index':'①②③④⑤⑥⑦⑧⑨⑩'.index(reference[1])+1}
            if b['kind']=='type_change' and '这张卡同调召唤的场合' in source and '当作调整使用' in source:
                b.update(kind='material_permission',tag={'dimension':'effect','value':LABELS['material_permission']})
                b['qualifiers'].update(material_role='tuner',application='this_card_synchro_material_only',subject='selected_material',condition_source=source)
            if b['kind']=='material_count' and re.search(r'作为仪式召唤需要的(?:等级)?数值的解放',source):
                b['qualifiers'].update(value_rule='full_ritual_requirement',material_reason='ritual',subject='this_card',condition_source=source)
            if b['kind']=='stats' and '骰子' in text:
                result=re.match(r'(\d+)[：:]',b['source'])
                if result:b['qualifiers']['result_condition']={'kind':'dice_result','value':int(result[1]),'source':b['source']}
            if b['kind']=='counter' and re.search(r'(?:发动时|发动的)?效果处理(?:时|后)|(?:这张卡|这个效果)(?:的)?发动时|指示物来发动',source):
                b['phase']='activation_initialization'
            if b['kind']=='special_summon' and '把装备的同盟解除' in source:
                b['qualifiers'].update(from_zones=['field'],to_zone='field',source_state='equipped_union',quantity=1)
            if b['kind']=='return_field':
                b['qualifiers'].update(from_zones=['banished'],to_zone='field',is_special_summon=False)
                b['phase']='delayed'
            if b['kind']=='control' and re.search(r'下个回合的结束阶段回归原本持有者',source):
                b['phase']='delayed';b['qualifiers'].update(destination_controller='owner',timing_source=source)
            if b['kind']=='return_deck' and '作为同调素材' in source:
                b['phase']='continuous';b['qualifiers'].update(material_reason='synchro',destination_rule='material_destination_replacement')
            if b['kind']=='reveal_top' and '额外卡组' in text[:start]:
                b['qualifiers'].update(from_zones=['extra'],quantity=1)
            if b['kind']=='lp_change' and '双方基本分合计数值的一半' in source:
                b['qualifiers'].update(resource='lp',owner='both',value_rule='half_combined_lp')
            if b['kind'] in ('destroy','send_grave','banish','return_hand','stats') and re.search(r'(?:结束|准备)阶段',source) and not re.search(r'阶段[^。]{0,30}发动',source):
                b['qualifiers']['timing_source']=source
                if re.search(r'这个回合|下次|下个|第\d+次',source):b['phase']='delayed'
            end_hand_banish = re.fullmatch(r'这个回合的结束阶段[，,]自己(\d+)张手卡除外', source)
            if b['kind'] == 'banish' and end_hand_banish:
                b['phase'] = 'delayed'
                b['qualifiers'].update(quantity=int(end_hand_banish[1]), owner='self', from_zones=['hand'],
                    to_zone='banished', selector_query={'selector': '卡'}, random=False, timing='end_phase', starts_chain=False)
            if b['kind']=='destroy' and '这张卡发动后' in source:
                b['phase']='delayed'
                b['qualifiers'].update(subject='this_card',quantity=1,from_zones=['field'],to_zone='grave',timing_source=source)
            if b['kind']=='send_grave' and '这张卡发动后' in source and '第2次的自己准备阶段' in source:
                b['phase']='delayed'
                b['qualifiers'].update(subject='this_card',quantity=1,from_zones=['field'],to_zone='grave',timing_source=source)
            if b['kind'] in ('draw','destroy','search','recover','add_hand'):
                divisor=re.search(r'每有(\d+)|每(\d+)(?:张|只|个)为1张',source)
                if divisor:
                    b['qualifiers'].update(quantity=None,quantity_rule={'kind':'source_quantity_divided',
                        'divisor':int(next(v for v in divisor.groups() if v)),'source':source})
    for i,rule in enumerate(restrictions):
        source=rule['source']
        rule.setdefault('block_id',f'{key}:restriction:{i}')
        rule.setdefault('group',key)
        if re.search(r'发动的回合|发动这个效果的回合|特殊召唤的回合',source):
            rule.update(duration='turn',whole_turn=True,condition='effect_activation' if '发动' in source else 'special_summon_this_card')
        elif re.search(r'发动后|发动以后的回合结束|直到回合结束',source):
            rule.update(duration='turn_end',whole_turn=False)
        if re.search(r'这张卡不能(?:通常|特殊)?召唤',source) and not re.search(r'这个回合|发动|自己|对方',source):
            rule.update(scope='this_card',duration='intrinsic')
        end=re.search(r'这个效果直到[^。]+为止适用',text)
        if end:rule['end_condition_source']=end[0]


def finalize_record(record):
    """Keep refinements and option costs consistent in live and exported views."""
    from .effect_blocks import LABELS
    view=record['block_view']
    key=record.get('effect_key',view['effect_key'])
    scopes=[record,*record.get('branch_records',{}).values()]
    def unbound_payment(block):
        if block['phase']!='conditional_activation_payment':return True
        activation=block['qualifiers'].get('activation_source','').strip()
        for scoped in scopes:
            if activation and scoped['source_text'].strip().startswith(activation) and any(
                c.get('choice') and c['kind']==block['kind'] and (c['source'] in block['source'] or block['source'] in c['source'])
                for c in scoped['costs']):return False
        return bool(record.get('branch_records') or block['source'] in record['source_text'])
    view['cost_blocks']=[b for b in view['cost_blocks'] if unbound_payment(b)]
    parameters=[deepcopy(d) for d in view.get('description_blocks',[]) if d.get('phase')=='activation_parameter'
        and d['source'] in record['source_text']]
    if parameters:
        record['activation_parameters']=parameters
        record['unknown'].append('activation_parameter_requires_binding')
    payment_reference=re.search(r'取除(?:的超量素材|的指示物)?数量[^。]{0,90}|以那个数量[^。]{0,80}为对象',record['source_text'])
    if payment_reference and any(c['kind'] in ('detach','remove_counter') for c in record['costs']):
        record['payment_dependencies']=[dict(source=payment_reference[0],resource='xyz_material' if '超量素材' in record['source_text'] else 'counters',
            applies_to='selector_level' if '等级' in payment_reference[0] else 'selection_or_effect_quantity')]
        record['unknown'].append('variable_payment_requires_binding')
    if view.get('alternatives',{} ) and view['alternatives'].get('mode')=='subset':
        record['unknown'].append('paid_subset_selection_requires_binding')
    if any(c['phase']=='alternative_activation_payment' for c in view['cost_blocks']):
        record['unknown'].append('activation_payment_option_requires_binding')
    if any(c['phase']=='conditional_activation_payment' for c in view['cost_blocks']):
        record['unknown'].append('nested_activation_payment_requires_binding')
    for branch in record.get('branch_records',{}).values():
        if 'block_view' in branch:finalize_record(branch)
    costs=[c for c in view['cost_blocks'] if c['phase']!='activation_payment']
    payment_blocks={}
    for i,payment in enumerate(record['costs']):
        kind=payment['kind']
        if kind not in LABELS:continue
        signature=json.dumps({k:v for k,v in payment.items() if k not in ('choice','cost_index','effect_index')},sort_keys=True,ensure_ascii=False)
        if signature in payment_blocks:
            block=payment_blocks[signature]
            choices=block['qualifiers'].setdefault('choices',[])
            previous=block['qualifiers'].pop('choice',None)
            for choice in (previous,payment.get('choice')):
                if choice and choice not in choices:choices.append(choice)
            continue
        block=dict(kind=kind,tag={'dimension':'cost','value':LABELS[kind]},
            phase='activation_payment',source=payment.get('source',''),
            qualifiers={k:deepcopy(v) for k,v in payment.items() if k not in ('kind','source')},
            block_id=f"{key}:cost:{i}",group=key)
        costs.append(block)
        payment_blocks[signature]=block
    view['cost_blocks']=costs
    for operation in record['operations']:
        if operation.get('result_condition'):
            record['unknown'].append('random_result_condition_requires_binding')
        if operation.get('quantity_rule') and not operation.get('quantity_binding'):
            operation['quantity']=None
            record['unknown'].append('dynamic_quantity_requires_binding')
        if operation['kind'] in ('special_summon','token') and '衍生物' in operation.get('source',''):
            operation.update(from_zones=[],creates_token=True)
            operation.pop('selector_query',None)
            operation.pop('selector_source',None)
        block=next((b for b in view['blocks'] if b['block_id']==operation.get('block_id')),None)
        if block and operation.get('creates_token'):
            block['qualifiers'].update(from_zones=[],creates_token=True)
            block['qualifiers'].pop('selector_query',None)
    modifiers=[]
    for sentence in re.finditer(r'[^。]+',record['source_text']):
        marker=re.search(r'这个效果加入手卡的数量|可以把加入手卡的(?:卡|怪兽)改成|也能从卡组选加入手卡的怪兽',sentence[0])
        if not marker:continue
        source=sentence[0][marker.start():]
        order=sentence.start()+marker.start()
        referenced=[o for o in record['operations'] if o['kind']=='search_or_recover' and source in o.get('source','')]
        previous=[o for o in record['operations'] if o not in referenced and o['kind']=='search_or_recover'
            and o.get('order',0)<order]
        if not previous:continue
        base=previous[-1]
        variant=dict(source=source,condition_source=sentence[0][:marker.start()])
        number=re.search(r'数量可以变成(\d+)张',source)
        if number:variant['quantity']=int(number[1])
        if '同名卡最多1张' in source:variant['maximum_per_name']=1
        if '改成' in source:variant['selector_source']=source.split('改成',1)[1]
        if '从卡组' in source:variant['from_zones']=['deck']
        base.setdefault('variants',[]).append(variant)
        b=next((b for b in view['blocks'] if b['block_id']==base.get('block_id')),None)
        if b:b['qualifiers']['variants']=deepcopy(base['variants'])
        modifiers.extend(referenced)
        if 'conditional_search_variant_requires_binding' not in record['unknown']:
            record['unknown'].append('conditional_search_variant_requires_binding')
    if modifiers:
        removed={o['block_id'] for o in modifiers}
        record['operations']=[o for o in record['operations'] if o not in modifiers]
        view['blocks']=[b for b in view['blocks'] if b['block_id'] not in removed]
        view['connectors']=[c for c in view['connectors'] if c.get('target') not in removed]
    for sentence in re.finditer(r'[^。]+',record['source_text']):
        raw=sentence[0]
        quantity=re.search(r'(?:这个效果的对象|对象|这个效果加入手卡的数量)可以变成(\d+)(?:张|只)',raw)
        reduced=re.search(r'取除的超量素材数量可以变成(\d+)个',raw)
        if quantity:
            variant=dict(quantity=int(quantity[1]),condition_source=raw[:quantity.start()],source=raw)
            for target in record['targets']:target.setdefault('quantity_variants',[]).append(deepcopy(variant))
            for operation in record['operations']:
                if operation['kind'] in ('stats','search_or_recover','special_summon','negate','destroy','banish','return_hand','return_deck') and (
                        operation.get('target_ref') is not None or len(record['targets'])==1 and
                        (operation['kind'] in ('stats','negate') or '同名怪兽' in operation.get('source',''))):
                    operation.setdefault('quantity_variants',[]).append(deepcopy(variant))
                    b=next((b for b in view['blocks'] if b['block_id']==operation.get('block_id')),None)
                    if b:b['qualifiers']['quantity_variants']=deepcopy(operation['quantity_variants'])
        if reduced:
            variant=dict(quantity=int(reduced[1]),condition_source=raw[:reduced.start()],source=raw)
            for payment in record['costs']:
                if payment['kind']=='detach':payment.setdefault('quantity_variants',[]).append(deepcopy(variant))
        if quantity or reduced:record['unknown'].append('conditional_quantity_requires_binding')
    for i,payment in enumerate(record['costs']):
        block=next((b for b in view['cost_blocks'] if b['block_id']==f'{key}:cost:{i}'),None)
        if block and payment.get('quantity_variants'):
            block['qualifiers']['quantity_variants']=deepcopy(payment['quantity_variants'])
    view['unknown']=list(dict.fromkeys(record['unknown']))
