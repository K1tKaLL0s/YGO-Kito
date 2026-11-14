"""Current layer feedback, unknown dependencies and bounded recall; no CB."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import unittest

from ygo_kito.build_contracts import BuildTask,digest
from ygo_kito.construction_binding import CatalogBindingAdapter
from ygo_kito.construction_inventory import recall_dependencies,matches,selector,archetype_names
from ygo_kito.construction_learning import candidate_pairs,validate_pair,cycle_pairs
from ygo_kito.effect_mechanisms import MechanismCatalog
from ygo_kito.validation import ContractError
from tests.test_construction_inventory import fixture
from tests.test_construction_layer_flow import run_fill
from tests.test_construction_functional_flow import functional_fill


class ConstructionUnificationTests(unittest.TestCase):
    def test_missing_printed_cost_object_does_not_earn_coverage(self):
        value,_,_=fixture();task,assets,graph,_,decks,_=value
        raw=task.to_dict();raw['requirements']=[];value[0]=BuildTask.from_dict(raw)
        assets.rows[2]['desc']='①：从手卡把1只7星以上的「不存在」怪兽送去墓地才能发动。从自己卡组上面把3张卡送去墓地。'
        value[3]=CatalogBindingAdapter(assets)
        blocked=replace(decks[0],main=tuple(sorted((2,)+decks[0].main[1:])),side=(1,))
        value[4]=[decks[0],blocked]
        result=run_fill(value);rows=result['candidate_trace']['candidates']
        inventory=rows[1]['layer_evaluation']['relations']['inventory_dependencies']
        self.assertEqual(inventory['cards']['2']['effects'][0]['status'],'missing')
        self.assertTrue(inventory['known_deficits'])
        functions=rows[1]['layer_evaluation']['axis']['overview']['functions']
        self.assertFalse(functions['node:goal:main']['supported_copies'])
        self.assertFalse(result['layer_selection']['preferred_pairs'])
        self.assertEqual(candidate_pairs(value[0],result['learning_candidates']),[])

    def test_recall_finds_external_support_before_task_identity_is_sealed(self):
        value,_,_=fixture();task,assets=value[:2]
        initial=tuple(c for c in task.pool if c!=2)
        pool,trace=recall_dependencies(MechanismCatalog(assets),initial,task.pool,limit=2)
        self.assertIn(2,pool)
        self.assertEqual(trace['events'][0]['consumer'],1)
        self.assertEqual(trace['events'][0]['query']['level'],7)
        unavailable,_=recall_dependencies(MechanismCatalog(assets),initial,initial,limit=2)
        self.assertNotIn(2,unavailable)
        bounded,trace=recall_dependencies(MechanismCatalog(assets),initial,task.pool,checks=0)
        self.assertEqual(bounded,tuple(sorted(initial)));self.assertTrue(trace['truncated'])

    def test_quality_labels_bind_actual_inventory_and_reject_changed_evidence(self):
        task,_,_,result=functional_fill()
        pairs = candidate_pairs(task, result['learning_candidates'])
        self.assertTrue(pairs)
        pair = pairs[0]
        validate_pair(task, pair)
        self.assertNotEqual(pair['better'],pair['worse'])
        bad=deepcopy(pair);bad['better']=bad['worse']
        with self.assertRaises(ContractError):validate_pair(task,bad)
        bad=deepcopy(pair);bad['evidence']['comparison']['status']='undetermined'
        with self.assertRaises(ContractError):validate_pair(task,bad)
        bad=deepcopy(pair);bad['evidence']['evaluations']['before']['score']['value']=100
        with self.assertRaises(ContractError):validate_pair(task,bad)
        with self.assertRaises(ContractError):validate_pair(SimpleNamespace(sha256='different'),pair)

    def test_recall_pool_supply_can_exceed_deck_section_limits(self):
        value,_,_=fixture();task,assets=value[:2]
        for code in range(200,230):assets.rows[code]=dict(assets.rows[101],id=code)
        initial=tuple(c for c in task.pool if c!=2)+tuple(range(200,230))
        pool,trace=recall_dependencies(MechanismCatalog(assets),initial,tuple(sorted(assets.rows)),limit=2)
        self.assertIn(2,pool);self.assertTrue(trace['events'])

    def test_unparsed_fusion_materials_do_not_count_as_present(self):
        value,dependencies,_=fixture();assets=value[1]
        assets.rows[101]['desc']='「绯色素材」＋攻击力2000以上的怪兽\n①：自己主要阶段才能发动。抽1张。'
        result=dependencies.evaluate(value[4][1])
        self.assertEqual(result['cards']['101']['materials']['status'],'unknown')
        self.assertIn('materials:101',result['unknown_requirements'])

    def test_rule_name_treatment_counts_but_effect_mentions_do_not(self):
        query=selector('「匿名系列」陷阱卡')
        row=dict(name='别名陷阱',type=4,desc='这个卡名在规则上也当作「匿名系列」卡使用。')
        self.assertTrue(matches(row,query))
        row['desc']='从卡组把1张「匿名系列」卡加入手卡。'
        self.assertFalse(matches(row,query))

    def test_whole_inventory_deficit_is_visible_even_outside_selected_function(self):
        value,dependencies,_=fixture()
        value[1].rows[3]['desc']='①：自己主要阶段才能发动。从卡组把1张「另一个配套」卡加入手卡。'
        actual=dependencies.evaluate(value[4][1],value[2])
        self.assertTrue(any(k.startswith('effect:3:') for k in actual['known_deficits']))
        self.assertFalse(actual['scoped_deficits'])

    def test_archetype_membership_uses_catalog_codes_not_translated_name_substrings(self):
        value,_,_=fixture();assets=value[1]
        assets.set_names={'绯色':0x27}
        assets.rows[2].update(setcode=0x39,name='女绯色')
        from ygo_kito.construction_inventory import InventoryDependencies
        dependencies=InventoryDependencies(MechanismCatalog(assets))
        self.assertTrue(dependencies.evaluate(value[4][1])['known_deficits'])
        assets.rows[2].update(setcode=0x27,name='完全不同的译名')
        self.assertFalse(dependencies.evaluate(value[4][1])['known_deficits'])

    def test_early_quality_signal_keeps_actual_iteration_and_deduplicates_evaluations(self):
        task,_,_,phase=functional_fill()
        result=dict(phases=[dict(stage_3=phase,phase_number=9,optimization_iteration=8),dict(stage_3=phase),dict(stage_3={'portfolio':[]}),
                            dict(stage_3={'portfolio':[]})],retained_candidates=[])
        pairs=cycle_pairs(task,result)
        self.assertEqual(len(pairs),6);validate_pair(task,pairs[0])
        self.assertEqual(pairs[0]['evidence']['construction_phase'],9)
        self.assertEqual(pairs[0]['evidence']['optimization_iteration'],8)

    def test_cycle_uses_comparisons_beyond_the_retained_winner(self):
        task,_,decks,stage=functional_fill()
        self.assertEqual(len(stage['learning_candidates']),len(decks))
        winner, = stage['portfolio']
        self.assertEqual(winner['deck'], stage['best_deck'])
        pairs=cycle_pairs(task,dict(phases=[dict(stage_3=stage)]))
        self.assertEqual(len(pairs),6);validate_pair(task,pairs[0])

    def test_pinned_archetype_registry_is_available_without_native_strings_file(self):
        from ygo_kito.construction_inventory import InventoryDependencies
        value,_,_=fixture();assets=value[1]
        assets.receipt=dict(source_commits={'database':'217ae165c1886af2fc36b823fc08f9fc3ec13185'},
            resources={'cards':'ff52f585de24a762a4e613ac37654b1a7fb15a58990c14f5eada85f28c3be152'})
        dependencies=InventoryDependencies(MechanismCatalog(assets))
        self.assertGreater(len(dependencies.set_names),500)
        query=dependencies.resolve_query(selector('「武神」怪兽'))
        self.assertEqual(query['setcode'],0x88)
        self.assertFalse(matches(dict(name='女武神',type=1,setcode=0x122),query))
        with self.assertRaises(ContractError):archetype_names('wrong','wrong')


if __name__=='__main__':unittest.main()
