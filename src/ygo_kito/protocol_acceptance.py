"""Bounded CPU-only protocol/history acceptance. No model update or provider."""
import hashlib
import json
from pathlib import Path
import platform
import resource
import time

from .protocol_cases import CASES_PATH, REQUIRED, run_protocol_case
from .effect_duel import run_effect_duel
from .training_runner import atomic_json, file_receipt
from .validation import ContractError


def run_protocol_acceptance(root, output):
    output=Path(output).resolve()
    if output.exists():
        raise ContractError("protocol acceptance requires a new output directory; old evidence is preserved")
    output.mkdir(parents=True)
    wall,cpu=time.monotonic(),time.process_time()
    implementation=hashlib.sha256()
    for p in sorted(Path(__file__).parent.glob('*.py')):
        implementation.update(p.name.encode()+b'\0'+hashlib.sha256(p.read_bytes()).digest())
    plans=[(name,'first',False) for name in REQUIRED]
    plans += [(name,'last',False) for name in ('sum-at-least','counter','sort')]
    plans += [('number-equip','first',True)]
    receipts,proofs,resources=[],[],None
    for name,preference,complete in plans:
        proof,trace=run_protocol_case(root,name,preference=preference,complete=complete)
        replayed,again=run_protocol_case(root,name,preference=preference,complete=complete,
                                        replay=json.loads(json.dumps(trace)))
        if trace!=again or proof['trace_sha256']!=replayed['trace_sha256']:
            raise ContractError("independent protocol replay differs")
        if resources is not None and trace['resources']!=resources:
            raise ContractError("protocol suite crossed engine resource versions")
        resources=trace['resources']
        path=output/f'{name}-{preference}{"-complete" if complete else ""}.trace.json'
        atomic_json(path,trace)
        receipt=file_receipt(path,output)
        # Read content, size AND digest back; no local path is called a download.
        if json.loads(path.read_text())!=trace or file_receipt(path,output)!=receipt:
            raise ContractError("saved trace verification differs")
        receipts.append(receipt)
        proofs.append({**proof,'preference':preference,'complete':complete,'replay_verified':True})
    generic_path=CASES_PATH.parent/'effect-history-engineering-v3.json'
    generic_profile=json.loads(generic_path.read_text())
    generic,trace=run_effect_duel(Path(root),generic_profile,seed=3,budget_seconds=30)
    checked,again=run_effect_duel(Path(root),generic_profile,replay=json.loads(json.dumps(trace)),budget_seconds=30)
    if again!=trace or not checked['replay_verified'] or trace['versions']['adapter_schema']!='native-protocol-history-v3':
        raise ContractError('generic effect duel did not retain its revision-3 version or replay')
    path=output/'generic-effect-history-v3.trace.json'
    atomic_json(path,trace)
    receipts.append(file_receipt(path,output))
    if json.loads(path.read_text())!=trace:
        raise ContractError('generic saved replay differs')
    result={'schema_version':1,'kind':'nonpaid-real-protocol-history-v3-acceptance',
            'binding':{'python_implementation_sha256':implementation.hexdigest(),
                       'engineering_cases_sha256':hashlib.sha256(CASES_PATH.read_bytes()).hexdigest(),
                       'generic_profile_sha256':hashlib.sha256(generic_path.read_bytes()).hexdigest(),
                       'resources':resources,'python':platform.python_version()},
            'ok':True,'proofs':proofs,'generic_effect_duel':generic,'trace_receipts':receipts,
            'measured':{'wall_seconds':time.monotonic()-wall,'process_cpu_seconds':time.process_time()-cpu,
                        'parent_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},
            'limits':{'cli_kernel_wall_seconds':120,'per_case_seconds':30,'per_case_decisions':2200,
                      'enumerated_choices':2048,'card_declaration_choices':50000,'sorting_cards':6},
            'scope':{'real_engine':True,'paid_resources_started':False,'provider_calls':0,'parameter_updates':0,
                     'full_phase_1_delivered':False,'formal_training_ready':False,'competitive_ability_verified':False,
                     'pc_compatibility_verified':False,'all_cards_or_all_event_mechanisms_verified':False,
                     'legacy_profiles_keep_history_v1_v2':True,'large_declaration_neural_policy_cap_still_2048':True}}
    atomic_json(output/'proof.json',result)
    return result
