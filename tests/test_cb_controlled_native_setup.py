"""Exact CB initial-state fixtures; no core, native library or model execution."""
from collections import Counter
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from ygo_kito.native import NativeNormalEngine, _validate_cb_opening_hand
from ygo_kito.validation import ContractError


class FakeSetupLibrary:
    def __init__(self):
        self.start_counts = {}
        self.decks = [[], []]
        self.extras = [[], []]
        self.hands = [[], []]

    def set_player_info(self, handle, player, lp, start_count, draw_count):
        self.start_counts[player] = start_count

    def new_card(self, handle, code, owner, player, location, sequence, position):
        target = self.decks if location == 1 else self.extras
        target[player].append(code)

    def start_duel(self, handle, options):
        # Mirror only the pinned core's initial draw direction, not game rules.
        for player in (0, 1):
            for _ in range(self.start_counts[player]):
                self.hands[player].append(self.decks[player].pop())


class ControlledCbNativeSetupTests(unittest.TestCase):
    def test_exact_opening_validation_preserves_duplicates_and_rejects_invalid_inputs(self):
        main = (1, 1, *range(2, 40))
        self.assertEqual(_validate_cb_opening_hand('conditional-cb', (1, 1), main), (1, 1))
        profile = {'schema_version': 2, 'name': 'fixture-only',
                   'decks': [list(main), list(range(100, 140))],
                   'extras': [[901], []], 'sides': [[801], []]}
        cases = [('conditional-cb', opening) for opening in (
            None, (), [1], (1,) * 6, (1, 1, 1), (901,), (801,), (999,),
            (0,), (-1,), (2**32,), (True,), ('1',))]
        cases.extend((scenario, (1,)) for scenario in ('normal', 'effect-duel'))
        with patch('ygo_kito.native.verify_resources', side_effect=AssertionError('must reject before native setup')):
            for scenario, opening in cases:
                with self.subTest(scenario=scenario, opening=opening), self.assertRaises(ContractError):
                    NativeNormalEngine(Path('.'), scenario=scenario,
                                       deck_profile=profile if scenario != 'normal' else None,
                                       cb_opening_hand=opening)

    def test_exact_draw_inventory_and_default_five_card_setup(self):
        mains = ((1, 1, *range(2, 40)), tuple(range(100, 140)))
        extras, sides = ((901, 902), (903,)), ((801,), (802,))
        seed = 7
        for opening in ((1, 1, 3), None):
            with self.subTest(opening=opening):
                engine = object.__new__(NativeNormalEngine)
                engine.lib, engine.handle = FakeSetupLibrary(), object()
                engine.cb_opening_hand = opening
                engine.player_decks, engine.player_extras, engine.player_sides = mains, extras, sides
                engine._setup_initial_cards(seed)

                expected = []
                for player in (0, 1):
                    order = list(mains[player])
                    random.Random(seed * 2 + player).shuffle(order)
                    if player == 0 and opening is not None:
                        for code in opening:
                            order.remove(code)
                        order.extend(opening)
                    expected.append(order)
                self.assertEqual(engine.lib.decks, expected)
                self.assertEqual(engine.lib.extras, [list(cards) for cards in extras])
                self.assertEqual(engine.player_decks, mains)
                self.assertEqual(engine.player_sides, sides)
                self.assertEqual(engine.lib.start_counts, {0: len(opening) if opening is not None else 5, 1: 5})

                engine.lib.start_duel(engine.handle, 5 << 16)
                for player in (0, 1):
                    self.assertEqual(Counter(engine.lib.decks[player]) + Counter(engine.lib.hands[player]),
                                     Counter(mains[player]))
                    self.assertEqual(engine.lib.hands[player], list(reversed(expected[player][-engine.lib.start_counts[player]:])))
                if opening is not None:
                    self.assertEqual(Counter(engine.lib.hands[0]), Counter(opening))
                    self.assertEqual(len(engine.lib.decks[0]), len(mains[0]) - len(opening))
                else:
                    self.assertEqual([len(hand) for hand in engine.lib.hands], [5, 5])


if __name__ == '__main__':
    unittest.main()
