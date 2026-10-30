"""Host-owned actual construction feedback between blocks of formal matches."""
from copy import deepcopy
import hashlib
import json
import shutil
import time
from pathlib import Path
from itertools import combinations


def record_basic_cb_inference(root,task,deck,inference):
    """Persist the exact post-construction input under the observer's namespace."""
    root=Path(root)
    ordinals=[int(p.stem.removeprefix('basic-cb-inference-'))
              for p in root.glob('basic-cb-inference-*.json')
              if p.stem.removeprefix('basic-cb-inference-').isdigit()]
    path=root/('basic-cb-inference-'+str(max(ordinals,default=0)+1).zfill(3)+'.json')
    value={'task':task.to_dict(),'deck':deck.to_dict(),'inference':inference}
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(path)
    return path


def basic_cb_completed(value):
    cb=(value or {}).get('basic_cb') or {}
    return cb.get('inference_completed') is True and cb.get('status') in ('routes_inferred','bounded_inference_unknown')


def comparison_training_pair(comparison,candidates,preferred,auxiliary=None):
    """Preserve an absent preference; never manufacture a pair from unknown."""
    from ygo_kito.model_build_feedback import SOURCE
    if preferred is None:return None
    if comparison['preferred_index'] is None:
        if auxiliary is None or auxiliary['preferred_index']!=preferred:
            raise RuntimeError('An auxiliary preference requires its exact evaluated evidence')
        evidence=auxiliary;values=(1.,0.);source=auxiliary['source']
    else:
        if comparison['preferred_index']!=preferred:
            raise RuntimeError('Training preference differs from the strict primary comparison')
        evidence=comparison;source=SOURCE
        values=(comparison['mean_scores'][preferred],comparison['mean_scores'][1-preferred])
    return {'better':candidates[preferred].to_dict(),'worse':candidates[1-preferred].to_dict(),
        'better_value':values[0],'worse_value':values[1],
        'source':source,'hard_constraints_checked':True,'evidence':evidence}


def optimizer_feedback_receipt(consumed,feedback_id,artifact_id):
    if not any(row['feedback_id']==feedback_id and row['artifact_id']==artifact_id and
            row['role']=='build_optimizer' for row in consumed):
        raise RuntimeError('Optimizer comparison feedback has no consumed role receipt')
    return {'status':'consumed','artifact_id':artifact_id,'feedback_id':feedback_id}


def admit_comparison_candidates(task,contexts,assets,comparison_policy=None):
    from ygo_kito.build_contracts import DeckParts
    from ygo_kito.training_admission import require_training_admission
    admitted=[];verdicts=[]
    for context in contexts:
        verdict=require_training_admission(task=task,deck=DeckParts.from_dict(context['deck']),
            basic_cb=context.get('basic_cb'),assets=assets,purpose='construction_comparison',
            comparison_policy=comparison_policy)
        verdicts.append(verdict)
        if verdict['status']=='admitted':admitted.append(context)
    return admitted,verdicts


def cycle(course,base,target,stop,status,*,initial=False,force_rebuild=False,feedback=None,cycle_id=None,budget=None,
          comparison_policy=None):
    comparison_policy=comparison_policy if comparison_policy is not None else getattr(course,'comparison_policy',None)
    cb_signal_consumer=getattr(status,'cb_signal_consumer',None) or getattr(comparison_policy,'consume_cb_signal',None)
    from ygo_kito.build_contracts import BuildTask,DeckParts,digest
    from ygo_kito.build_pipeline import verify_goal
    from ygo_kito.build_training import supervision_projection
    from ygo_kito.model_build_feedback import SOURCE as PAIR_SOURCE,compare_model_candidates
    from ygo_kito.semantic_training import SOURCE
    from ygo_kito.build_semantics import accepted_status
    from ygo_kito.construction_course_evidence import cycle_identity,task_supervision,supervision_seeds
    from ygo_kito.construction_candidates import (comparable_candidates, record_comparison,
        strict_portfolio_winner, select_retained, task_checked)
    def read(p):return json.loads(p.read_text(encoding='utf-8'))
    def write(p,v):
        tmp=p.with_name(p.name+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(p)
    def pause_if_requested():
        if budget is not None:budget.check('collaborative_feedback_boundary')
        if stop.exists():
            # Admission may have advanced the DataIndex since the last update.
            # Commit its exact full boundary before reporting a recoverable stop.
            course.save()
            error=RuntimeError('Safe stop at saved collaborative feedback boundary')
            error.safe_boundary_saved=True
            error.saved_course_status={'course':course.status(),'goal_updates':course.models.builder.updates['build_goal'],'optimizer_updates':course.models.builder.updates['build_optimizer'],'duel_updates':course.models.duel.updates,'coordinator_updates':course.models.coordinator.updates}
            raise error
    def apply_once(feedback_id,artifact_id,**kw):
        if not any(x['feedback_id']==feedback_id for x in course.feedback.consumed):
            pause_if_requested()
            course.apply_feedback(feedback_id,artifact_id,**kw)
            status('actual_collaborative_role_update',formal_matches=sum(course.counts().values()),
                goal_updates=course.models.builder.updates['build_goal'],
                optimizer_updates=course.models.builder.updates['build_optimizer'],
                duel_updates=course.models.duel.updates,coordinator_updates=course.models.coordinator.updates)
    if budget is not None:budget.check('before_four_step_cycle')
    number=sum(course.counts().values())
    cycle_key,root_name=cycle_identity(number,force_rebuild,cycle_id)
    root=target/root_name;root.mkdir(exist_ok=True)
    task=course._task();models=course.models;assets=course.assets
    identity={'cycle_id':cycle_id,'cycle_key':cycle_key,'formal_matches':number,
              'force_rebuild':force_rebuild,'task_sha256':task.sha256}
    identity_path=root/'cycle-identity.json'
    if identity_path.exists() and read(identity_path)!=identity:raise RuntimeError('Saved construction cycle identity differs')
    if not identity_path.exists():write(identity_path,identity)
    if (root/'complete.json').exists():return read(root/'complete.json')
    incumbent=deepcopy(course.construction['best']);deployed=deepcopy(course.construction)
    # A retained incumbent may have its full private proof in an earlier
    # closed construction. Search only this course, matching the complete task
    # and deck; public/redacted outputs are never substituted for that proof.
    proof_paths=sorted(set(target.glob('construction-route-*.json'))|
                       set(target.glob('collaboration-*/route-*.json')))
    proof_records=[(p,read(p)) for p in proof_paths]
    def private_proof(deck):
        return next(((p,r) for p,r in reversed(proof_records)
            if r.get('task')==task.to_dict() and r.get('deck')==deck.to_dict()
            and r['proof'].get('task_sha256')==task.sha256
            and r['proof'].get('deck_sha256')==digest(deck.to_dict())
            and r['proof'].get('status')==accepted_status(task)),None)
    path=root/'actual-four-stage.json'
    if path.exists():
        existing=read(path)
        current,_=models.kernel._session(course.selection)
        current_sha=current.logic.sha256 if current.logic is not None else None
        if not initial and existing.get('latest_logic_sha256')!=current_sha:
            # The process failed before committing the inference's kernel state.
            # Preserve that trace and rebuild only inference, reusing exact
            # private proofs. No duel or parameter update is replayed.
            path.rename(path.with_name('actual-four-stage.uncommitted-'+str(time.time_ns())+'.json'))
    if path.exists():result=read(path)
    elif initial:
        result=deepcopy(course.construction);write(path,result)
    else:
        counter=len(list(root.glob('route-*.json')))
        def verifier(t,d,a,**limits):
            nonlocal counter
            if stop.exists():raise RuntimeError('Safe stop before next actual construction route')
            counter+=1;prior=None
            options={'seconds':30.,'attempts':64,'decision_budget':100};options.update(limits)
            prior_flight=getattr(budget,'in_flight',False) if budget is not None else False
            if budget is not None:
                options['seconds']=min(options['seconds'],budget.check('before_basic_cb_verifier'))
                budget.in_flight=True
            proof=verify_goal(t,d,a,**options)
            if budget is not None:budget.check('after_basic_cb_verifier')
            provenance={'kind':'construction_task_validation','new_native_execution':'route_goal' in t.goal}
            row={'task':t.to_dict(),'deck':d.to_dict(),'proof':proof,'proof_provenance':provenance}
            saved=root/('route-'+str(counter).zfill(3)+'.json');write(saved,row);proof_records.append((saved,row))
            if budget is not None:budget.in_flight=prior_flight
            status('collaborative_task_validation',
                   formal_matches=number,route_attempt=counter,result=proof['status'])
            return proof
        def record_basic_cb(t,d,inference):
            from local_course_forecast import record_conditional_cb_signal
            path=record_basic_cb_inference(root,t,d,inference)
            record_conditional_cb_signal(cb_signal_consumer,path,t,d,inference,assets=assets)
            return path
        routing_feedback=({'source':'duel','message':'Actual completed training matches: '+str(number)+'; observed wins: '+str(sum(r['winner']=='actor' for r in course.records if r['purpose']=='train' and r['complete']))+'. Reconsider the unchanged goal with actual public feedback; no quality label from one game.'},)
        public_scorer=getattr(comparison_policy,'public_feedback',None)
        if callable(public_scorer):
            public_score=public_scorer(task=task,deck=course.deck)
            if public_score is not None:
                routing_feedback+=({'source':'duel','message':'Completed candidate construction feedback: '+json.dumps(public_score,sort_keys=True)},)
        if feedback:routing_feedback+=({'source':'duel','message':'Actual immutable forecast discrepancy: '+json.dumps(feedback,sort_keys=True)},)
        result=models.kernel.run_selected(course.selection,base=None if force_rebuild else course.deck,
            feedback=routing_feedback,verifier=verifier,basic_cb_recorder=record_basic_cb,
            budget=budget,basic_cb_verifier=verifier)
        if force_rebuild:result['forced_reconstruction_executed_from_empty']=True
        write(path,result)
        # Commit the generated session/history together with its inference trace
        # before role admission. A later resume can then consume it exactly once.
        course.save()
    if (not task_checked(result.get('best')) or result.get('alternation_completed') is not True
            or not basic_cb_completed(result)):
        raise RuntimeError('Collaborative task, four handoffs or actual basic CB inference is incomplete')
    # Independent completed construction evaluations precede admission queries.
    # Score every emitted actual candidate; a deferred CB never becomes a
    # negative training pair or a fabricated construction score.
    scoring_feedback={}
    scorer=getattr(comparison_policy,'record_completed_construction',None)
    if callable(scorer):
        seen=set()
        for candidate in [result['best']]+list(result.get('retained_candidates',())):
            if not task_checked(candidate):continue
            subject=digest(candidate['deck'])
            if subject in seen:continue
            seen.add(subject)
            scoring_feedback[subject]=scorer(task=task,deck=DeckParts.from_dict(candidate['deck']),
                assets=assets,basic_cb=candidate.get('basic_cb'),cycle_id=cycle_key)
    from local_design_supervision import require_artifact_clearance
    require_artifact_clearance(base,course,target,path,stop)
    session=models.kernel.sessions[course.selection['candidate_id']]
    session.check_goal()
    if result.get('goal_sha256')!=session.goal_sha256 or session.task.sha256!=task.sha256:raise RuntimeError('Collaboration changed the selected objective')
    proposal=DeckParts.from_dict(result['best']['deck'])
    comparable_incumbent=incumbent if basic_cb_completed(incumbent) else None
    contexts=[candidate for candidate in comparable_candidates(result,comparable_incumbent) if basic_cb_completed(candidate)]
    candidates=[DeckParts.from_dict(c['deck']) for c in contexts]
    if initial or proposal==course.deck:deployed=deepcopy(result)
    goal_rows=[]
    for deck in candidates:
        matched=private_proof(deck)
        goal_rows.append(task_supervision(task,deck,assets,private_evidence=matched[1]['proof'] if matched else None))
    def admit(data,suffix):
        pause_if_requested()
        data['supervision_sha256']=digest(supervision_projection(data));write(root/(suffix+'.json'),data)
        dataset_id='course-build-'+task.sha256[:24]
        course.data_index.freeze({'dataset_id':dataset_id,'experiment_id':course.config['course_id'],'purpose':'train','family':'construction','versions':task.environment['versions'],'opponents':[],'task_sha256':task.sha256})
        artifact_id='course-v2-'+cycle_key+'-'+suffix
        course.data_index.ingest_construction(dataset_id,artifact_id,task,assets,data,seeds=supervision_seeds(data))
        return artifact_id
    common={'source':SOURCE,'purpose':'train','task_sha256':task.sha256,'goals':goal_rows,'pairs':[],
            'unknown_routes_used_as_negative':False,'competitive_quality_labels':False,'public_effect_receipts':assets.effect_receipts(task)}
    goal_id=admit(deepcopy(common),'native-goal')
    apply_once('course-v2-'+cycle_key+'-goal',goal_id,kind='construction',task=task,roles=('build_goal',))
    trace_sha=hashlib.sha256(path.read_bytes()).hexdigest();dataset_id='course-actual-coordinator'
    pause_if_requested()
    course.data_index.freeze({'dataset_id':dataset_id,'experiment_id':course.config['course_id'],'purpose':'train','family':'coordinator','versions':task.environment['versions'],'opponents':[],'task_sha256':None})
    for i in range(3):
        before,after=result['phases'][i:i+2]
        if before.get('stage_3',{}).get('status')!='concrete_candidate_cb_pending':continue
        context={'goal_valid':True,'card_list_valid':True,'has_forecast':False,'warning':False,'rebuild_required':False,
                 'operation_error':False,'system_error':False,'remaining_tasks':3-i,'completed_matches':number,'score_mean':None,'forecast':None}
        trace={'source':'host_logged_workflow_transition_v1','trace_sha256':trace_sha,'from_phase':i+1,'to_phase':i+2,'context':context,
               'route_label':after['role'],'forecast_target':None,'evidence':{'from_phase':before,'to_phase':after}}
        artifact_id='course-v2-'+cycle_key+'-route-'+str(i)
        pause_if_requested()
        artifact=course.data_index.ingest_coordinator_trace(dataset_id,artifact_id,trace)
        rows=[{'context':context,'route_label':after['role'],'forecast_target':None,'provenance':{'dataset_id':dataset_id,'record_id':artifact_id,
               'source':'actual_four_stage_transition_only','evidence_sha256':artifact['payload_sha256']}}]
        examples={'source':'host_logged_supervision_v1','records':rows,'real_win_rate_supervision':False,'sha256':digest(rows)}
        apply_once(artifact_id,artifact_id,kind='coordinator',examples=examples)
    from local_course_auxiliary import completed_auxiliary,auxiliary_applicability
    auxiliary_scope=auxiliary_applicability(task)
    # Record applicability before sampling. The primary comparison's own plan
    # binds the task, candidates, frozen driver, opponent, seeds and seats.
    scope_path=root/'auxiliary-applicability.json'
    if scope_path.exists() and read(scope_path)!=auxiliary_scope:
        raise RuntimeError('Saved auxiliary applicability differs from the declared goal')
    if not scope_path.exists():write(scope_path,auxiliary_scope)
    construction_candidate_count=len(candidates)
    admitted_contexts,comparison_admissions=admit_comparison_candidates(task,contexts,assets,comparison_policy)
    write(root/'comparison-admissions.json',{'task_sha256':task.sha256,'purpose':'construction_comparison',
        'candidates':comparison_admissions})
    contexts=admitted_contexts;candidates=[DeckParts.from_dict(c['deck']) for c in contexts]
    candidate_basic_cbs={digest(context['deck']):context['basic_cb'] for context in contexts}
    comparison=None;auxiliary=None;portfolio_pairs=[];training_pairs=[];pair_feedback=[]
    optimizer_feedback={'status':'comparison_deferred' if len(candidates)<construction_candidate_count else 'no_comparison',
        'artifact_id':None,'feedback_id':None}
    if len(candidates)>=2:
        bot_entry=next(b for b in course.bots.values() if b['stage']=='bots-bo1' and b['purpose']=='train')
        runtime=bot_entry['runtime'];bot={'bot_id':runtime.opponent_id,'executor_id':runtime.executor_id,'source_id':runtime.source_id,'source':runtime.source,'mono':runtime.mono}
        audit_path=runtime.workspace/runtime.audit['path'];audit=read(audit_path)
        pair_seed_count=2 if len(candidates)>2 else 4
        seeds=tuple(models.duel.config.game_seeds[models.duel.episode_cursor:models.duel.episode_cursor+pair_seed_count])
        from ygo_kito.data_isolation import DataIndex
        comparison_index=root/'comparison-index'
        if not comparison_index.exists():
            # Preserve the main course's committed index identity during a
            # frozen multi-case operation. Import only its closed supervision.
            shutil.copytree(course.data_index.path.parent,comparison_index)
        private_index=DataIndex(comparison_index)
        driver_sha=models.versions()['duel']
        for pair_number,(a,b) in enumerate(combinations(range(len(candidates)),2)):
            # All pairs share the model, opponent and seed budget; update only
            # after the complete bounded comparison set has been recorded.
            pair_root=root if pair_number==0 else root/('portfolio-pair-'+str(a)+'-'+str(b))
            pair_root.mkdir(exist_ok=True)
            pair_candidates=[candidates[a],candidates[b]]
            comparison=compare_model_candidates(task,assets,pair_candidates,bot_entry['deck'],trainer=models.duel,registry=runtime.registry,
                bot=bot,audit={'path':str(audit_path),'assembly_sha256':audit['assembly_sha256']},workspace=runtime.workspace,
                seeds=seeds,directory=pair_root/'fixed-model-pairs',data_index=private_index,experiment_id=course.config['course_id'],
                stop=stop,status=status,artifact_namespace=cycle_key,budget=budget,
                comparison_policy=comparison_policy,candidate_basic_cbs=candidate_basic_cbs,
                seconds=7200. if budget is None else min(7200.,budget.check('before_paired_comparison')))
            if models.versions()['duel']!=driver_sha:raise RuntimeError('Portfolio comparison changed its frozen driver')
            status('saved_complete_collaborative_comparison',completed_cases=len(comparison['games']),total_cases=len(comparison['games']),complete_pairs=len(comparison['games'])//2)
            if budget is not None:budget.check('before_auxiliary_readout')
            auxiliary=None
            if comparison['preferred_index'] is None and auxiliary_scope['supported']:
                auxiliary=completed_auxiliary(task,assets,comparison,private_index,pair_root,base,number)
            receipt=record_comparison(session,assets,comparison,[contexts[a],contexts[b]],auxiliary=auxiliary)
            preferred=receipt['preferred_index'];label_source=PAIR_SOURCE
            if comparison['preferred_index'] is None and preferred is not None:
                label_source=auxiliary['source']
            portfolio_pairs.append((a,b,preferred))
            pair_feedback.append({'candidate_indices':[a,b],
                'primary_preferred_index':comparison['preferred_index'],
                'auxiliary_status':('evaluated' if auxiliary is not None else
                    auxiliary_scope['status'] if comparison['preferred_index'] is None else 'not_requested_primary_strict'),
                'auxiliary_reason':(auxiliary['preference_reason'] if auxiliary is not None else
                    auxiliary_scope['reason'] if comparison['preferred_index'] is None else 'primary_strict_label_available'),
                'preferred_index':preferred,'label_source':label_source if preferred is not None else None})
            training_pair=comparison_training_pair(comparison,pair_candidates,preferred,auxiliary)
            if training_pair is not None:training_pairs.append(training_pair)
        if training_pairs:
            data=deepcopy(common);data['pairs']=training_pairs
            artifact_id=admit(data,'real-model-comparison')
            feedback_id='course-v2-'+cycle_key+'-optimizer'
            apply_once(feedback_id,artifact_id,kind='construction',task=task,roles=('build_optimizer',))
            optimizer_feedback=optimizer_feedback_receipt(course.feedback.consumed,feedback_id,artifact_id)
        else:
            optimizer_feedback['status']='no_strict_label'
        winner=strict_portfolio_winner(len(candidates),portfolio_pairs)
        if winner is not None and candidates[winner]!=course.deck:
            course.deck=candidates[winner];deployed=select_retained(result,contexts[winner])
            deployed['training_adoption']={'source':'completed_frozen_portfolio_comparisons',
                'candidate_deck_sha256':digest(course.deck.to_dict()),'strict_pair_results':portfolio_pairs,
                'independent_acceptance':False,'optimality_claimed':False}
    course.construction=deployed
    paired_status=('paired_training_preferences_observed' if training_pairs else 'no_strict_label') if portfolio_pairs else 'no_new_pair_label'
    course.events.append({'kind':'actual_collaborative_role_feedback','complete_matches':number,
        'paired_training_status':paired_status,
        'final_proposal_deck_sha256':digest(proposal.to_dict()),'deployed_deck_sha256':digest(course.deck.to_dict()),
        'candidate_and_deployment_distinct':True,
        'single_game_quality_label':False,'forecast_supervision':False})
    course.save()
    summary={'formal_matches':number,'goal_updates':models.builder.updates['build_goal'],'optimizer_updates':models.builder.updates['build_optimizer'],
        'duel_updates':models.duel.updates,'coordinator_updates':models.coordinator.updates,'actual_four_stage':True,
        'paired_training_status':(paired_status if portfolio_pairs else
            'comparison_deferred_by_training_admission' if len(candidates)<construction_candidate_count else
            'initial_separate_comparison_preserved' if initial else 'no_distinct_verified_candidate'),
        'formal_credit_for_comparison':False,'forecast_training':False,'independent_acceptance':False,
        'auxiliary_preferred_index':auxiliary['preferred_index'] if auxiliary else None,
        'auxiliary_reason':(auxiliary['preference_reason'] if auxiliary is not None else
            auxiliary_scope['reason'] if not auxiliary_scope['supported'] else
            'not_requested_primary_strict' if portfolio_pairs else 'not_requested_no_comparison'),
        'auxiliary_summary_scope':'last_pair_compatibility_fields',
        'auxiliary_applicability':auxiliary_scope,'pair_feedback':pair_feedback,
        'optimizer_feedback':optimizer_feedback,'comparison_admissions':comparison_admissions,
        'construction_candidate_count':construction_candidate_count,'comparison_policy_required':True}
    summary['portfolio_candidate_count']=len(candidates);summary['portfolio_pair_results']=portfolio_pairs
    summary['cycle_id']=cycle_id;summary['cycle_key']=cycle_key
    summary['construction_scoring_feedback']=scoring_feedback
    summary['review_receipt']={'kind':'completed_four_step_construction_review_v2',
        'cycle_id':'review-'+(cycle_id if cycle_id is not None else str(number)),
        'task_sha256':task.sha256,'deployed_deck_sha256':digest(course.deck.to_dict()),'trace_sha256':trace_sha,
        'roles':[phase['role'] for phase in result['phases']],
        'task_verified':result.get('task_verified') is True,
        'basic_cb_inference_performed':bool((result.get('basic_cb') or {}).get('inference_completed')),
        'reviewed_forecasts':feedback['status'].get('pending_review_forecasts',[]) if feedback else []}
    write(root/'complete.json',summary);return summary
