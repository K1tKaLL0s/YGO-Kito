"""Policy-facing DTOs, not a rule engine or a hidden-state sanitiser.

The future real adapter must create these from a player-specific engine view.
Unknown fields are rejected instead of silently carrying internal state along.
"""

from dataclasses import asdict, dataclass, field

from .validation import ContractError, array, fields, integer, member, strings, text

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Versions:
    core: str
    scripts: str
    cards: str
    protocol: str
    card_pool: str
    banlist: str

    def __post_init__(self):
        for key, value in asdict(self).items():
            text(value, key + " version")

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"core", "scripts", "cards", "protocol", "card_pool", "banlist"}))


@dataclass(frozen=True)
class ModelVersion:
    role: str
    version: str
    lora: str | None = None

    def __post_init__(self):
        member(self.role, "model role", ("duel", "build_goal", "build_optimizer", "coordinator"))
        text(self.version, "model version")
        if self.lora is not None:
            text(self.lora, "LoRA version")

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"role", "version"}, {"lora"}))


@dataclass(frozen=True)
class RunContext:
    run_id: str
    versions: Versions
    seed: int | None
    models: tuple[ModelVersion, ...] = ()

    def __post_init__(self):
        text(self.run_id, "run_id")
        if self.seed is not None:
            integer(self.seed, "seed")
        if not isinstance(self.versions, Versions):
            raise ContractError("versions must be Versions")
        if any(not isinstance(model, ModelVersion) for model in self.models):
            raise ContractError("models must contain ModelVersion records")
        if len({model.role for model in self.models}) != len(self.models):
            raise ContractError("duplicate model roles")

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"run_id", "versions", "seed"}, {"models"})
        return cls(d["run_id"], Versions.from_dict(d["versions"]), d["seed"],
                   tuple(ModelVersion.from_dict(m) for m in array(d.get("models", []), "models")))

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class CardView:
    ref: str
    owner: int | None
    controller: int
    zone: str
    visibility: str
    card_id: int | None
    position: int | None = None
    attack: int | None = None
    defense: int | None = None

    def __post_init__(self):
        text(self.ref, "card reference")
        if self.owner is not None:
            integer(self.owner, "owner", 0, 1)
        elif self.visibility != "hidden":
            raise ContractError("visible cards require a known owner")
        integer(self.controller, "controller", 0, 1)
        # Deck contents/order are not representable in this policy interface.
        member(self.zone, "card zone", ("hand", "monster", "spell_trap", "graveyard", "banished", "extra"))
        member(self.visibility, "visibility", ("public", "observer", "hidden"))
        if self.visibility == "hidden":
            if self.card_id is not None or self.attack is not None or self.defense is not None:
                raise ContractError("hidden cards must not contain card_id or combat stats")
        else:
            integer(self.card_id, "visible card_id", 1)
        if self.position is not None:
            integer(self.position, "card position mask", 1, 15)
        for name in ("attack", "defense"):
            if getattr(self, name) is not None:
                integer(getattr(self, name), name, -2, 2**31 - 1)

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"ref", "owner", "controller", "zone", "visibility", "card_id"}, {"position", "attack", "defense"}))


@dataclass(frozen=True)
class PublicEvent:
    event_id: str
    kind: str
    card_ids: tuple[int, ...] = ()

    def __post_init__(self):
        text(self.event_id, "event_id")
        member(self.kind, "public event", ("reveal", "move", "activate", "summon", "attack", "phase", "result"))
        for card_id in self.card_ids:
            integer(card_id, "public historical card_id", 1)

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"event_id", "kind", "card_ids"})
        return cls(d["event_id"], d["kind"], tuple(array(d["card_ids"], "public card_ids")))


def _pair(value, label):
    if not isinstance(value, tuple) or len(value) != 2:
        raise ContractError(label + " must contain exactly two counts")
    for item in value:
        integer(item, label)


@dataclass(frozen=True)
class Observation:
    observer: int
    turn_player: int
    turn: int
    phase: str
    life_points: tuple[int, int]
    hand_counts: tuple[int, int]
    deck_counts: tuple[int, int]
    cards: tuple[CardView, ...]
    public_history: tuple[PublicEvent, ...] = ()

    def __post_init__(self):
        integer(self.observer, "observer", 0, 1)
        integer(self.turn_player, "turn_player", 0, 1)
        integer(self.turn, "turn", 1)
        member(self.phase, "phase", ("draw", "standby", "main1", "battle", "main2", "end"))
        for key in ("life_points", "hand_counts", "deck_counts"):
            _pair(getattr(self, key), key)
        if any(not isinstance(c, CardView) for c in self.cards):
            raise ContractError("cards must contain CardView records")
        if len({c.ref for c in self.cards}) != len(self.cards):
            raise ContractError("duplicate card references")
        for c in self.cards:
            if c.visibility == "observer":
                viewer = c.controller
                if viewer != self.observer:
                    raise ContractError("opponent private cards are not policy-visible")
        if any(not isinstance(e, PublicEvent) for e in self.public_history):
            raise ContractError("history must contain PublicEvent records")
        if len({e.event_id for e in self.public_history}) != len(self.public_history):
            raise ContractError("duplicate public event IDs")

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"observer", "turn_player", "turn", "phase", "life_points", "hand_counts", "deck_counts", "cards"}, {"public_history"})
        return cls(
            d["observer"], d["turn_player"], d["turn"], d["phase"],
            tuple(array(d["life_points"], "life_points")), tuple(array(d["hand_counts"], "hand_counts")),
            tuple(array(d["deck_counts"], "deck_counts")), tuple(CardView.from_dict(c) for c in array(d["cards"], "cards")),
            tuple(PublicEvent.from_dict(e) for e in array(d.get("public_history", []), "public_history")),
        )


@dataclass(frozen=True)
class Placement:
    controller: int
    zone: str
    sequence: int

    def __post_init__(self):
        integer(self.controller, "placement controller", 0, 1)
        member(self.zone, "placement zone", ("monster", "spell_trap"))
        integer(self.sequence, "placement sequence", 0, 6 if self.zone == "monster" else 7)

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"controller", "zone", "sequence"}))


@dataclass(frozen=True)
class ActionDetails:
    description: int | None = None
    operation: str | None = None
    destination: Placement | None = None

    def __post_init__(self):
        if self.description is not None:
            integer(self.description, "effect description", 0, 2**32 - 1)
        if self.operation is not None:
            member(self.operation, "selection operation", ("add", "remove", "finish", "cancel", "shuffle"))
        if self.destination is not None and not isinstance(self.destination, Placement):
            raise ContractError("destination must be Placement")
        if self.description is None and self.operation is None and self.destination is None:
            raise ContractError("action details cannot be empty")

    @classmethod
    def from_dict(cls, value):
        d = fields(value, set(), {"description", "operation", "destination"})
        return cls(d.get("description"), d.get("operation"),
                   Placement.from_dict(d["destination"]) if d.get("destination") is not None else None)


@dataclass(frozen=True)
class PromptInfo:
    message: int
    minimum: int | None = None
    maximum: int | None = None
    cancelable: bool = False
    finishable: bool = False

    def __post_init__(self):
        integer(self.message, "native prompt message", 0, 255)
        if self.message not in (10, 11, 12, 13, 14, 15, 16, 18, 19, 20, 26):
            raise ContractError("unsupported native prompt message")
        if (self.minimum is None) != (self.maximum is None):
            raise ContractError("both selection bounds are required")
        if self.minimum is not None:
            integer(self.minimum, "selection minimum", 0, 255)
            integer(self.maximum, "selection maximum", self.minimum, 255)
        if type(self.cancelable) is not bool or type(self.finishable) is not bool:
            raise ContractError("selection flags must be bool")

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"message"}, {"minimum", "maximum", "cancelable", "finishable"}))


@dataclass(frozen=True)
class LegalAction:
    action_id: str
    kind: str
    card_refs: tuple[str, ...] = ()
    value: int | None = None
    details: ActionDetails | None = None

    def __post_init__(self):
        text(self.action_id, "action_id")
        member(self.kind, "action kind", ("summon", "special_summon", "set", "activate", "attack", "select", "order", "number", "position", "yes", "no", "pass"))
        strings(list(self.card_refs), "action card references")
        if self.value is not None:
            integer(self.value, "action value")
        if self.details is not None and not isinstance(self.details, ActionDetails):
            raise ContractError("details must be ActionDetails")

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"action_id", "kind", "card_refs"}, {"value", "details"})
        return cls(d["action_id"], d["kind"], strings(d["card_refs"], "action card references"), d.get("value"),
                   ActionDetails.from_dict(d["details"]) if d.get("details") is not None else None)


@dataclass(frozen=True)
class SearchChoice:
    """A legally offered identity without deck position or native index."""
    ref: str
    card_id: int
    owner: int

    def __post_init__(self):
        text(self.ref, "search reference")
        integer(self.card_id, "search card_id", 1)
        integer(self.owner, "search owner", 0, 1)

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"ref", "card_id", "owner"}))


@dataclass(frozen=True)
class DecisionRequest:
    context: RunContext
    duel_id: str
    decision_id: str
    observation: Observation
    actions: tuple[LegalAction, ...]
    schema_version: int = field(default=SCHEMA_VERSION)
    search_choices: tuple[SearchChoice, ...] = ()
    prompt: PromptInfo | None = None

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ContractError("unsupported decision schema_version")
        text(self.duel_id, "duel_id")
        text(self.decision_id, "decision_id")
        if not isinstance(self.context, RunContext) or not isinstance(self.observation, Observation):
            raise ContractError("typed context and observation required")
        if self.prompt is not None and not isinstance(self.prompt, PromptInfo):
            raise ContractError("prompt must be PromptInfo")
        if not self.actions or any(not isinstance(a, LegalAction) for a in self.actions):
            raise ContractError("a decision requires at least one LegalAction")
        if len({a.action_id for a in self.actions}) != len(self.actions):
            raise ContractError("duplicate action IDs")
        refs = {c.ref for c in self.observation.cards}
        for choice in self.search_choices:
            if not isinstance(choice, SearchChoice) or choice.owner != self.observation.observer or choice.ref in refs:
                raise ContractError("search choices must be unique and visible only to the chooser")
            refs.add(choice.ref)
        if any(set(action.card_refs) - refs for action in self.actions):
            raise ContractError("action references an unobserved card")

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"schema_version", "context", "duel_id", "decision_id", "observation", "actions"}, {"search_choices", "prompt"})
        return cls(
            RunContext.from_dict(d["context"]), d["duel_id"], d["decision_id"],
            Observation.from_dict(d["observation"]), tuple(LegalAction.from_dict(a) for a in array(d["actions"], "actions")),
            d["schema_version"], tuple(SearchChoice.from_dict(c) for c in array(d.get("search_choices", []), "search_choices")),
            PromptInfo.from_dict(d["prompt"]) if d.get("prompt") is not None else None,
        )

    def to_dict(self):
        result = asdict(self)
        if not self.search_choices:
            result.pop("search_choices")
        if self.prompt is None:
            result.pop("prompt")
        for action in result["actions"]:
            if action["details"] is None:
                action.pop("details")
        for card in result["observation"]["cards"]:
            for key in ("position", "attack", "defense"):
                if card[key] is None:
                    card.pop(key)
        return result


@dataclass(frozen=True)
class ActionSelection:
    run_id: str
    duel_id: str
    decision_id: str
    action_id: str

    def __post_init__(self):
        for key, value in asdict(self).items():
            text(value, key)

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"run_id", "duel_id", "decision_id", "action_id"}))


def validate_selection(request: DecisionRequest, selection: ActionSelection) -> LegalAction:
    """Validate membership and request identity, without claiming rule verification."""
    if (selection.run_id, selection.duel_id, selection.decision_id) != (
        request.context.run_id, request.duel_id, request.decision_id
    ):
        raise ContractError("stale or mismatched decision selection")
    for action in request.actions:
        if selection.action_id == action.action_id:
            return action
    raise ContractError("action_id is not in the engine-provided candidates")
