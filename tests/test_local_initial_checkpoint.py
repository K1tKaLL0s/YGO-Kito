from pathlib import Path
import tempfile
import unittest

from ygo_kito.cpu_training import CpuTrainer, CpuTrainingConfig, load_checkpoint, save_checkpoint
from ygo_kito.duel_model import parameter_digest
from ygo_kito.validation import ContractError


class InitialLocalCheckpointTests(unittest.TestCase):
    def test_real_initial_weights_require_explicit_save_and_load_opt_in(self):
        trainer = CpuTrainer(CpuTrainingConfig(), [1, 2])
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with self.assertRaises(ContractError):
                save_checkpoint(trainer, directory, "implicit-zero", {"unit": True})
            path = save_checkpoint(trainer, directory, "explicit-zero", {"unit": True}, allow_initial=True)
            with self.assertRaises(ContractError):
                load_checkpoint(path, {"unit": True})
            restored = load_checkpoint(path, {"unit": True}, allow_initial=True)
            self.assertEqual(restored.updates, 0)
            self.assertEqual(restored.episode_cursor, 0)
            self.assertEqual(restored.optimizer.state_dict(), trainer.optimizer.state_dict())
            self.assertEqual(parameter_digest(restored.model), parameter_digest(trainer.model))


if __name__ == "__main__":
    unittest.main()
