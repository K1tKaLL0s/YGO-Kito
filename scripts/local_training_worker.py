"""One isolated local learning job, owned independently of the chat transport."""
import argparse
import fcntl
from datetime import datetime, timezone
import importlib.util
import hashlib
import re
import json
import os
from pathlib import Path
import signal
import threading
import time
import traceback

def main():
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True)
    p.add_argument('--run-id',required=True);p.add_argument('--job',choices=('fusion','comparison','course'),default='fusion')
    p.add_argument('--resume',action='store_true')
    p.add_argument('--source-root',type=Path);p.add_argument('--resource-base',type=Path);a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9._-]+',a.run_id):raise ValueError('Invalid local run identity')
    base=a.base.resolve()
    if base!=Path(__file__).resolve().parents[2]:raise ValueError('Worker base must be this local project')
    if (base/'reports/training.hold.json').exists():raise RuntimeError('Training is held for repair integration; no learning job was started')
    explicit_roots=a.source_root is not None or a.resource_base is not None
    source_root=base/'source';resource_base=None;continuation=None
    if a.job=='course':
        continuation_path=base/'reports/course-continuation.json'
        if continuation_path.exists():continuation=json.loads(continuation_path.read_text(encoding='utf-8'))
    if explicit_roots:
        if a.source_root is None or a.resource_base is None or a.job!='course' or not a.resume:
            raise ValueError('Explicit source and resource roots require a resumed course')
        source_root=a.source_root.resolve();resource_base=a.resource_base.resolve()
        if source_root!=Path(__file__).resolve().parents[1]:raise ValueError('Source root must be this worker repository')
        if not isinstance(continuation,dict) or set(continuation)!={'state_root','source_manifest','source_archive'}:
            raise ValueError('Explicit roots require the exact migrated course continuation')
        state_root=Path(continuation['state_root']).resolve()
        if not state_root.is_relative_to(base) or not state_root.is_dir():
            raise ValueError('Explicit roots require an existing migrated course inside this worker base')
        reports=(base/'reports').resolve()
        if any(not Path(continuation[key]).resolve().is_relative_to(reports) for key in ('source_manifest','source_archive')):
            raise ValueError('Migrated execution source artifacts must be inside this worker reports')
    directory=base/'reports/local-training'/a.run_id;directory.mkdir(parents=True,exist_ok=True)
    if (directory/'completed.json').exists():raise RuntimeError('This job already completed; do not replay it')
    lease=base/'reports/local-training/active.lock';stop=directory/'stop.request'
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();pid=os.getpid()
    ticks=Path('/proc/self/stat').read_text().split()[21]
    identity={'run_id':a.run_id,'job':a.job,'pid':pid,'process_start_ticks':ticks,'boot_id':boot,'base':str(base)}
    def alive(old):
        path=Path('/proc')/str(old.get('pid',-1))/'stat'
        return old.get('boot_id')==boot and path.is_file() and path.read_text().split()[21]==old.get('process_start_ticks')
    # This fixed inode is never renamed or unlinked. Hold the OS lock for the
    # whole worker lifetime, including stale-lease inspection and replacement.
    owner_mutex=(lease.parent/'active.mutex').open('a+b')
    try:fcntl.flock(owner_mutex.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        owner_mutex.close()
        raise RuntimeError('Another local learning worker owns the project OS mutex')
    if lease.exists():
        old=json.loads(lease.read_text())
        if alive(old):raise RuntimeError('An identified learning process already owns the project: '+str(old['pid']))
        if not a.resume:raise RuntimeError('Stale lease preserved; inspect the previous boundary before Resume')
        lease.rename(lease.with_name('inactive-'+str(old['pid'])+'-'+str(time.time_ns())+'.json'))
    descriptor=os.open(lease,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as f:json.dump(identity,f)
    if stop.exists():
        if not a.resume:raise RuntimeError('Previous stop request preserved; use Resume')
        stop.rename(stop.with_name('prior-stop-'+str(time.time_ns())+'.request'))
    state=dict(identity,stage='starting',desired='running',started_utc=datetime.now(timezone.utc).isoformat(),formal_course_bo1=0,formal_course_bo3=0)
    mutex=threading.Lock();finished=threading.Event()
    def status(stage=None,**values):
        with mutex:
            if stage is not None:state['stage']=stage
            state.update(values)
            counts=values.get('course',{}).get('complete_training_matches')
            if counts is not None:state.update(formal_course_bo1=counts['bo1'],formal_course_bo3=counts['bo3'],formal_matches=sum(counts.values()))
            state['heartbeat_utc']=datetime.now(timezone.utc).isoformat()
            temp=directory/'status.json.tmp';temp.write_text(json.dumps(state,indent=2)+'\n');temp.replace(directory/'status.json')
    if a.job=='course':
        from local_design_supervision import make_unit_boundary
        status.unit_boundary=make_unit_boundary(base,stop)
        status.course_continuation=continuation
    def heartbeat():
        while not finished.wait(10):status()
    def signal_stop(*_):stop.write_text('safe stop requested by signal\n')
    signal.signal(signal.SIGHUP,signal.SIG_IGN)
    signal.signal(signal.SIGTERM,signal_stop)
    thread=threading.Thread(target=heartbeat,daemon=True);thread.start();status()
    try:
        if (directory/'completed.json').exists():raise RuntimeError('This job is already complete; do not replay it')
        filename={'fusion':'local_foundation_fusion.py','comparison':'local_foundation_comparison.py','course':'local_foundation_course.py'}[a.job]
        path=source_root/'scripts'/filename
        # Preserve the exact orchestration bytes for this launch/resume.
        snapshot=directory/'execution-scripts';snapshot.mkdir(exist_ok=True)
        for script in (Path(__file__),path,path.with_name('local_course_collaboration.py'),path.with_name('local_foundation_comparison.py'),path.with_name('local_course_forecast.py'),path.with_name('local_design_supervision.py'),path.with_name('design_supervisor.py'),path.with_name('local_course_auxiliary.py'),path.with_name('local_course_source_continuation.py'),path.with_name('local_course_recovery.py'),path.with_name('local_course_corrected_flow.py')):
            if script.exists():
                data=script.read_bytes();saved=snapshot/(hashlib.sha256(data).hexdigest()+'-'+script.name)
                if not saved.exists():saved.write_bytes(data)
        status('loading_registered_job',job_script_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),worker_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        spec=importlib.util.spec_from_file_location('registered_local_learning_job',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        options={'unit_boundary':status.unit_boundary,'continuation':getattr(status,'course_continuation',None)} if a.job=='course' else {}
        if explicit_roots:options.update(execution_source_root=source_root,resource_base=resource_base)
        result=module.run(base,directory,stop,status,resume=a.resume,**options)
        status('completed',desired='completed',result=result)
        (directory/'completed.json').write_text(json.dumps(state,indent=2)+'\n')
    except Exception as error:
        paused=(stop.exists() or getattr(error,'pause_requested',False)) and getattr(error,'safe_boundary_saved',False)
        status('paused_at_boundary' if paused else 'failed_needs_inspection',
               desired='paused' if paused else 'needs_inspection',error=repr(error),automatic_retry=False,
               stop_requested=stop.exists(),safe_boundary_confirmed=paused,**getattr(error,'saved_course_status',{}))
        with (directory/'failure.log').open('a') as f:traceback.print_exc(file=f)
        raise
    finally:
        finished.set();thread.join(timeout=2)
        if lease.exists() and json.loads(lease.read_text())==identity:lease.unlink()
        fcntl.flock(owner_mutex.fileno(),fcntl.LOCK_UN);owner_mutex.close()
if __name__=='__main__':main()
