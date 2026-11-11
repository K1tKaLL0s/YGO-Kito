"""Joint controller/real model binding with synthetic engine and formal-admission boundaries."""
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
        self.binding={'fixture':'synthetic-frozen-model-bundle'}
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
        self.enterContext(helper.fake_model_execution())  # Model identity/constructor checks stay real; formal CB admission is isolated.
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
        course=SimpleNamespace(models=models,assets=helper.assets,deck=actor,construction=None,_task=lambda:task,binding={'fixture':'joint-no-real-engine'},
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
            self.enterContext(patch.object(controller,'require_formal_duel',
                return_value={'status':'admitted','fixture':'frozen-model-binding-only'}))
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



if __name__=='__main__':unittest.main()
