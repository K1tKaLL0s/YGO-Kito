"""Fact-only v3 service entry. Neural evaluation uses axis_generic.workflow_v3."""

import argparse
import json
from pathlib import Path

from .contracts import FactorContractError, fields


def service_request(payload, operation):
    from .analysis import AnalysisFacts, RoleAnalyzer
    from .contracts import AnalysisRequestContext, FunctionSeed, StructureLink
    from .functional_units import FunctionalContract
    from .conditions import Resource
    expected = {"schema_version", "context", "facts"} | {
        "analyze_deck": {"deck"}, "assess_unit": {"unit", "receiver_deck", "requested_function"},
        "compare_copy_change": {"base_deck", "add_card", "remove_card", "functions"}}[operation]
    fields(payload, expected)
    if payload["schema_version"] != "axis-service-request-v3":
        raise FactorContractError("axis-service-request-v3 required")
    context = AnalysisRequestContext.from_dict(payload["context"])
    facts = payload["facts"]
    if not isinstance(facts, dict) or not set(facts) <= set(AnalysisFacts.__dataclass_fields__):
        raise FactorContractError("service facts accept observations only")
    facts = dict(facts)
    for name in ("card_rows", "effect_snapshots"):
        if name in facts:
            facts[name] = {int(code): row for code, row in facts[name].items()}
    for name, kind in (("structure_links", StructureLink), ("function_seeds", FunctionSeed), ("unit_contracts", FunctionalContract)):
        if name in facts:
            facts[name] = tuple(kind.from_dict(row) for row in facts[name])
    if 'resources' in facts:
        facts['resources'] = tuple(Resource.from_dict(row) for row in facts['resources'])
    observed = AnalysisFacts(**facts)
    analyzer = RoleAnalyzer(lambda deck, context, unit: observed)
    if operation == "analyze_deck":
        result = analyzer.analyze_deck(payload["deck"], context)
    elif operation == "assess_unit":
        result = analyzer.assess_unit(payload["unit"], payload["receiver_deck"], context, payload["requested_function"])
    else:
        result = analyzer.compare_copy_change(payload["base_deck"], payload["add_card"], payload["remove_card"], payload["functions"], context)
    return dict(result.to_dict(), training_started=False)


def main():
    parser = argparse.ArgumentParser(description="Fact-only axis-service-request-v3; neural prediction: training.axis_generic.workflow_v3 predict")
    parser.add_argument("--input", type=Path, required=True, help="axis-service-request-v3 JSON")
    parser.add_argument("--output", type=Path, help="write JSON here instead of stdout")
    parser.add_argument("--service", choices=("analyze_deck", "assess_unit", "compare_copy_change"),
                        required=True,help="fact-only operation; never constructs or loads a model")
    args = parser.parse_args()
    try:
        if args.input.stat().st_size > 8 * 1024 * 1024:
            raise FactorContractError("candidate input exceeds 8 MiB")
        payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
        result = service_request(payload, args.service)
        output = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
    except (ValueError, TypeError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
