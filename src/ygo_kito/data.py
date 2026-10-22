"""Versioned source records. Annotations never overwrite card facts."""

from dataclasses import asdict, dataclass

from .validation import ContractError, fields, integer, language_map, member, strings, text


@dataclass(frozen=True)
class Evidence:
    reference: str
    version: str

    def __post_init__(self):
        text(self.reference, "source reference")
        text(self.version, "source version")

    @classmethod
    def from_dict(cls, value):
        return cls(**fields(value, {"reference", "version"}))


@dataclass(frozen=True)
class CardRecord:
    card_id: int
    names: dict[str, str]
    aliases: tuple[str, ...]
    card_type: str
    effect_texts: dict[str, str]
    source: Evidence

    def __post_init__(self):
        integer(self.card_id, "card_id", 1, 2**63 - 1)
        language_map(self.names, "names")
        language_map(self.effect_texts, "effect_texts")
        strings(list(self.aliases), "aliases")
        text(self.card_type, "card_type")
        if not isinstance(self.source, Evidence):
            raise ContractError("source must be Evidence")

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"card_id", "names", "aliases", "card_type", "effect_texts", "source"})
        return cls(
            d["card_id"], language_map(d["names"], "names"), strings(d["aliases"], "aliases"),
            d["card_type"], language_map(d["effect_texts"], "effect_texts"), Evidence.from_dict(d["source"]),
        )

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Annotation:
    annotation_id: str
    card_id: int
    dimension: str
    layer: str
    tags: tuple[str, ...]
    condition: str
    source: Evidence

    def __post_init__(self):
        text(self.annotation_id, "annotation_id")
        integer(self.card_id, "card_id", 1, 2**63 - 1)
        member(self.dimension, "tag dimension", ("effect", "theme", "role"))
        member(self.layer, "annotation layer", ("fact", "model_inference", "llm_review", "human_correction"))
        strings(list(self.tags), "tags")
        if not self.tags or any("·" in tag for tag in self.tags):
            raise ContractError("store individual tags; join them with · only for display")
        text(self.condition, "condition", empty=True)
        if not isinstance(self.source, Evidence):
            raise ContractError("source must be Evidence")

    @property
    def display_label(self):
        return "·".join(self.tags)

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"annotation_id", "card_id", "dimension", "layer", "tags", "condition", "source"})
        return cls(
            d["annotation_id"], d["card_id"], d["dimension"], d["layer"],
            strings(d["tags"], "tags"), d["condition"], Evidence.from_dict(d["source"]),
        )

    def to_dict(self):
        return asdict(self)

