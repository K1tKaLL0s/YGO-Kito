from pathlib import Path
import tempfile
import unittest

from ygo_kito.training_preflight import cpu_preflight
from ygo_kito.validation import read_json

ROOT = Path(__file__).resolve().parents[1]


class TrainingPreflightIntegrationTests(unittest.TestCase):
    def test_missing_native_resources_are_reported_as_an_unavailable_health_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "not-prepared"
            result = cpu_preflight(missing, read_json(ROOT / "configs/training-plan-v1.json"))
            self.assertFalse(result["ok"])
            self.assertFalse(result["checks"]["locked_native_assets"]["passed"])
            self.assertTrue(result["checks"]["torch_cpu_forward_backward"]["passed"])
            self.assertFalse(result["formal_training"]["ready"])
            self.assertFalse(missing.exists())

    def test_real_cpu_assets_and_scratch_sqlite_do_not_authorize_paid_execution(self):
        result = cpu_preflight(ROOT / ".cache", read_json(ROOT / "configs/training-plan-v1.json"))
        self.assertTrue(result["ok"])
        self.assertTrue(result["checks"]["torch_cpu_forward_backward"]["passed"])
        self.assertGreater(result["checks"]["torch_cpu_forward_backward"]["gradient_norm"], 0)
        self.assertTrue(result["checks"]["sqlite_rollback"]["passed"])
        self.assertTrue(result["checks"]["locked_native_assets"]["passed"])
        self.assertFalse(result["checks"]["locked_native_assets"]["native_duel_executed"])
        self.assertFalse(result["formal_training"]["ready"])
        self.assertFalse(result["formal_training"]["resource_launch_implemented"])
        self.assertFalse(result["formal_training"]["paid_execution_authorized"])
        self.assertFalse(result["external_agent"]["credentials_read"])
        self.assertFalse(result["external_agent"]["provider_called"])
        self.assertFalse(result["external_agent"]["model_or_quota_checked"])


if __name__ == "__main__":
    unittest.main()
