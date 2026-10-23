"""Explicit fact-constraint/preference supervision, never fake game outcomes."""
from .build_contracts import DeckParts,digest
from .build_semantics import preference_value,proof
from .validation import ContractError,fields,array

SOURCE='catalog_constraint_and_explicit_preference_v1'


def dataset(task,assets,*,purpose='train'):
    from .build_pipeline import goal_candidates,edit_candidates
    from .build_training import supervision_projection
    candidates=goal_candidates(task,assets)
    if len(candidates)<2:raise ContractError('two independently checked semantic candidates required')
    goals=[]
    for deck in candidates[:2]:
        if 'route_goal' in task.goal:
            from .build_pipeline import verify_goal
            evidence=verify_goal(task,deck,assets,attempts=64)
            if evidence['status']!='constraints_and_route_verified':continue
            source='pinned_constraints_and_actual_native_route'
        else:evidence,source=proof(task,deck,assets),'pinned_catalog_constraint_check'
        goals.append({'deck':deck.to_dict(),'label':1.,'source':source,'evidence':evidence})
        goals.append({'deck':DeckParts(deck.main[:-1],deck.extra,deck.side).to_dict(),'label':0.,
                      'source':'explicit_hard_constraint_failure','evidence':{'status':'hard_constraint_failure','reason':'section size differs'}})
    if not goals:raise ContractError('no verified combined route within budget; no invented positive or impossibility label')
    # Optimizer examples must preserve the whole conjunctive objective, not
    # merely its list counts. Reuse only candidates with actual route witnesses.
    choices=([DeckParts.from_dict(r['deck']) for r in goals if r['label']==1] if 'route_goal' in task.goal else
             list(dict.fromkeys(candidates+edit_candidates(task,assets,candidates[0]))))
    ordered=sorted(choices,key=lambda d:(preference_value(task,d,assets),digest(d.to_dict())))
    pairs=[]
    for worse in ordered[:2]:
        better=ordered[-1];low,high=(preference_value(task,d,assets) for d in (worse,better))
        if low<high:pairs.append({'better':better.to_dict(),'worse':worse.to_dict(),'better_value':high,'worse_value':low,
                                  'source':'explicit_user_preference_not_strength','hard_constraints_checked':True})
    if not pairs:raise ContractError('no strict preference comparison; no invented optimizer label')
    result={'source':SOURCE,'purpose':purpose,'task_sha256':task.sha256,'goals':goals,'pairs':pairs,
            'unknown_routes_used_as_negative':False,'competitive_quality_labels':False,
            'public_effect_receipts':assets.effect_receipts(task)}
    result['supervision_sha256']=digest(supervision_projection(result));validate(task,assets,result,for_training=False)
    return result


def validate(task,assets,data,*,for_training=True):
    from .build_training import supervision_projection
    fields(data,{'source','purpose','task_sha256','goals','pairs','supervision_sha256','unknown_routes_used_as_negative','competitive_quality_labels','public_effect_receipts'})
    from .data_isolation import PURPOSES
    if data['purpose'] not in PURPOSES or for_training and data['purpose']!='train':raise ContractError('held-out semantic data cannot train building models')
    if (task.goal['kind']!='deck_constraints' or data['source']!=SOURCE or data['task_sha256']!=task.sha256
        or data['unknown_routes_used_as_negative'] is not False or data['competitive_quality_labels'] is not False
        or data['public_effect_receipts']!=assets.effect_receipts(task)):
        raise ContractError('semantic supervision identity/source differs')
    if not 1<=len(array(data['goals'],'semantic goals'))<=16 or not 1<=len(array(data['pairs'],'semantic pairs'))<=8:
        raise ContractError('semantic supervision record budget exceeded')
    for row in data['goals']:
        fields(row,{'deck','label','source','evidence'});deck=DeckParts.from_dict(row['deck'])
        if type(row['label']) not in (int,float) or row['label'] not in (0,1):raise ContractError('invalid semantic label')
        if row['label']==1:
            if 'route_goal' in task.goal:
                from .build_semantics import route_task
                from .route_search import replay_discovered_goal
                evidence=fields(row['evidence'],{'status','task_sha256','deck_sha256','constraints','native_route','effect_execution_verified','competitive_strength_verified','unmet'})
                if (row['source']!='pinned_constraints_and_actual_native_route' or evidence['status']!='constraints_and_route_verified'
                    or evidence['task_sha256']!=task.sha256 or evidence['deck_sha256']!=digest(deck.to_dict())
                    or evidence['constraints']!=proof(task,deck,assets) or evidence['effect_execution_verified'] is not True
                    or evidence['competitive_strength_verified'] is not False or evidence['unmet']):
                    raise ContractError('combined positive lacks its exact constraint/native goal binding')
                replay_discovered_goal(route_task(task),deck,assets,evidence['native_route'],
                                       required_activations=tuple(task.goal.get('required_activations',())),
                                       required_chain_resolutions=tuple(task.goal.get('required_chain_resolutions',())))
            elif row['source']!='pinned_catalog_constraint_check' or row['evidence']!=proof(task,deck,assets):
                raise ContractError('semantic positive is not a catalog-checked constraint result')
        else:
            fields(row['evidence'],{'status','reason'})
            if row['source']!='explicit_hard_constraint_failure' or row['evidence']['status']!='hard_constraint_failure':
                raise ContractError('unknown rules cannot be semantic negative labels')
            try:assets.validate(task,deck)
            except ContractError:pass
            else:raise ContractError('semantic negative satisfies all constraints')
    verified={digest(r['deck']) for r in data['goals'] if r['label']==1}
    for pair in data['pairs']:
        fields(pair,{'better','worse','better_value','worse_value','source','hard_constraints_checked'})
        better,worse=(DeckParts.from_dict(pair[k]) for k in ('better','worse'))
        assets.validate(task,better);assets.validate(task,worse)
        if 'route_goal' in task.goal and any(digest(d.to_dict()) not in verified for d in (better,worse)):
            raise ContractError('combined optimizer comparisons require verified native goals on both sides')
        if (pair['source']!='explicit_user_preference_not_strength' or pair['hard_constraints_checked'] is not True
            or pair['better_value']!=preference_value(task,better,assets) or pair['worse_value']!=preference_value(task,worse,assets)
            or pair['better_value']<=pair['worse_value']):raise ContractError('semantic preference label differs')
    if data['supervision_sha256']!=digest(supervision_projection(data)):raise ContractError('semantic supervision digest differs')
