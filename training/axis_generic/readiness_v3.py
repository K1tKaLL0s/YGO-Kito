"""Full-task, per-coordinate readiness checks before formal v3 updates."""
from collections import defaultdict
import gzip
import json
from pathlib import Path

from ygo_kito.multifactor.contracts import FactorContractError,RoleInput,digest
from ygo_kito.multifactor.task_queries import (BINARY_COORDINATES,CATEGORY_COORDINATES,LEARNED_TASKS,
    comparison_for_record,observation_view,query_domain,record_sources,validate_query)


def reviewed_source(row):
    """Prepared IDs are hashes; inspect retained original IDs, including merges."""
    return any(namespace=='full18_reviewed_context' and original.startswith('full18:')
               for namespace,original in (json.loads(v) for v in row['provenance']['source_record_ids']))


def check(config,manifest,coverage,evidence_dir):
    import train_v3
    from ygo_kito.multifactor.training import Targets
    from full18_sources import required_classes,NORMALS
    evidence_dir=Path(evidence_dir)
    evidence=train_v3.read(evidence_dir/'full18-evidence.json')
    protocol=train_v3.read(evidence_dir/'full18-protocol.json')
    expected_partitions=train_v3.read(evidence_dir/'source-partitions.json')
    missing=[]
    if set(config['selection_tasks'])!=set(LEARNED_TASKS) or len(config['selection_tasks'])!=len(LEARNED_TASKS):
        missing.append('full18 selection scope differs')
    if evidence.get('annotation_method') is None or protocol.get('human_gold') is not False or protocol.get('engine_executed') is not False:
        raise FactorContractError('explicit weak annotation provenance required')
    for unit in evidence['units'].values():
        for code,quote in unit['quotes']:
            if quote not in evidence['cards'][str(code)]['desc']:
                raise FactorContractError('review quote missing from pinned card text')
        if set(unit['functions'])&set(unit['negative_functions']):
            raise FactorContractError('review contains conflicting functional values')
    for code in NORMALS:
        row=evidence['cards'][str(code)]
        if row['type']&0x10==0 or row['type']&0x20:
            raise FactorContractError('known-negative control is not an effectless Normal Monster')
    reserved=set(config['calibration_groups'])
    classes=defaultdict(set);known_groups=defaultdict(set);counts=defaultdict(int)
    all_groups=defaultdict(set);ids=set();records=0;queries=0;unknown=0;new_records=0
    folds=('train','validation','retrospective_test','test')
    root=Path(config['dataset_dir']).resolve()
    for fold in folds:
        for shard in manifest['shards'].get(fold,[]):
            path=(root/shard['file']).resolve()
            if not path.is_relative_to(root):raise FactorContractError('shard escapes prepared root')
            with gzip.open(path,'rt',encoding='utf-8') as stream:rows=[json.loads(line) for line in stream]
            if len(rows)!=shard['records'] or digest(rows)!=shard['semantic_records']:
                raise FactorContractError('prepared shard differs during full readiness check')
            for row in rows:
                records+=1
                if row['record_id'] in ids:raise FactorContractError('duplicate record across readiness folds')
                ids.add(row['record_id'])
                sources=record_sources(row,label_protocol_sha256=digest(config['label_protocol']))
                if sources-{'weak_context_annotation','human_feedback','engine_probe','self_generated_candidate'}:
                    raise FactorContractError('formal readiness cannot relabel engineering data')
                group=row['provenance']['leakage_group']
                scope='calibration' if fold=='validation' and group in reserved else 'selection' if fold=='validation' else fold
                all_groups[scope].add(group)
                example,graph,candidates=observation_view(row);domain=query_domain(example,graph,candidates)
                if row.get('comparison') is not None:comparison_for_record(row)
                is_new=reviewed_source(row)
                if is_new:
                    new_records+=1
                    meta=row['provenance']
                    if meta.get('annotation_method')!='assistant_reviewed_weak_context' or meta.get('previously_consumed') is not True or meta.get('final_eval_eligible') is not False:
                        raise FactorContractError('new weak annotation loses source/consumption history')
                    if not meta.get('review_ref') or not meta.get('observed_receiver_ref'):
                        raise FactorContractError('new annotation lacks exact review/receiver references')
                    if meta.get('excluded_query_member'):
                        excluded=meta['excluded_query_member']
                        if excluded in dict(example.unit_definition.members):
                            raise FactorContractError('excluded member remains in exact query')
                        if row['targets']['task_labels'] or row['targets']['roles'][0][1][4].get('value')!=0:
                            raise FactorContractError('incomplete query was repurposed as another head truth')
                for task,subject,coordinate,cell in Targets.from_dict(row['targets']).graph_cells():
                    if not cell.known:unknown+=1;continue
                    if task=='copy_preference':
                        if tuple(subject)!=('query:unit','query:unit') or coordinate!='preference':
                            raise FactorContractError('unexpected copy comparison scope')
                    else:validate_query(domain,task,subject,coordinate)
                    queries+=1
                    value=cell.value if task in CATEGORY_COORDINATES else int(cell.value>=.5)
                    classes[scope,task,coordinate].add(str(value))
                    known_groups[scope,task,coordinate].add(group)
                    counts[scope,task,coordinate,str(value)]+=1
                    if is_new and not cell.evidence_refs:
                        raise FactorContractError('new known cell lacks evidence reference')
                if is_new and 'access' in row['provenance']:
                    from math import comb
                    access=row['provenance']['access'];n=access['deck_size'];draws=access['draws']
                    left=RoleInput.from_dict(row['observations']['input'])
                    right=RoleInput.from_dict(row['comparison']['right']['input'])
                    ka,kb=dict(left.deck.main)[53129443],dict(right.deck.main)[53129443]
                    if (ka,kb)!=(access['left_copies'],access['right_copies']):
                        raise FactorContractError('preference proof copy counts differ')
                    pa,pb=(1-comb(n-k,draws)/comb(n,draws) for k in (ka,kb))
                    answer='equal' if pa==pb else 'left' if pa>pb else 'right'
                    if row['targets']['task_labels'][0]['cells']['preference']['value']!=answer:
                        raise FactorContractError('preference label differs from exact declared comparison')
    for a in all_groups:
        for b in all_groups:
            if a!=b and all_groups[a]&all_groups[b]:raise FactorContractError('readiness source overlap')
    for key,scope in (('training_groups','train'),('selection_groups','selection'),('calibration_groups','calibration'),('retrospective_groups','retrospective_test')):
        if set(expected_partitions[key])!=all_groups[scope]:
            raise FactorContractError('prepared source allocation differs from frozen annotations')
    per_task={}
    required=required_classes()
    for task in LEARNED_TASKS:
        values={}
        for scope in ('train','selection','calibration','retrospective_test'):
            rows=[]
            for coordinate in BINARY_COORDINATES.get(task,(CATEGORY_COORDINATES.get(task,'value'),)):
                expected={v for t,c,v in required if t==task and c==coordinate}
                uncovered=expected-classes[scope,task,coordinate]
                if scope in ('train','selection','calibration') and uncovered:
                    missing.append(f'{scope}:{task}:{coordinate}:missing classes '+','.join(sorted(uncovered)))
                if scope in ('train','selection','calibration') and len(known_groups[scope,task,coordinate])<2:
                    missing.append(f'{scope}:{task}:{coordinate}:fewer than 2 labelled source groups')
                rows.append(dict(coordinate=coordinate,classes=sorted(classes[scope,task,coordinate]),
                    class_counts={v:counts[scope,task,coordinate,v] for v in sorted(expected)},
                    labelled_source_groups=len(known_groups[scope,task,coordinate]),missing_classes=sorted(uncovered)))
            values[scope]=rows
        per_task[task]=values
    if new_records<40:missing.append('fewer than 40 distinct reviewed context/function queries')
    return dict(version='axis-full18-readiness-v1',ready=not missing,missing=missing,tasks=per_task,
        dataset_id=manifest['preparation_identity']['semantic_id'],source_groups={k:len(v) for k,v in all_groups.items()},
        records=records,new_reviewed_queries=new_records,known_cells=queries,unknown_cells=unknown,
        annotation_method=evidence['annotation_method'],human_gold=False,independent_final=bool(all_groups['test']),
        evidence_id=digest(evidence),protocol_id=digest(protocol),engineering_fixture_used=False,
        training_started=False,capability_accepted=False)
