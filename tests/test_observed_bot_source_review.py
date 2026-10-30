"""Pure-data checks for the exact observed-bot source-review bridge."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/'src') not in sys.path:sys.path.insert(0,str(ROOT/'src'))
from ygo_kito import observed_bot_evidence as observed
from ygo_kito.validation import ContractError


def fixture():
    old={'native.py':'1'*64,'native_protocol.py':'2'*64,'scenario_course.py':'3'*64}
    current=dict(old,**{'scenario_course.py':'4'*64})
    actual=dict(current,**{'native.py':'5'*64,'native_protocol.py':'6'*64,'basic_cb_inference.py':'7'*64})
    changes={name:{'before_sha256':current.get(name),'after_sha256':actual.get(name)}
             for name in set(current)|set(actual) if current.get(name)!=actual.get(name)}
    review={'kind':'observed-bot-source-review-v1','qualification_sha256':'a'*64,
            'from_source_map':current,'to_source_map':actual,'changes':changes,
            'ordinary_duel_review':{'scope':'ordinary_effect_duel_default_path','reviewed_changes':deepcopy(changes),
                'evidence':[{'path':'/review/reports/ordinary-duel.json','sha256':'b'*64}]}}
    evidence={'kind':'ordinary-duel-source-review-evidence-v1','scope':'ordinary_effect_duel_default_path',
              'reviewed_changes':deepcopy(changes),'checks':['Inspected the exact ordinary-duel default branches.']}
    return {'original_source_map':old,'current_source_map':current},actual,review,evidence


class ObservedBotSourceReviewTests(unittest.TestCase):
    def test_exact_bridge_and_unchanged_default_guard(self):
        report,actual,review,evidence=fixture();saved=deepcopy(review)
        self.assertIsNone(observed.validate_observed_source_review(report,report['current_source_map'],'a'*64))
        with self.assertRaisesRegex(ContractError,'unreviewed driver/protocol'):
            observed.validate_observed_source_review(report,actual,'a'*64)
        raw=json.dumps(evidence).encode()
        with patch.object(Path,'is_file',return_value=True),patch.object(Path,'read_bytes',return_value=raw),\
             patch.object(observed.hashlib,'sha256',return_value=SimpleNamespace(hexdigest=lambda:'b'*64)):
            result=observed.validate_observed_source_review(report,actual,'a'*64,review)
        self.assertEqual(result['changed_source_files'],sorted(review['changes']))
        self.assertEqual(review,saved)

    def test_wrong_qualification_maps_changes_or_historical_protocol_are_rejected(self):
        report,actual,review,_=fixture()
        cases={}
        wrong=deepcopy(review);wrong['qualification_sha256']='c'*64;cases['qualification']=wrong
        wrong=deepcopy(review);wrong['from_source_map']['scenario_course.py']='c'*64;cases['from map']=wrong
        wrong=deepcopy(review);wrong['to_source_map']['native.py']='c'*64;cases['to map']=wrong
        wrong=deepcopy(review);del wrong['changes']['native_protocol.py'];cases['omitted protocol']=wrong
        wrong=deepcopy(review);wrong['changes']['native.py']['before_sha256']='c'*64;cases['wrong before']=wrong
        wrong=deepcopy(review);wrong['ordinary_duel_review']['reviewed_changes']={};cases['reviewed set']=wrong
        wrong=deepcopy(review);wrong['ordinary_duel_review']['scope']='passed';cases['scope']=wrong
        wrong=deepcopy(review);wrong['ordinary_duel_review']['evidence']=[];cases['evidence']=wrong
        with patch.object(Path,'read_bytes',side_effect=AssertionError('invalid review read evidence')):
            for name,value in cases.items():
                with self.subTest(name=name),self.assertRaises(ContractError):
                    observed.validate_observed_source_review(report,actual,'a'*64,value)
            historical=deepcopy(report);historical['original_source_map']['native.py']='d'*64
            with self.assertRaisesRegex(ContractError,'unreviewed driver/protocol'):
                observed.validate_observed_source_review(historical,actual,'a'*64,review)

    def test_evidence_is_pinned_and_a_passed_boolean_is_insufficient(self):
        report,actual,review,_=fixture()
        with patch.object(Path,'is_file',return_value=True),patch.object(Path,'read_bytes',return_value=b'{"passed":true}'),\
             patch.object(observed.hashlib,'sha256',return_value=SimpleNamespace(hexdigest=lambda:'b'*64)):
            with self.assertRaisesRegex(ContractError,'exact review scope and checks'):
                observed.validate_observed_source_review(report,actual,'a'*64,review)
        with patch.object(Path,'is_file',return_value=True),patch.object(Path,'read_bytes',return_value=b'{}'),\
             patch.object(observed.hashlib,'sha256',return_value=SimpleNamespace(hexdigest=lambda:'c'*64)):
            with self.assertRaisesRegex(ContractError,'checksum differs'):
                observed.validate_observed_source_review(report,actual,'a'*64,review)

    def test_real_game_and_qualification_callers_forward_the_bound_review(self):
        from ygo_kito import scenario_course,course_game_adapter
        _,_,review,_=fixture()
        course=object.__new__(scenario_course.ScenarioCourse)
        runtime=object.__new__(scenario_course.CourseBotRuntime)
        course.pending={'state':SimpleNamespace(status='ready',_current={'actor':object()}),'bot_id':'bot','purpose':'train'}
        course._require_training_admission=lambda *args: {'status':'admitted','fixture':'review-routing-only'}
        course.training_attempt_cursor=0;course.comparison_policy=None
        course.bots={'bot':{'runtime':runtime}}
        course.models=SimpleNamespace(duel=object(),sessions={},policy_rng=object(),binding={'observed_bot_source_review':review})
        course.assets=object();course.data_index=object();course.config={'course_id':'fixture','evaluation_pairs':{}}
        course.evaluation_cursor={};course.construction={};course.deck=object()
        course._storage_guard=lambda:None;course._task=lambda:object()
        class StopBeforeGame(Exception):pass
        with patch.object(scenario_course,'CourseGameAdapter',side_effect=StopBeforeGame) as constructor,\
             patch('ygo_kito.duel_planning.plans_from_construction',return_value=()):
            with self.assertRaises(StopBeforeGame):course._game()
        self.assertIs(constructor.call_args.kwargs['observed_bot_source_review'],review)
        adapter=object.__new__(course_game_adapter.CourseGameAdapter)
        opponent=object();registry=SimpleNamespace(training_adapter=Mock(return_value=opponent))
        adapter.bot=SimpleNamespace(workspace=Path('/recorded'),qualification_profile={},
            qualification={'sha256':'a'*64},registry=registry,executor_id='ExactExecutor')
        original=SimpleNamespace(main=(1,),extra=(),side=())
        adapter._originals={'bot':original};adapter.bot_id='bot'
        adapter.assets=object.__new__(course_game_adapter.PeriodBuildAssets)
        adapter._observed_bot_source_review=review;adapter._runtime_options=Mock(return_value={})
        proof=json.dumps({'kind':observed.KIND,'actor_seat':0}).encode()
        with patch.object(course_game_adapter,'_bytes',side_effect=[(None,b'{}'),(None,proof)]),\
             patch.object(course_game_adapter,'validate_profile'),patch.object(course_game_adapter,'_parts',return_value=original),\
             patch.object(observed,'validate_observed_bot_evidence') as validator:
            adapter._bind_original_qualification()
        self.assertIs(validator.call_args.kwargs['source_review'],review)


if __name__=='__main__':unittest.main()
