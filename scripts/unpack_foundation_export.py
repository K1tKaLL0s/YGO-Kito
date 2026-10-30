"""Restore the published foundation snapshot; never overwrite differing files."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

ARCHIVE_SHA256 = '872047224d99ff069fec7aeb12d2a98319efc7cab27cf49a02b60c2cacd27fde'
MANIFEST_SHA256 = '2539298a7e31d55839fd081f7100a8e3373cb20d060d5d61161782516513ca87'
README_SHA256 = '16a880986711f31ea884489bdbf70fb046ed1f7ad6492a9b5c3476ccc98eaedd'


def restore(archive, manifest, destination):
    sha = lambda data: hashlib.sha256(data).hexdigest()
    if sha(archive.read_bytes()) != ARCHIVE_SHA256:
        raise ValueError('Published archive SHA256 mismatch')
    if sha(manifest.read_bytes()) != MANIFEST_SHA256:
        raise ValueError('Published manifest SHA256 mismatch')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if (data['kind'] != 'full-base-resume-with-four-stage-construction-v1'
            or data['source_baseline'] != 'c1157ca5add6c29149eccf7106226b1099e63d8c'):
        raise ValueError('Unexpected export schema or baseline')
    rows = {r['path']: r for r in data['files']}
    if len(rows) != len(data['files']):
        raise ValueError('Duplicate manifest path')
    rows['artifacts/checkpoints/20261027-foundation-002.manifest.json'] = {
        'bytes': manifest.stat().st_size, 'sha256': MANIFEST_SHA256}
    rows['artifacts/checkpoints/20261027-foundation-002.README.zh-CN.md'] = {
        'bytes': 1109, 'sha256': README_SHA256}
    destination = destination.resolve()
    payloads, folded = {}, set()
    with tarfile.open(archive, 'r:gz') as bundle:
        for member in bundle.getmembers():
            if not member.isfile():
                raise ValueError('Export may contain only regular files')
            name = member.name
            parts = PurePosixPath(name)
            if (parts.is_absolute() or '..' in parts.parts or '\\' in name or ':' in name
                    or name not in rows or name.casefold() in folded):
                raise ValueError('Unsafe or unlisted member: ' + name)
            folded.add(name.casefold())
            raw = bundle.extractfile(member).read()
            if len(raw) != rows[name]['bytes'] or sha(raw) != rows[name]['sha256']:
                raise ValueError('Export member digest mismatch: ' + name)
            target = destination.joinpath(*parts.parts)
            if not target.resolve().is_relative_to(destination):
                raise ValueError('Destination escapes requested root')
            if target.exists() and target.read_bytes() != raw:
                raise FileExistsError('Preserve and reconcile existing file: ' + str(target))
            payloads[name] = raw
    if payloads.keys() != rows.keys():
        raise ValueError('Missing export members')
    copied = 0
    for name, raw in payloads.items():
        target = destination.joinpath(*PurePosixPath(name).parts)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(raw)
            copied += 1
    return {'members': len(rows), 'copied': copied, 'destination': str(destination),
            'archive_sha256': ARCHIVE_SHA256, 'checkpoint_deserialized': False,
            'runtime_binding_migrated': False, 'training_started': False}


if __name__ == '__main__':
    repo = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, default=repo / 'artifacts/checkpoints/20261027-foundation-002.tar.gz')
    p.add_argument('--manifest', type=Path, default=repo / 'artifacts/checkpoints/20261027-foundation-002.manifest.json')
    p.add_argument('--destination', type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(restore(args.archive, args.manifest, args.destination), indent=2))
