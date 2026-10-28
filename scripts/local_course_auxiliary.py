"""Actual paired goal auxiliaries; original win comparison remains intact."""
import hashlib
import json
from pathlib import Path


POLICY_SHA='e8679b1ba4ebb68bc056e17b1c86bd6008b03574f1bb32d6b06905588c3c7327'


def completed_auxiliary(task,assets,comparison,index,root,base,formal_matches):
    from ygo_kito.build_contracts import digest
    from ygo_kito.model_auxiliary import pack_requests,make_auxiliary_comparison,validate_auxiliary_comparison
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    policy=read(base/'reports/auxiliary-evaluation-v1'/('plan-v2-future32.json' if formal_matches>=32 else 'plan-corrected-future-v1_1.json'))
    expected=POLICY_SHA if formal_matches>=32 else '29a40e8c12143effd5ba60d439717a119a6fdb231ab17ed82a08cd34b8d4b589'
    if policy['plan_sha256']!=expected:raise RuntimeError('Registered future auxiliary policy changed')
    if policy['task_sha256']!=task.sha256:raise RuntimeError('Changed goal requires prospective auxiliary registration')
    output=root/('actual-goal-auxiliary-'+policy['version'].split('-')[-1]+'.json')
    if output.exists():
        value=read(output)
        validate_auxiliary_comparison(task,assets,value)
        if value['original_win_comparison']!=comparison:raise RuntimeError('Auxiliary comparison belongs to different games')
        return value
    inputs=[]
    for game in comparison['games']:
        name=f"candidate-{game['candidate_index']}-seed-{game['seed_audit_only']}-seat-{game['actor_seat']}"
        trace=read(root/'fixed-model-pairs'/(name+'.private-replay.json'))
        envelope=index.artifact(game['data_artifact_id'],for_training=True)
        episode=envelope['payload']
        if digest(episode)!=envelope['payload_sha256'] or episode['policy_sha256']!=game['policy_sha256']:
            raise RuntimeError('Actual frozen episode identity differs')
        row={k:game[k] for k in ('candidate_index','seed_audit_only','actor_seat')}
        row.update(trace=trace,actor_requests=pack_requests(episode),episode_artifact_sha256=digest(envelope))
        inputs.append(row)
    value=make_auxiliary_comparison(task,assets,comparison,policy,inputs,formal_matches)
    validate_auxiliary_comparison(task,assets,value)
    temporary=output.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temporary.replace(output)
    summary={'kind':'actual-goal-auxiliary-v2-summary','auxiliary_sha256':value['auxiliary_sha256'],
        'preferred_index':value['preferred_index'],'reason':value['preference_reason'],'cases':len(value['cases']),
        'original_win_comparison_sha256':comparison['comparison_sha256'],'original_win_comparison_changed':False,
        'policy_sha256':POLICY_SHA,'metric_names':value['metrics'],'formal_credit_for_comparison':0,
        'raw_file_sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
    (root/'actual-goal-auxiliary-v2-summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    return value
