"""Finite static calculation resumes without labels or engine execution."""
from dataclasses import replace
import json
import unittest
from copy import deepcopy
from dataclasses import asdict
from unittest.mock import patch

from ygo_kito.construction_relations import (RelationBudget, RelationContext, evaluate_relations,
    relation_index)
from tests.test_construction_relations import fact, need, use, all_of
from tests.test_construction_layers import skeleton


def roundtrip(value):
    return json.loads(json.dumps(value))


class CalculationResumeTests(unittest.TestCase):
    def finish_allocations(self, context, deck):
        full = evaluate_relations(deck, context, relation_index(None, context), resumable=True).to_dict()
        self.assertNotIn('continuation', full)
        sliced = replace(context, budget=replace(context.budget, allocations=1))
        index, progress, work, updates = relation_index(None, sliced), None, 0, 0
        kinds = set()
        for _ in range(10000):
            result = evaluate_relations(deck, sliced, index, continuation=progress, resumable=True).to_dict()
            work += result['work']['allocation_states']
            updates += result['work']['updates']
            self.assertEqual(result['work']['total_allocation_states'], work)
            if not result.get('continuation'):
                break
            progress = roundtrip(result['continuation'])
            active = progress.get('active')
            if active:
                kinds.add(active['kind'])
                if active['kind'] == 'fact':
                    self.assertEqual(active['identity'], progress['queue'][0])
        else:
            self.fail('finite local allocation did not finish')
        self.assertEqual(roundtrip(result['uses']), roundtrip(full['uses']))
        self.assertEqual(roundtrip(result['joint_groups']), roundtrip(full['joint_groups']))
        self.assertEqual(work, full['work']['allocation_states'])
        self.assertEqual(updates, full['work']['updates'])
        return result, kinds

    def test_relation_all_129_witnesses_survive_json_and_single_state_slices(self):
        from ygo_kito.construction_relations import Resource
        context = RelationContext((use('target', need('supply')),),
            tuple(fact(f'fact-{i:03d}', None, output=Resource('supply')) for i in range(129)))
        result, kinds = self.finish_allocations(context, skeleton((1,)))
        self.assertEqual(len(result['uses']['target']['allocation_witnesses']), 129)
        self.assertIn('use', kinds)
        self.assertIn('joint', kinds)

    def test_fact_keeps_its_queue_position_until_local_alternatives_finish(self):
        from ygo_kito.construction_relations import Resource
        context = RelationContext((use('target', need('end')),), (
            *(fact(f'base-{i}', None, output=Resource('base')) for i in range(3)),
            fact('end', None, inputs=all_of(need('base')))))
        result, kinds = self.finish_allocations(context, skeleton((1,)))
        self.assertIn('fact', kinds)
        self.assertEqual(result['uses']['target']['status'], 'supported')

    def test_partial_supplier_quantity_cursor_keeps_next_amount_and_child_results(self):
        from ygo_kito.construction_relations import Resource, _partial_allocations
        partial = {f'pool-{i}': [(2, {}, f'fact-{i}')] for i in range(3)}
        expected, exhausted = _partial_allocations(partial, 3, 100000)
        self.assertFalse(exhausted)
        state = {}
        for _ in range(1000):
            value, exhausted = _partial_allocations(partial, 3, 1, work_state=state)
            if not exhausted:
                break
            state = roundtrip(state)
        else:
            self.fail('quantity allocation did not finish')
        self.assertEqual(roundtrip(value), roundtrip(expected))
        context = RelationContext((use('target', need('base', quantity=3)),), tuple(
            fact(f'base-{i}', None, output=Resource('base'), quantity=2, conditions=(f'access-{i}',))
            for i in range(3)))
        result, _ = self.finish_allocations(context, skeleton((1,)))
        self.assertEqual(result['uses']['target']['status'], 'supported')

    def test_recovery_quantity_identity_and_shared_inventory_resume_together(self):
        from ygo_kito.construction_relations import Resource, Need, ResourcePool, ResourceTransfer, PoolRecovery
        deck_resource, hand_resource = Resource('x', zone='deck'), Resource('x', zone='hand')
        transfer = ResourceTransfer('return actual consumed card', 'grave', 'hand', 'self', 'self',
            'targeted', (('main', 1),), 'effect')
        context = RelationContext((use('target', Need('first', deck_resource, destination='grave'),
            Need('second', hand_resource)),), (
            fact('deck', None, output=deck_resource, output_pool='stock'),
            fact('hand', None, output=hand_resource, output_pool='stock'),
            fact('return', 2, transfer=transfer)), (
            ResourcePool('stock', 'one actual card', inventory=(('main', 1),),
                recoveries=(PoolRecovery('return', 'first', 'second'),)),))
        result, _ = self.finish_allocations(context, skeleton((1, 2)))
        self.assertEqual(result['uses']['target']['status'], 'supported')
        witnesses = result['uses']['target']['branches']
        self.assertTrue(any(row.get('transfer_states') for row in witnesses))

    def test_cyclic_physical_support_with_single_state_json_slices(self):
        from ygo_kito.construction_relations import InputGroup, ResourcePool
        context = RelationContext((use('end', need('b', mode='presence')),), (
            fact('stock', 1, output_pool='physical'),
            fact('a', None, inputs=InputGroup('any', (need('stock', mode='presence'), need('b', mode='presence')))),
            fact('b', None, inputs=all_of(need('a', mode='presence')))), (
            ResourcePool('physical', 'one anonymous physical card', inventory=(('main', 1),)),))
        result, _ = self.finish_allocations(context, skeleton((1,)))
        self.assertEqual(result['uses']['end']['status'], 'supported')

    def test_zero_allocation_slice_returns_pending_with_a_live_stop_callback(self):
        from ygo_kito.construction_layer_flow import normalize_function_uses
        from tests.test_construction_functional_flow import fixture
        task, _assets, _graph, binder, decks, policy = fixture()
        value = normalize_function_uses(task, decks[-1], binder.semantic_catalog, policy=policy,
            budget=RelationBudget(allocations=0), should_stop=lambda: None)
        self.assertTrue(value.get('calculation_pending'))

    def test_f04_all_129_single_supplier_allocations_are_enumerated(self):
        from ygo_kito.construction_relations import _partial_allocations
        partial = {f'pool-{i:03d}': [(1, {}, f'fact-{i:03d}')] for i in range(129)}
        allocations, exhausted = _partial_allocations(partial, 1, 100000)
        self.assertFalse(exhausted)
        self.assertEqual(len(allocations), 129)
        self.assertEqual(len({a[0][0] for a in allocations}), 129)

    def test_complete_resource_alternatives_survive_a_truncated_summary(self):
        from ygo_kito.construction_layer_flow import _relation_support
        from ygo_kito.construction_quality import support_state
        facts={};reasons=[]
        def condition(key,value,reason,evidence):
            facts[key]=value;reasons.append(reason);return key
        row=dict(status='unknown',support_expression=('unresolved',()),branches_incomplete=False,
            branches=[dict(support_expression=('all',(('atom','first'),('atom','fee')))),
                      dict(support_expression=('atom','alternative'))])
        expression=_relation_support(row,'fixture','resident',condition,('source',))
        self.assertEqual(set(reasons),{'first','fee','alternative'})
        self.assertIsNone(support_state(expression,facts))
        self.assertTrue(support_state(expression,{key:key.endswith(':alternative') for key in facts}))
        self.assertFalse(support_state(expression,{key:False for key in facts}))
        row['branches_incomplete']=True
        _relation_support(row,'incomplete','resident',condition,('source',))
        self.assertEqual(reasons[-1],'relation_expression_budget')

    def test_common_conditions_are_factored_without_changing_truth(self):
        from itertools import product
        from ygo_kito.construction_relations import _expression
        atoms=[('atom',name) for name in ('a','b','c')]
        expression=_expression('any',[('all',(atoms[0],atoms[1])),('all',(atoms[0],atoms[2]))])
        def value(expr,truth):
            return truth[expr[1]] if expr[0]=='atom' else (all if expr[0]=='all' else any)(value(v,truth) for v in expr[1])
        for bits in product((False,True),repeat=3):
            truth=dict(zip(('a','b','c'),bits))
            self.assertEqual(value(expression,truth),bits[0] and (bits[1] or bits[2]))
        a,b,c=atoms;d=('atom','d')
        grouped=_expression('any',[('all',(a,b)),('all',(a,c)),('all',(b,d))])
        for bits in product((False,True),repeat=4):
            self.assertEqual(value(grouped,dict(zip(('a','b','c','d'),bits))),
                (bits[0] and bits[1]) or (bits[0] and bits[2]) or (bits[1] and bits[3]))
        shared=('atom','root')
        for i in range(20):
            shared=_expression('any',[('all',(shared,('atom',f'a{i}'))),('all',(shared,('atom',f'b{i}')))])
            self.assertNotEqual(shared[0],'unresolved')

    def chain(self):
        facts=tuple(fact(str(i),None,inputs=all_of(need(str(i-1))) if i else None) for i in range(8))
        return RelationContext((use('end',need('7')),),facts)

    def test_matching_cursor_json_does_not_repeat_completed_pairs(self):
        ctx=self.chain()
        full=relation_index(None,ctx)
        sliced=replace(ctx,budget=replace(ctx.budget,matches=1))
        progress=None
        checks=[]
        for _ in range(40):
            index=relation_index(None,sliced,continuation=progress)
            checks.append(index.matched_state['checks'])
            if index.continuation is None:break
            progress=roundtrip(index.continuation)
        else:self.fail('finite matching did not finish')
        self.assertEqual(index.matches,full.matches)
        self.assertEqual(index.matched_state['checks'],full.matched_state['checks'])
        self.assertEqual(checks,list(range(1,full.matched_state['checks']+1)))

    def test_update_queue_json_reuses_finished_states(self):
        ctx=self.chain();deck=skeleton((1,))
        full=evaluate_relations(deck,ctx,relation_index(None,ctx)).to_dict()
        sliced=replace(ctx,budget=replace(ctx.budget,updates=1))
        index=relation_index(None,sliced);progress=None;updates=0
        for _ in range(80):
            result=evaluate_relations(deck,sliced,index,continuation=progress,resumable=True).to_dict()
            updates+=result['work']['updates']
            if not result.get('continuation'):break
            progress=roundtrip(result['continuation'])
        else:self.fail('finite update queue did not finish')
        self.assertEqual(result['uses'],full['uses'])
        self.assertEqual(result['joint_required'],full['joint_required'])
        self.assertEqual(updates,full['work']['updates'])

    def test_physical_allocation_json_does_not_requeue_unchanged_cycle(self):
        from ygo_kito.construction_relations import InputGroup, ResourcePool
        ctx=RelationContext((use('end',need('b',mode='presence')),),(
            fact('stock',1,output_pool='physical'),
            fact('a',None,inputs=InputGroup('any',(need('stock',mode='presence'),need('b',mode='presence')))),
            fact('b',None,inputs=all_of(need('a',mode='presence')))),
            (ResourcePool('physical','one anonymous physical card',inventory=(('main',1),)),))
        deck=skeleton((1,))
        full=evaluate_relations(deck,ctx,relation_index(None,ctx)).to_dict()
        self.assertFalse(full['budget']['update_exhausted'])
        sliced=replace(ctx,budget=replace(ctx.budget,updates=1))
        index=relation_index(None,sliced);progress=None;updates=0
        for _ in range(full['work']['updates']+1):
            result=evaluate_relations(deck,sliced,index,continuation=progress,resumable=True).to_dict()
            updates+=result['work']['updates']
            if not result.get('continuation'):break
            progress=roundtrip(result['continuation'])
        else:self.fail('JSON representation changes requeued an unchanged physical allocation')
        self.assertEqual(roundtrip(result['uses']),roundtrip(full['uses']))
        self.assertEqual(roundtrip(result['joint_required']),roundtrip(full['joint_required']))
        self.assertEqual(updates,full['work']['updates'])

    def test_candidate_calculation_json_finishes_before_evaluation_is_cached(self):
        from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
        from tests.test_construction_functional_flow import fixture
        task,assets,graph,binder,decks,policy=fixture()
        deck=decks[-1];rows=[{'deck':deck}];proposals={0:binder(graph,task,deck)}
        adapter=ConstructionLayerAdapter(binder)
        _,expected,_=adapter.evaluate(task,graph,rows,proposals,[0],policy=policy)
        sliced=ConstructionLayerAdapter(binder,budget=RelationBudget(cards=1,facts=1,matches=1,updates=1))
        calculations=None
        seen=[]
        for _ in range(100):
            _,values,trace=sliced.evaluate(task,graph,rows,proposals,[0],policy=policy,calculations=calculations)
            if trace['selection_complete']:break
            self.assertEqual(values,{})
            work=trace['calculation_progress']['0']
            seen.append(work['read_cursor'])
            calculations={int(i):v for i,v in roundtrip(trace['calculation_progress']).items()}
        else:self.fail('finite candidate calculation did not finish')
        self.assertEqual(seen,sorted(seen))
        self.assertEqual(values[0]['quality_evaluation']['score'],expected[0]['quality_evaluation']['score'])
        self.assertEqual(values[0]['quality_evaluation']['unknowns'],expected[0]['quality_evaluation']['unknowns'])
        self.assertFalse(any('budget' in str(item) for item in values[0]['quality_evaluation']['unknowns']))

    def test_reference_resume_reuses_candidate_batch_and_optimizer_phase(self):
        from ygo_kito.build_contracts import DeckParts,digest
        from ygo_kito.construction_fill import construction_cycle,FillProposal,NodeBinding
        from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
        from ygo_kito.construction_logic import ConstructionLogic
        from ygo_kito.construction_progress import restore_progress
        from ygo_kito.construction_quality import EvaluationComparisons, _delta, validate_evaluation
        from ygo_kito.construction_learning import cycle_pairs
        from tests.test_construction_functional_flow import fixture,reviewed
        from tests.test_construction_layer_flow import session_for,rows_for
        task,assets,graph,binder,decks,policy=fixture()
        task = replace(task, candidate_budget=12)
        reference_deck = decks[-1]
        candidates = list(decks)
        for code in (4, 5):
            for deck in decks:
                main = list(deck.main)
                main.remove(code)
                candidates.append(DeckParts(tuple(sorted([*main, 16]))))
        source='anonymous specified reference'
        policy['pass']=dict(mode='reference_ratio',minimum_reference_ratio=.8,
            reference=dict(reference_id='resume-reference',deck_sha256=digest(reference_deck.to_dict()),source=source))
        reference=dict(reference_id='resume-reference',source=source,environment=task.environment,deck=reference_deck.to_dict())
        roles, evaluated_candidates, pairs, checked = [], [], [], []
        target_pairs = 17
        def provider(ctx):
            roles.append(ctx['role']);old=ConstructionLogic.from_dict(ctx['logic'])
            return dict(logic=replace(graph,revision=old.revision+1,parent_sha256=old.sha256).to_dict(),reason='fixture')
        def skeleton_result(session,*_args,**_kwargs):
            deck=DeckParts((1,))
            proposal=FillProposal(deck,(NodeBinding('goal',(1,)),),(),session.logic.sha256,task.sha256)
            return dict(status='axis_skeleton_ready',best_deck=deck.to_dict(),concrete_proposal=asdict(proposal),
                unfilled=dict(main=39,extra=0,side=0))
        def compare(a,b,ratio):
            if a is not b and ratio == 1.:
                pairs.append((a.evaluation_id, b.evaluation_id))
            return _delta(a,b,ratio)
        def check(row):
            checked.append(row['evaluation_id'])
            return validate_evaluation(row)
        class SlicedReference(ConstructionLayerAdapter):
            def evaluate_inventory(self,task,deck,layer,context,**kwargs):
                if layer['axis']['logic'] is not None:
                    evaluated_candidates.append(deck)
                    return super().evaluate_inventory(task,deck,layer,context,**kwargs)
                original=self.budget
                try:
                    self.budget=RelationBudget(cards=6)
                    kwargs['should_stop']=None
                    return super().evaluate_inventory(task,deck,layer,context,**kwargs)
                finally:self.budget=original
        session=session_for(task,graph)
        options=dict(binding_provider=binder,text_reviewer=binder.reviewer,quality_criteria=policy,
            quality_reference=reference,quality_evidence=reviewed(binder.semantic_catalog,policy),
            layer_adapter=SlicedReference(binder),run_mode='slice',seconds=30.,max_iterations=1,
            basic_cb_provider=lambda *_a,**_k:self.fail('CB forbidden'), pause_requested=lambda:len(pairs)>=target_pairs)
        providers={key:provider for key in ('build_goal','build_optimizer')}
        def copied(obj):
            self.assertFalse(isinstance(obj,dict) and ('pending_quality' in obj and 'iteration' in obj
                or 'evaluation_id' in obj or 'quality_evaluation' in obj and 'layer_evaluation' in obj))
            return deepcopy(obj)
        with patch('ygo_kito.construction_fill.build_axis_skeleton',side_effect=skeleton_result), \
             patch('ygo_kito.build_pipeline._goal_candidates',return_value=candidates), \
             patch('ygo_kito.construction_candidates.portfolio',return_value=rows_for(task,candidates)), \
             patch('ygo_kito.construction_fill.deepcopy',side_effect=copied), \
             patch('ygo_kito.construction_quality.validate_evaluation',side_effect=check), \
             patch('ygo_kito.construction_quality._delta',side_effect=compare):
            result=construction_cycle(session,assets,providers,**options)
        self.assertEqual(len(checked),12)
        self.assertEqual(len(set(checked)),12)
        from ygo_kito.validation import ContractError
        tampered = roundtrip(result['continuation'])
        tampered['pending_quality']['comparison_progress']['pairs'][0]['delta_range'][0] = 123
        with self.assertRaisesRegex(ContractError, 'invalid saved candidate comparison progress'):
            restore_progress(session,tampered,assets)
        for completed, target_pairs in ((17, 34), (34, 51), (51, 67)):
            pending=roundtrip(result['continuation']['pending_quality'])
            self.assertEqual(pending['comparison_progress']['next_pair'],completed)
            self.assertEqual(pending['pending_indices'],[])
            self.assertEqual(result['stop_reason'],'user_pause')
            restore_progress(session,roundtrip(result['continuation']),assets)
            with patch('ygo_kito.construction_candidates.portfolio',side_effect=AssertionError('regenerated S2')), \
                 patch('ygo_kito.construction_quality._delta',side_effect=compare):
                result=construction_cycle(session,assets,providers,**options,max_candidates=0)
        first=roundtrip(result['continuation'])
        self.assertEqual(first['iteration'],0)
        self.assertIsNone(first['pending_quality'])
        self.assertIsNone(first['reference_evaluation'])
        self.assertTrue(first['pending_reference'])
        expected = first['pending_phase']['stage_3']
        ids = [row['quality_evaluation_id'] for row in expected['candidate_trace']['candidates']]
        self.assertEqual(len(set(ids)), 12)
        self.assertCountEqual(evaluated_candidates, candidates)
        self.assertEqual(len(set(pairs)), 66)
        self.assertEqual(len(pairs), 66)
        reads = [first['pending_reference']['calculation']['read_cursor']]
        for _ in range(3):
            restore_progress(session,roundtrip(result['continuation']),assets)
            verified = EvaluationComparisons()
            with patch('ygo_kito.construction_fill.fill_with_existing',side_effect=AssertionError('reopened S4')), \
                 patch('ygo_kito.construction_quality._delta',side_effect=compare):
                result=construction_cycle(session,assets,providers,**options,max_candidates=0,_comparisons=verified)
                self.assertTrue(cycle_pairs(task,result,_comparisons=verified))
            selection = result['phases'][-1]['stage_3']
            self.assertEqual([row['quality_evaluation_id'] for row in selection['candidate_trace']['candidates']], ids)
            self.assertEqual(selection['candidate_trace']['candidate_order'],expected['candidate_trace']['candidate_order'])
            self.assertEqual(selection['best_deck'], expected['best_deck'])
            if not result['continuation'].get('pending_reference'):break
            reads.append(result['continuation']['pending_reference']['calculation']['read_cursor'])
            self.assertIsNone(result['continuation']['reference_evaluation'])
        else:self.fail('finite reference calculation did not finish')
        self.assertEqual(reads, [6, 12])
        self.assertEqual(len(pairs), 66)
        self.assertCountEqual(evaluated_candidates, candidates)
        self.assertEqual(roles,['build_goal','build_optimizer'])
        self.assertTrue(result['construction_passed'])
        self.assertEqual(result['continuation']['iteration'],1)
        self.assertEqual(result['continuation']['candidate_cursor'],first['candidate_cursor'])
        self.assertIsNone(result['continuation']['pending_quality'])
        self.assertFalse(result['basic_cb']['execution_authorized'])

    def test_completed_candidate_survives_a_later_candidate_exception(self):
        from ygo_kito.build_contracts import DeckParts
        from ygo_kito.construction_fill import construction_cycle,FillProposal,NodeBinding
        from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
        from ygo_kito.construction_logic import ConstructionLogic
        from ygo_kito.construction_progress import restore_progress
        from tests.test_construction_functional_flow import fixture,reviewed
        from tests.test_construction_layer_flow import session_for,rows_for
        task,assets,graph,binder,decks,policy=fixture();roles=[]
        def provider(ctx):
            roles.append(ctx['role']);old=ConstructionLogic.from_dict(ctx['logic'])
            return dict(logic=replace(graph,revision=old.revision+1,parent_sha256=old.sha256).to_dict(),reason='fixture')
        def skeleton_result(session,*_a,**_kw):
            deck=DeckParts((1,));proposal=FillProposal(deck,(NodeBinding('goal',(1,)),),(),session.logic.sha256,task.sha256)
            return dict(status='axis_skeleton_ready',best_deck=deck.to_dict(),concrete_proposal=asdict(proposal),unfilled=dict(main=39,extra=0,side=0))
        class FailingLater(ConstructionLayerAdapter):
            fail=True
            def __init__(self,*a,**kw):super().__init__(*a,**kw);self.projected=[]
            def _project_layers(self,task,graph,proposal,context):
                if self.fail and self.projected:raise RuntimeError('later anonymous candidate failed')
                self.projected.append(proposal.deck.to_dict())
                return super()._project_layers(task,graph,proposal,context)
        session=session_for(task,graph);adapter=FailingLater(binder)
        options=dict(binding_provider=binder,text_reviewer=binder.reviewer,quality_criteria=policy,
            quality_evidence=reviewed(binder.semantic_catalog,policy),layer_adapter=adapter,
            run_mode='slice',seconds=30.,max_iterations=1,basic_cb_provider=lambda *_a,**_kw:self.fail('CB forbidden'))
        providers={key:provider for key in ('build_goal','build_optimizer')}
        with patch('ygo_kito.construction_fill.build_axis_skeleton',side_effect=skeleton_result), \
             patch('ygo_kito.build_pipeline._goal_candidates',return_value=decks), \
             patch('ygo_kito.construction_candidates.portfolio',return_value=rows_for(task,decks)):
            with self.assertRaisesRegex(RuntimeError,'later anonymous candidate'):
                construction_cycle(session,assets,providers,**options)
        saved=roundtrip(session.construction_progress)
        self.assertEqual(len(saved['pending_quality']['evaluations']),1)
        self.assertEqual(len(saved['pending_quality']['candidates']),len(decks))
        self.assertIsNotNone(saved['pending_phase'])
        first=adapter.projected[0];ids={k:v['quality_evaluation']['evaluation_id'] for k,v in saved['pending_quality']['evaluations'].items()}
        restore_progress(session,saved,assets);adapter.fail=False;adapter.projected=[]
        with patch('ygo_kito.construction_fill.build_axis_skeleton',side_effect=AssertionError('new skeleton')), \
             patch('ygo_kito.build_pipeline._goal_candidates',side_effect=AssertionError('new candidates')):
            result=construction_cycle(session,assets,providers,**options,max_candidates=0)
        self.assertNotIn(first,adapter.projected)
        for identity in ids.values():self.assertIn(identity,json.dumps(result))
        self.assertEqual(roles,['build_goal','build_optimizer'])
        self.assertTrue(result['construction_passed'])
        self.assertEqual(result['continuation']['candidate_cursor'],saved['candidate_cursor'])

    def test_quality_timeout_keeps_completed_normalization_for_resume(self):
        from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
        from tests.test_construction_functional_flow import fixture
        task,assets,graph,binder,decks,policy=fixture()
        deck=decks[-1];rows=[{'deck':deck}];proposals={0:binder(graph,task,deck)}
        adapter=ConstructionLayerAdapter(binder)
        _,expected,_=adapter.evaluate(task,graph,rows,proposals,[0],policy=policy)
        with patch('ygo_kito.construction_quality.evaluate_functional_quality',return_value={'evaluation_timed_out':True}):
            _,values,trace=adapter.evaluate(task,graph,rows,proposals,[0],policy=policy,should_stop=lambda:None)
        self.assertEqual(values,{})
        self.assertIn('0',trace['calculation_progress'])
        self.assertIn('resident',trace['calculation_progress']['0']['projections'])
        calculations={int(k):v for k,v in roundtrip(trace['calculation_progress']).items()}
        with patch('ygo_kito.construction_layer_flow._functional_relations',side_effect=AssertionError('completed relation repeated')):
            _,resumed,final=adapter.evaluate(task,graph,rows,proposals,[0],policy=policy,calculations=calculations)
        self.assertTrue(final['selection_complete'])
        self.assertFalse(final['calculation_progress'])
        self.assertEqual(resumed[0]['quality_evaluation']['evaluation_id'],expected[0]['quality_evaluation']['evaluation_id'])

    def test_adapter_persists_real_quality_budget_work_before_comparison(self):
        from ygo_kito.construction_binding import CatalogBindingAdapter
        from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
        from tests.test_construction_functional_flow import fixture
        task, assets, graph, _, decks, policy = fixture()
        assets.rows[1].update(type=33, desc='①：自己主要阶段，自己拥有未知计数的场合才能发动。抽1张。')
        binder = CatalogBindingAdapter(assets)
        adapter = ConstructionLayerAdapter(binder)
        policy['quality']['completion_budget'] = 1
        deck = decks[-1]
        rows, proposals = [{'deck': deck}], {0: binder(graph, task, deck)}
        _, values, trace = adapter.evaluate(task, graph, rows, proposals, [0], policy=policy)
        self.assertEqual(values, {})
        self.assertEqual(trace['stop_reason'], 'quality_evaluation_budget')
        progress = roundtrip(trace['calculation_progress']['0'])
        self.assertIn('resident', progress['projections'])
        self.assertEqual(progress['quality']['next_completion'], 1)
        with patch('ygo_kito.construction_layer_flow._functional_relations', side_effect=AssertionError('relation replay')):
            for _ in range(128):
                _, values, trace = adapter.evaluate(task, graph, rows, proposals, [0], policy=policy,
                    calculations={0: progress})
                if trace['selection_complete']:
                    break
                next_progress = roundtrip(trace['calculation_progress']['0'])
                self.assertEqual(next_progress['quality']['next_completion'], progress['quality']['next_completion'] + 1)
                self.assertEqual(values, {})
                progress = next_progress
            else:
                self.fail('adapter did not finish the finite quality calculation')
        self.assertTrue(trace['selection_complete'])
        self.assertEqual(trace['calculation_progress'], {})
        self.assertEqual(values[0]['quality_evaluation']['completion_evaluated_count'], progress['quality']['next_completion'] + 1)
        self.assertEqual(values[0]['quality_evaluation']['completion_evaluated_count'],
                         2 ** len(values[0]['quality_evaluation']['unknowns']))
        self.assertIn('evaluation_id', values[0]['quality_evaluation'])

    def test_theme_pairs_resume_and_stale_inputs_are_rejected(self):
        from types import SimpleNamespace
        from ygo_kito.construction_layer_flow import normalize_function_uses
        from ygo_kito.construction_progress import host_construction_quality
        from ygo_kito.validation import ContractError
        from tests.test_construction_theme import theme_fixture
        task,assets,graph,binder,decks,relations=theme_fixture()
        policy=host_construction_quality(task,catalog=binder.semantic_catalog)[0]
        options=dict(policy=policy,context=SimpleNamespace(relations=relations))
        expected=normalize_function_uses(task,decks[0],binder.semantic_catalog,**options)
        progress=None;first=None;saw_theme=False
        for _ in range(100):
            value=normalize_function_uses(task,decks[0],binder.semantic_catalog,**options,
                budget=RelationBudget(cards=1,facts=1,matches=1,updates=1),continuation=progress)
            if not value.get('calculation_pending'):break
            progress=roundtrip(value['calculation_pending'])
            first=first or deepcopy(progress)
            saw_theme|=bool((progress.get('active') or {}).get('work',{}).get('theme'))
        else:self.fail('finite theme calculation did not finish')
        self.assertTrue(saw_theme)
        self.assertEqual(value,expected)
        assets.rows[1]['desc']+='自己受到100伤害。'
        with self.assertRaisesRegex(ContractError,'different inputs|rederivation'):
            normalize_function_uses(task,decks[0],binder.semantic_catalog,**options,continuation=first)


if __name__=='__main__':
    unittest.main()
