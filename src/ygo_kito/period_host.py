"""Trusted repository descriptor to actual period-aware training inputs.

There is no RPC path selection, default roster, generated training data, or
provider fallback. Loading reads/validates resources and creates visible rule
policy objects; it does not create a native duel or start a worker.
"""

from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
import hashlib
from pathlib import Path

from .build_contracts import digest
from .deck_intake import PERIODS, SLOTS, validate_intake
from .opponent_pool import SNAPSHOT_DRIVER
from .period_runtime import PeriodBuildAssets, _sha256
from .training_input import LoadedTrainingInputs, compile_training_inputs, load_training_inputs, validate_policy
from .validation import ContractError, fields, integer, member, read_json, text

ROOT = Path(__file__).resolve().parents[2]
_OPERATION = ContextVar("period_host_operation", default=None)


def assert_period_hosts_unchanged():
    """Recheck the active operation immediately before publishing a result."""
    for entry in (_OPERATION.get() or {}).values():
        entry.assert_unchanged()


@contextmanager
def period_host_operation():
    """Reuse fully loaded hosts only inside one synchronous host operation.

    Every hit and successful exit rehashes source bytes and checks memory seals.
    There is no persisted, process-wide or stat-based resource cache.
    """
    if _OPERATION.get() is not None:
        yield
        return
    entries = {}
    token = _OPERATION.set(entries)
    try:
        yield
        assert_period_hosts_unchanged()
    finally:
        _OPERATION.reset(token)


def host_operation(function):
    @wraps(function)
    def run(*args, **kwargs):
        with period_host_operation():
            return function(*args, **kwargs)
    return run


def _source_snapshot(workspace, references):
    result = []
    for reference in sorted(set(references)):
        original = workspace / reference
        resolved = _inside(workspace, reference)
        try:
            checksum = hashlib.sha256(original.read_bytes()).hexdigest()
        except OSError as error:
            raise ContractError("period host source cannot be read") from error
        result.append((str(original), str(resolved), checksum))
    return tuple(result)


@dataclass(frozen=True)
class _OperationHost:
    host: "PeriodHost"
    workspace: Path
    sources: tuple
    manifest_sha256: str
    descriptor_sha256: str
    period_id: str
    runtime_seals: tuple

    def assert_unchanged(self):
        for original, resolved, checksum in self.sources:
            path = Path(original)
            if (path.resolve() != Path(resolved) or not path.resolve().is_relative_to(self.workspace)):
                raise ContractError("period host source path changed during operation")
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as error:
                raise ContractError("period host source cannot be read during operation") from error
            if actual != checksum:
                raise ContractError("period host source bytes changed during operation")
        host = self.host
        host.loaded._check_manifest()
        if (host.loaded.manifest["binding_sha256"] != self.manifest_sha256 or
                host.descriptor_sha256 != self.descriptor_sha256 or host.period_id != self.period_id or
                set(host.loaded.assets) != {row[0] for row in self.runtime_seals}):
            raise ContractError("period host memory binding changed during operation")
        for period, identity, root, workspace, receipt in self.runtime_seals:
            assets = host.loaded.assets[period]
            if (id(assets) != identity or str(assets.root) != root or str(assets.workspace) != workspace or
                    digest(assets.receipt) != receipt):
                raise ContractError("period host runtime binding changed during operation")
            assets.assert_integrity(physical=False)


def _inside(workspace, value):
    text(value, "host period path")
    path = (workspace / value).resolve()
    if not path.is_relative_to(workspace):
        raise ContractError("host period paths must stay inside the workspace")
    return path


def _bot_specs(descriptor, workspace, selected_periods):
    """Host-selected fixed builds, never RPC/provider path selection."""
    bots = fields(descriptor.get("bots", {}), set(), set(PERIODS))
    references = []
    for period in selected_periods:
        assignments = fields(bots.get(period, {}), set(), set(SLOTS[3:]))
        for spec in assignments.values():
            fields(spec, {"source_id", "executor_id", "installed_root", "build_audit", "mono"}, {"variant_root"})
            member(spec["source_id"], "desktop WindBot source", ("ice", "pure"))
            text(spec["executor_id"], "exact pinned WindBot Executor identity")
            installed = _inside(workspace, spec["installed_root"])
            audit = fields(spec["build_audit"], {"path", "sha256"})
            _inside(workspace, audit["path"])
            _sha256(audit["sha256"], "full WindBot build audit")
            text(spec["mono"], "explicit host Mono executable")
            if not Path(spec["mono"]).is_absolute():
                raise ContractError("host Mono executable requires an explicit absolute path")
            references.extend([audit["path"], str(installed / "bot-deployment-manifest.json")])
            if "variant_root" in spec:
                if spec["source_id"] != "pure":
                    raise ContractError("exact desktop overlay requires its full Pure base")
                variant = _inside(workspace, spec["variant_root"])
                from .bot_overlay import MANIFEST
                references.append(str(variant / MANIFEST))
    if any(bots.get(p) for p in selected_periods):
        references.append("configs/bot-sources-v1.json")
    return bots, references


@dataclass(frozen=True)
class PeriodHost:
    loaded: LoadedTrainingInputs
    period_id: str
    descriptor_sha256: str

    @property
    def assets(self):
        return self.loaded.assets[self.period_id]

    def for_runner(self, purpose, episode_cursor=0):
        return self.loaded.for_runner(self.period_id, purpose, episode_cursor=episode_cursor)

    def require_task(self, task):
        return self.loaded.require_task(self.period_id, task)

    def opponent_for(self, binding, profile):
        return self.assets.opponent_for(binding, profile)

    def rebind_actor(self, binding, deck, purpose=None):
        return self.assets.rebind_rule_opponent(binding, deck, purpose=purpose)


def load_period_host(recipe, *, workspace=ROOT):
    """Optional group hook: return None only when the option is truly absent."""
    if not isinstance(recipe, dict):
        raise ContractError("typed group recipe object required")
    if "period_inputs" not in recipe:
        return None
    workspace = Path(workspace).resolve()
    reference = recipe["period_inputs"]
    if not isinstance(reference, str) or not reference.startswith("configs/") or not reference.endswith(".json"):
        raise ContractError("period input descriptor must be a repository configs JSON path")
    entries = _OPERATION.get()
    operation_key = (str(workspace), reference)
    if entries is not None and operation_key in entries:
        entry = entries[operation_key]
        entry.assert_unchanged()
        return entry.host
    path = _inside(workspace, reference)
    if not path.is_relative_to(workspace / "configs"):
        raise ContractError("period input descriptor must stay in repository configs")
    descriptor_sources = _source_snapshot(workspace, [reference])
    descriptor = fields(read_json(path), {"schema_version", "intake", "policy", "period_id", "native_roots"}, {"snapshots", "scope", "bots"})
    integer(descriptor["schema_version"], "period host schema", 1, 1)
    member(descriptor["period_id"], "selected training period", PERIODS)
    scope = descriptor.get("scope", "whole-plan")
    member(scope, "period host loading scope", ("whole-plan", "selected-period"))
    selected_period = descriptor["period_id"] if scope == "selected-period" else None
    selected_periods = (selected_period,) if selected_period is not None else PERIODS
    roots = fields(descriptor["native_roots"], set(selected_periods), set(PERIODS) - set(selected_periods))
    # Resolve every host path before reading any model/data/resource content.
    intake_path, policy_path = (_inside(workspace, descriptor[key]) for key in ("intake", "policy"))
    native_roots = {p: _inside(workspace, roots[p]) for p in selected_periods}
    if intake_path.suffix != ".json" or policy_path.suffix != ".json":
        raise ContractError("period intake and policy must be explicit JSON files")
    input_sources = _source_snapshot(workspace, [descriptor["intake"], descriptor["policy"]])
    intake = validate_intake(read_json(intake_path))
    policy = validate_policy(read_json(policy_path), selected_period=selected_period)
    bots, references = _bot_specs(descriptor, workspace, selected_periods)
    snapshots = fields(descriptor.get("snapshots", {}), set(), set(PERIODS))
    for period in selected_periods:
        assignments = snapshots.get(period, {})
        for slot_id, snapshot in fields(assignments, set(), set(SLOTS[3:])).items():
            fields(snapshot, {"path", "sha256", "model_source", "migration"})
            _inside(workspace, snapshot["path"])
            _sha256(snapshot["sha256"], "host snapshot artifact")
            text(snapshot["model_source"], "host snapshot model source")
            member(snapshot["migration"], "host snapshot inference migration", ("same-period-inference", "explicit-inference-migration"))
            references.append(snapshot["path"])
    for period in selected_periods:
        environment = intake["environments"][period]
        references.extend(artifact["path"] for artifact in (environment[key] for key in ("catalog", "releases", "banlist"))
                          if artifact is not None)
    sources = (*descriptor_sources, *input_sources, *_source_snapshot(workspace, references))
    compiled = compile_training_inputs(intake, policy, workspace, selected_period=selected_period)
    if compiled["status"] != "compiled_not_runtime_validated":
        raise ContractError("period host input data is incomplete; no runtime or default roster was created")
    source = "engineering_fixture" if policy["source"] == "synthetic_contract_test" else "user_supplied"
    assets = {p: PeriodBuildAssets(native_roots[p], p, intake["environments"][p], workspace,
                adapter_revision=policy["periods"][p]["adapter_revision"], evidence_source=source) for p in selected_periods}
    slots = {s["slot_id"]: s for s in intake["slots"]}
    used_snapshots, used_bots = set(), set()
    bot_registries = {}
    for period in selected_periods:
        for purpose, partition in policy["periods"][period]["partitions"].items():
            profiles = compiled["periods"][period]["partitions"][purpose]["profiles"]
            for entry, profile in zip(partition["opponents"], profiles):
                controller = slots[entry["slot_id"]]["controller"]
                expected = entry["binding"]
                if controller["controller"] == "rule_baseline":
                    actual = assets[period].bind_rule_opponent(profile, expected["opponent_id"],
                        driver_version=controller["driver_version"], source=expected["source"])
                elif controller["controller"] == "local_snapshot" and controller["driver_version"] == SNAPSHOT_DRIVER:
                    snapshot = snapshots.get(period, {}).get(entry["slot_id"])
                    if snapshot is None:
                        raise ContractError("period local snapshot requires its explicit host artifact/source/migration")
                    used_snapshots.add((period, entry["slot_id"]))
                    actual = assets[period].bind_snapshot_opponent(profile, expected["opponent_id"], _inside(workspace, snapshot["path"]),
                        snapshot["sha256"], controller["model"], model_source=snapshot["model_source"], migration=snapshot["migration"],
                        source=expected["source"])
                elif controller["controller"] == "bot":
                    from .bot_deployment import BotSourceRegistry
                    spec = bots.get(period, {}).get(entry["slot_id"])
                    if spec is None:
                        raise ContractError("period WindBot requires its explicit fixed source and full-build audit")
                    if controller["model"] != spec["executor_id"]:
                        raise ContractError("period bot slot must name the same exact pinned Executor")
                    installed = _inside(workspace, spec["installed_root"])
                    key = str(installed)
                    if key not in bot_registries:
                        bot_registries[key] = BotSourceRegistry(read_json(_inside(workspace, "configs/bot-sources-v1.json")), installed)
                    actual = assets[period].bind_bot_opponent(profile, expected["opponent_id"], bot_registries[key],
                        executor_id=spec["executor_id"], source_id=spec["source_id"],
                        build_audit_path=_inside(workspace, spec["build_audit"]["path"]),
                        build_audit_sha256=spec["build_audit"]["sha256"], mono=spec["mono"], source=expected["source"],
                        variant_root=_inside(workspace, spec["variant_root"]) if "variant_root" in spec else None)
                    used_bots.add((period, entry["slot_id"]))
                else:
                    raise ContractError("period bot/external provider requires an implemented legal-action transport")
                if actual.binding != expected:
                    kind = {"rule_baseline": "rule", "local_snapshot": "snapshot", "bot": "bot"}[controller["controller"]]
                    raise ContractError("period host actual " + kind + " driver binding differs from the frozen input evidence")
    if used_snapshots != {(p, slot) for p in selected_periods for slot in snapshots.get(p, {})}:
        raise ContractError("period host snapshot artifacts must correspond exactly to configured local snapshot slots")
    if used_bots != {(p, slot) for p in selected_periods for slot in bots.get(p, {})}:
        raise ContractError("period host bot artifacts must correspond exactly to configured bot slots")
    loaded = load_training_inputs(intake, policy, workspace, runtime_assets=assets, selected_period=selected_period)
    host = PeriodHost(loaded, descriptor["period_id"], digest(deepcopy(descriptor)))
    entry = _OperationHost(host, workspace, sources, loaded.manifest["binding_sha256"], host.descriptor_sha256, host.period_id,
        tuple((p, id(a), str(a.root), str(a.workspace), digest(a.receipt)) for p, a in sorted(assets.items())))
    entry.assert_unchanged()
    if entries is not None:
        entries[operation_key] = entry
    return host
