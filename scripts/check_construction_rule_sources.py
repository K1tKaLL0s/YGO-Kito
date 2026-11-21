"""Compare initialized core registrations with the catalog used by construction S3."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ygo_kito.build_pipeline import BuildAssets
from ygo_kito.card_identity import native_card_identity, rule_name_id
from ygo_kito.construction_relations import _record_outputs
from ygo_kito.deck_intake import PERIODS
from ygo_kito.effect_mechanisms import MechanismCatalog
from ygo_kito.period_runtime import PeriodBuildAssets


def card_data(assets):
    cdb = assets.root / "engine-src/database/locales/zh-CN/cards.cdb"
    with sqlite3.connect(cdb.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = {row["id"]: dict(row) for row in connection.execute("SELECT * FROM datas")}
    for code, row in rows.items():
        printed, name = assets.native_code_overrides.get(code, (row["alias"] or code,) * 2)
        link = row["def"] if row["type"] & 0x4000000 else 0
        yield (code, printed if printed != code else 0, row["setcode"] % (1 << 64),
               row["type"], row["level"] & 255, row["attribute"], row["race"], row["atk"], row["def"],
               (row["level"] >> 24) & 255, (row["level"] >> 16) & 255, link,
               name if name != printed else 0)


def run_core(assets, output, codes, compiler):
    core = assets.root / "engine-src"
    library = assets.root / "engine-build/libocgcore.so"
    with TemporaryDirectory(dir=output, prefix="registration-build-") as scratch:
        scratch = Path(scratch)
        executable = scratch / "registrations"
        subprocess.run([compiler, "-std=c++20", "-O2", "-I", core / "core", "-I", core / "lua",
                        Path(__file__).with_name("construction_rule_registrations.cpp"), library,
                        f"-Wl,-rpath,{library.parent}", "-o", executable], check=True)
        table = scratch / "card-data.tsv"
        with table.open("w", encoding="utf-8") as handle:
            for row in card_data(assets):
                handle.write(" ".join(map(str, row)) + "\n")
        raw = output / "registrations.tsv"
        with raw.open("w", encoding="utf-8") as handle:
            subprocess.run([executable, core / "scripts", table],
                           input="\n".join(map(str, codes)), stdout=handle, text=True, check=True)
    return raw


def read_row(handle, expected):
    kind, *values = next(handle).rstrip("\n").split("\t")
    if kind != expected:
        raise ValueError("expected locked core " + expected + " row, got " + kind)
    return values


def registered_effect(handle, scripts):
    scope, kind, event, area, description, category, limit, *callbacks = read_row(handle, "registration")
    bindings = {}
    for offset, role in enumerate(("condition", "cost", "target", "operation", "value")):
        source, start, end = callbacks[3 * offset:3 * offset + 3]
        if source == "-":
            continue
        match = re.fullmatch(r'\[string "\./script/(.+)"\]', source)
        name = match[1] if match else source
        bindings[role] = dict(file=name, lines=[int(start), int(end)])
        if name in scripts:
            bindings[role]["sha256"] = scripts[name][1]
    return dict(scope=scope, type=int(kind), event=int(event), range=int(area), description=int(description),
                category=int(category), count_code=int(limit), callbacks=bindings)


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


def compare_registrations(assets, raw, codes):
    lua = assets.effect_lua_source
    catalog = MechanismCatalog(assets)
    counts = Counter()
    cards = {}
    with raw.open(encoding="utf-8") as handle:
        for code in codes:
            current, printed, name, warnings, registrations = map(int, read_row(handle, "card"))
            if current != code or (printed, name) != native_card_identity(assets.rows, code):
                raise ValueError(f"core script identity disagrees with the construction catalog for {code}")
            diagnostics = [read_row(handle, "diagnostic")[0] for _ in range(warnings)]
            native = [registered_effect(handle, lua._scripts) for _ in range(registrations)]
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
            cards[str(code)] = dict(printed_code=printed, rule_name=name, diagnostics=diagnostics,
                native=native, static=static, s3_records=formal, unmatched_signatures=unmatched)
        if handle.readline():
            raise ValueError("core returned registrations beyond the selected catalog")
    return dict(source=lua.binding, resources=assets.receipt, period=getattr(assets, "period_context", None),
                statistics=dict(counts), cards=cards)


def compare_versions(previous, current):
    if previous.get("schema_version") != 1:
        raise ValueError("incompatible prior registration audit")
    before, after = previous["cards"], current["cards"]
    return dict(previous_source=previous["source"], previous_period=previous["period"],
                added=sorted(after.keys() - before.keys(), key=int), removed=sorted(before.keys() - after.keys(), key=int),
                changed=sorted((code for code in before.keys() & after.keys() if before[code] != after[code]), key=int))


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
    args.output.mkdir(parents=True, exist_ok=True)
    result = compare_registrations(assets, run_core(assets, args.output, codes, args.compiler), codes)
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
