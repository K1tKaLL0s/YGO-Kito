"""M6 real consumer seams with synthetic host facts; source only this batch."""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

from ygo_kito.build_contracts import DeckParts, digest
from ygo_kito.construction_fill import _candidate_basic_cb, construction_cycle, fill_with_existing
from ygo_kito.construction_recognition import (
    CatalogRecognitionFacts, ConstructionRecognitionProvider, cb_search_hints, collect_recognition,
    recognition_quality_evidence,
)
from ygo_kito.multifactor import CapabilityStatus, RoleAnalyzer
from tests.test_construction_functional_flow import fixture as functional_fixture, reviewed
from tests.test_construction_layer_flow import rows_for, session_for
from tests.test_construction_progress import pending_fixture
from tests.test_construction_theme import static_cycle


def fixture():
    values = functional_fixture()
    values[1].rows[2]['desc'] = '①：自己主要阶段可以发动。自己从卡组抽1张。'
    return values


def available_facts():
    return CapabilityStatus('deterministic_only', 'fixture reviewed observer', 'v1', ('fixture-only validation',), True)


def provider_for(assets, *, available=False, layer_policy=None):
    return ConstructionRecognitionProvider(RoleAnalyzer(CatalogRecognitionFacts(assets), capabilities=(
        {'function_facts': available_facts(), 'requirements': available_facts()} if available else {})),
        layer_policy=layer_policy, layer_policy_version='fixture-host-policy-v1' if layer_policy else '')


class ConstructionRecognitionTests(unittest.TestCase):
    def test_f12_pending_validator_raises_defined_contract_error(self):
        from types import SimpleNamespace
        from ygo_kito.construction_recognition import recognition_evidence_validator
        from ygo_kito.validation import ContractError
        validate = recognition_evidence_validator(SimpleNamespace(catalog=None, budget=None), {}, None)
        with patch('ygo_kito.construction_layer_flow.normalize_function_uses',
                   return_value={'calculation_pending': {'cursor': 1}}):
            with self.assertRaisesRegex(ContractError, 'static calculation must finish'):
                validate({}, None, None, None)

    def test_validator_implementation_error_is_not_optional_policy_fallback(self):
        from types import SimpleNamespace
        task, _, _, _, decks, _ = fixture()
        deck = decks[0]
        incoming = SimpleNamespace(layer_policy=lambda *args:{'source':'fixture'}, layer_policy_version='fixture-v1')
        records = {digest(deck.to_dict()):{'facts':{'capabilities':{'function_facts':'fixture'}}}}
        for error_type in (NameError,RuntimeError,TypeError):
            with self.subTest(error_type=error_type):
                validate = Mock(side_effect=error_type('unresolved internal implementation symbol'))
                evidence = recognition_quality_evidence(None, incoming, records, 'assist', validator=validate)
                with self.assertRaisesRegex(error_type, 'internal implementation'):
                    evidence(task, deck, {})

    def setUp(self):
        clock = patch('ygo_kito.construction_relations.perf_counter', return_value=0.)
        clock.start()
        self.addCleanup(clock.stop)

    def fill(self, mode, *, provider=None, host_evidence=None):
        task, assets, graph, binder, decks, policy = fixture()
        provider = provider if provider is not None else provider_for(assets)
        session = session_for(task, graph)
        with patch('ygo_kito.build_pipeline.edit_candidates', return_value=rows_for(task, decks)):
            result = fill_with_existing(session, assets, role='build_optimizer', base=decks[0],
                binding_provider=binder, text_reviewer=binder.reviewer, verifier=None, defer_engine=True,
                quality_policy=policy, quality_evidence=host_evidence, recognition_provider=provider, recognition_mode=mode)
        return task, assets, session, result

    def test_v26_off_does_not_call_or_inspect_recognition_provider(self):
        provider = Mock(side_effect=AssertionError('off must never call recognition'))
        self.fill('off', provider=provider)
        provider.assert_not_called()
        provider.analyze_candidate.assert_not_called()

    def test_v26_observe_preserves_order_scores_learning_feedback_and_gate_inputs(self):
        _, _, off_session, off = self.fill('off')
        _, _, observe_session, observe = self.fill('observe')
        records = observe.pop('recognition')['records']
        self.assertTrue(records)
        self.assertTrue(all(r['status'] == 'recorded' for r in records.values()))
        self.assertEqual(off, observe)
        self.assertEqual(off_session.to_dict(), observe_session.to_dict())

    def test_unavailable_assist_has_no_host_policy_call_and_keeps_selection(self):
        task, assets, graph, binder, decks, policy = fixture()
        mapper = Mock(side_effect=AssertionError('unavailable capabilities must not cross into host'))
        incoming = provider_for(assets, layer_policy=mapper)
        with patch('ygo_kito.build_pipeline.edit_candidates', return_value=rows_for(task, decks)):
            result = fill_with_existing(session_for(task, graph), assets, role='build_optimizer', base=decks[0],
                binding_provider=binder, text_reviewer=binder.reviewer, verifier=None, defer_engine=True,
                quality_policy=policy, recognition_provider=incoming, recognition_mode='assist')
        mapper.assert_not_called()
        self.assertTrue(all(not r['facts']['capabilities'] for r in result['recognition']['records'].values()))

    def test_assist_passes_available_facts_to_existing_host_evidence_protocol(self):
        task, assets, graph, binder, decks, policy = fixture()
        review = reviewed(binder.semantic_catalog, policy)
        calls = []
        def host_policy(task, deck, layers, facts):
            calls.append(facts)
            self.assertEqual(set(facts['capabilities']), {'function_facts'})
            self.assertTrue(all(c['contribution_score'] is None for c in facts['candidates']))
            return review(task, deck, layers)
        incoming = provider_for(assets, available=True, layer_policy=host_policy)
        with patch('ygo_kito.build_pipeline.edit_candidates', return_value=rows_for(task, decks)):
            result = fill_with_existing(session_for(task, graph), assets, role='build_optimizer', base=decks[0],
                binding_provider=binder, text_reviewer=binder.reviewer, verifier=None, defer_engine=True,
                quality_policy=policy, recognition_provider=incoming, recognition_mode='assist')
        self.assertTrue(calls)
        supplied = [r for r in result['recognition']['records'].values() if r.get('layer_policy', {}).get('status') == 'host_evidence_supplied']
        self.assertTrue(supplied)
        self.assertTrue(result['selection_complete'])
        self.assertEqual(result['quality_evaluation']['policy_version'], policy['version'])

    def test_observe_provider_failure_does_not_change_fill(self):
        provider = Mock()
        provider.analyze_candidate.side_effect = RuntimeError('recognition offline')
        _, _, _, off = self.fill('off')
        _, _, _, observe = self.fill('observe', provider=provider)
        records = observe.pop('recognition')['records']
        self.assertTrue(all(r['status'] == 'unknown' for r in records.values()))
        self.assertEqual(off, observe)

    def test_observe_latency_does_not_consume_cycle_budget_or_reach_cb(self):
        def run(mode):
            f = pending_fixture()
            session = session_for(f[0], f[2])
            clock = [0.]
            real = provider_for(f[1])
            def observer(task, deck, assets, *, mode):
                self.assertIsNotNone(session.construction_progress)
                self.assertEqual(session.construction_progress['status'], 'suspended')
                clock[0] = 10000.
                return real.analyze_candidate(task, deck, assets, mode=mode)
            with patch('time.monotonic', side_effect=lambda: clock[0]):
                result = static_cycle(self, f, session, seconds=30, max_iterations=1,
                    recognition_provider=observer, recognition_mode=mode)
            return result, session.to_dict()
        off, off_session = run('off')
        observe, observe_session = run('observe')
        self.assertTrue(observe.pop('recognition')['records'])
        self.assertEqual(off, observe)
        self.assertEqual(off_session, observe_session)

    def test_v27_duplicate_candidate_decks_only_observed_once(self):
        task, assets, _, _, decks, _ = fixture()
        real = provider_for(assets)
        observer = Mock(spec=real.analyze_candidate, side_effect=real.analyze_candidate)
        records = collect_recognition(observer, 'observe', task, [decks[0], decks[0]], assets)
        self.assertEqual(len(records), 1)
        self.assertTrue(all(record['status'] == 'recorded' for record in records.values()))
        observer.assert_called_once()

    def test_quality_mapper_failure_is_local_and_returns_prior_host_evidence(self):
        task, assets, _, _, decks, _ = fixture()
        incoming = provider_for(assets, available=True, layer_policy=Mock(side_effect=RuntimeError('one host mapping offline')))
        deck = decks[1]
        records = collect_recognition(incoming, 'assist', task, [deck], assets)
        self.assertTrue(records[digest(deck.to_dict())]['facts']['capabilities'])
        existing = Mock(return_value={'source': 'old host evidence'})
        wrapped = recognition_quality_evidence(existing, incoming, records, 'assist')
        self.assertEqual(wrapped(task, deck, {}), {'source': 'old host evidence'})
        incoming.layer_policy.assert_called_once()
        self.assertEqual(records[digest(deck.to_dict())]['layer_policy']['status'], 'unknown')

    def test_off_observe_reuse_exact_host_evidence_callable(self):
        existing, incoming = Mock(), Mock()
        for mode in ('off', 'observe'):
            self.assertIs(recognition_quality_evidence(existing, incoming, {'row': {}}, mode), existing)

    def test_cb_hints_require_available_assist_facts_and_explicit_provider_support(self):
        task, assets, _, _, decks, _ = fixture()
        incoming = provider_for(assets, available=True)
        # decks[0] contains none of the card carrying the reviewed draw fact.
        deck = decks[1]
        record = next(iter(collect_recognition(incoming, 'assist', task, [deck], assets).values()))
        hints = cb_search_hints(record)
        self.assertEqual(hints['legality'], 'unknown')
        self.assertEqual(hints['route_success'], 'unknown')
        self.assertIsNone(cb_search_hints(dict(record, mode='observe')))
        calls = []
        def cb(task, deck, assets, **kwargs):
            calls.append(kwargs)
            return dict(status='not_run', routes=[])
        _candidate_basic_cb(task, deck, assets, cb, recognition_record=record)
        self.assertNotIn('recognition_hints', calls[-1])
        cb.accepts_recognition_hints = True
        result = _candidate_basic_cb(task, deck, assets, cb, recognition_record=record)
        self.assertIn('recognition_hints', calls[-1])
        self.assertEqual(result['status'], 'not_run')
        self.assertFalse(result.get('cb_verified', False))

    def test_provider_cannot_change_original_target_by_mutating_its_task_copy(self):
        task, assets, _, _, decks, _ = fixture()
        original = deepcopy(task.goal)
        real = provider_for(assets)
        def bad(task, deck, assets, *, mode):
            task.goal['extra_unrequested_target'] = True
            return real.analyze_candidate(task, deck, assets, mode=mode)
        records = collect_recognition(bad, 'observe', task, decks[:1], assets)
        self.assertEqual(task.goal, original)
        self.assertTrue(all(r['status'] == 'unknown' for r in records.values()))

    def test_pending_quality_recomputes_when_recognition_policy_version_changes(self):
        from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
        from ygo_kito.construction_relations import RelationBudget
        task, assets, graph, binder, decks, policy = fixture()
        adapter = ConstructionLayerAdapter(binder, budget=RelationBudget(candidates=1))
        review = reviewed(binder.semantic_catalog, policy)
        incoming = provider_for(assets, available=True, layer_policy=lambda t, d, l, f: review(t, d, l))
        def run(pending=None):
            with patch('ygo_kito.build_pipeline.edit_candidates', return_value=rows_for(task, decks)):
                return fill_with_existing(session_for(task, graph), assets, role='build_optimizer', base=decks[0],
                    binding_provider=binder, text_reviewer=binder.reviewer, verifier=None, defer_engine=True,
                    layer_adapter=adapter, quality_policy=policy, pending_quality=pending,
                    recognition_provider=incoming, recognition_mode='assist')
        first = run()
        self.assertEqual(first['status'], 'quality_evaluation_pending')
        self.assertEqual(len(first['pending_quality']['evaluations']), 1)
        incoming.layer_policy_version = 'fixture-host-policy-v2'
        second = run(first['pending_quality'])
        self.assertNotEqual(first['pending_quality']['recognition_binding'], second['pending_quality']['recognition_binding'])
        self.assertEqual(len(second['pending_quality']['evaluations']), 1)


if __name__ == '__main__':
    unittest.main()
