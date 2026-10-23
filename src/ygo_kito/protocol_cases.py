"""Real upstream-card engineering cases in ordinary 8000-LP duels.

Only deck/seed setup is supplied. No field injection, custom Lua, patched rule,
pretended victory or all-state policy. Traces are private replay artifacts.
"""
from dataclasses import asdict
import json
from pathlib import Path
import time

from .build_contracts import digest
from .contracts import ActionSelection, DecisionRequest, Observation
from .native import NativeError, NativeNormalEngine
from .normal_duel import request_digest, choose_normal_action
from .validation import ContractError, canonical_json, fields

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "configs/protocol-history-engineering-v3.json"
REQUIRED = {"sum-at-least": (23,), "sum-dual": (23,), "counter": (22,), "sort": (25,),
            "announcements": (140,141), "card-name": (142,), "number-equip": (143,),
            "move-zone": (24,), "rps": (132,), "disable-two": (24,), "private-sort": (25,),
            "filtered-card": (142,), "confirm-extra": (14,), "public-deck": (18,)}


class EngineeringDriver:
    """Declared case intent + legal DTO + public catalogue, no engine/seed."""
    def __init__(self, case, catalog, preference):
        self.plan, self.catalog, self.preference = case["plan"], catalog, preference
        self.private = case["profile"].get("adapter_revision") == 4
        self.selections = case.get("selection_preferences", [])
        self.cursor = 0

    def choose(self, req, *, after_case=False):
        if after_case:
            return choose_normal_action(req)
        kind = req.prompt.message
        codes={c.ref:c.card_id for c in req.observation.cards}
        codes.update({c.ref:c.card_id for c in req.search_choices})
        codes.update({c.ref:c.card_id for c in req.selection_choices})
        if self.cursor < len(self.plan):
            step=self.plan[self.cursor]
            if req.observation.observer==step["player"] and req.observation.turn>=step["earliest_turn"]:
                matching=[a for a in req.actions if a.kind==step["kind"] and any(codes.get(r)==step["code"] for r in a.card_refs)]
                if matching:
                    self.cursor+=1
                    return matching[0]
        for selection in self.selections:
            if req.observation.observer==selection['player'] and kind==selection['message']:
                matching=[a for a in req.actions if a.kind=='select' and any(codes.get(r)==selection['card_id'] for r in a.card_refs)]
                if matching:return matching[0]
        if kind in (15,18,19,20,22,23,24,25):
            choices=[a for a in req.actions if a.kind in ("select","order","position")]
            return choices[-1] if self.preference=="last" and (kind in (22,23,24,25) or kind==15 and self.private) else choices[0]
        if kind in (140,141):
            public=[c.card_id for c in req.observation.cards if c.controller!=req.observation.observer and c.zone=="monster" and c.visibility=="public"]
            desired=self.catalog[public[0]]["race" if kind==140 else "attribute"] if public else 1
            return next((a for a in req.actions if a.value==desired),req.actions[0])
        if kind==142:
            return next(a for a in req.actions if a.value==32864)
        if kind==143:
            return next((a for a in req.actions if a.value==2000),req.actions[-1])
        if kind==132:
            desired=1 if req.observation.observer==0 else 2
            return next(a for a in req.actions if a.value==desired)
        if kind in (12,13):
            return next(a for a in req.actions if a.kind=="yes")
        if kind==26:
            return next((a for a in req.actions if a.details and a.details.operation=="finish"),req.actions[0])
        if kind==16:
            trigger=next((a for a in req.actions if a.kind=="activate" and any(codes.get(r)==71413901 for r in a.card_refs)),None)
            if trigger is not None:return trigger
        if kind==11:
            attack_pending=self.cursor<len(self.plan) and self.plan[self.cursor]["kind"]=="attack" and self.plan[self.cursor]["player"]==req.observation.observer
            preferred=6 if attack_pending else 7
            return next((a for a in req.actions if a.kind=="pass" and a.value==preferred),req.actions[0])
        return next((a for a in req.actions if a.kind=="pass"),req.actions[0])


def run_protocol_case(root, name, *, preference="first", replay=None, complete=False, budget_seconds=30):
    if name not in REQUIRED:
        raise ContractError("invalid bounded protocol case")
    case=json.loads(CASES_PATH.read_text())["cases"][name]
    return run_configured_case(root,name,case,REQUIRED[name],preference=preference,replay=replay,
                               complete=complete,budget_seconds=budget_seconds)


def run_configured_case(root,name,case,required,*,preference="first",replay=None,complete=False,budget_seconds=30):
    if preference not in ("first","last") or type(complete) is not bool or not 0<budget_seconds<=120:
        raise ContractError("invalid bounded configured protocol case")
    private=case['profile'].get('adapter_revision')==4
    trace_kind='real-private-selection-audit-v4' if private else 'real-protocol-history-private-audit-v3'
    if replay is not None:
        fields(replay,{"schema_version","kind","name","preference","complete","case","resources","responses","windows","events","final_observations","outcome","result"},{"selection_key_audit_only"})
        if replay["schema_version"]!=1 or replay["kind"]!=trace_kind or replay["name"]!=name or replay["case"]!=case or replay["preference"]!=preference or replay["complete"]!=complete:
            raise ContractError("protocol case replay binding differs")
    started=time.monotonic()
    if replay is not None and private != ('selection_key_audit_only' in replay):
        raise ContractError('private selection replay key/version binding differs')
    with NativeNormalEngine(Path(root),scenario="effect-duel",deck_profile=case["profile"],seed=case["seed_audit_only"],
                            selection_key=replay.get('selection_key_audit_only') if replay else None) as engine:
        if replay is not None and replay["resources"]!=engine.receipt:
            raise ContractError("protocol replay resource versions differ")
        driver=EngineeringDriver(case,engine._rows,preference)
        req=engine.next_decision()
        first=engine._observation(0)
        # Opening checks are audit-only, never passed as policy information.
        if not set(case["required_opening"][0])<={c.card_id for c in first.cards if c.zone=="hand"}:
            raise NativeError("real opening does not meet declared engineering requirements")
        rows,windows,seen=[],[],set()
        case_done=False
        for _ in range(2200):
            if req is None:
                if not case_done: raise NativeError("real duel ended before protocol case completed")
                break
            if time.monotonic()-started>budget_seconds:
                raise NativeError("protocol case budget exhausted; no result claimed")
            if not case_done and driver.cursor==len(driver.plan) and set(required)<=seen and req.prompt.message==11:
                if name!="sort" or req.observation.turn>=3:
                    case_done=True
                    if not complete:break
            action=driver.choose(req,after_case=case_done)
            if req.prompt.message in required:
                seen.add(req.prompt.message)
                # No pending RPS answer is part of the next player's DTO.
                if req.prompt.message==132 and req.observation.observer==1 and any(e.details.message==133 for e in req.observation.public_history):
                    raise NativeError("RPS result exposed before both responses")
                window=json.loads(canonical_json(req.to_dict()))
                window["context"]["run_id"]="private-replay-audit"
                if req.prompt.message==142:
                    # Entire public catalogue can be large; keep its digest and
                    # exact chosen ID, not a truncated pretend candidate list.
                    window={"request_sha256":request_digest(req),"message":142,"candidate_count":len(req.actions),"chosen_card_id":action.value}
                windows.append({"message":req.prompt.message,"request":window,"chosen_action":action.action_id,
                                "chosen_value":action.value,"chosen_refs":list(action.card_refs)})
            raw=engine._responses[action.action_id]
            row={"player":req.observation.observer,"message":req.prompt.message,"request_sha256":request_digest(req),
                 "action_id":action.action_id,"wire_response_audit_only":{"bytes_hex":raw.hex()} if isinstance(raw,bytes) else {"integer":raw}}
            if replay is not None and (len(rows)>=len(replay["responses"]) or row!=replay["responses"][len(rows)]):
                raise NativeError("protocol replay response/request diverged")
            rows.append(row)
            engine.submit(ActionSelection(req.context.run_id,req.duel_id,req.decision_id,action.action_id))
            req=engine.next_decision()
        else:
            raise NativeError("protocol decision budget exhausted")
        if not case_done or set(required)-seen:
            raise NativeError("declared actual core prompts not reached")
        final=[]
        for p in (0,1):
            obs=engine._observation(p)
            if any(c.card_id is not None or c.owner is not None for c in obs.cards if c.visibility=="hidden"):
                raise NativeError("hidden identity leaked")
            # Typed reconstruction checks public fields, never raw trace.
            obs_dict=json.loads(canonical_json(asdict(obs)))
            if Observation.from_dict(obs_dict)!=obs:
                raise NativeError("public observation round trip differs")
            final.append(obs_dict)
        if final[0]["public_history"]!=final[1]["public_history"]:
            raise NativeError("public histories differ by observer")
        messages=sorted({e["kind"] for e in engine.events})
        result={"actual_prompts":sorted(seen),"plan_completed":driver.cursor==len(driver.plan),"natural_terminal":engine.outcome is not None,
                "turns":engine.turn,"life_points":engine.life_points,"public_events":len(engine._public_history),
                "public_histories_equal":True,"hidden_identity_isolated":True,"scripts":sorted(engine.loaded_scripts),"callback_errors":len(engine.callback_errors)}
        trace={"schema_version":1,"kind":trace_kind,"name":name,"preference":preference,"complete":complete,
               "case":case,"resources":engine.receipt,"responses":rows,"windows":windows,"events":engine.events,
               "final_observations":final,"outcome":engine.outcome,"result":result}
        if engine.private_actions:trace['selection_key_audit_only']=engine._selection_seed
        if replay is not None and trace!=replay:
            raise NativeError("protocol replay events/history/result diverged")
        return {"ok":True,"name":name,"elapsed_seconds":time.monotonic()-started,"trace_sha256":digest(trace),"messages":messages,"result":result},trace
