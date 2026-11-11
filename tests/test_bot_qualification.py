"""Exact fixture inputs and mocked execution control; no C#/native execution."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import io
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch, Mock

from tests import test_bot_deployment as source_fixtures
from ygo_kito.bot_deployment import BotSourceRegistry
from ygo_kito.bot_qualification import prepare_qualification, _execute_qualification, execute_qualification, normal_engineering_actor
from ygo_kito.validation import ContractError


class BotQualificationTests(unittest.TestCase):
    def setUp(self):
        fixture = source_fixtures.BotDeploymentTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.root, self.lock = fixture.root, fixture.lock
        for source in ("ice", "pure"):
            fixture.write(source, "Decks/AI_Alpha.ydk",
                          ("#main\n"+"\n".join(map(str, range(1,41)))+"\n#extra\n!side\n").encode())
        self.registry = BotSourceRegistry(fixture.lock, fixture.root)
        versions = dict(core="fixture-core", scripts="fixture-scripts", cards="fixture-cards",
                        protocol="fixture-wire", card_pool="native-private-knowledge-v5", banlist="fixture-ban")
        self.assets = SimpleNamespace(root=self.root, receipt={"scope":"inert source/list fixture"}, limits={},
            rows={c:dict(type=17,alias=0,ot=1,level=4,atk=1000,**{"def":1000}) for c in range(1,41)},
            environment_for=lambda kind:{"versions":versions})
        scoped = patch("ygo_kito.bot_qualification.BuildAssets", return_value=self.assets)
        scoped.start(); self.addCleanup(scoped.stop)
        self.actor = normal_engineering_actor(self.root)
        self.plan = prepare_qualification(self.registry, self.root, self.actor)
        self.ice = next(r for r in self.plan['rows'] if r['source_id']=='ice')
        self.audits = {'ice':{'path':str(self.root/'not-a-real-audit.json'),'sha256':'a'*64}}

    def execute(self, **kwargs):
        return _execute_qualification(self.registry, self.plan, self.root, self.actor, audits=self.audits,
            mono='/unused/mono', workspace=self.root, selected_bot_ids=[self.ice['bot_id']], **kwargs)

    def test_plan_preserves_all_origins_and_never_calls_any_runtime(self):
        with patch.object(self.registry, 'training_adapter') as runtime:
            actual = prepare_qualification(self.registry,self.root,self.actor)
        runtime.assert_not_called()
        self.assertEqual(len(actual['rows']),3)
        self.assertEqual(sum(r['runtime_candidate'] for r in actual['rows']),2)
        self.assertTrue(all(r['list_legal'] for r in actual['rows']))
        self.assertFalse(actual['native_executed']); self.assertFalse(actual['csharp_executed'])
        self.assertFalse(actual['normal_duel_verified'])
        self.assertEqual(actual['training_updates'],0)

    def test_source_tampering_or_changed_plan_rejects_before_execution(self):
        with patch.object(self.registry,'training_adapter') as runtime:
            self.plan['rows'][0]['list_legal']=False
            with self.assertRaisesRegex(ContractError,'plan changed'):
                self.execute()
            self.plan['rows'][0]['list_legal']=True
            (self.root/'ice/Decks/AI_Alpha.ydk').write_text('#main\n999\n')
            with self.assertRaises(ContractError): self.execute()
        runtime.assert_not_called()

    def test_missing_or_rejected_actual_audit_cannot_launch_engine(self):
        with patch.object(self.registry,'training_adapter',side_effect=ContractError('real complete audit absent')) as runtime, \
             patch('ygo_kito.bot_qualification.NativeNormalEngine') as engine:
            result=self.execute()
        self.assertEqual(runtime.call_count,1); engine.assert_not_called()
        row=next(r for r in result['rows'] if r['bot_id']==self.ice['bot_id'])
        self.assertEqual(row['failed_stage'],'runtime_audit_gate')
        self.assertFalse(result['csharp_executed']); self.assertFalse(result['native_executed'])
        self.assertFalse(result['all_selected_normal_verified'])

    def test_partial_start_failure_preserves_unknown_instead_of_false(self):
        @contextmanager
        def failed(*args,**kwargs):
            raise ContractError('managed start outcome uncertain')
            yield  # explicit never-entered fixture
        adapter=SimpleNamespace(managed_engine_factory=failed)
        with patch.object(self.registry,'training_adapter',return_value=adapter) as runtime:
            result=self.execute(seconds=2)
        self.assertEqual(runtime.call_args.kwargs['session_seconds'],2)
        self.assertIsNone(result['csharp_executed']);self.assertIsNone(result['native_executed'])
        self.assertFalse(result['all_selected_normal_verified'])

    def test_complete_loop_requires_terminal_and_actual_bot_choices_fixture_only(self):
        from tests.fixtures import request as fixture_request
        from ygo_kito.contracts import DecisionRequest, validate_selection
        requests=[]
        for observer in (0,1):
            raw=fixture_request();raw['context']['seed']=None
            raw['observation']['observer']=observer
            raw['observation']['cards']=[]
            raw['decision_id']='fixture-window-'+str(observer)
            raw['prompt']={'message':13}
            raw['actions']=[{'action_id':'fixture-yes','kind':'yes','card_refs':[]}]
            requests.append(DecisionRequest.from_dict(raw))
        class ExplicitEngineFixture:
            outcome=None;events=[];turn=2
            def next_decision(self):
                self.pending=requests.pop(0) if requests else None
                if self.pending is None:
                    self.outcome={'winner':1,'reason_code':0};self.events=[{'kind':5}]
                return self.pending
            def submit(self,selection):validate_selection(self.pending,selection)
        engine=ExplicitEngineFixture()
        @contextmanager
        def managed(*args,**kwargs):yield engine
        adapter=SimpleNamespace(managed_engine_factory=managed,seat=1,binding={'explicit':'not-a-real-driver'},
                                policy=SimpleNamespace(choose=lambda r:r.actions[0]))
        with patch.object(self.registry,'training_adapter',return_value=adapter), \
             patch('ygo_kito.bot_qualification.NativeNormalEngine') as native:
            result=self.execute()
        native.assert_not_called()
        self.assertTrue(result['all_selected_normal_verified'])
        selected=next(r for r in result['rows'] if r['bot_id']==self.ice['bot_id'])
        self.assertEqual((selected['decisions'],selected['bot_decisions']),(2,1))
        self.assertTrue(selected['normal_duel_verified'])
        self.assertFalse(result['historical_qualified']);self.assertFalse(result['strength_qualified'])

    def test_default_only_selects_desktop_candidates_and_retains_source_only_rows(self):
        result=_execute_qualification(self.registry,self.plan,self.root,self.actor,audits={},mono='/unused/mono',workspace=self.root)
        library=next(r for r in result['rows'] if r['source_id']=='library')
        self.assertEqual(library['status'],'source_only_not_desktop_qualified')
        self.assertEqual(len(result['rows']),3)
        self.assertFalse(result['all_selected_normal_verified'])

    def test_nonfinite_limits_and_unknown_identity_are_not_executed(self):
        with patch.object(self.registry,'training_adapter') as runtime:
            for seconds in (True,0,float('nan'),float('inf'),301):
                with self.subTest(seconds=seconds),self.assertRaises(ContractError): self.execute(seconds=seconds)
            with self.assertRaisesRegex(ContractError,'unknown qualification'):
                _execute_qualification(self.registry,self.plan,self.root,self.actor,audits={},mono='/unused/mono',
                                      workspace=self.root,selected_bot_ids=['not-a-source-bot'])
        runtime.assert_not_called()

    def test_existing_report_prevents_all_cli_work_and_is_not_overwritten(self):
        from scripts import bot_qualification as cli
        report=self.root/'existing.json';report.write_text('preserve')
        argv=['bot_qualification.py','--installed-root',str(self.root),'--native-root',str(self.root),
              '--report',str(report),'--execute']
        with patch.object(sys,'argv',argv),patch.object(cli,'BotSourceRegistry') as registry:
            self.assertEqual(cli.main(),2)
        registry.assert_not_called();self.assertEqual(report.read_text(),'preserve')

    def test_public_execution_uses_the_fixed_worker_and_preserves_timeout_log(self):
        def timed_out(argv, *, log_path, seconds, **options):
            self.assertEqual(argv[2:4], ['-m', 'ygo_kito.bot_qualification'])
            self.assertEqual(seconds, 2)
            request = json.loads(Path(argv[4]).read_text(encoding='utf-8'))
            self.assertEqual(request['options']['selected_bot_ids'], [self.ice['bot_id']])
            log_path.write_text('owned native worker started', encoding='utf-8')
            return dict(process_started=True, child_reaped=True, process_tree_terminated=True, stop_reason='timeout')
        with patch('ygo_kito.owned_runtime.run_owned_process', side_effect=timed_out), \
             patch('ygo_kito.agent_monitor.RunReporter._sample', return_value=({}, {})), \
             patch('ygo_kito.agent_monitor.nvidia_device_sample') as gpu_sample, \
             patch('ygo_kito.bot_qualification.NativeNormalEngine', side_effect=AssertionError('native forbidden')):
            result = execute_qualification(self.registry, self.plan, self.root, self.actor, audits=self.audits,
                mono='/unused/mono', workspace=self.root, log_directory=self.root/'worker-logs',
                selected_bot_ids=[self.ice['bot_id']], seconds=2)
        row = next(value for value in result['rows'] if value['bot_id'] == self.ice['bot_id'])
        self.assertEqual(row['failed_stage'], 'owned_native_worker')
        self.assertEqual(row['reason'], 'timeout')
        self.assertIsNone(row['native_executed'])
        self.assertIsNone(row['csharp_executed'])
        self.assertEqual(Path(row['worker_log']).read_text(encoding='utf-8'), 'owned native worker started')
        gpu_sample.assert_not_called()
        self.assertIsNone(result['host_resources']['hardware']['gpu'])
        self.assertIsNone(result['host_resources']['metrics']['gpu_memory_bytes'])

    def test_cli_gpu_selection_reaches_host_sampler_after_owned_worker(self):
        from scripts import bot_qualification as cli
        calls = []
        def complete(argv, *, log_path, seconds, **options):
            calls.append('worker')
            self.assertEqual(seconds, 2)
            child = deepcopy(self.plan)
            for row in child['rows']:
                selected = row['bot_id'] == self.ice['bot_id']
                row.update(native_executed=selected, csharp_executed=selected, decisions=10 if selected else 0,
                           bot_decisions=5 if selected else 0, normal_duel_verified=selected,
                           status='normal_game_verified' if selected else 'not_selected')
            Path(argv[5]).write_text(json.dumps(child), encoding='utf-8')
            log_path.write_text('fixture completed', encoding='utf-8')
            return dict(process_started=True, child_reaped=True, stop_reason='completed')
        def sample(index):
            self.assertEqual(calls, ['worker'])
            calls.append('gpu')
            self.assertEqual(index, 2)
            return dict(device=dict(uuid='fixture-device', name='fixture GPU', driver='fixture driver'),
                metrics=dict(gpu_memory_bytes=123, gpu_memory_total_bytes=456, gpu_utilization_percent=20),
                source='fixture nvidia-smi')
        audits = self.root/'audits.json'
        audits.write_text(json.dumps(self.audits), encoding='utf-8')
        lock = self.root/'host-sampling-lock.json'
        lock.write_text(json.dumps(self.lock), encoding='utf-8')
        report = self.root/'qualified-with-device.json'
        argv = ['bot_qualification.py', '--installed-root', str(self.root), '--native-root', str(self.root),
                '--workspace', str(self.root), '--lock', str(lock), '--report', str(report), '--execute', '--audits', str(audits),
                '--mono', '/unused/mono', '--bot-id', self.ice['bot_id'], '--seconds', '2', '--gpu-device-index', '2']
        with patch.object(sys, 'argv', argv), patch.object(cli, 'BotSourceRegistry', return_value=self.registry), \
             patch('ygo_kito.owned_runtime.run_owned_process', side_effect=complete), \
             patch('ygo_kito.agent_monitor.RunReporter._sample', return_value=({}, {})), \
             patch('ygo_kito.agent_monitor.nvidia_device_sample', side_effect=sample), \
             patch('ygo_kito.bot_qualification.NativeNormalEngine', side_effect=AssertionError('native forbidden')), \
             patch('builtins.print'):
            self.assertEqual(cli.main(), 0)
        actual = json.loads(report.read_text(encoding='utf-8'))['host_resources']
        self.assertEqual(calls, ['worker', 'gpu'])
        self.assertEqual(actual['binding']['gpu_device_index'], 2)
        self.assertEqual(actual['binding']['gpu_sample_stage'], 'after_qualification_jobs')
        self.assertEqual(actual['hardware']['gpu']['uuid'], 'fixture-device')
        self.assertEqual(actual['metrics']['gpu_memory_bytes'], 123)
        self.assertEqual(actual['metric_sources']['gpu_memory_bytes'], 'fixture nvidia-smi')
        self.assertGreaterEqual(actual['stage_seconds']['end_to_end'], actual['stage_seconds']['qualification_jobs'])

    def test_missing_device_and_cancelled_or_unverified_jobs_keep_unmeasured_gpu(self):
        for reason, tree_terminated, probes in (('timeout', True, 1), ('user_pause', True, 0), ('timeout', False, 0)):
            with self.subTest(reason=reason, tree_terminated=tree_terminated):
                receipt = dict(process_started=True, child_reaped=True,
                               process_tree_terminated=tree_terminated, stop_reason=reason)
                with patch('ygo_kito.owned_runtime.run_owned_process', return_value=receipt), \
                     patch('ygo_kito.agent_monitor.RunReporter._sample', return_value=({}, {})), \
                     patch('ygo_kito.agent_monitor.nvidia_device_sample', return_value=None) as gpu_sample, \
                     patch('ygo_kito.bot_qualification.NativeNormalEngine', side_effect=AssertionError('native forbidden')):
                    result = execute_qualification(self.registry, self.plan, self.root, self.actor, audits=self.audits,
                        mono='/unused/mono', workspace=self.root, selected_bot_ids=[self.ice['bot_id']],
                        seconds=2, gpu_device_index=0)
                self.assertEqual(gpu_sample.call_count, probes)
                self.assertIsNone(result['host_resources']['hardware']['gpu'])
                self.assertIsNone(result['host_resources']['metrics']['gpu_memory_bytes'])
                self.assertIsNone(result['host_resources']['metric_sources']['gpu_memory_bytes'])

    def test_owned_worker_rate_uses_recorded_decisions_and_managed_game_time(self):
        from ygo_kito.bot_qualification import _owned_worker
        request, destination = self.root/'worker-request.json', self.root/'worker-result.json'
        request.write_text(json.dumps(dict(lock=self.lock, installed_root=str(self.root), plan=self.plan,
            native_root=str(self.root), actor_profile=self.actor,
            options=dict(selected_bot_ids=[self.ice['bot_id']], seconds=2))), encoding='utf-8')
        result = dict(resources=self.plan['resources'], rows=[dict(bot_id=self.ice['bot_id'], elapsed_seconds=2., decisions=10)])
        with patch('ygo_kito.bot_qualification.BotSourceRegistry', return_value=self.registry), \
             patch('ygo_kito.bot_qualification._execute_qualification', return_value=result), \
             patch('ygo_kito.agent_monitor.RunReporter._sample', return_value=({}, {})), \
             patch('ygo_kito.agent_monitor.nvidia_device_sample', side_effect=AssertionError('device sample belongs to host')):
            _owned_worker(request, destination)
        actual = json.loads(destination.read_text(encoding='utf-8'))['rows'][0]['resources']
        self.assertEqual(actual['metrics']['decisions_per_second'], 5.)
        self.assertEqual(actual['metric_sources']['decisions_per_second'], 'recorded decisions / managed-game wall seconds')

    def test_cli_device_sampling_requires_execution_and_a_valid_device_index(self):
        from scripts import bot_qualification as cli
        for index, flags in enumerate((['--gpu-device-index', '0'], ['--execute', '--gpu-device-index', '-1'])):
            report = self.root/f'invalid-device-{index}.json'
            argv = ['bot_qualification.py', '--installed-root', str(self.root), '--native-root', str(self.root),
                    '--report', str(report), *flags]
            with patch.object(sys, 'argv', argv), patch.object(cli, 'BotSourceRegistry') as registry, \
                 patch('ygo_kito.agent_monitor.nvidia_device_sample') as gpu_sample, \
                 patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as error:
                    cli.main()
            self.assertEqual(error.exception.code, 2)
            registry.assert_not_called()
            gpu_sample.assert_not_called()
            self.assertFalse(report.exists())

    def test_ordinary_owned_children_timeout_or_cancel_without_touching_another_child(self):
        from ygo_kito.owned_runtime import run_owned_process

        def command(source):
            return [sys.executable, '-B', '-c', source]
        unaffected = subprocess.Popen(command('import time; time.sleep(15)'), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            done = run_owned_process(command('print("done", flush=True)'), cwd=self.root,
                                     log_path=self.root/'done.log', seconds=4.)
            self.assertEqual((done['stop_reason'], done['exit_code']), ('completed', 0))
            sleeper = command('import time; print("ready", flush=True); time.sleep(15)')
            for reason in ('timeout', 'user_pause'):
                log = self.root/(reason+'.log')
                pause = (lambda: log.is_file() and log.stat().st_size > 0) if reason=='user_pause' else None
                result = run_owned_process(sleeper, cwd=self.root, log_path=log,
                                           seconds=1. if pause is None else 5., cancel_requested=pause)
                self.assertEqual(result['stop_reason'], reason)
                self.assertTrue(result['child_reaped'])
                self.assertIn(b'ready', log.read_bytes())
                self.assertIsNone(unaffected.poll())
        finally:
            if unaffected.poll() is None:
                unaffected.terminate()
            unaffected.wait(timeout=4)


if __name__=='__main__': unittest.main()
