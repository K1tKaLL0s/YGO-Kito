"""Standalone offline scoring. This entry point has no training command."""

import argparse
import json
from pathlib import Path

from .contracts import DEFAULT_LABEL_PROTOCOL_SHA256, FactorContractError, fields
from .scoring import Candidate, CandidateScorer
from .training import RoleTrainer


def main():
    parser = argparse.ArgumentParser(description="Optional offline multi-factor candidate scoring; no engine or training")
    parser.add_argument("--input", type=Path, required=True, help="multifactor-candidates-v2 JSON")
    parser.add_argument("--checkpoint", type=Path, help="explicit independent checkpoint; otherwise untrained diagnostics")
    parser.add_argument("--adapter", type=Path, help="explicit independent LoRA version bound to --checkpoint")
    parser.add_argument("--label-protocol-sha256", default=DEFAULT_LABEL_PROTOCOL_SHA256, help="explicit expected role annotation protocol")
    parser.add_argument("--output", type=Path, help="write JSON here instead of stdout")
    parser.add_argument("--without-explanations", action="store_true")
    args = parser.parse_args()
    try:
        if args.input.stat().st_size > 8 * 1024 * 1024:
            raise FactorContractError("candidate input exceeds 8 MiB")
        payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
        fields(payload, ("schema_version", "candidates"))
        if payload["schema_version"] != "multifactor-candidates-v2" or not isinstance(payload["candidates"], list):
            raise FactorContractError("versioned candidate JSON array required")
        trainer = (RoleTrainer.load(args.checkpoint, expected_label_protocol_sha256=args.label_protocol_sha256)
                   if args.checkpoint else RoleTrainer(label_protocol_sha256=args.label_protocol_sha256))
        if args.adapter:
            if not args.checkpoint:
                raise FactorContractError("adapter requires an explicitly supplied matching base checkpoint")
            trainer.load_adapter(args.adapter)
        results = CandidateScorer(trainer).score_candidates(tuple(Candidate.from_dict(row) for row in payload["candidates"]),
                                                           explain=not args.without_explanations)
        output = json.dumps(dict(schema_version="multifactor-scores-v2", training_started=False, results=results),
                            indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
    except (FactorContractError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
