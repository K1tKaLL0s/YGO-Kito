"""Version-limited caller classification plus real MSG24 multi-zone evidence."""
import hashlib
from pathlib import Path
import subprocess

from .build_contracts import digest
from .contracts import DecisionRequest
from .knowledge_acceptance import audit_place_calls
from .native_assets import verify_resources
from .protocol_cases import run_protocol_case
from .validation import ContractError


def classify_sources(root):
    base=Path(root)/'engine-src';audit=audit_place_calls(root);receipt=verify_resources(Path(root))
    expected=receipt['source_commits']['core']
    actual=subprocess.run(['git','-C',str(base/'core'),'rev-parse','HEAD'],check=True,capture_output=True,text=True).stdout.strip()
    changed=subprocess.run(['git','-C',str(base/'core'),'diff','HEAD','--','playerop.cpp','processor.cpp','libduel.cpp'],
                           check=True,capture_output=True).stdout
    if actual!=expected or changed:raise ContractError('place classification requires the unmodified pinned core source')
    source=(base/'core/playerop.cpp').read_text();bridge=(base/'core/processor.cpp').read_text()
    if ('write_buffer8(count)' not in source or 'select_place(it->step, it->arg1, it->arg2, it->arg3)' not in bridge):
        raise ContractError('pinned count forwarding requires another source audit')
    return {'schema_version':1,'kind':'pinned-source-caller-classification-not-universal-unreachability',
            'source_commits':receipt['source_commits'],'resources':receipt['resources'],'caller_audit':audit,
            'pinned_core_checkout_verified':True,
            'files':{str(p.relative_to(base)):hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (base/'core/playerop.cpp',base/'core/processor.cpp',base/'core/libduel.cpp')},
            'msg18':{'wire_multiple_count_supported':True,'real_multizone_case_verified':False,
                     'current_pinned_ordinary_bo1_multizone_caller_present':not audit['no_direct_multizone_msg18_call_found'],
                     'classification':'multi-count caller absent in these pinned core/scripts; not a claim about other versions or injected scripts',
                     'scope':'ordinary non-tag non-debug BO1 through existing core operations and unmodified shipped Lua entry points'},
            'msg24':{'multiple_source_caller_present':any(c['message']==24 and c['count_expression']!='1' for c in audit['lua_calls']),
                     'real_multizone_case_verified':False}}


def verify_multi_zone(root):
    classification=classify_sources(root);traces=[];proofs=[]
    for preference in ('first','last'):
        summary,trace=run_protocol_case(root,'disable-two',preference=preference)
        checked,again=run_protocol_case(root,'disable-two',preference=preference,replay=trace)
        if again!=trace or checked['trace_sha256']!=summary['trace_sha256']:raise ContractError('MSG24 real replay diverged')
        window=next(w for w in trace['windows'] if w['message']==24);request=DecisionRequest.from_dict(window['request'])
        chosen=next(a for a in request.actions if a.action_id==window['chosen_action'])
        destinations=chosen.details.destinations
        if len(destinations)<2:raise ContractError('no actual MSG24 multi-zone response reached')
        expected=sum(1<<(d.sequence+(16 if d.controller else 0)+(8 if d.zone=='spell_trap' else 0)) for d in destinations)
        observed=[e['details']['value'] for e in trace['final_observations'][0]['public_history'] if e['details']['message']==56]
        if not observed or observed[-1]!=expected:raise ContractError('core field-disabled mask differs from submitted MSG24 zones')
        proofs.append({'preference':preference,'actual_message':24,'zones_selected':len(destinations),
                       'field_disabled_mask':observed[-1],'replay_verified':True,'trace_sha256':digest(trace)})
        traces.append(trace)
    classification['msg24']['real_multizone_case_verified']=True;classification['msg24']['proofs']=proofs
    return classification,traces
