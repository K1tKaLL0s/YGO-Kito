"""Projection unit tests only; real core cases live in integration_tests."""

import unittest

from ygo_kito.native import public_event_projection


class PublicHistoryTests(unittest.TestCase):
    def test_private_prompts_counts_indices_and_extra_payloads_cannot_enter_public_history(self):
        private = [{"kind": 11, "player": 1, "choices": 99, "hidden_card": 77414722},
                   {"kind": 15, "global_index": 800, "choices": 3}]
        public = [{"kind": 40, "player": 0}, {"kind": 50, "from_zone": 2, "to_zone": 8}]
        self.assertEqual(public_event_projection(private + public), public_event_projection(public))
        self.assertNotIn("77414722", str(public_event_projection(private + public)))

    def test_only_explicitly_public_identity_is_projected(self):
        events = [{"kind": 50, "hidden_card": 123}, {"kind": 70, "public_card": 43898403, "choices": 50}]
        self.assertEqual(public_event_projection(events), [
            {"event": "move", "card_ids": []}, {"event": "activate", "card_ids": [43898403]}])
