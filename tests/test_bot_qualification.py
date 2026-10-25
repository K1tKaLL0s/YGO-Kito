"""Exact fixture inputs and mocked execution control; no C#/native execution."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import unittest
from unittest.mock import patch, Mock

from tests import test_bot_deployment as source_fixtures
from ygo_kito.bot_deployment import BotSourceRegistry
from ygo_kito.bot_qualification import prepare_qualification, execute_qualification, normal_engineering_actor
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
        return execute_qualification(self.registry, self.plan, self.root, self.actor, audits=self.audits,
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
        result=execute_qualification(self.registry,self.plan,self.root,self.actor,audits={},mono='/unused/mono',workspace=self.root)
        library=next(r for r in result['rows'] if r['source_id']=='library')
        self.assertEqual(library['status'],'source_only_not_desktop_qualified')
        self.assertEqual(len(result['rows']),3)
        self.assertFalse(result['all_selected_normal_verified'])

    def test_nonfinite_limits_and_unknown_identity_are_not_executed(self):
        with patch.object(self.registry,'training_adapter') as runtime:
            for seconds in (True,0,float('nan'),float('inf'),301):
                with self.subTest(seconds=seconds),self.assertRaises(ContractError): self.execute(seconds=seconds)
            with self.assertRaisesRegex(ContractError,'unknown qualification'):
                execute_qualification(self.registry,self.plan,self.root,self.actor,audits={},mono='/unused/mono',
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


if __name__=='__main__': unittest.main()
