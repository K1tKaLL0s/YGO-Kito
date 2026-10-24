"""Explicit CPU merge checks; never discover the native fault experiments.

Run from a full source checkout with its existing CPU Python environment. This
allowlist tests local contracts/composition, not native correctness or providers.
"""
import argparse
from collections import Counter
import datetime
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT))
MODULES=(
    "tests.test_intent_model","tests.test_construction_model","tests.test_construction_binding",
    "tests.test_construction_logic","tests.test_construction_cli","tests.test_build_intent",
    "tests.test_build_contracts","tests.test_build_semantics","tests.test_catalog_discovery",
    "tests.test_combined_goals","tests.test_cli","tests.test_agent_contract",
    "tests.test_model_group_invariants","tests.test_training_checkpoint_contract",
    "tests.test_agent_tools","tests.test_construction_service","tests.test_integration_startup",
)
DP_HEAD="a7085e23a74fb04bff571c1c679e0097dd1ae430"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/".cache/merge-check")
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    native_pair={}
    for name in ("src/ygo_kito/native.py","src/ygo_kito/native_response_guard.py"):
        original=subprocess.check_output(["git","show",DP_HEAD+":"+name],cwd=ROOT)
        current=(ROOT/name).read_bytes()
        native_pair[name]={"sha256":hashlib.sha256(current).hexdigest(),"matches_dp_commit":original==current}
    if not all(v["matches_dp_commit"] for v in native_pair.values()):
        raise SystemExit("DP native/guard pair differs; review before running this candidate")
    source=hashlib.sha256()
    for path in sorted((ROOT/"src/ygo_kito").glob("*.py")):
        source.update(path.name.encode()+b"\0"+hashlib.sha256(path.read_bytes()).digest())
    started=datetime.datetime.now(datetime.timezone.utc).isoformat()
    stream=io.StringIO();suite=unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    before=time.monotonic();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    elapsed=time.monotonic()-before
    raw=stream.getvalue();(args.output/"tests.log").write_text(raw,encoding="utf-8")
    by_module=Counter()
    for line in raw.splitlines():
        if line.startswith("test_") and " (tests." in line:
            by_module[line.split(" (")[1].split(".")[1]]+=1
    receipt={"started_utc":started,"tested_head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        "implementation_sha256":source.hexdigest(),"tests_run":result.testsRun,"failures":len(result.failures),
        "errors":len(result.errors),"skipped":len(result.skipped),"success":result.wasSuccessful(),
        "elapsed_seconds":elapsed,"by_module":dict(by_module),"dp_native_pair":native_pair,
        "excluded_modules":["tests.test_native_response_buffer","integration_tests"],
        "exclusion_reason":"No native execution, fault reproduction, unscreened discovery, or external provider calls authorized in this run.",
        "evidence_scope":"local CPU contracts and explicitly synthetic model/composition tests",
        "native_executed":False,"external_provider_verified":False,"ci_verified":False}
    (args.output/"results.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


if __name__=="__main__":
    raise SystemExit(main())
