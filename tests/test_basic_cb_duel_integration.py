"""Real inference-envelope and planner readers with explicit synthetic proofs.

The native proof fixture is not new rule-engine evidence or a strength result.
"""
from copy import deepcopy
from pathlib import Path
import unittest

from tests.test_duel_runtime_interfaces import construction_fixture
from ygo_kito.basic_cb_inference import infer_basic_cb
from ygo_kito.build_contracts import BuildTask,digest
from ygo_kito.build_pipeline import BuildAssets
from ygo_kito.build_semantics import route_task
from ygo_kito.construction_fill import _candidate_basic_cb
from ygo_kito.duel_planning import plans_from_construction
from ygo_kito.validation import ContractError


class BasicCbDuelIntegrationTests(unittest.TestCase):
    def inference_fixture(self, *, general_task=False, unknown=False):
        task,deck,fixture=construction_fixture()
        if general_task:
            raw=task.to_dict();raw['requirements']=[];task=BuildTask.from_dict(raw)
        assets=BuildAssets.__new__(BuildAssets)
        assets.root=Path(__file__).resolve().parents[1]
        assets.environment=deepcopy(task.environment);assets.limits={}
        assets.receipt={'resources':{'cards':'a'*64,'scripts':'b'*64},'engineering_fixture':True}
        assets.rows={c:{'id':c,'alias':0,'ot':1,'type':0x2001 if c in (42,43) else 0x1011 if c==1 else 17,
            'level':8 if c in (42,43) else 4,'setcode':0,'race':1,'attribute':1,
            'atk':1000,'def':1000,'name':'synthetic-'+str(c),'desc':''} for c in task.pool}
        calls=[]
        def synthetic_verifier(derived,current,current_assets,**kwargs):
            target=derived.goal['route_goal']['card_id'];calls.append(derived.sha256)
            if unknown:return {'status':'not_found_within_budget','exploration':{'nodes_expanded':1},
                               'unmet':['synthetic bounded search, not impossibility']}
            proof=deepcopy(next(row['proof'] for row in fixture['basic_cb']['routes']
                                if row['task']['goal']['route_goal']['card_id']==target))
            native_task=route_task(derived)
            proof['task_sha256']=derived.sha256;proof['deck_sha256']=digest(current.to_dict())
            proof['native_route'].update(task_sha256=native_task.sha256,
                deck_sha256=digest(current.to_dict()),starting_condition=native_task.goal['starting_conditions'])
            return proof
        inferred=infer_basic_cb(task,deck,assets,verifier=synthetic_verifier)
        result={'best':{'deck':deck.to_dict()},'goal_sha256':digest(task.goal),'basic_cb':inferred}
        return task,deck,assets,result,calls

    def test_real_material_inference_envelope_reaches_planner_with_derived_task_ownership(self):
        task,deck,_,result,calls=self.inference_fixture()
        inferred=result['basic_cb']
        self.assertTrue(calls);self.assertTrue(inferred['routes'])
        plans=plans_from_construction(task,result,deck=deck)
        self.assertTrue(plans)
        self.assertEqual(plans[0].goal_card,inferred['routes'][0]['task']['goal']['route_goal']['card_id'])
        self.assertNotIn('card_id',task.goal);self.assertNotIn('route_goal',task.goal)
        self.assertNotIn('private-seed-secret',repr(plans));self.assertNotIn('private-native-action',repr(plans))

    def test_general_construction_accepts_only_route_card_requirements_in_its_derived_inference(self):
        task,deck,_,result,calls=self.inference_fixture(general_task=True)
        before=task.to_dict();self.assertEqual(task.requirements,())
        self.assertTrue(calls);self.assertEqual(result['basic_cb']['status'],'routes_inferred')
        self.assertTrue(result['basic_cb']['inference_completed'])
        self.assertTrue(result['basic_cb']['routes'][0]['task']['requirements'])
        self.assertTrue(plans_from_construction(task,result,deck=deck))
        self.assertEqual(task.to_dict(),before);self.assertNotIn('route_goal',task.goal)
        bad=deepcopy(result);bad['task_goal_sha256']='0'*64
        with self.assertRaisesRegex(ContractError,'original task/goal/deck'):
            plans_from_construction(task,bad,deck=deck)

    def test_missing_provider_is_not_run_while_bounded_search_unknown_is_completed(self):
        task,deck,assets,result,calls=self.inference_fixture(unknown=True)
        missing=_candidate_basic_cb(task,deck,assets,None)
        self.assertEqual(missing['status'],'not_run');self.assertFalse(missing['inference_completed'])
        inferred=result['basic_cb']
        self.assertTrue(calls);self.assertTrue(inferred['attempts'])
        self.assertEqual(inferred['status'],'bounded_inference_unknown');self.assertTrue(inferred['inference_completed'])
        self.assertEqual(inferred['routes'],[]);self.assertTrue(inferred['unknown_is_not_negative'])
        self.assertEqual(plans_from_construction(task,result,deck=deck),())

    def test_rebound_proof_cannot_drop_original_or_add_unrelated_or_change_maximum_requirements(self):
        task,deck,_,result,_=self.inference_fixture()
        for mutation in ('drop_original','unrelated_card','change_maximum'):
            bad=deepcopy(result);row=bad['basic_cb']['routes'][0]
            requirements=row['task']['requirements']
            if mutation=='drop_original':requirements.pop()
            elif mutation=='unrelated_card':requirements.append(dict(zone='main',card_id=3,minimum=1,maximum=3))
            else:requirements[0]['maximum']=2
            # Rebind the synthetic proof so an unrelated stale hash cannot
            # hide a weakened derived-requirements admission check.
            derived=BuildTask.from_dict(row['task']);native=route_task(derived)
            row['proof']['task_sha256']=derived.sha256
            row['proof']['native_route']['task_sha256']=native.sha256
            with self.subTest(mutation=mutation),self.assertRaisesRegex(ContractError,'requirements'):
                plans_from_construction(task,bad,deck=deck)
