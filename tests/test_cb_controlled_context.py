"""CB hypotheses are explicit initial states, never lucky random deals."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.fixtures import request as request_payload
from tests.test_cb_chain_regressions import construction
from ygo_kito.basic_cb_inference import infer_basic_cb, proposals
from ygo_kito.build_semantics import route_task
from ygo_kito.contracts import DecisionRequest
from ygo_kito.extra_routes import engine_for_goal
from ygo_kito.route_search import _CONDITIONAL_CB, discover_goal


class ControlledCbContextTests(unittest.TestCase):
    def test_real_infer_factory_path_uses_exact_hand_once_and_keeps_unknown(self):
        task,deck,assets=construction()
        candidate=proposals(task,deck,assets)[1]
        opening=candidate.goal['route_goal']['starting_conditions']['requires_opening_hand']
        assets.root=Path('.')
        raw=request_payload();raw['context']['seed']=None;raw['prompt']=dict(message=11)
        raw['observation'].update(cards=[dict(ref=str(i),owner=0,controller=0,zone='hand',
            card_id=code,visibility='observer') for i,code in enumerate(opening)],
            public_history=[],hand_counts=[len(opening),0])
        raw['actions']=[dict(action_id='pass',kind='pass',card_refs=[],value=7)]
        request=DecisionRequest.from_dict(raw)
        calls=[]
        class Engine:
            events=[]
            turn=1
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def next_decision(self):return request if self.turn==1 else None
            def _observation(self,_):return request.observation
            def submit(self,_):self.turn=2
        def factory(root,**options):
            calls.append(options)
            self.assertTrue(_CONDITIONAL_CB.get())
            self.assertEqual(options['scenario'],'conditional-cb')
            self.assertEqual(options['cb_opening_hand'],tuple(opening))
            return Engine()
        assets.engine_factory=factory
        def verify(candidate,deck,assets,**limits):
            return discover_goal(route_task(candidate),deck,assets,**limits)
        with patch('ygo_kito.basic_cb_inference.proposals',return_value=[candidate]):
            result=infer_basic_cb(task,deck,assets,verifier=verify,seconds=1.,limit=1)
        self.assertEqual(len(calls),1)
        self.assertFalse(_CONDITIONAL_CB.get())
        self.assertEqual(result['initial_state_mode'],'hypothetical_exact_hand_v1')
        self.assertFalse(result['opening_probability_evaluated'])
        self.assertEqual(result['status'],'bounded_inference_unknown')
        self.assertTrue(result['inference_completed'])
        self.assertEqual(result['routes'],[])
        proof=result['attempts'][0]['proof']
        self.assertEqual(proof['exploration']['nodes_expanded'],1)
        self.assertEqual(proof['opening_assumption']['hand'],opening)
        self.assertEqual(proof['opening_assumption']['unspecified_hand_resources'],0)
        self.assertTrue(proof['core_attempts'][0]['declared_opening_condition_met'])

    def test_regular_factory_remains_unconditioned_and_scope_resets_on_error(self):
        from ygo_kito.route_search import conditional_cb_search
        _,deck,assets=construction();assets.root=Path('.')
        calls=[];assets.engine_factory=lambda root,**options:calls.append(options)
        engine_for_goal(assets,deck,7)
        self.assertEqual(calls[-1]['scenario'],'effect-duel')
        self.assertNotIn('cb_opening_hand',calls[-1])
        with self.assertRaisesRegex(RuntimeError,'fixture'):
            with conditional_cb_search():
                self.assertTrue(_CONDITIONAL_CB.get())
                raise RuntimeError('fixture')
        self.assertFalse(_CONDITIONAL_CB.get())


if __name__=='__main__':unittest.main()
