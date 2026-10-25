"""Explicitly enabled, bounded local CPU worker control; no cloud operations.

SQLite is authoritative. Each worker has a kernel wall timer, frozen recipe,
independent process and complete-episode checkpoints. Pausing exits the worker;
resuming loads the verified checkpoint in a new process.
"""

from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
from uuid import uuid4

from .agent_registry import identifier
from .build_contracts import digest
from .validation import ContractError, canonical_json, fields, integer, read_json

APPLICATION_ID = 0x59474C43
ROOT = Path(__file__).resolve().parents[2]


def process_stamp(pid):
    try:
        raw = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if raw[0] == "Z" else raw[19]
    except (OSError, IndexError):
        return None


def alive(row):
    return row.get("pid") is not None and row.get("pid_stamp") is not None and process_stamp(row["pid"]) == row["pid_stamp"]


def _connect(state_root, *, create=False, read_only=False):
    path = Path(state_root).resolve() / "local-control.sqlite3"
    if path.is_symlink():
        raise ContractError("local control database symlinks unsupported")
    if not path.exists():
        if not create:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                raise ContractError("refusing foreign control database")
            db.execute("CREATE TABLE runs(id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute("PRAGMA user_version=1")
    db = sqlite3.connect(path.as_uri() + ("?mode=ro" if read_only else "?mode=rw"), uri=True, timeout=10)
    if db.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID or db.execute("PRAGMA user_version").fetchone()[0] != 1:
        db.close()
        raise ContractError("foreign/incompatible local CPU control database")
    return db


def get_row(db, run_id):
    identifier(run_id)
    value = db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
    if value is None:
        raise ContractError("local CPU run was not prepared by this host")
    return json.loads(value[0])


def put_row(db, row):
    db.execute("UPDATE runs SET payload=? WHERE id=?", (canonical_json(row), row["run_id"]))


def elapsed(row):
    extra = 0.
    if row.get("segment_started") is not None:
        extra = max(0., time.monotonic() - row["segment_started"])
        extra = min(extra, max(0., row["wall_limit_seconds"] - row["active_seconds"]))
    return row["active_seconds"] + extra


def snapshot_for(row):
    active = elapsed(row)
    metrics = dict(row["metrics"], elapsed_seconds=active, time_limit_seconds=row["wall_limit_seconds"],
                   budget_seconds_remaining=max(0., row["wall_limit_seconds"] - active),
                   discarded_episodes=row["discarded_episodes"], recovery_count=row["recovery_count"])
    state = row["state"]
    if state == "running" and row.get("pid") and not alive(row):
        state = "stopped" if active >= row["wall_limit_seconds"] else "failed"
    return {"schema_version": 1, "run_id": row["run_id"], "state": state, "revision": row["revision"],
            "model_versions": row.get("model_versions", {"duel": "bounded-local-cpu-prototype-v1"}), "metrics": metrics,
            "checkpoint_ids": row["checkpoint_ids"], "source": "trainer"}


def local_snapshot(state_root, run_id):
    db = _connect(state_root, read_only=True)
    if db is None:
        return None
    with closing(db):
        value = db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
    return None if value is None else snapshot_for(json.loads(value[0]))


def run_path(state_root, run_id):
    from .agent_monitor import RunMonitor
    return RunMonitor(state_root)._path(run_id, "")


def checkpoint_receipt(run_id, path, step):
    return {"schema_version": 1, "run_id": run_id, "checkpoint_id": path.stem,
            "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "artifact_bytes": path.stat().st_size, "step": step}


def write_checkpoint(trainer, state_root, row, *, checkpoint_id=None):
    from .cpu_training import save_checkpoint
    checkpoint_id = checkpoint_id or f"local-step-{trainer.updates}"
    directory = run_path(state_root, row["run_id"]) / "checkpoints"
    staged = directory / ("staging-" + uuid4().hex)
    if row.get("recipe", {}).get("workflow") == "four-model-alternating-v1":
        staged.mkdir(parents=True)
        path = staged / (checkpoint_id + ".weights")
        trainer.save_to(path)
    else:
        path = save_checkpoint(trainer, staged, checkpoint_id, row["binding"], allow_initial=True)
    receipt = checkpoint_receipt(row["run_id"], path, trainer.updates)
    target = directory / path.name
    if target.exists() or target.with_suffix(".json").exists():
        raise ContractError("checkpoint destination exists; inspect orphan evidence before retry")
    path.replace(target)
    with target.with_suffix(".json").open("x") as output:
        output.write(canonical_json(receipt) + "\n")
        output.flush()
        os.fsync(output.fileno())
    staged.rmdir()
    return receipt


def verified_trainer(state_root, row):
    if row.get("recipe", {}).get("workflow") == "four-model-alternating-v1":
        from .group_runner import verified
        return verified(state_root, row)
    from .agent_monitor import RunMonitor
    from .cpu_training import load_checkpoint, resource_binding
    from .training_runner import binding_for
    if binding_for(Path(row["native_root"]), row) != row["binding"]:
        raise ContractError("local CPU recipe implementation/resources changed")
    latest = row["checkpoint_ids"][-1]
    receipt = RunMonitor(state_root).checkpoint(row["run_id"], latest)
    trainer = load_checkpoint(run_path(state_root, row["run_id"]) / "checkpoints" / (latest + ".weights"),
                              row["binding"], allow_initial=True)
    if trainer.updates != receipt["step"] or asdict(trainer.config) != row["config"]:
        # JSON normalizes tuples in the recipe; compare canonical wire values.
        if trainer.updates != receipt["step"] or digest(asdict(trainer.config)) != digest(row["config"]):
            raise ContractError("local checkpoint step/configuration differs")
    if "recipe" in row:
        from .training_runner import verify_committed
        verify_committed(state_root, row, trainer)
    return trainer


class LocalCpuBackend:
    def __init__(self, state_root, native_root, *, recipe=None):
        self.state_root, self.native_root = Path(state_root).resolve(), Path(native_root).resolve()
        from .training_runner import validate_recipe
        self.recipe = validate_recipe(recipe) if recipe is not None else None
        self.children = {}

    def details(self, run_id):
        db = _connect(self.state_root)
        if db is None:
            raise ContractError("local CPU backend has no prepared jobs")
        with closing(db):
            return get_row(db, run_id)

    def prepare(self, run_id, *, wall_limit_seconds=None):
        identifier(run_id)
        cap = self.recipe["wall_seconds"] if self.recipe is not None else 60.
        wall_limit_seconds = cap if wall_limit_seconds is None else wall_limit_seconds
        if type(wall_limit_seconds) not in (int, float) or not 1 <= wall_limit_seconds <= cap:
            raise ContractError("local CPU wall budget exceeds the trusted host configuration")
        if self.recipe is not None and self.recipe.get("workflow") == "four-model-alternating-v1":
            from .group_runner import prepare
            return prepare(self, run_id, wall_limit_seconds)
        started = time.monotonic()
        setup_cpu = time.process_time()
        from .build_pipeline import BuildAssets
        from .cpu_training import CpuTrainer, CpuTrainingConfig, resource_binding
        from .agent_monitor import RunReporter
        assets = BuildAssets(self.native_root)
        directory = run_path(self.state_root, run_id)
        if directory.exists():
            raise ContractError("run directory exists; no overwrite")
        db = _connect(self.state_root, create=True)
        with closing(db), db:
            if db.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone():
                raise ContractError("local run identity already prepared")
        profile = read_json(ROOT / "configs/effect-duel-v1.json")
        cfg = CpuTrainingConfig()
        profiles = None
        if self.recipe is not None:
            from .training_runner import recipe_inputs
            profiles, cfg = recipe_inputs(self.recipe)
            profile = profiles["train"]
        trainer = CpuTrainer(cfg, sorted(c for c in assets.rows if 0 < c < 2**32))
        row = {"schema_version": 1, "run_id": run_id, "native_root": str(self.native_root), "profile": profile,
               "config": json.loads(canonical_json(asdict(trainer.config))), "binding": resource_binding(self.native_root, profile),
               "wall_limit_seconds": float(wall_limit_seconds), "active_seconds": 0., "segment_started": None,
               "state": "created", "desired": "created", "phase": "prepared", "revision": 0,
               "pid": None, "pid_stamp": None, "generation": None, "checkpoint_ids": [],
               "metrics": {"steps": 0, "episodes": 0}, "updates": [], "history": [],
               "discarded_episodes": 0, "recovery_count": 0, "reason": "prepared_real_initial_weights_not_a_training_update"}
        if self.recipe is not None:
            from .training_runner import binding_for
            from .training_plan import validate_plan
            from .duel_model import parameter_digest
            row.update(recipe=self.recipe, validation_profile=profiles["validation"], rounds=[], validations=[],
                       scheduled_checkpoint_ids=[], usage_outbox=[],
                       initial_model_sha256=parameter_digest(trainer.model),
                       budget_plan=validate_plan(read_json(ROOT / "configs/training-plan-v1.json")))
            row["binding"] = binding_for(self.native_root, row)
        receipt = write_checkpoint(trainer, self.state_root, row)
        row["checkpoint_ids"] = [receipt["checkpoint_id"]]
        row["active_seconds"] = time.monotonic() - started
        row["completed_worker_cpu_seconds"] = 0.
        row["metrics"]["setup_process_cpu_seconds"] = time.process_time() - setup_cpu
        row["metrics"]["unmeasured_worker_segments"] = 0
        if self.recipe is not None:
            row["usage_outbox"].append({"payload": {"event_id": "setup-" + digest(run_id)[:40],
                "stage_id": "throughput-small-train", "gpu_count": 0, "wall_seconds": max(.001, row["active_seconds"]),
                "activity": "setup", "outcome": "completed", "amount": None, "currency": None},
                "measurement": "measured_host_setup", "exported": False})
        row["history"].append({"event": "prepared", "checkpoint_id": receipt["checkpoint_id"], "optimizer_steps": 0})
        RunReporter(self.state_root).publish(snapshot_for(row))
        with closing(_connect(self.state_root)) as db, db:
            db.execute("INSERT INTO runs VALUES(?,?)", (run_id, canonical_json(row)))
        if self.recipe is not None:
            from .training_runner import sync_usage
            sync_usage(self.state_root, run_id)
        return self.status(run_id)

    def status(self, run_id):
        self.refresh(run_id)
        return snapshot_for(self.details(run_id))

    def refresh(self, run_id):
        child = self.children.get(run_id)
        if child is not None:
            child.poll()
        with closing(_connect(self.state_root)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = get_row(db, run_id)
            if row["state"] == "running" and row.get("pid") and not alive(row):
                if "recipe" in row:
                    from .training_runner import settle_usage
                    settle_usage(row, "uncertain", "observed_elapsed_upper_bound_after_worker_loss")
                else:
                    row["active_seconds"] = elapsed(row)
                    row["segment_started"] = None
                row["state"] = "stopped" if row["active_seconds"] >= row["wall_limit_seconds"] else "failed"
                row["reason"] = "kernel_wall_budget_exhausted" if row["state"] == "stopped" else "worker_lost_inspect_checkpoint"
                row["usage_source"] = "observed_elapsed_upper_bound_after_worker_loss"
                row["metrics"]["unmeasured_worker_segments"] += 1
                row["discarded_episodes"] += int(row["phase"] in ("sampling", "updating", "saving", "validating"))
                row["phase"] = "exited"
                row["revision"] += 1
                put_row(db, row)
        if "recipe" in row:
            from .training_runner import sync_usage
            sync_usage(self.state_root, run_id)
            row = self.details(run_id)
        return row

    def _signal_owned(self, row, sig):
        if not alive(row):
            return
        argv = Path(f"/proc/{row['pid']}/cmdline").read_bytes().split(b"\0")
        required = [b"ygo_kito.local_training", str(self.state_root).encode(), row["run_id"].encode(), row["generation"].encode()]
        if not all(arg in argv for arg in required):
            raise ContractError("worker identity changed; refusing process signal")
        os.kill(row["pid"], sig)

    def _launch(self, run_id, expected_revision):
        row = self.details(run_id)
        verified_trainer(self.state_root, row)  # Fail before a process is created.
        with closing(_connect(self.state_root)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = get_row(db, run_id)
            if row["revision"] != expected_revision or alive(row):
                raise ContractError("local worker revision/lease changed")
            for payload, in db.execute("SELECT payload FROM runs"):
                if alive(json.loads(payload)):
                    raise ContractError("one live local CPU worker budget reached")
            if elapsed(row) >= row["wall_limit_seconds"]:
                raise ContractError("local active wall budget exhausted; no worker launched")
            row.update(state="running", desired="running", phase="launching", generation=uuid4().hex,
                       segment_started=time.monotonic(), revision=row["revision"] + 1)
            args = [sys.executable, "-m", "ygo_kito.local_training", "--state-root", str(self.state_root),
                    "--run-id", run_id, "--generation", row["generation"]]
            logfile = run_path(self.state_root, run_id) / ("worker-" + row["generation"] + ".log")
            with logfile.open("x") as log:
                child = subprocess.Popen(args, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                         start_new_session=True, close_fds=True)
            row["pid"], row["pid_stamp"] = child.pid, process_stamp(child.pid)
            if row["pid_stamp"] is None:
                raise ContractError("worker exited during launch; inspect state before retry")
            row["history"].append({"event": "worker_started", "generation": row["generation"],
                                   "from_checkpoint": row["checkpoint_ids"][-1]})
            put_row(db, row)
            self.children[run_id] = child
        return row

    def validate_control(self, run_id, operation, expected_revision):
        """Known precondition failures reject before reserving an execution ID."""
        row = self.details(run_id)
        if row["revision"] != expected_revision:
            raise ContractError("local control revision changed")
        if operation in ("start", "resume") or (operation == "save_checkpoint" and row["state"] == "paused"):
            verified_trainer(self.state_root, row)
        if operation in ("start", "resume") and elapsed(row) >= row["wall_limit_seconds"]:
            raise ContractError("local wall budget exhausted; no worker launched")

    def control(self, *, run_id, operation, expected_revision, request_id):
        identifier(request_id)
        integer(expected_revision, "expected revision")
        row = self.refresh(run_id)
        if row["revision"] != expected_revision:
            raise ContractError("local control revision changed; inspect actual state")
        valid = {"start": {"created"}, "resume": {"paused"}, "pause": {"running"},
                 "stop": {"created", "running", "paused"}, "save_checkpoint": {"running", "paused"}}
        if operation not in valid or row["state"] not in valid[operation]:
            raise ContractError("local CPU operation invalid for current state")
        if operation in ("start", "resume"):
            row = self._launch(run_id, expected_revision)
        elif operation == "save_checkpoint" and row["state"] == "paused":
            trainer = verified_trainer(self.state_root, row)
            receipt = write_checkpoint(trainer, self.state_root, row, checkpoint_id="manual-" + uuid4().hex[:16])
            with closing(_connect(self.state_root)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                current = get_row(db, run_id)
                if current["revision"] != expected_revision or alive(current):
                    raise ContractError("checkpoint request state changed; inspect saved artifact")
                current["checkpoint_ids"].append(receipt["checkpoint_id"])
                current["revision"] += 1
                current["history"].append({"event": "manual_checkpoint_saved", "checkpoint_id": receipt["checkpoint_id"]})
                put_row(db, current)
                row = current
        else:
            old_checkpoints = len(row["checkpoint_ids"])
            with closing(_connect(self.state_root)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                row = get_row(db, run_id)
                if row["revision"] != expected_revision:
                    raise ContractError("local request revision changed")
                if operation in ("pause", "stop"):
                    row["desired"] = "paused" if operation == "pause" else "stopped"
                    if not alive(row):
                        row["state"], row["phase"] = ("failed" if "recipe" in row and operation == "pause" else row["desired"]), "exited"
                row["revision"] += 1
                row["history"].append({"event": "control_requested", "operation": operation, "request_id": request_id})
                put_row(db, row)
            deadline = time.monotonic() + 15
            while True:
                row = self.refresh(run_id)
                if operation == "save_checkpoint":
                    done = len(row["checkpoint_ids"]) > old_checkpoints
                else:
                    done = row["state"] != "running" and not alive(row)
                if done:
                    break
                if time.monotonic() >= deadline:
                    if operation == "save_checkpoint":
                        raise ContractError("checkpoint outcome pending; read status before retry")
                    self._signal_owned(row, signal.SIGTERM)
                    for _ in range(20):
                        if not alive(row):
                            break
                        time.sleep(.05)
                    if alive(row):
                        self._signal_owned(row, signal.SIGKILL)
                        for _ in range(20):
                            if not alive(row):
                                break
                            time.sleep(.05)
                    if alive(row):
                        raise ContractError("managed worker exit uncertain; inspect before retry")
                    self.refresh(run_id)
                    with closing(_connect(self.state_root)) as db, db:
                        db.execute("BEGIN IMMEDIATE")
                        row = get_row(db, run_id)
                        row["active_seconds"], row["segment_started"] = elapsed(row), None
                        row["state"], row["phase"] = ("failed" if "recipe" in row and operation == "pause" else row["desired"]), "exited"
                        row["reason"] = ("pause_forced_recovery_required" if "recipe" in row and operation == "pause"
                                         else operation + "_forced_to_last_committed_checkpoint")
                        row["revision"] += 1
                        put_row(db, row)
                    break
                time.sleep(.05)
        return {"applied": True, "revision": row["revision"], "checkpoint_id": row["checkpoint_ids"][-1],
                "state": snapshot_for(row)["state"], "scope": "managed-local-cpu",
                "local_process_exited": not alive(row), "cloud_billing_stopped": False}

    def recover(self, run_id, expected_revision):
        previous = self.details(run_id)
        if previous["revision"] != expected_revision:
            raise ContractError("recovery revision changed; inspect the local run")
        row = self.refresh(run_id)
        if row["state"] != "failed" or alive(row):
            raise ContractError("recovery requires the inspected failed local run and no live worker")
        expected_revision = row["revision"]
        trainer = verified_trainer(self.state_root, row)
        round_reconciliation = None
        if "recipe" in row:
            if row["recipe"].get("workflow") == "four-model-alternating-v1":
                from .group_runner import reconcile
                round_reconciliation = reconcile(self.state_root, row, trainer)
            else:
                from .training_runner import reconcile_round
                round_reconciliation = reconcile_round(self.state_root, row, trainer)
        next_file = run_path(self.state_root, run_id) / "checkpoints" / f"local-step-{trainer.updates + 1}.weights"
        reconciliation = None
        if "recipe" not in row and next_file.exists():
            manifest = next_file.with_suffix(".json")
            if manifest.exists():
                receipt = fields(read_json(manifest), {"schema_version", "run_id", "checkpoint_id", "artifact_sha256", "artifact_bytes", "step"})
                if receipt != checkpoint_receipt(run_id, next_file, trainer.updates + 1):
                    raise ContractError("unregistered complete checkpoint integrity mismatch")
                from .cpu_training import load_checkpoint
                recovered = load_checkpoint(next_file, row["binding"])
                if recovered.updates != trainer.updates + 1 or digest(asdict(recovered.config)) != digest(row["config"]):
                    raise ContractError("unregistered checkpoint recipe differs")
                reconciliation = {"event": "adopted_verified_checkpoint_after_publication_crash",
                                  "checkpoint_id": receipt["checkpoint_id"], "step": recovered.updates}
            else:
                quarantine = next_file.parent / "quarantine"
                quarantine.mkdir(exist_ok=True)
                destination = quarantine / (next_file.name + "-" + uuid4().hex)
                next_file.replace(destination)
                reconciliation = {"event": "unpublished_checkpoint_quarantined", "artifact": destination.name}
        with closing(_connect(self.state_root)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = get_row(db, run_id)
            if row["revision"] != expected_revision or alive(row):
                raise ContractError("recovery state changed")
            row.update(state="paused", desired="paused", phase="recovered", revision=row["revision"] + 1,
                       recovery_count=row["recovery_count"] + 1)
            if reconciliation is not None:
                row["history"].append(reconciliation)
                if "checkpoint_id" in reconciliation:
                    row["checkpoint_ids"].append(reconciliation["checkpoint_id"])
                    row["metrics"].update(steps=reconciliation["step"], episodes=reconciliation["step"])
                    row["metrics"].pop("loss", None)  # Unlogged loss is unknown.
            if round_reconciliation is not None:
                if "manifest" in round_reconciliation:
                    if row["recipe"].get("workflow") == "four-model-alternating-v1":
                        from .group_runner import commit
                        commit(row, round_reconciliation["manifest"])
                    else:
                        from .training_runner import commit_round
                        commit_round(row, round_reconciliation["manifest"])
                row["history"].append({k: v for k, v in round_reconciliation.items() if k != "manifest"})
            row["history"].append({"event": "explicit_recovery", "checkpoint_id": row["checkpoint_ids"][-1],
                                   "optimizer_steps": row["metrics"].get("optimizer_updates", row["metrics"]["steps"])})
            put_row(db, row)
        return snapshot_for(row)


def worker(state_root, run_id, generation):
    backend = LocalCpuBackend(state_root, ROOT / ".cache")
    row = backend.details(run_id)
    if row["generation"] != generation or row["pid"] != os.getpid() or not alive(row):
        raise ContractError("worker lease does not identify this process")
    remaining = row["wall_limit_seconds"] - elapsed(row)
    if remaining <= 0:
        return 3
    # Default signal action is handled by the kernel, including blocked C++.
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    from .agent_monitor import RunReporter
    reporter = RunReporter(state_root)
    try:
        if row.get("recipe", {}).get("workflow") == "four-model-alternating-v1":
            from .group_runner import worker as group_worker
            completed = group_worker(state_root, run_id, generation, reporter)
        elif "recipe" in row:
            from .training_runner import worker_rounds
            completed = worker_rounds(state_root, run_id, generation, reporter)
        else:
            completed = False
        trainer = verified_trainer(state_root, row) if "recipe" not in row else None
        while trainer is not None and trainer.updates < 2:
            with closing(_connect(state_root)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                row = get_row(db, run_id)
                if row["generation"] != generation:
                    raise ContractError("worker generation superseded")
                if row["desired"] != "running":
                    break
                row.update(phase="sampling", revision=row["revision"] + 1)
                put_row(db, row)
            episode = trainer.sample_episode(Path(row["native_root"]), row["profile"])
            with closing(_connect(state_root)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                row = get_row(db, run_id)
                row["phase"] = "updating"
                put_row(db, row)
            update = trainer.update(episode)
            receipt = write_checkpoint(trainer, state_root, row)
            with closing(_connect(state_root)) as db, db:
                db.execute("BEGIN IMMEDIATE")
                row = get_row(db, run_id)
                row["checkpoint_ids"].append(receipt["checkpoint_id"])
                row["updates"].append({"update": update, "duel": {k: v for k, v in episode["summary"].items() if k != "actor_inference_ms"}})
                resources = reporter.resources()
                row["metrics"].update(steps=trainer.updates, episodes=trainer.episode_cursor, loss=update["loss"],
                                      process_cpu_seconds=row["completed_worker_cpu_seconds"] + resources["process_cpu_seconds"],
                                      process_peak_rss_bytes=max(row["metrics"].get("process_peak_rss_bytes", 0), resources.get("process_peak_rss_bytes", 0)))
                row["revision"] += 1
                row["phase"] = "checkpoint_boundary"
                row["history"].append({"event": "actual_optimizer_update_checkpointed", "step": trainer.updates,
                                       "model_sha256": update["after_sha256"], "checkpoint_id": receipt["checkpoint_id"]})
                put_row(db, row)
        if trainer is not None:
            completed = trainer.updates == 2
        with closing(_connect(state_root)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = get_row(db, run_id)
            if "recipe" in row:
                from .training_runner import settle_usage
                settle_usage(row, "completed" if completed else "interrupted", "measured_worker_wall")
            else:
                row["active_seconds"], row["segment_started"] = elapsed(row), None
            row["completed_worker_cpu_seconds"] += reporter.resources()["process_cpu_seconds"]
            row["metrics"]["process_cpu_seconds"] = row["completed_worker_cpu_seconds"]
            row["state"] = "completed" if completed else row["desired"]
            row["phase"] = "exited"
            if row["reason"] not in ("wall_budget_reserve_reached", "worker_stage_budget_reached"):
                row["reason"] = "safe_checkpoint_boundary"
            row["revision"] += 1
            put_row(db, row)
        if "recipe" in row:
            from .training_runner import sync_usage
            sync_usage(state_root, run_id)
        return 0
    except Exception as error:
        with closing(_connect(state_root)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = get_row(db, run_id)
            unsettled = row["segment_started"] is not None
            if "recipe" in row:
                from .training_runner import settle_usage
                settle_usage(row, "failed", "measured_worker_wall")
            else:
                row["active_seconds"], row["segment_started"] = elapsed(row), None
            if unsettled:
                row["completed_worker_cpu_seconds"] += reporter.resources()["process_cpu_seconds"]
            row["metrics"]["process_cpu_seconds"] = row["completed_worker_cpu_seconds"]
            row.update(state="failed", phase="exited", reason=type(error).__name__ + "_inspect_checkpoint",
                       revision=row["revision"] + 1, failure_detail=str(error)[:400])
            put_row(db, row)
        return 2
    # Leave the kernel timer armed through interpreter/native teardown.


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--generation", required=True)
    args = parser.parse_args()
    raise SystemExit(worker(args.state_root, args.run_id, args.generation))
