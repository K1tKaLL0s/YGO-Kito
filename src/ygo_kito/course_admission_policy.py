"""Candidate admission from current inventory, without separate score ledgers."""
from copy import deepcopy
from dataclasses import asdict, is_dataclass

from .build_contracts import digest
from .construction_inventory import InventoryDependencies
from .effect_mechanisms import MechanismCatalog
from .validation import ContractError

POLICY_EPOCH = 'construction-before-cb-v3'


class CourseAdmissionPolicy:
    """The course checkpoint alone owns completed CB and review events."""
    def __init__(self, course):
        self.course=course
        self.feedback={}

    def _identity(self,task,deck):
        return dict(task_sha256=task.sha256,deck_sha256=digest(deck.to_dict()))

    def record_completed_construction(self, *, task, deck, assets, basic_cb, cycle_id,
                                      layer_evaluation=None, construction=None):
        assets.validate(task,deck)
        if not isinstance(cycle_id,str) or not cycle_id.strip():
            raise ContractError('completed construction requires a cycle identity')
        if layer_evaluation is not None and layer_evaluation['axis']['inventory']!=deck.to_dict():
            raise ContractError('construction feedback refers to another inventory')
        dependencies=InventoryDependencies(MechanismCatalog(assets,task.pool)).evaluate(deck)
        from .construction_progress import construction_gate
        construction = construction if construction is not None else getattr(self.course, 'construction', None) or {}
        candidate = construction.get('best') or {}
        if candidate.get('deck') != deck.to_dict():
            candidate = {}
        layer_evaluation = layer_evaluation or candidate.get('layer_evaluation')
        saved_gate = candidate.get('construction_gate') or {}
        kernel = getattr(getattr(self.course,'models',None),'kernel',None)
        policy = (kernel.quality_for_task(task)[0] if callable(getattr(kernel,'quality_for_task',None)) else
                  getattr(kernel,'source_binding',{}).get('construction_quality_policy'))
        gate = construction_gate(task, deck, assets, layer_evaluation, policy=policy,
            candidate_version=saved_gate.get('candidate_version', 0),
            quality=candidate.get('quality_evaluation'),
            reference_quality=(construction.get('continuation') or {}).get('reference_evaluation'))
        result={**self._identity(task,deck),'policy_epoch':gate['version'],'cycle_id':cycle_id,
            'inventory_dependencies':dependencies,'layers':deepcopy(layer_evaluation),
            'quality_evaluation':deepcopy(candidate.get('quality_evaluation')),
            'construction_gate':gate, 'force_optimization':gate['status'] != 'passed',
            'optimization_reason':';'.join(gate['reasons']) or None,
            'context_review_required':False,'construction_strength_status':'unknown'}
        self.feedback[task.sha256,digest(deck.to_dict())]=result
        while len(self.feedback)>16:self.feedback.pop(next(iter(self.feedback)))
        return deepcopy(result)

    def public_feedback(self, *, task, deck):
        return deepcopy(self.feedback.get((task.sha256,digest(deck.to_dict()))))

    def consume_cb_signal(self, signal):
        row=asdict(signal) if is_dataclass(signal) else deepcopy(signal)
        required={'attempt_id','task_sha256','deck_sha256','success','failure_count_eligible','reason'}
        if (not isinstance(row,dict) or set(row)!=required or
            any(not isinstance(row[k],str) or not row[k] for k in ('attempt_id','task_sha256','deck_sha256','reason')) or
            type(row['success']) is not bool or row['failure_count_eligible'] not in (True,False,None)):
            raise ContractError('invalid completed conditional CB signal')
        previous=next((e['signal'] for e in self.course.events if e.get('kind')=='conditional_cb_signal'
                       and e['signal']['attempt_id']==row['attempt_id']),None)
        if previous is not None:
            if previous!=row:raise ContractError('CB attempt identity already bound')
            return
        if row['success'] or row['failure_count_eligible'] is True:
            self.course.events.append(dict(kind='conditional_cb_signal',signal=row))

    def _cb_trigger(self,task,deck):
        rows=[e['signal'] for e in self.course.events if e.get('kind')=='conditional_cb_signal'
              and e['signal']['task_sha256']==task.sha256 and e['signal']['deck_sha256']==digest(deck.to_dict())]
        reviewed={e['through_attempt_id'] for e in self.course.events if e.get('kind')=='construction_cb_review'
                  and e['task_sha256']==task.sha256}
        boundary=max((i for i,r in enumerate(rows) if r['attempt_id'] in reviewed),default=-1)
        streak=0;trigger=None
        for row in rows[boundary+1:]:
            streak=0 if row['success'] else streak+1
            if row['success']:trigger=None
            elif streak>=2:trigger=row['attempt_id']
        return trigger

    def review_completed(self, *, task, deck, cycle_id, through_attempt_id=None):
        if through_attempt_id is None:return
        if not any(e.get('kind')=='conditional_cb_signal' and e['signal']['task_sha256']==task.sha256
                   and e['signal']['attempt_id']==through_attempt_id for e in self.course.events):
            raise ContractError('completed construction acknowledgement needs its actual CB trigger')
        self.course.events.append(dict(kind='construction_cb_review',task_sha256=task.sha256,
            deck_sha256=digest(deck.to_dict()),cycle_id=cycle_id,through_attempt_id=through_attempt_id))

    def __call__(self, *, task, deck, basic_cb, assets, purpose, construction=None):
        feedback=self.record_completed_construction(task=task,deck=deck,assets=assets,
            basic_cb=basic_cb,cycle_id='current-candidate',construction=construction)
        reasons=list(feedback['construction_gate']['reasons'])
        trigger=self._cb_trigger(task,deck)
        refs=[dict(kind='current_candidate_inventory_evaluation',policy_epoch=POLICY_EPOCH,
            **self._identity(task,deck),evaluation_sha256=digest(feedback['inventory_dependencies']))]
        if trigger is not None:refs.append(dict(kind='conditional_cb_optimization_signal',attempt_id=trigger))
        return {**self._identity(task,deck),'status':'deferred' if reasons else 'admitted',
            'policy_epoch':POLICY_EPOCH,'reasons':reasons,'evidence_refs':refs,
            'signals':dict(optimization_requested=bool(reasons) or trigger is not None,
                mandatory_rebuild=False,hint_permission=False)}


def load_course_admission_policy(course):
    return CourseAdmissionPolicy(course)
