"""In-memory data contracts for CB resume; no temporary-file I/O claim."""
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/'src') not in sys.path:sys.path.insert(0,str(ROOT/'src'))
course=types.ModuleType('cb_resume_course');course.__file__=str(ROOT/'scripts/local_foundation_course.py')
exec(compile(Path(course.__file__).read_text(encoding='utf-8'),course.__file__,'exec'),course.__dict__)


def preserved_result():
    decks=[{'main':[index+1],'extra':[],'side':[]} for index in range(4)]
    roles=('build_goal','build_optimizer','build_goal','build_optimizer')
    phases=[{'phase_number':index+1,'role':role,'input_deck':None if not index else decks[index-1],
             'proposal_deck':decks[index],'role_parameter_updates':False,
             'stage_1':{'logic_sha256':'final-logic'}} for index,role in enumerate(roles)]
    best={'deck':decks[-1],'logic_sha256':'final-logic','validation':{
        'status':'list_constraints_verified_logic_unproven','best_deck':decks[-1]},
        'basic_cb':{'status':'not_run'},'cb_verified':False}
    return {'selected_task_sha256':'same-task','phases':phases,'alternation_completed':True,
            'best':deepcopy(best),'construction_candidate':deepcopy(best),'verified_best':deepcopy(best),
            'retained_candidates':[{'deck':decks[0],'basic_cb':{'status':'old-evidence'}}],
            'basic_cb':{'status':'not_run'},'competitive_improvement_verified':False}


class MemoryInput:
    """Read the same JSON payload without retrying unavailable temp writes."""
    def __init__(self,value):self.value=value
    def __truediv__(self,name):
        if name!='preserved-four-stage-construction.json':raise AssertionError(name)
        return self
    def exists(self):return True
    def read_text(self,**kwargs):return json.dumps(self.value)


class CbResumeFourHandoffsTests(unittest.TestCase):
    def test_same_task_reuses_phases_and_runs_real_cb_provider(self):
        from ygo_kito import basic_cb_inference
        original=preserved_result()
        task=types.SimpleNamespace(sha256='same-task',to_dict=lambda:{'goal':{'kind':'deck_constraints'}})
        route=types.SimpleNamespace(sha256='inferred-route',goal={'route_goal':{'kind':'fusion_summon'}},
                                    to_dict=lambda:{'goal':{'route_goal':{'kind':'fusion_summon'}}})
        model=Mock(training=False);model.return_value.item.return_value=0.5
        builder=types.SimpleNamespace(models={'build_goal':model},encoder=types.SimpleNamespace(batch=Mock()))
        models=types.SimpleNamespace(builder=builder,kernel=types.SimpleNamespace(_selection=Mock(return_value=task)))
        assets=types.SimpleNamespace(validate=Mock(),rows={4:{'name':'fixture learner'}});budget=types.SimpleNamespace(check=Mock(return_value=60.))
        verifier=Mock(return_value={'status':'route_verified','task_sha256':'inferred-route','deck_sha256':'learner',
            'exploration':{'nodes_expanded':1},'private_selection_key_audit_only':{'seed':'private'}})
        recorder=Mock();selection={'candidate_id':'same-task'}
        target=MemoryInput(original)
        with patch.object(basic_cb_inference,'proposals',return_value=[route]),\
                 patch.object(basic_cb_inference,'digest',return_value='learner'),\
                 patch.object(basic_cb_inference,'infer_basic_cb',wraps=basic_cb_inference.infer_basic_cb) as provider,\
                 patch('ygo_kito.build_semantics.accepted_status',return_value='route_verified'),\
                 patch('ygo_kito.route_search.conditional_cb_search',return_value=nullcontext()):
            result=course.resume_preserved_four_handoffs(models,selection,assets,target,
                verifier=verifier,budget=budget,recorder=recorder)
        models.kernel._selection.assert_called_once_with(selection)
        self.assertIs(provider.call_args.kwargs['builder'],builder)
        self.assertIs(provider.call_args.kwargs['verifier'],verifier)
        self.assertIs(provider.call_args.kwargs['budget'],budget)
        verifier.assert_called_once();recorder.assert_called_once()
        self.assertIn('private_selection_key_audit_only',recorder.call_args.args[2]['attempts'][0]['proof'])
        self.assertNotIn('private_selection_key_audit_only',result['basic_cb']['attempts'][0]['proof'])
        self.assertEqual(result['phases'],original['phases'])
        self.assertEqual(result['retained_candidates'],original['retained_candidates'])
        self.assertTrue(result['preserved_four_handoffs'])
        self.assertTrue(result['basic_cb_inference_performed']);self.assertTrue(result['cb_verified'])
        self.assertFalse(result['cb_resume_provenance']['role_parameter_updates'])
        self.assertFalse(result['cb_resume_provenance']['new_four_handoffs_executed'])
        self.assertFalse(result['competitive_improvement_verified'])
        self.assertEqual(result['best']['basic_cb'],result['basic_cb'])

    def test_task_or_learner_mismatch_stops_before_cb(self):
        task=types.SimpleNamespace(sha256='same-task')
        models=types.SimpleNamespace(kernel=types.SimpleNamespace(_selection=Mock(return_value=task)),builder=object())
        for mismatch in ('task','learner'):
            with self.subTest(mismatch=mismatch):
                result=preserved_result()
                if mismatch=='task':result['selected_task_sha256']='different-task'
                else:result['best']['deck']={'main':[999],'extra':[],'side':[]}
                target=MemoryInput(result)
                with patch('ygo_kito.basic_cb_inference.infer_basic_cb') as provider:
                    with self.assertRaisesRegex(RuntimeError,'different selected task|learner differs'):
                        course.resume_preserved_four_handoffs(models,{},object(),target,
                            verifier=Mock(),budget=Mock(),recorder=Mock())
                    provider.assert_not_called()


if __name__=='__main__':unittest.main()
