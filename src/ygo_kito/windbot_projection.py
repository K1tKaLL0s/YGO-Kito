"""Host-only, recipient-filtered projection of the normal core message API.

The Python library proxy does not alter CDLL functions, ABI or response handling.
It parses each already returned bounded message once, retaining named legal facts
only. Unsupported history fails closed; this is not a general LAN/core adapter.
"""
from copy import deepcopy
from contextlib import contextmanager
import ctypes
from pathlib import Path
import struct

from .build_contracts import digest
from .native import NativeNormalEngine
from .native_protocol import NativeError, Reader
from .contracts import ActionSelection, LegalAction, Versions, validate_selection
from .opponent_pool import FrozenOpponent
from .validation import ContractError, integer
from .windbot_room import WindBotMessage, WindBotSlot, WindBotTransportFrame, WindBotUnsupported

_PROMPTS = {10,11,12,13,14,15,16,18,19,20,22,23,24,25,26,132,140,141,142,143}
_ZONES = {"hand":2,"monster":4,"spell_trap":8,"graveyard":16,"banished":32,"extra":64}
_SCALARS = ((1,"code"),(2,"position"),(4,"alias"),(8,"type"),(16,"level"),
            (32,"rank"),(64,"attribute"),(128,"race"),(256,"attack"),(512,"defense"),
            (1024,"base_attack"),(2048,"base_defense"),(0x40000,"owner"),
            (0x80000,"status"),(0x200000,"lscale"),(0x400000,"rscale"),
            (0x800000,"link"))
_FLAGS = sum(bit for bit,_ in _SCALARS)


def _public(slot):
    return bool(slot[1]&128) or slot[1] == 16 or slot[1] in (4,8,32,64) and bool(slot[3]&5) or slot[1] in (4,8) and bool(slot[3]&128)


def _slot(raw):
    p,z,s,pos = raw
    if p not in (0,1) or z not in (0,1,2,4,8,16,32,64,132,136,192):
        raise WindBotUnsupported("transport does not support this location/material transition")
    return (p,z,s,pos)


class _Aliases:
    """Local placeholders, independent of a hidden vector's original order."""
    def __init__(self,count=0,*,own=False):
        self.own=own;self.serial=count
        self.native=list(range(count));self.local=list(range(count));self.known={};self.locked=set()

    def index(self,native,*,known=None,lock=False):
        if not 0<=native<len(self.native):raise WindBotUnsupported('alias source is outside its tracked vector')
        token=self.native[native]
        already_locked=token in self.locked
        if known is not None and not self.own and token not in self.known and token not in self.locked:
            self.index(native,lock=True);token=self.native[native]
        if known is not None:self.known[token]=known
        if known is not None and not lock and not already_locked:self.locked.discard(token)
        if not self.own and lock and token not in self.known and token not in self.locked:
            candidate=next((t for t in reversed(self.local) if t not in self.known and t not in self.locked),None)
            if candidate is None:raise WindBotUnsupported('no independent anonymous placeholder remains')
            other=self.native.index(candidate)
            self.native[native],self.native[other]=candidate,token;token=candidate
        if lock:self.locked.add(token)
        return self.local.index(token)

    def remove(self,native,*,public=False):
        if not 0<=native<len(self.native):raise WindBotUnsupported('alias removal is outside its vector')
        token=self.native[native]
        if not self.own and not public and token in self.known:
            raise WindBotUnsupported('hidden removal cannot use a previously identified native slot')
        seq=self.index(native,lock=not public)
        token=self.native.pop(native);self.local.remove(token)
        self.known.pop(token,None);self.locked.discard(token)
        return seq

    def insert(self,native,*,known=None):
        if not 0<=native<=len(self.native):raise WindBotUnsupported('alias insertion is outside its vector')
        token=self.serial;self.serial+=1;self.native.insert(native,token)
        self.local.insert(native if self.own else len(self.local),token)
        if known is not None:self.known[token]=known
        return self.local.index(token)

    def shuffle(self,codes,*,full):
        if full:
            if len(codes)!=len(self.native):raise WindBotUnsupported('shuffle count differs from tracked vector')
            self.known={};self.locked=set()
            if self.own:
                self.local=list(self.native)
                for t,c in zip(self.native,codes):
                    if c:self.known[t]=c&0x7fffffff
            else:
                # Only published IDs are used, never hidden codes or their rank.
                for t,c in zip(self.native,codes):
                    if c&0x80000000:self.known[t]=c&0x7fffffff
                self.local=sorted(self.native,key=lambda t:(t in self.known,self.known.get(t,0),t))
        else:
            # Extra shuffle changes only facedown entries. A locked unknown
            # material host cannot be silently reassociated across that shuffle.
            if self.locked:raise WindBotUnsupported('extra shuffle with a bound anonymous object is unsupported')
        return tuple(self.known.get(t,0) for t in self.local)


class ProjectionJournal:
    """One fixed recipient's ordered facts, starting before the first draw.

    Anonymous removals use local placeholders, not native hidden sequences.
    Published identities get local aliases; hidden removals after identification
    fail when they would need information absent from the legal player contract.
    """
    def __init__(self, observer, *, deck_counts, extra_counts=(0,0)):
        integer(observer,"projection observer",0,1)
        if len(deck_counts)!=2 or len(extra_counts)!=2:
            raise ContractError("two initial deck/extra counts required")
        self.observer=observer
        self.deck_counts=[integer(n,"initial deck count",40,60) for n in deck_counts]
        self.extra_counts=[integer(n,"initial extra count",0,15) for n in extra_counts]
        self.hand_counts=[0,0]
        self.aliases={(p,z):_Aliases(0 if z==2 else self.extra_counts[p],own=p==observer)
                      for p in (0,1) for z in (2,64)}
        self.messages=[WindBotMessage(4,dict(player_type=observer,duel_rule=5,life_points=(8000,8000),
                         deck_counts=tuple(self.deck_counts),extra_counts=tuple(self.extra_counts)))]
        self.counters={}; self.targets={}; self.equips={}
        self.capture=None
        self.failed=False

    def _emit(self,kind,**value):
        if len(self.messages)>=4000:
            raise WindBotUnsupported("recipient event journal exceeds bounded frame")
        self.messages.append(WindBotMessage(kind,value))

    def _visible_slot(self,slot):
        p,z,s,pos=_slot(slot)
        if z==1:
            return (p,z,0,pos)  # no original deck index crosses the boundary
        base=z&127
        if base in (2,64):
            s=self.aliases[(p,base)].index(s,lock=bool(z&128) or p!=self.observer)
        return (p,z,s,pos)

    def consume(self,data):
        """Parse a local ephemeral byte string; never store it or forward it."""
        if self.failed:
            raise WindBotUnsupported("projection journal already failed closed")
        try:
            r=Reader(data)
            while r.offset<len(data):
                kind=r.u8()
                if kind in _PROMPTS:
                    self.capture=self._prompt(kind,Reader(r.data[r.offset:]))
                    return  # the original adapter validates/consumes the prompt
                self._event(kind,r)
        except (NativeError,ContractError,ValueError,IndexError,struct.error):
            self.failed=True
            raise

    def _prompt(self,kind,r):
        # These flags were offered to this exact chooser, not inferred from cards.
        if kind==23:
            r.u8()  # sum mode precedes player
        player=r.u8()
        if player not in (0,1):raise WindBotUnsupported("invalid prompt recipient")
        facts={}; index=0
        if kind==10:
            index=r.u8(); r.take(index*11)
            direct={}
            for _ in range(r.u8()):
                r.take(7); value=r.u8()
                if value not in (0,1):raise WindBotUnsupported("unknown direct-attack flag")
                direct[f"choice-{index}"]=bool(value);index+=1
            facts["direct_attack"]=direct
        elif kind==11:
            modes={}
            for mode in range(6):
                for _ in range(r.u8()):
                    r.take(11 if mode==5 else 7)
                    if mode in (3,4):modes[f"choice-{index}"]=mode
                    index+=1
            facts["idle_set_modes"]=modes
        elif kind==16:
            count,special=r.u8(),r.u8()
            facts["chain_special_count"]=special
            facts["chain_hints"]=(r.u32(),r.u32())
            chain={}
            for i in range(count):
                flag,forced=r.u8(),r.u8()
                if forced not in (0,1):raise WindBotUnsupported("unknown chain forced flag")
                r.take(12)
                chain[f"choice-{i}"]={"flag":flag,"forced":bool(forced)}
            facts["chain"]=chain
        elif kind==19:
            facts["position_card_id"]=r.u32()
        elif kind==20:
            r.take(3); weights={}
            for _ in range(r.u8()):
                r.u32();p,z,s,w=r.take(4)
                if p!=player or z!=4 or not w:raise WindBotUnsupported("unsupported tribute facts")
                weights[f"p{p}.monster.{s}"]=w
            facts["tribute_weights"]=weights
        elif kind==22:
            r.u16();r.u16();caps={}
            for _ in range(r.u8()):
                r.u32();p,z,s=r.take(3);cap=r.u16()
                if p not in (0,1) or z not in (4,8) or not cap:
                    raise WindBotUnsupported("unsupported counter allocation facts")
                ref=f"p{p}.{'monster' if z==4 else 'spell_trap'}.{s}"
                if ref in caps:raise WindBotUnsupported("duplicate counter candidate")
                caps[ref]=cap
            facts["counter_caps"]=caps
        elif kind==142:
            facts["declaration_opcodes"]=tuple(r.u32() for _ in range(r.u8()))
        return kind,player,facts

    def _event(self,k,r):
        if k==2:
            hint,p,value=r.u8(),r.u8(),r.u32()
            if p not in (0,1):raise WindBotUnsupported("invalid hint recipient")
            if p==self.observer or hint in (10,11):self._emit(k,hint=hint,player=p,value=value)
        elif k==40:self._emit(k,player=r.u8())
        elif k==41:self._emit(k,phase=r.u16())
        elif k==5:self._emit(k,winner=r.u8(),reason=r.u8())
        elif k==90:
            p,n=r.u8(),r.u8()
            if p not in (0,1) or n>self.deck_counts[p]:raise WindBotUnsupported("invalid draw counts")
            codes=tuple(r.u32() for _ in range(n))
            for c in codes:
                self.aliases[(p,2)].insert(self.hand_counts[p],known=c&0x7fffffff if p==self.observer or c&0x80000000 else None)
                self.hand_counts[p]+=1
            self.deck_counts[p]-=n
            self._emit(k,player=p,card_ids=tuple(c if p==self.observer or c&0x80000000 else 0 for c in codes))
        elif k==50:
            code,a,b,reason=r.u32(),_slot(r.take(4)),_slot(r.take(4)),r.u32()
            if a[1]==b[1]==1:return
            public=_public(a) or _public(b)
            visible=public or a[0]==self.observer and a[1] not in (0,1) or b[0]==self.observer and b[1] not in (0,1)
            projected=[]
            for old,slot in ((True,a),(False,b)):
                p,z,s,pos=slot
                if z==2:
                    if old and not 0<=s<self.hand_counts[p]:raise WindBotUnsupported("hand source differs from journal")
                    aliases=self.aliases[(p,z)]
                    if old:
                        if p!=self.observer and aliases.known and not _public(slot):
                            raise WindBotUnsupported('identified opponent hand continuity is ambiguous after hidden removal')
                        s=aliases.remove(s,public=_public(slot))
                    else:s=aliases.insert(s,known=code if visible else None)
                    self.hand_counts[p]+= -1 if old else 1
                elif z==1:
                    s=0;self.deck_counts[p]+= -1 if old else 1
                elif z==64:
                    aliases=self.aliases[(p,z)]
                    s=aliases.remove(s,public=_public(slot)) if old else aliases.insert(s,known=code if visible else None)
                    self.extra_counts[p]+= -1 if old else 1
                elif z&128:
                    s=self._visible_slot(slot)[2]
                projected.append((p,z,s,pos))
            relocation=a[1] in (4,8) and b[1] in (4,8)
            for mapping in (self.counters,self.targets,self.equips):
                prior=mapping.pop(a[:3],None)
                mapping.pop(b[:3],None)
                if relocation and prior is not None:mapping[b[:3]]=prior
            for key,targets in self.targets.items():
                self.targets[key]={b if relocation and target[:3]==a[:3] else target for target in targets
                                   if relocation or target[:3]!=a[:3]}
            for key,target in tuple(self.equips.items()):
                if target[:3]==a[:3]:
                    if relocation:self.equips[key]=b
                    else:del self.equips[key]
            self._emit(k,card_id=code if visible else 0,previous=projected[0],current=projected[1],reason=reason)
        elif k in (60,62,64):
            code,slot=r.u32(),_slot(r.take(4))
            self._emit(k,card_id=code if _public(slot) or slot[0]==self.observer else 0,slot=self._visible_slot(slot))
        elif k in (61,63,65,74,112,113,114):self._emit(k)
        elif k==53:
            code=r.u32();p,z,s,old,new=r.take(5)
            slot=self._visible_slot((p,z,s,new))
            self._emit(k,card_id=code if p==self.observer or (old|new)&5 else 0,
                       player=p,location=z,sequence=slot[2],previous=old,current=new)
        elif k==70:
            code,slot=r.u32(),self._visible_slot(r.take(4))
            p,z,s,description,link=r.u8(),r.u8(),r.u8(),r.u32(),r.u8()
            if z in (1,2,64) and p!=self.observer:raise WindBotUnsupported("chain source needs unsupported private-zone aliases")
            self._emit(k,card_id=code,slot=slot,chain_location=(p,z,0 if z==1 else s),description=description,link=link)
        elif k in (71,72,73,75,76):self._emit(k,link=r.u8())
        elif k in (91,92,94,100):self._emit(k,player=r.u8(),amount=r.u32())
        elif k in (93,96,97):
            a,b=self._visible_slot(r.take(4)),self._visible_slot(r.take(4))
            if k==93:self.equips[a[:3]]=b
            elif k==96:self.targets.setdefault(a[:3],set()).add(b)
            else:self.targets.setdefault(a[:3],set()).discard(b)
            self._emit(k,first=a,second=b)
        elif k in (101,102):
            counter,p,z,s,count=r.u16(),r.u8(),r.u8(),r.u8(),r.u16()
            slot=self._visible_slot((p,z,s,0));values=self.counters.setdefault(slot[:3],{})
            new=values.get(counter,0)+(count if k==101 else -count)
            if not 0<=new<=65535:raise WindBotUnsupported("counter event history is incomplete")
            values[counter]=new
            self._emit(k,counter_type=counter,player=p,location=z,sequence=slot[2],count=count)
        elif k==32:
            p=r.u8()
            if p not in (0,1):raise WindBotUnsupported('invalid shuffle player')
            self._emit(k,player=p)
        elif k in (33,39):
            p,count=r.u8(),r.u8();codes=tuple(r.u32() for _ in range(count))
            if p not in (0,1):raise WindBotUnsupported('invalid shuffle player')
            aliases=self.aliases[(p,2 if k==33 else 64)]
            if k==33:
                local=aliases.shuffle(codes,full=True)
                self._emit(k,player=p,card_ids=tuple(c&0x7fffffff for c in codes) if p==self.observer else local)
            else:
                aliases.shuffle(codes,full=False)
                self._emit(k,player=p,card_ids=tuple(c&0x7fffffff if p==self.observer else 0 for c in codes))
        elif k==31:
            viewer,skip,count=r.u8(),r.u8(),r.u8()
            cards=[];rows=[]
            for _ in range(count):
                code,p,z,s=r.u32(),r.u8(),r.u8(),r.u8()
                if not code or p not in (0,1) or z not in (2,4,8,16,32,64):
                    raise WindBotUnsupported('private deck confirmation has no order-free exact LAN representation')
                rows.append((code,p,z,s))
            for code,p,z,s in sorted(rows,key=lambda row:(row[1],row[2],row[0])):
                if z in (2,64):s=self.aliases[(p,z)].index(s,known=code)
                cards.append(dict(card_id=code,controller=p,location=z,sequence=s))
            if viewer not in (0,1) or skip not in (0,1):raise WindBotUnsupported('invalid public confirmation flags')
            self._emit(k,player=viewer,skip_panel=skip,cards=cards)
        elif k==110:self._emit(k,first=self._visible_slot(r.take(4)),second=self._visible_slot(r.take(4)))
        elif k==111:
            a=self._visible_slot(r.take(4));aa,ad=struct.unpack('<ii',r.take(8));av=r.u8()
            b=self._visible_slot(r.take(4));ba,bd=struct.unpack('<ii',r.take(8));bv=r.u8()
            self._emit(k,attacker=a,attacker_attack=aa,attacker_defense=ad,attacker_destroyed=av,
                       defender=b,defender_attack=ba,defender_defense=bd,defender_destroyed=bv)
        else:
            raise WindBotUnsupported(f"transport event {k} has no exact recipient projection")


class _ProjectionLibrary:
    """Python delegation only; original CDLL function attributes stay untouched."""
    def __init__(self,original,journal):self.original,self.journal=original,journal
    def __getattr__(self,name):return getattr(self.original,name)
    def get_message(self,handle,buffer):
        length=self.original.get_message(handle,buffer)
        if not 0<=length<=min(len(buffer),65536):raise NativeError("native message exceeded buffer")
        self.journal.consume(bytes(buffer[:length]))
        return length


def _query_visible(engine,card,slot,journal,*,native_sequence=None):
    """Fixed-size documented scalar query; never query a hidden card or deck."""
    if card.card_id is None: return {"sequence":slot.sequence}
    if card.zone=='hand' and card.controller!=journal.observer:
        # A remembered ConfirmCards identity does not authorize current hidden
        # hand stats. RefreshHand in the pinned server masks those full records.
        return {'sequence':slot.sequence,'code':card.card_id,'owner':card.owner}
    if card.visibility not in ("observer","public") or slot.location==1:
        raise WindBotUnsupported("only independently visible identities may be queried")
    buffer=(ctypes.c_uint8*84)()
    query_sequence=slot.sequence if native_sequence is None else native_sequence
    length=engine.lib.query_card(engine.handle,slot.controller,slot.location,query_sequence,_FLAGS,buffer,0)
    expected=8+4*(len(_SCALARS)+1)  # QUERY_LINK writes rating AND marker
    if length!=expected or length>len(buffer):raise WindBotUnsupported("visible scalar query length differs")
    r=Reader(bytes(buffer[:length]))
    if r.u32()!=length or r.u32()!=_FLAGS:raise WindBotUnsupported("visible scalar query schema differs")
    value={"sequence":slot.sequence}
    for _,name in _SCALARS:
        raw=r.u32()
        value[name]=raw-(1<<32) if name in ("attack","defense","base_attack","base_defense") and raw&(1<<31) else raw
        if name=="link":value["link_marker"]=r.u32()
    if value["code"]!=card.card_id or value["owner"]!=card.owner:
        raise WindBotUnsupported("query identity/owner differs from the legal observation")
    p,z,s,pos=struct.unpack('<BBBB',struct.pack('<I',value['position']))
    if (p,z,s)!=(slot.controller,slot.location,query_sequence):raise WindBotUnsupported("query location differs")
    if card.position is not None and pos&15!=card.position:
        raise WindBotUnsupported('query position differs from legal observation')
    value["position"]=pos
    key=(slot.controller,slot.location,slot.sequence)
    value["counters"]=[{"type":k,"count":v} for k,v in sorted(journal.counters.get(key,{}).items()) if v]
    value["targets"]=sorted(journal.targets.get(key,()))
    if key in journal.equips:value["equip"]=journal.equips[key]
    return value


class WindBotProjectionEngine(NativeNormalEngine):
    """Normal host engine with an explicit fixed-seat transport projection.

    The host calls transport_frame for its currently pending bot request, then
    submits the room's selected existing action through inherited submit/guard.
    It must not discard a frame after sending it or reuse one for a new window.
    """
    def __init__(self,*args,observer,**kwargs):
        integer(observer,"projection observer",0,1)
        profile=kwargs.get("deck_profile")
        if not isinstance(profile,dict) or profile.get("adapter_revision") not in (3,4,5):
            raise WindBotUnsupported("transport requires an explicit modern effect-duel profile")
        super().__init__(*args,**kwargs)
        install_projection(self,observer=observer)

    def transport_frame(self,request,*,state_version):
        return transport_frame(self,request,state_version=state_version)


def install_projection(engine,*,observer):
    """Attach to an unopened normal/period host without changing its class/ABI."""
    if not isinstance(engine,NativeNormalEngine) or not engine.modern_actions:
        raise WindBotUnsupported("projection needs an existing modern normal/period host")
    if engine.window or engine.pending is not None or engine.closed or hasattr(engine,'_transport'):
        raise WindBotUnsupported("projection must start before the first normal host decision")
    engine._transport=ProjectionJournal(observer,deck_counts=tuple(map(len,engine.player_decks)),
                                      extra_counts=tuple(map(len,engine.player_extras)))
    engine.lib=_ProjectionLibrary(engine.lib,engine._transport)
    engine._transport_sent=set()
    return engine


def transport_frame(self,request,*,state_version):
    """Produce a single-use frame for the exact pending host-owned request."""
    journal=self._transport
    if journal.failed:raise WindBotUnsupported("projection journal failed closed")
    if request is not self.pending or request.observation.observer!=journal.observer or request.context.seed is not None:
        raise WindBotUnsupported("transport accepts only the current fixed-seat legal request")
    key=digest(request.to_dict())
    if key in self._transport_sent:raise WindBotUnsupported("transport frame was already consumed")
    if journal.capture is None or (journal.capture[0],journal.capture[1])!=(request.prompt.message,journal.observer):
        raise WindBotUnsupported("transport prompt capture differs from the legal request")
    if tuple(journal.hand_counts)!=request.observation.hand_counts or tuple(journal.deck_counts)!=request.observation.deck_counts:
        raise WindBotUnsupported("continuous transport counts differ from legal observation")
    slots=[];grouped={};by_ref={};materials=[]
    extra_reverse={ref:(p,s) for (p,s),ref in getattr(self,"_extra_refs",{}).items()}
    for card in sorted(request.observation.cards,key=lambda c:(c.controller,c.zone,c.card_id or 0,c.ref)):
        if card.zone=="overlay":materials.append(card);continue
        if card.zone=="extra":
            if card.visibility=="hidden":continue
            if card.ref not in extra_reverse:raise WindBotUnsupported("visible extra has no registered exact slot")
            p,s=extra_reverse[card.ref]
        else:
            try:s=int(card.ref.rsplit('.',1)[1]);p=card.controller
            except (ValueError,IndexError) as exc:raise WindBotUnsupported("card lacks exact visible location") from exc
        native_sequence=s
        if card.zone in ('hand','extra'):
            s=journal.aliases[(p,_ZONES[card.zone])].index(s,known=card.card_id if card.visibility!='hidden' else None)
        slot=WindBotSlot(card.ref,p,_ZONES[card.zone],s)
        slots.append(slot);by_ref[card.ref]=slot
        grouped.setdefault((p,slot.location),{})[s]=_query_visible(self,card,slot,journal,native_sequence=native_sequence)
    reverse_material={ref:(p,z,s,sub) for (p,z,s,sub),ref in getattr(self,'_material_refs',{}).items()}
    for card in sorted(materials,key=lambda c:reverse_material.get(c.ref,(-1,-1,-1,-1))):
        if card.ref not in reverse_material or card.attached_to not in by_ref:
            raise WindBotUnsupported('visible material has no registered legal host')
        p,z,s,sub=reverse_material[card.ref];host=by_ref[card.attached_to]
        if (p,z,s)!=(host.controller,host.location,host.sequence):
            raise WindBotUnsupported('material host address differs from public host')
        slots.append(WindBotSlot(card.ref,p,z|128,host.sequence,sub))
        record=grouped[(p,z)][host.sequence]
        ids=record.setdefault('overlay',[])
        if sub!=len(ids):raise WindBotUnsupported('public material order is incomplete')
        ids.append(card.card_id)
    virtual_counts={}
    for choice in (*request.search_choices,*request.selection_choices):
        p=getattr(choice,'controller',getattr(choice,'owner',None))
        zone=getattr(choice,'zone','deck');z=1 if zone=='deck' else _ZONES.get(zone)
        if z not in (1,2,16,32,64):raise WindBotUnsupported('temporary choice has no safe virtual location')
        group_key=(p,z)
        if group_key not in virtual_counts:
            virtual_counts[group_key]=request.observation.deck_counts[p] if z==1 else request.observation.hand_counts[p] if z==2 else journal.extra_counts[p] if z==64 else self._count(p,z)
        ordinal=virtual_counts[group_key]
        if ordinal>255:raise WindBotUnsupported('window-local virtual choice exceeds LAN sequence')
        slots.append(WindBotSlot(choice.ref,p,z,ordinal));virtual_counts[group_key]+=1
    messages=list(journal.messages)
    # All object creation events precede updates. Empty fixed field slots are
    # represented by a length-4 record; no query creates a missing object.
    for p in (0,1):
        for z in (2,4,8,16,32,64):
            data=grouped.get((p,z),{})
            count=7 if z==4 else 8 if z==8 else journal.hand_counts[p] if z==2 else journal.extra_counts[p] if z==64 else self._count(p,z)
            records=[data.get(s,{"sequence":s}) for s in range(count)]
            messages.append(WindBotMessage(6,{"player":p,"location":z,"cards":records}))
    facts=deepcopy(journal.capture[2])
    action_ids={a.action_id for a in request.actions}
    for name in ("idle_set_modes","direct_attack","chain"):
        if set(facts.get(name,{}))-action_ids:raise WindBotUnsupported("captured prompt actions differ")
    frame=WindBotTransportFrame(journal.observer,key,state_version,tuple(messages),tuple(slots),facts)
    self._transport_sent.add(key);journal.messages.clear()
    return frame

class WindBotOpponent(FrozenOpponent):
    """Explicit audited host adapter; the registry supplies immutable validators.

    ``runtime_validator()`` verifies pinned sources, compilation/resource audit
    and current physical seals. ``room_factory(opponent)`` is a context manager
    yielding an actually launched/accepted room. There is no default validator,
    process, fixture fallback, provider or alternate opponent.
    """
    def __init__(self,*,root,profile,seat,versions,binding,runtime_validator,room_factory):
        integer(seat,'WindBot seat',0,1)
        if not callable(runtime_validator) or not callable(room_factory):
            raise ContractError('audited runtime validator and managed room factory are required')
        self.root=Path(root).resolve();self.seat=seat
        self.profile=deepcopy(profile);self._profile=self.profile
        self.versions=versions if isinstance(versions,Versions) else Versions.from_dict(versions)
        self.binding=deepcopy(binding)
        if not isinstance(self.binding,dict) or self.binding.get('profile_sha256')!=digest(self.profile):
            raise ContractError('WindBot binding must pin the actual host profile')
        self._binding_sha256=digest(self.binding)
        self._runtime_validator,self._room_factory=runtime_validator,room_factory
        self._runtime_identity=(self.root,self.seat,deepcopy(self.versions),runtime_validator,room_factory)
        self.policy=self;self._engine=None;self._room=None;self._state=0
        self.historical_rules_verified=False;self.official_sources_verified=False
        self.assert_runtime(self.root,self.profile,1-seat)

    def assert_runtime(self,root,profile,actor_seat,**kwargs):
        if kwargs:raise ContractError('WindBot physical runtime validation cannot be disabled')
        fixed_root,fixed_seat,fixed_versions,validator,room_factory=self._runtime_identity
        if (Path(root).resolve()!=self.root or actor_seat!=1-self.seat or
                digest(profile)!=self.binding['profile_sha256'] or digest(self.binding)!=self._binding_sha256 or
                digest(self.profile)!=self.binding['profile_sha256'] or digest(self._profile)!=self.binding['profile_sha256'] or
                (self.root,self.seat,self.versions)!=(fixed_root,fixed_seat,fixed_versions) or
                self._runtime_validator is not validator or self._room_factory is not room_factory or self.policy is not self):
            raise ContractError('frozen WindBot profile/seat/binding changed')
        self._runtime_validator()

    @contextmanager
    def managed_engine_factory(self,base_factory,root,**options):
        if self._engine is not None:raise ContractError('WindBot opponent already has an active game')
        self.assert_runtime(root,options.get('deck_profile'),1-self.seat)
        with base_factory(root,**options) as engine:
            install_projection(engine,observer=self.seat)
            if engine.context.versions!=self.versions:raise ContractError('WindBot host versions differ from binding')
            with self._room_factory(self) as room:
                if room.observer!=self.seat or room.duel_rule!=5:
                    raise ContractError('managed WindBot room seat/rule differs')
                self._engine,self._room=engine,room
                try:yield engine
                finally:self._engine=None;self._room=None

    def choose(self,request):
        self.assert_runtime(self.root,self.profile,1-self.seat)
        if self._engine is None or self._room is None or self._engine.pending is not request:
            raise ContractError('WindBot policy requires its current managed host request')
        if request.context.versions!=self.versions or request.observation.observer!=self.seat:
            raise ContractError('WindBot policy request versions/seat differ')
        self._state+=1
        frame=transport_frame(self._engine,request,state_version=f'windbot-{self._state}')
        action=self._room.choose(request,frame)
        if not isinstance(action,LegalAction) or action not in request.actions:
            raise ContractError('WindBot room did not return an existing exact legal action')
        validate_selection(request,ActionSelection(request.context.run_id,request.duel_id,request.decision_id,action.action_id))
        return action

    def select(self,request):
        action=self.choose(request)
        return ActionSelection(request.context.run_id,request.duel_id,request.decision_id,action.action_id)
