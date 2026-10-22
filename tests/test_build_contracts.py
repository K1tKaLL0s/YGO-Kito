"""Synthetic building/listing contracts; no rule-core or construction ability claim."""

import copy
import json
from pathlib import Path
import unittest

from ygo_kito.build_contracts import BuildTask, DeckParts
from ygo_kito.build_pipeline import apply_changes, deck_changes
from ygo_kito.deck_profile import validate_deck_parts
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]
TASK = json.loads((ROOT / "configs/build-engineering-v1.json").read_text())


class BuildContractTests(unittest.TestCase):
    def test_task_round_trip_retains_goal_constraints_context_and_sources(self):
        task = BuildTask.from_dict(copy.deepcopy(TASK))
        self.assertEqual(BuildTask.from_dict(task.to_dict()), task)
        self.assertEqual(task.source, "engineering_fixture")
        self.assertEqual(task.annotations[-1]["layer"], "engineering_proxy")
        payload = copy.deepcopy(TASK)
        detached = BuildTask.from_dict(payload)
        before = detached.sha256
        payload["goal"]["card_id"] = 123
        payload["requirements"][0]["minimum"] = 0
        self.assertEqual(detached.sha256, before)

    def test_unknown_hidden_seed_and_unsupported_goal_or_historical_scope_fail_closed(self):
        for mutation in ("raw", "seed", "goal", "history", "minimum", "sizes", "tag"):
            payload = copy.deepcopy(TASK)
            if mutation == "raw":
                payload["opponent_private_hand"] = [123]
            elif mutation == "seed":
                payload["goal"]["starting_conditions"]["seed"] = 7
            elif mutation == "goal":
                payload["goal"]["kind"] = "arbitrary-combo-not-implemented"
            elif mutation == "history":
                payload["environment"]["authority"] = "official"
                payload["environment"]["release_cutoff"] = "2022-09-30"
            elif mutation == "minimum":
                payload["requirements"][0]["minimum"] = 0
            elif mutation == "sizes":
                payload["sizes"]["main"] = 39
            else:
                payload["annotations"][0]["tag"] = "theme-without-connector"
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                BuildTask.from_dict(payload)

    def test_three_sections_round_trip_and_unknown_or_boolean_card_ids_rejected(self):
        deck = DeckParts(tuple(range(1, 41)), (101,), (42,))
        self.assertEqual(DeckParts.from_dict(deck.to_dict()), deck)
        for payload in ({"main": [], "extra": []}, {"main": [True], "extra": [], "side": []},
                        {"main": [1], "extra": [], "side": [], "hidden_order": []}):
            with self.assertRaises(ContractError):
                DeckParts.from_dict(payload)

    def rows(self):
        rows = {code: {"id": code, "alias": 0, "ot": 1, "type": 17} for code in range(1, 61)}
        rows[101] = {"id": 101, "alias": 0, "ot": 1, "type": 0x41}
        rows[102] = {"id": 102, "alias": 0, "ot": 1, "type": 0x4011}
        rows[103] = {"id": 103, "alias": 1, "ot": 1, "type": 17}
        return rows

    def test_shared_listing_checks_all_sections_aliases_types_tokens_and_pool(self):
        rows = self.rows()
        good = DeckParts(tuple(range(1, 41)), (101,), (42,)).to_dict()
        validate_deck_parts(good, rows, {})
        for mutation in ("extra-type", "main-type", "combined-alias", "token", "pool", "side-size"):
            bad = copy.deepcopy(good)
            allowed = None
            if mutation == "extra-type":
                bad["extra"] = [1]
            elif mutation == "main-type":
                bad["main"][0] = 101
            elif mutation == "combined-alias":
                bad["side"] = [103, 103, 103]
            elif mutation == "token":
                bad["side"] = [102]
            elif mutation == "pool":
                allowed = set(range(1, 41))
            else:
                bad["side"] = [42] * 16
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                validate_deck_parts(bad, rows, {}, allowed=allowed)

    def test_deck_changes_are_replayable_and_reject_stale_or_duplicate_changes(self):
        before = DeckParts(tuple(range(1, 41)), (101,), (42,))
        after = DeckParts(tuple(range(2, 42)), (101,), (43,))
        changes = deck_changes(before, after)
        self.assertEqual(apply_changes(before, changes), after)
        for bad in (changes + [changes[0]], [dict(changes[0], before=3)], [dict(changes[0], zone="deck-order")]):
            with self.assertRaises(ContractError):
                apply_changes(before, bad)

    def test_section_and_candidate_limits_cannot_silently_expand_work(self):
        for mutation in ("candidates", "extra", "seed-condition", "too-many-fixed"):
            payload = copy.deepcopy(TASK)
            if mutation == "candidates":
                payload["candidate_budget"] = 33
            elif mutation == "extra":
                payload["sizes"]["extra"] = 16
            elif mutation == "seed-condition":
                payload["goal"]["starting_conditions"]["requires_opening_hand"] = []
            else:
                payload["requirements"][1]["minimum"] = payload["requirements"][1]["maximum"] = 2
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                BuildTask.from_dict(payload)
