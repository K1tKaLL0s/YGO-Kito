"""Bound functional-quality preferences; retain their order after model updates."""
from copy import deepcopy
import math
from itertools import zip_longest

from .build_contracts import DeckParts, digest
from .construction_layer_flow import order_by_layers
from .validation import ContractError

SOURCE = 'construction_quality_preference_v2'


def _current_quality(quality):
    from .construction_layer_flow import NORMALIZATION_VERSION
    from .construction_quality import FUNCTION_DICTIONARY_VERSION, FUNCTIONAL_QUALITY_VERSION
    if (not isinstance(quality,dict) or quality.get('version') != FUNCTIONAL_QUALITY_VERSION
            or quality.get('score', {}).get('unit') != 'functional_log2'):
        raise ContractError('bound current functional quality evaluation required')
    if quality.get('normalization_version') != NORMALIZATION_VERSION:
        raise ContractError('quality normalization version requires reevaluation')
    if quality.get('function_dictionary_version') != FUNCTION_DICTIONARY_VERSION:
        raise ContractError('quality function dictionary version requires reevaluation')


def comparisons(task, contexts, *, _comparisons=None):
    from .construction_quality import EvaluationComparisons
    verified = _comparisons or EvaluationComparisons()
    by_deck={digest(c['deck']):c.get('quality_evaluation') for c in contexts}
    task_sha = task.sha256
    result={}
    bound = set()
    for context in contexts:
        for row in context.get('quality_comparisons', ()):
            a,b=row['before_deck_sha256'],row['after_deck_sha256']
            if a not in by_deck or b not in by_deck or a==b:continue
            pair=tuple(sorted((a,b)))
            if pair in result:
                if result[pair]!=row:
                    raise ContractError('conflicting quality comparisons for one candidate pair')
                continue
            if row.get('task_sha256')!=task_sha:
                raise ContractError('quality comparison belongs to another task')
            for key in {a,b} - bound:
                evaluation=by_deck[key]
                if not evaluation or evaluation['deck_sha256']!=key or evaluation['task_sha256']!=task_sha:
                    raise ContractError('quality comparison inventory/task differs from candidate')
                _current_quality(evaluation)
                bound.add(key)
            expected=verified.compare(by_deck[a],by_deck[b])
            if row!=expected:
                raise ContractError('quality comparison differs from its bound evaluations')
            result[pair]=row
    return list(result.values())


def candidate_pairs(task, contexts, *, _comparisons=None, _copy=True):
    by_deck={digest(c['deck']):c for c in contexts}
    decks={key: row['deck'] for key, row in by_deck.items()}
    rows=comparisons(task, contexts, _comparisons=_comparisons)
    incoming={k:set() for k in decks}
    for row in rows:
        if row['status']=='preferred' and row['preferred'] in ('before','after'):
            winner=row[row['preferred']+'_deck_sha256']
            loser=row[('after' if row['preferred']=='before' else 'before')+'_deck_sha256']
            incoming[loser].add(winner)
    _,cycles=order_by_layers(list(decks),incoming)
    result=[]
    for row in rows:
        if row['status']!='preferred' or row['preferred'] not in ('before','after'):continue
        better=row[row['preferred']+'_deck_sha256']
        worse=row[('after' if row['preferred']=='before' else 'before')+'_deck_sha256']
        if better in cycles or worse in cycles:continue
        result.append(dict(better=decks[better],worse=decks[worse],
            better_value=1.,worse_value=0.,source=SOURCE,hard_constraints_checked=True,
            evidence=dict(task_sha256=task.sha256,comparison=row,
                evaluations={side:by_deck[row[side+'_deck_sha256']]['quality_evaluation'] for side in ('before','after')},
                label_meaning='strict final functional score order; no win or CB label')))
    return deepcopy(result) if _copy else result


def validate_pair(task,pair):
    from .construction_quality import compare_functional_quality
    evidence=pair.get('evidence',{});row=evidence.get('comparison',{})
    preference=row.get('preferred')
    if (pair['source']!=SOURCE or pair['hard_constraints_checked'] is not True
        or pair['better_value']!=1. or pair['worse_value']!=0.
        or evidence.get('task_sha256')!=task.sha256 or row.get('task_sha256')!=task.sha256
        or row.get('status')!='preferred' or preference not in ('before','after')):
        raise ContractError('construction preference requires an actual strict quality comparison')
    evaluations=evidence.get('evaluations',{})
    for evaluation in evaluations.values():
        _current_quality(evaluation)
    if set(evaluations)!= {'before','after'} or compare_functional_quality(evaluations['before'],evaluations['after'])!=row:
        raise ContractError('construction preference lost its quality evaluation binding')
    better=row[preference+'_deck_sha256']
    worse=row[('after' if preference=='before' else 'before')+'_deck_sha256']
    if better==worse or digest(pair['better'])!=better or digest(pair['worse'])!=worse:
        raise ContractError('construction preference does not bind these two inventories')


def cycle_pairs(task,result,*,limit=8, _comparisons=None):
    """Keep strict evidence from actual optimizer rounds, not only survivors."""
    from .construction_quality import EvaluationComparisons
    verified = _comparisons or EvaluationComparisons()
    if limit <= 0:
        return []
    if task.goal['kind']!='deck_constraints' or 'route_goal' in task.goal:
        selected = candidate_pairs(task, result.get('retained_candidates',()), _comparisons=verified, _copy=False)[:limit]
        return selected if _comparisons is not None else deepcopy(selected)
    phases=[p for p in result.get('phases',()) if p.get('role', 'build_optimizer') == 'build_optimizer']
    stages=[p.get('stage_3',{}) for p in phases]
    groups=[candidate_pairs(task, s.get('learning_candidates', s.get('portfolio', ())),
                            _comparisons=verified, _copy=False) for s in stages]
    for phase,group in zip(phases,groups):
        for pair in group:
            pair['evidence']['construction_phase']=phase.get('phase_number')
            pair['evidence']['optimization_iteration']=phase.get('optimization_iteration')
    directions={}
    for group in groups:
        for pair in group:
            a,b=digest(pair['better']),digest(pair['worse'])
            directions.setdefault(tuple(sorted((a,b))),set()).add(a)
    selected=[];seen=set()
    for rows in zip_longest(*groups):
        for pair in rows:
            if pair is None:continue
            deck_key=tuple(sorted((digest(pair['better']),digest(pair['worse']))))
            key=tuple(sorted(r['evaluation_id'] for r in pair['evidence']['evaluations'].values()))
            if key in seen or len(directions[deck_key])!=1:continue
            seen.add(key);selected.append(pair)
            if len(selected)>=limit:
                return selected if _comparisons is not None else deepcopy(selected)
    return selected if _comparisons is not None else deepcopy(selected)


def quality_order(task, contexts, scores):
    """Final S determines order; model scores break genuine ties only."""
    from .construction_quality import EvaluationComparisons
    if not scores or len(scores)!=len(contexts) or any(not math.isfinite(v) for v in scores):
        raise ContractError('construction ranking requires finite candidate scores')
    verified = EvaluationComparisons()
    for context in contexts:
        quality=context.get('quality_evaluation')
        if quality is None or quality.get('task_sha256')!=task.sha256 or quality.get('deck_sha256')!=digest(context['deck']):
            raise ContractError('quality ranking requires each candidate\'s bound evaluation')
        verified.bind(quality)
        _current_quality(quality)
        if not quality['complete'] or any(r['status']!='satisfied' for r in quality['hard_requirements']):
            raise ContractError('quality ranking requires complete eligible candidates')
    for context in contexts[1:]:
        verified.compare(contexts[0]['quality_evaluation'], context['quality_evaluation'])
    return sorted(range(len(scores)),key=lambda i:(-contexts[i]['quality_evaluation']['score']['value'],-scores[i],i))


def rank_candidates(builder,task,contexts):
    assets = getattr(builder.encoder,'assets',None)
    if assets is not None:
        from .construction_layer_flow import functional_asset_version
        from .effect_mechanisms import MechanismCatalog
        catalog=MechanismCatalog(assets)
        for context in contexts:
            q=context.get('quality_evaluation') or {}
            if (q.get('asset_version') != functional_asset_version(catalog)
                    or any(e['record']['text_sha256'] != catalog.card(int(k.split(':')[1])).text_sha256
                           for k,v in q.get('coverage_details',{}).items() for e in v.get('effects',()))):
                raise ContractError('quality assets or card facts require reevaluation')
    import torch
    model=builder.models['build_optimizer'];mode=model.training;model.eval()
    try:
        with torch.no_grad():
            scores=model(builder.encoder.batch(task,[DeckParts.from_dict(c['deck']) for c in contexts])).reshape(-1).tolist()
    finally:model.train(mode)
    order=quality_order(task,contexts,scores)
    return dict(selected_index=order[0],scores=scores,order=order,comparison_cycles=[],
        role='build_optimizer',updates=builder.updates['build_optimizer'],
        source='updated_model_with_quality_order',candidate_deck_sha256=digest(contexts[order[0]]['deck']))


def consume_optimizer_slice(course, result, *, pause_requested=lambda:False, status=None):
    """Future authorized training consumes strict pre-CB iteration evidence."""
    from .semantic_training import supervision_projection
    from .semantic_training import SOURCE
    from .build_semantics import proof
    task = course._task()
    pairs = cycle_pairs(task, result)
    receipt = dict(iterations=(result.get('continuation') or {}).get('iteration', 0),
        eligible_pairs=len(pairs), updates_before=course.models.builder.updates['build_optimizer'],
        status='no_strict_quality_preferences' if not pairs else 'pending_consumption')
    result['optimizer_learning'] = receipt
    if task.goal['kind'] != 'deck_constraints' or 'route_goal' in task.goal:
        receipt.update(status='pre_cb_learning_requires_route_free_constraint_task',updates_after=receipt['updates_before'])
        return receipt
    if not pairs or pause_requested():
        if pause_requested(): receipt['status'] = 'user_paused_before_learning'
        receipt['updates_after'] = course.models.builder.updates['build_optimizer']
        return receipt
    decks={digest(pair[key]):DeckParts.from_dict(pair[key]) for pair in pairs for key in ('better','worse')}
    goals=[dict(deck=deck.to_dict(),label=1.,source='pinned_catalog_constraint_check',evidence=proof(task,deck,course.assets)) for deck in decks.values()]
    data = dict(source=SOURCE, purpose='train', task_sha256=task.sha256, goals=goals, pairs=pairs,
        unknown_routes_used_as_negative=False, competitive_quality_labels=False,
        public_effect_receipts=course.assets.effect_receipts(task))
    data['supervision_sha256'] = digest(supervision_projection(data))
    artifact_id = 'optimizer-slice-' + digest({'task':task.sha256,'data':data})[:32]
    dataset_id = 'course-build-' + task.sha256[:24]
    course.data_index.freeze(dict(dataset_id=dataset_id, experiment_id=course.config['course_id'],
        purpose='train', family='construction', versions=task.environment['versions'], opponents=[], task_sha256=task.sha256))
    from ygo_kito.construction_course_evidence import supervision_seeds
    course.data_index.ingest_construction(dataset_id, artifact_id, task, course.assets, data, seeds=supervision_seeds(data))
    if not any(r['feedback_id'] == artifact_id for r in course.feedback.consumed):
        course.apply_feedback(artifact_id, artifact_id, kind='construction', task=task, roles=('build_optimizer',))
    receipt.update(status='consumed', feedback_id=artifact_id,
        updates_after=course.models.builder.updates['build_optimizer'])
    receipt['consumption'] = [deepcopy(r) for r in course.feedback.consumed if r['feedback_id'] == artifact_id and r['role'] == 'build_optimizer']
    if not receipt['consumption']: raise ContractError('optimizer slice has no consumption receipt')
    if status is not None: status('optimizer_construction_slice_learning', **receipt)
    return receipt
