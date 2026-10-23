"""General public-fact search discovers routes without card-ID intent tables."""
import copy
import json
from pathlib import Path
import unittest

from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.build_pipeline import BuildAssets, verify_goal
from ygo_kito.build_model import BuildEncoder, BuildModelConfig
from ygo_kito.catalog_search import CatalogQuery, expand_pool, recall, recalled_edits
from ygo_kito.native import NativeNormalEngine
from ygo_kito.route_search import discover_goal, ranked_actions, replay_discovered_goal
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"


class RealDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assets = BuildAssets(CACHE)
        cls.profile = json.loads((ROOT / "configs/extra-material-engineering-v2.json").read_text())
        cls.tasks = [BuildTask.from_dict(json.loads((ROOT / f"configs/build-{k}-discovery-v3.json").read_text())) for k in ("extra", "xyz")]
        cls.decks = [DeckParts(tuple(cls.profile["decks"][0]), (t.goal["card_id"],)) for t in cls.tasks]
        cls.proofs = [discover_goal(t, d, cls.assets, seconds=20.) for t, d in zip(cls.tasks, cls.decks)]

    def test_both_extra_goals_discovered_by_core_and_replayed_without_declared_route(self):
        for task, deck, proof in zip(self.tasks, self.decks, self.proofs):
            self.assertNotIn("route", task.goal)
            self.assertEqual(proof["status"], "verified_success", proof)
            exploration = proof["route_evidence"]["exploration"]
            self.assertFalse(exploration["prewritten_route_supplied"])
            self.assertLessEqual(exploration["branches_executed"], exploration["branch_budget"])
            self.assertTrue(replay_discovered_goal(task, deck, self.assets, proof)["replay_verified"])

    def test_unknown_budget_never_becomes_infeasibility_and_tampered_replay_rejected(self):
        unknown = discover_goal(self.tasks[0], self.decks[0], self.assets, seconds=0.)
        self.assertEqual(unknown["status"], "not_found_within_budget")
        unknown = verify_goal(self.tasks[0], self.decks[0], self.assets, attempts=0)
        self.assertEqual(unknown["status"], "not_found_within_budget")
        bad = copy.deepcopy(self.proofs[0])
        bad["responses"][0]["action_id"] = "invented"
        with self.assertRaises(ContractError):
            replay_discovered_goal(self.tasks[0], self.decks[0], self.assets, bad)
        for mutation in ("hash", "start", "versions", "view", "count", "turn_events"):
            bad = copy.deepcopy(self.proofs[0])
            if mutation == "hash": bad["trajectory_sha256"] = "0" * 64
            elif mutation == "start": bad["starting_condition"]["turn"] = 2
            elif mutation == "versions": bad["route_evidence"]["versions"]["core"] = "different"
            elif mutation == "view": bad["route_evidence"]["final_observation"]["turn"] = 2
            elif mutation == "count":
                bad["responses"] *= 101
                bad["trajectory_sha256"] = digest(bad["responses"])
            elif mutation == "turn_events": bad["core_event_kinds"] = []
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                replay_discovered_goal(self.tasks[0], self.decks[0], self.assets, bad)

    def test_goal_type_swap_never_mislabels_xyz_as_synchro_or_the_reverse(self):
        for task, deck in zip(self.tasks, self.decks):
            raw = task.to_dict()
            raw["goal"]["kind"] = "xyz_summon" if task.goal["kind"] == "synchro_summon" else "synchro_summon"
            result = discover_goal(BuildTask.from_dict(raw), deck, self.assets)
            self.assertEqual(result["status"], "unsupported_route")
            self.assertEqual(result["core_attempts"], [])

    def test_cross_axes_are_union_evidence_and_gap_recall_expands_before_core_recheck(self):
        raw = self.tasks[0].to_dict()
        raw["pool"].remove(11066358)
        raw["requirements"] = [r for r in raw["requirements"] if r["card_id"] != 11066358]
        task = BuildTask.from_dict(raw)
        main = list(self.decks[0].main)
        main = [c for c in main if c != 11066358] + [549481] * 3
        # The legal replacement itself must be in this initial catalog revision.
        raw = task.to_dict(); raw["pool"] = sorted(set(raw["pool"]) | {549481}); task = BuildTask.from_dict(raw)
        deck = DeckParts(tuple(sorted(main)), self.decks[0].extra)
        self.assets.validate(task, deck)
        initial = discover_goal(task, deck, self.assets, seconds=4., attempts=3, branch_budget=6)
        self.assertEqual(initial["status"], "not_found_within_budget")
        query = CatalogQuery(effect_terms=("特殊召唤",), theme_terms=("银河",), context_terms=("调整", "通常怪兽"),
                             preferred_level=2, preferred_type=0x1011, limit=8)
        hits = recall(task, self.assets, query)
        self.assertTrue(any(not h["axis_matches"]["effect"] for h in hits))
        hit = next(h for h in hits if h["card_id"] == 11066358)
        revised, receipt = expand_pool(task, self.assets, [hit], gap="bounded route unverified; recall normal tuner for a level-5 goal")
        self.assertEqual(task.goal, revised.goal)
        self.assertTrue(receipt["original_goal_and_hard_constraints_preserved"])
        self.assertNotEqual(task.sha256, revised.sha256)
        old_encoder = BuildEncoder(task, self.assets, BuildModelConfig())
        with self.assertRaises(ContractError):
            old_encoder.encode(revised, deck)
        candidates = recalled_edits(revised, deck, self.assets, [hit], limit=1)
        self.assertEqual(len(candidates), 1)
        proof = discover_goal(revised, candidates[0], self.assets, seconds=20., attempts=16)
        self.assertEqual(proof["status"], "verified_success", proof)
        self.assertTrue(replay_discovered_goal(revised, candidates[0], self.assets, proof)["replay_verified"])
        self.assertNotIn(11066358, task.pool)

    def test_search_ranker_is_identical_in_two_hidden_extra_worlds(self):
        outcomes = []
        for code in (26593852, 78156759):
            profile = copy.deepcopy(self.profile)
            profile["extras"][1] = [code]
            with NativeNormalEngine(CACHE, scenario="effect-duel", deck_profile=profile, seed=1) as engine:
                req = engine.next_decision()
                outcomes.append([a.action_id for a in ranked_actions(req, self.tasks[0].goal, self.assets.rows)])
                self.assertIsNone(req.context.seed)
                self.assertTrue(all(c.card_id is None for c in req.observation.cards if c.zone == "extra" and c.controller == 1))
        self.assertEqual(*outcomes)


if __name__ == "__main__":
    unittest.main()
