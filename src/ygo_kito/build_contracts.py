"""Bounded building DTOs. Well-formed lists require separate rule validation."""

from dataclasses import asdict, dataclass
from collections import Counter
import hashlib
import json

from .agent_registry import identifier
from .contracts import Versions
from .validation import ContractError, array, canonical_json, fields, integer, member, text

ZONES = ("main", "extra", "side")


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class DeckParts:
    main: tuple[int, ...]
    extra: tuple[int, ...] = ()
    side: tuple[int, ...] = ()

    def __post_init__(self):
        for zone in ZONES:
            cards = getattr(self, zone)
            if not isinstance(cards, tuple) or len(cards) > (60 if zone == "main" else 15):
                raise ContractError("deck parts exceed DTO bounds")
            for code in cards:
                integer(code, "deck card ID", 1, 2**32 - 1)

    @classmethod
    def from_dict(cls, value):
        d = fields(value, set(ZONES))
        return cls(*(tuple(array(d[zone], zone)) for zone in ZONES))

    def to_dict(self):
        return {zone: list(getattr(self, zone)) for zone in ZONES}


@dataclass(frozen=True)
class BuildTask:
    task_id: str
    environment: dict
    goal: dict
    sizes: dict
    pool: tuple[int, ...]
    requirements: tuple[dict, ...]
    annotations: tuple[dict, ...]
    candidate_budget: int = 16
    source: str = "engineering_fixture"
    schema_version: int = 1

    def __post_init__(self):
        integer(self.schema_version, "build schema", 1, 3)
        identifier(self.task_id)
        member(self.source, "build task source", ("engineering_fixture", "user_provided"))
        env = fields(self.environment, {"environment_id", "versions", "authority", "release_cutoff"})
        identifier(env["environment_id"])
        Versions.from_dict(env["versions"])
        member(env["authority"], "environment authority", ("custom", "community", "official"))
        # Historical environments can be recorded elsewhere; this slice must fail closed.
        if env["authority"] != "custom" or env["release_cutoff"] is not None:
            raise ContractError("historical building environment is not verified in this slice")
        goal = fields(self.goal, {"kind", "card_id", "starting_conditions"}, {"route"})
        member(goal["kind"], "building goal", ("normal_summon", "synchro_summon", "xyz_summon"))
        integer(goal["card_id"], "goal card", 1, 2**32 - 1)
        start = fields(goal["starting_conditions"], {"player", "turn", "requires_opening_hand"})
        integer(start["player"], "goal player", 0, 0)
        integer(start["turn"], "goal turn", 1, 1)
        opening = array(start["requires_opening_hand"], "opening-hand requirements")
        integer(len(opening), "opening-hand requirement count", 1, 5)
        for code in opening:
            integer(code, "opening-hand card ID", 1, 2**32 - 1)
        if goal["kind"] == "normal_summon":
            if opening != [goal["card_id"]] or "route" in goal:
                raise ContractError("normal-summon proof requires the declared goal card in the opening hand")
        else:
            if self.schema_version < 2 or (self.schema_version == 2 and "route" not in goal):
                raise ContractError("extra goals require explicit v2 intents or bounded v3 discovery")
            route = array(goal.get("route", []), "route intents")
            if "route" in goal:
                integer(len(route), "route intent count", 1, 16)
            for intent in route:
                fields(intent, {"operation", "card_ids"})
                member(intent["operation"], "route operation", ("activate", "summon", "search", "special_summon"))
                ids = array(intent["card_ids"], "route card IDs")
                integer(len(ids), "route card count", 1, 8 if intent["operation"] == "search" else 1)
                for code in ids:
                    integer(code, "route card", 1, 2**32 - 1)
            if route and route[-1] != {"operation": "special_summon", "card_ids": [goal["card_id"]]}:
                raise ContractError("extra-deck route must end with the declared goal summon")
        fields(self.sizes, set(ZONES))
        for zone in ZONES:
            integer(self.sizes[zone], zone + " size", 40 if zone == "main" else 0, 60 if zone == "main" else 15)
        if not isinstance(self.pool, tuple) or list(self.pool) != sorted(set(self.pool)):
            raise ContractError("candidate pool must be sorted and unique")
        integer(len(self.pool), "building pool size", 1, 128)
        for code in self.pool:
            integer(code, "pool card", 1, 2**32 - 1)
        seen = set()
        for req in self.requirements:
            fields(req, {"zone", "card_id", "minimum", "maximum"})
            member(req["zone"], "requirement zone", ZONES)
            integer(req["card_id"], "required card ID", 1, 2**32 - 1)
            if req["card_id"] not in self.pool or (req["zone"], req["card_id"]) in seen:
                raise ContractError("required card absent from pool or duplicated")
            seen.add((req["zone"], req["card_id"]))
            integer(req["minimum"], "required minimum", 0, 3)
            integer(req["maximum"], "required maximum", req["minimum"], 3)
        goal_zone = "main" if goal["kind"] == "normal_summon" else "extra"
        if not any(r["zone"] == goal_zone and r["card_id"] == goal["card_id"] and r["minimum"] >= 1 for r in self.requirements):
            raise ContractError("goal card requires an explicit minimum in its deck section")
        if goal["kind"] != "normal_summon":
            for code, count in Counter(opening).items():
                if not any(r["zone"] == "main" and r["card_id"] == code and r["minimum"] >= count for r in self.requirements):
                    raise ContractError("opening requirements require explicit main-deck minima")
            if any(code not in self.pool for step in goal.get("route", []) for code in step["card_ids"]):
                raise ContractError("route intent card outside the task pool")
        if any(sum(r["minimum"] for r in self.requirements if r["zone"] == zone) > self.sizes[zone] for zone in ZONES):
            raise ContractError("required minimum counts exceed declared section size")
        integer(len(self.annotations), "context annotation count", 1, 16)
        for annotation in self.annotations:
            fields(annotation, {"tag", "layer", "source", "subject", "condition"})
            member(annotation["layer"], "annotation layer", ("fact", "engineering_goal", "engineering_proxy", "model_inference", "human"))
            member(annotation["subject"], "annotation subject", ("self", "opponent", "both"))
            for key in ("tag", "source", "condition"):
                text(annotation[key], key)
                if len(annotation[key]) > 256:
                    raise ContractError("building context text exceeds budget")
            if "·" not in annotation["tag"]:
                raise ContractError("building tags must preserve the · connector")
        integer(self.candidate_budget, "building candidate budget", 2, 32)
        # Detach nested mutable caller data; model output never replaces the task.
        for name in ("environment", "goal", "sizes", "requirements", "annotations"):
            value = json.loads(canonical_json(getattr(self, name)))
            object.__setattr__(self, name, tuple(value) if name in ("requirements", "annotations") else value)

    @classmethod
    def from_dict(cls, value):
        d = dict(fields(value, {"schema_version", "task_id", "environment", "goal", "sizes", "pool", "requirements", "annotations", "source", "candidate_budget"}))
        for name in ("pool", "requirements", "annotations"):
            d[name] = tuple(array(d[name], name))
        return cls(**d)

    def to_dict(self):
        return json.loads(canonical_json(asdict(self)))

    @property
    def sha256(self):
        return digest(self.to_dict())
