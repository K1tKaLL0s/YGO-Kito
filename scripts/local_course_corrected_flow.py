"""Retain earlier real learning while excluding the superseded flow's volume."""
from copy import deepcopy
import hashlib,json
from pathlib import Path


def import_corrected_flow(course,target):
    import torch
    from ygo_kito.build_contracts import digest
    from ygo_kito.group_runner import tree_digest
    from ygo_kito.scenario_course import index_identity
    meta=json.loads((target/'corrected-flow-continuation.json').read_text())
    parent=Path(meta['parent_checkpoint'])
    if hashlib.sha256(parent.read_bytes()).hexdigest()!=meta['parent_checkpoint_sha256']:raise RuntimeError('Corrected flow parent differs')
    saved=torch.load(parent,weights_only=True,map_location='cpu')
    if saved['pending'] is not None or saved['feedback']['pending'] is not None:raise RuntimeError('Uncertain transaction cannot be migrated')
    if len(saved['records'])!=course.config['training_record_offset']:raise RuntimeError('Prior record boundary differs')
    if index_identity(course.data_index)!=saved['data_index_sha256']:raise RuntimeError('Corrected flow data index differs')
    current=course.models.save_state()
    for key in ('components','rng','cursors','task','vocabulary','available_ids'):
        if tree_digest(current[key])!=tree_digest(saved['models'][key]):raise RuntimeError('Corrected flow changed learned state: '+key)
    for key in ('records','events','active_seconds','evaluation_cursor','frozen_evaluation'):
        setattr(course,key,deepcopy(saved[key]))
    feedback=deepcopy(saved['feedback']);feedback['binding_sha256']=course.feedback.binding_sha256
    feedback['metadata_sha256']=digest({k:v for k,v in feedback.items() if k!='metadata_sha256'})
    course.feedback.load_state_dict(feedback)
    course.selection=course.deck=course.construction=None;course.pending=None;course.desired='ready'
    course.events.append({'kind':meta['kind'],'parent_checkpoint_sha256':meta['parent_checkpoint_sha256'],
        'old_flow_complete_matches':meta['prior_complete_training_matches'],'old_flow_credit_in_corrected_course':0,
        'models_optimizers_rng_cursors_preserved':True,'original_selected_goal_preserved':True,
        'new_required_volume':{'bo1':600,'bo3':400}})
    return course.save()
