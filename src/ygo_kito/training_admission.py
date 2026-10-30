"""Candidate-owned CB and explicit host policy admission for future duels."""
from copy import deepcopy
from dataclasses import asdict,dataclass
from typing import Protocol

from .build_contracts import BuildTask,digest
from .build_semantics import accepted_status
from .validation import ContractError


class ComparisonPolicy(Protocol):
    def __call__(self, *, task,deck,basic_cb,assets,purpose) -> dict: ...


class TrainingAdmissionDeferred(ContractError):
    safe_boundary_saved=False
    pause_requested=False

    def __init__(self,verdict):
        self.verdict=deepcopy(verdict)
        super().__init__('Training admission deferred: '+';'.join(verdict['reasons']))


@dataclass(frozen=True)
class AdmissionSignals:
    """Independent host decisions; None means its definition is unavailable."""
    optimization_requested: bool | None = None
    mandatory_rebuild: bool | None = None
    hint_permission: bool | None = None

    @classmethod
    def from_dict(cls,value):
        if not isinstance(value,dict) or set(value)-set(cls.__dataclass_fields__):
            raise ContractError('unknown admission signal fields')
        if any(v is not None and type(v) is not bool for v in value.values()):
            raise ContractError('admission signals require explicit booleans or unknown')
        return cls(**value)


def _verified_native_receipt(task,deck,assets,proof):
    """Consume the existing successful native receipt without running a duel.

    These are saved execution facts, not a new native replay or a strength label.
    Reuse the route driver's completion/material predicates and DTO validation.
    """
    from .build_semantics import route_task,validate_counts
    from .contracts import DecisionRequest,Observation
    from .extra_routes import completed_special_summon,completed_fusion_summon
    from .normal_duel import request_digest
    from .route_search import DRIVER,action_intent,resolved_chain_cards
    from .validation import fields,integer
    assets.validate(task,deck)
    subject=digest(deck.to_dict());native_task=route_task(task)
    constraints=proof['constraints'];native=proof['native_route']
    if (proof.get('effect_execution_verified') is not True or
            constraints.get('status')!='constraints_satisfied' or constraints.get('task_sha256')!=task.sha256 or
            constraints.get('deck_sha256')!=subject or constraints.get('versions')!=task.environment['versions'] or
            constraints.get('counts')!=validate_counts(task,deck,assets)):
        return False
    fields(native,{'status','card_list_legal','task_sha256','deck_sha256','starting_condition','random_dependency',
                   'core_attempts','responses','core_event_kinds','trajectory_sha256','elapsed_seconds','unmet','route_evidence'})
    evidence=fields(native['route_evidence'],{'driver','opponent','conditional_only','material_preference','sum_choices',
        'final_observation','core_event_audit_not_policy_input','versions','exploration'},
        {'private_selection_key_audit_only','fusion_summon_evidence','opening_assumption'})
    exploration=fields(evidence['exploration'],{'branches_executed','branch_budget','discovered_intents','prewritten_route_supplied','failed_branches'},
        {'required_activations','required_chain_resolutions','intent_schema_version','nodes_expanded'})
    integer(exploration['branch_budget'],'CB receipt branch budget',1,64)
    integer(exploration['branches_executed'],'CB receipt branch count',1,exploration['branch_budget'])
    integer(exploration.get('nodes_expanded'),'CB receipt expanded nodes',1)
    integer(exploration.get('intent_schema_version'),'CB receipt intent schema',1,2)
    expected_hand=list(native_task.goal['starting_conditions']['requires_opening_hand'])
    assumption={'mode':'hypothetical_exact_hand_v1','player':0,'hand':expected_hand,
                'unspecified_hand_resources':0,'opening_probability_evaluated':False}
    if (native['status']!='verified_success' or native['card_list_legal'] is not True or
            native['task_sha256']!=native_task.sha256 or native['deck_sha256']!=subject or
            native['starting_condition']!=native_task.goal['starting_conditions'] or native['unmet']!=[] or
            evidence['versions']!=native_task.environment['versions'] or evidence['driver']!=DRIVER or
            evidence['opponent']!='neutral-pass-engineering-only' or evidence['conditional_only'] is not True or
            evidence.get('opening_assumption')!=assumption or exploration['prewritten_route_supplied'] is not False or
            exploration.get('required_activations',[])!=task.goal.get('required_activations',[]) or
            exploration.get('required_chain_resolutions',[])!=task.goal.get('required_chain_resolutions',[])):
        return False
    mask={'fusion_summon':0x40,'synchro_summon':0x2000,'xyz_summon':0x800000}[native_task.goal['kind']]
    if not assets.rows[native_task.goal['card_id']]['type']&mask:return False
    attempts=native['core_attempts']
    if not isinstance(attempts,list) or not 1<=len(attempts)<=64:return False
    for attempt in attempts:
        fields(attempt,{'seed_audit_only','declared_opening_condition_met','opening_assumption'})
        integer(attempt['seed_audit_only'],'CB receipt audit seed',0,2**32-8)
        if attempt['declared_opening_condition_met'] is not True or attempt['opening_assumption']!=assumption:return False
    responses=native['responses'];events=evidence['core_event_audit_not_policy_input'];intents=exploration['discovered_intents']
    if (not isinstance(responses,list) or not 1<=len(responses)<=100 or native['trajectory_sha256']!=digest(responses) or
            not isinstance(events,list) or not events or not isinstance(intents,list) or not intents):return False
    for response in responses:
        fields(response,{'player','request_sha256','action_id'})
        integer(response['player'],'CB response player',0,1)
        if not isinstance(response['request_sha256'],str) or len(response['request_sha256'])!=64 or not isinstance(response['action_id'],str):return False
    if any(not isinstance(e,dict) or type(e.get('kind')) is not int for e in events):return False
    if native['core_event_kinds']!=[e['kind'] for e in events]:return False
    own=set(deck.main+deck.extra+deck.side)
    for intent in intents:
        fields(intent,{'operation','card_ids'},{'effect_description'})
        if (not isinstance(intent['operation'],str) or not isinstance(intent['card_ids'],list) or
                not intent['card_ids'] or any(type(c) is not int or c not in own for c in intent['card_ids'])):return False
    observation=Observation.from_dict(evidence['final_observation'])
    if observation.observer!=0 or observation.turn!=1 or observation.turn_player!=0:return False
    target=native_task.goal['card_id']
    if not completed_special_summon(events,observation,0,target):return False
    if not any(target in i['card_ids'] and i['operation'] in ('select','special_summon') for i in intents):return False
    activated={e['public_card'] for e in events if e['kind']==70 and e.get('player')==0 and 'public_card' in e}
    if (not set(task.goal.get('required_activations',()))<=activated or
            not set(task.goal.get('required_chain_resolutions',()))<=resolved_chain_cards(events)):return False
    if any(not any(code in i['card_ids'] and i['operation']=='activate' for i in intents)
           for code in task.goal.get('required_activations',())):return False
    choices=evidence['sum_choices']
    if not isinstance(choices,list):return False
    for choice in choices:
        fields(choice,{'request','chosen_card_ids','action_id'})
        request=DecisionRequest.from_dict(choice['request'])
        action=next((a for a in request.actions if a.action_id==choice['action_id']),None)
        if action is None or request.sum_selection is None:return False
        intent=action_intent(request,action,schema_version=exploration['intent_schema_version'])
        if (intent not in intents or choice['chosen_card_ids']!=intent['card_ids'] or
                not any(r['player']==request.observation.observer and r['request_sha256']==request_digest(request) and
                        r['action_id']==action.action_id for r in responses)):return False
    if native_task.goal['kind']=='fusion_summon':
        from .fusion_witness import validate_fusion_witness
        witness=native_task.goal['fusion_witness'];validate_fusion_witness(witness,task.pool,assets)
        actual=completed_fusion_summon(events,observation,0,target,witness)
        if actual is None or actual!=evidence.get('fusion_summon_evidence'):return False
    elif native_task.goal['kind']=='synchro_summon':
        if not choices:return False  # Actual offered sum/material choices must be retained.
    elif native_task.goal['kind']=='xyz_summon':
        targets={c.ref for c in observation.cards if c.card_id==target and c.zone=='monster' and c.controller==0}
        materials=[c for c in observation.cards if c.zone=='overlay' and c.attached_to in targets]
        if not materials or any(not any(c.card_id in i['card_ids'] and i['operation']=='select' for i in intents) for c in materials):return False
    return True


def verified_conditional_basic_cb(task,deck,basic_cb,*,assets=None):
    """Require a verified actual route for this constructed deck and task."""
    from .basic_cb_inference import inference_requirements
    if assets is None:return False
    subject=digest(deck.to_dict())
    if (not isinstance(basic_cb,dict) or basic_cb.get('status')!='routes_inferred' or
            basic_cb.get('inference_completed') is not True or basic_cb.get('task_sha256')!=task.sha256 or
            basic_cb.get('subject_deck_sha256')!=subject or basic_cb.get('initial_state_mode')!='hypothetical_exact_hand_v1' or
            basic_cb.get('opening_probability_evaluated') is not False):return False
    original=task.to_dict();routes=basic_cb.get('routes')
    if not isinstance(routes,list):return False
    for route in routes:
        if not isinstance(route,dict) or not isinstance(route.get('task'),dict):continue
        try:
            derived=BuildTask.from_dict(route['task']);changed=derived.to_dict()
            if {k:v for k,v in original.items() if k not in ('task_id','goal','requirements')}!={k:v for k,v in changed.items() if k not in ('task_id','goal','requirements')}:continue
            if {k:v for k,v in task.goal.items() if k not in ('route_goal','required_activations','required_chain_resolutions')}!={k:v for k,v in derived.goal.items() if k not in ('route_goal','required_activations','required_chain_resolutions')}:continue
            if 'route_goal' in task.goal and derived.goal.get('route_goal')!=task.goal['route_goal']:continue
            if any(not set(task.goal.get(k,()))<=set(derived.goal.get(k,())) for k in ('required_activations','required_chain_resolutions')):continue
            if derived.to_dict()['requirements']!=inference_requirements(task,deck,derived.goal):continue
        except (ContractError,ValueError,TypeError,KeyError):continue
        proof=route.get('proof',{})
        if not isinstance(proof,dict):continue
        try:
            if (proof.get('status')==accepted_status(derived) and proof.get('task_sha256')==derived.sha256 and
                    proof.get('deck_sha256')==subject and _verified_native_receipt(derived,deck,assets,proof)):return True
        except (ContractError,ValueError,TypeError,KeyError,AttributeError,IndexError):continue
    return False


def require_training_admission(*,task,deck,basic_cb,assets,purpose,comparison_policy=None):
    """Return admitted/deferred; missing score/count policy is always deferred.

    The host policy owns score, counter, threshold-window and reset definitions.
    This consumer neither derives them from legacy records nor changes ledgers.
    """
    identity={'task_sha256':None if task is None else task.sha256,'deck_sha256':None if deck is None else digest(deck.to_dict())}
    reasons=[]
    if task is None or deck is None:
        return {**identity,'status':'deferred','policy_epoch':None,'reasons':['explicit_candidate_task_and_deck_required'],
                'evidence_refs':[],'signals':asdict(AdmissionSignals())}
    if not verified_conditional_basic_cb(task,deck,basic_cb,assets=assets):reasons.append('candidate_owned_verified_conditional_cb_required')
    if not isinstance(purpose,str) or not purpose.strip():reasons.append('explicit_duel_purpose_required')
    result={**identity,'status':'deferred','policy_epoch':None,'reasons':reasons,'evidence_refs':[],
            'signals':asdict(AdmissionSignals())}
    if not callable(comparison_policy):
        result['reasons'].append('score_counter_and_forecast_policy_definitions_missing');return result
    verdict=comparison_policy(task=task,deck=deck,basic_cb=basic_cb,assets=assets,purpose=purpose)
    if not isinstance(verdict,dict):
        result['reasons'].append('invalid_comparison_policy_verdict');return result
    if (any(verdict.get(key)!=value for key,value in identity.items()) or
            not isinstance(verdict.get('policy_epoch'),str) or not verdict['policy_epoch'].strip()):
        result['reasons'].append('comparison_policy_identity_or_definition_epoch_missing');return result
    policy_reasons=verdict.get('reasons');references=verdict.get('evidence_refs')
    if (verdict.get('status') not in ('admitted','deferred') or not isinstance(policy_reasons,list) or
            any(not isinstance(reason,str) or not reason.strip() for reason in policy_reasons) or
            not isinstance(references,list) or any(not isinstance(reference,dict) or not reference for reference in references)):
        result['reasons'].append('invalid_comparison_policy_verdict');return result
    try:signals=AdmissionSignals.from_dict(verdict.get('signals',{}))
    except ContractError:
        result['reasons'].append('invalid_comparison_policy_signals');return result
    result['policy_epoch']=verdict['policy_epoch'];result['evidence_refs']=deepcopy(references)
    result['signals']=asdict(signals)
    result['reasons'].extend(policy_reasons)
    if signals.mandatory_rebuild is True:result['reasons'].append('registered_forecast_requires_mandatory_rebuild')
    if verdict['status']=='deferred':
        if not policy_reasons:result['reasons'].append('comparison_policy_deferred_without_admission_evidence')
        return result
    if not references:result['reasons'].append('comparison_policy_admission_evidence_missing')
    # Reasons are blockers. Advisory requests belong to independent signals.
    if not result['reasons'] and references:result['status']='admitted'
    return result
