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


def execute_cycle(course, forecasts, construction, base, target, stop, status, max_units, *, unit_boundary=None):
    """Execute the learned allocation only between indivisible four-step cycles."""
    planned_at,accounted=time.monotonic(),course.active_seconds
    plan = forecasts.decide(max_units)
    course.active_seconds+=max(0.,time.monotonic()-planned_at-(course.active_seconds-accounted))
    action, allocated = plan['action'], plan['budget_units']
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
        if action == 'train_duel':
            if current['mandatory_rebuild']:
                break
            try: budget.check('before_training_game',required=course.models.duel.config.episode_seconds)
            except CycleBudgetExhausted:
                course.desired='paused';course.save()
                return {'action':action,'executed_units':executed,'paused':True,'reason':'insufficient_training_game_reserve'}
            forecasts.before_training()
            course.run(1)
            forecasts.train_closed_outcomes()
        elif action == 'evaluate_duel':
            try: actual=forecasts.evaluate(1,budget=budget)
            except CycleBudgetExhausted:
                course.desired='paused';course.save()
                return {'action':action,'executed_units':executed,'paused':True,'reason':'insufficient_monitor_reserve'}
            if actual == 0:
                course.desired='paused';course.save()
                return {'action':action,'executed_units':executed,'paused':True,'reason':'monitor_window_requires_new_action'}
        else:
            started,accounted = time.monotonic(),course.active_seconds
            discrepancy = {'kind':'force_goal_reconstruction' if current['mandatory_rebuild'] else 'reassess_construction',
                'forecast_id':forecasts.value['active_forecast'],'status':current}
            cycle_id = str(len(forecasts.value['decisions']))+'-'+str(executed)
            # The shared collaboration helper owns candidate adoption/role
            # admission. See the small companion integration patch for cycle_id.
            try:
                # The absolute deadline, not a fresh 7200-second allowance, is
                # passed through the shared adapter to every expensive child.
                result=construction(course,base,target,stop,status,initial=False,
                    force_rebuild=current['mandatory_rebuild'],feedback=discrepancy,cycle_id=cycle_id,budget=budget)
            except CycleBudgetExhausted:
                uncertain=getattr(budget,'in_flight',False)
                course.desired='needs_inspection' if uncertain else 'paused'
                return {'action':action,'executed_units':executed,'paused':True,'safe_boundary_saved':not uncertain,
                        'reason':'uncertain_construction_transaction' if uncertain else 'construction_budget_boundary'}
            finally:
                course.active_seconds += max(0.,time.monotonic()-started-(course.active_seconds-accounted))
                course.save()
            forecasts.construction_completed(review=result.get('review_receipt') if isinstance(result,dict) else None)
        executed += 1
        if unit_boundary is not None:
            checked_at=time.monotonic();verdict=unit_boundary('after',course,forecasts,plan,executed)
            course.active_seconds+=time.monotonic()-checked_at
            if verdict is not True:
                course.desired='paused';course.save()
                return {'action':action,'executed_units':executed,'paused':True,'reason':'unit_supervisor_stopped_after_saved_unit'}
        if course.desired in ('needs_inspection','paused') or (action == 'train_duel' and course.stage() == 'complete'):
            break
        if action == 'evaluate_duel' and forecasts.status()['mandatory_rebuild'] and not forecasts.status()['rebuild_validation_eligible']:
            break
    return {'action':action,'executed_units':executed,'allocated_units':allocated,'paused':False}


def run(base,directory,stop,status,*,resume=False,unit_boundary=None,continuation=None):
    from local_foundation_comparison import unpack_exact,restore_cached_bot_audit
    def read(p): return json.loads(p.read_text(encoding='utf-8'))
    def write(p,v):
        tmp=p.with_name(p.name+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8');tmp.replace(p)
    def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
    source=base/'source'
    runtime_pack=read(base/'reports/model-pair-runtime-pack.json')
    runtime=Path('/tmp')/('ygo-kito-model-pair-'+runtime_pack['archive_sha256'][:16])
    unpack_exact(base/'cache/model-pair-runtime-001.tar',runtime_pack,runtime)
    native_pack=read(base/'reports/native-runtime-cache-source-manifest.json')
    native=Path(native_pack['cache_root'])
    unpack_exact(base/'cache/native-runtime-42b468cc.tar',native_pack,native)
    if continuation is not None and (not resume or set(continuation)!={'state_root','source_manifest','source_archive'}):
        raise RuntimeError('Explicit migrated state and exact execution source are required for continuation')
    pack=read(Path(continuation['source_manifest']) if continuation else base/'reports/formal-course-source-pack-006.json')
    project=Path('/tmp')/('ygo-kito-formal-source-'+pack['archive_sha256'][:16])
    unpack_exact(Path(continuation['source_archive']) if continuation else base/'cache/formal-course-source-006.tar',pack,project)
    actual={str(p.relative_to(source)):sha(p) for p in sorted((source/'src/ygo_kito').glob('*.py'))}
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
    assets=PeriodBuildAssets(native,'2022-07',read(foundation/'active-environment.local.json'),base,adapter_revision=5,evidence_source='user_supplied')
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
    course=ScenarioCourse(models,assets=assets,data_index=index,config=config,state_root=target/'course',bots=bots)
    if (course.root/'latest.json').exists():course.restore_latest()
    else:
        from local_course_corrected_flow import import_corrected_flow
        import_corrected_flow(course,target)
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
        rank=next((i for i,c in enumerate(proposals.get('candidates',[])) if c['candidate_id']==wanted),None)
        if rank is None:raise RuntimeError('Corrected flow cannot silently change the original selected goal')
        selection=course.selection or models.kernel.select_task(proposals,rank=rank)
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
        from local_course_collaboration import record_basic_cb_inference
        result=models.kernel.run_selected(selection,verifier=verifier,budget=initial_budget,basic_cb_verifier=verifier,
            basic_cb_recorder=lambda t,d,value:record_basic_cb_inference(target,t,d,value))
        prior=target/'initial-four-stage-construction.json'
        if prior.exists():prior.rename(prior.with_name('initial-four-stage.prior-'+str(time.time_ns())+'.json'))
        write(prior,result)
        from ygo_kito.construction_candidates import task_checked
        if not task_checked(result.get('best')):
            course.save();raise RuntimeError('Construction task unresolved; actual incomplete cycle preserved')
        if result['best']['logic_sha256']!=result['phases'][-1]['stage_1']['logic_sha256']:
            raise RuntimeError('Final candidate and final optimizer graph differ')
        course.construction=result;course.deck=DeckParts.from_dict(result['best']['deck']);course.rules.validate(course.deck)
        course.save()
        if unit_boundary('after',course,None,{'action':'build_goal'},1) is not True:
            course.desired='paused';course.save()
            error=RuntimeError('Independent supervision stopped after initial construction')
            error.safe_boundary_saved=True;error.pause_requested=True
            raise error
    from local_course_collaboration import cycle as collaborative_cycle
    from local_course_forecast import CourseForecast
    forecasts=CourseForecast(course,target,stop)
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
