"""Continue actual historical base learning through the existing match course.

The initial opponent is the existing historical-legal bot baseline. This does
not certify common-deck coverage, mirror strength or any final acceptance.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time


class CycleBudgetExhausted(RuntimeError):
    pass


class CycleBudget:
    """One absolute deadline shared by construction, CB, sampling and replay."""
    def __init__(self, course, *, clock=time.monotonic):
        self.clock = clock
        self.deadline = clock() + max(0., course.config['wall_seconds']-course.active_seconds)

    def remaining(self):
        return max(0., self.deadline-self.clock())

    def check(self, stage, *, required=0., allowance=None):
        left=self.remaining()
        if allowance is not None:left=min(left,max(0.,allowance))
        if left <= 0 or left < required:
            raise CycleBudgetExhausted('Insufficient remaining course budget at '+stage)
        return left


def publish_course_status(status,stage,course,**details):
    """Publish the current course counters without changing their saved source."""
    models=course.models
    status(stage,course=course.status(),goal_updates=models.builder.updates['build_goal'],
        optimizer_updates=models.builder.updates['build_optimizer'],duel_updates=models.duel.updates,
        coordinator_updates=models.coordinator.updates,latest_checkpoint=str(course.root/'latest.json'),**details)


def execute_cycle(course, forecasts, construction, base, target, stop, status, max_units, *, unit_boundary=None):
    """Execute the learned allocation only between indivisible four-step cycles."""
    from ygo_kito.training_admission import TrainingAdmissionDeferred
    planned_at,accounted=time.monotonic(),course.active_seconds
    plan = forecasts.decide(max_units)
    course.active_seconds+=max(0.,time.monotonic()-planned_at-(course.active_seconds-accounted))
    action, allocated = plan['action'], plan['budget_units']
    publish_course_status(status,'complete_cycle_planned',course,action=action,allocated_units=allocated)
    if action == 'stop':
        course.desired = 'paused'; course.save()
        return {'action': action, 'executed_units': 0, 'paused': True}
    if action not in ('build_goal','build_optimizer','train_duel','evaluate_duel'):
        raise RuntimeError('Host safety action needs inspection before executing: '+action)
    executed = 0
    budget = CycleBudget(course)
    for _ in range(allocated):
        if stop.exists() or course.active_seconds >= course.config['wall_seconds']:
            break
        # Re-check hard guards after every complete unit, including each game in
        # a multi-game allocation. The model cannot spend past a new alert.
        current = forecasts.status()
        if unit_boundary is not None:
            checked_at=time.monotonic();verdict=unit_boundary('before',course,forecasts,plan,executed)
            course.active_seconds+=time.monotonic()-checked_at
            if verdict is not True:
                course.desired='paused';course.save()
                return {'action':action,'executed_units':executed,'paused':True,'reason':'unit_supervisor_stopped_before_next_unit'}
        try:
            budget.check('complete_cycle_boundary')
        except CycleBudgetExhausted:
            course.desired='paused';course.save()
            return {'action':action,'executed_units':executed,'paused':True,'reason':'course_budget_exhausted'}
        publish_course_status(status,'complete_cycle_unit_ready',course,
            action=action,executed_units=executed,allocated_units=allocated)
        if action == 'train_duel':
            if current['mandatory_rebuild']:
                break
            try: budget.check('before_training_game',required=course.models.duel.config.episode_seconds)
            except CycleBudgetExhausted:
                course.desired='paused';course.save()
                return {'action':action,'executed_units':executed,'paused':True,'reason':'insufficient_training_game_reserve'}
            try:
                forecasts.require_formal_duel('train')
                forecasts.before_training()
                course.run(1)
            except TrainingAdmissionDeferred as error:
                if not any((course.root/name).exists() for name in ('in-flight.json','feedback-in-flight.json')):
                    course.desired='paused';course.save()
                    error.safe_boundary_saved=True;error.pause_requested=True
                raise
            publish_course_status(status,'saved_training_game_boundary',course,
                action=action,executed_units=executed,allocated_units=allocated)
            forecasts.train_closed_outcomes()
        elif action == 'evaluate_duel':
            try: actual=forecasts.evaluate(1,budget=budget)
            except TrainingAdmissionDeferred as error:
                if not any((course.root/name).exists() for name in ('in-flight.json','feedback-in-flight.json')):
                    course.desired='paused';course.save()
                    error.safe_boundary_saved=True;error.pause_requested=True
                raise
            except CycleBudgetExhausted:
                course.desired='paused';course.save()
                return {'action':action,'executed_units':executed,'paused':True,'reason':'insufficient_monitor_reserve'}
            if actual == 0:
                course.desired='paused';course.save()
                return {'action':action,'executed_units':executed,'paused':True,'reason':'monitor_window_requires_new_action'}
        else:
            started,accounted = time.monotonic(),course.active_seconds
            mandatory=current['mandatory_rebuild'] or plan.get('admission_signals',{}).get('mandatory_rebuild') is True
            discrepancy = {'kind':'force_goal_reconstruction' if mandatory else 'reassess_construction',
                'forecast_id':forecasts.value['active_forecast'],'status':current,
                'actual_training_feedback':plan.get('training_feedback_review'),
                'training_admission':plan.get('training_admission'),'admission_signals':plan.get('admission_signals')}
            cycle_id = str(len(forecasts.value['decisions']))+'-'+str(executed)
            # The shared collaboration helper owns candidate adoption/role
            # admission. See the small companion integration patch for cycle_id.
            try:
                # The absolute deadline, not a fresh 7200-second allowance, is
                # passed through the shared adapter to every expensive child.
                result=construction(course,base,target,stop,status,initial=False,
                    force_rebuild=mandatory,feedback=discrepancy,cycle_id=cycle_id,budget=budget,
                    comparison_policy=getattr(forecasts,'comparison_policy',None))
            except CycleBudgetExhausted:
                uncertain=getattr(budget,'in_flight',False)
                course.desired='needs_inspection' if uncertain else 'paused'
                return {'action':action,'executed_units':executed,'paused':True,'safe_boundary_saved':not uncertain,
                        'reason':'uncertain_construction_transaction' if uncertain else 'construction_budget_boundary'}
            finally:
                course.active_seconds += max(0.,time.monotonic()-started-(course.active_seconds-accounted))
                course.save()
            trigger=next((row.get('attempt_id') for row in
                (plan.get('training_admission') or {}).get('evidence_refs',[])
                if row.get('kind')=='conditional_cb_optimization_signal'),None)
            acknowledge=getattr(getattr(course,'comparison_policy',None),'review_completed',None)
            if trigger is not None and callable(acknowledge) and isinstance(result,dict) and result.get('cycle_key'):
                acknowledge(task=course._task(),deck=course.deck,cycle_id=result['cycle_key'],through_attempt_id=trigger)
                course.save()  # Private acknowledgement and public checkpoint reference close together.
            forecasts.construction_completed(review=result.get('review_receipt') if isinstance(result,dict) else None)
        executed += 1
        if unit_boundary is not None:
            checked_at=time.monotonic();verdict=unit_boundary('after',course,forecasts,plan,executed)
            course.active_seconds+=time.monotonic()-checked_at
            if verdict is not True:
                course.desired='paused';course.save()
                return {'action':action,'executed_units':executed,'paused':True,'reason':'unit_supervisor_stopped_after_saved_unit'}
        publish_course_status(status,'saved_complete_cycle_unit',course,
            action=action,executed_units=executed,allocated_units=allocated)
        if action=='train_duel' and callable(getattr(forecasts,'monitoring_due',None)) and forecasts.monitoring_due():
            break  # Close the complete unit; the next learned decision must observe its frozen scope.
        if course.desired in ('needs_inspection','paused') or (action == 'train_duel' and course.stage() == 'complete'):
            break
        if action == 'evaluate_duel' and forecasts.status()['mandatory_rebuild'] and not forecasts.status()['rebuild_validation_eligible']:
            break
    return {'action':action,'executed_units':executed,'allocated_units':allocated,'paused':False}


def restore_readonly_cached_bot_audit(resource_base,runtime):
    """Reuse the recorded audit, restoring missing runtime copies only."""
    saved=resource_base/'reports/cached-bot-runtime-audit-001'
    meta=json.loads((saved/'manifest.json').read_text(encoding='utf-8'))
    if meta['runtime_root']!=str(runtime):raise RuntimeError('Cached audit belongs to another physical runtime path')
    plan=resource_base/'source/.cache/local-base-training-20261027/2207-base-006/paired-comparison-001/plan.json'
    expected=json.loads(plan.read_text(encoding='utf-8'))['driver']['audit_sha256']
    if meta['completed_game_audit_sha256']!=expected or meta['files']['cached-build-audit.json']!=expected:
        raise RuntimeError('Recorded audit differs from the completed games')
    for name in ('cached-build-audit.json','cache-audit-output.json','cache-audit-input.json'):
        destination=runtime/'build'/name;expected_file=meta['files'][name]
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest()!=expected_file:
                raise RuntimeError('Preserve differing cached audit: '+str(destination))
        else:
            source=saved/name;data=source.read_bytes()
            if hashlib.sha256(data).hexdigest()!=expected_file:raise RuntimeError('Persisted audit file changed: '+str(source))
            destination.write_bytes(data)
    return runtime/'build/cached-build-audit.json'


def restore_saved_runtime_proofs(target,runtime):
    """Restore missing original proof bytes without replacing runtime evidence."""
    manifest=target/'runtime-evidence-manifest.json'
    if not manifest.exists():return
    meta=json.loads(manifest.read_text(encoding='utf-8'))
    if meta.get('kind')!='saved-runtime-proof-copies-v1' or meta.get('runtime_root')!=str(runtime) or not isinstance(meta.get('files'),dict):
        raise RuntimeError('Saved runtime proof manifest identity differs: '+str(manifest))
    allowed={'build/'+name for name in ('cached-build-audit.json','cache-audit-output.json','cache-audit-input.json')}
    allowed.update('observed-course-evidence-006/'+name for name in
        ('comparison.json','task.json','private-trace.json','closed-case.json','profile.json','observed-runtime.json'))
    saved_root=(target/'runtime-evidence').resolve();runtime_root=runtime.resolve()
    for name,expected in meta['files'].items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts or relative.as_posix() not in allowed:
            raise RuntimeError('Unsupported saved runtime proof path: '+name)
        destination=runtime/relative
        if not destination.resolve().is_relative_to(runtime_root):raise RuntimeError('Runtime proof path leaves its original runtime: '+name)
        if destination.exists():
            if not destination.is_file() or hashlib.sha256(destination.read_bytes()).hexdigest()!=expected:
                raise RuntimeError('Preserve differing runtime proof: '+str(destination))
            continue
        source=(saved_root/relative).resolve(strict=True)
        if not source.is_relative_to(saved_root) or not source.is_file():raise RuntimeError('Saved runtime proof leaves its evidence directory: '+name)
        data=source.read_bytes()
        if hashlib.sha256(data).hexdigest()!=expected:raise RuntimeError('Saved runtime proof bytes differ: '+str(source))
        destination.parent.mkdir(parents=True,exist_ok=True)
        with destination.open('xb') as stream:stream.write(data)


def restore_saved_course_bots(target,runtime):
    """Construct the original bot identities without issuing new qualification."""
    from ygo_kito.bot_deployment import BotSourceRegistry
    from ygo_kito.build_contracts import DeckParts,digest
    from ygo_kito.course_game_adapter import CourseBotRuntime
    registry=BotSourceRegistry(json.loads((runtime/'project/configs/bot-sources-v1.json').read_text(encoding='utf-8')),runtime/'bots')
    saved=json.loads((target/'course-bots.json').read_text(encoding='utf-8'));bots={}
    for ident,bot in saved.items():
        spec=bot['runtime']
        if set(spec)!={'source_id','executor_id','audit','qualification','qualification_profile',
                       'source_lock_sha256','inventory_sha256','session_seconds','mono'}:
            raise RuntimeError('Unsupported saved bot runtime identity: '+ident)
        if digest(registry.lock)!=spec['source_lock_sha256'] or registry.inventory['inventory_sha256']!=spec['inventory_sha256']:
            raise RuntimeError('Actual original bot registry differs: '+ident)
        for field in ('audit','qualification','qualification_profile'):
            reference=spec[field];relative=Path(reference['path'])
            if relative.is_absolute() or '..' in relative.parts:raise RuntimeError('Saved bot reference leaves its original runtime: '+field)
            artifact=(runtime/relative).resolve(strict=True)
            if not artifact.is_relative_to(runtime.resolve()) or not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest()!=reference['sha256']:
                raise RuntimeError('Original bot artifact differs: '+field)
        actual=CourseBotRuntime(registry,runtime,spec['source_id'],spec['executor_id'],deepcopy(spec['audit']),
            deepcopy(spec['qualification']),deepcopy(spec['qualification_profile']),spec['mono'],ident,
            source=bot['source'],session_seconds=spec['session_seconds'])
        bots[ident]=dict(runtime=actual,deck=DeckParts.from_dict(bot['deck']),
            **{field:deepcopy(bot[field]) for field in ('stage','purpose','first_order','coverage_label','source')})
    return bots


def initial_task_rank(proposals,source_binding,prior_task_sha256,*,explicit_roots=False):
    """Keep legacy identity matching, or select the migrated semantic objective."""
    candidates=proposals.get('candidates',[])
    if (explicit_roots and source_binding.get('construction_flow')=='four_concrete_handoffs_then_basic_cb_inference_v3'
            and source_binding.get('basic_cb_stage')=='after_construction'):
        for rank,candidate in enumerate(candidates):
            task=candidate.get('task',{});goal=deepcopy(task.get('goal',{}))
            if candidate.get('theme',{}).get('theme_id') not in source_binding.get('construction_theme_ids',[]):continue
            if task.get('requirements')!=source_binding.get('construction_card_requirements',[]):continue
            if any(field in goal for field in ('route_goal','required_activations','required_chain_resolutions')):continue
            goal['constraints']=[item for item in goal.get('constraints',[]) if item.get('id')!='autonomous-axis']
            if goal!=source_binding.get('construction_goal'):continue
            return rank,{'kind':'explicit_postconstruction_policy_reselection',
                'old_selected_task_sha256':prior_task_sha256,'new_selected_task_sha256':candidate['candidate_id'],
                'candidate_rank':rank,'old_matches_relabelled':False}
        raise RuntimeError('No ranked candidate matches the migrated post-construction semantic objective')
    rank=next((i for i,candidate in enumerate(candidates) if candidate['candidate_id']==prior_task_sha256),None)
    if rank is None:raise RuntimeError('Corrected flow cannot silently change the original selected goal')
    return rank,None


def resume_preserved_four_handoffs(models,selection,assets,target,*,verifier,budget,recorder):
    """Run only CB for the same learner after its four recorded handoffs."""
    path=target/'preserved-four-stage-construction.json'
    if not path.exists():return None
    from ygo_kito.basic_cb_inference import infer_basic_cb
    from ygo_kito.build_contracts import DeckParts
    from ygo_kito.construction_candidates import task_checked
    from ygo_kito.proof_visibility import without_private_selection_key
    task=models.kernel._selection(selection)
    result=json.loads(path.read_text(encoding='utf-8'))
    if result.get('selected_task_sha256')!=task.sha256:
        raise RuntimeError('Preserved four handoffs belong to a different selected task')
    phases=result.get('phases');roles=('build_goal','build_optimizer','build_goal','build_optimizer')
    if not isinstance(phases,list) or len(phases)!=4 or result.get('alternation_completed') is not True:
        raise RuntimeError('Preserved construction has no completed four handoffs')
    for index,(phase,role) in enumerate(zip(phases,roles)):
        if phase.get('role')!=role or phase.get('phase_number')!=index+1 or not isinstance(phase.get('proposal_deck'),dict):
            raise RuntimeError('Preserved construction role or ordinal differs')
        if index and phase.get('input_deck')!=phases[index-1]['proposal_deck']:
            raise RuntimeError('Preserved construction has a different concrete handoff')
    learner=phases[-1]['proposal_deck'];best=result.get('best');candidate=result.get('construction_candidate')
    if (not task_checked(best) or not isinstance(candidate,dict) or
            candidate.get('deck')!=learner or best.get('deck')!=learner):
        raise RuntimeError('Preserved learner differs from the fourth concrete output')
    deck=DeckParts.from_dict(learner)
    seconds=min(20.,budget.check('before_basic_cb_provider'))
    inference=infer_basic_cb(task,deck,assets,builder=models.builder,seconds=seconds,verifier=verifier,budget=budget)
    budget.check('after_basic_cb_provider')
    recorder(task,deck,inference)
    cb=without_private_selection_key(inference)
    cb_verified=cb.get('status')=='routes_inferred' and bool(cb.get('routes'))
    result.update(basic_cb=cb,basic_cb_inference_performed=bool(cb.get('inference_completed')),
        cb_verified=cb_verified,preserved_four_handoffs=True,
        cb_resume_provenance={'preserved_four_handoffs':True,'new_four_handoffs_executed':False,
            'role_parameter_updates':False,'competitive_improvement_verified':False})
    for key in ('best','construction_candidate','verified_best'):
        primary=result.get(key)
        if isinstance(primary,dict) and primary.get('deck')==learner:
            primary.update(basic_cb=deepcopy(cb),cb_verified=cb_verified)
    return result


def run(base,directory,stop,status,*,resume=False,unit_boundary=None,continuation=None,
        execution_source_root=None,resource_base=None,comparison_policy=None,cb_signal_consumer=None):
    comparison_policy=comparison_policy if comparison_policy is not None else getattr(status,'comparison_policy',None)
    cb_signal_consumer=cb_signal_consumer if cb_signal_consumer is not None else getattr(status,'cb_signal_consumer',None)
    status.comparison_policy=comparison_policy;status.cb_signal_consumer=cb_signal_consumer
    from local_foundation_comparison import unpack_exact,restore_cached_bot_audit
    def read(p): return json.loads(p.read_text(encoding='utf-8'))
    def write(p,v):
        tmp=p.with_name(p.name+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');tmp.replace(p)
    def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
    explicit_roots=execution_source_root is not None or resource_base is not None
    resources=base if resource_base is None else Path(resource_base).resolve()
    source=resources/'source'
    execution_source=source if execution_source_root is None else Path(execution_source_root).resolve()
    if explicit_roots:
        if execution_source_root is None or resource_base is None or not resume or not isinstance(continuation,dict) or set(continuation)!={'state_root','source_manifest','source_archive'}:
            raise RuntimeError('Explicit source and resource roots require the exact resumed course continuation')
        if execution_source!=Path(__file__).resolve().parents[1]:raise RuntimeError('Execution source must be this course repository')
        target=Path(continuation['state_root']).resolve()
        if not target.is_relative_to(base.resolve()) or not target.is_dir():
            raise RuntimeError('Explicit roots require an existing migrated course inside this worker base')
        if any(not Path(continuation[key]).resolve().is_relative_to((base/'reports').resolve()) for key in ('source_manifest','source_archive')):
            raise RuntimeError('Migrated execution source artifacts must be inside this worker reports')
    runtime_pack=read(resources/'reports/model-pair-runtime-pack.json')
    runtime=Path('/tmp')/('ygo-kito-model-pair-'+runtime_pack['archive_sha256'][:16])
    unpack_exact(resources/'cache/model-pair-runtime-001.tar',runtime_pack,runtime)
    native_pack=read(resources/'reports/native-runtime-cache-source-manifest.json')
    native=Path(native_pack['cache_root'])
    unpack_exact(resources/'cache/native-runtime-42b468cc.tar',native_pack,native)
    if continuation is not None and (not resume or set(continuation)!={'state_root','source_manifest','source_archive'}):
        raise RuntimeError('Explicit migrated state and exact execution source are required for continuation')
    pack=read(Path(continuation['source_manifest']) if continuation else base/'reports/formal-course-source-pack-006.json')
    project=Path('/tmp')/('ygo-kito-formal-source-'+pack['archive_sha256'][:16])
    unpack_exact(Path(continuation['source_archive']) if continuation else base/'cache/formal-course-source-006.tar',pack,project)
    actual={str(p.relative_to(execution_source)):sha(p) for p in sorted((execution_source/'src/ygo_kito').glob('*.py'))}
    snapshot={str(p.relative_to(project)):sha(p) for p in sorted((project/'src/ygo_kito').glob('*.py'))}
    if snapshot!=actual: raise RuntimeError('Source differs from immutable course execution snapshot')
    sys.path.insert(0,str(project/'src'))
    import torch
    from ygo_kito.build_contracts import BuildTask,DeckParts,digest
    from ygo_kito.build_pipeline import verify_goal
    from ygo_kito.bot_deployment import BotSourceRegistry
    from ygo_kito.course_models import CourseModels
    from ygo_kito.course_game_adapter import CourseBotRuntime,course_config_from_dict
    from ygo_kito.data_isolation import DataIndex
    from ygo_kito.group_runner import tree_digest
    from ygo_kito.implementation_identity import source_tree_snapshot
    from ygo_kito.observed_bot_evidence import KIND
    from ygo_kito.period_runtime import PeriodBuildAssets
    from ygo_kito.scenario_course import ScenarioCourse
    torch.set_num_threads(2)
    old=source/'.cache/local-base-training-20261027/2207-base-006'
    foundation=source/'.cache/local-base-training-20261027/2207-base-005'
    target=Path(continuation['state_root']).resolve() if continuation else source/'.cache/local-base-training-20261027/2207-course-005'
    assets=PeriodBuildAssets(native,'2022-07',read(foundation/'active-environment.local.json'),resources,adapter_revision=5,evidence_source='user_supplied')
    if target.exists():
        if not resume: raise RuntimeError('Existing course preserved; inspect then Resume')
        binding=read(target/'model-binding.json')
        if binding['source_files']!=actual: raise RuntimeError('Saved course needs an explicit source migration')
        pointer=read(target/'initial-pointer.json')
        if sha(Path(pointer['path']))!=pointer['sha256']: raise RuntimeError('Saved initial course state changed')
        models=CourseModels.from_state(torch.load(pointer['path'],map_location='cpu',weights_only=False),assets=assets,expected_binding=binding)
    else:
        pointer=read(old/'latest-pointer.json')
        if sha(Path(pointer['path']))!=pointer['sha256']: raise RuntimeError('Latest comparison state changed')
        state=torch.load(pointer['path'],map_location='cpu',weights_only=False)
        if state['state_sha256']!=tree_digest({k:v for k,v in state.items() if k!='state_sha256'}): raise RuntimeError('Full source state changed')
        changed={p for p in set(actual)|set(state['binding']['source_files']) if actual.get(p)!=state['binding']['source_files'].get(p)}
        allowed={'src/ygo_kito/'+n+'.py' for n in ('autonomous_construction','construction_effect_blocks','course_game_adapter','observed_bot_evidence','scenario_course')}
        if not changed or not changed<=allowed: raise RuntimeError('Unexpected course source migration: '+repr(changed-allowed))
        goal=read(foundation/'fusion-task.json')['goal']
        goal['constraints']=[c for c in goal['constraints'] if c['id']!='autonomous-axis']
        binding=deepcopy(state['binding']);binding.update(source_files=actual,construction_goal=goal)
        temporary=CourseModels.initialize(BuildTask.from_dict(state['task']),assets,course_config_from_dict(state['configs']['duel']),state['configs']['adapters'],source,None,state['available_ids'],binding,device='cpu')
        for role,model in temporary.models().items(): model.load_state_dict(state['components']['models'][role],strict=True)
        temporary.kernel.updates=deepcopy(state['kernel']['updates'])
        migrated=deepcopy(state);migrated.update(binding=binding,binding_sha256=digest(binding),kernel=temporary.kernel.state_dict())
        migrated['state_sha256']=tree_digest({k:v for k,v in migrated.items() if k!='state_sha256'})
        models=CourseModels.from_state(migrated,assets=assets,expected_binding=binding)
        restored=models.save_state()
        if tree_digest(restored['components'])!=tree_digest(state['components']) or tree_digest(restored['rng'])!=tree_digest(state['rng']) or restored['cursors']!=state['cursors']: raise RuntimeError('Course migration changed learning state')
        target.mkdir();shutil.copytree(old/'index',target/'index')
        write(target/'model-binding.json',binding)
        torch.save(restored,target/'initial-full.weights')
        write(target/'initial-pointer.json',{'path':str(target/'initial-full.weights'),'sha256':sha(target/'initial-full.weights')})
        write(target/'migration.json',{'kind':'explicit-observed-runtime-and-construction-objective-migration','source_checkpoint_sha256':pointer['sha256'],
            'changed_source_files':sorted(changed),'weights_optimizers_rng_cursors_preserved':True,'reference_inputs':[],
            'prior_formal_training_credit':0,'prior_kernel_sessions_preserved':str(old),'execution_source_sha256':pack['archive_sha256']})
    status('binding_existing_actual_bot_games_no_extra_qualification')
    if explicit_roots:
        restore_readonly_cached_bot_audit(resources,runtime)
        restore_saved_runtime_proofs(target,runtime)
        bots=restore_saved_course_bots(target,runtime)
    else:
        evidence_dir=runtime/'observed-course-evidence-006';evidence_dir.mkdir(exist_ok=True)
        pair_root=old/'paired-comparison-001'
        def reference(p):return {'path':str(p.relative_to(runtime)),'sha256':sha(p)}
        names={'comparison.json':pair_root/'comparison.json','task.json':foundation/'fusion-task.json',
            'private-trace.json':pair_root/'candidate-0-seed-701002-seat-0.private-replay.json',
            'closed-case.json':pair_root/'candidate-0-seed-701002-seat-0.closed-flight.json'}
        for name,p in names.items():
            data=p.read_bytes();dest=evidence_dir/name
            if dest.exists() and dest.read_bytes()!=data: raise RuntimeError('Preserve differing observed evidence')
            if not dest.exists(): dest.write_bytes(data)
        trace=read(evidence_dir/'private-trace.json');profile=trace['profile']
        profile_path=evidence_dir/'profile.json'
        if not profile_path.exists():write(profile_path,profile)
        if read(profile_path)!=profile:raise RuntimeError('Observed profile changed')
        report={'kind':KIND,'comparison':reference(evidence_dir/'comparison.json'),'task':reference(evidence_dir/'task.json'),
            'private_trace':reference(evidence_dir/'private-trace.json'),'closed_case':reference(evidence_dir/'closed-case.json'),
            'actor_seat':0,'original_source_map':source_tree_snapshot(runtime/'project/src/ygo_kito'),
            'current_source_map':source_tree_snapshot(project/'src/ygo_kito'),
            'native_receipt_sha256':digest(assets.receipt),'period_context_sha256':digest(assets.period_context),
            'extra_qualification_games':0,'strength_qualified':False}
        report_path=evidence_dir/'observed-runtime.json'
        if report_path.exists() and read(report_path)!=report:raise RuntimeError('Observed runtime migration changed')
        if not report_path.exists():write(report_path,report)
        host=read(source/'.cache/local-base-training-20261027/2207-base-002/runtime-host.json')
        bot=dict(host['bots'][0]);deck_path=source/bot['deck']['path'];opponent=DeckParts.from_dict(read(deck_path))
        registry=BotSourceRegistry(read(runtime/'project/configs/bot-sources-v1.json'),runtime/'bots')
        audit_path=restore_cached_bot_audit(base,runtime,status);mono=read(audit_path)['toolchain']['mono']['path']
        runtime_bot=CourseBotRuntime(registry,runtime,bot['source_id'],bot['executor_id'],reference(audit_path),
            reference(report_path),reference(profile_path),mono,bot['bot_id'],source=bot['source'],session_seconds=300)
        # Only the existing-bot BO1 curriculum is currently supplied. Common-deck
        # and strong mirror coverage remain pending rather than relabeling this bot.
        bots={bot['bot_id']:{'runtime':runtime_bot,'deck':opponent,'stage':'bots-bo1','purpose':'train',
            'first_order':'always_first','source':bot['source'],'coverage_label':bot['coverage_label']}}
    config={'course_id':'pearl-base-2207-v1','period_id':'2022-07','mode':'fixed_theme',
        'pilot_mean_seconds':None,'timing_basis':{'kind':'user_confirmed_slow_branch','branch':'slow',
            'source':'user-confirmed-existing-timing-no-rerun','observed_mean_seconds':None,
            'retiming_requested':False,'current_device_measured':False},'training_seeds':list(models.duel.config.game_seeds),
        'evaluation_pairs':{'validation':[[810000+i,820000+i] for i in range(1200)],
                            'final_eval':[[910000+i,920000+i] for i in range(1200)]},
        'matches_per_invocation':1,'wall_seconds':25*3600,'allocated_gpu_count':0,'fixed_deck':None,
        'construction_theme_ids':['setcode-181'],'initial_first':'alternate','evaluation_matches':400,
        'opponent_side':'keep_original_baseline','checkpoint_policy':{'keep_last':3,'milestone_every':100,
            'min_free_bytes':1000000000,'max_state_bytes':2000000000}}
    correction=read(target/'corrected-flow-continuation.json') if (target/'corrected-flow-continuation.json').exists() else None
    if continuation:
        config=read(target/'course-config.json')  # Exact migrated config, including its original budget/counters.
    else:
        config['training_record_offset']=correction['prior_record_count']
    config_path=target/'course-config.json'
    if config_path.exists() and read(config_path)!=config:raise RuntimeError('Course configuration differs')
    if not config_path.exists():write(config_path,config)
    index=DataIndex(target/'index')
    course=ScenarioCourse(models,assets=assets,data_index=index,config=config,state_root=target/'course',bots=bots,
        comparison_policy=comparison_policy)
    if (course.root/'latest.json').exists():course.restore_latest()
    else:
        from local_course_corrected_flow import import_corrected_flow
        import_corrected_flow(course,target)
    if comparison_policy is None:
        from ygo_kito.course_admission_policy import load_course_admission_policy
        comparison_policy=load_course_admission_policy(course,target)
    if cb_signal_consumer is None:cb_signal_consumer=getattr(comparison_policy,'consume_cb_signal',None)
    course.bind_admission_policy(comparison_policy)
    status.comparison_policy=comparison_policy;status.cb_signal_consumer=cb_signal_consumer
    score_completed=getattr(comparison_policy,'record_completed_construction',None)
    if (course.deck is not None and isinstance(course.construction,dict) and
            course.construction.get('alternation_completed') is True and callable(score_completed)):
        # Score the actual preserved candidate prospectively in the new epoch.
        # This does not import any old failure/loss count or re-run its inference.
        candidate=(course.construction.get('best') or {})
        if candidate.get('deck')==course.deck.to_dict():
            score_completed(task=course._task(),deck=course.deck,assets=assets,basic_cb=candidate.get('basic_cb'),
                cycle_id='prospective-preserved-four-stage-'+digest(course.construction))
    course.save()  # Seal the prospective epoch/reference without copying private counters into learner data.
    publish_course_status(status,'course_restored',course)
    if unit_boundary is None:
        course.save()
        error=RuntimeError('Independent unit supervisor is required; course stays paused')
        error.safe_boundary_saved=True;error.pause_requested=True
        raise error
    if course.deck is None:
        if continuation and correction is None:
            raise RuntimeError('Migrated course has no original selected construction; preserve state and inspect')
        status('actual_corrected_four_handoffs_before_cb',course=course.status())
        proposals=models.kernel.propose_tasks()
        wanted=correction['preserved_selected_task_sha256']
        rank,reselection=initial_task_rank(proposals,models.kernel.source_binding,wanted,explicit_roots=explicit_roots)
        if reselection is not None:
            selection=models.kernel.select_task(proposals,rank=rank)
            if selection.get('candidate_id')!=reselection['new_selected_task_sha256']:
                raise RuntimeError('Kernel selection differs from the migrated semantic candidate')
            course.events.append(reselection)
        else:selection=course.selection or models.kernel.select_task(proposals,rank=rank)
        course.selection=selection
        if unit_boundary('before',course,None,{'action':'build_goal'},0) is not True:
            course.desired='paused';course.save()
            error=RuntimeError('Independent supervision stopped initial construction')
            error.safe_boundary_saved=True;error.pause_requested=True
            raise error
        initial_budget=CycleBudget(course)
        attempts=len(list(target.glob('construction-route-*.json')))
        def verifier(task,deck,current_assets,**limits):
            nonlocal attempts
            if stop.exists():raise RuntimeError('Safe stop before final candidate CB')
            attempts+=1
            status('actual_final_optimizer_candidate_cb',formal_matches=sum(course.counts().values()),route_attempt=attempts)
            options={'seconds':30.,'attempts':64,'decision_budget':100};options.update(limits)
            options['seconds']=min(options['seconds'],initial_budget.check('initial_task_or_basic_cb_verifier'))
            proof=verify_goal(task,deck,current_assets,**options)
            initial_budget.check('after_initial_task_or_basic_cb_verifier')
            write(target/('construction-route-'+str(attempts).zfill(3)+'.json'),{'task':task.to_dict(),'deck':deck.to_dict(),'proof':proof})
            return proof
        from local_course_collaboration import record_basic_cb_inference,basic_cb_completed
        def recorder(t,d,value):
            from local_course_forecast import record_conditional_cb_signal
            path=record_basic_cb_inference(target,t,d,value)
            record_conditional_cb_signal(cb_signal_consumer,path,t,d,value,assets=assets)
            return path
        result=resume_preserved_four_handoffs(models,selection,assets,target,
            verifier=verifier,budget=initial_budget,recorder=recorder)
        if result is None:
            result=models.kernel.run_selected(selection,verifier=verifier,budget=initial_budget,basic_cb_verifier=verifier,
                basic_cb_recorder=recorder)
        prior=target/'initial-four-stage-construction.json'
        if prior.exists():prior.rename(prior.with_name('initial-four-stage.prior-'+str(time.time_ns())+'.json'))
        write(prior,result)
        from ygo_kito.construction_candidates import task_checked
        if (not task_checked(result.get('best')) or result.get('alternation_completed') is not True
                or not basic_cb_completed(result)):
            course.save();raise RuntimeError('Construction task or actual basic CB inference incomplete; trace preserved')
        if result['best']['logic_sha256']!=result['phases'][-1]['stage_1']['logic_sha256']:
            raise RuntimeError('Final candidate and final optimizer graph differ')
        course.construction=result;course.deck=DeckParts.from_dict(result['best']['deck']);course.rules.validate(course.deck)
        score_completed=getattr(comparison_policy,'record_completed_construction',None)
        if callable(score_completed):
            cycle_id='initial-four-stage-'+digest(result)
            seen=set()
            for candidate in [result['best'],*result.get('retained_candidates',[])]:
                if not isinstance(candidate,dict) or not isinstance(candidate.get('deck'),dict):continue
                key=digest(candidate['deck'])
                if key in seen:continue
                seen.add(key)
                score_completed(task=course._task(),deck=DeckParts.from_dict(candidate['deck']),assets=assets,
                    basic_cb=candidate.get('basic_cb'),cycle_id=cycle_id)
        course.save()
        if unit_boundary('after',course,None,{'action':'build_goal'},1) is not True:
            course.desired='paused';course.save()
            error=RuntimeError('Independent supervision stopped after initial construction')
            error.safe_boundary_saved=True;error.pause_requested=True
            raise error
    from local_course_collaboration import cycle as collaborative_cycle
    from local_course_forecast import CourseForecast
    forecasts=CourseForecast(course,target,stop,comparison_policy=comparison_policy)
    forecasts.train_closed_outcomes()
    while course.stage()!='complete':
        if stop.exists():
            course.save()
            error=RuntimeError('Safe stop at a complete saved course boundary');error.safe_boundary_saved=True;error.saved_course_status={'course':course.status(),'goal_updates':course.models.builder.updates['build_goal'],'optimizer_updates':course.models.builder.updates['build_optimizer'],'duel_updates':course.models.duel.updates,'coordinator_updates':course.models.coordinator.updates};raise error
        if course.stage()=='common-decks-bo3':
            course.save();raise RuntimeError('Existing-bot stage complete; same-period common/mirror opponent coverage is not yet supplied')
        reserve=models.duel.config.episode_seconds
        max_units=max(0,min(8,int((course.config['wall_seconds']-course.active_seconds)/reserve)))
        result=execute_cycle(course,forecasts,collaborative_cycle,base,target,stop,status,max_units,unit_boundary=unit_boundary)
        status('learned_complete_cycle_executed',decision=result,course=course.status())
        if result['paused']:
            error=RuntimeError('Learned coordinator stopped at a saved complete-cycle boundary')
            error.safe_boundary_saved=result.get('safe_boundary_saved',True)
            error.pause_requested=error.safe_boundary_saved
            error.saved_course_status={'course':course.status(),'coordinator_updates':models.coordinator.updates}
            raise error
        write(target/'current-course-status.json',course.status())
        status('saved_formal_match_boundary',course=course.status(),goal_updates=models.builder.updates['build_goal'],
            optimizer_updates=models.builder.updates['build_optimizer'],duel_updates=models.duel.updates,
            coordinator_updates=models.coordinator.updates,latest_checkpoint=str(course.root/'latest.json'))
        if course.desired in ('needs_inspection','paused'):raise RuntimeError('Course saved its actual stop condition: '+course.desired)
    return {'status':'course_volume_complete_not_acceptance','course':course.status()}
