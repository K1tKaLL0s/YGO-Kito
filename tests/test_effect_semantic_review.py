"""Targeted review regressions and real synthetic Adam-state continuation.

No native engine, formal course, private checkpoint, download or WSL operation.
"""
from copy import deepcopy
import hashlib
import io
import unittest

import torch

from ygo_kito.build_model import (BuildModelConfig, BuildRanker)
from ygo_kito.effect_mechanisms import (analyze_card, MechanismCatalog, SEMANTIC_VERSION,
                                       MECHANISM_WIDTH)
from ygo_kito.construction_effect_blocks import reviewed_effect_blocks
from tests.test_effect_mechanisms import FUSION, row, assets_fixture


ISOLDE = ('战士族怪兽2只\n这个卡名的①②的效果1回合各能使用1次。\n'
    '①：这张卡连接召唤的场合才能发动。从卡组把1只战士族怪兽加入手卡。这个回合，自己不能把这个效果加入手卡的怪兽以及那些同名怪兽通常召唤·特殊召唤，那些怪兽效果也不能发动。\n'
    '②：从卡组把装备魔法卡任意数量送去墓地才能发动（同名卡最多1张）。和送去墓地的卡数量相同等级的1只战士族怪兽从卡组特殊召唤。')


class EffectReviewRegressions(unittest.TestCase):
    def test_isolde_parenthesis_separates_cost_from_resolution(self):
        for code in (59934749, 900001):
            p=analyze_card(row(code,ISOLDE))
            effect=p.effects[1]
            self.assertEqual(effect.knowledge['activation_boundary'],'recognized')
            self.assertEqual(len(effect.costs),1)
            self.assertEqual(effect.costs[0]['reason'],'cost')
            self.assertEqual(effect.costs[0]['from_zones'],('deck',))
            self.assertEqual(effect.trigger['activation_annotation'],'（同名卡最多1张）')
            self.assertIn('activation_annotation',effect.unknown)
            self.assertNotIn('send_grave',effect.kinds)
            self.assertNotIn('卡组送墓',p.tags)
        _,assets,_,_=assets_fixture()
        assets.rows[1]['desc']=ISOLDE
        tags,reviews=reviewed_effect_blocks(assets,[1])
        self.assertEqual({t.value for t in tags},{'检索','特召'})
        self.assertTrue(reviews)
        self.assertFalse(any(t.value in ('送墓','卡组送墓') for t in tags))

    def test_unrecognized_activation_boundary_is_not_a_positive_operation(self):
        desc='①：从卡组把1张卡送去墓地才能发动（条件（复杂））。抽1张。'
        p=analyze_card(row(900002,desc));e=p.effects[0]
        self.assertEqual(e.knowledge['activation_boundary'],'unknown')
        self.assertTrue(e.operations)
        self.assertTrue(all(o['reason']=='unknown' for o in e.operations))
        self.assertEqual(e.observed_operations,());self.assertEqual(p.tags,())
        later=analyze_card(row(900012,desc+'自己主要阶段可以发动。从自己卡组上面把3张卡送去墓地。'))
        self.assertEqual(later.effects[0].knowledge['activation_boundary'],'unknown')
        self.assertEqual(later.tags,())
        _,assets,_,kernel=assets_fixture();assets.rows[1]['desc']=desc
        _,reasons=kernel.mechanisms.support(1,kernel.mechanisms.summarize([100,101,114]))
        self.assertNotIn('effect_deck_to_grave_feeds_core_triggers',reasons)

    def test_fusion_summoned_protection_is_not_a_summon_instruction(self):
        for desc in ('①：融合召唤的这张卡不会被战斗破坏。',
                     '①：自己主要阶段才能发动。融合召唤的这张卡不会被战斗破坏。'):
            p=analyze_card(row(900003,desc))
            self.assertNotIn('fusion_summon',p.kinds)
            self.assertEqual(p.grave_fusion,())
        perform=analyze_card(row(900004,'①：自己主要阶段才能发动。从额外卡组把1只融合怪兽融合召唤。'))
        self.assertIn('fusion_summon',perform.kinds)

    def test_unknown_grave_condition_never_becomes_a_definite_fusion_opening(self):
        _,assets,_,kernel=assets_fixture()
        assets.rows[101]['desc']=FUSION.replace('这张卡被效果送去墓地的场合',
            '这张卡被效果送去墓地的场合，自己场上有另1只怪兽时')
        profile=kernel.mechanisms.card(101)
        self.assertTrue(any('fusion_summon' in e.kinds for e in profile.effects))
        self.assertEqual(profile.grave_fusion,());self.assertNotIn('墓地融合',profile.tags)
        self.assertEqual(kernel.mechanisms.fusion_goals(list(assets.rows),[100,101,114]),[])
        self.assertEqual(kernel.mechanisms.construction_mechanism_groups(list(assets.rows),[100,101,114]),())
        assets.rows[101]['desc']=FUSION.replace('才能发动。融合怪兽','才能发动（自己手卡有怪兽）。融合怪兽')
        self.assertEqual(kernel.mechanisms.card(101).grave_fusion,())
        self.assertEqual(kernel.mechanisms.fusion_goals(list(assets.rows),[100,101,114]),[])

    def test_unparsed_resolution_stays_out_of_an_opening(self):
        _,assets,_,kernel=assets_fixture()
        assets.rows[101]['desc']=FUSION+'随后须满足尚未识别的条件。'
        self.assertTrue(kernel.mechanisms.card(101).grave_fusion)
        self.assertFalse(kernel.mechanisms.card(101).grave_fusion[0].route_ready)
        self.assertEqual(kernel.mechanisms.fusion_goals(list(assets.rows),[100,101,114]),[])

    def test_starter_cannot_borrow_another_effects_send(self):
        _,assets,_,kernel=assets_fixture()
        assets.rows[100]['desc']=('这个卡名的①②的效果1回合各能使用1次。\n'
            '①：这张卡召唤·特殊召唤成功的场合才能发动。从卡组把1只「其他族」怪兽送去墓地。\n'
            '②：自己主要阶段，自己墓地有怪兽的场合才能发动。从卡组把1只「星河」怪兽送去墓地。')
        effects=kernel.mechanisms.card(100).effects
        self.assertTrue(effects[0].route_ready);self.assertFalse(effects[1].route_ready)
        self.assertEqual(kernel.mechanisms.fusion_goals(list(assets.rows),[100,101,114]),[])

    def test_one_card_hand_opening_does_not_assume_tribute_or_extra_access(self):
        _,assets,_,kernel=assets_fixture();catalog=kernel.mechanisms;pool=list(assets.rows)
        self.assertTrue(catalog.fusion_goals(pool,[100,101,114]))
        original=deepcopy(assets.rows[100])
        for changes in ({'level':8},{'type':0x2001},{'type':0x2000021},
                        {'desc':'自己场上有未知条件的怪兽存在的场合才能通常召唤。\n'+original['desc']},
                        {'desc':'这张卡不能通常召唤。\n'+original['desc']}):
            with self.subTest(changes=changes):
                assets.rows[100]=dict(original,**changes)
                self.assertEqual(catalog.fusion_goals(pool,[100,101,114]),[])
        assets.rows[100]=original
        self.assertTrue(catalog.fusion_goals(pool,[100,101,114]))

    def test_relationship_adapter_exports_the_existing_three_key_contract(self):
        _,assets,_,kernel=assets_fixture();selected=kernel.select_task()
        groups=kernel.construction_mechanism_groups(selected)
        self.assertEqual(kernel._current_binding()['semantic_version'],SEMANTIC_VERSION)
        self.assertEqual(kernel.builder.encoder.binding()['semantic_version'],SEMANTIC_VERSION)
        self.assertTrue(groups)
        for group in groups:
            self.assertEqual(set(group),{'group_id','zones','source'})
            self.assertEqual(set(group['zones']),{'main','extra','side'})
            self.assertEqual(set(group['zones']['main']),{100,101})
            self.assertEqual(group['zones']['extra'],[114])
            self.assertTrue(group['source'].startswith(SEMANTIC_VERSION+':'))
            self.assertLessEqual(sum(map(len,group['zones'].values())),6)




if __name__=='__main__':unittest.main()
