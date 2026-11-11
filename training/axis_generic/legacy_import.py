"""Read-only migration of consumed v7 annotations; no preparation or training entry."""
import copy
import math
import re
import unicodedata

TYPE={'monster': 1, 'spell': 2, 'trap': 4, 'fusion': 64, 'synchro': 8192, 'xyz': 8388608, 'link': 67108864, 'ritual': 128}

def confidence(value):
    if type(value) in (int,float):
        return max(0.,min(1.,float(value))) if math.isfinite(value) else 0.
    return {"high":.95,"medium":.7,"low":.35}.get(value,0.)

def selector_text(text):
    text=str(text or '').replace('「','').replace('」','').strip()
    for word in ('融合怪兽','连接怪兽','仪式怪兽','同调怪兽','超量怪兽','速攻魔法','通常魔法','永续魔法','魔法卡','陷阱卡','暗属性','光属性','怪兽','魔法','陷阱'):
        text=text.replace(word,'')
    return re.sub(r'^[一二三四五六七八九十]+(?=.{2})','',text).strip()

def name_key(text):return re.sub(r'[\s\-—·★☆「」『』・]','',unicodedata.normalize('NFKC',str(text)))

def resolve_plan(plan,rows,construction):
    text=plan.get('primary_plan_text') or '';entities=copy.deepcopy(plan.get('entities') or [])
    # Without structured references, resolve only explicit names in the primary
    # statement among actual construction cards. No role or focal-membership test.
    if not entities and confidence(plan.get('confidence',0))>=.55:
        for code in sorted(construction):
            name=rows[code]['name']
            if len(name)>=2 and name in text:entities.append(dict(surface=name,name_contains=name,kind='actor',type_constraint=None,evidence_quote=name))
    resolved=[];codes=set();missing=[]
    for entity in entities:
        raw=entity.get('name_contains') or entity.get('surface');term=selector_text(raw);kind=entity.get('kind','actor')
        bit=TYPE.get(entity.get('type_constraint'));quick='速攻' in str(raw)
        matches=sorted(c for c in construction if term and name_key(term) in name_key(rows[c]['name']) and (bit is None or rows[c]['type']&bit) and (not quick or rows[c]['type']&0x10000))
        quote=entity.get('evidence_quote') or entity.get('surface') or text
        if matches:codes.update(matches)
        else:missing.append(dict(surface=entity.get('surface'),selector=term,type_constraint=entity.get('type_constraint'),reason='No literal candidate in this construction; aliases/abstract categories may remain unresolved.'))
        resolved.append(dict(kind=kind,codes=matches,evidence_quote=quote,surface=entity.get('surface'),selector=term))
    return dict(codes=codes,entities=resolved,missing=missing,coverage=sum(bool(e['codes']) for e in resolved)/len(resolved) if resolved else 0,
        known=confidence(plan.get('confidence',0))>=.55,confidence=confidence(plan.get('confidence',0)),text=text,
        operation_tags=sorted(set(plan.get('operation_tags',[]))))

def audited_targets(c,original,audit,generic):
    values=list(original['roles']);trust=[v or 0 for v in original['confidence']]
    if confidence(c['primary_plan'].get('confidence'))<.55:values[2:4]=[None,None]
    for i,name in [(2,'core_status'),(3,'support_status')]:
        if audit.get(name)!='supported':values[i]=None
    low=audit.get('low_support_scope_resolution')
    if low and low.get('category')=='supported_low' and confidence(c['primary_plan'].get('confidence'))>=.55:
        values[3]=0;trust[3]=low['confidence']
    for finding in audit.get('axis_generic_findings',[]):
        i=finding['dimension_index']
        if i in (0,1) and finding.get('status')!='supported':values[i]=None
    g=generic[c['case_id']];values[4]=g.get('generic_role');trust[4]=g.get('confidence') or 0
    if not c.get('unit') and values[4] not in (None,0):values[4]=None
    for i in range(5):
        if values[i] is None or trust[i]<.55:values[i]=None;trust[i]=0
        else:values[i]=int(values[i]>=.5)
    return values,trust
