"""Candidate-bound functional wiring, with no model, training or engine."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.construction_binding import CatalogBindingAdapter
from ygo_kito.construction_layer_flow import ConstructionLayerAdapter, normalize_function_uses, NORMALIZATION_VERSION
from ygo_kito.construction_logic import LogicTag
from ygo_kito.construction_quality import evaluate_functional_quality
from ygo_kito.construction_relations import RelationBudget
from ygo_kito.validation import ContractError
from tests.test_construction_binding import catalog, one_node
from tests.test_construction_functional_quality import policy
from tests.test_construction_layer_flow import rows_for, session_for
from ygo_kito.construction_fill import fill_with_existing, construction_cycle, FillProposal, NodeBinding
from ygo_kito.construction_logic import ConstructionLogic
from ygo_kito.construction_progress import construction_gate, restore_progress, revise_quality_policy


def fixture():
    task, assets = catalog()
    raw = task.to_dict()
    raw["goal"]["constraints"][0]["predicate"]["value"] = 1
    raw["candidate_budget"] = 4
    task = BuildTask.from_dict(raw)
    assets.rows[2].update(type=33, desc="①：自己从卡组抽1张。")
    binder = CatalogBindingAdapter(assets)
    graph = one_node(LogicTag("race", "植物族"))
    core = (1,) + tuple(c for c in range(4, 16) for _ in range(3))
    decks = [DeckParts(tuple(sorted(core + (2,) * count + (3,) * (3-count)))) for count in range(4)]
    p = policy()
    p["pass"] = p.pop("pass_")
    return task, assets, graph, binder, decks, p


def reviewed(catalog, policy):
    def evidence(task, deck, layers):
        facts = normalize_function_uses(task, deck, catalog, policy=policy, layer_evaluation=layers)
        return {**{k: facts[k] for k in ("version", "task_sha256", "deck_sha256", "asset_version")},
            "source": "static fixture review", "evidence_refs": ["reviewed activation conditions"],
            "variables": {k: True for k, value in facts["variables"].items() if value is None}}
    return evidence


def functional_fill():
    task, assets, graph, binder, decks, p = fixture()
    with patch('ygo_kito.build_pipeline.edit_candidates', return_value=rows_for(task, decks)):
        result = fill_with_existing(session_for(task, graph), assets, role='build_optimizer', base=decks[0],
            binding_provider=binder, text_reviewer=binder.reviewer, verifier=None, defer_engine=True,
            quality_policy=p, quality_evidence=reviewed(binder.semantic_catalog, p))
    return task, assets, decks, result


class FunctionalFlowTests(unittest.TestCase):
    def test_copy_edit_reuses_unchanged_resources_and_function_pricing(self):
        from ygo_kito import construction_layer_flow as flow, construction_quality as scoring

        task, assets, graph, binder, decks, p = fixture()
        assets.rows[4]['desc'] = '①：从自己卡组上面把3张卡送去墓地。'
        adapter = ConstructionLayerAdapter(binder)
        reuse = dict(specifications={}, projections={}, family_prices={})

        def evaluate(deck, memo=None):
            layer = dict(axis=dict(inventory=deck.to_dict(), task=task.to_dict(), logic=graph.to_dict()))
            result, work, stop = adapter.evaluate_inventory(task, deck, layer, None,
                policy=p, reuse=memo, should_stop=lambda: None)
            self.assertIsNone(work)
            self.assertIsNone(stop)
            return result

        evaluate(decks[1], reuse)
        cold_work = reuse['projections']['resident'].data['work']
        with (patch.object(flow, 'relation_index', wraps=flow.relation_index) as matching,
              patch.object(scoring, '_price_family', wraps=scoring._price_family) as prices):
            hot = evaluate(decks[2], reuse)
            hot_work = reuse['projections']['resident'].data['work']
            self.assertFalse(matching.called)
            hot_price_count = prices.call_count
            self.assertEqual(hot, evaluate(decks[2]))
            self.assertLess(hot_price_count, prices.call_count - hot_price_count)
            self.assertEqual(evaluate(decks[0], reuse), evaluate(decks[0]))
            self.assertFalse(reuse['projections']['resident'].data['work']['incremental'])
        self.assertTrue(hot_work['incremental'])
        self.assertLess(hot_work['updates'], cold_work['updates'])
        self.assertLess(hot_work['allocation_states'], cold_work['allocation_states'])

    def test_reference_numeric_boundaries_invalid_zero_and_static_cb_markers(self):
        from tests.test_construction_functional_quality import fixture as qfixture,use
        from ygo_kito.construction_layer_flow import NORMALIZATION_VERSION,functional_asset_version
        from ygo_kito.construction_quality import compare_functional_quality
        task,assets,graph,binder,decks,p=fixture()
        p['pass']=dict(mode='reference_ratio',minimum_reference_ratio=.8,
            reference=dict(reference_id='numeric-contract',deck_sha256=digest(decks[3].to_dict()),source='specified static numerical example'))
        def quality(n,deck,policy,cb='not_run'):
            layers,facts=qfixture([use(str(i),family=str(i)) for i in range(n)],main=list(deck.main),extra=list(deck.extra),side=list(deck.side))
            layers['axis'].update(task=task.to_dict(),logic=graph.to_dict());layers['basic_cb']={'status':cb}
            facts.update(task_sha256=task.sha256,normalization_version=NORMALIZATION_VERSION,
                asset_version=functional_asset_version(binder.semantic_catalog))
            return layers,evaluate_functional_quality(layers,policy=policy,facts=facts)
        for reference,candidate,expected in ((90,60,'pending'),(50,42,'passed'),(70,56,'passed')):
            _,r=quality(reference,decks[3],p);layer,c=quality(candidate,decks[2],p)
            gate=construction_gate(task,decks[2],assets,layer,policy=p,quality=c,reference_quality=r)
            self.assertEqual(gate['status'],expected)
        _,zero=quality(0,decks[3],p);layer,c=quality(1,decks[2],p)
        self.assertIn('reference_score_nonpositive',construction_gate(task,decks[2],assets,layer,policy=p,quality=c,reference_quality=zero)['reasons'])
        bad_deck=replace(decks[3],main=decks[3].main[:-1]);bad_policy=deepcopy(p)
        bad_policy['pass']['reference']['deck_sha256']=digest(bad_deck.to_dict())
        _,r=quality(50,decks[3],bad_policy);r.update(inventory=bad_deck.to_dict(),deck_sha256=digest(bad_deck.to_dict()))
        r['evaluation_id']=digest({k:v for k,v in r.items() if k!='evaluation_id'})
        layer,c=quality(42,decks[2],bad_policy)
        gate=construction_gate(task,decks[2],assets,layer,policy=bad_policy,quality=c,reference_quality=r)
        self.assertEqual(gate['status'],'pending');self.assertTrue(any(s.startswith('reference_invalid:') for s in gate['reasons']))
        q0=quality(0,decks[2],p)[1]
        comparisons=[];scores=[]
        for status in ('not_run','failed','success'):
            _,q=quality(1,decks[2],p,status);scores.append(q['score']);comparisons.append(compare_functional_quality(q0,q))
        self.assertTrue(all(s==scores[0] for s in scores));self.assertTrue(all(c==comparisons[0] for c in comparisons))

    def test_complete_structures_and_removed_support_keep_actual_main_size(self):
        from math import log2
        from ygo_kito.construction_relations import RelationContext,RelationFact,Resource
        cases=[(40,15,15,12,False),(50,0,0,10,False),(60,0,0,18,False),
               (40,0,0,10,False),(40,2,0,12,False),(40,1,0,1,True)]
        values={}
        for n,x,s,e,extra_cost in cases:
            with self.subTest(main=n,extra=x,side=s):
                task,assets,_,binder,_,p=fixture()
                for c in (*range(1,92),*range(101,116),*range(201,216)):
                    assets.rows[c]=dict(assets.rows[3],id=c,name='匿名'+str(c),type=17,desc='Normal text')
                for c in range(101,116):assets.rows[c].update(type=0x41,desc='「匿名4」＋「匿名5」')
                assets.rows[90]['name']='必要配套';assets.rows[101]['name']='额外配套'
                payment='把自己额外卡组的1张「额外配套」卡除外' if extra_cost else '从自己卡组把1张「必要配套」卡送去墓地'
                for c in range(1,e+1):
                    head='自己主要阶段，'+payment if c==1 else '自己主要阶段'
                    assets.rows[c].update(type=33,desc='这个卡名的①效果1回合只能使用1次。①：'+head+'才能发动。抽1张。')
                raw=task.to_dict();raw['sizes'].update(main=n,extra=x,side=s);raw['pool']=sorted(assets.rows)
                raw['goal']['constraints'][0]['maximum']=n
                task=BuildTask.from_dict(raw)
                deck=DeckParts(tuple([*range(1,n),90]),tuple(range(101,101+x)),tuple(range(201,201+s)))
                assets.validate(task,deck)
                phases=tuple(RelationFact('phase:'+str(c),'phase:'+str(c),Resource('activation',event='own_main_phase',
                    reason='not_applicable',attributes=('card:'+str(c),)),'explicit complete phase') for c in range(1,e+1))
                ctx=SimpleNamespace(relations=RelationContext((),(*phases,RelationFact('pay','pay',Resource('payment',reason='cost',attributes=(payment,)),
                    'complete payment under the declared origin'))))
                def score(selected):
                    f=normalize_function_uses(task,selected,binder.semantic_catalog,policy=p,context=ctx)
                    q=evaluate_functional_quality(dict(axis=dict(task=task.to_dict(),inventory=selected.to_dict(),logic=None)),policy=p,facts=f)
                    return f,q
                f,q=score(deck);self.assertTrue(q['complete'])
                self.assertAlmostEqual(q['score']['value'],log2(1+40*e/n))
                missing=replace(deck,extra=(102,)) if extra_cost else replace(deck,main=tuple(91 if c==90 else c for c in deck.main))
                assets.validate(task,missing);failed,bad=score(missing)
                self.assertTrue(bad['complete']);self.assertLess(bad['score']['value'],q['score']['value'])
                self.assertTrue(any(u.self_condition is False for u in failed['uses']))
                values[n,e,x,s]=q['score']['value']
        self.assertEqual(values[40,12,15,15],values[60,18,0,0])
        self.assertEqual(values[40,12,15,15],values[40,12,2,0])
        self.assertAlmostEqual(values[40,10,0,0]-values[50,10,0,0],.289506617194985)

    def test_six_part_payment_fails_and_independent_three_part_mode_survives(self):
        from ygo_kito.construction_relations import RelationContext,RelationFact,Resource
        task,assets,graph,binder,decks,p=fixture()
        assets.rows[2].update(type=17,desc='Normal text')
        for c,name in ((4,'代价素材甲'),(5,'代价素材乙')):assets.rows[c]['name']=name
        payment=lambda n:'从自己手卡把'+str(n)+'张「代价素材」卡送去墓地'
        assets.rows[1].update(type=33,desc='这个卡名的①效果1回合只能使用1次。这个卡名的②效果1回合只能使用1次。①：自己主要阶段，'+payment(6)+'才能发动。抽1张。②：自己主要阶段，'+payment(3)+'才能发动。抽1张。')
        main=list(decks[0].main);main[main.index(5)]=2;deck=replace(decks[0],main=tuple(main));assets.validate(task,deck)
        ctx=SimpleNamespace(relations=RelationContext((),(
            RelationFact('phase','phase',Resource('activation',event='own_main_phase',reason='not_applicable',attributes=('card:1',)),'phase'),
            RelationFact('pay','pay',Resource('payment',reason='cost',attributes=(payment(3),)),'whole three-card payment',quantity=3))))
        facts=normalize_function_uses(task,deck,binder.semantic_catalog,policy=p,context=ctx)
        q=evaluate_functional_quality(dict(axis=dict(task=task.to_dict(),inventory=deck.to_dict(),logic=graph.to_dict())),policy=p,facts=facts)
        self.assertTrue(q['complete']);self.assertEqual(q['score']['value'],1.)
        self.assertEqual(sum(u.self_condition is False for u in facts['uses']),1)
        self.assertEqual(q['losses'][0]['lower'],0.)

    def test_external_target_and_delayed_condition_use_the_supplied_route(self):
        from ygo_kito.construction_relations import InputGroup,Need,RelationContext,RelationFact,Resource
        task,assets,_,binder,decks,p=fixture();assets.rows[2].update(type=17,desc='Normal text')
        assets.rows[1].update(type=33,desc='这个卡名的①效果1回合只能使用1次。①：自己主要阶段，以对方场上的1只怪兽为对象才能发动。抽1张。')
        record,=binder.semantic_catalog.effect_records(1);target,=record['targets']
        phase=RelationFact('phase','phase',Resource('activation',event='own_main_phase',reason='not_applicable',attributes=('card:1',)),'phase')
        legal=Resource('legal_opponent_target',event='current_processing')
        selected=RelationFact('target','target',Resource('target',reason=target.get('reason'),attributes=(target['source'],)),
            'complete supplied opponent target',inputs=InputGroup('all',(Need('legal',legal,mode='presence'),)))
        def evaluate(facts):
            f=normalize_function_uses(task,decks[0],binder.semantic_catalog,policy=p,context=SimpleNamespace(relations=RelationContext((),facts)))
            return next(u for u in f['uses'] if u.contributes).self_condition
        self.assertIs(evaluate((phase,selected,RelationFact('legal','legal',legal,'confirmed applicable target'))),True)
        self.assertIs(evaluate((phase,selected)),False)
        delayed=RelationFact('legal','legal',replace(legal,event='end_phase'),'target is available only at the End Phase')
        self.assertIs(evaluate((phase,selected,delayed)),False)
        future=RelationFact('legal','legal',legal,'target depends on a later processing condition',unknown=('future_condition',))
        self.assertNotIn(evaluate((phase,selected,future)),(True,False))
        self.assertIs(evaluate((phase,)),True)  # Printed response range needs no current opponent object.

    def test_lp_payment_is_complete_and_unpriced_with_joint_contention(self):
        from ygo_kito.construction_relations import InputGroup,Need,RelationContext,RelationFact,Resource,ResourcePool,UseRequirement
        task,assets,_,binder,decks,p=fixture()
        payment='支付2000基本分'
        for c in (1,2):assets.rows[c].update(type=33,desc='这个卡名的①效果1回合只能使用1次。①：自己主要阶段，'+payment+'才能发动。抽1张。')
        phases=tuple(RelationFact('phase:'+str(c),'phase:'+str(c),Resource('activation',event='own_main_phase',reason='not_applicable',
            attributes=('card:'+str(c),)),'phase') for c in (1,2))
        pay=RelationFact('pay','pay',Resource('payment',reason='cost',attributes=(payment,)),'host verified legal LP payment',quantity=2000,output_pool='LP')
        ctx=SimpleNamespace(relations=RelationContext((),(*phases,pay),(ResourcePool('LP','LP that may legally be paid',capacity=2000),)))
        f=normalize_function_uses(task,decks[1],binder.semantic_catalog,policy=p,context=ctx)
        self.assertTrue(all(u.self_condition is True for u in f['uses']))
        self.assertTrue(all(r['resource']['quantity']==2000 and r['kind']=='unpriced_effect' for r in f['unpriced_effects']))
        from math import log2
        q=evaluate_functional_quality(dict(axis=dict(task=task.to_dict(),inventory=decks[1].to_dict(),logic=None)),policy=p,facts=f)
        self.assertAlmostEqual(q['score']['value'],log2(3))
        required=UseRequirement('both',InputGroup('all',tuple(Need('u:'+str(c),Resource('functional_operation',attributes=('catalog:'+str(c)+':1:op:0',)),
            mode='presence') for c in (1,2))),'explicit joint LP payments',functional_use_ids=tuple(u.use_id for u in f['uses']))
        ctx.relations=replace(ctx.relations,uses=(required,))
        joint=normalize_function_uses(task,decks[1],binder.semantic_catalog,policy=p,context=ctx)
        self.assertTrue(all(u.joint_condition is False for u in joint['uses']))
        ctx.relations=replace(ctx.relations,uses=(),pools=(ResourcePool('LP','only 1999 LP may legally be paid',capacity=1999),))
        failed=normalize_function_uses(task,decks[1],binder.semantic_catalog,policy=p,context=ctx)
        self.assertTrue(all(u.self_condition is False for u in failed['uses']))

    def test_schema_two_migration_preserves_progress_and_unknown_slot_sources(self):
        task,assets,graph,binder,decks,p=fixture()
        adapter=ConstructionLayerAdapter(binder)
        row=adapter.evaluate(task,graph,rows_for(task,[decks[1]]),{0:binder(graph,task,decks[1])},[0],policy=p,
            quality_evidence=reviewed(binder.semantic_catalog,p))[1][0]
        legacy=dict(version='construction-quality-evaluation-v3',task_sha256=task.sha256,
            deck_sha256=digest(decks[1].to_dict()),total={'value':73.,'complete':True},
            slot_ledger=[{'status':'unknown','verified':True,'source':'original unresolved slot','card_id':3}],losses=[{'amount':4.}])
        candidate=dict(deck=decks[1].to_dict(),deck_sha256=digest(decks[1].to_dict()),layer_evaluation=row['layer_evaluation'],quality_evaluation=legacy)
        skeleton=dict(deck={'main':[1],'extra':[],'side':[]},source='original goal skeleton')
        state=dict(schema_version=2,task_sha256=task.sha256,logic_sha256=graph.sha256,status='passed',iteration=5,
            candidate_version=1,candidate=candidate,skeleton=skeleton,candidate_cursor=17,stagnation=2,
            quality_policy={'version':'old','source':'saved archive','metrics':[],'quality':{'structure_accepted':True},'pass':{'mode':'absolute','threshold':70}},
            gate={'status':'passed'},retained_candidates=[deepcopy(candidate)],
            handoffs=[dict(role='build_goal',candidate_version=1,input_deck_sha256=None,output_deck_sha256=candidate['deck_sha256'])])
        session=session_for(task,graph)
        restore_progress(session,json.loads(json.dumps(state)),assets,policy=p)
        saved=session.construction_progress
        self.assertEqual((saved['schema_version'],saved['iteration'],saved['candidate_cursor'],saved['stagnation']),(3,5,17,2))
        self.assertEqual(saved['skeleton'],skeleton);self.assertEqual(saved['candidate']['deck'],candidate['deck'])
        self.assertEqual(saved['candidate']['layer_evaluation'],json.loads(json.dumps(row['layer_evaluation'])))
        self.assertEqual(saved['candidate']['stale_quality_evaluation'],legacy)
        self.assertNotIn('quality_evaluation',saved['candidate']);self.assertIsNone(saved['gate'])
        self.assertFalse(saved['quality_migration']['scalar_scores_reused'])
        self.assertFalse(saved['quality_migration']['slot_statuses_inferred'])
        self.assertIn('candidate.stale_quality_evaluation.slot_ledger',saved['quality_migration']['rebind_paths'])

    def test_stale_reference_and_direct_consumers_require_current_normalization(self):
        from ygo_kito.construction_progress import quality_policy
        task,assets,graph,binder,decks,p=fixture()
        p['pass']=dict(mode='reference_ratio',minimum_reference_ratio=.8,
            reference=dict(reference_id='fixed',deck_sha256=digest(decks[3].to_dict()),source='fixture'))
        values=ConstructionLayerAdapter(binder).evaluate(task,graph,rows_for(task,decks),
            {i:binder(graph,task,d) for i,d in enumerate(decks)},list(range(4)),policy=p,
            quality_evidence=reviewed(binder.semantic_catalog,p))[1]
        old=deepcopy(values[3]['quality_evaluation']);old['normalization_version']='old-normalization'
        old['evaluation_id']=digest({k:v for k,v in old.items() if k!='evaluation_id'})
        with self.assertRaisesRegex(ContractError,'normalization'):
            construction_gate(task,decks[3],assets,values[3]['layer_evaluation'],policy=p,quality=old,reference_quality=values[3]['quality_evaluation'])
        candidate=dict(values[2],deck=decks[2].to_dict(),deck_sha256=digest(decks[2].to_dict()))
        state=dict(schema_version=3,task_sha256=task.sha256,logic_sha256=graph.sha256,status='optimizing',iteration=2,
            candidate_version=1,candidate=candidate,quality_policy=p,reference_evaluation=old,gate=None,
            handoffs=[dict(role='build_goal',candidate_version=1,input_deck_sha256=None,output_deck_sha256=candidate['deck_sha256'])])
        session=session_for(task,graph);restore_progress(session,state,assets)
        self.assertIsNone(session.construction_progress['reference_evaluation'])
        self.assertEqual(session.construction_progress['stale_reference_evaluation'],old)
        self.assertEqual(session.construction_progress['candidate']['quality_evaluation'],candidate['quality_evaluation'])
        self.assertEqual(session.construction_progress['stop_reason'],'quality_reevaluation_required')
        with self.assertRaises(ContractError):quality_policy(dict(version='old',source='old',metrics=[],quality={'structure_accepted':True},**{'pass':{'mode':'absolute','threshold':70}}))

    def test_host_policy_reads_actual_references_and_keeps_other_themes_unbound(self):
        from ygo_kito.construction_progress import host_construction_quality
        task,*_ = fixture()
        for period,refid in (('2022-07','main-01-source-v1'),('2022-10','main-02-source-v2')):
            p,reference = host_construction_quality(task,period_id=period,reference_id=refid)
            self.assertEqual(reference['reference_id'],refid)
            self.assertEqual(p['pass']['minimum_reference_ratio'],.8)
            self.assertEqual(p['pass']['reference']['deck_sha256'],digest(reference['deck']))
            self.assertEqual(reference['environment'],task.environment)
            self.assertEqual(p['quality']['theme_rules'],[])
            self.assertGreaterEqual(len(reference['deck']['main']),40)
        p,reference = host_construction_quality(task,period_id='2026-10')
        self.assertEqual(p['pass'],{'mode':'none'});self.assertIsNone(reference)
        for period in ('2022-07','2022-10','2026-10'):
            p,reference=host_construction_quality(task,period_id=period,theme_id='another-theme')
            self.assertEqual(p['quality']['theme_profile']['status'],'unknown')
            self.assertIn('fixed_card_effects_required',p['quality']['theme_profile']['gaps'])
            self.assertEqual(p['pass'],{'mode':'none'});self.assertIsNone(reference)

    def test_non_deck_call_changes_only_the_supported_function(self):
        from ygo_kito.construction_relations import InputGroup,Need,RelationContext,RelationFact,Resource
        task,assets,_,binder,decks,p = fixture()
        assets.rows[3].update(name='通用接收方',type=33,desc='这个卡名的①效果1回合只能使用1次。这个卡名的②效果1回合只能使用1次。①：这张卡特殊召唤成功的场合才能发动。抽1张。②：自己主要阶段才能发动。从卡组上面把2张卡送去墓地。')
        assets.rows[2]['desc'] = '这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。从自己墓地把1张「通用接收方」特殊召唤。'
        access = Resource('card_access',zone='grave',attributes=('card:3',))
        phases = tuple(RelationFact('phase:'+str(c),'phase:'+str(c),Resource('activation',event='own_main_phase',
            reason='not_applicable',attributes=('card:'+str(c),)),'explicit function support',
            inputs=InputGroup('all',(Need('access',access,mode='presence'),)) if c==2 else None) for c in (2,3))
        ctx = SimpleNamespace(relations=RelationContext((),(*phases,RelationFact('access','access',access,'supplied grave recipient'))))
        def modes(deck):
            f = normalize_function_uses(task,deck,binder.semantic_catalog,policy=p,context=ctx)
            return {f['use_details'][u.use_id]['semantics']['kind']:u.valuation_mode for u in f['uses']
                    if f['use_details'][u.use_id]['card_id']==3}
        self.assertEqual(modes(decks[1]),{'draw':'called','send_grave':'main_density'})
        removed = replace(decks[1],main=tuple(3 if c==2 else c for c in decks[1].main))
        self.assertEqual(modes(removed)['draw'],'main_density')

    def test_non_grave_themes_and_empty_theme_share_the_same_evaluator(self):
        from ygo_kito.construction_relations import RelationContext,RelationFact,Resource
        task,assets,_,binder,decks,p = fixture()
        assets.rows[3]['name'] = '匿名支援'
        assets.rows[1].update(type=33,desc='这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。抽1张。')
        assets.rows[2]['desc'] = '这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。从自己手卡把1张「匿名支援」特殊召唤。'
        seeds = tuple(RelationFact('phase:'+str(c),'phase:'+str(c),Resource('activation',event='own_main_phase',
            origin='field',reason='not_applicable',attributes=('card:'+str(c),)),'complete supplied function support') for c in (1,2))
        ctx = SimpleNamespace(relations=RelationContext((),seeds))
        def score(policy):
            f = normalize_function_uses(task,decks[1],binder.semantic_catalog,policy=policy,context=ctx)
            q = evaluate_functional_quality(dict(axis=dict(task=task.to_dict(),inventory=decks[1].to_dict(),logic=None)),policy=policy,facts=f)
            return f,q
        _,plain = score(p)
        p['quality']['theme_rules'] = [dict(rule_id='draw',increment=1,predicate={'kind':'draw'}),
            dict(rule_id='summoning',increment=2,predicate={'kind':'special_summon','from_zone':'hand','to_zone':'field'})]
        themed,q = score(p)
        self.assertTrue(q['complete'])
        self.assertGreater(q['score']['value'],plain['score']['value'])
        self.assertEqual({r for u in themed['uses'] for r,_ in u.theme_conditions},{'draw','summoning'})
        self.assertTrue(all(themed['variables'][v] is True for u in themed['uses'] for _,v in u.theme_conditions))
        assets.rows[3]['name'] = '更名支援'
        assets.rows[2]['desc'] = assets.rows[2]['desc'].replace('匿名支援','更名支援')
        _,renamed = score(p)
        self.assertEqual(renamed['score'],q['score'])

    def test_side_alternatives_fit_individually_but_joint_sources_need_capacity(self):
        from ygo_kito.construction_relations import InputGroup,JointConstraint,Need,RelationContext,RelationFact,Resource,UseRequirement
        task,assets,_,binder,decks,p = fixture()
        raw = task.to_dict();raw['sizes'].update(extra=1,side=2);raw['pool'].extend([101,102,103]);task=BuildTask.from_dict(raw)
        assets.rows[101] = dict(assets.rows[3],id=101,type=0x41,name='无效果额外资源',desc='「匿名素材」＋「其他素材」')
        for c in (102,103):
            assets.rows[c] = dict(assets.rows[2],id=c,type=0x61,name='额外工具'+str(c),
                desc='这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。抽1张。')
        assets.rows[2]['desc'] = 'Normal text';assets.rows[2]['type']=17
        deck=replace(decks[0],extra=(101,),side=(102,103));assets.validate(task,deck)
        phases=tuple(RelationFact('phase:'+str(c),'phase:'+str(c),Resource('activation',event='own_main_phase',
            reason='not_applicable',attributes=('card:'+str(c),)),'supplied direction entry') for c in (102,103))
        ctx=SimpleNamespace(relations=RelationContext((),phases))
        f=normalize_function_uses(task,deck,binder.semantic_catalog,policy=p,context=ctx)
        layers=dict(axis=dict(task=task.to_dict(),inventory=deck.to_dict(),logic=None))
        q=evaluate_functional_quality(layers,policy=p,facts=f)
        self.assertTrue(q['complete']);self.assertEqual(q['score']['value'],1.)
        self.assertEqual(q['side_directions']['going_first']['resident'],[0.,0.])
        side={f['use_details'][u.use_id]['card_id']:u for u in f['uses'] if u.scope_id=='going_first'}
        uses=tuple(UseRequirement('tool:'+str(c),InputGroup('all',(Need('tool:'+str(c),
            Resource('functional_operation',attributes=('catalog:'+str(c)+':1:op:0',)),mode='presence'),)),
            'explicit joint tools',required=False,functional_use_ids=(side[c].use_id.removesuffix(':going_first'),)) for c in (102,103))
        ctx.relations=replace(ctx.relations,uses=uses,constraints=(JointConstraint('both',tuple(u.use_id for u in uses),'all','explicit common use'),))
        joint=normalize_function_uses(task,deck,binder.semantic_catalog,policy=p,context=ctx)
        self.assertTrue(all(u.joint_condition is False for u in joint['uses'] if u.scope_id!='resident' and u.contributes))
        self.assertEqual(evaluate_functional_quality(layers,policy=p,facts=joint)['score']['value'],0.)
        assets.rows[104]=dict(assets.rows[101],id=104,name='无效果填充')
        task=replace(task,sizes={**task.sizes,'extra':2},pool=tuple([*task.pool,104]));deck=replace(deck,extra=(101,104))
        assets.validate(task,deck)
        coexist=normalize_function_uses(task,deck,binder.semantic_catalog,policy=p,context=ctx)
        self.assertTrue(all(u.joint_condition is True for u in coexist['uses'] if u.scope_id!='resident' and u.contributes))
        ctx.relations=replace(ctx.relations,constraints=(*ctx.relations.constraints,JointConstraint('mutual',tuple(u.use_id for u in uses),
            'incompatible','the supplied modes are mutually exclusive')))
        excluded=normalize_function_uses(task,deck,binder.semantic_catalog,policy=p,context=ctx)
        self.assertTrue(all(u.joint_condition is False for u in excluded['uses'] if u.scope_id!='resident' and u.contributes))

    def test_declared_normal_entry_combines_only_when_functions_are_joint(self):
        from ygo_kito.construction_relations import InputGroup, Need, RelationContext, RelationFact, Resource, UseRequirement
        task, assets, _, binder, decks, p = fixture()
        for c in (1,2):
            assets.rows[c].update(type=33,desc='这个卡名的①效果1回合只能使用1次。①：这张卡召唤·特殊召唤成功的场合才能发动。抽1张。')
        events = []
        for c in (1,2):
            normal = Resource('activation',event='normal_summon',zone='field',reason='not_applicable',attributes=('card:'+str(c),))
            events.extend((RelationFact('normal:'+str(c),'normal:'+str(c),normal,'declared normal entry',c),
                RelationFact('entry:'+str(c),'entry:'+str(c),replace(normal,event='normal_or_special_summon'),
                    'only the normal route is supplied',c,inputs=InputGroup('all',(Need('normal:'+str(c),normal,mode='presence'),)))))
        ctx = SimpleNamespace(relations=RelationContext((),tuple(events)))
        initial = normalize_function_uses(task,decks[1],binder.semantic_catalog,policy=p,context=ctx)
        self.assertTrue(all(u.self_condition is True for u in initial['uses']))
        required = tuple(UseRequirement('use:'+str(i),InputGroup('all',(Need('use:'+str(i),
            Resource('functional_operation',attributes=('catalog:'+str(initial['use_details'][u.use_id]['card_id'])+':1:op:0',)),mode='presence'),)),
            'original task requires both normal entries',functional_use_ids=(u.use_id,)) for i,u in enumerate(initial['uses']))
        ctx.relations = replace(ctx.relations,uses=required)
        together = normalize_function_uses(task,decks[1],binder.semantic_catalog,policy=p,context=ctx)
        self.assertTrue(any(h['requirement_id']=='joint_required' and h['condition'] is False for h in together['hard_requirements']))
        bonus = RelationFact('bonus','bonus',Resource('normal_summon_allowance',attributes=('controller:self',)),
            'one additional normal summon with supplied applicability')
        ctx.relations = replace(ctx.relations,facts=(*ctx.relations.facts,bonus))
        permitted = normalize_function_uses(task,decks[1],binder.semantic_catalog,policy=p,context=ctx)
        self.assertTrue(all(h['condition'] is True for h in permitted['hard_requirements']))

    def test_extra_cost_resource_reaches_final_score_without_extra_function(self):
        from ygo_kito.construction_relations import RelationContext, RelationFact, Resource
        task, assets, _, binder, decks, p = fixture()
        raw = task.to_dict(); raw['sizes']['extra'] = 1; raw['pool'].append(101)
        task = BuildTask.from_dict(raw)
        payment = '把自己额外卡组的1张卡除外'
        assets.rows[1].update(type=33,desc='这个卡名的①效果1回合只能使用1次。①：自己主要阶段，'+payment+'才能发动。抽1张。')
        assets.rows[2]['desc'] = 'Normal text'
        assets.rows[101] = dict(assets.rows[1],id=101,name='匿名代价资源',type=0x41,desc='「匿名素材」＋「其他素材」')
        deck = replace(decks[0],extra=(101,))
        ctx = SimpleNamespace(relations=RelationContext((),(
            RelationFact('phase','phase',Resource('activation',event='own_main_phase',reason='not_applicable',
                attributes=('card:1',)),'explicit phase'),
            RelationFact('payment','payment',Resource('payment',reason='cost',attributes=(payment,)),'explicit complete payment'))))
        def score(selected):
            facts = normalize_function_uses(task,selected,binder.semantic_catalog,policy=p,context=ctx)
            layers = dict(axis=dict(task=task.to_dict(),inventory=selected.to_dict(),logic=None))
            return facts,evaluate_functional_quality(layers,policy=p,facts=facts)
        facts,good = score(deck)
        self.assertTrue(good['complete'])
        self.assertGreater(good['score']['value'],0.)
        self.assertEqual({facts['use_details'][u.use_id]['card_id'] for u in facts['uses'] if u.contributes},{1})
        failed,bad = score(replace(deck,extra=()))
        self.assertEqual(bad['score']['value'],0.)
        self.assertIs(next(u for u in failed['uses'] if u.contributes).self_condition,False)

    def test_unknown_intrinsic_material_clause_does_not_block_unrelated_effect(self):
        from ygo_kito.construction_relations import RelationContext, RelationFact, Resource
        task, assets, _, binder, decks, p = fixture()
        draw = '这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。抽1张。'
        assets.rows[1].update(type=33, desc=draw)
        assets.rows[2]['desc'] = draw
        phases = tuple(RelationFact('phase:'+str(c), 'phase:'+str(c), Resource('activation', event='own_main_phase',
            reason='not_applicable', attributes=('card:'+str(c),)), 'explicit activation support') for c in (1,2))
        ctx = SimpleNamespace(relations=RelationContext((), phases))
        deck = decks[1]
        layers = dict(axis=dict(task=task.to_dict(), inventory=deck.to_dict(), logic=None))
        baseline = evaluate_functional_quality(layers, policy=p, facts=normalize_function_uses(
            task, deck, binder.semantic_catalog, policy=p, context=ctx))
        assets.rows[1]['desc'] = '这张卡有指示物的场合，不能作为融合素材。' + draw
        facts = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, context=ctx)
        result = evaluate_functional_quality(layers, policy=p, facts=facts)
        self.assertTrue(baseline['complete'])
        self.assertTrue(result['complete'])
        self.assertEqual(result['score'], baseline['score'])
        self.assertEqual(facts['scope_status']['impacts'], 'evaluated')
        self.assertTrue(any(r['kind']=='cannot_be_fusion_material' for d in facts['use_details'].values() for r in d['restrictions']))

    def test_processing_lock_checks_whole_payment_and_effect_reason_separately(self):
        from ygo_kito.construction_layer_flow import _bind_mandatory_impacts
        from tests.test_construction_functional_quality import fixture as qfixture, use
        source = use('lock', family='adoption', contributes=False, required=True, requirement_origin='original task adopts lock')
        targets = [use(k, family=k) for k in ('hand-cost', 'deck-cost', 'effect', 'unknown-cost')]
        layers, facts = qfixture([source, *targets])
        rule = dict(kind='cannot_send_grave', source='complete structured payment restriction', scope='player',
            controller='self', condition='effect_activation', duration='turn', whole_turn=True,
            from_zones=['hand'], to_zone='grave', reason='cost')
        facts.update(coverage_details={}, use_details={
            'lock':dict(restrictions=[rule], semantics={'kind':'effect_adoption'}),
            **{k:dict(restrictions=[], semantics=dict(kind='draw', from_zones=['deck'], to_zone='hand', owner='self', reason='effect'),
                operation={'controller':'self', 'phase':'resolution'}, costs=[dict(kind='send_grave', from_zones=[origin],
                    to_zone='grave', owner='opponent', reason=reason)])
               for k, origin, reason in (('hand-cost','hand','cost'), ('deck-cost','deck','cost'), ('unknown-cost','hand',None))},
            'effect':dict(restrictions=[], semantics=dict(kind='send_grave', from_zones=['hand'], to_zone='grave',
                owner='self', reason='effect'), operation={'controller':'self', 'phase':'resolution'})})
        def condition(key, value, reason, evidence):
            if value is not None:
                return value
            facts['variables'][key] = None
            return key
        p = policy(); p['pass'] = p.pop('pass_')
        _bind_mandatory_impacts(facts, None, condition)
        self.assertEqual({uid for i in facts['impacts'] for uid in i.affected_use_ids}, {'hand-cost','unknown-cost'})
        result = evaluate_functional_quality(layers, policy=p, facts=facts)
        self.assertEqual((result['score']['lower'],result['score']['upper']), (2.,3.))
        rule['reason'] = 'effect'
        facts['impacts'] = []
        _bind_mandatory_impacts(facts, None, condition)
        self.assertEqual({uid for i in facts['impacts'] for uid in i.affected_use_ids}, {'effect','unknown-cost'})
        facts['use_details']['effect']['operation']['controller'] = 'opponent'
        facts['impacts'] = []
        _bind_mandatory_impacts(facts, None, condition)
        self.assertEqual({uid for i in facts['impacts'] for uid in i.affected_use_ids}, {'unknown-cost'})

    def test_activation_and_return_locks_keep_actual_processing_conditions(self):
        from ygo_kito.construction_layer_flow import _bind_mandatory_impacts
        from tests.test_construction_functional_quality import fixture as qfixture, use
        source = use('lock', family='adoption', contributes=False, required=True, requirement_origin='original task adopts lock')
        targets = [use(k, family=k) for k in ('yes', 'other', 'unknown', 'unrelated')]
        for kind in ('cannot_activate', 'cannot_return', 'cannot_banish', 'cannot_special_summon'):
            with self.subTest(kind=kind):
                layers, facts = qfixture([source, *targets])
                rule = dict(kind=kind, source='complete structured processing restriction', scope='player',
                    controller='self', condition='effect_activation', duration='turn', whole_turn=True)
                if kind == 'cannot_return':
                    rule['to_zone'] = 'deck'
                if kind in ('cannot_banish', 'cannot_special_summon'):
                    rule['from_zones'] = ['grave']
                specs = {
                    'cannot_activate': (('draw','resolution'),('draw','continuous'),('draw',None),('draw','summon_procedure')),
                    'cannot_return': (('return_deck','deck'),('return_hand','hand'),('return_deck',None),('draw','hand')),
                    'cannot_banish': (('banish',['grave']),('banish',['hand']),('banish',['grave','hand']),('draw',['deck'])),
                    'cannot_special_summon': (('special_summon',['grave']),('special_summon',['hand']),('special_summon',[]),('draw',['deck']))}[kind]
                details = {'lock':dict(restrictions=[rule], semantics={'kind':'effect_adoption'})}
                for key, (action, value) in zip(('yes','other','unknown','unrelated'), specs):
                    semantics = dict(kind=action, owner='self', reason='effect')
                    operation = {'controller':'self', 'phase':'resolution'}
                    if kind == 'cannot_activate':
                        operation['phase'] = value
                    elif kind == 'cannot_return':
                        semantics['to_zone'] = value
                    else:
                        semantics['from_zones'] = value
                    details[key] = dict(restrictions=[], semantics=semantics, operation=operation)
                facts.update(coverage_details={}, use_details=details)
                def condition(key, value, reason, evidence):
                    if value is not None:
                        return value
                    facts['variables'][key] = None
                    return key
                p = policy(); p['pass'] = p.pop('pass_')
                _bind_mandatory_impacts(facts, None, condition)
                self.assertEqual({uid for i in facts['impacts'] for uid in i.affected_use_ids}, {'yes','unknown'})
                result = evaluate_functional_quality(layers, policy=p, facts=facts)
                self.assertEqual((result['score']['lower'],result['score']['upper']), (2.,3.))

    def test_optional_raw_unknown_restriction_does_not_defer_unrelated_draw(self):
        from ygo_kito.construction_relations import InputGroup, Need, RelationContext, RelationFact, Resource, UseRequirement
        task, assets, _, binder, decks, p = fixture()
        assets.rows[1].update(type=33, desc='①：这张卡在怪兽区域存在，自己不能在抽卡阶段以外抽卡。')
        assets.rows[2]['desc'] = '这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。抽1张。'
        phase = RelationFact('phase', 'phase', Resource('activation', event='own_main_phase', reason='not_applicable',
            attributes=('card:2',)), 'explicit activation support for the draw')
        ctx = SimpleNamespace(relations=RelationContext((), (phase,)))
        deck = decks[1]
        layers = dict(axis=dict(task=task.to_dict(), inventory=deck.to_dict(), logic=None))
        facts = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, context=ctx)
        adoption, = (u for u in facts['uses'] if not u.contributes)
        result = evaluate_functional_quality(layers, policy=p, facts=facts)
        self.assertEqual(facts['scope_status']['impacts'], 'evaluated')
        self.assertFalse(facts['impacts'])
        self.assertTrue(result['complete'])
        self.assertEqual(result['score']['value'], 1.)
        self.assertTrue(any(v is None for v in facts['variables'].values()))
        self.assertTrue(all(r['status'] == 'not_adopted' for r in facts['use_details'][adoption.use_id]['restriction_checks']))
        required = UseRequirement('adopt', InputGroup('all', (Need('adopt',
            Resource('functional_operation', attributes=('catalog:1:1:adoption',)), mode='presence'),)),
            'original task requires the continuous effect', functional_use_ids=(adoption.use_id,))
        ctx.relations = replace(ctx.relations, uses=(required,))
        required_facts = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, context=ctx)
        required_result = evaluate_functional_quality(layers, policy=p, facts=required_facts)
        self.assertTrue(required_facts['impacts'])
        self.assertFalse(required_result['complete'])
        self.assertEqual(next(r for r in required_result['hard_requirements'] if r['requirement_id']=='adopt')['status'], 'unknown')

    def test_intrinsic_recipient_prohibition_reaches_required_summon_and_trigger(self):
        from ygo_kito.construction_relations import InputGroup, Need, RelationContext, RelationFact, Resource, UseRequirement
        task, assets, _, binder, decks, p = fixture()
        assets.rows[2]['desc'] = ('这个卡名的①效果1回合只能使用1次。'
            '①：自己主要阶段才能发动。从自己墓地把1只「召唤对象」特殊召唤。')
        trigger = '这个卡名的①效果1回合只能使用1次。①：这张卡特殊召唤成功的场合才能发动。抽1张。'
        assets.rows[3].update(name='召唤对象', desc=trigger)
        phase = RelationFact('phase', 'phase', Resource('activation', event='own_main_phase', reason='not_applicable',
            attributes=('card:2',)), 'explicit source activation support')
        ctx = SimpleNamespace(relations=RelationContext((), (phase,)))
        deck = decks[1]
        layers = dict(axis=dict(task=task.to_dict(), inventory=deck.to_dict(), logic=None))
        allowed = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, context=ctx)
        caller, = (u for u in allowed['uses'] if allowed['use_details'][u.use_id]['card_id'] == 2)
        receiver, = (u for u in allowed['uses'] if allowed['use_details'][u.use_id]['card_id'] == 3)
        self.assertIs(caller.self_condition, True)
        self.assertIs(receiver.self_condition, True)
        required = UseRequirement('summon-recipient', InputGroup('all', (Need('summon',
            Resource('functional_operation', attributes=('catalog:2:1:op:0',)), mode='presence'),)),
            'original task requires this actual summon', functional_use_ids=(caller.use_id,))
        ctx.relations = replace(ctx.relations, uses=(required,))
        assets.rows[3]['desc'] = '这张卡不能特殊召唤。' + trigger
        blocked = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, context=ctx)
        result = evaluate_functional_quality(layers, policy=p, facts=blocked)
        self.assertIs(next(u for u in blocked['uses'] if u.use_id == caller.use_id).self_condition, False)
        self.assertEqual(next(r for r in result['hard_requirements'] if r['requirement_id'] == 'summon-recipient')['status'], 'failed')
        receiver, = (u for u in blocked['uses'] if blocked['use_details'][u.use_id]['card_id'] == 3)
        self.assertIs(receiver.self_condition, False)
        self.assertFalse(any(':receiver:3:' in s for s in blocked['use_details'][receiver.use_id]['relation']['suppliers']))
        self.assertEqual(blocked['scope_status']['impacts'], 'evaluated')
        supplied_event = RelationFact('special-success', 'special-success', Resource('activation', event='special_summon',
            zone='field', reason='not_applicable', attributes=('card:3',)), 'host supplies a summon event')
        injected = SimpleNamespace(relations=replace(ctx.relations, facts=(phase, supplied_event)))
        impossible = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, context=injected)
        own, = (u for u in impossible['uses'] if impossible['use_details'][u.use_id]['card_id'] == 3)
        self.assertIs(own.self_condition, False)
        assets.rows[3]['desc'] = '这张卡不能特殊召唤，但可以用指定效果召唤。' + trigger
        uncertain = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, context=ctx)
        evaluated = evaluate_functional_quality(layers, policy=p, facts=uncertain)
        self.assertEqual(next(r for r in evaluated['hard_requirements'] if r['requirement_id'] == 'summon-recipient')['status'], 'unknown')
        self.assertEqual(uncertain['scope_status']['impacts'], 'evaluated')
        self.assertFalse(evaluated['complete'])
        checks = uncertain['use_details'][caller.use_id]['inventory_checks']['objects']['requirements'][0]['restriction_checks']
        self.assertTrue(all('但可以用指定效果召唤' in c['restriction']['source'] for c in checks))

    def test_conditional_fusion_material_reaches_evaluation_without_global_exclusion(self):
        from ygo_kito.construction_relations import InputGroup, Need, RelationContext, RelationFact, Resource, UseRequirement
        task, assets, _, binder, decks, p = fixture()
        raw = task.to_dict(); raw['sizes']['extra'] = 1; raw['pool'].append(101)
        task = BuildTask.from_dict(raw)
        assets.rows[1].update(name='条件素材', type=33,
            desc='这张卡在墓地存在，不能作为融合素材。①：自己主要阶段才能发动。抽1张。')
        assets.rows[4]['name'] = '另一素材'
        assets.rows[101] = dict(assets.rows[1], id=101, name='融合目标', type=0x41,
            desc='「条件素材」＋「另一素材」\n这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。抽1张。')
        deck = replace(decks[1], extra=(101,))
        phase = RelationFact('extra-phase', 'extra-phase', Resource('activation', event='own_main_phase', reason='not_applicable',
            attributes=('card:101',)), 'explicit extra effect activation support')
        ctx = SimpleNamespace(relations=RelationContext((), (phase,)))
        facts = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, context=ctx)
        target, = (u for u in facts['uses'] if facts['use_details'][u.use_id]['card_id'] == 101)
        material = facts['use_details'][target.use_id]['inventory_checks']['materials']
        self.assertEqual((material['status'], material['shortfall']), ('unknown', 0))
        self.assertIsNot(target.self_condition, True)
        self.assertIsNot(target.self_condition, False)
        required = UseRequirement('fusion-use', InputGroup('all', (Need('fusion-use',
            Resource('functional_operation', attributes=('catalog:101:1:op:0',)), mode='presence'),)),
            'original task requires the actual extra function', functional_use_ids=(target.use_id,))
        ctx.relations = replace(ctx.relations, uses=(required,))
        layers = dict(axis=dict(task=task.to_dict(), inventory=deck.to_dict(), logic=None))
        result = evaluate_functional_quality(layers, policy=p, facts=normalize_function_uses(
            task, deck, binder.semantic_catalog, policy=p, context=ctx))
        self.assertEqual(next(r for r in result['hard_requirements'] if r['requirement_id'] == 'fusion-use')['status'], 'unknown')
        assets.rows[1]['desc'] = assets.rows[1]['desc'].replace('这张卡在墓地存在，不能作为融合素材', '这张卡不能作为融合素材')
        blocked = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, context=ctx)
        target, = (u for u in blocked['uses'] if blocked['use_details'][u.use_id]['card_id'] == 101)
        self.assertIs(target.self_condition, False)
        failed = evaluate_functional_quality(layers, policy=p, facts=blocked)
        self.assertEqual(next(r for r in failed['hard_requirements'] if r['requirement_id'] == 'fusion-use')['status'], 'failed')
        # The material prohibition does not erase this card's own draw.
        own, = (u for u in blocked['uses'] if blocked['use_details'][u.use_id]['card_id'] == 1)
        self.assertIsNot(own.self_condition, False)

    def test_raw_normal_and_attack_locks_apply_only_to_matching_actor_and_use(self):
        from ygo_kito.construction_layer_flow import _bind_mandatory_impacts
        from ygo_kito.construction_relations import RelationContext, RelationFact, Resource
        from tests.test_construction_functional_quality import fixture as qfixture, use
        for body, action, actor in (('自己不能通常召唤（盖放）', 'normal_summon', 'self'),
                                    ('对方不能攻击宣言', 'attack', 'opponent')):
            with self.subTest(body=body):
                task, assets, _, binder, decks, p = fixture()
                assets.rows[1].update(type=33, desc='①：这张卡在怪兽区域存在，' + body + '。')
                record, = binder.semantic_catalog.effect_records(1)
                state = RelationFact('field', 'field', Resource('effect_applicability', zone='field',
                    attributes=('card:1', 'controller:self', 'state:monster_zone')), 'explicit own source state')
                raw = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p,
                    context=SimpleNamespace(relations=RelationContext((), (state,))))
                adoption, = (u for u in raw['uses'] if not u.contributes)
                self.assertIs(adoption.self_condition, True)
                self.assertEqual(raw['scope_status']['impacts'], 'evaluated')
                source = use('source', family='adoption', contributes=False, required=True,
                    requirement_origin='original task adopts this field source')
                targets = [use(k, family=k, required=k == 'affected',
                    requirement_origin='original task requires this action' if k == 'affected' else None)
                    for k in ('affected', 'other-actor', 'unrelated', 'set')]
                layers, facts = qfixture([source, *targets])
                facts.update(coverage_details={}, use_details={
                    'source':dict(restrictions=record['restrictions'], applicability='this_card_in_monster_zone',
                        semantics={'kind':'effect_adoption'}),
                    **{k:dict(restrictions=[], semantics=dict(kind=kind), operation={'controller':who})
                       for k, kind, who in (('affected', action, actor),
                           ('other-actor', action, 'opponent' if actor == 'self' else 'self'),
                           ('unrelated', 'draw', 'self'), ('set', 'normal_set', 'self'))}})
                def condition(key, value, reason, evidence):
                    if value is not None:
                        return value
                    facts['variables'][key] = None
                    return key
                _bind_mandatory_impacts(facts, None, condition)
                affected = {uid for impact in facts['impacts'] for uid in impact.affected_use_ids}
                self.assertEqual(affected, {'affected', 'set'} if action == 'normal_summon' else {'affected'})
                result = evaluate_functional_quality(layers, policy=p, facts=facts)
                self.assertEqual(result['score']['value'], 2. if action == 'normal_summon' else 3.)
                self.assertEqual(next(r for r in result['hard_requirements'] if r['requirement_id'] == 'affected')['status'], 'failed')
                self.assertEqual(sum(r['lower'] for r in result['loss_records']), 2. if action == 'normal_summon' else 1.)
                if action == 'normal_summon':
                    facts['impacts'] = []
                    facts['use_details']['source']['restrictions'] = [dict(kind='cannot_normal_summon',
                        source='reviewed complete normal-summon lock from hand', scope='player', controller='self',
                        condition='effect_activation', duration='turn', whole_turn=True, includes_set=True, from_zones=['hand'])]
                    facts['use_details']['affected']['semantics']['from_zones'] = ['hand']
                    facts['use_details']['other-actor']['operation']['controller'] = 'self'
                    facts['use_details']['other-actor']['semantics']['from_zones'] = ['grave']
                    facts['use_details']['set']['semantics']['from_zones'] = ['hand', 'grave']
                    _bind_mandatory_impacts(facts, None, condition)
                    mixed = evaluate_functional_quality(layers, policy=p, facts=facts)
                    self.assertEqual({uid for i in facts['impacts'] for uid in i.affected_use_ids}, {'affected', 'set'})
                    self.assertEqual((mixed['score']['lower'], mixed['score']['upper']), (2., 3.))

    def test_raw_cross_zone_return_reaches_bound_requirement_and_evaluation(self):
        from ygo_kito.construction_relations import InputGroup, Need, PoolRecovery, RelationContext, RelationFact, Resource, ResourcePool, UseRequirement
        task, assets, graph, binder, decks, p = fixture()
        assets.rows[1]['name'] = '跨区对象'
        assets.rows[2]['desc'] = '这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。从自己墓地把1张「跨区对象」加入手卡。'
        initial = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p)
        uid = next(u.use_id for u in initial['uses'] if initial['use_details'][u.use_id]['card_id'] == 2)
        first = Need('first', Resource('physical-call', zone='deck'), destination='grave')
        last = Need('last', replace(first.resource, zone='hand'))
        required = UseRequirement('cross-zone', InputGroup('all', (first, last)), 'original task crosses zones', functional_use_ids=(uid,))
        supplied = tuple(RelationFact(z, z, replace(first.resource, zone=z), 'explicit initial access', output_pool='stock')
                         for z in ('deck', 'hand'))
        phase = RelationFact('phase', 'phase', Resource('activation', event='own_main_phase', reason='not_applicable',
            attributes=('card:2',)), 'explicit activation support')
        ctx = SimpleNamespace(relations=RelationContext((required,), (*supplied, phase), (
            ResourcePool('stock', 'one physical target', inventory=(('main', 1),), recoveries=(
                PoolRecovery('catalog:2:1:op:0', 'first', 'last'),)),)))
        layers = dict(axis=dict(task=task.to_dict(), inventory=decks[1].to_dict(), logic=graph.to_dict()))
        facts = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p, context=ctx)
        result = evaluate_functional_quality(layers, policy=p, facts=facts)
        self.assertEqual(next(r for r in result['hard_requirements'] if r['requirement_id'] == 'cross-zone')['status'], 'satisfied')
        witness = next(b for g in facts['use_details'][uid]['joint_groups'] for b in g.get('branches', ())
                       if b['status'] == 'supported' and b.get('transfer_states'))
        self.assertEqual(witness['transfer_states'][0]['destination'], 'hand')
        stale = replace(required, inputs=InputGroup('all', (first, last, Need('old-zone', first.resource))))
        invalid = SimpleNamespace(relations=replace(ctx.relations, uses=(stale,)))
        failed = evaluate_functional_quality(layers, policy=p, facts=normalize_function_uses(
            task, decks[1], binder.semantic_catalog, policy=p, context=invalid))
        self.assertEqual(next(r for r in failed['hard_requirements'] if r['requirement_id'] == 'cross-zone')['status'], 'failed')
        self.assertGreater(result['score']['upper'], failed['score']['upper'])

    def test_leave_banish_lifecycle_reaches_bound_evaluation(self):
        from ygo_kito.construction_relations import InputGroup, Need, PoolRecovery, RelationContext, RelationFact, Resource, ResourcePool, UseRequirement
        task, assets, graph, binder, decks, p = fixture()
        assets.rows[1]['name'] = '离场对象'
        summon = '这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。从自己墓地把1只「离场对象」特殊召唤。'
        assets.rows[2]['desc'] = summon
        assets.rows[3]['desc'] = '这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。从自己墓地把1张「离场对象」加入手卡。'
        initial = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p)
        uid = next(u.use_id for u in initial['uses'] if initial['use_details'][u.use_id]['card_id'] == 3)
        first = Need('first', Resource('physical-call', zone='deck'), destination='grave')
        field = Need('field', replace(first.resource, zone='field'), destination='grave')
        last = Need('last', replace(first.resource, zone='hand'))
        required = UseRequirement('grave-continuation', InputGroup('all', (first, field, last)),
            'original task needs the actual grave continuation', functional_use_ids=(uid,))
        supplied = tuple(RelationFact(z, z, replace(first.resource, zone=z), 'explicit initial access', output_pool='stock')
                         for z in ('deck', 'field', 'hand'))
        phases = tuple(RelationFact('phase:' + str(c), 'phase:' + str(c), Resource('activation', event='own_main_phase',
            reason='not_applicable', attributes=('card:' + str(c),)), 'explicit activation support') for c in (2, 3))
        ctx = SimpleNamespace(relations=RelationContext((required,), (*supplied, *phases), (
            ResourcePool('stock', 'one physical target', inventory=(('main', 1),), recoveries=(
                PoolRecovery('catalog:2:1:op:0', 'first', 'field'),
                PoolRecovery('catalog:3:1:op:0', 'field', 'last'))),)))
        layers = dict(axis=dict(task=task.to_dict(), inventory=decks[1].to_dict(), logic=graph.to_dict()))
        ordinary = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p, context=ctx)
        before = evaluate_functional_quality(layers, policy=p, facts=ordinary)
        self.assertEqual(next(r for r in before['hard_requirements'] if r['requirement_id'] == 'grave-continuation')['status'], 'satisfied')
        assets.rows[2]['desc'] = summon + '这个效果特殊召唤的怪兽从场上离开的场合除外。'
        constrained = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p, context=ctx)
        after = evaluate_functional_quality(layers, policy=p, facts=constrained)
        self.assertEqual(next(r for r in after['hard_requirements'] if r['requirement_id'] == 'grave-continuation')['status'], 'failed')
        self.assertGreater(before['score']['upper'], after['score']['upper'])
        self.assertIn("leave_fact_id", repr(constrained['use_details'][uid]['joint_groups']))
        self.assertIn("catalog:2:1:op:0", repr(constrained['use_details'][uid]['joint_groups']))
        self.assertFalse(any(d['semantics']['kind'] == 'banish' for d in constrained['use_details'].values()))
        self.assertEqual(constrained['scope_status']['impacts'], 'evaluated')
        source = next(d for d in constrained['use_details'].values() if d['card_id'] == 2)
        self.assertEqual(source['semantics']['kind'], 'special_summon')

    def test_raw_non_scoring_adoption_binds_impact_and_source_removal(self):
        from ygo_kito.construction_relations import InputGroup, Need, RelationContext, RelationFact, Resource, UseRequirement
        task, assets, _, binder, decks, p = fixture()
        assets.rows[1].update(type=33, desc='①：这张卡在怪兽区域存在，自己不能从额外卡组特殊召唤。')
        assets.rows[2]['desc'] = ('这个卡名的①效果1回合只能使用1次。这个卡名的②效果1回合只能使用1次。'
            '①：自己主要阶段才能发动。从额外卡组把1只融合怪兽特殊召唤。②：自己主要阶段才能发动。抽1张。')
        state = RelationFact('field', 'field', Resource('effect_applicability', zone='field',
            attributes=('card:1', 'controller:self', 'state:monster_zone')), 'reviewed own monster-zone state')
        ctx = SimpleNamespace(relations=RelationContext((), (state,)))
        assets.rows[101] = dict(assets.rows[3],id=101,type=0x41,desc='怪兽2只')
        deck = replace(decks[1],extra=(101,))
        layers = dict(axis=dict(task=task.to_dict(), inventory=deck.to_dict(), logic=None))
        optional = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, context=ctx)
        adoption, = (u for u in optional['uses'] if not u.contributes
            and optional['use_details'][u.use_id]['card_id']==1)
        self.assertIs(adoption.self_condition, True)
        self.assertFalse(adoption.required)
        self.assertFalse(adoption.theme_eligible)
        self.assertIsNone(optional['use_details'][adoption.use_id]['operation'])
        self.assertFalse(optional['impacts'])
        before = evaluate_functional_quality(layers, policy=p, facts=optional)
        self.assertEqual(before['score']['upper'], 2.)
        required = UseRequirement('adopt', InputGroup('all', (Need('adopt:effect',
            Resource('functional_operation', attributes=('catalog:1:1:adoption',)), mode='presence'),)),
            'original task explicitly adopts the field restriction', functional_use_ids=(adoption.use_id,))
        ctx.relations = replace(ctx.relations, uses=(required,))
        facts = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, context=ctx)
        result = evaluate_functional_quality(layers, policy=p, facts=facts)
        self.assertTrue(next(u for u in facts['uses'] if u.use_id == adoption.use_id).required)
        self.assertEqual(next(r for r in result['hard_requirements'] if r['requirement_id'] == 'adopt')['status'], 'satisfied')
        self.assertEqual(result['score']['upper'], 1.)
        self.assertEqual(result['stages']['P']['upper'], before['stages']['P']['upper'])
        affected = {uid for impact in facts['impacts'] for uid in impact.affected_use_ids}
        self.assertEqual({facts['use_details'][uid]['semantics']['kind'] for uid in affected}, {'special_summon'})
        self.assertTrue(any('cannot_special_summon_from_extra' in row['reason_codes'] for row in result['loss_records']))
        absent = replace(deck, main=tuple(3 if c == 1 else c for c in deck.main))
        for changed in (absent, replace(absent, side=(1,))):
            missing = normalize_function_uses(task, changed, binder.semantic_catalog, policy=p, context=ctx)
            changed_layers = dict(axis=dict(task=task.to_dict(), inventory=changed.to_dict(), logic=None))
            evaluated = evaluate_functional_quality(changed_layers, policy=p, facts=missing)
            self.assertIs(next(r for r in missing['hard_requirements'] if r['requirement_id'] == 'adopt')['condition'], False)
            self.assertEqual(next(r for r in evaluated['hard_requirements'] if r['requirement_id'] == 'adopt')['status'], 'failed')
            self.assertFalse(any(i.scope_id == 'resident' for i in missing['impacts']))
        unresolved = SimpleNamespace(relations=replace(ctx.relations, facts=()))
        unknown = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, context=unresolved)
        self.assertIs(next(u for u in unknown['uses'] if u.use_id == adoption.use_id).self_condition, True)
        evaluated = evaluate_functional_quality(layers, policy=p, facts=unknown)
        self.assertEqual(next(r for r in evaluated['hard_requirements'] if r['requirement_id'] == 'adopt')['status'], 'satisfied')
        self.assertEqual(evaluated['score']['upper'], 1.)
        bad = SimpleNamespace(relations=replace(ctx.relations,
            uses=(replace(required, functional_use_ids=('unrelated absent use',)),)))
        with self.assertRaisesRegex(ContractError, 'binds absent functional uses'):
            normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, context=bad)

    def test_raw_non_scoring_adoption_preserves_full_cost_and_unmapped_restrictions(self):
        from ygo_kito.construction_relations import InputGroup, Need, RelationContext, Resource, UseRequirement
        task, assets, _, binder, decks, p = fixture()
        assets.rows[1].update(type=33, desc='这个卡名的①效果1回合只能使用1次。①：丢弃41张手卡才能发动。')
        facts = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p)
        source, = (u for u in facts['uses'] if not u.contributes)
        self.assertIs(source.self_condition, False)
        detail = facts['use_details'][source.use_id]
        self.assertEqual(detail['inventory_checks']['costs']['requirements'][0]['minimum'], 41)
        self.assertEqual(detail['costs'][0]['quantity'], 41)
        required = UseRequirement('pay', InputGroup('all', (Need('pay:effect',
            Resource('functional_operation', attributes=('catalog:1:1:adoption',)), mode='presence'),)),
            'original task requires complete non-scoring payment', functional_use_ids=(source.use_id,))
        ctx = SimpleNamespace(relations=RelationContext((required,)))
        facts = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p, context=ctx)
        layers = dict(axis=dict(task=task.to_dict(), inventory=decks[1].to_dict(), logic=None))
        result = evaluate_functional_quality(layers, policy=p, facts=facts)
        self.assertEqual(next(r for r in result['hard_requirements'] if r['requirement_id'] == 'pay')['status'], 'failed')
        self.assertEqual(result['stages']['P']['upper'], 1.)
        self.assertTrue(facts['unpriced_effects'])
        assets.rows[1]['desc'] = '①：这张卡在怪兽区域存在，自己不能在抽卡阶段以外抽卡。'
        unknown = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p)
        self.assertTrue(any(not u.contributes for u in unknown['uses']))
        self.assertEqual(unknown['scope_status']['impacts'], 'evaluated')
        self.assertFalse(unknown['impacts'])

    def test_raw_draw_lock_reaches_required_adoption_and_evaluation(self):
        from ygo_kito.construction_relations import InputGroup, Need, RelationContext, RelationFact, Resource, UseRequirement, _record_facts, _needs
        task, assets, _, binder, decks, p = fixture()
        assets.rows[1].update(type=33, desc='①：这张卡在怪兽区域存在，自己不能抽卡。')
        assets.rows[2]['desc'] = '这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。抽1张。'
        state = RelationFact('field', 'field', Resource('effect_applicability', zone='field',
            attributes=('card:1', 'controller:self', 'state:monster_zone')), 'reviewed source in own monster zone')
        target, _ = next(_record_facts(2, binder.semantic_catalog.effect_records(2)))
        activation, = _needs(target.inputs)
        access = RelationFact('main-phase', 'main-phase', activation.resource, 'reviewed target main-phase access')
        ctx = SimpleNamespace(relations=RelationContext((), (state, access)))
        deck = decks[1]
        layers = dict(axis=dict(task=task.to_dict(), inventory=deck.to_dict(), logic=None))
        optional = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, context=ctx)
        adoption, = (u for u in optional['uses'] if not u.contributes)
        draw, = (u for u in optional['uses'] if u.contributes)
        self.assertIs(adoption.self_condition, True)
        self.assertIs(draw.self_condition, True)
        self.assertFalse(adoption.required)
        before = evaluate_functional_quality(layers, policy=p, facts=optional)
        self.assertEqual(before['score']['upper'], 1.)
        required = UseRequirement('adopt-draw-lock', InputGroup('all', (Need('adopt',
            Resource('functional_operation', attributes=('catalog:1:1:adoption',)), mode='presence'),)),
            'original task adopts this field source', functional_use_ids=(adoption.use_id,))
        ctx.relations = replace(ctx.relations, uses=(required,))
        facts = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, context=ctx)
        after = evaluate_functional_quality(layers, policy=p, facts=facts)
        self.assertEqual(after['score']['upper'], 0.)
        self.assertEqual(after['stages']['P']['upper'], before['stages']['P']['upper'])
        self.assertEqual(next(r for r in after['hard_requirements'] if r['requirement_id'] == 'adopt-draw-lock')['status'], 'satisfied')
        self.assertEqual(facts['scope_status']['impacts'], 'evaluated')
        self.assertTrue(all(facts['use_details'][uid]['semantics']['kind'] == 'draw'
                            for impact in facts['impacts'] for uid in impact.affected_use_ids))
        self.assertTrue(any('cannot_draw' in row['reason_codes'] for row in after['loss_records']))
        draw_required = UseRequirement('required-draw', InputGroup('all', (Need('draw',
            Resource('functional_operation', attributes=(target.fact_id,)), mode='presence'),)),
            'original task requires the actual draw', functional_use_ids=(draw.use_id,))
        both = SimpleNamespace(relations=replace(ctx.relations, uses=(required, draw_required)))
        bound = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, context=both)
        bound_result = evaluate_functional_quality(layers, policy=p, facts=bound)
        # The access relation remains available, but its bound functional use
        # must fail the final hard gate after the mandatory impact.
        self.assertEqual(next(r for r in bound_result['hard_requirements'] if r['requirement_id'] == draw.use_id)['status'], 'failed')
        for side in ((), (1,)):
            removed = replace(deck, main=tuple(3 if c == 1 else c for c in deck.main), side=side)
            missing = normalize_function_uses(task, removed, binder.semantic_catalog, policy=p, context=ctx)
            self.assertIs(next(r for r in missing['hard_requirements'] if r['requirement_id'] == 'adopt-draw-lock')['condition'], False)
            self.assertFalse(any(i.scope_id == 'resident' for i in missing['impacts']))
        unresolved = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p,
            context=SimpleNamespace(relations=replace(ctx.relations, facts=())))
        # Printed applicability is a static configured capability. It does
        # not wait for a current monster-zone observation from the host.
        self.assertIs(next(u for u in unresolved['uses'] if u.use_id == adoption.use_id).self_condition, True)
        unknown = evaluate_functional_quality(layers, policy=p, facts=unresolved)
        self.assertEqual(unknown['score']['value'], 0.)

    def test_raw_add_hand_lock_reaches_evaluation_and_direction_scope(self):
        from ygo_kito.construction_layer_flow import _bind_mandatory_impacts
        from ygo_kito.construction_relations import InputGroup, Need, RelationContext, RelationFact, Resource, UseRequirement
        from tests.test_construction_functional_quality import fixture as qfixture, use
        task, assets, _, binder, decks, p = fixture()
        assets.rows[1].update(type=33, desc='①：这张卡在怪兽区域存在，自己不能从卡组把卡加入手卡。')
        state = RelationFact('field', 'field', Resource('effect_applicability', zone='field',
            attributes=('card:1', 'controller:self', 'state:monster_zone')), 'reviewed source state')
        ctx = SimpleNamespace(relations=RelationContext((), (state,)))
        facts = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p, context=ctx)
        source, = (u for u in facts['uses'] if not u.contributes)
        req = UseRequirement('adopt-add-lock', InputGroup('all', (Need('adopt',
            Resource('functional_operation', attributes=('catalog:1:1:adoption',)), mode='presence'),)),
            'original task adopts add-to-hand restriction', functional_use_ids=(source.use_id,))
        ctx.relations = replace(ctx.relations, uses=(req,))
        facts = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p, context=ctx)
        layers = dict(axis=dict(task=task.to_dict(), inventory=decks[1].to_dict(), logic=None))
        self.assertEqual(evaluate_functional_quality(layers, policy=p, facts=facts)['score']['upper'], 0.)
        self.assertEqual(facts['scope_status']['impacts'], 'evaluated')
        source_detail = facts['use_details'][source.use_id]
        target = use('resident', family='draw')
        first = replace(target, use_id='first', scope_id='going_first')
        second = replace(target, use_id='second', scope_id='going_second')
        source = use('lock', sources=('side:1:1',), family='adoption', scope_id='going_first',
                     contributes=False, required=True, requirement_origin='going-first plan adopts this source')
        layers, facts = qfixture([target, first, second, source], side=(1,))
        facts.update(coverage_details={}, use_details={
            'lock':source_detail,
            **{k:dict(restrictions=[], semantics=dict(kind='draw', from_zones=['deck'], to_zone='hand', owner='self'))
               for k in ('resident','first','second')}})
        def condition(key, value, reason, evidence):
            if value is not None:
                return value
            facts['variables'][key] = None
            return key
        p = policy(); p['pass'] = p.pop('pass_')
        _bind_mandatory_impacts(facts, None, condition)
        self.assertEqual([i.affected_use_ids for i in facts['impacts']], [('first',)])
        result = evaluate_functional_quality(layers, policy=p, facts=facts)
        self.assertEqual(result['side_directions']['going_first']['delta'], [-1.,-1.])
        self.assertEqual(result['side_directions']['going_second']['delta'], [0.,0.])
        self.assertEqual(result['score']['value'], .5)

    def test_add_hand_lock_preserves_origin_receiver_and_unknowns(self):
        from ygo_kito.construction_layer_flow import _bind_mandatory_impacts
        from tests.test_construction_functional_quality import fixture as qfixture, use
        source = use('source', family='adoption', contributes=False, required=True, requirement_origin='task adopts source')
        specs = (('draw', 'draw', ['deck'], 'self'), ('search', 'search', ['deck'], 'self'),
                 ('recover', 'recover', ['grave'], 'self'), ('return', 'return_hand', ['field'], 'self'),
                 ('opponent', 'search', ['deck'], 'opponent'), ('mixed', 'add_hand', ['deck', 'grave'], 'self'),
                 ('unknown-owner', 'search', ['deck'], 'unknown'))
        layers, facts = qfixture([source, *(use(k, family=k) for k, _, _, _ in specs)])
        rule = dict(kind='cannot_add_hand', scope='player', duration='while_applicable',
            source='这张卡在怪兽区域存在，自己不能从卡组把卡加入手卡')
        facts.update(coverage_details={}, use_details={
            'source':dict(restrictions=[rule], applicability='this_card_in_monster_zone', semantics={'kind':'effect_adoption'}),
            **{k:dict(restrictions=[], semantics=dict(kind=kind, from_zones=origins, owner=owner, to_zone='hand'))
               for k, kind, origins, owner in specs}})
        def condition(key, value, reason, evidence):
            if value is not None:
                return value
            facts['variables'][key] = None
            return key
        p = policy(); p['pass'] = p.pop('pass_')
        _bind_mandatory_impacts(facts, None, condition)
        self.assertEqual({i.affected_use_ids[0] for i in facts['impacts']}, {'draw','search','mixed','unknown-owner'})
        result = evaluate_functional_quality(layers, policy=p, facts=facts)
        self.assertEqual((result['score']['lower'], result['score']['upper']), (3.,5.))
        facts['impacts'] = []
        rule['source'] = '这张卡在怪兽区域存在，双方不能从卡组把卡加入手卡'
        _bind_mandatory_impacts(facts, None, condition)
        self.assertIn('opponent', {i.affected_use_ids[0] for i in facts['impacts']})
        facts['impacts'] = []
        rule['source'] = '这张卡在怪兽区域存在，对方不能从卡组把卡加入手卡'
        _bind_mandatory_impacts(facts, None, condition)
        self.assertEqual({i.affected_use_ids[0] for i in facts['impacts']}, {'opponent','unknown-owner'})

    def test_hand_lock_order_preserves_transitive_and_whole_turn_conditions(self):
        from ygo_kito.construction_layer_flow import _bind_mandatory_impacts, _mapped_restriction
        from ygo_kito.construction_relations import InputGroup, Need, Resource, UseRequirement, JointConstraint, RelationContext
        from tests.test_construction_functional_quality import fixture as qfixture, use
        layers, facts = qfixture([use(k, family=k) for k in ('source','bridge','target')])
        rule = dict(kind='cannot_draw', source='reviewed after activation', scope='player', condition='effect_activation',
                    duration='turn', whole_turn=False, controller='self')
        facts.update(coverage_details={}, use_details={
            'source':dict(restrictions=[rule], semantics={'kind':'draw', 'owner':'self'}),
            'bridge':dict(restrictions=[], semantics={'kind':'recover', 'owner':'self'}),
            'target':dict(restrictions=[], semantics={'kind':'draw', 'owner':'self'})})
        requirements = tuple(UseRequirement(k, InputGroup('all', (Need(k, Resource(k)),)), 'reviewed order',
                             functional_use_ids=(k,)) for k in ('source','bridge','target'))
        def condition(key, value, reason, evidence):
            if value is not None:
                return value
            facts['variables'][key] = None
            return key
        p = policy(); p['pass'] = p.pop('pass_')
        for ordered, expected in ((('target','bridge','source'), (3.,3.)),
                                  (('source','bridge','target'), (2.,2.)), ((), (3.,3.))):
            constraints = (JointConstraint('order', ordered, 'before', 'reviewed'),) if ordered else ()
            ctx = SimpleNamespace(relations=RelationContext(requirements, constraints=constraints))
            facts['impacts'] = []
            _bind_mandatory_impacts(facts, ctx, condition)
            result = evaluate_functional_quality(layers, policy=p, facts=facts)
            self.assertEqual((result['score']['lower'], result['score']['upper']), expected)
        safe = SimpleNamespace(relations=RelationContext(requirements,
            constraints=(JointConstraint('safe', ('target','bridge','source'), 'before', 'reviewed'),)))
        rule['whole_turn'] = True
        facts['impacts'] = []
        _bind_mandatory_impacts(facts, safe, condition)
        self.assertEqual(evaluate_functional_quality(layers, policy=p, facts=facts)['score']['value'], 2.)
        cyclic = SimpleNamespace(relations=replace(safe.relations, constraints=safe.relations.constraints + (
            JointConstraint('reverse', ('source','target'), 'before', 'reviewed contradictory order'),)))
        rule['whole_turn'] = False
        facts['impacts'] = []
        _bind_mandatory_impacts(facts, cyclic, condition)
        self.assertTrue(all(type(i.condition) is bool for i in facts['impacts']))
        self.assertTrue(any(r['condition'] is False for r in facts['hard_requirements']))
        rule['condition'] = 'unresolved_source_clause'
        self.assertFalse(_mapped_restriction(dict(restrictions=[rule], operations=[]), rule))
        facts['impacts'] = []
        _bind_mandatory_impacts(facts, safe, condition)
        self.assertTrue(all(isinstance(i.condition, str) for i in facts['impacts']))

    def test_fusion_only_impact_uses_actual_origin_and_actor(self):
        from ygo_kito.construction_layer_flow import _bind_mandatory_impacts
        from tests.test_construction_functional_quality import fixture as qfixture, use
        source = use('source', family='adoption', contributes=False, required=True, requirement_origin='task adopts lock')
        specs = (('extra','synchro_summon',['extra'],'self'), ('grave','synchro_summon',['grave'],'self'),
                 ('fusion','fusion_summon',['extra'],'self'), ('generic','special_summon',['extra'],'self'),
                 ('opponent','xyz_summon',['extra'],'opponent'))
        layers, facts = qfixture([source, *(use(k, family=k) for k, _, _, _ in specs)])
        rule = dict(kind='extra_fusion_only', source='reviewed turn restriction', scope='player',
                    controller='self', condition='effect_use', duration='turn', whole_turn=True)
        facts.update(coverage_details={}, use_details={
            'source':dict(restrictions=[rule], semantics={'kind':'effect_adoption'}),
            **{k:dict(restrictions=[], semantics=dict(kind=kind, from_zones=origins), operation=dict(controller=actor))
               for k, kind, origins, actor in specs}})
        def condition(key, value, reason, evidence):
            if value is not None:
                return value
            facts['variables'][key] = None
            return key
        p = policy(); p['pass'] = p.pop('pass_')
        _bind_mandatory_impacts(facts, None, condition)
        self.assertEqual({i.affected_use_ids[0] for i in facts['impacts']}, {'extra','generic'})
        result = evaluate_functional_quality(layers, policy=p, facts=facts)
        self.assertEqual((result['score']['lower'], result['score']['upper']), (3.,4.))

    def test_extra_summon_impact_keeps_origin_controller_and_condition_unknowns(self):
        from ygo_kito.construction_layer_flow import _bind_mandatory_impacts
        from tests.test_construction_functional_quality import fixture as qfixture, use
        source = use('source', family='adoption', contributes=False, required=True, requirement_origin='task adopts field state')
        targets = [use(k, family=k) for k in ('extra', 'deck', 'mixed', 'draw')]
        layers, facts = qfixture([source, *targets])
        restriction = dict(kind='cannot_special_summon_from_extra', source='reviewed continuous lock', scope='player',
            condition='this_card_in_monster_zone', duration='while_applicable', controller='self')
        facts.update(coverage_details={}, use_details={
            'source': dict(restrictions=[restriction], applicability='this_card_in_monster_zone', semantics={'kind':'effect_adoption'}),
            **{k:dict(restrictions=[], semantics=dict(kind='draw' if k == 'draw' else 'special_summon', from_zones=origins))
               for k, origins in (('extra',['extra']), ('deck',['deck']), ('mixed',['extra','grave']), ('draw',['deck']))}})
        def condition(key, value, reason, evidence):
            if value is not None:
                return value
            facts['variables'][key] = None
            return key
        p = policy(); p['pass'] = p.pop('pass_')
        _bind_mandatory_impacts(facts, None, condition)
        self.assertEqual({i.affected_use_ids[0] for i in facts['impacts']}, {'extra','mixed'})
        result = evaluate_functional_quality(layers, policy=p, facts=facts)
        self.assertEqual((result['score']['lower'], result['score']['upper']), (2.,3.))
        facts['impacts'] = []
        facts['use_details']['extra']['operation'] = {'controller':'opponent'}
        _bind_mandatory_impacts(facts, None, condition)
        self.assertEqual({i.affected_use_ids[0] for i in facts['impacts']}, {'mixed'})
        facts['use_details']['extra']['operation'] = {'controller':'both'}
        facts['impacts'] = []
        _bind_mandatory_impacts(facts, None, condition)
        self.assertTrue(all(isinstance(i.condition, str) for i in facts['impacts']))
        facts['use_details']['extra'].pop('operation')
        facts['impacts'] = []
        restriction['controller'] = 'opponent'
        _bind_mandatory_impacts(facts, None, condition)
        self.assertFalse(facts['impacts'])
        restriction.update(controller='self', condition='source_clause')
        _bind_mandatory_impacts(facts, None, condition)
        self.assertTrue(all(isinstance(i.condition, str) for i in facts['impacts']))
        unknown = evaluate_functional_quality(layers, policy=p, facts=facts)
        self.assertEqual((unknown['score']['lower'], unknown['score']['upper']), (2.,4.))

    def test_non_scoring_extra_lock_keeps_directional_negative_delta(self):
        from ygo_kito.construction_layer_flow import _bind_mandatory_impacts
        from tests.test_construction_functional_quality import fixture as qfixture, use
        target = use('resident', family='summon')
        first = replace(target, use_id='first', scope_id='going_first')
        second = replace(target, use_id='second', scope_id='going_second')
        source = use('lock', sources=('side:2:1',), family='adoption', scope_id='going_first',
            contributes=False, required=True, requirement_origin='original going-first plan adopts the lock')
        layers, facts = qfixture([target, first, second, source], side=(2,))
        restriction = dict(kind='cannot_special_summon_from_extra', source='reviewed side restriction', scope='player',
            condition='this_card_in_monster_zone', duration='while_applicable', controller='self')
        facts.update(coverage_details={}, use_details={
            'lock':dict(restrictions=[restriction], applicability='this_card_in_monster_zone', semantics={'kind':'effect_adoption'}),
            **{k:dict(restrictions=[], semantics=dict(kind='fusion_summon', from_zones=['extra']))
               for k in ('resident','first','second')}})
        def condition(key, value, reason, evidence):
            if value is not None:
                return value
            facts['variables'][key] = None
            return key
        p = policy(); p['pass'] = p.pop('pass_')
        _bind_mandatory_impacts(facts, None, condition)
        self.assertEqual([i.affected_use_ids for i in facts['impacts']], [('first',)])
        result = evaluate_functional_quality(layers, policy=p, facts=facts)
        self.assertEqual(result['side_directions']['going_first']['resident'], [1.,1.])
        self.assertEqual(result['side_directions']['going_first']['delta'], [-1.,-1.])
        self.assertEqual(result['side_directions']['going_second']['delta'], [0.,0.])
        self.assertEqual(result['score']['value'], .5)
        facts['impacts'] = []
        facts['use_details']['lock']['applicability'] = None
        _bind_mandatory_impacts(facts, None, condition)
        unknown = evaluate_functional_quality(layers, policy=p, facts=facts)
        self.assertEqual((unknown['score']['lower'], unknown['score']['upper']), (.5,1.))

    def test_catalog_return_witness_reaches_bound_requirement_and_evaluation(self):
        from ygo_kito.construction_relations import InputGroup, Need, PoolRecovery, RelationContext, RelationFact, Resource, ResourcePool, UseRequirement
        task, assets, graph, binder, decks, p = fixture()
        assets.rows[1]['name'] = '静态对象'
        assets.rows[2]['desc'] = '这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。从自己墓地把1张「静态对象」加入手卡。'
        initial = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p)
        uid = next(u.use_id for u in initial['uses'] if initial['use_details'][u.use_id]['card_id'] == 2)
        first = Need('first', Resource('physical-call', zone='hand'), destination='grave')
        last = Need('last', first.resource)
        required = UseRequirement('reuse', InputGroup('all', (first, last)), 'original task', functional_use_ids=(uid,))
        stock = RelationFact('physical-call', 'physical-call', first.resource, 'explicit initial hand access', output_pool='stock')
        phase = RelationFact('phase', 'phase', Resource('activation', event='own_main_phase', reason='not_applicable',
            attributes=('card:2',)), 'explicit activation support')
        ctx = SimpleNamespace(relations=RelationContext((required,), (stock, phase), (
            ResourcePool('stock', 'one physical target', inventory=(('main', 1),), recoveries=(
                PoolRecovery('catalog:2:1:op:0', 'first', 'last'),)),)))
        layers = dict(axis=dict(task=task.to_dict(), inventory=decks[1].to_dict(), logic=graph.to_dict()))
        facts = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p, context=ctx)
        detail = facts['use_details'][uid]
        joint = next(g for g in detail['joint_groups'] if g['status'] == 'supported')
        witness = next(b for b in joint['branches'] if b['status'] == 'supported' and b.get('recovery_returns'))
        transfer = witness['recovery_returns'][0]['transfer']
        self.assertEqual((transfer['origin'], transfer['destination'], transfer['owner'], transfer['controller']),
            ('grave', 'hand', 'self', 'self'))
        self.assertEqual(transfer['inventory'], (('main', 1),))
        self.assertTrue(any(tuple(r['slot']) == ('physical:main:1', 0) for r in witness['recovery_allocation']
            if r['selector'] in witness['return_selections']))
        result = evaluate_functional_quality(layers, policy=p, facts=facts)
        self.assertEqual(next(r for r in result['hard_requirements'] if r['requirement_id'] == 'reuse')['status'], 'satisfied')
        impossible = replace(required, inputs=InputGroup('all', (replace(first, destination='banished'), last)))
        wrong = SimpleNamespace(relations=replace(ctx.relations, uses=(impossible,)))
        failed_facts = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p, context=wrong)
        failed = evaluate_functional_quality(layers, policy=p, facts=failed_facts)
        self.assertIs(next(u for u in failed_facts['uses'] if u.use_id == uid).joint_condition, False)
        self.assertEqual(next(r for r in failed['hard_requirements'] if r['requirement_id'] == 'reuse')['status'], 'failed')
        self.assertGreater(result['score']['upper'], failed['score']['upper'])
        undeclared = replace(required, inputs=InputGroup('all', (replace(first, destination=None), last)))
        unknown = SimpleNamespace(relations=replace(ctx.relations, uses=(undeclared,)))
        unknown_facts = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p, context=unknown)
        self.assertTrue(any('recovery_transfer_origin' in d['reason_code'] for d in unknown_facts['fact_details'].values()))
        side_only = DeckParts(tuple(16 if c == 1 else c for c in decks[1].main), side=(1,))
        isolated = normalize_function_uses(task, side_only, binder.semantic_catalog, policy=p, context=ctx)
        self.assertIs(next(r for r in isolated['hard_requirements'] if r['requirement_id'] == 'reuse')['condition'], False)

    def test_mandatory_restriction_mapping_obeys_whole_turn_and_known_order(self):
        from ygo_kito.construction_layer_flow import _bind_mandatory_impacts
        from ygo_kito.construction_relations import InputGroup, Need, Resource, UseRequirement, JointConstraint, RelationContext
        from tests.test_construction_functional_quality import fixture as qfixture, use
        a, b = use('source',family='draw'), use('target',family='summon')
        layer, facts = qfixture([a,b])
        facts['coverage_details'] = {}
        facts['use_details'] = {'source':dict(restrictions=[dict(kind='cannot_normal_summon',source='lock',condition='effect_use',whole_turn=True,controller='self')],semantics={'kind':'draw'}),
            'target':dict(restrictions=[],semantics={'kind':'normal_summon'})}
        def condition(key,value,reason,evidence):
            if value is not None:return value
            facts['variables'][key]=None
            return key
        p=policy();p['pass']=p.pop('pass_')
        _bind_mandatory_impacts(facts,None,condition)
        self.assertEqual(evaluate_functional_quality(layer,policy=p,facts=facts)['score']['value'],1.)
        facts['use_details']['source']['restrictions'][0]['whole_turn']=False
        requirements=tuple(UseRequirement(k,InputGroup('all',(Need(k,Resource(k)),)),'sourced order',functional_use_ids=(k,)) for k in ('source','target'))
        context=SimpleNamespace(relations=RelationContext(requirements,constraints=(JointConstraint('safe',('target','source'),'before','reviewed'),)))
        facts['impacts']=[]
        _bind_mandatory_impacts(facts,context,condition)
        self.assertEqual(evaluate_functional_quality(layer,policy=p,facts=facts)['score']['value'],2.)
        facts['impacts']=[]
        _bind_mandatory_impacts(facts,None,condition)
        arranged=evaluate_functional_quality(layer,policy=p,facts=facts)
        self.assertEqual(arranged['score']['value'],2.)
        self.assertTrue(arranged['complete'])

    def test_printed_processing_order_does_not_cross_cards_with_equal_local_block_ids(self):
        from ygo_kito.construction_layer_flow import _bind_mandatory_impacts
        from tests.test_construction_functional_quality import fixture as qfixture, use
        layer, facts = qfixture([use(k,family=k) for k in ('source','bridge','target')])
        facts.update(coverage_details={}, use_details={
            'source':dict(card_id=1, restrictions=[dict(kind='cannot_normal_summon',source='printed lock',
                condition='effect_use',whole_turn=False,controller='self')],semantics={'kind':'draw'},
                operation={'block_id':'local:0'}),
            'bridge':dict(card_id=2,restrictions=[],semantics={'kind':'recover'},operation={'block_id':'local:0'}),
            'target':dict(card_id=2,restrictions=[],semantics={'kind':'normal_summon'},
                operation={'block_id':'local:1','depends_on':['local:0']})})
        def condition(key,value,reason,evidence):
            if value is not None:return value
            facts['variables'][key]=None
            return key
        _bind_mandatory_impacts(facts,None,condition)
        p=policy();p['pass']=p.pop('pass_')
        q=evaluate_functional_quality(layer,policy=p,facts=facts)
        self.assertTrue(q['complete'])
        self.assertEqual(q['score']['value'],3.)

    def test_targeted_grave_call_and_both_theme_channels_share_source_support(self):
        from ygo_kito.construction_relations import RelationContext, RelationFact, Resource
        from ygo_kito.construction_quality import support_facts
        task, assets, _, binder, decks, p = fixture()
        assets.rows[3].update(name='静态接收方', type=33,
            desc='这个卡名的①效果1回合只能使用1次。这个卡名的②效果1回合只能使用1次。①：这张卡被效果送去墓地的场合才能发动。抽1张。②：自己主要阶段才能发动。从卡组上面把2张卡送去墓地。')
        assets.rows[2]['desc'] = '这个卡名的①效果1回合只能使用1次。①：自己主要阶段才能发动。从卡组把1张「静态接收方」送去墓地。'
        p['quality']['theme_rules'] = [dict(rule_id='grave', increment=1, predicate={'grave_related': True}),
            dict(rule_id='mill', increment=1, predicate={'kind':'send_grave', 'from_zone':'deck', 'to_zone':'grave', 'owner':'self','reason':'effect'})]
        facts = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p)
        donor = next(u for u in facts['uses'] if facts['use_details'][u.use_id]['card_id'] == 2)
        receiver = next(u for u in facts['uses'] if facts['use_details'][u.use_id]['trigger'].get('event') == 'sent_to_grave')
        self.assertIs(donor.self_condition, True)
        self.assertIs(receiver.self_condition, True)
        seed = RelationFact('phase','phase', Resource('activation',event='own_main_phase', reason='not_applicable',
            attributes=('card:2',)), 'explicit static activation support')
        ctx = SimpleNamespace(relations=RelationContext((), (seed,)))
        facts = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p, context=ctx)
        donor = next(u for u in facts['uses'] if facts['use_details'][u.use_id]['card_id'] == 2)
        receiver = next(u for u in facts['uses'] if facts['use_details'][u.use_id]['trigger'].get('event') == 'sent_to_grave')
        second = next(u for u in facts['uses'] if facts['use_details'][u.use_id]['card_id'] == 3 and u != receiver)
        self.assertEqual(receiver.valuation_mode, 'called')
        self.assertEqual(second.valuation_mode, 'main_density')
        self.assertEqual(set(donor.theme_eligible), {'grave', 'mill'})
        self.assertTrue(all(facts['variables'][expr] is True for _, expr in donor.theme_conditions))

    def test_explicit_joint_group_withdraws_only_bound_functional_uses(self):
        from ygo_kito.construction_relations import Claim, InputGroup, Need, RelationContext, RelationFact, Resource, ResourcePool, UseRequirement
        task, _, _, binder, decks, p = fixture()
        initial = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p)
        uid = initial['uses'][0].use_id
        group = tuple(UseRequirement(k, InputGroup('all',(Need(k,Resource(k)),)), 'original task',
            functional_use_ids=(uid,) if k == 'a' else ()) for k in ('a','b'))
        records = tuple(RelationFact(k,k,Resource(k),'explicit shared use',claims=(Claim('once'),)) for k in ('a','b'))
        ctx = SimpleNamespace(relations=RelationContext(group, records, (ResourcePool('once','shared activation',capacity=1),)))
        facts = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p, context=ctx)
        self.assertIs(facts['uses'][0].joint_condition, False)
        self.assertTrue(facts['uses'][0].required)
        self.assertEqual(facts['uses'][0].requirement_origin, 'original task')
        self.assertTrue(any(r['condition'] is False for r in facts['hard_requirements']))
        optional = SimpleNamespace(relations=replace(ctx.relations, uses=tuple(replace(u,required=False) for u in group)))
        facts = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p, context=optional)
        self.assertIs(facts['uses'][0].joint_condition, True)

    def test_global_return_witness_discharges_bound_required_subgroup(self):
        from ygo_kito.construction_relations import InputGroup, Need, PoolRecovery, RelationContext, RelationFact, Resource, ResourcePool, UseRequirement
        task, _, graph, binder, decks, p = fixture()
        initial = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p)
        uid = initial['uses'][0].use_id
        first, middle, last = (Need(k, Resource('shared')) for k in ('first', 'middle', 'last'))
        requirements = (UseRequirement('outer', InputGroup('all', (first, last)), 'original task', functional_use_ids=(uid,)),
                        UseRequirement('middle', InputGroup('all', (middle,)), 'original task'))
        records = (RelationFact('shared', 'shared', Resource('shared'), 'reviewed stock', output_pool='stock'),
                   RelationFact('r1', 'r1', Resource('r1'), 'first return', 2),
                   RelationFact('r2', 'r2', Resource('r2'), 'second return', 3))
        ctx = SimpleNamespace(relations=RelationContext(requirements, records, (
            ResourcePool('stock', 'one physical source', inventory=(('main', 1),), recoveries=(
                PoolRecovery('r1', 'first', 'middle'), PoolRecovery('r2', 'middle', 'last'))),)))
        layers = dict(axis=dict(task=task.to_dict(), inventory=decks[1].to_dict(), logic=graph.to_dict()))
        facts = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p, context=ctx)
        self.assertEqual(facts['normalization_version'], NORMALIZATION_VERSION)
        self.assertIs(next(u for u in facts['uses'] if u.use_id == uid).joint_condition, True)
        self.assertIs(next(r for r in facts['hard_requirements'] if r['requirement_id'] == 'outer')['condition'], True)
        result = evaluate_functional_quality(layers, policy=p, facts=facts)
        self.assertEqual(next(r for r in result['hard_requirements'] if r['requirement_id'] == 'outer')['status'], 'satisfied')
        scarce = SimpleNamespace(relations=replace(ctx.relations, facts=records[:-1] + (replace(records[-1], card_id=16),)))
        missing = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p, context=scarce)
        self.assertIs(next(u for u in missing['uses'] if u.use_id == uid).joint_condition, False)
        failed = evaluate_functional_quality(layers, policy=p, facts=missing)
        self.assertEqual(next(r for r in failed['hard_requirements'] if r['requirement_id'] == 'joint_required')['status'], 'failed')
        self.assertGreater(result['score']['upper'], failed['score']['upper'])

    def test_side_projection_restores_inventory_without_supporting_resident(self):
        task, assets, _, binder, decks, p = fixture()
        assets.rows[3]['name'] = '静态对象'
        task = replace(task, sizes={**task.sizes, 'side':1})
        assets.rows[2]['desc'] = '①：从卡组把1张「静态对象」加入手卡。'
        deck = replace(decks[3], side=(3,))
        facts = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p)
        resident = [u for u in facts['uses'] if u.scope_id == 'resident']
        directions = [u for u in facts['uses'] if u.scope_id != 'resident']
        self.assertTrue(resident)
        self.assertTrue(all(u.self_condition is False for u in resident))
        self.assertTrue(all(facts['use_details'][u.use_id]['inventory_checks']['objects']['status'] == 'inventory_present' for u in directions))
        self.assertEqual(facts['scope_status']['side'], 'evaluated')
        self.assertTrue(all(v['main_size'] == 40 for v in facts['side_contexts'].values()))
        for key, value in facts['variables'].items():
            if value is None:
                facts['variables'][key] = True  # Explicit fixture execution review.
        layer = dict(axis=dict(inventory=deck.to_dict(), task=task.to_dict(), logic=None))
        q = evaluate_functional_quality(layer, policy=p, facts=facts)
        self.assertTrue(q['complete'])
        self.assertEqual(q['details'][3]['resident']['value'], 0.)
        self.assertGreater(q['score']['value'], 0.)
        assets.rows[3]['type'] = 0x41
        facts = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p)
        self.assertTrue(all('side:3:1' in v['excluded_source_ids'] for v in facts['side_contexts'].values()))
        self.assertTrue(all(u.self_condition is False for u in facts['uses']))
    def test_quality_order_and_labels_use_final_score_without_a_model(self):
        from ygo_kito.construction_learning import candidate_pairs, validate_pair, SOURCE
        task, _, _, result = functional_fill()
        contexts = result['learning_candidates']
        winner = max(contexts, key=lambda row: row['quality_evaluation']['score']['value'])
        self.assertEqual(result['best_deck'], winner['deck'])
        for pair in candidate_pairs(task, result['learning_candidates']):
            validate_pair(task, pair)
            self.assertEqual(pair['source'], SOURCE)
        self.assertEqual(candidate_pairs(task, [{'deck': c['deck'], 'layer_comparisons': c['quality_comparisons']}
                                              for c in contexts]), [])

    def test_full_payment_matching_includes_spells_and_never_reuses_one_entity(self):
        from ygo_kito.construction_inventory import InventoryDependencies
        task, assets, _, binder, decks, _ = fixture()
        assets.rows[3]['type'] = 2
        dependencies = InventoryDependencies(binder.semantic_catalog)
        req = dict(query={'type': 2}, minimum=3, source='fixture three spell cost', origin='hand', category='costs')
        value = dependencies._check(decks[0], [req], distinct=True)
        self.assertEqual(value['status'], 'inventory_present')
        value = dependencies._check(decks[0], [req, dict(req, minimum=1)], distinct=True)
        self.assertEqual(value['status'], 'missing')
        self.assertEqual(value['shortfall'], 1)

    def test_cycle_pending_resume_reuses_skeleton_graph_and_candidate_results(self):
        task, assets, graph, binder, decks, p = fixture()
        session = session_for(task, graph)
        roles = []
        def provider(ctx):
            roles.append(ctx['role'])
            old = ConstructionLogic.from_dict(ctx['logic'])
            return dict(logic=replace(graph, revision=old.revision+1, parent_sha256=old.sha256).to_dict(), reason='fixture')
        def skeleton(s, *_args, **_kwargs):
            deck = DeckParts((1,))
            proposal = FillProposal(deck, (NodeBinding('goal', (1,)),), (), s.logic.sha256, task.sha256)
            return dict(status='axis_skeleton_ready', best_deck=deck.to_dict(), concrete_proposal=asdict(proposal),
                        unfilled=dict(main=39, extra=0, side=0))
        pause = [False]
        review = reviewed(binder.semantic_catalog, p)
        def once(*args):
            value = review(*args)
            pause[0] = True
            return value
        options = dict(binding_provider=binder, text_reviewer=binder.reviewer, quality_criteria=p,
            verifier=None, basic_cb_provider=lambda *_a, **_k: self.fail('CB forbidden'),
            run_mode='slice', seconds=30., max_iterations=1)
        providers = {key: provider for key in ('build_goal', 'build_optimizer')}
        with patch('ygo_kito.construction_fill.build_axis_skeleton', side_effect=skeleton), \
             patch('ygo_kito.build_pipeline._goal_candidates', return_value=decks), \
             patch('ygo_kito.construction_candidates.portfolio', return_value=rows_for(task, decks)):
            first = construction_cycle(session, assets, providers, **options, quality_evidence=once, pause_requested=lambda: pause[0])
        state = json.loads(json.dumps(first['continuation']))
        self.assertEqual(state['schema_version'], 3)
        self.assertEqual(state['iteration'], 0)
        self.assertEqual(state['stagnation'], 0)
        restore_progress(session, state, assets)
        with patch('ygo_kito.build_pipeline._goal_candidates', side_effect=AssertionError('no new candidates')), \
             patch('ygo_kito.construction_fill.build_axis_skeleton', side_effect=AssertionError('no new skeleton')):
            final = construction_cycle(session, assets, providers, **options, quality_evidence=review)
        self.assertEqual(roles, ['build_goal'])
        self.assertTrue(final['construction_passed'])
        self.assertEqual(final['continuation']['iteration'], 1)
        self.assertEqual(final['continuation']['candidate_cursor'], state['candidate_cursor'])
        self.assertEqual(final['best']['deck'], decks[3].to_dict())
        self.assertFalse(final['basic_cb']['execution_authorized'])
        self.assertFalse(final['retained_candidates'])
        from ygo_kito.course_admission_policy import CourseAdmissionPolicy
        course = SimpleNamespace(construction=final, models=SimpleNamespace(kernel=SimpleNamespace(source_binding={'construction_quality_policy': p})))
        receipt = CourseAdmissionPolicy(course).record_completed_construction(task=task,
            deck=decks[3], assets=assets, basic_cb=None, cycle_id='static-fixture')
        self.assertEqual(receipt['quality_evaluation']['evaluation_id'], final['best']['quality_evaluation']['evaluation_id'])
        self.assertEqual(receipt['construction_gate']['status'], 'passed')
        changed = deepcopy(p)
        changed['version'] = 'explicit-host-revision'
        revise_quality_policy(session, changed)
        self.assertEqual(session.construction_progress['candidate']['deck'], decks[3].to_dict())
        self.assertIsNone(session.construction_progress['gate'])
        self.assertEqual(session.construction_progress['candidate']['evaluation_status'], 'stale')
        assets.rows[2]['desc'] = '①：自己从卡组抽2张。'
        restore_progress(session, final['continuation'], assets)
        self.assertIsNone(session.construction_progress['gate'])
        self.assertEqual(session.construction_progress['candidate']['evaluation_status'], 'stale')

    def test_reference_gate_uses_own_bound_evaluation_and_none_has_no_threshold(self):
        task, assets, graph, binder, decks, p = fixture()
        adapter = ConstructionLayerAdapter(binder)
        def values(policy):
            return adapter.evaluate(task, graph, rows_for(task, decks),
                {i: binder(graph, task, d) for i, d in enumerate(decks)}, list(range(4)),
                policy=policy, quality_evidence=reviewed(binder.semantic_catalog, policy))[1]
        result = values(p)
        gate = construction_gate(task, decks[0], assets, result[0]['layer_evaluation'], policy=p,
                                quality=result[0]['quality_evaluation'])
        self.assertEqual(gate['status'], 'passed')
        self.assertFalse(gate['metrics'])
        p['pass'] = dict(mode='reference_ratio', minimum_reference_ratio=.8,
            reference=dict(reference_id='fixed', deck_sha256=digest(decks[3].to_dict()), source='fixture'))
        result = values(p)
        gate = construction_gate(task, decks[2], assets, result[2]['layer_evaluation'], policy=p,
            quality=result[2]['quality_evaluation'], reference_quality=result[3]['quality_evaluation'])
        self.assertEqual(gate['metrics'][-1]['status'], 'failed')
        self.assertNotEqual(gate['status'], 'passed')
        with self.assertRaisesRegex(ContractError, 'specified reference'):
            construction_gate(task, decks[2], assets, result[2]['layer_evaluation'], policy=p,
                quality=result[2]['quality_evaluation'], reference_quality=result[1]['quality_evaluation'])

    def test_fill_evaluates_four_and_retains_only_the_winner(self):
        _, _, decks, result = functional_fill()
        self.assertEqual(result['best_deck'], decks[3].to_dict())
        winner, = result['portfolio']
        self.assertEqual(winner['deck'], result['best_deck'])
        self.assertEqual(winner['quality_evaluation'], result['quality_evaluation'])
        contexts = result['learning_candidates']
        self.assertCountEqual([row['deck'] for row in contexts], [deck.to_dict() for deck in decks])
        evaluations = {}
        for row in contexts:
            key = digest(row['deck'])
            self.assertEqual(row['quality_evaluation']['deck_sha256'], key)
            evaluations[key] = row['quality_evaluation']['evaluation_id']
        self.assertEqual(len(set(evaluations.values())), len(decks))
        trace = result['candidate_trace']['candidates']
        self.assertCountEqual([(digest(row['recognition_inventory']), row['quality_evaluation_id']) for row in trace],
            evaluations.items())
        self.assertTrue(all('quality_evaluation' not in row for row in trace))
        json.dumps(result)

    def test_fill_pending_json_resumes_without_generation_or_truncation(self):
        task, assets, graph, binder, decks, p = fixture()
        session = session_for(task, graph)
        options = dict(role='build_optimizer', base=decks[0], binding_provider=binder,
            text_reviewer=binder.reviewer, verifier=None, defer_engine=True,
            quality_policy=p, quality_evidence=reviewed(binder.semantic_catalog, p))
        finished=[]
        def evaluate(*args,**kwargs):
            value=evaluate_functional_quality(*args,**kwargs)
            finished.append(value['evaluation_id'])
            return value
        with patch('ygo_kito.build_pipeline.edit_candidates', return_value=rows_for(task, decks)), \
             patch('ygo_kito.construction_quality.evaluate_functional_quality',side_effect=evaluate):
            first = fill_with_existing(session, assets, **options,
                should_stop=lambda:'user_pause' if finished else None)
        self.assertEqual(first['status'], 'quality_evaluation_pending')
        self.assertEqual(first['portfolio'], [])
        self.assertEqual(len(first['pending_candidates']), 3)
        pending = json.loads(json.dumps(first['pending_quality']))
        with patch('ygo_kito.build_pipeline.edit_candidates', side_effect=AssertionError('must resume saved candidates')):
            final = fill_with_existing(session, assets, **options, pending_quality=pending)
        self.assertEqual(final['best_deck'], decks[3].to_dict())
        self.assertEqual(len(final['learning_candidates']), 4)
        self.assertTrue(final['selection_complete'])

    def test_real_effects_outside_graph_and_candidate_local_sources(self):
        task, _, graph, binder, decks, p = fixture()
        adapter = ConstructionLayerAdapter(binder)
        rows = rows_for(task, decks)
        proposals = {i: binder(graph, task, d) for i, d in enumerate(decks)}
        hook = reviewed(binder.semantic_catalog, p)
        order, values, trace = adapter.evaluate(task, graph, rows, proposals, [0, 1, 2, 3],
            policy=p, quality_evidence=hook)
        self.assertEqual(order, [3, 2, 1, 0])
        self.assertTrue(all(v["evaluation_status"] == "complete" for v in values.values()))
        _, alone, _ = adapter.evaluate(task, graph, rows, {1: proposals[1]}, [1], policy=p, quality_evidence=hook)
        self.assertEqual(values[1]["quality_evaluation"]["score"], alone[1]["quality_evaluation"]["score"])
        self.assertEqual(values[1]["quality_evaluation"]["facts_sha256"], alone[1]["quality_evaluation"]["facts_sha256"])
        self.assertEqual(values[0]["quality_evaluation"]["score"]["value"], 0.)
        self.assertEqual(values[1]["quality_evaluation"]["score"]["value"], 1.)
        self.assertEqual(trace["evaluated_indices"], [0, 1, 2, 3])
        json.dumps(values)

    def test_identity_ignores_graph_names_and_keeps_real_operations(self):
        task, assets, graph, binder, decks, p = fixture()
        assets.rows[2]["desc"] = "①：自己从卡组上面把3张卡送去墓地。自己从卡组抽1张。"
        facts = normalize_function_uses(task, decks[2], binder.semantic_catalog, policy=p)
        self.assertEqual(len({u.score_family_id for u in facts["uses"]}), 2)
        self.assertEqual({s for u in facts["uses"] for s in u.source_ids}, {"main:2:1", "main:2:2"})
        renamed = replace(graph, logic_id="another-display-name")
        adapter = ConstructionLayerAdapter(binder)
        row = rows_for(task, [decks[2]])
        a = adapter.evaluate(task, graph, row, {0: binder(graph, task, decks[2])}, [0], policy=p)[1][0]
        b = adapter.evaluate(task, renamed, row, {0: binder(renamed, task, decks[2])}, [0], policy=p)[1][0]
        self.assertEqual(a["quality_evaluation"]["facts_sha256"], b["quality_evaluation"]["facts_sha256"])

    def test_complete_cost_fails_without_partial_credit_or_optional_hard_requirement(self):
        task, assets, _, binder, decks, p = fixture()
        assets.rows[2]["desc"] = "①：丢弃41张手卡才能发动。自己从卡组抽1张。②：自己从卡组抽1张。"
        facts = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p)
        self.assertEqual(len(facts["uses"]), 2)
        self.assertEqual(sum(u.self_condition is False for u in facts["uses"]), 1)
        self.assertTrue(all(not u.required for u in facts["uses"]))
        self.assertFalse(facts["hard_requirements"])
        self.assertFalse(any(value is False and "theme" in key for key, value in facts["variables"].items()))

    def test_host_cannot_overwrite_known_failure_or_other_candidate(self):
        task, assets, _, binder, decks, p = fixture()
        assets.rows[2]["desc"] = "①：丢弃41张手卡才能发动。自己从卡组抽1张。"
        facts = normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p)
        evidence = {**{k: facts[k] for k in ("version", "task_sha256", "deck_sha256", "asset_version")},
            "source": "fixture", "evidence_refs": ["fixture"],
            "variables": {k: True for k, v in facts["variables"].items() if v is False}}
        with self.assertRaisesRegex(ContractError, "conflicts"):
            normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p, quality_evidence=evidence)
        evidence["deck_sha256"] = digest(decks[2].to_dict())
        with self.assertRaisesRegex(ContractError, "binding"):
            normalize_function_uses(task, decks[1], binder.semantic_catalog, policy=p, quality_evidence=evidence)

    def test_paused_evaluation_keeps_pending_and_resumes_same_candidates(self):
        task, assets, graph, binder, decks, p = fixture()
        rows = rows_for(task, decks)
        proposals = {i: binder(graph, task, d) for i, d in enumerate(decks)}
        adapter = ConstructionLayerAdapter(binder)
        completed = []
        _, values, trace = adapter.evaluate(task, graph, rows, proposals, [0, 1, 2, 3], policy=p,
            quality_evidence=reviewed(binder.semantic_catalog, p),
            should_stop=lambda: 'user_pause' if completed else None,
            on_progress=lambda *args:completed.append(True))
        self.assertEqual(trace["pending_indices"], [1, 2, 3])
        self.assertFalse(trace["selection_complete"])
        _, resumed, trace = adapter.evaluate(task, graph, rows, proposals, [0, 1, 2, 3], policy=p,
            quality_evidence=reviewed(binder.semantic_catalog, p), evaluated=values)
        self.assertEqual(resumed[0], values[0])
        self.assertTrue(trace["selection_complete"])
        assets.rows[2]['desc'] = '①：自己从卡组抽2张。'
        bounded = ConstructionLayerAdapter(binder, budget=RelationBudget(candidates=1))
        _, updated, trace = bounded.evaluate(task, graph, rows, proposals, [0, 1, 2, 3], policy=p,
            quality_evidence=reviewed(binder.semantic_catalog, p), evaluated=resumed)
        self.assertEqual(set(updated), {0, 1})
        self.assertEqual(trace['pending_indices'], [2, 3])
        self.assertEqual(trace['stop_reason'], 'candidate_evaluation_budget')

    def test_unread_semantics_and_side_are_not_complete(self):
        task, _, _, binder, decks, p = fixture()
        deck = replace(decks[1], side=(2,))
        facts = normalize_function_uses(task, deck, binder.semantic_catalog, policy=p, budget=RelationBudget(cards=1))
        self.assertEqual(facts["coverage"]["main:2"], "deferred")
        self.assertTrue(facts['calculation_pending'])
        self.assertEqual(facts['calculation_pending']['read_cursor'],1)
        layers = dict(axis=dict(task=task.to_dict(), inventory=deck.to_dict(), logic=None))
        with self.assertRaisesRegex(ContractError,'facts contract'):
            evaluate_functional_quality(layers, policy=p, facts=facts)


if __name__ == "__main__":
    unittest.main()
