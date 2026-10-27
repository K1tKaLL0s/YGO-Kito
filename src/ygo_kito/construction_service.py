"""Host-configured construction inference for the existing local agent bridge.

RPC data never selects files, providers, training operations or a verifier.
Assets, classifier, binding evidence and optional model checkpoint are pinned by
its host. A run uses the existing controller with verifier=None and host=None;
it cannot execute native goal validation or submit a coordinator ledger job.
"""

from pathlib import Path
import pickle
import sqlite3

from .build_intent import classify_build_intent
from .intent_model import LinearIntentClassifier
from .validation import ContractError, array, canonical_json, fields, parse_json, read_json, text


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


class HostConstructionBackend:
    def __init__(self, classifier, *, assets=None, binding_data=None, logic_checkpoint=None, assets_factory=None):
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

    @classmethod
    def from_config(cls, workspace, native_root, value):
        config = fields(value, {"intent_model", "binding_data"}, {"logic_checkpoint"})
        workspace = Path(workspace).resolve()
        paths = {name: _workspace_file(workspace, config[name]) for name in config}
        try:
            classifier = LinearIntentClassifier.load(paths["intent_model"])
        except (OSError, ContractError) as error:
            raise ConstructionUnavailable("host intent model is missing or invalid") from error

        def assets_factory():
            from .build_pipeline import BuildAssets
            return BuildAssets(native_root)

        backend = cls(classifier, assets_factory=assets_factory, logic_checkpoint=paths.get("logic_checkpoint"))
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
        except (OSError, sqlite3.Error, EngineUnavailable, ContractError) as error:
            raise ConstructionUnavailable("host construction catalogue or binding evidence is unavailable") from error
        return self._assets, self._binding_adapter

    def run(self, params):
        data = fields(params, {"request", "task", "required_tags"}, {"base", "scopes", "feedback"})
        # Validate the complete request before touching host resources.
        from .build_contracts import BuildTask, DeckParts, digest
        from .construction_logic import ConstructionSession, LogicTag, ThemeScope
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
            self._builders[task.sha256] = BuildTrainer(task, assets, BuildTrainingConfig())
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
            self._coordinator = CoordinatorTrainer()
        controller = ConstructionController(adapter, binder, self._coordinator)
        result = controller.run(session, scopes=scopes, base=base, verifier=None)
        result.update(classification=session.classification.to_dict(), native_execution=False,
                      training_performed=False, coordinator_ledger_submission=False,
                      service_scope="host_configured_cpu_construction_inference")
        return result
