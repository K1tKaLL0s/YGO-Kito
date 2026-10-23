"""Pinned native scripts/core, actual opening hands, no seeded field or mock rules."""
import copy
import json
from pathlib import Path
import unittest

import torch

from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.build_pipeline import BuildAssets, verify_goal
from ygo_kito.contracts import ActionSelection, DecisionRequest, Observation
from ygo_kito.duel_model import DuelActorCritic, DuelModelConfig, PlayerEncoder
from ygo_kito.extra_routes import RouteDriver, completed_special_summon, profile_for, verify_extra_goal
from ygo_kito.group_runner import actor_profile
from ygo_kito.native import NativeError, NativeNormalEngine
from ygo_kito.normal_duel import request_digest
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"
PROFILE = json.loads((ROOT / "configs/extra-material-engineering-v2.json").read_text())


def task_for(kind="synchro"):
    return BuildTask.from_dict(json.loads((ROOT / f"configs/build-{'extra' if kind == 'synchro' else 'xyz'}-engineering-v2.json").read_text()))


class RealExtraMaterialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.assets = BuildAssets(CACHE)
        cls.task = task_for()
        cls.deck = DeckParts(tuple(PROFILE["decks"][0]), (26593852,))
        cls.proofs = [verify_extra_goal(cls.task, cls.deck, cls.assets, material_preference=p) for p in ("first", "last")]
        cls.xyz_task = task_for("xyz")
        cls.xyz_deck = DeckParts(cls.deck.main, (78156759,))
        cls.xyz = verify_goal(cls.xyz_task, cls.xyz_deck, cls.assets)

    def test_two_real_sum_choices_consume_different_materials_and_replay_exactly(self):
        chosen = []
        for proof in self.proofs:
            self.assertEqual(proof["status"], "verified_success", proof)
            self.assertIn(23, proof["core_event_kinds"])
            self.assertNotIn(1, proof["core_event_kinds"])
            evidence = proof["route_evidence"]
            self.assertTrue(evidence["conditional_only"])
            self.assertEqual(len(evidence["sum_choices"]), 1)
            selection = evidence["sum_choices"][0]
            self.assertEqual(len(selection["request"]["actions"]), 2)
            chosen.append(set(selection["chosen_card_ids"]))
            final = evidence["final_observation"]["cards"]
            self.assertTrue(any(c["zone"] == "monster" and c["card_id"] == self.task.goal["card_id"] for c in final))
            self.assertTrue(chosen[-1] <= {c["card_id"] for c in final if c["zone"] == "graveyard"})
            # Native success must occur after THIS goal's summon-start event.
            events = evidence["core_event_audit_not_policy_input"]
            self.assertTrue(completed_special_summon(events, Observation.from_dict(evidence["final_observation"]), 0, 26593852))
        self.assertNotEqual(chosen[0], chosen[1])
        again = verify_goal(self.task, self.deck, self.assets)
        self.assertEqual(again["trajectory_sha256"], self.proofs[0]["trajectory_sha256"])
        self.assertEqual(again["route_evidence"]["core_event_audit_not_policy_input"], self.proofs[0]["route_evidence"]["core_event_audit_not_policy_input"])

    def test_real_xyz_material_hosts_and_actual_owners_match_both_views(self):
        proof = self.xyz
        self.assertEqual(proof["status"], "verified_success", proof)
        seed = proof["core_attempts"][-1]["seed_audit_only"]
        with NativeNormalEngine(CACHE, scenario="effect-duel", deck_profile=profile_for(self.xyz_deck), seed=seed) as engine:
            req = engine.next_decision()
            for row in proof["responses"]:
                self.assertEqual(request_digest(req), row["request_sha256"])
                engine.submit(ActionSelection(req.context.run_id, req.duel_id, req.decision_id, row["action_id"]))
                req = engine.next_decision()
            projected = []
            for observer in (0, 1):
                obs = engine._observation(observer)
                materials = [c for c in obs.cards if c.zone == "overlay"]
                self.assertEqual({c.card_id for c in materials}, {1761063, 32269855})
                self.assertTrue(all(c.owner == 0 and c.controller == 0 and c.visibility == "public" for c in materials))
                host = next(c for c in obs.cards if c.card_id == 78156759)
                self.assertEqual(host.material_count, 2)
                self.assertTrue(all(c.attached_to == host.ref for c in materials))
                projected.append(materials)
            self.assertEqual(projected[0], projected[1])

    def test_hidden_opponent_extra_worlds_have_identical_requests_and_model_features(self):
        requests = []
        for code in (26593852, 78156759):
            profile = copy.deepcopy(PROFILE)
            profile["extras"][1] = [code]
            with NativeNormalEngine(CACHE, scenario="effect-duel", deck_profile=profile, seed=1) as engine:
                req = engine.next_decision()
                requests.append(req)
                own = [c for c in req.observation.cards if c.zone == "extra" and c.controller == 0]
                other = [c for c in req.observation.cards if c.zone == "extra" and c.controller == 1]
                self.assertTrue(all(c.card_id is not None and c.visibility == "observer" for c in own))
                self.assertTrue(all(c.card_id is None and c.owner is None and c.visibility == "hidden" for c in other))
                self.assertIsNone(req.context.seed)
        self.assertEqual(request_digest(requests[0]), request_digest(requests[1]))
        encoder = PlayerEncoder(sorted(set(self.deck.main + (26593852, 78156759))), DuelModelConfig())
        first, second = [encoder.encode(r) for r in requests]
        self.assertTrue(all(torch.equal(first[k], second[k]) for k in first))

    def test_v1_side_is_bound_validated_and_never_dealt_or_enabled_as_extra(self):
        profile = json.loads((ROOT / "configs/effect-duel-v1.json").read_text())
        baseline = copy.deepcopy(profile)
        with NativeNormalEngine(CACHE, scenario="effect-duel", deck_profile=profile, seed=7) as engine:
            expected = request_digest(engine.next_decision())
        bound = actor_profile(profile, DeckParts(tuple(profile["decks"][0]), (), (26593852,)))
        self.assertNotEqual(digest(profile), digest(bound))
        with NativeNormalEngine(CACHE, scenario="effect-duel", deck_profile=bound, seed=7) as engine:
            req = engine.next_decision()
            self.assertEqual(engine.player_sides, ((26593852,), ()))
            self.assertEqual(engine.player_extras, ((), ()))
            self.assertFalse(engine.extended_actions)
            self.assertEqual(req.context.versions.card_pool, "native-effect-duel-v1")
            self.assertEqual(request_digest(req), expected)
            self.assertNotIn(26593852, engine.player_decks[0])
            self.assertFalse(any(c.card_id == 26593852 for c in req.observation.cards))
        self.assertEqual(profile, baseline)
        token = next(c for c, row in self.assets.rows.items() if row["type"] & 0x4000 and row["ot"] & 1)
        for side in ([26202165], [32864] * 16, [token]):
            bad = dict(profile, sides=[side, []])
            with self.assertRaises(ContractError):
                with NativeNormalEngine(CACHE, scenario="effect-duel", deck_profile=bad, seed=7):
                    pass

    def test_real_sum_metadata_reaches_network_and_preserves_distinct_action_pointers(self):
        req = DecisionRequest.from_dict(json.loads(json.dumps(self.proofs[0]["route_evidence"]["sum_choices"][0]["request"])))
        encoder = PlayerEncoder(sorted(set(self.deck.main + self.deck.extra)), DuelModelConfig())
        batch = encoder.batch([req], pad_actions_to=4)
        self.assertFalse(torch.equal(batch["pointers"][0, 0], batch["pointers"][0, 1]))
        model = DuelActorCritic(encoder.config, len(encoder.card_ids)).eval()
        with torch.no_grad():
            probs = model(batch)[0].softmax(-1)
        self.assertTrue(torch.equal(probs[0, 2:], torch.zeros(2)))
        changed = copy.deepcopy(req.to_dict())
        changed["sum_selection"]["target"] = 6
        altered = DecisionRequest.from_dict(json.loads(json.dumps(changed)))
        self.assertFalse(torch.equal(encoder.encode(req)["numbers"], encoder.encode(altered)["numbers"]))

    def test_illegal_id_preserves_sum_window_and_core_rejects_corrupted_sum_response(self):
        with NativeNormalEngine(CACHE, scenario="effect-duel", deck_profile=PROFILE, seed=1) as engine:
            driver = RouteDriver(self.task.goal["route"])
            req = engine.next_decision()
            for _ in range(100):
                if req.prompt.message == 23:
                    break
                action = driver.choose(req)
                engine.submit(ActionSelection(req.context.run_id, req.duel_id, req.decision_id, action.action_id))
                req = engine.next_decision()
            self.assertEqual(req.prompt.message, 23)
            with self.assertRaises(ContractError):
                engine.submit(ActionSelection(req.context.run_id, req.duel_id, req.decision_id, "invented"))
            self.assertIs(engine.pending, req)
            action = req.actions[0]
            # Integration negative test intentionally bypasses the adapter mapping.
            engine._responses[action.action_id] = b"\x00"
            engine.submit(ActionSelection(req.context.run_id, req.duel_id, req.decision_id, action.action_id))
            with self.assertRaisesRegex(NativeError, "MSG_RETRY"):
                engine.next_decision()

    def test_banish_scripts_show_faceup_public_and_facedown_only_to_own_player(self):
        for spell, count in ((75500286, 1), (35261759, 3)):
            profile = copy.deepcopy(PROFILE)
            profile["decks"][0] = sorted(profile["decks"][0][:-count] + [spell] * count)
            with NativeNormalEngine(CACHE, scenario="effect-duel", deck_profile=profile, seed=24) as engine:
                req = engine.next_decision()
                self.assertTrue(any(c.card_id == spell and c.zone == "hand" for c in req.observation.cards))
                for _ in range(50):
                    cards = {c.ref: c.card_id for c in req.observation.cards}
                    action = next((a for a in req.actions if a.kind == "activate" and any(cards[r] == spell for r in a.card_refs)), None)
                    if action is None and req.search_choices:
                        action = next(a for a in req.actions if a.kind == "select")
                    action = action or next((a for a in req.actions if a.kind == "pass"), req.actions[0])
                    engine.submit(ActionSelection(req.context.run_id, req.duel_id, req.decision_id, action.action_id))
                    req = engine.next_decision()
                    own = [c for c in engine._observation(0).cards if c.zone == "banished"]
                    if own:
                        break
                other = [c for c in engine._observation(1).cards if c.zone == "banished"]
                self.assertEqual(len(own), 1 if spell == 75500286 else 10)
                self.assertTrue(all(c.card_id is not None and c.owner == 0 for c in own))
                if spell == 75500286:
                    self.assertEqual(own, other)
                    self.assertTrue(all(c.visibility == "public" for c in other))
                else:
                    self.assertTrue(all(c.visibility == "hidden" and c.card_id is None and c.owner is None for c in other))
                    self.assertTrue(all("public_card" not in e for e in engine.events if e["kind"] == 50 and e.get("to_zone") == 32))

    def test_unsearched_route_budget_is_unknown_and_binding_mismatch_fails(self):
        result = verify_goal(self.task, self.deck, self.assets, attempts=0)
        self.assertEqual(result["status"], "not_found_within_budget")
        bad = self.task.to_dict()
        bad["environment"]["versions"]["card_pool"] = "native-effect-duel-v1"
        with self.assertRaises(ContractError):
            verify_goal(BuildTask.from_dict(bad), self.deck, self.assets)
