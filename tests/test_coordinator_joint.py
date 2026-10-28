"""Joint controller/real adapter admission with only the native engine faked."""
from copy import deepcopy
from dataclasses import asdict,replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import hashlib

import tests.test_coordinator_control  # Explicit Windows locking boundary; no native locks used here.
import tests.test_course_game_adapter as fixtures
from ygo_kito.build_contracts import BuildTask,digest
from ygo_kito.build_training import BuildTrainer,BuildTrainingConfig
from ygo_kito.coordinator import Coordinator
from ygo_kito.coord_contracts import FeedbackPolicy
from ygo_kito.coordinator_model import CoordinatorTrainer
from ygo_kito.duel_model import parameter_digest
from ygo_kito.group_runner import tree_digest
from ygo_kito.match_runner import MatchState
from ygo_kito.course_game_adapter import CourseGameAdapter
from ygo_kito.validation import ContractError
from local_course_forecast import CourseForecast,canonical_deck
import torch


class Bundle:
    def __init__(self,helper,task):
        self.duel=helper.trainer
        self.builder=BuildTrainer(task,helper.assets,BuildTrainingConfig(batches=2))
        self.coordinator=CoordinatorTrainer()
        self.policy_rng=self.duel.policy_rng;self.sessions={}
    def models(self):return dict(self.builder.models,duel=self.duel.model,coordinator=self.coordinator.model)
    def versions(self):return {k:parameter_digest(v) for k,v in self.models().items()}
    def rng_state(self):return {'global':torch.get_rng_state(),'policy':self.policy_rng.get_state(),'batch':self.duel.batch_rng.get_state()}
    def restore_rng(self,value):
        torch.set_rng_state(value['global']);self.policy_rng.set_state(value['policy']);self.duel.batch_rng.set_state(value['batch'])
    def fingerprint(self):return tree_digest({'models':{k:v.state_dict() for k,v in self.models().items()},
        'optimizer':self.duel.optimizer.state_dict(),'cursor':(self.duel.updates,self.duel.episode_cursor),'rng':self.rng_state()})


class JointAdapterAdmissionTests(unittest.TestCase):
    def test_frozen_actor_survives_live_update_and_real_model_opponent_constructor_accepts_binding(self):
        helper=fixtures.CourseGameAdapterTests('test_course_long_game_cap_reaches_actual_sampler_and_legacy_limit_stays_strict')
        helper.setUp();self.addCleanup(helper.doCleanups)
        from tests.test_autonomous_construction import fixture
        _,catalog,_,_=fixture(41,initialize=False)
        helper.assets.rows=deepcopy(catalog.rows)  # Complete, varied synthetic public facts for the real build encoder.
        helper.assets.receipt=deepcopy(helper.assets.receipt)
        helper.assets.receipt['resources']['cards']=digest(helper.assets.rows)
        helper.assets.environment['versions']['cards']=helper.assets.receipt['resources']['cards']
        helper.assets.adapter_revision=5
        self.enterContext(helper.fake_model_execution())  # Only native resources/engine are faked; adapter admission stays real.
        issue_game_spec=MatchState.issue_game_spec
        def issue_for_fixture(state):
            spec=issue_game_spec(state)  # Preserve the real issuer token, seat mapping and integrity checks.
            helper.state=state  # The fake engine must observe this monitor match, rather than the helper's old match.
            return spec
        self.enterContext(patch.object(MatchState,'issue_game_spec',issue_for_fixture))
        raw=deepcopy(tests.test_coordinator_control.TASK.to_dict())
        raw.update(environment=helper.assets.environment,pool=sorted(helper.assets.rows),
                   requirements=[{'zone':'main','card_id':1,'minimum':1,'maximum':3}],
                   goal={'kind':'normal_summon','card_id':1,'starting_conditions':{'player':0,'turn':1,'requires_opening_hand':[1]}},
                   sizes={'main':40,'extra':0,'side':1})
        task=BuildTask.from_dict(raw)
        models=Bundle(helper,task);runtime=helper.model_runtime()
        actor=canonical_deck(helper.participants[0].deck);opponent=canonical_deck(helper.participants[1].deck)
        # The original adapter constructor is deliberately NOT patched.
        wrong=MatchState('missing-model-binding',helper.participants,helper.rules,{'fixture':'missing-identity'},'actor')
        with self.assertRaisesRegex(ContractError,'exact frozen model opponent'):
            CourseGameAdapter(assets=helper.assets,match_state=wrong,actor_participant_id='actor',trainer=models.duel,
                model_runtime=runtime,data_index=helper.index,experiment_id='fixture-course',purpose='validation',evaluation_pairs=((1000,2000),))
        course=SimpleNamespace(models=models,assets=helper.assets,deck=actor,_task=lambda:task,binding={'fixture':'joint-no-real-engine'},
            stage=lambda:'common-decks-bo3',rules=helper.rules,data_index=helper.index,active_seconds=0.,save=lambda:None,
            config={'course_id':'fixture-course','evaluation_pairs':{'validation':[[1000+i,2000+i] for i in range(30)]}},
            bots={'fixture-opponent':{'runtime':runtime,'deck':opponent,'stage':'common-decks-bo3','purpose':'train',
                  'first_order':'always_first','source':'engineering_fixture','coverage_label':'fixture',
                  'common_deck_evidence':{'kind':'host_reviewed_common_deck','source':'synthetic structural fixture, no historical coverage claim',
                    'reviewed_at':'2026-10-28','period_id':'2026-10','format':'OCG','banlist_effective':'2026-10-01',
                    'deck_sha256':digest(opponent.to_dict())}}})
        with tempfile.TemporaryDirectory(dir=tests.test_coordinator_control.ROOT.parent) as tmp:
            root=Path(tmp);host=Coordinator(root/'ledger.sqlite3',FeedbackPolicy(),role='coordinator',source='synthetic_contract_test',create=True)
            snapshots={}
            def capture(ident,receipt):
                if ident not in snapshots:snapshots[ident]=deepcopy(models)
                return snapshots[ident]
            controller=CourseForecast(course,root,host=host,snapshot_factory=capture)
            controller.before();first=controller.value['active_forecast'];frozen_actor=controller.status()['forecast']['scope']['actor_policy_sha256']
            self.assertEqual(controller.evaluate(1),1)
            with torch.no_grad():next(models.duel.model.parameters()).add_(.01)
            self.assertNotEqual(controller._actor_identity(),frozen_actor)
            controller.before();self.assertEqual(controller.value['active_forecast'],first)
            self.assertEqual(controller.evaluate(1),1)
            self.assertEqual(controller.status()['matches'],2)
            self.assertEqual(controller._actor_identity(controller._window_models(first)),frozen_actor)
            self.assertEqual(models.duel.updates,0)
            self.assertFalse(controller.value['trained_artifacts'])
            import json
            for audit in root.glob('monitor-*.json'):
                record=json.loads(audit.read_text())
                self.assertEqual(record['formal_training_credit'],0)
                self.assertFalse(record['forecast_supervision'])
            course.bots['fixture-opponent']['runtime']=replace(runtime,opponent_id='fixture-other-model')
            with self.assertRaisesRegex(ContractError,'opponent differs'):
                controller.evaluate(1)

    def test_complete_base_course_migrates_through_original_and_new_restore_checks(self):
        from tests.test_scenario_course import ScenarioCourseTests
        from ygo_kito.course_models import CourseModels
        import ygo_kito.course_models as course_module
        from ygo_kito.course_feedback import CourseFeedbackUpdater
        from ygo_kito.data_isolation import DataIndex
        from ygo_kito.scenario_course import ScenarioCourse
        from migrate_coordinator_course import export_closed_course,migrate_closed_course,sha
        helper=ScenarioCourseTests('test_real_adapter_updates_same_lora_and_pause_restore_resumes_next_bo1')
        helper.setUp();self.addCleanup(helper.doCleanups)
        # A real legacy 14-feature architecture fixture, not a relaxed loader.
        class LegacyTrainer(CoordinatorTrainer):
            def __init__(self,*args,**kwargs):
                super().__init__(*args,**kwargs)
                del self.model.scope_projection;del self.model.budget_head
                self.optimizer=torch.optim.AdamW(self.model.parameters(),lr=self.config.learning_rate,weight_decay=0.,foreach=False,fused=False)
                self.scheduler=torch.optim.lr_scheduler.StepLR(self.optimizer,1,.99)
        package=Path(course_module.__file__).parent
        target={'src/ygo_kito/'+p.name:sha(p) for p in package.glob('*.py')}
        old_source=dict(target);old_source['src/ygo_kito/coordinator_model.py']='4'*64
        binding=deepcopy(helper.models.binding);binding.update(learning_stage='base',source_files=old_source)
        with tempfile.TemporaryDirectory(dir=tests.test_coordinator_control.ROOT.parent) as tmp:
            root=Path(tmp);parent=root/'parent';parent.mkdir()
            with patch.object(course_module,'CoordinatorTrainer',LegacyTrainer):
                models=CourseModels.initialize(helper.models.builder.task,helper.host.assets,helper.models.duel.config,
                    helper.models.adapter_configs,root,None,helper.host.assets.rows,binding)
                old=ScenarioCourse(models,assets=helper.host.assets,data_index=DataIndex(parent/'index'),config=helper.config,
                    state_root=parent/'course',bots=helper.bots)
                old.active_seconds=17.;old.desired='paused'
                # Full statvfs contract: Linux shutil.disk_usage also reads
                # block counts while the production storage guard stays active.
                with patch('os.statvfs',return_value=SimpleNamespace(f_frsize=4096,f_blocks=1_000_000,f_bfree=900_000,f_bavail=900_000),create=True):
                    old.save();receipt=export_closed_course(old,root/'export.weights')
            before=(parent/'course/latest.json').read_bytes()
            with patch('os.statvfs',return_value=SimpleNamespace(f_frsize=4096,f_blocks=1_000_000,f_bfree=900_000,f_bavail=900_000),create=True):
                migrated,report=migrate_closed_course(receipt,root/'next',assets=helper.host.assets,bots=helper.bots,
                    source_files=target,allowed_changed_files={'src/ygo_kito/coordinator_model.py'})
                migrated.restore_latest()
            self.assertEqual(migrated.active_seconds,17.)
            self.assertEqual(migrated.records,old.records)
            self.assertEqual(migrated.models.duel.updates,0)
            self.assertEqual(migrated.models.coordinator.updates,0)
            self.assertEqual(migrated.desired,'paused')
            self.assertFalse(report['training_executed'])
            self.assertEqual((parent/'course/latest.json').read_bytes(),before)
            self.assertEqual(migrated.models.versions()['duel'],old.models.versions()['duel'])
            with self.assertRaises(ContractError):
                migrate_closed_course(dict(receipt,sha256='0'*64),root/'bad',assets=helper.host.assets,bots=helper.bots,
                    source_files=target,allowed_changed_files={'src/ygo_kito/coordinator_model.py'})


if __name__=='__main__':unittest.main()
