"""Local, resumable v3 orchestration. Default invocation prepares only."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent.parent / 'src'))

import prepare_v3
import runtime
import train_v3
from ygo_kito.multifactor.contracts import FactorContractError, digest


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return train_v3.read(path)


def write(path, value):
    train_v3.write(path, value)


def load_config(path):
    path = Path(path).resolve()
    config = read(path)
    if config.get('version') != 'axis-automatic-v3':
        raise FactorContractError('axis-automatic-v3 config required')
    def linked(name):
        value = Path(config[name])
        return read(value if value.is_absolute() else path.parent / value)
    preparation, training = linked('prepare_config'), linked('train_config')
    if preparation.get('formal_training') is not False or training.get('formal_training') is not False:
        raise FactorContractError('source recipes must stay paused; use --start for this invocation')
    for recipe in (preparation, training):
        if recipe.get('automatic_lora') is not False or recipe.get('core_course_resumed') is not False:
            raise FactorContractError('automatic adaptation and course activation are not supported')
    if training.get('load_mode') != 'fresh' or training.get('checkpoint') is not None:
        raise FactorContractError('automatic flow resumes its own experiment; external checkpoints are not accepted')
    paths = [Path(preparation['run_dir']).resolve(), Path(training['run_dir']).resolve(), Path(config['state_dir']).resolve()]
    if Path(training['dataset_dir']).resolve() != paths[0]:
        raise FactorContractError('preparation/training dataset paths differ')
    if any(a == b or a.is_relative_to(b) or b.is_relative_to(a) for i,a in enumerate(paths) for b in paths[i+1:]):
        raise FactorContractError('data, training and automatic state directories must be separate')
    post = config.get('postprocess', {})
    if type(post.get('calibrate', False)) is not bool or set(post.get('evaluate_folds', [])) - {'test', 'retrospective_test'}:
        raise FactorContractError('only calibration and explicit test/retrospective evaluation are supported')
    if post.get('evaluate_folds') and not post.get('calibrate'):
        raise FactorContractError('evaluation requires calibration')
    reservation = config['calibration_reservation']
    if (type(reservation.get('minimum_groups')) is not int or reservation['minimum_groups'] < 2 or
            type(reservation.get('fraction')) not in (int,float) or not 0 < reservation['fraction'] < 1):
        raise FactorContractError('calibration needs >=2 groups and fraction in (0,1)')
    if type(config.get('minimum_free_gib')) not in (int,float) or not 0 < config['minimum_free_gib'] <= 1024:
        raise FactorContractError('positive minimum_free_gib required')
    return config, preparation, training


def disk_free(path):
    path = Path(path).resolve()
    while not path.exists():
        path = path.parent
    return shutil.disk_usage(path).free


def hardware(config, training):
    import torch
    from ygo_kito.multifactor.network import NetworkConfig
    NetworkConfig(**training['network'])
    device = torch.device(training['device'])
    info = dict(python=sys.version, executable=sys.executable, torch=torch.__version__, cuda=torch.version.cuda,
                requested_device=str(device), storage={}, cpu_threads=torch.get_num_threads())
    if device.type == 'cuda':
        index = device.index or 0
        if not torch.cuda.is_available() or index >= torch.cuda.device_count():
            raise FactorContractError('requested CUDA device is unavailable; no CPU fallback')
        # Actually allocate and execute on the requested GPU, without creating a model.
        tensor = torch.ones(1, device=device)
        if (tensor + 1).item() != 2:
            raise FactorContractError('CUDA arithmetic preflight failed')
        info['gpu'] = dict(name=torch.cuda.get_device_name(index), total_bytes=torch.cuda.get_device_properties(index).total_memory,
                           free_bytes=torch.cuda.mem_get_info(index)[0])
        del tensor
    elif device.type != 'cpu' or training.get('execution_mode') != 'engineering_fixture':
        raise FactorContractError('formal automatic flow requires explicit CUDA; CPU is for bounded fixtures')
    for name,path in (('state',config['state_dir']),('data',training['dataset_dir']),('run',training['run_dir'])):
        free = disk_free(path)
        info['storage'][name] = dict(path=str(path), free_bytes=free)
        if free < config['minimum_free_gib'] * 1024**3:
            raise FactorContractError('insufficient free space at '+str(path))
    return info


def reserve_groups(training, manifest, policy):
    groups = set()
    for _,rows in train_v3.batches(training['dataset_dir'],manifest,'validation',training['batch_size']):
        groups.update(row['provenance']['leakage_group'] for row in rows)
    if training.get('calibration_groups'):
        return sorted(training['calibration_groups'])
    ordered = sorted(groups, key=lambda g:digest((training['seed'],'calibration',g)))
    count = max(policy['minimum_groups'], round(len(groups)*policy['fraction']))
    # Keep at least one selection group; insufficient calibration remains a reported gap.
    return sorted(ordered[:min(count,max(0,len(groups)-1))])


def prepare_data(preparation, state_dir, emit):
    target = Path(preparation['run_dir']).resolve()
    if target.exists():
        return prepare_v3.prepare(preparation,target,emit)
    attempt = state_dir / ('prepare-attempt-'+uuid.uuid4().hex)
    emit('prepare_attempt',path=str(attempt),destination=str(target))
    manifest = prepare_v3.prepare(preparation,attempt,emit)
    target.parent.mkdir(parents=True,exist_ok=True)
    # Same-volume rename publishes the complete directory, with no replacement.
    if attempt.drive != target.drive:
        raise FactorContractError('preparation attempt and dataset must share a volume')
    attempt.rename(target)
    return manifest


def postprocess(config, training, manifest, state_dir, emit):
    """Only the explicitly configured offline stages; no release or activation."""
    from ygo_kito.multifactor.calibration import Calibration, fit_calibration, model_identity, prediction_bundle, bound_predictions
    from ygo_kito.multifactor.network import NetworkConfig
    from ygo_kito.multifactor.training import RoleTrainer
    import workflow_v3
    post = config.get('postprocess',{})
    if not post.get('calibrate'):
        return dict(status='disabled',evaluations={})
    run = Path(training['run_dir'])
    binding = train_v3.binding_for(training,manifest)
    best = read(run/'best-development.json')
    if best.get('binding') != binding or best.get('tasks') != training['selection_tasks']:
        raise FactorContractError('best-development binding differs')
    chosen = Path(best['file'])
    if chosen.name != str(chosen) or (run/chosen).resolve().parent != run.resolve():
        raise FactorContractError('best checkpoint escapes this experiment')
    trainer = RoleTrainer.load(run/chosen,mode='inference',expected_config=NetworkConfig(**training['network']),
        expected_binding=binding,expected_label_protocol_sha256=digest(training['label_protocol']),device=training['device'])
    model_id = model_identity(trainer)
    dataset_id = binding['dataset']
    partitions = read(run/'partitions.json')
    destination = state_dir/'postprocess'
    destination.mkdir(exist_ok=True)
    def predictions(fold,groups=None):
        rows,actual = workflow_v3.evaluation_records(training['dataset_dir'],fold,groups=groups)
        if actual != dataset_id:
            raise FactorContractError('evaluation dataset differs')
        path = destination/(fold+'-predictions.json')
        if path.exists():
            bundle = read(path)
            bound_predictions(bundle,rows,model_id=model_id,dataset_id=dataset_id)
            emit('predictions_reused',fold=fold)
        else:
            bundle = prediction_bundle(workflow_v3.predict_records(trainer,rows,batch_size=training['batch_size']),rows,
                                       model_id=model_id,dataset_id=dataset_id)
            write(path,bundle)
            emit('predictions_saved',fold=fold)
        return rows,bundle
    rows,bundle = predictions('validation',partitions['calibration_groups'])
    calibration_path = destination/'calibration.json'
    if calibration_path.exists():
        calibration = Calibration(read(calibration_path))
        expected = dict(model_id=model_id,dataset_id=dataset_id,training_groups=partitions['training_groups'],
                        selection_groups=partitions['selection_groups'],calibration_groups=partitions['calibration_groups'])
        if any(calibration.artifact.get(k)!=v for k,v in expected.items()):
            raise FactorContractError('cached calibration binding differs')
    else:
        calibration = fit_calibration(rows,bundle,model_id=model_id,dataset_id=dataset_id,
            training_groups=partitions['training_groups'],selection_groups=partitions['selection_groups'],
            reserved_groups=partitions['calibration_groups'])
        write(calibration_path,calibration.artifact)
    emit('calibration_complete',path=str(calibration_path))
    results = {}
    protocol = read(ROOT/training['assessment_protocol'])
    for fold in post.get('evaluate_folds',[]):
        if not manifest['split_counts'].get(fold):
            results[fold] = dict(status='unavailable',reason='no prepared records in this partition')
            continue
        rows,bundle = predictions(fold)
        identity = dict(model_id=model_id,dataset_id=dataset_id,records_id=bundle['records_id'],
                        calibration=digest(calibration.artifact),protocol=digest(protocol))
        path = destination/(fold+'-assessment.json')
        if path.exists():
            result = read(path)
            if result.get('automatic_binding') != identity:
                raise FactorContractError('cached assessment binding differs')
        else:
            report,saved = workflow_v3.evaluate(rows,bundle,calibration,protocol,training_groups=partitions['training_groups'])
            result = dict(automatic_binding=identity,report=report,predictions=saved)
            write(path,result)
        results[fold] = dict(status='complete',path=str(path),independent=fold=='test')
        emit('evaluation_complete',fold=fold,path=str(path))
    return dict(status='complete',model_id=model_id,checkpoint=str(run/chosen),calibration=str(calibration_path),evaluations=results)


class Tee:
    def __init__(self, console, log):
        self.console,self.log=console,log
    def write(self,text):
        self.console.write(text)
        self.log.write(text)
        self.log.flush()
        return len(text)
    def flush(self):
        self.console.flush()
        self.log.flush()


def run(path, *, start=False):
    config,preparation,base = load_config(path)
    state_dir = Path(config['state_dir']).resolve()
    for key,value in {'CUBLAS_WORKSPACE_CONFIG':':4096:8','OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'2'}.items():
        os.environ.setdefault(key,value)
    identity = digest(dict(config=config,preparation=preparation,training=base,
                           implementation=Path(__file__).read_text('utf-8-sig').replace('\r\n','\n')))
    with runtime.training_lock(state_dir):
        state_path = state_dir/'state.json'
        if state_path.exists():
            state = read(state_path)
            if state.get('identity') != identity:
                raise FactorContractError('automatic run config/implementation differs; use a new state/run/data version as needed')
        else:
            if any(p.name!='.training.lock' for p in state_dir.iterdir()):
                raise FactorContractError('unbound automatic state directory is not empty')
            state = dict(version='axis-automatic-state-v3',identity=identity,created_at=now(),attempts=0)
        state['attempts'] += 1
        attempt = state['attempts']
        log_path = state_dir/f'attempt-{attempt:04d}.log'
        events_path = state_dir/'events.jsonl'
        started,cpu_started = time.monotonic(),time.process_time()
        state.update(status='running',stage='hardware',started_at=now(),pid=os.getpid(),log=str(log_path),formal_start_requested=start)
        summary = dict(version='axis-automatic-summary-v3',state_dir=str(state_dir),training_dir=base['run_dir'],
                       dataset_dir=base['dataset_dir'],formal_training_started=False,model_activated=False,log=str(log_path))
        measurement=None
        batch_times=[]
        observed_development=None
        with log_path.open('x',encoding='utf-8') as log, events_path.open('a',encoding='utf-8') as events:
            def emit(event,**values):
                nonlocal observed_development
                entry=dict(time=now(),attempt=attempt,event=event,**values)
                line=json.dumps(entry,ensure_ascii=False,allow_nan=False)
                print(line,flush=True)
                events.write(line+'\n');events.flush()
                if event in ('v3_batch','v3_epoch','v3_checkpoint'):
                    if event=='v3_batch' and not values.get('skipped',False):
                        summary['formal_training_started']=base.get('execution_mode')!='engineering_fixture'
                    state['progress']=entry
                    if measurement is not None and event in ('v3_batch','v3_epoch'):
                        import statistics
                        from timing_v3 import forecast
                        if event=='v3_batch':batch_times.append(values['batch_seconds'])
                        else:observed_development=values['development_seconds']
                        estimate=forecast(training,manifest,measurement,
                            batch_seconds=statistics.median(batch_times[-10:]) if batch_times else None,
                            completed_epoch=values['epoch'],next_batch=values['batch']+1 if event=='v3_batch' else 0,
                            development_seconds=observed_development)
                        write(state_dir/'estimate.json',estimate)
                        state['estimate']={k:estimate[k] for k in ('estimated_complete_at','estimated_check_at','remaining_seconds')}
                    write(state_path,state)
            def stage(name):
                state.update(stage=name,status='running',updated_at=now())
                write(state_path,state)
                emit('stage_started',stage=name)
            with redirect_stdout(Tee(sys.stdout,log)),redirect_stderr(Tee(sys.stderr,log)):
                try:
                    stage('hardware')
                    summary['hardware']=hardware(config,base)
                    write(state_dir/'hardware.json',summary['hardware'])
                    stage('prepare')
                    manifest=prepare_data(preparation,state_dir,emit)
                    training=deepcopy(base)
                    training['formal_training']=training.get('execution_mode')!='engineering_fixture'
                    training['calibration_groups']=reserve_groups(training,manifest,config['calibration_reservation'])
                    stage('preflight')
                    checked=train_v3.inspect_data(training,manifest)
                    if len(checked['calibration_groups'])<config['calibration_reservation']['minimum_groups']:
                        checked['missing'].append('insufficient reserved calibration source groups')
                    checked['ready']=not checked['missing']
                    checked.update(dataset_id=manifest['preparation_identity']['semantic_id'],split_counts=manifest['split_counts'],
                                   source_counts=manifest['source_counts'],new_independent_final=manifest['new_independent_final'])
                    if config.get('require_full18_readiness'):
                        from readiness_v3 import check
                        complete=check(training,manifest,checked,config['full18_evidence_dir'])
                        write(state_dir/'full18-readiness.json',complete)
                        checked['missing'].extend(complete['missing'])
                        checked['ready']=not checked['missing']
                        summary['full18_readiness']=str(state_dir/'full18-readiness.json')
                    write(state_dir/'coverage.json',checked)
                    frozen=dict(dataset_id=checked['dataset_id'],training_groups=checked['training_groups'],
                                selection_groups=checked['selection_groups'],calibration_groups=checked['calibration_groups'])
                    partition_path=state_dir/'reserved-partitions.json'
                    if partition_path.exists() and read(partition_path)!=frozen:
                        raise FactorContractError('prepared data or reserved source groups changed')
                    write(partition_path,frozen)
                    write(state_dir/'resolved-train.json',dict(training,formal_training=False))
                    summary.update(ready=checked['ready'],missing=checked['missing'],coverage=str(state_dir/'coverage.json'),partitions=frozen)
                    if not checked['ready']:
                        state['status']='not_ready'
                        emit('preflight_not_ready',missing=checked['missing'])
                    elif not start:
                        state['status']='prepared'
                        emit('prepared_only',training_started=False)
                    else:
                        if config.get('measure_training_time'):
                            stage('cuda-timing-recovery')
                            from timing_v3 import measure,forecast
                            measurement=measure(training,manifest,state_dir/'timing',emit)
                            estimate=forecast(training,manifest,measurement)
                            write(state_dir/'estimate.json',estimate)
                            summary['estimate']=str(state_dir/'estimate.json')
                            write(state_dir/'dot-handoff.json',dict(version='axis-training-dot-handoff-v1',pid=os.getpid(),
                                command=str(ROOT.parent.parent/'scripts'/'axis-generic-training.ps1')+' -Start',
                                state=str(state_path),events=str(events_path),log=str(log_path),
                                training_dir=training['run_dir'],readiness=str(state_dir/'full18-readiness.json'),
                                estimate=str(state_dir/'estimate.json'),estimated_check_at=estimate['estimated_check_at'],
                                task_count=len(training['selection_tasks']),model_activated=False))
                        stage('train')
                        run_dir=Path(training['run_dir'])
                        training['load_mode']='resume' if (run_dir/'experiment.json').exists() else 'fresh'
                        write(state_dir/'invocation-train.json',training)
                        result=train_v3.fit(training,run_dir,manifest,emit)
                        summary['training']=result
                        summary['formal_training_started']=training['formal_training']
                        stage('postprocess')
                        summary['postprocess']=postprocess(config,training,manifest,state_dir,emit)
                        state.update(status='complete',stage='complete')
                        emit('automatic_complete',resumed_completed=result.get('resumed_completed',False),updates=result['updates'])
                except BaseException as error:
                    state['status']='interrupted' if isinstance(error,KeyboardInterrupt) else 'failed'
                    state['error']=dict(type=type(error).__name__,message=str(error))
                    traceback.print_exc()
                    raise
                finally:
                    elapsed=time.monotonic()-started
                    state.update(updated_at=now(),elapsed_seconds=elapsed)
                    if state['status'] not in ('failed','interrupted'):
                        state.pop('error',None)
                    summary.update(status=state['status'],stage=state['stage'],error=state.get('error'),elapsed_seconds=elapsed,
                                   cpu_seconds=time.process_time()-cpu_started,finished_at=now())
                    if 'torch' in sys.modules:
                        torch=sys.modules['torch']
                        if torch.cuda.is_initialized():
                            summary['gpu_peak_allocated_bytes']=torch.cuda.max_memory_allocated(base['device'])
                    write(state_path,state)
                    write(state_dir/'summary.json',summary)
        return summary


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default=str(ROOT/'config.automatic.v3.json'))
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--start',action='store_true',help='explicitly start or resume local training after preparation')
    mode.add_argument('--status',action='store_true',help='read saved state without executing stages')
    args=parser.parse_args()
    try:
        if args.status:
            config,_,_=load_config(args.config)
            result=read(Path(config['state_dir'])/'state.json')
        else:
            result=run(args.config,start=args.start)
        print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
        return 2 if result.get('status')=='not_ready' else 0
    except KeyboardInterrupt:
        print('Interrupted. Run the same --start command to resume.',file=sys.stderr)
        return 130
    except Exception as error:
        print(type(error).__name__+': '+str(error),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
