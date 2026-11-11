"""Shared metrics over saved predictions; this module never loads a model."""
from collections import defaultdict
import json

from ygo_kito.multifactor.contracts import LabelCell, ROLES, TASK_DOMAINS
from ygo_kito.multifactor.metrics import (axis_set_metrics, binary_metrics, categorical_metrics,
    group_bootstrap, macro_f1_report, probability_calibration)


def _cell(value):
    return LabelCell.from_dict(value) if isinstance(value,dict) else LabelCell.from_legacy(value)


def summarize(rows):
    """Legacy report shape, with the same known-cell accounting as v3."""
    values = defaultdict(lambda:[[] for _ in ROLES])
    for row in rows:
        for i,y in enumerate(row['labels']):
            values[row['family']][i].append((_cell(y),row['prediction'][i]))
    families = {family:{name:binary_metrics(cells[i]) for i,name in enumerate(ROLES)} for family,cells in sorted(values.items())}
    overall = {name:binary_metrics([p for cell in values.values() for p in cell[i]]) for i,name in enumerate(ROLES)}
    means = {}
    for name in ROLES:
        covered = [f[name] for f in families.values() if f[name]['known']]
        means[name] = sum(v['balanced_brier'] for v in covered)/len(covered) if covered and all(v['balanced_brier'] is not None for v in covered) else None
    complete = all(overall[name]['complete_class_coverage'] and means[name] is not None for name in ROLES)
    return dict(roles=overall,by_family=families,family_balanced_role_brier=means,
        complete_coverage=complete,selection_score=max(means.values()) if complete else None,
        metric_version='known-cell-metrics-v3',
        scope='Fixed previously consumed construction-role references; retrospective development only; not an independent final test.')


def comparison(candidate,baseline,tolerance=1e-4):
    a,b = candidate['family_balanced_role_brier'],baseline['family_balanced_role_brier']
    comparable = candidate.get('metric_version') == baseline.get('metric_version') == 'known-cell-metrics-v3'
    covered = comparable and candidate.get('complete_coverage') is True and baseline.get('complete_coverage') is True
    regressions = {name:a[name]-b[name] for name in ROLES if a[name] is not None and b[name] is not None and a[name]>b[name]+tolerance}
    improved = any(a[name] is not None and b[name] is not None and a[name]<b[name]-tolerance for name in ('strategic_core','support_role'))
    return dict(no_head_regression=not regressions if covered else None,regressions=regressions,
        core_or_support_improved=improved if covered else None,comparable_coverage=covered,
        eligible_to_replace_previous_limited_base=covered and not regressions and improved,
        meaning='Development retention only; requires matching metric version and complete class/head coverage.')


def coverage(rows,cases):
    known = {name:dict(positive=0,negative=0,unknown=0,positive_families=set(),negative_families=set()) for name in ROLES}
    for row in rows:
        for i,name in enumerate(ROLES):
            cell = _cell(row['labels'][i])
            if not cell.known:
                known[name]['unknown'] += 1
            else:
                side = 'positive' if cell.value>=.5 else 'negative'
                known[name][side] += 1
                known[name][side+'_families'].add(row['family'])
    for cell in known.values():
        for key in ('positive_families','negative_families'):
            cell[key] = sorted(cell[key])
    co = sum(_cell(r['labels'][2]).known and _cell(r['labels'][3]).known and _cell(r['labels'][2]).value>=.5 and _cell(r['labels'][3]).value>=.5 for r in rows)
    return dict(reference_cases=len(rows),actual_sources=len({r['source_rowid'] for r in rows}),role_coverage=known,
        core_and_support_positive_cases=co,new_reference_cases=0,
        independence='All case inputs/prior results were observed; no fresh-final claim.')


def prediction_key(task, coordinate):
    """Saved prediction key: JSON [task, coordinate-array], never a feature."""
    return json.dumps([task,list(coordinate)],ensure_ascii=False,separators=(',',':'))


def _mean_complete(rows,key):
    values = [r.get(key) for r in rows]
    return sum(values)/len(values) if values and all(v is not None for v in values) else None


def _source_summary(by_group,bootstrap):
    metrics = list(by_group.values())
    covered = [v['f1'] for v in metrics if v.get('f1') is not None]
    result = {name:_mean_complete(metrics,name) for name in ('f1','coverage','overall_accuracy','selective_accuracy')}
    result.update(source_groups=len(metrics),covered_f1_groups=len(covered),
                  covered_macro_f1=sum(covered)/len(covered) if covered else None)
    samples = {g:[v] for g,v in by_group.items()}
    result['f1_interval'] = group_bootstrap(samples,lambda rows:_mean_complete(rows,'f1'),**bootstrap)
    result['accuracy_interval'] = group_bootstrap(samples,lambda rows:_mean_complete(rows,'overall_accuracy'),**bootstrap)
    return result


def assess_records(records, predictions, protocol):
    """Evaluate saved maps on fixed cells, separately for each partition/layer.

    predictions[record_id][raw|calibrated|applied][prediction_key(...)] = value.
    Optional predictions[record_id]['axes'][layer] contains candidate_ref/member
    dictionaries. Axes are evaluated only when provenance.axis_truth exists;
    its absence is unannotated, while [] is a reviewed empty truth set.
    """
    from prepare_v3 import RECORD_VERSION, iter_target_cells
    layers = ('raw','calibrated','applied')
    all_tasks = tuple('legacy:'+r for r in ROLES)+('legacy:compatibility','legacy:pairs')+tuple(TASK_DOMAINS)
    if protocol.get('version') != 'axis-generic-assessment-v3' or tuple(protocol.get('layers',())) != layers:
        raise ValueError('explicit three-layer v3 assessment protocol required')
    tasks = tuple(protocol.get('tasks',()))
    if len(tasks)!=len(set(tasks)) or set(tasks)!=set(all_tasks):
        raise ValueError('assessment must keep the complete fixed task vocabulary')
    partitions = tuple(protocol.get('partitions',()))
    if not partitions or len(set(partitions)) != len(partitions) or any(s not in ('validation','test','retrospective_test') for s in partitions):
        raise ValueError('assessment partitions must be explicit evaluation partitions')
    bootstrap = dict(protocol.get('bootstrap',{}))
    if bootstrap.pop('unit',None) != 'leakage_group':
        raise ValueError('bootstrap unit must be leakage_group')
    ids = [r['record_id'] for r in records]
    if len(set(ids)) != len(ids) or set(predictions)-set(ids):
        raise ValueError('duplicate record ids or predictions outside this dataset')
    cells = defaultdict(lambda:defaultdict(list))
    mechanisms = defaultdict(lambda:defaultdict(list))
    axes = defaultdict(lambda:defaultdict(list))
    audit = defaultdict(lambda:dict(records=0,axis_unannotated=0,axis_overflow=0))
    group_partitions = {}
    for row in records:
        if row.get('schema_version') != RECORD_VERSION or row['supervision'].get('label_protocol') != protocol.get('label_protocol'):
            raise ValueError('record/label protocol mismatch')
        group,fold = row['provenance']['leakage_group'],row['supervision']['partition']
        if group_partitions.setdefault(group,fold) != fold:
            raise ValueError('a source component crosses partitions')
        if fold not in partitions:
            continue
        audit[fold]['records'] += 1
        saved = predictions.get(row['record_id'],{})
        target_cells = list(iter_target_cells(row['targets']))
        expected = {prediction_key(t,c) for t,c,_ in target_cells}
        for layer in layers:
            guesses = saved.get(layer,{})
            if not isinstance(guesses,dict) or set(guesses)-expected:
                raise ValueError('prediction coordinates must match explicit target cells')
            for task,coordinate,cell in target_cells:
                pair = (cell, guesses.get(prediction_key(task,coordinate)))
                cells[fold,layer,task][group].append(pair)
                if task == 'mechanism':
                    mechanisms[fold,layer][coordinate[-1]].append(pair)
        natural = row['observations']['candidates']
        if natural.get('producer') != 'natural_input_facts':
            raise ValueError('gold-injected candidates cannot enter evaluation')
        audit[fold]['axis_overflow'] += int(natural.get('overflow',False))
        truth = row['provenance'].get('axis_truth')
        if truth is None:
            audit[fold]['axis_unannotated'] += 1
            continue
        candidates = {v['candidate_id']:v for v in natural['candidates']}
        observable_members = {n['ref'] for n in row['observations']['graph']['nodes'] if n['kind']=='card'} | {v['candidate_id'] for v in natural['units']}
        for layer in layers:
            proposed = saved.get('axes',{}).get(layer,[])
            for value in proposed:
                ref = value.get('candidate_ref')
                if ref in candidates:
                    if len(set(value['members']))!=len(value['members']) or not set(value['members'])<=observable_members:
                        raise ValueError('predicted axis members must be distinct observed cards/units')
            axes[fold,layer][group].append(axis_set_metrics(truth,proposed,natural_candidate_ids=candidates))
    result = dict(version='axis-assessment-report-v3',label_protocol=protocol['label_protocol'],partitions={},
        capability_accepted=False,model_loaded=False,predictions_generated=False,
        scope='Saved predictions only; coverage/diagnostics do not publish a capability or select a checkpoint.')
    for fold in partitions:
        output = dict(audit=audit[fold],layers={})
        for layer in layers:
            per_task = {}
            for task in tasks:
                grouped = cells[fold,layer,task]
                classes = TASK_DOMAINS.get(task)
                def measure(pairs):
                    return categorical_metrics(pairs,classes) if classes else binary_metrics(pairs)
                pairs = [p for values in grouped.values() for p in values]
                overall = measure(pairs)
                by_group = {g:measure(v) for g,v in sorted(grouped.items()) if any(c.known for c,_ in v)}
                overall.update(by_source=by_group,source_macro=_source_summary(by_group,bootstrap))
                if classes is None:
                    overall['reliability'] = probability_calibration(pairs,protocol.get('reliability_bins',10))
                if task == 'mechanism':
                    from ygo_kito.multifactor.task_queries import BINARY_COORDINATES
                    overall['by_coordinate'] = {coordinate: binary_metrics(mechanisms[fold,layer].get(coordinate, ()))
                                                for coordinate in BINARY_COORDINATES['mechanism']}
                per_task[task] = overall
            source_axes = {g:{name:_mean_complete(v,name) for name in ('matched_mean_iou','candidate_recall','f1')} for g,v in sorted(axes[fold,layer].items())}
            axis_report = dict(by_source=source_axes,source_groups=len(source_axes),
                source_macro_iou=_mean_complete(list(source_axes.values()),'matched_mean_iou'),
                source_macro_candidate_recall=_mean_complete(list(source_axes.values()),'candidate_recall'),
                iou_interval=group_bootstrap({g:[v] for g,v in source_axes.items()},lambda rows:_mean_complete(rows,'matched_mean_iou'),**bootstrap),
                by_record_group=dict(axes[fold,layer]),
                candidate_counts={field: sum(row[field] for group in axes[fold,layer].values() for row in group)
                                  for field in ('candidate_mapped_truth', 'candidate_unmapped_truth', 'candidate_missed_truth')})
            output['layers'][layer] = dict(tasks=per_task,macro=macro_f1_report(per_task,tasks=tasks),axes=axis_report)
        output['independent_final'] = fold == 'test' and bool(audit[fold]['records']) and all(
            r['provenance'].get('final_eval_eligible') is True and r['provenance'].get('previously_consumed') is False
            for r in records if r['supervision']['partition']==fold)
        result['partitions'][fold] = output
    return result
