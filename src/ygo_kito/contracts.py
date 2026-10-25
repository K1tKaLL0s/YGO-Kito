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
    attached_to: str | None = None
    material_count: int | None = None

    def __post_init__(self):
        text(self.ref, "card reference")
        if self.owner is not None:
            integer(self.owner, "owner", 0, 1)
        elif self.visibility != "hidden" and self.zone != "overlay":
            raise ContractError("visible cards require a known owner")
        integer(self.controller, "controller", 0, 1)
        # Deck contents/order are not representable in this policy interface.
        member(self.zone, "card zone", ("hand", "monster", "spell_trap", "graveyard", "banished", "extra", "overlay"))
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
        if self.zone == "overlay":
            text(self.attached_to, "material host reference")
        elif self.attached_to is not None:
            raise ContractError("only overlay materials have a host reference")
        if self.material_count is not None:
            if self.zone != "monster":
                raise ContractError("only monster hosts have material counts")
            integer(self.material_count, "material count", 0, 128)

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"ref", "owner", "controller", "zone", "visibility", "card_id"}, {"position", "attack", "defense", "attached_to", "material_count"}))


@dataclass(frozen=True)
class PublicLocation:
    controller: int
    zone: str
    sequence: int | None = None
    position: int | None = None

    def __post_init__(self):
        integer(self.controller, "history controller", 0, 1)
        member(self.zone, "history zone", ("deck", "hand", "monster", "spell_trap", "graveyard", "banished", "extra", "overlay", "none"))
        if self.sequence is not None:
            if self.zone in ("deck", "hand", "extra", "none"):
                raise ContractError("private historical sequence is forbidden")
            integer(self.sequence, "public historical sequence", 0, 255)
        if self.position is not None:
            integer(self.position, "historical position", 0, 15)

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"controller", "zone"}, {"sequence", "position"}))


@dataclass(frozen=True)
class PublicEventDetails:
    message: int
    player: int | None = None
    turn: int | None = None
    phase: str | None = None
    locations: tuple[PublicLocation, ...] = ()
    amount: int | None = None
    value: int | None = None
    values: tuple[int, ...] = ()
    link: int | None = None
    description: int | None = None
    reason: int | None = None
    life_points: tuple[int, int] | None = None

    def __post_init__(self):
        integer(self.message, "public native message", 0, 255)
        if self.player is not None:
            integer(self.player, "history player", 0, 1)
        if self.turn is not None:
            integer(self.turn, "history turn", 0)
        if self.phase is not None:
            member(self.phase, "history phase", ("draw", "standby", "main1", "battle", "main2", "end"))
        if not isinstance(self.locations, tuple) or len(self.locations) > 255 or any(not isinstance(x, PublicLocation) for x in self.locations):
            raise ContractError("history locations must be typed and bounded")
        for key in ("amount", "value", "link", "description", "reason"):
            value = getattr(self, key)
            if value is not None:
                integer(value, "history " + key, -2**31, 2**32 - 1)
        if not isinstance(self.values, tuple) or len(self.values) > 255:
            raise ContractError("history values must be a bounded tuple")
        for v in self.values:
            integer(v, "history numeric value", -2**31, 2**32 - 1)
        if self.life_points is not None:
            _pair(self.life_points, "historical life points")

    @classmethod
    def from_dict(cls, value):
        d = dict(fields(value, {"message"}, {"player", "turn", "phase", "locations", "amount", "value", "values", "link", "description", "reason", "life_points"}))
        d["locations"] = tuple(PublicLocation.from_dict(x) for x in array(d.get("locations", []), "history locations"))
        d["values"] = tuple(array(d.get("values", []), "history values"))
        if d.get("life_points") is not None:
            d["life_points"] = tuple(array(d["life_points"], "historical life points"))
        return cls(**d)


@dataclass(frozen=True)
class PublicEvent:
    event_id: str
    kind: str
    card_ids: tuple[int, ...] = ()
    details: PublicEventDetails | None = None

    def __post_init__(self):
        text(self.event_id, "event_id")
        member(self.kind, "public event", ("reveal", "move", "activate", "summon", "attack", "phase", "result", "turn", "chain", "lp", "counter", "shuffle", "battle", "position", "announce", "random", "equip", "target", "disabled", "hint"))
        for card_id in self.card_ids:
            integer(card_id, "public historical card_id", 1)
        if self.details is not None and not isinstance(self.details, PublicEventDetails):
            raise ContractError("public details must be typed")

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"event_id", "kind", "card_ids"}, {"details"})
        return cls(d["event_id"], d["kind"], tuple(array(d["card_ids"], "public card_ids")),
                   PublicEventDetails.from_dict(d["details"]) if d.get("details") is not None else None)


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
            if c.zone == "overlay" and not any(h.ref == c.attached_to and h.zone == "monster" and h.controller == c.controller
                                               and (h.visibility != "hidden" and h.visibility == c.visibility
                                                    or c.visibility == "public" and h.material_count is not None)
                                               for h in self.cards):
                raise ContractError("overlay material references an absent/different host")
            if c.material_count is not None and sum(m.attached_to == c.ref for m in self.cards) != c.material_count:
                raise ContractError("material count differs from observed attachments")
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
    quantities: tuple[int, ...] = ()
    destinations: tuple[Placement, ...] = ()
    counter_type: int | None = None

    def __post_init__(self):
        if self.description is not None:
            integer(self.description, "effect description", 0, 2**32 - 1)
        if self.operation is not None:
            member(self.operation, "selection operation", ("add", "remove", "finish", "cancel", "shuffle", "sum"))
        if self.destination is not None and not isinstance(self.destination, Placement):
            raise ContractError("destination must be Placement")
        if self.counter_type is not None:
            integer(self.counter_type,"counter type",1,65535)
        if not isinstance(self.quantities, tuple) or len(self.quantities) > 32:
            raise ContractError("counter quantities must be bounded")
        for q in self.quantities:
            integer(q, "counter quantity", 0, 65535)
        if not isinstance(self.destinations, tuple) or len(self.destinations) > 21 or any(not isinstance(p, Placement) for p in self.destinations):
            raise ContractError("destinations must be typed and bounded")
        if len(set(self.destinations)) != len(self.destinations):
            raise ContractError("duplicate destinations")
        if self.description is None and self.operation is None and self.destination is None and not self.quantities and not self.destinations and self.counter_type is None:
            raise ContractError("action details cannot be empty")

    @classmethod
    def from_dict(cls, value):
        d = fields(value, set(), {"description", "operation", "destination", "quantities", "destinations", "counter_type"})
        return cls(d.get("description"), d.get("operation"),
                   Placement.from_dict(d["destination"]) if d.get("destination") is not None else None,
                   tuple(array(d.get("quantities", []), "counter quantities")),
                   tuple(Placement.from_dict(p) for p in array(d.get("destinations", []), "destinations")),d.get("counter_type"))


@dataclass(frozen=True)
class PromptInfo:
    message: int
    minimum: int | None = None
    maximum: int | None = None
    cancelable: bool = False
    finishable: bool = False

    def __post_init__(self):
        integer(self.message, "native prompt message", 0, 255)
        if self.message not in (10, 11, 12, 13, 14, 15, 16, 18, 19, 20, 22, 23, 24, 25, 26, 132, 140, 141, 142, 143):
            raise ContractError("unsupported native prompt message")
        if (self.minimum is None) != (self.maximum is None):
            raise ContractError("both selection bounds are required")
        if self.minimum is not None:
            integer(self.minimum, "selection minimum", 0, 65535)
            integer(self.maximum, "selection maximum", self.minimum, 65535)
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
    scope: str = "search"

    def __post_init__(self):
        text(self.ref, "search reference")
        integer(self.card_id, "search card_id", 1)
        integer(self.owner, "search owner", 0, 1)
        member(self.scope, "choice scope", ("search", "ordering"))

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"ref", "card_id", "owner"}, {"scope"}))


@dataclass(frozen=True)
class SelectionChoice:
    """Window-local selection, with no native index or hidden-zone sequence."""
    ref: str
    controller: int
    zone: str
    visibility: str
    card_id: int | None = None
    owner: int | None = None
    knowledge_ref: str | None = None

    def __post_init__(self):
        text(self.ref, "selection reference")
        integer(self.controller, "selection controller", 0, 1)
        member(self.zone, "selection zone", ("deck", "hand", "monster", "spell_trap", "graveyard", "banished", "extra", "overlay"))
        member(self.visibility, "selection visibility", ("observer", "hidden"))
        if self.visibility == "hidden":
            if self.card_id is not None or self.owner is not None or self.knowledge_ref is not None:
                raise ContractError("opaque selections cannot carry identity or ownership")
        else:
            integer(self.card_id, "offered selection identity", 1, 2**32 - 1)
        if self.owner is not None:
            integer(self.owner, "selection owner", 0, 1)
        if self.knowledge_ref is not None:
            text(self.knowledge_ref,"selection knowledge reference")
            if self.owner is not None:raise ContractError("private confirmation carries no ownership evidence")

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"ref", "controller", "zone", "visibility"}, {"card_id", "owner", "knowledge_ref"}))


@dataclass(frozen=True)
class RevealedCard:
    card_id: int
    controller: int
    zone: str

    def __post_init__(self):
        integer(self.card_id,"revealed identity",1,2**32-1)
        integer(self.controller,"revealed controller",0,1)
        member(self.zone,"private revelation zone",("deck",))

    @classmethod
    def from_dict(cls,value):return cls(**fields(value,{"card_id","controller","zone"}))


@dataclass(frozen=True)
class PrivateReveal:
    """A past legal confirmation to ONE observer, without card positions."""
    ref: str
    observer: int
    cards: tuple[RevealedCard,...]
    message: int = 31

    def __post_init__(self):
        text(self.ref,"private revelation reference")
        integer(self.observer,"private revelation observer",0,1)
        integer(self.message,"private revelation message",31,31)
        if not isinstance(self.cards,tuple) or not 1<=len(self.cards)<=128 or any(not isinstance(c,RevealedCard) for c in self.cards):
            raise ContractError("private revelation requires bounded typed identities")

    @classmethod
    def from_dict(cls,value):
        d=fields(value,{"ref","observer","cards","message"})
        return cls(d['ref'],d['observer'],tuple(RevealedCard.from_dict(c) for c in array(d['cards'],'revealed identities')),d['message'])


@dataclass(frozen=True)
class SumCandidate:
    ref: str
    values: tuple[int, ...]

    def __post_init__(self):
        text(self.ref, "sum reference")
        if not isinstance(self.values, tuple) or not 1 <= len(self.values) <= 2:
            raise ContractError("sum candidate requires one/two native contributions")
        for value in self.values:
            integer(value, "native sum contribution", 0, 2**31 - 1)

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"ref", "values"})
        return cls(d["ref"], tuple(array(d["values"], "sum values")))


@dataclass(frozen=True)
class SumSelection:
    mode: str
    target: int
    minimum_optional: int
    maximum_optional: int
    mandatory: tuple[SumCandidate, ...]
    optional: tuple[SumCandidate, ...]

    def __post_init__(self):
        member(self.mode, "sum mode", ("equal", "minimal_at_least"))
        integer(self.target, "sum target", 1, 2**31 - 1)
        integer(self.minimum_optional, "sum minimum", 0, 128)
        integer(self.maximum_optional, "sum maximum", self.minimum_optional, 128)
        if not isinstance(self.mandatory, tuple) or not isinstance(self.optional, tuple):
            raise ContractError("sum candidate groups must be tuples")
        candidates = self.mandatory + self.optional
        if any(not isinstance(c, SumCandidate) for c in candidates) or len(candidates) > 128 or len({c.ref for c in candidates}) != len(candidates):
            raise ContractError("sum candidates must be bounded and unique")

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"mode", "target", "minimum_optional", "maximum_optional", "mandatory", "optional"})
        return cls(d["mode"], d["target"], d["minimum_optional"], d["maximum_optional"],
                   tuple(SumCandidate.from_dict(v) for v in array(d["mandatory"], "mandatory sum cards")),
                   tuple(SumCandidate.from_dict(v) for v in array(d["optional"], "optional sum cards")))


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
    sum_selection: SumSelection | None = None
    selection_choices: tuple[SelectionChoice, ...] = ()
    private_reveals: tuple[PrivateReveal,...] = ()

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
        if self.sum_selection is not None:
            if not isinstance(self.sum_selection, SumSelection) or self.prompt is None or self.prompt.message != 23:
                raise ContractError("sum metadata requires its typed native prompt")
            visible = {c.ref for c in self.observation.cards if c.card_id is not None}
            if any(c.ref not in visible for c in self.sum_selection.mandatory + self.sum_selection.optional):
                raise ContractError("sum values cannot reveal unobserved/hidden cards")
        for choice in self.search_choices:
            if not isinstance(choice, SearchChoice) or (choice.scope == "search" and choice.owner != self.observation.observer) or choice.ref in refs:
                raise ContractError("search choices must be unique and visible only to the chooser")
            if choice.scope == "ordering" and (self.prompt is None or self.prompt.message != 25):
                raise ContractError("ordering identities require their explicit chooser-only prompt")
            refs.add(choice.ref)
        if not isinstance(self.private_reveals,tuple) or len(self.private_reveals)>32:
            raise ContractError("private revelation history exceeds its bounded contract")
        knowledge={}
        for reveal in self.private_reveals:
            if not isinstance(reveal,PrivateReveal) or reveal.observer!=self.observation.observer or reveal.ref in knowledge:
                raise ContractError("private revelation belongs to another observer or repeats")
            from collections import Counter
            knowledge[reveal.ref]=Counter((c.controller,c.zone,c.card_id) for c in reveal.cards)
        for choice in self.selection_choices:
            if not isinstance(choice, SelectionChoice) or choice.ref in refs:
                raise ContractError("selection choices must be typed and unique")
            if self.prompt is None or self.prompt.message not in (15,26):
                raise ContractError("temporary selections require an explicit selection window")
            if choice.knowledge_ref is not None:
                counts=knowledge.get(choice.knowledge_ref)
                key=(choice.controller,choice.zone,choice.card_id)
                if counts is None or counts[key]<1:raise ContractError("temporary identity lacks its legal confirmation")
                counts[key]-=1
            elif choice.visibility == "observer" and choice.controller != self.observation.observer:
                raise ContractError("opponent temporary identities require legal confirmation evidence")
            refs.add(choice.ref)
        if any(set(action.card_refs) - refs for action in self.actions):
            raise ContractError("action references an unobserved card")
        for action in self.actions:
            if action.details and action.details.quantities:
                if self.prompt is None or self.prompt.message != 22 or len(action.details.quantities) != len(action.card_refs):
                    raise ContractError("counter allocations require one quantity per referenced native candidate")
                if action.details.counter_type is None:
                    raise ContractError("counter allocation requires its native counter type")
            if action.details and action.details.counter_type is not None and (self.prompt is None or self.prompt.message != 22):
                raise ContractError("counter type requires counter selection")
            if action.details and action.details.destinations and (self.prompt is None or self.prompt.message not in (18,24)):
                raise ContractError("multiple destinations require disabled-field prompt")

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"schema_version", "context", "duel_id", "decision_id", "observation", "actions"}, {"search_choices", "prompt", "sum_selection", "selection_choices", "private_reveals"})
        return cls(
            RunContext.from_dict(d["context"]), d["duel_id"], d["decision_id"],
            Observation.from_dict(d["observation"]), tuple(LegalAction.from_dict(a) for a in array(d["actions"], "actions")),
            d["schema_version"], tuple(SearchChoice.from_dict(c) for c in array(d.get("search_choices", []), "search_choices")),
            PromptInfo.from_dict(d["prompt"]) if d.get("prompt") is not None else None,
            SumSelection.from_dict(d["sum_selection"]) if d.get("sum_selection") is not None else None,
            tuple(SelectionChoice.from_dict(c) for c in array(d.get("selection_choices", []), "selection_choices")),
            tuple(PrivateReveal.from_dict(c) for c in array(d.get("private_reveals", []), "private_reveals")),
        )

    def to_dict(self):
        result = asdict(self)
        if not self.search_choices:
            result.pop("search_choices")
        if self.prompt is None:
            result.pop("prompt")
        if self.sum_selection is None:
            result.pop("sum_selection")
        if not self.selection_choices:
            result.pop("selection_choices")
        if not self.private_reveals:result.pop('private_reveals')
        for choice in result.get('selection_choices',[]):
            if choice['knowledge_ref'] is None:choice.pop('knowledge_ref')
        for action in result["actions"]:
            if action["details"] is None:
                action.pop("details")
            else:
                for key in ("quantities", "destinations"):
                    if not action["details"][key]:
                        action["details"].pop(key)
                if action["details"]["counter_type"] is None:
                    action["details"].pop("counter_type")
        for choice in result.get("search_choices", []):
            if choice["scope"] == "search":
                choice.pop("scope")
        for card in result["observation"]["cards"]:
            for key in ("position", "attack", "defense", "attached_to", "material_count"):
                if card[key] is None:
                    card.pop(key)
        for event in result["observation"]["public_history"]:
            if event["details"] is None:
                event.pop("details")
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
