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


def run(base,directory,stop,status,*,resume=False):
    def read(p):return json.loads(p.read_text(encoding='utf-8'))
    def write(p,v):
        tmp=p.with_name(p.name+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');tmp.replace(p)
    source=base/'source';pack=read(base/'reports/model-pair-runtime-pack.json')
    cache=Path('/tmp')/('ygo-kito-model-pair-'+pack['archive_sha256'][:16])
    status('restoring_exact_offline_model_and_bot_runtime')
    unpack_exact(base/'cache/model-pair-runtime-001.tar',pack,cache)
    native_meta=read(base/'reports/native-runtime-cache-source-manifest.json');native=Path(native_meta['cache_root'])
    unpack_exact(base/'cache/native-runtime-42b468cc.tar',native_meta,native)
    sys.path.insert(0,str(cache/'project/src'))
    import torch
    from ygo_kito.build_contracts import BuildTask,DeckParts,digest
    from ygo_kito.bot_build_audit import prepare_plan,validate_audit_result,file_sha
    from ygo_kito.bot_deployment import BotSourceRegistry
    from ygo_kito.build_training import supervision_projection
    from ygo_kito.course_models import CourseModels
    from ygo_kito.course_game_adapter import course_config_from_dict
    from ygo_kito.course_feedback import CourseFeedbackUpdater
    from ygo_kito.data_isolation import DataIndex
    from ygo_kito.group_runner import tree_digest
    from ygo_kito.model_build_feedback import SOURCE as MODEL_SOURCE,compare_model_candidates
    from ygo_kito.period_runtime import PeriodBuildAssets
    from ygo_kito.semantic_training import SOURCE
    torch.set_num_threads(2)
    old=source/'.cache/local-base-training-20261027/2207-base-005'
    target=source/'.cache/local-base-training-20261027/2207-base-006'
    assets=PeriodBuildAssets(native,'2022-07',read(old/'active-environment.local.json'),base,adapter_revision=5,evidence_source='user_supplied')
    actual={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((source/'src/ygo_kito').glob('*.py'))}
    snapshot={str(p.relative_to(cache/'project')):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((cache/'project/src/ygo_kito').glob('*.py'))}
    if snapshot!=actual:raise RuntimeError('Local code differs from this immutable execution snapshot; repack explicitly')
    status('restoring_started_base_for_frozen_comparison')
    if target.exists():
        if not resume:raise RuntimeError('Existing comparison preserved; inspect then Resume')
        if (target/'update-in-flight.json').exists():raise RuntimeError('Uncertain optimizer update; no automatic replay')
        pointer=read(target/'latest-pointer.json');binding=read(target/'binding.json')
        if binding['source_files']!=actual:raise RuntimeError('Source differs from saved comparison state')
        if hashlib.sha256(Path(pointer['path']).read_bytes()).hexdigest()!=pointer['sha256']:raise RuntimeError('Saved state changed')
        models=CourseModels.from_state(torch.load(pointer['path'],map_location='cpu',weights_only=False),assets=assets,expected_binding=binding)
    else:
        pointer=read(old/'latest-pointer.json')
        if hashlib.sha256(Path(pointer['path']).read_bytes()).hexdigest()!=pointer['sha256']:raise RuntimeError('Previous complete state changed')
        state=torch.load(pointer['path'],map_location='cpu',weights_only=False)
        if state['state_sha256']!=tree_digest({k:v for k,v in state.items() if k!='state_sha256'}):raise RuntimeError('State content differs')
        changed={p for p in set(actual)|set(state['binding']['source_files']) if actual.get(p)!=state['binding']['source_files'].get(p)}
        allowed={'src/ygo_kito/'+n+'.py' for n in ('model_build_feedback','semantic_training','course_feedback')}
        if not changed or not changed<=allowed:raise RuntimeError('Unexpected source change: '+repr(changed-allowed))
        binding=deepcopy(state['binding']);binding['source_files']=actual
        temp=CourseModels.initialize(BuildTask.from_dict(state['task']),assets,course_config_from_dict(state['configs']['duel']),state['configs']['adapters'],source,None,state['available_ids'],binding,device='cpu')
        for role,model in temp.models().items():model.load_state_dict(state['components']['models'][role],strict=True)
        temp.kernel.updates=deepcopy(state['kernel']['updates'])
        migrated=deepcopy(state);migrated['binding']=binding;migrated['binding_sha256']=digest(binding);migrated['kernel']=temp.kernel.state_dict()
        migrated['state_sha256']=tree_digest({k:v for k,v in migrated.items() if k!='state_sha256'})
        models=CourseModels.from_state(migrated,assets=assets,expected_binding=binding)
        restored=models.save_state()
        if tree_digest(restored['components'])!=tree_digest(state['components']) or tree_digest(restored['rng'])!=tree_digest(state['rng']) or restored['cursors']!=state['cursors']:raise RuntimeError('Source-only migration changed training state')
        target.mkdir();shutil.copytree(old/'index',target/'index');write(target/'binding.json',binding)
        torch.save(restored,target/'migrated-initial.weights')
        write(target/'latest-pointer.json',{'path':str(target/'migrated-initial.weights'),'sha256':file_sha(target/'migrated-initial.weights')})
        write(target/'migration.json',{'kind':'explicit-source-and-runtime-location-migration','source_checkpoint_sha256':pointer['sha256'],'changed_source_files':sorted(changed),'components_rng_cursors_preserved':True,'execution_snapshot_sha256':pack['archive_sha256']})
    index=DataIndex(target/'index');updater=CourseFeedbackUpdater(models,index,'pearl-base-2207-v1')
    feedback=read(target/'feedback-state.json') if (target/'feedback-state.json').exists() else read(old/'feedback-state.json')
    if feedback['pending'] is not None:raise RuntimeError('Prior feedback uncertain')
    rebound=updater.state_dict();rebound['consumed']=deepcopy(feedback['consumed']);rebound['metadata_sha256']=digest({k:v for k,v in rebound.items() if k!='metadata_sha256'});updater.load_state_dict(rebound)
    task=BuildTask.from_dict(read(old/'fusion-task.json'));cycle=read(old/'actual-fusion-four-stage.json')
    candidates=[DeckParts.from_dict(cycle['best']['deck'])]
    for phase in cycle['phases']:
        if phase.get('stage_3',{}).get('status')=='task_goal_verified_logic_unproven' and phase.get('proposal_deck'):
            deck=DeckParts.from_dict(phase['proposal_deck'])
            if deck not in candidates:candidates.append(deck)
            if len(candidates)==2:break
    if len(candidates)!=2:raise RuntimeError('Need a second actually generated/verified proposal; do not force an edit')
    proofs=[]
    for candidate in candidates:
        proofs.append(next(read(p)['proof'] for p in sorted(old.glob('route-attempt-*.json')) if read(p)['deck']==candidate.to_dict() and read(p)['proof']['status']=='constraints_and_route_verified'))
    lock=read(cache/'project/configs/bot-sources-v1.json');roots={i:str(cache/'bots'/i) for i in ('ice','pure','library','mobile-config')}
    # Copying changes physical paths. Reuse the same binary and execute only its
    # constructor/resource audit at the new paths; no extra duel qualification.
    audit_path=cache/'build/cached-build-audit.json'
    original_audit=read(base/'reports/local-ice-build-audit-002-resumed.json')
    if not audit_path.exists():
        status('binding_same_audited_bot_bytes_to_local_runtime_cache')
        plan=prepare_plan(lock,roots,'ice',cache/'resources/cards.cdb',original_audit['cards']['sha256'],cache/'build')
        spec={k:plan[k] for k in ('schema_version','source_id','assembly_path','source_root','cards','resources','bots')};spec['assembly_sha256']=file_sha(plan['assembly_path'])
        if spec['assembly_sha256']!=original_audit['assembly_sha256']:raise RuntimeError('Compiled bot bytes changed')
        input_path=cache/'build/cache-audit-input.json';output_path=cache/'build/cache-audit-output.json';write(input_path,spec)
        with (cache/'build/cache-audit.log').open('xb') as log:
            subprocess.run([original_audit['toolchain']['mono']['path'],str(cache/'build/BotAssemblyAudit.exe'),str(input_path),str(output_path),'--construct'],cwd=plan['source_root'],stdout=log,stderr=subprocess.STDOUT,timeout=180,check=True)
        audited=read(output_path);validate_audit_result(plan,audited,construct=True)
        if prepare_plan(lock,roots,'ice',plan['cards']['path'],plan['cards']['sha256'],cache/'build')!=plan:raise RuntimeError('Cached runtime changed during constructor audit')
        receipt=deepcopy(original_audit)
        for k in ('assembly_path','source_root','source_roots','cards','inventory_sha256','source_lock_sha256','audit_source_sha256'):receipt[k]=plan[k]
        receipt.update(expected_bots=plan['bots'],audit=audited,audit_output_path=str(output_path),audit_output_sha256=file_sha(output_path))
        write(audit_path,receipt)
        write(target/'runtime-migration.json',{'original_audit_sha256':file_sha(base/'reports/local-ice-build-audit-002-resumed.json'),'cached_audit_sha256':file_sha(audit_path),'assembly_bytes_identical':True,'constructor_resource_audit_actual':True,'extra_duel_qualification_run':False})
    registry=BotSourceRegistry(lock,cache/'bots');host=read(source/'.cache/local-base-training-20261027/2207-base-002/runtime-host.json')
    bot=next(dict(b) for b in host['bots'] if b['purpose']=='train' and b['stage']=='bots-bo1' and 'CyberDragon' in b['executor_id'])
    deck_path=Path(bot['deck']['path']);deck_path=deck_path if deck_path.is_absolute() else source/deck_path
    if str(deck_path).startswith('/workspace/'):deck_path=source/str(deck_path)[len('/workspace/'):]
    opponent=DeckParts.from_dict(read(deck_path));bot['mono']=original_audit['toolchain']['mono']['path']
    audit={'path':str(audit_path),'assembly_sha256':original_audit['assembly_sha256']}
    seeds=tuple(models.duel.config.game_seeds[models.duel.episode_cursor:models.duel.episode_cursor+4])
    if len(seeds)<2:raise RuntimeError('Declared paired training seed capacity exhausted')
    comparison=compare_model_candidates(task,assets,candidates,opponent,trainer=models.duel,registry=registry,bot=bot,audit=audit,workspace=cache,
        seeds=seeds,directory=target/'paired-comparison-001',data_index=index,experiment_id='pearl-base-2207-v1',stop=stop,status=status)
    status('saved_complete_actual_comparison',completed_cases=len(comparison['games']),total_cases=len(comparison['games']),complete_pairs=len(comparison['games'])//2)
    preferred=comparison['preferred_index']
    if preferred is None:
        summary={'status':'no_strict_training_preference','comparison_saved':True,'model_updates':0,'mean_scores':comparison['mean_scores'],'formal_course_credit':False}
        write(target/'summary.json',summary);return summary
    goals=[{'deck':d.to_dict(),'label':1.,'source':'pinned_constraints_and_actual_native_route','evidence':proof} for d,proof in zip(candidates,proofs)]
    pair={'better':candidates[preferred].to_dict(),'worse':candidates[1-preferred].to_dict(),
          'better_value':comparison['mean_scores'][preferred],'worse_value':comparison['mean_scores'][1-preferred],
          'source':MODEL_SOURCE,'hard_constraints_checked':True,'evidence':comparison}
    data={'source':SOURCE,'purpose':'train','task_sha256':task.sha256,'goals':goals,'pairs':[pair],
          'unknown_routes_used_as_negative':False,'competitive_quality_labels':False,'public_effect_receipts':assets.effect_receipts(task)}
    data['supervision_sha256']=digest(supervision_projection(data));write(target/'paired-optimizer-supervision.json',data)
    dataset_id='pearl-real-model-optimizer-2207-v1';artifact_id='pearl-fixed-model-pair-001'
    index.freeze({'dataset_id':dataset_id,'experiment_id':'pearl-base-2207-v1','purpose':'train','family':'construction','versions':task.environment['versions'],'opponents':[],'task_sha256':task.sha256})
    index.ingest_construction(dataset_id,artifact_id,task,assets,data,seeds=seeds)
    if stop.exists():raise RuntimeError('Safe stop before optimizer update')
    write(target/'update-in-flight.json',{'artifact_id':artifact_id,'status':'no_automatic_replay'})
    updates=updater.apply_construction('optimizer-base-real-model-001',artifact_id,task,roles=('build_optimizer',))
    checkpoint=target/'after-real-model-optimizer.weights';torch.save(models.save_state(),checkpoint)
    write(target/'feedback-state.json',updater.state_dict());write(target/'latest-pointer.json',{'path':str(checkpoint),'sha256':file_sha(checkpoint)})
    (target/'update-in-flight.json').rename(target/'closed-optimizer-update.json');write(target/'optimizer-update.json',updates)
    summary={'status':'saved_actual_optimizer_base_update','goal_updates':models.builder.updates['build_goal'],
             'optimizer_updates':models.builder.updates['build_optimizer'],'duel_updates':models.duel.updates,'coordinator_updates':models.coordinator.updates,
             'mean_scores':comparison['mean_scores'],'independent_acceptance':False,'incumbent_replaced':False,'formal_course_credit':False}
    write(target/'summary.json',summary);return summary


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
