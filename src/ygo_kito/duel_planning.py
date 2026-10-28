"""Budgeted, player-view planning over conditional CB projections.

Only the root actions are core-certified legal. Later moves and responses are
explicit hypotheses, not cloned native state or effect execution proofs. This
module has no engine, profile, seed, opponent deck, or deck-order argument.
"""
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from itertools import combinations, islice
import math
import time

import torch

from .build_contracts import BuildTask, DeckParts, digest
from .contracts import DecisionRequest
from .duel_effect_limits import EffectLimitTracker, RULES
from .normal_duel import request_digest
from .validation import ContractError, integer

VERSION = "player-view-cb-expectimax-v1"


@dataclass(frozen=True)
class PlanningBudget:
    nodes: int = 96
    depth: int = 4
    roots: int = 12
    seconds: float = .025
    strength: float = 1.5

    def __post_init__(self):
        for name, maximum in (("nodes", 512), ("depth", 6), ("roots", 32)):
            integer(getattr(self, name), "planning " + name, 1, maximum)
        if not 0 < self.seconds <= 1 or not math.isfinite(self.seconds):
            raise ContractError("planning seconds must be finite and within (0,1]")
        if not 0 < self.strength <= 4 or not math.isfinite(self.strength):
            raise ContractError("bounded planning strength required")


@dataclass(frozen=True)
class ComboPlan:
    plan_id: str
    goal_card: int
    opening: tuple
    steps: tuple  # (operation, tuple(card_ids)); own intents, never native refs
    effect_descriptions: tuple = ()  # optional exact native descriptions, aligned with steps

    def __post_init__(self):
        integer(self.goal_card, "CB goal", 1, 2**32-1)
        if not isinstance(self.plan_id,str) or not self.plan_id: raise ContractError("CB plan identity required")
        if not 1 <= len(self.steps) <= 32 or len(self.opening) > 8:
            raise ContractError("bounded CB intents and conditions required")
        for operation, codes in self.steps:
            if operation not in ("summon", "activate", "search", "special_summon") or not 1 <= len(codes) <= 8:
                raise ContractError("unsupported conditional CB intent")
            for code in codes: integer(code, "CB identity", 1, 2**32-1)
        for code in self.opening: integer(code,"CB opening identity",1,2**32-1)
        if self.effect_descriptions and len(self.effect_descriptions)!=len(self.steps):
            raise ContractError("CB effect descriptions must align with exact steps")
        for description in self.effect_descriptions:
            if description is not None: integer(description,"CB effect description",0,2**32-1)


def plans_from_construction(task, construction, *, deck=None):
    """Strip a host construction result to OWN goals/conditions/intent lists.

    In particular, replay seeds, engine final observations, native action IDs
    and complete route audit windows cannot cross this boundary.
    """
    basic=construction.get('basic_cb') if isinstance(construction,dict) else None
    if isinstance(basic,dict) and 'routes' in basic:
        from .build_semantics import accepted_status,route_task
        if not isinstance(task,BuildTask):raise ContractError('basic CB requires its typed original task')
        best=construction.get('best')
        if not isinstance(best,dict) or not isinstance(best.get('deck'),dict):return ()
        constructed=DeckParts.from_dict(best['deck'])
        if deck is not None and (not isinstance(deck,DeckParts) or deck!=constructed):
            raise ContractError('basic CB does not belong to the actual constructed deck')
        deck_sha=digest(constructed.to_dict())
        # The session goal binds request+task. Production construction exposes
        # a separate task-goal digest; legacy inference envelopes use this
        # digest directly in goal_sha256. Neither can substitute another task.
        goal_sha=construction.get('task_goal_sha256',construction.get('goal_sha256'))
        if (basic.get('task_sha256')!=task.sha256 or basic.get('subject_deck_sha256')!=deck_sha or
                goal_sha!=digest(task.goal)):
            raise ContractError('basic CB original task/goal/deck binding differs')
        routes=basic['routes']
        if not isinstance(routes,(list,tuple)) or len(routes)>8:raise ContractError('bounded basic CB routes required')
        original=task.to_dict();plans=[];own=set(constructed.main+constructed.extra)
        for row in routes:
            if not isinstance(row,dict) or not isinstance(row.get('task'),dict):continue
            derived=BuildTask.from_dict(row['task']);raw=derived.to_dict()
            if (any(raw[k]!=v for k,v in original.items() if k not in ('task_id','goal','requirements')) or
                    any(derived.goal.get(k)!=v for k,v in task.goal.items()) or
                    set(derived.goal)-set(task.goal)-{'route_goal','required_activations','required_chain_resolutions'}):
                raise ContractError('derived basic CB changes its original construction task or goal')
            from .basic_cb_inference import inference_requirements
            expected={(r['zone'],r['card_id']):r for r in inference_requirements(task,constructed,derived.goal)}
            actual={(r['zone'],r['card_id']):r for r in raw['requirements']}
            if actual!=expected:
                raise ContractError('derived basic CB changes requirements beyond its inferred route cards')
            proof=row.get('proof')
            if not isinstance(proof,dict) or proof.get('status')!=accepted_status(derived):continue
            if proof.get('task_sha256')!=derived.sha256 or proof.get('deck_sha256')!=deck_sha:
                raise ContractError('basic CB proof belongs to another derived task or deck')
            native=proof.get('native_route');native_task=route_task(derived)
            if not isinstance(native,dict) or native.get('status')!='verified_success':continue
            if (native.get('task_sha256')!=native_task.sha256 or native.get('deck_sha256')!=deck_sha or
                    native.get('starting_condition')!=native_task.goal['starting_conditions']):
                raise ContractError('basic CB native route binding differs')
            evidence=native.get('route_evidence',{});responses=native.get('responses')
            # Status/provenance names alone are not execution evidence. Consume
            # only bound recorded route data; do not run/replay the engine here.
            if (not isinstance(responses,list) or not responses or native.get('trajectory_sha256')!=digest(responses) or
                    native.get('card_list_legal') is not True or proof.get('effect_execution_verified') is not True or
                    not isinstance(evidence,dict) or evidence.get('conditional_only') is not True):continue
            if evidence.get('versions')!=native_task.environment['versions']:
                raise ContractError('basic CB route uses different source versions')
            opening=Counter(native_task.goal['starting_conditions']['requires_opening_hand'])
            if any(Counter(constructed.main)[c]<n for c,n in opening.items()):
                raise ContractError('basic CB opening is absent from its constructed deck')
            for plan in plans_from_construction(derived,{'native_route':native}):
                if plan.goal_card not in own or any(c not in own for _,cs in plan.steps for c in cs):
                    raise ContractError('basic CB intents are outside the constructed deck')
                plan=replace(plan,plan_id=digest([task.sha256,derived.sha256,deck_sha,plan.plan_id]))
                if plan not in plans:plans.append(plan)
                if len(plans)==8:return tuple(plans)
        return tuple(plans)
    goal = task.goal.get("route_goal", task.goal)
    if "card_id" not in goal: return ()
    own_pool = set(task.pool)
    routes = []
    if goal.get("route"): routes.append(goal["route"])
    if goal.get("kind") == "normal_summon":
        routes.append([{"operation": "summon", "card_ids": [goal["card_id"]]}])
    def visit(value, depth=0):
        if depth > 12: return
        if isinstance(value, dict):
            # Only the whitelisted intent field is consumed. Other values are
            # traversed for nested combined-goal receipts, never copied.
            if isinstance(value.get("discovered_intents"), list): routes.append(value["discovered_intents"])
            for key in ("best", "validation", "attempts", "engine_validation", "route_evidence",
                        "exploration", "route_validation", "route_result", "native_route", "route"):
                if key in value: visit(value[key], depth+1)
        elif isinstance(value, (list, tuple)):
            for item in value[:32]: visit(item, depth+1)
    visit(construction)
    plans = []
    for route in routes[:8]:
        supported=[s for s in route if s.get("operation") in ("summon","activate","search","special_summon") and s.get("card_ids")]
        steps=tuple((s['operation'],tuple(s['card_ids'])) for s in supported)
        descriptions=tuple(s.get('effect_description') for s in supported)
        if not any(d is not None for d in descriptions):descriptions=()
        if not steps: continue
        if any(c not in own_pool for _,codes in steps for c in codes): continue
        opening = tuple(goal.get("starting_conditions", {}).get("requires_opening_hand", ()))
        ident = digest([goal["card_id"], opening, steps,descriptions])
        plan = ComboPlan(ident, goal["card_id"], opening, steps,descriptions)
        if plan not in plans: plans.append(plan)
    return tuple(plans)


def response_catalog(rows):
    """Uncalibrated text-based response hypotheses; no card-ID dispatch.

    Text classification proposes possible threats, not availability, timing,
    costs or a proof that the particular effect can currently be activated.
    """
    result = {}
    for code, row in rows.items():
        desc = str(row.get("desc", "")).lower()
        threats = []
        if any(word in desc for word in ("无效", "無効", "negate")): threats.append("negate")
        if any(word in desc for word in ("破坏", "破壊", "destroy", "除外", "banish", "返回手", "return to the hand")):
            threats.append("remove")
        if threats: result[code] = tuple(threats)
    return result


@dataclass
class PlanMemory:
    observer: int | None = None
    duel: tuple | None = None
    turn: int | None = None
    progress: dict = field(default_factory=dict)
    goal: int | None = None
    selected: list = field(default_factory=list)
    pending: list = field(default_factory=list)
    seen_events: set = field(default_factory=set)
    known_hand: Counter = field(default_factory=Counter)
    possible_hand: set = field(default_factory=set)
    interruptions: int = 0
    normal_used: bool = False
    interruption_context: list = field(default_factory=list)


@dataclass(frozen=True)
class _State:
    cards: tuple  # (card_id, zone, attack); OWN visible cards only
    cursors: tuple
    normal_used: bool = False
    damage: float = 0.
    enabled_search: bool = False
    unverified_retries: tuple = ()  # future projection uncertainty, NOT a rule prohibition
    limit_spends: tuple = ()  # (verified shared counter subject, hypothetical additional uses)
    uncertain_limit_subjects: tuple = ()
    material_events: tuple = ()  # (card_id, procedure, event_class), independent of resource zone
    unverified_material_effects: tuple = ()


@dataclass(frozen=True)
class _Projection:
    committed: _State  # resources already paid BEFORE the modeled response window
    resolved: _State   # hypothetical successful resolution/summon
    operation: str
    codes: tuple
    stage: str
    target_index: int | None = None
    paid_materials: tuple = ()
    limit_bindings: tuple = ()
    material_indices: tuple = ()
    material_kind: str | None = None


class DuelPlanner:
    def __init__(self, *, own_deck=(), plans=(), facts=None, responses=None, budget=None,effect_limit_bindings=()):
        self.inventory = Counter(own_deck)  # own unordered contents only
        self.plans = tuple(plans)
        if (len(self.plans) > 8 or any(not isinstance(p, ComboPlan) for p in self.plans) or
                len({p.plan_id for p in self.plans}) != len(self.plans)):
            raise ContractError("typed bounded own CB plans required")
        self.facts = {c: {k: row[k] for k in ("type", "level", "attack", "defense") if k in row}
                      for c, row in (facts or {}).items()}
        self.responses, self.budget = dict(responses or {}), budget or PlanningBudget()
        self.memory = PlanMemory()
        self.limits = EffectLimitTracker(effect_limit_bindings)
        for binding in self.limits.bindings:binding.assert_catalog(facts or {})
        self.last_receipt = None

    def _observe(self, request):
        obs, m = request.observation, self.memory
        identity = (request.context.run_id, request.duel_id)
        if m.duel != identity:
            self.memory = m = PlanMemory(observer=obs.observer, duel=identity, turn=obs.turn)
        if m.observer != obs.observer: raise ContractError("planner cannot mix player perspectives")
        self.limits.observe(request)
        if m.turn != obs.turn:
            m.turn = obs.turn; m.progress.clear(); m.pending.clear(); m.selected.clear(); m.goal = None
            m.normal_used = False
        fresh = [e for e in obs.public_history if e.event_id not in m.seen_events]
        m.seen_events.update(e.event_id for e in fresh)
        for event in fresh:
            d = event.details
            if d is None: continue
            if event.kind == "move" and len(d.locations) == 2:
                src, dst = d.locations
                if src.controller == 1-obs.observer and src.zone == "hand":
                    if event.card_ids:
                        for code in event.card_ids:
                            m.known_hand[code] = max(0, m.known_hand[code]-1); m.possible_hand.discard(code)
                    else:
                        # Anonymous hand exits break identity tracking. Preserve
                        # a possibility, never a false known-current identity.
                        m.possible_hand.update(c for c, n in m.known_hand.items() if n)
                        m.known_hand.clear()
                if dst.controller == 1-obs.observer and dst.zone == "hand":
                    m.known_hand.update(event.card_ids)
            if event.kind == "shuffle" and d.player == 1-obs.observer:
                m.known_hand.clear(); m.possible_hand.clear()
        current_hand = Counter(c.card_id for c in obs.cards if c.controller == 1-obs.observer and
                               c.zone == "hand" and c.card_id is not None)
        for code,n in current_hand.items(): m.known_hand[code] = max(n,m.known_hand[code])
        for pending in list(m.pending):
            if pending not in m.pending: continue
            code = pending["codes"][0]
            own = [c for c in obs.cards if c.controller == obs.observer and c.card_id is not None]
            success = (pending["operation"] in ("summon", "special_summon") and
                       any(c.card_id == code and c.zone == "monster" for c in own))
            if pending["operation"] == "search":
                before = Counter(pending["hand_before"])
                after = Counter(c.card_id for c in own if c.zone == "hand")
                success = all(after[c] >= before[c]+n for c,n in Counter(pending["codes"]).items())
            for event in fresh:
                d = event.details
                if d is None: continue
                if event.kind == "activate" and code in event.card_ids and d.player == obs.observer:
                    pending["link"] = d.link
                if pending.get("link") is not None and d.link == pending["link"]:
                    if d.message in (75, 76): pending["interruption_message"] = d.message
                    if d.message == 73 and pending["operation"] == "activate": success = "interruption_message" not in pending
            if (not success and request.prompt and request.prompt.message in (10,11) and
                    pending["operation"] in ("summon","special_summon")):
                pending["interruption_message"] = None  # unsuccessful observed attempt, reason unproved
            if "interruption_message" in pending:
                m.interruptions += 1
                # Preserve distinct raw messages/effect descriptions for the
                # source-bound official rule table. No use/activation counter
                # or retry prohibition is inferred from an interruption alone.
                m.interruption_context.append({"native_message":pending["interruption_message"],
                    "operation":pending["operation"],"card_ids":list(pending["codes"]),
                    "effect_description":pending.get("effect_description"),"turn":obs.turn,
                    "count_rule_status":"explicit_binding_required", "retry_legality":"engine_legal_options",
                    "bound_counters":self.limits.view()})
                m.interruption_context[:] = m.interruption_context[-8:]
                m.progress[pending["plan"]] = pending["cursor"]
                m.pending[:] = [p for p in m.pending if p["plan"] != pending["plan"] or p["cursor"] < pending["cursor"]]
                m.selected.clear(); m.goal = None
            elif success:
                m.progress[pending["plan"]] = max(m.progress.get(pending["plan"],0),pending["cursor"]+1)
                m.pending.remove(pending)
        if request.prompt and request.prompt.message in (10, 11):
            m.selected.clear()
        if obs.hand_counts[1-obs.observer] == 0:
            m.known_hand.clear(); m.possible_hand.clear()

    def _belief(self, request):
        obs, m = request.observation, self.memory
        other = 1-obs.observer
        hand_n = obs.hand_counts[other]
        visible = [c for c in obs.cards if c.controller == other and c.card_id is not None]
        known = set(c for c,n in m.known_hand.items() if n)
        known.update(c.card_id for c in visible if c.zone == "hand")
        field = {c.card_id for c in visible if c.zone in ("monster", "spell_trap")}
        # These are explicitly fixed, uncalibrated priors, not inferred exact
        # deck contents. Unknown identities are never manufactured.
        hidden_hand = max(0, hand_n-sum(m.known_hand.values()))
        hidden_sets = sum(c.controller == other and c.visibility == "hidden" and
                          c.zone in ("monster", "spell_trap") for c in obs.cards)
        unknown = 1-(.94**hidden_hand)*(.88**hidden_sets)
        identifiable = .65 if any(c in self.responses for c in known) else 0.
        field_risk = .45 if any(c in self.responses for c in field) else 0.
        possible = .2 if any(c in self.responses for c in m.possible_hand) else 0.
        risk = min(.92, 1-(1-unknown)*(1-identifiable)*(1-field_risk)*(1-possible))
        return {"known_revealed_in_hand": sorted(known), "possibly_still_in_hand": sorted(m.possible_hand-known),
                "visible_field": sorted(field), "unknown_hand_count": hidden_hand, "unknown_set_count": hidden_sets,
                "response_probability": risk, "probability_status": "uncalibrated-conservative-hypothesis",
                "response_kinds": sorted({r for c in known|field|m.possible_hand for r in self.responses.get(c, ())}),
                "unknown_response_kinds": ["negate", "remove"] if unknown else []}

    def _power(self, code):
        return max(0, self.facts.get(code, {}).get("attack", 0))/2000

    def _value(self, state):
        value = state.damage/4000
        for code, zone, attack in state.cards:
            value += (max(0, attack)/2000+.3 if zone == "monster" else
                      .2 if zone == "hand" else .06 if zone == "graveyard" else .03)
        for goal in {plan.goal_card for plan in self.plans}:
            if any(code == goal and zone == "monster" for code,zone,_ in state.cards): value += 2.5
        return value

    def _project(self, state, operation, codes, *, root=False,effect_description=None):
        """Separate committed resources from hypothetical resolution benefits.

        None can mean unmodeled/unknown, not a ruling that a real action is
        illegal. Every newly offered root remains governed by the engine.
        """
        if not root and (operation,tuple(codes)) in state.unverified_retries:
            return None  # retry count/timing unknown; await another real legal window
        if not root and operation=='activate' and codes[0] in state.unverified_material_effects:
            return None  # GY presence alone does not establish the required material-trigger event
        bindings=self.limits.matching(codes[0],effect_description) if operation=='activate' else ()
        spends=dict(state.limit_spends)
        for b in bindings:
            remaining=self.limits.remaining(b)
            if b.subject_key in state.uncertain_limit_subjects:remaining=None
            if not root and remaining is None:return None  # incomplete bound counter, await engine
            if not root and remaining is not None and remaining-spends.get(b.subject_key,0)<=0:return None
        for subject in {b.subject_key for b in bindings if self.limits.remaining(b) is not None}:
            spends[subject]=spends.get(subject,0)+1
        with_counts=replace(state,limit_spends=tuple(sorted(spends.items())))
        cards = list(state.cards); used = state.normal_used
        def find(code, zones):
            return next((i for i,c in enumerate(cards) if c[0] == code and c[1] in zones), None)
        if operation == "search":
            if not root and not state.enabled_search: return None
            for code in codes:
                i = find(code, ("deck",))
                if i is None: return None
                cards[i] = (code, "hand", cards[i][2])
            resolved = replace(state, cards=tuple(cards), enabled_search=False)
            return _Projection(state,resolved,operation,tuple(codes),"effect_before_resolution")
        i = find(codes[0], ("hand",) if operation == "summon" else
                 ("extra", "hand", "graveyard") if operation == "special_summon" else
                 ("hand", "monster", "spell_trap", "graveyard"))
        if i is None: return None
        code, zone, attack = cards[i]
        if (not root and operation == "special_summon" and zone != "extra" and
                self.facts.get(code,{}).get("type",0)&(0x40|0x2000|0x800000|0x4000000)):
            return None  # revival procedure unmodeled; await a real legal window
        committed = with_counts; paid = (); chosen = (); material_kind=None
        resolved_events=state.material_events;stage = "response_timing_unknown"
        if operation == "summon":
            if used and not root: return None
            used = True
            committed = replace(with_counts,normal_used=True)
            stage = "summon_attempt_after_commitment"
            cards[i] = (code, "monster", attack)
        elif operation == "special_summon":
            if zone == "extra":
                materials = [j for j,c in enumerate(cards) if c[1] == "monster"]
                kind = self.facts.get(code, {}).get("type", 0)
                level = self.facts.get(code, {}).get("level", 0) & 255
                chosen = None
                # Bounded structural necessary conditions, not effect legality.
                for group in islice(combinations(materials, 2), 16):
                    facts = [self.facts.get(cards[j][0], {}) for j in group]
                    levels = [f.get("level", 0)&255 for f in facts]
                    if kind & 0x2000 and (sum(levels) != level or not any(f.get("type",0)&0x1000 for f in facts)): continue
                    if kind & 0x800000 and any(n != level for n in levels): continue
                    chosen = group; break
                if chosen is None: return None
                material_kind=('xyz' if kind&0x800000 else 'synchro' if kind&0x2000 else
                               'link' if kind&0x4000000 else 'fusion' if kind&0x40 else 'unknown')
                for j in chosen: cards[j] = (cards[j][0],"overlay" if material_kind=='xyz' else "graveyard",cards[j][2])
                paid = tuple(cards[j][0] for j in chosen)
                attempt_events=tuple((c,material_kind,'committed_for_summon_attempt') for c in paid)
                resolved_events=state.material_events+tuple((c,material_kind,'successful_summon_material_use') for c in paid)
                # Only the currently modeled Synchro/Xyz procedure has a
                # pre-attempt material commitment. Effect-driven Fusion/other
                # procedures need explicit timing knowledge; do not guess it.
                if kind & (0x2000|0x800000):
                    committed = replace(with_counts,cards=tuple(cards),material_events=state.material_events+attempt_events)
                    stage = "summon_attempt_after_material_commitment"
                else: stage = "material_timing_unknown"
            cards[i] = (code, "monster", attack)
        elif operation == "activate":
            stage = "effect_before_resolution"
            # This remains only a successful-resolution placeholder. Being a
            # spell is NOT evidence that its activation cost was paid to GY.
            if zone == "hand" and self.facts.get(code, {}).get("type", 0)&2:
                cards[i] = (code, "graveyard", attack)
        resolved = replace(with_counts,cards=tuple(cards),normal_used=used,enabled_search=operation == "activate",
                           material_events=resolved_events)
        return _Projection(committed,resolved,operation,tuple(codes),stage,i,paid,bindings,tuple(chosen),material_kind)

    def _failure(self, projection,*,interruption=None):
        """Keep paid resources; discard only benefits absent at this stage."""
        if projection.stage in ("response_timing_unknown","material_timing_unknown"):
            return None  # no invented refund OR payment; recovery needs the engine
        committed = projection.committed
        cards = list(committed.cards)
        if projection.stage in ("summon_attempt_after_commitment","summon_attempt_after_material_commitment"):
            i = projection.target_index
            cards[i] = (cards[i][0],"graveyard",cards[i][2])
        material_events=committed.material_events
        if projection.material_kind=='xyz':
            # FAQ11269: materials already became Xyz materials; on failure
            # they go to GY from that material state, not back to the field.
            for j in projection.material_indices:cards[j]=(cards[j][0],'graveyard',cards[j][2])
            material_events+=tuple((c,'xyz','sent_to_gy_from_material_after_failed_summon') for c in projection.paid_materials)
        retry = (projection.operation,projection.codes)
        spends=dict(committed.limit_spends);uncertain=set(committed.uncertain_limit_subjects)
        seen_subjects=set()
        for b in projection.limit_bindings:
            if b.subject_key in seen_subjects:continue
            seen_subjects.add(b.subject_key)
            rule=RULES[b.rule_id]
            if interruption in ('activation_negated','effect_negated'):
                counted=rule[interruption]
            else:
                flags=(rule['activation_negated'],rule['effect_negated'])
                counted=True if flags==(True,True) else None
            if counted is False:spends[b.subject_key]=max(0,spends.get(b.subject_key,0)-1)
            elif counted is None:uncertain.add(b.subject_key)
        return replace(committed,cards=tuple(cards),enabled_search=False,
                       unverified_retries=committed.unverified_retries+(retry,),
                       limit_spends=tuple(sorted(spends.items())),uncertain_limit_subjects=tuple(sorted(uncertain)),
                       material_events=material_events,
                       unverified_material_effects=committed.unverified_material_effects+projection.paid_materials)

    def _continuation(self, state, depth, risk):
        best, path = self._value(state), []  # stopping/reserving is a real alternative
        if depth == 0 or self._exhausted(): return best, path
        for n, plan in enumerate(self.plans):
            cursor = state.cursors[n]
            if cursor >= len(plan.steps): continue
            operation, codes = plan.steps[cursor]
            description=plan.effect_descriptions[cursor] if plan.effect_descriptions else None
            projection = self._project(state,operation,codes,effect_description=description)
            if projection is None or self._exhausted(): continue
            self._nodes += 1
            cursors = list(state.cursors); cursors[n] += 1
            projected = replace(projection.resolved, cursors=tuple(cursors))
            good, suffix = self._continuation(projected, depth-1, risk)
            p = risk if operation in ("activate", "summon", "special_summon") else 0.
            bad = self._value(state)
            if p and not self._exhausted():
                self._nodes += 1
                failed = self._failure(projection)
                if failed is not None: bad, _ = self._continuation(failed, depth-1, 0.)
            expected = (1-p)*good+p*bad
            if expected > best:
                best, path = expected, [{"plan": plan.plan_id, "operation": operation, "card_ids": list(codes),
                    "success_value": good, "response_value": bad, "response_probability": p,
                    "response_stage":projection.stage,"committed_materials":list(projection.paid_materials)
                        if projection.stage == "summon_attempt_after_material_commitment" else [],
                    "retry_rule_status":"unknown_requires_engine"}] + suffix
        return best, path

    def _exhausted(self):
        return self._nodes >= self._root_limit or time.perf_counter() >= self._deadline

    def _cursors(self, request):
        m = self.memory
        result = []
        own = Counter((c.card_id,c.zone) for c in request.observation.cards if c.controller == request.observation.observer)
        for plan in self.plans:
            cursor = max([m.progress.get(plan.plan_id,0)]+[p["cursor"]+1 for p in m.pending if p["plan"] == plan.plan_id])
            # An already established board can enter a suffix without requiring
            # the original opening again. Activation success is never inferred
            # merely from a card's presence in the graveyard.
            while cursor < len(plan.steps):
                op,codes = plan.steps[cursor]
                if op in ("summon","special_summon") and all(own[(c,"monster")] >= n for c,n in Counter(codes).items()): cursor += 1
                else: break
            result.append(cursor)
        return tuple(result)

    def _operation(self, request, action):
        return "search" if request.search_choices and action.kind == "select" else action.kind

    def _materials(self, request, action, ids):
        """Conditional compatibility using the retained target AND prior picks."""
        m = self.memory
        if m.goal is None: return 0.
        codes = [ids[r] for r in action.card_refs if r in ids]
        picked = list(m.selected)
        removing = action.details and action.details.operation == "remove"
        if removing:
            for code in codes:
                if code in picked: picked.remove(code)
        elif action.kind == "select": picked.extend(codes)
        if action.details and action.details.operation == "finish":
            return .5 if picked else 0.
        goal = self.facts.get(m.goal,{})
        levels = [self.facts.get(c,{}).get("level",0)&255 for c in picked]
        target = goal.get("level",0)&255
        if goal.get("type",0)&0x2000 and target:
            if sum(levels)>target: return -1.
            tuner = any(self.facts.get(c,{}).get("type",0)&0x1000 for c in picked)
            possible = {(sum(levels),bool(tuner))}
            refs = set(r for a in request.actions if not (a.details and a.details.operation=="remove") for r in a.card_refs)
            remaining = Counter(ids[r] for r in refs if r in ids)-Counter(codes)
            for code in list(remaining.elements())[:16]:
                f = self.facts.get(code,{})
                possible |= {(n+(f.get("level",0)&255),t or bool(f.get("type",0)&0x1000)) for n,t in possible
                             if n+(f.get("level",0)&255)<=target}
                possible = set(sorted(possible)[:128])
            return .5 if (target,True) in possible else -.5
        if goal.get("type",0)&0x800000 and target:
            return .4 if all(n==target for n in levels) else -.4
        return 0.  # unknown Fusion/Link material text stays with the neural head

    def _matches(self, operation, codes, state):
        return [n for n,p in enumerate(self.plans) if state.cursors[n] < len(p.steps) and
                p.steps[state.cursors[n]][0] == operation and Counter(p.steps[state.cursors[n]][1]) == Counter(codes)]

    def evaluate(self, request, neural_logits):
        if not isinstance(request, DecisionRequest): raise ContractError("validated player request required")
        if request.context.seed is not None: raise ContractError("controller duel seeds cannot enter planning")
        if neural_logits.ndim != 1 or len(neural_logits) != len(request.actions): raise ContractError("complete root logits required")
        self._nodes = 0; self._deadline = time.perf_counter()+self.budget.seconds
        self._root_limit = self.budget.nodes
        self._observe(request)
        obs, m = request.observation, self.memory
        visible = {c.ref: c for c in obs.cards}
        ids = {r:c.card_id for r,c in visible.items() if c.card_id is not None}
        ids.update({c.ref:c.card_id for c in request.search_choices})
        ids.update({c.ref:c.card_id for c in request.selection_choices if c.card_id is not None})
        cards = [(c.card_id,c.zone,c.attack if c.attack is not None else self.facts.get(c.card_id,{}).get("attack",0))
                 for c in obs.cards if c.controller == obs.observer and c.card_id is not None]
        counts = Counter(c for c,_,_ in cards)
        for code,n in (self.inventory-counts).items(): cards.extend([(code,"deck",self.facts.get(code,{}).get("attack",0))]*n)
        state = _State(tuple(cards), self._cursors(request),normal_used=m.normal_used)
        belief = self._belief(request); risk = belief["response_probability"]
        values = neural_logits.detach().cpu().tolist()
        def rank(i):
            a = request.actions[i]; codes = tuple(ids[r] for r in a.card_refs if r in ids)
            matches = self._matches(self._operation(request,a), codes, state)
            return values[i]+(2. if matches else 0.)
        # Keep a neural shortlist plus CB-compatible roots found within the
        # SAME time budget. Large declaration/selection windows cannot turn a
        # Python ranking pass into an unbounded search.
        pool = set(torch.topk(neural_logits.detach().cpu(),min(self.budget.roots,len(values))).indices.tolist())
        scanned = 0
        if self.plans:
            for i,a in enumerate(request.actions):
                if scanned >= 1024 or time.perf_counter() >= self._deadline: break
                scanned += 1
                codes = tuple(ids[r] for r in a.card_refs if r in ids)
                if self._matches(self._operation(request,a),codes,state): pool.add(i)
        roots = sorted(pool,key=lambda i:(-rank(i),i))[:self.budget.roots]
        baseline = self._value(state); scores = {}; branches = []
        for i in roots:
            if self._nodes >= self.budget.nodes or time.perf_counter() >= self._deadline: break
            self._root_limit = min(self.budget.nodes,self._nodes+max(1,self.budget.nodes//len(roots)))
            self._nodes += 1
            a = request.actions[i]; codes = tuple(ids[r] for r in a.card_refs if r in ids)
            operation = self._operation(request,a)
            description=None if a.details is None else a.details.description
            projection = self._project(state,operation,codes,root=True,effect_description=description) if codes and operation in ("summon","special_summon","activate","search") else None
            matching = self._matches(operation, codes, state)
            if operation == "activate" and not matching:
                # Unsupported effect semantics retain the neural prior. A cost
                # without its unknown benefit would systematically suppress it.
                projection = None
            projected = projection.resolved if projection is not None else state
            for n in matching if projection is not None else ():
                cursors = list(projected.cursors); cursors[n] += 1
                projected = replace(projected,cursors=tuple(cursors))
            good, path = (self._continuation(projected,self.budget.depth-1,risk)
                          if projected is not state else (baseline,[]))
            p = risk if projected is not state and codes and operation in ("summon","special_summon","activate") else 0.
            bad = baseline
            response_status = "not_evaluated"; recovery = []
            if p and projection is not None and not self._exhausted():
                self._nodes += 1
                failed = self._failure(projection)
                response_status = "unknown_requires_engine" if failed is None else "stage_conditioned_resource_projection"
                if failed is not None:
                    bad,recovery = self._continuation(failed,self.budget.depth-1,0.)
            value = (1-p)*good+p*bad-baseline
            combat = []
            if operation == "attack" and a.card_refs:
                attacker = visible.get(a.card_refs[0]); target = visible.get(a.card_refs[1]) if len(a.card_refs)>1 else None
                attack = max(0,attacker.attack or 0) if attacker else 0
                defending = bool(target and (target.position or 0)&10)
                unknown = target is not None and target.card_id is None
                cases = ((0,.2),(2000,.5),(3000,.3)) if unknown else ((max(0,(target.defense if defending else target.attack) or 0) if target else 0,1.),)
                for defense,probability in cases:
                    damage = 0 if defending else max(0,attack-defense)
                    gain = damage/4000+(2 if damage >= obs.life_points[1-obs.observer] else 0)
                    if target and not defending and defense >= attack: gain -= attack/2000+.3
                    if target and attack>defense: gain += .2
                    combat.append({"defending_stat":defense,"probability":probability,
                                   "gain":gain,"status":"unknown-stat-prior" if unknown else "visible-stat-projection"})
                    value += (1-risk)*probability*gain
            if request.prompt and request.prompt.message in (15,20,23,26) and operation == "select":
                # Keep the chosen goal and materials through incremental windows;
                # rank legal alternatives by opportunity cost of remaining fuel.
                reserved = set(c for plan in self.plans for op,cs in plan.steps[state.cursors[self.plans.index(plan)]:] for c in cs if op != "special_summon")
                value -= sum(self._power(c)*.15 + (.45 if c in reserved else 0.) for c in codes)
                if m.goal in codes: value += 2.
                if a.details and a.details.operation == "remove": value -= .6
            if not request.search_choices and request.prompt and request.prompt.message in (15,20,23,26):
                value += self._materials(request,a,ids)
            if a.details and a.details.operation == "shuffle": value -= 2.
            scores[i] = 4*math.tanh(value*self.budget.strength/4)
            branches.append({"action_index":i,"projected_gain":value,"success_value":good,"response_value":bad,
                             "response_probability":p,"continuation":path,"recovery":recovery,"combat":combat,
                             "response_stage":None if projection is None else projection.stage,
                             "response_status":response_status,
                             "committed_materials":list(projection.paid_materials) if projection is not None and
                                 projection.stage == "summon_attempt_after_material_commitment" else [],
                             "retry_rule_status":"unknown_requires_engine"})
        # Unexpanded leaves retain the neural prior. ALL legal actions keep
        # finite mass; the tree budget is not an action mask.
        bias = [scores.get(i,0.) for i in range(len(request.actions))]
        receipt = {"version":VERSION,"request_sha256":request_digest(request),"bias":bias,
            "plans_sha256":digest([asdict(p) for p in self.plans]),"goal":m.goal,"progress":dict(m.progress),
            "selected_materials":list(m.selected),"interruptions":m.interruptions,"belief":belief,
            "interruption_context":list(m.interruption_context),
            "interruption_rules":{"status":"exact_bindings_only",
                "use_vs_activation_counts_inferred":False,"root_legality":"engine_provided",
                "counter_queries":self.limits.view(),"standard_named_card_activation_limit":"pending_direct_official_evidence"},
            "projection_revision":2,
            "nodes":self._nodes,"node_limit":self.budget.nodes,"depth_limit":self.budget.depth,
            "cb_roots_scanned":scanned,"cb_scan_limit":1024,
            "root_count":len(branches),"budget_exhausted":self._nodes >= self.budget.nodes or time.perf_counter() >= self._deadline,"branches":branches,
            "projection_status":"conditional-approximate-not-core-verified",
            "starting_conditions":{p.plan_id:{"required":list(p.opening),
                "currently_in_hand": all(Counter(c for c,z,_ in cards if z == "hand")[c]>=n for c,n in Counter(p.opening).items())}
                for p in self.plans}}
        self.last_receipt = receipt
        return neural_logits + neural_logits.new_tensor(bias), receipt

    def accepted(self, request, action):
        """Called only AFTER actual engine.submit returned successfully."""
        ids = {c.ref:c.card_id for c in request.observation.cards if c.card_id is not None}
        ids.update({c.ref:c.card_id for c in request.search_choices})
        ids.update({c.ref:c.card_id for c in request.selection_choices if c.card_id is not None})
        codes = tuple(ids[r] for r in action.card_refs if r in ids)
        m = self.memory
        if action.kind == "summon": m.normal_used = True
        extra_goal = (action.kind == "select" and len(codes)==1 and any(c.ref in action.card_refs and
                      c.zone == "extra" and c.controller == request.observation.observer
                      for c in (*request.observation.cards,*request.selection_choices)))
        if extra_goal:
            m.goal = codes[0]; m.selected.clear()
        if not extra_goal and not request.search_choices and request.prompt and request.prompt.message in (15,20,23,26):
            if action.details and action.details.operation == "remove":
                for code in codes:
                    if code in m.selected: m.selected.remove(code)
            elif action.kind == "select": m.selected.extend(codes)
        if action.kind == "special_summon" and codes: m.goal = codes[0]
        operation = self._operation(request,action)
        for plan,cursor in zip(self.plans,self._cursors(request)):
            if cursor < len(plan.steps) and plan.steps[cursor][0] == operation and Counter(plan.steps[cursor][1]) == Counter(codes):
                m.goal = plan.goal_card
                m.pending.append({"plan":plan.plan_id,"cursor":cursor,"operation":operation,"codes":codes,
                    "effect_description":None if action.details is None else action.details.description,
                    "hand_before":[c.card_id for c in request.observation.cards if c.controller == request.observation.observer and c.zone == "hand"]})
                break


def replay_planning_bias(logits, steps):
    """Replay the SAME conditional behavior policy in base and LoRA PPO."""
    offsets = torch.zeros_like(logits)
    for i,step in enumerate(steps):
        receipt = step.get("planning")
        if receipt is None: continue  # historical unplanned episodes
        req = step["request"]; bias = receipt.get("bias")
        if (receipt.get("version") != VERSION or receipt.get("request_sha256") != request_digest(req) or
                not isinstance(bias,list) or len(bias) != len(req.actions) or
                any(type(x) not in (int,float) or not math.isfinite(x) or abs(x)>4 for x in bias)):
            raise ContractError("planning behavior receipt differs from this player request")
        offsets[i,:len(bias)] = logits.new_tensor(bias)
    return logits+offsets
