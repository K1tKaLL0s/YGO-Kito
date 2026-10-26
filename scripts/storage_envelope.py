#!/usr/bin/env python3
"""Read-only workspace storage admission report; no training or allocation."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'src'))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,default=ROOT)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--additional-bytes',type=int,default=0)
    args=parser.parse_args(argv)
    from ygo_kito.storage_envelope import StorageEnvelope
    from ygo_kito.validation import fields,read_json
    try:
        config={} if args.config is None else dict(fields(read_json(args.config),set(),
            {'state_roots','temporary_roots','limit_bytes','outside_bytes','min_free_bytes','safety_margin_bytes'}))
        report=StorageEnvelope(args.workspace,**config).audit(args.additional_bytes)
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as error:
        print(json.dumps({'kind':'workspace-storage-envelope-audit','mode':'read_only','status':'blocked',
            'error_type':type(error).__name__,'training_started':False,'existing_data_deleted':False}))
        return 2
    print(json.dumps(report,sort_keys=True,ensure_ascii=False,allow_nan=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
