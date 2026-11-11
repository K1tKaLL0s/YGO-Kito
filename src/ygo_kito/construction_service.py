"""Host-configured construction inference for the existing local agent bridge.

RPC data never selects files, providers, training operations or a verifier.
Assets, classifier, binding evidence and optional model checkpoint are pinned by
its host. A run uses the existing controller with verifier=None and host=None;
it cannot execute native goal validation or submit a coordinator ledger job.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
import math
from pathlib import Path
import pickle
import re
import sqlite3
from threading import Event, Lock

from .build_contracts import BuildTask, DeckParts, digest
from .build_intent import classify_build_intent
from .construction_checkpoint import ConstructionCheckpoint, KERNEL_FILENAME, LEGACY_KERNEL_FILENAME
from .construction_logic import ConstructionLogic, ConstructionSession, LogicTag, ThemeScope
from .intent_model import LinearIntentClassifier
from .validation import ContractError, array, canonical_json, fields, integer, member, parse_json, read_json, text


class ConstructionUnavailable(ContractError):
    """A configured host artifact/catalogue is absent or cannot be loaded."""


def _workspace_file(workspace, value):
    text(value, "host construction artifact path")
    path = Path(value)
    if not path.is_absolute():
        path = workspace / path
    path = path.resolve()
    if not path.is_relative_to(workspace):
        raise ContractError("host construction artifacts must stay inside the workspace")
    return path


def _runtime_options(value):
    data = fields(value if value is not None else {}, set(), {'mode', 'seconds', 'slice_seconds', 'iterations'})
    mode = member(data.get('mode', 'development'), 'construction runtime mode', ('development', 'online'))
    slice_seconds = data.get('slice_seconds', 30.)
    if type(slice_seconds) not in (int, float) or not math.isfinite(slice_seconds) or slice_seconds <= 0:
        raise ContractError('construction slice_seconds must be positive and finite')
    result = dict(run_mode=mode, slice_seconds=slice_seconds,
                  max_iterations=integer(data.get('iterations', 4), 'construction iterations per slice', 1, 64))
    if mode == 'online':
        seconds = data.get('seconds', 600.)
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            raise ContractError('online construction seconds must be finite and nonnegative')
        result['seconds'] = seconds
    elif 'seconds' in data:
        raise ContractError('construction seconds require online mode')
    return result


@dataclass
class _Job:
    checkpoint: ConstructionCheckpoint
    state: dict
    progress: dict
    pause: Event = field(default_factory=Event)
    active: bool = False


class HostConstructionBackend:
    def __init__(self, classifier, *, assets=None, binding_data=None, logic_checkpoint=None, assets_factory=None,
                 runtime=None, device="cpu"):
        if not isinstance(classifier, LinearIntentClassifier):
            raise ContractError("host must supply a fixed typed intent classifier")
        if assets is not None and assets_factory is not None:
            raise ContractError("supply fixed assets or a lazy asset factory, not both")
        if assets_factory is not None and not callable(assets_factory):
            raise ContractError("host construction asset factory must be callable")
        if binding_data is not None and not isinstance(binding_data, dict):
            raise ContractError("host binding data must be an object")
        self.classifier = classifier
        self._assets = assets
        self._assets_factory = assets_factory
        self._binding_data = parse_json(canonical_json(binding_data or {}))
        self._binding_path = None
        self._logic_checkpoint = Path(logic_checkpoint) if logic_checkpoint is not None else None
        self._binding_adapter = None
        self._coordinator = None
        self._builders = {}
        self._adapters = {}
        self._runtime = _runtime_options(runtime)
        self._device = text(device, "host construction device")
        self._state_root = None
        self._owner = None
        self._executor = None
        self._jobs = {}
        self._lock = Lock()
        self._models_lock = Lock()
        self._closed = False

    @classmethod
    def from_config(cls, workspace, native_root, value):
        config = fields(value, {"intent_model", "binding_data"}, {"logic_checkpoint", "runtime", "device"})
        workspace = Path(workspace).resolve()
        paths = {name: _workspace_file(workspace, config[name]) for name in config.keys() - {'runtime', 'device'}}
        try:
            classifier = LinearIntentClassifier.load(paths["intent_model"])
        except (OSError, ContractError) as error:
            raise ConstructionUnavailable("host intent model is missing or invalid") from error

        def assets_factory():
            from .build_pipeline import BuildAssets
            return BuildAssets(native_root)

        backend = cls(classifier, assets_factory=assets_factory, logic_checkpoint=paths.get("logic_checkpoint"),
                      runtime=config.get('runtime'), device=config.get('device', 'cuda:0'))
        backend._binding_path = paths["binding_data"]
        return backend

    def plan(self, params):
        data = fields(params, {"request"})
        intent = classify_build_intent(data["request"], classifier=self.classifier)
        from .construction_logic import stage_route
        return {"classification": intent.to_dict(), "route": stage_route(intent),
                "training_status": intent.classifier_status, "graph_execution_verified": False,
                "native_execution": False, "training_performed": False}

    def _resources(self):
        if self._binding_adapter is not None:
            return self._assets, self._binding_adapter
        from .construction_binding import CatalogBindingAdapter
        from .engine import EngineUnavailable
        try:
            if self._assets is None:
                if self._assets_factory is None:
                    raise ConstructionUnavailable("host construction catalogue is not configured")
                self._assets = self._assets_factory()
            data = read_json(self._binding_path) if self._binding_path is not None else self._binding_data
            self._binding_adapter = CatalogBindingAdapter.from_dict(self._assets, data)
            self._assessment_sha256 = digest(data)
        except (OSError, sqlite3.Error, EngineUnavailable, ContractError) as error:
            raise ConstructionUnavailable("host construction catalogue or binding evidence is unavailable") from error
        return self._assets, self._binding_adapter

    def _inputs(self, params):
        data = fields(params, {"request", "task", "required_tags"}, {"base", "scopes", "feedback"})
        task = BuildTask.from_dict(data["task"])
        raw_tags = array(data["required_tags"], "required logic tags")
        if not 1 <= len(raw_tags) <= 8:
            raise ContractError("agent construction accepts one to eight required tags")
        tags = tuple(LogicTag.from_dict(tag) for tag in raw_tags)
        if len(set(tags)) != len(tags):
            raise ContractError("duplicate required logic tags")
        base = DeckParts.from_dict(data["base"]) if "base" in data else None
        scopes = tuple(ThemeScope.from_dict(scope) for scope in array(data.get("scopes", []), "theme scopes"))
        feedback = array(data.get("feedback", []), "construction feedback")
        if len(feedback) > 32:
            raise ContractError("too many construction feedback messages")
        session = ConstructionSession(data["request"], task, classifier=self.classifier)
        for item in feedback:
            row = fields(item, {"source", "message"})
            session.record_feedback(row["source"], row["message"])
        return session, tags, base, scopes

    def _controller(self, task, tags, base):
        assets, binder = self._resources()
        assets.check_task(task)
        if base is not None:
            assets.validate(task, base)
        from .build_training import BuildTrainer, BuildTrainingConfig
        from .construction_model import LogicCodec, LogicModelAdapter
        from .construction_controller import ConstructionController
        from .coordinator_model import CoordinatorTrainer
        codec = LogicCodec(tags)
        key = (task.sha256, digest(codec.to_dict()))
        if task.sha256 not in self._builders:
            self._builders[task.sha256] = BuildTrainer(task, assets, BuildTrainingConfig(), device=self._device)
        if key not in self._adapters:
            adapter = LogicModelAdapter.from_builder(self._builders[task.sha256], codec, required_tags=tags)
            if self._logic_checkpoint is not None:
                try:
                    adapter.load(self._logic_checkpoint)
                except (OSError, EOFError, ContractError, RuntimeError, ValueError, pickle.UnpicklingError) as error:
                    raise ConstructionUnavailable("host graph checkpoint is missing or invalid") from error
            self._adapters[key] = adapter
        adapter = self._adapters[key]
        adapter.last_selection.clear()  # Each RPC owns its evidence, while weights are reused.
        if self._coordinator is None:
            self._coordinator = CoordinatorTrainer(device=self._device)
        return assets, ConstructionController(adapter, binder, self._coordinator)

    def _execute(self, controller, session, base, scopes, **options):
        result = controller.run(session, scopes=scopes, base=base, verifier=None, cb_authorized=False, **options)
        result.update(classification=session.classification.to_dict(), native_execution=False,
                      training_performed=False, coordinator_ledger_submission=False,
                      service_scope="host_configured_construction_inference", inference_device=str(controller.graph_adapter.device))
        return result

    def run(self, params):
        session, tags, base, scopes = self._inputs(params)
        if not self._models_lock.acquire(blocking=False):
            raise ConstructionUnavailable('construction models are busy; use the active session progress interface')
        try:
            _, controller = self._controller(session.task, tags, base)
            return self._execute(controller, session, base, scopes, **self._runtime)
        finally:
            self._models_lock.release()

    def attach_state_root(self, root):
        root = Path(root).resolve()
        directory = root/'construction'
        if directory.resolve() != directory or self._state_root not in (None, directory):
            raise ContractError('construction requires its own host state directory')
        self._state_root = directory

    def _open_jobs(self):
        if self._closed or self._state_root is None:
            raise ConstructionUnavailable('construction session storage is unavailable')
        if self._owner is None:
            self._state_root.mkdir(parents=True, exist_ok=True)
            owner_path = self._state_root/'owner.sqlite3'
            if owner_path.is_symlink():
                raise ContractError('construction owner file must stay in its host directory')
            owner = sqlite3.connect(owner_path, timeout=0., isolation_level=None,
                                    check_same_thread=False)
            try:
                owner.execute('BEGIN IMMEDIATE')
            except sqlite3.Error as error:
                owner.close()
                raise ConstructionUnavailable('another construction host owns this state directory') from error
            self._owner = owner
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='construction')

    def _host_binding(self):
        return digest(dict(directory=str(self._state_root), classifier=self.classifier.sha256, runtime=self._runtime))

    def _checkpoint_path(self, session_id):
        if not isinstance(session_id, str) or re.fullmatch(r'construction-[0-9a-f]{32}', session_id) is None:
            raise ContractError('invalid construction session identifier')
        root = self._state_root/session_id
        current, legacy = root/KERNEL_FILENAME, root/LEGACY_KERNEL_FILENAME
        for path in (current, legacy):
            if path.resolve() != path or path.is_symlink() or path.with_suffix(path.suffix + '.tmp').is_symlink():
                raise ContractError('construction session state must stay in its host directory')
        if legacy.exists() and current.exists():
            raise ContractError('construction session has two committed kernels')
        return legacy if legacy.exists() else current

    def _job(self, session_id):
        path = self._checkpoint_path(session_id)
        if session_id not in self._jobs:
            if not path.is_file():
                raise ContractError('unknown construction session')
            saved = ConstructionCheckpoint.read(path)
            state = saved['state']
            if (state.get('schema') != 'construction-service-session-v1' or state.get('session_id') != session_id
                    or state.get('host_binding') != self._host_binding()
                    or state.get('request_sha256') != digest(state.get('request'))):
                raise ContractError('construction session belongs to another host or request')
            progress = dict(state['progress'], revision=saved['revision'])
            if progress['status'] in ('queued', 'running'):
                progress.update(status='paused', stop_reason='host_interrupted')
            state = {k: v for k, v in state.items() if k not in ('session', 'accepted_fill', 'progress')}
            self._jobs[session_id] = _Job(ConstructionCheckpoint(path, revision=saved['revision']), state, progress)
        return self._jobs[session_id]

    def _report(self, job):
        return deepcopy(dict(job.progress, active=job.active, cancel_requested=job.active and job.pause.is_set()))

    def _queue(self, job, attempt):
        job.pause.clear()
        job.active = True
        job.progress = dict(job.progress, status='queued', attempt=attempt, stop_reason=None)
        job.progress.pop('error', None)
        self._executor.submit(self._work, job, attempt)
        return self._report(job)

    def start(self, params, request_id):
        session, _, _, _ = self._inputs(params)
        request = parse_json(canonical_json(params))
        request_sha = digest(request)
        session_id = 'construction-' + digest(request_id)[:32]
        with self._lock:
            self._open_jobs()
            path = self._checkpoint_path(session_id)
            if path.exists():
                job = self._job(session_id)
                if job.state['request_sha256'] != request_sha:
                    raise ContractError('construction start request ID was already used for another task')
                return self._report(job)
            path.parent.mkdir(parents=True, exist_ok=True)
            checkpoint = ConstructionCheckpoint(path)
            state = dict(schema='construction-service-session-v1', session_id=session_id, request=request,
                         request_sha256=request_sha, host_binding=self._host_binding(), model_binding=None,
                         continuations={}, remaining_seconds=self._runtime.get('seconds'))
            progress = dict(session_id=session_id, task_sha256=session.task_sha256, goal_sha256=session.goal_sha256,
                            status='queued', attempt=1, mode=self._runtime['run_mode'])
            revision = checkpoint.commit(dict(state, progress=progress, session=None, accepted_fill=None), stop_reason='created')
            job = self._jobs[session_id] = _Job(checkpoint, state, dict(progress, revision=revision))
            return self._queue(job, 1)

    def continue_session(self, params, request_id):
        data = fields(params, {'session_id', 'revision'})
        revision = integer(data['revision'], 'construction resume revision', 1)
        with self._lock:
            self._open_jobs()
            job = self._job(data['session_id'])
            requests = job.state['continuations']
            if request_id in requests:
                if requests[request_id] != revision:
                    raise ContractError('construction continue request ID was already used at another revision')
                return self._report(job)
            if job.active or job.progress.get('construction_passed') or job.progress['revision'] != revision:
                raise ContractError('construction continuation requires its current inactive revision')
            job.state = dict(job.state, continuations={**requests, request_id: revision})
            return self._queue(job, job.progress['attempt'] + 1)

    def progress(self, params):
        data = fields(params, {'session_id'})
        with self._lock:
            self._open_jobs()
            return self._report(self._job(data['session_id']))

    def cancel(self, params):
        data = fields(params, {'session_id', 'attempt'})
        attempt = integer(data['attempt'], 'construction attempt', 1)
        with self._lock:
            self._open_jobs()
            job = self._job(data['session_id'])
            if job.active and job.progress['attempt'] == attempt:
                job.pause.set()
            return self._report(job)

    def _model_binding(self, assets, controller):
        from .construction_model import FEATURE_VERSION
        from .duel_model import parameter_digest
        adapter = controller.graph_adapter
        return digest(dict(feature=FEATURE_VERSION, assets=assets.receipt, assessments=self._assessment_sha256,
            vocabulary=adapter.deck_encoder.vocabulary_sha256, requirements=adapter.requirements_sha256,
            roles={role: parameter_digest(model) for role, model in adapter.models.items()},
            coordinator=parameter_digest(controller.coordinator.model)))

    @staticmethod
    def _restore_session(session, raw, accepted, assets):
        if (raw['request'] != session.request or raw['task'] != session.task.to_dict()
                or raw['goal_sha256'] != session.goal_sha256 or raw['classification'] != session.classification.to_dict()):
            raise ContractError('saved construction session differs from the original task')
        for event in raw['history']:
            if event['stage'] == 1:
                session.submit_logic(ConstructionLogic.from_dict(event['logic']), role=event['role'], reason=event['reason'])
        if raw['logic'] != (session.logic.to_dict() if session.logic else None):
            raise ContractError('saved construction session lost its graph ancestry')
        session.history = raw['history']
        session.feedback = []
        for item in raw['feedback']:
            session.record_feedback(item['source'], item['message'])
        session.feedback = raw['feedback']
        session.optimization_feedback = raw['optimization_feedback']
        session.logic_requirements_sha256 = raw['logic_requirements_sha256']
        if accepted is not None:
            if session.logic is None or accepted['task_sha256'] != session.task_sha256 or accepted['logic_sha256'] != session.logic.sha256:
                raise ContractError('saved accepted fill belongs to another task or graph')
            assets.validate(session.task, DeckParts.from_dict(accepted['deck']))
        session._accepted_fill = accepted
        from .construction_progress import restore_progress
        restore_progress(session, raw['construction_progress'], assets)

    def _work(self, job, attempt):
        state = job.state

        def commit(progress, reason, snapshot, accepted):
            revision = job.checkpoint.commit(dict(state, progress=progress, session=snapshot, accepted_fill=accepted),
                                             stop_reason=reason)
            with self._lock:
                job.state = state
                job.progress = dict(progress, revision=revision)

        try:
            with self._models_lock:
                saved = job.checkpoint.read(job.checkpoint.path)['state']
                if job.pause.is_set():
                    commit(dict(job.progress, status='paused', stop_reason='user_pause'), 'user_pause',
                           saved['session'], saved['accepted_fill'])
                    return
                with self._lock:
                    job.progress = dict(job.progress, status='running')
                session, tags, base, scopes = self._inputs(state['request'])
                assets, controller = self._controller(session.task, tags, base)
                binding = self._model_binding(assets, controller)
                if state['model_binding'] not in (None, binding):
                    raise ContractError('construction session models or resources have changed')
                state = dict(state, model_binding=binding)
                if saved['session'] is not None:
                    self._restore_session(session, saved['session'], saved['accepted_fill'], assets)

                def publish(result):
                    nonlocal state
                    execution = result['execution']
                    reason = result['stop_reason']
                    candidate = result.get('construction_candidate') or {}
                    gate = result.get('construction_gate') or {}
                    continuation = result.get('continuation') or {}
                    pending = continuation.get('pending_quality') or {}
                    status = 'paused' if reason == 'user_pause' else 'finished' if execution['finished'] else 'running'
                    if execution['deadline_seconds'] is not None:
                        state = dict(state, remaining_seconds=max(0., execution['deadline_seconds'] - execution['elapsed_seconds']))
                    progress = dict(session_id=state['session_id'], task_sha256=session.task_sha256, goal_sha256=session.goal_sha256,
                        attempt=attempt, status=status, stop_reason=reason, execution=execution,
                        construction_passed=result['construction_passed'], completion_status=result['completion_status'],
                        iteration=continuation.get('iteration'), candidate=candidate.get('deck'),
                        candidate_evaluation_id=(candidate.get('quality_evaluation') or {}).get('evaluation_id'),
                        gate_status=gate.get('status'), gate_reasons=gate.get('reasons', []),
                        pending_candidates=len(pending.get('pending_indices', ())),
                        comparisons=(pending.get('comparison_progress') or {}).get('next_pair'))
                    commit(progress, reason, session._snapshot(), session._accepted_fill)

                options = dict(self._runtime)
                if state['remaining_seconds'] is not None:
                    options['seconds'] = state['remaining_seconds']
                self._execute(controller, session, base, scopes, **options, pause_requested=job.pause.is_set,
                              _checkpoint=publish)
        except Exception as error:
            with self._lock:
                job.progress = dict(job.progress, status='failed', stop_reason='error',
                                    error=dict(type=type(error).__name__, message=str(error)))
        finally:
            with self._lock:
                job.active = False

    def close(self):
        with self._lock:
            self._closed = True
            for job in self._jobs.values():
                if job.active:
                    job.pause.set()
        if self._executor is not None:
            self._executor.shutdown()
            self._executor = None
        if self._owner is not None:
            self._owner.close()
            self._owner = None
