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

    def test_run_selected_passes_current_groups_to_actual_portfolio_before_construction_ends(self):
        _,assets,builder,kernel=assets_fixture()
        selection=kernel.select_task();task=BuildTask.from_dict(selection['task'])
        expected=kernel.construction_mechanism_groups(selection);self.assertTrue(expected)
        base=legal_base(task,assets);calls=[];before=deepcopy(builder.updates)
        original=portfolio
        def observe(bound,current_assets,**kwargs):
            groups=kwargs.get('mechanism_groups')
            self.assertEqual(groups,expected)
            self.assertTrue(all(code in bound.pool for group in groups for cards in group['zones'].values() for code in cards))
            rows=original(bound,current_assets,**kwargs)
            calls.append({'task':bound.sha256,'groups':groups,'rows':len(rows)})
            return rows
        with patch('ygo_kito.construction_candidates.portfolio',side_effect=observe):
            result=kernel.run_selected(selection,base=base,verifier=None)
        self.assertTrue(calls)
        self.assertTrue(result['alternation_completed'])
        self.assertTrue(all(p['stage_3']['status']=='concrete_candidate_cb_pending' for p in result['phases']))
        self.assertEqual(result['construction_mechanism_groups'],expected)
        self.assertEqual(builder.updates,before)
        self.assertFalse(result['cb_verified']);self.assertFalse(result['ability_verified'])
