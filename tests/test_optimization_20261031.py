"""Focused regression tests for paused-course optimization, no native games."""
from tests.fixtures import synthetic_cb_authorization
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from ygo_kito.build_contracts import DeckParts,digest
from ygo_kito.coord_contracts import FeedbackPolicy
from ygo_kito.cb_effect_points import route_effect_points
from ygo_kito.validation import ContractError


class OptimizationContracts(unittest.TestCase):
    def test_unit_base_and_theme_are_separate(self):
        generic=route_effect_points('another_theme');pearl=route_effect_points('pearl_grave_fusion', {'grave_fusion':1.5})
        self.assertTrue(all(value==1. for value in generic.values()))
        self.assertEqual(pearl['grave_fusion'],1.5)
        self.assertEqual(generic['grave_fusion'],1.)
        with self.assertRaises(ValueError):route_effect_points('theme',{'missing':2.})

    def test_responsive_twenty_fifty_has_conditions_and_preserves_old_policy(self):
        policy=FeedbackPolicy.responsive_twenty_fifty()
        self.assertIsNone(policy.assess(19,0,.5,1))
        self.assertEqual(policy.alert_kinds(policy.assess(20,2,.5,1)),('reevaluate',))
        self.assertEqual(policy.alert_kinds(policy.assess(50,10,.5,1)),('reevaluate','mandatory_rebuild'))
        self.assertFalse(policy.assess(20,9,.5,1)['low'])
        self.assertFalse(policy.assess(50,30,.5,1)['low'])
        self.assertFalse(FeedbackPolicy.twenty_fifty().assess(20,2,.5,1)['low'])
        self.assertEqual(FeedbackPolicy.from_dict(policy.to_dict()),policy)





    def test_same_family_targets_each_get_a_search_slice(self):
        from unittest.mock import patch
        from ygo_kito.basic_cb_inference import infer_basic_cb
        task=SimpleNamespace(sha256='construction')
        deck=DeckParts((1,));assets=SimpleNamespace(rows={},validate=lambda *args:None)
        candidates=[]
        for i,target in enumerate((10,10,10,20,20,20)):
            goal={'route_goal':{'kind':'fusion_summon','card_id':target}}
            candidates.append(SimpleNamespace(sha256=str(i),goal=goal,to_dict=lambda:{}))
        calls=[]
        def verify(candidate,*args,**kw):
            calls.append(candidate.goal['route_goal']['card_id'])
            return {'status':'not_run','native_route':{'status':'not_run','search_started':False}}
        with patch('ygo_kito.basic_cb_inference.proposals',return_value=candidates):
            infer_basic_cb(task,deck,assets,**synthetic_cb_authorization(task,deck),verifier=verify)
        self.assertEqual(calls,[10,20,10,20,10,20])

    def test_explicit_grave_self_material_does_not_require_an_optional_hand_material(self):
        from unittest.mock import patch
        from tests.test_duel_runtime_interfaces import construction_fixture
        from ygo_kito.basic_cb_inference import proposals
        task,deck,_=construction_fixture()
        rows={c:{'id':c,'type':17 if c<42 else 65,'level':3} for c in task.pool}
        starter=SimpleNamespace(observed_operations=[{'kind':'send_grave','from_zones':('deck',),'random':False}],operations=[])
        fusion=SimpleNamespace(index=2,text='包含墓地的这张卡的融合素材怪兽从手卡·场上·墓地回到卡组下面。',
            trigger={'event':'sent_to_grave'},operations=[{'kind':'fusion_summon'}],
            observed_operations=[{'kind':'return_fusion_materials','from_zones':('hand','field','grave'),'to_zone':'deck_bottom'}])
        profiles={c:SimpleNamespace(effects=([starter] if c==1 else [fusion] if c==2 else []),
            cards_sha256='a'*64,text_sha256='b'*64) for c in deck.main}
        assets = SimpleNamespace(rows=rows, receipt={'resources': {'cards': 'a' * 64}})
        catalog=SimpleNamespace(assets=assets, card=lambda c:profiles[c], effect_records=lambda c: ())
        with patch('ygo_kito.basic_cb_inference.MechanismCatalog',return_value=catalog):
            candidates=proposals(task,deck,assets)
        self.assertEqual({c.goal['route_goal']['card_id'] for c in candidates},{42,43})
        self.assertTrue(all(c.goal['route_goal']['fusion_witness']['required_source_zones']==[16] for c in candidates))

    def test_closed_state_continuation_does_not_require_an_implementation_archive(self):
        from scripts.local_course_source_continuation import validate_continuation
        with TemporaryDirectory() as temp:
            base=Path(temp);target=base/'new';(target/'course').mkdir(parents=True)
            (target/'course/latest.json').write_text('{}')
            self.assertEqual(validate_continuation({'state_root':str(target)},base),target.resolve())
            (target/'course/in-flight.json').write_text('{}')
            with self.assertRaises(ValueError):validate_continuation({'state_root':str(target)},base)

    def test_legal_cb_gets_a_score_and_unknown_has_no_score(self):
        from tests.test_basic_cb_duel_integration import BasicCbDuelIntegrationTests
        fixture=BasicCbDuelIntegrationTests()
        result=fixture.inference_fixture()[3]['basic_cb']
        route=result['routes'][0]
        self.assertTrue(route['score_after_legality'])
        self.assertEqual(route['score'],sum(r['points'] for r in route['score_breakdown']))
        unknown=fixture.inference_fixture(unknown=True)[3]['basic_cb']
        self.assertFalse(unknown['routes']);self.assertNotIn('score',unknown)



if __name__=='__main__':unittest.main()
