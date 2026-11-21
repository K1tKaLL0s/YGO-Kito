"""Necessary inventory dependencies of selected functions, without action search.

Only bounded, fully recognized selectors are counted. A positive count is an
inventory upper bound, not evidence of access to a hand, field or graveyard.
Sources, unknown selectors and per-effect alternatives remain separate.
"""
from collections import Counter
from copy import deepcopy
from functools import lru_cache
from types import SimpleNamespace
from pathlib import Path
import json
import re

from .build_contracts import DeckParts, ZONES, digest
from .effect_mechanisms import EXTRA_TYPES, RACES, MechanismCatalog
from .validation import ContractError


_SPECIAL_SUMMON_ACTIONS = frozenset({
    'special_summon', 'fusion_summon', 'synchro_summon', 'xyz_summon',
    'link_summon', 'ritual_summon', 'pendulum_summon',
})


def selector(text):
    """Recognize a complete simple card selector; never discard qualifiers."""
    original = text
    if text.startswith('除效果怪兽外的'):
        query = selector(text.removeprefix('除效果怪兽外的'))
        if query is not None:
            return dict(query, predicate={'not': {'field': 'type_all', 'value': 0x20}}, selector=original)
        return None
    names = re.findall(r'「([^」]+)」', text)
    if '有那个卡名记述的' in text and len(names) == 1:
        text = text.replace('有那个卡名记述的', '有「'+names[0]+'」卡名记述的')
    alternatives = text.split('或者')
    if len(alternatives) > 1:
        queries = [selector(part) for part in alternatives]
        return dict(any=queries, selector=original) if all(queries) else None
    mention = re.fullmatch(r'有「([^」]+)」(?:的)?(?:卡名|衍生物名)记述的(怪兽|魔法卡|陷阱卡|魔法·陷阱卡|卡)', text)
    if mention:
        return dict(mentions_name=mention[1], type={'怪兽':1,'魔法卡':2,'陷阱卡':4,'魔法·陷阱卡':6,'卡':7}[mention[2]],
                    selector=original)
    query = {}
    name=None
    while text:
        before=text
        level = re.match(r"(\d+)星(?P<bound>以上|以下|以外)?(?:的)?", text)
        rank = re.match(r'(\d+)阶(?:的)?', text)
        link = re.match(r'连接(\d+)(?:的)?', text)
        attribute=re.match(r'(地|水|炎|风|光|暗|神)属性(?:的)?',text)
        stat=re.match(r'(攻击力|守备力)(\d+)(以上|以下)(?:的)?',text)
        quoted=re.match(r'「([^」]+)」',text)
        position=re.match(r'(表侧|里侧)表示(?:的)?',text)
        race=next((r for r in RACES if text.startswith(r)),None)
        if position and 'face_up' not in query:
            query['face_up']=position[1]=='表侧';text=text[position.end():]
        elif level and not {'level', 'level_between', 'exclude_level'} & query.keys():
            value=int(level[1]);bound=level['bound']
            if bound == '以外':
                if not 1 <= value <= 255:
                    return None
                query['exclude_level'] = value
            else:
                query['level_between' if bound else 'level']=([value,13] if bound=='以上' else [1,value]) if bound else value
            text=text[level.end():]
        elif rank and 'rank' not in query:
            query['rank']=int(rank[1]);text=text[rank.end():]
        elif link and 'link_rating' not in query:
            query['link_rating']=int(link[1]);text=text[link.end():]
        elif attribute and 'attribute_any' not in query:
            query['attribute_any']={'地':1,'水':2,'炎':4,'风':8,'光':16,'暗':32,'神':64}[attribute[1]]
            text=text[attribute.end():]
        elif stat:
            key=('atk' if stat[1]=='攻击力' else 'def')+('_min' if stat[3]=='以上' else '_max')
            if key in query:break
            query[key]=int(stat[2]);text=text[stat.end():]
        elif quoted and name is None:
            name=quoted[1];text=text[quoted.end():]
        elif race and 'race' not in query:
            query['race']=RACES[race];text=text[len(race):]
        if before==text:break
        text=text.lstrip('·')
    types = {'怪兽':1, '魔法卡':2, '陷阱卡':4, '魔法·陷阱卡':6, '卡':0, '':0,
        '效果怪兽':0x21,'通常怪兽':0x11,'融合怪兽':0x41,'同调怪兽':0x2001,
        '超量怪兽':0x800001,'连接怪兽':0x4000001,'灵摆怪兽':0x1000001,'仪式怪兽':0x81,
        '场地魔法卡':0x80002,'装备魔法卡':0x40002,'速攻魔法卡':0x10002}
    if text not in types or not query and text == '':
        if text or name is None:return None
    if name is not None:query['name_contains' if text else 'exact_name']=name
    if types[text]:query['type_all' if types[text] not in (1,2,4,6) else 'type'] = types[text]
    return dict(query, selector=original)


def query_supported(query):
    """Only complete existing public predicates can select definite stock."""
    if not isinstance(query, dict) or not query:
        return False
    if set(query) <= {'selector','face_up'} and query.get('selector') != '卡':
        return False
    strings = {'selector', 'exact_name', 'name_contains', 'exclude_name', 'mentions_name'}
    numbers = {'level', 'exclude_level', 'rank', 'link_rating', 'setcode', 'type', 'race', 'type_all', 'race_any', 'attribute_any',
               'atk_min','atk_max','def_min','def_max'}
    if set(query) - strings - numbers - {'predicate', 'level_between', 'face_up', 'any'}:
        return False
    if 'any' in query and (not isinstance(query['any'], list) or not query['any']
            or not all(query_supported(q) for q in query['any'])):
        return False
    if any(not isinstance(query[k], str) for k in strings & query.keys()) or any(
            type(query[k]) is not int for k in numbers & query.keys()):
        return False
    if 'exclude_level' in query and not 1 <= query['exclude_level'] <= 255:
        return False
    if 'face_up' in query and type(query['face_up']) is not bool:
        return False
    from .build_semantics import validate_predicate
    try:
        if 'level_between' in query:
            validate_predicate({'field':'level_between', 'value':query['level_between']}, ())
        if 'predicate' in query:
            def ids(node):
                if 'field' in node:
                    return node['value'] if node['field']=='card_ids' else []
                return [v for k,children in node.items() for child in ([children] if k=='not' else children) for v in ids(child)]
            validate_predicate(query['predicate'], ids(query['predicate']))
    except (ContractError, TypeError, KeyError, AttributeError):
        return False
    return True


def matches(row, query):
    if not query_supported(query):
        raise ContractError('incomplete inventory selector')
    if 'exact_name' in query and row.get('name') != query['exact_name']:return False
    if 'exclude_name' in query and query['exclude_name'] == row.get('name'):return False
    if 'mentions_name' in query and query['mentions_name'] not in re.findall(r'[「『]([^」』]+)[」』]',row.get('desc','')):
        return False
    if 'any' in query and not any(matches(row, q) for q in query['any']):return False
    if 'setcode' in query:
        from .build_semantics import matches as predicate_matches
        if not predicate_matches(row,{'field':'setcode','value':query['setcode']}):return False
    elif query.get('name_contains', '') not in row.get('name', ''):
        # Only an explicit rule-level name treatment extends membership. An
        # effect mentioning or searching another archetype does not do so.
        aliases=re.findall(r'规则上也?当作「([^」]+)」',row.get('desc',''))
        if not any(query['name_contains'] in name for name in aliases):return False
    card_type = row.get('type', 0)
    has_rank_or_link = card_type & (0x800000 | 0x4000000)
    if 'level' in query and row.get('level', 0) & 255 != query['level']:return False
    if ('level' in query or 'level_between' in query) and has_rank_or_link:return False
    # The CDB reuses the level column for Xyz rank and Link rating.
    if 'exclude_level' in query and card_type & 1 and not has_rank_or_link:
        level = max(1, row.get('level', 0) & 255)
        if level == query['exclude_level']:
            return False
    for field, kind in (('rank', 0x800000), ('link_rating', 0x4000000)):
        if field in query and (not card_type & kind or row.get('level', 0) & 255 != query[field]):
            return False
    for stat in ('atk','def'):
        value=row.get(stat)
        if value is not None and value>=0:
            if stat+'_min' in query and value<query[stat+'_min']:return False
            if stat+'_max' in query and value>query[stat+'_max']:return False
    if not all(key not in query or bool(row.get(key, 0) & query[key]) for key in ('type','race')):
        return False
    from .build_semantics import matches as predicate_matches
    for key in ('type_all', 'race_any', 'attribute_any', 'level_between'):
        if key in query and not predicate_matches(row, {'field':key,'value':query[key]}):
            return False
    return 'predicate' not in query or predicate_matches(row, query['predicate'])


def printed_extra_material_slots(row):
    """Parse complete ordinary Xyz or inclusion-based Link material lines."""
    source = row.get('desc', '').partition('\n')[0].strip().rstrip('。')
    card_type = row.get('type', 0)
    if card_type & 0x800000:
        clause = re.fullmatch(r'(?P<selector>.+?)\s*[×x](?P<count>[2-9])(?:只)?(?:以上)?', source)
        if clause:
            query = selector(clause['selector'])
            if query_supported(query):
                return [dict(selector_query=query, count=int(clause['count']), source=source, summon_type='xyz')]
    if card_type & 0x4000000:
        clause = re.fullmatch(r'包含(?P<selector>.+?)在内的怪兽(?P<count>[2-6])只(?:以上)?', source)
        if clause:
            selected = clause['selector']
            ratings = re.fullmatch(r'((?:\d+(?:星|阶)|连接\d+)(?:[·、](?:\d+(?:星|阶)|连接\d+))+)的怪兽', selected)
            query = dict(any=[selector(part + '怪兽') for part in re.split('[·、]', ratings[1])],
                         selector=selected) if ratings else selector(selected)
            if query_supported(query):
                return [dict(selector_query=query, count=1, source=source, summon_type='link'),
                        dict(selector_query={'type': 1}, count=int(clause['count'])-1, source=source, summon_type='link')]
    return []


def printed_link_material(row):
    """Recognize a complete single-selector Link material line."""
    if not row.get('type', 0) & 0x4000000:
        return None
    source = row.get('desc', '').partition('\n')[0].strip().rstrip('。')
    clause = re.fullmatch(r'(?P<selector>.+?)(?P<count>[1-6])只(?P<at_least>以上)?', source)
    if not clause:
        return None
    selector_text = clause['selector']
    excludes_link = selector_text.startswith('连接怪兽以外的')
    normal_summoned = selector_text.startswith('通常召唤的')
    selector_text = selector_text.removeprefix('连接怪兽以外的').removeprefix('通常召唤的')
    query = selector(selector_text)
    if not query_supported(query):
        return None
    if excludes_link:
        query['predicate'] = {'not': {'field': 'type_all', 'value': 0x4000000}}
    return dict(query=query, minimum=int(clause['count']), exact=not clause['at_least'],
                normal_summoned=normal_summoned, source=source, rating=row.get('level', 0) & 255)


@lru_cache(maxsize=8)
def archetype_names(database_commit, cards_sha256):
    """Names travel with the package, bound to the actual native card catalog."""
    path=Path(__file__).with_name('resources')/'rules/native-archetype-names.json'
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        source=data['source'];names=data['names']
        if (source['database_commit']!=database_commit or source['cards_sha256']!=cards_sha256
            or not names or any(not isinstance(k,str) or v is not None and
                               (type(v) is not int or not 0<v<=0xffff) for k,v in names.items())):
            raise ContractError('archetype registry differs from the locked card catalog')
        return names,dict(source,registry_sha256=digest(names))
    except (OSError,ValueError,KeyError,TypeError) as error:
        raise ContractError('locked archetype registry is missing or invalid') from error


def asset_archetype_names(assets):
    receipt = assets.receipt
    commits = receipt.get('source_commits') or {}
    # The engine version alone does not identify the card database.
    if 'database' in commits or 'source_lock_sha256' in receipt:
        return archetype_names(commits.get('database'), receipt.get('resources', {}).get('cards'))
    return getattr(assets, 'set_names', {}), None


_MOVE_ZONES = r'(?:额外卡组|融合卡组|手卡|卡组|墓地|场上|除外状态)(?:[·、／/](?:手卡|卡组|墓地|场上|除外状态))*'
_MOVE_ACTION = r'送去墓地|加入手卡|特殊召唤|通常召唤|上级召唤|除外|解放|返回卡组|回到卡组|返回额外卡组|回到额外卡组|返回手卡|回到手卡|给对方观看'
_MOVE = re.compile(r"(?:从|把|将)(?P<owner>自己|对方|双方)?(?:的)?(?P<zone>"+_MOVE_ZONES+r")(?:的)?(?:把|将|选)?"
                   r"(?P<selection>.+?)(?P<action>(?:"+_MOVE_ACTION+r')(?:或(?:'+_MOVE_ACTION+r'))?)$')
_MOVE_POSTFIX = re.compile(r'(?:把|将|选)(?P<selection>.+?)从(?P<owner>自己|对方|双方)?(?:的)?'
                          r'(?P<zone>'+_MOVE_ZONES+r')(?P<action>(?:'+_MOVE_ACTION+r')(?:或(?:'+_MOVE_ACTION+r'))?)$')


def requirement(source, category):
    original_source = source
    if category == 'operations' and '表侧表示加入' in source:
        alternate_destination = re.fullmatch(
            r'(?:(?:攻击|守备)表示[：:])?从(?:自己的?)?卡组选(\d+)[只张](.+?)表侧表示加入(?:自己的?)?额外卡组或送去墓地',
            source)
        if alternate_destination:
            query = selector(alternate_destination[2])
            quantity = int(alternate_destination[1])
            if quantity > 0 and query_supported(query):
                return dict(query=query, minimum=quantity, source=original_source,
                    origin='deck', origins=['deck'], owner='self', category=category,
                    action='加入额外卡组或送去墓地', actions=['加入额外卡组','送去墓地'])
    normal = re.fullmatch(r'(?:可以)?(?:自己)?(?:把|将)(\d+只[^。；，]*怪兽)(?:通常)?召唤', source)
    if normal and category == 'operations':
        source = '从手卡把' + normal[1] + '通常召唤'
    either = re.fullmatch(r'从(?:自己)?手卡(?:以及|和)自己场上的表侧表示怪兽之中(?:把|将)(\d+只.+?怪兽)除外', source)
    if either:
        source = '从手卡·场上把' + either[1] + '除外'
    faceup_send = re.fullmatch(r'从(?:自己)?手卡(?:以及|和)自己场上的表侧表示的卡之中'
        r'(?P<instruction>(?:选|把|将)\d+张[^。；，]+送去墓地)', source)
    if faceup_send:
        source = '从手卡·场上' + faceup_send['instruction']
    if source.endswith('特殊召唤'):
        source = re.sub(r'(?:当作|作为)(?:融合|同调|超量|连接|仪式)召唤(?:处理)?', '', source)
        source = re.sub(r'^除效果怪兽外的(\d+只)(?=.+从(?:自己)?(?:的)?额外卡组特殊召唤$)',
                        r'把\1除效果怪兽外的', source)
    selected_discard = (re.fullmatch(r'从(?:自己的?)?手卡(?:丢弃|舍弃)(\d+[只张][^。；，]+)', source)
                        if category == 'costs' else None)
    if selected_discard:
        source = '从手卡把' + selected_discard[1] + '送去墓地'
    match = _MOVE.fullmatch(source) or _MOVE_POSTFIX.fullmatch(source)
    if not match:
        discard = re.fullmatch(r"(?:丢弃|舍弃)(\d+)张手卡", source)
        if discard:return dict(query={'selector':'卡'}, minimum=int(discard[1]), source=source,
                               origin='hand', owner='self', category=category)
        return None
    selection = match['selection']
    other = bool(re.match(r'\d+[只张]其他的',selection))
    selection = re.sub(r'^(\d+[只张])其他的',r'\1',selection)
    names = re.findall(r'「([^」]+)」', selection)
    if '有那个卡名记述的' in selection and len(names) == 1:
        selection = selection.replace('有那个卡名记述的','有「'+names[0]+'」卡名记述的')
    options, quantities = [], []
    for option in selection.split('或者'):
        chosen = re.fullmatch(r'(?P<exclude>「[^」]+」以外的)?(?P<n>\d+)(?P<unit>[只张])(?P<selector>.+)', option)
        if not chosen:return None
        query = selector(chosen['selector'])
        if query is None:return None
        if chosen['unit']=='只':query.setdefault('type',1)
        if chosen['exclude']:query['exclude_name']=chosen['exclude'][1:chosen['exclude'].index('」')]
        options.append(query);quantities.append(int(chosen['n']))
    if len(set(quantities)) != 1 or quantities[0] < 1:return None
    query = options[0] if len(options)==1 else dict(any=options,selector=selection)
    origins=[{'手卡':'hand','卡组':'deck','墓地':'grave','场上':'field','额外卡组':'extra',
        '融合卡组':'extra','除外状态':'banished'}[z] for z in re.split(r'[·、／/]',match['zone'])]
    return dict(query=query, minimum=quantities[0], source=original_source,
                origin=origins[0] if len(origins)==1 else 'choice', origins=origins,
                owner={'自己':'self','对方':'opponent','双方':'both',None:'self'}[match['owner']],
                category=category, action='丢弃' if selected_discard else match['action'],
                actions=['丢弃'] if selected_discard else match['action'].split('或'),
                **({'origin_states': {'field': 'face_up'}} if either or faceup_send else {}),
                **({'exclude_source_copy':True} if other else {}))


def effect_matches(record, tags):
    functional = [t for t in tags if t.dimension in ('effect', 'effect_type', 'role')]
    if not functional:return False
    operations = [o for o in record['operations'] if o.get('reason') == 'effect']
    for tag in functional:
        if tag.dimension == 'effect' and tag.value == '卡组送墓':
            if not any(o['kind'] in ('mill','send_grave') and tuple(o.get('from_zones',())) == ('deck',) for o in operations):return False
        elif tag.dimension == 'effect' and tag.value == '墓地融合':
            if record['trigger'].get('event') != 'sent_to_grave' or not any(o['kind']=='fusion_summon' for o in operations):return False
        elif tag.dimension == 'effect_type':
            if not any(o['kind'] == tag.value for o in operations):return False
        elif tag.dimension == 'effect':
            if not any(b['tag']['value']==tag.value for b in record.get('block_view',{}).get('blocks',())):return False
        else:return False
    return True


def qualified_effect_node(node):
    return getattr(node, 'requirements', None) is not None or (
        any(t.dimension in ('field', 'race') for t in node.tags)
        and any(t.dimension in ('effect', 'effect_type') for t in node.tags))


def _operation_matches_tag(record, operation, tag):
    from .effect_blocks import LABELS

    kind = operation['kind']
    if tag.dimension == 'effect_type':
        return kind == tag.value
    if tag.value == '卡组送墓':
        return kind in ('mill', 'send_grave') and operation.get('from_zones') == ['deck']
    if tag.value == '墓地融合':
        return kind == 'fusion_summon' and record['trigger'].get('event') == 'sent_to_grave'
    block_id = operation.get('block_id', '')
    return any(
        (block_id == b['block_id'] or block_id.startswith(b['block_id'] + ':'))
        and b['tag']['value'] == tag.value
        for b in record.get('block_view', {}).get('blocks', ())
    ) or LABELS.get(kind) == tag.value


def _printed_setcode(query, code):
    if query.get('setcode') == code:
        return True
    predicate = query.get('predicate') or {}
    if predicate == {'field': 'setcode', 'value': code}:
        return True
    children = predicate.get('all', ()) or predicate.get('any', ())
    return any(_printed_setcode({'predicate': child}, code) for child in children) or any(
        _printed_setcode(child, code) for child in query.get('any', ()))


def _activation_target(record, operation, *, availability_timing=None):
    reference = operation.get('target_ref')
    if type(reference) is int and 0 <= reference < len(record['targets']):
        target = record['targets'][reference]
        if (target.get('timing') == 'activation'
                and (availability_timing is None or target.get('availability_timing') == availability_timing)):
            return target
    return None


def _has_self_grave_payment(record):
    return any(cost.get("subject") == "this_card" and cost.get("requires_arrival")
               and cost["kind"] == "send_grave" and cost.get("to_zone") == "grave"
               for cost in record["costs"])


def _processing_activation_source(record):
    query = {'predicate': {'field': 'card_ids', 'value': [record['card_id']]}}
    source = 'activation source: ' + record['source_text']
    return dict(query=query, minimum=1, origin='field', owner='self', category='source', source=source)


def _field_source_needs_reservation(record, requirements):
    return record.get('trigger', {}).get('zone') == 'field' and all(
        'field' not in req.get('origins', (req['origin'],)) for req in requirements)


class InventoryDependencies:
    def __init__(self, catalog, *, requirement_limit=1024):
        self.catalog = catalog
        self.rows = catalog.assets.rows
        self.requirement_limit = requirement_limit
        self._specifications = {}
        self._processing = {}
        self.set_names, self.registry_source = asset_archetype_names(catalog.assets)
        self.strict_names = bool(self.set_names or self.registry_source)

    def holder_matches(self, code, node, fact_tags=None):
        from .build_semantics import matches as public_matches

        for tag in node.tags:
            if tag.dimension not in ('field', 'race'):
                continue
            fact = (fact_tags or {}).get(tag)
            if fact is not None:
                field, value = fact.field, fact.value
            else:
                field = 'setcode' if tag.dimension == 'field' else 'race_any'
                prefix = field + ':'
                if tag.value.startswith(prefix):
                    try:
                        value = int(tag.value.removeprefix(prefix), 16)
                    except ValueError:
                        return False
                else:
                    value = (self.set_names if field == 'setcode' else RACES).get(tag.value)
            if not value or not public_matches(self.rows[code], dict(field=field, value=value)):
                return False
        return True

    def draft_matches(self, code, node, *, records=None, fact_tags=None):
        """Return exact effect/operation pairs that support one draft node."""
        from .effect_records import operation_record

        tags = tuple(t for t in node.tags if t.dimension in ('effect', 'effect_type'))
        if not tags or not self.holder_matches(code, node, fact_tags):
            return ()
        requirements = getattr(node, 'requirements', None)
        records = self.catalog.effect_records(code) if records is None else records
        hits = []
        if requirements is not None and requirements.reason == 'cost':
            for record in records:
                branches = record.get('branch_records') or {None: record}
                for branch in branches.values():
                    scoped = dict(record, **branch) if branch is not record else record
                    for block in scoped['block_view'].get('cost_blocks', ()):
                        operation = dict(block['qualifiers'], kind=block['kind'], source=block['source'],
                                         block_id=block['block_id'], reason='cost')
                        if (all(_operation_matches_tag(scoped, operation, tag) for tag in tags)
                                and self._draft_requirements(scoped, operation, requirements)):
                            hits.append((scoped, operation))
            return tuple(hits)
        for record in records:
            branches = record.get('branch_records')
            for operation in record['operations']:
                if operation.get('reason') != 'effect':
                    continue
                scope = branches.get(operation.get('choice')) if branches else record
                if scope is None or not _operation_matches_tag(scope, operation, tags[0]):
                    continue
                scoped = operation_record(record, operation)
                if not all(any(op.get('reason') == 'effect' and _operation_matches_tag(scoped, op, tag)
                               for op in scoped['operations']) for tag in tags[1:]):
                    continue
                if requirements is not None and not self._draft_requirements(scoped, operation, requirements):
                    continue
                hits.append((scoped, operation))
        return tuple(hits)

    def draft_operation_query(self, record, operation):
        from .construction_theme import operation_query

        query = operation_query(operation, self)
        target_ref = operation.get('target_ref')
        if query is None and type(target_ref) is int and 0 <= target_ref < len(record['targets']):
            target = self.item_requirement(record['targets'][target_ref], 'targets')
            query = target['query'] if target else None
        return query

    def draft_grave_domain(self, record, operation):
        """Known own Deck-to-GY domain, including an unrestricted random mill."""
        if (operation.get('reason') != 'effect' or operation.get('owner') not in ('self', 'both')
                or 'deck' not in operation.get('from_zones', ()) or operation.get('to_zone') != 'grave'):
            return None
        query = self.draft_operation_query(record, operation)
        return {} if query is None and operation.get('random') else query

    def draft_grave_receiver(self, domain, receiver, record):
        trigger = record['trigger']
        return (trigger.get('event') == 'sent_to_grave'
                and trigger.get('reason') in ('effect', 'not_applicable')
                and (not domain or matches(self.rows[receiver], domain)))

    def _draft_requirements(self, record, operation, demand):
        trigger = record['trigger']
        if (demand.from_zone and demand.from_zone not in operation.get('from_zones', ())
                or demand.to_zone and demand.to_zone != operation.get('to_zone')
                or demand.reason and demand.reason != operation.get('reason')
                or demand.trigger and demand.trigger != trigger.get('event')
                or demand.trigger_reason and demand.trigger_reason != trigger.get('reason')):
            return False
        if demand.selector_setcode:
            query = self.draft_operation_query(record, operation)
            if not query or not _printed_setcode(query, demand.selector_setcode):
                return False
        if demand.material_setcode:
            materials = (*record.get('fusion_material_selection', {}).get('materials', ()),
                         *(operation.get('materials') or ()), *record.get('printed_materials', ()))
            queries = [row.get('selector_query') or
                       ({'predicate': row['predicate']} if 'predicate' in row else
                        {row['kind']: row['value']} if 'kind' in row and 'value' in row else {})
                       for row in materials if isinstance(row, dict)]
            if not any(_printed_setcode(self.resolve_query(query), demand.material_setcode) for query in queries):
                return False
        return True

    def resolve_query(self,query):
        query = deepcopy(query)
        if 'any' in query:query['any']=[self.resolve_query(q) for q in query['any']]
        types = {'monster':1, 'spell':2, 'trap':4, 'fusion':0x41, 'synchro':0x2001,
                 'xyz':0x800001, 'link':0x4000001, 'ritual':0x81, 'pendulum':0x1000001}
        if isinstance(query.get('type'), str) and query['type'] in types:
            query['type_all'] = types[query.pop('type')]
        name=query.get('name_contains')
        if name and self.strict_names:
            code=self.set_names.get(name)
            return dict(query,**({'setcode':code} if code else {'unknown_archetype':name}))
        return query

    def item_requirement(self, item, category):
        source = item.get('source','')
        if category == 'targets':
            source = re.sub(r'^以(?P<owner>自己|对方)(?:的)?', r'从\g<owner>', source)
            source = re.sub(r'为对象$', '送去墓地', source)
        parsed = requirement(source, category)
        query = item.get('selector_query')
        if query is None and item.get('selector'):
            query = selector(item['selector'])
        query = query or (parsed['query'] if parsed else None)
        query = self.resolve_query(query) if query else None
        if not query_supported(query):
            return None
        if parsed:
            if item.get('quantity') is not None and item['quantity'] != parsed['minimum']:
                return None
            return dict(parsed, query=query, source=item.get('source',''),
                **{k:item[k] for k in ('source_card_id','exclude_source_copy') if k in item})
        origins = item.get('from_zones', item.get('zones', ()))
        quantity = item.get('quantity')
        if (type(quantity) is not int or quantity < 1 or not origins
                or any(z not in ('hand','deck','grave','field','extra','banished','xyz_material') for z in origins)):
            return None
        return dict(query=query, minimum=quantity, source=item.get('source',''), origin=origins[0] if len(origins)==1 else 'choice',origins=list(origins),
                    owner=item.get('owner','unknown'), category=category,
                    **{k:item[k] for k in ('source_card_id','exclude_source_copy') if k in item})

    @lru_cache(maxsize=256)
    def intrinsic_restrictions(self, code):
        from .construction_relations import _INTRINSIC_RESTRICTIONS, _restriction_contract
        # The card dictionary already observes special-summon prohibitions.
        # Its short source must be checked against the entire printed clause.
        text = re.split(r'【怪兽(?:效果|描述)】', self.rows[code].get('desc', ''))[-1]
        prelude = re.split(r'[①②③④⑤⑥⑦⑧⑨⑩]\s*[：:]', text, maxsplit=1)[0]
        clauses = [s.strip() for s in re.split(r'[。\n]', prelude) if s.strip()]
        entry = self.catalog.effect_blocks(code)
        exclusive_methods = {
            block['source']: set(block.get('qualifiers', {}).get('from_zones', ()))
            for view in entry['effects'] if view['scope'] == 'monster'
            for block in (*view['description_blocks'], *view['procedure_blocks'])
            if block['kind'] in ('summon_condition', 'special_summon')
            and (re.search(r'才能(?:从(?:手卡|墓地|额外卡组))?特殊召唤$', block['source'])
                 or re.fullmatch(r'(?:这张卡)?(?:只能|必须)[^。]+特殊召唤', block['source']))
        }
        observed_rules = list(entry.get('card_restrictions', ()))
        for clause in clauses:
            grave_lock = '这张卡不能从墓地特殊召唤'
            if (clause == grave_lock or clause.startswith((grave_lock + '，', grave_lock + ','))) and not any(
                    r['kind'] == 'cannot_special_summon_this_card' and r['source'] == grave_lock
                    for r in observed_rules):
                observed_rules.append(dict(kind='cannot_special_summon_this_card', scope='this_card',
                    duration='intrinsic', condition='this_card_in_zone', from_zones=['grave'], source=grave_lock))
            if clause in exclusive_methods:
                observed_rules.append(dict(kind='special_summon_condition', scope='this_card', duration='intrinsic',
                    condition='summon_method', source=clause, unknown=['summon_method_eligibility']))
            for word,kind in (('通常','normal'),('特殊','special')):
                if re.fullmatch(r'(?:这张卡)?不能'+word+r'召唤(?:（盖放）|\(盖放\))?',clause):
                    observed_rules.append(dict(kind='cannot_'+kind+'_summon_this_card',scope='this_card',
                        duration='intrinsic',condition='this_card',source=clause))
            for name,kind in (('融合','fusion'),('同调','synchro'),('超量','xyz'),('连接','link'),('仪式','ritual')):
                if '不能作为'+name in clause and not any(r['source'] == clause for r in observed_rules):
                    observed_rules.append(dict(kind='cannot_be_'+kind+'_material', scope='this_card',
                        duration='while_applicable', condition='this_card', source=clause))
        understood = {r['source'].strip() for r in observed_rules if _restriction_contract(r)}
        understood.update(limit['source'].strip() for record in entry.get('source_records', ())
            for limit in record['count_limits'] if limit.get('status') == 'known')
        if entry.get('summon_materials') and entry.get('summon_material_source'):
            understood.add(entry['summon_material_source'].strip())
        complete_legacy_effect = any(
            record['source_text'].strip() == text.strip() and record['effect_index'] == 0
            and record.get('lua_source', {}).get('preselected_grave_summon_status') == 'bound'
            for record in entry['source_records'])
        rules = []
        for observed in observed_rules:
            if observed['kind'] not in _INTRINSIC_RESTRICTIONS:
                continue
            rule = deepcopy(observed)
            full = [s for s in clauses if rule['source'].strip() in s]
            if len(full) == 1 and full[0] != rule['source']:
                rule.update(observed_source=rule['source'], source=full[0])
            elif len(full) != 1:
                rule['unknown'] = ['complete_intrinsic_clause']
            known_grave_lock = (complete_legacy_effect and observed['kind'] == 'cannot_special_summon_this_card'
                                and observed.get('from_zones') == ['grave'])
            independent_methods = set()
            if observed['kind'] == 'cannot_normal_summon_this_card':
                independent_methods = exclusive_methods.keys()
            elif observed.get('from_zones'):
                independent_methods = {source for source, zones in exclusive_methods.items()
                                       if zones and zones.isdisjoint(observed['from_zones'])}
            if not known_grave_lock and any(
                    s not in understood and s not in full and s not in independent_methods for s in clauses):
                # A second sentence can qualify the first prohibition. Do not
                # certify that first sentence while dropping its context.
                rule.update(unknown=[*rule.get('unknown', ()), 'complete_intrinsic_context'], context_source=prelude)
            if rule not in rules:
                rules.append(rule)
        return tuple(rules)

    def candidate_status(self, code, req, *, target=None):
        """Eligibility of this entity for this action, independent of access."""
        from .construction_relations import _restriction_contract
        operation = req.get('operation', {})
        action = operation.get('kind') if req['category'] == 'operations' else None
        material = req['category'] == 'material'
        summon_type = req.get('summon_type')
        if material and summon_type is None and target is not None:
            summon_type = next((name for name,mask in (('fusion',0x40),('synchro',0x2000),
                ('xyz',0x800000),('link',0x4000000),('ritual',0x80)) if self.rows[target]['type'] & mask), None)
        kinds = ({'cannot_be_'+summon_type+'_material'} if material and summon_type else
                 set() if material and target is not None else
                 {k for k in ('cannot_be_'+s+'_material' for s in ('fusion','synchro','xyz','link','ritual'))} if material else
                 {'cannot_normal_summon_this_card'} if action in ('normal_summon', 'tribute_summon', 'normal_set') else
                 {'cannot_special_summon_this_card', 'special_summon_condition'}
                 if action in _SPECIAL_SUMMON_ACTIONS else set())
        if not kinds:
            return True, []
        origins = operation.get('from_zones', ()) if operation else (
            [req['origin']] if req.get('origin') in ('hand', 'deck', 'grave', 'field', 'banished', 'extra') else [])
        checks = []
        for restriction in self.intrinsic_restrictions(code):
            if restriction['kind'] not in kinds:
                continue
            rule = _restriction_contract(restriction)
            allowed = None
            if rule and not (material and target is None):
                if action == 'normal_set' and not rule.get('includes_set'):
                    allowed = True
                elif rule['condition'] == 'summoned_this_turn':
                    history = req.get('summon_history')
                    if history is None or history.get('this_turn') is False:
                        allowed = True
                    else:
                        previous = history.get('kind')
                        prohibited = rule['summon_kind']
                        special_methods = ('fusion_summon', 'synchro_summon', 'xyz_summon', 'link_summon',
                                           'ritual_summon', 'pendulum_summon')
                        if previous == prohibited or prohibited == 'special_summon' and previous in special_methods:
                            allowed = False if history.get('this_turn') is True else None
                        elif previous is not None and not (previous == 'special_summon' and prohibited in special_methods):
                            allowed = True
                elif rule.get('from_zones'):
                    zones, applies = set(origins), set(rule['from_zones'])
                    if zones and not zones & applies:
                        allowed = True
                    elif zones and zones <= applies and 'field' not in applies:
                        allowed = False
                    # Field presence alone does not prove the source's face-up
                    # monster-zone state. Keep that state unresolved here.
                else:
                    allowed = False
            if allowed is False and action in _SPECIAL_SUMMON_ACTIONS and operation.get('ignore_summon_conditions') is True:
                # The operation can bypass some summon checks. Its text alone
                # does not establish that this recipient's restriction is bypassable.
                allowed = None
            checks.append(dict(card_id=code, target_card_id=target, action=(summon_type or 'unknown')+'_material' if material else action,
                from_zones=list(origins), controller=operation.get('controller'), allowed=allowed,
                restriction=deepcopy(restriction), contract=rule))
        return (False if any(r['allowed'] is False for r in checks) else
                None if any(r['allowed'] is None for r in checks) else True), checks

    def summon_trigger_check(self, code, record):
        event = record['trigger'].get('event')
        actions = ('normal_summon', 'special_summon') if event == 'normal_or_special_summon' else (
            (event,) if event in ('normal_summon', 'tribute_summon', 'special_summon') else ())
        if record['trigger'].get('summon_kind') == 'pendulum_summon':
            actions = ('pendulum_summon',)
        candidates = [self.candidate_status(code, dict(category='operations', operation={'kind':action}))
                      for action in actions]
        allowed = True if not candidates or any(s is True for s,_ in candidates) else (
            None if any(s is None for s,_ in candidates) else False)
        return dict(status='missing' if allowed is False else 'unknown' if allowed is None else 'inventory_present',
            shortfall=int(allowed is False), restriction_checks=[r for _,checks in candidates for r in checks],
            event=event, access_to_required_zone_verified=False)

    @lru_cache(maxsize=256)
    def specs(self, code):
        if code in self._specifications:
            return self._specifications[code]
        profile = self.catalog.card(code)
        effects = []
        from .construction_relations import _INTRINSIC_RESTRICTIONS
        card_rules = [*self.intrinsic_restrictions(code), *(r for r in
            self.catalog.effect_blocks(code).get('card_restrictions', ()) if r['kind'] not in _INTRINSIC_RESTRICTIONS)]
        for pos, observed in enumerate(self.catalog.effect_records(code)):
            record = deepcopy(observed)
            # Refine a legacy generic payment only when its entire source is
            # understood. The recognizer and its original observation stay intact.
            for item in record['costs']:
                parsed = requirement(item.get('source',''), 'costs')
                if parsed and item.get('kind') == 'payment':
                    action = {'除外':('banish','banished'), '送去墓地':('send_grave','grave'),
                        '解放':('release','grave'), '加入手卡':('add_hand','hand'),
                        '返回手卡':('return','hand'), '回到手卡':('return','hand'),
                        '返回卡组':('return','deck'), '回到卡组':('return','deck'),
                        '返回额外卡组':('return','extra'), '回到额外卡组':('return','extra')}.get(parsed.get('action'))
                    if action and (item.get('quantity') is None or item['quantity'] == parsed['minimum']):
                        item['observed_payment'] = deepcopy(item)
                        item.update(kind=action[0], from_zones=[parsed['origin']], to_zone=action[1],
                            quantity=parsed['minimum'], owner=parsed['owner'], reason='cost',
                            selector_query=parsed['query'])
            complete_operations = []
            for item in record['operations']:
                parsed = requirement(item.get('source', ''), 'operations')
                if (parsed and item.get('quantity') in (None, parsed['minimum'])
                        and item.get('owner') in (None, 'unknown', parsed['owner'])
                        and item.get('from_zones', []) in ([], [parsed['origin']])):
                    item['observed_operation'] = deepcopy(item)
                    item.update(from_zones=[parsed['origin']], owner=parsed['owner'],
                        quantity=parsed['minimum'], selector_query=parsed['query'], random=False)
                    complete_operations.append(item['source'])
            # The complete existing movement parser may fill a missing field;
            # a coarse verb or an unhandled suffix cannot clear a resolution gap.
            if complete_operations and len(complete_operations) == len(record['operations']):
                body = record.get('source_text', '').partition('发动')[2]
                if body:
                    for source in complete_operations:
                        body = body.replace(source, '', 1)
                    if not body.strip('。．.，,：:；; 　\n'):
                        for container in (record, record.get('block_view', {})):
                            container['unknown'] = [v for v in container.get('unknown', ())
                                if v not in ('resolution', 'unparsed_resolution_or_restriction')]
            if record.get('scope') == 'monster':
                for rule in card_rules:
                    if rule not in record['card_restrictions']:
                        record['card_restrictions'].append(deepcopy(rule))
            requirements, unknown = [], []
            required_processing = {block for op in record['operations'] for block in op.get('depends_on', ())}
            for category in ('costs','targets','operations'):
                for item in record[category]:
                    if category=='operations' and item.get('outcome_requirement'):
                        requirements.append(dict(item['outcome_requirement'],category='outcome',operation=item,
                            source=item['source']))
                    if (category == 'operations' and item.get('processing_role') == 'auxiliary'
                            and item['block_id'] not in required_processing):
                        continue
                    if category=='operations' and item.get('phase') in ('delayed','replacement'):
                        continue  # Its sourced result identity/timing is retained on the operation.
                    if category=='operations' and item.get('generation',{}).get('kind')=='token':
                        continue  # This entity is generated, never a Main/Extra copy.
                    if category=='operations' and item.get('subject')=='activated_card':
                        continue  # Printed response range; no particular current card is asserted.
                    if (category=='operations' and record.get('fusion_material_selection')
                            and item['kind'] in ('return_fusion_materials','fusion_summon')):
                        continue  # Full printed-material alternatives are checked by fusion_check.
                    # Random mill/draw does not name a dedicated recipient.
                    if category == 'operations' and (item.get('random') or item['kind'] not in (
                            'send_grave','search_or_recover','search','recover','add_hand','return','return_deck',
                            'add_extra','banish','release','special_summon','fusion_summon','synchro_summon',
                            'xyz_summon','link_summon','ritual_summon','normal_summon','tribute_summon','place')):continue
                    if category == 'costs' and item.get('resource') == 'lp':continue
                    req = self.item_requirement(item, category)
                    if req is None:
                        unknown.append(dict(category=category, source=item.get('source',''),
                            **({'choice':item['choice']} if item.get('choice') else {}),
                            **({'operation':item} if category=='operations' else {})))
                    else:
                        req['source'] = item.get('source','')
                        if category == 'costs' and req.get('exclude_source_copy'):
                            item.update(exclude_source_copy=True, source_card_id=code)
                            req['source_card_id'] = code
                        if item.get('choice'):req['choice']=item['choice']
                        if category == 'operations':req['operation'] = item
                        requirements.append(req)
            for item in record.get('activation_requirements', ()):
                requirements.append(dict(item, query=self.resolve_query(item['query']), category='conditions'))
            for choice,branch in record.get('branch_records',{}).items():
                for item in branch.get('activation_requirements',()):
                    requirements.append(dict(item,query=self.resolve_query(item['query']),category='conditions',choice=choice))
            head = record['conditions'].get('source','')
            complete_head = bool(record['costs'] or record['targets'])
            for category in ('costs','targets'):
                for item in record[category]:
                    lp = (category=='costs' and item.get('resource')=='lp' and item.get('kind')=='pay_lp'
                        and type(item.get('quantity')) is int and item['quantity']>0
                        and re.fullmatch(r'支付'+str(item['quantity'])+r'(?:基本分|LP)',item.get('source','')))
                    if not (lp or self.item_requirement(item, category)) or not item.get('source') or item['source'] not in head:
                        complete_head = False
                    else:
                        head = head.replace(item['source'], '', 1)
            if (complete_head and record['trigger'].get('event') == 'own_main_phase'
                    and head.strip('，,：:。 　') == '自己主要阶段'):
                record['conditions']['status'] = 'recognized'
                for container in (record, record.get('block_view',{})):
                    container['unknown'] = [v for v in container.get('unknown',())
                                            if v not in ('activation_condition','additional_activation_conditions')]
            # A newly recalled coarse function cannot erase unresolved support
            # requirements merely because the legacy operation parser missed it.
            # Only sources actually inspected above count as handled. Newly
            # projected operations must not acknowledge their own selectors.
            inspected_sources=[item.get('source','') for cat in ('costs','targets') for item in record[cat]]
            inspected_sources += [item.get('source','') for item in record['operations']
                                  if item['kind'] in ('send_grave','search_or_recover','special_summon','normal_summon','tribute_summon')
                                  or item.get('selector_query') and self.item_requirement(item,'operations')
                                  or item.get('observed_operation') or record.get('fusion_material_selection')
                                      and item['kind'] in ('return_fusion_materials','fusion_summon')]
            for block in record.get('block_view',{}).get('blocks',()):
                if block['kind'] in ('search','recover','add_hand','special_summon','fusion_summon','ritual_summon','attach','place',
                                     'reveal','material_identity','material_permission','material_count','cost_replacement',
                                     'normal_summon','tribute_summon','pendulum_summon','material_level','material_race',
                                     'effect_copy','effect_apply','cost_source_expand','selection_expand','add_extra','place_deck'):
                    if not any(block['source'] in s or s in block['source'] for s in inspected_sources if s):
                        unknown.append(dict(category='block_selector',source=block['source'],block_id=block['block_id']))
            for connector in record.get('block_view',{}).get('connectors',()):
                if connector['kind']=='怪兽选择' and not record['targets']:
                    unknown.append(dict(category='legacy_selector',source=connector['condition_source']))
            effects.append(dict(key=f"effect:{code}:{record['effect_index']}:{pos}", record=record,
                                requirements=requirements, unknown=unknown))
        materials = []
        for item in self.catalog.effect_blocks(code).get('summon_materials') or profile.materials:
            query = item.get('selector_query')
            if query is None and 'predicate' in item:
                query = {'predicate':item['predicate']}
            if query is None:
                query = {item['kind']:item['value'], 'selector':item['source']}
                if item['kind'] == 'name_contains':query['type']=1
            materials.append(dict(query=self.resolve_query(query), minimum=item.get('count',item.get('quantity')),
                source=item['source'], origin=item.get('origin','material'), owner=item.get('owner','self'),
                category='material', **({'summon_type':item['summon_type']} if 'summon_type' in item else {})))
        return effects, materials

    def fusion_check(self, deck, code, record):
        """Printed fusion alternatives with distinct stock and required inclusion.

        This checks the configured conversion, without choosing a duel board or
        searching an operation sequence. The existing integer matcher assigns
        the remaining material slots after this card occupies one legal slot.
        """
        selection=record.get('fusion_material_selection')
        if not selection:
            return None
        options, unresolved = [], []
        for target in sorted(set(deck.extra)):
            if not self.rows[target]['type'] & 0x40:
                continue
            allowed,_=self.candidate_status(target,dict(category='operations',operation=dict(
                kind='fusion_summon',from_zones=['extra'],controller='self')))
            if allowed is False:
                continue
            _,materials=self.specs(target)
            if not materials or any(not query_supported(r['query']) for r in materials):
                unresolved.append(target);continue
            variants=[materials]
            stock=deck
            if selection['requires_this_card']:
                variants=[]
                for i,req in enumerate(materials):
                    eligible,_=self.candidate_status(code,dict(req,origin='grave'),target=target)
                    if eligible is None:unresolved.append(target)
                    if eligible is not True or not matches(self.rows[code],req['query']):continue
                    other=deepcopy(materials)
                    other[i]['minimum']-=1
                    variants.append([r for r in other if r['minimum']])
                main,extra=list(deck.main),list(deck.extra)
                (main if code in main else extra).remove(code)
                stock=SimpleNamespace(main=tuple(main),extra=tuple(extra))
            for required in variants:
                checked=self._check(stock,required,joint=True,target=target)
                if checked['status']=='inventory_present' and allowed is True:
                    options.append(dict(target=target,material_quantity=sum(r['minimum'] for r in materials),
                        includes_card=code if selection['requires_this_card'] else None,requirements=deepcopy(materials)))
                    break
                if checked['status']=='unknown' or allowed is None:unresolved.append(target)
        return dict(status='inventory_present' if options else 'unknown' if unresolved else 'missing',
            shortfall=0 if options or unresolved else 1,options=options,uncovered_targets=sorted(set(unresolved)),
            source=selection['source'],actual_duel_state_required=False)

    def simultaneous_processing(self, deck, record, selected=None, *, card_id=None):
        """Check the distinct summon and target of one simultaneous processing."""
        if selected is not None and not selected.get('simultaneous_group'):
            return None
        if len(record['operations']) != 2 or record['costs']:
            return None
        summon, send = record['operations']
        group = summon.get('simultaneous_group')
        if (not group or group != send.get('simultaneous_group')
                or summon['kind'] != 'special_summon' or send['kind'] != 'send_grave'
                or send.get('target_ref') is None or send.get('depends_on') != [summon['block_id']]):
            return None
        requirements = [self.item_requirement(op, 'operations') for op in (summon, send)]
        if any(req is None or req['owner'] != 'self' for req in requirements):
            return dict(status='unknown', reason='simultaneous_processing_selector')
        for req, operation in zip(requirements, (summon, send)):
            req['operation'] = operation
        if record['trigger'].get('zone') == 'field':
            # The activating card can be the field target, but its physical
            # copy cannot also be summoned from the hand or Graveyard.
            requirements[0].update(source_card_id=record['card_id'], exclude_source_copy=True)
        if card_id is not None:
            req = requirements[0 if selected is summon or selected == summon else 1]
            predicate = {'field': 'card_ids', 'value': [card_id]}
            query = req['query']
            if 'predicate' in query:
                predicate = {'all': [query['predicate'], predicate]}
            req['query'] = dict(query, predicate=predicate)
        proof = self._check(deck, requirements, distinct=True)
        return dict(status=proof['status'], reason='simultaneous_processing_entities', checks=[proof])

    def _handler_grave_processing(self, resident, extra, record, selected=None):
        if not any(target.get('availability_timing') == 'before_activation_payment' for target in record['targets']):
            return None
        handler, summon = record['operations']
        if selected is not None and selected.get('block_id') == summon['block_id']:
            summon = selected
        target = _activation_target(record, summon, availability_timing='before_activation_payment')
        cost, = record['costs']
        payment = self.item_requirement(cost, 'costs')
        source = dict(self.item_requirement(handler, 'operations'), operation=handler)
        chosen = self.item_requirement(summon, 'operations')
        grave = self.item_requirement(target, 'targets')
        # The handler is still on the field during both activation callbacks.
        existing = self._check_counts(resident, extra, [source, payment, dict(chosen, operation=summon)],
                                      distinct=True)
        original = {key: value for key, value in grave['query'].items() if key != 'selector'}
        proposed = {key: value for key, value in chosen['query'].items() if key != 'selector'}
        if existing['status'] == 'inventory_present' or proposed == original:
            return existing

        # With a narrowed choice, the paid card may be the actual target.
        # Another copy must already satisfy the pre-payment Graveyard check.
        paid = dict(payment, category='operations', operation=summon,
                    query=dict(payment['query'], any=[chosen['query']]))
        prechecked = dict(grave, category='operations', operation=summon)
        after_payment = self._check_counts(resident, extra, [source, paid, prechecked], distinct=True)
        if after_payment['status'] == 'inventory_present' or (
                existing['status'] == 'missing' and
                (after_payment['status'] == 'unknown' or after_payment['shortfall'] < existing['shortfall'])):
            return after_payment
        return existing

    def summon_choice_check(self, deck, record, operation, allowed, *, physical_inventory):
        '''Check one printed summon with the legal object range already applied.'''
        requirement = self.item_requirement(operation, 'operations')
        if requirement is None or requirement['owner'] != 'self':
            return None
        query = requirement['query']
        predicate = {'field': 'card_ids', 'value': list(allowed)}
        if 'predicate' in query:
            predicate = {'all': [query['predicate'], predicate]}
        query = dict(query, predicate=predicate)
        checked = self._check(deck, [dict(requirement, query=query, operation=operation)])
        if checked['status'] != 'inventory_present':
            return False if checked['status'] == 'missing' else None
        narrowed = dict(operation, selector_query=query)
        scoped = dict(record, operations=[narrowed if op == operation else op for op in record['operations']])
        processing = self.processing_check(deck, scoped, narrowed, physical_inventory=physical_inventory)
        return True if processing is None or processing['status'] == 'inventory_present' else (
            False if processing['status'] == 'missing' else None)

    def _type_matched_deck_inventory(self, resident, extra, record, selected=None):
        """Allocate the target, Deck send, hand handler and optional revival together."""
        binding = record['type_matched_deck_send']
        operations = {op['block_id']: op for op in record['operations']}
        move = operations[binding['send']]
        handler = operations[binding['handler']]
        target = self.item_requirement(record['targets'][0], 'targets')
        sender = dict(self.item_requirement(move, 'operations'), operation=move)
        activating = dict(self.item_requirement(handler, 'operations'), operation=handler)
        revival = (dict(self.item_requirement(selected, 'operations'), operation=selected)
                   if selected and selected['block_id'] == binding.get('revival') else None)
        source = getattr(self.catalog.assets, 'effect_lua_source', None)
        main = {code for code in resident if resident[code] > extra[code]}
        rows = {code: self.rows[code] for code in resident}
        mask = binding['base_type_mask']
        best = None
        send_cards = set()
        rank = {'inventory_present': 0, 'unknown': 1, 'missing': 2}

        for kind in (1, 2, 4):
            if not mask & kind:
                continue
            target_query = dict(target['query'], type=kind)
            if kind == 2:
                # Pendulum cards retain their printed monster type in Deck and
                # can supply a face-up Spell target in a Pendulum Zone.
                del target_query['type']
                target_query['any'] = [{'type': kind}, {'type_all': 0x1000001}]
            field = dict(target, query=target_query)
            send_query = dict(sender['query'], type=mask ^ kind)
            candidates = sorted(code for code in main if matches(rows[code], send_query))
            for code in candidates or [None]:
                query = dict(send_query, predicate={'field': 'card_ids', 'value': [code]}) if code else send_query
                requirements = [field, dict(sender, query=query), activating]
                if revival:
                    name = rows[code].get('alias') or code if code else None
                    exclusion = source.inventory_query({'exclude_rule_codes': [name]}, rows) if name and source else None
                    revived_query = dict(revival['query'], any=[exclusion]) if exclusion else {'unresolved_name': True}
                    requirements.append(dict(revival, query=revived_query))
                value = self._check_counts(resident, extra, requirements, distinct=True)
                if code and value['status'] != 'missing':
                    send_cards.add(code)
                if best is None or (rank[value['status']], value['shortfall']) < (
                        rank[best['status']], best['shortfall']):
                    best = value
        return dict(best, reason='complete_processing_different_base_types',
                    possible_send_card_ids=sorted(send_cards))

    def processing_check(self, deck, record, selected=None, *, physical_inventory=None):
        """Allocate the printed complete processing, not a duel starting hand.

        Each branch owns its stock. A sourced movement can release that same
        entity in its destination; otherwise overlapping selectors reserve
        different physical copies through the existing relation allocator.
        """
        physical_inventory = physical_inventory or (deck if isinstance(deck,DeckParts) else
            DeckParts(tuple(deck.main),tuple(deck.extra)))
        if not isinstance(physical_inventory,DeckParts):
            raise ContractError('processing requires the original physical candidate')
        deck=SimpleNamespace(main=tuple(deck.main),extra=tuple(deck.extra))
        key = digest([dict(main=deck.main,extra=deck.extra),physical_inventory.to_dict(),
                      record,(selected or {}).get('block_id')])
        if key in self._processing:
            return self._processing[key]
        if record.get('type_matched_deck_send'):
            proof = self._type_matched_deck_inventory(Counter(deck.main + deck.extra), Counter(deck.extra), record, selected)
            self._processing[key] = proof
            return proof
        targets = record.get('targets', ())
        if 'targets' not in record and any(op.get('target_ref') is not None for op in record['operations']):
            raise KeyError('targets')
        if any(target.get('availability_timing') == 'before_activation_payment' for target in targets):
            proof = self._handler_grave_processing(Counter(deck.main + deck.extra), Counter(deck.extra), record, selected)
            self._processing[key] = dict(status=proof['status'], reason='complete_processing_preselected_grave_target',
                                         checks=[proof])
            return self._processing[key]
        simultaneous = self.simultaneous_processing(deck, record, selected)
        if simultaneous is not None:
            self._processing[key] = simultaneous
            return simultaneous
        # Bind a printed name comparison to the payment's chosen entity. Each
        # finite name branch still uses the same integer processing allocator.
        comparisons = {(field, op[field]) for op in record['operations']
            if not op.get('optional') or op == selected
            for field in ('different_name_from_cost', 'different_name_from_reveal') if field in op}
        if comparisons:
            if len(comparisons) != 1:
                raise ContractError('processing name binding requires one reference')
            field, reference = next(iter(comparisons))
            is_payment = field == 'different_name_from_cost'
            category, key_field = ('costs', 'cost_index') if is_payment else ('operations', 'block_id')
            name_key = 'payment_name' if is_payment else 'revealed_name'
            source = next((item for item in record[category] if item.get(key_field) == reference), None)
            req = self.item_requirement(source, category) if source else None
            if req is None:
                result = dict(status='unknown', reason='payment_name_reference' if is_payment else 'revealed_name_reference')
            else:
                check = self._check(deck,[req])
                codes = sorted(set(deck.main + deck.extra))
                rule_names = {code: self.rows.get(self.rows[code].get('alias'), self.rows[code])['name'] for code in codes}
                names = sorted({rule_names[code] for code in check['requirements'][0]['matching_card_ids']})
                def restrict(query, predicate):
                    if 'predicate' in query:
                        predicate = {'all': [query['predicate'], predicate]}
                    return dict(query, predicate=predicate)
                options = []
                for name in names:
                    scoped = deepcopy(record)
                    same_ids = [code for code, rule_name in rule_names.items() if rule_name == name]
                    same_name = {'field': 'card_ids', 'value': same_ids}
                    if is_payment:
                        for cost in scoped['costs']:
                            if cost['cost_index'] == reference:
                                cost['selector_query'] = restrict(req['query'], same_name)
                    for op in scoped['operations']:
                        if op.get(field) == reference:
                            del op[field]
                            op['selector_query'] = restrict(op['selector_query'], {'not': same_name})
                        if not is_payment and op.get('subject_ref') == reference and op.get('selection_method') == 'revealed_card':
                            op['selector_query'] = restrict(op['selector_query'], same_name)
                    chosen = next((op for op in scoped['operations'] if selected and op['block_id']==selected['block_id']),None)
                    value = self.processing_check(deck,scoped,chosen,physical_inventory=physical_inventory)
                    options.append({name_key: name, 'result': value, **({} if is_payment else {'revealed_card_ids': same_ids})})
                status = ('inventory_present' if any(o['result'] and o['result']['status']=='inventory_present' for o in options)
                    else 'unknown' if any(o['result'] is None or o['result']['status']=='unknown' for o in options)
                    else 'missing')
                result = dict(status=status,reason='complete_processing_different_names',options=options)
            self._processing[key]=result
            return result
        from .construction_relations import (InputGroup, Need, PoolRecovery, RelationContext,
            RelationFact, Resource, ResourcePool, UseRequirement, evaluate_relations,
            relation_index, _operation_transfer, _zone_support)
        from .construction_layers import SkeletonSpec
        parts = []
        for category in ('costs', 'operations'):
            for item in record[category]:
                if item.get('phase') == 'delayed' or item.get('optional') and item != selected:
                    continue
                req = self.item_requirement(item, category)
                if req and req['owner'] == 'self' and item.get('to_zone') and not item.get('random'):
                    if category == 'operations':
                        req['operation'] = item
                    parts.append((req, item))
        self_paid = _has_self_grave_payment(record)
        if self_paid:
            bound_targets = [target for req, item in parts if req['category'] == 'operations'
                             and (target := _activation_target(record, item)) is not None]
            # Stats, negation and other non-moving effects can still have a
            # formal target. Allocate it once, separately from the paid copy.
            for target in targets:
                if target in bound_targets or target.get('selection_timing') != 'after_activation_payment':
                    continue
                requirement = self.item_requirement(target, 'targets')
                if requirement and requirement['owner'] == 'self':
                    parts.append((requirement, target))
        if parts and not self_paid and _field_source_needs_reservation(record, (req for req, _ in parts)):
            # The activating entity is already on the field. Reserving it in
            # the same allocator prevents paying/receiving that very copy in
            # hand or grave. Explicit field movements keep their existing
            # transfer/recovery checks instead of this stationary reservation.
            req = _processing_activation_source(record)
            item = dict(kind='activation_source', source=req['source'], from_zones=['field'], to_zone=None,
                        quantity=1, owner='self', random=False, selector_query=req['query'], reason='effect')
            parts.insert(0, (req, item))
        if len(parts) < 2:
            self._processing[key] = None
            return None
        checks = [self._check(deck, [req]) for req, _ in parts]
        if any(c['status'] == 'missing' for c in checks):
            result = dict(status='missing', reason='complete_processing_inventory', checks=checks)
        elif any(c['status'] == 'unknown' for c in checks):
            result = dict(status='unknown', reason='complete_processing_selector_or_restriction', checks=checks)
        else:
            facts, pools, needs, transfers = [], [], [], []
            members = tuple(sorted({(z, c) for z in ('main', 'extra') for c in getattr(deck, z)}))
            for i, ((req, item), check) in enumerate(zip(parts, checks)):
                name = 'processing:'+str(i)
                stock = tuple(pair for pair in members if pair[1] in check['requirements'][0]['matching_card_ids'])
                origins = tuple(req.get('origins', (req['origin'],)))
                choices = []
                for j, origin in enumerate(origins):
                    port = Resource(name, zone=origin)
                    nid = name+':origin:'+str(j)
                    # Reserving the object precedes this printed movement.
                    choices.append(Need(nid, port, req['minimum'], destination=origin))
                    facts.append(RelationFact(nid+':stock', nid+':stock', port, req['source'],
                        quantity=max(1, len(deck.main)+len(deck.extra)), output_pool=name))
                needs.append(choices[0] if len(choices)==1 else InputGroup('any', tuple(choices)))
                pools.append(ResourcePool(name, req['source'], inventory=stock) if stock else
                             ResourcePool(name, req['source'], capacity=0))
                move = dict(item, owner='self', controller='self', from_zones=list(origins),
                    selector_query=req['query'], random=False)
                transfer = (None if req['category'] in ('source', 'targets') else
                            _operation_transfer(move, req['source'], members, self, 'self', record))
                fid = name+':move'
                facts.append(RelationFact(fid, fid, Resource('processing_movement', attributes=(name,)),
                    req['source'], quantity=req['minimum'], transfer=transfer))
                transfers.append((fid, transfer, choices))
            from dataclasses import replace
            for i, (fid, transfer, before) in enumerate(transfers):
                if transfer is None:
                    continue
                recoveries = tuple(PoolRecovery(fid, a.need_id, b.need_id, 'before')
                    for j, (_, _, after) in enumerate(transfers[i+1:], i+1)
                    # A target picked at activation must exist before any resolution movement.
                    if parts[j][0]['category'] != 'targets' and _activation_target(record, parts[j][1]) is None
                    for a in before for b in after
                    if transfer.inventory is None or set(transfer.inventory) & set(pools[j].inventory)
                    if _zone_support(transfer.destination, b.resource.zone) is True)
                if recoveries:
                    pools[i] = replace(pools[i], recoveries=recoveries)
            context = RelationContext((UseRequirement('complete_processing', InputGroup('all', tuple(needs)),
                record['source_text']),), tuple(facts), tuple(pools))
            index = relation_index(None, context)
            counts = Counter((z, c) for z in ('main', 'extra') for c in getattr(deck, z))
            relation = evaluate_relations(SkeletonSpec(physical_inventory, ()), context, index,
                inventory_counts=counts, existential=True).to_dict()['joint_required']
            result = dict(status={'supported':'inventory_present','missing':'missing','unknown':'unknown'}[relation['status']],
                reason='complete_processing_entities', checks=checks, relation=relation)
        if self_paid and selected and result['status'] != 'inventory_present':
            target = _activation_target(record, selected)
            if target and target.get('payment_may_supply_target'):
                result = self._after_grave_payment_target(deck, parts, target, selected, result)
        self._processing[key] = result
        return result

    def _after_grave_payment_target(self, deck, parts, target, selected, existing):
        """A newly paid card may be selected if another legal object existed."""
        before = self.item_requirement(target, 'targets')
        chosen = self.item_requirement(selected, 'operations')
        if (not before or not chosen or before['owner'] != 'self' or chosen['owner'] != 'self'
                or before['origin'] != 'grave' or chosen['origin'] != 'grave'
                or before['minimum'] != 1 or chosen['minimum'] != 1):
            return existing
        for paid, movement in parts:
            if (paid['category'] != 'costs' or movement.get('to_zone') != 'grave'
                    or not movement.get('requires_arrival') or paid['minimum'] != 1):
                continue
            if 'any' in paid['query']:
                continue
            same_card = dict(paid, category='operations', operation=selected,
                             query=dict(paid['query'], any=[chosen['query']]))
            precheck = dict(before, category='operations', operation=selected)
            others = [req for req, item in parts if req is not paid and item != selected]
            proof = self._check(deck, [same_card, precheck, *others], distinct=True)
            if proof['status'] == 'inventory_present' or (proof['status'] == 'unknown' and existing['status'] == 'missing'):
                return dict(status=proof['status'], reason='complete_processing_entities', checks=[proof])
        return existing

    def _check(self, deck, specs, *, joint=False, target=None, distinct=False):
        return self._check_counts(Counter(deck.main + deck.extra), Counter(deck.extra), specs,
                                  joint=joint, target=target, distinct=distinct)

    def summon_material_check(self, deck, code, *, costs=()):
        return self._summon_material_check_counts(Counter(deck.main + deck.extra), Counter(deck.extra), code, costs=costs)

    def _summon_material_check_counts(self, resident, extra, code, *, costs=()):
        """Test each printed material method independently and stop at a legal assignment."""
        effects, materials = self.specs(code)
        def check(rows):
            return self._check_counts(resident, extra, [*costs, *rows], joint=not costs,
                                      target=code, distinct=bool(costs))

        best = check(materials) if materials else None
        if best and best['status'] == 'inventory_present':
            return best
        for effect in effects:
            procedure = effect['record'].get('summon_procedure', {})
            if procedure.get('kind') != 'xyz_overlay':
                continue
            material = procedure['material']
            query = self.resolve_query(material['query'])
            checked = check([dict(material, query=query)])
            checked['summon_procedure'] = procedure
            if checked['status'] == 'inventory_present':
                family = self.rows[code].get('alias') or code
                bases = checked['requirements'][-1]['matching_card_ids']
                if all((self.rows[base].get('alias') or base) == family for base in bases):
                    checked.update(status='unknown', unknown_restrictions=[dict(category='material',
                        source=procedure['source'], reason='overlay_base_requires_independent_access')])
            if checked['status'] == 'inventory_present':
                return checked
            if (best is None or checked['status'] == 'unknown' and best['status'] == 'missing'
                    or checked['status'] == best['status'] and checked['shortfall'] < best['shortfall']):
                best = checked
        return best

    def _check_counts(self, resident, extra, specs, *, joint=False, target=None, distinct=False, bound_targets=(),
                      shared_categories=()):
        # Printed materials are distinct physical monsters; one card cannot
        # satisfy both an exact-name slot and an overlapping race slot.
        copies = [(code, i) for code, n in resident.items() for i in range(n)]
        if joint:
            copies = [(c,i) for c,i in copies if self.rows[c]['type'] & 1
                      and not (c == target and i == 0)]
        unresolved=[r for r in specs if not query_supported(r['query'])]
        specs=[r for r in specs if query_supported(r['query'])]
        result = []
        slots, confirmed_slots = [], []
        for req in specs:
            candidates = [(c,i) for c,i in copies if matches(self.rows[c], req['query'])
                         and not (req.get('exclude_source_copy') and (c,i)==(req.get('source_card_id'),0))
                         and (req['origin'] not in ('hand','deck') or not self.rows[c]['type'] & EXTRA_TYPES)
                         and (req['origin'] != 'extra' or extra[c] > 0)
                         and (req['category'] != 'material' or (self.rows[c]['type'] & 1
                              and not (c == target and i == 0)))]
            external = req.get('owner', 'self') != 'self'
            if external:
                candidates = []
            statuses = {c:(None,['unknown_printed_stat']) if any(
                (stat+'_min' in req['query'] or stat+'_max' in req['query']) and self.rows[c].get(stat,-1)<0
                for stat in ('atk','def')) else self.candidate_status(c, req, target=target) for c,_ in candidates}
            available = [(c,i) for c,i in candidates if statuses[c][0] is not False]
            confirmed = [(c,i) for c,i in candidates if statuses[c][0] is True]
            if 'face_up' in req['query'] and not (req['origin']=='extra' and req['query']['face_up'] is False):
                confirmed = []  # The public catalog does not contain current positions.
            if external:
                # An unknown external supply is not an own-deck shortage or a
                # physical card witness. Distinct placeholders only bound it.
                available = [('external:'+str(len(result)),i) for i in range(req['minimum'])]
            result.append(dict(req, available=len(available), matching_card_ids=sorted({c for c,_ in available}),
                confirmed_available=len(confirmed), restriction_checks=[r for c in sorted(statuses) for r in statuses[c][1]],
                shortfall=max(0,req['minimum']-len(available)), external_supply_unknown=external))
            if external:
                result[-1]['matching_card_ids'] = []
            if ((joint or distinct) and req['category'] not in shared_categories
                    and not (req['category'] == 'targets' and req['source'] in bound_targets)):
                slots.extend([available]*req['minimum'])
                confirmed_slots.extend([confirmed]*req['minimum'])
        def shortage_for(groups):
            owners = {}
            def assign(slot, seen):
                for copy in groups[slot]:
                    if copy in seen:continue
                    seen.add(copy)
                    if copy not in owners or assign(owners[copy], seen):
                        owners[copy]=slot;return True
                return False
            return len(groups)-sum(assign(i,set()) for i in range(len(groups)))
        if joint or distinct:
            shortage, confirmed_shortage = shortage_for(slots), shortage_for(confirmed_slots)
        else:
            shortage = sum(r['shortfall'] for r in result)
            confirmed_shortage = sum(max(0,r['minimum']-r['confirmed_available']) for r in result)
        return dict(status='missing' if shortage else 'unknown' if unresolved or confirmed_shortage else 'inventory_present', requirements=result,
                    shortfall=shortage, unknown_selectors=unresolved,
                    unknown_restrictions=[dict(check, category='restriction', source=check['restriction']['source'])
                        for row in result for check in row['restriction_checks'] if check['allowed'] is None]
                        if confirmed_shortage and not shortage else [],
                    confirmed_shortfall=confirmed_shortage,
                    execution_status='unknown', access_to_required_zone_verified=False)

    def evaluate(self, deck, graph=None, *, codes=None):
        return self.evaluate_counts(Counter(deck.main), Counter(deck.extra), graph, codes=codes)

    def evaluate_counts(self, main, extra, graph=None, *, codes=None):
        resident = main + extra
        selected = sorted(resident if codes is None else set(codes))
        evaluations, deficits, scoped, unknowns = {}, {}, {}, {}
        uncovered = set(resident) - set(selected)
        remaining = self.requirement_limit
        for code in selected:
            if remaining <= 0:
                uncovered.add(code);continue
            effects, materials = self.specs(code)
            work = max(1, len(materials)+sum(len(e['requirements'])+len(e['unknown']) for e in effects))
            if work > remaining:
                uncovered.add(code);continue
            remaining -= work
            rows = []
            for effect in effects:
                # All selected cards expose their dependencies. Graph-specific
                # projections separately decide which particular function earns K/E.
                groups = {'candidate_component':([], ['candidate_component'] if graph is None else [])}
                if graph is not None:
                    for node in graph.nodes:
                        if not effect_matches(effect['record'], node.tags):continue
                        key = digest([(t.dimension,t.value) for t in node.tags])[:12]
                        groups.setdefault(key, (node.tags, []))[1].append(node.node_id)
                for scope, (tags, nodes) in groups.items():
                    requirements = [req for req in effect['requirements'] if not tags or 'operation' not in req or
                        effect_matches(dict(effect['record'], operations=[req['operation']]),tags)]
                    dependencies = {ref for req in requirements for ref in req.get('operation', {}).get('depends_on', ())}
                    record = effect['record']
                    proof = (self._type_matched_deck_inventory(resident, extra, record)
                             if record.get('type_matched_deck_send') else
                             self._handler_grave_processing(resident, extra, record))
                    if proof is not None:
                        value = proof
                    else:
                        hand_sends = [req for req in effect['requirements'] if (op := req.get('operation'))
                            and op['block_id'] in dependencies and op.get('processing_role') == 'auxiliary'
                            and op['kind'] == 'send_grave' and op.get('from_zones') == ['hand']]
                        requirements.extend(req for req in hand_sends if req not in requirements)
                        bound_targets = {target['source'] for req in requirements
                            if (target := _activation_target(effect['record'], req.get('operation', {}))) is not None}
                        record = effect['record']
                        self_paid = _has_self_grave_payment(record)
                        if hand_sends and not self_paid and (bound_targets or _field_source_needs_reservation(record, requirements)):
                            # The activating entity and the two moved cards occupy different zones.
                            requirements.insert(0, _processing_activation_source(record))
                        value = self._check_counts(resident, extra, requirements,
                            distinct=bool(hand_sends) or self_paid, bound_targets=bound_targets,
                            shared_categories=('conditions', 'outcome') if self_paid else ())
                    key = effect['key'] + ':' + scope
                    unresolved=[r for r in effect['unknown'] if not tags or 'operation' not in r or
                        effect_matches(dict(effect['record'],operations=[r['operation']]),tags)]
                    unresolved = [*value['unknown_selectors'], *unresolved]
                    value.update(key=key, nodes=nodes, unknown_selectors=unresolved)
                    if unresolved or value['unknown_restrictions']:
                        if scope=='candidate_component':unknowns[key] = [*unresolved, *value['unknown_restrictions']]
                        if not value['shortfall']:value['status'] = 'unknown'
                    rows.append(value)
                    if value['shortfall']:
                        target_deficits=deficits if scope=='candidate_component' else scoped
                        target_deficits[key+':shortfall'] = value['shortfall']
                        target_deficits[key+':blocked_copies'] = resident[code]
            material = self._summon_material_check_counts(resident, extra, code)
            if material and (material['unknown_selectors'] or material['unknown_restrictions']):
                unknowns[f'materials:{code}']=[*material['unknown_selectors'], *material['unknown_restrictions']]
            formula=next((s.strip() for s in self.rows[code].get('desc','').splitlines() if '＋' in s or '+' in s),'')
            if extra[code] and self.rows[code]['type'] & 0x40 and formula and not materials:
                unknowns[f'materials:{code}']=[dict(category='material',source=formula)]
                material=dict(status='unknown',requirements=[],shortfall=0,
                    execution_status='unknown',access_to_required_zone_verified=False)
            if material and material['shortfall']:
                deficits[f'materials:{code}:shortfall']=material['shortfall']
                deficits[f'materials:{code}:blocked_copies']=extra[code]
            evaluations[str(code)] = dict(effects=rows, materials=material)
        return dict(kind='static_necessary_inventory_dependencies', cards=evaluations,
                    known_deficits=deficits, scoped_deficits=scoped,
                    unknown_requirements=unknowns, uncovered_cards=sorted(uncovered),
                    archetype_membership='catalog_setcode' if self.strict_names else 'synthetic_literal_names',
                    archetype_registry_names=len(self.set_names),
                    archetype_registry_source=self.registry_source,
                    requirement_work=self.requirement_limit-remaining,
                    side_supplies_resources=False, cb_performed=False)

    def function_status(self, evaluation, code, node_id):
        if code in evaluation['uncovered_cards']:return 'unknown'
        card = evaluation['cards'].get(str(code), {})
        material = card.get('materials')
        if material and material['status'] == 'missing':return 'missing'
        if material and material['status'] == 'unknown':return 'unknown'
        effects = [r for r in card.get('effects',[]) if node_id in r['nodes']]
        if effects and all(r['status']=='missing' for r in effects):return 'missing'
        if effects and not any(r['status']=='inventory_present' for r in effects):return 'unknown'
        return None

    def function_missing(self, evaluation, code, node_id):
        return self.function_status(evaluation, code, node_id) == 'missing'


def improves(before, after):
    keys = before.keys() | after.keys()
    return any(after.get(k,0)<before.get(k,0) for k in keys) and all(after.get(k,0)<=before.get(k,0) for k in keys)


def dependency_improves(before, after):
    """Unknown replacement obligations cannot masquerade as a cleared gap."""
    if before.get('uncovered_cards') or after.get('uncovered_cards'):return False
    old,new=before['known_deficits'],after['known_deficits']
    if not improves(old,new):return False
    if set(after.get('unknown_requirements',{})) <= set(before.get('unknown_requirements',{})):return True
    # Adding a support can introduce unrelated unknown effects. It proves a
    # necessary supply improvement only when every affected consumer survives
    # and its actual shortage decreases, not merely its number of dead copies.
    changed={k.rsplit(':',1)[0] for k,v in old.items() if new.get(k,0)<v}
    return all(key.split(':')[1] in after['cards'] and
        new.get(key+':shortfall',0)<old.get(key+':shortfall',0) for key in changed)


def recall_dependencies(catalog, pool, available, *, limit=16, rounds=3, checks=65536):
    """Recall missing prerequisites into one query inside the unchanged task.

    This is an upper-bound inventory, not a proposed deck or access proof. Only
    known predicates can recall a card from the host's already legal vocabulary.
    """
    current = set(pool);events=[];work=0
    dependencies = InventoryDependencies(catalog)
    by_set,by_name={},{}
    for code in available:
        work+=1
        if work>checks:return tuple(sorted(current)),dict(events=events,checks=checks,truncated=True)
        row=catalog.assets.rows[code]
        by_name.setdefault(row.get('name',''),[]).append(code)
        codes=row.get('setcode',0)
        for shift in (0,16,32,48):
            value=(codes>>shift)&0xffff
            if value:by_set.setdefault(value&0xfff,set()).add(code)
    for step in range(rounds):
        main=[];extra=[]
        for code in sorted(current):
            zone = extra if catalog.assets.rows[code]['type'] & EXTRA_TYPES else main
            zone.extend([code]*catalog.assets.limits.get(catalog.assets.rows[code].get('alias') or code,3))
        # A pool can exceed deck section limits. It is a supply bound, never
        # a DeckParts proposal; actual candidates still pass assets.validate.
        analysis=dependencies.evaluate(SimpleNamespace(main=tuple(main),extra=tuple(extra),side=()))
        requests=[(code,r) for code,row in analysis['cards'].items()
            for v in (*row['effects'], *((row['materials'],) if row['materials'] else ()))
            for r in v['requirements'] if r['shortfall']]
        added=[]
        for consumer,request in requests:
            query=request['query']
            recalled=(sorted(by_set.get(query['setcode']&0xfff,())) if 'setcode' in query else
                      by_name.get(query['exact_name'],()) if 'exact_name' in query else available)
            for code in recalled:
                if code in current:continue
                work+=1
                if work>checks or len(events)>=limit:
                    return tuple(sorted(current)),dict(events=events,checks=min(work,checks),truncated=True)
                if request['origin'] in ('hand','deck') and catalog.assets.rows[code]['type'] & EXTRA_TYPES:continue
                if matches(catalog.assets.rows[code],request['query']):
                    current.add(code);added.append(code)
                    events.append(dict(round=step+1,consumer=int(consumer),card_id=code,
                                       source=request['source'],query=request['query']))
                    break
        if not added:break
    return tuple(sorted(current)),dict(events=events,checks=work,truncated=False)


def repair_ideas(task, assets, base, *, graph=None, limit=6, checks=128, edits=None):
    """Yield cumulative edits to repair known shortages, deepest repair first."""
    from .build_pipeline import DeckEdits

    if limit <= 0 or checks <= 0:
        return
    catalog = InventoryDependencies(MechanismCatalog(assets, task.pool))
    editor = edits if edits is not None else DeckEdits(task, assets, base)
    original = editor.counts
    current = original
    pool = sorted(task.pool)
    names = {code: assets.rows[code].get('alias') or code for code in pool}
    analysis = catalog.evaluate_counts(current['main'], current['extra'], graph)
    ideas = []
    for step in range(limit):
        old = analysis['known_deficits']
        if analysis['uncovered_cards'] or not old:
            break
        requests = []
        affected = set()
        for code, row in analysis['cards'].items():
            for value in (*row['effects'], *((row['materials'],) if row['materials'] else ())):
                if value['status'] != 'missing':continue
                affected.add(int(code))
                requests.extend(r for r in value['requirements'] if r['shortfall'])
        # First try the actual requested support; then alternative components.
        recalled = dict.fromkeys(c for req in requests for c in pool if matches(assets.rows[c], req['query']))
        incoming = [*recalled, *(c for c in pool if c not in recalled)]
        name_counts = Counter()
        for counts in current.values():
            for code, count in counts.items():
                name_counts[names[code]] += count
        cumulative = {z: counts.copy() for z, counts in current.items()}
        for z, delta in cumulative.items():
            delta.subtract(original[z])
        accepted = None
        attempts = 0
        for new in incoming:
            zone = 'extra' if assets.rows[new]['type'] & EXTRA_TYPES else 'main'
            # Unrelated Main substitutions cannot consume the budget needed
            # for an Extra-only gap. Supports may come from another zone;
            # alternative consumers replace an actually affected component.
            outgoing = sorted((c for c in current[zone] if c in affected or new in recalled),
                              key=lambda c:(c not in affected,c))
            for old_card in outgoing:
                if new == old_card:continue
                attempts += 1
                if attempts > checks:break
                changed = {zone: Counter({old_card: -1, new: 1})}
                name = names[new]
                if names[old_card] != name and name_counts[name] >= assets.limits.get(name, 3):
                    side_copy = next((c for c in sorted(current['side'], key=lambda c: (c != new, c))
                                      if names[c] == name), None)
                    if side_copy is not None:
                        changed['side'] = Counter({side_copy: -1, old_card: 1})
                changes = {}
                for z in ZONES:
                    delta = cumulative[z].copy()
                    delta.update(changed.get(z, {}))
                    changes[z] = dict(added=sorted((+delta).elements()), removed=sorted((-delta).elements()))
                if editor.rejection(changes) is not None:
                    continue
                next_counts = editor.inventory(changes)
                updated = catalog.evaluate_counts(next_counts['main'], next_counts['extra'], graph)
                if dependency_improves(analysis,updated):
                    accepted = next_counts, updated, changes
                    break
            if accepted is not None or attempts > checks:break
        if accepted is None:
            break
        current, analysis, changes = accepted
        ideas.append(dict(changes=changes, strategy='dependency:inventory',
            proposal_basis='source_scoped_necessary_inventory_repair',
            proposal_source='public_effect_records_and_printed_materials',
            dependency_repair=dict(step=step+1, checks=attempts, before=old, after=analysis['known_deficits'])))
    yield from reversed(ideas)
