"""Compare initialized core registrations with the catalog used by construction S3."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ygo_kito.build_pipeline import BuildAssets
from ygo_kito.card_identity import rule_name_id
from ygo_kito.construction_relations import _record_outputs
from ygo_kito.deck_intake import PERIODS
from ygo_kito.effect_mechanisms import MechanismCatalog
from ygo_kito.native_registrations import collect_native_registrations
from ygo_kito.period_runtime import PeriodBuildAssets


def signature(registration):
    return registration["event"], registration["description"], registration["category"]


def construction_records(catalog, code):
    records = []
    for record in catalog.effect_records(code):
        source = record.get("lua_source", {})
        records.append(dict(key=record["effect_key"], scope=record["scope"], text_sha256=record["text_sha256"],
            script_status=source.get("status"), alignment=source.get("alignment"),
            registration_spans=[reg["registration_span"] for reg in source.get("registrations", ())],
            gaps=record["unknown"],
            outputs=[dict(block=op["block_id"], kind=op["kind"]) for _, op in _record_outputs(record) if op is not None]))
    return records


def compare_registrations(assets, initialized):
    lua = assets.effect_lua_source
    catalog = MechanismCatalog(assets)
    counts = Counter()
    cards = {}
    for card, observed in initialized.items():
        code, printed, name = int(card), observed["printed_code"], observed["rule_name"]
        native, diagnostics = observed["native"], observed["diagnostics"]
        static = lua.summarize_effects(printed)
        formal = construction_records(catalog, code)
        signatures = Counter(map(signature, native))
        extracted = Counter((reg.get("event_code") or 0,
            printed * 16 + reg["description_index"] if reg.get("description_index") is not None else 0,
            reg.get("category") or 0) for reg in static["registrations"])
        unmatched = sum((signatures - extracted).values())
        counts.update(cards=1, same_printing_variants=int(code != printed), distinct_rule_names=int(printed != name),
                      core_registrations=len(native), field_registrations=sum(r["scope"] == "field" for r in native),
                      cards_with_diagnostics=int(bool(diagnostics)), core_signatures_without_static_match=unmatched)
        cards[card] = dict(observed, static=static, s3_records=formal, unmatched_signatures=unmatched)
    return dict(source=lua.binding, resources=assets.receipt, period=getattr(assets, "period_context", None),
                statistics=dict(counts), cards=cards)


def compare_versions(previous, current):
    if previous.get("schema_version") != 1:
        raise ValueError("incompatible prior registration audit")
    before, after = previous["cards"], current["cards"]
    prior_resources = previous["resources"]["resources"]
    current_resources = current["resources"]["resources"]
    changed_resources = {key: dict(previous=prior_resources.get(key), current=current_resources.get(key))
        for key in sorted(prior_resources.keys() | current_resources.keys())
        if prior_resources.get(key) != current_resources.get(key)}

    def card_content(card):
        # The bundle identity already has its own comparison. Keep each
        # script's bytes, callback sources, registrations and S3 records here.
        static = {k: v for k, v in card["static"].items() if k not in ("extractor", "scripts_sha256")}
        return dict(card, static=static)

    return dict(previous_source=previous["source"], previous_period=previous["period"],
                changed_resources=changed_resources, added=sorted(after.keys() - before.keys(), key=int),
                removed=sorted(before.keys() - after.keys(), key=int),
                changed=sorted((code for code in before.keys() & after.keys()
                                if card_content(before[code]) != card_content(after[code])), key=int))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True, help="Existing locked native resource root")
    parser.add_argument("--output", type=Path, required=True, help="Directory for the audit artifacts")
    parser.add_argument("--period", choices=PERIODS)
    parser.add_argument("--environment", type=Path)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--against", type=Path, help="Previous rule-sources.json to compare")
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    if args.period:
        if args.environment is None or args.workspace is None:
            parser.error("--period requires --environment and --workspace")
        assets = PeriodBuildAssets(args.assets, args.period, json.loads(args.environment.read_text(encoding="utf-8")),
                                   args.workspace, evidence_source="engineering_fixture")
        available = assets.allowed_card_ids
    else:
        if args.environment is not None or args.workspace is not None:
            parser.error("--environment and --workspace require --period")
        assets = BuildAssets(args.assets)
        available = assets.rows
    codes = sorted(code for code in available if assets.rows[code]["ot"] & 1
                   and not assets.rows[code]["type"] & 0x4000
                   and (not args.period or assets.limits.get(rule_name_id(assets.rows, code), 3) > 0))
    initialized = collect_native_registrations(assets, codes, args.output, compiler=args.compiler,
                                               raw=args.output / "registrations.tsv")
    result = compare_registrations(assets, initialized)
    result["schema_version"] = 1
    if args.against:
        result["version_comparison"] = compare_versions(json.loads(args.against.read_text(encoding="utf-8")), result)
    path = args.output / "rule-sources.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps(dict(report=str(path), **result["statistics"]), ensure_ascii=False))
    return int(any(result["statistics"].get(key) for key in
                   ("cards_with_diagnostics", "core_signatures_without_static_match")))


if __name__ == "__main__":
    sys.exit(main())
