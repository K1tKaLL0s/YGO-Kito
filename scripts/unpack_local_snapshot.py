"""Verify and extract a closed local snapshot without loading model objects."""
import argparse
import hashlib
import io
import json
from pathlib import Path,PurePosixPath
import tarfile

def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    metadata=json.loads(a.manifest.read_text(encoding='utf-8'))
    if metadata.get('kind')!='closed-local-foundation-continuation-v1':raise ValueError('Unsupported snapshot kind')
    files=metadata['files'];total=sum(x['size'] for x in files.values())
    if not 1<=len(files)<=2000 or not 0<total<=512000000:raise ValueError('Snapshot extraction allocation exceeded')
    raw=a.archive.read_bytes()
    if len(raw)!=metadata['archive_bytes'] or hashlib.sha256(raw).hexdigest()!=metadata['archive_sha256']:raise ValueError('Archive identity differs')
    output=a.output.resolve();output.mkdir(parents=True,exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as bundle:
        members=bundle.getmembers()
        if len(members)!=len(files) or {m.name for m in members}!=set(files):raise ValueError('Snapshot member list differs')
        for m in members:
            name=PurePosixPath(m.name);destination=output/Path(m.name);expected=files[m.name]
            if not m.isfile() or name.is_absolute() or '..' in name.parts or not destination.resolve().is_relative_to(output):raise ValueError('Unsafe snapshot member')
            if m.size!=expected['size']:raise ValueError('Snapshot member size differs')
            if destination.exists() and (not destination.is_file() or hashlib.sha256(destination.read_bytes()).hexdigest()!=expected['sha256']):raise ValueError('Preserve differing existing file: '+m.name)
        for m in members:
            data=bundle.extractfile(m).read();expected=files[m.name];destination=output/Path(m.name)
            if len(data)!=expected['size'] or hashlib.sha256(data).hexdigest()!=expected['sha256']:raise ValueError('Snapshot member hash differs')
            if destination.exists():continue
            destination.parent.mkdir(parents=True,exist_ok=True)
            with destination.open('xb') as target:target.write(data)
    print(json.dumps({'status':'extracted_hash_verified_snapshot','members':len(files),'bytes':total,
        'output':str(output),'models_loaded':False,'training_started':False}))
if __name__=='__main__':main()
