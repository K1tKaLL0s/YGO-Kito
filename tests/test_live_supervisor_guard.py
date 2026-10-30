"""Linux observer process -> production unit guard, synthetic artifacts only."""
from datetime import datetime,timezone
import json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace

from tests import test_design_supervisor as observer_fixtures
write,digest=observer_fixtures.write,observer_fixtures.digest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))


@unittest.skipUnless(sys.platform.startswith('linux'),'live observer uses Linux process identity and flock')
class LiveGuardTests(unittest.TestCase):
    def test_actual_live_guard_allows_one_unit_then_saves_stop_after_observer_exit(self):
        from local_design_supervision import make_unit_boundary,require_running
        from local_foundation_course import execute_cycle
        from ygo_kito.build_contracts import DeckParts
        fixture=observer_fixtures.IndependentDesignSupervisorTests('runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        base=fixture.base
        write(base/'reports/local-training/fixture-main/status.json',dict(desired='running',pid=os.getpid(),
            boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            process_start_ticks=Path('/proc/self/stat').read_text().split()[21],
            heartbeat_utc=datetime.now(timezone.utc).isoformat()))
        log=(base/'observer.log').open('w');self.addCleanup(log.close)
        child=subprocess.Popen([sys.executable,str(fixture.script),'--base',str(base),'--run-id','fixture-supervisor',
                                '--policy',str(fixture.policy_path)],stdout=log,stderr=subprocess.STDOUT)
        def close():
            if child.poll() is None:child.terminate();child.wait(timeout=6)
        self.addCleanup(close)
        deadline=time.monotonic()+8
        while True:
            try:
                _,value=require_running(base)
                if value['verdict']=='clear':break
            except (OSError,ValueError,KeyError,RuntimeError):pass
            if child.poll() is not None or time.monotonic()>deadline:
                self.fail('actual observer did not clear synthetic evidence: '+(base/'observer.log').read_text())
            time.sleep(.05)
        self.assertNotEqual(value['pid'],os.getpid())
        calls=[];saved=[];stop=base/'unit-stop.request'
        def one_unit(n):
            calls.append(n);child.terminate();child.wait(timeout=6)
        course=SimpleNamespace(root=fixture.course/'course',deck=DeckParts.from_dict(fixture.result['construction_candidate']['deck']),
            _task=lambda:SimpleNamespace(sha256=digest(fixture.task)),active_seconds=0.,desired='ready',
            config={'wall_seconds':100.},save=lambda:saved.append(True),run=one_unit,
            status=lambda:{'fixture':'no-learning'},
            models=SimpleNamespace(duel=SimpleNamespace(config=SimpleNamespace(episode_seconds=1.),updates=0),
                builder=SimpleNamespace(updates={'build_goal':0,'build_optimizer':0}),coordinator=SimpleNamespace(updates=0)),
            stage=lambda:'bots-bo1')
        forecast=SimpleNamespace(decide=lambda n:{'action':'train_duel','budget_units':2},
            status=lambda:{'mandatory_rebuild':False},before_training=lambda:None,train_closed_outcomes=lambda:None,
            require_formal_duel=lambda purpose:{'status':'admitted','fixture':'observer-process-only'})
        result=execute_cycle(course,forecast,None,base,fixture.course,stop,lambda *a,**k:None,2,
                             unit_boundary=make_unit_boundary(base,stop))
        self.assertEqual(calls,[1]);self.assertEqual(result['executed_units'],1)
        self.assertTrue(result['paused']);self.assertTrue(saved);self.assertTrue(stop.exists())
        self.assertEqual(course.desired,'paused')
