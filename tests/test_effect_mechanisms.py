"""Bounded synthetic contracts; no engine, optimizer steps or formal training."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch
torch.set_num_threads(2)

from ygo_kito.effect_mechanisms import analyze_card, MechanismCatalog, SEMANTIC_VERSION
from ygo_kito.construction_effect_blocks import reviewed_effect_blocks
from ygo_kito.construction_binding import CatalogBindingAdapter
from ygo_kito.construction_logic import LogicTag, LogicNode
from ygo_kito.build_contracts import BuildTask, DeckParts
from ygo_kito.build_model import (BuildModelConfig, BuildEncoder, BuildRanker,
    migrate_legacy_ranker, LEGACY_FEATURE_VERSION)
from ygo_kito.build_pipeline import BuildAssets
from ygo_kito.build_training import BuildTrainer, BuildTrainingConfig
from ygo_kito.autonomous_construction import AutonomousConstructionKernel, initialize_course_vocabulary
from ygo_kito.coordinator_model import CoordinatorTrainer, CoordinatorModelConfig
from ygo_kito.validation import ContractError
from ygo_kito.effect_count_limits import negation_counting

FUSION = ('这个卡名的①②的效果1回合各能使用1次。\n'
    '①：这张卡召唤·特殊召唤成功的场合才能发动。从自己卡组上面把3张卡送去墓地。\n'
    '②：这张卡被效果送去墓地的场合才能发动。融合怪兽卡决定的包含墓地的这张卡的融合素材怪兽'
    '从自己的手卡·场上·墓地用喜欢的顺序回到持有者卡组下面，把那1只融合怪兽从额外卡组融合召唤。')


def row(code, desc, **values):
    return dict(id=code,alias=0,ot=1,type=33,race=64,setcode=0x2d1,level=4,attribute=1,
                atk=1000,**{'def':1000},name='星河·'+str(code),desc=desc,**values)


def assets_fixture():
    from tests.test_autonomous_construction import fixture
    task,assets,_,_=fixture(initialize=False)
    assets.rows={c:row(c,'') for c in range(100,115)}
    assets.rows[100].update(race=1,desc='这个卡名的①的效果1回合各能使用1次。\n①：这张卡召唤·特殊召唤成功的场合才能发动。从卡组把「星河·100」以外的1只「星河」怪兽送去墓地。')
    assets.rows[101]['desc']=FUSION
    assets.rows[114].update(type=97,desc='「星河」怪兽＋水族怪兽\n①：未知结界规则。')
    assets.rows[1]=row(1,'完全未见的未知机制。');assets.rows[1].update(setcode=0,race=0x2000,name='外来未知')
    assets.rows[2]=row(2,'这张卡特殊召唤的回合，自己不能通常召唤。');assets.rows[2]['setcode']=0
    assets.rows[99999]=row(99999,'①：自己主要阶段才能发动。从自己卡组上面把3张卡送去墓地。');assets.rows[99999].update(setcode=0,race=0x2000,name='泛用效果怪兽')
    raw=task.to_dict();raw.update(pool=sorted(assets.rows),sizes={'main':40,'extra':1,'side':0},requirements=[],candidate_budget=2)
    raw['goal']={'kind':'deck_constraints','constraints':[{'id':'main-monsters','zones':['main'],
        'predicate':{'field':'type_all','value':1},'minimum':40,'maximum':40}],'preferences':[]}
    task=BuildTask.from_dict(raw)
    config=BuildTrainingConfig(model=BuildModelConfig(width=8,card_width=4,heads=2,layers=1,feedforward=16,max_tokens=256),batches=1)
    builder=BuildTrainer(task,assets,config);initialize_course_vocabulary(builder,assets.rows)
    coordinator=CoordinatorTrainer(CoordinatorModelConfig(hidden=4,steps=1))
    kernel=AutonomousConstructionKernel(builder,coordinator,assets=assets,host_available_ids=assets.rows,
        source_binding={'kind':'anonymous-synthetic-mechanism-course','learning_stage':'base'},allowed_theme_ids=['setcode-2d1'])
    return task,assets,builder,kernel


class EffectSemanticsTests(unittest.TestCase):
    def test_effect_trigger_material_cycle_and_per_name_limits_without_topic_mapping(self):
        p=analyze_card(row(900001,FUSION),'a'*64)
        e=p.grave_fusion[0]
        self.assertEqual(e.trigger['reason'],'effect');self.assertEqual(e.index,2)
        self.assertEqual(e.count_limit['scope'],'same_name_this_effect')
        move=next(o for o in e.operations if o['kind']=='return_fusion_materials')
        self.assertEqual(move['from_zones'],('hand','field','grave'))
        self.assertEqual(move['to_zone'],'deck_bottom');self.assertTrue(move['requires_this_grave_card'])
        self.assertIsNone(move['quantity'])  # The one summoned target is not one material.
        self.assertEqual(e.costs,());self.assertEqual(e.targets,())
        self.assertEqual(e.knowledge['targets'],'not_observed_in_recognized_activation')
        self.assertEqual(set(p.tags),{'卡组送墓','墓地融合'})
        self.assertEqual(analyze_card(row(7,FUSION)).tags,p.tags)

    def test_cost_and_resolution_sends_have_different_reasons(self):
        p=analyze_card(row(4,'①：丢弃1张手卡才能发动。从自己卡组上面把3张卡送去墓地。'))
        self.assertEqual(p.effects[0].costs[0]['reason'],'cost')
        self.assertEqual(next(o for o in p.effects[0].operations if o['kind']=='mill')['reason'],'effect')
        p=analyze_card(row(5,'①：自己主要阶段才能发动。从自己的手卡选1只怪兽送去墓地。'))
        self.assertEqual(p.effects[0].costs,())
        self.assertEqual(p.effects[0].operations[0]['reason'],'effect')
        self.assertNotIn('墓地融合',p.tags)

    def test_targeting_and_shared_limit_are_effect_scoped(self):
        p=analyze_card(row(8,'这个卡名的①②的效果1回合只能有1次使用其中任意1个。\n①：以自己墓地1只怪兽为对象才能发动。那张卡加入手卡。\n②：未知效果。'))
        self.assertEqual(p.effects[0].targets[0]['quantity'],1)
        self.assertEqual(p.effects[0].count_limit['subject']['effect_indices'],[1,2])
        self.assertEqual(p.effects[1].count_limit['scope'],'same_name_shared_effects')

    def test_restrictions_do_not_become_a_whole_deck_no_lock_claim(self):
        p=analyze_card(row(9,'这张卡特殊召唤的回合，自己不能通常召唤。'))
        r=p.restrictions[0]
        self.assertEqual(r['condition'],'special_summon_this_card');self.assertTrue(r['whole_turn'])
        self.assertIsNone(r['includes_set'])  # No unsupported claim that setting is allowed.
        intrinsic=analyze_card(row(91,'这张卡不能通常召唤。')).restrictions[0]
        self.assertEqual(intrinsic['scope'],'this_card');self.assertEqual(intrinsic['duration'],'intrinsic')
        lock=analyze_card(row(92,'①：自己主要阶段才能发动。这个回合，自己不能从额外卡组特殊召唤融合怪兽以外的怪兽。')).effects[0].restrictions[0]
        self.assertEqual(lock['kind'],'extra_fusion_only');self.assertEqual(lock['scope'],'player')
        p=analyze_card(row(10,'这张卡不能作为融合素材。\n①：未知效果。'))
        self.assertEqual(p.restrictions[0]['scope'],'this_card')
        _,assets,_,kernel=assets_fixture()
        summary=kernel.mechanisms.summarize([100,101,114])
        self.assertIsNone(summary['global_no_summon_restriction'])
        self.assertEqual(summary['summon_lock_assessment']['status'],'no_player_summon_lock_in_listed_effects')
        self.assertTrue(summary['summon_lock_assessment']['unreviewed_effects'])
        self.assertTrue(any(o['to_zone']=='deck_bottom' for o in summary['resource_flows']))
        self.assertLess(kernel.mechanisms.support(2,summary)[0],0)

    def test_unknown_negated_and_additional_conditions_are_not_guessed(self):
        for text in ('①：将梦境映射为下一局因果。','①：自己主要阶段才能发动。不能从自己卡组上面把3张卡送去墓地。'):
            p=analyze_card(row(11,text));self.assertEqual(p.tags,())
            self.assertIn('resolution',p.effects[0].unknown)
        p=analyze_card(row(12,'①：这张卡召唤·特殊召唤成功的场合，若自己场上有另1只怪兽才能发动。从卡组把1只「星河」怪兽送去墓地。'))
        self.assertEqual(p.effects[0].trigger['additional_conditions'],'unknown')
        _,assets,_,kernel=assets_fixture()
        assets.rows[1]['desc']='①：自己主要阶段才能发动。从对方卡组上面把3张卡送去墓地。'
        score,reasons=kernel.mechanisms.support(1,kernel.mechanisms.summarize([100,101,114]))
        self.assertNotIn('effect_deck_to_grave_feeds_core_triggers',reasons)

    def test_binding_uses_current_semantics_and_unknown_stays_unknown(self):
        _,assets,_,_=assets_fixture()
        tags,reviews=reviewed_effect_blocks(assets,[101,99999])
        self.assertEqual({t.value for t in tags},{'卡组送墓','墓地融合'})
        self.assertTrue(all(a.source==SEMANTIC_VERSION for a in reviews))
        binding=CatalogBindingAdapter(assets)
        self.assertEqual(binding._tag_status(assets.rows[101],LogicTag('effect','墓地融合'))[0],'satisfied')
        self.assertEqual(binding._tag_status(assets.rows[1],LogicTag('effect','墓地融合'))[0],'unknown')
        assets.rows[101]['desc']='未知机制'
        self.assertEqual(binding._tag_status(assets.rows[101],LogicTag('effect','墓地融合'))[0],'unknown')

    def test_use_three_counts_both_negation_types_and_leaves_two(self):
        p=analyze_card(row(18,'这个卡名的效果1回合可以使用最多3次。\n①：自己主要阶段才能发动。抽1张。'))
        limit=p.effects[0].count_limit
        self.assertEqual(limit['maximum'],3);self.assertEqual(limit['subject']['kind'],'same_name_all_effects')
        self.assertEqual(limit['reset_scope'],'each_turn')
        for outcome in ('activation_negated','effect_negated','resolution_not_applied'):
            self.assertEqual(negation_counting(limit,outcome),'counts')
            self.assertEqual(limit['maximum']-1,2)
        once=analyze_card(row(19,'这个卡名的效果1回合只能使用1次。\n①：自己主要阶段才能发动。抽1张。')).effects[0].count_limit
        self.assertEqual(negation_counting(once,'activation_negated'),'counts')
        self.assertEqual(once['maximum']-1,0)
        _,assets,_,kernel=assets_fixture()
        assets.rows[1]['desc']='这个卡名的效果1回合可以使用最多3次。\n①：自己主要阶段才能发动。抽1张。'
        three=kernel.mechanisms.vector(1)
        assets.rows[1]['desc']=assets.rows[1]['desc'].replace('最多3次','最多1次')
        one=kernel.mechanisms.vector(1)
        self.assertNotEqual(three,one)

    def test_trap_activation_scope_differs_from_global_monster_effect_limit(self):
        trap_effect=analyze_card(row(20,'这个卡名的卡1回合只能发动1张。\n①：自己主要阶段才能发动。抽1张。这张卡的发动后，直到回合结束时自己只能有1次把陷阱卡发动。')).effects[0]
        self.assertEqual(len(trap_effect.count_limits),2)
        self.assertEqual(negation_counting(trap_effect.count_limits[0],'activation_negated'),'unknown')
        trap=trap_effect.count_limits[1]
        self.assertEqual(trap['subject']['kind'],'player_trap_card_activations')
        self.assertEqual(negation_counting(trap,'activation_negated'),'does_not_count')
        for outcome in ('effect_negated','resolution_not_applied'):
            self.assertEqual(negation_counting(trap,outcome),'counts')
        global_limit=analyze_card(row(21,'①：只要这张卡在怪兽区域存在，那个期间双方在1回合只能有1次把怪兽的效果发动，在同1次的战斗阶段中只能用1只怪兽攻击。')).effects[0].count_limit
        self.assertEqual(global_limit['subject']['controller'],'both_separately')
        self.assertEqual(global_limit['applies_until'],'while_this_card_in_monster_zone')
        self.assertEqual(negation_counting(global_limit,'activation_negated'),'counts')

    def test_unreviewed_named_activation_and_specific_restriction_never_infer_refund(self):
        p=analyze_card(row(22,'这个卡名的卡1回合只能发动1张。\n①：自己主要阶段才能发动。抽1张。'))
        limit=p.effects[0].count_limit
        self.assertEqual(limit['count_event'],'card_activation')
        self.assertEqual(negation_counting(limit,'activation_negated'),'unknown')
        p=analyze_card(row(23,'①：这张卡发动后，直到下个回合结束时，自己只能发动1次特定种族以外的魔法·陷阱·怪兽的效果。'))
        self.assertEqual(negation_counting(p.effects[0].count_limit,'activation_negated'),'unknown')


class LearnerMechanismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):torch.set_num_threads(2)

    def test_mechanism_changes_actual_goal_and_pool_not_only_report(self):
        _,assets,_,kernel=assets_fixture()
        proposals=kernel.propose_tasks();self.assertEqual(proposals['status'],'model_ranked_tasks')
        candidate=proposals['candidates'][0]
        self.assertEqual(candidate['task']['goal']['route_goal']['kind'],'fusion_summon')
        self.assertEqual(candidate['task']['goal']['route_goal']['card_id'],114)
        self.assertEqual(candidate['task']['goal']['route_goal']['starting_conditions']['requires_opening_hand'],[100])
        self.assertIn(99999,candidate['task']['pool']);self.assertNotIn(1,candidate['task']['pool']);self.assertNotIn(2,candidate['task']['pool'])
        assets.rows[99999]['desc']='未知机制'
        # New source identity requires a new kernel, never reuse a sealed task.
        kernel=AutonomousConstructionKernel(kernel.builder,kernel.coordinator,assets=assets,host_available_ids=assets.rows,
            source_binding={'kind':'changed-synthetic-source'},allowed_theme_ids=['setcode-2d1'])
        changed=kernel.propose_tasks()['candidates'][0]
        self.assertNotIn(99999,changed['task']['pool'])
        assets.rows[101]['desc']='未知融合条件'
        kernel=AutonomousConstructionKernel(kernel.builder,kernel.coordinator,assets=assets,host_available_ids=assets.rows,
            source_binding={'kind':'unrecognized-synthetic-source'},allowed_theme_ids=['setcode-2d1'])
        self.assertTrue(all('route_goal' not in c['task']['goal'] for c in kernel.propose_tasks()['candidates']))

    def test_shared_learner_rankers_receive_mechanisms_and_four_phase_binding(self):
        task,assets,builder,kernel=assets_fixture()
        selected=kernel.select_task();self.assertEqual(selected['status'],'model_selected_task')
        before={r:{k:v.clone() for k,v in m.state_dict().items()} for r,m in builder.models.items()}
        result=kernel.run_selected(selected,verifier=None)
        self.assertTrue(result['alternation_completed']);self.assertFalse(result['cb_verified'])
        self.assertEqual([p['role'] for p in result['phases']],['build_goal','build_optimizer','build_goal','build_optimizer'])
        self.assertTrue(all(p['stage_3']['status']=='concrete_candidate_cb_pending' for p in result['phases']))
        last=result['phases'][0]['stage_3']['attempts'][-1]
        self.assertTrue(any(t['value']=='墓地融合' for r in last['text_reviews'] for t in r['reviewed_tags']))
        deck=DeckParts.from_dict(result['phases'][0]['proposal_deck']);bound=BuildTask.from_dict(selected['task'])
        batch=builder.encoder.batch(bound,[deck]);self.assertTrue(batch['mechanisms'].any())
        builder.models['build_goal'](batch).sum().backward()
        self.assertGreater(builder.models['build_goal'].mechanism.weight.grad.abs().sum().item(),0)
        for role,model in builder.models.items():
            self.assertTrue(all(torch.equal(v,model.state_dict()[k]) for k,v in before[role].items()))
        self.assertEqual(builder.updates,{'build_goal':0,'build_optimizer':0})

    def test_explicit_migration_preserves_old_weights_and_adam_and_never_relabels_restore(self):
        _,_,builder,_=assets_fixture();model=builder.models['build_goal']
        old={k:v.clone() for k,v in model.state_dict().items() if k!='mechanism.weight'}
        optimizer=deepcopy(builder.optimizers['build_goal'].state_dict());optimizer['param_groups'][0]['params'].pop()
        with self.assertRaises(RuntimeError):model.load_state_dict(old)
        new,adam,receipt=migrate_legacy_ranker(old,optimizer,source_feature_version=LEGACY_FEATURE_VERSION,source_checkpoint_sha256='a'*64)
        model.load_state_dict(new)
        self.assertTrue(all(torch.equal(new[k],v) for k,v in old.items()))
        self.assertEqual(new['mechanism.weight'].count_nonzero().item(),0)
        self.assertEqual(adam['state'],optimizer['state']);self.assertEqual(len(adam['param_groups'][0]['params']),len(old)+1)
        self.assertFalse(receipt['whole_checkpoint_restore_performed'])
        with self.assertRaises(ContractError):migrate_legacy_ranker(old,source_feature_version='unknown',source_checkpoint_sha256='a'*64)

    def test_actual_course_models_and_learner_reach_semantics_without_core_or_updates(self):
        from ygo_kito.course_models import CourseModels
        from ygo_kito.course_game_adapter import CourseTrainingConfig
        from ygo_kito.duel_model import DuelModelConfig
        from ygo_kito.lora import AdapterConfig
        # This test invokes no lifecycle/lock operation. On Windows an import-
        # only sentinel makes any accidental flock call fail, never simulate it.
        try:
            import fcntl
        except ImportError:
            import types,sys
            sentinel=types.ModuleType('fcntl')
            def forbidden_lock(*args):raise AssertionError('file locking is outside this inference-only test')
            sentinel.flock=forbidden_lock
            with patch.dict(sys.modules,{'fcntl':sentinel}):
                from ygo_kito.scenario_course import ScenarioCourse
        else:
            from ygo_kito.scenario_course import ScenarioCourse
        task,assets,_,_=assets_fixture()
        roles=('build_goal','build_optimizer','duel','coordinator')
        configs={r:AdapterConfig('repair-'+r,r,
            ('head.0',) if r.startswith('build_') else ('policy_head.0',) if r=='duel' else ('route_head',),rank=1) for r in roles}
        cfg=CourseTrainingConfig(model=DuelModelConfig(width=8,card_width=4,heads=2,feedforward=16),
                                game_seeds=(200,201),episode_seconds=120)
        with tempfile.TemporaryDirectory() as root:
            models=CourseModels.initialize(task,assets,cfg,configs,Path(root),None,assets.rows,
                {'kind':'anonymous-learner-inference-fixture','learning_stage':'base','construction_theme_ids':['setcode-2d1']})
            course=ScenarioCourse.__new__(ScenarioCourse)
            course.models=models;course.selection=None;course.deck=None;course.events=[]
            kernel=models.kernel;actual=kernel.run_selected;results=[]
            def without_native(selection,**kwargs):
                result=actual(selection,verifier=None,**kwargs);results.append(result);return result
            # Disable only the native-verifier boundary, not graph/fill/model providers.
            with patch.object(kernel,'run_selected',side_effect=without_native):
                with self.assertRaisesRegex(ContractError,'no concrete verified CB'):course._construct()
            self.assertTrue(results);self.assertTrue(all(r['mechanisms']['fusion_effects'] for r in results))
            self.assertTrue(all(r['alternation_completed'] for r in results))
            self.assertTrue(all(not r['cb_verified'] for r in results))
            self.assertIs(kernel.builder,models.builder)
            self.assertEqual(models.builder.updates,{'build_goal':0,'build_optimizer':0})


if __name__=='__main__':unittest.main()
