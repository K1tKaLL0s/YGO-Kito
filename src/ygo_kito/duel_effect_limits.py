"""Small evidence-bound counter queries, not a text classifier/rules engine.

Official FAQs define ONLY the named scopes below. A host must bind exact
card/effect descriptions and source text hashes; absent/partial scope is unknown.
No lookup based on a generic occurrence of 'activate' or 'use' is performed.
"""
from copy import deepcopy
from dataclasses import dataclass

from .build_contracts import digest
from .validation import ContractError, integer
from .rule_references import bound_counter_reference, library_reference


def _source(fid):
    return f"https://www.db.yugioh-card.com/yugiohdb/faq_search.action?ope=5&fid={fid}&request_locale=ja"


# Fields are narrow paraphrases of the cited rulings, not universal templates
# for other similarly worded cards. None means this evidence does not decide it.
RULES = {
    "qa17200": {"source":_source(17200),"source_card_name_ja":"タツノオトシオヤ","effect_scope":"①",
        "subject":"controller_named_tatsunootoshioya_effect_1",
        "limit":3,"reset":"turn","scope":"named_effect_across_copies",
        "activation_negated":True,"effect_negated":True,"not_applied":True},
    "qa17377": {"source":_source(17377),"source_card_name_ja":"破壊剣士融合","effect_scope":"①",
        "subject":"controller_named_destruction_swordsman_fusion_effect_1",
        "limit":1,"reset":"turn","scope":"named_effect_across_copies",
        "activation_negated":True,"effect_negated":None,"not_applied":None},
    "qa17376": {"source":_source(17376),"source_card_name_ja":"破壊剣士の宿命","effect_scope":"①",
        "subject":"controller_named_destruction_swordsman_fate_effect_1",
        "limit":1,"reset":"turn","scope":"named_effect_across_copies",
        "activation_negated":None,"effect_negated":True,"not_applied":None},
    "qa22010": {"source":_source(22010),"source_card_name_ja":"トラップトリック",
        "subject":"affected_player_trap_card_activations_after_trap_trick_applies",
        "limit":1,"reset":"turn","scope":"explicit_applied_scope","maximum_turn_span":0,
        "activation_negated":False,"effect_negated":True,"not_applied":True},
    "qa7813-caligula": {"source":_source(7813),"source_card_name_ja":"召喚獣カリギュラ",
        "subject":"affected_player_monster_effect_activations_under_caligula",
        "limit":1,"reset":"turn","scope":"explicit_applied_scope","maximum_turn_span":None,
        "activation_negated":True,"effect_negated":None,"not_applied":None},
    "qa23158-soul-crossing": {"source":_source(23158),"source_card_name_ja":"交差する魂",
        "subject":"affected_player_non_divine_beast_spell_trap_monster_effects",
        "limit":1,"reset":"turn","scope":"explicit_applied_scope","maximum_turn_span":1,
        "activation_negated":True,"effect_negated":None,"not_applied":None},
    "qa23158-unmei-no-draw": {"source":_source(23158),"source_card_name_ja":"運命のドロー",
        "subject":"affected_player_spell_trap_monster_effects_after_unmei_no_draw",
        "limit":1,"reset":"turn","scope":"explicit_applied_scope","maximum_turn_span":0,
        "activation_negated":True,"effect_negated":None,"not_applied":None},
}


@dataclass(frozen=True)
class EffectLimitBinding:
    binding_id: str
    rule_id: str
    subject_key: str  # SAME key across physical copies; distinct effects stay separate
    effects: tuple  # exact (card_id, native effect_description), never card-name guessing
    card_text_digests: tuple  # (card_id, digest(public catalog desc))
    first_turn: int = 1
    last_turn: int | None = None
    application_event_id: str | None = None  # certified scope applicability, not inferred from presence
    scope_complete: bool = False

    def __post_init__(self):
        if self.rule_id not in RULES or not self.binding_id or not self.subject_key:
            raise ContractError("explicit supported FAQ and counter subject required")
        if not isinstance(self.effects,tuple) or not 1<=len(self.effects)<=128:
            raise ContractError("exact bounded effect selectors required")
        for code,description in self.effects:
            integer(code,"limit card",1,2**32-1);integer(description,"exact effect description",0,2**32-1)
        if set(c for c,_ in self.effects)!=set(c for c,_ in self.card_text_digests):
            raise ContractError("limit selectors require matching public text hashes")
        for _,sha in self.card_text_digests:
            if not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):
                raise ContractError("source-bound public card text digest required")
        integer(self.first_turn,"limit start turn",1)
        if self.last_turn is not None: integer(self.last_turn,"limit end turn",self.first_turn)
        rule=RULES[self.rule_id]
        if rule['scope']=='explicit_applied_scope':
            if not self.application_event_id or self.last_turn is None:
                raise ContractError("applied restriction needs certified public scope and expiry")
            span=rule.get('maximum_turn_span')
            if span is not None and self.last_turn-self.first_turn>span:
                raise ContractError("restriction expiry exceeds its cited scope")

    def assert_catalog(self,rows):
        if any(code not in rows or digest(rows[code].get('desc',''))!=sha for code,sha in self.card_text_digests):
            raise ContractError("effect-limit binding public source text changed")


class EffectLimitTracker:
    """Count only exact, actor-owned public activations; negations stay distinct."""
    def __init__(self,bindings=()):
        self.bindings=tuple(bindings)
        if (len(self.bindings)>32 or any(not isinstance(b,EffectLimitBinding) for b in self.bindings)
                or len({b.binding_id for b in self.bindings})!=len(self.bindings)):
            raise ContractError("bounded unique effect-limit bindings required")
        groups={}
        for b in self.bindings:
            if b.subject_key in groups and groups[b.subject_key]!=b.rule_id:
                raise ContractError("one counter subject cannot silently mix different rulings")
            groups[b.subject_key]=b.rule_id
        self.duel=None;self.turn=0;self.event_turn=0;self.seen=set();self.records={};self.links={}
        self.applied=set();self.uncertain=set();self.prior_activation_turns=set()

    def observe(self,request):
        identity=(request.context.run_id,request.duel_id,request.observation.observer)
        if self.duel!=identity:
            self.__init__(self.bindings);self.duel=identity;self.event_turn=request.observation.turn
        self.turn=request.observation.turn
        for event in request.observation.public_history:
            if event.event_id in self.seen: continue
            self.seen.add(event.event_id)
            d=event.details
            if d is not None and d.turn is not None: self.event_turn=d.turn
            for b in self.bindings:
                if event.event_id==b.application_event_id:
                    self.applied.add(b.binding_id)
                    if b.rule_id=='qa7813-caligula' and self.event_turn in self.prior_activation_turns:
                        # This FAQ establishes negation treatment, not how an
                        # earlier pre-application activation enters the count.
                        self.uncertain.add((b.subject_key,self.event_turn))
            if d is None: continue
            if d.message==74: self.links.clear()
            if d.message==70 and d.player==request.observation.observer:
                matched=[]
                for b in self.bindings:
                    if not self._active(b,self.event_turn):continue
                    if any((c,d.description) in b.effects for c in event.card_ids):
                        key=(b.subject_key,event.event_id)
                        self.records[key]=dict(rule=b.rule_id,turn=self.event_turn,outcome='pending' if d.link is not None else 'unknown_link')
                        matched.append(key)
                    elif (RULES[b.rule_id]['scope']=='explicit_applied_scope' or not event.card_ids or
                          d.description is None and any(c in {code for code,_ in b.effects} for c in event.card_ids)):
                        # The classifier for this global scope is incomplete.
                        # Do not guess whether another public activation counts.
                        self.uncertain.add((b.subject_key,self.event_turn))
                self.links[d.link]=matched
                self.prior_activation_turns.add(self.event_turn)
            elif d.message in (73,75,76):
                for key in self.links.get(d.link,()):
                    record=self.records[key]
                    if d.message==75: record['outcome']='activation_negated'
                    elif d.message==76:record['outcome']='effect_negated'
                    elif record['outcome']=='pending':record['outcome']='resolved'

    def _active(self,b,turn):
        return (b.first_turn<=turn and (b.last_turn is None or turn<=b.last_turn) and
                (RULES[b.rule_id]['scope']!='explicit_applied_scope' or b.binding_id in self.applied))

    def remaining(self,b):
        if not self._active(b,self.turn) or not b.scope_complete or (b.subject_key,self.turn) in self.uncertain:return None
        total=0
        for (subject,_),record in self.records.items():
            if subject!=b.subject_key or record['turn']!=self.turn:continue
            counted=True if record['outcome'] in ('pending','resolved') else RULES[b.rule_id].get(record['outcome'])
            if counted is None:return None
            total+=int(counted)
        return max(0,RULES[b.rule_id]['limit']-total)

    def matching(self,code,description):
        if description is None:return ()
        return tuple(b for b in self.bindings if (code,description) in b.effects and
                     b.first_turn<=self.turn and (b.last_turn is None or self.turn<=b.last_turn))

    def view(self):
        return [{"binding_id":b.binding_id,"rule_id":b.rule_id,"source":RULES[b.rule_id]['source'],
            "subject_key":b.subject_key,"counter_subject":RULES[b.rule_id]['subject'],
            "reset":RULES[b.rule_id]['reset'],"first_turn":b.first_turn,"last_turn":b.last_turn,
            "remaining":self.remaining(b),"status":"known" if self.remaining(b) is not None else "unknown_requires_engine",
            "rule_review":bound_counter_reference(b,[dict(event_id=event_id,**record)
                for (subject,event_id),record in self.records.items() if subject==b.subject_key])}
            for b in self.bindings]


def rule_reference():
    """Reviewable metadata for the model host; unbound entries are not applied."""
    return {"rules":deepcopy(RULES),"reference_library":library_reference(),
        "standard_named_card_activation_limit":"pending_direct_official_evidence",
        "native_negation_messages":{"75":"activation_negated","76":"effect_negated"},
        "native_protocol_source":"locked ocgcore/common.h MSG_CHAIN_NEGATED/MSG_CHAIN_DISABLED"}
