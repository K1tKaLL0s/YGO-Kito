"""Current role, continuation and feedback contracts; no model or CB runs."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from ygo_kito.build_contracts import digest
from ygo_kito.construction_progress import (construction_gate, quality_policy,
    restore_progress, record_optimization_feedback)
from ygo_kito.construction_relations import InputGroup, Need, RelationFact, Resource, UseRequirement
from ygo_kito.validation import ContractError
from tests.test_construction_layer_flow import session_for
from tests.test_construction_theme import theme_fixture, static_cycle, evaluate


def pending_fixture():
    f = list(theme_fixture())
    # Pending means an unimplemented printed qualifier, not an absent board or
    # actual phase input: construction evaluates static configuration purposes.
    f[1].rows[1]['desc'] = f[1].rows[1]['desc'].replace('自己主要阶段才能发动',
        '自己主要阶段且满足未识别的额外条件才能发动')
    f[4] = [f[4][0]]  # Keep the receiver; removing every effect is a different complete candidate.
    return f


class ConstructionProgressTests(unittest.TestCase):
    def test_goal_emits_effect_draft_and_only_optimizer_binds_cards(self):
        f = theme_fixture()
        result = static_cycle(self, f, session_for(f[0], f[2]), max_iterations=1)
        self.assertEqual([p['role'] for p in result['phases']], ['build_goal', 'build_optimizer'])
        self.assertEqual(result['phases'][0]['unfilled'], f[0].sizes)
        self.assertNotIn('proposal_deck_sha256', result['phases'][0])
        seed = result['handoffs'][0]
        self.assertEqual(seed['role'], 'build_optimizer')
        self.assertEqual(seed['input_draft_sha256'], result['effect_draft']['logic_sha256'])
        self.assertEqual(result['phases'][1]['input_deck_sha256'], seed['output_deck_sha256'])
        self.assertEqual(len(result['construction_candidate']['deck']['main']), 40)
        self.assertTrue(result['construction_passed'])

    def test_json_resume_continues_optimizer_and_preserves_original_task(self):
        f = pending_fixture()
        session = session_for(f[0], f[2])
        first = static_cycle(self, f, session, max_iterations=1)
        state = json.loads(json.dumps(first['continuation']))
        restore_progress(session, state, f[1])
        second = static_cycle(self, f, session, max_iterations=1)
        self.assertEqual([p['role'] for p in second['phases']], ['build_optimizer'])
        self.assertEqual(second['phases'][0]['input_deck_sha256'], digest(first['construction_candidate']['deck']))
        self.assertEqual(second['continuation']['iteration'], 2)
        self.assertEqual(session.task.sha256, f[0].sha256)
        bad = deepcopy(state); bad['task_sha256'] = 'another-task'
        with self.assertRaises(ContractError):
            restore_progress(session, bad, f[1])

    def test_passed_gate_still_requires_cb_authorization(self):
        f = theme_fixture()
        result = static_cycle(self, f, session_for(f[0], f[2]), max_iterations=1)
        self.assertTrue(result['construction_passed'])
        self.assertEqual(result['basic_cb']['status'], 'not_run')
        self.assertFalse(result['basic_cb']['execution_authorized'])
        self.assertFalse(result['construction_gate']['cb_result_used'])

    def test_pause_and_zero_time_do_not_start_role_or_cb(self):
        f = theme_fixture()
        for options in (dict(seconds=0), dict(pause_requested=lambda: True)):
            result = static_cycle(self, f, session_for(f[0], f[2]), max_iterations=1, **options)
            self.assertEqual(result['phases'], [])
            self.assertFalse(result['construction_passed'])
            self.assertIsNone(result['construction_candidate'])

    def test_candidate_budget_suspends_instead_of_completing(self):
        f = theme_fixture()
        session = session_for(f[0], f[2])
        result = static_cycle(self, f, session, max_iterations=1, max_candidates=0)
        self.assertEqual([p['role'] for p in result['phases']], ['build_goal'])
        self.assertEqual(result['stop_reason'], 'candidate_slice_exhausted')
        self.assertIsNone(result['continuation'])
        self.assertEqual(result['effect_draft']['unfilled'], session.task.sizes)
        self.assertEqual(result['effect_draft']['logic_sha256'], session.logic.sha256)
        resumed = static_cycle(self, f, session, max_iterations=1)
        self.assertEqual([p['role'] for p in resumed['phases']], ['build_optimizer'])
        self.assertEqual(resumed['effect_draft'], result['effect_draft'])

    def test_feedback_consumes_candidate_bound_external_instruction(self):
        f = pending_fixture()
        session = session_for(f[0], f[2])
        first = static_cycle(self, f, session, max_iterations=1)
        instruction = dict(feedback_id='current', source='external_ai', task_sha256=f[0].sha256,
            candidate_sha256=digest(first['construction_candidate']['deck']), issue='保留必要启动件',
            suggested_package={'main':[1], 'extra':[], 'side':[]})
        record_optimization_feedback(session, instruction)
        record_optimization_feedback(session, dict(instruction, feedback_id='old', candidate_sha256='0'*64))
        result = static_cycle(self, f, session, max_iterations=1)
        current, old = result['optimization_feedback']
        self.assertEqual(current['status'], 'adopted')
        self.assertEqual(current['consumed_iteration'], 2)
        self.assertEqual(old['status'], 'stale_candidate')
        self.assertTrue(any(r['source'] == 'external_ai' for r in session.feedback))

    def test_required_unknown_prevents_passing_but_unrelated_unknown_is_recorded(self):
        f = theme_fixture()
        p, _, known = evaluate(f)
        resource = Resource('original_task_state')
        fact = RelationFact('original-state', 'original-state', resource, 'original task condition', unknown=('missing_state',))
        relations = replace(f[5], facts=(*f[5].facts, fact))
        _, _, optional = evaluate(f, relations=relations)
        self.assertEqual(optional['score'], known['score'])
        self.assertTrue(optional['complete'])
        required = UseRequirement('original-condition', InputGroup('all', (Need('need-state', resource, mode='presence'),)),
            'original task condition', required=True)
        relations = replace(relations, uses=(required,))
        _, _, unknown = evaluate(f, relations=relations)
        layers = dict(axis=dict(task=f[0].to_dict(), inventory=f[4][0].to_dict(), logic=f[2].to_dict()))
        gate = construction_gate(f[0], f[4][0], f[1], layers, policy=p, quality=unknown)
        self.assertTrue(any('original-condition:unknown' in reason for reason in gate['reasons']))
        bad = deepcopy(p); bad['metrics'] = [dict(path=['model_score'], operator='ge', threshold=0)]
        with self.assertRaises(ContractError):
            quality_policy(bad)

    def test_direct_cb_entry_does_not_propose_without_pass_and_authorization(self):
        from ygo_kito.basic_cb_inference import infer_basic_cb
        f = theme_fixture()
        with patch('ygo_kito.basic_cb_inference.proposals', side_effect=AssertionError('CB forbidden')):
            result = infer_basic_cb(f[0], f[4][0], f[1], execution_authorized=True)
        self.assertEqual(result['status'], 'not_run')

    def test_only_winner_gets_cb_and_survives_resume(self):
        f = list(theme_fixture())
        original = f[4][0]
        cards = list(original.main)
        cards[cards.index(4)] = 16
        alternate = replace(original, main=tuple(sorted(cards)))
        f[4] = [original, alternate]
        session = session_for(f[0], f[2])
        visited = []
        def cb(_task, deck, _assets, **_kwargs):
            visited.append(deck.to_dict())
            return dict(status='routes_inferred', routes=[{'fixture': True}], normal_completion=True)
        result = static_cycle(self, f, session, max_iterations=1, cb_authorized=True, basic_cb_provider=cb)
        winner = result['best']['deck']
        self.assertEqual(visited, [winner])
        stage = result['phases'][-1]['stage_3']
        self.assertEqual(stage['candidate_count'], 2)
        loser = next(deck.to_dict() for deck in f[4] if deck.to_dict() != winner)

        def inventories(value):
            if isinstance(value, dict):
                if {'main', 'extra', 'side'} <= value.keys():
                    yield {key: value[key] for key in ('main', 'extra', 'side')}
                for child in value.values():
                    yield from inventories(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    yield from inventories(child)

        self.assertNotIn(loser, list(inventories(result)))
        self.assertFalse(result['retained_candidates'])
        self.assertFalse(result['continuation']['retained_candidates'])
        restore_progress(session, json.loads(json.dumps(result['continuation'])), f[1])
        resumed = static_cycle(self, f, session, max_iterations=0)
        self.assertEqual(resumed['best']['deck'], winner)
        self.assertFalse(resumed['retained_candidates'])


if __name__ == '__main__':
    unittest.main()
