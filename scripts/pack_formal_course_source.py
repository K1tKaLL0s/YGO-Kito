"""Pack this project's exact Python execution source for local Linux caching."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--base',type=Path,required=True);args=parser.parse_args()
    base=args.base.resolve();source=base/'source'
    archive=base/'cache/formal-course-source-003.tar'
    manifest=base/'reports/formal-course-source-pack-003.json'
    if archive.exists() or manifest.exists():raise RuntimeError('Preserve existing immutable execution snapshot')
    members={p.relative_to(source).as_posix():p for p in sorted((source/'src/ygo_kito').glob('*.py'))}
    members['configs/bot-sources-v1.json']=source/'configs/bot-sources-v1.json'
    members['configs/native-sources.lock.json']=source/'configs/native-sources.lock.json'
    members['scripts/BotAssemblyAudit.cs']=source/'scripts/BotAssemblyAudit.cs'
    metadata={'kind':'exact-local-course-execution-source','redistribution':False,'files':{}}
    with tarfile.open(archive,'w:') as bundle:
        for name,p in sorted(members.items()):
            data=p.read_bytes();metadata['files'][name]={'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
            bundle.add(p,arcname=name,recursive=False)
    metadata.update(archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),archive_bytes=archive.stat().st_size)
    manifest.write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in metadata.items() if k!='files'},indent=2))
if __name__=='__main__':main()
