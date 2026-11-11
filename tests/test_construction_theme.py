"""Automatic task-goal weighting through real static construction entry points."""
from copy import deepcopy
from dataclasses import replace
from math import log2
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.construction_fill import fill_with_existing
from ygo_kito.construction_layer_flow import ConstructionLayerAdapter, normalize_function_uses
from ygo_kito.construction_layers import LayerContext
from ygo_kito.construction_progress import host_construction_quality
from ygo_kito.construction_quality import evaluate_functional_quality, support_state, functional_quality_config
from ygo_kito.construction_relations import RelationContext, RelationFact, Resource
from ygo_kito.construction_theme import PRIMARY, SECONDARY
from ygo_kito.validation import ContractError
from tests.test_construction_functional_flow import fixture
from tests.test_construction_layer_flow import rows_for, session_for


LIMIT = '这个卡名的①效果1回合只能使用1次。①：'
PHASE = '自己主要阶段才能发动。'


def theme_fixture(kind='summon'):
    task, assets, graph, binder, decks, _ = fixture()
    for row in assets.rows.values():
        row.update(type=17, setcode=0, desc='Normal text')
    assets.rows[2].update(name='主题通常怪兽', setcode=0x515)
    assets.rows[3].update(name='接收效果', type=33, setcode=0x515)
    assets.rows[4]['name'] = '配合资源'
    assets.rows[1]['type'] = 33
    if kind == 'summon':
        assets.rows[1]['desc'] = LIMIT + PHASE + '从自己墓地把1张「接收效果」特殊召唤。'
        assets.rows[3]['desc'] = LIMIT + '这张卡特殊召唤成功的场合才能发动。抽1张。'
    elif kind == 'grave':
        assets.rows[1]['desc'] = LIMIT + PHASE + '从卡组上面把2张卡送去墓地。'
        assets.rows[3]['desc'] = LIMIT + '这张卡被效果送去墓地的场合才能发动。抽1张。'
    elif kind == 'banished':
        assets.rows[1]['desc'] = LIMIT + PHASE + '从自己墓地把1张「配合资源」卡除外。'
        assets.rows[3]['desc'] = LIMIT + PHASE + '从自己除外状态把1张「配合资源」卡加入手卡。'
    else:
        raise AssertionError(kind)
    raw = task.to_dict()
    raw['goal']['constraints'].append(dict(id='selected-theme', zones=['main', 'extra'],
        predicate=dict(field='setcode', value=0x515), minimum=1, maximum=40))
    task = BuildTask.from_dict(raw)
    phases = tuple(RelationFact('phase:' + str(code), 'phase:' + str(code),
        Resource('activation', event='own_main_phase', reason='not_applicable', attributes=('card:' + str(code),)),
        'host observation: own Main Phase') for code in (1, 3))
    relations = RelationContext((), phases)
    return task, assets, graph, binder, decks, relations


def evaluate(fixture_, deck=None, *, policy=None, relations=None):
    task, _, graph, binder, decks, default_relations = fixture_
    deck = deck or decks[0]
    policy = policy or host_construction_quality(task, catalog=binder.semantic_catalog)[0]
    facts = normalize_function_uses(task, deck, binder.semantic_catalog, policy=policy,
        context=SimpleNamespace(relations=relations or default_relations))
    layers = dict(axis=dict(task=task.to_dict(), inventory=deck.to_dict(), logic=graph.to_dict()))
    quality = evaluate_functional_quality(layers, policy=policy, facts=facts)
    return policy, facts, quality


def card_use(facts, card):
    return next(u for u in facts['uses'] if u.contributes and facts['use_details'][u.use_id]['card_id'] == card)


def static_cycle(test, f, session, **options):
    from dataclasses import asdict
    from ygo_kito.construction_fill import construction_cycle, FillProposal, NodeBinding
    from ygo_kito.construction_logic import ConstructionLogic
    task, assets, graph, binder, decks, relations = f
    def provider(context):
        old = ConstructionLogic.from_dict(context['logic'])
        return dict(logic=replace(graph, revision=old.revision + 1, parent_sha256=old.sha256).to_dict(),
            reason='static graph provider; no model invocation')
    def skeleton(s, *_args, **_kwargs):
        deck = DeckParts((1,))
        proposal = FillProposal(deck, (NodeBinding('goal', (1,)),), (), s.logic.sha256, task.sha256)
        return dict(status='axis_skeleton_ready', best_deck=deck.to_dict(), concrete_proposal=asdict(proposal),
            unfilled=dict(main=39, extra=0, side=0))
    adapter = ConstructionLayerAdapter(binder, context_provider=lambda t, g: LayerContext(t, g, (), relations=relations))
    options.setdefault('seconds', 30)
    options.setdefault('run_mode', 'slice')
    with patch('ygo_kito.construction_fill.build_axis_skeleton', side_effect=skeleton), \
         patch('ygo_kito.build_pipeline._goal_candidates', return_value=decks), \
         patch('ygo_kito.build_pipeline.edit_candidates', return_value=rows_for(task, decks)), \
         patch('ygo_kito.construction_candidates.portfolio', return_value=rows_for(task, decks)):
        return construction_cycle(session, assets, {r:provider for r in ('build_goal', 'build_optimizer')},
            binding_provider=binder, text_reviewer=binder.reviewer, layer_adapter=adapter, verifier=None,
            basic_cb_provider=lambda *_a, **_k: test.fail('CB forbidden'), **options)


class AutomaticThemeTests(unittest.TestCase):
    def test_default_inference_uses_percentages_for_two_non_grave_mechanisms(self):
        for kind in ('summon', 'banished'):
            with self.subTest(kind=kind):
                f = theme_fixture(kind)
                p, facts, q = evaluate(f)
                self.assertEqual(p['quality']['theme_profile']['status'], 'evaluated')
                self.assertEqual([(r['percentage'], r['increment']) for r in p['quality']['theme_rules']], [(100, 1), (50, .5)])
                self.assertEqual(card_use(facts, 3).theme_eligible, (PRIMARY,))
                self.assertEqual(card_use(facts, 1).theme_eligible, (SECONDARY,))
                self.assertIs(support_state(dict(card_use(facts, 1).theme_conditions)[SECONDARY], facts['variables']), True)
                self.assertIs(support_state(dict(card_use(facts, 1).theme_joint_conditions)[SECONDARY], facts['variables']), True)
                self.assertTrue(q['complete'], (q['unknowns'], q['deferred'], q['coverage']))
                expected = 1.5 + 2 * log2(1 + 1 + .9 * 2)
                self.assertAlmostEqual(q['score']['value'], expected)

    def test_random_mill_proves_available_cooperation_without_claiming_a_specific_call(self):
        f = theme_fixture('grave')
        _, facts, q = evaluate(f)
        source, receiver = card_use(facts, 1), card_use(facts, 3)
        self.assertIs(support_state(dict(source.theme_conditions)[SECONDARY], facts['variables']), True)
        self.assertIs(support_state(dict(source.theme_joint_conditions)[SECONDARY], facts['variables']), True)
        self.assertIs(facts['use_details'][source.use_id]['operation']['random'], True)
        self.assertIs(support_state(receiver.self_condition, facts['variables']), True)
        self.assertEqual(receiver.valuation_mode, 'main_density')
        self.assertNotIn('called_by', facts['use_details'][receiver.use_id])
        self.assertTrue(q['complete'], q['unknowns'])
        self.assertAlmostEqual(q['score']['value'], 1.5 + 2 * log2(1 + 1 + .9 * 2))

    def test_removing_actual_counterpart_withdraws_only_its_preparation_bonus(self):
        f = theme_fixture('grave')
        p, facts, _ = evaluate(f)
        deck = replace(f[4][0], main=tuple(2 if c == 3 else c for c in f[4][0].main))
        _, removed, q = evaluate(f, deck, policy=p)
        self.assertEqual(card_use(removed, 1).theme_eligible, ())
        self.assertIs(card_use(removed, 1).self_condition, True)
        self.assertAlmostEqual(q['score']['value'], 1)
        self.assertEqual(p, host_construction_quality(f[0], catalog=f[3].semantic_catalog)[0])

    def test_explicit_function_goal_changes_roles_without_changing_formula(self):
        f = theme_fixture('banished')
        ordinary, _, _ = evaluate(f)
        explicit, _ = host_construction_quality(f[0], catalog=f[3].semantic_catalog,
            goal_tags=[dict(dimension='effect_type', value='banish')])
        _, facts, q = evaluate(f, policy=explicit)
        self.assertTrue(explicit['quality']['theme_profile']['explicit_goals'])
        self.assertNotEqual(digest(ordinary), digest(explicit))
        self.assertEqual(card_use(facts, 1).theme_eligible, (PRIMARY,))
        self.assertEqual(card_use(facts, 3).theme_eligible, ())
        self.assertAlmostEqual(q['score']['value'], 2 + log2(3.8))
        invalid = deepcopy(explicit)
        invalid['quality']['theme_rules'][0]['percentage'] = 200
        with self.assertRaises(ContractError):
            functional_quality_config(invalid['quality'])

    def test_missing_theme_input_is_unknown_and_explicitly_ordinary_task_is_empty(self):
        f = theme_fixture()
        p, _ = host_construction_quality(f[0], theme_id='unresolved-theme')
        self.assertEqual(p['quality']['theme_profile']['status'], 'unknown')
        self.assertIn('fixed_card_effects_required', p['quality']['theme_profile']['gaps'])
        _, _, q = evaluate(f, policy=p)
        self.assertIn('functions', q['deferred'])
        self.assertIsNone(q['score']['upper'])
        task, _, _, binder, _, _ = fixture()
        p, _ = host_construction_quality(task, catalog=binder.semantic_catalog)
        self.assertEqual(p['quality']['theme_rules'], [])
        self.assertEqual(p['quality']['theme_profile']['status'], 'not_applicable')

    def test_default_fill_uses_automatic_rules_and_strict_final_quality_order(self):
        f = theme_fixture('summon')
        task, assets, graph, binder, decks, relations = f
        context = LayerContext(task, graph, (), relations=relations)
        adapter = ConstructionLayerAdapter(binder, context_provider=lambda *_: context)
        candidates = [decks[2], decks[0]]
        with patch('ygo_kito.build_pipeline.edit_candidates', return_value=rows_for(task, candidates)):
            result = fill_with_existing(session_for(task, graph), assets, role='build_optimizer', base=candidates[0],
                binding_provider=binder, text_reviewer=binder.reviewer, verifier=None, defer_engine=True,
                layer_adapter=adapter)
        self.assertEqual(result['best_deck'], decks[0].to_dict())
        self.assertTrue(result['quality_evaluation']['complete'])
        self.assertTrue(result['quality_evaluation']['theme_profile']['goals'])
        self.assertTrue(any(r['status'] == 'preferred' for r in result['quality_comparisons']))
        self.assertEqual(len(result['learning_candidates']), 2)
        from ygo_kito.construction_learning import candidate_pairs, validate_pair
        pairs = candidate_pairs(task, result['learning_candidates'])
        self.assertEqual(len(pairs), 1)
        validate_pair(task, pairs[0])
        self.assertEqual(pairs[0]['better'], decks[0].to_dict())

    def test_full_payment_and_joint_contention_withdraw_secondary_bonus_at_the_right_stage(self):
        from ygo_kito.construction_relations import ResourcePool
        f = theme_fixture('banished')
        for code in (1, 3):
            f[1].rows[code]['desc'] = f[1].rows[code]['desc'].replace(PHASE,
                '自己主要阶段，支付2000基本分才能发动。')
        payment = RelationFact('LP', 'LP', Resource('payment', reason='cost', attributes=('支付2000基本分',)),
            'host observation: payable LP', quantity=2000, output_pool='LP-pool')
        relations = replace(f[5], facts=(*f[5].facts, payment),
            pools=(ResourcePool('LP-pool', 'actual payable LP', capacity=4000),))
        p, facts, full = evaluate(f, relations=relations)
        self.assertTrue(full['complete'])
        self.assertIs(dict(card_use(facts, 1).theme_joint_conditions)[SECONDARY], True)
        shared = replace(relations, pools=(replace(relations.pools[0], capacity=2000),))
        _, facts, contended = evaluate(f, policy=p, relations=shared)
        self.assertTrue(all(u.self_condition is True for u in facts['uses'] if u.contributes))
        self.assertIs(dict(card_use(facts, 1).theme_conditions)[SECONDARY], True)
        self.assertIs(dict(card_use(facts, 1).theme_joint_conditions)[SECONDARY], False)
        self.assertAlmostEqual(full['score']['value'] - contended['score']['value'], .5)
        self.assertAlmostEqual(contended['losses'][0]['upper'], 0)
        self.assertAlmostEqual(contended['losses'][1]['upper'], .5)
        short = replace(relations, pools=(replace(relations.pools[0], capacity=1999),))
        _, facts, impossible = evaluate(f, policy=p, relations=short)
        self.assertTrue(all(u.self_condition is False for u in facts['uses'] if u.contributes))
        self.assertEqual(impossible['score']['value'], 0)

    def test_reason_owner_selector_and_incomplete_text_do_not_create_false_cooperation(self):
        for change in ('reason', 'owner', 'selector', 'suffix'):
            with self.subTest(change=change):
                f = theme_fixture('grave' if change in ('reason', 'owner') else 'banished')
                if change == 'reason':
                    # The moved resource is a cost, not a resolving effect.
                    f[1].rows[1]['desc'] = LIMIT + '自己主要阶段，从卡组上面把2张卡送去墓地才能发动。抽1张。'
                elif change == 'owner':
                    f[1].rows[1]['desc'] = LIMIT + PHASE + '从对方卡组上面把2张卡送去墓地。'
                elif change == 'selector':
                    f[1].rows[1]['desc'] = f[1].rows[1]['desc'].replace('「配合资源」', '「不相符的资源」')
                else:
                    f[1].rows[1]['desc'] = f[1].rows[1]['desc'].replace('除外。', '除外。那之后，满足未知条件时才能适用。')
                p, facts, q = evaluate(f)
                if change == 'suffix':
                    source = card_use(facts, 1)
                    self.assertIsNone(support_state(source.self_condition, facts['variables']))
                    self.assertIsNone(q['score']['value'])
                else:
                    self.assertEqual(p['quality']['theme_profile']['status'], 'unknown')
                    self.assertNotIn(SECONDARY, card_use(facts, 1).theme_eligible)

    def test_primary_precedence_and_duplicate_counterparts_never_stack_bonuses(self):
        f = theme_fixture('banished')
        f[1].rows[1]['desc'] = LIMIT + PHASE + '从自己除外状态把1张「配合资源」卡送去墓地。'
        f[1].rows[3]['desc'] = LIMIT + PHASE + '从自己墓地把1张「配合资源」卡除外。'
        _, facts, q = evaluate(f)
        self.assertEqual(len(q['theme_profile']['goals']), 2)
        self.assertTrue(all(u.theme_eligible == (PRIMARY,) for u in facts['uses'] if u.contributes))
        self.assertAlmostEqual(q['score']['value'], 2 + 2 * log2(3.8))
        f = theme_fixture('grave')
        f[1].rows[5].update(type=33, desc=f[1].rows[3]['desc'])
        _, facts, _ = evaluate(f)
        source = card_use(facts, 1)
        self.assertEqual(len(facts['theme_witnesses'][source.use_id]), 2)
        self.assertEqual(source.theme_eligible, (SECONDARY,))
        self.assertEqual(len(dict(source.theme_conditions)), 1)

    def test_unused_optional_lock_does_not_block_and_adopted_lock_withdraws_counterpart_bonus(self):
        from ygo_kito.construction_relations import InputGroup, Need, UseRequirement
        f = theme_fixture('grave')
        f[1].rows[5].update(type=33, desc='①：这张卡在怪兽区域存在，自己不能抽卡。')
        state = RelationFact('field', 'field', Resource('effect_applicability', zone='field',
            attributes=('card:5', 'controller:self', 'state:monster_zone')), 'host: present in own monster zone')
        relations = replace(f[5], facts=(*f[5].facts, state))
        p, facts, optional = evaluate(f, relations=relations)
        self.assertGreater(optional['score']['upper'], 1.5)
        adoption = next(u for u in facts['uses'] if not u.contributes and facts['use_details'][u.use_id]['card_id'] == 5)
        required = UseRequirement('adopt', InputGroup('all', (Need('adopt-field',
            Resource('functional_operation', attributes=('catalog:5:1:adoption',)), mode='presence'),)),
            'original task adopts this field restriction', functional_use_ids=(adoption.use_id,))
        relations = replace(relations, uses=(required,))
        _, facts, blocked = evaluate(f, policy=p, relations=relations)
        self.assertEqual(blocked['score']['upper'], 1)
        loss = next(r for r in blocked['loss_records'] if r['channel_id'] == SECONDARY)
        self.assertIn('cannot_draw', loss['reason_codes'])

    def test_renaming_and_reidentifying_equivalent_cards_preserve_scores(self):
        original = theme_fixture('summon')
        expected = evaluate(original)[2]['score']
        f = list(theme_fixture('summon'))
        f[1].rows[1]['desc'] = f[1].rows[1]['desc'].replace('接收效果', '另一个名称')
        f[1].rows[3]['name'] = '另一个名称'
        self.assertEqual(evaluate(f)[2]['score'], expected)
        mapping = {c: c + 1000 for c in f[0].pool}
        f[1].rows = {mapping[c]: dict(row, id=mapping[c], alias=0) for c, row in f[1].rows.items()}
        raw = f[0].to_dict()
        raw['pool'] = [mapping[c] for c in raw['pool']]
        for row in raw['requirements']:
            row['card_id'] = mapping[row['card_id']]
        f[0] = BuildTask.from_dict(raw)
        from ygo_kito.construction_binding import CatalogBindingAdapter
        f[3] = CatalogBindingAdapter(f[1])
        f[4] = [DeckParts(tuple(mapping[c] for c in d.main)) for d in f[4]]
        f[5] = replace(f[5], facts=tuple(replace(row, output=replace(row.output,
            attributes=tuple('card:' + str(mapping[int(a.split(':')[1])]) if a.startswith('card:') else a
                for a in row.output.attributes))) for row in f[5].facts))
        self.assertEqual(evaluate(f)[2]['score'], expected)

    def test_changing_only_the_task_theme_reverses_the_preference(self):
        f = list(theme_fixture('summon'))
        f[1].rows[5].update(type=33, desc=LIMIT + PHASE + '从自己墓地把1张「配合资源」卡除外。')
        f[1].rows[6].update(type=33, setcode=0x616,
            desc=LIMIT + PHASE + '从自己除外状态把1张「配合资源」卡加入手卡。')
        f[1].rows[2]['setcode'] = 0x515 | (0x616 << 16)
        common = (1, 5, 2, 2, 2, 4, 4, 4) + tuple(c for c in range(7, 16) for _ in range(3))
        decks = [DeckParts(tuple(sorted(common + (3, 3, 3, 6, 6)))),
                 DeckParts(tuple(sorted(common + (3, 3, 6, 6, 6))))]
        extra_phases = tuple(RelationFact('phase:' + str(c), 'phase:' + str(c),
            Resource('activation', event='own_main_phase', reason='not_applicable', attributes=('card:' + str(c),)),
            'host own Main Phase') for c in (5, 6))
        f[5] = replace(f[5], facts=(*f[5].facts, *extra_phases))
        p, _, a = evaluate(f, decks[0])
        _, _, b = evaluate(f, decks[1], policy=p)
        self.assertGreater(a['score']['value'], b['score']['value'])
        raw = f[0].to_dict()
        raw['goal']['constraints'][-1]['predicate']['value'] = 0x616
        f[0] = BuildTask.from_dict(raw)
        p2, _, a2 = evaluate(f, decks[0])
        _, _, b2 = evaluate(f, decks[1], policy=p2)
        self.assertLess(a2['score']['value'], b2['score']['value'])
        self.assertNotEqual(p['quality']['theme_profile']['goals'], p2['quality']['theme_profile']['goals'])

    def test_stale_profile_is_rejected_and_kernel_policy_method_uses_actual_task_catalog(self):
        import ast
        from pathlib import Path
        f = theme_fixture('summon')
        p, _, _ = evaluate(f)
        f[1].rows[3]['desc'] = f[1].rows[3]['desc'].replace('抽1张', '抽2张')
        with self.assertRaisesRegex(ContractError, 'rederivation'):
            evaluate(f, policy=p)
        # Compile the real method alone: do not import/initialize model modules.
        tree = ast.parse(Path('src/ygo_kito/autonomous_construction.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AutonomousConstructionKernel')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'quality_for_task')
        namespace = {'deepcopy':deepcopy, '__name__':'ygo_kito._static_kernel_method', '__package__':'ygo_kito'}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), '<actual quality_for_task>', 'exec'), namespace)
        kernel = SimpleNamespace(source_binding=dict(period_id='2022-07', construction_theme_ids=['setcode-515']),
            mechanisms=f[3].semantic_catalog, selections={'s':dict(task=f[0].to_dict(),
                theme=dict(theme_id='setcode-515', field='setcode', value=0x515))})
        actual, reference = namespace['quality_for_task'](kernel, f[0])
        self.assertIsNone(reference)
        self.assertEqual(actual['quality']['theme_profile']['status'], 'evaluated')
        self.assertTrue(actual['quality']['theme_profile']['goals'])
        from ygo_kito.construction_progress import specified_course_reference
        for period, ref in (('2022-07', 'main-01-source-v1'), ('2022-10', 'main-02-source-v2')):
            self.assertEqual(specified_course_reference(period, 'setcode-181'), ref)
            self.assertIsNone(specified_course_reference(period, 'setcode-515'))

    def test_resource_cost_is_a_real_mechanism_and_does_not_label_unrelated_draw_effects(self):
        from ygo_kito.construction_relations import ResourcePool
        f = theme_fixture('grave')
        payment = '从自己墓地把1张「配合资源」卡除外'
        f[1].rows[3]['desc'] = LIMIT + '自己主要阶段，' + payment + '才能发动。抽1张。'
        f[1].rows[5].update(type=33, desc=LIMIT + PHASE + '抽1张。')
        phases = RelationFact('phase:5', 'phase:5', Resource('activation', event='own_main_phase',
            reason='not_applicable', attributes=('card:5',)), 'host own Main Phase')
        paid = RelationFact('grave-payment', 'grave-payment', Resource('payment', reason='cost', attributes=(payment,)),
            'host observation: legal grave payment', output_pool='grave-cards')
        relations = replace(f[5], facts=(*f[5].facts, phases, paid),
            pools=(ResourcePool('grave-cards', 'actual payable grave cards', inventory=(('main', 4),)),))
        p, facts, q = evaluate(f, relations=relations)
        self.assertEqual(p['quality']['theme_profile']['status'], 'evaluated')
        self.assertEqual(card_use(facts, 3).theme_eligible, (PRIMARY,))
        self.assertEqual(card_use(facts, 5).theme_eligible, ())
        self.assertEqual(card_use(facts, 1).theme_eligible, (SECONDARY,))
        self.assertTrue(q['complete'])
        insufficient = replace(relations, pools=(ResourcePool('grave-cards', 'no payable grave card', capacity=0),))
        _, facts, failed = evaluate(f, policy=p, relations=insufficient)
        self.assertIs(dict(card_use(facts, 1).theme_conditions)[SECONDARY], False)
        self.assertIs(card_use(facts, 3).self_condition, False)
        self.assertAlmostEqual(failed['score']['value'], 1 + log2(3.8))

    def test_complete_recipient_quantity_is_required_without_deleting_the_source_function(self):
        f = theme_fixture('banished')
        f[1].rows[3]['desc'] = f[1].rows[3]['desc'].replace('把1张', '把2张')
        p, _, complete = evaluate(f)
        self.assertTrue(complete['complete'])
        cards = list(f[4][0].main)
        for _ in range(2):
            cards[cards.index(4)] = 2
        _, facts, short = evaluate(f, DeckParts(tuple(sorted(cards))), policy=p)
        self.assertIs(card_use(facts, 1).self_condition, True)
        self.assertIs(card_use(facts, 3).self_condition, False)
        self.assertIs(dict(card_use(facts, 1).theme_conditions)[SECONDARY], False)
        self.assertAlmostEqual(short['score']['value'], 1)

    def test_default_cycle_and_policy_revision_rebind_reference_and_preserve_progress(self):
        f = theme_fixture('summon')
        task, assets, graph, _, decks, _ = f
        session = session_for(task, graph)
        first = static_cycle(self, f, session, max_iterations=1)
        self.assertTrue(first['construction_passed'])
        self.assertTrue(first['best']['quality_evaluation']['theme_profile']['goals'])
        self.assertTrue(all(not p['parameter_update_performed'] for p in first['phases']))
        self.assertEqual(first['basic_cb']['status'], 'not_run')
        p = host_construction_quality(task, catalog=f[3].semantic_catalog)[0]
        descriptor = dict(reference_id='static-specified-reference', source='host static fixture',
            environment=deepcopy(task.environment), deck=decks[0].to_dict())
        p['pass'] = dict(mode='reference_ratio', minimum_reference_ratio=.8,
            reference={k:descriptor[k] for k in ('reference_id', 'source')})
        p['pass']['reference']['deck_sha256'] = digest(descriptor['deck'])
        bound = static_cycle(self, f, session, quality_criteria=p, quality_reference=descriptor, max_iterations=1)
        self.assertTrue(bound['construction_passed'])
        before = deepcopy(session.construction_progress)
        new = host_construction_quality(task, catalog=f[3].semantic_catalog,
            goal_tags=[dict(dimension='effect_type', value='special_summon')])[0]
        new['pass'] = deepcopy(p['pass'])
        static_cycle(self, f, session, quality_criteria=new, quality_reference=descriptor, max_iterations=0)
        revised = session.construction_progress
        self.assertEqual(revised['candidate']['deck'], before['candidate']['deck'])
        for key in ('iteration', 'candidate_cursor', 'skeleton', 'handoffs'):
            self.assertEqual(revised[key], before[key])
        self.assertEqual(revised['candidate']['evaluation_status'], 'stale')
        self.assertIsNone(revised['reference_evaluation'])
        self.assertEqual(revised['stale_reference_evaluation'], before['reference_evaluation'])
        self.assertNotEqual((revised.get('gate') or {}).get('status'), 'passed')
        final = static_cycle(self, f, session, quality_criteria=new, quality_reference=descriptor, max_iterations=1)
        self.assertTrue(final['construction_passed'])
        state = final['continuation']
        self.assertEqual(state['candidate']['quality_evaluation']['policy_sha256'], digest(new))
        self.assertEqual(state['reference_evaluation']['policy_sha256'], digest(new))
        self.assertNotEqual(state['reference_evaluation']['evaluation_id'], before['reference_evaluation']['evaluation_id'])
        self.assertLess(state['candidate']['quality_evaluation']['score']['value'], before['candidate']['quality_evaluation']['score']['value'])
        from ygo_kito.course_admission_policy import CourseAdmissionPolicy
        course = SimpleNamespace(construction=final, models=SimpleNamespace(kernel=SimpleNamespace(
            source_binding={'construction_quality_policy':new})))
        receipt = CourseAdmissionPolicy(course).record_completed_construction(task=task,
            deck=DeckParts.from_dict(final['best']['deck']), assets=assets, basic_cb=None, cycle_id='static-auto-theme')
        self.assertEqual(receipt['quality_evaluation']['policy_sha256'], digest(new))
        self.assertEqual(receipt['construction_gate']['status'], 'passed')

    def test_automatic_side_cooperation_requires_both_cards_to_fit_the_extra_deck(self):
        f = list(theme_fixture('summon'))
        for code in (1, 3):
            f[1].rows[code].update(type=17, setcode=0, desc='Normal text')
        for code in (101, 104):
            f[1].rows[code] = dict(f[1].rows[4], id=code, alias=0, type=0x41, name='额外通常卡' + str(code),
                desc='「配合资源」＋「主题通常怪兽」')
        f[1].rows[102] = dict(f[1].rows[1], id=102, alias=0, type=0x61, name='额外准备效果',
            desc=LIMIT + PHASE + '从自己额外卡组把1张「额外接收效果」特殊召唤。')
        f[1].rows[103] = dict(f[1].rows[3], id=103, alias=0, type=0x61, setcode=0x515, name='额外接收效果',
            desc=LIMIT + '这张卡特殊召唤成功的场合才能发动。抽1张。')
        f[5] = RelationContext((), (RelationFact('phase:102', 'phase:102', Resource('activation',
            event='own_main_phase', reason='not_applicable', attributes=('card:102',)), 'host own Main Phase'),))
        for size in (1, 2):
            with self.subTest(extra=size):
                raw = f[0].to_dict()
                raw['sizes'].update(extra=size, side=2)
                raw['pool'] = sorted(set(raw['pool']) | {101, 102, 103, 104})
                f[0] = BuildTask.from_dict(raw)
                deck = replace(f[4][0], main=tuple(2 if c == 3 else c for c in f[4][0].main),
                    extra=(101,) if size == 1 else (101, 104), side=(102, 103))
                f[1].validate(f[0], deck)
                _, facts, q = evaluate(f, deck)
                source = next(u for u in facts['uses'] if u.scope_id == 'going_first'
                    and facts['use_details'][u.use_id]['card_id'] == 102)
                joint = support_state(dict(source.theme_joint_conditions)[SECONDARY], facts['variables'])
                self.assertIs(joint, size == 2)
                if size == 1:
                    # The two-card cooperation cannot fit. The receiver's
                    # printed standalone capability needs no current board.
                    self.assertTrue(q['complete'])
                    self.assertEqual(q['score']['value'], 2)
                    self.assertFalse(q['unknowns'])
                else:
                    self.assertTrue(q['complete'])
                    self.assertAlmostEqual(q['score']['value'], 3.5)


if __name__ == '__main__':
    unittest.main()
