import copy
import json
from pathlib import Path
import unittest

from ygo_kito.training_scenarios import (validate_scenarios, volume_requirements, volume_met,
                                       check_2610_rates, eligible_card_ids)
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'configs/training-scenarios-v1.json').read_text())

    def test_confirmed_configuration_and_unchanged_historical_scopes(self):
        validate_scenarios(self.config)
        for period in ('2022-07', '2022-10'):
            a = self.config['periods'][period]['acceptance']
            self.assertEqual(a['external_at_least'], .6)
            self.assertEqual(a['frozen_external_bo3_min'] + a['frozen_mirror_bo3_min'], 400)
            self.assertIsNone(a['mirror_tolerance'])
        self.assertIsNone(self.config['periods']['2026-10']['fixed_theme'])

    def test_2610_thresholds_cannot_leak_into_common_or_historical_scope(self):
        for period in ('2022-07', '2022-10'):
            c = copy.deepcopy(self.config)
            c['periods'][period]['acceptance']['first_strictly_greater_than'] = .49
            with self.assertRaises(ContractError): validate_scenarios(c)
            with self.assertRaises(ContractError): check_2610_rates(period, 100, 100, 100, 100)
        c = copy.deepcopy(self.config); c['common']['first_strictly_greater_than'] = .49
        with self.assertRaises(ContractError): validate_scenarios(c)

    def test_exact_sixty_is_fast_and_slow_uses_matches_not_small_games(self):
        self.assertEqual(volume_requirements(60)['bo3_min'], 100)
        self.assertEqual(volume_requirements(60.0001)['minimum_bo3'], 400)
        self.assertTrue(volume_met(60, 1000, 100))
        self.assertFalse(volume_met(60, 1000, 99))
        self.assertTrue(volume_met(61, 600, 400))
        self.assertTrue(volume_met(61, 660, 440))
        self.assertFalse(volume_met(61, 1000, 100))
        self.assertFalse(volume_met(61, 599, 399))
        for invalid in (True, 0, -1, float('nan'), float('inf')):
            with self.assertRaises(ContractError): volume_requirements(invalid)

    def test_both_strict_thresholds_and_actual_small_game_denominators(self):
        self.assertFalse(check_2610_rates('2026-10', 49, 100, 40, 100)['arithmetic_thresholds_met'])
        self.assertFalse(check_2610_rates('2026-10', 50, 100, 39, 100)['arithmetic_thresholds_met'])
        self.assertTrue(check_2610_rates('2026-10', 50, 100, 40, 100)['arithmetic_thresholds_met'])
        self.assertIsNone(check_2610_rates('2026-10', 1, 1, 0, 0)['arithmetic_thresholds_met'])
        self.assertIsNone(check_2610_rates('2026-10', 50, 100, 40, 100, anomalies=1)['arithmetic_thresholds_met'])
        for kwargs in ({'stage':'available-bot-bo1'}, {'partition':'train'}, {'partition':'timing_pilot'}):
            with self.assertRaises(ContractError): check_2610_rates('2026-10', 100, 100, 100, 100, **kwargs)

    def test_missing_card_excludes_only_it_and_keeps_other_theme_candidates(self):
        self.assertEqual(eligible_card_ids([7, 8, 9, 100268022], [7, 8, 9], [7, 9]), [7, 9])

    def test_preparation_does_not_enable_training_or_stage2_first(self):
        c = copy.deepcopy(self.config); c['execution_enabled'] = True
        with self.assertRaises(ContractError): validate_scenarios(c)
        c = copy.deepcopy(self.config); c['periods']['2026-10']['stages'][1]['requires'] = []
        with self.assertRaises(ContractError): validate_scenarios(c)

    def test_unconfirmed_legacy_statistics_and_samples_cannot_silently_change(self):
        for period in ('2022-07', '2022-10'):
            for key, value in (('mirror_tolerance', .99), ('confidence_decision_rule', 'point_estimate_only'),
                               ('draw_and_repeated_observation_rule', 'discard_draws')):
                c = copy.deepcopy(self.config); c['periods'][period]['acceptance'][key] = value
                with self.assertRaises(ContractError): validate_scenarios(c)
        c = copy.deepcopy(self.config)
        c['periods']['2026-10']['acceptance']['legacy_evaluation_sampling'] = {'external_bo3_min':0,'mirror_bo3_min':0}
        with self.assertRaises(ContractError): validate_scenarios(c)


if __name__ == '__main__': unittest.main()
