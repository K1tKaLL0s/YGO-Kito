"""Public DTO progress/size diagnostics; no native calls or policy changes."""
import unittest

from tests.fixtures import request
from ygo_kito.contracts import ActionSelection, DecisionRequest, validate_selection
from ygo_kito.course_game_adapter import _FirstTurnObservation
from ygo_kito.duel_model import DuelModelConfig, PlayerEncoder
from ygo_kito.validation import ContractError


def typed(turn, phase, observer, message, kind, value):
    d = request(); d['context']['seed'] = None
    d['observation'].update(turn=turn, turn_player=(turn-1)%2, phase=phase, observer=observer)
    d['observation']['cards'] = []
    d['prompt'] = {'message': message}
    d['actions'] = [{'action_id': 'choice', 'kind': kind, 'card_refs': [], 'value': value}]
    return DecisionRequest.from_dict(d)


class ModelProgressTests(unittest.TestCase):
    def test_progress_separates_priority_passes_from_real_phase_control(self):
        windows = [typed(1, 'main1', 0, 11, 'pass', 6),
            typed(1, 'battle', 1, 16, 'pass', None),
            typed(1, 'battle', 0, 10, 'pass', 3),
            typed(2, 'main1', 1, 11, 'select', 8)]
        class NormalFixture:
            def __init__(self): self.pending = None; self.windows = iter(windows)
            def next_decision(self): self.pending = next(self.windows, None); return self.pending
            def submit(self, selected): validate_selection(self.pending, selected)
        class Observed(_FirstTurnObservation, NormalFixture): pass
        watched = {'decision_windows': 0, 'actual_first_core_seat': None}
        engine = Observed(course_observations=watched)
        while (r := engine.next_decision()) is not None:
            engine.submit(ActionSelection(r.context.run_id, r.duel_id, r.decision_id, 'choice'))
        d = watched['private_diagnostics']
        self.assertEqual(d['turn_changes_observed'], 1)
        self.assertEqual(d['maximum_windows_in_one_turn'], 3)
        self.assertEqual(d['phase_control_counts'], {'0:11:6': 1, '0:10:3': 1, '1:11:8': 1})
        self.assertEqual(d['last_public_progress_by_observer']['1']['turn'], 2)
        self.assertEqual(d['first_public_progress_by_observer']['0']['deck_counts'], [39, 39])
        self.assertIsNone(d['ring'][3]['phase_control'])  # MSG16 is a legal priority pass.
        for secret in ('card_id', 'card_refs', 'seed', 'private_reveals', 'old_log_prob'):
            self.assertNotIn(secret, str(d))
        self.assertFalse(d['terminal_claimed']); self.assertFalse(d['training_eligible'])

    def test_arbitrary_numeric_card_choices_are_not_recorded_as_phase_values(self):
        req = typed(1, 'main1', 0, 142, 'number', 123456789)
        class NormalFixture:
            def __init__(self): self.pending = req
            def next_decision(self): return self.pending
            def submit(self, selected): validate_selection(self.pending, selected)
        class Observed(_FirstTurnObservation, NormalFixture): pass
        watched = {'decision_windows': 0, 'actual_first_core_seat': None}
        engine = Observed(course_observations=watched); engine.next_decision()
        engine.submit(ActionSelection(req.context.run_id, req.duel_id, req.decision_id, 'choice'))
        self.assertNotIn('123456789', str(watched['private_diagnostics']))
        self.assertEqual(watched['private_diagnostics']['phase_control_counts'], {})

    def test_encoder_reports_actual_counts_without_truncating_or_revealing_ids(self):
        data = request(); data['context']['seed'] = None
        req = DecisionRequest.from_dict(data)
        normal = PlayerEncoder([1], DuelModelConfig()).encode(req)
        count = len(normal['tokens'])
        with self.assertRaises(ContractError) as caught:
            PlayerEncoder([1], DuelModelConfig(max_tokens=2)).encode(req)
        message = str(caught.exception)
        self.assertIn('tokens='+str(count)+' limit=2', message)
        self.assertIn('actions=2 limit=2048', message)
        self.assertIn('current_and_private_tokens=3', message)
        self.assertIn('public_history_tokens='+str(count-3), message)
        self.assertNotIn('own-hand', message)
        # Sufficient capacity yields exactly the same complete input.
        other = PlayerEncoder([1], DuelModelConfig(max_tokens=256)).encode(req)
        import torch
        self.assertTrue(all(torch.equal(normal[k], other[k]) for k in normal))


if __name__ == '__main__': unittest.main()
