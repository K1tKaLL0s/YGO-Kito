"""Explicit v3 base runner. Importing this module does not import Torch."""
from copy import deepcopy
from collections import defaultdict
from dataclasses import asdict
import gzip
import json
from pathlib import Path
import random
import sys
import os
import tempfile
import re
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT.parent.parent/'src'))

from ygo_kito.multifactor.contracts import GRAPH_VERSION, TASK_DOMAINS, FactorContractError, digest
from ygo_kito.multifactor.task_queries import (CATEGORY_COORDINATES, LEARNED_TASKS, observation_view, query_domain,
                                             missing_axis_query, query_key, validate_query, comparison_for_record, record_sources, BINARY_COORDINATES)



def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def write(path,value):
    path = Path(path)
    text=json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n'
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',prefix=path.name+'.',suffix='.tmp',dir=path.parent,delete=False) as stream:
        temporary=Path(stream.name)
    try:
        temporary.write_text(text,encoding='utf-8')
        # Windows indexers can briefly open recently written state without
        # delete sharing. Retry only that same atomic replacement, then fail.
        for attempt in range(6):
            try:
                os.replace(temporary,path)
                break
            except PermissionError as error:
                if os.name!='nt' or getattr(error,'winerror',None) not in (5,32) or attempt==5:
                    raise
                time.sleep(.05*(attempt+1))
    finally:
        temporary.unlink(missing_ok=True)


def load_manifest(config):
    path = Path(config['dataset_dir']).resolve()
    manifest = read(path/'dataset.json')
    if manifest.get('version')!='axis-dataset-v3' or not manifest.get('preparation_identity'):
        raise FactorContractError('explicit versioned prepared dataset required')
    semantic = manifest['preparation_identity']['semantic_config']
    if semantic['feature_schema']!=GRAPH_VERSION or semantic['label_protocol']!=config['label_protocol']:
        raise FactorContractError('dataset feature/label protocol differs')
    from prepare_v3 import verify_preparation_implementation
    verify_preparation_implementation(manifest)
    return manifest


def binding_for(config,manifest):
    recipe = {k:deepcopy(v) for k,v in config.items() if k not in ('run_dir','dataset_dir','checkpoint','load_mode')}
    implementation = {name:digest((ROOT/name).read_text('utf-8-sig').replace('\r\n','\n')) for name in
                      ('train_v3.py','runtime.py','assessment.py')}
    return dict(dataset=manifest['preparation_identity']['semantic_id'],split=digest(dict(
        version=manifest['split_version'],config=manifest['preparation_identity']['semantic_config']['split'],
        source_components=sorted(manifest['grouping']['groups']))),
        calibration=digest(dict(version='unfitted',reserved_groups=sorted(config.get('calibration_groups',())))),recipe=digest(dict(config=recipe,implementation=implementation)))


def batches(data_dir,manifest,fold,size=32,seed=None,skip=0):
    if fold not in ('train','validation'):
        raise FactorContractError('base runner never opens final/retrospective/quarantine shards')
    if type(size) is not int or not 1<=size<=64 or type(skip) is not int or skip<0:
        raise FactorContractError('bounded batch size and nonnegative next-batch cursor required')
    root = Path(data_dir).resolve()
    shards = sorted(manifest['shards'].get(fold,()),key=lambda v:v['file'])
    if seed is not None:
        random.Random(seed).shuffle(shards)
    index,pending = 0,[]
    for shard in shards:
        path = (root/shard['file']).resolve()
        if not path.is_relative_to(root):
            raise FactorContractError('dataset shard escapes its directory')
        with gzip.open(path,'rt',encoding='utf-8') as stream:
            rows = [json.loads(line) for line in stream]
        if len(rows)!=shard['records'] or digest(rows)!=shard['semantic_records']:
            raise FactorContractError('parsed dataset records changed')
        if any(r.get('schema_version')!='axis-training-record-v3' or r['supervision']['partition']!=fold for r in rows):
            raise FactorContractError('shard schema/partition differs')
        if seed is not None:
            random.Random(digest((seed,shard['file']))).shuffle(rows)
        pending.extend(rows)
        while len(pending)>=size:
            if index>=skip:
                yield index,pending[:size]
            pending = pending[size:]
            index += 1
    if pending and index>=skip:
        yield index,pending


def predict_saved(trainer,records,*,max_axis_queries=1000000):
    """Explicit diagnostic raw predictions on saved evaluation coordinates."""
    import torch
    from ygo_kito.multifactor.graph_training import cells
    from ygo_kito.multifactor.network import encode_batch
    if type(max_axis_queries) is not int or max_axis_queries<1:
        raise FactorContractError('positive axis-query evaluation budget required')
    queries,keys,misses,domains = [],[],[],[]
    for b,row in enumerate(records):
        example,graph,candidates = observation_view(row)
        domain = query_domain(example,graph,candidates)
        domains.append(domain)
        if len(domain['axes'])*len(domain['members'])>max_axis_queries:
            raise FactorContractError('full axis/member query budget exceeded; no partial evaluation')
        for task,subject,coordinate,_ in cells(row['targets']):
            if task=='state_readiness':
                continue
            if missing_axis_query(domain,task,subject,coordinate):
                misses.append((row['record_id'],query_key(task,subject,coordinate)))
                continue
            if task=="copy_preference":
                comparison=comparison_for_record(row)
                if tuple(subject)!=(comparison["left_key"],comparison["right_key"]) or coordinate!="preference":
                    raise FactorContractError("evaluation preference endpoints differ from paired configurations")
            else:
                validate_query(domain,task,subject,coordinate)
            queries.append((b,task,subject,coordinate))
            keys.append((row['record_id'],query_key(task,subject,coordinate)))
    if not records:
        return {}
    saved = {r['record_id']:{'raw':{},'probabilities':{},'axis_probabilities':{},'axes':{'raw':[]}} for r in records}
    for rid,key in misses:
        saved[rid]['raw'][key] = None
    batch = encode_batch(records,device=trainer.device,config=trainer.model.config)
    was_training = trainer.model.training
    trainer.model.eval()
    try:
        with torch.no_grad():
            output = trainer.model(batch)
            scores = []
            for start in range(0,len(queries),32):
                scores.extend(trainer.model.score_queries(output,batch,queries[start:start+32]))
            for (_,task,_,_),score,(rid,key) in zip(queries,scores,keys):
                saved[rid]['raw'][key] = TASK_DOMAINS[task][int(score.argmax())] if task in CATEGORY_COORDINATES else float(score.sigmoid())
                saved[rid]['probabilities'][key] = ({k:float(v) for k,v in zip(TASK_DOMAINS[task],score.softmax(-1))}
                    if task in CATEGORY_COORDINATES else float(score.sigmoid()))
            # Decode all natural candidates over the full observable member
            # domain. Annotation coordinates never restrict candidate recall.
            for b,(row,domain) in enumerate(zip(records,domains)):
                for axis in domain['axes']:
                    selected = []
                    member_probabilities = {}
                    members = domain['members']
                    for start in range(0,len(members),32):
                        block = members[start:start+32]
                        logits = trainer.model.score_queries(output,batch,[(b,'axis_membership',(axis,m),'member') for m in block])
                        member_probabilities.update({m:float(score.sigmoid()) for m,score in zip(block,logits)})
                        selected.extend(m for m,score in zip(block,logits) if float(score.sigmoid())>=.5)
                    saved[row['record_id']]['axis_probabilities'][axis] = member_probabilities
                    if len(selected)>1:
                        saved[row['record_id']]['axes']['raw'].append(dict(candidate_ref=axis,members=sorted(selected)))
    finally:
        trainer.model.train(was_training)
    return saved


def evaluate_rows(trainer,iterator,protocol,*,reserved_groups=()):
    from assessment import assess_records
    rows,predictions = [],{}
    reserved = set(reserved_groups)
    for _,part in iterator:
        selected = [r for r in part if r['provenance']['leakage_group'] not in reserved]
        if selected:
            rows.extend(selected)
            predictions.update(predict_saved(trainer,selected))
    scoped = deepcopy(protocol)
    scoped['partitions'] = ['validation']
    return assess_records(rows,predictions,scoped),predictions


def selection_score(report,tasks,metric='source_macro_accuracy'):
    if not tasks or len(set(tasks))!=len(tasks) or set(tasks)-set(LEARNED_TASKS):
        raise FactorContractError('selection tasks must be a fixed nonempty subset of learned heads')
    values = report['partitions']['validation']['layers']['raw']['tasks']
    if metric!='source_macro_accuracy':
        raise FactorContractError('unsupported selection metric')
    if any(not values[t].get('complete_class_coverage') or values[t]['source_macro']['overall_accuracy'] is None for t in tasks):
        return None
    return sum(values[t]['source_macro']['overall_accuracy'] for t in tasks)/len(tasks)


def validate_execution(config):
    engineering = config.get('execution_mode')=='engineering_fixture'
    if config.get('automatic_lora') is not False or config.get('core_course_resumed') is not False:
        raise FactorContractError('automatic adaptation/course activation is not supported')
    if engineering:
        if config.get('formal_training') is not False or config.get('device')!='cpu' or not 1<=config.get('epochs',0)<=3 or not 1<=config.get('engineering_max_records',0)<=64:
            raise FactorContractError('engineering mode requires CPU, <=3 epochs and <=64 explicit fixture records')
    elif config.get('formal_training') is not True:
        raise FactorContractError('formal training remains paused')
    for name,value,limit in (('batch_size',config['batch_size'],64),('effective_batch_size',config.get('effective_batch_size',config['batch_size']),64),
                             ('epochs',config['epochs'],10000),('save_every_batches',config['save_every_batches'],1000000),('patience',config.get('patience',config['epochs']),10000)):
        if type(value) is not int or not 1<=value<=limit:
            raise FactorContractError('invalid '+name)
    if type(config.get('minimum_improvement',0)) not in (int,float) or not 0<=config.get('minimum_improvement',0)<=1:
        raise FactorContractError('invalid minimum improvement')
    tasks=config.get('selection_tasks')
    if not isinstance(tasks,list) or not tasks or len(set(tasks))!=len(tasks) or set(tasks)-set(LEARNED_TASKS):
        raise FactorContractError('explicit fixed selection tasks required')
    return engineering


def inspect_data(config,manifest):
    """Shared pre-update validation and coverage report; never constructs a model."""
    from ygo_kito.multifactor.graph_training import cells,GROUPS
    engineering=validate_execution(config)
    label_protocol=digest(config['label_protocol'])
    components={'train':set(),'validation':set()}
    seen_ids=set()
    reserved=set(config.get('calibration_groups',()))
    counts=defaultdict(lambda:defaultdict(int))
    sources=defaultdict(set)
    coverage={'train':defaultdict(set),'validation':defaultdict(set),'calibration':defaultdict(set)}
    for fold in components:
        for _,part in batches(config['dataset_dir'],manifest,fold,config['batch_size']):
            for row in part:
                record_sources(row,label_protocol_sha256=label_protocol)
                if row['record_id'] in seen_ids:
                    raise FactorContractError('duplicate prepared record id')
                seen_ids.add(row['record_id'])
                group=row['provenance']['leakage_group']
                components[fold].add(group)
                scope='calibration' if group in reserved and fold=='validation' else fold
                for task,subject,coordinate,cell in cells(row['targets']):
                    key=(scope,task,coordinate)
                    counts[key][cell.status]+=1
                    sources[key].add(group)
                    if not cell.known:
                        continue
                    value=cell.value if task in CATEGORY_COORDINATES else int(cell.value>=.5)
                    counts[key]['class:'+str(value)]+=1
                    effective=True
                    if fold=='train':
                        origins=row['supervision']['cell_sources'].get(query_key(task,subject,coordinate),())
                        effective=bool(row['supervision'].get('trainable') and cell.confidence and
                            max((s['confidence'] for s in origins),default=0) and row['supervision'].get('confidence',1) and
                            any(task in names and config.get('task_weights',{}).get(g,weight)>0 for g,(weight,names) in GROUPS.items()))
                    if effective:
                        coverage[scope][task,coordinate].add(value)
                        counts[key]['effective']+=1
                if engineering and (set(row['supervision'].get('source_kinds',()))-{'engineering_fixture','definition_development'} or
                        row['supervision'].get('kind') not in ('engineering_fixture','definition_development') or
                        any(s.get('kind') not in ('engineering_fixture','definition_development') for origins in row['supervision'].get('cell_sources',{}).values() for s in origins)):
                    raise FactorContractError('engineering runner rejects real supervision')
    if engineering and len(seen_ids)>config['engineering_max_records']:
        raise FactorContractError('engineering record budget exceeded')
    if components['train']&components['validation'] or not reserved<=components['validation']:
        raise FactorContractError('source partition/calibration reservation differs')
    missing=[]
    tasks={}
    for task in LEARNED_TASKS:
        classes=set(TASK_DOMAINS[task]) if task in CATEGORY_COORDINATES else {0,1}
        required=BINARY_COORDINATES.get(task,(CATEGORY_COORDINATES.get(task,'value'),))
        task_gaps=[]
        if not any(t==task and values for (t,_),values in coverage['train'].items()):
            task_gaps.append('no effective training labels')
        keys=[(t,c) for t,c in coverage['validation'] if t==task]
        if not keys or set().union(*(coverage['validation'][key] for key in keys))!=classes:
            task_gaps.append('development classes uncovered')
        if not engineering and task in BINARY_COORDINATES and any(coverage['validation'][task,c]!=classes for c in required):
            task_gaps.append('development output coordinates uncovered')
        if task in config['selection_tasks']:
            missing.extend(task+':'+reason for reason in task_gaps)
        tasks[task]=dict(selected=task in config['selection_tasks'],missing=task_gaps,required_classes=sorted(classes,key=str),
            partitions={scope:[dict(coordinate=c,counts=dict(counts[scope,task,c]),source_groups=len(sources[scope,task,c]),
                effective_classes=sorted(coverage[scope][task,c],key=str),
                missing_classes=sorted(classes-coverage[scope][task,c],key=str)) for c in required] for scope in coverage})
    return dict(ready=not missing,missing=missing,tasks=tasks,records=len(seen_ids),
        training_groups=sorted(components['train']),selection_groups=sorted(components['validation']-reserved),calibration_groups=sorted(reserved))


def latest_checkpoint(run):
    """Recover a published snapshot even if latest.json was not committed yet."""
    candidates=[]
    for path in Path(run).glob('checkpoint-*.pt'):
        if path.resolve().parent!=Path(run).resolve() or not path.is_file():
            raise FactorContractError('checkpoint escapes experiment directory')
        match=re.fullmatch(r'checkpoint-e(\d{4})-b(\d{7})-s(\d{9})-f([01])\.pt',path.name)
        if not match:
            raise FactorContractError('unrecognized checkpoint in experiment')
        candidates.append((tuple(map(int,match.groups())),path))
    return max(candidates)[1] if candidates else None


def fit(config,run,manifest,emit):
    validate_execution(config)
    run = Path(run).resolve()
    data = Path(config['dataset_dir']).resolve()
    if run==data or run.is_relative_to(data) or data.is_relative_to(run):
        raise FactorContractError('training and prepared-data directories must be separate')
    if run.exists():
        if config.get('load_mode')=='resume' and not (run/'experiment.json').is_file():
            raise FactorContractError('resume identity missing; preserve this directory')
        if config.get('load_mode')!='resume' and any(p.name!='.training.lock' for p in run.iterdir()):
            raise FactorContractError('fresh/warm-start needs a new experiment directory')
    import runtime
    with runtime.training_lock(run):
        return _fit(config,run,manifest,emit)


def _fit(config,run,manifest,emit):
    engineering = validate_execution(config)
    import torch
    from ygo_kito.multifactor.network import NetworkConfig
    from ygo_kito.multifactor.training import RoleTrainer
    from ygo_kito.multifactor.graph_training import SAMPLER_VERSION
    run = Path(run).resolve()
    data_dir = Path(config['dataset_dir']).resolve()
    if run==data_dir or run.is_relative_to(data_dir) or data_dir.is_relative_to(run):
        raise FactorContractError('training and prepared-data directories must be separate')
    architecture = NetworkConfig(**config['network'])
    if architecture.feature_schema!=GRAPH_VERSION:
        raise FactorContractError('v3 architecture required')
    binding = binding_for(config,manifest)
    label_protocol = digest(config['label_protocol'])
    mode = config['load_mode']
    checkpoint = config.get('checkpoint')
    if mode not in ('fresh','resume','warm_start'):
        raise FactorContractError('explicit fresh/resume/warm_start required')
    if mode=='resume':
        expected=dict(binding=binding,architecture=asdict(architecture),sampler=SAMPLER_VERSION)
        if read(run/'experiment.json')!=expected:
            raise FactorContractError('resume experiment differs')
        published=latest_checkpoint(run)
        if checkpoint is not None and (published is None or Path(checkpoint).resolve()!=published.resolve()):
            raise FactorContractError('resume must use latest published checkpoint in this experiment')
        checkpoint=published
        if checkpoint is None and any(p.name not in ('.training.lock','experiment.json','recipe.json','partitions.json') and
                not (p.name.endswith('.tmp') and p.is_file()) for p in run.iterdir()):
            raise FactorContractError('incomplete experiment has unexpected artifacts; preserve it')
    if mode=='warm_start' and not checkpoint:
        raise FactorContractError('warm start checkpoint missing')
    kwargs = dict(device=config['device'],expected_label_protocol_sha256=label_protocol,expected_config=architecture,
                  expected_binding=binding,expected_learning_rate=config['learning_rate'],expected_task_weights=config.get('task_weights'),
                  expected_optimizer_config=config.get('optimizer'),expected_gradient_clip=config.get('gradient_clip',1.0))
    checked=inspect_data(config,manifest)
    if not checked['ready']:
        raise FactorContractError('selection preflight: '+'; '.join(checked['missing']))
    components={'train':set(checked['training_groups']),
                'validation':set(checked['selection_groups'])|set(checked['calibration_groups'])}
    if mode!='resume' or checkpoint is None:
        import runtime
        runtime.seed_everything(config['seed'])
        torch.use_deterministic_algorithms(config.get('deterministic',True))
    if mode=='fresh' or checkpoint is None:
        trainer = RoleTrainer(architecture,device=config['device'],label_protocol_sha256=label_protocol,
            learning_rate=config['learning_rate'],binding=binding,task_weights=config.get('task_weights'),
            optimizer_config=config.get('optimizer'),gradient_clip=config.get('gradient_clip',1.0))
    else:
        trainer = RoleTrainer.load(checkpoint,mode=mode,**kwargs)
    effective = config.get('effective_batch_size',config['batch_size'])
    batch_count = (sum(v['records'] for v in manifest['shards'].get('train',()))+effective-1)//effective
    cursor = trainer.sampler_state
    if cursor['epoch']>config['epochs'] or cursor['next_batch']>batch_count or cursor['epoch']==config['epochs'] and cursor['next_batch']!=0 or cursor['finished'] and (cursor['next_batch']!=0 or cursor['epoch']!=config['epochs'] and trainer.run_state.get('stop_reason')!='early_stopping'):
        raise FactorContractError('checkpoint cursor is outside this dataset/epoch schedule')
    protocol = read(ROOT/config['assessment_protocol'])
    if protocol.get('label_protocol')!=config['label_protocol']:
        raise FactorContractError('assessment/training label protocol differs')
    reserved = set(config.get('calibration_groups',()))
    if not run.exists():
        run.mkdir(parents=True)
    config_binding_path = run/'experiment.json'
    identity = dict(binding=binding,architecture=trainer.model.config_dict(),sampler=SAMPLER_VERSION)
    partitions=dict(binding=binding,training_groups=sorted(components['train']),
        selection_groups=sorted(components['validation']-reserved),calibration_groups=sorted(reserved))
    if config_binding_path.exists():
        if mode!='resume' or read(config_binding_path)!=identity:
            raise FactorContractError('existing experiment differs; preserve it and choose a new directory')
        if (run/'partitions.json').exists() and read(run/'partitions.json')!=partitions:
            raise FactorContractError('resume source partitions differ')
        if not (run/'partitions.json').exists():
            write(run/'partitions.json',partitions)
        if not (run/'recipe.json').exists():
            write(run/'recipe.json',config)
    elif mode=='resume':
        raise FactorContractError('resume experiment identity missing')
    else:
        if any(p.name!='.training.lock' for p in run.iterdir()):
            raise FactorContractError('new experiment directory is not empty')
        write(config_binding_path,identity)
        write(run/'recipe.json',config)
        write(run/'partitions.json',partitions)
    best_path = run/'best-development.json'
    best = trainer.run_state['best_score']
    last_saved = None
    def save():
        nonlocal last_saved
        cursor = trainer.sampler_state
        name = f"checkpoint-e{cursor['epoch']:04d}-b{cursor['next_batch']:07d}-s{trainer.steps:09d}-f{int(cursor['finished'])}.pt"
        trainer.save(run/name,data_cursor=json.dumps(cursor,sort_keys=True))
        write(run/'latest.json',dict(file=name,binding=binding,sampler=cursor))
        last_saved = name
        emit('v3_checkpoint',file=name,sampler=dict(cursor),updates=trainer.steps)
        return name
    if mode=='resume' and checkpoint is not None:
        write(run/'latest.json',dict(file=checkpoint.name,binding=binding,sampler=trainer.sampler_state))
    else:
        save()
    if trainer.run_state['best_file'] is not None:
        chosen=Path(trainer.run_state['best_file'])
        if chosen.name!=str(chosen) or not (run/chosen).is_file() or best is None:
            raise FactorContractError('selected checkpoint reference is missing or escapes this run')
        write(best_path,dict(file=str(chosen),score=best,tasks=config['selection_tasks'],binding=binding,scope='development only'))
    if trainer.sampler_state['finished']:
        return dict(updates=trainer.steps,sampler=trainer.sampler_state,resumed_completed=True,
                    stop_reason=trainer.run_state.get('stop_reason'),formal_training=not engineering)
    for epoch in range(trainer.sampler_state['epoch'],config['epochs']):
        training_started=time.perf_counter()
        skip = trainer.sampler_state['next_batch'] if epoch==trainer.sampler_state['epoch'] else 0
        for index,part in batches(data_dir,manifest,'train',effective,config['seed']+epoch,skip):
            if any(r['provenance']['leakage_group'] in reserved for r in part):
                raise FactorContractError('calibration component entered training')
            batch_started=time.perf_counter()
            result = trainer.train_supervised(part,micro_batch_size=config['batch_size'])
            trainer.sampler_state.update(epoch=epoch,next_batch=index+1)
            if (index+1)%config['save_every_batches']==0:
                save()
            emit('v3_batch',epoch=epoch,batch=index,batch_seconds=time.perf_counter()-batch_started,**result)
        training_seconds=time.perf_counter()-training_started
        validation_started=time.perf_counter()
        report,predictions = evaluate_rows(trainer,batches(data_dir,manifest,'validation',config['batch_size']),protocol,reserved_groups=reserved)
        validation_seconds=time.perf_counter()-validation_started
        score = selection_score(report,config['selection_tasks'],config.get('selection_metric','source_macro_accuracy'))
        trainer.sampler_state.update(epoch=epoch+1,next_batch=0)
        improved = score is not None and (best is None or score>best+config.get('minimum_improvement',0))
        trainer.run_state['bad_epochs'] = 0 if improved else trainer.run_state.get('bad_epochs',0)+1
        if improved:
            best = score
            cursor = trainer.sampler_state
        stopping=(trainer.run_state['bad_epochs']>=config.get('patience',config['epochs']) or epoch+1==config['epochs'])
        if stopping:
            trainer.run_state['stop_reason']='early_stopping' if trainer.run_state['bad_epochs']>=config.get('patience',config['epochs']) else 'epochs_complete'
            trainer.sampler_state['finished']=True
        if improved:
            cursor=trainer.sampler_state
            trainer.run_state.update(best_score=score,best_file=f"checkpoint-e{cursor['epoch']:04d}-b{cursor['next_batch']:07d}-s{trainer.steps:09d}-f{int(cursor['finished'])}.pt")
        file = save()
        write(run/f"development-{epoch+1:04d}.json",dict(report=report,raw_predictions=predictions,selection_score=score))
        if improved:
            write(best_path,dict(file=file,score=score,tasks=config['selection_tasks'],binding=binding,scope='development only'))
        emit('v3_epoch',epoch=epoch+1,selection_score=score,selection_complete=score is not None,
             training_seconds=training_seconds,development_seconds=validation_seconds)
        if stopping:
            break
    return dict(updates=trainer.steps,sampler=trainer.sampler_state,checkpoint=last_saved,selection_score=best,
                final_evaluated=False,calibration_fitted=False,capability_accepted=False,
                stop_reason=trainer.run_state['stop_reason'],formal_training=not engineering)


def finish(config,run,emit):
    """Explicit development-only saved-prediction assessment; no final read."""
    from ygo_kito.multifactor.network import NetworkConfig
    from ygo_kito.multifactor.training import RoleTrainer
    manifest = load_manifest(config)
    run = Path(run)
    latest = read(run/'latest.json')
    trainer = RoleTrainer.load(run/latest['file'],expected_config=NetworkConfig(**config['network']),
        expected_binding=binding_for(config,manifest),expected_label_protocol_sha256=digest(config['label_protocol']),
        device=config['device'],expected_learning_rate=config['learning_rate'],expected_task_weights=config.get('task_weights'))
    report,predictions = evaluate_rows(trainer,batches(config['dataset_dir'],manifest,'validation',config['batch_size']),
        read(ROOT/config['assessment_protocol']),reserved_groups=config.get('calibration_groups',()))
    write(run/'development-assessment.json',dict(report=report,raw_predictions=predictions,capability_accepted=False))
    emit('v3_development_assessment',final_evaluated=False,capability_accepted=False)
    return report


def main_config(config):
    validate_execution(config)
    import runtime
    os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
    import torch
    runtime.warn_if_hash_seed_unset()
    manifest = load_manifest(config)
    def emit(event,**values):
        print(json.dumps(dict(event=event,**values),ensure_ascii=False),flush=True)
    return fit(config,Path(config['run_dir']),manifest,emit)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    args = parser.parse_args()
    return main_config(read(args.config))


if __name__=='__main__':
    main()
