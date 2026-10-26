"""Read-only CPU takeover inventory and explicitly conditional volume arithmetic.

This module has no launch, install, model-load, native-load or training action.
Byte receipts do not establish historical rules, bot operation, model strength,
durable hosting or execution authorization.
"""
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import shutil
import sys

from .build_contracts import digest
from .validation import ContractError, fields, integer

KINDS=("period_catalog","release_manifest","opponent_deck","bot_build_audit","bot_qualification",
       "model_group","data_index","course_checkpoint","availability","a10_reference","host_config",
       "source_bundle","external_sync")
SYNC=("not_received","received_unread","ready_for_audit","source_only")
PERIODS=("2022-07","2022-10","2026-10")


def _sha(path):
    result=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):result.update(block)
    return result.hexdigest()


def _inside(workspace,value):
    if not isinstance(value,str) or not value.strip():raise ContractError("explicit workspace artifact path required")
    path=(workspace/value).resolve()
    if not path.is_relative_to(workspace):raise ContractError("takeover artifact must stay inside the selected workspace")
    return path


def _pointer(value,pointer):
    if pointer=="":return value
    if not isinstance(pointer,str) or not pointer.startswith("/"):raise ContractError("JSON pointer required")
    for raw in pointer[1:].split("/"):
        key=raw.replace("~1","/").replace("~0","~")
        value=value[int(key)] if isinstance(value,list) else value[key]
    return value


def artifact_inventory(workspace,entry):
    """Only inspect an explicit file; never return its payload or card contents."""
    fields(entry,{"artifact_id","category","sync_status","reference"},{"expected_json_fields"})
    from .agent_registry import identifier
    identifier(entry["artifact_id"])
    if entry["category"] not in KINDS or entry["sync_status"] not in SYNC:
        raise ContractError("unknown takeover asset category/sync state")
    output={"artifact_id":entry["artifact_id"],"category":entry["category"],"reported_sync_status":entry["sync_status"],
        "status":"expected_unsynced" if entry["sync_status"]=="not_received" else "missing",
        "bytes_verified":False,"semantics_verified":False}
    ref=entry["reference"]
    if ref is None:return output
    fields(ref,{"path","sha256"})
    expected=ref["sha256"]
    if not isinstance(expected,str) or len(expected)!=64 or any(c not in "0123456789abcdef" for c in expected):
        raise ContractError("pinned artifact SHA256 required")
    path=_inside(workspace,ref["path"])
    output["path"]=path.relative_to(workspace).as_posix()
    if not path.is_file():return output
    output.update(bytes=path.stat().st_size,sha256=_sha(path))
    if output["sha256"]!=expected:
        output["status"]="hash_mismatch";return output
    output.update(status="verified_bytes_semantics_unread",bytes_verified=True)
    if entry["sync_status"]=="source_only":output["status"]="source_only"
    if entry["sync_status"]=="not_received":
        output["status"]="bytes_present_sync_confirmation_missing"
    checks=entry.get("expected_json_fields",{})
    if not isinstance(checks,dict):raise ContractError("explicit JSON source-field checks required")
    if checks and entry["sync_status"]=="ready_for_audit":
        try:
            value=json.loads(path.read_text(encoding="utf-8"))
            mismatches=[pointer for pointer,wanted in checks.items() if digest(_pointer(value,pointer))!=digest(wanted)]
            output.update(report_source_fields_match=not mismatches,failed_source_field_pointers=mismatches)
            if mismatches:output["status"]="report_source_mismatch"
        except (OSError,UnicodeError,ValueError,KeyError,IndexError,TypeError):
            output.update(status="report_source_unreadable",report_source_fields_match=False)
    return output


def conditional_budget(reference_mean_seconds=None,*,parallel_games=None):
    """A10 reference arithmetic, never a new CPU/period throughput prediction."""
    if reference_mean_seconds is not None and (type(reference_mean_seconds) not in (int,float) or
            not math.isfinite(reference_mean_seconds) or reference_mean_seconds<=0):
        raise ContractError("observed A10 paired-sample mean must be finite and positive or unknown")
    if parallel_games is not None:integer(parallel_games,"explicit hypothetical concurrent games",1,1024)
    per={"completed_bo1_matches":600,"completed_bo3_matches":400,
         "small_games_minimum":1400,"small_games_maximum_without_draw_retries":1800}
    total={"completed_bo1_matches":1800,"completed_bo3_matches":1200,
           "small_games_minimum":4200,"small_games_maximum_without_draw_retries":5400}
    result={"branch":"user_confirmed_slow_above_60_seconds","measured_new_cpu_mean_seconds":None,
        "confirmed_branch_does_not_require_remeasurement":True,"per_environment":{p:dict(per) for p in PERIODS},
        "three_environment_total":total,"self_play_credits_required_coverage":False,
        "pilot_or_evaluation_credits_training_volume":False,"reference_mean_seconds":reference_mean_seconds,
        "reference_scope":"original_A10_paired_sample_not_new_CPU_or_each_environment",
        "original_budget":{"amount":100,"unit":"GPU_instance_hours","changed":False},
        "current_CPU_budget_unit":"unknown_requires_user_clarification",
        "actual_CPU_wall_hours":None,"actual_parallelism_speedup":None,
        "parallel_games_assumed":parallel_games,"linear_scaling_from_cpu_count_assumed":False,
        "serial_game_seconds_sum_under_A10_reference":None,"idealized_reference_wall_hours":None,
        "excluded_from_game_seconds":["construction_and_CB_search","siding","model_updates","checkpoint_and_data_IO",
            "independent_evaluation","failure_or_draw_retries","installation_and_idle_time"],
        "fits_budget_verified":False}
    if reference_mean_seconds is not None:
        low,high=(total[k]*reference_mean_seconds for k in ("small_games_minimum","small_games_maximum_without_draw_retries"))
        result["serial_game_seconds_sum_under_A10_reference"]={"minimum":low,"maximum_without_draw_retries":high,
            "unit":"sum_of_game_seconds_not_elapsed_wall_time"}
        if parallel_games is not None:
            result["idealized_reference_wall_hours"]={"minimum":low/(3600*parallel_games),
                "maximum_without_draw_retries":high/(3600*parallel_games),
                "condition":"only_if_A10_reference_per_game_speed_transfers_and_concurrency_scales_perfectly_zero_overhead",
                "is_actual_CPU_estimate":False}
    return result


def hardware_observation(workspace):
    def read_number(path):
        try:
            raw=Path(path).read_text().strip()
            return int(raw) if raw.isdecimal() else raw
        except OSError:return None
    quota=read_number("/sys/fs/cgroup/cpu.max")
    cores=None
    if isinstance(quota,str):
        parts=quota.split()
        if len(parts)==2 and all(p.isdecimal() for p in parts) and int(parts[1]):cores=int(parts[0])/int(parts[1])
    disk=shutil.disk_usage(workspace)
    return {"python":platform.python_version(),"python_executable":sys.executable,"platform":platform.system(),
        "logical_cpu_count":os.cpu_count(),"affinity_cpu_count":len(os.sched_getaffinity(0)) if hasattr(os,"sched_getaffinity") else None,
        "cgroup_cpu_quota_cores":cores,"cgroup_memory_limit_bytes":read_number("/sys/fs/cgroup/memory.max"),
        "disk_total_bytes":disk.total,"disk_free_bytes":disk.free,"long_term_available_resources_verified":False,
        "provider_session_lifetime_seconds":None,"maximum_reliable_job_duration_seconds":None,
        "workspace_persistence_across_termination_verified":None,"cloudstudio_external_sync_verified":False,
        "note":"Instantaneous OS/cgroup observations do not establish hosting duration, storage persistence or parallel throughput."}


def local_inventory(workspace):
    """Passive local materials; a filename is never a model/bot qualification."""
    from .implementation_identity import source_tree_snapshot
    snapshot=source_tree_snapshot(workspace/"src/ygo_kito")
    cache=workspace/".cache"
    weights=[];indices=[];engineering_dates=[]
    if cache.is_dir():
        for path in cache.rglob("*"):
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(workspace):continue
            if path.suffix==".weights":
                weights.append({"path":path.relative_to(workspace).as_posix(),"bytes":path.stat().st_size,"sha256":_sha(path)})
            elif path.name=="data-index.sqlite3":
                indices.append({"path":path.relative_to(workspace).as_posix(),"bytes":path.stat().st_size})
            elif path.name.endswith("-engineering-dates.json"):
                engineering_dates.append(path.relative_to(workspace).as_posix())
    weights.sort(key=lambda item:(-item["bytes"],item["path"]))
    bots={"status":"missing","runtime_loaded":False,"compiled_executables_found":0}
    lock_path=workspace/"configs/bot-sources-v1.json"
    if lock_path.is_file():
        try:
            from .bot_deployment import verify_sources,verify_bundle
            lock=json.loads(lock_path.read_text())
            roots={source["source_id"]:_inside(workspace,(Path(".cache/bot-source-review")/source["repository"].replace("/","--")/"source").as_posix()) for source in lock["sources"]}
            sources=verify_sources(lock,roots)
            bots.update(status="source_only_verified_bytes",files=sum(len(s["files"]) for s in sources["sources"]),
                origins=[{"source_id":s["source_id"],"commit":s["commit"],"executor_source_files":s["expected_executor_files"]} for s in sources["sources"]])
            archive=cache/"bot-source-review/complete-bot-build-inputs-v2.tar.gz"
            if archive.is_file():
                verified=verify_bundle(archive,lock)
                bots["offline_bundle"]={"path":archive.relative_to(workspace).as_posix(),"sha256":_sha(archive),
                    "verified_source_files":verified["verified_source_files"],"runtime_ready":False}
        except (ContractError,OSError,ValueError,KeyError,TypeError):bots["status"]="source_missing_or_bytes_unverified"
    if cache.is_dir():bots["compiled_executables_found"]=sum(1 for p in cache.rglob("WindBot.exe") if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(workspace))
    return {"implementation_file_count":len(snapshot),"implementation_manifest_sha256":digest(snapshot),
        "model_artifacts":{"status":"present_unread" if weights else "missing","file_count":len(weights),
            "total_bytes":sum(w["bytes"] for w in weights),"file_manifest_sha256":digest(weights),
            "largest_candidates":weights[:8],"model_deserialized":False,"source_group_boundary_verified":False},
        "data_indices":{"status":"present_unread" if indices else "missing","file_count":len(indices),
            "total_bytes":sum(i["bytes"] for i in indices),"index_semantics_or_checkpoint_match_verified":False},
        "release_files":{"engineering_fixture_file_count":len(engineering_dates),"historical_release_completeness_verified":False,
            "note":"Engineering date fixtures are not historical release evidence; supply explicit independently sourced artifact refs."},
        "bots":bots,"actual_course_checkpoint_pointers":sum(1 for p in cache.rglob("course/latest.json") if p.is_file()) if cache.is_dir() else 0,
        "storage_growth":{"retention_or_pruning_verified":False,"full_course_storage_requirement_bytes":None,
            "checkpoint_contains_full_models_and_cumulative_records":True,
            "note":"Current files are a point-in-time footprint. Per-game and match-close saves plus the growing private index need explicit capacity/retention planning."}}


def default_config():
    return {"schema_version":1,"kind":"cpu-takeover-readiness-audit-v1","native_root":".cache",
        "start_notification_received":False,"artifacts":[],"a10_reference":None,"parallel_games_assumed":None}


def collect(workspace,config=None):
    workspace=Path(workspace).resolve(strict=True)
    config=default_config() if config is None else config
    fields(config,{"schema_version","kind","native_root","start_notification_received","artifacts","a10_reference","parallel_games_assumed"})
    integer(config["schema_version"],"takeover audit schema",1,1)
    if config["kind"]!="cpu-takeover-readiness-audit-v1" or type(config["start_notification_received"]) is not bool:
        raise ContractError("explicit audit configuration and user-notification state required")
    if not isinstance(config["artifacts"],list):raise ContractError("explicit artifact list required")
    rows=[artifact_inventory(workspace,entry) for entry in config["artifacts"]]
    if len({r["artifact_id"] for r in rows})!=len(rows):raise ContractError("duplicate takeover artifact ID")
    dependencies={}
    for name in ("torch","numpy","scipy"):
        try:dependencies[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:dependencies[name]=None
    locks={}
    for relative in ("requirements/ci-cpu.txt","configs/native-sources.lock.json","configs/bot-sources-v1.json"):
        path=workspace/relative
        locks[relative]={"exists":path.is_file(),"sha256":_sha(path) if path.is_file() else None}
    try:
        from .native_assets import verify_resources
        receipt=verify_resources(_inside(workspace,config["native_root"]))
        if receipt["source_lock_sha256"]!=locks["configs/native-sources.lock.json"]["sha256"]:
            raise ContractError("selected workspace native lock differs from verified resources")
        native={"status":"verified_file_hashes_only","source_commits":receipt["source_commits"],"resources":receipt["resources"],
            "library_loaded":False,"rules_executed":False}
    except (OSError,ValueError,KeyError,TypeError,RuntimeError):
        native={"status":"missing_or_hash_mismatch","library_loaded":False,"rules_executed":False}
    tools={name:shutil.which(name) for name in ("mono","mcs","xbuild","msbuild","dotnet")}
    reference_mean=None;reference={"status":"not_supplied","actual_CPU_speed_verified":False}
    if config["a10_reference"] is not None:
        spec=fields(config["a10_reference"],{"artifact_id","mean_json_pointer"})
        found=next((r for r in rows if r["artifact_id"]==spec["artifact_id"] and r["category"]=="a10_reference"),None)
        if found is None or not found["bytes_verified"] or found["reported_sync_status"]!="ready_for_audit":
            raise ContractError("A10 reference requires its explicitly received, hash-verified report artifact")
        entry=next(e for e in config["artifacts"] if e["artifact_id"]==spec["artifact_id"])
        value=json.loads(_inside(workspace,entry["reference"]["path"]).read_text(encoding="utf-8"))
        reference_mean=_pointer(value,spec["mean_json_pointer"])
        reference={"status":"read_pinned_report_mean_only","artifact_id":spec["artifact_id"],
            "sha256":found["sha256"],"source_fields_verified":found.get("report_source_fields_match"),"actual_CPU_speed_verified":False}
        if found.get("report_source_fields_match") is False:raise ContractError("A10 reference report source fields differ")
    categories={kind:sum(r["category"]==kind and r["bytes_verified"] and r["status"]=="verified_bytes_semantics_unread" for r in rows) for kind in KINDS}
    required=("period_catalog","release_manifest","model_group","host_config","availability","bot_build_audit","bot_qualification","opponent_deck")
    missing=[kind for kind in required if not categories[kind]]
    blockers=["formal_start_requires_user_notification"] if not config["start_notification_received"] else []
    blockers+= ["missing_verified_artifact_category:"+kind for kind in missing]
    if native["status"]!="verified_file_hashes_only":blockers.append("native_resource_hashes_unverified")
    if tools["mono"] is None:blockers.append("mono_toolchain_unavailable")
    if any(v is None for v in dependencies.values()):blockers.append("CPU_dependency_missing")
    blockers.append("semantic_period_bot_model_and_host_runtime_readiness_not_certified_by_byte_audit")
    return {"schema_version":1,"kind":"cpu-takeover-readiness-report","mode":"audit_only","config_sha256":digest(config),
        "native":native,"dependencies":dependencies,"locks":locks,"toolchain":tools,"artifacts":rows,
        "hardware":hardware_observation(workspace),"local_inventory":local_inventory(workspace),"a10_reference":reference,
        "budget":conditional_budget(reference_mean,parallel_games=config["parallel_games_assumed"]),
        "start_notification_received":config["start_notification_received"],"blockers":blockers,
        "formal_start_ready":False,"execution_authorized_by_this_tool":False,"training_started":False,
        "native_executed":False,"third_party_code_executed":False,"raw_private_payloads_in_report":False}
