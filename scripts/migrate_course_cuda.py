"""Explicit closed-course CPU to CUDA migration; never runs the curriculum."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]


def migrate(base, source, target, *, device, cuda_seed, source_review=None):
    import torch
    from local_foundation_course import run
    from local_course_source_continuation import validate_continuation
    from ygo_kito.course_models import CourseModels
    from ygo_kito.data_isolation import DataIndex
    from ygo_kito.scenario_course import ScenarioCourse, index_identity
    from ygo_kito.group_runner import tree_digest

    base, source, target = base.resolve(), source.resolve(), target.resolve()
    validate_continuation({'state_root': str(source)}, base)
    if target.exists() or not target.is_relative_to(base) or target == source:
        raise ValueError('Migration requires a new target inside the resource base')
    if not (base / 'reports/training.hold.json').exists():
        raise ValueError('Pause the local course before migrating its checkpoint and index')
    pointer_bytes = (source / 'course/latest.json').read_bytes()
    def status(*args, **kwargs):
        print(json.dumps({'stage': args, **kwargs}, default=str), flush=True)
    old = run(base, source, source / 'unused-stop', status, resume=True,
              continuation={'state_root': str(source)}, execution_source_root=ROOT,
              resource_base=base, restore_only=True)
    if old.pending is not None or old.feedback.pending is not None or old.frozen_evaluation is not None:
        raise ValueError('Migration requires a closed learning and evaluation boundary')
    before = old.models.save_state()
    index_before = index_identity(old.data_index)
    models = CourseModels.migrate_to_cuda(before, assets=old.assets,
        expected_binding=old.models.binding, device=device, cuda_seed=cuda_seed)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    # Retain only files consumed by the current host. Historical code and old
    # checkpoints remain in their original location, not another executable copy.
    for name in ('course-bots.json', 'runtime-evidence-manifest.json',
                 'observed-bot-source-review.json'):
        path = source / name
        if path.exists(): shutil.copy2(path, target / name)
    if source_review is not None:
        from ygo_kito.observed_bot_evidence import validate_source_review_schema
        review = validate_source_review_schema(json.loads(source_review.read_text(encoding='utf-8')))
        (target / 'observed-bot-source-review.json').write_text(json.dumps(review, indent=2) + '\n')
    if (source / 'runtime-evidence').exists():
        shutil.copytree(source / 'runtime-evidence', target / 'runtime-evidence')
    (target / 'index').mkdir()
    with sqlite3.connect(old.data_index.path.as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(target / 'index/data-index.sqlite3') as dst: src.backup(dst)
    index = DataIndex(target / 'index', storage_limits=old.data_index.storage_limits)
    if index_identity(index) != index_before:
        raise RuntimeError('Copied DataIndex differs')
    config = deepcopy(old.config); config['allocated_gpu_count'] = 1
    new = ScenarioCourse(models, assets=old.assets, data_index=index, config=config,
                         state_root=target / 'course', bots=old.bots)
    for key in ('records', 'events', 'active_seconds', 'selection', 'deck', 'construction',
                'evaluation_cursor', 'frozen_evaluation', 'desired', 'initial_model_execution',
                'training_attempt_cursor', '_legacy_attempt_acknowledgments'):
        setattr(new, key, deepcopy(getattr(old, key)))
    new.feedback.load_state_dict(old.feedback.state_dict())
    # Partial game artifacts are historical records, never replayed by migration.
    for record in new.records:
        for receipt in record.get('receipts', []):
            artifact = receipt.get('partial_game')
            if artifact:
                rel = Path(artifact['path'])
                if rel.is_absolute() or '..' in rel.parts:
                    raise ValueError('Partial artifact leaves course root')
                dest = new.root / rel; dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists(): shutil.copy2(old.root / rel, dest)
    event = {'kind': 'explicit-cpu-to-cuda-course-migration-v1',
        'source_root': str(source), 'source_checkpoint': json.loads(pointer_bytes),
        'device': str(models.device), 'cuda_seed': cuda_seed,
        'rng_policy': 'preserve_cpu_and_owned_streams_start_new_cuda_stream',
        'cross_device_bitwise_continuation': False, 'data_index_sha256': index_before,
        'preserved_model_state_sha256': before['state_sha256'],
        'preserved_cursors': deepcopy(before['cursors']),
        'runtime': {'python': sys.version, 'torch': str(torch.__version__), 'cuda': torch.version.cuda},
        'formal_training_started': False}
    new.events.append(event)
    def write(path, value):
        with path.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2); stream.write('\n')
    write(target / 'model-binding.json', models.binding)
    write(target / 'course-config.json', config)
    if (source / 'course/latest.json').read_bytes() != pointer_bytes or index_identity(old.data_index) != index_before:
        raise RuntimeError('Source advanced during migration; target is not published')
    saved = new.save()
    restored = run(base, target, target / 'unused-stop', status, resume=True,
        continuation={'state_root': str(target)}, execution_source_root=ROOT,
        resource_base=base, restore_only=True, required_device=device)
    if (restored.models.fingerprint() != new.models.fingerprint()
            or restored.counts() != old.counts()
            or tree_digest(restored.feedback.state_dict()) != tree_digest(old.feedback.state_dict())
            or restored.training_attempt_cursor != old.training_attempt_cursor):
        raise RuntimeError('Migrated course round trip differs; target is not published')
    event.update(target_root=str(target), checkpoint=saved, restore_verified=True,
                 preserved_match_counts=old.counts(), training_attempt_cursor=old.training_attempt_cursor)
    write(target / 'cuda-migration.json', event)
    return event


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--device', default='cuda:0')
    parser.add_argument('--cuda-seed', type=int, required=True)
    parser.add_argument('--source-review', type=Path)
    args = parser.parse_args()
    import fcntl
    import torch
    torch.set_num_threads(2)
    torch.cuda.set_per_process_memory_fraction(0.2)
    with (args.base / 'reports/local-training/active.mutex').open('a+b') as mutex:
        fcntl.flock(mutex.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps(migrate(args.base, args.source, args.target,
            device=args.device, cuda_seed=args.cuda_seed, source_review=args.source_review), indent=2))


if __name__ == '__main__': main()
