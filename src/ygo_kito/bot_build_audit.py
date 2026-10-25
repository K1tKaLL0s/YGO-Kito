"""Full fixed desktop-bot build/audit plans and explicitly invoked execution.

No tooling is installed. Android/library, room connections and duels are outside
this checker. A prepared plan or injected test runner is never runtime evidence.
"""

from pathlib import Path
import hashlib
import json
import os
import subprocess

from . import bot_deployment
from .bot_deployment import PINS, inventory, validate_lock
from .build_contracts import digest
from .validation import ContractError, canonical_json

ROOT = Path(__file__).resolve().parents[2]


def file_sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def prepare_plan(lock, roots, source_id, cards_cdb, cards_sha256, output_directory):
    lock = validate_lock(lock)
    if source_id not in ("ice", "pure"):
        raise ContractError("only complete reviewed desktop builds are enabled; Android/library is excluded")
    data = inventory(lock, roots)
    source = next(s for s in lock["sources"] if s["source_id"] == source_id)
    if data["projects"][source_id]["postbuild_events"]:
        raise ContractError("unreviewed post-build execution is forbidden")
    cards = Path(cards_cdb).resolve()
    if not cards.is_file() or file_sha(cards) != cards_sha256:
        raise ContractError("explicit cards.cdb checksum is absent or differs")
    output = Path(output_directory).resolve()
    source_root = Path(roots[source_id]).resolve()
    if output == source_root or output.is_relative_to(source_root):
        raise ContractError("build outputs must remain outside immutable pinned source roots")
    bots = []
    for row in data["origins"]:
        if row["source_id"] != source_id:
            continue
        candidates = row["deck_resource_candidates"]
        local = [c for c in candidates if c["source_id"] == source_id and
                 c["path"].casefold() == ("Decks/" + row["deck_file"] + ".ydk").casefold()]
        if len(local) == 1:
            selected = local[0]
        elif candidates and len({c["sha256"] for c in candidates}) == 1:
            selected = sorted(candidates, key=lambda c: (c["source_id"], c["path"]))[0]
        else:
            raise ContractError("Executor requires an explicit unambiguous source YDK variant: " + row["deck_name"])
        bots.append({"full_type": "WindBot.Game.AI.Decks." + row["class_name"],
            "deck_name": row["deck_name"], "deck_file": row["deck_file"], "level": row["level"] or "Normal",
            "selected_deck": {"path": str((Path(roots[selected["source_id"]]) / selected["path"]).resolve()),
                              "sha256": selected["sha256"]},
            "selected_deck_source_id": selected["source_id"]})
    if len(bots) != bot_deployment.COUNTS[source_id][0] or len({b["full_type"] for b in bots}) != len(bots):
        raise ContractError("expected complete Executor type list differs from its fixed source")
    return {"schema_version": 1, "kind": "complete-desktop-bot-build-plan", "source_id": source_id,
        "repository": PINS[source_id][0], "commit": PINS[source_id][1],
        "source_lock_sha256": digest(lock), "inventory_sha256": data["inventory_sha256"],
        "source_roots": {i: str(Path(p).resolve()) for i, p in roots.items()}, "source_root": str(source_root),
        "output_directory": str(output), "assembly_path": str(output / "bin/WindBot.exe"),
        "cards": {"path": str(cards), "sha256": cards_sha256},
        "resources": [{"path": str(source_root / f["path"]), "sha256": f["sha256"]} for f in source["files"]],
        "bots": bots, "audit_source": str(ROOT / "scripts/BotAssemblyAudit.cs"),
        "audit_source_sha256": file_sha(ROOT / "scripts/BotAssemblyAudit.cs"),
        "executed": False, "runtime_loaded": False, "normal_duel_verified": False,
        "strength_verified": False, "history_verified": False, "training_connected": False}


def validate_audit_result(plan, audit, *, construct):
    expected = {(b["full_type"], b["deck_name"]) for b in plan["bots"]}
    rows = audit.get("bots", [])
    actual = [(r.get("full_type"), r.get("deck_name")) for r in rows]
    if (type(audit.get("schema_version")) is not int or audit.get("schema_version") != 1 or audit.get("error") is not None or
            audit.get("assembly_loaded") is not True or audit.get("all_expected_executors_matched") is not True or
            audit.get("all_resources_verified") is not True or audit.get("constructor_execution_requested") is not construct or
            audit.get("assembly_sha256") != file_sha(plan["assembly_path"]) or len(actual) != len(expected) or set(actual) != expected):
        raise ContractError("runtime audit is incomplete or differs from the exact full source set")
    if any(r.get("metadata_matched") is not True or r.get("error") is not None or
           (construct and (r.get("resource_verified") is not True or r.get("constructed") is not True)) for r in rows):
        raise ContractError("an Executor did not pass its exact metadata/resource/constructor check")
    if any(audit.get(k) is not False for k in ("normal_duel_verified", "strength_verified", "history_verified", "training_connected")):
        raise ContractError("assembly audit must not claim duel, training, history or strength")
    return audit


def execute_plan(lock, plan, *, mono, compiler, msbuild, construct=True, runner=None, timeout=180):
    expected = prepare_plan(lock, plan["source_roots"], plan["source_id"], plan["cards"]["path"],
                            plan["cards"]["sha256"], plan["output_directory"])
    if plan != expected:
        raise ContractError("prepared build plan or exact source/resources changed")
    if type(construct) is not bool or type(timeout) not in (int, float) or not 0 < timeout <= 600:
        raise ContractError("explicit constructor mode and bounded process timeout required")
    tools = [Path(p) for p in (mono, compiler, msbuild)]
    if any(not p.is_absolute() or not p.is_file() or not os.access(p, os.X_OK) for p in tools):
        raise ContractError("explicit verified official Mono/compiler/MSBuild paths are unavailable; no build executed")
    toolchain = {name: {"path": str(path.resolve()), "sha256": file_sha(path)}
                 for name, path in zip(("mono", "compiler", "msbuild"), tools)}
    output = Path(plan["output_directory"])
    output.mkdir(parents=True, exist_ok=False)
    injected = runner is not None
    run = subprocess.run if runner is None else runner
    commands = [
        [str(tools[2]), "WindBot.csproj", "/t:Build", "/p:Configuration=Release", "/p:Platform=AnyCPU",
         "/p:ExternalPolicyOnly=false", "/p:RunPostBuildEvent=Never", "/p:OutputPath=" + str(output / "bin") + "/",
         "/p:BaseIntermediateOutputPath=" + str(output / "obj") + "/"],
        [str(tools[1]), "-r:System.Runtime.Serialization", "-r:System.Core", "-out:" + str(output / "BotAssemblyAudit.exe"), plan["audit_source"]],
    ]
    for index, argv in enumerate(commands):
        with (output / ("build-" + str(index) + ".log")).open("xb") as log:
            result = run(argv, cwd=plan["source_root"], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                         timeout=timeout, check=False)
        if result.returncode != 0:
            raise ContractError("complete fixed-source build failed; inspect per-step log; no reduced fallback")
    spec = {k: plan[k] for k in ("schema_version", "source_id", "assembly_path", "source_root", "cards", "resources", "bots")}
    spec["assembly_sha256"] = file_sha(plan["assembly_path"])
    manifest = output / "assembly-audit-input.json"
    manifest.write_text(canonical_json(spec) + "\n", encoding="utf-8")
    result_path = output / "assembly-audit-output.json"
    argv = [str(tools[0]), str(output / "BotAssemblyAudit.exe"), str(manifest), str(result_path)]
    if construct: argv.append("--construct")
    with (output / "reflection.log").open("xb") as log:
        result = run(argv, cwd=plan["source_root"], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                     timeout=timeout, check=False)
    audit = json.loads(result_path.read_text(encoding="utf-8"))
    validate_audit_result(plan, audit, construct=construct)
    if result.returncode != 0:
        raise ContractError("reflection/constructor process failed")
    # Third-party construction may read resources; any mutation invalidates proof.
    if prepare_plan(lock, plan["source_roots"], plan["source_id"], plan["cards"]["path"],
                    plan["cards"]["sha256"], plan["output_directory"]) != plan:
        raise ContractError("source/resource state changed during assembly audit")
    if any(file_sha(tool["path"]) != tool["sha256"] for tool in toolchain.values()):
        raise ContractError("Mono/build tool identity changed during audit")
    return {"schema_version": 1, "kind": "complete-desktop-bot-build-audit", "source_id": plan["source_id"],
        "repository": plan["repository"], "commit": plan["commit"], "source_lock_sha256": plan["source_lock_sha256"],
        "inventory_sha256": plan["inventory_sha256"], "assembly_path": plan["assembly_path"],
        "source_root": plan["source_root"], "source_roots": plan["source_roots"],
        "audit_source_sha256": plan["audit_source_sha256"],
        "audit_output_path": str(result_path), "audit_output_sha256": file_sha(result_path),
        "toolchain": toolchain,
        "assembly_sha256": spec["assembly_sha256"], "cards": plan["cards"], "expected_bots": plan["bots"],
        "evidence_source": "injected_process_contract_check" if injected else "actual_complete_assembly_audit",
        "runtime_loaded": not injected, "constructors_verified": construct and not injected, "audit": audit,
        "normal_duel_verified": False, "strength_verified": False, "history_verified": False, "training_connected": False}
