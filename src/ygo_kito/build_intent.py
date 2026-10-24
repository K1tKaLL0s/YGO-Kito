"""Small, non-LLM classifier for the *scope* of a building request.

This is an untrained engineering classifier, not a card-effect parser. A domain
lexicon supplies features; local negation, adjunct roles, explicit scope slots,
and alternatives determine whether those features actually constrain the axis.
Unknown bare names are deliberately unresolved. Confidence is an engineering
routing score and has not been statistically calibrated.
"""

from dataclasses import asdict, dataclass
import math
import re
import unicodedata

from .validation import ContractError


@dataclass(frozen=True)
class DomainTerm:
    canonical: str
    kind: str
    aliases: tuple[str, ...] = ()

    def __post_init__(self):
        if self.kind not in ("theme", "race", "field", "mechanism"):
            raise ContractError("unknown intent lexicon kind")
        if (not isinstance(self.canonical, str) or not self.canonical.strip()
                or len(self.canonical) > 80 or not isinstance(self.aliases, tuple)
                or any(not isinstance(a, str) or not a.strip() or len(a) > 80 for a in self.aliases)):
            raise ContractError("intent terms require bounded names and tuple aliases")


@dataclass(frozen=True)
class DomainLexicon:
    terms: tuple[DomainTerm, ...]

    def __post_init__(self):
        if not isinstance(self.terms, tuple) or len(self.terms) > 4096:
            raise ContractError("intent lexicon requires a bounded tuple")
        aliases = {}
        for term in self.terms:
            if not isinstance(term, DomainTerm):
                raise ContractError("intent lexicon requires DomainTerm entries")
            for alias in (term.canonical, *term.aliases):
                key = _normalize(alias)
                if key in aliases and aliases[key] != (term.canonical, term.kind):
                    raise ContractError("intent lexicon alias has conflicting meanings")
                aliases[key] = (term.canonical, term.kind)

    def extended(self, *terms):
        """Return a new lexicon; caller-owned vocabulary never mutates defaults."""
        return DomainLexicon((*self.terms, *terms))

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"terms"} or not isinstance(value["terms"], list):
            raise ContractError("intent lexicon JSON requires only a terms array")
        terms = []
        for entry in value["terms"]:
            if (not isinstance(entry, dict) or not {"canonical", "kind"} <= set(entry)
                    or set(entry) - {"canonical", "kind", "aliases"}
                    or not isinstance(entry.get("aliases", []), list)):
                raise ContractError("intent lexicon entries require canonical, kind and optional aliases")
            terms.append(DomainTerm(entry["canonical"], entry["kind"], tuple(entry.get("aliases", []))))
        return cls(tuple(terms))

    def to_dict(self):
        return {"terms": [{"canonical": term.canonical, "kind": term.kind, "aliases": list(term.aliases)}
                          for term in self.terms]}


@dataclass(frozen=True)
class IntentClassification:
    kind: str
    confidence: float
    narrow_terms: tuple[str, ...] = ()
    broad_terms: tuple[str, ...] = ()
    excluded_terms: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    classifier_status: str = "engineering_untrained"

    def __post_init__(self):
        if self.kind not in ("narrow", "broad", "ambiguous"):
            raise ContractError("unknown building intent classification")
        if (isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float))
                or not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1):
            raise ContractError("intent confidence must be finite and between zero and one")
        if self.kind != "ambiguous" and self.confidence < 0.5:
            raise ContractError("low-confidence intent must remain ambiguous")
        for name in ("narrow_terms", "broad_terms", "excluded_terms", "reasons"):
            values = getattr(self, name)
            if (not isinstance(values, tuple) or len(values) > 256
                    or any(not isinstance(value, str) or not value.strip()
                           or len(value) > (256 if name == "reasons" else 80) for value in values)):
                raise ContractError("intent evidence requires bounded tuples of text")
        if self.classifier_status != "engineering_untrained":
            raise ContractError("this classifier has no trained weights")

    def to_dict(self):
        result = asdict(self)
        for key in ("narrow_terms", "broad_terms", "excluded_terms", "reasons"):
            result[key] = list(result[key])
        result["confidence_calibrated"] = False
        return result


def _normalize(value):
    return unicodedata.normalize("NFKC", value).casefold().strip()


# Examples seed an extensible vocabulary, not a closed list of supported decks.
DEFAULT_LEXICON = DomainLexicon((
    DomainTerm("珠泪哀歌", "theme", ("珠泪", "tearlaments", "tear")),
    DomainTerm("神碑", "theme", ("runick",)),
    DomainTerm("植物族", "race", ("植物", "plant", "plants")),
    DomainTerm("龙族", "race", ("dragon", "dragons")),
    DomainTerm("堆墓", "mechanism", ("mill", "milling", "送墓", "墓地资源循环")),
    DomainTerm("除外", "mechanism", ("banish", "banishing", "banished")),
    DomainTerm("抽卡", "mechanism", ("draw", "drawing")),
    DomainTerm("特殊召唤", "mechanism", ("特召", "special summon")),
    DomainTerm("检索", "mechanism", ("search", "searching")),
))

_SEGMENTS = re.compile(r"[，,。.!！?？;；\n]|而是|但是|不过|(?<![a-z])but(?![a-z])")
_NEGATED = re.compile(
    r"(?:不要|不用|别用|不想|不希望|不需要|不要求|不考虑|不采用|不使用|不以|排除|避开|禁止|而非|不是|并非|除了|非)"
    r"(?:要|用|玩|打|使用|采用|围绕|选择|构筑|以)?\s*(?:任何)?[\"'‘“「『]?\s*$"
    r"|(?:\bno|\bnot(?:\s+(?:use|want|play))?|\bwithout|\bexclude|\bavoid|\bdon't\s+(?:use|want|play))\s+(?:(?:any|a|an)\s+)?$"
)
_NONBINDING_BEFORE = re.compile(
    r"(?:比如|例如|举例|不只(?:是|用)?|不限于|不限定(?:为|用)?|不排斥|不强求|不限制(?:为|用)?|不限)\s*[\"'‘“「『]?\s*$"
    r"|(?:\be\.g\.|\bfor example|\bnot only|\bnot limited to)\s*$"
)
_NONBINDING_AFTER = re.compile(
    r"^[\"'’”」』]?\s*(?:(?:只|仅)(?:是|作|作为|用作)?(?:外挂|挂件|参考|例子|示例|可选)|可选|(?:只|仅)作为?辅助|(?:不是|不作|不做|不当)(?:为)?主轴|(?:可|可以)(?:作|作为|用作)?外挂|作(?:为)?例子|都可以|随便)"
    r"|^\s*(?:as\s+(?:an?\s+)?(?:optional\s+)?splash|(?:is\s+)?(?:optional|not required)|(?:is\s+)?(?:only|just)\s+(?:a\s+)?(?:splash|example))\b"
)
_NEGATED_AFTER = re.compile(r"^[\"'’”」』]?\s*(?:不要|不用|排除|不考虑|禁止)")
_ANY_AXIS = re.compile(r"不限(?:主题|字段|种族|主轴)|任意(?:主题|字段|种族)|不限定(?:主题|字段|种族)|any\s+(?:archetype|theme|race)|regardless of\s+(?:archetype|theme|race)")
_ALTERNATIVE = re.compile(r"还是|或者|或是|或|到底哪|二选一|\beither\b|\bor\b|/|／")
_COORDINATION = re.compile(r"\s*[\"'’”」』]?\s*(?:和|与|及|以及|或者|或是|或|、|\+|/|and\b|or\b|plus\b)\s*[\"'‘“「『]?\s*")
_UNCLEAR = {"什么", "哪个", "某个", "未知", "任意", "不限", "任何", "所有", "这个", "那个", "特定"}


def _pattern(alias):
    escaped = re.escape(_normalize(alias))
    # Latin aliases must be tokens: 'tear' must not match 'teardown'.
    left = r"(?<![a-z0-9_])" if alias[0].isascii() and alias[0].isalnum() else ""
    right = r"(?![a-z0-9_])" if alias[-1].isascii() and alias[-1].isalnum() else ""
    return re.compile(left + escaped + right)


def _explicit_unknowns(segment):
    """Recognize open vocabulary only in explicit theme/race/field slots."""
    found = []
    patterns = (
        r"[「『\"“]([^」』\"”]{1,40})[」』\"”]\s*(?:主题|字段|族)",
        r"(?:不(?:想|希望)(?:要|使用|采用|围绕|用|玩|打)?|不要(?:使用|用|玩|打)?|不用|不要求|排除|以|围绕|使用|用|想要|想玩|想打|构筑|构建|做)(?:一个|一套|个)?\s*[「『\"“]?([\u3400-\u9fffA-Za-z0-9_-]{1,24}?)[」』\"”]?\s*(?:主题|字段|族)",
        r"^\s*([\u3400-\u9fffA-Za-z0-9_-]{1,24}?)(?:主题|字段|族)(?:卡组|构筑|为主轴|为核心|$)",
        r"(?:theme|archetype|race|field|主题|字段|种族)\s*[:=]\s*([\u3400-\u9fffa-z0-9_-]{1,32})",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, segment):
            name = match.group(1).strip()
            if name not in _UNCLEAR:
                # Keep the semantic slot in the canonical name for stage-2 evidence.
                whole = match.group(0)
                kind = "race" if "族" in whole or "race" in whole else "field" if "字段" in whole or "field" in whole else "theme"
                found.append((name, kind, match.start(1), match.end(1)))
    return found


def classify_build_intent(request, lexicon=None, classifier=None):
    """Classify the requested main-axis scope without calling any model/API.

    A narrow axis plus a mechanism ("植物堆墓") remains narrow. Mechanisms with
    optional theme splashes remain broad. A choice *between* those interpretations
    stays ambiguous. Unknown names need an explicit theme/race/field slot or an
    extended lexicon; this function never invents card metadata for them.
    """
    if classifier is not None:
        from .intent_model import LinearIntentClassifier
        if not isinstance(classifier, LinearIntentClassifier):
            raise ContractError("typed trainable intent classifier required")
        return classifier.predict(request, lexicon=lexicon)
    if not isinstance(request, str) or not request.strip() or len(request) > 4096:
        raise ContractError("building request must contain 1..4096 characters")
    if lexicon is None:
        lexicon = DEFAULT_LEXICON
    if not isinstance(lexicon, DomainLexicon):
        raise ContractError("typed intent lexicon required")
    # Normalize the illustrative abbreviation before sentence segmentation;
    # its periods must not turn an example into an apparent axis requirement.
    normalized = re.sub(r"\be\.g\.", "for example", _normalize(request))
    narrow, broad, excluded, reasons = [], [], [], []
    unresolved_combination = False
    positive_positions = []
    segment_cursor = 0
    for segment in _SEGMENTS.split(normalized):
        segment_start = normalized.find(segment, segment_cursor)
        segment_cursor = segment_start + len(segment)
        if not segment.strip():
            continue
        candidates = []
        for term in lexicon.terms:
            for alias in (term.canonical, *term.aliases):
                for match in _pattern(alias).finditer(segment):
                    candidates.append((term.canonical, term.kind, match.start(), match.end()))
        # Prefer the longest matching alias at a position, avoiding plant/植物 duplicates.
        candidates.sort(key=lambda hit: (hit[2], -(hit[3] - hit[2])))
        accepted = []
        for hit in candidates:
            if any(hit[2] >= prior[2] and hit[3] <= prior[3] for prior in accepted):
                continue
            accepted.append(hit)
        for hit in _explicit_unknowns(segment):
            if not any(hit[2] < old[3] and old[2] < hit[3] for old in accepted):
                accepted.append(hit)
        accepted.sort(key=lambda hit: hit[2])
        previous = None
        for canonical, kind, start, end in accepted:
            before, after = segment[max(0, start - 32):start], segment[end:end + 36]
            before = re.sub(r"(?:theme|archetype|race|field|主题|字段|种族)\s*[:=]\s*$", "", before)
            illustrative = bool(re.match(r"^\s*(?:比如|例如|举例|for example\b|e\.g\.)", segment))
            nonbinding = bool(illustrative or _NONBINDING_BEFORE.search(before) or _NONBINDING_AFTER.search(after))
            if kind == "mechanism" and re.match(r"^\s*(?:都可以|随便)", after):
                nonbinding = bool(illustrative or _NONBINDING_BEFORE.search(before))
            negative = bool(_NEGATED.search(before) or _NEGATED_AFTER.search(after)) and not nonbinding
            if previous is not None:
                previous_end, previous_kind, previous_negative, previous_nonbinding = previous
                link = segment[previous_end:start]
                coordinated = bool(_COORDINATION.fullmatch(link))
                compound = not link.strip() and previous_kind != "mechanism" and kind == "mechanism"
                if coordinated or compound:
                    negative = negative or previous_negative
                    nonbinding = nonbinding or previous_nonbinding
            previous = (end, kind, negative, nonbinding)
            if negative:
                excluded.append(canonical)
                reasons.append("negated:" + canonical)
            elif nonbinding:
                reasons.append("nonbinding_mention:" + canonical)
            else:
                (broad if kind == "mechanism" else narrow).append(canonical)
                positive_positions.append((segment_start + start, segment_start + end, kind, canonical))
                if kind == "mechanism":
                    # An unrecognized coordinated noun may be a missing theme.
                    # Do not let one recognized mechanism erase that uncertainty.
                    coordination = re.search(r"([\u3400-\u9fffa-z0-9_-]{2,24})\s*(?:加|配|混|搭配|\+)\s*$", before)
                    if coordination and not any(old[2] < start and old[3] <= start for old in accepted):
                        unresolved_combination = True
    narrow, broad, excluded = (tuple(dict.fromkeys(values)) for values in (narrow, broad, excluded))
    # A positive and negative constraint for one term needs user resolution.
    conflict = bool(set(excluded) & set((*narrow, *broad))) or unresolved_combination
    if unresolved_combination:
        reasons.append("unresolved_combination_term; extend_lexicon_or_clarify")
    if _ANY_AXIS.search(normalized) and narrow:
        conflict = True
        reasons.append("unrestricted_axis_conflicts_with_positive_axis")
    if len(narrow) > 1 and re.search(r"二选一|选哪|哪(?:种|个)|\beither\b", normalized):
        conflict = True
        reasons.append("alternative_axis_requires_resolution")
    if narrow:
        for alternative in _ALTERNATIVE.finditer(normalized):
            left = [p for p in positive_positions if p[1] <= alternative.start()]
            right = [p for p in positive_positions if p[0] >= alternative.end()]
            if left and right:
                first, second = max(left, key=lambda p: p[1]), min(right, key=lambda p: p[0])
                if first[3] != second[3] and (first[2] != "mechanism" or second[2] != "mechanism"):
                    conflict = True
                    reasons.append("alternative_axis_requires_resolution")
    if conflict:
        kind, confidence = "ambiguous", 0.35
        reasons.append("conflicting_or_alternative_scope")
    elif narrow:
        kind, confidence = "narrow", 0.90
        reasons.append("positive_theme_race_or_field_constraint")
        if broad:
            reasons.append("mechanism_is_goal_within_narrow_axis")
    elif broad:
        kind, confidence = "broad", 0.88
        reasons.append("positive_mechanism_without_required_axis")
    else:
        kind, confidence = "ambiguous", 0.20
        reasons.append("no_positive_scope_evidence; extend_lexicon_or_clarify")
    return IntentClassification(kind, confidence, narrow, broad, excluded, tuple(dict.fromkeys(reasons)))
