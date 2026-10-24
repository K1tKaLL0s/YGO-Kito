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
import os
from pathlib import Path
import platform
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
    "tests.test_training_handoff",
    "tests.test_agent_lifecycle","tests.test_construction_scenarios","tests.test_deck_intake",
    "tests.test_device_execution","tests.test_training_execution_limits","tests.test_coordinator_supervision",
    "tests.test_training_input","tests.test_deployment_prepare",
    "tests.test_period_runtime","tests.test_period_host","tests.test_semantic_solver",
    "tests.test_duel_model","tests.test_lora","tests.test_coordinator_model","tests.test_group_runner",
    "tests.test_merge_candidate_context",
)
DP_HEAD="a7085e23a74fb04bff571c1c679e0097dd1ae430"
DP_HASHES={"src/ygo_kito/native.py":"0a2f40c99e3e14bb1eb0446c89c8b80175cd6f1893c8207ee8496deb6725139e",
           "src/ygo_kito/native_response_guard.py":"685846435d4f951324f36a04ff49ea67c4d70c2d4b2c974963e12a4a9e8df64b"}
LIMIT_READ='limits = banlist_limits(self.sources / "client/lflist.conf")'
LIMIT_HOOK=('    def _deck_limits(self):\n'
            '        """Host period adapters may select a separately checked historical section."""\n'
            '        return banlist_limits(self.sources / "client/lflist.conf")\n\n')


def checkout_context(root):
    root=Path(root).resolve()
    try:
        top=subprocess.check_output(["git","rev-parse","--show-toplevel"],cwd=root,text=True,stderr=subprocess.DEVNULL).strip()
        if Path(top).resolve()==root:
            head=subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
            return {"checkout_kind":"git","tested_head":head,"source_archive_commit":None}
    except (OSError,subprocess.SubprocessError):
        pass
    from scripts.deployment_prepare import verify_source_tree
    manifest=verify_source_tree(root)
    return {"checkout_kind":"source_archive","tested_head":None,"source_archive_commit":manifest["source_commit"]}


def approved_period_hook(original):
    source=original.decode("utf-8")
    target='    def validate_deck(self, deck):\n'
    if source.count(LIMIT_READ)!=2 or source.count(target)!=1:
        raise SystemExit("DP native baseline differs from the reviewed hook patch")
    return source.replace(LIMIT_READ,'limits = self._deck_limits()').replace(target,LIMIT_HOOK+target).encode("utf-8")


def matches_pinned_native_hook(current):
    """The only accepted extension must reverse exactly to the pinned DP bytes."""
    if hashlib.sha256(current).hexdigest()==DP_HASHES["src/ygo_kito/native.py"]:
        return False  # Original bytes are separately identified, not an extension.
    source=current.decode("utf-8")
    call='limits = self._deck_limits()'
    if source.count(call)!=2 or source.count(LIMIT_HOOK)!=1:
        return False
    original=source.replace(LIMIT_HOOK,"").replace(call,LIMIT_READ).encode("utf-8")
    return hashlib.sha256(original).hexdigest()==DP_HASHES["src/ygo_kito/native.py"]


def audit_native_pair(root,context):
    pair={}
    for name,expected_sha in DP_HASHES.items():
        current=(Path(root)/name).read_bytes()
        sha=hashlib.sha256(current).hexdigest()
        if context["checkout_kind"]=="git":
            original=subprocess.check_output(["git","show",DP_HEAD+":"+name],cwd=root)
            if hashlib.sha256(original).hexdigest()!=expected_sha:
                raise SystemExit("DP native/guard baseline differs from its pinned SHA256")
            approved=approved_period_hook(original) if name.endswith("/native.py") else original
            matches_dp,reviewed=original==current,approved==current
        else:
            matches_dp=None  # A source archive has no local Git commit evidence.
            reviewed=matches_pinned_native_hook(current) if name.endswith("/native.py") else False
        pair[name]={"sha256":sha,"dp_baseline_sha256":expected_sha,"matches_dp_commit":matches_dp,
                    "matches_pinned_dp_sha256":sha==expected_sha,"matches_reviewed_period_hook":reviewed,
                    "comparison_source":"git-show-pinned-commit" if context["checkout_kind"]=="git" else "pinned-dp-sha256-without-git"}
        if not (sha==expected_sha or reviewed):
            raise SystemExit("DP binding/guard or reviewed period hook differs; review before running")
    return pair


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/".cache/merge-check")
    args=parser.parse_args()
    args.output=args.output.resolve()
    args.output.mkdir(parents=True,exist_ok=True)
    # Several older contract fixtures intentionally use repository-relative
    # configuration paths. Make invocation independent of the caller's cwd.
    os.chdir(ROOT)
    try:
        import torch
        import numpy
        import scipy
    except ModuleNotFoundError as error:
        raise SystemExit("Required CPU test dependency missing: "+str(error)) from error
    if torch.version.cuda is not None or torch.version.hip is not None:
        raise SystemExit("This check requires the CPU-only PyTorch build")
    dependencies={"python":platform.python_version(),"torch":torch.__version__,"numpy":numpy.__version__,"scipy":scipy.__version__}
    context=checkout_context(ROOT)
    native_pair=audit_native_pair(ROOT,context)
    source=hashlib.sha256()
    for path in sorted((ROOT/"src/ygo_kito").glob("*.py")):
        source.update(path.name.encode()+b"\0"+hashlib.sha256(path.read_bytes()).digest())
    started=datetime.datetime.now(datetime.timezone.utc).isoformat()
    stream=io.StringIO();suite=unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    before=time.monotonic();cpu_before=time.process_time()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    elapsed=time.monotonic()-before
    resources={"test_wall_seconds":elapsed,"process_cpu_seconds":time.process_time()-cpu_before,
        "process_peak_rss_bytes":None,"gpu_memory_bytes":None,"game_samples_per_second":None,
        "scope":"test runner parent process; subprocess CPU/RSS not aggregated; no game throughput measured"}
    try:
        import resource
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        resources["process_peak_rss_bytes"]=peak if sys.platform=="darwin" else peak*1024
    except ImportError:
        pass
    raw=stream.getvalue();(args.output/"tests.log").write_text(raw,encoding="utf-8")
    by_module=Counter()
    for line in raw.splitlines():
        if line.startswith("test_") and " (tests." in line:
            by_module[line.split(" (")[1].split(".")[1]]+=1
    success=result.wasSuccessful() and not result.skipped
    from scripts.deployment_prepare import selected_dirty
    source_clean=context["checkout_kind"]=="source_archive" or not selected_dirty(ROOT)
    receipt={"started_utc":started,**context,"selected_source_clean":source_clean,
        "implementation_sha256":source.hexdigest(),"tests_run":result.testsRun,"failures":len(result.failures),
        "errors":len(result.errors),"skipped":len(result.skipped),"success":success,
        "dependencies":dependencies,"skipped_tests":[{"test":str(test),"reason":reason} for test,reason in result.skipped],
        "resources":resources,
        "elapsed_seconds":elapsed,"by_module":dict(by_module),"dp_native_pair":native_pair,
        "excluded_modules":["tests.test_native_response_buffer","integration_tests"],
        "exclusion_reason":"This explicit CPU allowlist performs no native calls. Ordinary native tests are checked separately; fault reproduction and unscreened discovery remain excluded.",
        "evidence_scope":"local CPU contracts and explicitly synthetic model/composition tests",
        "native_executed":False,"external_provider_verified":False,"ci_verified":False}
    (args.output/"results.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False))
    return 0 if success else 1


if __name__=="__main__":
    raise SystemExit(main())
