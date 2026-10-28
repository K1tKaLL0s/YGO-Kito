"""Require a fresh, separate observer before each formal match."""
from datetime import datetime,timezone
import hashlib,json,time,os
from pathlib import Path


def require_running(base):
    policy_path=base/'reports/design-supervision-policy.json'
    policy=json.loads(policy_path.read_text())
    path=base/'reports/local-training'/policy['supervisor_run_id']/'status.json'
    value=json.loads(path.read_text())
    proc=Path('/proc')/str(value['pid'])/'stat'
    if (value.get('job')!='supervisor' or value.get('pid')==os.getpid()
        or value.get('run_id')!=policy['supervisor_run_id'] or policy['supervisor_run_id']==policy['main_run_id']
        or value['boot_id']!=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        or not proc.exists() or proc.read_text().split()[21]!=value['process_start_ticks']
        or value['policy_sha256']!=hashlib.sha256(policy_path.read_bytes()).hexdigest()
        or value['script_sha256']!=policy['supervisor_script_sha256']
        or value.get('desired')!='running'
        or (datetime.now(timezone.utc)-datetime.fromisoformat(value['heartbeat_utc'])).total_seconds()>15):
        raise RuntimeError('Independent supervisor is unavailable; formal training stays stopped')
    return policy,value


def require_clearance(base,course,target,stop):
    from ygo_kito.build_contracts import digest
    reason='independent evidence has not been observed yet'
    for _ in range(10):
        try:
            policy,value=require_running(base)
            if Path(policy['course_root']).resolve()!=target.resolve():raise RuntimeError('Observer is attached to a different course')
            if value['verdict']=='violation':raise RuntimeError(value.get('reason','design violation'))
            if value['verdict']=='clear' and any(r['deck_sha256']==digest(course.deck.to_dict()) and
                    r.get('task_sha256')==course._task().sha256 for r in value['receipts']):return
            reason=value.get('reason') or reason
        except (OSError,ValueError,KeyError,RuntimeError) as error:reason=str(error)
        time.sleep(1)
    stop.write_text('Safe stop required by independent supervision: '+reason+'\n')
    course.save();error=RuntimeError('Independent supervision requires inspection: '+reason)
    error.safe_boundary_saved=True
    error.saved_course_status={'course':course.status(),'goal_updates':course.models.builder.updates['build_goal'],
        'optimizer_updates':course.models.builder.updates['build_optimizer'],'duel_updates':course.models.duel.updates,'coordinator_updates':course.models.coordinator.updates}
    raise error


def make_unit_boundary(base,stop):
    """Attach the independent observer to the production course's real units."""
    def boundary(phase,course,forecasts,plan,executed):
        try:
            if (base/'reports/training.hold.json').exists():
                raise RuntimeError('Training hold remains active')
            policy,value=require_running(base)
            target=course.root.parent
            if Path(policy['course_root']).resolve()!=target.resolve():
                raise RuntimeError('Observer is attached to a different course')
            if value.get('verdict')=='violation':raise RuntimeError(value.get('reason') or 'design violation')
            bootstrap=(phase=='before' and course.deck is None and plan['action'] in ('build_goal','build_optimizer')
                and value.get('verdict')=='unknown' and str(value.get('reason','')).startswith('awaiting initial four-step construction evidence;'))
            if not bootstrap:require_clearance(base,course,target,stop)
            return True
        except (OSError,ValueError,KeyError,RuntimeError) as error:
            stop.write_text('Independent unit supervision requires a saved stop: '+str(error)+'\n',encoding='utf-8')
            return False
    return boundary




def require_artifact_clearance(base,course,target,artifact,stop):
    reason='new construction evidence has not been independently observed yet'
    expected=hashlib.sha256(artifact.read_bytes()).hexdigest()
    relative=str(artifact.relative_to(target))
    for _ in range(10):
        try:
            policy,value=require_running(base)
            if Path(policy['course_root']).resolve()!=target.resolve():raise RuntimeError('Observer is attached to a different course')
            if value['verdict']=='violation':raise RuntimeError(value.get('reason','design violation'))
            if value['verdict']=='clear' and any(r['artifact']==relative and r['artifact_sha256']==expected for r in value['receipts']):return
            reason=value.get('reason') or reason
        except (OSError,ValueError,KeyError,RuntimeError) as error:reason=str(error)
        time.sleep(1)
    stop.write_text('Safe stop required by independent construction supervision: '+reason+'\n')
    course.save();error=RuntimeError('Independent construction supervision requires inspection: '+reason)
    error.safe_boundary_saved=True
    error.saved_course_status={'course':course.status(),'goal_updates':course.models.builder.updates['build_goal'],
        'optimizer_updates':course.models.builder.updates['build_optimizer'],'duel_updates':course.models.duel.updates,'coordinator_updates':course.models.coordinator.updates}
    raise error

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);a=p.parse_args()
    policy,status=require_running(a.base)
    print(json.dumps({'supervisor_pid':status['pid'],'verdict':status['verdict'],'formal_guard_installed':True}))
