"""Read durable status and verify an existing Linux worker's process identity."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    if not args.run_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in args.run_id):
        raise ValueError('Invalid local run identity')
    path = args.base / 'reports/local-training' / args.run_id / 'status.json'
    value = json.loads(path.read_text())
    counts=value.get('course',{}).get('complete_training_matches')
    if counts is not None:
        value.update(formal_course_bo1=counts['bo1'],formal_course_bo3=counts['bo3'],formal_matches=sum(counts.values()),counts_source='committed_nested_course_status')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    stat = Path('/proc') / str(value['pid']) / 'stat'
    cmdline = stat.with_name('cmdline')
    expected = (str(args.base / 'source/scripts/local_training_worker.py'),
                '--base', str(args.base), '--run-id', args.run_id, '--job', value['job'])
    identity = False
    if boot == value['boot_id'] and stat.is_file():
        try:
            ticks = stat.read_text().split()[21]
            argv = cmdline.read_bytes().decode().split('\0')
            identity = ticks == value['process_start_ticks'] and all(item in argv for item in expected)
        except FileNotFoundError:
            pass  # A worker can finish between these read-only operations.
    then = datetime.fromisoformat(value['heartbeat_utc'])
    value['process_identity_verified'] = identity
    value['heartbeat_age_seconds'] = max(0., (datetime.now(timezone.utc) - then).total_seconds())
    value['observed_utc'] = datetime.now(timezone.utc).isoformat()
    value['observation_only_no_worker_started'] = True
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
