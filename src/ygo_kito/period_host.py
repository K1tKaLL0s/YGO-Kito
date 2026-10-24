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
from .deck_intake import PERIODS, validate_intake
from .period_runtime import PeriodBuildAssets
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
                set(host.loaded.assets) != set(PERIODS)):
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
    descriptor = fields(read_json(path), {"schema_version", "intake", "policy", "period_id", "native_roots"})
    integer(descriptor["schema_version"], "period host schema", 1, 1)
    member(descriptor["period_id"], "selected training period", PERIODS)
    roots = fields(descriptor["native_roots"], set(PERIODS))
    # Resolve every host path before reading any model/data/resource content.
    intake_path, policy_path = (_inside(workspace, descriptor[key]) for key in ("intake", "policy"))
    native_roots = {p: _inside(workspace, value) for p, value in roots.items()}
    if intake_path.suffix != ".json" or policy_path.suffix != ".json":
        raise ContractError("period intake and policy must be explicit JSON files")
    input_sources = _source_snapshot(workspace, [descriptor["intake"], descriptor["policy"]])
    intake = validate_intake(read_json(intake_path))
    policy = validate_policy(read_json(policy_path))
    references = []
    for environment in intake["environments"].values():
        references.extend(artifact["path"] for artifact in (environment[key] for key in ("catalog", "releases", "banlist"))
                          if artifact is not None)
    sources = (*descriptor_sources, *input_sources, *_source_snapshot(workspace, references))
    compiled = compile_training_inputs(intake, policy, workspace)
    if compiled["status"] != "compiled_not_runtime_validated":
        raise ContractError("period host input data is incomplete; no runtime or default roster was created")
    source = "engineering_fixture" if policy["source"] == "synthetic_contract_test" else "user_supplied"
    assets = {p: PeriodBuildAssets(native_roots[p], p, intake["environments"][p], workspace,
                adapter_revision=policy["periods"][p]["adapter_revision"], evidence_source=source) for p in PERIODS}
    slots = {s["slot_id"]: s for s in intake["slots"]}
    for period in PERIODS:
        for purpose, partition in policy["periods"][period]["partitions"].items():
            profiles = compiled["periods"][period]["partitions"][purpose]["profiles"]
            for entry, profile in zip(partition["opponents"], profiles):
                controller = slots[entry["slot_id"]]["controller"]
                if controller["controller"] != "rule_baseline":
                    raise ContractError("period host needs an implemented driver; external/bot/snapshot input is not a rule baseline")
                expected = entry["binding"]
                actual = assets[period].bind_rule_opponent(profile, expected["opponent_id"],
                    driver_version=controller["driver_version"], source=expected["source"])
                if actual.binding != expected:
                    raise ContractError("period host actual rule driver binding differs from the frozen input evidence")
    loaded = load_training_inputs(intake, policy, workspace, runtime_assets=assets)
    host = PeriodHost(loaded, descriptor["period_id"], digest(deepcopy(descriptor)))
    entry = _OperationHost(host, workspace, sources, loaded.manifest["binding_sha256"], host.descriptor_sha256, host.period_id,
        tuple((p, id(a), str(a.root), str(a.workspace), digest(a.receipt)) for p, a in sorted(assets.items())))
    entry.assert_unchanged()
    if entries is not None:
        entries[operation_key] = entry
    return host
