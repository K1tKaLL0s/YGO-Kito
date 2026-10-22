"""Real locked assets, independent Transformer updates and core-verified goals."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from ygo_kito.agent_monitor import RunMonitor
from ygo_kito.agent_registry import OpponentRegistry
from ygo_kito.build_contracts import BuildTask, DeckParts, digest
from ygo_kito.build_pipeline import BuildAssets, EXTRA_TYPES, alternate_build, apply_changes, goal_candidates, verify_goal
from ygo_kito.validation import ContractError

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".cache"
TASK = BuildTask.from_dict(json.loads((ROOT / "configs/build-engineering-v1.json").read_text()))
HAS_TORCH = importlib.util.find_spec("torch") is not None
if HAS_TORCH:
    import torch
    from ygo_kito.build_training import (load_checkpoint, run_build_training_smoke, save_checkpoint)
    from ygo_kito.duel_model import parameter_digest


@unittest.skipUnless(HAS_TORCH, "optional CPU PyTorch unavailable; building training not passed")
class RealBuildingCpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.state = Path(cls.temp.name)
        cls.result = run_build_training_smoke(CACHE, cls.state, "actual-build-proof", TASK)
        cls.folder = cls.state / "runs/actual-build-proof"
        cls.assets = BuildAssets(CACHE)
        cls.roles = ("build_goal", "build_optimizer")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def restored(self, batch=1):
        return load_checkpoint(self.folder / f"checkpoints/batch-{batch}.weights", self.assets, self.result["binding"])

    def test_both_independent_transformers_have_real_nonzero_supervised_updates(self):
        result = self.result
        self.assertTrue(result["independent_weights"])
        self.assertFalse(result["competitive_construction_quality_validated"])
        self.assertEqual(result["canonical_optimizer_calls"], 4)
        self.assertEqual(result["physical_optimizer_calls_including_recovery"], 6)
        trainer = self.restored()
        pointers = [{p.data_ptr() for p in trainer.models[r].parameters()} for r in self.roles]
        self.assertFalse(pointers[0] & pointers[1])
        other_before = parameter_digest(trainer.models["build_optimizer"])
        records = self.result["supervision"]["goals"]
        scores = trainer.models["build_goal"](trainer.encoder.batch(TASK, [DeckParts.from_dict(r["deck"]) for r in records]))
        trainer._apply("build_goal", torch.nn.functional.binary_cross_entropy_with_logits(scores, torch.tensor([r["label"] for r in records])))
        self.assertEqual(parameter_digest(trainer.models["build_optimizer"]), other_before)
        with self.assertRaisesRegex(ContractError, "completed role-update"):
            save_checkpoint(trainer, self.state / "half-updated", "bad-boundary", self.result["binding"])
        for batch in result["updates"]:
            for update in batch:
                self.assertGreater(update["changed_parameter_elements"], 0)
                self.assertGreater(update["gradient_norm_before_clip"], 0)
                self.assertGreater(update["head_delta_l2"], 0)
                self.assertNotEqual(update["before_sha256"], update["after_sha256"])

    def test_checkpoint_restores_each_optimizer_scheduler_rng_and_actual_next_update(self):
        self.assertTrue(self.result["restore_verified"])
        trainer = self.restored()
        repeat = trainer.step(self.result["supervision"])
        self.assertEqual(repeat, self.result["updates"][1])
        for role in self.roles:
            self.assertEqual(trainer.updates[role], 2)
            self.assertEqual(trainer.schedulers[role].last_epoch, 2)
            self.assertTrue(all(int(s["step"].item()) == 2 for s in trainer.optimizers[role].state.values()))
        self.assertEqual(trainer.batch_cursor, 2)
        with self.assertRaises(ContractError):
            trainer.step(self.result["supervision"])
        wrong = dict(self.result["binding"], task_sha256="0" * 64)
        with self.assertRaisesRegex(ContractError, "resources differ"):
            load_checkpoint(self.folder / "checkpoints/batch-1.weights", self.assets, wrong)
        snapshot = RunMonitor(self.state).snapshot("actual-build-proof")
        self.assertEqual(snapshot["source"], "trainer")
        self.assertEqual(snapshot["metrics"]["steps"], 4)
        self.assertTrue(RunMonitor(self.state).checkpoint("actual-build-proof", "batch-2")["integrity_verified"])
        with self.assertRaises(FileExistsError):
            save_checkpoint(trainer, self.folder / "checkpoints", "batch-2", self.result["binding"])
        with self.assertRaisesRegex(ContractError, "already exists"):
            run_build_training_smoke(CACHE, self.state, "actual-build-proof", TASK)

    def test_goal_optimizer_goal_optimizer_preserves_actual_goals_and_verifiable_changes(self):
        stages = self.result["alternation"]["stages"]
        self.assertEqual([s["role"] for s in stages], ["build_goal", "build_optimizer"] * 2)
        previous = DeckParts(())
        for stage in stages:
            deck = DeckParts.from_dict(stage["deck"])
            self.assets.validate(TASK, deck)
            self.assertEqual(stage["task_sha256"], TASK.sha256)
            self.assertEqual(stage["validation"]["task_sha256"], TASK.sha256)
            self.assertEqual(stage["validation"]["deck_sha256"], digest(deck.to_dict()))
            self.assertEqual(stage["validation"]["status"], "verified_success")
            self.assertIn(61, stage["validation"]["core_event_kinds"])
            self.assertEqual(apply_changes(previous, stage["changes"]), deck)
            if stage["role"] == "build_optimizer":
                self.assertTrue(stage["changes"])
            previous = deck
        self.assets.validate(TASK, DeckParts.from_dict(self.result["alternation"]["best_deck"]))

    def test_explicit_starting_conditions_and_proxy_labels_are_not_construction_strength(self):
        data = self.result["supervision"]
        self.assertFalse(data["competitive_quality_labels"])
        self.assertFalse(data["unknown_routes_used_as_negative"])
        for record in data["goals"]:
            if record["label"] == 1:
                proof = record["evidence"]
                self.assertEqual(proof["starting_condition"], TASK.goal["starting_conditions"])
                self.assertTrue(any(x["declared_opening_condition_met"] for x in proof["core_attempts"]))
                self.assertTrue(proof["random_dependency"])
            else:
                self.assertEqual(record["evidence"]["status"], "hard_constraint_failure")
        for pair in data["pairs"]:
            self.assertIn("proxy_only", pair["source"])
            self.assertGreater(pair["better_value"], pair["worse_value"])

    def test_false_negative_wrong_proxy_or_stale_supervision_rejected_before_weights_change(self):
        trainer = self.restored()
        hashes = {r: parameter_digest(trainer.models[r]) for r in self.roles}
        for mutation in ("unknown-negative", "wrong-proxy", "goal-identity", "fingerprint"):
            data = copy.deepcopy(self.result["supervision"])
            if mutation == "unknown-negative":
                data["goals"][1]["evidence"]["status"] = "not_found_within_budget"
            elif mutation == "wrong-proxy":
                data["pairs"][0]["source"] = "competitive-win-rate"
            elif mutation == "goal-identity":
                data["task_sha256"] = "0" * 64
            else:
                data["supervision_sha256"] = "0" * 64
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                trainer.step(data)
            self.assertEqual({r: parameter_digest(trainer.models[r]) for r in self.roles}, hashes)

    def test_actual_card_lists_extra_boundary_and_budget_unknown_are_separate(self):
        base = DeckParts.from_dict(self.result["alternation"]["best_deck"])
        deleted = list(base.main)
        deleted.remove(TASK.goal["card_id"])
        spare = next(c for c in TASK.pool if c != TASK.goal["card_id"] and
                     deleted.count(c) + base.side.count(c) < self.assets.limits.get(c, 3))
        deleted.append(spare)
        with self.assertRaisesRegex(ContractError, "fixed goal/card"):
            self.assets.validate(TASK, DeckParts(tuple(sorted(deleted)), base.extra, base.side))
        bad = DeckParts(base.main, (), (TASK.goal["card_id"],))
        with self.assertRaises(ContractError):
            self.assets.validate(TASK, bad)
        extra = next(c for c, r in self.assets.rows.items() if r["ot"] & 1 and r["type"] & EXTRA_TYPES
                     and not r["type"] & 0x4000 and self.assets.limits.get(r["alias"] or c, 3) >= 1)
        payload = TASK.to_dict()
        payload["pool"] = sorted([*payload["pool"], extra])
        payload["sizes"]["extra"] = 1
        expanded = BuildTask.from_dict(payload)
        deck = DeckParts(base.main, (extra,), base.side)
        self.assets.validate(expanded, deck)
        self.assertEqual(verify_goal(expanded, deck, self.assets)["status"], "unsupported_route")
        unknown = verify_goal(TASK, base, self.assets, attempts=0)
        self.assertEqual(unknown["status"], "not_found_within_budget")
        trainer = self.restored()
        budget = alternate_build(TASK, self.assets, trainer.models, trainer.encoder, seconds=0)
        self.assertIsNone(budget["best_deck"])
        self.assertEqual(budget["status"], "not_found_within_budget")

    def test_encoder_uses_explicit_context_and_cards_without_ids_or_audit_labels(self):
        trainer = self.restored()
        deck = DeckParts.from_dict(self.result["alternation"]["best_deck"])
        payload = TASK.to_dict()
        payload["task_id"] = "renamed-opaque-task"
        other = BuildTask.from_dict(payload)
        batches = [trainer.encoder.batch(t, [deck]) for t in (TASK, other)]
        self.assertTrue(all(torch.equal(batches[0][k], batches[1][k]) for k in batches[0]))
        payload["annotations"][0]["layer"] = "model_inference"
        with self.assertRaisesRegex(ContractError, "unseen"):
            trainer.encoder.batch(BuildTask.from_dict(payload), [deck])
        with self.assertRaises(ContractError):
            trainer.encoder.encode({"raw_audit": []}, deck)

    def test_from_zero_and_existing_deck_candidates_are_bounded_and_keep_fixed_cards(self):
        base = DeckParts.from_dict(self.result["alternation"]["best_deck"])
        candidates = goal_candidates(TASK, self.assets, base)
        self.assertIn(base, candidates)
        self.assertLessEqual(len(candidates), TASK.candidate_budget)
        for candidate in candidates:
            self.assets.validate(TASK, candidate)
            self.assertEqual(candidate.main.count(TASK.goal["card_id"]), 3)
            self.assertEqual(len(candidate.side), 1)

    def test_three_section_output_imports_into_existing_opponent_registry(self):
        registry = OpponentRegistry(self.state / "output-import", CACHE)
        env = registry.environment(self.assets.environment)
        record = registry.import_deck({"deck_id": "generated-engineering-deck", "environment_id": env["environment_id"],
                                       "source": "engineering_fixture", "format": "json",
                                       "content": self.result["alternation"]["best_deck"]})
        self.assertEqual(record["cards"], self.result["alternation"]["best_deck"])
        self.assertEqual(record["source"], "engineering_fixture")
        self.assertTrue(record["runtime_compatible"])
        self.assertFalse(record["user_acceptance_verified"])
