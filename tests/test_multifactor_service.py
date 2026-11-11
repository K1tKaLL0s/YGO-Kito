"""M6 service regressions. Source only; this batch does not execute tests."""
from dataclasses import replace
import json
import unittest
from unittest.mock import Mock, patch

from ygo_kito.multifactor import (
    AnalysisBudget, AnalysisContext, AnalysisFacts, AnalysisRequestContext, CapabilityStatus,
    CandidateBudget, CopyChange, DeckSpec, ExternalLegality, FactorContractError, FunctionSeed, GraphBudget,
    RoleAnalyzer, SamplingSpec, StructureLink, UnitSpec,
    Resource, Condition, ConditionGroup,
)
from ygo_kito.multifactor.functional_units import Dependency, FunctionalContract, KnownCondition, MemberAmount


def request(**kwargs):
    return AnalysisRequestContext(context_ref='goal', declared_goal='draw without changing the original objective', **kwargs)


def facts(deck=None, context=None, unit=None):
    return AnalysisFacts(function_seeds=(FunctionSeed('effect:draw', (('card:1', 1),), ('draw',),
                                                 evidence_refs=('reviewed draw operation',)),))


def contract(context='goal'):
    return FunctionalContract('draw-unit', context, 'function:draw', (MemberAmount('card:1', 1),),
        (Dependency('card:1', (MemberAmount('card:2', 1),), 'necessary companion'),),
        ('card:1', 'card:2'), (KnownCondition('structure', 'satisfied', 'reviewed', 'structure'),),
        'reviewed definition', function_tags=('draw',))


def published():
    return CapabilityStatus('available', 'fixture scorer', 'fixture-v1', ('isolated validation',), True, True)


class ServiceTests(unittest.TestCase):
    def test_v23_actual_section_denominators_at_all_requested_sizes(self):
        analyzer = RoleAnalyzer(facts)
        for size in (40, 41, 45, 50, 55, 60):
            for extra, side in (((), ()), (((3, 4),), ((4, 7),)), (((3, 15),), ((4, 15),))):
                with self.subTest(size=size, extra=extra, side=side):
                    result = analyzer.analyze_deck(DeckSpec(((1, 3), (2, size - 3)), extra, side), request())
                    self.assertEqual(result.deck_summary['main']['count'], size)
                    self.assertEqual(result.units[0]['concentration']['main']['value'], 3 / size)
                    self.assertIsNone(result.units[0]['contribution_score'])
                    self.assertEqual(result.deck_summary['extra']['count'], sum(n for _, n in extra))

    def test_unknown_and_known_empty_regions_are_distinct(self):
        result = RoleAnalyzer(facts).analyze_deck(DeckSpec(((1, 1),), None, ()), request())
        self.assertEqual(result.deck_summary['extra']['density_status'], 'unknown')
        self.assertEqual(result.deck_summary['side']['density_status'], 'not_applicable')
        self.assertIsNone(result.deck_summary['extra']['count'])

    def test_off_never_touches_fact_or_score_provider(self):
        provider, scorer = Mock(side_effect=AssertionError('off provider called')), Mock()
        result = RoleAnalyzer(provider, scorer=scorer, capabilities={'mechanism': published()}).analyze_deck(
            DeckSpec(((1, 1),), (), ()), request(mode='off'))
        provider.assert_not_called()
        scorer.score_graph.assert_not_called()
        self.assertEqual(result.raw_prediction, ())

    def test_untrained_missing_and_engineering_heads_stay_unknown(self):
        for status in ('unavailable', 'untrained', 'engineering_only'):
            scorer = Mock()
            result = RoleAnalyzer(facts, scorer=scorer, capabilities={'mechanism': CapabilityStatus(status)}).analyze_deck(
                DeckSpec(((1, 1),), (), ()), request(mode='assist'))
            scorer.score_graph.assert_not_called()
            self.assertEqual(result.applied_prediction, ())
            self.assertEqual(result.genericity['environment_value']['status'], 'unknown')

    def test_uncalibrated_head_is_diagnostic_only(self):
        row = dict(task='mechanism', subject=['card:1'], coordinate='draw', value=.8)
        scorer = Mock()
        scorer.score_graph.return_value = dict(raw_prediction=(row,))
        result = RoleAnalyzer(facts, scorer=scorer,
            capabilities={'mechanism': CapabilityStatus('trained_uncalibrated')}).analyze_deck(
                DeckSpec(((1, 1),), (), ()), request(mode='assist'))
        self.assertEqual(result.raw_prediction, (row,))
        self.assertEqual(result.calibrated_scores, ())
        self.assertEqual(result.applied_prediction, ())

    def test_capability_failure_only_disables_that_head(self):
        row = dict(task='legacy:support_role', subject=['card:1'], coordinate='value', value=.8)
        scorer = Mock()
        def score(build, *, task, query_budget):
            if task == 'mechanism':
                raise RuntimeError('one unavailable head')
            return dict(raw_prediction=(row,), calibrated_scores=(row,), applied_prediction=(row,))
        scorer.score_graph.side_effect = score
        result = RoleAnalyzer(facts, scorer=scorer, capabilities={'mechanism': published(), 'legacy:support_role': published()}).analyze_deck(
            DeckSpec(((1, 1),), (), ()), request(mode='assist'))
        self.assertEqual(result.capabilities['mechanism']['status'], 'failed')
        self.assertEqual(result.capabilities['legacy:support_role']['status'], 'available')
        self.assertEqual(len(result.functions), 1)
        self.assertEqual(result.derived_summary['support_role']['status'], 'known')
        self.assertEqual(result.derived_summary['large_axis']['status'], 'unknown')

    def test_applied_queries_must_have_corresponding_calibrated_rows(self):
        scorer = Mock()
        scorer.score_graph.return_value = dict(applied_prediction=(dict(task='mechanism', subject=['card:1'], coordinate='draw', value=1),))
        result = RoleAnalyzer(facts, scorer=scorer, capabilities={'mechanism': published()}).analyze_deck(
            DeckSpec(((1, 1),), (), ()), request(mode='assist'))
        self.assertEqual(result.capabilities['mechanism']['status'], 'failed')
        self.assertEqual(result.applied_prediction, ())

    def test_observe_keeps_fitted_predictions_out_of_applied_layer(self):
        row = dict(task='mechanism', subject=['card:1'], coordinate='draw', value=.8)
        scorer = Mock()
        scorer.score_graph.return_value = dict(raw_prediction=(row,), calibrated_scores=(row,), applied_prediction=(row,))
        result = RoleAnalyzer(facts, scorer=scorer, capabilities={'mechanism': published()}).analyze_deck(
            DeckSpec(((1, 1),), (), ()), request())
        self.assertEqual(result.calibrated_scores, (row,))
        self.assertEqual(result.applied_prediction, ())

    def test_definition_and_receiver_instance_are_separate(self):
        analyzer = RoleAnalyzer(lambda d, c, u: replace(facts(), unit_contracts=(contract(),)))
        unit = UnitSpec('package', ((1, 1), (2, 1)), 'function:draw')
        result = analyzer.assess_unit(unit, DeckSpec(((1, 1),), (), ((2, 1),)), request(), 'function:draw')
        self.assertEqual(result.definition_assessment[0]['structural_status'], 'complete')
        self.assertEqual(result.requirement_assessment[0]['structural_status'], 'partial')
        self.assertEqual(result.requirement_assessment[0]['missing_members'], {'card:2': 1})
        no_receiver = analyzer.assess_unit(unit, None, request(), 'function:draw')
        self.assertEqual(no_receiver.genericity['receiver_compatibility']['status'], 'not_applicable')
        self.assertEqual(no_receiver.genericity['transferability']['status'], 'unknown')

    def test_unknown_active_region_cannot_establish_missing_companion(self):
        analyzer = RoleAnalyzer(lambda d, c, u: replace(facts(), unit_contracts=(contract(),)))
        result = analyzer.assess_unit(UnitSpec('package', ((1, 1), (2, 1)), 'function:draw'),
            DeckSpec(((1, 1),), None, ()), request(), 'function:draw')
        self.assertEqual(result.requirement_assessment[0]['structural_status'], 'unknown')
        self.assertIsNone(result.requirement_assessment[0]['branches'][0]['requirement_assessment']['satisfied'])

    def test_graph_budget_failure_preserves_independent_contract_assessment(self):
        analyzer = RoleAnalyzer(lambda d, c, u: replace(facts(), unit_contracts=(contract(),)),
            budget=AnalysisBudget(graph=GraphBudget(nodes=1)))
        result = analyzer.analyze_deck(DeckSpec(((1, 1), (2, 1)), (), ()), request())
        self.assertEqual(result.capabilities['function_facts']['status'], 'failed')
        self.assertEqual(result.requirement_assessment[0]['structural_status'], 'complete')
        scorer = Mock()
        partial = RoleAnalyzer(lambda d, c, u: AnalysisFacts(function_seeds=tuple(
            FunctionSeed('scope:' + str(i), (('card:1', 1),), ('draw',)) for i in range(10))),
            scorer=scorer, capabilities={'legacy:support_role': published()},
            budget=AnalysisBudget(candidates=CandidateBudget(checks=1))).analyze_deck(
                DeckSpec(((1, 1),), (), ()), request(mode='assist'))
        self.assertTrue(partial.derived_summary['candidate_overflow'])
        self.assertEqual(partial.capabilities['legacy:support_role']['status'], 'failed')
        scorer.score_graph.assert_not_called()

    def test_v24_addition_replacement_and_reduction_are_actual_changes(self):
        analyzer = RoleAnalyzer(facts)
        deck = DeckSpec(((1, 3), (2, 37)), (), ())
        addition = analyzer.compare_copy_change(deck, CopyChange(1, 'main'), None, ('draw',), request())
        self.assertEqual(addition.after.deck_summary['main']['count'], 41)
        self.assertEqual(addition.differences['section_counts']['main'], 1)
        self.assertEqual(addition.after.units[0]['concentration']['main']['value'], 4 / 41)
        replacement = analyzer.compare_copy_change(deck, CopyChange(1, 'main'), CopyChange(2, 'main'), ('draw',), request())
        self.assertEqual(replacement.after.deck_summary['main']['count'], 40)
        reduction = analyzer.compare_copy_change(deck, None, CopyChange(1, 'main'), ('draw',), request())
        self.assertEqual(reduction.after.deck_summary['main']['count'], 39)
        self.assertEqual(reduction.preference.status, 'unknown')
        self.assertEqual(reduction.preference.reason_code, 'REPLACEMENT_UNSPECIFIED')

    def test_reobserve_full_after_inventory_and_related_dependencies(self):
        seen = []
        def provider(deck, context, unit):
            seen.append(deck)
            return replace(facts(), unit_contracts=(contract(),), structure_links=(StructureLink('card:1', 'card:2', 'requires', required=True),))
        result = RoleAnalyzer(provider).compare_copy_change(DeckSpec(((1, 1), (2, 1)), (), ()),
            CopyChange(3, 'main'), CopyChange(2, 'main'), ('draw',), request())
        self.assertEqual(len(seen), 2)
        self.assertEqual(dict(seen[1].main), {1: 1, 3: 1})
        self.assertEqual(result.before.requirement_assessment[0]['structural_status'], 'complete')
        self.assertEqual(result.after.requirement_assessment[0]['structural_status'], 'partial')
        self.assertIn('resource_conflicts', result.differences['recomputed'])

    def test_invalid_removal_and_unknown_region_fail_before_provider(self):
        provider = Mock()
        analyzer = RoleAnalyzer(provider)
        for deck, remove in ((DeckSpec(((1, 1),), (), ()), CopyChange(1, 'main', 2)),
                             (DeckSpec(((1, 1),), None, ()), CopyChange(1, 'extra'))):
            with self.assertRaises(FactorContractError):
                analyzer.compare_copy_change(deck, None, remove, ('draw',), request())
        provider.assert_not_called()

    def test_contact_probability_only_uses_declared_single_sample(self):
        from ygo_kito.construction_relations import single_event_probabilities
        analyzer = RoleAnalyzer(facts)
        deck = DeckSpec(((1, 3), (2, 37)), (), ())
        args = (deck, CopyChange(1, 'main'), None, ('draw',))
        self.assertEqual(analyzer.compare_copy_change(*args, request()).differences['contact_probability']['status'], 'unknown')
        result = analyzer.compare_copy_change(*args, request(sampling=SamplingSpec('main', 5)))
        value = result.differences['contact_probability']['value']
        self.assertEqual(value['before'], single_event_probabilities(40, 3, 5))
        self.assertEqual(value['after'], single_event_probabilities(41, 4, 5))
        self.assertEqual(result.differences['joint_success']['status'], 'unknown')

    def test_legality_requires_external_producer_version_and_exact_subject(self):
        deck = DeckSpec(((1, 1),), (), ())
        external = ExternalLegality('pass', deck, 'goal', 'existing verifier', 'v1', ('external result',),
                                    declared_goal=request().declared_goal)
        analyzer = RoleAnalyzer()
        self.assertEqual(analyzer.analyze_deck(deck, request()).legality.status, 'unknown')
        self.assertEqual(analyzer.analyze_deck(deck, request(external_legality=external)).legality.value, 'pass')
        result = analyzer.compare_copy_change(deck, CopyChange(1, 'main'), None, ('draw',), request(external_legality=external))
        self.assertEqual(result.after.legality.status, 'unknown')

    def test_v27_repeated_function_facts_do_not_duplicate_contribution(self):
        seed = facts().function_seeds[0]
        result = RoleAnalyzer(lambda d, c, u: AnalysisFacts(function_seeds=(seed, seed))).analyze_deck(
            DeckSpec(((1, 1),), (), ()), request())
        self.assertEqual(len(result.functions), 1)
        self.assertIsNone(result.units[0]['contribution_score'])

    def test_supervision_blocks_cannot_be_request_context(self):
        for block in ('targets', 'supervision', 'provenance', 'labels'):
            with self.assertRaises(FactorContractError):
                AnalysisRequestContext.from_dict({block: {}})

    def test_v25_changed_effect_reason_and_count_event_are_reobserved(self):
        from ygo_kito.effect_mechanisms import analyze_card
        row = dict(id=1, type=33, name='fixture', desc='这个卡名的①效果1回合只能使用1次。①：从卡组把1张卡送去墓地。')
        changed = dict(row, desc='这个卡名的①效果1回合只能发动1次。①：从卡组把1张卡送去墓地才能发动。自己抽1张。')
        snapshots = [analyze_card(value, '').to_dict() for value in (row, changed)]
        seen = []
        def provider(deck, context, unit):
            value = snapshots[len(seen)]
            seen.append(value)
            return AnalysisFacts(effect_snapshots={1: value})
        analyzer = RoleAnalyzer(provider)
        before = analyzer.analyze_deck(DeckSpec(((1, 1),), (), ()), request())
        after = analyzer.analyze_deck(DeckSpec(((1, 2),), (), ()), request())
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(before.functions, after.functions)
        self.assertNotEqual(snapshots[0]['effects'][0]['count_limits'], snapshots[1]['effects'][0]['count_limits'])

    def test_inventory_resources_and_shared_consumption_are_recomputed(self):
        demand = ConditionGroup('all', (Condition('card', 'card:1', deck_section='main'),
                                       Condition('card', 'card:1', deck_section='main')))
        defined = replace(contract(), dependencies=(), requirements=demand)
        def provider(deck, context, unit):
            count = dict(deck.main).get(1, 0)
            return AnalysisFacts(unit_contracts=(defined,), resources=(Resource('card', 'card:1', count,
                resource_id='actual:1', pool_id='actual:1', capacity=count, deck_section='main'),))
        context = request(rules=AnalysisContext(public_resources=()), resource_coverage=True)
        result = RoleAnalyzer(provider).compare_copy_change(DeckSpec(((1, 2),), (), ()), None,
            CopyChange(1, 'main'), ('draw',), context)
        self.assertEqual(result.before.requirement_assessment[0]['structural_status'], 'complete')
        self.assertNotEqual(result.after.requirement_assessment[0]['structural_status'], 'complete')
        self.assertIs(result.after.requirement_assessment[0]['branches'][0]['requirement_assessment']['satisfied'], False)

    def test_copy_capability_is_used_only_for_explicit_pairs_and_functions(self):
        scorer = Mock()
        def compare(left, right, *, operation):
            self.assertEqual(operation['kind'], 'replacement')
            self.assertEqual(left.input.unit_definition.function_id, right.input.unit_definition.function_id)
            raw = dict(task='copy_preference', subject=['query:unit', 'query:unit'], coordinate='preference',
                       value={'left': .1, 'equal': .1, 'right': .8})
            return dict(raw_prediction=(raw,), calibrated_scores=(raw,), applied_prediction=(dict(raw, value='right'),))
        scorer.score_copy_graphs.side_effect = compare
        analyzer = RoleAnalyzer(facts, scorer=scorer, capabilities={'copy_preference': published()})
        deck = DeckSpec(((1, 1), (2, 1)), (), ())
        args = (deck, CopyChange(1, 'main'), CopyChange(2, 'main'))
        pair = analyzer.compare_copy_change(*args, ('draw',), request(mode='assist'))
        self.assertEqual(pair.preference.value, 'right')
        self.assertEqual(json.loads(json.dumps(pair.to_dict()))['preference']['value'], 'right')
        scorer.score_graph.assert_not_called()
        multi = analyzer.compare_copy_change(*args, ('draw', 'search'), request(mode='assist'))
        self.assertEqual(multi.preference.status, 'unknown')
        self.assertEqual(len(multi.differences['function_preferences']), 2)
        prior_calls = scorer.score_copy_graphs.call_count
        analyzer.compare_copy_change(*args, ('draw',), request())
        analyzer.compare_copy_change(deck, CopyChange(1, 'main'), None, ('draw',), request(mode='assist'))
        self.assertEqual(scorer.score_copy_graphs.call_count, prior_calls)

    def test_request_roundtrip_keeps_rules_sampling_and_external_scope(self):
        deck = DeckSpec(((1, 1),), (), ())
        context = request(sampling=SamplingSpec('main', 1))
        external = ExternalLegality('pass', deck, context.context_ref, 'external', 'v1', ('scope',),
                                    context.rules, context.declared_goal)
        context = replace(context, external_legality=external)
        self.assertEqual(AnalysisRequestContext.from_dict(context.to_dict()), context)

    def test_service_cli_dispatch_uses_facts_without_constructing_a_trainer(self):
        from ygo_kito.multifactor.__main__ import service_request
        payload = dict(schema_version='axis-service-request-v3', context=request().to_dict(), facts={},
                       deck=DeckSpec(((1, 1),), (), ()).to_dict())
        result = service_request(payload, 'analyze_deck')
        self.assertEqual(result['legality']['status'], 'unknown')
        self.assertFalse(result['training_started'])
        self.assertEqual(result['raw_prediction'], ())

    def test_candidate_scorer_streams_all_queries_beyond_first_block(self):
        import torch
        from ygo_kito.multifactor import Factors, RoleInput, build_analysis_graph
        from ygo_kito.multifactor.network import NetworkConfig
        from ygo_kito.multifactor.scoring import CandidateScorer
        from ygo_kito.multifactor.training import RoleTrainer
        from ygo_kito.multifactor.task_queries import iter_queries, query_domain
        example = RoleInput('goal', Factors('context'), (), analysis_mode='deck_analysis',
            analysis_context=AnalysisContext(), deck=DeckSpec(((1, 1), (2, 1)), (), ()))
        build = build_analysis_graph(example, function_seeds=tuple(FunctionSeed('scope:' + str(i),
            (('card:1', 1), ('card:2', 1)), ('draw',)) for i in range(40)))
        trainer = RoleTrainer(NetworkConfig.v3(hidden_dim=8))
        trainer.updates['axis_function']['human_feedback'] = 1  # Synthetic status fixture only.
        count = len(list(iter_queries(query_domain(example, build.graph, build.candidates.to_dict()), 'axis_function')))
        self.assertGreater(count, 32)
        blocks = []
        def scores(output, batch, queries):
            blocks.append(len(queries))
            return [torch.tensor(0.) for _ in queries]
        with patch('ygo_kito.multifactor.scoring.encode_batch', return_value={}), \
             patch.object(trainer.model, 'forward', return_value={}), \
             patch.object(trainer.model, 'score_queries', side_effect=scores):
            result = CandidateScorer(trainer).score_graph(build, task='axis_function')
        self.assertEqual(len(result['raw_prediction']), count)
        self.assertEqual(sum(blocks), count)
        self.assertTrue(all(size <= 32 for size in blocks))
        self.assertTrue(trainer.model.training)
        self.assertEqual(result['applied_prediction'], ())

    def test_candidate_scorer_query_budget_rejects_before_forward(self):
        from ygo_kito.multifactor import Factors, RoleInput, build_analysis_graph
        from ygo_kito.multifactor.network import NetworkConfig
        from ygo_kito.multifactor.scoring import CandidateScorer
        from ygo_kito.multifactor.training import RoleTrainer
        example = RoleInput('goal', Factors('context'), (), analysis_mode='deck_analysis',
            analysis_context=AnalysisContext(), deck=DeckSpec(((1, 1),), (), ()))
        build = build_analysis_graph(example)
        trainer = RoleTrainer(NetworkConfig.v3(hidden_dim=8))
        trainer.updates['mechanism']['human_feedback'] = 1
        with patch.object(trainer.model, 'forward', side_effect=AssertionError('budget overflow must precede inference')) as forward:
            with self.assertRaises(FactorContractError):
                CandidateScorer(trainer).score_graph(build, task='mechanism', query_budget=1)
            forward.assert_not_called()


if __name__ == '__main__':
    unittest.main()
