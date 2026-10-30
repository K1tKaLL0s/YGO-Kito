"""Card-independent, revisable 构筑逻辑 and conservative stage routing.

Tags are small identities; metadata and coarse connectors are separate. This
graph describes a construction idea, never an executable effect/condition DSL.
Existing deck tasks remain the authority for concrete cards and hard goals.
"""

from dataclasses import asdict, dataclass, replace

from .build_contracts import digest
from .validation import ContractError, array, fields, integer, member, text


def short(value, label, limit=64):
    text(value, label)
    if len(value) > limit:
        raise ContractError(label + " is too long")
    return value


@dataclass(frozen=True)
class LogicTag:
    dimension: str
    value: str

    def __post_init__(self):
        member(self.dimension, "logic tag dimension", ("effect", "effect_type", "field", "race", "role"))
        short(self.value, "basic tag")
        if "·" in self.value:
            raise ContractError("store basic tags separately; · joins display labels only")

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"dimension", "value"}))


@dataclass(frozen=True)
class LogicMetadata:
    source: str
    layer: str = "model_inference"
    note: str = ""

    def __post_init__(self):
        short(self.source, "logic source", 256)
        member(self.layer, "logic layer", ("user", "fact", "model_inference", "human", "engineering"))
        text(self.note, "logic note", empty=True)
        if len(self.note) > 512:
            raise ContractError("logic note is too long")

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"source", "layer", "note"}))


@dataclass(frozen=True)
class LogicNode:
    node_id: str
    tags: tuple[LogicTag, ...]
    metadata: tuple[LogicMetadata, ...] = ()

    def __post_init__(self):
        short(self.node_id, "logic node ID")
        if (not isinstance(self.tags, tuple) or not 1 <= len(self.tags) <= 12
                or any(not isinstance(t, LogicTag) for t in self.tags) or len(set(self.tags)) != len(self.tags)):
            raise ContractError("logic nodes need distinct bounded basic tags")
        if (not isinstance(self.metadata, tuple) or len(self.metadata) > 8
                or any(not isinstance(m, LogicMetadata) for m in self.metadata)):
            raise ContractError("typed bounded logic metadata required")

    @property
    def tag_identity(self):
        return tuple(sorted((t.dimension, t.value) for t in self.tags))

    @property
    def display_label(self):
        return "·".join(t.value for t in self.tags)

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"node_id", "tags", "metadata"})
        return cls(d["node_id"], tuple(LogicTag.from_dict(t) for t in array(d["tags"], "tags")),
                   tuple(LogicMetadata.from_dict(m) for m in array(d["metadata"], "metadata")))


@dataclass(frozen=True)
class LogicConnector:
    connector_id: str
    source: str
    target: str
    kind: str

    def __post_init__(self):
        for key in ("connector_id", "source", "target"):
            short(getattr(self, key), key)
        # Open vocabulary: ns, ss, 送墓时发动, etc. No condition interpreter.
        short(self.kind, "coarse connector", 32)

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"connector_id", "source", "target", "kind"}))


@dataclass(frozen=True)
class ConstructionLogic:
    logic_id: str
    nodes: tuple[LogicNode, ...]
    connectors: tuple[LogicConnector, ...]
    entry_nodes: tuple[str, ...]
    goal_nodes: tuple[str, ...]
    revision: int = 0
    parent_sha256: str | None = None

    def __post_init__(self):
        short(self.logic_id, "logic ID")
        integer(self.revision, "logic revision", 0)
        if self.revision == 0:
            if self.parent_sha256 is not None:
                raise ContractError("initial logic has no parent")
        elif (not isinstance(self.parent_sha256, str) or len(self.parent_sha256) != 64
              or any(c not in "0123456789abcdef" for c in self.parent_sha256)):
            raise ContractError("revised logic requires a parent digest")
        if (not isinstance(self.nodes, tuple) or not 1 <= len(self.nodes) <= 64
                or any(not isinstance(n, LogicNode) for n in self.nodes)):
            raise ContractError("typed bounded logic nodes required")
        ids = {n.node_id for n in self.nodes}
        if len(ids) != len(self.nodes):
            raise ContractError("duplicate logic node ID")
        if (not isinstance(self.connectors, tuple) or len(self.connectors) > 128
                or any(not isinstance(e, LogicConnector) for e in self.connectors)):
            raise ContractError("typed bounded coarse connectors required")
        if len({e.connector_id for e in self.connectors}) != len(self.connectors):
            raise ContractError("duplicate connector ID")
        if any(e.source not in ids or e.target not in ids for e in self.connectors):
            raise ContractError("dangling logic connector")
        for endpoints in (self.entry_nodes, self.goal_nodes):
            if (not isinstance(endpoints, tuple) or not endpoints or any(type(i) is not str for i in endpoints)
                    or len(set(endpoints)) != len(endpoints) or not set(endpoints) <= ids):
                raise ContractError("distinct existing entry/goal nodes required")
        if not set(self.goal_nodes) <= reachable(set(self.entry_nodes), self.connectors):
            raise ContractError("logic goals must be reachable from entries")

    def to_dict(self):
        # A JSON round trip detaches caller-owned data and normalizes tuples.
        from .validation import canonical_json, parse_json
        return parse_json(canonical_json(asdict(self)))

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"logic_id", "nodes", "connectors", "entry_nodes", "goal_nodes", "revision", "parent_sha256"})
        return cls(d["logic_id"], tuple(LogicNode.from_dict(n) for n in array(d["nodes"], "nodes")),
                   tuple(LogicConnector.from_dict(e) for e in array(d["connectors"], "connectors")),
                   tuple(array(d["entry_nodes"], "entry nodes")), tuple(array(d["goal_nodes"], "goal nodes")),
                   d["revision"], d["parent_sha256"])

    @property
    def sha256(self):
        return digest(self.to_dict())


def reachable(entries, connectors):
    found = set(entries)
    while True:
        more = {e.target for e in connectors if e.source in found} - found
        if not more:
            return found
        found.update(more)


def revise_logic(previous, *, nodes=None, connectors=None, entry_nodes=None, goal_nodes=None):
    """Replacement of the whole graph is allowed, with explicit ancestry."""
    return replace(previous, nodes=previous.nodes if nodes is None else nodes,
                   connectors=previous.connectors if connectors is None else connectors,
                   entry_nodes=previous.entry_nodes if entry_nodes is None else entry_nodes,
                   goal_nodes=previous.goal_nodes if goal_nodes is None else goal_nodes,
                   revision=previous.revision + 1, parent_sha256=previous.sha256)


def stage_route(classification):
    member(classification.kind, "intent", ("narrow", "broad", "ambiguous"))
    kind = classification.kind if classification.confidence >= .7 else "ambiguous"
    stages = {"narrow": [1, 2, 3], "broad": [1, 3], "ambiguous": [1]}[kind]
    return {"stages": stages, "needs_clarification": kind == "ambiguous",
            "names": {1: "构筑逻辑", 2: "主题主轴筛选", 3: "卡文填卡与核验"}}


@dataclass(frozen=True)
class ThemeScope:
    term: str
    field: str
    value: int
    source: str
    minimum: int = 1

    def __post_init__(self):
        short(self.term, "theme term", 80)
        member(self.field, "theme public fact", ("setcode", "race_any"))
        integer(self.value, "theme mask", 1, 65535 if self.field == "setcode" else 2**32 - 1)
        short(self.source, "theme fact source", 256)
        integer(self.minimum, "main-axis minimum", 1, 75)

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"term", "field", "value", "source", "minimum"}))


def select_main_axes(task, assets, classification, scopes=()):
    """Stage 2 finds core candidates; generic/support cards keep the full pool."""
    from .build_semantics import matches
    if stage_route(classification)["needs_clarification"]:
        return {"status": "needs_clarification", "axes": []}
    if classification.kind == "broad":
        if scopes:
            raise ContractError("broad requests skip theme-axis selection")
        return {"status": "skipped_broad", "axes": []}
    if (not isinstance(scopes, tuple) or any(not isinstance(s, ThemeScope) for s in scopes)
            or len({s.term for s in scopes}) != len(scopes)):
        raise ContractError("distinct typed theme scopes required")
    if not classification.narrow_terms or set(s.term for s in scopes) != set(classification.narrow_terms):
        return {"status": "unresolved_theme_facts", "axes": [],
                "unmet": ["supply sourced setcode/race facts for every requested narrow axis"]}
    assets.check_task(task)
    axes = [{**asdict(scope), "card_ids": [c for c in task.pool
             if matches(assets.rows[c], {"field": scope.field, "value": scope.value})]}
            for scope in scopes]
    return {"status": "selected" if all(a["card_ids"] for a in axes) else "no_axis_candidates", "axes": axes}


class ConstructionSession:
    """Deterministic coordinator around the existing goal/optimizer roles.

    No graph-generating weights are bundled. Providers must return real graph
    proposals; absence is reported rather than filled with rule-made templates.
    """

    def __init__(self, request, task, *, lexicon=None, classifier=None):
        from .build_contracts import BuildTask
        from .build_intent import classify_build_intent
        short(request, "user request", 4096)
        if not isinstance(task, BuildTask):
            raise ContractError("existing typed BuildTask required")
        self.request = request
        self._task = task.to_dict()
        self.task_sha256 = task.sha256
        self.goal_sha256 = digest({"request": request, "task": self._task})
        from .intent_model import LinearIntentClassifier
        self.classification = classify_build_intent(request, lexicon,
            classifier=classifier if classifier is not None else LinearIntentClassifier(lexicon=lexicon))
        self.logic = None
        self.history = []
        self.feedback = []
        self._accepted_fill = None

    @property
    def task(self):
        from .build_contracts import BuildTask
        return BuildTask.from_dict(self._task)

    def check_goal(self):
        if digest({"request": self.request, "task": self._task}) != self.goal_sha256:
            raise ContractError("user goal changed; start an explicitly revised request/session")

    def record_feedback(self, source, message):
        member(source, "feedback source", ("user", "fill", "duel", "build_goal", "build_optimizer", "coordinator"))
        short(message, "feedback", 1024)
        self.feedback.append({"source": source, "message": message,
                              "logic_sha256": self.logic.sha256 if self.logic else None})

    def submit_logic(self, graph, *, role, reason):
        self.check_goal()
        member(role, "logic role", ("build_goal", "build_optimizer", "user"))
        short(reason, "logic revision reason", 1024)
        if not isinstance(graph, ConstructionLogic):
            raise ContractError("typed construction logic required")
        if self.logic is None:
            if graph.revision != 0 or role == "build_optimizer":
                raise ContractError("initial logic must come from user/goal role")
        elif (graph.logic_id != self.logic.logic_id or graph.revision != self.logic.revision + 1
              or graph.parent_sha256 != self.logic.sha256):
            raise ContractError("stale or disconnected logic revision")
        self.logic = ConstructionLogic.from_dict(graph.to_dict())
        self._accepted_fill = None  # A prior graph's evidence cannot verify this one.
        self.history.append({"stage": 1, "role": role, "reason": reason, "goal_sha256": self.goal_sha256,
                             "logic": graph.to_dict(), "logic_sha256": graph.sha256,
                             "feedback": [dict(f) for f in self.feedback]})

    def logic_cycle(self, providers):
        """One target→optimizer cycle; either may reconstruct the graph."""
        self.check_goal()
        for role in ("build_goal", "build_optimizer"):
            result = self.propose_logic(role, providers.get(role))
            if result["status"] != "logic_revised":
                return result
        return {"status": "logic_revised", "logic_sha256": self.logic.sha256,
                "goal_sha256": self.goal_sha256, "training_status": "provider_supplied_no_training_claim"}

    def propose_logic(self, role, provider):
        self.check_goal()
        member(role, "logic provider role", ("build_goal", "build_optimizer"))
        if provider is None:
            return {"status": "graph_provider_unavailable", "role": role,
                    "training_status": "graph_generation_not_trained_in_this_change"}
        context = {"request": self.request, "goal_sha256": self.goal_sha256,
                   "task": self.task.to_dict(), "logic": self.logic.to_dict() if self.logic else None,
                   "feedback": [dict(f) for f in self.feedback], "role": role}
        from .construction_candidates import attributed_feedback
        context["attributed_feedback"]=attributed_feedback(self)
        proposal = fields(provider(context), {"logic", "reason"})
        self.check_goal()
        self.submit_logic(ConstructionLogic.from_dict(proposal["logic"]), role=role, reason=proposal["reason"])
        return {"status": "logic_revised", "logic_sha256": self.logic.sha256}

    def to_dict(self):
        from .validation import canonical_json, parse_json
        self.check_goal()
        return parse_json(canonical_json({"request": self.request, "task": self.task.to_dict(),
            "goal_sha256": self.goal_sha256, "classification": self.classification.to_dict(),
            "logic": self.logic.to_dict() if self.logic else None, "history": self.history, "feedback": self.feedback,
            "logic_requirements_sha256":getattr(self,"logic_requirements_sha256",None)}))
