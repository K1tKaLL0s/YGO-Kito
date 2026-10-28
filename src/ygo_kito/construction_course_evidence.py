"""Task-specific construction admission and persistent host cycle identities."""
from .build_contracts import digest
from .build_semantics import accepted_status,proof
from .validation import ContractError


def cycle_identity(number,force_rebuild,cycle_id):
    if force_rebuild and cycle_id is None:
        raise ContractError("forced reconstruction requires the persisted host cycle_id")
    if cycle_id is not None and (not isinstance(cycle_id,str) or len(cycle_id)>40 or
                                 not cycle_id.replace('-','').isdigit()):
        raise ContractError("invalid host cycle identity")
    suffix='-cycle-'+cycle_id if cycle_id is not None else ''
    return str(number)+suffix,'collaboration-v2-'+str(number).zfill(6)+('-forced' if force_rebuild else '')+suffix


def task_supervision(task,deck,assets,*,private_evidence=None):
    """No route proof is required when the construction task has no route goal."""
    assets.validate(task,deck)
    if task.goal['kind']=='deck_constraints' and 'route_goal' not in task.goal:
        evidence=proof(task,deck,assets);source='pinned_catalog_constraint_check'
    else:
        evidence=private_evidence
        if (not isinstance(evidence,dict) or evidence.get('status')!=accepted_status(task) or
                evidence.get('task_sha256')!=task.sha256 or evidence.get('deck_sha256')!=digest(deck.to_dict()) or
                not evidence.get('native_route',{}).get('core_attempts')):
            raise ContractError("explicit task route needs its own exact private task evidence")
        source='pinned_constraints_and_actual_native_route'
    return {'deck':deck.to_dict(),'label':1.,'source':source,'evidence':evidence}


def supervision_seeds(data):
    seeds=set()
    for row in data['goals']:
        evidence=row['evidence']
        if row['source']=='pinned_constraints_and_actual_native_route':
            seeds.update(a['seed_audit_only'] for a in evidence['native_route']['core_attempts'])
    for pair in data['pairs']:
        evidence=pair['evidence']
        plan=evidence.get('plan',evidence.get('original_win_comparison',{}).get('plan'))
        if plan is None:raise ContractError("comparison lacks its exact paired seed plan")
        seeds.update(plan['paired_seeds_audit_only'])
    return tuple(sorted(seeds))
