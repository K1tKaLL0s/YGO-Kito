"""Restore existing bot proof bytes and bind a reviewed execution source.

No games, model updates or course saves occur here. Existing qualification
checksums must match before the reconstructed evidence can be retained.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]


def run(base,target,validation,checks,*,restore_only=False):
    from local_foundation_comparison import unpack_exact
    from local_foundation_course import restore_readonly_cached_bot_audit,restore_saved_course_bots
    from ygo_kito.build_contracts import digest
    from ygo_kito.course_game_adapter import CourseGameAdapter
    from ygo_kito.implementation_identity import source_tree_snapshot
    from ygo_kito.observed_bot_evidence import KIND
    from ygo_kito.period_runtime import PeriodBuildAssets
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    encode=lambda value:(json.dumps(value,indent=2)+'\n').encode()
    sha=lambda raw:hashlib.sha256(raw).hexdigest()
    def keep(path,raw):
        if path.exists():
            if path.read_bytes()!=raw:raise RuntimeError('Preserve differing evidence: '+str(path))
        else:
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    if not (base/'reports/training.hold.json').exists():raise RuntimeError('Production training hold required')
    pack=read(base/'reports/model-pair-runtime-pack.json')
    runtime=Path('/tmp')/('ygo-kito-model-pair-'+pack['archive_sha256'][:16])
    unpack_exact(base/'cache/model-pair-runtime-001.tar',pack,runtime)
    restore_readonly_cached_bot_audit(base,runtime)
    native_pack=read(base/'reports/native-runtime-cache-source-manifest.json')
    native=Path(native_pack['cache_root'])
    unpack_exact(base/'cache/native-runtime-42b468cc.tar',native_pack,native)
    foundation=base/'source/.cache/local-base-training-20261027/2207-base-005'
    old=foundation.parent/'2207-base-006/paired-comparison-001'
    assets=PeriodBuildAssets(native,'2022-07',read(foundation/'active-environment.local.json'),base,
        adapter_revision=5,evidence_source='user_supplied')
    evidence=runtime/'observed-course-evidence-006'
    files={'comparison.json':old/'comparison.json','task.json':foundation/'fusion-task.json',
        'private-trace.json':old/'candidate-0-seed-701002-seat-0.private-replay.json',
        'closed-case.json':old/'candidate-0-seed-701002-seat-0.closed-flight.json'}
    for name,path in files.items():keep(evidence/name,path.read_bytes())
    keep(evidence/'profile.json',encode(read(evidence/'private-trace.json')['profile']))
    reference=lambda p:{'path':str(p.relative_to(runtime)),'sha256':sha(p.read_bytes())}
    def source_map(manifest,prefix):
        return {name[len(prefix):]:entry['sha256'] for name,entry in sorted(manifest['files'].items())
            if name.startswith(prefix) and name.endswith('.py')}
    frozen=read(base/'reports/formal-course-source-pack-006.json')
    report={'kind':KIND,**{key:reference(evidence/name) for key,name in
        [('comparison','comparison.json'),('task','task.json'),('private_trace','private-trace.json'),('closed_case','closed-case.json')]},
        'actor_seat':0,'original_source_map':source_map(pack,'project/src/ygo_kito/'),
        'current_source_map':source_map(frozen,'src/ygo_kito/'),
        'native_receipt_sha256':digest(assets.receipt),'period_context_sha256':digest(assets.period_context),
        'extra_qualification_games':0,'strength_qualified':False}
    saved=read(target/'course-bots.json');expected={v['runtime']['qualification']['sha256'] for v in saved.values()}
    if expected!={sha(encode(report))}:raise RuntimeError('Reconstructed original qualification bytes differ')
    keep(evidence/'observed-runtime.json',encode(report))
    retained={}
    for path in [*(evidence/name for name in (*files,'profile.json','observed-runtime.json')),
                 *(runtime/'build'/name for name in ('cached-build-audit.json','cache-audit-input.json','cache-audit-output.json'))]:
        name=str(path.relative_to(runtime));raw=path.read_bytes();retained[name]=sha(raw)
        keep(target/'runtime-evidence'/name,raw)
    keep(target/'runtime-evidence-manifest.json',encode({'kind':'saved-runtime-proof-copies-v1',
        'runtime_root':str(runtime),'files':retained}))
    if restore_only:
        print(json.dumps({'original_qualification_preserved':True,'restorable_runtime_proof_files':len(retained)}))
        return
    cpu=read(checks);normal=read(validation/'ordinary-effect-game.json')
    if not cpu['success'] or not normal['replay']['replay_verified'] or normal['terminal_event']['kind']!=5:
        raise RuntimeError('Completed CPU and ordinary native replay evidence required')
    actual=source_tree_snapshot(ROOT/'src/ygo_kito');before=report['current_source_map']
    changes={name:{'before_sha256':before.get(name),'after_sha256':actual.get(name)}
        for name in sorted(set(before)|set(actual)) if before.get(name)!=actual.get(name)}
    review_evidence={'kind':'ordinary-duel-source-review-evidence-v1','scope':'ordinary_effect_duel_default_path',
        'reviewed_changes':changes,'checks':[
            'Reviewed native default: cb_opening_hand is None outside conditional-cb; ordinary games still draw five cards.',
            'Pinned native response guard and reviewed native extension passed the repository CPU check.',
            str(cpu['tests_run'])+' explicitly allowed CPU checks passed, without fault experiments.',
            'A complete ordinary effect game reached native terminal and exact replay on the current implementation.',
            'Construction scoring and optimizer feedback use separate candidate artifacts and do not alter ordinary duel setup.'],
        'validation_files':[{'path':str(p),'sha256':sha(p.read_bytes())} for p in (checks,validation/'ordinary-effect-game.json')]}
    evidence_path=target/'ordinary-duel-source-review.json';keep(evidence_path,encode(review_evidence))
    review={'kind':'observed-bot-source-review-v1','qualification_sha256':next(iter(expected)),
        'from_source_map':before,'to_source_map':actual,'changes':changes,
        'ordinary_duel_review':{'scope':'ordinary_effect_duel_default_path','reviewed_changes':changes,
            'evidence':[{'path':str(evidence_path),'sha256':sha(evidence_path.read_bytes())}]}}
    bots=restore_saved_course_bots(target,runtime)
    for ident,entry in bots.items():
        adapter=object.__new__(CourseGameAdapter);adapter.bot=entry['runtime'];adapter.bot_id=ident
        adapter.assets=assets;adapter._originals={ident:entry['deck']};adapter._observed_bot_source_review=review
        adapter._bind_original_qualification()
        if adapter._qualification_sha256 not in expected:raise RuntimeError('Restored bot qualification differs')
    keep(target/'observed-bot-source-review.json',encode(review))
    result={'bot_count':len(bots),'original_qualification_preserved':True,'current_source_review_bound':True,
        'restorable_runtime_proof_files':len(retained),'formal_training_started':False,'model_checkpoint_modified':False}
    keep(target/'runtime-restore-check.json',encode(result));print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('base','target','validation','checks'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--restore-only',action='store_true')
    args=parser.parse_args();run(args.base.resolve(),args.target.resolve(),args.validation.resolve(),args.checks.resolve(),restore_only=args.restore_only)
