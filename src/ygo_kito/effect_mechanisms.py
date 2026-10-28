"""Bounded, source-bound card-text semantics for construction, not a rules engine.

Recognition is by effect clauses, never by card ID or archetype. Unsupported
clauses stay visible. Positive observations may guide recall; neither a missing
observation nor a successful recall establishes an unrestricted/legal combo.
"""
from dataclasses import asdict, dataclass
import re

from .build_contracts import digest
from .effect_count_limits import parse_count_limits

SEMANTIC_VERSION = "public-effect-clauses-v2"
MECHANISM_WIDTH = 18
EXTRA_TYPES = 0x40 | 0x2000 | 0x800000 | 0x4000000
RACES = {"战士族": 1, "魔法师族": 2, "天使族": 4, "恶魔族": 8,
         "不死族": 16, "机械族": 32, "水族": 64, "炎族": 128,
         "岩石族": 256, "鸟兽族": 512, "植物族": 0x400, "昆虫族": 0x800, "龙族": 0x2000,
         "雷族": 0x1000, "兽族": 0x4000, "兽战士族": 0x8000, "恐龙族": 0x10000,
         "鱼族": 0x20000, "海龙族": 0x40000, "爬虫类族": 0x80000,
         "念动力族": 0x100000, "幻龙族": 0x800000, "电子界族": 0x1000000}
NUMBERED = re.compile(r"([①②③④⑤⑥⑦⑧⑨⑩])\s*[：:]")
DIGITS = "①②③④⑤⑥⑦⑧⑨⑩"


def _zones(text):
    return tuple(z for word, z in (("手卡", "hand"), ("场上", "field"),
                                  ("墓地", "grave"), ("卡组", "deck"),
                                  ("除外", "banished")) if word in text)


def _restriction_clauses(text):
    result = []
    for sentence in re.split(r"[。\n]", text):
        if "不能作为融合素材" in sentence:
            result.append(dict(kind="cannot_be_fusion_material", scope="this_card",
                               duration="while_applicable", condition="this_card", source=sentence))
        if "不能通常召唤" in sentence:
            if "这张卡不能通常召唤" in sentence and "回合" not in sentence:
                result.append(dict(kind="cannot_normal_summon_this_card",scope="this_card",
                                   duration="intrinsic",condition="this_card",source=sentence))
            else:
                condition = "special_summon_this_card" if "这张卡特殊召唤的回合" in sentence else "effect_use"
                result.append(dict(kind="cannot_normal_summon", scope="player", duration="turn",
                                   condition=condition, whole_turn=True if condition=='special_summon_this_card' else None,
                                   includes_set=True if "盖放" in sentence else None, source=sentence))
        if ("额外卡组" in sentence and "融合" in sentence and "特殊召唤" in sentence
                and ("以外" in sentence or "不是融合" in sentence) and "不能" in sentence):
            result.append(dict(kind="extra_fusion_only", scope="player", duration="turn",
                               condition="effect_use", whole_turn=True if '发动这个效果的回合' in sentence else
                               False if '发动后' in sentence else None, source=sentence))
        if "从场上离开" in sentence and "除外" in sentence:
            result.append(dict(kind="leave_field_banish", scope="this_effect_summoned_card",
                               duration="until_leave_field", condition="summoned_by_this_effect", source=sentence))
    return tuple(result)


def _materials(prelude):
    formula = next((s.strip() for s in prelude.splitlines() if "＋" in s or "+" in s), "")
    if not formula:
        return ()
    result = []
    for part in re.split(r"[＋+]", formula):
        part = part.strip()
        amount = re.search(r"[×x](\d+)", part)
        count = int(amount[1]) if amount else 1
        quoted = re.fullmatch(r"「([^」]+)」(怪兽)?(?:[×x]\d+)?", part)
        race = next((v for k, v in RACES.items() if part == k + "怪兽" + (amount[0] if amount else "")), None)
        if quoted:
            result.append(dict(kind="name_contains" if quoted[2] else "exact_name", value=quoted[1], count=count, source=part))
        elif race:
            result.append(dict(kind="race", value=race, count=count, source=part))
        else:
            return ()  # A partly understood material formula is not certified.
    return tuple(result)


@dataclass(frozen=True)
class EffectSemantics:
    index: int
    text: str
    trigger: dict
    costs: tuple
    targets: tuple
    operations: tuple
    count_limits: tuple
    restrictions: tuple
    knowledge: dict
    unknown: tuple

    @property
    def kinds(self):
        return {o["kind"] for o in self.observed_operations}

    @property
    def observed_operations(self):
        return tuple(o for o in self.operations if o.get('reason')=='effect')

    @property
    def conditions_known(self):
        return (self.knowledge.get('activation_boundary')=='recognized' and
                self.trigger.get('additional_conditions')=='none_in_recognized_activation_clause')

    @property
    def route_ready(self):
        # Count-negation details do not establish an opening. Activation,
        # payment, targeting and unresolved resolution conditions do matter.
        return (self.conditions_known and not self.costs and not self.targets and
                'unparsed_resolution_or_restriction' not in self.unknown)

    @property
    def count_limit(self):
        """Compatibility accessor; all scopes are retained in count_limits."""
        return self.count_limits[0] if self.count_limits else {'status':'unknown'}


@dataclass(frozen=True)
class CardSemantics:
    card_id: int
    cards_sha256: str
    text_sha256: str
    effects: tuple
    restrictions: tuple
    materials: tuple
    unknown: tuple

    def to_dict(self):
        return {"semantic_version": SEMANTIC_VERSION, **asdict(self)}

    @property
    def kinds(self):
        return {kind for effect in self.effects for kind in effect.kinds}

    @property
    def grave_fusion(self):
        return tuple(e for e in self.effects if e.trigger.get("event") == "sent_to_grave"
                     and e.trigger.get("reason") == "effect" and e.conditions_known and "fusion_summon" in e.kinds
                     and "return_fusion_materials" in e.kinds)

    @property
    def tags(self):
        result = []
        if any(o["kind"] in ("mill", "send_grave") and o.get("from_zones") == ("deck",)
               and o.get("reason") == "effect" for e in self.effects for o in e.observed_operations):
            result.append("卡组送墓")
        if self.grave_fusion:
            result.append("墓地融合")
        return tuple(result)


def _effect(index, text, prelude):
    marker=re.search(r'(?:才能|可以)发动',text)
    activation=(re.compile(r"(?:才能|可以)发动(?:（[^（）]*）|\([^()]*\))*[。；]").match(text,marker.start())
                if marker else None)
    head, body = (text[:activation.start()], text[activation.end():]) if activation else ("", text)
    annotation=activation[0].split('发动',1)[1][:-1] if activation else ''
    trigger = {"event": "unknown", "reason": "unknown", "source": head,
               "additional_conditions": "unknown",'activation_annotation':annotation}
    if "被效果送去墓地" in head:
        trigger.update(event="sent_to_grave", reason="effect", zone="grave")
    elif "召唤·特殊召唤成功" in head:
        trigger.update(event="normal_or_special_summon", reason="not_applicable", zone="field")
    elif "特殊召唤成功" in head:
        trigger.update(event="special_summon", reason="not_applicable", zone="field")
    elif "自己主要阶段" in head:
        trigger.update(event="own_main_phase", reason="not_applicable")
    elif "对方" in head and "怪兽" in head and "效果发动时" in head:
        trigger.update(event="opponent_monster_effect", reason="not_applicable")
    if not annotation and head in ("这张卡被效果送去墓地的场合", "这张卡召唤·特殊召唤成功的场合",
                                   "这张卡特殊召唤成功的场合", "自己主要阶段"):
        trigger["additional_conditions"] = "none_in_recognized_activation_clause"
    costs, targets, operations = [], [], []
    # Only pre-activation payment is cost. Sending during resolution is effect.
    if head and trigger["event"] != "sent_to_grave":
        payment = re.search(r"(?:丢弃|舍弃|从手卡|从(?:自己(?:的)?)?卡组|把|将)[^。]{0,100}(?:手卡|送去墓地|除外|解放)", head)
        if payment and not ("为对象" in payment[0] or "场合" in payment[0] or "成功" in payment[0]):
            amount=re.search(r'(\d+)[只张]',payment[0])
            origin=payment[0].split('送去墓地',1)[0]
            costs.append(dict(kind="send_grave" if any(w in payment[0] for w in ("丢弃", "舍弃", "送去墓地")) else "payment",
                              reason="cost", from_zones=_zones(origin), source=payment[0],quantity=int(amount[1]) if amount else None))
    target = re.search(r"以(.+?)为对象", head)
    if target:
        amount = re.search(r"(\d+)[只张]", target[1])
        targets.append(dict(kind="target", selector=target[1], zones=_zones(target[1]),
                            quantity=int(amount[1]) if amount else None, source=target[0]))

    def operation(kind, match, **values):
        prefix=body[:match.start()].rsplit("。",1)[-1]
        if re.search(r"不能|无法|不会", prefix):return
        amount=re.search(r"(\d+)[只张]",match[0]) if kind!='return_fusion_materials' else None
        operations.append(dict(kind=kind, reason="effect" if activation else "unknown",
                               source=match[0], order=match.start(), **values))
        operations[-1]["quantity"]=int(amount[1]) if amount else None
        clause=body[:match.end()].rsplit('。',1)[-1]
        operations[-1]['owner']='opponent' if '对方' in clause else 'both' if '双方' in clause else 'self'

    fusion = re.search(r"融合怪兽卡决定的.*?融合素材怪兽从自己的(.*?)回到持有者卡组下面.*?从额外卡组融合召唤", body)
    if fusion:
        operation("return_fusion_materials", fusion, from_zones=_zones(fusion[1]), to_zone="deck_bottom",
                  requires_this_grave_card="包含墓地的这张卡" in fusion[0])
        operation("fusion_summon", fusion, from_zones=("extra",), to_zone="field")
    else:
        # An adjectival "fusion-summoned card" is not an instruction to summon.
        perform = re.search(r"(?:把|将)[^。；]*?融合召唤(?!的|过的)|"
            r"从额外卡组(?:把|将)?[^。；]*?融合召唤(?!的|过的)|"
            r"融合召唤[0-9一二三四五六七八九十]+只[^。；]*", body)
        if perform:
            operation("fusion_summon", perform, from_zones=("extra",), to_zone="field", materials="unknown")
    for m in re.finditer(r"从(?:自己|对方)?(?:的)?卡组(?:上面|顶端)(?:把|将)?[0-9一二三四五六七八九十]+张卡送去墓地", body):
        operation("mill", m, from_zones=("deck",), to_zone="grave", random=True)
    for m in re.finditer(r"从(?:自己)?(?:的)?卡组[^。]{0,150}送去墓地", body):
        if "上面" not in m[0] and "顶端" not in m[0]:
            operation("send_grave", m, from_zones=("deck",), to_zone="grave", selector=m[0], random=False)
    for m in re.finditer(r"从自己(?:的)?手卡[^。]{0,70}送去墓地", body):
        operation("send_grave", m, from_zones=("hand",), to_zone="grave", selector=m[0])
    for m in re.finditer(r"(?:丢弃|舍弃)[^。]{0,35}手卡", body):
        operation("send_grave", m, from_zones=("hand",), to_zone="grave")
    for m in re.finditer(r"从(?:自己)?(?:的)?(?:卡组|墓地)[^。]{0,100}加入手卡", body):
        operation("search_or_recover", m, from_zones=_zones(m[0]), to_zone="hand", selector=m[0])
    for m in re.finditer(r"(?:抽|抽出)[0-9一二三四五六七八九十]+张", body):
        operation("draw", m, from_zones=("deck",), to_zone="hand")
    if "特殊召唤" in body and not fusion:
        m = re.search(r"[^。]*特殊召唤[^。]*", body)
        operation("special_summon", m, from_zones=_zones(m[0]), to_zone="field")
    for kind, word in (("negate", "无效"), ("destroy", "破坏")):
        for m in re.finditer(r"[^。]*(?:" + word + r")[^。]*", body):
            if "不会被" not in m[0] and "不能" not in m[0]:
                operation(kind, m)
    restrictions = _restriction_clauses(text)
    counts = parse_count_limits(index,prelude,text)
    unknown = []
    if not activation:unknown.append('activation_boundary')
    if annotation:unknown.append('activation_annotation')
    if trigger["event"] == "unknown": unknown.append("activation_condition")
    if trigger["additional_conditions"] == "unknown": unknown.append("additional_activation_conditions")
    if not counts or any(c['status']=='unknown' for c in counts): unknown.append("count_limit")
    if any('unknown' in c.get('negation_policy',{}).values() for c in counts):unknown.append('count_negation_policy')
    if not operations: unknown.append("resolution")
    # Preserve any unresolved clause rather than interpreting absence as no lock.
    remaining = body
    for op in operations: remaining = remaining.replace(op["source"], "")
    for restriction in restrictions: remaining = remaining.replace(restriction["source"], "")
    if re.search(r"[\u4e00-\u9fff]", remaining): unknown.append("unparsed_resolution_or_restriction")
    if head and trigger["event"] == "unknown" and not costs and not targets: unknown.append("cost_or_condition")
    activation_known=trigger["additional_conditions"]!="unknown"
    knowledge={"activation_boundary":"recognized" if activation else "unknown",
               "costs":"observed" if costs else "not_observed_in_recognized_activation" if activation_known else "unknown",
               "targets":"observed" if targets else "not_observed_in_recognized_activation" if activation_known else "unknown",
               "restrictions":"observed" if restrictions else "not_observed_in_recognized_effect" if activation_known and not re.search(r"[\u4e00-\u9fff]",remaining) else "unknown"}
    return EffectSemantics(index, text, trigger, tuple(costs), tuple(targets),
                           tuple(sorted(operations, key=lambda o:o["order"])), counts, restrictions, knowledge, tuple(unknown))


def analyze_card(row, cards_sha256=""):
    desc = row.get("desc") or ""
    boundaries = list(NUMBERED.finditer(desc))
    prelude = desc[:boundaries[0].start()] if boundaries else desc
    effects = tuple(_effect(DIGITS.index(m[1])+1, desc[m.end():boundaries[i+1].start() if i+1<len(boundaries) else None].strip(), prelude)
                    for i,m in enumerate(boundaries))
    if not boundaries:
        effects = (_effect(0, desc, ""),)
    return CardSemantics(row["id"], cards_sha256, digest(desc), effects, _restriction_clauses(prelude),
                         _materials(prelude) if row.get("type",0)&0x40 else (),
                         ("unnumbered_effect_boundaries",) if not boundaries else ())


def material_matches(row, requirement):
    if requirement["kind"] == "race": return bool(row.get("race",0) & requirement["value"])
    if requirement["kind"] == "exact_name": return row.get("name") == requirement["value"]
    return requirement["value"] in row.get("name", "")


def fit_materials(rows, requirements):
    slots = [r for r in requirements for _ in range(r["count"])]
    if len(rows) != len(slots): return False
    def assign(rest, pending):
        if not pending:return True
        return any(material_matches(row,pending[0]) and assign(rest[:i]+rest[i+1:],pending[1:]) for i,row in enumerate(rest))
    return assign(list(rows),slots)


class MechanismCatalog:
    def __init__(self, assets, available_ids=None):
        self.assets = assets
        self.cards_sha256 = getattr(assets,'receipt',{}).get("resources",{}).get("cards", "")
        self.ids = tuple(assets.rows if available_ids is None else available_ids)
        self._profiles = {}
        self._texts = {}

    def card(self, code):
        row = self.assets.rows[code]
        cached = self._profiles.get(code)
        text=row.get('desc') or ''
        if cached is None or self._texts.get(code) != text:
            cached = self._profiles[code] = analyze_card(row, self.cards_sha256)
            self._texts[code]=text
        return cached

    def summarize(self, core_ids):
        ids = tuple(core_ids)
        profiles = [self.card(c) for c in ids]
        effects = [e for p in profiles for e in p.effects]
        grave = sum(e.trigger.get("event")=="sent_to_grave" and e.trigger.get("reason")=="effect" and e.conditions_known for e in effects)
        fusion = sum("fusion_summon" in e.kinds for e in effects)
        scoped=[{"card_id":p.card_id,"effect_index":e.index} for p in profiles for e in p.effects
                if e.knowledge['restrictions']=='not_observed_in_recognized_effect']
        unknown_scopes=[{"card_id":p.card_id,"effect_index":e.index} for p in profiles for e in p.effects
                        if e.knowledge['restrictions']=='unknown']
        restrictions=[r for p in profiles for r in (*p.restrictions,*(r for e in p.effects for r in e.restrictions))]
        player_locks=[r for r in restrictions if r['scope']=='player']
        return {"semantic_version": SEMANTIC_VERSION, "core_ids": list(ids),
                "grave_effect_triggers": grave, "fusion_effects": fusion,
                "core_summon_mechanisms": ["fusion"] if fusion else [],
                "resource_returns": sum("return_fusion_materials" in e.kinds or "search_or_recover" in e.kinds for e in effects),
                "observed_restrictions": restrictions,
                "summon_lock_assessment":{'status':'observed_scoped_locks' if player_locks else
                    'no_player_summon_lock_in_listed_effects' if scoped else 'unknown',
                    'reviewed_effects':scoped,'unreviewed_effects':unknown_scopes,'observed_player_locks':player_locks,
                    'scope':'only the listed effects; never the entire deck'},
                "resource_flows":[{'card_id':p.card_id,'effect_index':e.index,**o} for p in profiles for e in p.effects
                    for o in e.observed_operations if o['kind'] in ('return_fusion_materials','search_or_recover')],
                "unparsed_effect_count": sum(bool(e.unknown) for e in effects),
                "global_no_summon_restriction": None,
                "restriction_scope": "only explicit per-card/per-effect observations; absence is unknown",
                "evidence": [{"card_id":p.card_id,"text_sha256":p.text_sha256,
                    "effect_indices":[e.index for e in p.effects]} for p in profiles], "learned_inference": False}

    def support(self, code, summary):
        p = self.card(code); row = self.assets.rows[code]
        core = summary["core_ids"]
        reasons=[];score=0
        if code in core: return 100, ("declared_theme_fact",)
        if summary["grave_effect_triggers"] and any(o['kind'] in ('mill','send_grave') and
                o.get('from_zones')==('deck',) and o.get('owner')=='self' for e in p.effects for o in e.observed_operations):
            score+=8;reasons.append("effect_deck_to_grave_feeds_core_triggers")
        if summary["fusion_effects"] and "fusion_summon" in p.kinds:
            score+=4;reasons.append("fusion_enabler_requires_material_check")
        if row.get("type",0)&0x40 and p.materials:
            monsters=[self.assets.rows[c] for c in core if self.assets.rows[c]["type"]&1 and not self.assets.rows[c]["type"]&EXTRA_TYPES]
            # Repeated copies are only proposals; listing limits/core validate them.
            if all(any(material_matches(m,r) for m in monsters) for r in p.materials):
                score+=5;reasons.append("fusion_material_predicates_match_core")
        if row.get('type',0)&1 and not row['type']&EXTRA_TYPES and summary['fusion_effects']:
            if any(material_matches(row,r) for c in core for r in self.card(c).materials):
                score+=2;reasons.append('public_fusion_material_predicate_match')
        if row.get('type',0)&0x800000:
            matches=[c for c in core if self.assets.rows[c]['type']&1 and not self.assets.rows[c]['type']&EXTRA_TYPES
                     and self.assets.rows[c]['level']&255==row['level']&255]
            if len(matches)>=2:score+=1;reasons.append('public_xyz_level_proposal_not_route_proof')
        for e in p.effects:
            for op in e.observed_operations:
                if op["kind"]=="search_or_recover":
                    quoted=re.findall(r"「([^」]+)」",op["source"])
                    if quoted and any(q in self.assets.rows[c]["name"] for q in quoted for c in core):
                        score+=5;reasons.append("search_or_recover_names_core")
        if any(o['kind'] in ('negate','destroy') or o['kind']=='draw' and o.get('owner')=='self'
               for e in p.effects for o in e.observed_operations):
            score+=1;reasons.append("recognized_generic_utility_not_theme_synergy")
        restrictions=[*p.restrictions,*(r for e in p.effects for r in e.restrictions)]
        if any(r["kind"]=="cannot_normal_summon" for r in restrictions):
            score-=4;reasons.append("using_this_card_conflicts_with_normal_summon_starters")
        return score,tuple(dict.fromkeys(reasons))

    def _normal_hand_opening(self, code):
        """Known ordinary, tribute-free normal access; no assumed special route."""
        row=self.assets.rows[code]
        if (not row['type']&1 or row['type']&(EXTRA_TYPES|0x80|0x2000000)
                or not 1<=row['level']&255<=4):
            return False
        profile=self.card(code)
        if any(r['kind']=='cannot_normal_summon_this_card' for r in profile.restrictions):
            return False
        prelude=NUMBERED.split(row.get('desc') or '',maxsplit=1)[0]
        # Unparsed normal-summon conditions must not become a one-card opening.
        return not any(term in prelude for term in ('通常召唤','不能召唤','才能召唤','召唤条件','必须解放'))

    def fusion_goals(self, pool, core_ids, limit=4):
        """Propose a nonrandom summon→effect-send→grave-fusion opening from text.

        A proposal is conditional and still needs the existing basic core check.
        Unsupported materials/conditions do not become guessed openings.
        """
        goals=[];allowed=frozenset(pool)
        enablers=[(c,e) for c in pool for e in self.card(c).grave_fusion if e.route_ready]
        starters=[(c,e) for c in pool if self._normal_hand_opening(c) for e in self.card(c).effects
                  if e.trigger.get('event')=='normal_or_special_summon' and e.route_ready and
                  any(o['kind']=='send_grave' and o.get('from_zones')==('deck',) and
                      o.get('owner')=='self' for o in e.observed_operations)]
        for target in core_ids:
            if target not in allowed:continue
            target_profile=self.card(target)
            if not target_profile.materials:continue
            for starter,starter_effect in starters:
                for enabler,effect in enablers:
                    if starter==enabler:continue
                    if any(r['kind']=='cannot_be_fusion_material' for c in (starter,enabler) for r in self.card(c).restrictions):continue
                    sends=[o for o in starter_effect.observed_operations if o['kind']=='send_grave' and
                           o.get('from_zones')==('deck',) and o.get('owner')=='self']
                    def eligible(op):
                        names=re.findall(r"「([^」]+)」",op["source"])
                        excluded=re.findall(r"「([^」]+)」以外",op["source"])
                        return bool(names) and any(n in self.assets.rows[enabler]["name"] for n in names if n not in excluded) and self.assets.rows[enabler]["name"] not in excluded
                    if not any(eligible(o) for o in sends):continue
                    if not fit_materials([self.assets.rows[starter],self.assets.rows[enabler]],target_profile.materials):continue
                    move=next(o for o in effect.observed_operations if o["kind"]=="return_fusion_materials")
                    if not move.get("requires_this_grave_card"):continue
                    quote=effect.text
                    goals.append({"kind":"fusion_summon","card_id":target,
                        "starting_conditions":{"player":0,"turn":1,"requires_opening_hand":[starter]},
                        "fusion_witness":{"effect_assessments":[{"card_id":enabler,"tag":{"dimension":"effect_type","value":"fusion_summon"},
                            "status":"satisfied","cards_sha256":self.cards_sha256,"effect_text_sha256":self.card(enabler).text_sha256,
                            "quote":quote[:512],"source":SEMANTIC_VERSION,"note":"Recognized effect clause; proposed route requires actual core validation."}],
                            "minimum_materials":2,"allowed_destination_zones":[1],"required_source_zones":[16]}})
                    if len(goals)>=limit:return goals
        return goals

    def construction_mechanism_groups(self, pool, core_ids, *, limit=8):
        """Export relationships to the existing construction portfolio seam.

        Three-key packages only; editing and candidate generation remain owned
        by construction_candidates. A group is a proposal, not a legal CB proof.
        """
        groups=[];seen=set();allowed=frozenset(pool)
        core_ids=tuple(c for c in core_ids if c in allowed)
        for goal in self.fusion_goals(pool,core_ids,limit=limit):
            main=list(goal['starting_conditions']['requires_opening_hand'])
            for review in goal['fusion_witness']['effect_assessments']:
                if review['card_id'] not in main:main.append(review['card_id'])
            zones={'main':sorted(main),'extra':[goal['card_id']],'side':[]}
            if any(c not in allowed for cards in zones.values() for c in cards):continue
            identity=digest({'semantic_version':SEMANTIC_VERSION,'cards':self.cards_sha256,'goal':goal})
            if identity in seen:continue
            seen.add(identity)
            groups.append({'group_id':'fusion-'+identity[:20], 'zones':zones,
                           'source':SEMANTIC_VERSION+':'+identity})
        return tuple(groups)

    def vector(self, code, summary=None):
        p=self.card(code);effects=p.effects
        limits=[c for e in effects for c in e.count_limits]
        restrictions=[*p.restrictions,*(r for e in effects for r in e.restrictions)]
        self_mill=any(o['kind'] in ('mill','send_grave') and o.get('from_zones')==('deck',)
                      and o.get('owner')=='self' for e in effects for o in e.observed_operations)
        return [float(self_mill),float(bool(p.grave_fusion)),
                float(any(e.trigger.get("event")=="sent_to_grave" and e.trigger.get("reason")=="effect" for e in effects)),
                float("return_fusion_materials" in p.kinds),float("search_or_recover" in p.kinds),
                float(any(e.costs for e in effects)),float(any(e.targets for e in effects)),
                float(any(e.count_limit.get("status")=="known" for e in effects)),
                float(any(r["kind"]=="cannot_normal_summon" for r in restrictions)),
                float(any(r["kind"]=="extra_fusion_only" for r in restrictions)),
                float(any(r["kind"]=="cannot_be_fusion_material" for r in restrictions)),
                float(bool(p.unknown) or any(e.unknown for e in effects)),
                max((c['maximum'] for c in limits if c.get('maximum') is not None),default=0)/10,
                float(any(c.get('count_event')=='use' for c in limits)),
                float(any(c.get('subject',{}).get('controller')=='both_separately' or
                    c.get('scope','').startswith('player_') for c in limits)),
                float(any(c.get('negation_policy',{}).get('activation_negated')=='counts' for c in limits)),
                float(any(c.get('negation_policy',{}).get('activation_negated')=='does_not_count' for c in limits)),
                float(any('unknown' in c.get('negation_policy',{}).values() for c in limits))]
