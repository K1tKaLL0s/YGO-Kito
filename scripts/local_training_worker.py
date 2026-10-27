"""One isolated local learning job, owned independently of the chat transport."""
import argparse
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
    p.add_argument('--resume',action='store_true');a=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9._-]+',a.run_id):raise ValueError('Invalid local run identity')
    base=a.base.resolve()
    if base!=Path(__file__).resolve().parents[2]:raise ValueError('Worker base must be this local project')
    directory=base/'reports/local-training'/a.run_id;directory.mkdir(parents=True,exist_ok=True)
    if (directory/'completed.json').exists():raise RuntimeError('This job already completed; do not replay it')
    lease=base/'reports/local-training/active.lock';stop=directory/'stop.request'
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();pid=os.getpid()
    ticks=Path('/proc/self/stat').read_text().split()[21]
    identity={'run_id':a.run_id,'job':a.job,'pid':pid,'process_start_ticks':ticks,'boot_id':boot,'base':str(base)}
    def alive(old):
        path=Path('/proc')/str(old.get('pid',-1))/'stat'
        return old.get('boot_id')==boot and path.is_file() and path.read_text().split()[21]==old.get('process_start_ticks')
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
    def heartbeat():
        while not finished.wait(10):status()
    def signal_stop(*_):stop.write_text('safe stop requested by signal\n')
    signal.signal(signal.SIGHUP,signal.SIG_IGN)
    signal.signal(signal.SIGTERM,signal_stop)
    thread=threading.Thread(target=heartbeat,daemon=True);thread.start();status()
    try:
        if (directory/'completed.json').exists():raise RuntimeError('This job is already complete; do not replay it')
        filename={'fusion':'local_foundation_fusion.py','comparison':'local_foundation_comparison.py','course':'local_foundation_course.py'}[a.job]
        path=base/'source/scripts'/filename
        # Preserve the exact orchestration bytes for this launch/resume.
        snapshot=directory/'execution-scripts';snapshot.mkdir(exist_ok=True)
        for script in (Path(__file__),path,path.with_name('local_course_collaboration.py'),path.with_name('local_foundation_comparison.py')):
            if script.exists():
                data=script.read_bytes();saved=snapshot/(hashlib.sha256(data).hexdigest()+'-'+script.name)
                if not saved.exists():saved.write_bytes(data)
        status('loading_registered_job',job_script_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),worker_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        spec=importlib.util.spec_from_file_location('registered_local_learning_job',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        result=module.run(base,directory,stop,status,resume=a.resume)
        status('completed',desired='completed',result=result)
        (directory/'completed.json').write_text(json.dumps(state,indent=2)+'\n')
    except Exception as error:
        status('paused_at_boundary' if stop.exists() else 'failed_needs_inspection',
               desired='paused' if stop.exists() else 'needs_inspection',error=repr(error),automatic_retry=False)
        with (directory/'failure.log').open('a') as f:traceback.print_exc(file=f)
        raise
    finally:
        finished.set();thread.join(timeout=2)
        if lease.exists() and json.loads(lease.read_text())==identity:lease.unlink()
if __name__=='__main__':main()
