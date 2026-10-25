"""Checkpoint/resume contract of the duel trainer, exercised without the core.

The training chain's recovery claim is that a saved complete-episode boundary can
be resumed and continue *identically*.  That claim rests on three things the rule
core does not participate in: the model/optimizer/scheduler state, the declared
update counters, and the sampler RNG streams.  All three are serialised by
``save_checkpoint``/``load_checkpoint``, so they can be checked here with a fresh
trainer and no duel.

What this module deliberately does not do: it never fabricates a training episode.
``CpuTrainer.update`` rejects anything that is not the actual fresh live-core
sample, so PPO arithmetic, GAE and on-policy sampling remain unverified until a
prepared engine is present.  See the delivery notes for that boundary.
"""

from pathlib import Path
import random
import tempfile
import unittest

try:
    import torch
except ModuleNotFoundError as error:
    if error.name != "torch":
        raise
    torch = None

if torch is not None:
    from ygo_kito.cpu_training import (
        CpuTrainer, CpuTrainingConfig, load_checkpoint, save_checkpoint,
    )
    from ygo_kito.duel_model import parameter_digest
    from ygo_kito.validation import ContractError

CARD_IDS = [1, 2, 3, 4, 5, 6, 7, 8]
BINDING = {"fixture": "checkpoint-contract-not-a-real-resource-binding"}


def make_trainer(game_seeds=(11, 12, 13)):
    return CpuTrainer(CpuTrainingConfig(game_seeds=game_seeds), CARD_IDS)


@unittest.skipIf(torch is None, "optional CPU PyTorch unavailable; checkpoint tests not passed")
class CheckpointContractTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.directory = Path(self.folder.name) / "checkpoints"

    def save(self, trainer, checkpoint_id="initial-state", binding=BINDING):
        return save_checkpoint(trainer, self.directory, checkpoint_id, binding, allow_initial=True)

    def test_initial_boundary_round_trips_weights_optimizer_and_counters(self):
        trainer = make_trainer()
        path = self.save(trainer)
        digest = parameter_digest(trainer.model)
        restored = load_checkpoint(path, BINDING, allow_initial=True)
        self.assertEqual(parameter_digest(restored.model), digest)
        self.assertEqual(restored.updates, 0)
        self.assertEqual(restored.episode_cursor, 0)
        self.assertEqual(restored.optimizer.param_groups[0]["lr"],
                         trainer.optimizer.param_groups[0]["lr"])
        self.assertEqual(len(restored.optimizer.state_dict()["state"]),
                         len(trainer.optimizer.state_dict()["state"]))
        self.assertEqual(restored.scheduler.state_dict(), trainer.scheduler.state_dict())
        self.assertEqual(restored.encoder.vocab_sha256, trainer.encoder.vocab_sha256)
        self.assertEqual(tuple(restored.config.game_seeds), (11, 12, 13))

    def test_the_sampler_streams_resume_exactly_where_the_checkpoint_stopped(self):
        # The resume claim, isolated to the streams: whatever the saved trainer
        # would draw next, the restored trainer must draw first.  CpuTrainer's
        # constructor reseeds the global generators, so the python stream is
        # seeded explicitly after construction and before the checkpoint.
        trainer = make_trainer()
        random.seed(99)
        path = self.save(trainer)
        expected = {
            "torch": torch.rand(4).tolist(),
            "policy": torch.multinomial(torch.ones(8), 4, generator=trainer.policy_rng).tolist(),
            "batch": torch.randperm(8, generator=trainer.batch_rng).tolist(),
            "python": [random.random() for _ in range(3)],
        }

        restored = load_checkpoint(path, BINDING, allow_initial=True)
        self.assertEqual(torch.rand(4).tolist(), expected["torch"])
        self.assertEqual(torch.multinomial(torch.ones(8), 4, generator=restored.policy_rng).tolist(),
                         expected["policy"])
        self.assertEqual(torch.randperm(8, generator=restored.batch_rng).tolist(), expected["batch"])
        self.assertEqual([random.random() for _ in range(3)], expected["python"])

    def test_a_different_resource_binding_is_refused(self):
        path = self.save(make_trainer())
        with self.assertRaisesRegex(ContractError, "resources differ"):
            load_checkpoint(path, {"fixture": "different"}, allow_initial=True)

    def test_an_initial_checkpoint_needs_explicit_permission_to_load(self):
        path = self.save(make_trainer())
        with self.assertRaisesRegex(ContractError, "schema/boundary"):
            load_checkpoint(path, BINDING)

    def test_an_initial_checkpoint_cannot_be_written_without_permission(self):
        with self.assertRaisesRegex(ContractError, "complete-episode boundary"):
            save_checkpoint(make_trainer(), self.directory, "initial-state", BINDING)

    def test_an_existing_checkpoint_file_is_never_overwritten(self):
        trainer = make_trainer()
        self.save(trainer)
        with self.assertRaises(OSError):
            self.save(trainer)

    def test_a_tampered_model_payload_is_refused_by_the_checksum(self):
        path = self.save(make_trainer())
        state = torch.load(path, map_location="cpu", weights_only=True)
        first = next(iter(state["model"].values()))
        first.view(-1)[0] += 0.5
        with path.open("wb") as handle:
            torch.save(state, handle)
        with self.assertRaisesRegex(ContractError, "checksum differs"):
            load_checkpoint(path, BINDING, allow_initial=True)

    def test_a_tampered_counter_pair_is_refused(self):
        # Both counters stay in range, so only the pairing rule can catch this.
        path = self.save(make_trainer())
        state = torch.load(path, map_location="cpu", weights_only=True)
        state["boundary"] = "complete-episode"
        state["updates"], state["episode_cursor"] = 2, 1
        with path.open("wb") as handle:
            torch.save(state, handle)
        with self.assertRaisesRegex(ContractError, "cursor/update boundary differs"):
            load_checkpoint(path, BINDING, allow_initial=True)

    def test_unknown_keys_are_refused_rather_than_ignored(self):
        path = self.save(make_trainer())
        state = torch.load(path, map_location="cpu", weights_only=True)
        state["injected"] = 1
        with path.open("wb") as handle:
            torch.save(state, handle)
        with self.assertRaises(ContractError):
            load_checkpoint(path, BINDING, allow_initial=True)


@unittest.skipIf(torch is None, "optional CPU PyTorch unavailable; checkpoint tests not passed")
class OnPolicyAdmissionTests(unittest.TestCase):
    """The gates that keep non-fresh data out of PPO, checked without sampling."""

    def setUp(self):
        torch.set_num_threads(1)
        self.trainer = make_trainer()

    def test_an_episode_from_another_purpose_is_rejected(self):
        with self.assertRaisesRegex(ContractError, "stale/off-policy|non-live-core"):
            self.trainer.update({"purpose": "validation", "source": "live-core-actor-seat",
                                 "policy_version": 0, "policy_sha256": parameter_digest(self.trainer.model),
                                 "steps": []})

    def test_an_episode_without_a_live_core_source_is_rejected(self):
        with self.assertRaisesRegex(ContractError, "stale/off-policy|non-live-core"):
            self.trainer.update({"purpose": "train", "source": "synthetic",
                                 "policy_version": 0, "policy_sha256": parameter_digest(self.trainer.model),
                                 "steps": []})

    def test_an_episode_from_an_older_policy_version_is_rejected(self):
        with self.assertRaisesRegex(ContractError, "stale/off-policy|non-live-core"):
            self.trainer.update({"purpose": "train", "source": "live-core-actor-seat",
                                 "policy_version": 7, "policy_sha256": parameter_digest(self.trainer.model),
                                 "steps": []})

    def test_a_replayed_episode_is_rejected_by_the_digest_gate(self):
        # Even a well-formed episode must be the one this trainer just sampled;
        # a held-out or relabelled episode must not become a training sample.
        with self.assertRaises(ContractError):
            self.trainer.update({"purpose": "train", "source": "live-core-actor-seat",
                                 "policy_version": 0, "policy_sha256": parameter_digest(self.trainer.model),
                                 "steps": [{"request": None, "action_index": 0, "old_log_prob": 0.,
                                            "old_value": 0., "reward": 0.}]})

    def test_the_declared_episode_budget_is_enforced(self):
        trainer = make_trainer(game_seeds=(1,))
        trainer.episode_cursor = 1
        with self.assertRaisesRegex(ContractError, "budget exhausted"):
            trainer.sample_episode(Path("."), {})


if __name__ == "__main__":
    unittest.main()
