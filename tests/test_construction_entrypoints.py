"""Active entry points, completed reference attempts and independent observation.

Only pure contracts and isolated static records are used. No trainer, model,
supervisor process, CB search or native game is started.
"""
from copy import deepcopy
import importlib.util
import json
import unittest

from ygo_kito.build_contracts import digest
from ygo_kito.construction_progress import (construction_gate, host_construction_quality,
    quality_policy, record_reference_attempt, restore_progress)
from ygo_kito.validation import ContractError
from tests.test_construction_layer_flow import session_for
from tests.test_construction_theme import theme_fixture, evaluate, static_cycle
from tests import test_design_supervisor as supervisor_cases


def reference_fixture():
    f = list(theme_fixture())
    reference = f[4][0]
    p = host_construction_quality(f[0], catalog=f[3].semantic_catalog)[0]
    descriptor = dict(reference_id='declared-static-reference', source='static host request',
        environment=deepcopy(f[0].environment), deck=reference.to_dict())
    p['pass'] = dict(mode='reference_ratio', minimum_reference_ratio=.8,
        reference=dict(reference_id=descriptor['reference_id'], source=descriptor['source'],
            deck_sha256=digest(descriptor['deck'])))
    f[4] = [f[4][2]]
    return f, p, descriptor, reference


def reference_gate(f, p, reference, *, passed=False, version=1):
    deck = reference if passed else f[4][0]
    _, _, q = evaluate(f, deck, policy=p)
    _, _, r = evaluate(f, reference, policy=p)
    layers = dict(axis=dict(task=f[0].to_dict(), inventory=deck.to_dict(), logic=f[2].to_dict()))
    return construction_gate(f[0], deck, f[1], layers, policy=p, quality=q,
        reference_quality=r, candidate_version=version)


class ReferenceAttemptTests(unittest.TestCase):
    def test_proven_ratio_and_static_completeness_are_independent_gate_checks(self):
        from ygo_kito.construction_quality import evaluate_functional_quality

        f, p, _, reference = reference_fixture()
        _, _, reference_quality = evaluate(f, reference, policy=p)
        for deck, expected in ((reference, 'passed'), (f[4][0], 'failed')):
            with self.subTest(expected=expected):
                _, facts, _ = evaluate(f, deck, policy=p)
                keys = [f'other:{i}:candidate:{facts["deck_sha256"]}' for i in range(17)]
                facts['variables'].update(dict.fromkeys(keys))
                facts['constraints'] = [{'any': [key, {'not': key}]} for key in keys]
                layers = dict(axis=dict(task=f[0].to_dict(), inventory=deck.to_dict(), logic=f[2].to_dict()))
                quality = evaluate_functional_quality(layers, policy=p, facts=facts)
                gate = construction_gate(f[0], deck, f[1], layers, policy=p,
                    quality=quality, reference_quality=reference_quality)
                line, = gate['metrics']
                self.assertEqual(line['status'], expected)
                self.assertEqual(gate['status'], 'pending')
                self.assertIn('quality_evaluation_incomplete', gate['reasons'])

    def test_completed_attempts_are_idempotent_and_hints_advance_without_reference_cards(self):
        f, p, _, reference = reference_fixture()
        gate = reference_gate(f, p, reference)
        self.assertEqual(gate['reasons'], ['quality_pass_line:reference_ratio:failed'])
        state = dict(quality_policy=p, task_sha256=f[0].sha256, iteration=1, candidate_version=1)
        self.assertIsNone(record_reference_attempt(state, gate))
        self.assertIsNone(record_reference_attempt(state, gate))
        self.assertEqual(state['reference_feedback']['consecutive_below_reference'], 1)
        stages = []
        for iteration in (2, 3, 4):
            state.update(iteration=iteration, candidate_version=iteration)
            hint = record_reference_attempt(state, dict(gate, candidate_version=iteration))
            stages.append(hint['stage'])
            self.assertNotIn('卡名', hint['message'])
            self.assertNotIn('reference', hint['message'])
            self.assertNotIn('接收效果', hint['message'])
        self.assertEqual(stages, ['main_axis', 'secondary_axes', 'generic'])
        with self.assertRaises(ContractError):
            record_reference_attempt(state, gate)

    def test_unknown_missing_or_invalid_reference_does_not_increment_the_counter(self):
        f, p, _, reference = reference_fixture()
        gate = reference_gate(f, p, reference)
        state = dict(quality_policy=p, task_sha256=f[0].sha256, iteration=1, candidate_version=1)
        record_reference_attempt(state, gate)
        for reasons in (['reference_evaluation_missing', 'quality_pass_line:reference_ratio:unknown'],
                        ['quality_evaluation_incomplete', 'quality_pass_line:reference_ratio:failed'],
                        ['reference_score_nonpositive', 'quality_pass_line:reference_ratio:failed'],
                        ['quality_assets_changed', 'quality_pass_line:reference_ratio:failed']):
            state.update(iteration=2, candidate_version=2)
            record_reference_attempt(state, dict(gate, candidate_version=2, reasons=reasons))
            self.assertEqual(state['reference_feedback']['consecutive_below_reference'], 1)
            self.assertEqual(state['reference_feedback']['last_iteration'], 1)

    def test_confirmed_pass_resets_a_consecutive_shortfall(self):
        f, p, _, reference = reference_fixture()
        state = dict(quality_policy=p, task_sha256=f[0].sha256, iteration=1, candidate_version=1)
        record_reference_attempt(state, reference_gate(f, p, reference))
        state.update(iteration=2, candidate_version=2)
        record_reference_attempt(state, reference_gate(f, p, reference, passed=True, version=2))
        self.assertEqual(state['reference_feedback']['consecutive_below_reference'], 0)
        self.assertIsNone(state['reference_feedback']['hint_stage'])

    def test_hints_enter_the_next_optimizer_feedback_and_restore_does_not_repeat_attempts(self):
        f, p, descriptor, _ = reference_fixture()
        session = session_for(f[0], f[2])
        result = static_cycle(self, f, session, quality_criteria=p, quality_reference=descriptor, max_iterations=4)
        self.assertFalse(result['construction_passed'])
        phases = [r for r in result['phases'] if r['role'] == 'build_optimizer']
        self.assertEqual([r['reference_feedback']['hint_stage'] for r in phases],
            [None, 'main_axis', 'secondary_axes', 'generic'])
        self.assertTrue(any('先检查主轴' in r['message'] for r in session.feedback))
        self.assertTrue(any('检查副轴' in r['message'] for r in session.feedback))
        self.assertTrue(any('检查泛用配置' in r['message'] for r in session.feedback))
        saved = json.loads(json.dumps(result['continuation']))
        restore_progress(session, saved, f[1])
        resumed = static_cycle(self, f, session, quality_criteria=p, quality_reference=descriptor, max_iterations=0)
        self.assertEqual(resumed['continuation']['reference_feedback'], saved['reference_feedback'])
        bad = deepcopy(saved); bad['reference_feedback']['last_iteration'] = saved['iteration'] + 1
        with self.assertRaises(ContractError):
            restore_progress(session, bad, f[1])

    def test_policy_revision_resets_the_counter_but_preserves_optimizer_progress(self):
        f, p, descriptor, _ = reference_fixture()
        session = session_for(f[0], f[2])
        first = static_cycle(self, f, session, quality_criteria=p, quality_reference=descriptor, max_iterations=2)
        self.assertEqual(first['continuation']['reference_feedback']['consecutive_below_reference'], 2)
        changed = deepcopy(p); changed['source'] += ':revised-host'
        revised = static_cycle(self, f, session, quality_criteria=changed, quality_reference=descriptor, max_iterations=0)
        self.assertNotIn('reference_feedback', revised['continuation'])
        for key in ('iteration', 'candidate_cursor', 'handoffs'):
            self.assertEqual(revised['continuation'][key], first['continuation'][key])
        final = static_cycle(self, f, session, quality_criteria=changed, quality_reference=descriptor, max_iterations=1)
        self.assertEqual(final['continuation']['reference_feedback']['consecutive_below_reference'], 1)

    def test_pause_and_budget_exhaustion_do_not_create_reference_attempts(self):
        f, p, descriptor, _ = reference_fixture()
        for options in (dict(pause_requested=lambda: True), dict(max_candidates=0)):
            result = static_cycle(self, f, session_for(f[0], f[2]), quality_criteria=p,
                quality_reference=descriptor, max_iterations=3, **options)
            self.assertNotIn('reference_feedback', result.get('continuation') or {})


class ActiveEntryTests(unittest.TestCase):
    def test_unused_scoring_contract_and_old_public_types_have_been_removed(self):
        import ygo_kito.construction_quality as q
        import ygo_kito.construction_candidates as c
        self.assertIsNone(importlib.util.find_spec('ygo_kito.construction_contract'))
        for name in ('GenericFit', 'DuplicatePurpose', 'SideValue', 'SlotUse', 'QualityLoss', 'SideDeck', 'ITEM_ORDER'):
            self.assertFalse(hasattr(q, name), name)
        self.assertFalse(hasattr(c, 'retained_order'))
        self.assertFalse(hasattr(c, 'layer_selection_allowed'))
        self.assertFalse(hasattr(c, 'select_retained'))

    def test_old_policies_and_old_scoring_arguments_are_rejected(self):
        from ygo_kito.construction_quality import evaluate_quality
        for p in (dict(version='old', source='old', metrics=[dict(path=['axis', 'K'], operator='ge', threshold=1)]),
                  dict(version='old', source='old', metrics=[], quality={'evaluator_version':'construction-quality-evaluation-v3'},
                      **{'pass':{'mode':'none'}})):
            with self.assertRaises(ContractError):
                quality_policy(p)
        with self.assertRaises(TypeError):
            evaluate_quality({}, policy={}, facts={}, slot_uses=[])


class StaticSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.fixture = supervisor_cases.IndependentDesignSupervisorTests(
            'test_separate_process_accepts_correct_evidence_without_trusting_main_flags')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        spec = importlib.util.spec_from_file_location('current_static_observer', self.fixture.script)
        self.observer = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.observer)
        self.catalog = self.observer.Catalog(self.fixture.base, self.fixture.policy)
        self.addCleanup(self.catalog.db.close)

    def inspect(self):
        supervisor_cases.write(self.fixture.path, self.fixture.result)
        return self.observer.inspect_artifact(self.fixture.path, self.fixture.course, self.catalog)

    def test_current_partial_skeleton_and_functional_gate_are_accepted(self):
        receipt = self.inspect()
        self.assertEqual(receipt['task_sha256'], digest(self.fixture.task))
        self.assertEqual(len(self.fixture.result['phases'][0]['proposal_deck']['main']), 1)

    def test_retired_gate_or_quality_version_cannot_open_clearance(self):
        result = deepcopy(self.fixture.result)
        self.fixture.result['construction_gate']['version'] = 'construction-before-cb-v2'
        with self.assertRaises(self.observer.Unknown):
            self.inspect()
        self.fixture.result = result
        self.fixture.result['construction_candidate']['quality_evaluation']['version'] = 'construction-quality-evaluation-v3'
        with self.assertRaises(self.observer.Unknown):
            self.inspect()

    def test_reported_pass_cannot_hide_mismatched_quality_or_a_failed_hard_requirement(self):
        result = deepcopy(self.fixture.result)
        self.fixture.result['construction_candidate']['quality_evaluation']['deck_sha256'] = '0'*64
        with self.assertRaises(self.observer.Violation):
            self.inspect()
        self.fixture.result = result
        q = self.fixture.result['construction_candidate']['quality_evaluation']
        q['hard_requirements'] = [dict(requirement_id='original', origin='original task', status='failed')]
        q['evaluation_id'] = digest({k:v for k,v in q.items() if k != 'evaluation_id'})
        with self.assertRaises(self.observer.Violation):
            self.inspect()

    def test_task_predicates_share_the_current_public_rules(self):
        task = deepcopy(self.fixture.task)
        task['goal']['constraints'] = [dict(id='nested', zones=['main'], minimum=40, maximum=40,
            predicate={'all':[{'field':'type_all','value':1}, {'any':[
                {'field':'setcode','value':385}, {'field':'card_ids','value':task['pool']}]}]})]
        self.catalog.deck(self.fixture.result['construction_candidate']['deck'], task)
        task['goal']['constraints'].append(dict(id='level', zones=['main'], minimum=40, maximum=40,
            predicate={'field':'level_between','value':[4,4]}))
        self.catalog.deck(self.fixture.result['construction_candidate']['deck'], task)
        task['goal']['constraints'][-1]['predicate']['value'] = [5,5]
        with self.assertRaises(self.observer.Violation):
            self.catalog.deck(self.fixture.result['construction_candidate']['deck'], task)
        self.assertTrue(self.observer.matches_task_predicate({'id':1, 'setcode':0x2181},
            {'field':'setcode','value':0x181}))


if __name__ == '__main__':
    unittest.main()
