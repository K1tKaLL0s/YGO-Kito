"""Scoped count observations; this module does not maintain engine counters.

Only matched wording/scope selects a reviewed negation policy. In particular,
activation is not a universal refund rule. Unsupported limits remain unknown.
"""
import re

FAQ = 'https://www.db.yugioh-card.com/yugiohdb/faq_search.action?ope=5&request_locale=ja&fid='
USE_SOURCES = tuple(FAQ+str(n) for n in (17200,17377,17376))
TRAP_SOURCE = FAQ+'22010'
GLOBAL_SOURCE = FAQ+'7813'
SPECIFIC_ACTIVATION_SOURCE = FAQ+'23158'
INDICES = '①②③④⑤⑥⑦⑧⑨⑩'


def _record(source, maximum, scope, event, *, effects=(), controller='self',
            activation_negated='unknown', effect_negated='unknown', citations=(),
            duration='turn', condition='applicable_effect', status='known'):
    return {'status':status,'scope':scope,'subject':{'kind':scope,'controller':controller,
            'effect_indices':list(effects)},'maximum':maximum,'period':'turn',
            'reset_scope':'each_turn','applies_until':duration,'condition':condition,
            'count_event':event,'source':source,
            'negation_policy':{'activation_negated':activation_negated,
                'effect_negated':effect_negated,'resolution_not_applied':effect_negated},
            'rule_sources':list(citations),'scope_match_required':True}


def _count_clauses(prelude):
    clauses=[]
    for sentence in re.split(r'[。\n]',prelude):
        subject=None
        for part in re.split(r'[，,]',sentence):
            named=re.match(r'(这个卡名|这张卡)',part.strip())
            if named:subject=named[1]
            elif subject and re.match(r'[①②③④⑤⑥⑦⑧⑨⑩]',part.strip()):part=subject+'的'+part.strip()
            clauses.append(part)
    return [part.strip().translate(str.maketrans('０１２３４５６７８９','0123456789')) for part in clauses]


def parse_count_limits(index, prelude, effect_text, *, section=None):
    records=[]
    # Full source clauses, not a search for the word "use".
    for sentence in _count_clauses(prelude):
        sentence=sentence.strip().translate(str.maketrans('０１２３４５６７８９','0123456789'))
        section_limit = re.fullmatch(r'这个卡名的(灵摆|怪兽)效果1回合只能使用(\d+)次', sentence)
        if section_limit:
            if section == {'灵摆':'pendulum', '怪兽':'monster'}[section_limit[1]]:
                limit = _record(sentence, int(section_limit[2]), 'same_name_all_effects', 'use',
                    activation_negated='counts', effect_negated='counts', citations=USE_SOURCES)
                limit['subject']['section'] = section
                records.append(limit)
            continue
        method=re.fullmatch(r'(这个卡名|这张卡)的([①②③④⑤⑥⑦⑧⑨⑩]+)的方法的特殊召唤1回合只能有(\d+)次',sentence)
        if method:
            indices=tuple(INDICES.index(c)+1 for c in method[2])
            if index in indices:
                records.append(_record(sentence,int(method[3]),'same_name_summon_method' if method[1]=='这个卡名' else 'this_card_summon_method',
                    'special_summon_method',effects=indices,condition='this_summon_method'))
            continue
        use=re.fullmatch(r'(这个卡名|这张卡)的([①②③④⑤⑥⑦⑧⑨⑩]*)(?:的)?效果1回合'
            r'(各能使用(\d+)次|可以使用最多(\d+)次|最多能使用(\d+)次|只能使用(\d+)次|只能有(\d+)次使用其中任意1个)',sentence)
        if use:
            indices=tuple(INDICES.index(c)+1 for c in use[2])
            if indices and index not in indices:continue
            maximum=int(next(v for v in use.groups()[3:] if v is not None))
            shared='其中任意' in use[3]
            scope=('same_name_shared_effects' if shared else 'same_name_this_effect' if indices else 'same_name_all_effects') if use[1]=='这个卡名' else 'this_card_effect'
            records.append(_record(sentence,maximum,scope,'use',effects=indices if shared else (index,),
                activation_negated='counts',effect_negated='counts',citations=USE_SOURCES))
            continue
        # The direct named-card activation negation ruling is not yet reviewed.
        activation=re.fullmatch(r'(这个卡名的卡|这张卡)(?:在)?1回合只能发动(\d+)张',sentence)
        if activation:
            records.append(_record(sentence,int(activation[2]),
                'same_name_card' if activation[1]=='这个卡名的卡' else 'this_card', 'card_activation'))

    text=effect_text.translate(str.maketrans('０１２３４５６７８９','0123456789'))
    per_effect = re.match(r'1回合(\d+)次[，,]', text)
    if per_effect:
        records.append(_record(per_effect[0].rstrip('，,'), int(per_effect[1]),
            'this_card_effect', 'effect_activation', effects=(index,)))
    trap=re.search(r'(?:这张卡的?发动后[，,]直到回合结束时[，,]?自己只能有1次把陷阱卡发动|'
        r'このカードの発動後、ターン終了時まで自分は罠カードを1枚しか発動できない)',text)
    if trap:
        records.append(_record(trap[0],1,'player_trap_card_activations','card_activation',effects=(index,),
            activation_negated='does_not_count',effect_negated='counts',citations=(TRAP_SOURCE,),
            duration='end_of_current_turn',condition='after_this_effect_applies'))
    global_limit=re.search(r'(?:只要这张卡在怪兽区域存在[，,]那个期间双方在1回合只能有1次把怪兽的效果发动|'
        r'このカードがモンスターゾーンに存在する限り、その間はお互いに、それぞれ1ターンに1度しかモンスターの効果を発動でき(?:ず|ない))',text)
    if global_limit:
        records.append(_record(global_limit[0],1,'each_player_monster_effects','effect_activation',effects=(index,),controller='both_separately',
            activation_negated='counts',effect_negated='counts',citations=(GLOBAL_SOURCE,),
            duration='while_this_card_in_monster_zone',condition='continuous_effect_applies'))
    # Other activation restrictions (including race exclusions / next-turn
    # durations) need a matching rule. Never derive a refund from 発動/发动 alone.
    recognized=[r['source'] for r in records]
    for sentence in re.split(r'[。\n]',text):
        if ('发动' in sentence or '発動' in sentence) and ('只能' in sentence or 'しか' in sentence) and not any(s in sentence for s in recognized):
            records.append(_record(sentence,None,'unknown','unknown',status='unknown',
                duration='unknown',condition='unknown'))
    return tuple(records)


def negation_counting(limit, outcome):
    """Return an observation for one *already scope-matched* engine event.

    Callers retain the real engine's counter/legality authority. An unknown
    policy must not be converted into a refund or a negative training label.
    """
    if limit.get('status')!='known' or outcome not in ('activation_negated','effect_negated','resolution_not_applied','applied'):
        return 'unknown'
    if outcome=='applied':return 'counts'
    return limit.get('negation_policy',{}).get(outcome,'unknown')
