"""Bounded CUDA timing/recovery checks and transparent runtime estimates."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
import math
import statistics
import time

from ygo_kito.multifactor.contracts import FactorContractError,digest


def forecast(training,manifest,measurement,*,batch_seconds=None,completed_epoch=0,next_batch=0,development_seconds=None):
    effective=training.get('effective_batch_size',training['batch_size'])
    batches=math.ceil(manifest['split_counts']['train']/effective)
    batch_time=measurement['train_batch_seconds'] if batch_seconds is None else batch_seconds
    dev_time=measurement['development_epoch_seconds'] if development_seconds is None else development_seconds
    epochs=training['epochs'];pending_current=0 if completed_epoch>=epochs else max(0,batches-next_batch)
    pending_epochs=max(0,epochs-completed_epoch-1)
    training_remaining=(pending_current+pending_epochs*batches)*batch_time
    io_remaining=max(0,epochs-completed_epoch)*measurement.get('training_io_epoch_seconds',0.)
    validation_remaining=max(0,epochs-completed_epoch)*dev_time
    post=measurement.get('postprocess_seconds',0.)
    seconds=training_remaining+io_remaining+validation_remaining+post
    earliest_epochs=min(epochs,training.get('patience',epochs)+1)
    earliest=max(0,earliest_epochs-completed_epoch)*(batches*batch_time+dev_time+measurement.get('training_io_epoch_seconds',0.))+post
    current=datetime.now(timezone.utc)
    local=timezone(timedelta(hours=8))
    return dict(version='axis-runtime-estimate-v1',updated_at=current.isoformat(),timezone='Asia/Hong_Kong',
        batches_per_epoch=batches,maximum_epochs=epochs,early_stopping_earliest_epoch=earliest_epochs,
        batch_seconds=batch_time,development_epoch_seconds=dev_time,remaining_seconds=seconds,
        possible_early_stop_remaining_seconds=earliest,estimated_complete_at=(current+timedelta(seconds=seconds)).astimezone(local).isoformat(),
        estimated_check_at=(current+timedelta(seconds=seconds*1.25)).astimezone(local).isoformat(),
        uncertainty='Initial sample extrapolation; updated by actual batches/epochs. Check time includes a 25% timing margin; early stopping is not predicted.',
        measurement_binding=measurement['binding'])


def measure(training,manifest,destination,emit):
    import torch
    import runtime
    import train_v3
    from ygo_kito.multifactor.network import NetworkConfig
    from ygo_kito.multifactor.training import RoleTrainer
    destination=Path(destination);destination.mkdir(exist_ok=True)
    binding=train_v3.binding_for(training,manifest)
    identity=dict(binding=binding,device=training['device'],torch=torch.__version__,network=training['network'])
    path=destination/'measurement.json'
    if path.exists():
        result=train_v3.read(path)
        if result.get('identity')!=identity or result.get('recovery_equal') is not True:
            raise FactorContractError('timing measurement differs; preserve it and use a new run')
        return result
    if torch.device(training['device']).type!='cuda':raise FactorContractError('real timing requires requested CUDA')
    runtime.seed_everything(training['seed']);torch.use_deterministic_algorithms(training.get('deterministic',True))
    architecture=NetworkConfig(**training['network'])
    trainer=RoleTrainer(architecture,device=training['device'],label_protocol_sha256=digest(training['label_protocol']),
        learning_rate=training['learning_rate'],binding=binding,task_weights=training.get('task_weights'),
        optimizer_config=training.get('optimizer'),gradient_clip=training.get('gradient_clip',1.))
    device=trainer.device
    iterator=train_v3.batches(training['dataset_dir'],manifest,'train',training.get('effective_batch_size',training['batch_size']),training['seed'])
    started=time.perf_counter();_,first=next(iterator);load_seconds=time.perf_counter()-started
    try:_,second=next(iterator)
    except StopIteration:second=first
    times=[]
    def update(rows):
        torch.cuda.synchronize(device);started=time.perf_counter()
        result=trainer.train_supervised(rows,micro_batch_size=training['batch_size'])
        torch.cuda.synchronize(device);elapsed=time.perf_counter()-started
        if result.get('skipped') or not math.isfinite(result['loss']):raise FactorContractError('timing sample has no finite real update')
        times.append(elapsed);emit('timing_batch',seconds=elapsed,loss=result['loss'],sample_records=len(rows))
        return result
    update(first)
    checkpoint=destination/'recovery-sample.pt'
    # A failed measurement never silently reuses a partial checkpoint.
    if checkpoint.exists():raise FactorContractError('unfinished timing snapshot exists; inspect before retry')
    trainer.save(checkpoint)
    update(second)
    expected={k:v.detach().clone() for k,v in trainer.model.state_dict().items()}
    original_steps=trainer.steps
    del trainer
    trainer=RoleTrainer.load(checkpoint,mode='resume',device=training['device'],expected_config=architecture,
        expected_binding=binding,expected_label_protocol_sha256=digest(training['label_protocol']),
        expected_learning_rate=training['learning_rate'],expected_task_weights=training.get('task_weights'),
        expected_optimizer_config=training.get('optimizer'),expected_gradient_clip=training.get('gradient_clip',1.))
    update(second)
    equal=trainer.steps==original_steps and all(torch.equal(expected[k],v) for k,v in trainer.model.state_dict().items())
    if not equal:raise FactorContractError('CUDA checkpoint resume next update differs')
    reserved=set(training['calibration_groups']);validation=[]
    for _,part in train_v3.batches(training['dataset_dir'],manifest,'validation',training['batch_size']):
        validation.extend(r for r in part if r['provenance']['leakage_group'] not in reserved)
        if len(validation)>=2:break
    if not validation:raise FactorContractError('no development sample for timing')
    sample=validation[:2]
    protocol=train_v3.read(train_v3.ROOT/training['assessment_protocol'])
    torch.cuda.synchronize(device);started=time.perf_counter()
    train_v3.evaluate_rows(trainer,[(0,sample)],protocol)
    torch.cuda.synchronize(device);development_sample_seconds=time.perf_counter()-started
    dev_count=0;cal_count=0
    for _,part in train_v3.batches(training['dataset_dir'],manifest,'validation',training['batch_size']):
        for row in part:
            if row['provenance']['leakage_group'] in reserved:cal_count+=1
            else:dev_count+=1
    per_record=development_sample_seconds/len(sample)
    train_io=load_seconds*len(manifest['shards'].get('train',()))
    result=dict(version='axis-cuda-timing-v1',identity=identity,binding=binding,recovery_equal=True,
        finite_updates=len(times),sample_train_records=[len(first),len(second)],batch_times=times,
        train_batch_seconds=statistics.median(times),first_shard_load_seconds=load_seconds,
        training_io_epoch_seconds=train_io,development_sample_records=len(sample),
        development_sample_seconds=development_sample_seconds,development_epoch_seconds=per_record*dev_count,
        selection_records=dev_count,calibration_records=cal_count,
        postprocess_seconds=per_record*(cal_count+manifest['split_counts'].get('retrospective_test',0)+manifest['split_counts'].get('test',0)),
        peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(device),published_or_activated=False)
    train_v3.write(path,result)
    emit('cuda_timing_recovery_complete',recovery_equal=True,batch_seconds=result['train_batch_seconds'],development_epoch_seconds=result['development_epoch_seconds'])
    del trainer,expected
    torch.cuda.empty_cache()
    return result
