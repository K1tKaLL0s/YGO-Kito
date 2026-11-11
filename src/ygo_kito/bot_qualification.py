"""Exact-source engineering list checks and explicitly invoked normal games.

Planning reads files only. Actual games require the registry's real complete
assembly audit and launcher; no callback can substitute for a C# executor.
These checks are neither a historical qualification nor a strength benchmark.
"""
from collections import Counter
import hashlib
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .agent_registry import parse_ydk
from .bot_deployment import BotSourceRegistry
from .build_contracts import DeckParts, digest
from .build_pipeline import BuildAssets
from .contracts import ActionSelection, Versions, validate_selection
from .deck_profile import validate_deck_parts, validate_profile
from .effect_duel import choose_effect_duel_action
from .native import NativeError, NativeNormalEngine
from .validation import ContractError, canonical_json, integer, read_json


def normal_engineering_actor(native_root):
    """The existing native smoke's public normal pool, never a user deck."""
    assets = BuildAssets(native_root)
    cards = [c for c, r in sorted(assets.rows.items()) if r["type"] == 17 and r["alias"] == 0 and
             r["ot"] & 1 and c < 100000000 and 1 <= r["level"] <= 4 and assets.limits.get(c, 3) >= 1][:40]
    if len(cards) != 40:
        raise ContractError("existing normal engineering pool does not contain 40 legal cards")
    return {"schema_version": 2, "name": "existing-normal-engineering-pool-not-user-deck",
            "adapter_revision": 5, "decks": [cards, list(cards)], "extras": [[], []], "sides": [[], []]}


def _deck_reference(registry, definition):
    candidates = definition["deck_resource_candidates"]
    local = [r for r in candidates if r["source_id"] == definition["source_id"] and
             r["path"].casefold() == ("Decks/" + definition["deck_file"] + ".ydk").casefold()]
    if len(local) == 1:
        selected = local[0]
    elif candidates and len({r["sha256"] for r in candidates}) == 1:
        selected = sorted(candidates, key=lambda r: (r["source_id"], r["path"]))[0]
    else:
        raise ContractError("missing or ambiguous exact source YDK; explicit variant required")
    root = registry.root.resolve()
    path = (root / selected["source_id"] / selected["path"]).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ContractError("YDK must be a regular file inside the fixed source registry")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != selected["sha256"]:
        raise ContractError("selected source YDK changed")
    return selected, DeckParts.from_dict(parse_ydk(raw.decode("utf-8-sig")))


def _profile(actor_profile, deck, actor_seat):
    validate_profile(actor_profile)
    actor = {"main": actor_profile["decks"][actor_seat],
             "extra": actor_profile.get("extras", [[], []])[actor_seat],
             "side": actor_profile.get("sides", [[], []])[actor_seat]}
    parts = [actor, actor]
    parts[1 - actor_seat] = deck.to_dict()
    return {"schema_version": 2, "name": "exact-bot-engineering-qualification", "adapter_revision": 5,
            "decks": [p["main"] for p in parts], "extras": [p["extra"] for p in parts],
            "sides": [p["side"] for p in parts]}


def _variant_definition(registry, variant_root):
    if variant_root is None:
        return None
    from .bot_overlay import runtime_overlay_identity
    identity = runtime_overlay_identity(registry.lock, variant_root)
    definitions = registry.inventory["origins"]
    matches = [r for r in definitions if r["source_id"] == "library" and
               r["source_path"] == identity["donor"]["path"] and
               r["sha256"] == identity["replacement"]["donor_sha256"]]
    if len(matches) != 1:
        raise ContractError("exact overlay donor must identify one preserved library origin")
    return identity, matches[0]


def prepare_qualification(registry, native_root, actor_profile, *, actor_seat=0, variant_root=None):
    """All fixed origins remain visible, including source-only Android entries."""
    if not isinstance(registry, BotSourceRegistry):
        raise ContractError("complete typed source registry required")
    integer(actor_seat, "qualification actor seat", 0, 1)
    validate_profile(actor_profile)
    registry.statuses()
    variant = _variant_definition(registry, variant_root)
    assets = BuildAssets(native_root)  # Receipt/file checks only, not CDLL loading.
    actor = {"main": actor_profile["decks"][actor_seat],
             "extra": actor_profile.get("extras", [[], []])[actor_seat],
             "side": actor_profile.get("sides", [[], []])[actor_seat]}
    validate_deck_parts(actor, assets.rows, assets.limits)
    rows = []
    for definition in registry.inventory["origins"]:
        row = {k: definition[k] for k in ("bot_id", "source_id", "class_name", "deck_name")}
        row.update(runtime_candidate=definition["source_id"] in ("ice", "pure"), list_legal=None,
                   status="source_only_not_desktop_qualified", normal_duel_verified=False)
        runtime_definition = definition
        row.update(runtime_source_id=definition["source_id"], runtime_executor_id=definition["class_name"])
        if variant is not None and definition["bot_id"] == variant[1]["bot_id"]:
            counterparts = [r for r in registry.inventory["origins"] if r["source_id"] == "pure" and
                            r["source_path"] == variant[0]["replacement"]["path"]]
            if len(counterparts) != 1:
                raise ContractError("overlay must preserve one full desktop Executor counterpart")
            runtime_definition = counterparts[0]
            row.update(runtime_candidate=True, runtime_source_id="pure", variant=variant[0])
        deck = None
        try:
            selected, deck = _deck_reference(registry, runtime_definition)
            row["selected_deck"] = {k: selected[k] for k in ("source_id", "path", "sha256")}
            row["deck_sha256"] = digest(deck.to_dict())
            profile = _profile(actor_profile, deck, actor_seat)
            row["profile_sha256"] = digest(profile)
            validate_deck_parts(deck.to_dict(), assets.rows, assets.limits)
            row["list_legal"] = True
            if row["runtime_candidate"]:
                row["status"] = "list_checked_runtime_unverified"
        except (ContractError, OSError, UnicodeError) as error:
            row.update(list_legal=False, status="source_deck_or_current_listing_rejected", reason=str(error))
            if deck is not None:
                codes = deck.main + deck.extra + deck.side
                counts = Counter(assets.rows[c]["alias"] or c for c in codes if c in assets.rows)
                row["listing_diagnostics"] = {
                    "sizes": {zone: len(getattr(deck, zone)) for zone in ("main", "extra", "side")},
                    "missing_card_ids": sorted(set(codes) - set(assets.rows)),
                    "non_ocg_or_token_ids": sorted({c for c in codes if c in assets.rows and
                                                    (not assets.rows[c]["ot"] & 1 or assets.rows[c]["type"] & 0x4000)}),
                    "copy_limits_exceeded": [{"alias_or_id": c, "copies": n, "limit": assets.limits.get(c, 3)}
                                             for c, n in sorted(counts.items()) if n > assets.limits.get(c, 3)]}
        rows.append(row)
    return {"schema_version": 1, "kind": "all-source-bot-engineering-qualification-plan",
            "context": "current-pinned-2026.10-engineering-resources-not-historical-course",
            "resources": assets.receipt, "source_lock_sha256": digest(registry.lock),
            "inventory_sha256": registry.inventory["inventory_sha256"], "actor_profile_sha256": digest(actor_profile),
            "variant": None if variant is None else variant[0],
            "actor_seat": actor_seat, "rows": rows, "counts": dict(Counter(r["status"] for r in rows)),
            "native_executed": False, "csharp_executed": False, "normal_duel_verified": False,
            "historical_qualified": False, "strength_qualified": False, "training_updates": 0}


def _execution_plan(registry, plan, native_root, actor_profile, audits, selected_bot_ids,
                    seed, max_decisions, seconds, variant_root):
    integer(seed, "engineering controller seed", 0, 2**32 - 8)
    integer(max_decisions, "normal qualification decision bound", 1, 10000)
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 300:
        raise ContractError("normal qualification duration must be within 300 seconds")
    fresh = prepare_qualification(registry, native_root, actor_profile, actor_seat=plan["actor_seat"], variant_root=variant_root)
    if fresh != plan:
        raise ContractError("qualification source, catalog, actor or plan changed")
    ids = {r["bot_id"] for r in fresh["rows"]}
    selected = ({r["bot_id"] for r in fresh["rows"] if r["runtime_candidate"]}
                if selected_bot_ids is None else set(selected_bot_ids))
    if not selected <= ids:
        raise ContractError("unknown qualification bot identity")
    from .bot_overlay import VARIANT_ID
    if not isinstance(audits, dict) or set(audits) - {"ice", "pure", VARIANT_ID}:
        raise ContractError("explicit desktop audit references required")
    return fresh, selected


def _execute_qualification(registry, plan, native_root, actor_profile, *, audits, mono, workspace,
                           selected_bot_ids=None, seed=7, max_decisions=3000, seconds=60, variant_root=None,
                           progress=None):
    fresh, selected = _execution_plan(registry, plan, native_root, actor_profile, audits, selected_bot_ids,
                                      seed, max_decisions, seconds, variant_root)
    assets = BuildAssets(native_root)
    versions = Versions.from_dict(assets.environment_for("deck_constraints")["versions"])
    facts = {c: {"type": r["type"], "level": r["level"] & 255, "attack": r["atk"], "defense": r["def"]}
             for c, r in assets.rows.items()}
    for row in fresh["rows"]:
        row.update(native_executed=False, csharp_executed=False, decisions=0, bot_decisions=0)
        if row["bot_id"] not in selected:
            if row["runtime_candidate"]:
                row["status"] = "not_selected"
            continue
        if not row["runtime_candidate"] or row["list_legal"] is not True:
            continue
        stage = "runtime_audit_gate"
        try:
            definition = registry.resolve(row["bot_id"])
            if row.get("variant") is not None:
                definition = next(r for r in registry.inventory["origins"] if r["source_id"] == "pure" and
                                  r["class_name"] == row["runtime_executor_id"])
            _, deck = _deck_reference(registry, definition)
            profile = _profile(actor_profile, deck, plan["actor_seat"])
            audit = audits.get(row["variant"]["variant_id"] if row.get("variant") else row["source_id"])
            if not isinstance(audit, dict) or set(audit) != {"path", "sha256"}:
                raise ContractError("actual complete source assembly audit not supplied")
            adapter = registry.training_adapter(definition["bot_id"], source_id=row["runtime_source_id"],
                native_root=native_root, profile=profile, seat=1-plan["actor_seat"], versions=versions,
                environment_id="bot-current-engineering-qualification", opponent_id="qual-"+row["bot_id"][:32],
                source="engineering_fixture", build_audit_path=audit["path"], build_audit_sha256=audit["sha256"],
                mono=mono, workspace=workspace, session_seconds=seconds,
                variant_root=variant_root if row.get("variant") else None)
            stage = "managed_engine_and_loopback_start"
            started = time.monotonic(); trajectory = hashlib.sha256()
            if progress is not None:
                progress(row['bot_id'], stage, None, None)
            with adapter.managed_engine_factory(NativeNormalEngine, native_root, scenario="effect-duel",
                                                 deck_profile=profile, seed=seed) as engine:
                row.update(native_executed=True, csharp_executed=True)
                stage = "normal_game"
                if progress is not None:
                    progress(row['bot_id'], stage, True, True)
                request = engine.next_decision()
                while request is not None:
                    if row["decisions"] >= max_decisions or time.monotonic()-started >= seconds:
                        raise NativeError("bounded normal qualification ended before a terminal result")
                    bot_turn = request.observation.observer == adapter.seat
                    action = adapter.policy.choose(request) if bot_turn else choose_effect_duel_action(request, facts)
                    selection = ActionSelection(request.context.run_id, request.duel_id, request.decision_id, action.action_id)
                    validate_selection(request, selection)
                    trajectory.update(canonical_json([digest(request.to_dict()), action.action_id]).encode())
                    engine.submit(selection)
                    row["decisions"] += 1; row["bot_decisions"] += int(bot_turn)
                    request = engine.next_decision()
                if engine.outcome is None or not engine.events or engine.events[-1]["kind"] != 5:
                    raise NativeError("normal qualification lacks actual core terminal result")
                row["outcome"] = dict(engine.outcome); row["turns"] = engine.turn
            row.update(status="normal_game_verified" if row["bot_decisions"] else "terminal_without_bot_decision",
                       normal_duel_verified=bool(row["bot_decisions"]), elapsed_seconds=time.monotonic()-started,
                       trajectory_sha256=trajectory.hexdigest(), binding_sha256=digest(adapter.binding))
        except (ContractError, NativeError, OSError, ValueError, KeyError) as error:
            row.update(status="qualification_failed", failed_stage=stage, reason=str(error), normal_duel_verified=False)
            # Entering a context may fail after native creation or C# spawn;
            # without a completed entry those individual outcomes are unknown.
            if stage == "managed_engine_and_loopback_start":
                row.update(native_executed=None, csharp_executed=None)
    return _execution_result(fresh, selected, seconds,
        "C# owned-session watchdog and cooperative normal-game decision loop")


def _execution_result(fresh, selected, seconds, bound_scope):
    def execution_state(key):
        values = [r[key] for r in fresh["rows"]]
        return True if any(v is True for v in values) else None if any(v is None for v in values) else False
    fresh.update(kind="all-source-bot-engineering-qualification-results",
                 counts=dict(Counter(r["status"] for r in fresh["rows"])),
                 native_executed=execution_state("native_executed"), csharp_executed=execution_state("csharp_executed"),
                 normal_duel_verified=any(r["normal_duel_verified"] for r in fresh["rows"]),
                 normal_game_seconds=seconds, csharp_session_wall_seconds=seconds,
                 bound_scope=bound_scope,
                 all_selected_normal_verified=bool(selected) and all(r["normal_duel_verified"] for r in fresh["rows"] if r["bot_id"] in selected))
    return fresh


def _owned_worker(request, destination):
    from .agent_monitor import RunReporter
    reporter = RunReporter(Path(destination).parent)
    data = read_json(Path(request))
    registry = BotSourceRegistry(data['lock'], data['installed_root'])
    setup_seconds = time.monotonic() - reporter.started

    def progress(bot_id, stage, native_executed, csharp_executed):
        print(canonical_json(dict(bot_id=bot_id, stage=stage, native_executed=native_executed,
                                  csharp_executed=csharp_executed)), flush=True)

    result = _execute_qualification(registry, data['plan'], data['native_root'], data['actor_profile'],
                                    **data['options'], progress=progress)
    verified = next(r for r in result['rows'] if r['bot_id'] == data['options']['selected_bot_ids'][0])
    verified['resources'] = reporter.resource_snapshot(
        binding=dict(resources=result['resources'], model='none', precision=None,
                     concurrency=1, budget_seconds=data['options']['seconds'], task_scale=verified['decisions']),
        stage_seconds={'worker_load':setup_seconds, 'managed_game':verified.get('elapsed_seconds')})
    elapsed = verified.get('elapsed_seconds')
    if elapsed is not None and elapsed > 0:
        verified['resources']['metrics']['decisions_per_second'] = verified['decisions'] / elapsed
        verified['resources']['metric_sources']['decisions_per_second'] = 'recorded decisions / managed-game wall seconds'
    with Path(destination).open('x', encoding='utf-8') as output:
        output.write(canonical_json(result)+'\n')


def execute_qualification(registry, plan, native_root, actor_profile, *, audits, mono, workspace,
                          selected_bot_ids=None, seed=7, max_decisions=3000, seconds=60, variant_root=None,
                          log_directory=None, cancel_requested=None, gpu_device_index=None):
    """Each actual native game runs behind a host-owned process deadline."""
    from .agent_monitor import RunReporter, nvidia_device_sample
    from .owned_runtime import run_owned_process

    if gpu_device_index is not None:
        integer(gpu_device_index, 'qualification GPU device index', 0)
    entered = time.monotonic()
    fresh, selected = _execution_plan(registry, plan, native_root, actor_profile, audits, selected_bot_ids,
                                      seed, max_decisions, seconds, variant_root)
    root = Path(log_directory) if log_directory is not None else Path(workspace)/'.cache'/'bot-qualification'
    root.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='qualification-', dir=root)).resolve()
    reporter = RunReporter(output)
    preflight_seconds = time.monotonic() - entered
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join(p for p in (str(Path(__file__).resolve().parents[1]), env.get('PYTHONPATH')) if p)
    halt_reason = None
    for index, row in enumerate(fresh['rows']):
        row.update(native_executed=False, csharp_executed=False, decisions=0, bot_decisions=0)
        if row['bot_id'] not in selected:
            if row['runtime_candidate']:
                row['status'] = 'not_selected'
            continue
        if not row['runtime_candidate'] or row['list_legal'] is not True:
            continue
        if halt_reason:
            row['status'] = 'qualification_stopped_before_start'
            continue
        request, destination, log = (output/f'{index}-{name}' for name in ('request.json', 'result.json', 'worker.log'))
        payload = dict(lock=registry.lock, installed_root=str(registry.root), plan=plan, native_root=str(Path(native_root).resolve()),
            actor_profile=actor_profile, options=dict(audits=audits, mono=str(mono), workspace=str(Path(workspace).resolve()),
                selected_bot_ids=[row['bot_id']], seed=seed, max_decisions=max_decisions, seconds=seconds,
                variant_root=str(Path(variant_root).resolve()) if variant_root is not None else None))
        request.write_text(canonical_json(payload)+'\n', encoding='utf-8')
        try:
            receipt = run_owned_process([sys.executable, '-B', '-m', 'ygo_kito.bot_qualification', str(request), str(destination)],
                cwd=Path.cwd(), env=env, seconds=seconds, log_path=log, cancel_requested=cancel_requested)
        except subprocess.TimeoutExpired:
            row.update(status='qualification_failed', failed_stage='worker_reap', worker_log=str(log),
                       native_executed=None, csharp_executed=None, normal_duel_verified=False)
            halt_reason = 'worker_reap_failed'
            continue
        row.update(worker=receipt, worker_log=str(log))
        reason = receipt['stop_reason']
        if reason == 'completed' and destination.is_file():
            child = read_json(destination)
            if child['source_lock_sha256'] != fresh['source_lock_sha256'] or child['inventory_sha256'] != fresh['inventory_sha256']:
                raise ContractError('qualification worker result lost its source binding')
            actual = next(r for r in child['rows'] if r['bot_id'] == row['bot_id'])
            row.update(actual)
        else:
            started = None if receipt['process_started'] else False
            row.update(status='qualification_cancelled' if reason == 'user_pause' else 'qualification_failed',
                failed_stage='owned_native_worker', reason=reason if reason != 'completed' else 'worker_result_missing',
                native_executed=started, csharp_executed=started, normal_duel_verified=False)
        if reason == 'user_pause':
            halt_reason = reason
        elif reason == 'timeout' and receipt.get('process_tree_terminated') is False:
            halt_reason = 'worker_descendants_unverified'
    jobs_seconds = time.monotonic() - reporter.started
    paused = cancel_requested is not None and cancel_requested()
    gpu_sampler = (lambda: nvidia_device_sample(gpu_device_index)) if (
        gpu_device_index is not None and halt_reason is None and not paused) else None
    telemetry_started = time.monotonic()
    fresh['host_resources'] = reporter.resource_snapshot(
        binding=dict(resources=fresh['resources'], actor_profile_sha256=fresh['actor_profile_sha256'],
                     process_role='qualification_host', model='none', precision=None, concurrency=1,
                     gpu_device_index=gpu_device_index, gpu_sample_stage='after_qualification_jobs',
                     budget_seconds=seconds, budget_scope='per_native_worker', task_scale=dict(selected_bots=len(selected))),
        stage_seconds=dict(preflight=preflight_seconds, qualification_jobs=jobs_seconds), gpu_sampler=gpu_sampler)
    fresh['host_resources']['stage_seconds'].update(telemetry=time.monotonic() - telemetry_started,
                                                  end_to_end=time.monotonic() - entered)
    fresh.update(native_worker_log_directory=str(output), native_worker_wall_seconds=seconds,
                 cancelled=halt_reason == 'user_pause', stop_reason=halt_reason)
    return _execution_result(fresh, selected, seconds, 'host-owned native worker deadline plus separate C# session watchdog')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('owned qualification worker requires its request and result files')
    _owned_worker(sys.argv[1], sys.argv[2])
