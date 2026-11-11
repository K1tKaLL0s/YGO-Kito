"""Transitive source isolation and distinct generalization protocols; no models."""
from collections import Counter, defaultdict
from datetime import date
import random
import re

from .contracts import digest

GENERALIZATION_PROTOCOLS = ("unseen_deck", "unseen_receiver", "unseen_card", "cross_period")
SPLITS = ("train", "validation", "test")
SPLIT_VERSION = "axis-source-components-v3"


def _metadata(row):
    return dict(row, **row.get("provenance", {}))


def _input(row):
    value = row.get("observations", row.get("example", row))
    value = value.get("input", value)
    return value.get("observations", value)


def _pairs(value):
    if value is None:
        return None
    pairs = value.items() if isinstance(value, dict) else value
    result = Counter()
    for item in pairs:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError("deck counts require card/count pairs")
        code, count = item
        code = int(code)
        if code <= 0 or type(count) is not int or count <= 0:
            raise ValueError("positive deck counts required")
        result[code] += count
    return tuple(sorted(result.items()))


def deck_signature(row):
    obs = _input(row)
    deck = obs.get("deck", row.get("deck"))
    if deck is None:
        deck = {s: row.get(s) for s in ("main", "extra", "side")}
    if hasattr(deck, "to_dict"):
        deck = deck.to_dict()
    context = obs.get("analysis_context", {})
    meta = _metadata(row)
    return (context.get("format", meta.get("format", "unknown")),
            context.get("period", meta.get("period", "unknown")),
            tuple(_pairs(deck.get(s)) for s in ("main", "extra", "side")))


def deck_signatures(row):
    yield deck_signature(row)
    if row.get("comparison") is not None:
        yield deck_signature({"observations":row["comparison"]["right"],"provenance":row.get("provenance",{})})


def identity_tokens(row):
    meta = _metadata(row)
    namespace = str(meta.get("source_namespace", "legacy"))
    tokens = set()
    for key in ("source_rowid", "reference", "reference_id", "case_id", "source_deck_id", "match_id", "event_id", "tournament_id"):
        if meta.get(key) is not None and meta[key] != "":
            # reference/reference_id identify the same kind of reference.
            kind = "reference" if key == "reference_id" else key
            tokens.add(f"{kind}:{namespace}:{meta[key]}")
    for key in ("record_id", "parent_id"):
        if meta.get(key):
            owner_namespace = str(meta.get("parent_namespace",namespace)) if key == "parent_id" else namespace
            tokens.add(f"record:{owner_namespace}:{meta[key]}")
    for key in ("parent_ids", "derived_from"):
        values = meta.get(key, ())
        if isinstance(values, str):
            values = (values,)
        tokens.update(f"record:{namespace}:{v}" for v in values)
    # Identical known Main/Extra with equally unknown Side are conservatively
    # one source component; None still differs from a reviewed empty Side.
    for fmt,period,parts in deck_signatures(row):
        if parts[0] is not None and parts[1] is not None:
            tokens.add("deck:" + digest((fmt, period, parts)))
    if not tokens:
        raise ValueError("row lacks source identity or a complete deck")
    return tokens


def leakage_group(row):
    """A single-row anchor; use build_leakage_groups for component identity."""
    return min(identity_tokens(row))


def build_leakage_groups(rows, *, near_duplicate_swaps=2, max_near_pairs=1000000):
    if type(near_duplicate_swaps) is not int or near_duplicate_swaps < 0 or type(max_near_pairs) is not int or max_near_pairs < 0:
        raise ValueError("nonnegative near-duplicate budgets required")
    parents = list(range(len(rows)))
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    def join(a, b):
        a, b = root(a), root(b)
        if a != b:
            parents[max(a, b)] = min(a, b)
    tokens_by_row, owners, reasons = [], {}, []
    for i, row in enumerate(rows):
        tokens = identity_tokens(row)
        tokens_by_row.append(tokens)
        for token in sorted(tokens):
            if token in owners:
                join(i, owners[token])
                reasons.append(dict(left=i, right=owners[token], relation="shared_identity", identity=token))
            else:
                owners[token] = i
    buckets = defaultdict(dict)
    for i, row in enumerate(rows):
        for fmt,period,parts in deck_signatures(row):
            if fmt in (None,"unknown") or period in (None,"unknown") or any(p is None for p in parts):
                continue
            totals=tuple(sum(n for _,n in p) for p in parts)
            buckets[(fmt,period,totals)].setdefault(parts,i)
    comparisons = 0
    for key in sorted(buckets):
        representatives = sorted(buckets[key].items())
        for offset, (left, i) in enumerate(representatives):
            for right, j in representatives[offset + 1:]:
                if root(i) == root(j):
                    continue
                comparisons += 1
                if comparisons > max_near_pairs:
                    raise ValueError("near-duplicate budget exhausted; grouping is not complete")
                distances = []
                for a, b in zip(left, right):
                    aa, bb = dict(a), dict(b)
                    distances.append(sum(abs(aa.get(c, 0) - bb.get(c, 0)) for c in aa.keys() | bb.keys()) / 2)
                if all(v <= near_duplicate_swaps for v in distances):
                    join(i, j)
                    reasons.append(dict(left=i, right=j, relation="near_duplicate", swaps=distances))
    components = defaultdict(list)
    for i in range(len(rows)):
        components[root(i)].append(i)
    groups, row_groups = {}, [None] * len(rows)
    for members in components.values():
        group = "group:" + digest(sorted({t for i in members for t in tokens_by_row[i]}))[:24]
        groups[group] = members
        for i in members:
            row_groups[i] = group
    return dict(version=SPLIT_VERSION, groups=dict(sorted(groups.items())), row_groups=row_groups,
                relations=reasons, near_pairs=comparisons, complete=True)


def group_rows(rows):
    return build_leakage_groups(rows)["groups"]


def referenced_cards(row):
    cards = {c for signature in deck_signatures(row) for p in signature[2] if p is not None for c, _ in p}
    def scan(value):
        if isinstance(value, dict):
            for k, v in value.items():
                scan(k)
                scan(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                scan(v)
        elif isinstance(value, str) and re.fullmatch(r"card:[1-9][0-9]*", value):
            cards.add(int(value[5:]))
    obs = _input(row)
    for key in ("unit", "unit_definition"):
        unit = obs.get(key)
        if isinstance(unit, dict):
            cards.update(int(c) for c, _ in unit.get("members", ()))
    raw = row.get("observations", {})
    for code in raw.get("card_rows", {}):
        cards.add(int(code))
    insertion = obs.get("insertion")
    if insertion:
        for change in ("add","remove"):
            for section in ("main","extra","side"):
                cards.update(c for c,_ in _pairs(insertion[change][section]))
    scan(row)
    if row.get("comparison") is not None:
        cards.update(referenced_cards({"observations":row["comparison"]["right"]}))
    cards.update(int(c) for c in _metadata(row).get("reserved_card_ids", ()))
    return cards


def _receiver(row, heldout=()):
    meta = _metadata(row)
    values = meta.get("receiver_family", meta.get("receiver_signature"))
    if values in (None, "", "unknown", [], ()):
        return None
    actual = set(values) if isinstance(values,(list,tuple)) else {values}
    for requested in heldout:
        if isinstance(requested,dict) and "mechanism_signature" in requested:
            family = requested.get("receiver_family",requested.get("receiver_signature"))
            expected = set(family) if isinstance(family,(list,tuple)) else {family}
            if actual == expected and meta.get("mechanism_signature") in (None,"","unknown"):
                return None
    return digest((sorted(values) if isinstance(values, (list, tuple)) else values, meta.get("mechanism_signature")))


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _receiver_heldout(row, heldout):
    meta = _metadata(row)
    family = meta.get("receiver_family",meta.get("receiver_signature"))
    actual = set(family) if isinstance(family,(list,tuple)) else {family} if family is not None else set()
    for requested in heldout:
        if isinstance(requested,dict):
            required = requested.get("receiver_family",requested.get("receiver_signature"))
            expected = set(required) if isinstance(required,(list,tuple)) else {required}
            if actual == expected and ("mechanism_signature" not in requested or meta.get("mechanism_signature") == requested["mechanism_signature"]):
                return True
        elif requested in actual:
            return True
    return False


def _availability_dates(row):
    meta = _metadata(row)
    result = [_date(meta.get("available_at"))]
    def has_known(value):
        if isinstance(value,dict):
            return value.get("status") == "known" or any(has_known(v) for v in value.values())
        return isinstance(value,(list,tuple)) and any(has_known(v) for v in value)
    if has_known(row.get("targets",{})) or any(v is not None for v in row.get("labels",())):
        result.append(_date(meta.get("label_available_at",meta.get("annotation_available_at"))))
    if "catalog_available_at" in meta:
        result.append(_date(meta["catalog_available_at"]))
    return result


def assign_group_splits(rows, *, train=0.6, dev=0.2, test=0.2, seed=17, protocol="unseen_deck",
                        heldout_receivers=(), heldout_cards=(), heldout_combinations=(), time_cutoff=None,
                        require_three=True, near_duplicate_swaps=2, max_near_pairs=1000000):
    fractions = (train, dev, test)
    if any(type(v) not in (int, float) or not 0 <= v <= 1 for v in fractions) or abs(sum(fractions) - 1) > 1e-9:
        raise ValueError("split fractions must be nonnegative and sum to one")
    if protocol not in GENERALIZATION_PROTOCOLS:
        raise ValueError("unknown generalization protocol")
    grouping = build_leakage_groups(rows, near_duplicate_swaps=near_duplicate_swaps, max_near_pairs=max_near_pairs)
    groups = grouping["groups"]
    if require_three and len(groups) < 3:
        raise ValueError("at least three leakage groups are required")
    cutoff = _date(time_cutoff)
    if protocol == "cross_period" and cutoff is None:
        raise ValueError("cross_period requires an explicit ISO date cutoff")
    if protocol == "unseen_receiver" and not heldout_receivers:
        raise ValueError("unseen_receiver requires explicit heldout receiver signatures")
    if protocol == "unseen_card" and not heldout_cards and not heldout_combinations:
        raise ValueError("unseen_card requires explicit heldout cards/combinations")
    cards = set(map(int, heldout_cards))
    combos = [set(map(int, v)) for v in heldout_combinations]
    if any(not v for v in combos):
        raise ValueError("heldout combinations must not be empty")
    assigned, available = {}, []
    for group, indices in groups.items():
        subset = [rows[i] for i in indices]
        receivers = [_receiver(r,heldout_receivers) for r in subset]
        present = set().union(*(referenced_cards(r) for r in subset))
        dates = [d for r in subset for d in _availability_dates(r)]
        if protocol == "unseen_receiver" and any(_receiver_heldout(r,heldout_receivers) for r in subset):
            assigned[group] = "test"
        elif protocol == "unseen_receiver" and any(r is None for r in receivers):
            assigned[group] = "quarantine"
        elif protocol == "unseen_card" and (bool(cards & present) or any(v <= present for v in combos)):
            assigned[group] = "test"
        elif protocol == "cross_period" and any(d is None for d in dates):
            assigned[group] = "quarantine"
        elif protocol == "cross_period" and any(d > cutoff for d in dates):
            assigned[group] = "test"
        else:
            available.append(group)
    random.Random(seed).shuffle(available)
    total = len(available)
    if protocol == "unseen_deck":
        n_train, n_dev = int(total * train), int(total * dev)
        if total and train > 0:
            n_train = max(1,n_train)
        if total > n_train and dev > 0:
            n_dev = max(1,n_dev)
        if total >= sum(v > 0 for v in fractions):
            n_train = max(int(train > 0), n_train)
            n_dev = max(int(dev > 0), n_dev)
            if test > 0 and n_train + n_dev >= total:
                if n_train > int(train > 0):
                    n_train -= 1
                else:
                    n_dev -= 1
        for i, group in enumerate(available):
            assigned[group] = "train" if i < n_train else "validation" if i < n_train + n_dev else "test"
    else:
        ratio = train / (train + dev) if train + dev else 0
        n_train = int(total * ratio)
        if train > 0 and total:
            n_train = max(1, n_train)
        if dev > 0 and total > 1:
            n_train = min(n_train, total - 1)
        for i, group in enumerate(available):
            assigned[group] = "quarantine" if train + dev == 0 else "train" if i < n_train else "validation"
    labels = [assigned[g] for g in grouping["row_groups"]]
    summary = {s: dict(groups=0, rows=0) for s in SPLITS}
    if "quarantine" in assigned.values():
        summary["quarantine"] = dict(groups=0, rows=0)
    for group, indices in groups.items():
        summary[assigned[group]]["groups"] += 1
        summary[assigned[group]]["rows"] += len(indices)
    return labels, summary
