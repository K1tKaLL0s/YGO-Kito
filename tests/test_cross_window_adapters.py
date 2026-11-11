"""Real post-construction provider/forecast paths with isolated synthetic data.

Native goal search is replaced at its explicit verifier boundary. No formal
learner update, original checkpoint, or Linux supervisor process is exercised.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,tempfile,unittest

from tests import test_coordinator_control  # explicit fail-loud Windows import guard
from tests.test_effect_mechanisms import assets_fixture
from tests.test_effect_construction_integration import legal_base
from ygo_kito.autonomous_construction import AutonomousConstructionKernel
from ygo_kito.build_contracts import BuildTask,DeckParts,digest
from ygo_kito.build_semantics import proof
from ygo_kito.data_isolation import DataIndex
from ygo_kito.validation import ContractError
from local_foundation_course import CycleBudget,execute_cycle
from local_course_collaboration import cycle
from local_course_forecast import CourseForecast,canonical_deck
from local_design_supervision import make_unit_boundary


class CrossWindowAdapterTests(unittest.TestCase):

    def test_real_unit_callback_stops_before_any_learning_when_observer_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stop=root/'stop';saved=[]
            course=SimpleNamespace(root=root/'course',deck=object(),active_seconds=0.,desired='ready',
                config={'wall_seconds':100.},save=lambda:saved.append(True),status=lambda:{},
                models=SimpleNamespace(builder=SimpleNamespace(updates={'build_goal':0,'build_optimizer':0}),
                    duel=SimpleNamespace(updates=0),coordinator=SimpleNamespace(updates=0)),
                run=lambda *a:(_ for _ in ()).throw(AssertionError('learning must not start')))
            forecast=SimpleNamespace(decide=lambda n:{'action':'train_duel','budget_units':1},
                                     status=lambda:{'mandatory_rebuild':False})
            result=execute_cycle(course,forecast,None,root,root,stop,lambda *a,**k:None,1,
                                 unit_boundary=make_unit_boundary(root,stop))
            self.assertEqual(result['executed_units'],0);self.assertTrue(result['paused'])
            self.assertEqual(course.desired,'paused');self.assertTrue(stop.exists());self.assertTrue(saved)
