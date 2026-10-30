"""Explicit closed-course migration, with an old-runtime export and new restore.

Call export_closed_course from the immutable old execution generation, then
migrate_closed_course in the new generation with the actual assets/bots. Neither
function samples a game, updates a model, changes a budget, or edits the parent.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

import torch

from ygo_kito.build_contracts import digest
from ygo_kito.group_runner import tree_digest
from ygo_kito.validation import ContractError


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _readonly_index_identity(root):
    path=Path(root)/'data-index.sqlite3'
    if not path.is_file() or path.is_symlink():raise ContractError('parent index must be an existing regular database')
    if any(Path(str(path)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
        raise ContractError('parent index must have a closed journal boundary before migration')
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        if str(db.execute('PRAGMA journal_mode').fetchone()[0]).lower()!='delete':
            raise ContractError('parent index requires an explicit closed DELETE journal boundary')
        return digest({table:db.execute('SELECT * FROM '+table+' ORDER BY 1,2').fetchall()
                       for table in ('datasets','seeds','artifacts','contents')})


def _preserved_monitor_bundle(parent,saved,state,review):
    controller_path=parent/'scoped-forecast-controller.json'
    if controller_path.is_symlink():raise ContractError('frozen controller must be an original regular file')
    controller=json.loads(controller_path.read_text(encoding='utf-8'))
    if controller.get('kind')!='scoped-course-controller-v3' or not isinstance(controller.get('forecasts'),dict):
        raise ContractError('unsupported frozen controller preserved without conversion')
    database=parent/'coordinator-scoped.sqlite3'
    if not database.is_file() or database.is_symlink() or any(Path(str(database)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
        raise ContractError('frozen coordinator requires its closed original database')
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        if str(db.execute('PRAGMA journal_mode').fetchone()[0]).lower()!='delete':
            raise ContractError('frozen coordinator requires a closed DELETE journal boundary')
        pending=controller.get('pending_evaluation')
        if pending is not None:
            job=db.execute('SELECT state FROM jobs WHERE id=?',(pending['job_id'],)).fetchone()
            if job is None or job[0]!='completed':raise ContractError('uncertain frozen monitoring job cannot be migrated')
    files={'scoped-forecast-controller.json':sha(controller_path),'coordinator-scoped.sqlite3':sha(database)}
    snapshots={}
    for window in controller['forecasts'].values():
        receipt=window['snapshot'];name=receipt['path'];path=parent/name
        if Path(name).name!=name or name!=window['id']+'.weights' or path.is_symlink() or not path.is_file() or sha(path)!=receipt['sha256']:
            raise ContractError('frozen monitor snapshot differs from its original receipt')
        files[name]=receipt['sha256'];snapshots[window['id']]=deepcopy(receipt)
    pending=controller.get('pending_training')
    result={'kind':'source-only-frozen-monitor-preservation-v1','parent_root':str(parent),
        'files':files,'snapshots':snapshots,'controller_bytes_preserved':True,'frozen_model_bindings_preserved':True,
        'scope_rebaselined':False,'observed_bot_source_review_sha256':digest(review),
        'pending_training_sha256':None if pending is None else digest(pending),
        'next_training_match_id':saved['binding']['config']['course_id']+'-train-'+str(sum(r['purpose']=='train' for r in saved['records'])+1),
        'duel_model_sha256':state['effective_hashes']['duel']}
    return result


def export_closed_course(old_course, destination):
    old_course.restore_latest()  # All original binding, manifest/index and RNG checks.
    old_course._assert_registry()
    if old_course.pending is not None or old_course.feedback.pending is not None or old_course.frozen_evaluation is not None:
        raise ContractError("course migration requires a closed training boundary")
    pointer = json.loads((old_course.root/'latest.json').read_text(encoding='utf-8'))
    checkpoint = old_course.root/pointer['path']
    if sha(checkpoint) != pointer['sha256']:
        raise ContractError('parent changed after old-runtime validation')
    payload = {'kind':'validated-old-course-export-v1','parent_root':str(old_course.root.parent.resolve()),
        'parent_pointer':pointer,'saved':torch.load(checkpoint,weights_only=True,map_location='cpu'),
        'kernel_binding':deepcopy(old_course.models.kernel._current_binding())}
    # Read the identity from the executing class' module, never infer a feature
    # generation from tensor shapes or relabel an unvalidated checkpoint.
    import sys
    payload['build_feature_version']=sys.modules[type(old_course.models.builder.models['build_goal']).__module__].FEATURE_VERSION
    path=Path(destination)
    with path.open('xb') as output:torch.save(payload,output)
    return {'path':str(path),'sha256':sha(path),'parent_sha256':pointer['sha256']}


def _upgrade_construction(state, export, assets, binding, *, transition_to_postconstruction_cb):
    from ygo_kito.autonomous_construction import AutonomousConstructionKernel,initialize_course_vocabulary
    from ygo_kito.build_contracts import BuildTask
    from ygo_kito.build_model import FEATURE_VERSION,LEGACY_FEATURE_VERSION,migrate_legacy_ranker
    from ygo_kito.build_training import BuildTrainer,config_from_dict
    from ygo_kito.coordinator_model import CoordinatorTrainer,CoordinatorModelConfig
    from ygo_kito.lora import tensor_digest
    old=deepcopy(state['kernel']);component=state['components']
    legacy=export.get('build_feature_version')==LEGACY_FEATURE_VERSION
    if not legacy:
        if transition_to_postconstruction_cb:raise ContractError('post-construction transition requires the explicit legacy v5 migration')
        if export.get('build_feature_version')!=FEATURE_VERSION:
            raise ContractError('export lacks a supported explicit build feature identity')
        return None,None
    if old['feature_version']!='autonomous-catalog-task-course-v1':
        raise ContractError('v5 export has an unexpected autonomous kernel generation')
    reports={}
    for role in ('build_goal','build_optimizer'):
        model,adam,report=migrate_legacy_ranker(component['models'][role],component['build_optimizers'][role],
            source_feature_version=export['build_feature_version'],source_checkpoint_sha256=export['parent_pointer']['sha256'])
        component['models'][role]=model;component['build_optimizers'][role]=adam
        component['model_hashes'][role]=tensor_digest(model);state['effective_hashes'][role]=tensor_digest(model)
        modes=state['rng']['modes'][role]
        if 'mechanism' in modes:raise ContractError('legacy modes already contain the appended projection')
        modes['mechanism']=modes[''];reports[role]=report
    # Constructors derive the exact target vocabulary, semantic identity and
    # source binding. A migration cannot choose arbitrary replacement hashes.
    with torch.random.fork_rng(devices=[]):
        builder=BuildTrainer(BuildTask.from_dict(state['task']),assets,config_from_dict(state['configs']['build']))
        vocabulary=initialize_course_vocabulary(builder,state['available_ids'],seed=state['vocabulary']['migration']['initialization_seed'])
        coordinator=CoordinatorTrainer(CoordinatorModelConfig(**state['configs']['coordinator']))
        kernel=AutonomousConstructionKernel(builder,coordinator,assets=assets,host_available_ids=state['available_ids'],
            source_binding=binding,allowed_theme_ids=binding.get('construction_theme_ids'))
    target_encoder=builder.encoder.binding()
    if vocabulary!=state['vocabulary']['migration']:
        raise ContractError('construction migration would change vocabulary rows or their initialization history')
    def physical_encoder(value):return {k:v for k,v in value.items() if k not in ('feature_version','semantic_version')}
    if physical_encoder(target_encoder)!=physical_encoder(state['vocabulary']['build']):
        raise ContractError('construction migration would change physical card/annotation/environment indices')
    target_binding=kernel._current_binding()
    def physical_kernel(value):return {k:v for k,v in value.items() if k not in ('feature_version','semantic_version','encoder','source')}
    if physical_kernel(target_binding)!=physical_kernel(export['kernel_binding']):
        raise ContractError('construction migration would change catalog, task, theme or bounds')
    state['vocabulary']['build']=target_encoder
    target=kernel.state_dict();target['updates']=deepcopy(old['updates'])
    target['graph_updates']=deepcopy(old.get('graph_updates',dict.fromkeys(old['updates'],0)))
    target['selections']={} if transition_to_postconstruction_cb else deepcopy(old['selections'])
    target['model_hashes']={r:component['model_hashes'][r] for r in ('build_goal','build_optimizer')}
    for selection in target['selections'].values():selection['binding_sha256']=target['binding_sha256']
    # New mechanism semantics change inferred session requirements. Preserve all
    # old sessions, fills, feedback and proposal seals as a separate immutable
    # archive; rebuild only the live semantic cache, without replaying learning.
    state['kernel']=target
    return {'kind':'explicit-full-construction-v5-to-v6','roles':reports,
        'old_encoder_binding_sha256':digest(old['encoder_binding']),
        'new_encoder_binding_sha256':digest(target_encoder),'archived_kernel_sha256':tree_digest(old),
        'archived_sessions':len(old['sessions']),'live_sessions_rebuilt':0,
        'training_executed':False,'source_objective_preserved':not transition_to_postconstruction_cb},old


def migrate_closed_course(export_receipt, destination, *, assets, bots, source_files, allowed_changed_files,
                          storage_envelope=None,transition_to_postconstruction_cb=False,
                          enable_coordinator_mechanisms=False,observed_bot_source_review=None,
                          preserve_frozen_monitor_windows=False, acknowledged_compute_truncations=()):
    from ygo_kito.coordinator_model import CoordinatorTrainer
    from ygo_kito.course_models import CourseModels
    from ygo_kito.course_feedback import CourseFeedbackUpdater
    from ygo_kito.data_isolation import DataIndex
    from ygo_kito.scenario_course import (ScenarioCourse,index_identity,migrate_training_attempt_state,
        current_course_records,validate_training_attempt_state,verify_partial_game_artifact)
    import sys
    if type(preserve_frozen_monitor_windows) is not bool:raise ContractError('explicit boolean frozen-window preservation policy required')
    path=Path(export_receipt['path'])
    if sha(path)!=export_receipt['sha256']:raise ContractError('old export checksum differs')
    export=torch.load(path,weights_only=True,map_location='cpu')
    if export['kind']!='validated-old-course-export-v1':raise ContractError('wrong migration export kind')
    parent=Path(export['parent_root']).resolve();new=Path(destination).resolve()
    if new.exists() or new==parent or parent.is_relative_to(new):raise ContractError('new generation must not overwrite or contain its parent')
    saved=export['saved'];pointer=export['parent_pointer']
    if Path(pointer['path']).name!=pointer['path']:raise ContractError('parent pointer escapes course root')
    current=json.loads((parent/'course/latest.json').read_text(encoding='utf-8'))
    if current!=pointer or sha(parent/'course'/pointer['path'])!=pointer['sha256']:
        raise ContractError('parent advanced or changed after export')
    if any((parent/'course'/name).exists() for name in ('in-flight.json','feedback-in-flight.json')):
        raise ContractError('uncertain parent transaction preserved')
    if saved['pending'] is not None or saved['feedback']['pending'] is not None or saved['frozen_evaluation'] is not None:
        raise ContractError('cannot migrate unfinished work or an active final evaluation')
    if 'training_attempts' in saved:
        if acknowledged_compute_truncations:raise ContractError('existing attempt ledger cannot receive a second legacy acknowledgment')
        training_attempts=deepcopy(saved['training_attempts'])
    else:
        training_attempts=migrate_training_attempt_state(saved,
            acknowledged_compute_truncations=acknowledged_compute_truncations)
    validate_training_attempt_state(saved,training_attempts,max_attempts=len(saved['binding']['config']['training_seeds']))
    known_legacy={(a['match_id'],a['record_sha256']) for a in training_attempts['legacy_acknowledgments']}
    for record in current_course_records(saved):
        if record['purpose']!='train' or record['complete']:continue
        if (record['match_id'],digest(record)) in known_legacy:continue
        receipts=record.get('receipts',[]);last=receipts[-1] if receipts else {}
        if (record.get('status')!='compute_truncated' or last.get('termination_kind')!='compute_budget' or
                last.get('sample_completed') is not False or last.get('model_update_started') is not False or
                last.get('model_update_completed') is not False or last.get('partial_game') is None):
            raise ContractError('unresolved native/model transaction cannot be cleared by a source-only migration')
    if saved.get('desired')=='needs_inspection' and not acknowledged_compute_truncations:
        raise ContractError('inspection stop requires an explicit proven legacy compute-truncation acknowledgment')
    # DataIndex.__init__ performs an application-id/schema write transaction.
    # Never open the parent through that constructor, even for an identity read.
    if _readonly_index_identity(parent/'index')!=saved['data_index_sha256']:raise ContractError('parent data index differs')
    state=deepcopy(saved['models'])
    if state['state_sha256']!=tree_digest({k:v for k,v in state.items() if k!='state_sha256'}):
        raise ContractError('old full-model state checksum differs')
    if state['binding_sha256']!=digest(state['binding']) or digest(export['kernel_binding'])!=state['kernel']['binding_sha256']:
        raise ContractError('old source/kernel bindings differ')
    if state['binding'].get('learning_stage')!='base' or state['adapters']:
        raise ContractError('this migration preserves the current base course; LoRA requires a separately specified adapter migration')
    original=deepcopy(state);binding=deepcopy(state['binding'])
    package=Path(sys.modules[CourseModels.__module__].__file__).parent
    actual_source={'src/ygo_kito/'+p.name:sha(p) for p in package.glob('*.py')}
    if source_files!=actual_source:raise ContractError('target source map differs from the executing package')
    changed={p for p in set(binding['source_files'])|set(source_files) if binding['source_files'].get(p)!=source_files.get(p)}
    if changed!=set(allowed_changed_files):raise ContractError('source changes differ from the explicitly reviewed migration set')
    binding['source_files']=deepcopy(source_files)
    if observed_bot_source_review is not None:
        from ygo_kito.observed_bot_evidence import validate_source_review_schema
        review=validate_source_review_schema(observed_bot_source_review)
        if review['to_source_map']!={Path(name).name:value for name,value in source_files.items()}:
            raise ContractError('observed bot source review target differs from the migrated source')
        if not any(getattr(bot['runtime'],'qualification',{}).get('sha256')==review['qualification_sha256'] for bot in bots.values()):
            raise ContractError('observed bot source review qualification is absent from the migrated bots')
        binding['observed_bot_source_review']=review
    if type(enable_coordinator_mechanisms) is not bool:
        raise ContractError('explicit boolean mechanism migration policy required')
    if enable_coordinator_mechanisms:
        if state['configs']['coordinator'].get('mechanism_inputs',False):
            raise ContractError('coordinator already uses mechanisms; no implicit repeat migration')
        binding['coordinator_mechanism_inputs']=True
    if type(transition_to_postconstruction_cb) is not bool:raise ContractError('explicit boolean construction policy transition required')
    previous_policy={k:deepcopy(binding.get(k)) for k in ('construction_goal','construction_flow','basic_cb_stage',
        'construction_card_requirements','construction_logic_requirements')}
    if transition_to_postconstruction_cb:
        if state['task']['requirements']:raise ContractError('cannot remove explicit base-task card requirements during a policy migration')
        goal=deepcopy(binding.get('construction_goal',state['task']['goal']))
        if goal.get('kind')!='deck_constraints':raise ContractError('post-construction transition requires the explicit constraint goal')
        for key in ('route_goal','required_activations','required_chain_resolutions'):goal.pop(key,None)
        binding.update(construction_goal=goal,basic_cb_stage='after_construction',
            construction_flow='four_concrete_handoffs_then_basic_cb_inference_v3',construction_card_requirements=[],
            construction_logic_requirements={'tags':[],'connector_kinds':[]})
    state['binding']=binding;state['binding_sha256']=digest(binding)
    component=state['components'];old_model=component['models']['coordinator']
    if 'scope_projection.weight' not in old_model:
        upgraded,upgrade=CoordinatorTrainer.upgrade_aggregate_state({'config':state['configs']['coordinator'],
            'feature_version':'coordinator-aggregate-context-v1','execution':state['execution'],'device_rng':state['device_rng'],
            'model':old_model,'model_sha256':component['model_hashes']['coordinator'],
            'optimizer':component['coordinator_optimizer'],'scheduler':component['coordinator_scheduler'],
            'batch_rng':state['rng']['coordinator_batch'],'updates':state['cursors']['coordinator_updates']})
        component['models']['coordinator']=upgraded['model'];component['model_hashes']['coordinator']=upgraded['model_sha256']
        component['coordinator_optimizer']=upgraded['optimizer'];component['coordinator_scheduler']=upgraded['scheduler']
        state['effective_hashes']['coordinator']=upgraded['model_sha256']
        modes=state['rng']['modes']['coordinator']
        for name in ('scope_projection','budget_head'):
            if name in modes:raise ContractError('legacy mode metadata already contains a new module')
            modes[name]=modes['']
    else:upgrade={'kind':'source-only-coordinator-course-migration','training_executed':False}
    mechanism_upgrade=None
    if enable_coordinator_mechanisms:
        from ygo_kito.coordinator_model import FEATURE_VERSION
        previous_model=deepcopy(component['models']['coordinator'])
        previous_optimizer=deepcopy(component['coordinator_optimizer'])
        upgraded,mechanism_upgrade=CoordinatorTrainer.upgrade_mechanism_state({
            'config':state['configs']['coordinator'],'feature_version':FEATURE_VERSION,
            'execution':state['execution'],'device_rng':state['device_rng'],
            'model':previous_model,'model_sha256':component['model_hashes']['coordinator'],
            'optimizer':previous_optimizer,'scheduler':component['coordinator_scheduler'],
            'batch_rng':state['rng']['coordinator_batch'],'updates':state['cursors']['coordinator_updates']})
        if any(not torch.equal(value,upgraded['model'][name]) for name,value in previous_model.items()):
            raise ContractError('mechanism extension changed an existing coordinator tensor')
        if tree_digest(previous_optimizer['state'])!=tree_digest(upgraded['optimizer']['state']):
            raise ContractError('mechanism extension changed existing coordinator Adam moments')
        if tree_digest(upgraded['batch_rng'])!=tree_digest(state['rng']['coordinator_batch']):
            raise ContractError('mechanism extension changed coordinator sampling RNG')
        component['models']['coordinator']=upgraded['model']
        component['model_hashes']['coordinator']=upgraded['model_sha256']
        component['coordinator_optimizer']=upgraded['optimizer']
        component['coordinator_scheduler']=upgraded['scheduler']
        state['configs']['coordinator']=upgraded['config']
        state['effective_hashes']['coordinator']=upgraded['model_sha256']
        modes=state['rng']['modes']['coordinator']
        if 'mechanism_projection' in modes:raise ContractError('legacy modes already contain mechanism projection')
        modes['mechanism_projection']=modes['']
    construction_upgrade,archived_kernel=_upgrade_construction(state,export,assets,binding,
        transition_to_postconstruction_cb=transition_to_postconstruction_cb)
    if construction_upgrade is None:
        kernel_binding=deepcopy(export['kernel_binding']);kernel_binding['source']=binding
        state['kernel']['binding_sha256']=digest(kernel_binding)
        for selection in state['kernel']['selections'].values():selection['binding_sha256']=state['kernel']['binding_sha256']
    invalidated=deepcopy((archived_kernel or state['kernel'])['proposal_seals']);state['kernel']['proposal_seals']=[]
    state['state_sha256']=tree_digest({k:v for k,v in state.items() if k!='state_sha256'})
    models=CourseModels.from_state(state,assets=assets,expected_binding=binding)  # Exact tensor/vocab/optimizer/kernel checks.
    for key in ('cursors','task','available_ids'):
        if tree_digest(state[key])!=tree_digest(original[key]):raise ContractError('migration changed '+key)
    expected_vocabulary=deepcopy(original['vocabulary'])
    if construction_upgrade is not None:expected_vocabulary['build']=state['vocabulary']['build']
    if tree_digest(expected_vocabulary)!=tree_digest(state['vocabulary']):raise ContractError('migration changed vocabulary history or duel IDs')
    expected_rng=deepcopy(original['rng'])
    if 'scope_projection' not in expected_rng['modes']['coordinator']:
        for name in ('scope_projection','budget_head'):
            expected_rng['modes']['coordinator'][name]=expected_rng['modes']['coordinator']['']
    if construction_upgrade is not None:
        for role in ('build_goal','build_optimizer'):expected_rng['modes'][role]['mechanism']=expected_rng['modes'][role]['']
    if mechanism_upgrade is not None:
        expected_rng['modes']['coordinator']['mechanism_projection']=expected_rng['modes']['coordinator']['']
    if tree_digest(state['rng'])!=tree_digest(expected_rng):raise ContractError('migration changed an RNG stream or an existing module mode')
    for role in ('duel','build_goal','build_optimizer'):
        if construction_upgrade is not None and role.startswith('build_'):
            for key,value in original['components']['models'][role].items():
                if not torch.equal(value,component['models'][role][key]):raise ContractError('migration changed an existing construction tensor')
            before=original['components']['build_optimizers'][role];after=component['build_optimizers'][role]
            if tree_digest(before['state'])!=tree_digest(after['state']):raise ContractError('migration changed existing construction Adam moments')
            expected=deepcopy(before);expected['param_groups'][0]['params'].append(max(expected['param_groups'][0]['params'],default=-1)+1)
            if tree_digest(expected)!=tree_digest(after):raise ContractError('migration changed construction Adam configuration')
            continue
        if tree_digest(component['models'][role])!=tree_digest(original['components']['models'][role]):
            raise ContractError('migration changed another role')
    for key in ('build_optimizers','build_schedulers','duel_optimizer','duel_scheduler'):
        if construction_upgrade is not None and key=='build_optimizers':continue
        if tree_digest(component[key])!=tree_digest(original['components'][key]):
            raise ContractError('migration changed another role optimizer or scheduler')
    monitor_preservation=None
    if (parent/'scoped-forecast-controller.json').exists():
        if not preserve_frozen_monitor_windows:
            raise ContractError('existing frozen monitor windows require an explicit window-preserving migration')
        from ygo_kito.scenario_course import bot_binding
        if (observed_bot_source_review is None or upgrade['kind']!='source-only-coordinator-course-migration' or
                enable_coordinator_mechanisms or transition_to_postconstruction_cb or mechanism_upgrade is not None or
                construction_upgrade is not None or {name:bot_binding(bot) for name,bot in bots.items()}!=saved['binding']['bots']):
            raise ContractError('frozen windows require an explicitly reviewed source-only migration with the same models, task and bots')
        monitor_preservation=_preserved_monitor_bundle(parent,saved,state,binding['observed_bot_source_review'])
    elif preserve_frozen_monitor_windows:
        raise ContractError('frozen-window preservation requires the existing original controller')
    new.mkdir()
    if monitor_preservation is not None:
        for name,expected in monitor_preservation['files'].items():
            shutil.copyfile(parent/name,new/name)
            if sha(new/name)!=expected:raise ContractError('preserved frozen monitoring bytes changed during copy')
    if archived_kernel is not None:
        with (new/'pre-mechanism-kernel.weights').open('xb') as output:torch.save(archived_kernel,output)
    if transition_to_postconstruction_cb:
        with (new/'pre-policy-construction.weights').open('xb') as output:
            torch.save({k:deepcopy(saved[k]) for k in ('selection','deck','construction')},output)
    shutil.copytree(parent/'index',new/'index')
    for name in ('actual-forecast-ledger.json','initial-four-stage-construction.json'):
        if (parent/name).exists():shutil.copyfile(parent/name,new/name)
    for path in list(parent.glob('construction-route-*.json'))+list(parent.glob('collaboration-*/route-*.json')):
        target=new/path.relative_to(parent);target.parent.mkdir(parents=True,exist_ok=True)
        if path.is_symlink():raise ContractError('construction proof symlink is not migrated')
        shutil.copyfile(path,target)
    if (parent/'corrected-flow-continuation.json').exists():
        shutil.copyfile(parent/'corrected-flow-continuation.json',new/'corrected-flow-continuation.json')
    course=ScenarioCourse(models,assets=assets,data_index=DataIndex(new/'index'),config=deepcopy(saved['binding']['config']),
        state_root=new/'course',bots=bots,storage_envelope=storage_envelope)
    for key in ('records','events','active_seconds','selection','construction','evaluation_cursor','desired','initial_model_execution'):
        setattr(course,key,deepcopy(saved[key]))
    course.training_attempt_cursor=training_attempts['next_cursor']
    course._legacy_attempt_acknowledgments=deepcopy(training_attempts['legacy_acknowledgments'])
    for record in saved['records']:
        for game_receipt in record.get('receipts',[]):
            artifact=game_receipt.get('partial_game')
            if artifact is None:continue
            source=verify_partial_game_artifact(parent/'course',artifact)
            target=course.root/artifact['path']
            if target.exists():raise ContractError('partial-game migration target already exists')
            shutil.copyfile(source,target)
    if course.selection is not None:course.selection['binding_sha256']=models.kernel._binding_sha256
    course.deck=None if saved['deck'] is None else __import__('ygo_kito.build_contracts',fromlist=['DeckParts']).DeckParts.from_dict(saved['deck'])
    if transition_to_postconstruction_cb:course.selection=course.deck=course.construction=None
    # A legacy name is mapped only here, with both old proof and its provenance retained.
    if course.construction and 'basic_cb' not in course.construction and course.construction.get('final_cb'):
        basic=deepcopy(course.construction['final_cb']);basic['subject_deck_sha256']=digest(course.construction['best']['deck'])
        course.construction['basic_cb']=basic
    feedback=deepcopy(saved['feedback']);feedback['binding_sha256']=course.feedback.binding_sha256
    feedback['model_hashes']={r:models.versions()[r] for r in feedback['model_hashes']}
    feedback['metadata_sha256']=digest({k:v for k,v in feedback.items() if k!='metadata_sha256'})
    course.feedback.load_state_dict(feedback)  # Re-check every consumed indexed artifact.
    receipt={'kind':'explicit-full-integrated-course-migration-v2','parent_checkpoint_sha256':pointer['sha256'],
        'parent_data_index_sha256':saved['data_index_sha256'],'source_changes':sorted(changed),'upgrade':upgrade,
        'coordinator_mechanism_upgrade':mechanism_upgrade,
        'construction_upgrade':construction_upgrade,
        'archived_kernel_file_sha256':sha(new/'pre-mechanism-kernel.weights') if archived_kernel is not None else None,
        'invalidated_old_proposal_seals':invalidated,'training_executed':False,'old_root_modified':False,
        'resume_authorized':False,'source_objective_transition_performed':transition_to_postconstruction_cb,
        'previous_construction_policy':previous_policy,
        'training_attempts':deepcopy(training_attempts),
        'acknowledged_compute_truncations':list(acknowledged_compute_truncations),
        'legacy_compute_truncations_are_terminal':False,'legacy_match_records_preserved':True,
        'optimizer_steps_added':0,'active_seconds_added':0,
        'frozen_monitor_preservation':monitor_preservation,
        'active_construction_archive_sha256':sha(new/'pre-policy-construction.weights') if transition_to_postconstruction_cb else None,
        'old_match_records_relabelled_as_repaired_flow':False}
    course.events.append(receipt);course.desired='paused'
    course.save();course.restore_latest()  # New manifest/source/index/model/feedback restoration must pass.
    if course.active_seconds!=saved['active_seconds'] or course.records!=saved['records']:
        raise ContractError('course accounting/history changed')
    (new/'model-binding.json').write_text(json.dumps(binding,indent=2)+'\n',encoding='utf-8')
    (new/'course-config.json').write_text(json.dumps(course.config,indent=2)+'\n',encoding='utf-8')
    initial=models.save_state()
    with (new/'initial-full.weights').open('xb') as output:torch.save(initial,output)
    (new/'initial-pointer.json').write_text(json.dumps({'path':str(new/'initial-full.weights'),'sha256':sha(new/'initial-full.weights')})+'\n',encoding='utf-8')
    (new/'coordinator-migration.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    return course,receipt
