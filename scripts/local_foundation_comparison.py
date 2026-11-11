"""Actual frozen-policy paired construction supervision, followed by base update."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile


def unpack_exact(archive,manifest,target):
    archive_bytes=archive.read_bytes()
    if hashlib.sha256(archive_bytes).hexdigest()!=manifest['archive_sha256']:raise RuntimeError('Runtime archive changed')
    target.mkdir(parents=True,exist_ok=True)
    # Reuse a complete byte-verified local cache without thousands of seeks in
    # the archive on DrvFS. The archive hash remains checked above.
    complete=True
    for name,expected in manifest['files'].items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:raise RuntimeError('Unsafe runtime manifest path')
        p=target/relative
        if not p.exists():complete=False;continue
        if not p.is_file() or p.stat().st_size!=expected['size'] or hashlib.sha256(p.read_bytes()).hexdigest()!=expected['sha256']:raise RuntimeError('Preserve differing runtime file')
    if complete:return
    with tarfile.open(fileobj=io.BytesIO(archive_bytes),mode='r:') as bundle:
        members=bundle.getmembers()
        if {m.name for m in members}!=set(manifest['files']):raise RuntimeError('Runtime member list differs')
        for member in members:
            name=Path(member.name)
            if not member.isfile() or name.is_absolute() or '..' in name.parts:raise RuntimeError('Unsafe runtime member')
            p=target/name;expected=manifest['files'][member.name]
            if p.exists():
                if p.stat().st_size!=expected['size'] or hashlib.sha256(p.read_bytes()).hexdigest()!=expected['sha256']:raise RuntimeError('Preserve differing runtime file')
                continue
            data=bundle.extractfile(member).read()
            if len(data)!=expected['size'] or hashlib.sha256(data).hexdigest()!=expected['sha256']:raise RuntimeError('Runtime bytes differ')
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)



def restore_cached_bot_audit(base,cache,status):
    """Restore exact prior audit bytes or repair missing runtime configuration."""
    from copy import deepcopy
    from ygo_kito.bot_build_audit import prepare_plan,validate_audit_result,file_sha
    def read(p):return json.loads(p.read_text(encoding='utf-8'))
    def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    saved=base/'reports/cached-bot-runtime-audit-001';saved.mkdir(exist_ok=True)
    names=('cached-build-audit.json','cache-audit-output.json','cache-audit-input.json')
    if (saved/'manifest.json').exists():
        meta=read(saved/'manifest.json')
        if meta['runtime_root']!=str(cache):raise RuntimeError('Cached audit belongs to another physical runtime path')
        for name in names:
            p=saved/name;destination=cache/'build'/name
            if file_sha(p)!=meta['files'][name]:raise RuntimeError('Persisted audit file changed')
            if destination.exists() and file_sha(destination)!=meta['files'][name]:raise RuntimeError('Preserve differing cached audit')
            if not destination.exists():destination.write_bytes(p.read_bytes())
    audit_path=cache/'build/cached-build-audit.json'
    if not audit_path.exists():
        status('restoring_missing_compiled_bot_audit_configuration')
        original=read(base/'reports/local-ice-build-audit-002-resumed.json')
        lock=read(cache/'project/configs/bot-sources-v1.json');roots={i:str(cache/'bots'/i) for i in ('ice','pure','library','mobile-config')}
        plan=prepare_plan(lock,roots,'ice',cache/'resources/cards.cdb',original['cards']['sha256'],cache/'build')
        spec={k:plan[k] for k in ('schema_version','source_id','assembly_path','source_root','cards','resources','bots')};spec['assembly_sha256']=file_sha(plan['assembly_path'])
        if spec['assembly_sha256']!=original['assembly_sha256']:raise RuntimeError('Compiled bot bytes differ')
        input_path=cache/'build/cache-audit-input.json';output_path=cache/'build/cache-audit-output.json';write(input_path,spec)
        with (saved/'configuration-repair.log').open('ab') as log:
            subprocess.run([original['toolchain']['mono']['path'],str(cache/'build/BotAssemblyAudit.exe'),str(input_path),str(output_path),'--construct'],
                cwd=plan['source_root'],stdout=log,stderr=subprocess.STDOUT,timeout=180,check=True)
        audited=read(output_path);validate_audit_result(plan,audited,construct=True)
        if prepare_plan(lock,roots,'ice',plan['cards']['path'],plan['cards']['sha256'],cache/'build')!=plan:raise RuntimeError('Runtime changed while restoring bot configuration')
        receipt=deepcopy(original)
        for k in ('assembly_path','source_root','source_roots','cards','inventory_sha256','source_lock_sha256','audit_source_sha256'):receipt[k]=plan[k]
        receipt.update(expected_bots=plan['bots'],audit=audited,audit_output_path=str(output_path),audit_output_sha256=file_sha(output_path))
        write(audit_path,receipt)
    old_plan=base/'source/.cache/local-base-training-20261027/2207-base-006/paired-comparison-001/plan.json'
    expected=read(old_plan)['driver']['audit_sha256']
    if file_sha(audit_path)!=expected:raise RuntimeError('Recovered audit differs from the completed games; preserve both, no invented compatibility')
    files={name:file_sha(cache/'build'/name) for name in names}
    for name in names:
        p=saved/name
        if p.exists() and file_sha(p)!=files[name]:raise RuntimeError('Preserve prior persisted audit')
        if not p.exists():p.write_bytes((cache/'build'/name).read_bytes())
    write(saved/'manifest.json',{'kind':'exact-completed-game-bot-audit-persistence','runtime_root':str(cache),'files':files,
        'completed_game_audit_sha256':expected,'extra_native_qualification_games':0,'bot_recompiled':False})
    return audit_path
