"""Concrete catalog binding with separate recall and source-bound evidence.

This adapter reads the pinned catalog for the existing candidate/ranking
pipeline. Lexical matches propose cards; they never certify a functional effect.
Only race/setcode facts and explicit current-source assessments support tags.
Coarse connectors remain unverified ideas, not executable card-effect rules.
"""

from dataclasses import asdict, dataclass
import heapq
import re
import unicodedata

from .build_contracts import BuildTask, DeckParts, digest
from .construction_fill import FillProposal, NodeBinding, NodeTextReview, TextEvidence
from .construction_logic import ConstructionLogic, LogicNode, LogicTag, short
from .validation import ContractError, array, fields, integer, member


def _sha(value, label):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ContractError(label + " requires a lowercase SHA-256")


@dataclass(frozen=True)
class PublicFactTag:
    tag: LogicTag
    field: str
    value: int
    source: str

    def __post_init__(self):
        if not isinstance(self.tag, LogicTag):
            raise ContractError("typed public-fact tag required")
        expected = {"race": "race_any", "field": "setcode"}.get(self.tag.dimension)
        if expected is None or self.field != expected:
            raise ContractError("only race/race_any and field/setcode are static tag facts")
        integer(self.value, "public tag mask", 1, 65535 if self.field == "setcode" else 2**32 - 1)
        short(self.source, "public tag mapping source", 256)

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"tag", "field", "value", "source"})
        return cls(LogicTag.from_dict(d["tag"]), d["field"], d["value"], d["source"])


@dataclass(frozen=True)
class CardTagAssessment:
    card_id: int
    tag: LogicTag
    status: str
    cards_sha256: str
    effect_text_sha256: str
    quote: str
    source: str
    note: str

    def __post_init__(self):
        integer(self.card_id, "assessed card ID", 1, 2**32 - 1)
        if not isinstance(self.tag, LogicTag):
            raise ContractError("typed assessed tag required")
        member(self.status, "card tag assessment", ("satisfied", "unsatisfied", "unknown"))
        _sha(self.cards_sha256, "cards source")
        _sha(self.effect_text_sha256, "effect text source")
        short(self.quote, "assessment excerpt", 512)
        short(self.source, "assessment source", 256)
        short(self.note, "assessment explanation", 1024)

    @classmethod
    def from_dict(cls, value):
        d = dict(fields(value, {"card_id", "tag", "status", "cards_sha256", "effect_text_sha256",
                                "quote", "source", "note"}))
        d["tag"] = LogicTag.from_dict(d["tag"])
        return cls(**d)


DEFAULT_FACT_TAGS = (
    PublicFactTag(LogicTag("race", "植物族"), "race_any", 0x4000, "pinned-cards-race-schema"),
    PublicFactTag(LogicTag("race", "龙族"), "race_any", 0x2000, "pinned-cards-race-schema"),
)


@dataclass(frozen=True)
class BindingResult:
    status: str
    proposal: FillProposal | None
    reasons: tuple[str, ...]
    node_candidates: tuple[dict, ...]

    def to_dict(self):
        from .validation import canonical_json, parse_json
        return parse_json(canonical_json(asdict(self)))


def _lexical(term, value):
    term = unicodedata.normalize("NFKC", term).casefold()
    value = unicodedata.normalize("NFKC", value).casefold()
    left = r"(?<![a-z0-9_])" if term[0].isascii() and term[0].isalnum() else ""
    right = r"(?![a-z0-9_])" if term[-1].isascii() and term[-1].isalnum() else ""
    return re.search(left + re.escape(term) + right, value) is not None


class CatalogBindingAdapter:
    """An actual binding_provider and text_reviewer over the pinned catalog.

    Call ``bind`` for structured failure/recall details. ``__call__`` implements
    the existing binding_provider(graph, task, deck) protocol; an unmatched graph
    raises ContractError with the reason instead of fabricating a proposal.
    ``reviewer`` implements text_reviewer(node, public_cards). Assessment records
    are explicit facts/reviews supplied by the application, never learned claims.
    """

    def __init__(self, assets, *, fact_tags=DEFAULT_FACT_TAGS, assessments=(), recall_terms=None):
        self.assets = assets
        try:
            self.cards_sha256 = assets.receipt["resources"]["cards"]
        except (AttributeError, KeyError, TypeError) as error:
            raise ContractError("binding requires a pinned cards source receipt") from error
        _sha(self.cards_sha256, "pinned cards source")
        if (not isinstance(fact_tags, tuple) or len(fact_tags) > 256
                or any(not isinstance(f, PublicFactTag) for f in fact_tags)
                or len({f.tag for f in fact_tags}) != len(fact_tags)):
            raise ContractError("distinct typed public-fact tag mappings required")
        if (not isinstance(assessments, tuple) or len(assessments) > 4096
                or any(not isinstance(a, CardTagAssessment) for a in assessments)
                or len({(a.card_id, a.tag) for a in assessments}) != len(assessments)):
            raise ContractError("distinct typed card/tag assessments required")
        self.fact_tags = {f.tag: f for f in fact_tags}
        self.assessments = {(a.card_id, a.tag): a for a in assessments}
        if recall_terms is None:
            recall_terms = {}
        if not isinstance(recall_terms, dict) or len(recall_terms) > 256:
            raise ContractError("bounded tag-to-recall-term mapping required")
        self.recall_terms = {}
        for tag, terms in recall_terms.items():
            if not isinstance(tag, LogicTag) or not isinstance(terms, tuple) or not 1 <= len(terms) <= 8:
                raise ContractError("recall terms require typed tags and bounded tuples")
            for term in terms:
                short(term, "recall term", 80)
            self.recall_terms[tag] = tuple(terms)

    @classmethod
    def from_dict(cls, assets, value):
        d = fields(value, set(), {"fact_tags", "assessments", "recall_terms"})
        facts = (tuple(PublicFactTag.from_dict(f) for f in array(d["fact_tags"], "fact tags"))
                 if "fact_tags" in d else DEFAULT_FACT_TAGS)
        assessments = tuple(CardTagAssessment.from_dict(a) for a in array(d.get("assessments", []), "assessments"))
        terms = {}
        for entry in array(d.get("recall_terms", []), "recall terms"):
            e = fields(entry, {"tag", "terms"})
            tag = LogicTag.from_dict(e["tag"])
            if tag in terms:
                raise ContractError("duplicate recall tag")
            terms[tag] = tuple(array(e["terms"], "tag terms"))
        return cls(assets, fact_tags=facts, assessments=assessments, recall_terms=terms)

    def to_dict(self):
        from .validation import canonical_json, parse_json
        return parse_json(canonical_json({"fact_tags": [asdict(f) for f in self.fact_tags.values()],
            "assessments": [asdict(a) for a in self.assessments.values()],
            "recall_terms": [{"tag": asdict(tag), "terms": list(terms)}
                             for tag, terms in self.recall_terms.items()]}))

    def _tag_status(self, row, tag):
        from .build_semantics import matches
        fact = self.fact_tags.get(tag)
        if fact is not None:
            satisfied = matches(row, {"field": fact.field, "value": fact.value})
            return ("satisfied" if satisfied else "unsatisfied"), "public-fact:" + fact.source
        assessment = self.assessments.get((row["id"], tag))
        if assessment is None:
            return "unknown", "no source-bound assessment for " + tag.value
        if (assessment.cards_sha256 != self.cards_sha256 or assessment.effect_text_sha256 != digest(row["desc"])
                or assessment.quote not in row["desc"]):
            return "unknown", "assessment source mismatch for " + tag.value
        return assessment.status, assessment.source + ":" + assessment.note

    def reviewer(self, node, cards):
        """Check every bound card/tag; lexical recall is deliberately ignored."""
        if not isinstance(node, LogicNode) or not isinstance(cards, tuple) or not cards:
            raise ContractError("typed node and nonempty public-card tuple required")
        evidence, statuses, notes = [], [], []
        for card in cards:
            row = self.assets.rows.get(card.get("id")) if isinstance(card, dict) else None
            if row is None or any(card.get(k) != row.get(k) for k in ("id", "desc", "race", "setcode")):
                return NodeTextReview(node.node_id, "unknown", (), (), "catalog-binding-adapter",
                                      "public cards do not match the pinned catalog")
            if not isinstance(row["desc"], str) or not row["desc"].strip():
                return NodeTextReview(node.node_id, "unknown", (), (), "catalog-binding-adapter",
                                      "current card text is empty; no source-bound text evidence")
            evidence.append(TextEvidence(row["id"], digest(row["desc"]), row["desc"].strip()[:512]))
            for tag in node.tags:
                status, note = self._tag_status(row, tag)
                statuses.append(status)
                notes.append(note)
        status = "unsatisfied" if "unsatisfied" in statuses else "unknown" if "unknown" in statuses else "satisfied"
        return NodeTextReview(node.node_id, status, node.tags, tuple(evidence), "catalog-binding-adapter",
                              "; ".join(dict.fromkeys(notes))[:1024])

    def bind(self, graph, task, deck, *, required_tags=()):
        if not isinstance(graph, ConstructionLogic) or not isinstance(task, BuildTask) or not isinstance(deck, DeckParts):
            raise ContractError("typed graph, task and concrete deck required")
        self.assets.validate(task, deck)
        candidates, details = {}, []
        for node in graph.nodes:
            hits = []
            for code in sorted(set(deck.main + deck.extra)):
                row = self.assets.rows[code]
                evaluations = [self._tag_status(row, tag) for tag in node.tags]
                statuses = [s for s, _ in evaluations]
                terms = [term for tag in node.tags for term in self.recall_terms.get(tag, (tag.value,))
                         if _lexical(term, row["name"] + " " + row["desc"])]
                if "unsatisfied" in statuses or not ("satisfied" in statuses or terms):
                    continue
                status = "supported" if all(s == "satisfied" for s in statuses) else "unknown"
                hits.append({"card_id": code, "status": status, "lexical_terms": sorted(set(terms)),
                             "supported_tags": sum(s == "satisfied" for s in statuses),
                             "reasons": list(dict.fromkeys(note for _, note in evaluations))})
            hits.sort(key=lambda h: (h["status"] != "supported", -h["supported_tags"], -len(h["lexical_terms"]), h["card_id"]))
            details.append({"node_id": node.node_id, "candidates": hits})
            if hits:
                candidates[node.node_id] = hits[0]
        # Prefer a supported path, then the shortest lexical proposal. These are
        # graph paths only; neither path selection nor card reuse proves a CB.
        outgoing = {n.node_id: [] for n in graph.nodes}
        for edge in sorted(graph.connectors, key=lambda e: e.connector_id):
            outgoing[edge.source].append(edge)
        queue = []
        for entry in graph.entry_nodes:
            if entry in candidates:
                heapq.heappush(queue, (int(candidates[entry]["status"] != "supported"), 0, (), (entry,)))
        paths = {}
        while queue:
            unknowns, length, edges, nodes = heapq.heappop(queue)
            last = nodes[-1]
            if last in paths:
                continue
            paths[last] = (nodes, edges)
            for edge in outgoing[last]:
                if edge.target in candidates and edge.target not in paths:
                    heapq.heappush(queue, (unknowns + int(candidates[edge.target]["status"] != "supported"),
                                          length + 1, (*edges, edge.connector_id), (*nodes, edge.target)))
        missing = tuple(g for g in graph.goal_nodes if g not in paths)
        if missing:
            return BindingResult("unmatched", None, ("no catalog-supported or lexical path to goal nodes: " + ", ".join(missing),), tuple(details))
        if not isinstance(required_tags,tuple) or any(not isinstance(t,LogicTag) for t in required_tags):
            raise ContractError("typed required logic tags required")
        node_map={n.node_id:n for n in graph.nodes}
        targets=set(graph.goal_nodes)
        for tag in required_tags:
            covered={t for goal in targets for node in paths[goal][0] for t in node_map[node].tags}
            if tag in covered:continue
            choices=[n for n in paths if tag in node_map[n].tags]
            if not choices:
                return BindingResult("unmatched",None,("no reachable binding covers required tag: "+tag.value,),tuple(details))
            targets.add(min(choices,key=lambda n:(candidates[n]["status"]!="supported",len(paths[n][1]),n)))
        active = {n for goal in targets for n in paths[goal][0]}
        edge_ids = tuple(sorted({e for goal in targets for e in paths[goal][1]}))
        bindings = tuple(NodeBinding(n.node_id, (candidates[n.node_id]["card_id"],)) for n in graph.nodes if n.node_id in active)
        proposal = FillProposal(deck, bindings, edge_ids, graph.sha256, task.sha256)
        uncertain = tuple(n.node_id for n in graph.nodes if n.node_id in active and candidates[n.node_id]["status"] != "supported")
        return BindingResult("proposed_unknown" if uncertain else "bound", proposal,
                             (("functional/effect tags remain unknown for nodes: " + ", ".join(uncertain),) if uncertain else
                              ("public facts/source-bound assessments support node tags; connectors still need engine verification",)),
                             tuple(details))

    def __call__(self, graph, task, deck):
        result = self.bind(graph, task, deck)
        if result.proposal is None:
            raise ContractError("catalog binding unmatched: " + "; ".join(result.reasons))
        return result.proposal
