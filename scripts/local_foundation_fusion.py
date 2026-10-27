"""Actual Pearl effect-block construction, fusion proof and goal base learning."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile

def run(base,directory,stop,status,*,resume=False):
    source=base/'source';sys.path.insert(0,str(source/'src'))
    # Restore exact runtime bytes after a WSL restart; N remains authoritative.
    manifest=json.loads((base/'reports/native-runtime-cache-source-manifest.json').read_text())
    runtime=Path(manifest['cache_root']);archive=base/'cache/native-runtime-42b468cc.tar'
    if not runtime.exists():
        status('restoring_byte_identical_native_runtime_cache')
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=manifest['archive_sha256']:raise RuntimeError('Native cache archive changed')
        runtime.mkdir()
        with tarfile.open(archive,'r:') as bundle:
            if {m.name for m in bundle.getmembers()}!=set(manifest['files']):raise RuntimeError('Cache member set differs')
            for member in bundle.getmembers():
                if not member.isfile() or Path(member.name).is_absolute() or '..' in Path(member.name).parts:raise RuntimeError('Unsafe cache member')
                data=bundle.extractfile(member).read();expected=manifest['files'][member.name]
                if len(data)!=expected['size'] or hashlib.sha256(data).hexdigest()!=expected['sha256']:raise RuntimeError('Cache bytes differ')
                path=runtime/member.name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    status('loading_existing_base_models_for_actual_construction')
    import torch
    from ygo_kito.autonomous_construction import _SharedLogicAdapter
    from ygo_kito.build_contracts import BuildTask,DeckParts,digest
    from ygo_kito.build_pipeline import verify_goal
    from ygo_kito.build_training import supervision_projection
    from ygo_kito.construction_binding import CatalogBindingAdapter,PublicFactTag
    from ygo_kito.construction_controller import ConstructionController
    from ygo_kito.construction_effect_blocks import pearl_effect_blocks
    from ygo_kito.construction_logic import ConstructionSession,ThemeScope,LogicTag
    from ygo_kito.construction_model import LogicCodec
    from ygo_kito.build_intent import IntentClassification
    from ygo_kito.course_models import CourseModels
    from ygo_kito.course_game_adapter import course_config_from_dict
    from ygo_kito.course_feedback import CourseFeedbackUpdater
    from ygo_kito.data_isolation import DataIndex
    from ygo_kito.group_runner import tree_digest
    from ygo_kito.period_runtime import PeriodBuildAssets
    from ygo_kito.semantic_training import SOURCE
    torch.set_num_threads(2)
    old=source/'.cache/local-base-training-20261027/2207-base-004'
    prior_feedback_root=source/'.cache/local-base-training-20261027/2207-base-002'
    target=source/'.cache/local-base-training-20261027/2207-base-005'
    def read(p):return json.loads(p.read_text(encoding='utf-8'))
    def write(p,v):
        temp=p.with_name(p.name+'.tmp');temp.write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');temp.replace(p)
    assets=PeriodBuildAssets(runtime,'2022-07',read(old/'active-environment.local.json'),base,adapter_revision=5,evidence_source='user_supplied')
    actual={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((source/'src/ygo_kito').glob('*.py'))}
    if target.exists():
        if not resume:raise RuntimeError('Existing fusion attempt preserved; inspect then Resume')
        if (target/'update-in-flight.json').exists():raise RuntimeError('Uncertain update must be inspected; no automatic replay')
        pointer=read(target/'latest-pointer.json');checkpoint=Path(pointer['path']);binding=read(target/'binding.json')
        if binding['source_files']!=actual:raise RuntimeError('Resume source differs; explicit migration required')
        if hashlib.sha256(checkpoint.read_bytes()).hexdigest()!=pointer['sha256']:raise RuntimeError('Saved state changed')
        models=CourseModels.from_state(torch.load(checkpoint,map_location='cpu',weights_only=False),assets=assets,expected_binding=binding)
    else:
        pointer=read(old/'latest-pointer.json');checkpoint=Path(pointer['path'])
        if hashlib.sha256(checkpoint.read_bytes()).hexdigest()!=pointer['sha256']:raise RuntimeError('Previous full state changed')
        state=torch.load(checkpoint,map_location='cpu',weights_only=False)
        if state['state_sha256']!=tree_digest({k:v for k,v in state.items() if k!='state_sha256'}):raise RuntimeError('State integrity differs')
        changed={p for p in set(actual)|set(state['binding']['source_files']) if actual.get(p)!=state['binding']['source_files'].get(p)}
        allowed={'src/ygo_kito/'+n+'.py' for n in ('construction_fill','duel_model','build_contracts','build_model','build_pipeline','build_semantics','extra_routes','route_search','autonomous_construction','construction_effect_blocks','fusion_witness','build_training')}
        if not changed or not changed<=allowed:raise RuntimeError('Unexpected source migration: '+repr(changed-allowed))
        binding=deepcopy(state['binding']);binding['source_files']=actual
        temporary=CourseModels.initialize(BuildTask.from_dict(state['task']),assets,course_config_from_dict(state['configs']['duel']),state['configs']['adapters'],source,None,state['available_ids'],binding,device='cpu')
        for role,model in temporary.models().items():model.load_state_dict(state['components']['models'][role],strict=True)
        temporary.kernel.updates=deepcopy(state['kernel']['updates'])
        migrated=deepcopy(state);migrated['binding']=binding;migrated['binding_sha256']=digest(binding);migrated['kernel']=temporary.kernel.state_dict()
        migrated['state_sha256']=tree_digest({k:v for k,v in migrated.items() if k!='state_sha256'})
        models=CourseModels.from_state(migrated,assets=assets,expected_binding=binding)
        restored=models.save_state()
        if tree_digest(restored['components'])!=tree_digest(state['components']) or tree_digest(restored['rng'])!=tree_digest(state['rng']) or restored['cursors']!=state['cursors']:raise RuntimeError('Migration changed learning state')
        target.mkdir();shutil.copytree(old/'index',target/'index')
        for name in ('active-environment.local.json','generated-deck.json','selected-task.json'):shutil.copyfile(old/name,target/name)
        write(target/'binding.json',binding)
        torch.save(restored,target/'migrated-initial.weights')
        write(target/'latest-pointer.json',{'path':str(target/'migrated-initial.weights'),'sha256':hashlib.sha256((target/'migrated-initial.weights').read_bytes()).hexdigest()})
        write(target/'migration.json',{'kind':'explicit-functional-source-migration','source_checkpoint_sha256':pointer['sha256'],'changed_source_files':sorted(changed),'weights_optimizers_rng_cursors_preserved':True,'original_kernel_sessions_archived':str(old),'runtime_root':str(runtime),'native_receipt_unchanged':True})
    index=DataIndex(target/'index');updater=CourseFeedbackUpdater(models,index,'pearl-base-2207-v1')
    prior=read(target/'feedback-state.json') if (target/'feedback-state.json').exists() else read((old if (old/'feedback-state.json').exists() else prior_feedback_root)/'feedback-state.json')
    if prior['pending'] is not None:raise RuntimeError('Prior feedback update is uncertain')
    rebound=updater.state_dict();rebound['consumed']=deepcopy(prior['consumed']);rebound['metadata_sha256']=digest({k:v for k,v in rebound.items() if k!='metadata_sha256'});updater.load_state_dict(rebound)
    raw=read(old/'selected-task.json');raw=raw['task'] if 'task' in raw else raw
    # Concrete route conditions come from the reviewed current card texts, not a reference deck.
    needed={73956664,74078255,92731385};pool=set(raw['pool'])|needed
    while len(pool)>128:pool.remove(max(c for c in pool if c not in needed and c not in {x[0] for x in __import__('ygo_kito.construction_effect_blocks',fromlist=['REVIEWS']).REVIEWS}))
    raw['pool']=sorted(pool);raw['task_id']='pearl-self-constructed-grave-fusion-001'
    from dataclasses import asdict
    _,source_reviews=pearl_effect_blocks(assets,raw['pool'])
    fusion_review=next(asdict(a) for a in source_reviews if a.card_id==74078255 and a.tag.value=='墓地融合')
    fusion_review['tag']={'dimension':'effect_type','value':'fusion_summon'}
    # This is one curriculum instance of a generic effect/material witness.
    witness={'effect_assessments':[fusion_review],'minimum_materials':2,
             'allowed_destination_zones':[1],'required_source_zones':[16]}
    raw['goal']['route_goal']={'kind':'fusion_summon','card_id':92731385,
        'starting_conditions':{'player':0,'turn':1,'requires_opening_hand':[73956664]},'fusion_witness':witness}
    raw['goal']['required_activations']=[73956664,74078255];raw['goal']['required_chain_resolutions']=[73956664,74078255]
    requirements={(r['zone'],r['card_id']):r for r in raw['requirements']}
    for zone,code in [('main',73956664),('main',74078255),('extra',92731385)]:
        requirements[(zone,code)]={'zone':zone,'card_id':code,'minimum':max(1,requirements.get((zone,code),{}).get('minimum',0)),'maximum':3}
    raw['requirements']=list(requirements.values());task=BuildTask.from_dict(raw);write(target/'fusion-task.json',task.to_dict())
    tags,assessments=pearl_effect_blocks(assets,task.pool)
    if len(tags)!=2:raise RuntimeError('Required source-reviewed effect blocks are unavailable')
    tag=LogicTag('field','setcode:181');fact=PublicFactTag(tag,'setcode',0x181,'actual-host-catalog:'+assets.receipt['resources']['cards'])
    binding_adapter=CatalogBindingAdapter(assets,fact_tags=(fact,),assessments=assessments)
    adapter=_SharedLogicAdapter(task,models.builder,LogicCodec(tags),models.kernel.updates)
    session=ConstructionSession('珠泪主题：卡组送墓·墓地融合，具体融合目标与发动条件见任务',task)
    session.classification=IntentClassification('narrow',1.0,('setcode:181',),reasons=('explicit internal fixed-theme assignment; not text classifier confidence',))
    controller=ConstructionController(adapter,binding_adapter,models.coordinator)
    route_counter=0
    def verifier(t,d,a):
        nonlocal route_counter
        if stop.exists():raise RuntimeError('Safe stop requested before the next native route')
        route_counter+=1
        status('actual_fusion_route_search',task_sha256=t.sha256,deck_sha256=digest(d.to_dict()),native_execution=True,route_attempt=route_counter)
        proof=verify_goal(t,d,a,seconds=30.,attempts=64,decision_budget=100)
        write(target/('route-attempt-'+str(route_counter).zfill(3)+'.json'),{'task_sha256':t.sha256,'deck':d.to_dict(),'proof':proof})
        status(last_route_result=proof['status'])
        return proof
    status('actual_effect_blocks_goal_optimizer_goal_optimizer',checkpoint=str(target/'latest-pointer.json'),reference_inputs=[])
    if resume and (target/'actual-fusion-four-stage.json').exists():
        result=read(target/'actual-fusion-four-stage.json')
        if result.get('goal_sha256')!=session.goal_sha256 or result.get('status')!='task_checked_candidate':
            raise RuntimeError('Prior construction does not provide this exact verified goal; no automatic replay')
        status('reusing_completed_actual_four_stage_construction',construction_replayed=False)
    else:
        result=controller.run(session,scopes=(ThemeScope('setcode:181','setcode',0x181,fact.source,1),),verifier=verifier)
        write(target/'actual-fusion-four-stage.json',result)
    if result['status']!='task_checked_candidate' or not result.get('incumbent_verified_for_task'):
        raise RuntimeError('Actual fusion construction unresolved; inspect the saved real attempts')
    best=result['best'];deck=DeckParts.from_dict(best['deck'])
    evidence=next(a['engine_validation'] for a in best['validation']['attempts'] if a.get('engine_validation',{}).get('status')=='constraints_and_route_verified' and a.get('best_deck')==deck.to_dict())
    # Manager-facing construction outputs correctly remove private view keys.
    # Training admission must consume the separate host-owned full replay proof.
    public_evidence=evidence
    private_matches=[read(p)['proof'] for p in sorted(target.glob('route-attempt-*.json'))
                     if read(p).get('task_sha256')==task.sha256 and read(p).get('deck')==deck.to_dict()
                     and read(p)['proof'].get('status')=='constraints_and_route_verified']
    if not private_matches:raise RuntimeError('Exact private route receipt unavailable; do not weaken replay admission')
    evidence=private_matches[-1]
    if evidence['native_route']['trajectory_sha256']!=public_evidence['native_route']['trajectory_sha256']:
        raise RuntimeError('Private route is not the public construction witness')
    if not evidence['native_route']['route_evidence'].get('private_selection_key_audit_only'):
        raise RuntimeError('Private host replay key unavailable')
    if not evidence['native_route']['route_evidence'].get('fusion_summon_evidence'):raise RuntimeError('No actual fusion/material certificate')
    data={'source':SOURCE,'purpose':'train','task_sha256':task.sha256,'goals':[
        {'deck':deck.to_dict(),'label':1.,'source':'pinned_constraints_and_actual_native_route','evidence':evidence},
        {'deck':DeckParts(deck.main[:-1],deck.extra,deck.side).to_dict(),'label':0.,'source':'explicit_hard_constraint_failure','evidence':{'status':'hard_constraint_failure','reason':'main section has one missing card'}}],
        'pairs':[],'unknown_routes_used_as_negative':False,'competitive_quality_labels':False,'public_effect_receipts':assets.effect_receipts(task)}
    data['supervision_sha256']=digest(supervision_projection(data));write(target/'fusion-goal-supervision.json',data)
    dataset_id='pearl-fusion-goal-2207-v1';artifact_id='pearl-fusion-actual-goal-001'
    index.freeze({'dataset_id':dataset_id,'experiment_id':'pearl-base-2207-v1','purpose':'train','family':'construction','versions':task.environment['versions'],'opponents':[],'task_sha256':task.sha256})
    index.ingest_construction(dataset_id,artifact_id,task,assets,data,seeds=tuple(r['seed_audit_only'] for r in evidence['native_route']['core_attempts']))
    if stop.exists():raise RuntimeError('Safe stop requested before goal update')
    write(target/'update-in-flight.json',{'artifact_id':artifact_id,'status':'no_automatic_replay'})
    update=updater.apply_construction('goal-base-fusion-001',artifact_id,task,roles=('build_goal',))
    checkpoint=target/'after-fusion-goal.weights';torch.save(models.save_state(),checkpoint)
    write(target/'feedback-state.json',updater.state_dict());write(target/'generated-deck.json',deck.to_dict())
    write(target/'latest-pointer.json',{'path':str(checkpoint),'sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest()})
    (target/'update-in-flight.json').rename(target/'closed-goal-update.json')
    write(target/'goal-update.json',update)
    summary={'goal_updates':models.builder.updates['build_goal'],'optimizer_updates':models.builder.updates['build_optimizer'],'duel_updates':models.duel.updates,'coordinator_updates':models.coordinator.updates,'formal_course_bo1':0,'formal_course_bo3':0,'conditional_fusion_verified':True,'whole_graph_execution_verified':False,'competitive_strength_verified':False,'comparison_training':'pending_fixed_driver_paired_games','checkpoint':str(checkpoint)}
    write(target/'summary.json',summary);status('saved_actual_fusion_goal_base_update',**summary)
    return summary
