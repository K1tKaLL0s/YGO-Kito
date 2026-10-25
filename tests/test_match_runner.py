"""CPU BO3 mechanisms and actual existing-ranker forward; no core/C#/updates."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import unittest

import torch

from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.build_model import BuildEncoder, BuildModelConfig, BuildRanker
from ygo_kito.build_pipeline import BuildAssets
from ygo_kito.duel_model import parameter_digest
from ygo_kito.match_runner import (FirstOrderPolicy, GameResult, GameSpec, MatchParticipant,
    MatchRules, MatchRunner, MatchState, ModelSideboardPolicy, keep_side, sideboard_candidates)
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    ids = [*range(1, 44), 101, 102, *range(201, 244), 301, 302, 500]
    rows = {code: dict(id=code, alias=0, ot=1, type=65 if code in (101, 102, 301, 302) else 17,
                      atk=1000+code, **{"def": 800}, level=4) for code in ids}
    a = MatchParticipant("actor", DeckParts(tuple(range(1, 41)), (101,), (41, 42, 102)))
    b = MatchParticipant("opponent", DeckParts(tuple(range(201, 241)), (301,), (241, 242, 302)))
    rules = MatchRules(rows, {}, rows)
    return (a, b), rules


def state():
    participants, rules = fixture()
    return MatchState("synthetic-bo3", participants, rules,
        {"kind": "synthetic-contract-fixture", "model_sha256": "a"*64, "resources": "fixture-not-native"}, "actor")


def result(spec, winner_id=None, *, draw=False, actual_first=0, terminal=True, anomaly=None):
    winner = 2 if draw else spec.seat_of(winner_id) if terminal else None
    return GameResult(spec.game_number, winner, actual_first, terminal, "synthetic_contract_fixture", 1.25, 10, anomaly)


def swap(deck, outgoing, incoming, zone="main"):
    data = deck.to_dict()
    data[zone][data[zone].index(outgoing)] = incoming
    data["side"][data["side"].index(incoming)] = outgoing
    return DeckParts.from_dict(data)


def policies():
    return {"actor": keep_side, "opponent": keep_side}, {
        "actor": FirstOrderPolicy("always_first"), "opponent": FirstOrderPolicy("always_first")}


class MatchRunnerTests(unittest.TestCase):
    def test_legally_changed_sideboards_feed_later_games_and_stable_loser_controls_first(self):
        match = state(); specs = []; requests = []
        winners = ("actor", "opponent", "actor")
        def game(spec):
            match.assert_game_spec(spec); specs.append(spec)
            return result(spec, winners[spec.game_number-1])
        def side(req):
            requests.append(req)
            out, into = (2, 41) if req.participant_id == "actor" else (202, 241)
            return swap(req.own_current_deck, out, into) if out in req.own_current_deck.main else req.own_current_deck
        orders = {"actor": FirstOrderPolicy("always_second"), "opponent": FirstOrderPolicy("always_first")}
        report = MatchRunner(match, game, {p: side for p in match.participant_ids}, orders).run()
        self.assertEqual(report["status"], "complete"); self.assertEqual(report["complete_matches"], 1)
        self.assertEqual(report["wins"], {"actor": 2, "opponent": 1})
        self.assertEqual([s.first_participant_id for s in specs], ["actor", "opponent", "opponent"])
        self.assertEqual(specs[1].profile()["decks"][0], list(swap(match.original_participants[1].deck, 202, 241).main))
        self.assertIn(41, specs[1].profile()["decks"][1]); self.assertNotIn(2, specs[1].profile()["decks"][1])
        self.assertEqual([g["actual_first_participant_id"] for g in report["games"]], ["actor", "opponent", "opponent"])
        for req in requests:
            self.assertEqual(set(asdict(req)), {"participant_id", "own_original_deck", "own_current_deck", "next_game_number", "public_match"})
            self.assertNotIn("decks", req.public_match); self.assertNotIn("seed", json.dumps(req.public_match))
            self.assertNotIn("native_decisions", json.dumps(req.public_match))
            self.assertNotIn("evidence_source", json.dumps(req.public_match))
            if req.participant_id == "actor":
                self.assertTrue(all(code < 200 for z in asdict(req)["own_current_deck"].values() for code in z))

    def test_two_wins_stop_after_two_actual_games(self):
        match = state(); sides, orders = policies(); calls = []
        def game(spec): calls.append(spec); return result(spec, "actor")
        report = MatchRunner(match, game, sides, orders).run()
        self.assertEqual(len(calls), 2); self.assertEqual(report["complete_games"], 2)
        self.assertEqual(report["match_winner"], "actor")
        self.assertFalse(report["formal_acceptance_qualified"])
        self.assertTrue(all(r["kind"] == "declared-keep-side-baseline" for r in report["side_policy_scope"].values()))
        self.assertTrue(all(not r["trained_sideboard_capability_verified"] for r in report["side_policy_scope"].values()))

    def test_draw_is_recorded_but_unfrozen_policy_never_becomes_a_complete_match(self):
        match = state()
        def never(req): self.fail("no siding or next-first decision after unresolved draw")
        report = MatchRunner(match, lambda spec: result(spec, draw=True),
            {p: never for p in match.participant_ids}, {p: never for p in match.participant_ids}).run()
        self.assertEqual(report["status"], "pending_draw_policy")
        self.assertEqual((report["game_attempts"], report["complete_games"], report["draw_games"]), (1, 1, 1))
        self.assertEqual(report["complete_matches"], 0); self.assertIsNone(report["match_winner"])
        with self.assertRaises(ContractError): match.issue_game_spec()

    def test_first_turn_observation_is_required_and_choice_mismatch_is_an_anomaly(self):
        for first in (None, 1):
            match = state(); sides, orders = policies()
            report = MatchRunner(match, lambda spec: result(spec, "actor", actual_first=first), sides, orders).run()
            self.assertEqual(report["complete_matches"], 0)
            self.assertEqual(report["terminal_games"], 1); self.assertEqual(report["complete_games"], 0)
            self.assertEqual(report["anomalous_game_attempts"], 1)
            self.assertEqual(report["wins"], {"actor": 0, "opponent": 0})
            self.assertEqual(report["games"][0]["actual_first_participant_id"], None if first is None else "opponent")

    def test_failure_is_retained_without_reward_match_completion_or_private_error_text(self):
        match = state(); sides, orders = policies()
        def game(spec): raise RuntimeError("opponent private card 987654321 should not reach policy context")
        report = MatchRunner(match, game, sides, orders).run()
        self.assertEqual(report["game_attempts"], 1); self.assertEqual(report["aborted_matches"], 1)
        self.assertEqual(report["complete_matches"], 0); self.assertEqual(report["complete_games"], 0)
        self.assertEqual(report["games"][0]["anomaly"], "RuntimeError")
        self.assertNotIn("987654321", json.dumps(report))

    def test_sideboards_preserve_each_zone_exact_inventory_and_normal_legality_atomically(self):
        match = state(); spec = match.issue_game_spec(); match.record_game(spec, result(spec, "actor"))
        original = {p.participant_id: p.deck for p in match.original_participants}
        invalid = [DeckParts(original["actor"].main[:-1], original["actor"].extra, original["actor"].side+(40,)),
                   replace(original["actor"], main=(500,)+original["actor"].main[1:]),
                   swap(original["actor"], 101, 41, "extra")]
        for bad in invalid:
            with self.assertRaises(ContractError): match.submit_sideboards(dict(original, actor=bad))
            self.assertEqual(match.intermission_request("actor").own_current_deck, original["actor"])
        good = swap(original["actor"], 2, 41)
        match.submit_sideboards(dict(original, actor=good))
        with self.assertRaisesRegex(ContractError, "loser"): match.choose_next_first("actor", "actor")
        match.choose_next_first("opponent", "opponent")
        self.assertEqual(match.issue_game_spec().profile()["decks"][1], list(good.main))

    def test_raw_alias_substitution_cannot_launder_a_card_outside_the_owned_multiset(self):
        participants, old_rules = fixture(); rows = deepcopy(old_rules.rows); rows[500]["alias"] = 1
        rules = MatchRules(rows, {}, rows)
        old = participants[0].deck; proposal = replace(old, main=(500,)+old.main[1:])
        with self.assertRaisesRegex(ContractError, "raw-card multiset"): rules.validate_sideboard(old, proposal)

    def test_only_current_state_issued_specs_can_run_and_active_games_cannot_be_saved(self):
        match = state(); spec = match.issue_game_spec()
        with self.assertRaises(ContractError): match.assert_game_spec(replace(spec))
        with self.assertRaises(ContractError): match.issue_game_spec()
        with self.assertRaisesRegex(ContractError, "half-games"): match.to_dict()
        other = state()
        with self.assertRaises(ContractError): other.assert_game_spec(spec)

    def test_closed_boundary_restore_replays_siding_and_has_exact_model_resource_rules_binding(self):
        match = state(); spec = match.issue_game_spec(); match.record_game(spec, result(spec, "actor"))
        before = match.to_dict()
        restored = MatchState.from_dict(deepcopy(before), rules=match.rules, expected_binding=match.binding)
        self.assertEqual(restored.to_dict(), before)
        sides, orders = policies()
        def game(spec): return result(spec, "actor")
        report = MatchRunner(restored, game, sides, orders).run()
        self.assertEqual(report["complete_matches"], 1); self.assertEqual(report["game_attempts"], 2)
        self.assertEqual(MatchState.from_dict(restored.to_dict(), rules=match.rules, expected_binding=match.binding).summary(),
                         {k:v for k,v in report.items() if k != "side_policy_scope"})
        with self.assertRaisesRegex(ContractError, "binding"):
            MatchState.from_dict(before, rules=match.rules, expected_binding=dict(match.binding, model_sha256="b"*64))
        rows = deepcopy(match.rules.rows); rows[1]["type"] = 33
        with self.assertRaisesRegex(ContractError, "binding"):
            MatchState.from_dict(before, rules=MatchRules(rows, {}, rows), expected_binding=match.binding)

    def test_restore_rejects_rehashed_illegal_side_transition_and_changed_rules_in_memory(self):
        match = state(); spec = match.issue_game_spec(); match.record_game(spec, result(spec, "actor"))
        decks = {p.participant_id:p.deck for p in match.original_participants}
        match.submit_sideboards(decks)
        saved = match.to_dict(); saved["transitions"][1]["decks"]["actor"]["main"][0] = 500
        saved["state_sha256"] = digest({k:v for k,v in saved.items() if k != "state_sha256"})
        with self.assertRaisesRegex(ContractError, "raw-card multiset"):
            MatchState.from_dict(saved, rules=match.rules, expected_binding=match.binding)
        match.rules.limits[1] = 0
        with self.assertRaisesRegex(ContractError, "rules changed"): match.to_dict()
        other = state(); other.binding["model_sha256"] = "b"*64
        with self.assertRaisesRegex(ContractError, "binding changed"): other.issue_game_spec()

    def test_candidate_search_includes_original_extra_and_bounded_multiple_swaps(self):
        match = state(); spec = match.issue_game_spec(); match.record_game(spec, result(spec, "actor"))
        req = match.intermission_request("actor")
        candidates = sideboard_candidates(req, match.rules, max_swaps=2, candidate_limit=16)
        self.assertIn(req.own_original_deck, candidates); self.assertLessEqual(len(candidates), 16)
        self.assertTrue(any(c.extra != req.own_current_deck.extra for c in candidates))
        self.assertTrue(any(len(set(req.own_current_deck.main)-set(c.main)) >= 2 for c in candidates))
        for candidate in candidates: match.rules.validate_sideboard(req.own_original_deck, candidate)
        changed = swap(req.own_current_deck, 2, 41)
        limited = sideboard_candidates(replace(req, own_current_deck=changed), match.rules, max_swaps=3, candidate_limit=2)
        self.assertEqual(limited, (changed, req.own_original_deck))

    def test_real_existing_optimizer_forward_is_differentiable_without_any_update(self):
        torch.set_num_threads(1)
        match = state(); spec = match.issue_game_spec(); match.record_game(spec, result(spec, "actor"))
        req = match.intermission_request("actor")
        payload = json.loads((ROOT / "configs/build-engineering-v1.json").read_text())
        payload.update(task_id="synthetic-side-own-task", pool=sorted(set(sum(req.own_original_deck.to_dict().values(), []))),
            sizes={"main":40,"extra":1,"side":3}, requirements=[{"zone":"main","card_id":1,"minimum":1,"maximum":3}])
        payload["goal"].update(card_id=1, starting_conditions={"player":0,"turn":1,"requires_opening_hand":[1]})
        task = BuildTask.from_dict(payload)
        assets = BuildAssets.__new__(BuildAssets)
        assets.rows = {c:dict(row, atk=1000+c, **{"def":800}, level=4) for c,row in match.rules.rows.items()}
        assets.limits = {}; assets.environment = deepcopy(task.environment)
        config = BuildModelConfig(width=8,card_width=4,heads=2,feedforward=16)
        encoder = BuildEncoder(task, assets, config)
        model = BuildRanker(config, len(encoder.card_ids), len(encoder.tags))
        before = parameter_digest(model)
        policy = ModelSideboardPolicy(model, encoder, task, assets, match.rules)
        candidates, scores = policy.score(req)
        self.assertIs(policy.model, model); self.assertTrue(scores.requires_grad); self.assertGreater(len(candidates), 1)
        scores.sum().backward()
        self.assertTrue(any(p.grad is not None and bool(p.grad.abs().sum()) for p in model.parameters()))
        self.assertEqual(parameter_digest(model), before)  # No optimizer step or model update.
        chosen = policy(req)
        self.assertIn(chosen, candidates); self.assertFalse(policy.last_receipt["trained_sideboard_capability_verified"])
        self.assertEqual(parameter_digest(model), before)
        model.zero_grad()


if __name__ == "__main__": unittest.main()
