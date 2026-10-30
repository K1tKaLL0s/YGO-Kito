"""Anonymous targeted contracts. No engine, optimizer steps or training run."""
from collections import Counter
from copy import deepcopy
from types import SimpleNamespace
import unittest

import torch

from ygo_kito.autonomous_construction import AutonomousConstructionKernel
from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.build_model import BuildEncoder, BuildModelConfig, BuildRanker
from ygo_kito.coordinator_model import (CoordinatorModelConfig, CoordinatorTrainer,
    engineering_examples, public_scope_features, public_scope_input, scope_input,
    MECHANISM_FEATURE_VERSION)
from ygo_kito.effect_mechanisms import MechanismCatalog, MECHANISM_WIDTH
from ygo_kito.effect_records import EFFECT_RECORD_VERSION, SUMMARY_VERSION, SUMMARY_WIDTH
from ygo_kito.validation import ContractError


def row(code, desc='', **changes):
    value = dict(id=code, alias=0, ot=1, type=33, race=1, setcode=0, level=4,
                 attribute=1, atk=1000, name='anonymous-' + str(code), desc=desc)
    value['def'] = 1000
    value.update(changes)
    return value


def catalog(rows):
    assets = SimpleNamespace(rows={r['id']: r for r in rows}, limits={},
        receipt={'resources': {'cards': 'a'*64}}, check_task=lambda task: None,
        facts=lambda code: [.1]*6)
    return MechanismCatalog(assets)


def task_fixture(ids):
    return BuildTask.from_dict({
        'schema_version': 4, 'task_id': 'anonymous-mechanism-input', 'source': 'engineering_fixture',
        'candidate_budget': 2, 'environment': {'environment_id': 'anonymous', 'authority': 'custom',
            'release_cutoff': None, 'versions': {key: 'anonymous' for key in
                ('core', 'scripts', 'cards', 'banlist', 'protocol', 'card_pool')}},
        'pool': sorted(ids), 'sizes': {'main': 40, 'extra': 0, 'side': 0}, 'requirements': [],
        'goal': {'kind': 'deck_constraints', 'constraints': [{'id': 'monsters', 'zones': ['main'],
            'predicate': {'field': 'type_all', 'value': 1}, 'minimum': 40, 'maximum': 40}], 'preferences': []},
        'annotations': [{'tag': 'effect·anonymous', 'layer': 'engineering_goal', 'subject': 'self',
                         'source': 'anonymous-contract', 'condition': 'Not a playable deck or ability label.'}],
    })


def context():
    return deepcopy(engineering_examples()['records'][3]['context'])


class EffectRecordContracts(unittest.TestCase):
    def test_same_effect_different_ids_has_same_mechanism_summary(self):
        text = '①：自己主要阶段才能发动。抽1张。'
        cat = catalog([row(1, text), row(9001, text)])
        first, second = cat.effect_records(1)[0], cat.effect_records(9001)[0]
        self.assertEqual(first['record_version'], EFFECT_RECORD_VERSION)
        self.assertEqual({k: v for k, v in first.items() if k != 'card_id'},
                         {k: v for k, v in second.items() if k != 'card_id'})
        self.assertEqual(cat.mechanism_summary([1]), cat.mechanism_summary([9001]))
        self.assertEqual(len(cat.mechanism_summary([1])), SUMMARY_WIDTH)

    def test_quantities_owners_effect_indices_and_resources_are_not_collapsed(self):
        text = ('这个卡名的①②的效果1回合各能使用1次。\n'
                '①：丢弃1张手卡才能发动。抽1张。\n'
                '②：从自己手卡把2张卡送去墓地才能发动。从自己卡组上面把3张卡送去墓地。')
        cat = catalog([row(1, text)])
        first, second = cat.effect_records(1)
        self.assertEqual([(r['costs'][0]['effect_index'], r['costs'][0]['quantity']) for r in (first, second)], [(1, 1), (2, 2)])
        self.assertEqual(second['costs'][0]['owner'], 'self')
        self.assertEqual(second['costs'][0]['from_zones'], ['hand'])
        self.assertEqual(second['costs'][0]['to_zone'], 'grave')
        self.assertTrue(any(c['phase'] == 'activation_payment' and c['quantity'] == 2 for c in second['resource_changes']))
        self.assertTrue(any(c['phase'] == 'resolution' and c['kind'] == 'mill' and c['quantity'] == 3 for c in second['resource_changes']))
        self.assertEqual(first['count_limits'][0]['subject']['effect_indices'], [1])
        self.assertEqual(second['count_limits'][0]['subject']['effect_indices'], [2])
        second['costs'][0]['quantity'] = 99
        self.assertEqual(cat.effect_records(1)[1]['costs'][0]['quantity'], 2)

    def test_multiple_explicit_payments_and_unknown_clauses_stay_effect_scoped(self):
        cat = catalog([row(1, '①：丢弃1张手卡，支付500基本分才能发动。抽2张。'),
                       row(2, '①：将未定义的因果改写为另一条规则。')])
        first = cat.effect_records(1)[0]
        self.assertEqual([(c['kind'], c['quantity']) for c in first['costs']], [('send_grave', 1), ('pay_lp', 500)])
        self.assertEqual(first['costs'][1]['resource'], 'lp')
        unknown = cat.effect_records(2)[0]
        self.assertTrue(unknown['unknown'])
        self.assertEqual(unknown['conditions']['status'], 'unknown')
        self.assertFalse(unknown['legality_verified'])

    def test_legacy_eighteen_slots_and_build_ranker_schema_are_unchanged(self):
        cat = catalog([row(1, '①：丢弃1张手卡才能发动。抽1张。'),
                       row(2, '①：丢弃2张手卡才能发动。抽1张。')])
        self.assertEqual(MECHANISM_WIDTH, 18)
        self.assertEqual(cat.vector(1), cat.vector(2))  # Deliberately retain old compressed semantics.
        self.assertNotEqual(cat.effect_records(1)[0]['costs'], cat.effect_records(2)[0]['costs'])
        model = BuildRanker(BuildModelConfig(width=8, card_width=4, heads=2, feedforward=16), 2, 1)
        self.assertEqual(tuple(model.mechanism.weight.shape), (8, 18))
        self.assertFalse(any('record' in key for key in model.state_dict()))


class MaterialRecallContracts(unittest.TestCase):
    def setUp(self):
        self.cat = catalog([row(1, type=33 | 0x1000, level=3), row(2, level=4), row(3, level=4),
            row(6, '①：自己主要阶段才能发动。融合召唤1只怪兽。'),
            row(7, '调整＋调整以外的怪兽1只以上', type=1 | 0x2000, level=7),
            row(8, '4星怪兽×2', type=1 | 0x800000, level=4), row(9, type=2, level=4),
            row(10, '未知召唤方法', type=1 | 0x4000000, level=1)])

    def test_synchro_and_xyz_material_recall_is_symmetric(self):
        for target, material, partner, name in ((7, 1, 2, 'synchro'), (8, 2, 3, 'xyz')):
            score, reasons = self.cat.support(material, self.cat.summarize([target]))
            self.assertGreater(score, 0)
            self.assertIn('public_' + name + '_material_predicate_match_not_route_proof', reasons)
            score, reasons = self.cat.support(target, self.cat.summarize([material, partner]))
            self.assertGreater(score, 0)
            self.assertIn('public_' + name + '_material_compatibility_not_route_proof', reasons)
        self.assertEqual(self.cat.attribute_material_pairs(10, [1, 2]), ())

    def test_copy_alias_limits_nonmonsters_and_available_inventory_are_respected(self):
        self.assertEqual(self.cat.attribute_material_pairs(8, [9]), ())
        self.cat.assets.rows[2]['alias'] = 50; self.cat.assets.rows[3]['alias'] = 50
        self.cat.assets.limits[50] = 1
        self.assertEqual(self.cat.attribute_material_pairs(8, [2, 3]), ())
        self.cat.assets.rows[2]['alias'] = 0; self.cat.assets.rows[3]['alias'] = 0
        self.assertEqual(self.cat.attribute_material_pairs(8, [2], available_counts=Counter({2: 1})), ())
        self.assertEqual(self.cat.attribute_material_pairs(8, [2], available_counts=Counter({2: 2})), ((2, 2),))

    def test_fusion_observation_does_not_hide_other_goal_or_group_families(self):
        pool = (1, 2, 3, 6, 7, 8)
        core = (6, 7, 8)
        self.assertGreater(self.cat.summarize(core)['fusion_effects'], 0)
        kernel = object.__new__(AutonomousConstructionKernel)
        kernel.source_binding = {}; kernel.mechanisms = self.cat; kernel.assets = self.cat.assets
        kernel.builder = SimpleNamespace(task=SimpleNamespace(goal={}, sizes={'extra': 2}))
        goals = kernel._route_goals(pool, {'card_ids': core})
        self.assertEqual({g['kind'] for g in goals}, {'synchro_summon', 'xyz_summon'})
        groups = self.cat.construction_mechanism_groups(pool, core)
        self.assertEqual({g['group_id'].split('-')[0] for g in groups}, {'synchro', 'xyz'})
        kernel.source_binding = {'basic_cb_stage': 'after_construction'}
        self.assertEqual(kernel._route_goals(pool, {'card_ids': core}), [None])


class CoordinatorMechanismContracts(unittest.TestCase):
    def test_versioned_public_input_uses_semantics_independent_of_identity_hashes(self):
        cat = catalog([row(1, '①：自己主要阶段才能发动。抽1张。'),
                       row(2, '①：自己主要阶段才能发动。从自己卡组上面把3张卡送去墓地。')])
        task = task_fixture(cat.ids)
        encoder = BuildEncoder(task, cat.assets, BuildModelConfig())
        builder = SimpleNamespace(encoder=encoder)
        deck = DeckParts((1,), (), ())
        scope = {'actor_policy_sha256': '3'*64, 'duel_lora': None,
            'opponents': [{'opponent_id': 'anonymous', 'deck_sha256': digest(deck.to_dict()), 'driver_sha256': '4'*64, 'weight': 1.}],
            'initiative_weights': [.5, .5], 'unit': 'BO1', 'prediction_target': 'win_rate', 'versions': task.environment['versions']}
        opponents = {'anonymous': deck}
        old = public_scope_features(builder, task, deck, scope, opponents)
        first = public_scope_input(builder, task, deck, scope, opponents)
        self.assertEqual(first['scope_features'], old); self.assertEqual(len(old), 64)
        self.assertEqual(first['summary_version'], SUMMARY_VERSION)
        cat.assets.rows[1]['desc'] = cat.assets.rows[2]['desc']
        second = public_scope_input(builder, task, deck, scope, opponents)
        self.assertEqual(first['scope_features'], second['scope_features'])
        self.assertNotEqual(first['mechanism_features'], second['mechanism_features'])
        self.assertEqual(scope_input(first)[0], old)

    def test_legacy_restore_and_explicit_zero_extension_preserve_predictions(self):
        legacy = CoordinatorTrainer(CoordinatorModelConfig(hidden=4, steps=1))
        features = [.2]*64
        expected = legacy.forecast(context(), features)
        state = deepcopy(legacy.state()); state['config'].pop('mechanism_inputs')
        self.assertEqual(CoordinatorTrainer.restore(deepcopy(state)).forecast(context(), features), expected)
        migrated, receipt = CoordinatorTrainer.upgrade_mechanism_state(state)
        self.assertEqual(migrated['feature_version'], MECHANISM_FEATURE_VERSION)
        self.assertNotIn('mechanism_projection.weight', state['model'])
        self.assertFalse(receipt['training_executed']); self.assertFalse(receipt['ability_verified'])
        self.assertTrue(all(torch.equal(value, migrated['model'][name]) for name, value in state['model'].items()))
        restored = CoordinatorTrainer.restore(migrated)
        rich = {'feature_version': MECHANISM_FEATURE_VERSION, 'summary_version': SUMMARY_VERSION,
                'scope_features': features, 'mechanism_features': [.25]*(2*SUMMARY_WIDTH)}
        self.assertEqual(restored.forecast(context(), rich)['probability'], expected['probability'])
        with self.assertRaises(ContractError): legacy.forecast(context(), rich)
        restored.model.zero_grad(set_to_none=True)
        values = torch.tensor([[0.]*14]); scope_values = torch.tensor([features])
        restored.model.forward_scoped(values, scope_values, torch.tensor([rich['mechanism_features']]))[1].sum().backward()
        self.assertGreater(restored.model.mechanism_projection.weight.grad.abs().sum().item(), 0)
        self.assertEqual(restored.updates, 0)


if __name__ == '__main__':
    unittest.main()
