"""Offline, per-card coarse semantic comparison against the Baige snapshot.

The review keeps literal contradictions, inferred discrepancies and unhandled
phrases separate. A row without a discrepancy is never a rules-engine verdict.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import re
import sqlite3


# This list is a review vocabulary. It is independent of the runtime matcher:
# in particular it preserves quoted token names, costs and noun references.
PREDICATES = (
    ('token', r'(?:(?:生成|特殊召唤)[^。；]{0,100}「[^」]*衍生物」|「[^」]*衍生物」[^。；]{0,100}特殊召唤)'),
    ('send_grave', r'送去墓地'), ('add_hand', r'加入(?:(?:自己|对方|其|持有者|自身)(?:的)?)?手卡'),
    ('draw', r'(?:抽|抽出)(?:\d+张|相同数量|相等数目)|(?:从(?:自己|对方)?卡组)?抽出[^。]{0,60}(?:数量|数目)|为止(?:从卡组)?抽卡|手卡抽到\d+张|抽相等数目的卡'),
    ('special_summon', r'特殊召唤'), ('fusion_summon', r'融合召唤'),
    ('ritual_summon', r'仪式召唤'), ('synchro_summon', r'同调召唤'),
    ('xyz_summon', r'超量召唤'), ('link_summon', r'连接召唤'),
    ('normal_summon', r'(?:把|将|选)[^。]{0,70}怪兽(?:通常)?召唤$|给人观看的怪兽召唤$|进行[^。]{0,35}(?<!特殊|融合|仪式|同调|超量|连接|上级|灵摆)召唤'),
    ('tribute_summon', r'进行[^。]{0,35}上级召唤|怪兽上级召唤$'),
    ('destroy', r'破坏'), ('banish', r'除外'), ('release', r'解放'),
    ('return_deck', r'(?:回到|返回|回|放回|加入)(?:其|持有者|自己|对方)?(?:的)?卡组'),
    ('return_extra_deck', r'(?:回到|返回|放回)(?:其|持有者|自己|对方)?(?:的)?(?:额外卡组|融合卡组)'),
    ('return_hand', r'(?:回到|返回|回)(?:其|持有者|自己|对方)?(?:的)?手卡'),
    ('return_grave', r'(?:回到|返回)墓地'),
    ('discard', r'(?:丢弃|舍弃)'), ('detach', r'超量素材(?:全部)?取除|\d+个超量素材取除'),
    ('pay_lp', r'支付(?:\d+(?:的倍数)?(?:基本分|LP)|一半(?:基本分|LP))|(?:基本分|LP)支付一半'),
    ('lp_loss', r'失去[^。]{0,40}(?:基本分|LP)'),
    ('lp_change', r'(?:基本分|LP)(?:全都)?变成(?:一半|\d+)'),
    ('lp_exchange', r'(?:基本分|LP)交换'),
    ('recover_lp', r'(?:回复|恢复)[^。]{0,50}(?:基本分|LP)|(?:基本分|LP)(?:回复|恢复)'),
    ('damage', r'(?:给与|给予|造成)[^。]{0,80}(?:效果)?伤害|受到\d+(?:分)?伤害'),
    ('negate_activation', r'发动(?:和效果)?无效'),
    ('negate_effect', r'效果(?:直到[^。]{0,25}|只在[^。]{0,25}|在伤害计算后)?(?:变成|变为)?无效'),
    ('negate_summon', r'那次(?:特殊)?召唤无效|(?:召唤|反转召唤|特殊召唤)无效|那个无效'),
    ('negate_attack', r'(?:那次|这次)?攻击无效'),
    ('stats', r'(?:攻击力|守备力|攻守力)[^。]{0,35}(?:变成|变为|成为|上升|下降|增加|交换|为|是|加\d+)'),
    ('level', r'等级(?:[·、]阶级)?[^。]{0,20}(?:变成|变为|上升|下降)|变成[^。]{0,40}等级$'),
    ('rank_change', r'阶级[^。]{0,20}(?:变成|上升|下降)'),
    ('position', r'(?:变成|变回|成为|转为)(?:表侧|里侧)?(?:攻击|守备)表示|表示形式(?:变更|改变)|(?:改变|变更)[^。]{0,20}表示形式'),
    ('set', r'(?:场上|区域|区)(?:里侧守备表示)?盖放|把[^。]{0,50}盖放$'),
    ('place', r'表侧表示放置|灵摆区域放置|魔法与陷阱区域出现'),
    ('equip', r'(?:当作装备卡|当作装备魔法卡|作为装备卡)[^。]{0,50}装备|(?:给|把|将)[^。]{0,50}装备$'),
    ('attach', r'(?:重叠)?作为[^。]{0,20}超量素材|变成[^。]{0,20}超量素材'),
    ('counter', r'放置[^。]{0,55}?指示物|指示物给[^。]{0,20}放置'),
    ('remove_counter', r'指示物(?:全部)?(?:取除|除去)'),
    ('reveal', r'(?:给对方|向对方|给双方|给人)(?:观看|展示|确认)|(?:公开|展示)[^。]{0,30}手卡'),
    ('inspect', r'(?:翻开|确认|观看)[^。]{0,35}(?:卡组|手卡)|(?:额外卡组|卡组|手卡|盖放的[^。]{0,15}卡)[^。]{0,20}(?:翻开|确认|观看)'),
    ('place_deck', r'卡组(?:最)?(?:上面|下面|顶端|底部)(?:放置|放回)|放(?:置|回|在)(?:到)?(?:自己)?(?:的)?卡组(?:的)?(?:最)?(?:上面|下面)'),
    ('hand_public', r'手卡(?:全部)?(?:持续)?公开'),
    ('shuffle', r'卡组洗切|洗切(?:自己|对方)?(?:的)?卡组|洗(?:自己|对方)?(?:的)?卡组'),
    ('direct_attack', r'(?:可以|能够|能)[^。]{0,12}直接攻击'),
    ('extra_attack', r'再(?:1次|次|度|进行)?攻击|继续[^。]{0,15}攻击|[2-9]次(?:可以)?(?:向怪兽)?攻击|追加\d*次攻击|通常(?:的)?攻击(?:外加上|之外|之上)|最多有[^。]{0,40}攻击'),
    ('piercing', r'攻击力超过[^。]{0,20}守备力|超过部分的数值[^。]{0,20}战斗伤害|贯通伤害'),
    ('battle_protection', r'(?:不会|不)被(?:那次)?战斗(?:[·、]效果)?破坏|不会被战斗破坏'),
    ('effect_protection', r'不会被[^。]{0,30}效果破坏|不被[^。]{0,20}效果破坏|不会被战斗以外破坏'),
    ('unaffected', r'不受[^。]{0,35}效果(?:的)?影响|不会受到[^。]{0,30}的效果'),
    ('control', r'(?:得到|获得)[^。]{0,40}控制权|控制权[^。]{0,25}(?:得到|获得|转移|交给|移给|回归)'),
    ('control_swap', r'控制权[^。]{0,12}交换|交换[^。]{0,20}控制权'),
    ('coin', r'(?:投掷|投|抛|掷)[^。]{0,6}硬币'), ('dice', r'(?:投掷|投|抛|掷)[^。]{0,6}骰子'),
    ('declare', r'宣言(?:1个|1张|1种|一个|卡名|属性|种族|数字|等级)'),
    ('skip_phase', r'(?:跳过|略过)[^。]{0,30}(?:阶段|回合)|(?:阶段|回合)[^。]{0,15}跳过'),
    ('end_phase', r'(?:立即|立刻|强制|就此)结束[^。]{0,10}(?:阶段|回合)|(?:战斗|主要)阶段结束$'),
    ('damage_change', r'(?:战斗伤害|效果伤害|受到的(?:全部)?伤害|那次伤害)[^。]{0,30}(?:变成|变为|加倍|减半)|伤害(?:变成|变为|为)0'),
    ('damage_redirect', r'伤害[^。]{0,45}(?:代受|代替|承受)|(?:对方|自己)代替[^。]{0,25}伤害'),
    ('destruction_replace', r'作为代替[^。]{0,50}(?:除外|丢弃|解放|破坏|取除)|代替破坏'),
    ('activation_permission', r'从手卡也能用|从手卡发动|在盖放的回合[^。]{0,20}发动'),
    ('additional_normal', r'通常召唤外加上|(?:召唤次数|通常召唤)[^。]{0,15}(?:增加|追加)|通常召唤最多\d+次'),
    ('name_change', r'卡名[^。]{0,50}当作|当作[^。]{0,40}同名卡使用'),
    ('race_change', r'种族[^。]{0,25}(?:变成|变为)|变成[^。]{0,12}族'),
    ('attribute_change', r'属性[^。]{0,25}(?:变成|变为|当作)|变成宣言的属性|变成[光暗地水炎风神]属性'),
    ('scale_change', r'灵摆刻度[^。]{0,25}(?:变成|上升|下降)'),
    ('effect_grant', r'(?:得到|获得)[^。]{0,60}以下(?:的)?效果'),
    ('effect_copy', r'(?:得到|获得)[^。]{0,50}(?:相同效果|相同的效果|卡名[·、]效果)|效果变成[^。]{0,40}效果'),
    ('win', r'(?:得到|获得)[^。]{0,15}(?:比赛|决斗)的胜利|(?:自己|对方)决斗胜利'),
    ('response_lock', r'不能对应[^。]{0,80}发动|不能把[^。]{0,70}效果发动'),
    ('deck_invert', r'卡组上下翻转'), ('field_shuffle', r'里侧守备表示怪兽洗切'),
    ('quick_effect_grant', r'效果变成对方回合也能发动'),
    ('material_reduction', r'连接素材[^。]{0,15}减少'),
    ('material_race', r'种族当作[^。]{0,15}族使用'),
    ('selection_expand', r'破坏的怪兽从对方场上也能选|也能作为代替从对方墓地装备'),
    ('force_battle', r'怪兽战斗进行伤害计算|怪兽向[^。]{0,30}怪兽作出攻击'),
    ('field_name', r'场地变成「[^」]+」'),
    ('pendulum_scale_use', r'用对方一组灵摆刻度'),
    ('cost_source_expand', r'从额外卡组选[^。]{0,60}发动而解放的同调怪兽'),
    ('tribute_replace', r'作为代替而解放来上级召唤'),
    ('face_up', r'(?:全部变成|全部变为)表侧表示|翻开确认|确认后回复原状'),
    ('card_public', r'抽到的卡持续公开|确认对方抽到的卡|卡全部确认'),
    ('cost_replacement', r'取除的[^。]{0,15}超量素材可以从|当作取除的超量素材中的\d+个|作为代替只把那只怪兽丢弃|作为代替从这张卡取除'),
    ('turn_count', r'回合计算(?:前进|倒退)'),
    ('tribute_count', r'可以作为\d+只的数量解放|作为\d+只(?:份|的数量)的祭品'),
    ('cost_reduction', r'(?:不需|不用|不必)支付(?:基本分|LP)|支付的基本分变成不需要|不把超量素材取除来发动'),
    ('effect_apply', r'(?:这张卡的[①②③④⑤⑥]的效果|作为这张卡的效果|卡发动时的效果)[^。]{0,15}适用'),
    ('field_change', r'当作「[^」]+」怪兽使用'),
    ('draw_count', r'通常抽卡(?:变成|增加)|抽卡阶段[^。]{0,25}抽卡数量'),
    ('equip_move', r'装备卡转换给|装备的对象(?:改变|变更)|装备魔法卡转移给|转换给1只别的'),
    ('gemini_enable', r'(?:变成|当作)再1次召唤的状态'),
    ('add_extra', r'表侧(?:表示)?加入[^。]{0,15}额外卡组'),
    ('position_swap', r'位置交换'),
    ('damage_prevent', r'不会受到[^。]{0,60}伤害|效果伤害无效|战斗伤害为零'),
    ('stat_reset', r'效果上升的数值回到0'),
    ('force_direct_attack', r'变成对(?:玩家|自己(?:基本分)?)的直接攻击'),
    ('additional_pendulum', r'通常的灵摆召唤外加上'),
    ('type_change', r'(?:当作|变成)(?:通常怪兽|调整|调整以外的怪兽|卡通怪兽|效果怪兽|永续魔法|永续陷阱|装备魔法|装备卡)'),
    ('material_permission', r'手卡的这张卡也能作为[^。]{0,15}素材|(?:可以|也能)[^。]{0,70}(?:作为|成为)[^。]{0,25}素材|可以代替融合怪兽素材'),
    ('material_count', r'(?:作为|当作)\d+只(?:分|数量)的?[^。]{0,15}素材'),
    ('material_level', r'把这张卡的等级当作|当作\d+星(?:怪兽|的素材)|当作和作为对象的怪兽的原本等级相同等级使用'),
    ('material_identity', r'当作和给人观看的怪兽相同的卡名[·、]种族[·、]属性的素材使用'),
    ('tribute_reduction', r'(?:不用|不需要)解放(?:作|进行)?(?:通常)?召唤|不用祭品(?:作|进行)?召唤|需要的解放[^。]{0,10}减少'),
    ('defense_attack', r'(?:用|以|在)(?:表侧)?守备表示[^。]{0,20}(?:攻击|作出攻击)'),
    ('attack_all', r'(?:向|对)[^。]{0,25}(?:全部怪兽|怪兽全部)各[^。]{0,20}攻击|攻击对方(?:的)?全部怪兽'),
    ('damage_recovery', r'(?:伤害|回复)[^。]{0,25}(?:变成|改为|变为)[^。]{0,20}(?:回复|伤害)'),
    ('effect_target', r'对象(?:转移|变更|转换|移向)|(?:变更|改变)[^。]{0,20}效果的对象|转移给其他正确的对象'),
    ('reorder_deck', r'用喜欢的顺序[^。]{0,20}卡组|卡组[^。]{0,20}用喜欢的顺序'),
    ('repeat_phase', r'(?:进行|得到|获得)(?:第2次|2次|额外的)[^。]{0,10}阶段|战斗阶段(?:可以)?进行2次'),
    ('advance_phase', r'变成(?:这个|那个)回合的结束阶段'),
    ('battle_target', r'攻击对象(?:转移|变更|改变|移去)|(?:转移|变更|改变)[^。]{0,20}攻击对象'),
    ('zone_move', r'(?:位置|区域)[^。]{0,18}(?:移动|转移)|移动到[^。]{0,20}(?:区域|区)'),
    ('hand_exchange', r'交换(?:双方|自己和对方)的?手卡|双方的?手卡[^。]{0,15}交换'),
    ('draw_replace', r'(?:通常抽卡|抽卡阶段的抽卡|抽卡阶段进行的抽卡)[^。]{0,20}(?:代替|不进行)|作为[^。]{0,15}抽卡的代替'),
    ('effect_optional', r'(?:必须|强制)[^。]{0,20}(?:变成|改为)可以'),
    ('cost_material_replace', r'也能把那些解放的怪兽[^。]{0,25}超量素材取除'),
    ('grave_destination_replace', r'被送去墓地的卡不去墓地而除外'),
    ('battle_calculation', r'伤害计算用原本的攻击力[·、]守备力进行|守备力当作攻击力使用进行伤害计算'),
    ('lp_payment', r'(?:对方|双方)(?:也要)?支付[^。]{0,35}基本分'),
    ('dice_result', r'可以把那之内1个数目作为'),
    ('damage_copy', r'对方也受到相同数值的效果伤害|也给与对方基本分这次战斗'),
    ('damage_type', r'算作这张卡的效果造成的伤害'),
)
COMPILED = [(kind, re.compile(pattern)) for kind,pattern in PREDICATES]
EQUIVALENT = {
    'add_hand': {'add_hand','search','recover'}, 'draw': {'draw'},
    # A token is still a special summon at the user-approved coarse level;
    # token identity remains visible in the quoted creation instruction.
    'token': {'token','special_summon'},
    'inspect': {'inspect','inspect_hand','inspect_extra','face_up','card_public','reveal_deck'},
    'reveal': {'reveal','card_public','hand_public','reveal_deck'},
    'return_deck': {'return_deck','return_fusion_materials','shuffle','place_deck'},
    'effect_grant': {'effect_grant','effect_copy'},
    'pay_lp': {'pay_lp','lp_payment'},
    'reorder_deck': {'reorder_deck','return_deck','place_deck'},
    'unaffected': {'unaffected','effect_exemption'},
    'damage_redirect': {'damage_redirect','recover_lp','damage_change'},
}
REFERENCE_SUFFIX = re.compile(r'^(?:的|过|成功|之际|时|条件|次数|方法|而进行|效果的发动)')
ACTIVATION_END = re.compile(r'(?:才能|可以|则能|即可)(?:把这张卡|把这个效果)?发动(?:这个效果|这张卡|和处理)?(?:\d+次)?(?=$|（|\()')
ACTION_HINTS = re.compile(r'送去墓地|加入手卡|特殊召唤|融合召唤|同调召唤|超量召唤|连接召唤|仪式召唤|破坏|除外|抽|装备|解放|无效|支付|丢弃|指示物|变成|上升|下降|宣言|翻开|确认|攻击|放置|盖放|交换|取除|洗切|胜利|跳过|得到|获得|不能|不受')


def norm(text):
    return '\n'.join(s.strip() for s in (text or '').splitlines()).strip()


def clauses(text):
    masked = re.sub(r'「[^」]*」|『[^』]*』', lambda m:'Q'*len(m[0]), text)
    for match in re.finditer(r'[^。；;，,\r\n●]+',masked):
        raw=text[match.start():match.end()].strip()
        raw=re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩][：:]','',raw).strip()
        if raw:
            stop=min([p for p in (text.find('。',match.end()), text.find('；',match.end()), text.find(';',match.end()), text.find('\n',match.end())) if p>=0] or [len(text)])
            tail=text[match.end():stop]
            yield raw,tail


def related(source, clause):
    source, clause = norm(source), norm(clause)
    # Cost spans commonly stop before "才能发动" and can include the preceding
    # trigger. Compare the printed action core as well as the complete clause.
    # Without this, a recorded cost is falsely treated as missing merely
    # because the review split at a comma and the runtime span did not.
    core = ACTIVATION_END.sub('', clause).rstrip('。；，, ')
    return bool(source and clause and (source in clause or clause in source
                                      or len(core) >= 4 and core in source))


def expected_atoms(clause, tail=''):
    # Keep token names for token recognition; hide all quoted names otherwise.
    masked=re.sub(r'「[^」]*」|『[^』]*』',lambda m:'Q'*len(m[0]),clause)
    # Negated selector descriptions are predicates on selectable cards.
    selector_mask=re.sub(r'不能通常召唤的|不能特殊召唤的|不能破坏的|不能被效果破坏的','选择条件',masked)
    atoms=[]
    activation=ACTIVATION_END.search(masked)
    activation_follows=bool(activation or re.search(r'(?:才能|可以|则能|即可)发动|选择[^。]{0,15}发动',tail)
                            or re.search(r'支付[^。]{0,20}发动$',masked))
    count_clause=bool(re.search(r'(?:1回合|每回合|决斗中)[^。]{0,20}(?:只能|只有|各能)|1回合只能有1次',re.sub(r'（[^（）]*）|\([^()]*\)','',masked)))
    for kind,pattern in COMPILED:
        body=clause if kind=='token' else masked
        for match in pattern.finditer(body):
            suffix=body[match.end():]
            prefix=body[:match.start()]
            role='effect'
            if kind not in {'battle_protection','effect_protection','unaffected','activation_permission','effect_grant','name_change','destruction_replace','negate_summon'}:
                if REFERENCE_SUFFIX.match(suffix):role='reference'
                elif re.search(r'(?:场合|时|之际)(?:发动|才能发动|可以发动)?$',body):role='condition'
                elif re.search(r'不能|不会|无法|不受|不是.+?不能',selector_mask[:match.start()]):role='restriction'
                elif body.startswith('每次') and not re.search(r'让|给与|给予|再',body[:match.start()]):role='condition'
            if count_clause and kind in {'special_summon','normal_summon','fusion_summon','ritual_summon','synchro_summon','xyz_summon','link_summon'}:
                role='count_reference'
            if kind in {'special_summon','fusion_summon','ritual_summon','synchro_summon','xyz_summon','link_summon'} and re.search(r'(?:用[^。]+的效果|用融合召唤|不用融合召唤|不用仪式召唤).*(?:才能|不能)(?:从额外卡组)?特殊召唤',body):
                role='summon_condition'
            if kind in {'special_summon','fusion_summon','ritual_summon','synchro_summon','xyz_summon','link_summon'}:
                if re.match(r'^(?:无效|之际|状态|中|区|怪兽|不能使用|不能进行)',suffix):role='reference'
                if re.search(r'(?:当作|作为)(?:融合|仪式|同调|超量|连接)召唤',body) and kind=='special_summon':
                    role='summon_method_detail'
                if kind!='special_summon' and '特殊召唤' in body and re.search(r'才能|不能|不用|若非',body):role='summon_condition'
                if re.search(r'(?:的效果|用卡的效果)才能特殊召唤',body):role='summon_condition'
                if kind=='special_summon' and re.search(r'才能(?:从[^。]{0,15})?特殊召唤',body):
                    role='summon_procedure' if re.search(r'把|将|让',body) and re.search(r'除外|送去墓地|解放|回到|返回',body) else 'summon_condition'
            if re.search(r'被[^。]{0,30}(?:破坏|送去墓地)[^。]{0,35}(?:回合|阶段|发动)',body) and kind in {'destroy','send_grave'}:role='condition'
            if kind=='negate_summon' and match[0]=='那个无效':role='context_needed'
            if kind=='level' and re.search(r'攻击力|守备力',prefix) and not re.search(r'等级[^。]{0,15}(?:变成|变为|上升|下降)',body):role='reference'
            if kind=='damage' and ('战斗伤害' in match[0] or '攻击力超过' in body):role='reference'
            if kind=='end_phase' and re.search(r'直到|下次|的结束阶段|的战斗阶段结束时',prefix):role='condition'
            if role=='condition' and body.startswith('每次') and kind in {'counter','damage','lp_loss'} and not REFERENCE_SUFFIX.match(suffix):role='effect'
            if kind=='counter' and (re.match(r'^的',suffix) or re.search(r'放置有|每放置|可以放置.+的',body) and not re.search(r'给.+放置',body)):
                role='reference'
            if kind=='counter' and re.search(r'放置的[^。]{0,25}指示物|放置[^。]{0,25}指示物(?:数量|每有)',body):role='reference'
            if activation_follows and (not activation or match.start()<activation.start()) and kind in {
                    'send_grave','banish','release','discard','detach','pay_lp','reveal','return_hand','return_deck','remove_counter'}:
                if role not in {'reference','restriction','condition'}:role='cost'
            if re.search(r'被(?:效果)?(?:送去墓地|丢弃)',body) and kind in {'send_grave','discard'}:role='condition'
            if kind=='name_change' and '规则上' in body:role='rule_identity'
            if kind=='release' and re.search(r'不用|不需要|不必|作为\d+只(?:的数量)?解放|作为\d+只的数量解放|代替.*解放|解放作上级召唤|不解放',body):role='material_permission'
            if kind=='attach' and re.match(r'^(?:取除|除去)',suffix):role='reference'
            if kind=='inspect' and re.search(r'给对方观看|给双方确认|给人观看|向对方展示',body):role='reference'
            if kind=='banish' and re.match(r'^(?:状态|中|的)',suffix):role='reference'
            if kind in {'discard','banish','release','detach','send_grave'} and re.match(r'^(?:数量|数目|的数量|的数目)',suffix):role='reference'
            if kind=='declare' and activation:role='activation_parameter'
            if kind=='race_change' and '变成通常怪兽' in body:role='summoned_monster_identity'
            if kind in {'race_change','attribute_change'} and re.search(r'变成(?:效果|通常)怪兽|(?:同|相同)(?:种族|属性)',body) and '特殊召唤' in body:role='summoned_monster_identity'
            if kind=='race_change' and re.search(r'种族是\d+种类以上|种族[^。]{0,20}为止必须送去墓地',body):role='reference'
            if kind=='name_change' and '卡名不同' in body:role='reference'
            if kind=='stats' and re.search(r'为对象|持有[^。]{0,25}攻击力|攻击力的[^。]{0,20}为对象',body) and not re.search(r'变成|变为|成为|上升|下降|增加|交换',body):role='reference'
            if kind=='activation_permission' and re.search(r'不能从手卡发动|不能在盖放的回合发动',body):role='restriction'
            if kind=='negate_activation' and re.search(r'让这张卡的发动无效',body) and not re.search(r'才能发动',body):role='condition'
            if kind in {'battle_protection','effect_protection','unaffected','response_lock'}:role='continuous_permission'
            if kind=='effect_target' and '攻击对象' in body:role='attack_target_detail'
            if kind in {'release','send_grave'} and re.search(r'被[^。]{0,15}(?:解放|送去墓地)',body):role='condition'
            atoms.append(dict(kind=kind,role=role,phrase=match[0]))
    # Multiple patterns can describe the same coarse function; preserve role.
    return list({(a['kind'],a['role']):a for a in atoms}.values())


def review_group(text, effects, extra=()):
    actual=[(section,b) for e in effects for section in ('blocks','cost_blocks','procedure_blocks','restrictions','description_blocks') for b in e[section]]
    actual+=list(extra)
    results=[]
    for clause,tail in clauses(text):
        atoms=expected_atoms(clause,tail)
        relevant=[(section,b) for section,b in actual if related(b.get('source',''),clause)]
        rows=[]
        for atom in atoms:
            kind,role=atom['kind'],atom['role']
            accepted=EQUIVALENT.get(kind,{kind})
            if role=='restriction':
                represented=any(section in {'restrictions','card_restrictions','count_limits','description_blocks'} for section,b in relevant)
                state='matched_restriction' if represented else 'pending_missing_restriction'
            elif role in {'reference','condition','summon_method_detail','rule_identity','context_needed','material_permission','summon_condition','count_reference','activation_parameter','summoned_monster_identity','attack_target_detail'}:
                state='non_processing_reference' if role!='context_needed' else 'pending_context'
            else:
                sections={'cost_blocks','record_costs'} if role=='cost' else {'blocks','procedure_blocks'}
                if role=='continuous_permission':sections|={'restrictions','card_restrictions'}
                if kind=='response_lock':accepted=accepted|{'cannot_activate'}
                if kind=='pay_lp':sections|={'cost_blocks','record_costs','non_activation_costs'}
                if role=='cost' and kind=='discard':accepted=accepted|{'send_grave'}
                # Existing broad operations may already cover a more specific
                # label. Require the same printed clause, not a card-wide hit.
                if kind=='type_change' and re.search(r'当作装备|变成装备',clause):accepted=accepted|{'equip'}
                if kind=='type_change' and '特殊召唤' in clause:accepted=accepted|{'special_summon'}
                found=[b['kind'] for section,b in relevant if section in sections and b.get('kind') in accepted]
                state='matched' if found else 'pending_missing_or_role_mismatch'
            rows.append(dict(**atom,state=state))
        if not atoms:
            if relevant:state='represented_by_other_coarse_function'
            elif not ACTION_HINTS.search(re.sub(r'「[^」]*」|『[^』]*』','',clause)):state='non_function_text'
            elif re.search(r'(?:场合|之际|时|存在|发动|伤害步骤内|战斗步骤内)$|表示：1回合1次',clause):state='condition_or_timing'
            elif re.search(r'不能|不会|不受|不必|不用|不需要|最多|至多|只能|必须|必需|才能装备',clause):state='restriction_or_permission_text'
            else:state='pending_unclassified_clause'
        else:state='checked_atoms'
        results.append(dict(source=clause,state=state,atoms=rows,
                            actual=[dict(section=section,kind=b.get('kind',section),source=b.get('source',''),
                                         qualifiers=b.get('qualifiers',{})) for section,b in relevant]))
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baige',type=Path,required=True)
    p.add_argument('--live',type=Path,required=True)
    p.add_argument('--aliases',type=Path,required=True)
    p.add_argument('--candidates',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    raw=json.loads(args.baige.read_text(encoding='utf-8'))
    entries={}
    with gzip.open(args.live,'rt',encoding='utf-8') as stream:
        for line in stream:
            e=json.loads(line);entries[e['card_id']]=e
    with args.aliases.open(encoding='utf-8') as stream:
        for line in stream:
            e=json.loads(line);entries[e['card_id']]=e
    candidates=defaultdict(list)
    for line in args.candidates.read_text(encoding='utf-8').splitlines():
        f=json.loads(line);candidates[f['card_id']].append(f)
    totals=Counter();pending_patterns=Counter();pattern_examples={}
    with (args.output/'per-card.jsonl').open('w',encoding='utf-8') as out:
        for cid,card in raw.items():
            code=card['id'];entry=entries.get(code)
            result=dict(cid=int(cid),card_id=code,name=card.get('cn_name') or card.get('jp_name'),groups=[],
                        previous_candidates=candidates.get(code,[]),semantic_review_type='offline_clause_comparison')
            if code<=0 or not card.get('data'):result['status']='source_metadata_only'
            elif entry is None:result['status']='missing_runtime_card_entry'
            else:
                for scope,source in (('pendulum',card['text'].get('pdesc','')),('monster' if card['data']['type']&1 else 'spell_trap',card['text'].get('desc',''))):
                    if not source:continue
                    effects=[e for e in entry['effects'] if e['scope']==scope]
                    extra=[('card_restrictions',r) for r in entry.get('card_restrictions',[])]
                    extra.extend(('count_limits',limit) for e in effects for limit in e['count_limits'])
                    extra.extend(('record_costs',payment) for r in entry['source_records'] if r['scope']==scope for field in ('costs','shared_costs') for payment in r.get(field,[]))
                    extra.extend(('non_activation_costs',payment) for r in entry['source_records'] if r['scope']==scope for payment in r.get('non_activation_costs',[]))
                    checks=review_group(source,effects,extra)
                    if scope=='monster' and card['data']['type']&0x10 and not card['data']['type']&0x20:
                        checks=[dict(source=source,state='non_effect_monster_description',atoms=[],actual=[])]
                    result['groups'].append(dict(scope=scope,clauses=checks))
                    for c in checks:
                        totals['clauses']+=1
                        for a in c['atoms']:totals['atom_'+a['state']]+=1
                        if c['state'].startswith('pending') or any(a['state'].startswith('pending') for a in c['atoms']):
                            key=re.sub(r'「[^」]*」|『[^』]*』','「X」',c['source'])
                            key=re.sub(r'\d+','N',key)
                            pending_patterns[key]+=1
                            pattern_examples.setdefault(key,dict(card_id=code,name=result['name'],scope=scope,clause=c))
                pending=sum(c['state'].startswith('pending') or any(a['state'].startswith('pending') for a in c['atoms'])
                            for g in result['groups'] for c in g['clauses'])
                result['pending_clauses']=pending
                result['status']='pending_semantic_review' if pending else 'no_discrepancy_in_reviewed_coarse_predicates'
            totals['cards_'+result['status']]+=1
            out.write(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
    patterns=[dict(template=k,count=n,example=pattern_examples[k]) for k,n in pending_patterns.most_common()]
    (args.output/'pending-patterns.json').write_text(json.dumps(patterns,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary=dict(totals=totals,unique_pending_patterns=len(patterns),all_source_rows_visited=sum(n for k,n in totals.items() if k.startswith('cards_'))==len(raw),full_semantic_review_complete=False)
    (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
