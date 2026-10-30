"""Prospective 20/50 host contracts; synthetic rows are not played matches."""
import json
from pathlib import Path
import tempfile
import unittest

from ygo_kito.build_contracts import digest
from ygo_kito.coord_contracts import FeedbackPolicy,TWENTY_FIFTY_POLICY_EPOCH
from ygo_kito.coordinator import Coordinator
from ygo_kito.validation import ContractError,canonical_json


ROOT=Path(__file__).resolve().parents[1]
TASK=json.loads((ROOT/'configs/build-engineering-v1.json').read_text())
DECK=json.loads((ROOT/'docs/reports/2026-10-23-m3b-best-deck.json').read_text())


class TwentyFiftyForecastContracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.policy=FeedbackPolicy.twenty_fifty()
        self.host=Coordinator(Path(self.temp.name)/'new-epoch.sqlite3',self.policy,
            role='coordinator',source='synthetic_contract_test',create=True)
        self.call(self.host,'handoff.submit',{'candidate_id':'candidate','parent_candidate_id':None,
            'task':TASK,'deck':DECK,'build_models':{'build_goal':'1'*64,'build_optimizer':'2'*64}})
        scope={'actor_policy_sha256':'3'*64,'duel_lora':None,
            'opponents':[{'opponent_id':'fixture','deck_sha256':'4'*64,'driver_sha256':'5'*64,'weight':1.}],
            'initiative_weights':[1.,0.],'unit':'BO1','prediction_target':'win_rate','versions':TASK['environment']['versions']}
        self.call(self.host,'forecast.register',{'forecast_id':'forecast','candidate_id':'candidate','probability':.9,
            'origin_role':'coordinator','model_sha256':'6'*64,'calibration':'pending','scope':scope})
        self.worker=Coordinator(self.host.path,self.policy,role='duel_worker',source=self.host.source)

    def call(self,host,method,params):
        response=host.dispatch({'schema_version':1,'id':'test','method':method,'params':params})
        self.assertTrue(response['ok'],response)
        return response['result']

    def rows(self,outcomes,*,diagnosis='none',terminal=True):
        """Lease synthetic envelopes; never sample a duel or label real data."""
        status=self.host.forecast_status('forecast');rows=[]
        with self.host._db() as db,db:
            start=db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
            for index,outcome in enumerate(outcomes,start):
                ident='synthetic-'+str(index)
                info={'candidate_id':'candidate','forecast_id':'forecast','scope_sha256':status['scope_sha256'],
                    'scope':status['forecast']['scope']}
                db.execute("INSERT INTO jobs VALUES(?,?,?,'leased','fixture')",(ident,'forecast',canonical_json(info)))
                rows.append({'result_id':ident,'job_id':ident,'worker_id':'fixture','forecast_id':'forecast',
                    'candidate_id':'candidate','scope_sha256':status['scope_sha256'],'source':self.host.source,
                    'unit':'BO1','outcome':outcome,'audit_sha256':digest(ident),'diagnosis':diagnosis,
                    'core_terminal_received':terminal})
        return rows

    def append(self,rows):
        return self.call(self.worker,'results.append',{'results':rows})['forecast']

    def test_engineering_policy_is_explicit_and_legacy_policy_stays_immutable(self):
        self.assertEqual(self.policy.policy_epoch,TWENTY_FIFTY_POLICY_EPOCH)
        self.assertEqual((self.policy.review_horizon,self.policy.rebuild_horizon),(20,50))
        self.assertEqual(self.policy.checkpoints,tuple(range(5,51,5)))
        self.assertTrue(self.policy.definitions_ready)
        self.assertIn('engineering-hoeffding',self.policy.significance_definition_id)
        legacy=FeedbackPolicy();saved=legacy.to_dict()
        self.assertNotIn('policy_epoch',saved)
        self.assertNotIn('review_horizon',saved)
        self.assertEqual(FeedbackPolicy.from_dict(saved).to_dict(),saved)
        legacy_path=Path(self.temp.name)/'legacy.sqlite3'
        Coordinator(legacy_path,legacy,role='coordinator',source=self.host.source,create=True)
        with self.assertRaisesRegex(ContractError,'immutable'):
            Coordinator(legacy_path,self.policy,role='monitor',source=self.host.source)

    def test_conditions_trigger_within_horizons_and_a_single_loss_is_not_a_trigger(self):
        status=self.append(self.rows(['loss']))
        self.assertFalse(status['alerts']);self.assertEqual(status['matches'],1)
        status=self.append(self.rows(['loss']*49))
        alerts={row['kind']:row['n'] for row in status['alerts']}
        self.assertLessEqual(alerts['reevaluate'],20)
        self.assertTrue(20<alerts['mandatory_rebuild']<=50)
        self.assertEqual(status['matches'],50)
        self.assertTrue(status['mandatory_rebuild'])

    def test_horizon_counts_alone_do_not_rebuild(self):
        status=self.append(self.rows(['win']*50))
        self.assertEqual(status['matches'],50)
        self.assertFalse(status['pending_review']);self.assertFalse(status['mandatory_rebuild'])
        self.assertFalse(status['alerts'])
        self.assertEqual([c['matches'] for c in status['checks']],list(self.policy.checkpoints))

    def test_nonterminal_and_diagnosed_results_preserve_audit_without_match_scores(self):
        truncated=self.rows(['compute_truncated'],terminal=False)
        truncated[0].update(termination_kind='compute_budget',sample_completed=False,
            model_update_started=False,model_update_completed=False)
        self.append(truncated);self.append(truncated)
        self.append(self.rows(['crash'],diagnosis='system_error',terminal=False))
        status=self.append(self.rows(['loss'],diagnosis='unknown',terminal=True))
        self.assertEqual(status['matches'],0);self.assertEqual(status['wins'],0)
        self.assertIsNone(status['score_mean']);self.assertFalse(status['checks']);self.assertFalse(status['alerts'])
        self.assertEqual(status['outcome_counts'],{'compute_truncated':1,'crash':1,'loss':1})

    def test_terminal_and_truncation_contracts_fail_closed_before_accounting(self):
        cases=[self.rows(['loss'],terminal=False)[0],self.rows(['compute_truncated'],terminal=False)[0]]
        for row in cases:
            response=self.worker.dispatch({'schema_version':1,'id':'invalid','method':'results.append','params':{'results':[row]}})
            self.assertFalse(response['ok'])
        self.assertEqual(self.host.forecast_status('forecast')['matches'],0)

    def test_changed_candidate_or_frozen_scope_cannot_enter_the_window(self):
        row=self.rows(['win'])[0]
        for change in ({'candidate_id':'different'},{'scope_sha256':'f'*64},{'unit':'BO3'}):
            response=self.worker.dispatch({'schema_version':1,'id':'wrong-scope','method':'results.append',
                'params':{'results':[dict(row,**change)]}})
            self.assertFalse(response['ok'])
        self.assertEqual(self.host.forecast_status('forecast')['matches'],0)


if __name__=='__main__':unittest.main()
