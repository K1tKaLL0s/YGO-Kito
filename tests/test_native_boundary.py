"""Unit checks for errors only; these are not real-engine success evidence."""

from pathlib import Path
import tempfile
import unittest

from ygo_kito.engine import EngineUnavailable
from ygo_kito.native import NativeError, Reader
from ygo_kito.native_assets import verify_resources


class NativeBoundaryTests(unittest.TestCase):
    def test_missing_resources_fail_without_a_simulated_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(EngineUnavailable):
                verify_resources(Path(folder))

    def test_truncated_native_message_fails_closed(self):
        with self.assertRaises(NativeError):
            Reader(b"\x01").u32()
