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
