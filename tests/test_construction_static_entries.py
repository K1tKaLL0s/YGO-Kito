"""Default configuration purposes through Evaluation; no supplied true facts."""
from dataclasses import replace
from types import SimpleNamespace
import unittest

from ygo_kito.build_contracts import DeckParts
from ygo_kito.construction_binding import CatalogBindingAdapter
from ygo_kito.construction_layer_flow import normalize_function_uses
from ygo_kito.construction_quality import evaluate_functional_quality, support_state
from ygo_kito.construction_relations import InputGroup, Need, RelationContext, Resource, UseRequirement
from tests.test_construction_functional_flow import fixture


class StaticEntryTests(unittest.TestCase):
    def joint_context(self, codes, before=()):
        from ygo_kito.construction_relations import JointConstraint
        initial, _ = self.evaluate()
        ids = {initial['use_details'][u.use_id]['card_id']: u.use_id
               for u in initial['uses'] if u.contributes}
        uses = tuple(UseRequirement('r:' + str(c), InputGroup('all', (Need('r:' + str(c),
            Resource('functional_operation', attributes=(f'catalog:{c}:1:op:0',)), mode='presence'),)),
            'required joint processing', functional_use_ids=(ids[c],)) for c in codes)
        constraints = (JointConstraint('original_order', tuple('r:' + str(c) for c in before),
            'before', 'original required order'),) if before else ()
        return SimpleNamespace(relations=RelationContext(uses, constraints=constraints))

    def test_joint_absence_can_precede_production_without_a_supplied_duel_order(self):
        self.assets.rows[1].update(type=2, desc='①：自己墓地没有卡存在的场合才能发动。抽1张。')
        self.assets.rows[2].update(type=2, desc='①：从自己卡组把1只怪兽送去墓地。')
        _, quality = self.evaluate(context=self.joint_context((1, 2)))
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertFalse(any(r['status'] == 'failed' for r in quality['hard_requirements']))

    def test_joint_absence_own_payment_follows_the_activation_check(self):
        self.assets.rows[1].update(type=33, desc='①：自己墓地没有卡存在的场合，'
            '把这张卡从手卡送去墓地才能发动。抽1张。')
        _, quality = self.evaluate(context=self.joint_context((1,)))
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertFalse(any(r['status'] == 'failed' for r in quality['hard_requirements']))

    def test_joint_mill_tracks_absence_and_clearance_for_each_legal_identity(self):
        self.assets.rows[1].update(type=33, desc='①：自己墓地没有卡存在的场合才能发动。给与对方500伤害。')
        self.assets.rows[2].update(type=33, desc='①：自己主要阶段才能发动。从自己卡组上面把1张卡送去墓地。')
        self.assets.rows[3].update(type=33, desc='①：自己主要阶段才能发动。从自己墓地把1只怪兽除外。')
        # Keep a legal second copy of each later actor after any one-card mill.
        self.deck = DeckParts(self.deck.main[:-2] + (1, 2))
        for codes, order, mixed, expected in (((1, 2), (2, 1), False, False),
                ((1, 2, 3), (2, 3, 1), False, True), ((1, 2, 3), (2, 3, 1), True, None)):
            with self.subTest(expected=expected):
                self.assets.rows[4]['type'] = 2 if mixed else 17
                facts, _ = self.evaluate(context=self.joint_context(codes, order))
                state = facts['fact_details']['state_order:required']
                self.assertIs(state['supported'], expected)
                if expected is None:
                    reasons = state['clearances'][0]['residual_conditions']
                    self.assertIn('RANDOM_IDENTITY_CONDITIONAL', {r['reason'] for r in reasons})

    def test_top_deck_payment_choices_use_one_scoring_function(self):
        self.assets.rows[1].update(type=33, desc='①：1回合1次，从自己卡组上面把最多3张卡送去墓地才能发动。'
            '这张卡的攻击力直到回合结束时上升因为这个效果发动而送去墓地的数量×500。'
            '②：自己场上的这张卡被破坏送去墓地的场合发动。自己抽1张。')
        facts, quality = self.evaluate()
        relevant = [(u, facts['use_details'][u.use_id]) for u in facts['uses'] if u.contributes
                    and facts['use_details'][u.use_id]['card_id'] == 1]
        boosts = [(u, detail) for u, detail in relevant if detail['operation']['kind'] == 'stats']
        self.assertEqual(sorted(detail['costs'][0]['quantity'] for _, detail in boosts), [1, 2, 3])
        self.assertEqual(len({u.score_family_id for u, _ in boosts}), 1)
        self.assertTrue(all(support_state(u.self_condition, facts['variables']) is True for u, _ in relevant))
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertEqual(quality['score']['value'], 2.)

    def test_state_order_resumes_schedule_and_allocation_without_rereading_relations(self):
        import json
        from unittest.mock import patch
        from ygo_kito.construction_relations import RelationBudget
        self.assets.rows[1].update(type=33, desc='①：自己墓地没有卡存在的场合才能发动。给与对方500伤害。')
        self.assets.rows[2].update(type=33, desc='①：自己主要阶段才能发动。从自己卡组把1只怪兽送去墓地。')
        context = self.joint_context((1, 2), (1, 2))
        catalog = CatalogBindingAdapter(self.assets).semantic_catalog
        options = dict(policy=self.policy, context=context)
        complete_work = {}
        expected = normalize_function_uses(self.task, self.deck, catalog, **options, work_state=complete_work)
        self.assertNotIn('calculation_pending', expected)
        expected_steps = complete_work.pop('state_orders')['explored_states']
        cursor = json.loads(json.dumps(complete_work))
        progress, seen = 0, set()
        with patch('ygo_kito.construction_layer_flow._functional_relations', side_effect=AssertionError('relation replay')):
            waiting = normalize_function_uses(self.task, self.deck, catalog, **options,
                continuation=cursor, budget=RelationBudget(allocations=0), should_stop=lambda: None)
            self.assertEqual(waiting['calculation_pending']['state_orders']['explored_states'], 0)
            for _ in range(500):
                work = {}
                result = normalize_function_uses(self.task, self.deck, catalog, **options,
                    continuation=cursor, budget=RelationBudget(allocations=1), work_state=work)
                if 'calculation_pending' not in result:
                    break
                cursor = json.loads(json.dumps(result['calculation_pending']))
                state = cursor['state_orders']
                self.assertGreater(state['explored_states'], progress)
                progress = state['explored_states']
                for check in state['checks'].values():
                    if 'result' not in check:
                        seen.add('allocation' if check['allocation'] else 'schedule')
            else:
                self.fail('finite joint state order did not finish')
        self.assertEqual(seen, {'schedule', 'allocation'})
        self.assertEqual(work['state_orders']['explored_states'], expected_steps)
        self.assertEqual(result['fact_details']['state_order:required'], expected['fact_details']['state_order:required'])
        self.assertEqual(result['hard_requirements'], expected['hard_requirements'])

    def test_joint_absence_requires_matching_sufficient_clearance(self):
        self.assets.rows[1].update(type=2, desc='①：自己墓地没有卡存在的场合才能发动。抽1张。')
        for quantity, produced, cleared, valid in ((1, '怪兽', '怪兽', True),
                (2, '怪兽', '怪兽', False), (1, '魔法卡', '怪兽', False)):
            with self.subTest(quantity=quantity, produced=produced, cleared=cleared):
                self.assets.rows[2].update(type=33, desc=f'①：自己主要阶段才能发动。从自己卡组把{quantity}张{produced}送去墓地。')
                self.assets.rows[3].update(type=33, desc=f'①：自己主要阶段才能发动。从自己墓地把1张{cleared}除外。')
                facts, quality = self.evaluate(context=self.joint_context((1, 2, 3), (2, 3, 1)))
                self.assertTrue(quality['complete'], quality['unknowns'])
                failures = [r for r in quality['hard_requirements'] if r['status'] == 'failed']
                self.assertEqual(not failures, valid, failures)
                if valid:
                    self.assertTrue(facts['fact_details']['state_order:required']['clearances'])

    def test_joint_absence_cannot_reuse_one_clearance_for_two_productions(self):
        self.assets.rows[1].update(type=2, desc='①：自己墓地没有卡存在的场合才能发动。抽1张。')
        for code in (2, 3):
            self.assets.rows[code].update(type=33, desc='①：自己主要阶段才能发动。从自己卡组把1只怪兽送去墓地。')
        self.assets.rows[4].update(type=33, desc='①：自己主要阶段才能发动。从自己墓地把1只怪兽除外。')
        _, quality = self.evaluate(context=self.joint_context((1, 2, 3, 4), (2, 3, 4, 1)))
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertTrue(any(r['status'] == 'failed' for r in quality['hard_requirements']))

    def test_joint_absence_allows_two_single_clearances_for_one_two_card_production(self):
        self.assets.rows[1].update(type=2, desc='①：自己墓地没有卡存在的场合才能发动。抽1张。')
        self.assets.rows[2].update(type=33, desc='①：自己主要阶段才能发动。从自己卡组把2只怪兽送去墓地。')
        for code in (3, 4):
            self.assets.rows[code].update(type=33, desc='①：自己主要阶段才能发动。从自己墓地把1只怪兽除外。')
        _, quality = self.evaluate(context=self.joint_context((1, 2, 3, 4), (2, 3, 4, 1)))
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertFalse(any(r['status'] == 'failed' for r in quality['hard_requirements']))

    def test_joint_absence_preserves_one_returned_copy_through_two_productions(self):
        self.assets.rows[1].update(type=2, desc='①：自己墓地没有卡存在的场合才能发动。抽1张。')
        self.assets.rows[5]['name'] = '匿名原料'
        for code in (2, 4):
            self.assets.rows[code].update(type=33, desc='①：自己主要阶段才能发动。从自己卡组把1只「匿名原料」怪兽送去墓地。')
        self.assets.rows[3].update(type=33, desc='①：自己主要阶段才能发动。从自己墓地把1只「匿名原料」怪兽回到卡组。')
        self.assets.rows[6].update(type=33, desc='①：自己主要阶段才能发动。从自己墓地把1只「匿名原料」怪兽除外。')
        _, quality = self.evaluate(context=self.joint_context((1, 2, 3, 4, 6), (2, 3, 4, 6, 1)))
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertFalse(any(r['status'] == 'failed' for r in quality['hard_requirements']))

    def test_joint_grave_absence_includes_activated_spell_rule_movement(self):
        self.assets.rows[1].update(type=2, desc='①：自己墓地没有卡存在的场合才能发动。抽1张。')
        self.assets.rows[2].update(type=2, desc='①：自己主要阶段才能发动。抽1张。')
        for card_type, valid in ((2, False), (0x20002, True)):
            with self.subTest(card_type=card_type):
                self.assets.rows[2]['type'] = card_type
                _, quality = self.evaluate(context=self.joint_context((1, 2), (2, 1)))
                self.assertTrue(quality['complete'], quality['unknowns'])
                self.assertEqual(not any(r['status'] == 'failed' for r in quality['hard_requirements']), valid)

    def test_joint_absence_replacement_redirects_future_cleanup_without_clearing_old_grave(self):
        self.assets.rows[1].update(type=2, desc='①：自己墓地没有卡存在的场合才能发动。抽1张。')
        self.assets.rows[2].update(type=2, desc='①：自己主要阶段才能发动。直到下个回合的结束时，被送去墓地的卡不去墓地而除外。')
        self.assets.rows[3].update(type=2, desc='①：抽1张。')
        for codes, before, valid in (((1, 2), (2, 1), True), ((1, 2, 3), (3, 2, 1), False)):
            with self.subTest(before=before):
                _, quality = self.evaluate(context=self.joint_context(codes, before))
                self.assertTrue(quality['complete'], quality['unknowns'])
                self.assertEqual(not any(r['status'] == 'failed' for r in quality['hard_requirements']), valid)

    def test_optional_placement_state_is_checked_after_its_own_token_production(self):
        self.assets.rows[1].update(type=2, desc='①：在自己场上把1只「匿名衍生物」'
            '（天使族·地·4星·攻/守2000）特殊召唤。'
            '自己场上没有「匿名衍生物」存在的场合，可以再从卡组把1张「匿名旅程」'
            '在自己的魔法与陷阱区域表侧表示放置。')
        self.assets.rows[2].update(type=0x20002, name='匿名旅程', desc='①：自己主要阶段才能发动。抽1张。')
        facts, quality = self.evaluate()
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertEqual(self.state(facts, 1), [True, False])

    def test_joint_field_absence_consumes_generated_token_and_real_clearance(self):
        self.assets.rows[1].update(type=2, desc='①：自己场上没有「匿名衍生物」存在的场合才能发动。抽1张。')
        self.assets.rows[2].update(type=2, desc='①：在自己场上把1只「匿名衍生物」'
            '（天使族·地·4星·攻/守2000）特殊召唤。')
        self.assets.rows[3].update(type=2, desc='①：从自己场上把1只怪兽除外。')
        for codes, before, valid in (((1, 2), (2, 1), False), ((1, 2, 3), (2, 3, 1), True)):
            with self.subTest(before=before):
                _, quality = self.evaluate(context=self.joint_context(codes, before))
                self.assertTrue(quality['complete'], quality['unknowns'])
                self.assertEqual(not any(r['status'] == 'failed' for r in quality['hard_requirements']), valid)

    def test_fixed_excavation_choice_and_return_is_one_non_targeted_addition(self):
        self.assets.rows[1].update(type=2,desc='这个卡名的卡在1回合只能发动1张，'
            '这张卡发动的回合，自己不能把怪兽特殊召唤。'
            '①：从自己卡组上面把3张卡翻开，从那之中选1张加入手卡。那之后，剩下的卡回到卡组。')
        facts,quality=self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(facts,1),[True])
        chosen,=[d['operation'] for d in facts['use_details'].values() if d['card_id']==1]
        self.assertTrue(chosen['random'])
        self.assertEqual(chosen['selection_method'],'choose_from_excavated')
        self.assertEqual(chosen['quantity'],1)

    def test_absence_condition_cannot_follow_uncleared_required_grave_production(self):
        from ygo_kito.construction_relations import JointConstraint
        self.assets.rows[1].update(type=2,desc='①：自己墓地没有卡存在的场合才能发动。抽1张。')
        self.assets.rows[2].update(type=2,desc='①：从自己卡组把1只怪兽送去墓地。')
        initial,_=self.evaluate()
        ids={initial['use_details'][u.use_id]['card_id']:u.use_id for u in initial['uses'] if u.contributes}
        uses=tuple(UseRequirement('r:'+str(c),InputGroup('all',(Need('r:'+str(c),
            Resource('functional_operation',attributes=(f'catalog:{c}:1:op:0',)),mode='presence'),)),
            'required joint processing',functional_use_ids=(ids[c],)) for c in (1,2))
        context=SimpleNamespace(relations=RelationContext(uses,constraints=(
            JointConstraint('grave_before_absence',('r:2','r:1'),'before','original required order'),)))
        _,quality=self.evaluate(context=context)
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertTrue(any(r['status']=='failed' for r in quality['hard_requirements']))

    def test_global_destination_replacement_preserves_optional_order_and_required_conflict(self):
        from ygo_kito.construction_relations import JointConstraint
        self.assets.rows[1].update(type=33,desc='①：自己·对方回合，自己墓地没有卡存在的场合，'
            '把这张卡从手卡送去墓地才能发动。'
            '直到下个回合的结束时，被送去墓地的卡不去墓地而除外。')
        self.assets.rows[2].update(type=2,desc='①：从自己卡组把1只怪兽送去墓地。')
        facts, quality=self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(facts,1),[True])
        self.assertEqual(self.state(facts,2),[True])
        ids={facts['use_details'][u.use_id]['card_id']:u.use_id for u in facts['uses'] if u.contributes}
        uses=tuple(UseRequirement('r:'+str(c),InputGroup('all',(Need('r:'+str(c),
            Resource('functional_operation',attributes=(f'catalog:{c}:1:op:0',)),mode='presence'),)),
            'required joint processing',functional_use_ids=(ids[c],)) for c in (1,2))
        ctx=SimpleNamespace(relations=RelationContext(uses,constraints=(
            JointConstraint('after_replacement',('r:1','r:2'),'before','original required order'),)))
        _, conflict=self.evaluate(context=ctx)
        self.assertTrue(conflict['complete'],conflict['unknowns'])
        self.assertTrue(any(r['status']=='failed' and r['requirement_id'].startswith('restriction_order:')
            for r in conflict['hard_requirements']))

    def test_aramesir_whole_turn_lock_distinguishes_normal_field_and_special_entry(self):
        self.assets.rows[1].update(type=2,desc='这个卡名的卡在1回合只能发动1张，'
            '这张卡发动的回合，自己不能把特殊召唤的怪兽以外的场上的怪兽的效果发动。'
            '①：自己场上没有「匿名衍生物」存在的场合才能发动。'
            '在自己场上把1只「匿名衍生物」（天使族·地·4星·攻/守2000）特殊召唤。')
        self.assets.rows[2].update(type=33,desc='①：自己主要阶段才能发动。抽1张。')
        without, quality=self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        checks=[c for d in without['use_details'].values() for c in d.get('restriction_checks',())]
        self.assertTrue(any(c['status']=='mapped' and c['affected_use_ids'] for c in checks))
        score=quality['score']['value']
        self.assets.rows[3].update(type=2,desc='①：从自己手卡把1只怪兽特殊召唤。')
        with_entry, quality=self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        target=[d for d in with_entry['use_details'].values() if d['card_id']==2]
        self.assertTrue(target[0]['special_summon_supported'])
        self.assertGreater(quality['score']['value'],score)

    def test_excavation_default_entry_scores_one_addition_and_one_damage_modifier(self):
        self.assets.rows[1].update(type=2,desc='这个卡名的卡在1回合只能发动1张，'
            '这张卡发动的回合，自己不能用卡的效果抽卡。'
            '①：从额外卡组把3张或6张卡里侧除外才能发动。'
            '把除外数量的卡从自己卡组上面翻开，从那之中选1张加入手卡，'
            '剩下的卡用喜欢的顺序回到卡组下面。'
            '这张卡的发动后，直到回合结束时对方受到的全部伤害变成一半。')
        for code in range(101,107):
            self.assets.rows[code]=dict(self.assets.rows[2],id=code,type=0x41,desc='怪兽2只')
        deck=replace(self.deck,extra=tuple(range(101,107)))
        facts, quality=self.evaluate(deck)
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(facts,1),[True]*4)
        self.assertEqual(len({u.score_family_id for u in facts['uses'] if u.contributes}),2)
        self.assertTrue(all(not d['operation'] or d['operation']['kind'] not in ('banish','return_deck','reveal_deck','damage')
            for d in facts['use_details'].values()))
        missing, quality=self.evaluate(replace(deck,extra=deck.extra[:2]))
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(missing,1),[False]*4)

    def test_counted_attack_checks_potential_tuners_without_asserting_random_hits(self):
        self.assets.rows[1].update(type=33,desc='①：1回合1次，可以发动。'
            '从自己卡组上面翻开5张并回到卡组。'
            '这个回合这张卡可以作出最多有所翻开之中的调整数量的攻击。')
        absent, quality=self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(absent,1),[False])
        self.assets.rows[3]['type']=0x1011
        possible, quality=self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(possible,1),[True])

    def test_other_card_excludes_source_entity_but_allows_another_same_name_copy(self):
        for code in self.assets.rows:self.assets.rows[code]['name']='普通库存'+str(code)
        self.assets.rows[1].update(type=33,name='匿名使者',desc='①：从手卡把1张其他的「匿名」卡送去墓地才能发动。'
            '这张卡从手卡特殊召唤。')
        deck = self.deck
        alone, quality = self.evaluate(deck)
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(alone,1),[False])
        paired, quality = self.evaluate(replace(deck,main=tuple(1 if c==2 else c for c in deck.main)))
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(paired,1),[True])

    def test_payment_name_comparison_rejects_same_names_and_accepts_other_names(self):
        for code in self.assets.rows:self.assets.rows[code]['name']='普通库存'+str(code)
        self.assets.rows[1].update(type=33,name='匿名使者',desc='①：可以从以下效果选择1个发动。'
            '●从手卡把1只「匿名」怪兽送去墓地才能发动。从自己墓地选和那只怪兽卡名不同的1只「匿名」怪兽加入手卡。'
            '●从自己墓地把1只「匿名」怪兽除外才能发动。和那只怪兽卡名不同的1只「匿名」怪兽从卡组送去墓地。')
        deck = self.deck
        same, quality = self.evaluate(deck)
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(same,1),[False,False])
        self.assets.rows[2]['name']='匿名支付'
        insufficient, quality=self.evaluate(deck)
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(insufficient,1),[False,False])
        self.assets.rows[3]['name']='匿名目标'
        different, quality = self.evaluate(deck)
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(different,1),[True,True])

    def test_generated_token_needs_no_deck_copy_but_optional_placement_needs_stock(self):
        self.assets.rows[1].update(type=2,desc='①：自己场上没有「匿名衍生物」存在的场合才能发动。'
            '在自己场上把1只「匿名衍生物」（天使族·地·4星·攻/守2000）特殊召唤。'
            '自己场上没有「匿名旅程」存在的场合，可以再从卡组把1张「匿名旅程」'
            '在自己的魔法与陷阱区域表侧表示放置。')
        missing, quality = self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(missing,1),[True,False])
        self.assets.rows[2]['name']='匿名旅程'
        present, quality = self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(present,1),[True,True])

    def test_effect_local_counters_and_opponent_response_reach_default_evaluation(self):
        self.assets.rows[1].update(type=33,desc='①：1回合1次，要让场上的卡破坏的效果的发动时才能发动。'
            '那个效果无效并破坏。②：1回合1次，对方的攻击宣言时以攻击怪兽为对象才能发动。'
            '场上的这张卡除外，那次攻击无效。③：这个②的效果除外的回合的结束阶段发动。'
            '这张卡特殊召唤。')
        facts, quality = self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertTrue(all(self.state(facts,1)),facts['use_details'])
        self.assets.rows[1]['desc']='③：这个②的效果除外的回合的结束阶段发动。这张卡特殊召唤。'
        missing, quality = self.evaluate()
        self.assertTrue(quality['complete'],quality['unknowns'])
        self.assertEqual(self.state(missing,1),[False])

    def test_f03_optional_after_activation_uses_need_no_actual_order(self):
        self.assets.rows[1].update(type=2, desc='①：抽1张。这个效果发动后，自己不能特殊召唤。')
        self.assets.rows[2].update(type=2, desc='①：从自己手卡把1只怪兽特殊召唤。')
        facts, quality = self.evaluate()
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertEqual(self.state(facts, 1), [True])
        self.assertEqual(self.state(facts, 2), [True])

    def test_extra_payment_choices_reach_default_evaluation_with_actual_stock(self):
        self.assets.rows[1].update(type=2, desc='①：自己主要阶段1开始时，'
            '把自己的额外卡组3张或6张里侧的卡随机里侧除外才能发动。'
            '除外的卡每有3张，自己抽1张。这张卡的发动后，直到回合结束时自己不能用卡的效果抽卡。')
        for code in range(101,107):
            self.assets.rows[code] = dict(self.assets.rows[2], id=code, type=0x41, desc='怪兽2只')
        deck = replace(self.deck, extra=tuple(range(101,107)))
        facts, quality = self.evaluate(deck)
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertEqual(self.state(facts,1), [True,True])
        self.assertEqual(len({u.score_family_id for u in facts['uses'] if u.contributes}), 1)
        supported, partial = self.evaluate(replace(deck, extra=deck.extra[:3]))
        self.assertEqual(self.state(supported,1), [True,False])
        self.assertEqual(quality['score']['value'], partial['score']['value'])
        failed, missing = self.evaluate(replace(deck, extra=deck.extra[:2]))
        self.assertEqual(self.state(failed,1), [False,False])
        self.assertTrue(missing['complete'])
        self.assertEqual(missing['score']['value'], 0)

    def test_effect_fusion_needs_an_eligible_target_without_invented_materials(self):
        self.assets.rows[1].update(type=2, desc='这个卡名的卡在1回合只能发动1张。'
            '①：支付1000基本分才能发动。把1只5星以下的融合怪兽当作融合召唤从额外卡组特殊召唤。'
            '这个效果特殊召唤的怪兽不能攻击，结束阶段破坏。')
        self.assets.rows[101] = dict(self.assets.rows[2], id=101, type=0x41, level=5,
            desc='「不存在的素材」＋「另一只不存在的素材」')
        facts, quality = self.evaluate(replace(self.deck,extra=(101,)))
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertEqual(self.state(facts,1), [True])
        self.assertEqual(len([u for u in facts['uses'] if u.contributes]), 1)
        self.assets.rows[101]['level'] = 6
        failed, quality = self.evaluate(replace(self.deck,extra=(101,)))
        self.assertEqual(self.state(failed,1), [False])
        self.assertTrue(quality['complete'])

    def test_after_lock_joint_order_and_whole_turn_are_distinct(self):
        from ygo_kito.construction_relations import JointConstraint
        self.assets.rows[1].update(type=2, desc='①：抽1张。这个效果发动后，自己不能特殊召唤。')
        self.assets.rows[2].update(type=2, desc='①：从自己手卡把1只怪兽特殊召唤。')
        initial, _ = self.evaluate()
        ids = {initial['use_details'][u.use_id]['card_id']:u.use_id for u in initial['uses'] if u.contributes}
        requirements = tuple(UseRequirement('required:'+str(c), InputGroup('all', (Need('required:'+str(c),
            Resource('functional_operation', attributes=(f'catalog:{c}:1:op:0',)), mode='presence'),)),
            'original joint requirement', functional_use_ids=(ids[c],)) for c in (1,2))
        context = SimpleNamespace(relations=RelationContext(requirements))
        _, arranged = self.evaluate(context=context)
        self.assertTrue(arranged['complete'], arranged['unknowns'])
        self.assertTrue(all(r['status']=='satisfied' for r in arranged['hard_requirements']))
        context.relations = replace(context.relations, constraints=(JointConstraint('forced',
            ('required:1','required:2'), 'before', 'original required dependency'),))
        _, impossible = self.evaluate(context=context)
        self.assertTrue(impossible['complete'])
        self.assertTrue(any(r['status']=='failed' for r in impossible['hard_requirements']))
        self.assets.rows[1]['desc'] = '①：抽1张。发动这个效果的回合，自己不能特殊召唤。'
        _, whole = self.evaluate()
        self.assertTrue(whole['complete'],whole['unknowns'])
        self.assertLess(whole['score']['value'], arranged['score']['value'])

    def test_optional_mutual_locks_fail_only_when_both_uses_are_required(self):
        self.assets.rows[1].update(type=2, desc='①：抽1张。这个效果发动后，自己不能特殊召唤。')
        self.assets.rows[2].update(type=2, desc='①：从自己手卡把1只怪兽特殊召唤。这个效果发动后，自己不能抽卡。')
        initial, optional = self.evaluate()
        self.assertTrue(optional['complete'], optional['unknowns'])
        ids = {initial['use_details'][u.use_id]['card_id']:u.use_id for u in initial['uses'] if u.contributes}
        required = tuple(UseRequirement('required:'+str(c), InputGroup('all', (Need('required:'+str(c),
            Resource('functional_operation', attributes=(f'catalog:{c}:1:op:0',)), mode='presence'),)),
            'original mandatory combination', functional_use_ids=(ids[c],)) for c in (1,2))
        _, joint = self.evaluate(context=SimpleNamespace(relations=RelationContext(required)))
        self.assertTrue(joint['complete'], joint['unknowns'])
        self.assertTrue(any(r['requirement_id'].startswith('restriction_order:') and r['status']=='failed'
            for r in joint['hard_requirements']))

    def test_opponents_lock_does_not_remove_own_configuration_use(self):
        self.assets.rows[1].update(type=2, desc='①：抽1张。发动这个效果的回合，对方不能特殊召唤。')
        self.assets.rows[2].update(type=2, desc='①：从自己手卡把1只怪兽特殊召唤。')
        _, quality = self.evaluate()
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertEqual(quality['losses'][2]['upper'], 0)

    def test_legacy_equipment_uses_configured_receiver_without_current_board(self):
        self.assets.rows[1].update(type=0x40002, desc='名字带有「匿名」的4星的怪兽才能装备。'
            '装备怪兽的原本攻击力变成2倍。发动后第2次的自己的准备阶段时这张卡破坏，'
            '自己受到装备怪兽的原本攻击力数值的伤害。')
        facts, quality = self.evaluate()
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertEqual(self.state(facts,1), [True])
        for row in self.assets.rows.values():row['name']='其他怪兽'
        missing, quality = self.evaluate()
        self.assertEqual(self.state(missing,1), [False])
        self.assertTrue(quality['complete'])

    def setUp(self):
        self.task, self.assets, _, _, self.decks, self.policy = fixture()
        for code, row in self.assets.rows.items():
            row.update(type=17, level=4, desc='普通怪兽。', name='匿名'+str(code))
        self.deck = self.decks[1]

    def evaluate(self, deck=None, context=None):
        deck = deck or self.deck
        catalog = CatalogBindingAdapter(self.assets).semantic_catalog
        facts = normalize_function_uses(self.task, deck, catalog, policy=self.policy, context=context)
        quality = evaluate_functional_quality(dict(axis=dict(task=self.task.to_dict(), inventory=deck.to_dict(), logic=None)),
            policy=self.policy, facts=facts)
        return facts, quality

    def state(self, facts, code):
        return [support_state(u.self_condition, facts['variables']) for u in facts['uses']
                if u.contributes and facts['use_details'][u.use_id]['card_id'] == code]

    def test_default_spell_and_normal_summoned_phase_reach_evaluation(self):
        self.assets.rows[1].update(type=2, desc='①：抽1张。')
        self.assets.rows[2].update(type=33, desc='①：自己主要阶段才能发动。抽1张。')
        facts, quality = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True])
        self.assertEqual(self.state(facts, 2), [True])
        self.assertTrue(quality['complete'])
        self.assertGreater(quality['score']['value'], 0)

    def test_default_normal_entries_preserve_joint_summon_capacity(self):
        for code in (1, 2):
            self.assets.rows[code].update(type=33, desc='①：这张卡召唤成功的场合才能发动。抽1张。')
        facts, _ = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True])
        self.assertEqual(self.state(facts, 2), [True])
        requested = tuple(UseRequirement('required:'+str(c), InputGroup('all', (Need('required:'+str(c),
            Resource('functional_operation', attributes=('catalog:'+str(c)+':1:op:0',)), mode='presence'),)),
            'explicit same-turn requirement', functional_use_ids=tuple(u.use_id for u in facts['uses']
                if facts['use_details'][u.use_id]['card_id'] == c)) for c in (1, 2))
        joint, quality = self.evaluate(context=SimpleNamespace(relations=RelationContext(requested)))
        self.assertTrue(any(h['requirement_id'] == 'joint_required' and h['condition'] is False
                            for h in joint['hard_requirements']))
        self.assertTrue(any(h['status'] == 'failed' for h in quality['hard_requirements']))

    def test_default_payment_checks_actual_stock_and_missing_support(self):
        self.assets.rows[1].update(type=2, desc='①：从自己卡组把1张「匿名2」送去墓地才能发动。抽1张。')
        facts, good = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True])
        absent = replace(self.deck, main=tuple(3 if c == 2 else c for c in self.deck.main))
        failed, bad = self.evaluate(absent)
        self.assertEqual(self.state(failed, 1), [False])
        self.assertLess(bad['score']['upper'], good['score']['value'])

    def test_default_external_target_is_scoped_to_its_configuration_purpose(self):
        self.assets.rows[1].update(type=2, desc='①：以对方场上1只怪兽为对象才能发动。那只怪兽破坏。')
        facts, quality = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True])
        self.assertTrue(quality['complete'])
        detail = next(v for v in facts['use_details'].values() if v['card_id'] == 1)
        self.assertTrue(any('configuration purpose' in s for s in detail['relation']['conditions']))

    def test_summon_procedure_supports_later_use_without_a_scoring_use(self):
        self.assets.rows[1].update(type=33, level=7,
            desc='①：对方场上的怪兽数量比自己场上的怪兽多的场合，这张卡可以从手卡特殊召唤。'
                 '②：自己主要阶段才能发动。抽1张。')
        facts, quality = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True])
        self.assertTrue(quality['complete'])
        self.assertEqual(len([u for u in facts['uses'] if u.contributes]), 1)

    def test_hand_and_random_deck_transfers_match_grave_uses_without_a_duel_state(self):
        self.assets.rows[1].update(type=33, desc='①：自己主要阶段才能发动。这张卡从手卡特殊召唤，'
            '从自己手卡选1只怪兽送去墓地。那之后，从自己卡组上面把3张卡送去墓地。')
        self.assets.rows[2].update(type=33, desc='①：这张卡被效果送去墓地的场合才能发动。自己抽1张。')
        facts, quality = self.evaluate()
        self.assertTrue(quality['complete'], quality['unknowns'])
        self.assertEqual(self.state(facts, 1), [True, True, True])
        self.assertEqual(self.state(facts, 2), [True])
        self.assertTrue(all(not v['costs'] for v in facts['use_details'].values()))
        for detail in facts['use_details'].values():
            self.assertFalse(any('random_recipient' in s for s in detail['relation']['unknown']))
        # Random milling alone is compatible support, never a specific call.
        self.assets.rows[1]['desc']='①：自己主要阶段才能发动。从自己卡组上面把3张卡送去墓地。'
        random_facts, random_quality = self.evaluate()
        self.assertTrue(random_quality['complete'])
        self.assertTrue(all(u.valuation_mode=='main_density' for u in random_facts['uses']))

    def test_choice_target_and_cost_do_not_leak_to_another_option(self):
        self.assets.rows[1].update(type=2, desc='从以下效果选择1个发动。'
            '\n●以自己墓地1只「不存在」怪兽为对象才能发动。那只怪兽加入手卡。'
            '\n●自己抽1张。')
        facts, quality = self.evaluate()
        values = {facts['use_details'][u.use_id]['operation']['choice']:support_state(u.self_condition, facts['variables'])
                  for u in facts['uses'] if u.contributes}
        self.assertEqual(values, {'option:1':False, 'option:2':True})
        self.assertTrue(quality['complete'], quality['unknowns'])

    def test_multi_zone_payment_counts_distinct_cards_once(self):
        self.assets.rows[1].update(type=2, desc='①：把自己手卡·墓地的2张「匿名2」卡除外才能发动。抽1张。')
        facts, _ = self.evaluate()
        self.assertEqual(self.state(facts, 1), [False])
        enough=replace(self.deck, main=tuple(self.deck.main)+(2,))
        facts, quality=self.evaluate(enough)
        self.assertEqual(self.state(facts, 1), [True])
        self.assertTrue(quality['complete'], quality['unknowns'])

    def test_complex_trigger_checks_configuration_presence_without_a_board(self):
        self.assets.rows[1].update(type=4, desc='①：场上有怪兽召唤·特殊召唤的场合，'
            '若自己场上有「匿名2」存在则能发动。从自己卡组上面把3张卡送去墓地。')
        facts, quality=self.evaluate()
        self.assertEqual(self.state(facts, 1), [True])
        self.assertTrue(quality['complete'], quality['unknowns'])
        absent=replace(self.deck,main=tuple(3 if c==2 else c for c in self.deck.main))
        facts, _=self.evaluate(absent)
        self.assertEqual(self.state(facts, 1), [False])

    def test_fusion_uses_complete_distinct_materials_including_its_source(self):
        for row in self.assets.rows.values():row['race']=2
        self.assets.rows[1].update(type=33,race=1,desc='①：这张卡被效果送去墓地的场合才能发动。'
            '融合怪兽卡决定的包含墓地的这张卡的融合素材怪兽从自己的手卡·场上·墓地用喜欢的顺序回到持有者卡组下面，'
            '把那1只融合怪兽从额外卡组融合召唤。')
        self.assets.rows[2]['race']=1
        self.assets.rows[101]=dict(self.assets.rows[3],id=101,name='匿名融合',type=0x41,desc='「匿名1」＋战士族怪兽')
        deck=replace(self.deck,extra=(101,))
        facts,quality=self.evaluate(deck)
        self.assertEqual(self.state(facts,1),[True,True])
        self.assertTrue(quality['complete'],quality['unknowns'])
        details=[v for v in facts['use_details'].values() if v['card_id']==1]
        self.assertTrue(all(v['inventory_checks']['fusion']['options'][0]['includes_card']==1 for v in details))
        absent=replace(deck,main=tuple(3 if c==2 else c for c in deck.main))
        failed,_=self.evaluate(absent)
        self.assertEqual(self.state(failed,1),[False,False])

    def test_normal_summon_prohibition_is_not_a_missing_board(self):
        self.assets.rows[1].update(type=33,desc='不能通常召唤。①：这张卡召唤成功的场合才能发动。抽1张。')
        facts,quality=self.evaluate()
        self.assertEqual(self.state(facts,1),[False])
        self.assertTrue(quality['complete'])

    def test_choice_payment_is_required_only_by_its_own_option(self):
        self.assets.rows[1].update(type=2,desc='从以下效果选择1个发动。'
            '\n●从自己卡组把1张「不存在」卡送去墓地才能发动。自己抽2张。'
            '\n●自己抽1张。')
        facts,quality=self.evaluate()
        values={facts['use_details'][u.use_id]['operation']['choice']:support_state(u.self_condition,facts['variables'])
            for u in facts['uses'] if u.contributes}
        self.assertEqual(values,{'option:1':False,'option:2':True})
        self.assertTrue(quality['complete'],quality['unknowns'])
        second=next(v for v in facts['use_details'].values() if v['card_id']==1 and v['operation']['choice']=='option:2')
        self.assertFalse(second['costs'])

    def test_unparsed_condition_is_a_program_gap_and_is_not_forced_true(self):
        self.assets.rows[1].update(type=33,desc='①：自己主要阶段，自己拥有未知计数的场合才能发动。抽1张。')
        facts,quality=self.evaluate()
        self.assertEqual(self.state(facts,1),[None])
        self.assertFalse(quality['complete'])
        reasons=[v['reason_code'] for v in facts['fact_details'].values()]
        self.assertTrue(any('activation_condition' in s for s in reasons))

    def test_default_candidate_adapter_consumes_static_applicability(self):
        from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
        from ygo_kito.construction_logic import LogicTag
        from tests.test_construction_binding import one_node
        from tests.test_construction_layer_flow import rows_for
        self.assets.rows[1].update(type=33,desc='①：自己主要阶段才能发动。从自己卡组上面把3张卡送去墓地。')
        graph=one_node(LogicTag('effect','卡组送墓'))
        binder=CatalogBindingAdapter(self.assets)
        _,evaluated,_=ConstructionLayerAdapter(binder).evaluate(self.task,graph,rows_for(self.task,[self.deck]),
            {0:binder(graph,self.task,self.deck)},[0],policy=self.policy)
        candidate=evaluated[0]
        self.assertTrue(candidate['quality_evaluation']['complete'])
        self.assertGreater(candidate['quality_evaluation']['score']['value'],0)
        self.assertFalse('host_condition_unspecified' in str(candidate['layer_evaluation']))

    def test_unrecognized_choice_branch_is_not_lost_from_coverage(self):
        self.assets.rows[1].update(type=2,desc='从以下效果选择1个发动。\n●自己抽1张。\n●调整尚未识别的计数。')
        facts,quality=self.evaluate()
        self.assertFalse(quality['complete'])
        effect=facts['coverage_details']['main:1']['effects'][0]
        self.assertEqual(effect['status'],'unknown')
        self.assertIn('unrecognized_operation',effect['gaps'])
        self.assertIn('调整尚未识别的计数',effect['record']['source_text'])

    def test_complete_processing_cannot_reuse_only_hand_monster(self):
        for code, row in self.assets.rows.items():
            if code != 1:
                row.update(type=2, desc='')
        self.assets.rows[1].update(type=33, desc='①：自己主要阶段才能发动。'
            '这张卡从手卡特殊召唤，从自己手卡选1只怪兽送去墓地。')
        facts, _ = self.evaluate()
        self.assertEqual(self.state(facts, 1), [False, False])
        details = [v for v in facts['use_details'].values() if v['card_id']==1]
        self.assertTrue(all(v['inventory_checks']['processing']['status']=='missing' for v in details))
        second = replace(self.deck, main=(*self.deck.main[:-1], 1))
        supported, _ = self.evaluate(second)
        self.assertEqual(self.state(supported, 1), [True, True])

    def test_complete_processing_can_move_same_monster_to_its_next_origin(self):
        for code, row in self.assets.rows.items():
            if code != 1:
                row.update(type=2, desc='')
        self.assets.rows[1].update(type=33, desc='①：自己主要阶段才能发动。'
            '这张卡从手卡特殊召唤。那之后，从自己场上选1只怪兽送去墓地。')
        facts, _ = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True, True])

    def test_alternative_processing_keeps_independent_entities(self):
        self.assets.rows[1].update(type=2, desc='从以下效果选择1个发动。'
            '\n●从自己手卡选1只「匿名2」特殊召唤。'
            '\n●从自己手卡选1只「匿名2」送去墓地。')
        facts, _ = self.evaluate()
        self.assertEqual(self.state(facts, 1), [True, True])
        self.assertEqual(self.deck.main.count(2), 1)

    def test_common_prefix_operation_cannot_recurse_through_options(self):
        self.assets.rows[1].update(type=2,desc='自己抽1张。从以下效果选择1个发动。'
            '\n●自己回复500基本分。\n●给与对方500伤害。')
        facts,quality=self.evaluate()
        self.assertTrue(any(v['card_id']==1 for v in facts['use_details'].values()))
        self.assertFalse(any('unscoped_choice_operation' in s for v in facts['use_details'].values()
            for s in v['relation']['unknown']))
        self.assertTrue(quality['complete'], quality['unknowns'])
        draws = [u for u in facts['uses'] if facts['use_details'][u.use_id]['card_id']==1
                 and facts['use_details'][u.use_id]['operation']['kind']=='draw']
        self.assertEqual(len(draws), 2)
        self.assertTrue(all(support_state(u.self_condition, facts['variables']) for u in draws))

    def test_unparsed_common_prefix_keeps_its_exact_coverage_gap(self):
        self.assets.rows[1].update(type=2,desc='调整尚未识别的计数。自己抽1张。从以下效果选择1个发动。'
            '\n●自己回复500基本分。\n●给与对方500伤害。')
        facts, quality = self.evaluate()
        self.assertTrue(any('unscoped_choice_operation' in s for v in facts['use_details'].values()
            for s in v['relation']['unknown']))
        self.assertFalse(quality['complete'])


if __name__ == '__main__':
    unittest.main()
