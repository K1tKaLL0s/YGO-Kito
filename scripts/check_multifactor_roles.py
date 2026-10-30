"""Explicit CPU-only checks for this optional module, with separate evidence groups.

Does not run test discovery, native tests, formal training or existing pipelines.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import torch

from ygo_kito.multifactor.contracts import schema_fingerprint
from ygo_kito.multifactor.network import RoleNetwork
from ygo_kito.multifactor.training import source_fingerprint

MODULES = (
    ("structural_properties", "tests.test_multifactor_structure"),
    ("synthetic_factor_code_paths", "tests.test_multifactor_synthetic"),
    ("official_effect_contract_samples", "tests.test_multifactor_real_effects"),
    ("functional_unit_contracts_and_definition_cases", "tests.test_multifactor_units"),
    ("lora_isolation_and_recovery", "tests.test_multifactor_adapters"),
    ("adapter_load_transaction_and_output_status", "tests.test_multifactor_adapter_transactions"),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".cache" / "multifactor-check")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    start = time.monotonic()
    groups = []
    with (args.output / "tests.log").open("w", encoding="utf-8") as stream:
        for kind, module in MODULES:
            suite = unittest.defaultTestLoader.loadTestsFromName(module)
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
            groups.append(dict(kind=kind, tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                               skipped=len(result.skipped), passed=result.wasSuccessful() and not result.skipped))
    code = subprocess.run(("git", "--work-tree=" + str(ROOT), "rev-parse", "HEAD"), cwd=ROOT,
                          capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    paths = list((ROOT / "src" / "ygo_kito" / "multifactor").glob("*.py"))
    paths += list((ROOT / "tests").glob("test_multifactor_*.py"))
    paths += [ROOT / "tests" / "multifactor_helpers.py", ROOT / "tests" / "fixtures" / "multifactor-real-effect-observations-v1.json", Path(__file__)]
    paths += [ROOT / "tests" / "fixtures" / "multifactor-functional-definition-cases-v2.json"]
    receipt = dict(schema_version="multifactor-engineering-check-v1", tested_head=code,
                   schema_sha256=schema_fingerprint(), module_source_sha256=source_fingerprint(),
                   tested_files={path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)},
                   python=platform.python_version(), torch=str(torch.__version__), platform=platform.platform(),
                   device="cpu", threads=torch.get_num_threads(), default_parameters=sum(p.numel() for p in RoleNetwork().parameters()),
                   elapsed_seconds=round(time.monotonic() - start, 3), groups=groups,
                   passed=all(group["passed"] for group in groups), ci_verified=False,
                   formal_training="not_run", native_engine="not_run", external_provider="not_run",
                   unseen_theme_quality_validation="not_run", same_package_contextual_role_quality_validation="not_run",
                   calibration="not_run", existing_active_pipelines_modified=False)
    (args.output / "results.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in receipt.items() if key != "tested_files"}, indent=2))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
