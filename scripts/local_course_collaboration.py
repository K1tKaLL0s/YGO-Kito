"""Host-owned actual construction feedback between blocks of formal matches."""
from copy import deepcopy
import hashlib
import json
import shutil
import time
from pathlib import Path


def cycle(course,base,target,stop,status,*,initial=False,force_rebuild=False,feedback=None):
    from ygo_kito.build_contracts import BuildTask,DeckParts,digest
    from ygo_kito.build_pipeline import verify_goal
    from ygo_kito.build_training import supervision_projection
    from ygo_kito.model_build_feedback import SOURCE as PAIR_SOURCE,compare_model_candidates
    from ygo_kito.semantic_training import SOURCE
    def read(p):return json.loads(p.read_text(encoding='utf-8'))
    def write(p,v):
        tmp=p.with_name(p.name+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(p)
    def pause_if_requested():
        if stop.exists():
            # Admission may have advanced the DataIndex since the last update.
            # Commit its exact full boundary before reporting a recoverable stop.
            course.save()
            error=RuntimeError('Safe stop at saved collaborative feedback boundary')
            error.safe_boundary_saved=True
            raise error
    def apply_once(feedback_id,artifact_id,**kw):
        if not any(x['feedback_id']==feedback_id for x in course.feedback.consumed):
            pause_if_requested()
            course.apply_feedback(feedback_id,artifact_id,**kw)
            status('actual_collaborative_role_update',formal_matches=sum(course.counts().values()),
                goal_updates=course.models.builder.updates['build_goal'],
                optimizer_updates=course.models.builder.updates['build_optimizer'],
                duel_updates=course.models.duel.updates,coordinator_updates=course.models.coordinator.updates)
    number=sum(course.counts().values());root=target/('collaboration-'+str(number).zfill(6)+('-forced' if force_rebuild else ''));root.mkdir(exist_ok=True)
    if (root/'complete.json').exists():return read(root/'complete.json')
    task=course._task();models=course.models;assets=course.assets
    incumbent=deepcopy(course.construction['best'])
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
            and r['proof'].get('status')=='constraints_and_route_verified'
            and r['proof'].get('native_route',{}).get('core_attempts')),None)
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
        def verifier(t,d,a):
            nonlocal counter
            if stop.exists():raise RuntimeError('Safe stop before next actual construction route')
            counter+=1;prior=private_proof(d)
            if prior is not None:
                source,receipt=prior;proof=deepcopy(receipt['proof'])
                provenance={'kind':'reuse_exact_private_native_proof','path':str(source.relative_to(target)),
                    'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'new_native_execution':False}
            else:
                proof=verify_goal(t,d,a,seconds=30.,attempts=64,decision_budget=100)
                provenance={'kind':'new_actual_native_route','new_native_execution':True}
            row={'task':t.to_dict(),'deck':d.to_dict(),'proof':proof,'proof_provenance':provenance}
            saved=root/('route-'+str(counter).zfill(3)+'.json');write(saved,row);proof_records.append((saved,row))
            status('collaborative_reused_exact_route' if prior is not None else 'collaborative_native_route',
                   formal_matches=number,route_attempt=counter,result=proof['status'])
            return proof
        routing_feedback=({'source':'duel','message':'Actual completed training matches: '+str(number)+'; observed wins: '+str(sum(r['winner']=='actor' for r in course.records if r['purpose']=='train' and r['complete']))+'. Reconsider the unchanged goal with actual public feedback; no quality label from one game.'},)
        if feedback:routing_feedback+=({'source':'duel','message':'Actual immutable forecast discrepancy: '+json.dumps(feedback,sort_keys=True)},)
        result=models.kernel.run_selected(course.selection,base=None if force_rebuild else course.deck,feedback=routing_feedback,verifier=verifier)
        if not result.get('best') or not result.get('cb_verified'):raise RuntimeError('Collaborative construction has no exact verified task route')
        if force_rebuild:
            result['forced_reconstruction_proposed_best']=deepcopy(result['best'])
            # Reconstruct from the goal, then compare with the still-valid
            # incumbent. Reconstruction does not force an unmeasured card edit.
            verifier(task,course.deck,assets)
            result['best']=deepcopy(incumbent);result['verified_best']=deepcopy(incumbent)
            result['forced_reconstruction_executed_from_empty']=True
        write(path,result)
        # Commit the generated session/history together with its inference trace
        # before role admission. A later resume can then consume it exactly once.
        course.save()
    session=models.kernel.sessions[course.selection['candidate_id']]
    session.check_goal()
    if result.get('goal_sha256')!=session.goal_sha256 or session.task.sha256!=task.sha256:raise RuntimeError('Collaboration changed the selected objective')
    candidates=[DeckParts.from_dict(result['best']['deck'])]
    for phase in result['phases']:
        if phase.get('stage_3',{}).get('status')=='task_goal_verified_logic_unproven' and phase.get('proposal_deck'):
            proposal=DeckParts.from_dict(phase['proposal_deck'])
            if proposal not in candidates:candidates.append(proposal)
            if len(candidates)==2:break
    goal_rows=[]
    for deck in candidates:
        matched=private_proof(deck)
        if matched is None:raise RuntimeError('Public redacted output cannot replace the exact private goal replay')
        proof=matched[1]['proof']
        goal_rows.append({'deck':deck.to_dict(),'label':1.,'source':'pinned_constraints_and_actual_native_route','evidence':proof})
    def admit(data,suffix):
        pause_if_requested()
        data['supervision_sha256']=digest(supervision_projection(data));write(root/(suffix+'.json'),data)
        dataset_id='course-build-'+task.sha256[:24]
        course.data_index.freeze({'dataset_id':dataset_id,'experiment_id':course.config['course_id'],'purpose':'train','family':'construction','versions':task.environment['versions'],'opponents':[],'task_sha256':task.sha256})
        artifact_id='course-'+str(number)+'-'+suffix
        proof_seeds={a['seed_audit_only'] for row in data['goals'] for a in row['evidence']['native_route']['core_attempts']}
        if data['pairs']:proof_seeds.update(data['pairs'][0]['evidence']['plan']['paired_seeds_audit_only'])
        course.data_index.ingest_construction(dataset_id,artifact_id,task,assets,data,seeds=tuple(sorted(proof_seeds)))
        return artifact_id
    common={'source':SOURCE,'purpose':'train','task_sha256':task.sha256,'goals':goal_rows,'pairs':[],
            'unknown_routes_used_as_negative':False,'competitive_quality_labels':False,'public_effect_receipts':assets.effect_receipts(task)}
    goal_id=admit(deepcopy(common),'native-goal')
    apply_once('course-'+str(number)+'-goal',goal_id,kind='construction',task=task,roles=('build_goal',))
    trace_sha=hashlib.sha256(path.read_bytes()).hexdigest();dataset_id='course-actual-coordinator'
    pause_if_requested()
    course.data_index.freeze({'dataset_id':dataset_id,'experiment_id':course.config['course_id'],'purpose':'train','family':'coordinator','versions':task.environment['versions'],'opponents':[],'task_sha256':None})
    for i in range(3):
        before,after=result['phases'][i:i+2]
        if before.get('stage_3',{}).get('status')!='task_goal_verified_logic_unproven':continue
        context={'goal_valid':True,'card_list_valid':True,'has_forecast':False,'warning':False,'rebuild_required':False,
                 'operation_error':False,'system_error':False,'remaining_tasks':3-i,'completed_matches':number,'score_mean':None,'forecast':None}
        trace={'source':'host_logged_workflow_transition_v1','trace_sha256':trace_sha,'from_phase':i+1,'to_phase':i+2,'context':context,
               'route_label':after['role'],'forecast_target':None,'evidence':{'from_phase':before,'to_phase':after}}
        artifact_id='course-'+str(number)+'-route-'+str(i)
        pause_if_requested()
        artifact=course.data_index.ingest_coordinator_trace(dataset_id,artifact_id,trace)
        rows=[{'context':context,'route_label':after['role'],'forecast_target':None,'provenance':{'dataset_id':dataset_id,'record_id':artifact_id,
               'source':'actual_four_stage_transition_only','evidence_sha256':artifact['payload_sha256']}}]
        examples={'source':'host_logged_supervision_v1','records':rows,'real_win_rate_supervision':False,'sha256':digest(rows)}
        apply_once(artifact_id,artifact_id,kind='coordinator',examples=examples)
    comparison=None
    if not initial and len(candidates)==2:
        bot_entry=next(b for b in course.bots.values() if b['stage']=='bots-bo1' and b['purpose']=='train')
        runtime=bot_entry['runtime'];bot={'bot_id':runtime.opponent_id,'executor_id':runtime.executor_id,'source_id':runtime.source_id,'source':runtime.source,'mono':runtime.mono}
        audit_path=runtime.workspace/runtime.audit['path'];audit=read(audit_path)
        seeds=tuple(models.duel.config.game_seeds[models.duel.episode_cursor:models.duel.episode_cursor+4])
        from ygo_kito.data_isolation import DataIndex
        comparison_index=root/'comparison-index'
        if not comparison_index.exists():
            # Preserve the main course's committed index identity during a
            # frozen multi-case operation. Import only its closed supervision.
            shutil.copytree(course.data_index.path.parent,comparison_index)
        private_index=DataIndex(comparison_index)
        comparison=compare_model_candidates(task,assets,candidates,bot_entry['deck'],trainer=models.duel,registry=runtime.registry,
            bot=bot,audit={'path':str(audit_path),'assembly_sha256':audit['assembly_sha256']},workspace=runtime.workspace,
            seeds=seeds,directory=root/'fixed-model-pairs',data_index=private_index,experiment_id=course.config['course_id'],stop=stop,status=status)
        status('saved_complete_collaborative_comparison',completed_cases=len(comparison['games']),total_cases=len(comparison['games']),complete_pairs=len(comparison['games'])//2)
        preferred=comparison['preferred_index']
        if preferred is not None:
            data=deepcopy(common);data['pairs']=[{'better':candidates[preferred].to_dict(),'worse':candidates[1-preferred].to_dict(),
                'better_value':comparison['mean_scores'][preferred],'worse_value':comparison['mean_scores'][1-preferred],
                'source':PAIR_SOURCE,'hard_constraints_checked':True,'evidence':comparison}]
            artifact_id=admit(data,'real-model-comparison')
            apply_once('course-'+str(number)+'-optimizer',artifact_id,kind='construction',task=task,roles=('build_optimizer',))
            # This is a measured training choice, not independent acceptance or
            # a declaration that the selected deck is optimal.
            selected=candidates[preferred]
            phase=next((p for p in result['phases'] if p.get('proposal_deck')==selected.to_dict() and
                        p.get('stage_3',{}).get('status')=='task_goal_verified_logic_unproven'),None)
            if selected!=course.deck and phase is not None:
                graph_sha=phase['stage_1']['logic_sha256']
                session=models.kernel.sessions[course.selection['candidate_id']]
                logic=next((h['logic'] for h in session.history if h.get('stage')==1 and h.get('logic_sha256')==graph_sha),None)
                if logic is None:raise RuntimeError('Preferred listing lacks its generated logic identity')
                from ygo_kito.construction_logic import ConstructionLogic
                graph=ConstructionLogic.from_dict(logic)
                result['best']={'deck':selected.to_dict(),'logic':logic,'logic_sha256':graph.sha256,
                    'validation':deepcopy(phase['stage_3']),'goal_sha256':session.goal_sha256}
                result['verified_best']=deepcopy(result['best'])
                result['training_adoption']={'source':PAIR_SOURCE,'comparison_sha256':comparison['comparison_sha256'],
                    'independent_acceptance':False,'optimality_claimed':False}
                course.deck=selected
    course.construction=result
    course.events.append({'kind':'actual_collaborative_role_feedback','complete_matches':number,
        'paired_training_status':comparison['status'] if comparison else 'no_new_pair_label',
        'single_game_quality_label':False,'forecast_supervision':False})
    course.save()
    summary={'formal_matches':number,'goal_updates':models.builder.updates['build_goal'],'optimizer_updates':models.builder.updates['build_optimizer'],
        'duel_updates':models.duel.updates,'coordinator_updates':models.coordinator.updates,'actual_four_stage':True,
        'paired_training_status':comparison['status'] if comparison else 'initial_separate_comparison_preserved' if initial else 'no_distinct_verified_candidate',
        'formal_credit_for_comparison':False,'forecast_training':False,'independent_acceptance':False}
    write(root/'complete.json',summary);return summary
