"""Explicitly continue one inspected, closed, no-update sampling abort."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def import_closed_abort(course, target):
    import torch
    from ygo_kito.build_contracts import DeckParts
    from ygo_kito.group_runner import tree_digest
    from ygo_kito.scenario_course import index_identity
    meta=json.loads((target/'budget-abort-continuation.json').read_text())
    parent=Path(meta['parent_checkpoint'])
    if hashlib.sha256(parent.read_bytes()).hexdigest()!=meta['parent_checkpoint_sha256']:
        raise RuntimeError('Closed parent checkpoint differs')
    for name in ('in-flight.json','feedback-in-flight.json'):
        if (parent.parent/name).exists():raise RuntimeError('Uncertain parent transaction cannot be continued')
    saved=torch.load(parent,weights_only=True,map_location='cpu')
    last=saved['records'][-1];receipt=last['receipts'][-1]
    if (saved['pending'] is not None or last['match_id']!=meta['aborted_match_id'] or
        last['status']!='aborted' or last['complete'] or receipt['model_update_started'] or
        receipt['model_update_completed'] or receipt['sample_completed'] or
        receipt['before']['model_sha256']!=receipt['after']['model_sha256'] or
        receipt['error']!={'type':'NativeError','message':'CPU sample budget exhausted; no terminal reward/update claimed'}):
        raise RuntimeError('Recovery is restricted to this known closed no-update abort')
    if index_identity(course.data_index)!=meta['parent_data_index_sha256']:
        raise RuntimeError('Continuation index differs from closed parent')
    old_binding=saved['binding'];new_binding=course.binding
    if {k:v for k,v in old_binding.items() if k!='config'}!={k:v for k,v in new_binding.items() if k!='config'}:
        raise RuntimeError('Recovery cannot change source, bot, assets or model binding')
    if {k:v for k,v in old_binding['config'].items() if k!='training_seeds'}!={k:v for k,v in new_binding['config'].items() if k!='training_seeds'}:
        raise RuntimeError('Recovery cannot change budgets or curriculum')
    current=course.models.save_state()
    for key in ('components','rng','cursors','kernel','binding'):
        if tree_digest(current[key])!=tree_digest(saved['models'][key]):
            raise RuntimeError('Continuation changed learned state: '+key)
    seeds=list(current['configs']['duel']['game_seeds']);cursor=current['cursors']['duel_episodes']
    original=list(saved['models']['configs']['duel']['game_seeds'])
    expected=original[:cursor]+original[cursor+1:]+[meta['appended_unused_training_seed']]
    if (seeds!=expected or cursor!=meta['sampler_cursor_unchanged'] or
        seeds[cursor]!=meta['next_sampling_seed'] or meta['quarantined_training_seed'] in seeds):
        raise RuntimeError('Exact declared seed quarantine differs')
    for key in ('records','events','active_seconds','selection','construction',
                'evaluation_cursor','frozen_evaluation','initial_model_execution'):
        setattr(course,key,deepcopy(saved[key]))
    course.deck=DeckParts.from_dict(saved['deck']);course.rules.validate(course.deck)
    course.feedback.load_state_dict(saved['feedback'])
    if course.counts()['bo1']!=meta['complete_prior_bo1']:
        raise RuntimeError('Continuation changed complete-match accounting')
    course.pending=None;course.desired='ready'
    course.events.append({'kind':meta['kind'],'parent_checkpoint_sha256':meta['parent_checkpoint_sha256'],
        'aborted_match_id':meta['aborted_match_id'],'quarantined_training_seed':meta['quarantined_training_seed'],
        'next_sampling_seed':meta['next_sampling_seed'],'aborted_match_credited':False,
        'weights_optimizers_rng_cursors_preserved':True,'sample_budget_preserved':True})
    return course.save()
