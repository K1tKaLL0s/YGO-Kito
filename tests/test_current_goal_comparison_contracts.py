"""Synthetic comparison contracts only; no model, native game or gradient proof."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock,patch

from ygo_kito.build_contracts import DeckParts,digest
from ygo_kito.model_auxiliary import auxiliary_capability
from ygo_kito import model_build_feedback as primary
from ygo_kito.validation import ContractError


def script(name):
    path=Path(__file__).resolve().parents[1]/'scripts'/(name+'.py')
    spec=importlib.util.spec_from_file_location('contract_'+name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


auxiliary=script('local_course_auxiliary')
collaboration=script('local_course_collaboration')


def task_for(kind='deck_constraints'):
    raw={'goal':{'kind':kind}}
    return SimpleNamespace(sha256='c'*64,to_dict=lambda:deepcopy(raw))


def compare_arguments():
    return {'trainer':SimpleNamespace(updates=1),'registry':None,'bot':None,'audit':None,
        'workspace':None,'seeds':(31,32),'directory':'contract-never-sampled',
        'data_index':None,'experiment_id':'synthetic-contract','stop':None,'status':Mock()}


def frozen_comparison(task):
    """A complete synthetic two-seed/two-seat contract, never actual evidence."""
    candidates=[DeckParts((101,)),DeckParts((202,))];opponent=DeckParts((303,))
    def old_plan(task,decks,other,seeds,purpose):
        return {'task_sha256':task.sha256,'candidates':[d.to_dict() for d in decks],
            'opponent':other.to_dict(),'paired_seeds_audit_only':list(seeds),
            'actor_seats':[0,1],'purpose':purpose,'format':'replaced_by_frozen_format',
            'versions':{},'adapter_revision':1}
    def profile(deck,other,seat,revision):
        return {'synthetic_contract':True,'deck':deck.to_dict(),'seat':seat,'revision':revision}
    plan=old_plan(task,candidates,opponent,(31,32),'construction_train')
    plan.update(format='BO1_frozen_model_audited_bot',driver={
        'version':'frozen-learned-actor-audited-bot-v1','type':'actual_learned_neural_policy',
        'trained_policy':True,'policy_sha256':'a'*64,'policy_version':1,
        'feature_version':primary.FEATURE_VERSION,'opponent_id':'synthetic-contract-opponent',
        'executor_id':'synthetic-contract-executor','source_id':'synthetic-contract-source',
        'audit_sha256':'b'*64,'assembly_sha256':'d'*64,'policy_sampling':'private-paired-rng'})
    games=[]
    for seed in (31,32):
        for seat in (0,1):
            for i,deck in enumerate(candidates):
                outcome={'winner':seat if i else 1-seat,'reason_code':1}
                games.append({'candidate_index':i,'seed_audit_only':seed,'actor_seat':seat,
                    'outcome':outcome,'score':primary.outcome_score(outcome,seat),'turns':1,
                    'decisions':1,'trace_sha256':'e'*64,
                    'profile_sha256':digest(profile(deck,opponent,seat,1)),
                    'core_terminal_received':True,'replay_verified':True,
                    'policy_sha256':'a'*64,'data_artifact_id':f'contract-{i}-{seed}-{seat}'})
    means,differences,preferred=primary.preference(games,(31,32))
    value={'source':primary.SOURCE,'plan':plan,'plan_sha256':digest(plan),'games':games,
        'mean_scores':means,'paired_differences':differences,'preferred_index':preferred,
        'status':'paired_training_preference_observed',
        'uncertainty':primary.descriptive_uncertainty(differences),'competitive_ability_validated':False}
    value['comparison_sha256']=digest(value)
    return value,old_plan,profile


class CurrentGoalComparisonContracts(unittest.TestCase):
    def test_collaboration_excludes_deferred_candidates_without_changing_their_evidence(self):
        unknown={'status':'bounded_inference_unknown','routes':[]}
        contexts=[{'deck':DeckParts((101,)).to_dict(),'basic_cb':unknown},
                  {'deck':DeckParts((202,)).to_dict(),'basic_cb':{'synthetic_contract_evidence':True}}]
        verdicts=[{'status':'deferred','reasons':['basic_cb_unverified']},
                  {'status':'admitted','policy_epoch':'synthetic-contract'}]
        with patch('ygo_kito.training_admission.require_training_admission',side_effect=verdicts) as guard:
            admitted,recorded=collaboration.admit_comparison_candidates(task_for(),contexts,None)
        self.assertEqual(admitted,[contexts[1]])
        self.assertEqual(recorded,verdicts)
        self.assertIs(guard.call_args_list[0].kwargs['basic_cb'],unknown)
        self.assertEqual(contexts[0]['basic_cb']['routes'],[])

    def test_comparison_missing_policy_defers_before_any_driver_or_sampler(self):
        deck=DeckParts((101,));guard_path='ygo_kito.training_admission.require_training_admission'
        with patch(guard_path,return_value={'status':'deferred','reasons':['policy_missing']}) as guard,\
                patch.object(primary,'parameter_digest') as driver_digest:
            with self.assertRaisesRegex(ContractError,'deferred by training admission'):
                primary.compare_model_candidates(task_for(),None,[deck],deck,**compare_arguments())
            self.assertIsNone(guard.call_args.kwargs['comparison_policy'])
            self.assertIsNone(guard.call_args.kwargs['basic_cb'])
            driver_digest.assert_not_called()

    def test_comparison_passes_unknown_cb_to_shared_guard_and_never_samples_it(self):
        deck=DeckParts((101,));cb={'status':'bounded_inference_unknown','routes':[]}
        policy=Mock();guard_path='ygo_kito.training_admission.require_training_admission'
        with patch(guard_path,return_value={'status':'deferred','reasons':['basic_cb_unverified']}) as guard,\
                patch.object(primary,'parameter_digest') as driver_digest:
            with self.assertRaisesRegex(ContractError,'basic_cb_unverified'):
                primary.compare_model_candidates(task_for(),None,[deck],deck,
                    comparison_policy=policy,candidate_basic_cbs={digest(deck.to_dict()):cb},**compare_arguments())
            self.assertIs(guard.call_args.kwargs['basic_cb'],cb)
            self.assertIs(guard.call_args.kwargs['comparison_policy'],policy)
            self.assertEqual(guard.call_args.kwargs['purpose'],'construction_comparison')
            driver_digest.assert_not_called()

    def test_comparison_cannot_mix_policy_epochs_before_sampling(self):
        decks=[DeckParts((101,)),DeckParts((202,))]
        verdicts=[{'status':'admitted','policy_epoch':'epoch-a'},
                  {'status':'admitted','policy_epoch':'epoch-b'}]
        with patch('ygo_kito.training_admission.require_training_admission',side_effect=verdicts),\
                patch.object(primary,'parameter_digest') as driver_digest:
            with self.assertRaisesRegex(ContractError,'one bound training policy epoch'):
                primary.compare_model_candidates(task_for(),None,decks,decks[0],**compare_arguments())
            driver_digest.assert_not_called()

    def test_legacy_cases_cannot_receive_a_retrospective_training_admission(self):
        class ContractTrainer:
            updates=1
            model=object()
            sample_episode=Mock()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);directory=root/'legacy-comparison';directory.mkdir()
            (directory/'candidate-0-seed-31-seat-0.json').write_text('{"synthetic_contract":true}')
            audit=root/'audit.json';audit.write_text('{"synthetic_contract":true}')
            decks=[DeckParts((101,)),DeckParts((202,))];task=task_for()
            verdicts=[{'status':'admitted','task_sha256':task.sha256,
                'deck_sha256':digest(deck.to_dict()),'policy_epoch':'synthetic-contract',
                'reasons':[],'evidence_refs':['synthetic-contract-only']} for deck in decks]
            args=compare_arguments();args.update(trainer=ContractTrainer(),directory=directory,
                bot={'bot_id':'contract','executor_id':'contract','source_id':'contract'},
                audit={'path':str(audit),'assembly_sha256':'a'*64})
            with patch('ygo_kito.training_admission.require_training_admission',side_effect=verdicts),\
                    patch.object(primary,'CpuTrainer',ContractTrainer),\
                    patch.object(primary,'parameter_digest',return_value='b'*64),\
                    patch.object(primary,'old_plan_for',return_value={}):
                with self.assertRaisesRegex(ContractError,'no retrospective relabelling'):
                    primary.compare_model_candidates(task,SimpleNamespace(adapter_revision=1),decks,decks[0],**args)
            self.assertFalse((directory/'training-admission.json').exists())
            ContractTrainer.sample_episode.assert_not_called()

    def test_deck_constraints_does_not_read_a_stale_auxiliary_plan(self):
        class ForbiddenBase:
            def __truediv__(self,other):
                raise AssertionError('current goal must not read an inapplicable old plan')
        task=task_for()
        capability=auxiliary_capability(task.to_dict())
        self.assertFalse(capability['supported'])
        self.assertEqual(capability['reason'],'declared_auxiliary_objective_absent')
        self.assertIsNone(auxiliary.completed_auxiliary(task,None,{},None,None,ForbiddenBase(),46))

    def test_primary_unknown_does_not_create_a_training_pair(self):
        comparison={'preferred_index':None,'mean_scores':[0.,0.]}
        candidates=[DeckParts((101,)),DeckParts((202,))]
        self.assertIsNone(collaboration.comparison_training_pair(comparison,candidates,None))
        with self.assertRaisesRegex(RuntimeError,'exact evaluated evidence'):
            collaboration.comparison_training_pair(comparison,candidates,1)

    def test_strict_primary_keeps_its_exact_evidence_and_candidate_order(self):
        comparison={'preferred_index':1,'mean_scores':[0.,1.]}
        candidates=[DeckParts((101,)),DeckParts((202,))]
        pair=collaboration.comparison_training_pair(comparison,candidates,1)
        self.assertIs(pair['evidence'],comparison)
        self.assertEqual(pair['source'],primary.SOURCE)
        self.assertEqual(pair['better'],candidates[1].to_dict())
        with self.assertRaisesRegex(RuntimeError,'strict primary'):
            collaboration.comparison_training_pair(comparison,candidates,0)

    def test_strict_comparison_rejects_a_different_current_task(self):
        task=task_for();value,old_plan,profile=frozen_comparison(task)
        assets=SimpleNamespace(validate=Mock())
        with patch.object(primary,'old_plan_for',side_effect=old_plan),patch.object(primary,'profile_for_case',side_effect=profile):
            self.assertEqual(len(primary.validate_model_comparison(task,assets,value)),2)
            other=SimpleNamespace(sha256='f'*64)
            with self.assertRaisesRegex(ContractError,'plan changed'):
                primary.validate_model_comparison(other,assets,value)

    def test_optimizer_consumption_requires_exact_feedback_artifact_and_role(self):
        correct={'feedback_id':'feedback-1','artifact_id':'artifact-1','role':'build_optimizer'}
        for rows in ([],[dict(correct,role='build_goal')],[dict(correct,artifact_id='other')],
                     [dict(correct,feedback_id='other')]):
            with self.assertRaisesRegex(RuntimeError,'consumed role receipt'):
                collaboration.optimizer_feedback_receipt(rows,'feedback-1','artifact-1')
        self.assertEqual(collaboration.optimizer_feedback_receipt([correct],'feedback-1','artifact-1')['status'],'consumed')

    def test_supported_goals_keep_registered_plan_and_task_guards(self):
        for kind in ('fusion_summon','normal_summon'):
            with self.subTest(kind=kind):
                task=task_for(kind)
                self.assertTrue(auxiliary_capability(task.to_dict())['supported'])
                stale={'plan_sha256':auxiliary.POLICY_SHA,'task_sha256':'b'*64}
                with patch.object(Path,'read_text',return_value=json.dumps(stale)):
                    with self.assertRaisesRegex(RuntimeError,'prospective auxiliary registration'):
                        auxiliary.completed_auxiliary(task,None,{},None,None,Path('contract-base'),46)
                stale['plan_sha256']='0'*64
                with patch.object(Path,'read_text',return_value=json.dumps(stale)):
                    with self.assertRaisesRegex(RuntimeError,'policy changed'):
                        auxiliary.completed_auxiliary(task,None,{},None,None,Path('contract-base'),46)


if __name__=='__main__':unittest.main()
