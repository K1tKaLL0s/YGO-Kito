"""Prospective scope forecasts and actual terminal-outcome coordinator labels."""
import json
from pathlib import Path


class CourseForecast:
    def __init__(self,course,target,stop=None):
        from ygo_kito.coord_contracts import FeedbackPolicy
        self.course=course;self.path=target/'actual-forecast-ledger.json';self.stop=stop
        self.policy=FeedbackPolicy()
        if self.path.exists():self.value=json.loads(self.path.read_text())
        else:self.value={'kind':'prospective-local-training-forecast-v1','unit':'completed_matches',
            'policy':self.policy.to_dict(),'policy_source':'declared_engineering_initial_values_not_user_final_acceptance',
            'calibration':'pending','scopes':{},'outcomes':[],'pending':None,'alerts':[],
            'first_registration_after_complete_matches':sum(course.counts().values()),'trained_artifacts':[],
            'actor_and_candidate_change_over_time':True,'statistical_assumptions_verified':False}
        if self.value['policy']!=self.policy.to_dict():raise RuntimeError('Forecast policy changed; preserve original ledger')
        self.save()

    def save(self):
        temp=self.path.with_name(self.path.name+'.tmp');temp.write_text(json.dumps(self.value,indent=2)+'\n');temp.replace(self.path)

    def context(self,*,forecast=None,completed=None,score=None):
        return {'goal_valid':True,'card_list_valid':True,'has_forecast':forecast is not None,'warning':False,
            'rebuild_required':False,'operation_error':False,'system_error':False,'remaining_tasks':1,
            'completed_matches':sum(self.course.counts().values()) if completed is None else completed,
            'score_mean':score,'forecast':forecast}

    def before(self):
        from ygo_kito.build_contracts import digest
        stage=self.course.stage()
        actual=[(key,bot['deck'].to_dict()) for key,bot in sorted(self.course.bots.items()) if bot['stage']==stage and bot['purpose']=='train']
        scope_id=digest({'period':self.course.config['period_id'],'stage':stage,'opponents':actual})
        if scope_id not in self.value['scopes']:
            advice=self.course.models.coordinator.advice(self.context())
            self.value['scopes'][scope_id]={'probability':advice['probability'],'model_sha256':advice['model_sha256'],
                'calibration':'pending','pool_scope':actual,'stage':stage,'ordinal':len(self.value['scopes'])+1,
                'registered_before_complete_match':sum(self.course.counts().values())+1,
                'initial_deck_sha256':digest(self.course.deck.to_dict()),'prediction_lowering_allowed':False}
        match_id=(self.course.pending['state'].match_id if self.course.pending else self.course.config['course_id']+'-train-'+str(sum(r['purpose']=='train' for r in self.course.records)+1))
        probability=self.value['scopes'][scope_id]['probability']
        if self.value['pending'] is None:
            self.value['pending']={'match_id':match_id,'scope_id':scope_id,'probability':probability,
                'context':self.context(forecast=probability),'duel_model_sha256':self.course.models.versions()['duel'],
                'deck_sha256':digest(self.course.deck.to_dict())}
        elif self.value['pending']['match_id']!=match_id:raise RuntimeError('Unclosed forecast match preserved')
        self.save()

    def train_closed_outcomes(self):
        """Observed BO1 scores are samples, never synthetic probability anchors."""
        from ygo_kito.build_contracts import digest
        for ordinal,record in enumerate(self.course.records):
            if self.stop is not None and self.stop.exists():
                self.course.save()
                error=RuntimeError('Safe stop at saved observed-outcome coordinator boundary');error.safe_boundary_saved=True;raise error
            if not record['complete'] or record['purpose']!='train' or record['format']!='bo1':continue
            receipt=next((r for r in record['receipts'] if r.get('kind')=='course-small-game-host-receipt'),None)
            if receipt is None or receipt['status']!='completed' or not receipt['model_update_completed']:raise RuntimeError('Actual completed native/PPO receipt required')
            artifact_id=receipt['data']['artifact_id'];feedback_id='actual-outcome-'+artifact_id
            if any(r['feedback_id']==feedback_id for r in self.course.feedback.consumed):continue
            artifact=self.course.data_index.artifact(artifact_id,for_training=True);summary=artifact['payload']['summary']
            if artifact['family']!='duel' or summary['opponent_binding']!=receipt['opponent_binding']:raise RuntimeError('Observed outcome provenance differs')
            outcome=summary['outcome'];score=float(outcome['winner']==receipt['actor_core_seat'])
            pending=self.value['pending'];context=(pending['context'] if pending and pending['match_id']==record['match_id'] else self.context(completed=ordinal))
            rows=[{'context':context,'route_label':'train_duel','forecast_target':score,
                'provenance':{'dataset_id':artifact['dataset_id'],'record_id':artifact_id,
                    'source':'actual_native_terminal_outcome_sample_not_calibration','evidence_sha256':artifact['payload_sha256']}}]
            examples={'source':'host_logged_supervision_v1','records':rows,'real_win_rate_supervision':False,'sha256':digest(rows)}
            self.course.apply_feedback(feedback_id,artifact_id,kind='coordinator',examples=examples)
            self.value['trained_artifacts'].append(artifact_id);self.save()

    def after(self):
        pending=self.value['pending']
        if pending is None:return
        record=next((r for r in self.course.records if r['match_id']==pending['match_id']),None)
        if record is None or not record['complete']:return
        if not any(x['match_id']==record['match_id'] for x in self.value['outcomes']):
            self.value['outcomes'].append(dict(pending,actual_score=float(record['winner']=='actor'),format=record['format']))
        self.value['pending']=None
        outcomes=self.value['outcomes'];n=len(outcomes)
        # The predeclared initial probabilities remain immutable, including
        # across candidate/model revisions. Earlier unforecast games stay visible
        # in the course and are not retroactively presented as predictions.
        expected=sum(x['probability'] for x in outcomes)/n;score=sum(x['actual_score'] for x in outcomes)
        check=self.policy.assess(n,score,expected,1)
        if check is not None:
            check.update(scope='declared_training_pool_only',actor_policy_stationary=False,formal_acceptance=False)
            self.value.setdefault('checks',[]).append(check)
            if check['low']:
                kind='force_goal_reconstruction' if n>=1000 else 'reassess_construction'
                if not any(a['kind']==kind for a in self.value['alerts']):
                    alert={'kind':kind,'forecast_matches':n,'complete_course_matches':sum(self.course.counts().values()),'check':check,'handled':False}
                    self.value['alerts'].append(alert)
                    self.course.events.append({'kind':'actual_prediction_discrepancy','action':kind,'check':check})
                    self.course.save()
        self.save()

    def due(self):
        return next((a for a in reversed(self.value['alerts']) if not a['handled']),None)

    def handled(self,alert):
        alert['handled']=True;alert['handled_after_complete_matches']=sum(self.course.counts().values());self.save()
