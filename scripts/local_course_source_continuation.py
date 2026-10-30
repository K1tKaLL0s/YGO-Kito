"""Import a closed course into an explicit auxiliary-source continuation."""
from copy import deepcopy
import hashlib,json
from pathlib import Path


def import_source_continuation(course,target):
    import torch
    from ygo_kito.build_contracts import DeckParts,digest
    from ygo_kito.group_runner import tree_digest
    from ygo_kito.scenario_course import index_identity
    meta=json.loads((target/'source-continuation.json').read_text())
    parent=Path(meta['parent_checkpoint'])
    if hashlib.sha256(parent.read_bytes()).hexdigest()!=meta['parent_checkpoint_sha256']:
        raise RuntimeError('Source continuation parent changed')
    for name in ('in-flight.json','feedback-in-flight.json'):
        if (parent.parent/name).exists():raise RuntimeError('Source continuation requires a closed parent transaction')
    saved=torch.load(parent,weights_only=True,map_location='cpu')
    if saved['pending'] is not None or saved['feedback']['pending'] is not None:
        raise RuntimeError('Source continuation cannot adopt pending work')
    if index_identity(course.data_index)!=saved['data_index_sha256']:
        raise RuntimeError('Source continuation index differs from closed parent')
    current=course.models.save_state()
    for key in ('components','rng','cursors','configs','task','available_ids','vocabulary'):
        if tree_digest(current[key])!=tree_digest(saved['models'][key]):
            raise RuntimeError('Source continuation changed learned state or task: '+key)
    if course.config!=saved['binding']['config']:raise RuntimeError('Source continuation changed course or runtime budgets')
    for key in ('records','events','active_seconds','construction','evaluation_cursor','frozen_evaluation','initial_model_execution'):
        setattr(course,key,deepcopy(saved[key]))
    course.selection=deepcopy(current['kernel']['selections'][saved['selection']['candidate_id']])
    course.deck=DeckParts.from_dict(saved['deck']);course.rules.validate(course.deck)
    feedback=deepcopy(saved['feedback'])
    feedback['binding_sha256']=course.feedback.binding_sha256
    feedback['metadata_sha256']=digest({k:v for k,v in feedback.items() if k!='metadata_sha256'})
    course.feedback.load_state_dict(feedback)
    course.pending=None;course.desired='ready'
    course.events.append({'kind':meta['kind'],'parent_checkpoint_sha256':meta['parent_checkpoint_sha256'],
        'changed_package_files':meta['changed_package_files'],'weights_optimizers_rng_cursors_preserved':True,
        'prior_matches_preserved':course.counts(),'reference_inputs':[],
        'old_and_new_binding_recorded':True,'runtime_budgets_preserved':True})
    return course.save()
