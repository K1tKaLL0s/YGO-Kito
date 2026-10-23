"""Selection DTO projection matching the pinned server's recipient masking.

No deck/hidden identity query is performed. Native response indices and a
controller-only deterministic permutation remain private replay metadata.
"""
from itertools import combinations
from math import comb
import hashlib
import random

from .contracts import ActionDetails, PromptInfo, SelectionChoice
from .native_protocol import DecodedPrompt, NativeError, NativeOption

ZONES={1:'deck',2:'hand',4:'monster',8:'spell_trap',16:'graveyard',32:'banished',64:'extra'}


def decode_selection(kind,r,resolve,obs,seed):
    player=r.u8()
    if player not in (0,1) or player!=obs.observer or seed is None:
        raise NativeError('private selection requires its legal observer and private replay key')
    if kind==15:
        cancelable,minimum,maximum=r.u8(),r.u8(),r.u8()
        finishable=False;groups=[('select',r.u8())]
    else:
        finishable,cancelable,minimum,maximum=r.u8(),r.u8(),r.u8(),r.u8()
        groups=[('add',r.u8())]
    # The pinned core tests this uint8 flag for nonzero (some attack windows
    # send 2), rather than specifying the enum {0,1}.
    if minimum>maximum:
        raise NativeError('invalid native selection limits')
    visible={c.ref:c for c in obs.cards}
    entries=[];locations=set()
    def read_group(operation,count):
        if len(entries)+count>128:
            raise NativeError('private selection candidate budget exceeded')
        for _ in range(count):
            code,c,z,s,sub=r.u32(),r.u8(),r.u8(),r.u8(),r.u8()
            if c not in (0,1) or z not in ZONES and not z&0x80:
                raise NativeError('unknown selection location/controller')
            key=(c,z,s,sub if z&0x80 else None)
            if key in locations:raise NativeError('duplicate native selection candidate')
            locations.add(key)
            zone='overlay' if z&0x80 else ZONES[z]
            ref=None
            if z not in (1,2):
                try:ref=resolve(player,c,z,s,sub if z&0x80 else None)
                except NativeError:pass
            elif z==2:
                ref=f'p{c}.hand.{s}'
            if ref not in visible:ref=None
            if ref is None and z not in (1,2,32,64):
                raise NativeError('unregistered field/material selection; no hidden query fallback')
            # single_duel.cpp masks EVERY opponent candidate code. Existing
            # legal card views can retain already-known identities; raw code
            # alone never upgrades knowledge, including own facedown targets.
            offered=code if z==1 and c==player else None
            if z==1 and c==player and not offered:
                raise NativeError('own deck selection has no offered identity')
            entries.append({'native':len(entries),'operation':operation,'controller':c,'zone':zone,
                            'ref':ref,'offered':offered})
    read_group(*groups[0])
    if kind==26:read_group('remove',r.u8())
    if r.offset!=len(r.data):raise NativeError('trailing private selection payload')
    # Native deck ordering can depend on secret card properties. Anonymous
    # references must not expose that rank. The private key is reproducible for
    # audit replay and never enters a DTO, model, provider or public history.
    rng=random.Random(int.from_bytes(hashlib.sha256(repr(seed).encode()).digest(),'big'))
    hidden=[e for e in entries if e['ref'] is None and e['offered'] is None]
    rng.shuffle(hidden)
    hidden_rank={e['native']:i for i,e in enumerate(hidden)}
    entries.sort(key=lambda e:(e['controller'],e['zone'],e['ref'] is None,
                              e['ref'] or '',e['offered'] or 0,
                              hidden_rank.get(e['native'],0)))
    choices=[]
    for i,e in enumerate(entries):
        if e['ref'] is None:
            e['ref']=f'selection-{i}'
            choices.append(SelectionChoice(e['ref'],e['controller'],e['zone'],
                                           'observer' if e['offered'] else 'hidden',e['offered']))
    options=[]
    if kind==15:
        count=len(entries);top=min(maximum,count)
        if minimum>top or top>63 or sum(comb(count,k) for k in range(minimum,top+1))>50000:
            raise NativeError('selection response/complete enumeration exceeds explicit budget')
        for size in range(minimum,top+1):
            for selected in combinations(entries,size):
                options.append(NativeOption('select',tuple(e['ref'] for e in selected),size,
                                            bytes((size,*(e['native'] for e in selected)))))
    else:
        for e in entries:
            op=e['operation']
            options.append(NativeOption('select',(e['ref'],),int(op=='add'),bytes((1,e['native'])),ActionDetails(operation=op)))
    if finishable or cancelable:
        options.append(NativeOption('pass',(),None,-1,ActionDetails(operation='finish' if finishable else 'cancel')))
    if not options:raise NativeError('empty native selection')
    return DecodedPrompt(player,PromptInfo(kind,minimum,maximum,bool(cancelable),bool(finishable)),tuple(options),selection_choices=tuple(choices))
