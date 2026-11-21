"""CPU-side refusal contracts; actual CUDA round trips use the explicit proof CLI."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import contextlib
import io

import torch
from tests.test_course_models import models_fixture
from ygo_kito.course_models import CourseModels
from ygo_kito.validation import ContractError


class CourseCudaMigrationTests(unittest.TestCase):
    def test_cli_routes_cuda_and_cpu_alias_to_the_same_real_consumers(self):
        from ygo_kito.cli import main
        from tests.test_construction_logic import fixture_assets
        task, _ = fixture_assets()
        for command, expected in (('duel-train', 'cuda:0'), ('duel-train-cpu', 'cpu'),
                                  ('build-train', 'cuda:0'), ('build-train-cpu', 'cpu')):
            build = command.startswith('build')
            module = 'build_training.run_build_training_smoke' if build else 'cpu_training.run_cpu_training_smoke'
            def read(path):
                return task.to_dict() if 'build-engineering' in str(path) else {}
            with self.subTest(command=command), patch('ygo_kito.' + module, return_value={'ok': True}) as run, \
                    patch('ygo_kito.native_assets.require_resource_receipt') as preflight, \
                    patch('ygo_kito.cli.read_json', side_effect=read), \
                    patch('ygo_kito.' + ('build_training' if build else 'cpu_training') + '.config_from_dict', return_value=None), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([command, '--run-id', 'migration-routing-check']), 0)
                preflight.assert_called_once_with(Path('.cache'))
                self.assertEqual(run.call_args.kwargs['device'], expected)

    def test_invalid_target_seed_and_unavailable_cuda_preserve_source(self):
        with tempfile.TemporaryDirectory() as temp:
            models, assets = models_fixture(Path(temp))
            state = deepcopy(models.save_state())
            before = models.fingerprint()
            for device, seed in (('cpu', 1), ('cuda:0', -1), ('cuda:0', True)):
                with self.subTest(device=device, seed=seed), self.assertRaises(ContractError):
                    CourseModels.migrate_to_cuda(state, assets=assets,
                        expected_binding=models.binding, device=device, cuda_seed=seed)
            with patch('torch.cuda.is_available', return_value=False), self.assertRaisesRegex(ContractError, 'unavailable'):
                CourseModels.migrate_to_cuda(state, assets=assets,
                    expected_binding=models.binding, device='cuda:0', cuda_seed=1)
            self.assertEqual(before, models.fingerprint())
            self.assertEqual(state['execution']['device'], 'cpu')


if __name__ == '__main__': unittest.main()
