"""Audit locked registrations and their use in supplied native S3 evaluations."""

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ygo_kito.build_pipeline import BuildAssets
from ygo_kito.build_contracts import digest
from ygo_kito.card_identity import rule_name_id
from ygo_kito.construction_layer_flow import NORMALIZATION_VERSION, functional_asset_version
from ygo_kito.construction_quality import validate_evaluation
from ygo_kito.deck_intake import PERIODS
from ygo_kito.effect_mechanisms import MechanismCatalog
from ygo_kito.native_registrations import collect_native_registrations
from ygo_kito.period_runtime import PeriodBuildAssets


def evaluation_coverage(evaluations, asset_version):
    coverage, uses, registrations = defaultdict(dict), defaultdict(list), {}
    for quality in evaluations:
        validate_evaluation(quality)
        source = quality["native_rule_evidence"]
        if (source.get("authority") != "locked_period_core" or quality["asset_version"] != asset_version
                or quality["normalization_version"] != NORMALIZATION_VERSION):
            raise ValueError("evaluation belongs to different rules or uses a different rule authority")
        evaluation = quality["evaluation_id"]
        for code, card in quality.get("static_rules", {}).items():
            for row in card["registrations"]:
                coverage[code, digest(row["rule"])][evaluation] = row["status"]
        for receipt in source["receipts"]:
            for case in receipt["native_executions"]:
                rule = case["registration"]
                key = str(case["card"]), digest(rule)
                registrations[key] = rule
                coverage[key].setdefault(evaluation, case["status"])
        for use, detail in quality["use_details"].items():
            if detail["relation"]["status"] != "supported":
                continue
            proof = detail["inventory_checks"].get("native")
            if proof:
                key = str(detail["card_id"]), digest(proof["registration"])
                uses[key].append(dict(evaluation=evaluation, use=use, receipt=proof["receipt"], scope=proof["scope"]))
            elif rule := detail.get("rule_registration"):
                key = str(detail["card_id"]), digest(rule)
                uses[key].append(dict(evaluation=evaluation, use=use, scope=use.split(":")[-1]
                    if use.endswith((":going_first", ":going_second")) else "resident"))
    return coverage, uses, registrations


def compare_registrations(assets, initialized, evaluations=()):
    lua = assets.effect_lua_source
    asset_version = functional_asset_version(MechanismCatalog(assets)) if evaluations else None
    coverage, uses, registrations = evaluation_coverage(evaluations, asset_version)
    counts = Counter()
    cards = {}
    initial = set()
    for card, observed in initialized.items():
        printed, name = observed["printed_code"], observed["rule_name"]
        native, diagnostics = observed["native"], observed["diagnostics"]
        signatures = [digest(rule) for rule in native]
        multiplicity = Counter(signatures)
        construction = []
        for ordinal, signature in enumerate(signatures):
            key = card, signature
            initial.add(key)
            searched = coverage.get(key, {})
            supported = uses.get(key, [])
            if searched or supported:
                classified = set(searched.values())
                if multiplicity[signature] > 1:
                    status = "ambiguous_registration"
                elif "unknown" in classified:
                    status = "unmapped_static_rule"
                elif classified == {"activation_only"}:
                    status = "activation_only"
                elif supported:
                    status = "supported_s3_use"
                elif classified & {"function", "alternate_trigger"}:
                    status = "classified_static_rule"
                else:
                    status = "without_supported_s3_use"
                construction.append(dict(ordinal=ordinal, status=status, evaluations=searched, uses=supported))
                counts[status] += 1
            else:
                counts["initialized_without_evaluation"] += 1
        counts.update(cards=1, same_printing_variants=int(int(card) != printed), distinct_rule_names=int(printed != name),
                      core_registrations=len(native), field_registrations=sum(r["scope"] == "field" for r in native),
                      cards_with_diagnostics=int(bool(diagnostics)))
        cards[card] = dict(observed, construction=construction, script_sha256=lua.script_checksum(f"c{printed}.lua"))
    runtime = []
    for key in sorted(registrations.keys() - initial):
        supported = uses.get(key, [])
        status = "supported_s3_use" if supported else "without_supported_s3_use"
        counts["runtime_" + status] += 1
        runtime.append(dict(card_id=int(key[0]), registration=registrations[key], status=status,
                            evaluations=coverage[key], uses=supported))
    return dict(source=lua.binding, resources=assets.receipt,
                period=getattr(assets, "period_context", None), asset_version=asset_version,
                statistics=dict(counts), cards=cards, runtime_registrations=runtime)


def compare_versions(previous, current):
    if previous.get("schema_version") not in (1, 2):
        raise ValueError("incompatible prior registration audit")
    before, after = previous["cards"], current["cards"]
    prior_resources = previous["resources"]["resources"]
    current_resources = current["resources"]["resources"]
    changed_resources = {key: dict(previous=prior_resources.get(key), current=current_resources.get(key))
        for key in sorted(prior_resources.keys() | current_resources.keys())
        if prior_resources.get(key) != current_resources.get(key)}
    unrecorded = set()
    if previous["schema_version"] == 1:
        count_details = {"count_maximum", "count_persistent"}
        recorded = {field for card in before.values() for rule in card["native"] for field in count_details & rule.keys()}
        unrecorded = count_details - recorded

    def card_content(card):
        snapshot = {key: card[key] for key in ("printed_code", "rule_name", "diagnostics")}
        snapshot["native"] = [{key: value for key, value in rule.items() if key not in unrecorded}
                              for rule in card["native"]] if unrecorded else card["native"]
        if previous["schema_version"] == 2:
            snapshot["script_sha256"] = card["script_sha256"]
        return snapshot

    return dict(previous_source=previous["source"], previous_period=previous["period"],
                changed_resources=changed_resources, prior_unrecorded_fields=sorted(unrecorded),
                added=sorted(after.keys() - before.keys(), key=int),
                removed=sorted(before.keys() - after.keys(), key=int),
                changed=sorted((code for code in before.keys() & after.keys()
                                if card_content(before[code]) != card_content(after[code])), key=int))


def _evaluation(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True, help="Existing locked native resource root")
    parser.add_argument("--output", type=Path, required=True, help="Directory for the audit artifacts")
    parser.add_argument("--period", choices=PERIODS)
    parser.add_argument("--environment", type=Path)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--against", type=Path, help="Previous rule-sources.json to compare")
    parser.add_argument("--evaluation", type=Path, action="append", default=[],
                        help="Native S3 Evaluation JSON or JSON.GZ from this period and observer")
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    if args.period:
        if args.environment is None or args.workspace is None:
            parser.error("--period requires --environment and --workspace")
        assets = PeriodBuildAssets(args.assets, args.period, json.loads(args.environment.read_text(encoding="utf-8")),
                                   args.workspace)
        available = assets.allowed_card_ids
    else:
        if args.environment is not None or args.workspace is not None:
            parser.error("--environment and --workspace require --period")
        if args.evaluation:
            parser.error("--evaluation requires locked period assets")
        assets = BuildAssets(args.assets)
        available = assets.rows
    codes = sorted(code for code in available if assets.rows[code]["ot"] & 1
                   and not assets.rows[code]["type"] & 0x4000
                   and (not args.period or assets.limits.get(rule_name_id(assets.rows, code), 3) > 0))
    initialized = collect_native_registrations(assets, codes, args.output, compiler=args.compiler,
                                               raw=args.output / "registrations.tsv")
    result = compare_registrations(assets, initialized, [_evaluation(path) for path in args.evaluation])
    result["schema_version"] = 2
    if args.against:
        result["version_comparison"] = compare_versions(json.loads(args.against.read_text(encoding="utf-8")), result)
    path = args.output / "rule-sources.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps(dict(report=str(path), **result["statistics"]), ensure_ascii=False))
    return int(any(result["statistics"].get(key) for key in
                   ("cards_with_diagnostics", "unmapped_static_rule", "without_supported_s3_use", "ambiguous_registration",
                    "runtime_without_supported_s3_use")))


if __name__ == "__main__":
    sys.exit(main())
