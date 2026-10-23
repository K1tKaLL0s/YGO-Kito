"""Public-catalog cross recall and explicit gap-driven task revisions.

Only environment eligibility is a hard filter. Effect/theme/context axes are
independent evidence scores, not a chain of semantic filters or rule labels.
Chinese source text and static facts are read; effect semantics remain unproven.
"""
from dataclasses import dataclass
import hashlib

from .build_contracts import BuildTask, digest
from .validation import ContractError, array, fields, integer, text


@dataclass(frozen=True)
class CatalogQuery:
    effect_terms: tuple = ()
    theme_terms: tuple = ()
    context_terms: tuple = ()
    preferred_level: int | None = None
    preferred_type: int | None = None
    zone: str = "main"
    limit: int = 8

    def __post_init__(self):
        for axis in (self.effect_terms, self.theme_terms, self.context_terms):
            if not isinstance(axis, tuple) or len(axis) > 8:
                raise ContractError("catalog terms require bounded tuples")
            for term in axis:
                text(term, "catalog term")
                if len(term) > 64:
                    raise ContractError("catalog term too long")
        if self.preferred_level is not None:
            integer(self.preferred_level, "preferred level", 1, 12)
        if self.preferred_type is not None:
            integer(self.preferred_type, "preferred type bits", 1, 2**32 - 1)
        if not any((self.effect_terms, self.theme_terms, self.context_terms,
                    self.preferred_level is not None, self.preferred_type is not None)):
            raise ContractError("catalog query must describe a gap")
        if self.zone not in ("main", "extra", "any"):
            raise ContractError("unknown catalog zone")
        integer(self.limit, "catalog recall limit", 1, 32)

    @classmethod
    def from_dict(cls, value):
        row = dict(fields(value, set(), set(cls.__dataclass_fields__)))
        for name in ("effect_terms", "theme_terms", "context_terms"):
            row[name] = tuple(array(row.get(name, []), name))
        return cls(**row)


def recall(task, assets, query):
    from .build_pipeline import EXTRA_TYPES
    assets.check_task(task)
    if not isinstance(query, CatalogQuery):
        raise ContractError("typed catalog query required")
    hits = []
    for code, row in assets.rows.items():
        if not row["ot"] & 1 or row["type"] & 0x4000 or assets.limits.get(row["alias"] or code, 3) == 0:
            continue
        if query.zone != "any" and bool(row["type"] & EXTRA_TYPES) != (query.zone == "extra"):
            continue
        public = row["name"] + " " + row["desc"]
        facts = []
        for mask, tag in ((0x10, "通常怪兽"), (0x1000, "调整"), (0x2000, "同调"), (0x800000, "超量")):
            if row["type"] & mask:
                facts.append(tag)
        matches = {"effect": [t for t in query.effect_terms if t.casefold() in row["desc"].casefold()],
                   "theme": [t for t in query.theme_terms if t.casefold() in public.casefold()],
                   "context": [t for t in query.context_terms if t.casefold() in (public + " ".join(facts)).casefold()]}
        preferences = []
        if query.preferred_level is not None and row["level"] & 0xff == query.preferred_level:
            preferences.append("preferred_level")
        if query.preferred_type is not None and row["type"] & query.preferred_type == query.preferred_type:
            preferences.append("preferred_type")
        score = 2 * len(matches["effect"]) + 2 * len(matches["theme"]) + len(matches["context"]) + 3 * len(preferences)
        if not score:
            continue
        script = assets.root / "engine-src/scripts" / f"c{code}.lua"
        hits.append({"card_id": code, "name": row["name"], "effect_text": row["desc"],
                     "facts": {"level": row["level"] & 255, "type": row["type"], "race": row["race"], "setcode": row["setcode"]},
                     "axis_matches": matches, "fact_preferences": preferences, "retrieval_score": score,
                     "source": {"cards_sha256": assets.receipt["resources"]["cards"], "effect_text_sha256": digest(row["desc"]),
                                "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest() if script.is_file() else None},
                     "semantic_inference": "lexical-and-static-fact-recall-only; legal route needs core verification"})
    return sorted(hits, key=lambda h: (-h["retrieval_score"], h["card_id"]))[:query.limit]


def expand_pool(task, assets, hits, *, gap):
    """New immutable task/vocabulary revision; no silent checkpoint migration."""
    text(gap, "route gap")
    if len(gap) > 256 or not isinstance(hits, list) or not 1 <= len(hits) <= 32:
        raise ContractError("bounded gap and retrieval hits required")
    codes = []
    for hit in hits:
        integer(hit.get("card_id"), "recalled card", 1, 2**32 - 1)
        row = assets.rows.get(hit["card_id"])
        if (not row or not row["ot"] & 1 or row["type"] & 0x4000
                or assets.limits.get(row["alias"] or row["id"], 3) == 0
                or hit.get("source", {}).get("cards_sha256") != assets.receipt["resources"]["cards"]
                or hit["source"].get("effect_text_sha256") != digest(row["desc"])):
            raise ContractError("retrieval source or environment eligibility differs")
        codes.append(hit["card_id"])
    expanded = sorted(set(task.pool) | set(codes))
    if expanded == list(task.pool):
        raise ContractError("gap recall did not expand the candidate pool")
    payload = task.to_dict()
    payload["pool"] = expanded
    revised = BuildTask.from_dict(payload)
    assets.check_task(revised)
    return revised, {"parent_task_sha256": task.sha256, "task_sha256": revised.sha256,
                     "original_goal_and_hard_constraints_preserved": all(task.to_dict()[k] == revised.to_dict()[k]
                         for k in ("goal", "requirements", "sizes", "environment", "annotations", "source")),
                     "gap": gap, "added_card_ids": sorted(set(expanded) - set(task.pool)),
                     "retrieval_receipts": hits, "vocabulary_revision_requires_new_encoder": True}


def recalled_edits(task, deck, assets, hits, *, limit=8):
    """Propose flexible main-card edits; hard constraints remain authoritative."""
    from .build_contracts import DeckParts
    integer(limit, "recalled edit budget", 1, 32)
    assets.validate(task, deck)
    candidates = []
    for hit in hits:
        code = hit["card_id"]
        if code not in task.pool:
            raise ContractError("recall must explicitly revise the task before candidate edits")
        for removed in sorted(set(deck.main)):
            parts = deck.to_dict()
            parts["main"].remove(removed)
            parts["main"].append(code)
            candidate = DeckParts.from_dict({k: sorted(v) for k, v in parts.items()})
            if candidate != deck and assets.accepts(task, candidate) and candidate not in candidates:
                candidates.append(candidate)
                if len(candidates) == limit:
                    return candidates
    return candidates
