"""Reviewed mechanism producer meets the real construction consumer.

Synthetic cards only. No core execution, optimizer step or strength claim.
"""
from copy import deepcopy
import unittest
from unittest.mock import patch

from tests.test_effect_mechanisms import assets_fixture
from ygo_kito.build_contracts import BuildTask,DeckParts
from ygo_kito.build_pipeline import EXTRA_TYPES
from ygo_kito.construction_candidates import portfolio


def legal_base(task,assets):
    parts={'main':[],'extra':[],'side':[]}
    for zone in parts:
        for code in task.pool:
            if zone in ('main','extra') and bool(assets.rows[code]['type']&EXTRA_TYPES)!=(zone=='extra'):
                continue
            while parts[zone].count(code)<3 and len(parts[zone])<task.sizes[zone]:parts[zone].append(code)
    deck=DeckParts.from_dict(parts);assets.validate(task,deck)
    return deck


class EffectConstructionIntegrationTests(unittest.TestCase):
    def test_shrunken_pool_cannot_export_an_outside_fusion_target_or_break_portfolio(self):
        task,assets,_,kernel=assets_fixture();catalog=kernel.mechanisms
        core=[100,101,114]
        self.assertTrue(catalog.construction_mechanism_groups(task.pool,core))
        reduced=tuple(c for c in task.pool if c!=114)
        self.assertEqual(catalog.fusion_goals(reduced,core),[])
        groups=catalog.construction_mechanism_groups(reduced,core)
        self.assertEqual(groups,())
        raw=task.to_dict();raw.update(pool=list(reduced),sizes={'main':40,'extra':0,'side':0})
        smaller=BuildTask.from_dict(raw)
        rows=portfolio(smaller,assets,base=legal_base(smaller,assets),mechanism_groups=groups)
        self.assertTrue(rows)
        self.assertTrue(all(set(r['deck'].main)<=set(smaller.pool) for r in rows))

    def test_qualified_effect_binds_holder_selector_and_one_printed_effect(self):
        from ygo_kito.construction_binding import CatalogBindingAdapter
        from ygo_kito.construction_inventory import InventoryDependencies
        from tests.test_effect_mechanisms import FUSION
        from ygo_kito.construction_logic import ConstructionLogic, EffectRequirements, LogicConnector, LogicNode, LogicTag

        task, assets, _, _ = assets_fixture()
        assets.set_names = {'星河': 0x2d1}
        assets.rows[99999]['desc'] = assets.rows[100]['desc']
        binding = CatalogBindingAdapter(assets)
        inventory = InventoryDependencies(binding.semantic_catalog)
        holder = LogicTag('field', 'setcode:2d1')
        send = LogicTag('effect', '卡组送墓')
        fusion = LogicTag('effect', '墓地融合')
        requirements = EffectRequirements(selector_setcode=0x2d1, from_zone='deck',
                                          to_zone='grave', reason='effect')
        node = LogicNode('mill', (send, holder), requirements=requirements)
        self.assertTrue(inventory.draft_matches(100, node))
        self.assertFalse(inventory.draft_matches(101, node))
        self.assertFalse(inventory.draft_matches(99999, node))
        self.assertTrue(inventory.draft_matches(99999, LogicNode('mill', (send,), requirements=requirements)))
        self.assertFalse(inventory.draft_matches(101, LogicNode('combined', (send, fusion, holder))))
        target = LogicNode('fusion', (fusion, holder), requirements=EffectRequirements(
            trigger='sent_to_grave', trigger_reason='effect'))
        self.assertTrue(inventory.draft_matches(101, target))
        graph = ConstructionLogic('qualified-fixture', (node,), (), (node.node_id,), (node.node_id,))
        from ygo_kito.construction_retrieval import candidate_ids
        recalled, _ = candidate_ids(task, assets, graph, catalog=binding.semantic_catalog, limit=16)
        self.assertIn(100, recalled)
        proposal = binding.bind(graph, task, DeckParts((100,)), partial=True).proposal
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.bindings[0].effect_key, 'monster:1:0')
        self.assertIn('block_id', proposal.bindings[0].to_dict())

        assets.rows[100]['desc'] += '\n②：' + FUSION.split('②：')[1]
        route = ConstructionLogic('qualified-route', (node, target),
            (LogicConnector('sent', node.node_id, target.node_id, '送墓时发动'),), (node.node_id,), (target.node_id,))
        self.assertIsNone(binding.bind(route, task, DeckParts((100, 100)), partial=True).proposal)
        paired = binding.bind(route, task, DeckParts((100, 101)), partial=True).proposal
        self.assertIsNotNone(paired)
        self.assertEqual(tuple(b.card_ids for b in paired.bindings), ((100,), (101,)))

    def test_run_selected_passes_the_effect_draft_to_the_bounded_solver(self):
        from ygo_kito.build_semantics import solve_candidates
        _, assets, builder, kernel = assets_fixture()
        selection = kernel.select_task()
        task = BuildTask.from_dict(selection['task'])
        base = legal_base(task, assets)
        before = deepcopy(builder.updates)
        with patch('ygo_kito.build_semantics.solve_candidates', wraps=solve_candidates) as solve:
            result = kernel.run_selected(selection, base=base, verifier=None, run_mode='slice', max_iterations=1)
        self.assertFalse(result['construction_passed'])
        draft = result['effect_draft']
        self.assertEqual(result['phases'][0]['stage_3']['status'], 'effect_draft_ready')
        self.assertEqual(result['handoffs'][0]['role'], 'build_optimizer')
        self.assertEqual(result['handoffs'][0]['input_draft_sha256'], draft['logic_sha256'])
        solve.assert_called_once()
        fill = solve.call_args.kwargs
        self.assertEqual(fill['draft_graph'].to_dict(), draft['logic'])
        self.assertIs(fill['catalog'].assets, assets)
        self.assertLessEqual(fill['candidate_count'], 5)
        self.assertEqual(builder.updates, before)
        self.assertFalse(result['cb_verified'])
        self.assertFalse(result['ability_verified'])
