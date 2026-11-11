"""S0--S5 and CB signal contracts, without model forward, training or search."""
import ast
from collections import Counter
from copy import copy, deepcopy
from contextlib import nullcontext
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.card_identity import canonical_card_id, released_identities
from ygo_kito.construction_effect_blocks import logic_vocabulary, requested_logic_tags
from ygo_kito.construction_logic import LogicTag
from ygo_kito.construction_progress import host_construction_quality, record_basic_cb_attempt
from ygo_kito.construction_retrieval import candidate_ids
from ygo_kito.deck_intake import _environment
from ygo_kito.validation import ContractError
from tests.test_construction_binding import catalog, one_node
from tests.test_construction_entrypoints import reference_fixture
from tests.test_construction_layer_flow import session_for
from tests.test_construction_theme import theme_fixture, evaluate, static_cycle, card_use


ROOT = Path(__file__).resolve().parents[1]


def expanded(task, assets, count=200):
    for code in range(max(assets.rows)+1, count+1):
        assets.rows[code] = dict(assets.rows[2],id=code,alias=0,setcode=0,type=17,
            name='通常怪兽'+str(code),desc='')
    raw = task.to_dict(); raw['pool'] = sorted(assets.rows)
    return BuildTask.from_dict(raw)


def source_method(file, cls, name, namespace):
    namespace.update(__name__='ygo_kito._static_workflow',__package__='ygo_kito')
    root = ast.parse((ROOT/'src/ygo_kito'/file).read_text(encoding='utf-8'))
    node = next(n for n in root.body if isinstance(n,ast.ClassDef) and n.name == cls)
    method = next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name == name)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),str(file),'exec'),namespace)
    return namespace[name]


class WorkflowTests(unittest.TestCase):
    def test_f06_completed_failed_gate_continues_development(self):
        from ygo_kito.construction_fill import construction_cycle
        session = SimpleNamespace(task=None, construction_progress={})
        failed = dict(status='construction_suspended', construction_passed=False,
            stop_reason='iteration_slice_exhausted', phases=[],
            construction_gate=dict(status='pending', reasons=['quality_pass_line:reference_ratio:failed']))
        passed = dict(status='construction_passed', construction_passed=True,
            stop_reason='construction_passed', phases=[], construction_gate=dict(status='passed', reasons=[]))
        with patch('ygo_kito.construction_fill._construction_cycle', side_effect=[failed, passed]) as cycle:
            result = construction_cycle(session, None, {}, run_mode='development', slice_seconds=1)
        self.assertEqual(cycle.call_count, 2)
        self.assertTrue(result['construction_passed'])

    def test_f07_cb_return_at_slice_boundary_precedes_static_pass(self):
        from ygo_kito.construction_fill import construction_cycle
        session = SimpleNamespace(task=None, construction_progress={})
        returned = dict(status='construction_passed', construction_passed=True, phases=[],
            stop_reason='basic_cb_requires_optimization', basic_cb_optimization_requested=True,
            construction_gate=dict(status='passed', reasons=[]))
        passed = dict(status='construction_passed', construction_passed=True, phases=[],
            stop_reason='construction_passed', construction_gate=dict(status='passed', reasons=[]))
        with patch('ygo_kito.construction_fill._construction_cycle', side_effect=[returned, passed]) as cycle:
            result = construction_cycle(session, None, {}, run_mode='development', slice_seconds=1)
        self.assertEqual(cycle.call_count, 2)
        self.assertEqual(result['stop_reason'], 'construction_passed')

    def test_f16_recent_safe_modules_are_registered_once(self):
        tree = ast.parse((ROOT/'scripts/check_merge_candidate.py').read_text(encoding='utf-8'))
        modules = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == 'MODULES' for t in n.targets))
        for name in ('workflow', 'text_completion', 'static_entries', 'runtime_processing',
                     'condition_selection', 'calculation_resume', 'recognition'):
            self.assertEqual(modules.count('tests.test_construction_' + name), 1)
        self.assertEqual(modules.count('tests.test_multifactor_candidates'), 1)

    def test_f08_reference_is_independent_of_optional_candidate_graph(self):
        from tests.test_construction_functional_flow import fixture
        from ygo_kito.construction_relations import InputGroup, Need, RelationContext, Resource, UseRequirement
        f = list(fixture())
        reference_deck = f[4][0]
        f[1].validate(f[0],reference_deck)
        f[2] = one_node(LogicTag('effect','抽卡'))
        p = deepcopy(f[5])
        p['pass'] = dict(mode='reference_ratio',minimum_reference_ratio=.8,
            reference=dict(reference_id='fixed-reference',deck_sha256=digest(reference_deck.to_dict()),source='fixture'))
        reference = dict(reference_id='fixed-reference',deck=reference_deck.to_dict(),source='fixture',
            environment=deepcopy(f[0].environment))
        f[4] = [f[4][1]]  # Only the generated candidate has the optional graph function.
        inputs = InputGroup('all', (Need('draw', Resource('functional_operation',
            attributes=('catalog:2:1:op:0',)), mode='presence'),))
        for required in (False, True):
            with self.subTest(required=required):
                f[5] = RelationContext((UseRequirement('original-draw', inputs, 'fixture requirement', required),))
                result = static_cycle(self,f,session_for(f[0],f[2]),quality_criteria=p,
                    quality_reference=reference,max_iterations=1)
                reasons = result['construction_gate']['reasons']
                self.assertFalse(any(r.startswith('reference_invalid:') for r in reasons))
                evaluation = result['continuation']['reference_evaluation']
                self.assertEqual(evaluation['logic_sha256'], digest(None))
                self.assertEqual(evaluation['score']['value'], 0.)
                self.assertIn('reference_score_nonpositive', reasons)
                requirements = {r['requirement_id']: r['status'] for r in evaluation['hard_requirements']}
                if required:
                    self.assertEqual(requirements['original-draw'], 'failed')
                    self.assertIn('reference_hard_requirement_unmet', reasons)
                else:
                    self.assertNotIn('original-draw', requirements)

    def test_fixed_reference_preparation_reuses_valid_inventory(self):
        from ygo_kito.construction_layer_flow import ConstructionLayerAdapter

        (task, assets, graph, binder, *_), policy, reference, deck = reference_fixture()
        descriptor = policy['pass']['reference']
        adapter = ConstructionLayerAdapter(binder)
        with patch.object(assets, 'validate', wraps=assets.validate) as validate:
            prepared_deck, binding, inputs = adapter.reference_inputs(task, graph, reference, descriptor,
                policy=policy)
            self.assertEqual(prepared_deck, deck)
            self.assertIs(adapter.reference_inputs(task, graph, reference, descriptor, policy=policy)[2], inputs)

            resumed = ConstructionLayerAdapter(binder)
            self.assertEqual(resumed.reference_inputs(task, graph, reference, descriptor,
                policy=policy, completed_binding=binding), (deck, binding, None))
            validate.assert_called_once_with(task, deck)

            code = deck.main[0]
            assets.limits[assets.rows[code]['alias'] or code] = 0
            with self.assertRaises(ContractError):
                resumed.reference_inputs(task, graph, reference, descriptor,
                    policy=policy, completed_binding=binding)
            self.assertEqual(validate.call_count, 2)

    def test_fixed_reference_reuses_evaluation_until_its_inputs_change(self):
        from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
        from ygo_kito.construction_progress import revise_quality_policy
        f, policy, reference, deck = reference_fixture()
        session = session_for(f[0], f[2])
        original = ConstructionLayerAdapter.evaluate_inventory
        reference_calls = []
        def evaluate(adapter,task,inventory,layer,context,**options):
            if layer['axis']['logic'] is None:
                reference_calls.append(inventory)
            return original(adapter,task,inventory,layer,context,**options)
        def run():
            return static_cycle(self, f, session, quality_criteria=policy,
                quality_reference=reference, max_iterations=1)['continuation']
        with patch.object(ConstructionLayerAdapter, 'evaluate_inventory', new=evaluate):
            first = run()
            f[2] = one_node(LogicTag('effect','特召'))
            second = run()
            self.assertNotEqual(second['logic_sha256'], first['logic_sha256'])
            self.assertEqual(second['iteration'], first['iteration']+1)
            self.assertEqual(second['reference_evaluation']['evaluation_id'], first['reference_evaluation']['evaluation_id'])
            self.assertEqual(reference_calls, [deck])

            f[5] = replace(f[5], facts=tuple(replace(fact, source='revised host observation') for fact in f[5].facts))
            third = run()
            self.assertNotEqual(third['reference_binding']['inputs'], second['reference_binding']['inputs'])
            self.assertEqual(reference_calls, [deck, deck])

            theme_cards = policy['quality']['theme_profile']['card_texts']
            changed = next(code for code in deck.main if str(code) not in theme_cards)
            f[1].rows[changed]['desc'] += ' '
            fourth = run()
            self.assertNotEqual(fourth['reference_binding']['assets'], third['reference_binding']['assets'])
            self.assertEqual(reference_calls, [deck, deck, deck])

            reference = dict(reference, source='revised fixed reference source')
            policy = deepcopy(policy)
            policy['pass']['reference']['source'] = reference['source']
            revise_quality_policy(session, policy)
            fifth = run()
            self.assertNotEqual(fifth['reference_binding']['inputs'], fourth['reference_binding']['inputs'])
            self.assertEqual(reference_calls, [deck, deck, deck, deck])

    def test_protection_effects_do_not_become_global_player_restriction_gaps(self):
        from tests.test_construction_functional_flow import fixture
        from ygo_kito.construction_layer_flow import normalize_function_uses
        from ygo_kito.construction_quality import evaluate_functional_quality
        from ygo_kito.construction_relations import RelationContext,RelationFact,Resource
        clauses=(('battle_protection','这张卡不会被战斗破坏。',False),
            ('effect_protection','这张卡不会被效果破坏。',False),
            ('effect_protection','这张卡在特殊召唤·反转的回合不会被战斗·效果破坏。',True))
        for kind,clause,conditional in clauses:
            with self.subTest(kind=kind):
                task,assets,graph,binder,decks,policy=fixture()
                assets.rows[2]['desc']='这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。抽1张。②：'+clause
                phase=RelationFact('phase','phase',Resource('activation',event='own_main_phase',
                    reason='not_applicable',attributes=('card:2',)),'explicit draw activation support')
                context=SimpleNamespace(relations=RelationContext((),(phase,)))
                facts=normalize_function_uses(task,decks[1],binder.semantic_catalog,policy=policy,context=context)
                checks=[c for d in facts['use_details'].values() for c in d['restriction_checks']
                    if c['restriction']['kind']==kind]
                self.assertTrue(checks)
                self.assertTrue(any(c['status']=='function_effect' for c in checks))
                q=evaluate_functional_quality(dict(axis=dict(task=task.to_dict(),inventory=decks[1].to_dict(),
                    logic=graph.to_dict())),policy=policy,facts=facts)
                self.assertNotIn('impacts',q['deferred'])
                if conditional:
                    from ygo_kito.construction_quality import support_state
                    protected=[u for u in facts['uses'] if facts['use_details'][u.use_id]['operation'].get('kind')==kind]
                    self.assertTrue(any(support_state(u.self_condition,facts['variables']) is None for u in protected))
                    self.assertFalse(q['complete'])

    def test_completed_round_saves_evaluation_receipts_and_winner(self):
        from ygo_kito.construction_progress import restore_progress
        f = theme_fixture()
        session = session_for(f[0], f[2])
        result = static_cycle(self, f, session, max_iterations=1)
        stage = result['phases'][-1]['stage_3']
        saved = result['continuation']['last_optimizer_phase']['stage_3']
        for key in ('learning_candidates', 'portfolio', 'attempts'):
            self.assertNotIn(key, stage)
        self.assertEqual(saved, stage)
        self.assertTrue(all(row['quality_evaluation_id'] for row in stage['candidate_trace']['candidates']))
        self.assertEqual(result['best']['quality_evaluation']['deck_sha256'],
                         result['continuation']['candidate']['deck_sha256'])
        restore_progress(session, json.loads(json.dumps(result['continuation'])), f[1])

    def test_fixed_task_uses_only_required_series_or_race_to_select_axes(self):
        from ygo_kito.construction_fill import construct_task
        from ygo_kito.construction_logic import ThemeScope
        task, assets, *_ = theme_fixture()
        observed=[]
        class Adapter:
            def __init__(self,*args,**options):
                self.required_tags=options['required_tags']
            def providers(self):return {}
        def cycle(session,*args,**options):
            observed.append((session.classification,options['scopes']))
            return dict(phases=[],best=None)
        modules={'ygo_kito.autonomous_construction':SimpleNamespace(_SharedLogicAdapter=Adapter),
            'ygo_kito.construction_model':SimpleNamespace(LogicCodec=lambda tags,kinds:None)}
        with patch.dict('sys.modules',modules), patch('ygo_kito.construction_fill.construction_cycle',side_effect=cycle):
            construct_task(task,assets,{},None)
            raw=task.to_dict()
            raw['goal']['constraints']=[r for r in raw['goal']['constraints'] if r['id']!='selected-theme']
            raw['goal']['constraints'].append(dict(id='optional-race',zones=['main'],
                predicate=dict(field='race_any',value=0x2000),minimum=0,maximum=40))
            broad=BuildTask.from_dict(raw)
            construct_task(broad,assets,{},None)
            raw['goal']['constraints'][-1]['minimum']=1
            construct_task(BuildTask.from_dict(raw),assets,{},None)
            with self.assertRaises(ContractError):
                construct_task(broad,assets,{},None,scopes=(ThemeScope('龙族','race_any',0x2000,'fixture'),))
        self.assertEqual([c.kind for c,_ in observed],['narrow','broad','narrow'])
        self.assertEqual([[(s.field,s.value) for s in scopes] for _,scopes in observed],
            [[('setcode',0x515)],[],[('race_any',0x2000)]])
        self.assertTrue(all(s.source=='original-task:'+task.sha256 for s in observed[0][1]))

    def test_required_race_uses_the_same_automatic_mechanism_weighting(self):
        f=list(theme_fixture('summon'))
        for code,row in f[1].rows.items():
            row['race']=0x2000 if code in (2,3) else 1
        raw=f[0].to_dict()
        selected=next(r for r in raw['goal']['constraints'] if r['id']=='selected-theme')
        selected['predicate']=dict(field='race_any',value=0x2000)
        f[0]=BuildTask.from_dict(raw)
        profile=host_construction_quality(f[0],catalog=f[3].semantic_catalog)[0]['quality']['theme_profile']
        self.assertEqual(profile['status'],'evaluated',profile['gaps'])
        self.assertTrue(profile['goals'])

    def test_release_admission_follows_catalog_identity_and_preserves_future_exclusion(self):
        rows = {1:dict(id=1,alias=0,name='原卡',desc='相同卡文',type=17),
            2:dict(id=2,alias=1,name='原卡',desc='相同卡文',type=17),
            3:dict(id=3,alias=0,name='未来卡',desc='',type=17),4:dict(id=4,alias=3,name='未来卡',desc='',type=17),
            5:dict(id=5,alias=1,name='规则上当作原卡',desc='不同卡文',type=33)}
        release = dict(schema_version=1,period_id='2022-07',release_cutoff='2022-09-30',cards=[
            dict(card_id=1,ocg_release_date='2017-01-14'),dict(card_id=3,ocg_release_date='2023-01-01')])
        env = dict(release_cutoff='2022-09-30',releases={},catalog={},banlist={},
                   banlist_effective='2022-07-01',banlist_section='2022.7')
        with patch('ygo_kito.deck_intake._artifact',return_value=(Path('fixture'),json.dumps(release).encode())), \
             patch('ygo_kito.deck_intake.cutoff_timing',return_value=dict(cutoff_selected=True,cutoff_reached=True)), \
             patch('ygo_kito.deck_intake.read_listing_catalog',return_value=rows), \
             patch('ygo_kito.deck_intake.read_selected_banlist',return_value={1:1}):
            receipt, parsed = _environment(Path('.'),'2022-07',env)
        self.assertEqual(parsed[2],{1,2})
        self.assertEqual(parsed[1],{1:1})
        self.assertEqual(canonical_card_id(rows,2),1)
        self.assertEqual(canonical_card_id(rows,5),5)
        self.assertEqual(released_identities(rows,{2}),{1,2})
        with self.assertRaises(ContractError):
            canonical_card_id({1:dict(alias=2,name='卡',desc='',type=17),2:dict(alias=1,name='卡',desc='',type=17)},1)

    def test_full_pool_and_repeat_queries_preserve_task_and_reach_new_cards(self):
        task, assets = catalog(); task = expanded(task,assets)
        original = task.to_dict()
        graph = one_node(LogicTag('effect','抽卡'))
        assets.rows[199].update(type=33,desc='①：自己主要阶段才能发动。抽1张。')
        first, a = candidate_ids(task,assets,graph,base=DeckParts((1,)))
        second, b = candidate_ids(task,assets,graph,base=DeckParts((1,)),cursor=128)
        self.assertGreater(len(task.pool),128)
        self.assertIn(199,first)
        self.assertTrue(set(second)-set(first))
        self.assertLessEqual(len(first),128)
        self.assertEqual(task.to_dict(),original)
        self.assertEqual(a['task_sha256'],b['task_sha256'])
        self.assertGreater(b['next_cursor'],a['next_cursor'])

    def test_theme_cooperation_does_not_require_reading_unrelated_environment_cards(self):
        for kind in ('summon','banished','grave'):
            f = list(theme_fixture(kind))
            before = host_construction_quality(f[0],catalog=f[3].semantic_catalog)[0]['quality']['theme_profile']
            f[0] = expanded(f[0],f[1])
            after = host_construction_quality(f[0],catalog=f[3].semantic_catalog)[0]['quality']['theme_profile']
            self.assertEqual(after['status'],'evaluated',after['gaps'])
            self.assertEqual(before['goals'],after['goals'])
            self.assertNotIn('theme_card_budget',after['gaps'])

    def test_explicit_function_matches_candidate_processing_in_a_full_pool(self):
        f = list(theme_fixture('summon')); f[0] = expanded(f[0],f[1])
        p = host_construction_quality(f[0],catalog=f[3].semantic_catalog,
            goal_tags=(LogicTag('effect','抽卡'),))[0]
        self.assertEqual(p['quality']['theme_profile']['status'],'evaluated')
        _, facts, _ = evaluate(f,policy=p)
        self.assertIn('task-primary',card_use(facts,3).theme_eligible)

    def test_same_card_printings_keep_real_sources_and_one_discounted_function(self):
        f=list(theme_fixture('summon'))
        _,_,baseline=evaluate(f)
        f[1].rows[200]=dict(f[1].rows[3],id=200,alias=3)
        raw=f[0].to_dict();raw['pool']=sorted((*raw['pool'],200));f[0]=BuildTask.from_dict(raw)
        main=list(f[4][0].main);main.remove(3);main.append(200)
        deck=replace(f[4][0],main=tuple(sorted(main)))
        _,facts,quality=evaluate(f,deck)
        self.assertTrue(quality['complete'],quality['total'])
        self.assertAlmostEqual(quality['score']['value'],baseline['score']['value'])
        uses=[u for u in facts['uses'] if u.contributes and facts['use_details'][u.use_id]['card_id'] in (3,200)]
        self.assertEqual(len({u.use_id for u in uses}),2)
        self.assertEqual(len({u.score_family_id for u in uses}),1)
        self.assertEqual(len({s for u in uses for s in u.source_ids}),3)

    def test_same_effect_repeated_processing_does_not_collide_or_create_another_function(self):
        f=list(theme_fixture('summon'))
        f[1].rows[3]['desc']='①：自己主要阶段才能发动。抽1张。抽1张。'
        p=host_construction_quality(f[0],catalog=f[3].semantic_catalog,
            goal_tags=(LogicTag('effect','抽卡'),))[0]
        _,facts,_=evaluate(f,policy=p)
        uses=[u for u in facts['uses'] if u.contributes and facts['use_details'][u.use_id]['card_id']==3]
        self.assertEqual(len(uses),2)
        self.assertEqual(len({u.use_id for u in uses}),2)
        self.assertEqual(len({u.score_family_id for u in uses}),1)
        self.assertEqual(len({s for u in uses for s in u.source_ids}),3)

    def test_reference_error_is_reported_after_candidate_generation_without_a_failure_count(self):
        f,p,reference,_ = reference_fixture()
        reference['source'] = 'incorrect-source'
        session = session_for(f[0],f[2])
        result = static_cycle(self,f,session,quality_criteria=p,quality_reference=reference,max_iterations=1)
        self.assertTrue(result['construction_candidate']['deck'])
        self.assertTrue(result['phases'][-1]['stage_3']['candidate_trace']['candidates'])
        self.assertFalse(result['construction_passed'])
        self.assertTrue(any(r.startswith('reference_invalid:') for r in result['construction_gate']['reasons']))
        self.assertNotIn('reference_feedback',result['continuation'])

    def test_interrupted_numeric_evaluation_is_not_cached_as_finished(self):
        from tests.test_construction_layer_flow import flow_fixture,rows_for
        from ygo_kito.construction_fill import fill_with_existing
        from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
        from ygo_kito.construction_quality import evaluate_functional_quality
        task,assets,graph,binder,decks,context=flow_fixture()
        adapter=ConstructionLayerAdapter(binder,context_provider=lambda t,g:context)
        def interrupted(layer,**options):
            options['should_stop']=lambda:'time_slice_exhausted'
            return evaluate_functional_quality(layer,**options)
        with patch('ygo_kito.build_pipeline.edit_candidates',return_value=rows_for(task,decks[:1])), \
             patch('ygo_kito.construction_quality.evaluate_functional_quality',side_effect=interrupted):
            result=fill_with_existing(session_for(task,graph),assets,role='build_optimizer',base=decks[0],
                binding_provider=binder,text_reviewer=binder.reviewer,verifier=None,defer_engine=True,
                layer_adapter=adapter,should_stop=lambda:None)
        self.assertEqual(result['status'],'quality_evaluation_pending')
        self.assertFalse(result['pending_quality']['evaluations'])
        self.assertEqual(len(result['pending_quality']['candidates']),1)

    def test_automatic_policy_is_derived_after_goal_logic_and_is_saved_for_resume(self):
        f = theme_fixture(); session = session_for(f[0],f[2]); events=[]
        original = session.propose_logic
        def propose(role,provider):
            events.append(role)
            return original(role,provider)
        def policy():
            events.append('policy')
            return host_construction_quality(f[0],catalog=f[3].semantic_catalog)
        with patch.object(session,'propose_logic',side_effect=propose):
            result = static_cycle(self,f,session,quality_factory=policy,max_iterations=1)
        self.assertLess(events.index('build_goal'),events.index('policy'))
        self.assertTrue(result['continuation']['quality_policy']['quality']['theme_rules'])

    def test_two_cb_failures_require_normal_completion_for_the_same_candidate(self):
        state = dict(task_sha256='a'*64,candidate_version=3,candidate=dict(deck_sha256='b'*64))
        cb = dict(task_sha256='a'*64,subject_deck_sha256='b'*64,status='bounded_inference_unknown',
                  normal_completion=False,failure_count_eligible=False,routes=[])
        for _ in range(3):
            self.assertFalse(record_basic_cb_attempt(state,cb))
        self.assertNotIn('basic_cb_feedback',state)
        self.assertFalse(record_basic_cb_attempt(state,dict(cb,normal_completion=True,failure_count_eligible=True)))
        self.assertNotIn('basic_cb_feedback',state)
        cb.update(normal_completion=True,failure_count_eligible=True,status='no_route_found')
        self.assertFalse(record_basic_cb_attempt(state,cb))
        self.assertTrue(record_basic_cb_attempt(state,cb))
        state['candidate_version'] += 1
        self.assertFalse(record_basic_cb_attempt(state,cb))
        cb.update(status='routes_inferred',routes=[{'witness':'static record only'}],failure_count_eligible=False)
        self.assertFalse(record_basic_cb_attempt(state,cb))
        self.assertEqual(state['basic_cb_feedback']['consecutive_failures'],0)

    def test_two_normal_cb_records_return_to_optimizer_within_the_original_slice(self):
        f,p,reference,deck=reference_fixture();f[4]=[deck]
        session=session_for(f[0],f[2])
        def static_record(task,deck,assets,provider,gate=None,recognition_record=None):
            self.assertIsNotNone(provider)
            return dict(status='no_route_found',routes=[],normal_completion=True,failure_count_eligible=True,
                inference_completed=True,task_sha256=task.sha256,subject_deck_sha256=digest(deck.to_dict()))
        with patch('ygo_kito.construction_fill._candidate_basic_cb',side_effect=static_record) as records:
            result=static_cycle(self,f,session,quality_criteria=p,quality_reference=reference,
                cb_authorized=True,max_iterations=2)
        self.assertEqual([p['role'] for p in result['phases']],['build_goal','build_optimizer','build_optimizer'])
        self.assertEqual(records.call_count,4)
        self.assertEqual(result['continuation']['iteration'],2)
        self.assertTrue(any(r.get('stage')=='basic_cb_return_to_optimizer' for r in session.history))
        self.assertTrue(result['basic_cb_optimization_requested'])

    def test_global_logic_dictionary_exists_without_card_queries(self):
        with patch('ygo_kito.construction_effect_blocks.MechanismCatalog',side_effect=AssertionError('card read before logic')):
            tags = logic_vocabulary()
        self.assertIn(LogicTag('effect','抽卡'),tags)
        self.assertIn(LogicTag('effect','特殊胜利'),tags)
        self.assertGreater(len(tags),30)


class StaticEncoderTests(unittest.TestCase):
    def test_legacy_metadata_is_archived_and_saved_scope_is_rebound_without_retargeting(self):
        task,assets = catalog(); full = expanded(task,assets)
        theme=dict(theme_id='setcode-123',field='setcode',value=0x123,card_ids=[1],
            tag=dict(dimension='field',value='setcode:123'),source='catalog')
        stub=SimpleNamespace(_check=lambda:None,_binding_sha256='a'*64,
            builder=SimpleNamespace(task=task,models={'build_goal':None,'build_optimizer':None},
                encoder=SimpleNamespace(binding=lambda:{})),archived_workflow=None,
            source_binding={'construction_goal':task.goal},task_ids=full.pool,theme_minimum=1,
            enumerate_themes=lambda:[theme])
        namespace=dict(ContractError=ContractError,FEATURE_VERSION='fixture',parameter_digest=lambda model:'b'*64,
            deepcopy=deepcopy,ROLES=('build_goal','build_optimizer'),integer=__import__('ygo_kito.validation',fromlist=['integer']).integer,
            Counter=__import__('collections').Counter,BuildTask=BuildTask,digest=digest)
        make_task=source_method('autonomous_construction.py','AutonomousConstructionKernel','_task',namespace)
        stub._task=lambda *args:make_task(stub,*args)
        old=make_task(stub,theme,task.pool,None)
        selection=dict(candidate_id=old.sha256,theme=theme,task=old.to_dict())
        state=dict(schema_version=1,feature_version='fixture',binding_sha256='a'*64,encoder_binding={},
            model_hashes={r:'b'*64 for r in namespace['ROLES']},updates={'build_goal':5,'build_optimizer':0},
            selections={old.sha256:selection},sessions={},proposal_seals=[])
        load=source_method('autonomous_construction.py','AutonomousConstructionKernel','load_state_dict',namespace)
        load(stub,state)
        self.assertEqual(stub.updates,{'build_goal':5,'build_optimizer':0})
        self.assertFalse(stub.selections)
        bad=deepcopy(state);bad['updates']['build_goal']=-1
        with self.assertRaises(ContractError):load(stub,bad)
        self.assertEqual(stub.archived_workflow,state)
        upgrade=source_method('autonomous_construction.py','AutonomousConstructionKernel','upgrade_selection',namespace)
        restored=upgrade(stub,selection)
        self.assertEqual(restored['task']['pool'],list(full.pool))
        self.assertEqual(restored['task']['goal'],old.to_dict()['goal'])
        self.assertEqual(restored['theme'],theme)
        self.assertEqual(restored['previous_task_sha256'],old.sha256)

    def test_task_proposal_fixes_the_full_environment_without_reading_effects(self):
        task,assets = catalog(); task = expanded(task,assets)
        theme = dict(theme_id='setcode-123',field='setcode',value=0x123,card_ids=[1],
            tag=dict(dimension='field',value='setcode:123'),source='catalog')
        class Scores:
            def detach(self):return self
            def cpu(self):return self
            def tolist(self):return [0.]
        class Model:
            training=True
            def eval(self):pass
            def train(self,mode):self.training=mode
            def __call__(self,batch):return Scores()
        stub = SimpleNamespace(_check=lambda:None,builder=SimpleNamespace(task=task,models={'build_goal':Model()}),
            source_binding={'construction_goal':task.goal},task_ids=task.pool,theme_minimum=1,
            allowed_theme_ids=[theme['theme_id']],enumerate_themes=lambda:[theme],candidate_limit=2,
            _binding_sha256='a'*64,_proposal_seals=set(),_task_batch=lambda tasks:tasks)
        namespace=dict(deepcopy=deepcopy,BuildTask=BuildTask,DeckParts=DeckParts,digest=digest,
            ContractError=ContractError,Counter=__import__('collections').Counter)
        make_task=source_method('autonomous_construction.py','AutonomousConstructionKernel','_task',namespace)
        stub._task=lambda *args:make_task(stub,*args)
        stub.assets=assets
        namespace.update(_referenced_ids=lambda value:set(),torch=SimpleNamespace(no_grad=nullcontext),
                         parameter_digest=lambda model:'b'*64,math=__import__('math'))
        propose=source_method('autonomous_construction.py','AutonomousConstructionKernel','propose_tasks',namespace)
        result=propose(stub)
        self.assertEqual(result['status'],'model_ranked_tasks')
        self.assertEqual(result['candidates'][0]['task']['pool'],list(task.pool))
        self.assertEqual(result['candidates'][0]['dependency_recall']['status'],'not_started_before_logic')

    def test_session_logic_uses_dictionary_and_only_explicit_requirements(self):
        task,assets = catalog(); task = expanded(task,assets)
        theme = dict(tag=dict(dimension='field',value='setcode:123'))
        selection = dict(candidate_id='selected',theme=theme)
        class Adapter:
            def __init__(self,task,builder,codec,updates,**options):
                self.codec=codec;self.required_tags=options['required_tags']
        namespace=dict(ConstructionSession=__import__('ygo_kito.construction_logic',fromlist=['ConstructionSession']).ConstructionSession,
            LogicTag=LogicTag,logic_vocabulary=logic_vocabulary,requested_logic_tags=requested_logic_tags,_SharedLogicAdapter=Adapter,
            LogicCodec=lambda tags,kinds:SimpleNamespace(tags=tuple(tags),kinds=tuple(kinds)))
        make_session=source_method('autonomous_construction.py','AutonomousConstructionKernel','_session',namespace)
        stub=SimpleNamespace(_selection=lambda s:task,sessions={},adapters={},builder=None,graph_updates={},
            source_binding=dict(construction_logic_requirements=dict(tags=[dict(dimension='effect',value='抽卡')],connector_kinds=[])))
        _,adapter=make_session(stub,selection)
        self.assertEqual(set(adapter.required_tags),{LogicTag('field','setcode:123'),LogicTag('effect','抽卡')})
        self.assertIn(LogicTag('effect','特殊胜利'),adapter.codec.tags)

    def test_graph_scoring_chunks_the_dictionary_and_restores_model_mode(self):
        class Model:
            training=True
            def eval(self):self.training=False
            def train(self,mode):self.training=mode
            def __call__(self,graphs):return SimpleNamespace(tolist=lambda:[float(i) for i in graphs])
        model=Model();calls=[]
        def batch(context,graphs):
            calls.append(len(graphs));self.assertLessEqual(len(graphs),16);return graphs
        stub=SimpleNamespace(_check=lambda *_:None,models={'build_goal':model},encoder=SimpleNamespace(batch=batch))
        scores=source_method('construction_model.py','LogicModelAdapter','scores',dict(
            torch=SimpleNamespace(no_grad=nullcontext),math=__import__('math'),ContractError=ContractError))
        self.assertEqual(scores(stub,dict(role='build_goal'),list(range(37))),list(map(float,range(37))))
        self.assertEqual(calls,[16,16,5]);self.assertTrue(model.training)
        with patch.object(stub.encoder,'batch',side_effect=ValueError('static scoring error')):
            with self.assertRaises(ValueError):scores(stub,dict(role='build_goal'),[1])
        self.assertTrue(model.training)

    def test_alias_uses_an_existing_row_without_expanding_vocabulary(self):
        task,assets = catalog(); task = expanded(task,assets)
        assets.rows[200] = dict(assets.rows[1],id=200,alias=1)
        original = {c:i for i,c in enumerate(task.pool[:-1],1)}
        stub = SimpleNamespace(assert_binding=lambda:None,assets=assets,
            available_ids=frozenset(original),card_index=dict(original),
            annotations_sha256=digest(list(task.annotations)),environment_sha256=digest(task.environment))
        namespace = dict(copy=copy,BuildTask=BuildTask,digest=digest,ContractError=ContractError)
        encoding_view = source_method('autonomous_construction.py','CourseBuildEncoder','_encoding_view',namespace)
        view = encoding_view(stub,task)
        self.assertEqual(view.card_index[200],original[1])
        self.assertEqual(stub.card_index,original)

    def test_environment_context_does_not_encode_the_entire_pool(self):
        task,assets = catalog(); task = expanded(task,assets)
        from ygo_kito.validation import canonical_json
        stub = SimpleNamespace(assets=assets,environment_sha256=digest(task.environment),card_ids=task.pool,
            card_index={c:i for i,c in enumerate(task.pool,1)},config=SimpleNamespace(max_tokens=192),
            tag_index={canonical_json(a):i+1 for i,a in enumerate(task.annotations)})
        encode = source_method('build_model.py','BuildEncoder','_encode_inventory',dict(
            digest=digest,ContractError=ContractError,canonical_json=canonical_json,ZONES=('main','extra','side')))
        deck = DeckParts(tuple([1]*3+[c for c in range(2,20) for _ in range(2)]+[20]))
        tokens,_,_ = encode(stub,task,{zone: Counter(getattr(deck, zone)) for zone in ('main','extra','side')})
        self.assertLess(len(tokens),192)
        self.assertTrue({stub.card_index[c] for c in deck.main} <= {r[0] for r in tokens})


class ScipyQueryTests(unittest.TestCase):
    def test_solver_keeps_the_original_task_while_using_a_query_batch(self):
        from ygo_kito.build_semantics import solve_candidates
        task,assets = catalog(); task = expanded(task,assets)
        before=task.to_dict()
        result=solve_candidates(task,assets,candidate_ids=tuple(range(1,15)),candidate_count=1)
        self.assertEqual(result['status'],'verified_list_candidates')
        self.assertTrue(set(result['candidates'][0].main) <= set(range(1,15)))
        assets.validate(task,result['candidates'][0])
        self.assertEqual(task.to_dict(),before)


if __name__ == '__main__':
    unittest.main()
