"""CPU real-script/replay proof and safe common-public projection export.

Raw private replay files remain under output/private. Only the whitelist-based
output/public directory is intended for repository review/publication.
"""
import hashlib
import re
from pathlib import Path
import platform
import resource
import time

from .contracts import DecisionRequest,PublicEvent
from .duel_model import FEATURE_VERSION
from .knowledge_cases import CASES_PATH,REQUIRED,run_knowledge_case
from .native_assets import verify_resources
from .training_runner import atomic_json,file_receipt
from .validation import ContractError


def _calls(source,pattern):
    """Bounded lexical argument extraction for this pinned, audited call set."""
    for match in re.finditer(pattern,source):
        depth,start,args=1,match.end(),[]
        for end in range(start,len(source)):
            char=source[end]
            if char=='(':depth+=1
            elif char==')':depth-=1
            if char==',' and depth==1 or depth==0:
                args.append(source[start:end].strip());start=end+1
            if depth==0:break
        else:raise ContractError('unterminated audited SelectField call')
        yield source.count('\n',0,match.start())+1,args


def audit_place_calls(root):
    """Source evidence of the missing MSG18 multi-zone route, NOT a real duel."""
    base=Path(root)/'engine-src';lua=[];core=[]
    for path in sorted((base/'scripts').rglob('*.lua')):
        text=path.read_text()
        for line,args in _calls(text,r'Duel\.SelectField\s*\('):
            if len(args)<5:raise ContractError('unexpected SelectField source arity')
            lua.append({'path':str(path.relative_to(base)),'line':line,'file_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                        'arity':len(args),'count_expression':args[1],'message':18 if len(args)>=6 else 24})
    for path in sorted((base/'core').glob('*.cpp')):
        text=path.read_text()
        for line,args in _calls(text,r'add_process\s*\(\s*(?=PROCESSOR_SELECT_PLACE\b)'):
            if len(args)!=7:raise ContractError('unexpected SelectPlace core arity')
            core.append({'path':str(path.relative_to(base)),'line':line,'file_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                         'count_expression':args[6]})
    bridge=base/'core/libduel.cpp'
    native_single=bool(core) and all(c['count_expression'] in ('0','1') for c in core)
    lua_single=bool(lua) and all(c['count_expression']=='1' for c in lua if c['message']==18)
    return {'kind':'static-pinned-source-call-audit-not-engine-test','core_calls':core,'lua_calls':lua,
            'libduel_bridge_sha256':hashlib.sha256(bridge.read_bytes()).hexdigest(),
            'bridge_review':'duel_select_field: default PROCESSOR_SELECT_DISFIELD; sixth argument switches PROCESSOR_SELECT_PLACE',
            'no_direct_multizone_msg18_call_found':native_single and lua_single,
            'real_msg18_multizone_verified':False,
            'blocker':'Pinned ordinary core calls request 0/1; both six-argument upstream scripts request 1. Multi-zone Lua call uses MSG24. No custom Lua or patched core substituted.'}


def public_projection(trace,raw_receipt):
    """Strict identical PublicEvents only; no decks, responses or private DTOs."""
    left,right=(o['public_history'] for o in trace['final_observations'])
    if left!=right:raise ContractError('public export histories differ')
    for value in left:PublicEvent.from_dict(value)
    value={'schema_version':1,'kind':'common-public-history-projection-not-private-replay',
           'engineering_case':trace['name'],'source_raw_trace_sha256':raw_receipt['sha256'],
           'source_raw_trace_bytes':raw_receipt['bytes'],'replay_verified_in_cloud':True,
           'common_public_history':left,'public_result':{'turns':trace['result']['turns'],'life_points':trace['result']['life_points'],'outcome':trace['outcome']}}
    def check(item):
        if isinstance(item,dict):
            forbidden={'decks','profile','seed','seed_audit_only','selection_key_audit_only','responses','windows','request','final_observations','selection_choices','private_reveals','knowledge_ref'}
            if set(item)&forbidden:raise ContractError('private field in public evidence export')
            for child in item.values():check(child)
        elif isinstance(item,list):
            for child in item:check(child)
    check(value)
    return value


def run_knowledge_acceptance(root,output):
    root,output=Path(root),Path(output)
    if output.exists():raise ContractError('acceptance output must be new; existing private evidence is not overwritten')
    private,public=output/'private',output/'public';private.mkdir(parents=True);public.mkdir()
    wall,cpu=time.monotonic(),time.process_time();results=[];receipts=[]
    runs=[(name,'first',False) for name in REQUIRED]+[(name,'last',False) for name in ('crescent-private','rescue-confirmed')]+[('crescent-private','first',True)]
    for name,preference,complete in runs:
        summary,trace=run_knowledge_case(root,name,preference=preference,complete=complete)
        checked,again=run_knowledge_case(root,name,preference=preference,complete=complete,replay=trace)
        if again!=trace or checked['trace_sha256']!=summary['trace_sha256']:raise ContractError('independent real replay differs')
        path=private/f'{name}-{preference}{"-complete" if complete else ""}.trace.json'
        atomic_json(path,trace);raw_receipt=file_receipt(path,private)
        exported=public/(path.stem.replace('.trace','')+'.public-history.json')
        atomic_json(exported,public_projection(trace,raw_receipt));receipts.append(file_receipt(exported,public))
        # Never copy the internal result wholesale: its loaded-script list can
        # identify unplayed hidden cards. Export only explicit aggregate fields.
        result={'case':name,'preference':preference,'complete':complete,'replay_verified':True,
                'trace_sha256':summary['trace_sha256'],'messages':summary['messages'],
                **{k:summary['result'][k] for k in ('actual_prompts','plan_completed','natural_terminal','turns','life_points',
                                                   'public_events','public_histories_equal','hidden_identity_isolated','callback_errors')}}
        if name in ('crescent-private','rescue-confirmed'):
            w=next(w for w in trace['windows'] if w['message']==15 and w['request']['observation']['observer']==1)
            req=DecisionRequest.from_dict(w['request'])
            known=all(c.card_id is not None and c.knowledge_ref for c in req.selection_choices)
            hidden=all(c.card_id is None and c.knowledge_ref is None for c in req.selection_choices)
            if not req.private_reveals or (name=='crescent-private' and not hidden) or (name=='rescue-confirmed' and not known):
                raise ContractError('actual private confirmation / shuffle knowledge boundary differs')
            result['private_confirmation_retained_without_position']=True
            result['offered_opponent_deck_identity_visible']=name=='rescue-confirmed'
        results.append(result)
    source=hashlib.sha256()
    for path in sorted((Path(__file__).parent).glob('*.py')):
        source.update(path.name.encode()+b'\0'+hashlib.sha256(path.read_bytes()).digest())
    result={'schema_version':1,'kind':'nonpaid-real-private-knowledge-v5-safe-delivery','ok':True,
            'python':platform.python_version(),'implementation_sha256':source.hexdigest(),'feature_version':FEATURE_VERSION,
            'resources':verify_resources(root),'cases_sha256':hashlib.sha256(CASES_PATH.read_bytes()).hexdigest(),
            'cases':results,'public_projections':receipts,'place_source_audit':audit_place_calls(root),
            'measured':{'wall_seconds':time.monotonic()-wall,'process_cpu_seconds':time.process_time()-cpu,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
            'scope':{'real_opponent_deck_selection':True,'real_own_private_deck_msg26':True,'real_previously_public_materials_under_facedown_host':True,
                     'real_msg18_multizone_verified':False,'full_phase_1_delivered':False,'formal_training_ready':False,
                     'competitive_ability_verified':False,'paid_resources_started':False,'external_provider_calls':0},
            'export_boundary':'Only common-public projection and aggregate proof may be published. Raw private audits stay in cloud; previously denied complete JSON upload is not retried.'}
    for rec in receipts:
        raw=(public/rec['path']).read_bytes()
        if len(raw)!=rec['bytes'] or hashlib.sha256(raw).hexdigest()!=rec['sha256']:raise ContractError('saved public receipt differs')
    atomic_json(public/'delivery-proof.json',result)
    return result
