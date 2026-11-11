"""Small pure-static checks for the functional migration; no models or engine."""
from copy import deepcopy
from dataclasses import replace
from math import log2
import unittest

from ygo_kito.build_contracts import digest
from ygo_kito.construction_quality import (
    FUNCTIONAL_QUALITY_VERSION, FUNCTION_DICTIONARY_VERSION, FUNCTIONAL_SCOPE,
    FunctionalUse, UseImpact, functional_quality_config, functional_pass_policy,
    evaluate_functional_quality, compare_functional_quality, physical_sources,
    functional_delta,
)
from ygo_kito.validation import ContractError


def policy(themes=(), budget=4096):
    return dict(version="test-functional-v1", source="static-fixture", metrics=[],
        quality=dict(evaluator_version=FUNCTIONAL_QUALITY_VERSION,
            function_dictionary_version=FUNCTION_DICTIONARY_VERSION, theme_rules=list(themes),
            side_directions={"going_first": .5, "going_second": .5},
            required_scope=list(FUNCTIONAL_SCOPE), completion_budget=budget), pass_={"mode": "none"})


def use(key="u", sources=("main:1:1",), family="f", condition=True, **options):
    return FunctionalUse(key, "effect:" + key, family, family, sources,
                         "main_density", ("review:" + key,), condition, **options)


def fixture(uses, *, main=None, extra=(), side=(), variables=None, impacts=(), aliases=None):
    deck = dict(main=list(main if main is not None else [1] + [99] * 39),
                extra=list(extra), side=list(side))
    layer = dict(axis=dict(inventory=deck, task={"task_id": "fixed"}, logic={"node": "display"}))
    facts = dict(version="construction-quality-facts-v1", task_sha256=digest(layer["axis"]["task"]),
        deck_sha256=digest(deck), asset_version="static-assets-v1", uses=list(uses), impacts=list(impacts),
        variables=variables or {}, constraints=[],
        coverage={f"{zone}:{c}": "evaluated" for zone, cards in deck.items() for c in cards},
        scope_status={k: "evaluated" for k in FUNCTIONAL_SCOPE}, source_aliases=aliases or {})
    return layer, facts


def score(uses, *, configuration=None, **options):
    layer, facts = fixture(uses, **options)
    p = configuration or policy()
    p = {**p, "pass": p["pass_"]}
    del p["pass_"]
    return evaluate_functional_quality(layer, policy=p, facts=facts)


class FunctionalQualityTests(unittest.TestCase):
    def test_loss_records_preserve_unassigned_inactive_theme_support(self):
        configuration=policy([dict(rule_id='theme',increment=1,predicate={'grave_related':True})])
        for self_condition, joint_condition, theme_condition, joint_theme in (
                (False,True,'inactive-theme',True),
                (True,False,True,'inactive-theme')):
            with self.subTest(self_condition=self_condition,joint_condition=joint_condition):
                source=use('blocked',condition=self_condition,joint_condition=joint_condition,
                    theme_eligible=('theme',),theme_conditions=(('theme',theme_condition),),
                    theme_joint_conditions=(('theme',joint_theme),))
                result=score([source],configuration=configuration,variables={'inactive-theme':None})
                self.assertTrue(result['complete'])
                self.assertEqual(result['score']['value'],0.)
                self.assertTrue(result['loss_records'])
                available=replace(source,self_condition=True,joint_condition=True)
                relevant=score([available],configuration=configuration,variables={'inactive-theme':None})
                self.assertFalse(relevant['complete'])
                self.assertEqual(len(relevant['unknowns']),1)
                self.assertIn('inactive-theme',dict(source.theme_conditions).values() if self_condition is False
                              else dict(source.theme_joint_conditions).values())

    def test_acceptance_split_discounts_channels_and_extra_withdrawal(self):
        main=list(range(1,41))
        together=score([use(sources=('main:1:1','main:2:1'))],main=main)
        split=score([use('a'),use('b',sources=('main:2:1',))],main=main)
        self.assertEqual(together['score'],split['score']);self.assertAlmostEqual(split['score']['value'],log2(3))
        for n in (1,2,3):
            ordinary=score([use(sources=tuple('main:1:'+str(i) for i in range(1,n+1)))],main=[1]*n+list(range(2,42-n)))
            extra=score([replace(use(sources=tuple('extra:101:'+str(i) for i in range(1,n+1))),valuation_mode='called')],main=main,extra=[101]*n)
            self.assertAlmostEqual(ordinary['score']['value'],log2(2+.9*(n-1)))
            self.assertAlmostEqual(extra['score']['value'],log2(2+.8*(n-1)))
            self.assertEqual(len([s for s in physical_sources(dict(main=main,extra=[101]*n,side=[])) if s.startswith('extra:')]),n)
        themes=[dict(rule_id=k,increment=1,predicate={'grave_related':True}) for k in ('a','b')]
        uses=[use(str(i),sources=('main:'+str(i)+':1',),condition=i!=1,
            theme_eligible=tuple(k for k,count in (('a',3),('b',2)) if i<=count),
            theme_conditions=tuple((k,True) for k,count in (('a',3),('b',2)) if i<=count)) for i in range(1,5)]
        q=score(uses,main=main,configuration=policy(themes))
        self.assertAlmostEqual(q['stages']['P']['lower']-q['score']['value'],1.3219280948873622)
        self.assertAlmostEqual(q['score']['value'],log2(4)+log2(3)+log2(2))
        uses=[replace(use(str(i),sources=('extra:101:'+str(i),),condition=i!=3),valuation_mode='called') for i in (1,2,3)]
        q=score(uses,main=main,extra=[101]*3)
        self.assertAlmostEqual(q['stages']['P']['lower']-q['score']['value'],.3625700793847082)
        self.assertEqual(score(list(reversed(uses)),main=main,extra=[101]*3)['score'],q['score'])

    def test_acceptance_independent_unknown_loss_and_shared_log_channel(self):
        main=list(range(1,41))
        uses=[use(str(i),sources=('main:'+str(i)+':1',),family=str(i),condition=True if i<=8 else 'u',
            joint_condition=i>2) for i in range(1,12)]
        q=score(uses,main=main,variables={'u':None})
        self.assertEqual((q['stages']['V1']['lower'],q['stages']['V1']['upper']),(8.,11.))
        self.assertEqual((q['score']['lower'],q['score']['upper']),(6.,9.))
        shared=[use('a',joint_condition=False),use('b',sources=('main:2:1',)),use('c',sources=('main:3:1',),condition='u')]
        q=score(shared,main=main,variables={'u':None})
        self.assertAlmostEqual(q['stages']['V1']['lower'],log2(3));self.assertAlmostEqual(q['stages']['V1']['upper'],2.)
        self.assertAlmostEqual(q['score']['lower'],1.);self.assertAlmostEqual(q['score']['upper'],log2(3))
        self.assertNotAlmostEqual(q['losses'][1]['lower'],q['losses'][1]['upper'])

    def test_acceptance_side_direction_increment_is_withdrawn_once(self):
        uses=[use(),use('first',sources=('side:2:1',),scope_id='going_first',condition=False),
            use('second',sources=('side:2:1',),scope_id='going_second')]
        q=score(uses,side=[2])
        delta=log2(3)-1
        self.assertAlmostEqual(delta,.5849625007211562)
        self.assertEqual(q['side_directions']['going_first']['resident'],[1.,1.])
        self.assertEqual(q['side_directions']['going_first']['delta'],[0.,0.])
        self.assertAlmostEqual(q['side_directions']['going_second']['delta'][0],delta)
        self.assertAlmostEqual(q['score']['value'],1+.5*delta)

    def test_unmapped_restriction_scope_uses_final_bound_source_support(self):
        source = use('source', family='source', condition='source-available')
        target = use('target', family='target')
        layer, facts = fixture([source, target], variables={'source-available':False})
        facts['use_details'] = {'source':{'restriction_checks':[{'status':'unmapped','restriction':{'kind':'unhandled'}}]}}
        p = policy(); p['pass'] = p.pop('pass_')
        absent = evaluate_functional_quality(layer, policy=p, facts=facts)
        self.assertTrue(absent['complete'])
        self.assertEqual(absent['score']['value'], 1.)
        facts['variables']['source-available'] = True
        present = evaluate_functional_quality(layer, policy=p, facts=facts)
        self.assertFalse(present['complete'])
        self.assertIn('impacts', present['deferred'])
        self.assertIsNone(present['score']['upper'])

    def test_unused_optional_adoption_keeps_unknowns_out_of_effective_score(self):
        source = use('optional', family='adoption', condition='field-state', contributes=False)
        target = use('draw')
        impact = UseImpact('unknown-lock', 'optional', ('draw',), ('base',), ('cannot_draw',), ('record',),
            condition='lock-condition')
        result = score([source, target], variables={'field-state':None, 'lock-condition':None}, impacts=(impact,))
        self.assertTrue(result['complete'])
        self.assertEqual(result['score']['value'], 1.)
        self.assertFalse(result['unknowns'])
        required = replace(source, required=True, requirement_origin='original task adopts the field effect')
        changed = score([required, target], variables={'field-state':None, 'lock-condition':None}, impacts=(impact,))
        self.assertFalse(changed['complete'])
        self.assertEqual((changed['score']['lower'], changed['score']['upper']), (0.,1.))
        self.assertEqual(changed['hard_requirements'][0]['status'], 'unknown')
        # Unused inputs must still satisfy the facts schema.
        with self.assertRaises(ContractError):
            score([source, target], variables={'field-state':None}, impacts=(impact,))

    def test_known_unavailable_source_cannot_make_its_impact_unknown_relevant(self):
        source = use('source', family='source', condition=False)
        target = use('target', family='target')
        impact = UseImpact('unused-lock', 'source', ('target',), ('base',), ('cannot_draw',), ('record',), condition='unknown-lock')
        result = score([source, target], variables={'unknown-lock':None}, impacts=(impact,))
        self.assertTrue(result['complete'])
        self.assertEqual(result['score']['value'], 1.)
        self.assertFalse(result['unknowns'])

    def test_required_non_scoring_source_applies_impacts_and_records_the_real_loss(self):
        source = use("adopt", family="adoption", contributes=False, required=True,
                     requirement_origin="original task explicitly adopts this effect")
        target = use("benefit", sources=("main:2:1",))
        impact = UseImpact("mandatory", "adopt", ("benefit",), ("base",), ("adoption_lock",), ("review",))
        result = score([source, target], main=[1,2]+[99]*38, impacts=(impact,))
        self.assertEqual(result["stages"]["P"]["lower"], 1.)
        self.assertEqual(result["score"]["value"], 0.)
        self.assertEqual(result["hard_requirements"][0]["status"], "satisfied")
        self.assertTrue(all(r["reason_codes"] == ["adoption_lock"] for r in result["loss_records"]))
        self.assertAlmostEqual(sum(r["lower"] for r in result["loss_records"]), 1.)
        optional = score([replace(source, required=False, requirement_origin=None), target],
                         main=[1,2]+[99]*38, impacts=(impact,))
        self.assertEqual(optional["score"]["value"], 1.)
        unknown = score([replace(source, self_condition="adoption_access"), target],
                        main=[1,2]+[99]*38, variables={"adoption_access":None}, impacts=(impact,))
        self.assertEqual((unknown["score"]["lower"],unknown["score"]["upper"]),(0.,1.))

    def test_source_scoped_damage_and_loss_ledger_do_not_double_charge(self):
        a = use("a", family="tool")
        b = use("b", sources=("main:2:1", "main:2:2", "main:2:3"))
        impact = UseImpact("i", "a", ("b",), ("base",), ("restriction",), ("text",),
                           affected_source_ids=("main:2:3",))
        result = score([a,b], main=[1,2,2,2]+[99]*36, impacts=(impact,
            replace(impact, impact_id="i2", reason_codes=("resource",))))
        self.assertAlmostEqual(result["score"]["value"], 1+log2(2.9))
        losses = result["loss_records"]
        self.assertEqual({tuple(r["source_ids"]) for r in losses}, {("main:2:3",)})
        self.assertTrue(all(r["reason_codes"] == ["resource", "restriction"] for r in losses))
        self.assertAlmostEqual(sum(r["lower"] for r in losses), result["stages"]["P"]["lower"]-result["score"]["value"])

    def test_direction_override_recomputes_restoration_and_negative_delta(self):
        resident = use(condition=False)
        restored = replace(resident, use_id="restored", scope_id="going_first", self_condition=True)
        other = use("other", sources=("main:2:1",), family="g")
        damaged = replace(other, use_id="damaged", scope_id="going_second", self_condition=False)
        result = score([resident,restored,other,damaged], main=[1,2]+[99]*38)
        self.assertEqual(result["score"]["value"], 1.)
        self.assertEqual(result["side_directions"]["going_first"]["delta"], [1.,1.])
        self.assertEqual(result["side_directions"]["going_second"]["delta"], [-1.,-1.])
        self.assertAlmostEqual(sum(r["lower"] for r in result["loss_records"]), result["stages"]["P"]["lower"]-result["score"]["value"])
    def test_comparison_shares_consistent_unknown_completions(self):
        q = score([use(condition='shared-semantic-fact')], variables={'shared-semantic-fact': None})
        self.assertEqual(compare_functional_quality(q, q)['delta_range'], [0., 0.])
        self.assertEqual(compare_functional_quality(q, q)['status'], 'unresolved')
        bounds = functional_delta(q, q, ratio=.8)
        self.assertEqual(bounds['lower'], 0.)
        self.assertAlmostEqual(bounds['upper'], .2)
        self.assertEqual(bounds['bound_kind'], 'joint')

    def test_duplicate_proofs_and_independent_functions(self):
        self.assertEqual(score([use(), use("second")])["score"]["value"], 1.)
        self.assertEqual(score([use(condition=False), use("alternative")])["score"]["value"], 1.)
        self.assertEqual(score([use(), use("second", family="g")])["score"]["value"], 2.)

    def test_configuration_discount_is_not_an_effect_use_limit(self):
        result = score([use(sources=tuple(f"main:1:{i}" for i in (1, 2, 3)))], main=[1]*3+[99]*37)
        self.assertAlmostEqual(result["score"]["value"], log2(3.8))
        self.assertEqual(len(physical_sources(dict(main=[1]*3, extra=[], side=[]))), 3)

    def test_real_main_size_and_called_use(self):
        ordinary = score([use()], main=[1]+[99]*49)["score"]["value"]
        called = score([replace(use(), valuation_mode="called")], main=[1]+[99]*49)["score"]["value"]
        self.assertAlmostEqual(ordinary, log2(1.8))
        self.assertEqual(called, 1.)

    def test_theme_only_failure_preserves_base(self):
        themes = [dict(rule_id=k, increment=1, predicate={"grave_related": True}) for k in ("grave", "mill")]
        u = use(theme_eligible=("grave", "mill"), theme_conditions=(("grave", False), ("mill", False)))
        result = score([u], configuration=policy(themes))
        self.assertEqual(result["stages"]["P"]["lower"], 3.)
        self.assertEqual(result["score"]["value"], 1.)
        self.assertEqual(result["losses"][0]["lower"], 2.)

    def test_failed_self_support_is_not_deducted_twice(self):
        result = score([use(condition=False)])
        self.assertEqual(result["score"]["value"], 0.)
        self.assertEqual([r["lower"] for r in result["losses"]], [1., 0., 0.])

    def test_mandatory_loss_is_bound_and_deduplicated(self):
        a, b = use("a"), use("b", family="g")
        impact = UseImpact("i", "a", ("b",), ("base",), ("restriction",), ("card-text",))
        result = score([a,b], impacts=(impact, replace(impact, impact_id="i2", reason_codes=("cost",))))
        self.assertEqual(result["score"]["value"], 1.)
        self.assertEqual(result["losses"][2]["lower"], 1.)
        self.assertEqual(score([replace(a,self_condition=False),b], impacts=(impact,))["score"]["value"], 1.)

    def test_correlated_unknown_equal_endpoints_do_not_mean_complete(self):
        a = use(condition="choice")
        b = use("b", family="g", condition={"not": "choice"})
        result = score([a,b], variables={"choice": None})
        self.assertEqual(result["score"]["lower"], 1.)
        self.assertEqual(result["score"]["upper"], 1.)
        self.assertFalse(result["complete"])

    def test_side_discount_and_no_resident_supply(self):
        resident = use()
        side_first = use("sf", sources=("side:1:1", "side:1:2"), scope_id="going_first")
        side_second = replace(side_first, use_id="ss", scope_id="going_second")
        result = score([resident,side_first,side_second], side=[1,1])
        self.assertAlmostEqual(result["score"]["value"], log2(3.8))
        self.assertEqual(result["details"][3]["resident"]["value"], 1.)
        with self.assertRaises(ContractError):
            score([replace(side_first,scope_id="resident")], side=[1,1])

    def test_side_mandatory_damage_can_make_negative_increment(self):
        resident = use(sources=("main:1:1", "main:1:2", "main:1:3"))
        tool = use("s", sources=("side:2:1",), family="g", scope_id="going_first")
        impact = UseImpact("i", "s", ("u",), ("base",), ("mandatory",), ("text",), scope_id="going_first")
        result = score([resident,tool], main=[1]*3+[99]*37, side=[2], impacts=(impact,))
        self.assertAlmostEqual(result["score"]["value"], (1+log2(3.8))/2)
        self.assertLess(result["score"]["value"], result["details"][3]["resident"]["value"])

    def test_completion_budget_returns_outer_bound(self):
        result = score([use(condition={"all": ["a", "b"]})],
                       variables={"a":None,"b":None}, configuration=policy(budget=1))
        self.assertEqual((result["score"]["lower"],result["score"]["upper"]), (0.,1.))
        self.assertEqual(result["score"]["bound_kind"], "conservative")
        self.assertFalse(result["complete"])

    def test_large_unknown_scope_does_not_enumerate_thousands_for_the_same_outer_bound(self):
        variables={str(i):None for i in range(17)}
        result=score([use(condition={'all':list(variables)})],variables=variables)
        self.assertEqual((result['score']['lower'],result['score']['upper']),(0.,1.))
        self.assertEqual(result['completion_evaluated_count'],2)
        self.assertFalse(result['complete'])
        self.assertEqual(result['completion_results'],[])

    def test_stop_during_evaluation_keeps_a_conservative_incomplete_bound(self):
        layer,facts=fixture([use(condition={'all':['a','b']})],variables={'a':None,'b':None})
        p=policy();p['pass']=p.pop('pass_')
        calls=[]
        def stop():
            calls.append(1)
            return 'time_slice_exhausted' if len(calls)>1 else None
        result=evaluate_functional_quality(layer,policy=p,facts=facts,should_stop=stop)
        self.assertTrue(result['evaluation_timed_out'])
        self.assertFalse(result['complete'])
        self.assertIsNone(result['score']['value'])
        self.assertEqual((result['score']['lower'],result['score']['upper']),(0.,1.))
        self.assertEqual(result['completion_evaluated_count'],1)

    def test_quality_resumes_completion_and_loss_without_rescoring_prefix(self):
        import json
        from unittest.mock import patch
        from ygo_kito import construction_quality as quality
        layer, facts = fixture([use(condition={'all': ['a', 'b']})], variables={'a': None, 'b': None})
        facts['constraints'] = [{'any': ['a', 'b']}]
        p = policy()
        p['pass'] = p.pop('pass_')
        expected = evaluate_functional_quality(layer, policy=p, facts=facts)
        self.assertEqual(expected['completion_evaluated_count'], 3)
        progress, previous, phases = None, (0, 0), set()
        with (patch.object(quality, '_accumulate_functional_losses', wraps=quality._accumulate_functional_losses) as explain,
              patch.object(quality, '_functional_inputs', wraps=quality._functional_inputs) as score_inputs):
            for _ in range(10):
                checks = iter((None, 'time_slice_exhausted'))
                result = evaluate_functional_quality(layer, policy=p, facts=facts, continuation=progress,
                    resumable=True, should_stop=lambda: next(checks, 'time_slice_exhausted'))
                if 'calculation_pending' not in result:
                    break
                self.assertNotIn('evaluation_id', result)
                progress = json.loads(json.dumps(result['calculation_pending']))
                counters = progress['next_completion'], progress['next_loss']
                self.assertGreater(counters, previous)
                previous = counters
                phases.add('explanation' if progress['active_outcome'] is not None else 'completion')
            else:
                self.fail('quality calculation did not finish')
            self.assertEqual(explain.call_count, expected['completion_evaluated_count'])
            scored = [call for call in score_inputs.call_args_list if call.args[4] == 3]
            self.assertEqual(len(scored), 3 * expected['completion_evaluated_count'])
        self.assertEqual(phases, {'completion', 'explanation'})
        self.assertEqual(result, expected)
        self.assertTrue(all(row['lower'] == 0. for row in result['loss_records']))
        self.assertEqual(sum(row['upper'] for row in result['loss_records']), 1.)

    def test_equivalent_condition_results_reuse_scoring_and_keep_every_shared_completion(self):
        from unittest.mock import patch
        from ygo_kito import construction_quality as quality

        variables = dict.fromkeys('abcdefgh')
        condition = {'all': list(variables)}
        layer, facts = fixture([use(condition=condition)], variables=variables)
        p = policy()
        p['pass'] = p.pop('pass_')
        with (patch.object(quality, '_functional_inputs', wraps=quality._functional_inputs) as inputs,
              patch.object(quality, '_accumulate_functional_losses', wraps=quality._accumulate_functional_losses) as losses):
            result = evaluate_functional_quality(layer, policy=p, facts=facts)
        self.assertEqual(result['completion_evaluated_count'], 256)
        self.assertEqual([row['value'] for row in result['completion_results']], [0.] * 255 + [1.])
        self.assertEqual(inputs.call_count, 21)  # Three contexts at P and at each of two outcomes in V1/V2/S.
        self.assertEqual(losses.call_count, 2)
        self.assertEqual((result['losses'][0]['lower'], result['losses'][0]['upper']), (0., 1.))

    def test_constraint_skips_untouched_facts_and_keeps_the_original_resume_index(self):
        variables = dict.fromkeys('abcd')
        layer, facts = fixture([use(condition={'all': list(variables)})], variables=variables)
        facts['constraints'] = ['a']
        p = policy(budget=1)
        p['pass'] = p.pop('pass_')
        first = evaluate_functional_quality(layer, policy=p, facts=facts, resumable=True)
        progress = first['calculation_pending']
        self.assertEqual(progress['next_completion'], 8)
        self.assertEqual(progress['completion_scores'], [])
        second = evaluate_functional_quality(layer, policy=p, facts=facts, continuation=progress)
        self.assertEqual(second['calculation_pending']['completion_scores'], [[8, 0.]])

    def test_quality_work_rejects_changed_facts_and_crosses_policy_slice_budget(self):
        import json
        layer, facts = fixture([use(condition='p')], variables={'p': None})
        p = policy(budget=1)
        p['pass'] = p.pop('pass_')
        first = evaluate_functional_quality(layer, policy=p, facts=facts, resumable=True)
        progress = json.loads(json.dumps(first['calculation_pending']))
        self.assertEqual(progress['next_completion'], 1)
        self.assertEqual(progress['next_loss'], 1)
        changed = dict(facts, variables={'p': True})
        with self.assertRaisesRegex(ContractError, 'quality continuation belongs to different inputs'):
            evaluate_functional_quality(layer, policy=p, facts=changed, continuation=progress)
        result = evaluate_functional_quality(layer, policy=p, facts=facts, continuation=progress)
        self.assertEqual(result['completion_results'], [dict(facts={'p': False}, value=0.),
                                                       dict(facts={'p': True}, value=1.)])
        self.assertNotIn('calculation_pending', result)
        self.assertEqual(result['score']['bound_kind'], 'exact')

    def test_unrecognized_scope_has_no_invented_upper_bound(self):
        layer, facts = fixture([use()])
        facts["coverage"]["main:99"] = "unknown"
        p=policy();p["pass"]=p.pop("pass_")
        result=evaluate_functional_quality(layer,policy=p,facts=facts)
        self.assertEqual(result["score"]["lower"],0.)
        self.assertIsNone(result["score"]["upper"])

    def test_final_score_preference_and_binding(self):
        a=score([use()]); b=score([use(condition=False)])
        comparison=compare_functional_quality(a,b)
        self.assertEqual(comparison["preferred"],"before")
        changed=deepcopy(a);changed["score"]["value"]=99
        with self.assertRaises(ContractError):compare_functional_quality(changed,b)

    def test_original_requirement_failure_is_separate(self):
        result=score([use(condition=False,required=True,requirement_origin="task:ability")])
        self.assertEqual(result["hard_requirements"][0]["status"],"failed")
        self.assertEqual(result["score"]["value"],0.)
        self.assertEqual(compare_functional_quality(result,score([use()]))["status"],"unresolved")

    def test_policy_rejects_old_units_and_bare_reference_scores(self):
        with self.assertRaises(ContractError):functional_quality_config({"targets":{"f":3}})
        with self.assertRaises(ContractError):functional_pass_policy(dict(mode="reference_ratio",ratio=.8,reference={"score":70}))
        self.assertEqual(functional_pass_policy({"mode":"none"}),{"mode":"none"})
        p=policy();p["quality"]["required_scope"]=[[]]
        with self.assertRaises(ContractError):functional_quality_config(p["quality"])
        p=policy();p["quality"]["theme_rules"]=[dict(rule_id=[],increment=1,predicate={"kind":"mill"})]
        with self.assertRaises(ContractError):functional_quality_config(p["quality"])

    def test_out_of_candidate_source_and_missing_unknown_are_errors(self):
        with self.assertRaises(ContractError):score([use(sources=("main:2:1",))])
        with self.assertRaises(ContractError):score([use(condition="missing")])

    def test_same_name_mode_split_cannot_reset_first_copy(self):
        ordinary=use(sources=("main:1:1",))
        called=replace(use("second",sources=("main:1:2",)),valuation_mode="called")
        with self.assertRaises(ContractError):
            score([ordinary,called],main=[1,1]+[99]*38)

    def test_source_and_proof_order_do_not_change_price(self):
        rows=[use("u"+str(i),sources=("main:"+str(i)+":1",)) for i in range(1,11)]
        first=score(rows,main=list(range(1,11))+[99]*30)
        second=score(list(reversed(rows)),main=list(reversed(range(1,11)))+[99]*30)
        self.assertEqual(first["score"]["value"],second["score"]["value"])

    def test_deferred_scope_does_not_claim_exact_score(self):
        layer,facts=fixture([use()]);facts["scope_status"]["impacts"]="deferred"
        p=policy();p["pass"]=p.pop("pass_")
        result=evaluate_functional_quality(layer,policy=p,facts=facts)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["score"]["upper"])
        self.assertEqual(result["score"]["lower"],0.)


if __name__ == "__main__":
    unittest.main()
