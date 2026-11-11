"""Short functional projections of effect_records, shared by build and export.

This is the coarse view of the existing semantic records. Labels do not encode
selectors or a rule program. Source spans, choices, payments and connectors
remain scoped to the effect that owns them.
"""
from copy import deepcopy
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3
import tempfile

from .effect_block_rules import FUNCTIONS, structural_records

BLOCK_VERSION = "public-effect-blocks-v1"
BLOCK_REVISION = 'local-library-review-20261111-b19'
LABELS = {
    "send_grave": "送墓", "search": "检索", "recover": "回收", "add_hand": "加入手牌",
    "draw": "抽卡", "special_summon": "特召", "fusion_summon": "融合召唤",
    "ritual_summon": "仪式召唤", "synchro_summon": "同调召唤", "xyz_summon": "超量召唤",
    "link_summon": "连接召唤", "destroy": "破坏", "banish": "除外", "return_deck": "回卡组",
    "return_hand": "回手", "negate_effect": "效果无效", "negate_activation": "发动无效",
    "control": "控制权取得", "level": "等级变更", "position": "表示形式变更",
    "stats": "攻守变更", "attach": "补充超量素材", "place": "表侧放置", "set": "盖放",
    "piercing": "贯穿战斗伤害", "extra_attack": "追加攻击", "damage": "效果伤害",
    "recover_lp": "回复LP", "battle_protection": "战斗破坏保护", "effect_protection": "效果破坏保护",
    "unaffected": "效果不受", "response_lock": "响应限制", "equip": "装备",
    "counter": "放置指示物", "inspect": "检视", "shuffle": "洗切", "negate_attack": "攻击无效",
    "detach": "取除素材", "release": "解放", "pay_lp": "支付LP",
    "activate_card": "发动卡片", "remove_counter": "取除指示物",
    "return_extra_deck": "回额外卡组", "direct_attack": "直接攻击",
    "race_change": "种族变更", "lp_change": "LP变更", "reveal": "展示",
    "material_identity": "素材身份代用", "cost_replacement": "费用代替",
    "win": "特殊胜利", "battle_calculation": "战斗计算变更", "tribute_summon": "上级召唤",
    'grave_destination_replace':'墓地去向替代', 'negate_summon':'召唤无效',
}
LABELS.update({kind:label for kind,label,_ in FUNCTIONS})
ZONES = {"额外卡组": "extra", "融合卡组": "extra", "手卡": "hand", "墓地": "grave", "卡组": "deck",
         "场上": "field", "灵摆区域": "pendulum", "除外状态": "banished", "除外":"banished",
         '魔法与陷阱区域':'field','魔法陷阱卡区域':'field','魔法·陷阱区域':'field','怪兽区域':'field','场地区域':'field'}
_SOURCE_ZONE=r'额外卡组|融合卡组|手卡|墓地|卡组|魔法与陷阱区域|魔法陷阱卡区域|魔法·陷阱区域|怪兽区域|场地区域|灵摆区域|场上|除外状态|除外(?=的|中)'
ACTIVATION = re.compile(r"(?:才能|可以|则能|即可)(?:把这张卡|把这个效果)?发动(?:这个效果|这张卡|和处理)?(?:\d+次)?(?:（[^（）]*）|\([^()]*\))*[。；;，,]|"
                        r"(?<=场合)发动[。；;]|(?<=时)发动[。；;]|(?<=阶段)发动[。；;]|(?<=对象)发动[。；;]|"
                        r"从以下(?:效果)?选择1个发动(?:（[^（）]*）|\([^()]*\))*[。；;]|选择下面1个效果发动[。；;]|"
                        r'(?<=怪兽)发动[。；;]|(?<=那个效果)发动[。；;]|把以下效果发动[。；;]|'
                        r'(?<=解放)发动[。；;]|(?<=墓地)发动[。；;]|(?<=除外)发动[。；;]|(?<=取除)发动[。；;]|(?<=调整)发动[。；;]')


def activation_parts(text):
    # This wording grants permission to activate another card; 发动 is the
    # capability being granted, not this effect's activation delimiter.
    permission=re.search(r'可以把[^。]+在盖放的回合[^。]*发动|这张卡[^。]{0,70}从手卡发动|这张卡的发动从手卡也能用|这张卡也能[^。]{0,100}(?:来发动|在盖放的回合发动)',text)
    earlier=ACTIVATION.search(text)
    if permission and (not earlier or permission.start()<=earlier.start()):return '',text,0,'unmarked'
    # New translated card text uses a semicolon for costs/targets even when
    # the word 发动 is omitted. Keep its original offsets.
    semicolon = re.search(r'[；;]',text)
    if semicolon and '。' not in text[:semicolon.start()] and not ACTIVATION.search(text[:semicolon.end()]):
        return text[:semicolon.start()],text[semicolon.end():],semicolon.end(),'activated'
    boundary_text=re.sub(r'（[^（）]*）|\([^()]*\)',lambda m:' '*len(m[0]),text)
    colon=re.match(r'[^。]+?(?:场合|时)\s*[：:]\s*(?:可以)?',boundary_text)
    if colon:
        return text[:colon.end()].rstrip('可以：: '),text[colon.end():],colon.end(),'activated'
    first=re.search(r'(?:才能|可以|则能|即可)发动',text)
    if first and not ACTIVATION.match(text,first.start()) and not text[first.end():].startswith('的'):
        return '',text,0,'boundary_unknown'
    match = ACTIVATION.search(text)
    if not match:
        plain=re.match(r'[^。]*?(?:时|选择[^。]+)发动[。；;]',boundary_text)
        if plain:
            return text[:plain.end()-3],text[plain.end():],plain.end(),'activated'
    if match:
        from .effect_text import legacy_payment_boundary
        legacy = legacy_payment_boundary(text)
        if legacy and '。' in text[:match.start()] and legacy[2]<=text.index('。')+1:
            return legacy
        return text[text.rfind('。',0,match.start())+1:match.start()], text[match.end():], match.end(), "activated"
    from .effect_text import legacy_payment_boundary
    legacy = legacy_payment_boundary(text)
    if legacy:
        return legacy
    # Older text can state the trigger and instruction without an activation word.
    match = re.match(r"[^。，,；;]*?(?:场合|时)\s*[，,]", boundary_text)
    if match:
        return text[:match.end()], text[match.end():], match.end(), "conditional"
    return "", text, 0, "unmarked"


def _unquote(text):
    return re.sub(r"「[^」]*」|『[^』]*』", lambda m: " " * len(m[0]), text)


def source_zones(text):
    text=re.sub(r'（[^（）]*）|\([^()]*\)','',text)
    match = re.search(r"从(?:自己|对方|双方)?(?:的)?("+_SOURCE_ZONE+r')', text)
    if not match:
        match = re.search(r"(?:把|将)(?:自己|对方)?(?:的)?("+_SOURCE_ZONE+r')', text)
    if not match:
        match=re.match(r'(?:自己|对方|双方)(?:的)?('+_SOURCE_ZONE+r')',text)
    if not match:
        match=re.match(r'(墓地|手卡|场上)存在的这张卡',text)
    if not match:
        return []
    result = [ZONES[match[1]]]
    tail = text[match.end():]
    if result==['deck']:tail=re.sub(r'^(?:最)?上面|^上方','',tail)
    extra = re.match(r"(?:(?:[·、／/]|或者|或|以及|和)(?:自己|对方|双方)?(?:的)?(?:"+_SOURCE_ZONE+r'))+', tail)
    if extra:
        result += [ZONES[w] for w in re.findall(_SOURCE_ZONE,extra[0])]
    if re.search(r'以及除外|以及被除外|或除外|以及除外状态',text):result.append('banished')
    return list(dict.fromkeys(result))


def _qualifiers(clause, kind, targets):
    masked = _unquote(clause)
    # A bullet's threshold/payment is not its instruction's quantity.
    masked = re.sub(r'^\s*\d+(?:个|只|张)?(?:以上|以下)?[：:]\s*', '', masked)
    origins = source_zones(masked)
    refers_target = '那' in masked or '作为对象' in masked
    if not origins and kind in ("special_summon", "recover", "add_hand", "return_hand", "attach") and refers_target:
        origins = list(dict.fromkeys(z for t in targets for z in t.get("zones", ())))
    n = re.search(r"(\d+)(?:张|只|个)(?!回合)", masked)
    owner_match=re.search(r'(双方|对方|自己)(?:的)?(?:卡组|墓地|手卡|场上|怪兽|基本分|LP)|(?:给与|给予)(对方|自己)',masked)
    owner_word=next((s for s in owner_match.groups() if s),None) if owner_match else None
    if refers_target and not owner_word:
        target_words={w for t in targets for w in re.findall(r'(自己|对方)(?:的)?(?:场上|墓地|手卡)',t.get('selector',''))}
        if len(target_words)==1:owner_word=target_words.pop()
    q = {"from_zones": origins, "quantity": int(n[1]) if n else None,
         "owner": {'双方':'both','对方':'opponent','自己':'self'}.get(owner_word,'unknown')}
    if refers_target and len(targets)==1:
        if q['quantity'] is None:q['quantity']=targets[0].get('quantity')
        if q['owner']=='unknown':q['owner']=targets[0].get('owner','unknown')
    destinations = {"send_grave":"grave", "search":"hand", "recover":"hand", "add_hand":"hand",
                    "draw":"hand", "special_summon":"field", "attach":"xyz_material", "banish":"banished",
                    "return_deck":"deck", "return_extra_deck":"extra", "return_hand":"hand", "place":"field", "set":"field"}
    if kind in destinations:q["to_zone"] = destinations[kind]
    if kind.endswith("_summon"):q["to_zone"] = "field"
    if kind in ("fusion_summon", "synchro_summon", "xyz_summon", "link_summon"):q["from_zones"] = ["extra"]
    if kind == "draw":q["from_zones"] = ["deck"]
    if kind == "send_grave":
        q["random"] = bool(re.search(r"卡组(?:上面|顶端)", masked))
        if q["random"]:q["from_zones"] = ["deck"]
        if q['owner']=='both':q['quantity_scope']='each_player'
    for word, value in (("直到伤害步骤结束", "damage_step_end"), ("直到结束阶段", "end_phase"), ("直到回合结束", "turn_end"), ("这个回合", "turn")):
        if word in masked:q["duration"] = value;break
    if "第2次的自己准备阶段" in masked:q["duration"] = "second_own_standby_phase"
    if "全部" in masked:q["quantity_mode"] = "all"
    from .effect_text import mask_action_references
    if "可以" in mask_action_references(masked):q["optional"] = True
    if "无视召唤条件" in masked:q["ignore_summon_conditions"] = True
    if '里侧' in masked:q['face_down']=True
    if kind=='damage':
        damage=re.search(r'(\d+)(?:分)?伤害',masked)
        count_damage=re.fullmatch(r'给[与予](?:对方|自己)为场上盖放的卡数量[×x](\d+)伤害',masked)
        if count_damage:
            q['amount_rule']=dict(kind='printed_card_count',zone='field',position='set',controller='both',multiplier=int(count_damage[1]))
        elif damage:q['amount']=int(damage[1])
    if kind=='position':
        destination=re.search(r'(?:变成|变回|转为)((?:表侧|里侧)?(?:攻击|守备)表示)',masked)
        if destination:q['position']='defense' if '守备' in destination[1] else 'attack'
    if kind=='level' and '原本等级合计' in masked:q['value_rule']='sum_original_levels'
    if kind=='return_extra_deck':
        if '场上' in masked:q['from_zones']=['field']
        if re.search(r'场上(?:存在)?的融合怪兽全部',masked):
            q.update(owner='both',selector_query=dict(type='fusion',face_up=True))
    if kind=='return_deck':
        if '喜欢的顺序' in masked:q['placement_order']='chosen'
        if '卡组下面' in masked or '卡组最下面' in masked:q['deck_position']='bottom'
    if kind=='direct_attack':q.update(subject='this_card' if '这张卡' in masked else 'selected_monsters',permission=True)
    if kind=='race_change':
        from .effect_mechanisms import RACES
        races=dict(RACES, **{'幻想魔族':0x2000000,'幻神兽族':0x200000,'创造神族':0x400000})
        race=next((name for name in races if re.search(r'变(?:成|为)?'+name,masked)),None)
        if race:q.update(race=races[race],race_name=race)
        if '表侧表示' in masked:q['face_up']=True
        if '没有召唤·反转召唤·特殊召唤' in masked:
            q['selector_condition']='not_summoned_this_turn';q.pop('duration',None)
        if '宣言的种族' in masked:q['race_reference']='declared_race'
        if re.search(r'变成那个种族|变成被宣言的种族',masked):q['race_reference']='declared_race'
        if re.search(r'种族[^。]{0,45}(?:相同|和)|变成相同种族',masked):
            q.update(race_reference='source_monster',reference_source=clause)
        if '变成和这张卡相同种族' in masked:q.update(race_reference='this_card',reference_source=clause)
    if kind=='lp_change':
        value=re.search(r'(?:基本分|LP)(?:变成|变为)(一半|\d+)',masked)
        if value:
            q['resource']='lp'
            if value[1]=='一半':q.update(value_rule='current_fraction',fraction=[1,2])
            else:q.update(value_rule='set',value=int(value[1]))
    if kind=='reveal':
        if not origins:
            zone=re.search(r'(额外卡组|融合卡组|手卡|卡组)(?:的)?\d+[只张]',masked)
            if zone:q['from_zones']=[ZONES[zone[1]]]
        q['audience']='both' if '给双方' in masked else 'opponent'
        if '连接怪兽' in masked:q['selector_query']={'type':'link'}
    if kind=='inspect' and '回到原状' in clause:q['restore_state']=True
    if kind=='material_identity':
        q.update(subject='this_card',application='summon_material_only',
                 fields=[key for word,key in (('卡名','name'),('种族','race'),('属性','attribute')) if word in masked])
        if '给人观看的怪兽' in masked or '展示的怪兽' in masked:q['reference']='revealed_monster'
        if '连接召唤' in masked:q['summon_type']='link'
    if kind=='win':
        q['scope']='match' if '比赛' in masked else 'duel'
        # Old Chinese match-winner wording uses 主人 for the controlling player.
        # Do not generalize this historical term to ownership in other effects.
        if re.search(r'这张卡的(?:主人|控制者).*比赛的胜利',masked):q['winner']='controller'
        elif re.search(r'自己(?:得到|获得).*胜利',masked):q['winner']='self'
    if kind=='battle_calculation':q.update(value_rule='original_atk_def',application='this_battle_damage_calculation')
    if kind=='battle_calculation' and '守备力当作攻击力' in masked:q['value_rule']='def_as_atk'
    if kind=='field_change':q['field_name']=next(iter(re.findall(r'当作[「『]([^」』]+)[」』]怪兽',clause)),None)
    if kind=='return_grave':q['to_zone']='grave'
    if kind=='add_extra':q.update(to_zone='extra',face_up=True)
    if kind=='discard':q.update(from_zones=['hand'],to_zone='grave',discard=True)
    if kind=='release':
        count=re.search(r'(\d+)只解放$',masked)
        if count:q['quantity']=int(count[1])
        minimum=re.search(r'怪兽(\d+)只以上解放',masked)
        if '任意数量解放' in masked or minimum:
            q.update(quantity=None,quantity_rule={'kind':'chosen_materials','source':clause})
            if minimum:q['quantity_rule']['minimum']=int(minimum[1])+(1 if '这张卡和' in masked else 0)
    if kind in ('special_summon','token') and '衍生物' in clause:
        q.update(from_zones=[],creates_token=True)
    if kind=='special_summon' and re.search(r'那\d+只之内的1只特殊召唤',masked):q['quantity']=1
    if kind=='return_extra_deck' and '这张卡回到额外卡组' in masked:q['quantity']=1
    if kind=='negate_summon':q.update(summon_negation=True)
    return q


# Match actual processing verbs. Quoted names, activation heads, negative
# instructions and adjectival summon mentions are excluded before classification.
_ACTIONS = (
    ('grave_destination_replace',r'被送去墓地的卡不去墓地而除外'),
    ("send_grave", r"(?:送去|送入|送进|扔进|送往)墓地(?!的)"), ("add_hand", r"加入(?:自己|对方|自身)?手卡"),
    ("draw", r"(?:抽|抽出)(?:\d+张|相等数目|相同数量|那个数量|这个回合|和[^。]{0,35}(?:数量|数目)|[^。]{0,12}数量的卡)|抽出(?!的|过)[^。]{0,85}(?:数量|数目)|抽自己[^。]{0,65}(?:数量|数目)|从卡组抽卡|直到手卡变成\d+张为止抽卡|手卡抽到\d+张"), ("special_summon", r"特殊召唤(?!的|过|成功|时|条件|怪兽|次数)"),
    ("fusion_summon", r"融合召唤(?!的|过|成功|时|条件|怪兽)"),
    ("ritual_summon", r"仪式召唤(?!的|过|成功|时|条件|怪兽)"),
    ("synchro_summon", r"同调召唤(?!的|过|成功|时|条件|怪兽)"),
    ("xyz_summon", r"超量召唤(?!的|过|成功|时|条件|怪兽)"),
    ("link_summon", r"连接召唤(?!的|过|成功|时|条件|怪兽)"),
    ("destroy", r"破坏(?!的|时|场合|怪兽时|耐性)"),
    ("banish", r"除外(?!的|状态|中|区|时|场合|怪兽|卡|数量)"),
    ("return_deck", r"(?:回到|返回|放回|弹回|加入)(?:其)?(?:持有者|自己|对方)?(?:的)?卡组(?:下面)?"),
    ("return_extra_deck", r"(?:回到|返回|放回)(?:持有者|自己|对方)?(?:的)?(?:额外卡组|融合卡组)"),
    ("return_hand", r"(?:回到|返回|弹回|回)(?:其)?(?:持有者|主人|自己|对方)?(?:的)?手卡"),
    ("negate_effect", r"效果(?:直到[^。]{0,20}|在那个回合中|在伤害计算后|只在那次战斗阶段内|1回合只有1次)?(?:变成|变为|当作)?无效"),
    ("negate_activation", r"发动(?:和效果)?无效"),
    ('negate_summon', r'(?:召唤|反转召唤|特殊召唤)(?:[·、](?:召唤|反转召唤|特殊召唤))*[^。]{0,18}(?:无效|无效化)'),
    ("control", r"控制权[^。]{0,24}(?:得到|获得|转移|交给|移给|回归|变更)|(?:得到|获得)[^。]{0,60}控制权|得到对方场上的\d+只[^。]{0,40}怪兽$"),
    ("level", r"等级[^。]{0,18}(?:变成|变为|上升|下降)|变成[^。]{0,40}等级"),
    ("position", r"(?:变成|变回|转为|成为|变更为)(?:表侧|表向|里侧)?(?:攻击|守备)表示|表示形式(?:变更|改变|交换)|(?:变更|改变)[^。]{0,40}表示形式"),
    ("stats", r"(?:攻击力|守备力|攻守力)[^。]{0,25}(?:变成|变为|成为|上升|下降|交换|都会加|加\d+|以\d+计算)|(?:攻击力|守备力|攻守力)各?(?:增加|加\d+|为|是)"),
    ("attach", r"(?:重叠)?(?:作为|当作)(?:[^。]{0,22}的|那)?超量素材|变成[^。]{0,15}超量素材|(?:在这张卡(?:的)?(?:下面|下方)重叠|重叠(?:在|到)这张卡(?:的)?下)"),
    ("place", r"表侧表示放置|灵摆区域放置|魔法与陷阱区域出现"), ("set", r"盖放(?!的|后|时|过|回合)"),
    ("piercing", r"攻击力超过那个守备力|超过其守备力|贯通伤害|超过部分的数值|攻击力超出部分|攻击力超过守备表示怪兽的守备力"),
    ("extra_attack", r"继续(?:向对方怪兽|进行)?攻击|再次攻击|再度攻击|再1次(?:可以)?(?:向怪兽)?攻击|只有1次再攻击|可以向对方怪兽再攻击|[2-9]次攻击|攻击[2-9]次|最多[2-9]次可以向怪兽攻击|通常攻击外加上|通常攻击之上追加|通常的攻击之外再增加|同样数目的攻击|最多有[^。]{0,40}(?:数量|次)的攻击"),
    ("damage", r"(?:给与|给予)[^。]{0,95}伤害|造成[^。]{0,80}(?<!战斗)伤害|受到[^。]{1,60}(?<!战斗|效果)伤害"),
    ("recover_lp", r"(?:回复|恢复)[^。]{0,90}(?:基本分|LP)|(?:基本分|LP)(?:回复|恢复)"),
    ("battle_protection", r"不会被(?:那次)?战斗破坏|不会被战斗(?:·效果)?破坏"),
    ("effect_protection", r"不会被[^。]{0,24}效果破坏"),
    ("unaffected", r"不受[^。]{0,30}效果(?:的)?影响|不会受到[^。]{0,30}的效果"),
    ("response_lock", r"不能对应[^。]*发动|不能把[^。]{0,60}效果发动"),
    ("equip", r"当作装备(?:魔法)?卡[^。]{0,40}装备|作为装备(?:魔法)?卡[^。]{0,40}装备|变成[^。]{0,25}装备卡|(?:给|把)[^。]{0,50}装备$|装备在这张卡(?:身)?上|装备到(?:自己|对方)场上的[^。]{0,15}怪兽上|怪兽装备$|并装备这张卡"),
    ("counter", r"放置(?!的)[^。]{0,30}指示物(?!取除|每)|指示物给[^。]{0,30}放置"),
    ("remove_counter", r"指示物(?:全部|任意数量|\d+个)?(?:取除|除去)|(?:取除|除去)[^。]{0,25}指示物(?!的)"),
    ("activate_card", r"从(?:自己(?:的)?)?(?:手卡|卡组|墓地)[^。]{0,50}(?:选|把)[^。]{1,40}发动$|正确卡区域放置并使用"),
    ("inspect", r"(?:翻开|确认)(?!的)[^。]{0,25}卡组[^。]{0,20}张|把(?:那张|那些|选择的|作为对象的|那张对方的)卡确认|那些全部确认|里侧(?:表示)?卡确认|(?:确认|检视|观看)(?!的|后|过)[^。]{0,25}(?:卡组|手卡|里侧|盖放)|(?:对方|双方|自己)(?:的)?(?:场上[^。]{0,25}(?:盖放|里侧)[^。]{0,15}|卡组[^。]{0,20}|手卡[^。]{0,15})(?:确认|翻开)"),
    ("shuffle", r"卡组(?:并且)?洗切|洗(?:自己|对方)?(?:的|\d+次)?卡组"), ("negate_attack", r"攻击(?:只有\d+次)?无效"),
    ("detach", r'(?:\d+个|全部|任意数量)?超量素材[^。]{0,25}(?:取除|除去)'),
    ("release", r'(?:怪兽|这张卡|那些卡)(?:尽可能|任意数量|\d+只(?:以上)?)?解放|那\d+只[^。]{0,18}之内的\d+只解放'),
    ("direct_attack", r"(?:可以|能够|(?<!不)能)(?:[对向](?:对方(?:玩家)?|玩家))?(?:进行)?直接攻击"),
    ("race_change", r"变成(?:那个|宣言的)?[\u4e00-\u9fff]{1,6}族|种族[^。]{0,40}(?:变成|变为)|种族变[\u4e00-\u9fff]{1,6}族|变成相同种族"),
    ("lp_change", r"(?:基本分|LP)(?:全都)?(?:变成|变为)(?:一半|\d+|比对方少\d+的数值)"),
    ("reveal", r"(?:给对方|向对方)(?:观看|展示|公开)(?!的)|给双方确认(?!的)|(?:给人|向对方)(?:观看|展示)(?!的)"),
    ("material_identity", r"可以当作[^。]{0,60}素材使用"),
    ("win", r"(?:得到|获得)(?:这场)?(?:比赛|决斗)的胜利|(?:自己|对方)决斗胜利"),
    ("battle_calculation", r"伤害计算用原本的攻击力[·、]守备力进行|守备力当作攻击力使用进行伤害计算"),
)
_COMPILED_ACTIONS = tuple((k, re.compile(p)) for k,p in (*_ACTIONS,*((k,p) for k,_,p in FUNCTIONS)))


def _connectors(head, body, mode, scope, row):
    values = []
    if "被效果送去墓地" in head:values.append("被效果送墓")
    elif "战斗破坏送去墓地" in head:values.append("战破送墓")
    elif re.search(r'被(?:战斗[·、]效果|战斗|效果)?破坏(?:并)?送去墓地', head):values.append('破坏送墓')
    elif "被战斗·效果破坏" in head:values.append("被破坏")
    elif "攻击破坏怪兽时" in head:values.append("战破怪兽后")
    # Summoned this turn is a condition on an ignition effect, not a summon trigger.
    if re.search(r"召唤·特殊召唤成功(?:的场合|时)", head):values += ["ns", "ss"]
    elif re.search(r"特殊召唤(?:成功)?(?:的场合|时)", head):values.append("ss")
    elif re.search(r"(?<!特殊)召唤成功(?:的场合|时)", head):values.append("ns")
    if "主要阶段2" in head:values.append("自己主要阶段2")
    elif re.search(r"自己(?:的)?主要阶段", head):values.append("自己主要阶段")
    if "对方回合" in head:values.append("对方回合")
    if "效果发动时" in head:values.append("效果发动时")
    if '伤害计算时' in head:values.append('伤害计算时')
    if re.search(r'战斗破坏(?:对方)?怪兽时',head):values.append('战破怪兽后')
    if not values:
        if mode == "activated":
            without_counts=re.sub(r'\d+回合[^，,]{0,12}次','',head)
            if row.get('type',0)&1 and not re.search(r'场合|时|阶段|回合',without_counts):values += ['起动','自己主要阶段']
            else:values.append("发动")
        elif "只要" in body or any(w in body for w in ("不会被", "不受")):values.append("持续适用")
        elif scope == "pendulum" and "存在才有1次" in body:values.append("持续适用")
        elif mode == "conditional":values.append("条件适用")
        elif row.get("type",0) & 6:values.append("卡片发动")
        else:values.append("时点未解析")
    return values


def block_view(record, row):
    text = record["source_text"]
    scope = record.get("scope", "monster" if row.get("type",0)&1 else "spell_trap")
    key = record.get("effect_key", f"{scope}:{record['effect_index']}:0")
    head, body, offset, mode = activation_parts(text)
    blocks, costs = [], []
    resolved_quantities = tuple(c['source'] for c in record['costs'] if
        c['kind'] == 'send_grave' and c.get('from_zones') == ['deck']
        and c.get('random') and c.get('selector_query'))
    restrictions,descriptions=structural_records(text,row,scope,resolved_quantities=resolved_quantities)
    if mode=='activated' and not body.strip('。；; \r\n') and head.strip():
        descriptions.append(dict(kind='activation_requirement',tag={'dimension':'description','value':'发动条件'},source=text))
    if record['effect_index']==0 and row.get('type',0)&(0x40|0x2000|0x800000|0x4000000) and not descriptions:
        formula=next((s.strip() for s in text.splitlines() if re.search(r'[＋+×]|怪兽\d+只',s)
            and not re.search(r'发动|这张卡|特殊召唤|攻击力|送去|破坏|加入|取除',s)),'')
        if formula:descriptions.append(dict(kind='printed_materials',tag={'dimension':'summon_description','value':'召唤素材说明'},source=formula))
    for i, cost in enumerate(record["costs"]):
        kind = cost["kind"]
        if kind == "mill":kind = "send_grave"
        if kind not in LABELS:continue
        costs.append(dict(block_id=f"{key}:cost:{i}", tag={"dimension":"cost", "value":LABELS[kind]},
                          kind=kind, phase="activation_payment", source=cost.get("source", ""),
                          qualifiers={k:deepcopy(v) for k,v in cost.items() if k not in ("source","kind","cost_index","effect_index")},
                          group=key))
    flavor = bool(row.get("type",0)&0x10 and not row.get("type",0)&0x20 and scope != "pendulum" and record['effect_index']==0)
    choice = bool(re.search(r"以下(?:效果)?.*?选择1个|以下数量取除[，,]那个效果|把以下效果发动", head + text[:offset]))
    if '●' in text and re.search(r'取除[^。]*数量的以下效果|取除数量的以下效果',text):choice=True
    multi_choice=re.search(r'从以下效果选择支付的基本分每(\d+)为1个的数量发动',text)
    conditional_choice=re.search(r'([^。\r\n]+场合)[，,]可以选择两方发动',text)
    if multi_choice:choice=True
    if '●' in text and record['costs'] and re.search(r'●[^●]+发动',text) and not re.search(r'得到|获得',text.split('●',1)[0]):choice=True
    branch = 0
    scan=' '*offset+body
    if mode=='activated':
        activation=ACTIVATION.search(text)
        earlier=text.rfind('。',0,activation.start())+1 if activation and activation.end()==offset else 0
        scan=text[:earlier]+scan[earlier:]
    for cost in record['costs']:
        source=cost.get('source','')
        if source:
            scan=scan.replace(source,' '*len(source),1)
    from .effect_text import activation_headers
    for start,end,_ in activation_headers(text):
        scan=scan[:start]+' '*(end-start)+scan[end:]
    # Split on punctuation, retaining offsets into the unmodified source text.
    for match in re.finditer(r"[^。；;，,\r\n●]+", scan):
        raw = match[0].strip()
        if not raw or flavor or (not row.get('type',0)&0x20 and any(d['kind'] in ('printed_materials','ritual_association','no_pendulum_effect') for d in descriptions)) or mode=='boundary_unknown':continue
        branch = scan[:match.start()].count("●")
        from .effect_text import mask_action_references
        clause = mask_action_references(_unquote(raw))
        start = match.start() + len(match[0])-len(match[0].lstrip())
        processing_clause=clause.split('（',1)[0].split('(',1)[0]
        if ACTIVATION.search(raw) and activation_parts(raw+'。')[3]=='activated':
            continue  # The option's activation payments are not resolution operations.
        conditional_tail = bool(re.search(r"(?:场合|时|之际|的时候)$", processing_clause))
        for kind, pattern in _COMPILED_ACTIONS:
            for action in pattern.finditer(clause):
                as_summon = re.search(r'(?:当作|作为)(融合|同调|超量|连接|仪式)召唤(?:处理)?', raw)
                if as_summon and '特殊召唤' in raw and kind == {
                        '融合':'fusion_summon','同调':'synchro_summon','超量':'xyz_summon',
                        '连接':'link_summon','仪式':'ritual_summon'}[as_summon[1]]:
                    continue  # One special summon with a method classification.
                prefix = clause[:action.start()]
                if kind.endswith('_summon') and kind!='negate_summon' and re.search(r'无效',clause[action.end():]):continue
                if kind=='negate_summon' and re.search(r'无效(?:的场合|时|的怪兽|的卡)',clause[action.start():]):continue
                if kind=='destroy' and re.search(r'(?:被|被战斗|被效果)$',prefix) and not re.search(r'被破坏[。\s]*$',raw):continue
                if kind=='name_change' and re.search(r'卡名(?:全部)?不同',clause) and not re.search(r'当作|变成|视为',clause):continue
                if kind=='reveal' and '给双方确认' in raw and re.search(r'加入(?:自己|自身)?手卡',raw) and '抽' not in raw:continue
                if kind=='position' and re.search(r'再度召唤|再1次召唤',raw):continue
                if kind=='activate_card' and re.search(r'从手卡(?:把)?这张卡发动|这张卡(?:也能|可以)从手卡发动',raw):continue
                if kind=='level' and re.search(r'(?:攻击力|守备力)[^。]*变成[^。]*等级[×x]',raw):continue
                if kind=='ritual_summon' and re.search(r'可以让这1张卡作为仪式召唤的祭品|作为仪式召唤的祭品',raw):continue
                if kind=='ritual_summon' and re.search(r'作为仪式召唤需要的(?:等级)?数值的解放',raw):continue
                if kind=='counter' and re.search(r'放置有|有[^。]{0,25}指示物(?:被)?放置|指示物被放置',raw) and not re.search(r'给这张卡放置$',raw):continue
                if kind in ('discard','detach','remove_counter') and re.search(r'不需要|不用|不需|不必|无需',prefix):continue
                if kind=='inspect' and '翻开' in raw and '卡组' in raw and not re.search(r'确认|观看|检视',raw):continue
                if kind=='lp_payment' and re.search(r'每次[^。]*支付[^。]*发动',raw):continue
                if kind=='material_permission' and '超量素材' in raw and re.search(r'重叠|作为那超量素材',raw):continue
                if kind=='material_level' and re.search(r'得到[^。]*作为融合素材[^。]*等级的以下效果',raw):continue
                if kind=='level' and re.search(r'等级合计[^。]*变成|等级变成[^。]*合计',raw) and not re.search(r'这张卡的等级变成',raw):continue
                if kind=='remove_counter' and re.search(r'^取除的指示物数量|^为这个效果发动而取除',raw):continue
                if kind=='send_grave' and re.search(r'不送去墓地|不去墓地|破坏送去墓地',raw):continue
                if kind=='attach' and '作为超量素材中' in raw:continue
                if kind=='reorder_deck' and not re.search(r'放回|回到|返回|放置|调整|改变|变更|排序|喜欢的顺序',raw):continue
                if kind.endswith('_summon') and re.search(r'(?:1|１)回合只能(?:有)?\d+次',raw):continue
                if kind=='inspect_extra' and re.search(r'给对方|给双方|向对方',raw):continue
                if kind=='attach' and re.search(r'(?:有|持有|取除|去除|作为素材的场合|成为素材的场合)',clause) and not re.search(r'重叠|(?:那张卡|那只怪兽|那些卡|这张卡)作为',clause):continue
                if kind=='banish' and '被送去墓地的卡不去墓地而除外' in clause:continue
                if conditional_tail:continue
                if kind=='stats' and not re.search(r'攻击力|守备力|攻守力',raw) and not re.search(r'攻击力|守备力|攻守力',text[:start]):continue
                if kind=='stats' and not re.search(r'攻击力|守备力|攻守力',raw) and re.search(r'等级|阶级|刻度|基本分|LP',raw):continue
                if processing_clause.endswith('的效果') and kind not in ('quick_effect_grant','damage_recovery','effect_copy','effect_grant','effect_apply'):continue
                if kind=='name_change' and '卡名' not in raw and re.search(r'属性|种族',raw):continue
                if kind=='destruction_replace' and '破坏' not in head+text[max(0,start-100):start]:continue
                if kind=='reorder_deck' and re.search(r'回到|返回|放回',raw) and not re.search(r'翻开|确认',head+text[:start]):continue
                if clause.startswith('每次') and kind in ('special_summon','fusion_summon','synchro_summon','xyz_summon','link_summon','destroy','banish','release','activate_card'):continue
                if kind not in ("battle_protection","effect_protection","unaffected","response_lock","activation_permission"):
                    if re.search(r"不能|无法|不会|不受|不是|不再|不当作", prefix) and not re.search(r'^(?:不是|不为)[^。]*的场合',prefix):continue
                    if kind == "destroy" and re.search(r'战斗(?:被)?$',prefix):continue
                    if kind == "damage" and ("战斗伤害" in clause or "攻击力超过" in clause) and not re.search(r'(?:给与|给予)[^。]+(?:相同|一半|倍)[^。]*伤害$',clause):continue
                    if kind == 'damage' and re.search(r'受到的(?:全部)?伤害变成一半',clause):continue
                q = _qualifiers(raw, kind, record["targets"])
                sentence_prefix=text[text.rfind('。',0,start)+1:start]
                duration=_qualifiers(sentence_prefix,kind,[]).get('duration') if sentence_prefix else None
                if duration and 'duration' not in q:q['duration']=duration
                if kind=='material_identity' and '连接召唤' in sentence_prefix:q['summon_type']='link'
                if kind=='cost_replacement':
                    q['replaces']='activation_payment'
                    q['resource']='xyz_material' if '超量素材' in raw else 'cards'
                    if '只把那只怪兽丢弃' in raw:q.update(replacement_source='hand',quantity=1,original_quantity=2)
                if kind=='race_change' and 'race' not in q and 'race_reference' not in q:continue
                actual = kind
                if kind == 'special_summon' and as_summon:
                    from .construction_inventory import requirement
                    actual = {'融合':'fusion_summon','同调':'synchro_summon','超量':'xyz_summon',
                        '连接':'link_summon','仪式':'ritual_summon'}[as_summon[1]]
                    q.update(summon_method='effect', materials_required=False)
                    parsed = requirement(raw.replace(as_summon[0], ''), 'operations')
                    if parsed:
                        q.update(selector_query=parsed['query'], from_zones=parsed['origins'],
                            quantity=parsed['minimum'], owner=parsed['owner'])
                if kind == "add_hand":
                    actual = "search" if q["from_zones"] == ["deck"] else "recover" if q["from_zones"] in (["grave"],["banished"]) else kind
                if kind == "send_grave" and not q["from_zones"]:
                    # A conditional description of a card sent to the GY is not a send instruction.
                    if re.search(r"送去墓地(?:的|时|后|的场合)", clause[action.start():]):continue
                if kind=='damage' and re.search(r'作为受到的伤害的代替',raw):continue
                block = dict(block_id=f"{key}:effect:{len(blocks)}", tag={"dimension":"effect","value":LABELS[actual]},
                             kind=actual, phase="resolution", source=raw,
                             source_span=[start, start+len(raw)], qualifiers=q, group=key, branch=branch,
                             order=start+action.start())
                if not any(b["kind"]==actual and b["source_span"]==block["source_span"] for b in blocks):blocks.append(block)
    # Cost substitution changes where another effect's payment is made; it is
    # not a payment or removal instruction of this effect itself.
    replacement=re.search(r'(?P<resource>[\u4e00-\u9fff]{0,8}指示物)取除的场合[，,]可以作为代替从这张卡取除',text)
    if replacement and not flavor and mode!='boundary_unknown':
        raw=text.strip();start=text.index(raw)
        blocks.append(dict(block_id=f'{key}:effect:{len(blocks)}',tag={'dimension':'effect','value':LABELS['cost_replacement']},
            kind='cost_replacement',phase='continuous',source=raw,source_span=[start,start+len(raw)],group=key,branch=0,order=start,
            qualifiers=dict(resource='counters',counter_name=replacement['resource'].split('的')[-1],replaces='activation_payment',
                            replacement_source='this_card',original_source='own_field',quantity_rule='entire_payment')))
    # Summon procedures coexist with actual effects in old unnumbered text.
    procedure_blocks=[]
    tribute=re.search(r'只能用自己场上(\d+)只([^。]{1,15}族)怪兽作为祭品进行祭品召唤出场',text)
    if tribute and scope=='monster':
        procedure_blocks.append(dict(block_id=f'{key}:procedure:0',tag={'dimension':'summon_procedure','value':LABELS['tribute_summon']},
            kind='tribute_summon',phase='summon_procedure',source=tribute[0],source_span=list(tribute.span()),group=key,
            qualifiers=dict(from_zones=['field'],owner='self',quantity=int(tribute[1]),race_name=tribute[2],material_reason='tribute')))
    from .effect_text import complete_structure
    complete_structure(text,row,scope,blocks,costs,procedure_blocks,restrictions,descriptions,key)
    blocks.sort(key=lambda b:b['order'])
    for i,b in enumerate(blocks):b['block_id']=f'{key}:effect:{i}'
    for b in list(blocks):
        if b['kind']=='battle_cost' and '攻击宣言' in text:
            amount=re.search(r'支付(\d+)基本分',b['source'])
            b.update(block_id=f'{key}:cost:{len(costs)}',kind='pay_lp',phase='attack_payment',tag={'dimension':'cost','value':LABELS['pay_lp']})
            b['qualifiers'].update(reason='cost',resource='lp',owner='self',quantity=int(amount[1]) if amount else None,
                                   payment_event='attack_declaration')
            costs.append(b);blocks.remove(b)
    revealed=None
    for b in blocks:
        if b['kind']=='reveal':revealed=b['block_id']
        if b['kind']=='material_identity' and revealed:b['qualifiers']['reference_block']=revealed
    if mode!='activated':
        for b in list(blocks):
            if b['kind'] in ('tribute_reduction','tribute_count','tribute_summon'):
                b['tag']['dimension']='summon_procedure';b['phase']='summon_procedure'
                procedure_blocks.append(b);blocks.remove(b)
    connector_values = _connectors(head, body, mode, scope, row) if blocks else ['召唤手续'] if procedure_blocks else ['召唤说明'] if descriptions else _connectors(head, body, mode, scope, row)
    continuous = "持续适用" in connector_values or (mode == "conditional" and all(b["kind"] in ("piercing","battle_protection","effect_protection","unaffected") for b in blocks))
    permission_kinds={'direct_attack','cost_replacement','name_change','attribute_change','type_change','material_permission','material_count','defense_attack','attack_all'}
    if row.get('type',0)&(0x20000|0x80000):permission_kinds|={'race_change','stats','damage_change','hand_public','zone_limit'}
    if mode!='activated' and blocks and all(b['kind'] in permission_kinds for b in blocks):
        continuous=True
        connector_values=['持续适用']
    if continuous:
        for b in blocks:
            if b['phase']=='resolution':b["phase"] = "continuous"
    connectors = [dict(connector_id=f"{key}:connector:{i}", kind=v, effect_key=key,
                       source="condition", target="effect_group", condition_source=head or None)
                  for i,v in enumerate(connector_values)]
    if continuous:
        for c in connectors:c['starts_chain']=False
    for block in blocks:
        prior=text[:block['source_span'][0]].rstrip('，, ')
        condition=re.split(r'[。；;，,\r\n]',prior)[-1]
        if re.search(r'(?:场合|时|时候)$',condition) and not condition.startswith('直到'):
            connectors.append(dict(connector_id=f'{key}:connector:{len(connectors)}',kind='条件适用',effect_key=key,
                                   source='condition',target=block['block_id'],condition_source=condition))
    selector_notes=[]
    for sentence in re.finditer(r'(?:^|。)(选择(?:自己|对方)场上[^。]{0,50}(?:怪兽|卡))[。]',text):
        selector_notes.append(sentence[1])
        connectors.append(dict(connector_id=f'{key}:connector:{len(connectors)}',kind='怪兽选择',effect_key=key,
                               source='selection',target='effect_group',condition_source=sentence[1],timing='unspecified_legacy'))
    unknown = list(record["unknown"])
    remainder=list(scan)
    for item in (*restrictions,*descriptions,*record['costs']):
        source=item.get('source','');start=text.find(source)
        if source and start>=0:remainder[start:start+len(source)]=' '*len(source)
    remaining=''.join(remainder)
    for selector in selector_notes:remaining=remaining.replace(selector,'')
    # Known control syntax is metadata, including old unnumbered material
    # formulas and selectors following a restriction's bullet introduction.
    remaining=re.sub(r'这个效果(?:1回合只能(?:使用|适用)1次|在对方回合也能发动)|这张卡特殊召唤时适用|这个效果直到[^。]+为止适用|发动[。；;]','',remaining)
    if any(r['kind'] in ('forbidden_card','protected_selector') for r in restrictions):
        remaining=re.sub(r'●[^。\r\n]+','',remaining)
    restriction_only=bool(restrictions) and not re.search(r'[\u4e00-\u9fff]',remaining)
    description_only=bool(descriptions) and not re.search(r'[\u4e00-\u9fff]',remaining)
    # Payment alone resolves only an otherwise empty processing body.
    cost_only=bool(costs) and (not re.search(r'[\u4e00-\u9fff]',remaining) or all(c['phase']=='attack_payment' for c in costs) and not blocks)
    if not blocks and not procedure_blocks and not flavor and not restriction_only and not description_only and not cost_only:
        unknown.append("no_recognized_function")
    limits = deepcopy(record["count_limits"])
    if "以下效果1回合各能选择1次" in text:
        limits.append(dict(status="known",scope="same_name_each_option",maximum=1,period="turn",count_event="choose"))
    if "决斗中只能使用1次" in text:
        limits.append(dict(status="known",scope="same_name_this_effect",maximum=1,period="duel",count_event="use"))
    if scope == "pendulum" and "灵摆区域存在才有1次" in text:
        limits.append(dict(status="known",scope="this_card_while_in_pendulum_zone",maximum=1,period="presence",count_event="apply"))
    if mode=='activated' and '伤害计算时' in head and re.search(r'发动1次[。；;]',text[:offset]):
        limits.append(dict(status='known',scope='this_effect',maximum=1,period='damage_calculation',count_event='activate'))
    if any(b['kind']=='cost_replacement' for b in blocks) and '1回合1次' in text:
        existing=[limit for limit in limits if limit.get('status')=='known' and limit.get('scope')=='this_card_effect'
            and limit.get('maximum')==1 and limit.get('period')=='turn']
        if existing:
            for limit in existing:limit['count_event']='apply'
        else:
            limits.append(dict(status='known',scope='this_card_effect',maximum=1,period='turn',count_event='apply'))
    for limit in limits:limit.setdefault('source',text)
    for dimension,items in (('restriction',restrictions),('description',descriptions)):
        for i,item in enumerate(items):
            start=text.index(item['source'])
            item.update(block_id=f'{key}:{dimension}:{i}',group=key,source_span=[start,start+len(item['source'])])
    return dict(version=BLOCK_VERSION, effect_key=key, scope=scope, blocks=blocks, cost_blocks=costs,procedure_blocks=procedure_blocks,
                restrictions=restrictions,description_blocks=descriptions,
                connectors=connectors, alternatives=dict(mode='subset' if multi_choice or conditional_choice else 'one_of',branches=sorted({b['branch'] for b in blocks}),
                    **({'default_count':1,'count_variants':[{'count':2,'condition_source':conditional_choice[1]}]} if conditional_choice else {}),
                    **({'count_binding':{'resource':'paid_lp','divisor':int(multi_choice[1]),'source':multi_choice[0]}} if multi_choice else {})) if choice else None,
                count_limits=limits, target_refs=list(range(len(record['targets']))),
                grouping_status='unresolved_text_group' if record['effect_index']==0 else 'numbered_effect',
                status="flavor" if flavor else "observed" if blocks or procedure_blocks else "restriction" if restriction_only else "summon_description" if description_only else "cost_only" if cost_only else "unresolved",
                unknown=list(dict.fromkeys(unknown)))


def record_operations(record):
    """Refine the shared operation records with the same scoped verb evidence.

    Legacy detailed fields (fusion material cycling, selectors, quantities) are
    reused. Referenced/negated operations rejected by the block view cannot leak
    into the construction relation adapter through an older broad regex.
    """
    projection={'search':'search_or_recover','recover':'search_or_recover','add_hand':'search_or_recover',
                'negate_effect':'negate','negate_activation':'negate'}
    result=[]
    previous={}
    for block in record['block_view']['blocks']:
        kind=projection.get(block['kind'],block['kind'])
        if kind=='send_grave' and block['qualifiers'].get('random'):kind='mill'
        compatible={kind}
        if kind=='return_deck':compatible.add('return_fusion_materials')
        legacy=next((o for o in record['operations'] if o['kind'] in compatible and
                     (block['source'] in o.get('source','') or o.get('source','') in block['source'])),None)
        op=deepcopy(legacy) if legacy else dict(kind=kind)
        if block['qualifiers'].get('materials_required') is False:
            op.pop('materials', None)
        for key,value in block['qualifiers'].items():
            if value is not None and value!=[] and value!='unknown':op[key]=deepcopy(value)
        if re.match(r'^\d+(?:个|只|张)?(?:以上|以下)?[：:]',block['source']):
            op['quantity']=block['qualifiers'].get('quantity')
        if 'amount_rule' in op:op.pop('amount',None)
        op.setdefault('quantity',None)
        # Keep a recognized bounded selector, e.g. "从卡组...送去墓地",
        # without adding the optional "可以" prefix to inventory.requirement.
        source=legacy['source'] if legacy and legacy.get('source') in block['source'] else block['source']
        if block['qualifiers'].get('materials_required') is False:
            source=block['source']
        op.update(reason='effect',phase=block['phase'],source=source,order=block['order'],
                  block_id=block['block_id'],effect_key=record['effect_key'])
        if record['block_view']['alternatives']:op['choice']='option:'+str(block['branch'])
        prior=previous.get(block['branch'])
        if prior and re.search(r'那之后|然后|之后',record['source_text'][prior['order']:block['order']]):
            op['depends_on']=[prior['block_id']]
        previous[block['branch']]=block
        result.append(op)
    return result


def identity_tags(row, set_names):
    from .effect_mechanisms import RACES
    from .build_semantics import matches
    tags = []
    def add(dim, value):
        tag = {"dimension":dim,"value":str(value)}
        if tag not in tags:tags.append(tag)
    for name, code in set_names.items():
        if code and matches(row,{"field":"setcode","value":code}):add("field",name)
    races = dict(RACES, **{"幻想魔族":0x2000000,"幻神兽族":0x200000,"创造神族":0x400000})
    for name, flag in races.items():
        if row.get("race",0)&flag:add("race",name)
    for name, flag in (("地",1),("水",2),("炎",4),("风",8),("光",16),("暗",32),("神",64)):
        if row.get("attribute",0)&flag:add("attribute",name)
    for name, flag in (("怪兽",1),("魔法",2),("陷阱",4),("通常",0x10),("效果",0x20),("融合",0x40),
                       ("仪式",0x80),("速攻",0x10000),("永续",0x20000),("装备",0x40000),("场地",0x80000),
                       ("反击",0x100000),("同调",0x2000),("超量",0x800000),("灵摆",0x1000000),
                       ("连接",0x4000000),("调整",0x1000),("反转",0x200000),
                       ("灵魂",0x200),("同盟",0x400),("二重",0x800),("卡通",0x400000),("特殊召唤",0x2000000)):
        if row.get("type",0)&flag:add("card_type",name)
    if row.get("type",0)&1:
        dim = "rank" if row['type']&0x800000 else "link" if row['type']&0x4000000 else "level"
        add(dim,row.get("level",0)&255)
    if row.get("type",0)&0x1000000:
        add("pendulum_scale_left",(row.get("level",0)>>24)&255)
        add("pendulum_scale_right",(row.get("level",0)>>16)&255)
    return tags


def card_blocks(catalog, code, *, set_names=None):
    row = catalog.assets.rows[code]
    if set_names is None:
        set_names = getattr(catalog.assets,"set_names",{})
        commits = catalog.assets.receipt.get("source_commits",{})
        if commits:
            from .construction_inventory import archetype_names
            set_names,_ = archetype_names(commits.get("database"),catalog.cards_sha256)
    records = catalog.effect_records(code)
    effects = [deepcopy(r["block_view"]) for r in records]
    # Preserve the two established construction identities as qualified aliases.
    profile = catalog.card(code)
    aliases = []
    for r,e in zip(records,effects):
        for b in e["blocks"]:
            if b["kind"]=="send_grave" and b["qualifiers"].get("from_zones")==["deck"]:
                aliases.append(dict(tag={"dimension":"effect","value":"卡组送墓"},effect_key=e['effect_key'],source=b['source']))
        if "墓地融合" in profile.tags and any(x.index==r['effect_index'] for x in profile.grave_fusion):
            aliases.append(dict(tag={"dimension":"effect","value":"墓地融合"},effect_key=e['effect_key'],source=r['source_text'][:512]))
    monster_text=re.split(r'【怪兽(?:效果|描述)】',row.get('desc',''))[-1]
    prelude = re.split(r"[①②③④⑤⑥⑦⑧⑨⑩][：:]",monster_text,maxsplit=1)[0]
    restrictions=[]
    for r in records:
        for restriction in r['card_restrictions']:
            if restriction not in restrictions:restrictions.append(deepcopy(restriction))
    if '这张卡不能特殊召唤' in prelude:
        restrictions.append(dict(kind='cannot_special_summon_this_card',scope='this_card',duration='intrinsic',source='这张卡不能特殊召唤'))
    if re.search(r'效果发动的回合[，,]自己不能攻击宣言',prelude):
        restrictions.append(dict(kind='cannot_declare_attack',scope='player',duration='whole_turn',condition='effect_activation',source=prelude.strip()))
    return dict(dictionary_version=BLOCK_VERSION,dictionary_revision=BLOCK_REVISION,card_id=code,name=row.get('name',''),
                cards_sha256=profile.cards_sha256,text_sha256=profile.text_sha256,
                identity_tags=identity_tags(row,set_names), effects=effects, compatibility_tags=aliases,
                summon_materials=next((deepcopy(r['printed_materials']) for r in records if r['scope']=='monster'),[]),
                summon_material_source=next((s.strip() for s in prelude.splitlines() if re.search(r"[＋+×]",s)),None),
                card_restrictions=restrictions,card_prelude=prelude,
                source_records=[{k:v for k,v in r.items() if k!='block_view'} for r in records])


def functional_tags(entry):
    """One source-bound effect tag per card; costs are intentionally separate."""
    result = {}
    for effect in entry['effects']:
        for block in effect['blocks']:
            result.setdefault(block['tag']['value'],dict(tag=block['tag'],source=block['source'],effect_key=effect['effect_key']))
    for item in entry['compatibility_tags']:result.setdefault(item['tag']['value'],item)
    return tuple(result.values())


def build_dictionary(catalog, path, *, source=None):
    """Export the canonical, non-token pool atomically, using the live API."""
    path=Path(path).resolve();path.parent.mkdir(parents=True,exist_ok=True)
    from .card_identity import canonical_card_id
    codes=sorted(c for c,r in catalog.assets.rows.items()
                 if canonical_card_id(catalog.assets.rows,c)==c and not r.get('type',0)&0x4000 and r.get('name','').strip())
    counts=Counter();functions=Counter();payments=Counter();procedures=Counter();restriction_counts=Counter();description_counts=Counter();unresolved=[]
    fd,tmp=tempfile.mkstemp(prefix=path.stem+'-',suffix='.building.sqlite3',dir=path.parent)
    import os
    os.close(fd)
    try:
        with closing(sqlite3.connect(tmp)) as db, db:
            db.executescript('''
                create table metadata(key text primary key,value text not null);
                create table cards(card_id integer primary key,name text not null,payload text not null);
                create table tags(card_id integer,dimension text,value text,effect_key text,block_id text);
                create index tags_lookup on tags(dimension,value,card_id);
                create table connectors(card_id integer,effect_key text,kind text);
                create index connectors_lookup on connectors(kind,card_id);
            ''')
            for code in codes:
                entry=catalog.effect_blocks(code)
                db.execute('insert into cards values(?,?,?)',(code,entry['name'],json.dumps(entry,ensure_ascii=False,separators=(',',':'))))
                tags=[(code,t['dimension'],t['value'],'','') for t in entry['identity_tags']]
                has_function=False
                for effect in entry['effects']:
                    counts['effect_records']+=1
                    counts[effect['status']+'_effect_records']+=1
                    if effect['unknown']:counts['effect_records_with_unknown_details']+=1
                    if effect['status']=='unresolved':unresolved.append(dict(card_id=code,effect_key=effect['effect_key']))
                    for key,counter in (('blocks',functions),('cost_blocks',payments),('procedure_blocks',procedures),
                                        ('restrictions',restriction_counts),('description_blocks',description_counts)):
                        for block in effect[key]:
                            counter[block['tag']['value']]+=1
                            tags.append((code,block['tag']['dimension'],block['tag']['value'],effect['effect_key'],block['block_id']))
                            if key=='blocks':has_function=True
                    for connector in effect['connectors']:
                        db.execute('insert into connectors values(?,?,?)',(code,effect['effect_key'],connector['kind']))
                        counts['connectors']+=1
                tags.extend((code,t['tag']['dimension'],t['tag']['value'],t['effect_key'],'compatibility') for t in entry['compatibility_tags'])
                db.executemany('insert into tags values(?,?,?,?,?)',tags)
                counts['identity_tags']+=len(entry['identity_tags'])
                counts['cards_with_functions' if has_function else 'cards_without_functions']+=1
            manifest=dict(dictionary_version=BLOCK_VERSION,dictionary_revision=BLOCK_REVISION,source=source or {},cards_sha256=catalog.cards_sha256,
                          pool_scope='independent printed identities; non-token; named; no period/banlist filter',total_source_rows=len(catalog.assets.rows),
                          canonical_cards=len(codes),counts=dict(counts),function_blocks=dict(sorted(functions.items())),
                          cost_blocks=dict(sorted(payments.items())),unresolved_effects=unresolved,
                          procedure_blocks=dict(sorted(procedures.items())),
                          restriction_blocks=dict(sorted(restriction_counts.items())),description_blocks=dict(sorted(description_counts.items())),
                          training_started=False,cb_started=False)
            db.execute('insert into metadata values(?,?)',('manifest',json.dumps(manifest,ensure_ascii=False)))
        os.replace(tmp,path)
        return manifest
    finally:
        if Path(tmp).exists():Path(tmp).unlink()


class EffectBlockDictionary:
    """Read-only catalog lookup; loading it never imports training or an engine."""
    def __init__(self, path):
        self.db = sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)
        self.metadata = json.loads(self.db.execute("select value from metadata where key='manifest'").fetchone()[0])
        if self.metadata['dictionary_version'] != BLOCK_VERSION:
            self.close(); raise ValueError('unsupported effect-block dictionary version')

    def close(self):self.db.close()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()

    def card(self, code):
        row = self.db.execute("select payload from cards where card_id=?",(code,)).fetchone()
        return json.loads(row[0]) if row else None

    def find(self, dimension, value):
        return tuple(r[0] for r in self.db.execute(
            "select distinct card_id from tags where dimension=? and value=? order by card_id",(dimension,value)))

    def find_connector(self, kind):
        return tuple(r[0] for r in self.db.execute(
            "select distinct card_id from connectors where kind=? order by card_id",(kind,)))
